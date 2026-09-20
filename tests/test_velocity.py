import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from khatam.matcher import Catalogue
from khatam.ledger import derive_state
from khatam.velocity import build_reorder_list, find_dead_stock, estimate_cadence
from khatam import seed

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAT = Catalogue.load(ROOT / "data" / "catalog.json")
NOW = time.time()
events = seed.generate(now=NOW)
states = derive_state(events)

print(f"{len(events)} events across {len(states)} SKUs\n")
print("=== FRIDAY REORDER LIST ===")
items = build_reorder_list(CAT, states, now=NOW)
for i in items:
    tag = "!" if i.reason == "flagged" else "~"
    conf = "" if i.confident else "  (low confidence)"
    print(f" {tag} {i.label:36.36s} {i.detail}{conf}")

print(f"\n  flagged: {sum(1 for i in items if i.reason=='flagged')}"
      f"   predicted: {sum(1 for i in items if i.reason=='predicted')}")

print("\n=== DEAD STOCK ===")
dead = find_dead_stock(CAT, states, now=NOW)
for d in dead:
    print(f"   {d.label:36.36s} {d.detail}")
print(f"\n  total parked: Rs {sum(d.value_parked for d in dead):,.0f}")

print("\n=== LEARNED CADENCE (sample) ===")
for sku in ["MAG-70", "AMU-TAZ", "RED-250", "BOU-500", "MAT-BOX"]:
    c = estimate_cadence(states[sku])
    print(f"   {CAT.label(CAT.by_id(sku)):34.34s} every {c.cycle_days:>5}d  "
          f"({c.observations} cycles, confident={c.confident})")
