"""Discover sensitive entities from PDF text."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf as fitz
import yaml

from pdf_anonymizer.fakes import (
    AUTH_CODE_PATTERN,
    CARD_UNDERSCORE,
    CTC_CONTRACT_PATTERN,
    CTC_PATTERN,
    HYPHEN_CONTRACT,
    LONG_DIGITS,
    NB_PATTERN,
    SLASH_CONTRACT,
    is_auth_code,
    CARD_PREFIX_MIN_LEN,
    CARD_PREFIX_TAIL_LEN,
    Entity,
)
from pdf_anonymizer.matcher import collect_segment_texts
from pdf_anonymizer.text_utils import join_hyphenation


def _is_valid_mmaa_suffix(tail: str) -> bool:
    if len(tail) != 4 or not tail.isdigit():
        return False
    month = int(tail[:2])
    return 1 <= month <= 12


def extract_page_text(doc: fitz.Document) -> str:
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text"))
    return "\n".join(parts)


def plain_lines_for_discovery(doc: fitz.Document) -> str:
    """Line-joined plain text (avoids cross-cell glue in table segments)."""
    lines: list[str] = []
    for page in doc:
        for line in page.get_text("text").splitlines():
            joined = join_hyphenation(line)
            if joined.strip():
                lines.append(joined)
    return "\n".join(lines)


def detect_card_prefixes(values: set[str]) -> set[str]:
    prefixes: set[str] = set()
    by_len: dict[int, dict[str, set[str]]] = {}

    for v in values:
        if not v.isdigit() or len(v) < CARD_PREFIX_MIN_LEN + 2:
            continue
        length = len(v)
        prefix = v[: length - CARD_PREFIX_TAIL_LEN]
        tail = v[length - CARD_PREFIX_TAIL_LEN :]
        if not _is_valid_mmaa_suffix(tail):
            continue
        by_len.setdefault(length, {}).setdefault(prefix, set()).add(v)

    for groups in by_len.values():
        for prefix, group in groups.items():
            if len(group) >= 3 and len(prefix) >= CARD_PREFIX_MIN_LEN:
                prefixes.add(prefix)

    return prefixes


def _prune_tokens(tokens: set[str], prefixes: set[str]) -> set[str]:
    pruned = set(tokens)

    for t in list(pruned):
        if any(x.startswith(t + "-") for x in tokens):
            pruned.discard(t)
        for p in prefixes:
            if t.startswith(p) and t != p:
                pruned.discard(t)

    for t in list(pruned):
        if t in prefixes:
            continue
        for other in pruned:
            if other != t and other.startswith(t) and len(other) > len(t):
                pruned.discard(t)
                break

    return pruned


def _drop_digit_substrings(tokens: set[str]) -> set[str]:
    digit_tokens = sorted((t for t in tokens if t.isdigit()), key=len, reverse=True)
    keep: set[str] = set()
    for t in digit_tokens:
        if any(t != k and t in k for k in keep):
            continue
        keep.add(t)
    for t in tokens:
        if not t.isdigit():
            keep.add(t)
    return keep


def _valid_slash_token(token: str) -> bool:
    m = SLASH_CONTRACT.search(token)
    if not m or m.group() != token:
        return False
    _, rest = token.split("/", 1)
    if "_" in rest:
        base, suffix = rest.split("_", 1)
        return base.isdigit() and suffix.isdigit() and len(suffix) == 2
    return rest.isdigit() and len(rest) in (2, 5)


def discover_from_text(
    text: str,
    *,
    holder_name: str | None = None,
    fake_name: str | None = None,
    account: str | None = None,
    agency: str | None = None,
    discovery_text: str | None = None,
) -> list[Entity]:
    entities: list[Entity] = []
    seen: set[str] = set()
    disc_text = discovery_text if discovery_text is not None else text

    def add(entity: Entity) -> None:
        if entity.original in seen:
            return
        seen.add(entity.original)
        entities.append(entity)

    if holder_name and holder_name in text:
        add(
            Entity(
                id="nome",
                kind="name",
                original=holder_name,
                replacement=fake_name,
            )
        )

    for m in NB_PATTERN.finditer(disc_text):
        add(Entity(id="nb", kind="nb", original=m.group()))

    if account and account in disc_text:
        add(Entity(id="conta", kind="digits", original=account))

    if agency and agency in disc_text:
        add(
            Entity(
                id="agencia",
                kind="digits",
                original=agency,
                anchor="Agência",
            )
        )

    for m in AUTH_CODE_PATTERN.finditer(disc_text):
        token = m.group()
        if is_auth_code(token):
            add(Entity(id="autenticidade", kind="alphanumeric", original=token))

    for m in CTC_PATTERN.finditer(disc_text):
        token = m.group()
        kind = "ctc_contract" if CTC_CONTRACT_PATTERN.match(token) else "contract"
        add(Entity(id=f"ctc_{token}", kind=kind, original=token))

    for m in SLASH_CONTRACT.finditer(disc_text):
        token = m.group()
        if _valid_slash_token(token):
            add(Entity(id=f"slash_{token.replace('/', '_').replace('-', '_')}", kind="contract", original=token))

    hyphen_tokens: set[str] = set()
    for m in HYPHEN_CONTRACT.finditer(disc_text):
        hyphen_tokens.add(m.group())

    for token in sorted(hyphen_tokens, key=len, reverse=True):
        if any(
            token != other
            and other.startswith(token.split("-")[0] + "-")
            and len(token) > len(other.split("-")[0]) + 2
            for other in hyphen_tokens
            if len(other) < len(token)
        ):
            continue
        add(Entity(id=f"hyphen_{token.replace('-', '_')}", kind="contract", original=token))

    long_digits: set[str] = set()
    for m in LONG_DIGITS.finditer(disc_text):
        token = m.group()
        if m.end() < len(disc_text) and disc_text[m.end()] == "/":
            continue
        long_digits.add(token)

    long_digits = _drop_digit_substrings(long_digits)

    for m in CARD_UNDERSCORE.finditer(disc_text):
        base = m.group(1)
        add(Entity(id=f"card_{base}", kind="contract", original=base))

    prefixes = detect_card_prefixes(long_digits)
    for prefix in sorted(prefixes, key=len, reverse=True):
        add(
            Entity(
                id=f"prefix_{prefix[:12]}",
                kind="contract_prefix",
                original=prefix,
            )
        )

    pruned = _prune_tokens(
        long_digits | hyphen_tokens,
        prefixes,
    )

    card_bases = {e.original for e in entities if e.id.startswith("card_")}
    slash_tokens = {e.original for e in entities if e.id.startswith("slash_")}

    for token in sorted(pruned, key=len, reverse=True):
        if token.startswith("CTC"):
            continue
        if token in card_bases:
            continue
        if token in slash_tokens:
            continue
        if any(token.startswith(p) and token != p for p in prefixes):
            continue
        if token.isdigit() and any(token in s.replace("-", "").replace("/", "") for s in slash_tokens):
            continue
        add(Entity(id=f"contract_{token}", kind="contract", original=token))

    stems = {e.original for e in entities if e.kind == "contract"}
    ctc_bodies = {e.original[3:] for e in entities if e.original.startswith("CTC")}
    hyphen_compact = {
        e.original.replace("-", "")
        for e in entities
        if e.kind == "contract" and "-" in e.original
    }

    filtered: list[Entity] = []
    for e in entities:
        if e.kind == "contract" and e.original.isdigit():
            if any(s.startswith(e.original + "-") for s in stems):
                continue
            if e.original in hyphen_compact:
                continue
            if any(token in body and token != body for body in ctc_bodies for token in [e.original]):
                continue
            if len(e.original) < 8 and any(
                e.original in long.replace("-", "") for long in stems if long.isdigit()
            ):
                continue
        filtered.append(e)
    return filtered


def discover_pdf(
    pdf_path: Path,
    *,
    holder_name: str | None = None,
    fake_name: str | None = None,
    account: str | None = None,
    agency: str | None = None,
) -> list[Entity]:
    doc = fitz.open(pdf_path)
    try:
        combined = collect_segment_texts(doc) + "\n"
        disc = plain_lines_for_discovery(doc)
    finally:
        doc.close()
    return discover_from_text(
        combined,
        holder_name=holder_name,
        fake_name=fake_name,
        account=account,
        agency=agency,
        discovery_text=disc,
    )


def discover_pdfs(docs_dir: Path) -> list[Entity]:
    combined = ""
    disc_parts: list[str] = []
    for pdf in sorted(docs_dir.glob("*.pdf")):
        doc = fitz.open(pdf)
        try:
            combined += collect_segment_texts(doc) + "\n"
            disc_parts.append(plain_lines_for_discovery(doc))
        finally:
            doc.close()
    return discover_from_text(combined, discovery_text="\n".join(disc_parts))


def entities_to_yaml(entities: list[Entity]) -> str:
    data = {
        "entities": [
            {
                "id": e.id,
                "kind": e.kind,
                "original": e.original,
                **({"anchor": e.anchor} if e.anchor else {}),
                **({"replacement": e.replacement} if e.replacement else {}),
            }
            for e in entities
        ]
    }
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_entities(path: Path) -> list[Entity]:
    raw = yaml.safe_load(path.read_text())
    entities: list[Entity] = []
    for item in raw.get("entities", []):
        entities.append(
            Entity(
                id=item["id"],
                kind=item["kind"],
                original=item["original"],
                replacement=item.get("replacement"),
                anchor=item.get("anchor"),
            )
        )
    return entities


def save_entities(path: Path, entities: list[Entity]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entities_to_yaml(entities))


def count_occurrences(text: str, entities: list[Entity]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for e in entities:
        counts[e.original] = text.count(e.original)
    return counts
