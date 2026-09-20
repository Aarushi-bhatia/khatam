"""One utterance in, one ledger entry out — and everything the UI reads.

This is the seam the Lambda handlers and the local dev server both sit on,
so the deployed and local paths run identical logic.
"""

from __future__ import annotations

import time
from pathlib import Path

from .adjudicator import Adjudicator
from .ledger import DAY, Event, EventStore, derive_state
from .matcher import Catalogue
from .parse import parse_utterance
from .velocity import build_reorder_list, estimate_cadence, find_dead_stock


class Khatam:
    def __init__(
        self,
        catalogue_path: str | Path,
        ledger_path: str | Path,
        adjudicator: Adjudicator | None = None,
    ):
        self.catalogue = Catalogue.load(catalogue_path)
        self.store = EventStore(ledger_path)
        self.adjudicator = adjudicator or Adjudicator()

    # -- write path -------------------------------------------------------

    def interpret(self, raw_text: str) -> dict:
        """Resolve an utterance without committing it.

        The UI calls this first so the shopkeeper sees what we heard and can
        correct it before anything lands in the ledger.
        """
        started = time.perf_counter()
        utt = parse_utterance(raw_text)
        match = self.catalogue.match(utt.product_phrase)

        decided_by = "auto"
        reason = "matched directly against this shop's catalogue"
        chosen = match.top.sku_id if match.top else None
        confidence = match.top.score if match.top else 0.0

        if match.decision == "model":
            verdict = self.adjudicator.adjudicate(
                raw_text, utt.product_phrase, match.candidates, self.catalogue
            )
            chosen = verdict.sku_id
            confidence = verdict.confidence
            reason = verdict.reason
            decided_by = verdict.decided_by
        elif match.decision == "unknown":
            chosen, confidence = None, 0.0
            reason = "nothing in this shop's catalogue sounds like that"
            decided_by = "none"

        sku = self.catalogue.by_id(chosen) if chosen else None
        return {
            "raw_text": raw_text,
            "heard_as": utt.product_phrase,
            "direction": utt.direction,
            "quantity": utt.quantity,
            "quantity_explicit": utt.quantity_explicit,
            "unit": utt.unit,
            "sku_id": chosen,
            "label": self.catalogue.label(sku) if sku else None,
            "confidence": round(confidence, 3),
            "decided_by": decided_by,
            "reason": reason,
            "needs_confirmation": decided_by != "auto" or chosen is None,
            "candidates": [c.to_dict() for c in match.candidates],
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def commit(
        self,
        sku_id: str,
        direction: str,
        quantity: float = 1.0,
        raw_text: str = "",
        confidence: float = 1.0,
        decided_by: str = "human",
    ) -> dict:
        event = self.store.append(Event(
            sku_id=sku_id,
            direction=direction,
            quantity=quantity,
            raw_text=raw_text,
            confidence=confidence,
            decided_by=decided_by,
        ))
        return event.to_dict()

    # -- read path --------------------------------------------------------

    def _states(self):
        return derive_state(self.store.all())

    def reorder(self) -> list[dict]:
        return [i.to_dict() for i in build_reorder_list(self.catalogue, self._states())]

    def dead_stock(self) -> list[dict]:
        return [d.to_dict() for d in find_dead_stock(self.catalogue, self._states())]

    def recent(self, limit: int = 20) -> list[dict]:
        events = [e for e in self.store.all() if e.source == "voice"]
        out = []
        for e in reversed(events[-limit:]):
            sku = self.catalogue.by_id(e.sku_id)
            d = e.to_dict()
            d["label"] = self.catalogue.label(sku) if sku else e.sku_id
            out.append(d)
        return out

    def shelf(self, query: str = "", limit: int = 20) -> list[dict]:
        """The shopper-facing view: what this shop has, and how fresh we think it is.

        We never claim a count. We say when it was last restocked and whether
        he has since told us it ran out — which is all the voice log knows,
        and all a shopper actually needs before walking over.
        """
        states = self._states()
        now = time.time()
        rows = []

        for sku in self.catalogue.skus:
            st = states.get(sku["id"])
            if st is None or st.last_in is None:
                continue
            out_since = [t for t in st.out_events if t > st.last_in]
            in_stock = not out_since
            updated = (now - (st.last_touch or st.last_in)) / DAY
            cadence = estimate_cadence(st)
            rows.append({
                "sku_id": sku["id"],
                "label": self.catalogue.label(sku),
                "category": sku["category"],
                "mrp": sku["mrp"],
                "in_stock": in_stock,
                "updated_days_ago": round(updated, 2),
                "cycle_days": cadence.cycle_days,
            })

        if query:
            ranked = {c.sku_id: c.score for c in self.catalogue.rank(query, limit=limit)}
            rows = [r for r in rows if r["sku_id"] in ranked]
            rows.sort(key=lambda r: -ranked[r["sku_id"]])
        else:
            rows.sort(key=lambda r: (not r["in_stock"], r["updated_days_ago"]))

        return rows[:limit]

    def stats(self) -> dict:
        events = self.store.all()
        voice = [e for e in events if e.source == "voice"]
        by_model = sum(1 for e in voice if e.decided_by == "model")
        return {
            "shop_name": self.catalogue.shop_name,
            "sku_count": len(self.catalogue),
            "events_total": len(events),
            "events_voice": len(voice),
            "escalated_to_model": by_model,
            "escalation_rate": round(by_model / len(voice), 3) if voice else 0.0,
            "adjudicator": self.adjudicator.status,
            "provider": self.adjudicator.provider,
        }
