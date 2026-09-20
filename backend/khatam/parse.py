"""Pull intent, quantity and the product phrase out of a spoken utterance.

Deliberately dumb and deterministic. This runs on every utterance for free;
the language model is only called when the *matcher* is unsure which SKU the
product phrase refers to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import basic_clean

# --- direction ------------------------------------------------------------
# "it left the shop" vs "it arrived from the distributor"

_OUT_MARKERS = [
    "khatam", "khatm", "katam", "khattam", "khatma",   # finished
    "ho gaya", "hogaya", "ho gaya hai",
    "gaya", "gayi", "gaye", "chala gaya",
    "nahi hai", "nahi bacha", "nahin hai", "nai hai",
    "finish", "finished", "over", "out", "empty",
    "sold", "bik gaya", "bik gayi",
    "stock out", "no stock",
]

_IN_MARKERS = [
    "aaya", "aayi", "aaye", "aa gaya", "aagaya", "agaya",
    "a gaya", "a gayi", "a gaye",              # from Devanagari "आ गया"
    "mila", "mili", "mil gaya", "mila gaya",
    "stock aaya", "delivery", "deliver", "received", "receive",
    "arrived", "aya", "ayi", "bhar diya", "bhar gaya",
]

# --- quantity -------------------------------------------------------------

_HINDI_NUMBERS = {
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4,
    "panch": 5, "paanch": 5, "chhe": 6, "che": 6, "chah": 6,
    "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9,
    "das": 10, "dus": 10, "gyarah": 11, "barah": 12, "bara": 12,
    "pandrah": 15, "bees": 20, "bis": 20, "pachas": 50, "sau": 100,
}

_ENGLISH_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "fifty": 50, "hundred": 100,
}

_FRACTIONS = {
    "adha": 0.5, "aadha": 0.5, "adhaa": 0.5, "half": 0.5,
    "pav": 0.25, "paav": 0.25, "quarter": 0.25,
    "dedh": 1.5, "derh": 1.5, "sava": 1.25, "dhai": 2.5, "dhaai": 2.5,
}

# Units the shopkeeper actually says. Kept separate from quantity so
# "do patti" reads as 2 strips, not 2 of an unknown thing.
_UNITS = {
    "packet": "packet", "pack": "packet", "paket": "packet",
    "bottle": "bottle", "botal": "bottle", "botel": "bottle",
    "dabba": "box", "dabbe": "box", "box": "box", "dibba": "box",
    "patti": "strip", "patty": "strip", "strip": "strip",
    "goli": "piece", "piece": "piece", "pcs": "piece", "nag": "piece",
    "kg": "kg", "kilo": "kg", "kilos": "kg",
    "gram": "gram", "gm": "gram", "grams": "gram",
    "litre": "litre", "liter": "litre", "ltr": "litre",
    "peti": "case", "case": "case", "carton": "case", "katta": "sack",
    "bag": "bag", "bora": "sack", "sack": "sack",
    "tray": "tray", "jar": "jar", "tube": "tube", "bar": "bar",
    "roll": "roll", "refill": "refill",
}


@dataclass
class Utterance:
    raw: str
    direction: str = "out"           # "out" | "in"
    quantity: float = 1.0
    quantity_explicit: bool = False
    unit: str | None = None
    product_phrase: str = ""
    markers: list[str] = field(default_factory=list)


def _lookup(word: str, *tables: dict):
    """Look a word up, tolerating the schwa Devanagari leaves behind.

    "दस" transliterates to "dasa", not "das"; "चार" to "chara". Rather than
    duplicating every entry, we retry once without a trailing 'a'.
    """
    for table in tables:
        if word in table:
            return table[word]
    if len(word) > 2 and word.endswith("a"):
        trimmed = word[:-1]
        for table in tables:
            if trimmed in table:
                return table[trimmed]
    return None


def _spans(text: str, marker: str, direction: str) -> list[tuple[int, int, str, str]]:
    """Every whole-word occurrence of `marker` as (start, end, direction, marker).

    Word boundaries are not optional here: "aya" (arrived) is a substring of
    "gaya" (went), so a naive find() flips the direction of every sentence
    ending in "ho gaya".
    """
    pattern = r"\b" + re.escape(marker) + r"\b"
    return [(m.start(), m.end(), direction, marker) for m in re.finditer(pattern, text)]


def _find_direction(text: str) -> tuple[str, list[str]]:
    """In Hindi the verb follows the product, so the latest marker wins —
    but only after overlapping markers have been resolved in favour of the
    longer one. "aa gaya" (arrived) literally contains "gaya" (went), and
    the nested match starts later, so position alone gets it backwards.
    """
    found: list[tuple[int, int, str, str]] = []
    for marker in _OUT_MARKERS:
        found += _spans(text, marker, "out")
    for marker in _IN_MARKERS:
        found += _spans(text, marker, "in")
    if not found:
        return "out", []

    def contained(span, others):
        s, e, _, _ = span
        return any(o_s <= s and e <= o_e and (o_e - o_s) > (e - s) for o_s, o_e, _, _ in others)

    outermost = [f for f in found if not contained(f, found)]
    chosen = max(outermost, key=lambda t: (t[0], t[1] - t[0]))
    return chosen[2], [f[3] for f in found]


def _strip_markers(text: str, markers: list[str]) -> str:
    for marker in sorted(markers, key=len, reverse=True):
        text = text.replace(marker, " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_utterance(raw: str) -> Utterance:
    text = basic_clean(raw)
    direction, markers = _find_direction(text)
    remainder = _strip_markers(text, markers)

    quantity = 1.0
    explicit = False
    unit = None
    kept: list[str] = []

    for word in remainder.split():
        if not explicit:
            if word.isdigit():
                quantity, explicit = float(word), True
                continue
            hit = _lookup(word, _HINDI_NUMBERS, _ENGLISH_NUMBERS, _FRACTIONS)
            if hit is not None:
                quantity, explicit = float(hit), True
                continue
        u = _lookup(word, _UNITS)
        if u is not None and unit is None:
            unit = u
            # keep it: some aliases *are* unit phrases ("shampoo ki patti")
        kept.append(word)

    return Utterance(
        raw=raw,
        direction=direction,
        quantity=quantity,
        quantity_explicit=explicit,
        unit=unit,
        product_phrase=" ".join(kept).strip(),
        markers=markers,
    )
