"""Validate anonymized PDF output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from pdf_anonymizer.discovery import extract_page_text
from pdf_anonymizer.fakes import Entity
from pdf_anonymizer.matcher import collect_segment_texts, extract_page_chars
from pdf_anonymizer.renderer import _collect_fragments

POSITION_TOLERANCE = 3.0


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _segmented_text(doc: fitz.Document) -> str:
    return collect_segment_texts(doc)


def _check_length_coherence(mapping: dict[str, str], entities: list[Entity] | None = None) -> list[str]:
    errors: list[str] = []
    exempt = {e.original for e in (entities or []) if e.kind == "name"}
    for orig, fake in mapping.items():
        if orig in exempt:
            continue
        if len(orig) != len(fake):
            errors.append(
                f"Length mismatch for {orig!r}: original={len(orig)} fake={len(fake)} ({fake!r})"
            )
    return errors


def _check_cross_document_coherence(
    outputs: dict[str, fitz.Document],
    mapping: dict[str, str],
) -> list[str]:
    """Shared originals must map to the same fake in every output file."""
    errors: list[str] = []
    segmented: dict[str, str] = {
        name: _segmented_text(doc) for name, doc in outputs.items()
    }

    for orig, fake in mapping.items():
        present_in = [name for name, text in segmented.items() if orig in text or fake in text]
        if len(present_in) < 2:
            continue
        for name, text in segmented.items():
            if name not in present_in:
                continue
            if fake not in text and fake not in re.sub(r"\s+", "", text):
                errors.append(
                    f"Cross-doc coherence: {fake!r} for {orig!r} missing in {name}"
                )
    return errors


def _check_positions(
    input_path: Path,
    output_path: Path,
    entities: list[Entity],
    mapping: dict[str, str],
) -> list[str]:
    """Inserted fakes should appear near the original character origins."""
    errors: list[str] = []
    orig_doc = fitz.open(input_path)
    out_doc = fitz.open(output_path)
    try:
        for page_idx in range(orig_doc.page_count):
            orig_page = orig_doc[page_idx]
            out_page = out_doc[page_idx]
            page_chars = extract_page_chars(orig_page)
            fragments = _collect_fragments(page_chars, entities, mapping)

            out_chars: list[tuple[str, tuple[float, float]]] = []
            raw = out_page.get_text("rawdict", flags=fitz.TEXTFLAGS_TEXT)
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for ch in span.get("chars", []):
                            c = ch.get("c", "")
                            if c:
                                out_chars.append((c, tuple(ch.get("origin", (0, 0)))))

            for frag in fragments:
                if not frag.chars or not frag.fake_text:
                    continue
                ox, oy = frag.chars[0].origin
                found = False
                fake = frag.fake_text
                for i, (c, origin) in enumerate(out_chars):
                    if c != fake[0]:
                        continue
                    if abs(origin[0] - ox) > POSITION_TOLERANCE:
                        continue
                    if abs(origin[1] - oy) > POSITION_TOLERANCE:
                        continue
                    candidate = "".join(out_chars[i + j][0] for j in range(len(fake)))
                    if candidate == fake:
                        found = True
                        break
                if not found:
                    errors.append(
                        f"{output_path.name} p{page_idx + 1}: "
                        f"{fake!r} not found near ({ox:.1f}, {oy:.1f})"
                    )
    finally:
        orig_doc.close()
        out_doc.close()
    return errors


def validate_pdf(
    output_path: Path,
    originals: list[str],
    fakes: list[str],
    *,
    expected_pages: int | None = None,
    segmented: str | None = None,
) -> ValidationResult:
    result = ValidationResult(ok=True)
    doc = fitz.open(output_path)
    try:
        if expected_pages is not None and doc.page_count != expected_pages:
            result.errors.append(
                f"{output_path.name}: page count {doc.page_count} != {expected_pages}"
            )
            result.ok = False

        text = extract_page_text(doc)
        if segmented is None:
            segmented = _segmented_text(doc)
        normalized = re.sub(r"\s+", "", text)
        segmented_norm = re.sub(r"\s+", "", segmented)

        for orig in originals:
            if (
                orig in text
                or orig in normalized
                or orig in segmented
                or orig in segmented_norm
            ):
                result.errors.append(
                    f"{output_path.name}: original value still present: {orig!r}"
                )
                result.ok = False

        for fake in fakes:
            if (
                fake not in text
                and fake not in normalized
                and fake not in segmented
                and fake not in segmented_norm
            ):
                result.warnings.append(
                    f"{output_path.name}: fake value not found in text: {fake!r}"
                )

        meta = doc.metadata or {}
        if any(meta.get(k) for k in ("creator", "producer", "creationDate", "modDate")):
            result.warnings.append(f"{output_path.name}: metadata not fully cleared")
    finally:
        doc.close()

    return result


def output_name_for(input_pdf: Path) -> str:
    return f"{input_pdf.stem}-Anonimizado.pdf"


def validate_outputs(
    output_dir: Path,
    input_dir: Path,
    mapping: dict[str, str],
    entities: list[Entity] | None = None,
) -> ValidationResult:
    combined = ValidationResult(ok=True)
    originals = list(mapping.keys())
    fakes = list(mapping.values())

    combined.errors.extend(_check_length_coherence(mapping, entities))

    open_outputs: dict[str, fitz.Document] = {}
    try:
        for input_pdf in sorted(input_dir.glob("*.pdf")):
            output_pdf = output_dir / output_name_for(input_pdf)
            if not output_pdf.exists():
                combined.errors.append(f"Missing output: {output_pdf.name}")
                combined.ok = False
                continue

            src = fitz.open(input_pdf)
            expected_pages = src.page_count
            src.close()

            out_doc = fitz.open(output_pdf)
            open_outputs[output_pdf.name] = out_doc
            segmented = _segmented_text(out_doc)

            r = validate_pdf(
                output_pdf,
                originals,
                fakes,
                expected_pages=expected_pages,
                segmented=segmented,
            )
            combined.errors.extend(r.errors)
            combined.warnings.extend(r.warnings)
            if not r.ok:
                combined.ok = False

            if entities is not None:
                pos_errors = _check_positions(input_pdf, output_pdf, entities, mapping)
                combined.errors.extend(pos_errors)
                if pos_errors:
                    combined.ok = False

        if len(open_outputs) >= 2:
            cross = _check_cross_document_coherence(open_outputs, mapping)
            combined.errors.extend(cross)
            if cross:
                combined.ok = False
    finally:
        for doc in open_outputs.values():
            doc.close()

    if combined.errors:
        combined.ok = False

    return combined
