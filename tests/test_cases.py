"""Output naming for case mode."""

from pathlib import Path

from pdf_anonymizer.cases import output_name_for


def test_output_name_replaces_holder_in_stem():
    pdf = Path("PARECER-HISCON-b_-_Hiscon_Completo_-_SET_2026-_IRENE_STOLF-0.pdf")
    name = output_name_for(pdf, "IRENE STOLF", "MARIA SOUZA")
    assert "IRENE" not in name.upper()
    assert "STOLF" not in name.upper()
    assert name.endswith("-Anonimizado.pdf")
