#!/usr/bin/env python3
"""Fill in a catalogue's spoken aliases with the model.

    python3 tools/generate_aliases.py --limit 10 --dry-run
    python3 tools/generate_aliases.py --out data/catalog.generated.json

Onboarding job, not a request path: a shop hands over a product list and this
turns it into something a voice app can actually match against.
"""
from __future__ import annotations

import argparse, json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from khatam.alias_gen import aliases_for, build_agent   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(ROOT / "data" / "catalog.json"))
    ap.add_argument("--out", default=None, help="default: alongside the input, .generated.json")
    ap.add_argument("--limit", type=int, default=0, help="only the first N SKUs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cat = json.loads(pathlib.Path(args.catalog).read_text(encoding="utf-8"))
    skus = cat["skus"][: args.limit] if args.limit else cat["skus"]

    try:
        agent, provider = build_agent()
    except Exception as exc:
        print(f"no model provider reachable: {exc}", file=sys.stderr)
        return 2
    print(f"provider: {provider}\n")

    started, failures = time.time(), 0
    for i, sku in enumerate(skus, 1):
        label = f"{sku['brand']} {sku['name']} {sku['pack']}"
        try:
            generated = aliases_for(agent, sku)
        except Exception as exc:
            failures += 1
            print(f"  [{i:3d}/{len(skus)}] {label:44.44s} FAILED ({type(exc).__name__})")
            continue
        print(f"  [{i:3d}/{len(skus)}] {label:44.44s} {', '.join(generated)}")
        if not args.dry_run:
            sku["aliases"] = generated

    took = time.time() - started
    print(f"\n{len(skus) - failures}/{len(skus)} generated in {took:.0f}s "
          f"({took / max(len(skus), 1):.1f}s per SKU), {failures} failed")

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    out = pathlib.Path(args.out or args.catalog.replace(".json", ".generated.json"))
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
