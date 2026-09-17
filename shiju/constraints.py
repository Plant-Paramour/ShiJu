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
class HanpaiConstraintContext:
    target_length: int
    forbid_isolated_level: bool
    allow_aojiu: bool
    forbid_three_same_ending: bool
    allowed_end_tones: tuple[str, ...] = ("平", "仄")


class HanpaiConstraintProfile:
    """汉俳的变长三行布局与可选声韵规则。"""

    _BREAKS = {
        3: frozenset(),
        5: frozenset({2}),
        7: frozenset({2, 4}),
    }
    _RHYME_LINES = {
        "AAA": frozenset({0, 1, 2}),
        "ABA": frozenset({0, 2}),
        "BAA": frozenset({1, 2}),
    }

    def __init__(
        self,
        line_lengths: tuple[int, int, int],
        lexicon: RhymeLookup,
        rhyme_scheme: str | None = None,
        forbid_isolated_level: bool = False,
        allow_aojiu: bool = False,
        forbid_three_same_ending: bool = False,
    ):
        if line_lengths not in {(5, 7, 5), (3, 5, 3)}:
            raise ValueError(f"汉俳仅支持 5-7-5 或 3-5-3，收到: {line_lengths}")
        normalized_scheme = rhyme_scheme.upper().strip() if rhyme_scheme else None
        if normalized_scheme is not None and normalized_scheme not in self._RHYME_LINES:
            raise ValueError(
                f"汉俳押韵格式仅支持 AAA、ABA、BAA 或不押韵，收到: {rhyme_scheme}"
            )

        self.line_lengths = line_lengths
        self.lexicon = lexicon
        self.rhyme_scheme = normalized_scheme
        self.forbid_isolated_level = forbid_isolated_level
        self.allow_aojiu = allow_aojiu
        self.forbid_three_same_ending = forbid_three_same_ending
        self._rhyme_lines = self._RHYME_LINES.get(normalized_scheme, frozenset())
        self._layout = GenerationLayout(
            tuple(
                LineLayout(
                    length=length,
                    break_positions=self._BREAKS[length],
                    caesura_positions=self._BREAKS[length],
                    stanza_index=index,
                    line_in_stanza=0,
                    stanza_end=True,
                )
                for index, length in enumerate(line_lengths)
            )
        )

    @property
    def layout(self) -> GenerationLayout:
        return self._layout

    @property
    def rhyme_lines(self) -> frozenset[int]:
        return self._rhyme_lines

    def create_session(self) -> "HanpaiConstraintSession":
        return HanpaiConstraintSession(
            line_lengths=self.line_lengths,
            lexicon=self.lexicon,
            rhyme_lines=self._rhyme_lines,
            forbid_isolated_level=self.forbid_isolated_level,
            allow_aojiu=self.allow_aojiu,
            forbid_three_same_ending=self.forbid_three_same_ending,
        )


class HanpaiConstraintSession(BaseConstraintSession):
    def __init__(
        self,
        line_lengths: tuple[int, int, int],
        lexicon: RhymeLookup,
        rhyme_lines: frozenset[int],
        forbid_isolated_level: bool,
        allow_aojiu: bool,
        forbid_three_same_ending: bool,
    ):
        self._line_lengths = line_lengths
        self._lexicon = lexicon
        self._rhyme_lines = rhyme_lines
        self._forbid_isolated_level = forbid_isolated_level
        self._allow_aojiu = allow_aojiu
        self._forbid_three_same_ending = forbid_three_same_ending
        self._locked_rhyme_parts: dict[str, set[str]] | None = None

    @property
    def locked_rhyme_parts(self) -> dict[str, frozenset[str]]:
        return {
            tone: frozenset(parts)
            for tone, parts in (self._locked_rhyme_parts or {}).items()
        }

    def allowed_tones_at(self, state: GenerationState, position: int) -> tuple[str, ...]:
        return ("平", "仄")

    def rhyme_constraint(
        self,
        state: GenerationState,
        pattern: str,
    ) -> RhymeConstraint | None:
        if state.line_index not in self._rhyme_lines:
            return RhymeConstraint.none()
        tone = pattern[-1]
        if self._locked_rhyme_parts is None:
            return RhymeConstraint.any(tone)
        parts = self._locked_rhyme_parts.get(tone)
        if not parts:
            return None
        return RhymeConstraint.specific(tone, parts)

    def observe_text(self, state: GenerationState, text: str) -> None:
        if state.line_index not in self._rhyme_lines:
            return
        if state.char_index + len(text) != self._line_lengths[state.line_index]:
            return

        last_char = text[-1]
        found = {
            tone: set(self._lexicon.get_rhyme_part_by_tone(last_char, tone))
            for tone in self._lexicon.get_pingze(last_char)
        }
        found = {tone: parts for tone, parts in found.items() if parts}
        if not found:
            return
        if self._locked_rhyme_parts is None:
            self._locked_rhyme_parts = found
            return

        narrowed = {
            tone: self._locked_rhyme_parts[tone].intersection(parts)
            for tone, parts in found.items()
            if tone in self._locked_rhyme_parts
        }
        narrowed = {tone: parts for tone, parts in narrowed.items() if parts}
        if narrowed:
            self._locked_rhyme_parts = narrowed

    def candidate_context(self, state: GenerationState) -> HanpaiConstraintContext:
        allowed_end_tones = ("平", "仄")
        if state.line_index in self._rhyme_lines and self._locked_rhyme_parts is not None:
            allowed_end_tones = tuple(
                tone
                for tone in ("平", "仄")
                if self._locked_rhyme_parts.get(tone)
            )
        return HanpaiConstraintContext(
            target_length=self._line_lengths[state.line_index],
            forbid_isolated_level=self._forbid_isolated_level,
            allow_aojiu=self._allow_aojiu,
            forbid_three_same_ending=self._forbid_three_same_ending,
            allowed_end_tones=allowed_end_tones,
        )


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
    """关系型诗体的字间规则配置。"""

    def __init__(
        self,
        line_length: int,
        num_lines: int,
        rhyme_type: str,
        lexicon: RhymeLookup,
        allow_aojiu: bool = False,
    ):
        if line_length not in (5, 7):
            raise ValueError(f"唐诗仅支持五言(5)或七言(7)，收到: {line_length}")
        if num_lines not in (4, 8) and not (num_lines >= 10 and num_lines % 2 == 0):
            raise ValueError(
                "关系型诗体句数必须为 4、8，或排律的至少十句偶数，"
                f"收到: {num_lines}"
            )
        self.line_length = line_length
        self.num_lines = num_lines
        self.rhyme_type = rhyme_type.strip()
        self.lexicon = lexicon
        self.allow_aojiu = allow_aojiu
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
            allow_aojiu=self.allow_aojiu,
        )


class RelationalConstraintSession(BaseConstraintSession):
    def __init__(
        self,
        line_length: int,
        num_lines: int,
        rhyme_type: str,
        lexicon: RhymeLookup,
        allow_aojiu: bool = False,
    ):
        self._line_length = line_length
        self._num_lines = num_lines
        self._rhyme_type = rhyme_type
        self._lexicon = lexicon
        self._allow_aojiu = allow_aojiu
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
        elif line_index % 4 in (1, 2):
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
        if self._allow_aojiu and (
            (position == 3 and base == 0)
            or (position == 5 and base == 1 and self._line_length >= 7)
        ):
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
