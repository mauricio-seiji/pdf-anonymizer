"""Deterministic fake value generation preserving format."""

from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass
from typing import Literal

EntityKind = Literal[
    "name",
    "nb",
    "digits",
    "alphanumeric",
    "contract",
    "contract_prefix",
    "ctc_contract",
]

# CTC0003924227 -> CTC + trunk(000392) + suffix(4227)
CTC_CONTRACT_PATTERN = re.compile(r"^CTC(000392)(\d{4})$")
CTC_TRUNK_ORIGINAL = "000392"

NB_PATTERN = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d\b")
AUTH_CODE_PATTERN = re.compile(r"\b\d{6}[A-Z0-9]{6,}-[A-Z0-9]{6,}\b")


def is_auth_code(token: str) -> bool:
    if not AUTH_CODE_PATTERN.fullmatch(token):
        return False
    return any(c.isalpha() for c in token)
CTC_PATTERN = re.compile(r"\bCTC\d{10}\b")
HYPHEN_CONTRACT = re.compile(r"\b\d{6,}-\d{1,3}\b")
SLASH_CONTRACT = re.compile(
    r"\b\d{2}-\d{6,9}/(?:\d{2}(?:_\d{2})?|\d{5})(?!\d)\b"
)
LONG_DIGITS = re.compile(r"(?<![\d.,/])\d{8,}(?!\d)")
CARD_UNDERSCORE = re.compile(r"(\d{10})_\d{2}")

CARD_PREFIX_MIN_LEN = 15
CARD_PREFIX_TAIL_LEN = 4


@dataclass(frozen=True)
class Entity:
    id: str
    kind: EntityKind
    original: str
    replacement: str | None = None
    anchor: str | None = None  # context label for short values (e.g. "Agência")


def preserve_case(original: str, replacement: str) -> str:
    """Apply casing pattern of *original* onto *replacement*."""
    if original.isupper():
        return replacement.upper()
    if original.islower():
        return replacement.lower()
    if original.istitle():
        return replacement.title()
    chars: list[str] = []
    for o, r in zip(original, replacement, strict=False):
        if o.isupper():
            chars.append(r.upper())
        elif o.islower():
            chars.append(r.lower())
        else:
            chars.append(r)
    if len(replacement) > len(original):
        chars.extend(replacement[len(original) :])
    return "".join(chars)


def _fake_digit_at(rng: random.Random, original_digit: str) -> str:
    choices = [str(d) for d in range(10) if str(d) != original_digit]
    return rng.choice(choices)


def _fake_letter_at(rng: random.Random, original_letter: str) -> str:
    pool = string.ascii_uppercase
    if original_letter.islower():
        pool = string.ascii_lowercase
    choices = [c for c in pool if c != original_letter]
    return rng.choice(choices)


def _generate_digit_string(original: str, rng: random.Random) -> str:
    out: list[str] = []
    for ch in original:
        if ch.isdigit():
            out.append(_fake_digit_at(rng, ch))
        else:
            out.append(ch)
    return "".join(out)


def generate_fake(original: str, kind: EntityKind, rng: random.Random) -> str:
    """Generate a fake value with the same length and separator layout."""
    out: list[str] = []
    for ch in original:
        if ch.isdigit():
            out.append(_fake_digit_at(rng, ch))
        elif ch.isalpha():
            repl = _fake_letter_at(rng, ch)
            out.append(repl.upper() if ch.isupper() else repl.lower())
        else:
            out.append(ch)
    return "".join(out)


def _generate_ctc_batch(
    contracts: list[str],
    rng: random.Random,
    *,
    fake_values: set[str],
    originals: set[str],
) -> dict[str, str]:
    fake_trunk = _generate_digit_string(CTC_TRUNK_ORIGINAL, rng)
    while fake_trunk == CTC_TRUNK_ORIGINAL or fake_trunk in fake_values:
        rng2 = random.Random(rng.randint(0, 999999))
        fake_trunk = _generate_digit_string(CTC_TRUNK_ORIGINAL, rng2)

    used_suffixes: set[str] = set()
    mapping: dict[str, str] = {}

    for original in sorted(contracts):
        m = CTC_CONTRACT_PATTERN.match(original)
        if not m:
            continue
        suffix = m.group(2)
        for _ in range(200):
            fake_suffix = "".join(_fake_digit_at(rng, d) for d in suffix)
            if fake_suffix == suffix or fake_suffix in used_suffixes:
                continue
            fake = f"CTC{fake_trunk}{fake_suffix}"
            if fake != original and fake not in fake_values and fake not in originals:
                mapping[original] = fake
                used_suffixes.add(fake_suffix)
                fake_values.add(fake)
                break
        else:
            raise ValueError(f"Could not generate unique CTC fake for {original!r}")

    return mapping


def build_mapping(
    entities: list[Entity],
    seed: int = 42,
) -> dict[str, str]:
    """Return original -> fake mapping with collision checks."""
    rng = random.Random(seed)
    mapping: dict[str, str] = {}
    fake_values: set[str] = set()
    originals = {e.original for e in entities}

    ctc_contracts = [
        e.original
        for e in entities
        if e.kind == "ctc_contract" or CTC_CONTRACT_PATTERN.match(e.original)
    ]
    if ctc_contracts:
        mapping.update(
            _generate_ctc_batch(ctc_contracts, rng, fake_values=fake_values, originals=originals)
        )

    for entity in entities:
        original = entity.original
        if original in mapping:
            continue

        if entity.replacement is not None:
            if entity.kind == "name":
                fake = preserve_case(original, entity.replacement)
            else:
                fake = entity.replacement
        else:
            fake = generate_fake(original, entity.kind, rng)

        if fake == original:
            raise ValueError(f"Fake equals original for {entity.id}: {original!r}")
        if fake in fake_values or fake in originals:
            for attempt in range(100):
                rng2 = random.Random(seed + attempt + hash(original) % 10000)
                fake = generate_fake(original, entity.kind, rng2)
                if fake != original and fake not in fake_values and fake not in originals:
                    break
            else:
                raise ValueError(f"Could not generate unique fake for {entity.id}")

        mapping[original] = fake
        fake_values.add(fake)

    return mapping


def apply_prefix_mapping(full: str, prefix: str, fake_prefix: str) -> str:
    """Replace a contract prefix inside a longer token (preserves suffix)."""
    if not full.startswith(prefix):
        return full
    return fake_prefix + full[len(prefix) :]
