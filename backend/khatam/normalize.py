"""Text normalisation for Hinglish speech-to-text output.

Transcribe (and every other ASR) mangles Indian brand names in predictable
ways: aspirated consonants collapse, v/w and j/z swap, doubled letters come
and go, and vowel length is basically noise. We normalise both the
transcription and the catalogue aliases into the same lossy space so that
"pale gee", "parle ji" and "parle-g" all land within striking distance of
each other.
"""

from __future__ import annotations

import re

# Digraphs first (longest match wins), then single-character folds.
_DIGRAPHS = [
    ("ph", "f"),
    ("bh", "b"),
    ("dh", "d"),
    ("gh", "g"),
    ("jh", "j"),
    ("kh", "k"),
    ("th", "t"),
    ("chh", "c"),
    ("ch", "c"),
    ("sh", "s"),
    ("ck", "k"),
    ("qu", "k"),
    ("x", "ks"),
]

_SINGLES = str.maketrans({
    "w": "v",
    "z": "j",
    "q": "k",
    "y": "i",
})

_VOWELS = set("aeiou")

_STOPWORDS = {
    # filler that carries no product signal
    "wala", "wali", "ka", "ki", "ke", "ko", "hai", "hain", "ye", "yeh", "woh",
    "vo", "arre", "are", "bhai", "ek", "the", "a", "an", "of", "and", "aur",
    "please", "zara", "jara", "bhi", "na", "to", "toh",
}


def basic_clean(text: str) -> str:
    """Lowercase, strip punctuation, squeeze whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def squash(text: str) -> str:
    """Collapse a string into the lossy phonetic space described above."""
    s = basic_clean(text).replace(" ", "")
    for a, b in _DIGRAPHS:
        s = s.replace(a, b)
    s = s.translate(_SINGLES)
    # Collapse any run of repeated characters: "maggi" -> "magi", "aa" -> "a".
    s = re.sub(r"(.)\1+", r"\1", s)
    # Vowel length is noise, but vowel *presence* still separates words.
    s = re.sub(r"[aeiou]+", lambda m: m.group(0)[0], s)
    return s


def skeleton(text: str) -> str:
    """Consonant skeleton — the most aggressive form we use.

    "maggi"/"meggi"/"magi" all reduce to "mg", which rescues matches that
    vowel-level comparison would miss entirely.
    """
    return "".join(ch for ch in squash(text) if ch not in _VOWELS)


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    """Word tokens with filler removed."""
    words = basic_clean(text).split()
    if drop_stopwords:
        words = [w for w in words if w not in _STOPWORDS]
    return words
