"""Discovery heuristics."""

from pdf_anonymizer.discovery import detect_card_prefixes, discover_from_text


def test_prefix_family_requires_mmaa():
    values = {
        "04100000000009442174",
        "04100000000009442176",
        "04100000000009442178",
    }
    assert detect_card_prefixes(values) == set()


def test_discovers_slash_contract():
    text = "Migrado do contrato 22-841016240/19 CBC: 739"
    ents = discover_from_text(text, holder_name="IRENE STOLF", fake_name="MARIA SOUZA")
    originals = {e.original for e in ents}
    assert "22-841016240/19" in originals
