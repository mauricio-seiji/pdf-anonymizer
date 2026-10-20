"""Character-level matching tolerant to line breaks and hyphenation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf as fitz

from pdf_anonymizer.fakes import Entity, apply_prefix_mapping
from pdf_anonymizer.text_utils import alnum_skeleton, map_alnum_to_fake


@dataclass
class CharInfo:
    char: str
    bbox: fitz.Rect
    origin: tuple[float, float]
    fontsize: float
    color: int
    span: dict
    block_no: int
    line_no: int
    dir: tuple[float, float]


@dataclass
class LineRun:
    block_no: int
    line_no: int
    dir: tuple[float, float]
    bbox: fitz.Rect
    chars: list[CharInfo]


@dataclass
class TextFragment:
    """Contiguous chars from one visual line within a match."""
    chars: list[CharInfo]
    fake_text: str
    is_name: bool = False

    @property
    def rect(self) -> fitz.Rect:
        r = fitz.Rect(self.chars[0].bbox)
        for c in self.chars[1:]:
            r |= c.bbox
        return r


@dataclass
class TextSegment:
    """Logical text segment: adjacent lines merged by geometry."""
    lines: list[LineRun]
    chars: list[CharInfo] = field(default_factory=list)
    normalized: str = ""
    norm_to_char: list[int] = field(default_factory=list)


@dataclass
class PageChars:
    segments: list[TextSegment] = field(default_factory=list)
    chars: list[CharInfo] = field(default_factory=list)


def _span_color(span: dict) -> int:
    c = span.get("color", 0)
    if isinstance(c, int):
        return c
    return 0


def _interval(rect: fitz.Rect, axis: str) -> tuple[float, float]:
    if axis == "x":
        return rect.x0, rect.x1
    return rect.y0, rect.y1


def _intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _intervals_adjacent(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    gap: float = 2.5,
) -> bool:
    return b[0] - a[1] <= gap or a[0] - b[1] <= gap


def _axes(dir_vec: tuple[float, float]) -> tuple[str, str]:
    dx, dy = dir_vec
    if abs(dx) >= abs(dy):
        return "x", "y"
    return "y", "x"


def _lines_mergeable(prev: LineRun, curr: LineRun) -> bool:
    if prev.dir != curr.dir:
        return False
    text_axis, stack_axis = _axes(prev.dir)
    prev_text = _interval(prev.bbox, text_axis)
    curr_text = _interval(curr.bbox, text_axis)
    prev_stack = _interval(prev.bbox, stack_axis)
    curr_stack = _interval(curr.bbox, stack_axis)

    if not _intervals_overlap(prev_text, curr_text):
        return False

    if _intervals_overlap(prev_stack, curr_stack):
        return True

    prev_width = prev_stack[1] - prev_stack[0]
    curr_width = curr_stack[1] - curr_stack[0]
    max_width = max(prev_width, curr_width)
    gap = min(abs(curr_stack[0] - prev_stack[1]), abs(prev_stack[0] - curr_stack[1]))
    return gap <= 8 and max_width <= 12


def _extract_line_runs(page: fitz.Page) -> list[LineRun]:
    raw = page.get_text("rawdict", flags=fitz.TEXTFLAGS_TEXT)
    runs: list[LineRun] = []

    for block_no, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_no, line in enumerate(block.get("lines", [])):
            dir_vec = tuple(line.get("dir", (1.0, 0.0)))
            bbox = fitz.Rect(line["bbox"])
            chars: list[CharInfo] = []
            for span in line.get("spans", []):
                origin = span.get("origin", (0, 0))
                fontsize = span.get("size", 11)
                color = _span_color(span)
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if not c or c == "\n":
                        continue
                    chars.append(
                        CharInfo(
                            char=c,
                            bbox=fitz.Rect(ch["bbox"]),
                            origin=tuple(ch.get("origin", origin)),
                            fontsize=fontsize,
                            color=color,
                            span=span,
                            block_no=block_no,
                            line_no=line_no,
                            dir=dir_vec,
                        )
                    )
            if chars:
                runs.append(
                    LineRun(
                        block_no=block_no,
                        line_no=line_no,
                        dir=dir_vec,
                        bbox=bbox,
                        chars=chars,
                    )
                )
    return runs


def build_logical_segments(page: fitz.Page) -> list[TextSegment]:
    runs = _extract_line_runs(page)
    if not runs:
        return []

    grouped: list[list[LineRun]] = [[runs[0]]]
    for run in runs[1:]:
        if _lines_mergeable(grouped[-1][-1], run):
            grouped[-1].append(run)
        else:
            grouped.append([run])

    segments: list[TextSegment] = []
    for lines in grouped:
        seg = TextSegment(lines=lines)
        seg.chars = [ch for line in lines for ch in line.chars]
        _build_normalized_segment(seg)
        segments.append(seg)
    return segments


def _same_line(a: CharInfo, b: CharInfo) -> bool:
    return a.block_no == b.block_no and a.line_no == b.line_no


def _build_normalized_segment(segment: TextSegment) -> None:
    """Build normalized string 1:1 with chars (hyphens kept; pattern tolerates breaks)."""
    chars = segment.chars
    normalized: list[str] = []
    norm_to_char: list[int] = []

    for i, ch in enumerate(chars):
        normalized.append(ch.char)
        norm_to_char.append(i)

    segment.normalized = "".join(normalized)
    segment.norm_to_char = norm_to_char


def extract_page_chars(page: fitz.Page) -> PageChars:
    segments = build_logical_segments(page)
    all_chars = [ch for seg in segments for ch in seg.chars]
    return PageChars(segments=segments, chars=all_chars)


def collect_segment_texts(doc: fitz.Document) -> str:
    parts: list[str] = []
    for page in doc:
        for seg in build_logical_segments(page):
            if seg.normalized:
                parts.append(seg.normalized)
    return "\n".join(parts)


def _group_by_line(char_indices: list[int], chars: list[CharInfo]) -> list[list[int]]:
    if not char_indices:
        return []
    groups: list[list[int]] = []
    current = [char_indices[0]]
    for idx in char_indices[1:]:
        if _same_line(chars[idx], chars[current[-1]]):
            current.append(idx)
        else:
            groups.append(current)
            current = [idx]
    groups.append(current)
    return groups


def _fake_for_match(matched_text: str, entity: Entity, mapping: dict[str, str]) -> str:
    if entity.kind == "contract_prefix":
        fake_prefix = mapping[entity.original]
        return apply_prefix_mapping(matched_text, entity.original, fake_prefix)
    fake_full = mapping.get(entity.original, matched_text)
    return map_alnum_to_fake(matched_text, fake_full)


def _find_anchor_positions(normalized: str, anchor: str) -> list[int]:
    positions: list[int] = []
    start = 0
    lower = normalized.lower()
    needle = anchor.lower()
    while True:
        pos = lower.find(needle, start)
        if pos == -1:
            break
        positions.append(pos + len(needle))
        start = pos + 1
    return positions


def _match_tail() -> str:
    """End anchor tolerant to glued competência/dates (e.g. /1913/12)."""
    return r"(?=\d{2}/|/|\D|$|-)"


def _flex_separator(sep: str) -> str:
    if sep == "-":
        return r"-{1,3}"
    if sep == "/":
        return r"(?:/+|/-*)"
    if sep == "_":
        return r"(?:_+|_-+|-*)"
    return r"(?:" + re.escape(sep) + r"|-)*"


def _compile_pattern(entity: Entity) -> str:
    original = entity.original

    if entity.kind == "contract_prefix":
        return re.escape(original) + r"\d{0,4}"

    if original.isdigit():
        body = "-?".join(re.escape(c) for c in original)
        # Allow glued competência (e.g. 1549896282 + 05/08 -> 154989628205/08)
        tail = _match_tail()
        if len(original) <= 6 and not entity.anchor:
            return rf"(?<![\d]){body}{tail}"
        return rf"(?<![\d]){body}{tail}"

    chunks = re.split(r"([^A-Za-z0-9]+)", original)
    body_parts: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        if chunk[0].isalnum():
            body_parts.append(re.escape(chunk))
        else:
            body_parts.append(_flex_separator(chunk))

    body = "".join(body_parts)

    if entity.anchor and original.isdigit():
        return rf"(?<![\d]){re.escape(original)}{_match_tail()}"

    return rf"(?<![\d]){body}{_match_tail()}"


def _find_matches_in_segment(
    segment: TextSegment,
    entities: list[Entity],
    mapping: dict[str, str],
    occupied: set[int],
    *,
    max_anchor_distance: int = 40,
) -> list[TextFragment]:
    normalized = segment.normalized
    norm_to_char = segment.norm_to_char
    chars = segment.chars

    sorted_entities = sorted(entities, key=lambda e: len(e.original), reverse=True)
    fragments: list[TextFragment] = []

    anchor_positions: dict[str, list[int]] = {}
    for e in sorted_entities:
        if e.anchor:
            anchor_positions[e.id] = _find_anchor_positions(normalized, e.anchor)

    for entity in sorted_entities:
        pattern = _compile_pattern(entity)

        for m in re.finditer(pattern, normalized):
            start, end = m.start(), m.end()
            if any(i in occupied for i in range(start, end)):
                continue

            matched_text = normalized[start:end]

            if entity.kind != "contract_prefix" and entity.kind != "name":
                if alnum_skeleton(matched_text) != alnum_skeleton(entity.original):
                    continue

            if entity.anchor:
                anchors = anchor_positions.get(entity.id, [])
                if not any(abs(start - a) <= max_anchor_distance for a in anchors):
                    continue

            char_indices = [norm_to_char[i] for i in range(start, end)]
            fake = _fake_for_match(matched_text, entity, mapping)

            if entity.kind not in ("name", "contract_prefix"):
                if alnum_skeleton(fake) != alnum_skeleton(mapping[entity.original]):
                    continue

            for line_group in _group_by_line(char_indices, chars):
                offset = char_indices.index(line_group[0])
                fake_slice = fake[offset : offset + len(line_group)]
                group_chars = [chars[i] for i in line_group]
                fragments.append(TextFragment(chars=group_chars, fake_text=fake_slice))

            for i in range(start, end):
                occupied.add(i)

    return fragments


def find_matches(
    page_chars: PageChars,
    entities: list[Entity],
    mapping: dict[str, str],
    *,
    max_anchor_distance: int = 40,
) -> list[TextFragment]:
    fragments: list[TextFragment] = []
    for segment in page_chars.segments:
        occupied: set[int] = set()
        fragments.extend(
            _find_matches_in_segment(
                segment,
                entities,
                mapping,
                occupied,
                max_anchor_distance=max_anchor_distance,
            )
        )
    return fragments


def find_name_fragments(
    page_chars: PageChars,
    name: str,
    fake_name: str,
) -> list[TextFragment]:
    """Match beneficiary name; one fragment per visual line per occurrence."""
    name_parts = name.split()
    pattern = r"\s+".join(re.escape(p) for p in name_parts)
    fragments: list[TextFragment] = []

    for segment in page_chars.segments:
        for m in re.finditer(pattern, segment.normalized, flags=re.IGNORECASE):
            char_indices = [segment.norm_to_char[i] for i in range(m.start(), m.end())]
            matched_chars = [segment.chars[i] for i in char_indices]
            matched_text = segment.normalized[m.start() : m.end()]
            from pdf_anonymizer.fakes import preserve_case

            fake = preserve_case(matched_text, fake_name)
            for line_group in _group_by_line(char_indices, segment.chars):
                offset = char_indices.index(line_group[0])
                fake_slice = fake[offset : offset + len(line_group)]
                group_chars = [segment.chars[i] for i in line_group]
                fragments.append(
                    TextFragment(chars=group_chars, fake_text=fake_slice, is_name=True)
                )
    return fragments


def rotate_from_dir(dir_vec: tuple[float, float]) -> int:
    dx, dy = dir_vec
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    return 90 if dy < 0 else 270
