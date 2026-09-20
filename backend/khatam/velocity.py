"""Learn each shop's rhythm, then build Friday's list from it.

Two things come out of here:

  * the reorder list — what he told us ran out, *plus* what we think is
    about to, based on how long a restock of that item usually lasts;
  * dead stock — things he bought that nobody has asked for since.

The second one is the one shopkeepers react to, because it is the only
number in the app they cannot see by looking at their own shelves.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, asdict

from .ledger import DAY, SkuState

# How far through its usual cycle an item must be before we put it on the
# list unprompted. 0.85 => "this normally lasts 6 days, it's been 5.1".
PREDICT_AT = 0.85

# Below this many observed cycles we show the prediction but flag it as a
# guess rather than a pattern.
CONFIDENT_AFTER = 2

# Restocked, never mentioned since, this long ago => money on a shelf.
DEAD_AFTER_DAYS = 28


@dataclass
class Cadence:
    sku_id: str
    cycle_days: float | None        # how long one restock usually lasts
    observations: int
    confident: bool

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_cadence(state: SkuState) -> Cadence:
    """Median days from a restock to the moment it runs out.

    Falls back to khatam-to-khatam spacing when we have never seen the
    restock side — common for items the distributor tops up silently.
    """
    cycles: list[float] = []

    # Preferred signal: each "in" paired with the next "out" after it.
    for in_ts in state.in_events:
        nxt = next((t for t in state.out_events if t > in_ts), None)
        if nxt is not None:
            cycles.append((nxt - in_ts) / DAY)

    # Fallback: spacing between consecutive run-outs.
    if len(cycles) < 1 and len(state.out_events) >= 2:
        cycles = [
            (b - a) / DAY
            for a, b in zip(state.out_events, state.out_events[1:])
        ]

    cycles = [c for c in cycles if c > 0.05]     # drop double-taps
    if not cycles:
        return Cadence(state.sku_id, None, 0, False)

    return Cadence(
        sku_id=state.sku_id,
        cycle_days=round(statistics.median(cycles), 2),
        observations=len(cycles),
        confident=len(cycles) >= CONFIDENT_AFTER,
    )


@dataclass
class ReorderItem:
    sku_id: str
    label: str
    reason: str                     # "flagged" | "predicted"
    detail: str                     # human sentence for the UI
    days_since_restock: float | None
    cycle_days: float | None
    confident: bool
    urgency: float                  # sort key, higher first

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeadStockItem:
    sku_id: str
    label: str
    days_idle: float
    units_in: float
    value_parked: float
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def _plural(days: float) -> str:
    n = int(round(days))
    return f"{n} day" if n == 1 else f"{n} days"


def _ago(verb: str, days: float) -> str:
    if days < 1:
        return f"{verb} today"
    if days < 2:
        return f"{verb} yesterday"
    return f"{verb} {int(days)} days ago"


def _is_currently_out(state: SkuState) -> bool:
    """He said khatam and nothing has arrived since."""
    if state.last_out is None:
        return False
    return state.last_in is None or state.last_out > state.last_in


def build_reorder_list(
    catalogue,
    states: dict[str, SkuState],
    now: float | None = None,
) -> list[ReorderItem]:
    now = now or time.time()
    items: list[ReorderItem] = []

    for sku_id, state in states.items():
        sku = catalogue.by_id(sku_id)
        if sku is None:
            continue
        label = catalogue.label(sku)
        cadence = estimate_cadence(state)
        since_restock = (now - state.last_in) / DAY if state.last_in else None

        if _is_currently_out(state):
            days_out = (now - state.last_out) / DAY
            items.append(ReorderItem(
                sku_id=sku_id,
                label=label,
                reason="flagged",
                detail=_ago("ran out", days_out),
                days_since_restock=round(since_restock, 1) if since_restock else None,
                cycle_days=cadence.cycle_days,
                confident=cadence.confident,
                urgency=100 + days_out,
            ))
            continue

        # Not flagged — do we think it's about to go?
        if cadence.cycle_days and since_restock is not None:
            progress = since_restock / cadence.cycle_days
            if progress >= PREDICT_AT:
                items.append(ReorderItem(
                    sku_id=sku_id,
                    label=label,
                    reason="predicted",
                    detail=(
                        f"usually lasts ~{_plural(cadence.cycle_days)} · "
                        + _ago("stocked", since_restock)
                    ),
                    days_since_restock=round(since_restock, 1),
                    cycle_days=cadence.cycle_days,
                    confident=cadence.confident,
                    urgency=50 * progress,
                ))

    return sorted(items, key=lambda i: -i.urgency)


def find_dead_stock(
    catalogue,
    states: dict[str, SkuState],
    now: float | None = None,
) -> list[DeadStockItem]:
    now = now or time.time()
    dead: list[DeadStockItem] = []

    for sku_id, state in states.items():
        if state.last_in is None:
            continue
        sold_since = [t for t in state.out_events if t > state.last_in]
        if sold_since:
            continue
        idle = (now - state.last_in) / DAY
        if idle < DEAD_AFTER_DAYS:
            continue
        sku = catalogue.by_id(sku_id)
        if sku is None:
            continue
        units = state.total_in
        value = units * sku.get("mrp", 0)
        dead.append(DeadStockItem(
            sku_id=sku_id,
            label=catalogue.label(sku),
            days_idle=round(idle, 1),
            units_in=units,
            value_parked=round(value, 2),
            detail=f"₹{value:,.0f} sitting {_plural(idle)}. Nobody has asked.",
        ))

    return sorted(dead, key=lambda d: -d.value_parked)
