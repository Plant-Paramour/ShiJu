from __future__ import annotations

from transformers import StoppingCriteria


class ActivationMarkerDeadline(StoppingCriteria):
    """Stop an attempt when the model never enters its constrained phase."""

    def __init__(self, tokenizer, prompt_length: int, marker: str, max_tokens: int = 128):
        self._tokenizer = tokenizer
        self._prompt_length = prompt_length
        self._marker = marker
        self._max_tokens = max_tokens

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        generated = input_ids[0][self._prompt_length :]
        if generated.shape[0] < self._max_tokens:
            return False
        text = self._tokenizer.decode(generated.tolist(), skip_special_tokens=True)
        return self._marker not in text

