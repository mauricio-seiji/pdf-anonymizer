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
    KNOWN_ACCOUNT,
    KNOWN_AGENCY,
    KNOWN_NAME,
    LONG_DIGITS,
    NB_PATTERN,
    CARD_PREFIX_MIN_LEN,
    CARD_PREFIX_TAIL_LEN,
    Entity,
)
from pdf_anonymizer.matcher import collect_segment_texts


def extract_page_text(doc: fitz.Document) -> str:
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text"))
    return "\n".join(parts)


def detect_card_prefixes(values: set[str]) -> set[str]:
    """Find digit prefixes whose last CARD_PREFIX_TAIL_LEN digits vary (MMAA)."""
    prefixes: set[str] = set()
    by_len: dict[int, dict[str, set[str]]] = {}

    for v in values:
        if not v.isdigit() or len(v) < CARD_PREFIX_MIN_LEN + 2:
            continue
        length = len(v)
        prefix = v[: length - CARD_PREFIX_TAIL_LEN]
        by_len.setdefault(length, {}).setdefault(prefix, set()).add(v)

    for groups in by_len.values():
        for prefix, group in groups.items():
            if len(group) >= 3 and len(prefix) >= CARD_PREFIX_MIN_LEN:
                prefixes.add(prefix)

    return prefixes


def _prune_tokens(tokens: set[str], prefixes: set[str]) -> set[str]:
    """Remove tokens covered by prefix or hyphenated parent."""
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


def discover_from_text(text: str) -> list[Entity]:
    entities: list[Entity] = []
    seen: set[str] = set()

    def add(entity: Entity) -> None:
        if entity.original in seen:
            return
        seen.add(entity.original)
        entities.append(entity)

    if KNOWN_NAME in text:
        add(Entity(id="nome", kind="name", original=KNOWN_NAME))

    for m in NB_PATTERN.finditer(text):
        add(Entity(id="nb", kind="nb", original=m.group()))

    if KNOWN_ACCOUNT in text:
        add(Entity(id="conta", kind="digits", original=KNOWN_ACCOUNT))

    if KNOWN_AGENCY in text:
        add(
            Entity(
                id="agencia",
                kind="digits",
                original=KNOWN_AGENCY,
                anchor="Agência",
            )
        )

    for m in AUTH_CODE_PATTERN.finditer(text):
        add(Entity(id="autenticidade", kind="alphanumeric", original=m.group()))

    for m in CTC_PATTERN.finditer(text):
        token = m.group()
        kind = "ctc_contract" if CTC_CONTRACT_PATTERN.match(token) else "contract"
        add(Entity(id=f"ctc_{token}", kind=kind, original=token))

    for m in HYPHEN_CONTRACT.finditer(text):
        token = m.group()
        add(Entity(id=f"hyphen_{token.replace('-', '_')}", kind="contract", original=token))

    long_digits: set[str] = set()
    for m in LONG_DIGITS.finditer(text):
        token = m.group()
        # Skip contract+date gluing (e.g. 190124207107/08/2025)
        if m.end() < len(text) and text[m.end()] == "/":
            continue
        long_digits.add(token)

    for m in CARD_UNDERSCORE.finditer(text):
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
        long_digits | {m.group() for m in HYPHEN_CONTRACT.finditer(text)},
        prefixes,
    )

    card_bases = {e.original for e in entities if e.id.startswith("card_")}

    for token in sorted(pruned, key=len, reverse=True):
        if token.startswith("CTC"):
            continue
        if token in card_bases:
            continue
        if any(token.startswith(p) and token != p for p in prefixes):
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
            if any(
                token in body and token != body
                for body in ctc_bodies
                for token in [e.original]
            ):
                continue
        filtered.append(e)
    return filtered


def discover_pdfs(docs_dir: Path) -> list[Entity]:
    combined = ""
    for pdf in sorted(docs_dir.glob("*.pdf")):
        doc = fitz.open(pdf)
        try:
            combined += collect_segment_texts(doc) + "\n"
        finally:
            doc.close()
    return discover_from_text(combined)


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
    path.write_text(entities_to_yaml(entities))


def count_occurrences(text: str, entities: list[Entity]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for e in entities:
        counts[e.original] = text.count(e.original)
    return counts
