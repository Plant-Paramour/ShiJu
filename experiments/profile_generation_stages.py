"""Profile generation hot-path stages without changing the shiju package."""

import json
import random
import time
from pathlib import Path

import numpy as np
import torch

from shiju.contracts import GeneratePoemRequest, SamplingOptions
from shiju.generation.engine import GenerationEngine
from shiju.generation.model_runner import ModelRunner
from shiju.generation.result import ModelSettings
from shiju import candidates as candidate_module
from shiju import processor as processor_module
from shiju import vocab as vocab_module
from shiju.policies import PolicyTier, TangVerifierPolicy


SEED = 20260928
REPEATS = 3
MODEL = r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B"
STAGE_NAMES = (
    "model_generate_seconds",
    "processor_seconds",
    "tokenizer_decode_seconds",
    "resolve_patterns_seconds",
    "policy_tier_seconds",
    "tang_policy_seconds",
    "viable_completion_seconds",
    "tensor_mask_seconds",
)


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def install_timers(stats, runner):
    def wrap(owner, name, key):
        original = getattr(owner, name)

        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                stats[key] = stats.get(key, 0.0) + time.perf_counter() - started
                stats[key + "_calls"] = stats.get(key + "_calls", 0) + 1

        setattr(owner, name, measured)
        return original

    originals = []
    originals.append((processor_module.ConstrainedLogitsProcessor, "__call__",
                      wrap(processor_module.ConstrainedLogitsProcessor, "__call__", "processor_seconds")))
    originals.append((vocab_module.VocabIndex, "resolve_patterns",
                      wrap(vocab_module.VocabIndex, "resolve_patterns", "resolve_patterns_seconds")))
    originals.append((PolicyTier, "evaluate",
                      wrap(PolicyTier, "evaluate", "policy_tier_seconds")))
    originals.append((TangVerifierPolicy, "evaluate",
                      wrap(TangVerifierPolicy, "evaluate", "tang_policy_seconds")))
    originals.append((candidate_module, "has_viable_tang_completion",
                      wrap(candidate_module, "has_viable_tang_completion", "viable_completion_seconds")))
    originals.append((torch, "full_like",
                      wrap(torch, "full_like", "tensor_mask_seconds")))

    originals.append((runner, "generate_streaming",
                      wrap(runner, "generate_streaming", "model_generate_wall_seconds")))

    # Count decoding separately while retaining the tokenizer's existing behavior.
    original_decode = None

    def restore():
        for owner, name, function in reversed(originals):
            setattr(owner, name, function)
        if original_decode is not None:
            tokenizer_type, function = original_decode
            tokenizer_type.decode = function

    return restore


runner = ModelRunner(ModelSettings(model_name=MODEL, quantization="8bit"))
engine = GenerationEngine(runner, rhyme_dir="Rhyme", meter_source="Songci_Meter")
request = GeneratePoemRequest(
    meter_type="唐诗",
    form_name="七言绝句",
    theme="秋江晚景",
    rhyme_dict_name="Pinshui",
    requirement="意境清远，语言自然。",
    use_thinking=False,
    candidate_count=1,
    sampling=SamplingOptions(max_new_tokens=128, temperature=0.6, top_p=0.95, top_k=20),
)

# Load the model and build the cached lexicon/index before timing measured runs.
seed_all(SEED)
engine.generate_poem(request, use_constraints=True)

records = []
for run in range(1, REPEATS + 1):
    stats = {}
    restore_timers = install_timers(stats, runner)
    tokenizer_type = type(runner.tokenizer)
    original_decode = tokenizer_type.decode

    def measured_decode(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_decode(self, *args, **kwargs)
        finally:
            stats["tokenizer_decode_seconds"] = stats.get("tokenizer_decode_seconds", 0.0) + time.perf_counter() - started
            stats["tokenizer_decode_calls"] = stats.get("tokenizer_decode_calls", 0) + 1

    tokenizer_type.decode = measured_decode
    try:
        seed_all(SEED)
        started = time.perf_counter()
        result = engine.generate_poem(request, use_constraints=True)
        elapsed = time.perf_counter() - started
    finally:
        tokenizer_type.decode = original_decode
        restore_timers()

    candidate = result["candidates"][0]
    record = {
        "run": run,
        "seed": SEED,
        "elapsed_seconds": elapsed,
        "stages": stats,
        "text": candidate["text"],
        "raw_output": candidate["raw_output"],
    }
    records.append(record)
    print(json.dumps({"run": run, "elapsed_seconds": elapsed, "stages": stats}, ensure_ascii=False))

stage_totals = {}
for record in records:
    for name, value in record["stages"].items():
        if name.endswith("_seconds"):
            stage_totals.setdefault(name, []).append(value)

summary = {
    "model": MODEL,
    "quantization": "8bit",
    "seed": SEED,
    "repeats": REPEATS,
    "request": request.to_dict(),
    "runs": records,
    "stage_means": {
        name: {
            "mean_seconds": float(np.mean(values)),
            "share_of_end_to_end": float(np.mean(values) / np.mean([r["elapsed_seconds"] for r in records])),
        }
        for name, values in stage_totals.items()
    },
}
output_dir = Path("experiments/generation_timing")
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / f"stages_{time.strftime('%Y%m%d_%H%M%S')}.json"
output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"output": str(output_path), "stage_means": summary["stage_means"]}, ensure_ascii=False))
