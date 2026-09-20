"""Held-out accuracy: corruptions the alias list has never seen.

The 36-case suite in test_matcher.py is not an honest measure of the matcher.
Its phrases were written by the same person who wrote the 363 catalogue
aliases, so "pale gee" resolves partly because "pale gee" is *in* the
catalogue. That number tells you the system handles the failures its author
anticipated.

This suite anticipates nothing. It derives corruptions mechanically from each
product's canonical brand+name, applies the substitutions speech-to-text
actually makes on Indian English, and — critically — **discards any corruption
that happens to match a hand-written alias**. What survives is input the
catalogue has never been shown.

Expect a lower number than 36/36. That lower number is the real one.
"""

from __future__ import annotations

import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from khatam.matcher import Catalogue          # noqa: E402
from khatam.normalize import squash           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAT = Catalogue.load(ROOT / "data" / "catalog.json")

# Substitutions ASR genuinely makes on Indian brand names.
SUBS = [
    ("ph", "f"), ("f", "ph"), ("v", "w"), ("w", "v"), ("z", "j"), ("j", "z"),
    ("c", "k"), ("k", "c"), ("s", "sh"), ("sh", "s"), ("th", "t"), ("t", "th"),
    ("ee", "i"), ("i", "ee"), ("oo", "u"), ("u", "oo"), ("aa", "a"), ("a", "aa"),
    ("y", "i"), ("ai", "ae"), ("ou", "au"),
]


def corrupt(text: str, rng: random.Random, n: int = 2) -> str:
    """Apply n plausible ASR-style mutations."""
    s = text.lower()
    for _ in range(n):
        kind = rng.choice(["sub", "drop", "double", "swap"])
        if kind == "sub":
            rng.shuffle(SUBS)
            for a, b in SUBS:
                if a in s:
                    s = s.replace(a, b, 1)
                    break
        elif kind == "drop" and len(s) > 4:
            i = rng.randrange(len(s))
            if s[i] != " ":
                s = s[:i] + s[i + 1:]
        elif kind == "double" and len(s) > 3:
            i = rng.randrange(len(s))
            if s[i] != " ":
                s = s[:i + 1] + s[i] + s[i + 1:]
        elif kind == "swap" and len(s) > 5:
            i = rng.randrange(len(s) - 1)
            if " " not in s[i:i + 2]:
                s = s[:i] + s[i + 1] + s[i] + s[i + 2:]
    return s


def build_cases(rng: random.Random, per_sku: int = 3):
    """Corruptions of the canonical name that no alias already covers."""
    cases, skipped = [], 0
    for sku in CAT.skus:
        canonical = f"{sku['brand']} {sku['name']}".lower()
        # Everything the catalogue has already been told about this product.
        known = {squash(a) for a in sku.get("aliases", [])}
        known.add(squash(canonical))
        known.add(squash(sku["name"]))
        made = 0
        for attempt in range(40):
            if made >= per_sku:
                break
            c = corrupt(canonical, rng, n=rng.choice([1, 2, 2, 3]))
            if squash(c) in known:          # the alias list already covers it
                skipped += 1
                continue
            known.add(squash(c))
            cases.append((c, sku["id"]))
            made += 1
    return cases, skipped


def run():
    rng = random.Random(20260920)
    cases, skipped = build_cases(rng)

    top1 = top3 = 0
    misses = []
    for phrase, want in cases:
        ranked = CAT.rank(phrase, limit=3)
        ids = [c.sku_id for c in ranked]
        if ids and ids[0] == want:
            top1 += 1
        elif want in ids:
            top3 += 1
            misses.append((phrase, want, ids[0]))
        else:
            misses.append((phrase, want, ids[0] if ids else "-"))

    n = len(cases)
    print(f"held-out corruptions: {n}  "
          f"(discarded {skipped} that an existing alias already covered)\n")
    print(f"  top-1 correct      {top1:4d}/{n}   {top1/n:6.1%}")
    print(f"  correct in top-3   {top1+top3:4d}/{n}   {(top1+top3)/n:6.1%}")
    print(f"  missed entirely    {n-top1-top3:4d}/{n}   {(n-top1-top3)/n:6.1%}")

    print("\n  sample of what it gets wrong:")
    for phrase, want, got in misses[:8]:
        w = CAT.by_id(want); g = CAT.by_id(got)
        print(f"    {phrase:34.34s} -> {(CAT.label(g) if g else got)[:30]:30s}"
              f" (wanted {CAT.label(w)[:26]})")

    # A floor, not a target: this is a regression guard, not a claim of quality.
    return 0 if top1 / n >= 0.55 else 1


if __name__ == "__main__":
    raise SystemExit(run())
