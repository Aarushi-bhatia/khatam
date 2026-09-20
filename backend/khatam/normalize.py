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


# --- Devanagari -------------------------------------------------------------
# Chrome's speech API returns Devanagari for hi-IN, not romanised Hinglish:
# you get "मैगी खत्म", never "maggi khatam". Everything downstream works in
# Latin, so we transliterate at the door.
#
# The romanisation is deliberately rough. It doesn't need to be correct — it
# feeds straight into squash()/skeleton(), which throw away vowel length
# anyway, and the consonant skeleton rescues the schwa problem ("parale" and
# "parle" both reduce to "prl").

_DEVA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}

_DEVA_VOWELS = {           # independent
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}

_DEVA_MATRAS = {           # dependent, replace the inherent 'a'
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}

_DEVA_DIGITS = {d: str(i) for i, d in enumerate("०१२३४५६७८९")}

_VIRAMA = "्"
_NASALS = {"ं", "ँ"}      # anusvara, chandrabindu
_VISARGA = "ः"


def transliterate(text: str) -> str:
    """Devanagari → rough Latin. Latin passes through untouched."""
    if not any("ऀ" <= ch <= "ॿ" for ch in text):
        return text

    out: list[str] = []
    inherent = False                 # a consonant is awaiting its vowel

    for ch in text:
        if ch in _DEVA_CONSONANTS:
            if inherent:
                out.append("a")
            out.append(_DEVA_CONSONANTS[ch])
            inherent = True
        elif ch in _DEVA_MATRAS:
            out.append(_DEVA_MATRAS[ch])
            inherent = False
        elif ch == _VIRAMA:
            inherent = False         # explicit "no vowel here"
        elif ch in _DEVA_VOWELS:
            if inherent:
                out.append("a")
                inherent = False
            out.append(_DEVA_VOWELS[ch])
        elif ch in _NASALS:
            if inherent:
                out.append("a")
                inherent = False
            out.append("n")
        elif ch == _VISARGA:
            if inherent:
                out.append("a")
                inherent = False
            out.append("h")
        elif ch in _DEVA_DIGITS:
            if inherent:
                out.append("a")
                inherent = False
            out.append(_DEVA_DIGITS[ch])
        else:
            if inherent:
                out.append("a")
                inherent = False
            out.append(ch)

    if inherent:
        out.append("a")

    # Vowel length is noise; collapsing it here keeps the marker lists in
    # parse.py to one spelling each ("gaya", not "gayaa").
    return re.sub(r"([aeiou])\1+", r"\1", "".join(out))


def basic_clean(text: str) -> str:
    """Transliterate, lowercase, strip punctuation, squeeze whitespace."""
    text = transliterate(text).lower().strip()
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
