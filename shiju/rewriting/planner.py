from __future__ import annotations

from dataclasses import dataclass

from ..constraints import ContextConstraintError
from ..contracts import RewritePoemRequest
from ..domain import CONTENT_MARKER
from ..state import GenerationController, GenerationStateMachine
from ..tasks import TaskRuntime
from .parser import ParsedPoem, PoemParseError, parse_poem
from .session import RewriteController


@dataclass(frozen=True)
class RewritePlan:
    request: RewritePoemRequest
    poem: ParsedPoem
    runtime: TaskRuntime
    target_indices: tuple[int, ...]
    fixed_lines: dict[int, str]

    @classmethod
    def build(
        cls,
        request: RewritePoemRequest,
        runtime: TaskRuntime,
    ) -> "RewritePlan":
        poem = parse_poem(request.original_text)
        layout = runtime.profile.layout
        if len(poem.lines) != len(layout.lines):
            raise ContextConstraintError(
                f"原诗解析为 {len(poem.lines)} 句，但 {request.form_name} 要求 {len(layout.lines)} 句"
            )
        if request.target_line_numbers[-1] > len(poem.lines):
            raise PoemParseError(
                f"目标句 {request.target_line_numbers[-1]} 超出原诗的 {len(poem.lines)} 句"
            )
        target_indices = tuple(number - 1 for number in request.target_line_numbers)
        fixed_lines = {
            index: line.text
            for index, line in enumerate(poem.lines)
            if index not in target_indices
        }
        session = runtime.profile.create_session(
            rhyme_mode=runtime.rhyme_mode,
            rhyme_parts=runtime.rhyme_parts,
        )
        session.prime_fixed_lines(
            fixed_lines,
            strict_polyphonic=request.strict_polyphonic,
        )
        return cls(
            request=request,
            poem=poem,
            runtime=runtime,
            target_indices=target_indices,
            fixed_lines=fixed_lines,
        )

    def create_controller(self) -> RewriteController:
        session = self.runtime.profile.create_session(
            rhyme_mode=self.runtime.rhyme_mode,
            rhyme_parts=self.runtime.rhyme_parts,
        )
        session.prime_fixed_lines(
            self.fixed_lines,
            strict_polyphonic=self.request.strict_polyphonic,
        )
        base = GenerationController(
            GenerationStateMachine(self.runtime.profile.layout),
            session,
        )
        return RewriteController(base, self.fixed_lines, self.target_indices)

    def replacements_from_text(self, rewrite_text: str) -> dict[int, str]:
        transformed = self.runtime.process_output(CONTENT_MARKER + rewrite_text)
        _, marker, content = transformed.partition(CONTENT_MARKER)
        generated = parse_poem(content if marker else transformed)
        if len(generated.lines) != len(self.poem.lines):
            raise PoemParseError(
                f"模型应输出完整的 {len(self.poem.lines)} 句，实际输出 {len(generated.lines)} 句"
            )
        replacements: dict[int, str] = {}
        for target_index, generated_line in enumerate(generated.lines):
            expected = self.runtime.profile.layout.lines[target_index].length
            if len(generated_line.text) != expected:
                raise PoemParseError(
                    f"第 {target_index + 1} 句应为 {expected} 字，实际为 {len(generated_line.text)} 字"
                )
            if target_index in self.fixed_lines:
                if generated_line.text != self.fixed_lines[target_index]:
                    raise PoemParseError(f"第 {target_index + 1} 句是固定句，不得改动")
                continue
            replacements[target_index + 1] = generated_line.source_text
        return replacements

    def apply(self, replacements: dict[int, str]) -> str:
        return self.poem.replace_lines(replacements)
