"""Text normalization for discovery and validation."""

from __future__ import annotations

import re

# Join react-pdf line-break hyphenation in plain text
_JOIN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"--\n"), "-"),
    (re.compile(r"([/_])-\n"), r"\1"),
    (re.compile(r"(\d)-\n(\d)"), r"\1\2"),
    (re.compile(r"_-\n"), "_"),
]


def join_hyphenation(text: str) -> str:
    out = text
    for pat, repl in _JOIN_PATTERNS:
        out = pat.sub(repl, out)
    return out


def digit_skeleton(text: str) -> str:
    return re.sub(r"[^\d]", "", text)


def alnum_skeleton(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", text)


def map_alnum_to_fake(matched: str, fake_full: str) -> str:
    """Replace alnum chars in *matched* with alnum chars from *fake_full* in order."""
    fake_alnum = list(alnum_skeleton(fake_full))
    if not fake_alnum:
        return matched
    fi = 0
    out: list[str] = []
    for ch in matched:
        if ch.isalnum():
            out.append(fake_alnum[fi])
            fi += 1
        else:
            out.append(ch)
    return "".join(out)
