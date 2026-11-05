"""Language-agnostic text normalization and fuzzy name matching.

Entity resolution compares what the user said ("the tender app") with known names and
aliases ("TenderPilot", "tender app"). Everything here is deterministic so the same input
always resolves the same way.
"""

import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)

# Words that describe a reference rather than name it ("my project", "le projet").
_MENTION_FILLERS = frozenset(
    {
        "the",
        "my",
        "a",
        "an",
        "our",
        "this",
        "that",
        "of",
        "project",
        "app",
        "application",
        "le",
        "la",
        "les",
        "l",
        "mon",
        "ma",
        "mes",
        "du",
        "de",
        "des",
        "projet",
    }
)


def fold(value: str) -> str:
    """Lowercase and strip accents/diacritics so "Étude" and "etude" compare equal."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def normalize_phrase(value: str) -> str:
    return " ".join(_NON_WORD.sub(" ", fold(value)).split())


def compact_key(value: str) -> str:
    """Key used for uniqueness: "Tender Pilot" and "TenderPilot" collide on purpose."""
    return normalize_phrase(value).replace(" ", "")


def mention_key(value: str) -> str:
    words = [word for word in normalize_phrase(value).split() if word not in _MENTION_FILLERS]
    return "".join(words) or compact_key(value)


def name_match_score(mention: str, names: Iterable[str]) -> float:
    """Best match score in [0, 1] between a mention and any of an entity's names."""
    key = mention_key(mention)
    if not key:
        return 0.0
    best = 0.0
    for name in names:
        candidate = mention_key(name)
        if not candidate:
            continue
        if key == candidate:
            return 1.0
        shorter = min(len(key), len(candidate))
        if shorter >= 4 and (key in candidate or candidate in key):
            best = max(best, 0.85)
            continue
        ratio = SequenceMatcher(None, key, candidate).ratio()
        if ratio >= 0.8:
            best = max(best, min(ratio * 0.95, 0.95))
    return best


def quote_appears_in(text: str, quote: str) -> bool:
    """True when every fragment of an evidence quote occurs, in order, in the text.

    Comparison ignores case, accents, punctuation and spacing, so a quote that drops a comma
    still counts, but a paraphrase does not.
    """
    haystack = normalize_phrase(text)
    fragments = [normalize_phrase(part) for part in re.split(r"\.\.\.|…", quote)]
    fragments = [fragment for fragment in fragments if fragment]
    if not fragments:
        return False
    position = 0
    for fragment in fragments:
        found = haystack.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return True
