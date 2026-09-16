from pathlib import Path

from shiju.constraints import RelationalConstraintProfile, TemplateConstraintProfile
from shiju.data import MeterTemplateRepository, RhymeLexicon
from shiju.domain import RhymeMode, StepKind
from shiju.state import GenerationController, GenerationStateMachine

from conftest import FakeLexicon


ROOT = Path(__file__).resolve().parents[1]


def test_template_session_expands_zhong_and_locks_rhyme():
    template = MeterTemplateRepository(ROOT / "Songci_Meter").get("浣溪沙")
    lexicon = RhymeLexicon(ROOT / "Rhyme" / "Xinyun.json")
    profile = TemplateConstraintProfile(template, lexicon)
    session = profile.create_session()
    controller = GenerationController(GenerationStateMachine(profile.layout), session)

    tones = {item.tones for item in controller.allowed_patterns(max_length=1)}
    assert tones == {"平", "仄"}
    controller.advance("山水清风入画春")
    assert controller.snapshot().step is StepKind.PUNCTUATION
    assert session.locked_rhyme_parts.get(1) in lexicon.get_rhyme_part_by_tone("春", "平")


def test_relational_session_infers_base_tone_and_first_line_rhyme():
    lexicon = FakeLexicon()
    profile = RelationalConstraintProfile(5, 4, "平韵", lexicon)
    session = profile.create_session()
    controller = GenerationController(GenerationStateMachine(profile.layout), session)

    controller.advance("山雨")
    info = controller.candidate_context()
    assert info.base_tone == 1
    controller.advance("山雨山")
    info = controller.candidate_context()
    assert info.line0_rhymes is True
    assert info.locked_rhyme_parts == frozenset({"一"})


def test_relational_even_line_uses_locked_rhyme():
    lexicon = FakeLexicon()
    profile = RelationalConstraintProfile(5, 4, "平韵", lexicon)
    session = profile.create_session()
    controller = GenerationController(GenerationStateMachine(profile.layout), session)
    controller.advance("山雨山雨山，")
    controller.advance("雨山雨山")

    final_patterns = controller.allowed_patterns(max_length=1)
    rhyme_patterns = [item for item in final_patterns if item.rhyme.mode is RhymeMode.PARTS]
    assert rhyme_patterns
    assert all(item.rhyme.parts == frozenset({"一"}) for item in rhyme_patterns)


def test_relational_first_line_oblique_end_excludes_its_rhyme_parts():
    lexicon = FakeLexicon()
    profile = RelationalConstraintProfile(5, 4, "平韵", lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )

    controller.advance("山雨山雨雨")
    info = controller.candidate_context()

    assert info.line0_rhymes is False
    assert info.excluded_rhyme_parts == frozenset({"四"})
