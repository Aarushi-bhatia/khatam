"""Generate a plausible history so the velocity model has something to learn.

This exists because a demo on day one has no past. Every event written here
is tagged `source="seed"`, and the UI labels any shop built from it, so the
seeded data is never passed off as real usage.
"""

from __future__ import annotations

import random
import time

from .ledger import DAY, Event

# sku_id -> (cycle_days, jitter_days)
# Cycles are what a north-Indian kirana actually looks like: Maggi and milk
# turn over in under a week, hair oil and Bournvita take a month.
RHYTHMS: dict[str, tuple[float, float]] = {
    "MAG-70":   (6.0, 1.2),
    "PAR-G50":  (4.0, 0.8),
    "PAR-G250": (9.0, 1.5),
    "AMU-TAZ":  (2.0, 0.4),
    "BRD-400":  (3.0, 0.6),
    "EGG-TRY":  (3.5, 0.7),
    "LAY-MAG":  (5.0, 1.0),
    "KUR-MAS":  (6.5, 1.2),
    "RED-250":  (12.0, 2.0),
    "TAT-SLT":  (16.0, 3.0),
    "SUR-1K":   (11.0, 2.0),
    "COL-100":  (14.0, 2.5),
    "LIF-BAR":  (8.0, 1.5),
    "BIS-750":  (2.5, 0.5),
    "THU-750":  (7.0, 1.4),
    "DAI-MLK":  (5.5, 1.0),
    "AMU-BUT":  (9.0, 1.8),
    "VIM-BAR":  (10.0, 2.0),
    "MAT-BOX":  (20.0, 4.0),
    "GOO-KNT":  (18.0, 3.5),
    "CLI-SHM":  (15.0, 3.0),
    "BOU-500":  (26.0, 4.0),
    "HAL-BHU":  (8.5, 1.6),
    "FOR-OIL":  (13.0, 2.5),
    "MAG-KET":  (22.0, 4.0),
}

# Restocked once and never mentioned again — this is the dead-stock demo.
PARKED: dict[str, tuple[float, float]] = {
    # sku_id: (days_ago_restocked, units)
    "DAB-AML": (35.0, 20.0),
    "NIV-CRM": (41.0, 6.0),
    "JOH-POW": (52.0, 4.0),
}

# Said "khatam" today and not yet restocked — the flagged rows.
FLAGGED_TODAY = ["MAG-70", "AMU-TAZ", "LAY-MAG"]

HISTORY_DAYS = 70


def generate(now: float | None = None, rng_seed: int = 20260920) -> list[Event]:
    now = now or time.time()
    rng = random.Random(rng_seed)
    events: list[Event] = []

    for sku_id, (cycle, jitter) in RHYTHMS.items():
        t = now - HISTORY_DAYS * DAY
        while t < now:
            events.append(Event(
                sku_id=sku_id, direction="in", quantity=rng.randint(6, 24),
                ts=t, source="seed", raw_text="stock aaya",
            ))
            span = max(0.5, rng.gauss(cycle, jitter))
            t_out = t + span * DAY
            if t_out >= now:
                break
            events.append(Event(
                sku_id=sku_id, direction="out", quantity=1,
                ts=t_out, source="seed", raw_text="khatam",
            ))
            # Distributor turns up a day or two after it runs out.
            t = t_out + max(0.2, rng.gauss(1.2, 0.5)) * DAY

    for sku_id, (days_ago, units) in PARKED.items():
        events.append(Event(
            sku_id=sku_id, direction="in", quantity=units,
            ts=now - days_ago * DAY, source="seed", raw_text="stock aaya",
        ))

    for sku_id in FLAGGED_TODAY:
        events.append(Event(
            sku_id=sku_id, direction="out", quantity=1,
            ts=now - rng.uniform(0.1, 0.6) * DAY,
            source="seed", raw_text="khatam",
        ))

    return sorted(events, key=lambda e: e.ts)
