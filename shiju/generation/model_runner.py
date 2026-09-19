from __future__ import annotations

import os
from collections.abc import Sequence

os.environ.setdefault("CUDA_LAUNCH_BLOCKING", "1")

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    LogitsProcessorList,
    StoppingCriteriaList,
)

from ..contracts import SamplingOptions
from .result import ModelSettings


class ModelRunner:
    """Own the tokenizer/model lifecycle and execute model sampling."""

    def __init__(self, settings: ModelSettings):
        self.settings = settings
        self._tokenizer = None
        self._model = None

    @property
    def tokenizer(self):
        self.load()
        return self._tokenizer

    @property
    def model(self):
        self.load()
        return self._model

    def load(self) -> None:
        if self._model is not None:
            return
        name = self.settings.model_name
        quantization = self.settings.quantization.lower().strip()
        self._tokenizer = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
        common = {"device_map": "auto", "trust_remote_code": True}
        if quantization in {"none", "fp16", "float16", ""}:
            self._model = AutoModelForCausalLM.from_pretrained(
                name,
                torch_dtype=torch.float16,
                **common,
            )
        elif quantization in {"8bit", "int8", "8"}:
            self._model = AutoModelForCausalLM.from_pretrained(
                name,
                quantization_config=BitsAndBytesConfig(load_in_8bit=True),
                **common,
            )
        elif quantization in {"4bit", "int4", "nf4", "4"}:
            self._model = AutoModelForCausalLM.from_pretrained(
                name,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                ),
                **common,
            )
        else:
            raise ValueError(
                f"不支持的量化参数: {self.settings.quantization!r}，可选 none、8bit、4bit"
            )
        self._model.eval()

    def render_chat(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool | None = None,
    ) -> str:
        tokenizer = self.tokenizer
        kwargs = {"tokenize": False, "add_generation_prompt": True}
        if enable_thinking is not None:
            kwargs["enable_thinking"] = enable_thinking
        try:
            return tokenizer.apply_chat_template(messages, **kwargs)
        except TypeError:
            kwargs.pop("enable_thinking", None)
            return tokenizer.apply_chat_template(messages, **kwargs)

    def generate(
        self,
        prompt: str,
        sampling: SamplingOptions,
        *,
        logits_processors: Sequence | None = None,
        stopping_criteria: Sequence | None = None,
    ) -> str:
        tokenizer = self.tokenizer
        model = self.model
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        prompt_length = inputs.input_ids.shape[1]
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=sampling.max_new_tokens,
                logits_processor=(
                    LogitsProcessorList(list(logits_processors))
                    if logits_processors
                    else None
                ),
                stopping_criteria=(
                    StoppingCriteriaList(list(stopping_criteria))
                    if stopping_criteria
                    else None
                ),
                pad_token_id=tokenizer.eos_token_id,
                do_sample=True,
                temperature=sampling.temperature,
                top_p=sampling.top_p,
                top_k=sampling.top_k,
                min_p=sampling.min_p,
            )
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        return tokenizer.decode(
            output_ids[0][prompt_length:],
            skip_special_tokens=True,
        )

