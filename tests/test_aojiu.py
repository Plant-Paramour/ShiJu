from shiju.candidates import (
    has_viable_tang_completion,
    tang_line_requires_cross_rescue,
)


class ToneLexicon:
    def get_pingze(self, char):
        return {"P": ["平"], "Z": ["仄"], "X": ["平", "仄"]}.get(char, [])


LEXICON = ToneLexicon()


def valid(
    tones,
    line_tone,
    end_tone,
    *,
    allow_aojiu=True,
    require_cross_rescue=False,
    is_first_line=False,
    strict_polyphonic=True,
):
    return has_viable_tang_completion(
        tones,
        len(tones),
        line_tone,
        end_tone,
        LEXICON,
        allow_aojiu=allow_aojiu,
        is_first_line=is_first_line,
        strict_polyphonic=strict_polyphonic,
        rhyme_tone=0,
        require_cross_rescue=require_cross_rescue,
    )


def test_rhyming_line_never_uses_even_position_as_isolated_level_rescue():
    assert valid("ZPZPZPP", 0, 0) is False


def test_five_character_isolated_level_must_be_rescued_at_third_position():
    assert valid("ZPZZP", 0, 0) is False
    assert valid("ZPPZP", 0, 0) is True


def test_seven_character_isolated_level_must_be_rescued_at_fifth_position():
    assert valid("ZZZPZZP", 1, 0) is False
    assert valid("PZZPPZP", 1, 0) is True


def test_seven_character_leading_level_or_sixth_level_prevents_isolated_level():
    assert valid("PZZPZZP", 1, 0) is True
    assert valid("ZPZZZPP", 0, 0) is True


def test_non_rhyming_major_ao_accepts_self_rescue_or_defers_to_next_line():
    assert valid("ZZPZZ", 1, 1) is True
    assert tang_line_requires_cross_rescue("ZZPZZ", 5, 1, 0, LEXICON) is False

    assert valid("ZZZZZ", 1, 1) is True
    assert tang_line_requires_cross_rescue("ZZZZZ", 5, 1, 0, LEXICON) is True


def test_deferred_major_ao_requires_the_next_lines_rescue_position_to_be_level():
    assert valid("ZPPZP", 0, 0, require_cross_rescue=True) is True
    assert valid("PPZZP", 0, 0, require_cross_rescue=True) is False


def test_special_ao_exchange_is_limited_to_non_rhyming_lines():
    assert valid("PPZPZ", 0, 1) is True
    assert valid("ZPZPZ", 0, 1) is False
    assert valid("PPZPZ", 0, 1, allow_aojiu=False) is False
    assert valid("PPZPZ", 0, 0) is False


def test_three_oblique_ending_is_allowed_but_three_level_ending_is_not():
    assert valid("ZZZZZ", 1, 1) is True
    assert valid("PPZZPPP", 0, 0) is False


def test_seven_character_major_ao_uses_fifth_position_for_self_or_cross_rescue():
    assert valid("PPZZPZZ", 0, 1) is True
    assert tang_line_requires_cross_rescue("PPZZPZZ", 7, 0, 0, LEXICON) is False

    assert valid("PPZZZZZ", 0, 1) is True
    assert tang_line_requires_cross_rescue("PPZZZZZ", 7, 0, 0, LEXICON) is True
    assert valid("PZZPPZP", 1, 0, require_cross_rescue=True) is True


def test_seven_character_special_ao_exchange_uses_fifth_and_sixth_positions():
    assert valid("PZPPZPZ", 1, 1) is True
    assert valid("PZZPZPZ", 1, 1) is False


def test_first_line_polyphonic_ending_uses_web_rhyme_mode_semantics():
    assert valid(
        "ZPZZX",
        0,
        2,
        is_first_line=True,
        strict_polyphonic=True,
    ) is True
    assert valid(
        "ZPZZX",
        0,
        2,
        is_first_line=True,
        strict_polyphonic=False,
    ) is False
