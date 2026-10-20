"""Redact and reinsert anonymized text preserving fonts."""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from pdf_anonymizer.fakes import Entity
from pdf_anonymizer.matcher import (
    TextFragment,
    extract_page_chars,
    find_matches,
    find_name_fragment,
    rotate_from_dir,
)


def _color_from_int(color: int) -> tuple[float, float, float]:
    if color == 0:
        return (0, 0, 0)
    r = ((color >> 16) & 255) / 255
    g = ((color >> 8) & 255) / 255
    b = (color & 255) / 255
    return (r, g, b)


class FontCache:
    def __init__(self) -> None:
        self._buffers: dict[int, bytes] = {}
        self._names: dict[int, str] = {}

    def get_font_name(self, doc: fitz.Document, span: dict) -> str:
        xref = span.get("xref", 0)
        if xref in self._names:
            return self._names[xref]
        if xref == 0:
            self._names[0] = "helv"
            return "helv"
        try:
            _, _, _, buffer = doc.extract_font(xref)
            if buffer:
                self._buffers[xref] = buffer
            font_id = f"anon{xref}"
            self._names[xref] = font_id
            return font_id
        except Exception:
            self._names[xref] = "helv"
            return "helv"

    def register_on_page(self, page: fitz.Page, xref: int, fontname: str) -> None:
        if xref in self._buffers:
            try:
                page.insert_font(fontname=fontname, fontbuffer=self._buffers[xref])
            except Exception:
                pass


def _collect_fragments(
    page_chars,
    entities: list[Entity],
    mapping: dict[str, str],
) -> list[TextFragment]:
    fragments: list[TextFragment] = []

    for entity in entities:
        if entity.kind == "name":
            fake = mapping[entity.original]
            frag = find_name_fragment(page_chars, entity.original, fake)
            if frag:
                fragments.append(frag)

    non_name = [e for e in entities if e.kind != "name"]
    fragments.extend(find_matches(page_chars, non_name, mapping))
    return fragments


def _insert_at(
    page: fitz.Page,
    point: fitz.Point,
    text: str,
    fontname: str,
    fontsize: float,
    color: tuple[float, float, float],
    rotate: int,
) -> None:
    try:
        page.insert_text(
            point,
            text,
            fontname=fontname,
            fontsize=fontsize,
            color=color,
            rotate=rotate,
        )
    except Exception:
        page.insert_text(
            point,
            text,
            fontname="helv",
            fontsize=fontsize,
            color=color,
            rotate=rotate,
        )


def _write_fragment_text(
    page: fitz.Page,
    doc: fitz.Document,
    fragment: TextFragment,
    font_cache: FontCache,
) -> None:
    if not fragment.chars:
        return

    first = fragment.chars[0]
    span = first.span
    xref = span.get("xref", 0)
    fontname = font_cache.get_font_name(doc, span)
    font_cache.register_on_page(page, xref, fontname)

    color = _color_from_int(first.color)
    fontsize = first.fontsize
    rot = rotate_from_dir(first.dir)
    point = fitz.Point(first.origin[0], first.origin[1])
    _insert_at(page, point, fragment.fake_text, fontname, fontsize, color, rot)


def _apply_fragments(
    page: fitz.Page,
    doc: fitz.Document,
    fragments: list[TextFragment],
    font_cache: FontCache,
) -> None:
    if not fragments:
        return

    for frag in fragments:
        page.add_redact_annot(frag.rect, fill=(1, 1, 1))

    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
    )

    for frag in fragments:
        _write_fragment_text(page, doc, frag, font_cache)


def anonymize_page(
    page: fitz.Page,
    doc: fitz.Document,
    entities: list[Entity],
    mapping: dict[str, str],
    font_cache: FontCache,
) -> int:
    page_chars = extract_page_chars(page)
    fragments = _collect_fragments(page_chars, entities, mapping)
    _apply_fragments(page, doc, fragments, font_cache)
    return len(fragments)


def anonymize_pdf(
    input_path: Path,
    output_path: Path,
    entities: list[Entity],
    mapping: dict[str, str],
) -> int:
    doc = fitz.open(input_path)
    font_cache = FontCache()
    total = 0
    try:
        for page in doc:
            total += anonymize_page(page, doc, entities, mapping, font_cache)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return total


def clean_metadata(path: Path) -> None:
    doc = fitz.open(path)
    try:
        doc.set_metadata({})
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
        tmp = path.with_suffix(".tmp.pdf")
        doc.save(tmp, garbage=4, deflate=True)
    finally:
        doc.close()
    tmp.replace(path)
