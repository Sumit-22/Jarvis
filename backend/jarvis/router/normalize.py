"""Command normalization: lowercase, trim, strip punctuation and filler words."""
from __future__ import annotations

import re

_FILLER_PHRASES = ("can you", "could you", "would you", "will you", "hey jarvis", "ok jarvis")
_FILLER_WORDS = {"please", "jarvis", "pls", "kindly"}


def strip_fillers(text: str) -> str:
    """Remove filler words but keep the user's case and punctuation (used to extract slot values verbatim)."""
    t = re.sub(r"\s+", " ", text.strip())
    for p in _FILLER_PHRASES:
        t = re.sub(rf"(^|\s){p}(\s|$)", " ", t, flags=re.I)
    t = re.sub(r"(^|\s)(" + "|".join(_FILLER_WORDS) + r")[,!.]?(?=\s|$)", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip().rstrip("?!.").strip()


def normalize(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\s\-']", " ", t)  # keep hyphens (leetcode slugs) and apostrophes
    t = t.replace("'", "")
    t = f" {re.sub(r'\s+', ' ', t)} "
    for p in _FILLER_PHRASES:
        t = t.replace(f" {p} ", " ")
    words = [w for w in t.split() if w not in _FILLER_WORDS]
    return " ".join(words)
