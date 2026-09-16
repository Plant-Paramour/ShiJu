from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("CUDA_LAUNCH_BLOCKING", "1")

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    LogitsProcessorList,
)

from .data import RhymeLexicon
from .tasks import TaskContext, TaskRequest, default_task_registry
from .vocab import VocabIndex


@dataclass(frozen=True)
class ModelConfig:
    model_name: str
    quantization: str = "8bit"


@dataclass(frozen=True)
class SamplingConfig:
    max_new_tokens: int = 4096
    temperature: float = 0.6
    top_p: float = 0.95
    top_k: int = 20
    min_p: float = 0.0


@dataclass(frozen=True)
class AppConfig:
    model: ModelConfig
    task: TaskRequest
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    use_constraints: bool = True
    num_generations: int = 1
    save_output: bool = True
    rhyme_dir: Path = Path("Rhyme")
    meter_source: Path = Path("Songci_Meter")
    output_dir: Path = Path("output")
    boundary_coherence_penalty: float = 50.0


def _load_model(model_config: ModelConfig):
    model_name = model_config.model_name
    quantization = model_config.quantization.lower().strip()
    print(f"Loading tokenizer {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    print(f"Loading model {model_name} (量化={model_config.quantization})...")

    common = {"device_map": "auto", "trust_remote_code": True}
    if quantization in {"none", "fp16", "float16", ""}:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            **common,
        )
    elif quantization in {"8bit", "int8", "8"}:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=BitsAndBytesConfig(load_in_8bit=True),
            **common,
        )
    elif quantization in {"4bit", "int4", "nf4", "4"}:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            ),
            **common,
        )
    else:
        raise ValueError(
            f"不支持的量化参数: {model_config.quantization!r}，可选 none、8bit、4bit"
        )
    return tokenizer, model.eval()


def run(config: AppConfig) -> None:
    tokenizer, model = _load_model(config.model)
    rhyme_path = config.rhyme_dir / f"{config.task.rhyme_dict_name}.json"
    lexicon = RhymeLexicon(rhyme_path)
    vocab = VocabIndex(tokenizer, lexicon)
    task_context = TaskContext(
        tokenizer=tokenizer,
        vocab=vocab,
        lexicon=lexicon,
        meter_source=config.meter_source,
        boundary_coherence_penalty=config.boundary_coherence_penalty,
    )
    runtime = default_task_registry().create(config.task, task_context)

    print(f"\nBuilding prompt for task: {config.task.task_type} (Theme: {config.task.theme})")
    chat_prompt = tokenizer.apply_chat_template(
        runtime.messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    print(f"Debug: use_thinking = {config.task.use_thinking}")
    print(f"Debug: Last prompt message = {runtime.messages[-1]['content']}")

    output_file = config.output_dir / config.task.form_name / f"{config.task.form_name}.txt"
    if config.save_output:
        output_file.parent.mkdir(parents=True, exist_ok=True)

    mode = "with constrained decoding" if config.use_constraints else "without constraints"
    print(f"\nStarting generation ({config.num_generations} times) {mode}...")
    for index in range(config.num_generations):
        print(f"\n=== [Generation {index + 1}/{config.num_generations}] ===")
        inputs = tokenizer(chat_prompt, return_tensors="pt").to(model.device)
        prompt_length = inputs.input_ids.shape[1]
        processors = None
        if config.use_constraints:
            processor = runtime.create_processor(vocab, tokenizer, prompt_length)
            processors = LogitsProcessorList([processor])

        try:
            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    max_new_tokens=config.sampling.max_new_tokens,
                    logits_processor=processors,
                    pad_token_id=tokenizer.eos_token_id,
                    do_sample=True,
                    temperature=config.sampling.temperature,
                    top_p=config.sampling.top_p,
                    top_k=config.sampling.top_k,
                    min_p=config.sampling.min_p,
                )
        except RuntimeError:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            raise

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        output = tokenizer.decode(
            output_ids[0][prompt_length:],
            skip_special_tokens=True,
        )
        output = runtime.process_output(output)
        print("\n[生成结果]")
        print(output)
        if config.save_output:
            with output_file.open("a", encoding="utf-8") as stream:
                stream.write(f"=== 作品 {index + 1} ===\n")
                stream.write(output.strip())
                stream.write("\n\n")
            print(f"已将作品 {index + 1} 存入 {output_file}")
