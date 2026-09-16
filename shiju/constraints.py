from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Protocol, Sequence

from .data import MeterTemplate, RhymeLookup
from .domain import (
    AllowedPattern,
    GenerationLayout,
    GenerationState,
    LineLayout,
    RhymeConstraint,
)


class ConstraintProfile(Protocol):
    @property
    def layout(self) -> GenerationLayout: ...

    def create_session(self) -> "BaseConstraintSession": ...


class BaseConstraintSession:
    """将位置级平仄规则统一展开为 token 级候选模式。"""

    def allowed_patterns(
        self,
        state: GenerationState,
        max_length: int,
    ) -> Sequence[AllowedPattern]:
        if state.line is None or state.is_finished:
            return ()
        remains = state.line.length - state.char_index
        allowed: list[AllowedPattern] = []
        for length in range(1, min(max_length, remains) + 1):
            tone_options = [
                self.allowed_tones_at(state, state.char_index + offset)
                for offset in range(length)
            ]
            for tones in product(*tone_options):
                pattern = "".join(tones)
                rhyme = (
                    self.rhyme_constraint(state, pattern)
                    if length == remains
                    else RhymeConstraint.none()
                )
                if rhyme is not None:
                    allowed.append(AllowedPattern(length=length, tones=pattern, rhyme=rhyme))
        return allowed

    def allowed_tones_at(self, state: GenerationState, position: int) -> tuple[str, ...]:
        raise NotImplementedError

    def rhyme_constraint(
        self,
        state: GenerationState,
        pattern: str,
    ) -> RhymeConstraint | None:
        return RhymeConstraint.none()

    def observe_text(self, state: GenerationState, text: str) -> None:
        return None

    def candidate_context(self, state: GenerationState):
        return None


class TemplateConstraintProfile:
    def __init__(self, template: MeterTemplate, lexicon: RhymeLookup):
        self.template = template
        self.lexicon = lexicon

    @property
    def layout(self) -> GenerationLayout:
        return self.template.layout

    def create_session(self) -> "TemplateConstraintSession":
        return TemplateConstraintSession(self.template, self.lexicon)


class TemplateConstraintSession(BaseConstraintSession):
    def __init__(self, template: MeterTemplate, lexicon: RhymeLookup):
        self._template = template
        self._lexicon = lexicon
        self._lines = template.lines
        self._locked_rhyme_parts: dict[int, str] = {}

    @property
    def locked_rhyme_parts(self) -> dict[int, str]:
        return dict(self._locked_rhyme_parts)

    def allowed_tones_at(self, state: GenerationState, position: int) -> tuple[str, ...]:
        return tuple(sorted(self._lines[state.line_index].tone_options[position]))

    def rhyme_constraint(
        self,
        state: GenerationState,
        pattern: str,
    ) -> RhymeConstraint | None:
        group = self._lines[state.line_index].rhyme_group
        if group is None:
            return RhymeConstraint.none()
        tone = pattern[-1]
        if group == 1:
            if self._template.rhyme_type == "平韵" and tone != "平":
                return None
            if self._template.rhyme_type == "仄韵" and tone != "仄":
                return None
        locked = self._locked_rhyme_parts.get(group)
        if locked is None:
            return RhymeConstraint.any(tone)
        return RhymeConstraint.specific(tone, (locked,))

    def observe_text(self, state: GenerationState, text: str) -> None:
        line = self._lines[state.line_index]
        if line.rhyme_group is None or state.char_index + len(text) != line.layout.length:
            return
        group = line.rhyme_group
        if group in self._locked_rhyme_parts:
            return
        if group == 1:
            expected_tone = "平" if "平" in self._template.rhyme_type else "仄"
        else:
            last_options = line.tone_options[-1]
            if len(last_options) == 1:
                expected_tone = next(iter(last_options))
            else:
                expected_tone = "仄" if "平" in self._template.rhyme_type else "平"
        parts = self._lexicon.get_rhyme_part_by_tone(text[-1], expected_tone)
        if parts:
            self._locked_rhyme_parts[group] = parts[0]


@dataclass(frozen=True)
class RelationalConstraintContext:
    current_line: int
    current_char_idx: int
    target_length: int
    is_rhyming: bool
    locked_rhyme_parts: frozenset[str] | None
    excluded_rhyme_parts: frozenset[str] | None
    rhyme_type: str
    base_tone: int
    global_base_tone: int
    line0_rhymes: bool


class RelationalConstraintProfile:
    """当前唐诗使用的字间关系规则配置。"""

    def __init__(
        self,
        line_length: int,
        num_lines: int,
        rhyme_type: str,
        lexicon: RhymeLookup,
    ):
        if line_length not in (5, 7):
            raise ValueError(f"唐诗仅支持五言(5)或七言(7)，收到: {line_length}")
        if num_lines not in (4, 8):
            raise ValueError(f"唐诗仅支持绝句(4)或律诗(8)，收到: {num_lines}")
        self.line_length = line_length
        self.num_lines = num_lines
        self.rhyme_type = rhyme_type.strip()
        self.lexicon = lexicon
        breaks = frozenset({2} if line_length == 5 else {2, 4})
        self._layout = GenerationLayout(
            tuple(
                LineLayout(
                    length=line_length,
                    break_positions=breaks,
                    stanza_index=0,
                    line_in_stanza=index,
                    stanza_end=False,
                )
                for index in range(num_lines)
            )
        )

    @property
    def layout(self) -> GenerationLayout:
        return self._layout

    def create_session(self) -> "RelationalConstraintSession":
        return RelationalConstraintSession(
            line_length=self.line_length,
            num_lines=self.num_lines,
            rhyme_type=self.rhyme_type,
            lexicon=self.lexicon,
        )


class RelationalConstraintSession(BaseConstraintSession):
    def __init__(
        self,
        line_length: int,
        num_lines: int,
        rhyme_type: str,
        lexicon: RhymeLookup,
    ):
        self._line_length = line_length
        self._num_lines = num_lines
        self._rhyme_type = rhyme_type
        self._lexicon = lexicon
        self._locked_rhyme_parts: set[str] | None = None
        self._excluded_rhyme_parts: set[str] | None = None
        self._global_base_tone = 2
        self._line0_rhymes = False
        self._active_line = 0
        self._current_base_tone = 2

    def _ensure_line(self, line_index: int) -> None:
        if line_index == self._active_line:
            return
        self._active_line = line_index
        if self._global_base_tone == 2:
            self._current_base_tone = 2
        elif line_index in (1, 2, 5, 6):
            self._current_base_tone = 1 - self._global_base_tone
        else:
            self._current_base_tone = self._global_base_tone

    def _is_rhyming_line(self, line_index: int) -> bool:
        if line_index == 0:
            return self._line0_rhymes
        return (line_index + 1) % 2 == 0

    def allowed_tones_at(self, state: GenerationState, position: int) -> tuple[str, ...]:
        self._ensure_line(state.line_index)
        base = self._current_base_tone
        if base == 2:
            return ("平", "仄")
        if position == 1 or (position == 5 and self._line_length >= 7):
            return ("平",) if base == 0 else ("仄",)
        if position == 3:
            return ("仄",) if base == 0 else ("平",)
        return ("平", "仄")

    def rhyme_constraint(
        self,
        state: GenerationState,
        pattern: str,
    ) -> RhymeConstraint | None:
        self._ensure_line(state.line_index)
        is_rhyming = self._is_rhyming_line(state.line_index)
        expected = "平" if "平" in self._rhyme_type else "仄"
        if is_rhyming:
            if pattern[-1] != expected:
                return None
            if self._locked_rhyme_parts:
                return RhymeConstraint.specific(expected, self._locked_rhyme_parts)
            return RhymeConstraint.any(expected, self._excluded_rhyme_parts)
        if state.line_index == 0:
            return RhymeConstraint.none()
        opposite = "仄" if expected == "平" else "平"
        if pattern[-1] != opposite:
            return None
        return RhymeConstraint.none()

    def observe_text(self, state: GenerationState, text: str) -> None:
        self._ensure_line(state.line_index)
        simulated = state.current_line_text + text
        if self._current_base_tone == 2:
            tone = self._infer_base_tone(simulated)
            if tone != 2:
                self._current_base_tone = tone
                if state.line_index == 0 and self._global_base_tone == 2:
                    self._global_base_tone = tone

        if state.char_index + len(text) != self._line_length:
            return
        last_char = text[-1]
        if self._is_rhyming_line(state.line_index):
            expected = "平" if "平" in self._rhyme_type else "仄"
            parts = set(self._lexicon.get_rhyme_part_by_tone(last_char, expected))
            if parts:
                if self._locked_rhyme_parts is None:
                    self._locked_rhyme_parts = parts
                else:
                    intersection = self._locked_rhyme_parts.intersection(parts)
                    if intersection:
                        self._locked_rhyme_parts = intersection
        elif state.line_index == 0 and not self._line0_rhymes:
            tones = self._lexicon.get_pingze(last_char)
            if len(tones) == 1 and "平" in self._rhyme_type and tones[0] == "平":
                self._line0_rhymes = True
                parts = self._lexicon.get_rhyme_part_by_tone(last_char, "平")
                if parts:
                    self._locked_rhyme_parts = set(parts)
            elif len(tones) == 1 and tones[0] == "仄":
                parts = self._lexicon.get_rhyme_part(last_char)
                if parts:
                    self._excluded_rhyme_parts = set(parts)

    def _infer_base_tone(self, line_text: str) -> int:
        if len(line_text) >= 2:
            tones = self._lexicon.get_pingze(line_text[1])
            if len(tones) == 1:
                return 0 if tones[0] == "平" else 1
        if len(line_text) >= 4:
            tones = self._lexicon.get_pingze(line_text[3])
            if len(tones) == 1:
                return 1 if tones[0] == "平" else 0
        if self._line_length >= 7 and len(line_text) >= 6:
            tones = self._lexicon.get_pingze(line_text[5])
            if len(tones) == 1:
                return 0 if tones[0] == "平" else 1
        return 2

    def candidate_context(self, state: GenerationState) -> RelationalConstraintContext:
        self._ensure_line(state.line_index)
        return RelationalConstraintContext(
            current_line=state.line_index,
            current_char_idx=state.char_index,
            target_length=self._line_length,
            is_rhyming=self._is_rhyming_line(state.line_index),
            locked_rhyme_parts=(
                frozenset(self._locked_rhyme_parts)
                if self._locked_rhyme_parts is not None
                else None
            ),
            excluded_rhyme_parts=(
                frozenset(self._excluded_rhyme_parts)
                if self._excluded_rhyme_parts is not None
                else None
            ),
            rhyme_type=self._rhyme_type,
            base_tone=self._current_base_tone,
            global_base_tone=self._global_base_tone,
            line0_rhymes=self._line0_rhymes,
        )
