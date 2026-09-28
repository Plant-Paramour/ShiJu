"""独立 chunk 生成实验：按 shiju 句读边界限制 token 长度，并连续生成全诗。"""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import random
import time
from pathlib import Path
from typing import Sequence

import torch
from transformers import (
    LogitsProcessor,
    LogitsProcessorList,
    StoppingCriteria,
    StoppingCriteriaList,
)

from shiju.data import RhymeLexicon
from shiju.domain import CONTENT_MARKER
from shiju.generation.model_runner import ModelRunner
from shiju.generation.result import ModelSettings
from shiju.tasks import TaskContext, TaskRequest, TangOptions, default_task_registry
from shiju.vocab import VocabIndex

try:
    from .scorer import Candidate, Lexicon, score
except ImportError:  # 允许直接执行 python experiments/chunk_scoring/generate.py
    from scorer import Candidate, Lexicon, score


_TOKEN_SET_CACHE: dict[tuple[int, int], tuple[dict[int, list[int]], set[int], set[int]]] = {}


def _cache_as_legacy(cache):
    """将 Transformers cache 规范化为可索引的 legacy tuple。"""
    if hasattr(cache, "to_legacy_cache"):
        return cache.to_legacy_cache(), type(cache)
    if isinstance(cache, (tuple, list)):
        return tuple(cache), None
    raise RuntimeError(f"当前 Transformers cache 类型不支持实验增量分支：{type(cache).__name__}")


def _cache_from_legacy(legacy, cache_type):
    if cache_type is None:
        return tuple(legacy)
    factory = getattr(cache_type, "from_legacy_cache", None)
    if factory is None:
        raise RuntimeError(f"{cache_type.__name__} 无法从 legacy KV cache 重建")
    return factory(tuple(legacy))


def _cache_batch_repeat(cache, count: int):
    """沿 batch 维复制 tuple 或新版 Transformers cache。"""
    if cache is None:
        return None
    legacy, cache_type = _cache_as_legacy(cache)
    result = []
    for layer in legacy:
        if not isinstance(layer, (tuple, list)) or len(layer) < 2:
            raise RuntimeError("模型返回了无法扩展的 KV cache")
        result.append(tuple(item.repeat_interleave(count, dim=0) for item in layer))
    return _cache_from_legacy(result, cache_type)


def _cache_select(cache, index: int):
    if cache is None:
        return None
    legacy, cache_type = _cache_as_legacy(cache)
    selected = tuple(tuple(item[index:index + 1].contiguous() for item in layer) for layer in legacy)
    return _cache_from_legacy(selected, cache_type)


def _cache_forward(model, input_ids, cache=None):
    kwargs = {"input_ids": input_ids, "use_cache": True, "return_dict": True}
    if cache is not None:
        kwargs["past_key_values"] = cache
    with torch.no_grad():
        output = model(**kwargs)
    if getattr(output, "past_key_values", None) is None:
        raise RuntimeError("模型未返回 past_key_values，无法启用 --generation-mode kv-cache")
    return output.logits[:, -1, :], output.past_key_values


def _decode(tokenizer, ids: list[int]) -> str:
    return "".join(tokenizer.decode(ids, skip_special_tokens=True).replace(" ", "").replace("\r", "").split())


def _selected_logprobs(outputs, token_ids_by_row: list[list[int]]) -> list[list[float]]:
    """批量计算已选 token 的 logprob，避免每个 token 都触发一次 GPU 同步。"""
    row_count = len(token_ids_by_row)
    max_steps = max((len(ids) for ids in token_ids_by_row), default=0)
    if not max_steps:
        return [[] for _ in token_ids_by_row]
    device = outputs.logits[0].device
    selected = torch.zeros((row_count, max_steps), dtype=torch.float32, device=device)
    for step in range(min(max_steps, len(outputs.logits))):
        active_rows = [row for row, ids in enumerate(token_ids_by_row) if len(ids) > step]
        if not active_rows:
            continue
        rows = torch.tensor(active_rows, dtype=torch.long, device=device)
        token_ids = torch.tensor(
            [token_ids_by_row[row][step] for row in active_rows], dtype=torch.long, device=device
        )
        log_probs = torch.log_softmax(outputs.logits[step].float(), dim=-1)
        selected[rows, step] = log_probs[rows, token_ids]
    values = selected.cpu().tolist()
    return [row[: len(ids)] for row, ids in zip(values, token_ids_by_row)]


def _is_han_text(text: str) -> bool:
    return bool(text) and all(
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in text
    )


class PoemBoundaryLogitsProcessor(LogitsProcessor):
    """按句读限制 token 不跨界；到边界后继续正文，到行末才允许标点。"""

    def __init__(self, tokenizer, prompt_length: int, chunks: list[int], line_count: int):
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length
        self.chunks = chunks
        self.line_length = sum(chunks)
        self.lines = line_count
        self.total_chars = self.line_length * self.lines
        self.line_boundaries = set()
        cursor = 0
        for length in chunks[:-1]:
            cursor += length
            self.line_boundaries.add(cursor)
        key = (id(tokenizer), max(self.chunks))
        if key not in _TOKEN_SET_CACHE:
            _TOKEN_SET_CACHE[key] = self._build_token_sets()
        self.han_ids_by_length, self.punctuation_ids, self.newline_ids = _TOKEN_SET_CACHE[key]
        self.pad_token_id = tokenizer.pad_token_id
        if self.pad_token_id is None or self.pad_token_id == tokenizer.eos_token_id:
            self.pad_token_id = next(iter(self.newline_ids), tokenizer.eos_token_id)

    def _build_token_sets(self):
        han_ids_by_length = {length: [] for length in range(1, max(self.chunks) + 1)}
        punctuation_ids = set()
        newline_ids = set()
        for token_id in range(len(self.tokenizer)):
            text = _decode(self.tokenizer, [token_id])
            if _is_han_text(text) and len(text) <= max(self.chunks):
                han_ids_by_length[len(text)].append(token_id)
        for token_id in range(len(self.tokenizer)):
            text = self.tokenizer.decode([token_id], skip_special_tokens=True)
            if text in ("，", "！", "？", "。", ",", "!", "?"):
                punctuation_ids.add(token_id)
            if "\n" in text:
                newline_ids.add(token_id)
        return han_ids_by_length, punctuation_ids, newline_ids

    def text_so_far(self, input_ids: torch.LongTensor) -> str:
        return _decode(self.tokenizer, input_ids[self.prompt_length :].tolist())

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> torch.FloatTensor:
        masked = torch.full_like(scores, -float("inf"))
        for row in range(input_ids.shape[0]):
            text = self.text_so_far(input_ids[row])
            chars = sum(1 for char in text if "\u3400" <= char <= "\ufaff")
            # 字数边界处的标点和换行按当前诗行位置控制；非汉输出不进入正文计数。
            if chars >= self.total_chars:
                allowed = {self.pad_token_id}
            elif chars > 0 and chars % self.line_length == 0:
                completed_line = chars // self.line_length - 1
                allowed = self.newline_ids if completed_line % 2 == 1 else self.punctuation_ids | self.newline_ids
            else:
                line_position = chars % self.line_length
                next_boundary_in_line = min((b for b in self.line_boundaries if b > line_position), default=self.line_length)
                max_length = min(max(self.chunks), next_boundary_in_line - line_position)
                allowed = {
                    token_id
                    for length in range(1, max_length + 1)
                    for token_id in self.han_ids_by_length[length]
                }
            allowed.discard(None)
            if allowed:
                valid = [token_id for token_id in allowed if 0 <= token_id < scores.shape[-1]]
                masked[row, valid] = scores[row, valid]
            elif chars < self.total_chars:
                raise RuntimeError(f"位置 {chars} 没有合法 token；请检查 tokenizer 对应的 1..N 字汉字 token")
        return masked


class StopAtCharacterCount(StoppingCriteria):
    """在 chunk 字数刚好到达时停止候选采样，不生成 EOS 或后续 chunk。"""

    def __init__(self, tokenizer, prompt_length: int, target_chars: int):
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length
        self.target_chars = target_chars

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor, **kwargs) -> torch.BoolTensor:
        done = []
        for row in input_ids:
            text = _decode(self.tokenizer, row[self.prompt_length :].tolist())
            count = sum(1 for char in text if "\u3400" <= char <= "\ufaff")
            done.append(count >= self.target_chars)
        return torch.tensor(done, dtype=torch.bool, device=input_ids.device)


def generate_poem_candidates(model, tokenizer, prompt: str, chunks: list[int], line_count: int, *, count: int,
                             temperature: float, top_p: float):
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    prompt_length = inputs.input_ids.shape[1]
    boundary = PoemBoundaryLogitsProcessor(tokenizer, prompt_length, chunks, line_count)
    max_new_tokens = boundary.total_chars + boundary.lines * 2 + 8
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            num_return_sequences=count,
            logits_processor=LogitsProcessorList([boundary]),
            return_dict_in_generate=True,
            output_logits=True,
            pad_token_id=boundary.pad_token_id,
        )
    generated_rows = [sequence[prompt_length:].tolist() for sequence in outputs.sequences]
    row_logprobs = _selected_logprobs(outputs, generated_rows)
    poems = []
    for row, generated in enumerate(generated_rows):
        text = _decode(tokenizer, generated)
        chars = "".join(c for c in text if "\u3400" <= c <= "\ufaff")
        if len(chars) != boundary.total_chars:
            continue
        token_logprobs = row_logprobs[row]
        chunks_text = []
        cursor = 0
        for _ in range(boundary.lines):
            for size in chunks:
                chunks_text.append(chars[cursor : cursor + size])
                cursor += size
        # 逐 token logprob 在字符边界上累计；特殊分隔符概率不计入 chunk 内容分。
        chunk_scores = []
        chunk_index = 0
        char_in_line = 0
        token_chunk_ids: list[int] = []
        token_chunk_logprobs: list[float] = []
        for step, token_id in enumerate(generated[: len(token_logprobs)]):
            piece = _decode(tokenizer, [token_id])
            if _is_han_text(piece):
                if len(piece) > chunks[chunk_index] - char_in_line:
                    raise RuntimeError("解码 token 跨越句读边界，processor 未正确限制候选 token")
                token_chunk_ids.append(token_id)
                token_chunk_logprobs.append(token_logprobs[step])
                char_in_line += len(piece)
                if char_in_line == chunks[chunk_index]:
                    chunk = chunks_text[len(chunk_scores)]
                    chunk_scores.append(Candidate(chunk, sum(token_chunk_logprobs), len(token_chunk_ids), tuple(token_chunk_ids)))
                    token_chunk_ids = []
                    token_chunk_logprobs = []
                    chunk_index += 1
                    char_in_line = 0
                    if chunk_index == len(chunks):
                        chunk_index = 0
            if token_id == tokenizer.eos_token_id:
                break
        poems.append({"text": text, "characters": chars, "chunks": chunks_text, "chunk_candidates": chunk_scores})
    return poems


def generate_chunk_candidates(model, tokenizer, prompt: str, target_chars: int, *, count: int,
                              temperature: float, top_p: float):
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    prompt_length = inputs.input_ids.shape[1]
    boundary = PoemBoundaryLogitsProcessor(tokenizer, prompt_length, [target_chars], 1)
    boundary.total_chars = target_chars
    boundary.line_length = target_chars
    boundary.lines = 1
    boundary.line_boundaries = set()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=target_chars + 2,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            num_return_sequences=count,
            logits_processor=LogitsProcessorList([boundary]),
            stopping_criteria=StoppingCriteriaList([
                StopAtCharacterCount(tokenizer, prompt_length, target_chars)
            ]),
            return_dict_in_generate=True,
            output_logits=True,
            pad_token_id=boundary.pad_token_id,
        )
    candidates_by_text = {}
    candidate_rows = {}
    for row, sequence in enumerate(outputs.sequences):
        generated = sequence[prompt_length:].tolist()
        text_ids = []
        text = ""
        for step, token_id in enumerate(generated):
            if token_id == tokenizer.eos_token_id:
                break
            piece = _decode(tokenizer, [token_id])
            if not _is_han_text(piece) or len(piece) > target_chars - len(text):
                break
            text_ids.append(token_id)
            text += piece
            if len(text) == target_chars:
                candidate_rows.setdefault(text, (row, tuple(text_ids)))
                break
    valid_token_ids = [[] for _ in outputs.sequences]
    for row, token_ids in candidate_rows.values():
        valid_token_ids[row] = list(token_ids)
    row_logprobs = _selected_logprobs(outputs, valid_token_ids)
    for text, (row, token_ids) in candidate_rows.items():
        candidates_by_text[text] = Candidate(
            text, sum(row_logprobs[row]), len(token_ids), token_ids
        )
    return list(candidates_by_text.values()), count


class _ConstraintBoundary(StoppingCriteria):
    def __init__(self, tokenizer, prompt_length: int, target_chars: int):
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length
        self.target_chars = target_chars

    def __call__(self, input_ids, scores, **kwargs):
        done = []
        for row in input_ids:
            text = _decode(self.tokenizer, row[self.prompt_length :].tolist())
            done.append(sum(1 for char in text if _is_han_text(char)) >= self.target_chars)
        return torch.tensor(done, dtype=torch.bool, device=input_ids.device)


class _BatchRowLogitsProcessor(LogitsProcessor):
    """把每条采样序列交给独立的 shiju 状态机处理。"""

    def __init__(self, processors, tokenizer, prompt_length: int, target_chars: int):
        self.processors = processors
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length
        self.target_chars = target_chars

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> torch.FloatTensor:
        if input_ids.shape[0] != len(self.processors):
            raise RuntimeError(
                f"采样序列数 {input_ids.shape[0]} 与约束状态数 {len(self.processors)} 不一致"
            )
        eos_token_id = self.tokenizer.eos_token_id
        for row, processor in enumerate(self.processors):
            row_ids = input_ids[row : row + 1]
            row_scores = scores[row : row + 1]
            text = _decode(self.tokenizer, row_ids[0, self.prompt_length :].tolist())
            chars = sum(1 for char in text if _is_han_text(char))
            if chars >= self.target_chars:
                row_scores.fill_(-float("inf"))
                if eos_token_id is None:
                    raise RuntimeError("分词器未配置 eos_token_id，无法结束已完成的候选")
                row_scores[0, eos_token_id] = 0.0
            else:
                scores[row : row + 1] = processor(row_ids, row_scores)
        return scores


def _shiju_runtime(args, tokenizer):
    lexicon = RhymeLexicon(Path(args.rhyme_dir) / f"{args.rhyme_dict}.json")
    vocab = VocabIndex(tokenizer, lexicon)
    resolve_patterns = vocab.resolve_patterns

    @lru_cache(maxsize=8192)
    def _resolve_cached(patterns, ignore_rhyme, strict_polyphonic):
        return frozenset(resolve_patterns(
            patterns,
            ignore_rhyme=ignore_rhyme,
            strict_polyphonic=strict_polyphonic,
        ))

    def _resolve_patterns_cached(patterns, ignore_rhyme=False, strict_polyphonic=True):
        return set(_resolve_cached(tuple(patterns), ignore_rhyme, strict_polyphonic))

    # 每个采样行维护独立状态，但相同状态下的平仄韵部 token 集合完全一致。
    # 仅缓存纯解析结果，不共享或改变候选控制器状态。
    vocab.resolve_patterns = _resolve_patterns_cached
    request = TaskRequest(
        meter_type=args.meter_type,
        form_name=args.form_name,
        variant_name=args.variant_name,
        theme=args.theme,
        rhyme_dict_name=args.rhyme_dict,
        requirement=args.requirement,
        task_type="instruction",
        use_thinking=False,
        num_lines=args.line_count,
        tang=TangOptions(allow_aojiu=True),
    )
    context = TaskContext(
        tokenizer=tokenizer,
        vocab=vocab,
        lexicon=lexicon,
        meter_source=Path(args.meter_source),
        boundary_coherence_penalty=args.boundary_coherence_penalty,
    )
    return default_task_registry().create(request, context), vocab


def generate_shiju_chunk_candidates(model, tokenizer, prompt: str, runtime, vocab, controller, *, count: int,
                                    temperature: float, top_p: float):
    """在持久 shiju 状态机上生成一个句读段；候选只保留完整到达当前边界的结果。"""
    prompt = prompt.rstrip()
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    prompt_length = inputs.input_ids.shape[1]
    controllers = list(controller) if isinstance(controller, (list, tuple)) else [controller]
    if len(controllers) != count:
        raise ValueError(f"候选数 {count} 与独立约束状态数 {len(controllers)} 不一致")
    processors = []
    for active_controller in controllers:
        processor = runtime.create_processor(
            vocab, tokenizer, prompt_length, controller=active_controller,
            activation_marker=CONTENT_MARKER,
        )
        # 生产协议由模型输出 [content] 后才启动；实验每次已把正文边界放在 prompt 末尾，
        # 因此在适配层显式进入正文状态，约束逻辑本身仍完全来自 shiju。
        processor._has_started_content = True
        processor._last_decoded_text = ""
        processors.append(processor)
    segment_lengths = {active.remaining_before_boundary() for active in controllers}
    if len(segment_lengths) != 1:
        raise RuntimeError("批量候选的 shiju 状态边界不一致")
    segment_chars = segment_lengths.pop()
    batch_processor = _BatchRowLogitsProcessor(processors, tokenizer, prompt_length, segment_chars)
    # _BatchRowLogitsProcessor 强制已完成行只允许 EOS；生成器本身会在
    # 所有行产生 EOS 后结束。避免再用一个逐步 decode 全文的 stopping
    # criteria，减少每个 generation step 的重复文本解析。
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=segment_chars + 8,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            num_return_sequences=count,
            logits_processor=LogitsProcessorList([batch_processor]),
            return_dict_in_generate=True,
            output_logits=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    candidates = {}
    candidate_rows = {}
    for row, sequence in enumerate(outputs.sequences):
        generated = sequence[prompt_length:].tolist()
        text = ""
        ids = []
        for step, token_id in enumerate(generated):
            piece = _decode(tokenizer, [token_id])
            if not _is_han_text(piece):
                break
            text += piece
            ids.append(token_id)
        if text and len(text) == segment_chars:
            candidate_rows.setdefault(text, (row, tuple(ids)))
    valid_token_ids = [[] for _ in outputs.sequences]
    for row, token_ids in candidate_rows.values():
        valid_token_ids[row] = list(token_ids)
    row_logprobs = _selected_logprobs(outputs, valid_token_ids)
    for text, (row, token_ids) in candidate_rows.items():
        candidates[text] = Candidate(
            text, sum(row_logprobs[row]), len(token_ids), token_ids
        )
    return list(candidates.values()), count


def generate_shiju_chunk_candidates_kv(model, tokenizer, runtime, vocab, controllers, kv_state, *, count: int,
                                       temperature: float, top_p: float):
    """使用已有 prompt cache 增量生成一个 chunk，并返回候选及其分支 cache。"""
    if len(controllers) != count:
        raise ValueError("候选数与约束状态数不一致")
    # 约束处理只扫描本 chunk 产生的 token；cache 中的历史诗文已由 controller.advance 载入。
    prompt_length = kv_state["input_ids"].shape[1]
    prefix_ids = kv_state["input_ids"]
    next_logits = kv_state["next_logits"]
    base_cache = kv_state["cache"]
    segment_lengths = {item.remaining_before_boundary() for item in controllers}
    if len(segment_lengths) != 1:
        raise RuntimeError("批量候选的 shiju 状态边界不一致")
    segment_chars = segment_lengths.pop()
    processors = []
    for active in controllers:
        processor = runtime.create_processor(
            vocab, tokenizer, prompt_length, controller=active,
            activation_marker=CONTENT_MARKER,
        )
        processor._has_started_content = True
        processor._last_decoded_text = ""
        processors.append(processor)
    batch_processor = _BatchRowLogitsProcessor(processors, tokenizer, prompt_length, segment_chars)
    full_ids = prefix_ids.repeat(count, 1)
    cache = _cache_batch_repeat(base_cache, count)
    logits = next_logits.repeat(count, 1)
    token_rows = [[] for _ in range(count)]
    logprob_rows = [[] for _ in range(count)]
    char_counts = [0] * count
    finished = [False] * count
    for _ in range(segment_chars + 8):
        raw_logits = logits
        constrained_logits = batch_processor(full_ids, logits.clone())
        probs = torch.softmax(constrained_logits / temperature, dim=-1)
        # top-p 采样与 transformers 的常用语义一致，避免重新调用 generate。
        sorted_probs, sorted_idx = torch.sort(probs, descending=True, dim=-1)
        cumulative = torch.cumsum(sorted_probs, dim=-1)
        remove = cumulative > top_p
        remove[:, 1:] = remove[:, :-1].clone()
        remove[:, 0] = False
        sorted_probs[remove] = 0
        sorted_probs.div_(sorted_probs.sum(dim=-1, keepdim=True).clamp_min(1e-12))
        sampled_pos = torch.multinomial(sorted_probs, 1).squeeze(1)
        sampled = sorted_idx.gather(1, sampled_pos[:, None]).squeeze(1)
        token_logprob = torch.log_softmax(raw_logits.float(), dim=-1).gather(1, sampled[:, None]).squeeze(1)
        for row, token_id in enumerate(sampled.tolist()):
            if not finished[row]:
                piece = _decode(tokenizer, [token_id])
                if _is_han_text(piece):
                    token_rows[row].append(token_id)
                    # 延迟到候选完成时再从 GPU 取值，避免每个 token 都触发同步。
                    logprob_rows[row].append(token_logprob[row].detach())
                    char_counts[row] += len(piece)
                elif token_id != tokenizer.eos_token_id:
                    finished[row] = True
            if char_counts[row] >= segment_chars:
                finished[row] = True
        full_ids = torch.cat([full_ids, sampled[:, None]], dim=1)
        logits, cache = _cache_forward(model, sampled[:, None], cache)
        if all(finished):
            break
    candidates = {}
    branches = {}
    for row, ids in enumerate(token_rows):
        if char_counts[row] != segment_chars:
            continue
        text = _decode(tokenizer, ids)
        if text in candidates:
            continue
        candidates[text] = Candidate(
            text, float(torch.stack(logprob_rows[row]).sum().item()), len(ids), tuple(ids)
        )
        branches[text] = {"input_ids": full_ids[row:row + 1], "cache": _cache_select(cache, row),
                          "next_logits": logits[row:row + 1], "prompt_length": prompt_length}
    return candidates, branches, count


def run_experiment(args, *, model=None, tokenizer=None) -> None:
    chunks = [int(item) for item in args.chunks.split(",") if item.strip()]
    if not chunks or any(size <= 0 for size in chunks):
        raise SystemExit("--chunks 必须是正整数，例如 2,3 或 2,2,3")
    if args.batches <= 0 or args.poems_per_batch <= 0:
        raise SystemExit("--batches 和 --poems-per-batch 必须大于 0")
    if args.generation_mode == "kv-cache" and args.constraint_backend != "shiju":
        raise SystemExit("--generation-mode kv-cache 当前只支持 --constraint-backend shiju")
    if model is None or tokenizer is None:
        runner = ModelRunner(
            ModelSettings(model_name=args.model, quantization=args.quantization)
        )
        tokenizer = tokenizer or runner.tokenizer
        model = model or runner.model
    model.eval()
    if not args.prompt.startswith("<|im_start|>"):
        args.prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": args.prompt}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
    lexicon = Lexicon(args.lexicon)
    shiju_runtime = shiju_vocab = None
    if args.constraint_backend == "shiju":
        shiju_runtime, shiju_vocab = _shiju_runtime(args, tokenizer)
    for batch in range(args.batches):
        batch_seed = args.seed + batch
        torch.manual_seed(batch_seed)
        random.seed(batch_seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(batch_seed)
        for poem_index in range(args.poems_per_batch):
            context = args.prompt
            poem_body = ""
            selected_chunks = []
            selected_chunk_scores = []
            poem_started = time.perf_counter()
            kv_state = None
            if args.generation_mode == "kv-cache":
                initial_ids = tokenizer(context, return_tensors="pt").input_ids.to(model.device)
                initial_logits, initial_cache = _cache_forward(model, initial_ids)
                kv_state = {"input_ids": initial_ids, "cache": initial_cache,
                            "next_logits": initial_logits, "prompt_length": initial_ids.shape[1]}
            for line in range(args.line_count):
                for chunk_index, target_chars in enumerate(chunks):
                    chunk_started = time.perf_counter()
                    if args.constraint_backend == "shiju":
                        from shiju.state import GenerationController, GenerationStateMachine
                        # 每个候选必须拥有独立状态，但历史正文对它们完全相同。
                        # 先回放一次，再复制状态，避免 candidates 次重复扫描 poem_body。
                        session = shiju_runtime.profile.create_session(
                            rhyme_mode=shiju_runtime.rhyme_mode,
                            rhyme_parts=shiju_runtime.rhyme_parts,
                        )
                        prototype = GenerationController(
                            GenerationStateMachine(shiju_runtime.profile.layout), session
                        )
                        prototype.advance(poem_body)
                        controllers = [
                            copy.deepcopy(prototype) for _ in range(args.candidates)
                        ]
                        if args.generation_mode == "kv-cache":
                            candidates_by_text, branches, sampled_count = generate_shiju_chunk_candidates_kv(
                                model, tokenizer, shiju_runtime, shiju_vocab, controllers, kv_state,
                                count=args.candidates, temperature=args.temperature, top_p=args.top_p,
                            )
                            candidates = list(candidates_by_text.values())
                        else:
                            candidates, _ = generate_shiju_chunk_candidates(
                                model, tokenizer, context, shiju_runtime, shiju_vocab, controllers,
                                count=args.candidates, temperature=args.temperature, top_p=args.top_p,
                            )
                            sampled_count = args.candidates
                    else:
                        candidates, sampled_count = generate_chunk_candidates(
                            model, tokenizer, context, target_chars, count=args.candidates,
                            temperature=args.temperature, top_p=args.top_p,
                        )
                    if not candidates:
                        raise SystemExit(
                            f"第 {batch + 1} 批第 {poem_index + 1} 首第 {line + 1} 句第 {chunk_index + 1} 个 chunk 无合法候选"
                        )
                    ranked = [score(c, lexicon=lexicon, reward_enabled=args.lexicon_reward,
                                    reward_weight=args.weight) for c in candidates]
                    logits = torch.tensor([float(item["total_score"]) for item in ranked], dtype=torch.float64) / args.selection_temperature
                    pick = int(torch.multinomial(torch.softmax(logits, dim=0), 1).item())
                    selected = ranked[pick]
                    if args.generation_mode == "kv-cache" and args.constraint_backend == "shiju":
                        kv_state = branches[str(selected["chunk"])]
                    chunk_seconds = time.perf_counter() - chunk_started
                    selected_chunks.append(str(selected["chunk"]))
                    poem_body += str(selected["chunk"])
                    selected_chunk_scores.append({
                        **selected,
                        "sampled_candidates": sampled_count,
                        "unique_candidates": len(candidates),
                        "duplicate_candidates": sampled_count - len(candidates),
                        "generation_seconds": round(chunk_seconds, 3),
                    })
                    context += str(selected["chunk"])
                    print(
                        f"[进度] 第 {batch + 1} 批第 {poem_index + 1} 首 "
                        f"第 {line + 1} 句第 {chunk_index + 1}/{len(chunks)} 段完成："
                        f"{chunk_seconds:.1f}s，候选 {len(candidates)}/{sampled_count}",
                        flush=True,
                    )
                context += ("，" if line % 2 == 0 else "。\n")
                poem_body += ("，" if line % 2 == 0 else "。\n")
                if args.generation_mode == "kv-cache":
                    separator = "，" if line % 2 == 0 else "。\n"
                    for separator_id in tokenizer.encode(separator, add_special_tokens=False):
                        token = torch.tensor([[separator_id]], dtype=torch.long, device=model.device)
                        next_logits, next_cache = _cache_forward(model, token, kv_state["cache"])
                        kv_state["input_ids"] = torch.cat([kv_state["input_ids"], token], dim=1)
                        kv_state["cache"] = next_cache
                        kv_state["next_logits"] = next_logits
            selected_text = "".join(
                "".join(selected_chunks[line * len(chunks) : (line + 1) * len(chunks)])
                + ("，" if line % 2 == 0 else "。\n")
                for line in range(args.line_count)
            ).rstrip("\n")
            result = {
                "batch": batch + 1,
                "seed": batch_seed,
                "poem": poem_index + 1,
                "text": selected_text,
                "chunks": selected_chunks,
                "generation_seconds": round(time.perf_counter() - poem_started, 3),
                "lexicon_reward": args.lexicon_reward,
                "chunk_scores": selected_chunk_scores,
            }
            line = json.dumps(result, ensure_ascii=False)
            print(line, flush=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("a", encoding="utf-8") as output:
                    output.write(line + "\n")
                    output.flush()


def main(argv: Sequence[str] | None = None, *, model=None, tokenizer=None) -> None:
    parser = argparse.ArgumentParser(description="Qwen3 固定句读 chunk 评分实验")
    parser.add_argument("--model", default=r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B")
    parser.add_argument("--quantization", default="8bit", choices=("none", "fp16", "8bit", "4bit"), help="与 shiju ModelRunner 一致的模型量化方式，默认 8bit")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--chunks", required=True, help="固定句读字数，例如 2,3 或 2,2,3")
    parser.add_argument("--line-count", type=int, default=4, help="每首诗的行数，七绝默认 4")
    parser.add_argument("--candidates", type=int, default=8, help="每首诗采样的整诗候选数")
    parser.add_argument("--batches", type=int, default=1)
    parser.add_argument("--poems-per-batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260927)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--selection-temperature", type=float, default=0.5)
    parser.add_argument("--lexicon", type=Path, default=Path("shiju/二三字词表.csv"))
    parser.add_argument("--lexicon-reward", action="store_true")
    parser.add_argument("--lambda", dest="weight", type=float, default=0.1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--constraint-backend", choices=("legacy", "shiju"), default="shiju")
    parser.add_argument("--generation-mode", choices=("generate", "kv-cache"), default="generate")
    parser.add_argument("--meter-type", default="唐诗")
    parser.add_argument("--form-name", default="七言绝句")
    parser.add_argument("--variant-name")
    parser.add_argument("--rhyme-dict", default="Pinshui")
    parser.add_argument("--rhyme-dir", type=Path, default=Path("Rhyme"))
    parser.add_argument("--meter-source", type=Path, default=Path("Songci_Meter"))
    parser.add_argument("--theme", default="")
    parser.add_argument("--requirement", default="")
    parser.add_argument("--boundary-coherence-penalty", type=float, default=50.0)
    args = parser.parse_args(argv)
    if args.selection_temperature <= 0:
        raise SystemExit("--selection-temperature 必须大于 0")
    if args.output and args.output.exists():
        args.output.unlink()
    run_experiment(args, model=model, tokenizer=tokenizer)


if __name__ == "__main__":
    main()
