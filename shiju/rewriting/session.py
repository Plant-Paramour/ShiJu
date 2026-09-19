from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..domain import AllowedPattern, GenerationState, StepKind
from ..state import GenerationController


class RewriteController:
    """Expose only target lines while advancing immutable lines internally."""

    def __init__(
        self,
        controller: GenerationController,
        fixed_lines: Mapping[int, str],
        target_indices: Sequence[int],
    ):
        self._controller = controller
        self._fixed_lines = dict(fixed_lines)
        self._target_indices = frozenset(target_indices)
        self._skip_fixed_lines()

    @property
    def layout(self):
        return self._controller.layout

    def snapshot(self) -> GenerationState:
        return self._controller.snapshot()

    def advance(self, text: str) -> None:
        for char in text:
            self._controller.advance(char)
            self._skip_fixed_lines()

    def allowed_patterns(self, max_length: int = 4) -> Sequence[AllowedPattern]:
        return self._controller.allowed_patterns(max_length)

    def remaining_before_boundary(self) -> int:
        return self._controller.remaining_before_boundary()

    def candidate_context(self) -> Any:
        return self._controller.candidate_context()

    def _skip_fixed_lines(self) -> None:
        while True:
            state = self._controller.snapshot()
            if state.is_finished or state.line_index in self._target_indices:
                return
            if state.step is not StepKind.TEXT or state.char_index != 0:
                raise RuntimeError("重写控制器只能在完整句边界跳过固定内容")
            try:
                text = self._fixed_lines[state.line_index]
            except KeyError as exc:
                raise RuntimeError(f"缺少第 {state.line_index + 1} 句固定上下文") from exc
            self._controller.advance(self._canonical_line(state.line_index, text))

    def _canonical_line(self, line_index: int, text: str) -> str:
        layout = self._controller.layout.lines[line_index]
        result: list[str] = []
        for position, char in enumerate(text, start=1):
            result.append(char)
            if position in layout.caesura_positions:
                result.append("、")
        result.append("\n" if layout.stanza_end else "，")
        return "".join(result)

