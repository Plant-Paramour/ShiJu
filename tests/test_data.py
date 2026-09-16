from pathlib import Path

import pytest

from shiju.data import MeterTemplateRepository, RhymeLexicon
from shiju.vocab import VocabIndex

from conftest import FakeLexicon, FakeTokenizer


ROOT = Path(__file__).resolve().parents[1]


def test_template_repository_resolves_default_variant_once():
    template = MeterTemplateRepository(ROOT / "Songci_Meter").get("浣溪沙")

    assert template.variant_name == "韩偓"
    assert [line.layout.length for line in template.lines] == [7] * 6
    assert [line.rhyme_group for line in template.lines] == [1, 1, 1, None, 1, 1]


def test_template_parser_separates_caesura_from_lexical_length():
    template = MeterTemplateRepository(ROOT / "Songci_Meter").get("桂枝香")
    line = template.stanzas[0].lines[6]

    assert line.layout.length == 7
    assert line.layout.caesura_positions == frozenset({3})
    assert line.layout.break_positions == frozenset({3, 5})


def test_template_repository_validates_missing_form():
    with pytest.raises(ValueError, match="文件不存在"):
        MeterTemplateRepository(ROOT / "Songci_Meter").get("不存在")


def test_rhyme_lexicon_has_tone_and_tone_filtered_parts():
    lexicon = RhymeLexicon(ROOT / "Rhyme" / "Xinyun.json")

    assert lexicon.get_pingze("春")
    for tone in lexicon.get_pingze("春"):
        assert lexicon.get_rhyme_part_by_tone("春", tone)


def test_vocab_keeps_unindexed_bigram_for_boundary_detection():
    tokenizer = FakeTokenizer({20: "天地", 21: "山雨"})
    index = VocabIndex(tokenizer, FakeLexicon())

    assert index.text_for_token(20) == "天地"
    assert "天地" in index.common_bigrams()
    assert index.resolve_patterns(()) == set()
