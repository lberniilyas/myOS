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


# Words a model may add or drop when it copies a quote without changing what it says
# ("Oh and I paid 300" quoted as "I also paid 300"). Negations are never in this list.
_QUOTE_FILLERS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "also",
        "oh",
        "so",
        "then",
        "um",
        "uh",
        "like",
        "just",
        "really",
        "actually",
        "too",
        "well",
        "i",
        "et",
        "aussi",
        "puis",
        "alors",
        "euh",
        "bon",
        "donc",
        "je",
        "j",
        "w",
        "wa",
        "ah",
    }
)
CLOSE, PARTIAL, EXACT, NONE = "close", "partial", "exact", "none"


def _most_in_order(needles: list[str], words: list[str], span: int) -> int:
    """The most needles found in order inside any window of `span` consecutive words."""
    best = 0
    for start in range(len(words)):
        found, position, end = 0, start, min(len(words), start + span)
        for needle in needles:
            try:
                position = words.index(needle, position, end) + 1
                found += 1
            except ValueError:
                continue
        best = max(best, found)
        if best == len(needles):
            break
    return best


def evidence_match(text: str, quote: str) -> str:
    """How well an evidence quote is supported by the message.

    "exact": the quote occurs in the message. "close": it differs only in filler words.
    "partial": most of its words occur in order, but something that may matter differs, so the
    record deserves a confirmation. "none": it can't be traced to the message. A number in the
    quote that isn't in the message always means "none".
    """
    if quote_appears_in(text, quote):
        return EXACT
    words = normalize_phrase(text).split()
    quoted = normalize_phrase(quote).split()
    if len(quoted) < 3:
        return NONE
    present = set(words)
    if any(word not in present for word in quoted if any(ch.isdigit() for ch in word)):
        return NONE
    span = 2 * len(quoted) + 4
    content = [word for word in quoted if word not in _QUOTE_FILLERS]
    if content and _most_in_order(content, words, span) == len(content):
        return CLOSE
    if _most_in_order(quoted, words, span) / len(quoted) >= 0.6:
        return PARTIAL
    return NONE


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
