"""Per-PDF case directories and output naming."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = ROOT / "cases"


def case_id_for(pdf_path: Path) -> str:
    key = f"{pdf_path.resolve()}:{pdf_path.stat().st_mtime_ns}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def case_dir(pdf_path: Path) -> Path:
    return CASES_DIR / case_id_for(pdf_path)


def entities_path(pdf_path: Path) -> Path:
    return case_dir(pdf_path) / "entities.yaml"


def mapping_path(pdf_path: Path) -> Path:
    return case_dir(pdf_path) / "mapping.json"


def output_name_for(input_pdf: Path, real_name: str | None, fake_name: str | None) -> str:
    stem = input_pdf.stem
    if real_name and fake_name:
        real_parts = real_name.upper().split()
        fake_parts = fake_name.upper().split()
        if len(real_parts) == len(fake_parts):
            for rp, fp in zip(real_parts, fake_parts, strict=True):
                stem = re.sub(re.escape(rp), fp, stem, flags=re.IGNORECASE)
                stem = re.sub(re.escape(rp.replace(" ", "_")), fp.replace(" ", "_"), stem, flags=re.IGNORECASE)
    return f"{stem}-Anonimizado.pdf"


def output_path(input_pdf: Path, real_name: str | None = None, fake_name: str | None = None) -> Path:
    return case_dir(input_pdf) / output_name_for(input_pdf, real_name, fake_name)
