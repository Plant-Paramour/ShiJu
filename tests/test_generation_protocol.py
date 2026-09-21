import pytest

from shiju.generation.protocol import GenerationProtocolError, parse_generation_protocol


def test_generation_protocol_accepts_visible_plan_before_title():
    parsed = parse_generation_protocol(
        "[plan]先写远山，再以归鸟收束。\n[title]春山晚望\n[content]山光入晚岚，归鸟过前川。"
    )
    assert parsed.title == "春山晚望"
    assert parsed.content == "山光入晚岚，归鸟过前川。"


@pytest.mark.parametrize(
    "text",
    [
        "只有正文",
        "[title]标题",
        "[content]正文",
        "[content]正文\n[title]标题",
        "[title]一[title]二[content]正文",
    ],
)
def test_generation_protocol_rejects_missing_duplicate_or_reversed_markers(text):
    with pytest.raises(GenerationProtocolError):
        parse_generation_protocol(text)
