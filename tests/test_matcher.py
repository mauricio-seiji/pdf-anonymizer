"""Matcher pattern and fake alignment tests."""

from pdf_anonymizer.fakes import Entity
from pdf_anonymizer.matcher import TextSegment, _compile_pattern, _find_matches_in_segment
from pdf_anonymizer.text_utils import map_alnum_to_fake


def _seg(text: str) -> TextSegment:
    from pdf_anonymizer.matcher import CharInfo, LineRun, _build_normalized_segment

    chars = [
        CharInfo(
            char=c,
            bbox=__import__("pymupdf").Rect(i * 5, 0, i * 5 + 4, 10),
            origin=(float(i * 5), 10.0),
            fontsize=10.0,
            color=0,
            span={"font": "helv", "xref": 0},
            block_no=0,
            line_no=0,
            dir=(1.0, 0.0),
        )
        for i, c in enumerate(text)
    ]
    seg = TextSegment(lines=[LineRun(0, 0, (1.0, 0.0), chars[0].bbox, chars)])
    seg.chars = chars
    _build_normalized_segment(seg)
    return seg


def test_map_alnum_preserves_separators():
    matched = "22--827744048/-17"
    fake = map_alnum_to_fake(matched, "33-918855159/-28")
    assert fake == "33--918855159/-28"


def test_match_hyphenated_slash_contract():
    entity = Entity(id="x", kind="contract", original="22-827744048/17")
    seg = _seg("22--827744048/-17")
    mapping = {"22-827744048/17": "33-918855159/28"}
    frags = _find_matches_in_segment(seg, [entity], mapping, set())
    assert frags
    assert "".join(c.char for c in frags[0].chars) == "22--827744048/-17"


def test_match_underscore_hyphen_break():
    entity = Entity(id="x", kind="contract", original="89-833769820/18_01")
    seg = _seg("89-833769820/18_-01")
    mapping = {"89-833769820/18_01": "90-944870931/29_12"}
    frags = _find_matches_in_segment(seg, [entity], mapping, set())
    assert frags


def test_compile_pattern_digit_hyphen():
    pat = _compile_pattern(Entity(id="a", kind="contract", original="313670420-6"))
    assert pat  # smoke


def test_banrisul_split():
    entity = Entity(id="a", kind="contract", original="04100000000009820087")
    seg = _seg("041000000000-09820087")
    mapping = {"04100000000009820087": "04100000000008731176"}
    frags = _find_matches_in_segment(seg, [entity], mapping, set())
    assert frags
