"""Tests for fake value generation."""

import random

from pdf_anonymizer.fakes import Entity, build_mapping, generate_fake


def test_nb_preserves_format():
    rng = random.Random(1)
    fake = generate_fake("174.445.188-2", "nb", rng)
    assert len(fake) == len("174.445.188-2")
    assert fake[3] == "."
    assert fake[7] == "."
    assert fake[11] == "-"
    assert fake != "174.445.188-2"


def test_digits_same_length():
    rng = random.Random(2)
    fake = generate_fake("8378380341", "digits", rng)
    assert len(fake) == 10
    assert fake.isdigit()
    assert fake != "8378380341"


def test_mapping_deterministic():
    entities = [
        Entity(id="a", kind="digits", original="8378380341"),
        Entity(id="b", kind="nb", original="174.445.188-2"),
    ]
    m1 = build_mapping(entities, seed=42)
    m2 = build_mapping(entities, seed=42)
    assert m1 == m2


def test_ctc_shared_trunk():
    entities = [
        Entity(id="a", kind="ctc_contract", original="CTC0003924227"),
        Entity(id="b", kind="ctc_contract", original="CTC0003924228"),
        Entity(id="c", kind="ctc_contract", original="CTC0003924235"),
    ]
    m = build_mapping(entities, seed=42)
    trunks = {v[3:9] for v in m.values()}
    assert len(trunks) == 1
    assert all(v.startswith("CTC") for v in m.values())
    assert all(len(v) == 13 for v in m.values())
    assert len(set(m.values())) == 3


def test_name_replacement():
    entities = [
        Entity(id="nome", kind="name", original="MARIA DE FATIMA RAMALHO MIRANDA"),
    ]
    m = build_mapping(entities, seed=42)
    assert m["MARIA DE FATIMA RAMALHO MIRANDA"] == "MARIA DA SILVA"
