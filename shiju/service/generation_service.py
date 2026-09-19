from __future__ import annotations

from typing import Any, Mapping

from ..contracts import GeneratePoemRequest, JobKind, RewritePoemRequest
from ..generation.engine import GenerationEngine


class GenerationService:
    def __init__(self, engine: GenerationEngine):
        self._engine = engine

    def execute(self, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if kind == JobKind.GENERATE.value:
            return self._engine.generate_poem(GeneratePoemRequest.from_mapping(payload))
        if kind == JobKind.REWRITE.value:
            return self._engine.rewrite_poem(RewritePoemRequest.from_mapping(payload))
        raise ValueError(f"不支持的任务类型: {kind}")

