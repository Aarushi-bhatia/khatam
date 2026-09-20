"""The measurement that actually matters, and the one the matcher fails.

test_holdout.py corrupts the *canonical product name* and the matcher scores
98% — but that is an easier task than the real one. Nobody standing at a
counter says "Maggi 2-Minute Noodles". They say "maggi". And for a great many
products the word they use shares no letters at all with the label on the
box: milk is "doodh", soap is "sabun", matches are "maachis", eggs are "anda".

Those words only work today because I hand-wrote them into the catalogue.
This suite deletes that help and measures what is left: for every SKU that has
a colloquial alias, strip the aliases and see whether the phonetic matcher can
still find the product from the word a shopkeeper would actually use.

It cannot, and it never could — no amount of phonetic normalisation gets from
"doodh" to "Amul Taaza Toned Milk". That is a vocabulary problem, not a
spelling one, and it is the real reason the catalogue needs 363 hand-written
aliases it will never get in a real shop.

This is the gap the language model is for.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # tests_support

from khatam.matcher import Catalogue          # noqa: E402
from khatam.normalize import squash           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))

from tests_support import COLLOQUIAL          # noqa: E402


def catalogue_without_aliases() -> Catalogue:
    stripped = json.loads(json.dumps(RAW))          # deep copy
    for sku in stripped["skus"]:
        sku["aliases"] = []
    return Catalogue(stripped)


def run():
    with_aliases = Catalogue(RAW)
    without = catalogue_without_aliases()

    hit_with = hit_without = 0
    rows = []
    for phrase, want in COLLOQUIAL:
        a = with_aliases.rank(phrase, limit=1)
        b = without.rank(phrase, limit=1)
        ok_a = bool(a) and a[0].sku_id == want
        ok_b = bool(b) and b[0].sku_id == want
        hit_with += ok_a
        hit_without += ok_b
        rows.append((phrase, want, ok_a, ok_b,
                     with_aliases.label(with_aliases.by_id(want)),
                     b[0].label if b else "-"))

    n = len(COLLOQUIAL)
    print("What a shopkeeper says vs what the box says\n")
    print(f"  {'he says':16s} {'with aliases':14s} {'aliases stripped':18s} lands on instead")
    print("  " + "-" * 82)
    for phrase, want, ok_a, ok_b, label, got in rows:
        print(f"  {phrase:16s} {('found' if ok_a else 'MISS'):14s} "
              f"{('found' if ok_b else 'MISS'):18s} {'' if ok_b else got[:34]}")
    print("  " + "-" * 82)
    print(f"  with hand-written aliases : {hit_with}/{n}  ({hit_with/n:.0%})")
    print(f"  aliases stripped          : {hit_without}/{n}  ({hit_without/n:.0%})")
    print()
    print(f"  => {hit_with - hit_without} of {n} everyday words are carried entirely by")
    print( "     aliases a human wrote. Phonetics cannot bridge a vocabulary gap.")
    print( "     A 500-SKU shop needs ~2,400 of these. Nobody is going to type them.")

    # This suite is a demonstration, not a gate — it is expected to fail badly
    # without aliases. Assert only that aliases are doing what we claim.
    return 0 if hit_with > hit_without else 1


if __name__ == "__main__":
    raise SystemExit(run())
