"""Does the model actually close the vocabulary gap? Measure it.

The claim being tested: the 363 hand-written aliases are load-bearing (proved
in test_vocabulary_gap.py — 95% drops to 20% without them), and a language
model can produce them instead of a human.

The experiment:
  1. take the SKUs behind the colloquial test words
  2. throw their hand-written aliases away
  3. ask the model to generate replacements from brand + name + pack alone
  4. re-run the same colloquial lookups against the regenerated catalogue

If the recovered score approaches the hand-written one, the model has done a
job no lookup table can do, and the escalation path is no longer the only
thing it is there for. If it doesn't, we say so.

Needs a reachable provider (Bedrock, or Ollama locally). Skips loudly rather
than failing when there isn't one, so the suite still runs on a bare machine.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # tests_support

from khatam.matcher import Catalogue                    # noqa: E402
from tests_support import COLLOQUIAL                    # noqa: E402  (see below)

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))


def _score(cat: Catalogue) -> tuple[int, list[str]]:
    hits, missed = 0, []
    for phrase, want in COLLOQUIAL:
        ranked = cat.rank(phrase, limit=1)
        if ranked and ranked[0].sku_id == want:
            hits += 1
        else:
            missed.append(phrase)
    return hits, missed


def run() -> int:
    from khatam.alias_gen import aliases_for, build_agent

    try:
        agent, provider = build_agent()
    except Exception as exc:
        print(f"SKIPPED — no model provider reachable ({exc})")
        return 0

    targets = {sku_id for _, sku_id in COLLOQUIAL}
    print(f"provider: {provider}")
    print(f"regenerating aliases for the {len(targets)} SKUs behind "
          f"{len(COLLOQUIAL)} everyday words\n")

    hand = Catalogue(RAW)
    hand_hits, _ = _score(hand)

    stripped = json.loads(json.dumps(RAW))
    for sku in stripped["skus"]:
        sku["aliases"] = []
    bare_hits, _ = _score(Catalogue(stripped))

    generated = json.loads(json.dumps(stripped))
    started, failures = time.time(), 0
    for sku in generated["skus"]:
        if sku["id"] not in targets:
            continue
        try:
            sku["aliases"] = aliases_for(agent, sku)
            print(f"  {sku['brand']} {sku['name']:<26.26s} -> {', '.join(sku['aliases'])}")
        except Exception as exc:
            failures += 1
            print(f"  {sku['brand']} {sku['name']:<26.26s} -> FAILED {type(exc).__name__}")
    took = time.time() - started

    gen_hits, gen_missed = _score(Catalogue(generated))
    n = len(COLLOQUIAL)

    print(f"\n  hand-written aliases   {hand_hits:2d}/{n}  {hand_hits/n:5.0%}")
    print(f"  no aliases at all      {bare_hits:2d}/{n}  {bare_hits/n:5.0%}")
    print(f"  model-generated        {gen_hits:2d}/{n}  {gen_hits/n:5.0%}"
          f"   ({took:.0f}s, {failures} failures)")
    if gen_missed:
        print(f"  still missed: {', '.join(gen_missed)}")

    recovered = (gen_hits - bare_hits) / max(hand_hits - bare_hits, 1)
    print(f"\n  => the model recovered {recovered:.0%} of the gap a human had filled by hand")

    # Gate: the model must beat a bare catalogue by a clear margin, or the
    # claim that it is doing real work here is not supported.
    return 0 if gen_hits > bare_hits + (hand_hits - bare_hits) * 0.4 else 1


if __name__ == "__main__":
    raise SystemExit(run())
