"""Command normalization: lowercase, trim, strip punctuation and filler words."""
from __future__ import annotations

import re

_FILLER_PHRASES = ("can you", "could you", "would you", "will you", "hey jarvis", "ok jarvis")
_FILLER_WORDS = {"please", "jarvis", "archu", "pls", "kindly"}
_NAMES = ("jarvis", "archu")  # what the assistant is called; only stripped as a call at the start/end


def strip_fillers(text: str) -> str:
    """Remove filler words but keep the user's case and punctuation (used to extract slot values verbatim)."""
    t = re.sub(r"\s+", " ", text.strip())
    # "Jarvis" only as a call at the start or end: inside a sentence it is content ("the jarvis project").
    names = "|".join(_NAMES)
    t = re.sub(rf"^((hey|ok|hi|hello)[,\s]+)?({names})\b[,!.:]?\s*|[,\s]+({names})[!.?]*$", " ", t, flags=re.I)
    for p in _FILLER_PHRASES:
        t = re.sub(rf"(^|\s){p}(\s|$)", " ", t, flags=re.I)
    t = re.sub(r"(^|\s)(" + "|".join(_FILLER_WORDS - set(_NAMES)) + r")[,!.]?(?=\s|$)", " ", t, flags=re.I)
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
