"""The event log, and the shop state we can honestly derive from it.

Design note that matters: we do **not** know absolute stock levels. The
shopkeeper never counts anything — he says "khatam" when the last one leaves
and "aa gaya" when the distributor drops off. So there is no `on_hand`
column here, because any number we put in it would be a lie.

What we do know per SKU is the *rhythm*: when it was last restocked, when it
last ran out, and how long that gap usually is. That is enough to build a
reorder list, and it is the only thing three seconds of speech can buy.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path

DAY = 86_400.0


@dataclass
class Event:
    sku_id: str
    direction: str                  # "out" = left the shop | "in" = restocked
    quantity: float = 1.0
    ts: float = field(default_factory=time.time)
    source: str = "voice"           # voice | manual | seed
    raw_text: str = ""
    confidence: float = 1.0
    decided_by: str = "auto"        # auto | model | human
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(**d)


class EventStore:
    """Append-only JSONL log.

    Deliberately the same shape as a DynamoDB table keyed on
    (shop_id, ts#event_id), so swapping the backend is a change of class and
    not a change of model.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Event) -> Event:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def extend(self, events: list[Event]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")

    def all(self) -> list[Event]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(Event.from_dict(json.loads(line)))
        return sorted(out, key=lambda e: e.ts)

    def for_sku(self, sku_id: str) -> list[Event]:
        return [e for e in self.all() if e.sku_id == sku_id]

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


@dataclass
class SkuState:
    sku_id: str
    out_events: list[float] = field(default_factory=list)   # timestamps
    in_events: list[float] = field(default_factory=list)
    total_out: float = 0.0
    total_in: float = 0.0

    @property
    def last_out(self) -> float | None:
        return self.out_events[-1] if self.out_events else None

    @property
    def last_in(self) -> float | None:
        return self.in_events[-1] if self.in_events else None

    @property
    def last_touch(self) -> float | None:
        stamps = [t for t in (self.last_out, self.last_in) if t is not None]
        return max(stamps) if stamps else None


def derive_state(events: list[Event]) -> dict[str, SkuState]:
    """Fold the log into per-SKU rhythm data."""
    states: dict[str, SkuState] = {}
    for e in events:
        st = states.setdefault(e.sku_id, SkuState(sku_id=e.sku_id))
        if e.direction == "out":
            st.out_events.append(e.ts)
            st.total_out += e.quantity
        else:
            st.in_events.append(e.ts)
            st.total_in += e.quantity
    return states


class DynamoEventStore:
    """DynamoDB-backed ledger with the same interface as EventStore.

    Partition key is the shop, sort key is "<zero-padded ts>#<event id>" so a
    plain Query comes back in chronological order without a sort. The local
    JSONL store was written to this shape from the start, so swapping them is
    a constructor change and nothing else.
    """

    def __init__(self, table_name: str, shop_id: str, region: str | None = None):
        import boto3

        self.shop_id = shop_id
        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    @staticmethod
    def _sk(event: Event) -> str:
        return f"{event.ts:015.3f}#{event.event_id}"

    def append(self, event: Event) -> Event:
        item = event.to_dict()
        item["shop_id"] = self.shop_id
        item["sk"] = self._sk(event)
        item["ts"] = str(event.ts)          # Dynamo has no float type
        item["quantity"] = str(event.quantity)
        item["confidence"] = str(event.confidence)
        self.table.put_item(Item=item)
        return event

    def extend(self, events: list[Event]) -> None:
        with self.table.batch_writer() as batch:
            for e in events:
                item = e.to_dict()
                item["shop_id"] = self.shop_id
                item["sk"] = self._sk(e)
                item["ts"] = str(e.ts)
                item["quantity"] = str(e.quantity)
                item["confidence"] = str(e.confidence)
                batch.put_item(Item=item)

    def all(self) -> list[Event]:
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {"KeyConditionExpression": Key("shop_id").eq(self.shop_id)}
        while True:
            resp = self.table.query(**kwargs)
            items += resp.get("Items", [])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        out = []
        for it in items:
            out.append(Event(
                sku_id=it["sku_id"],
                direction=it["direction"],
                quantity=float(it.get("quantity", 1)),
                ts=float(it["ts"]),
                source=it.get("source", "voice"),
                raw_text=it.get("raw_text", ""),
                confidence=float(it.get("confidence", 1)),
                decided_by=it.get("decided_by", "auto"),
                event_id=it.get("event_id", ""),
            ))
        return sorted(out, key=lambda e: e.ts)

    def for_sku(self, sku_id: str) -> list[Event]:
        return [e for e in self.all() if e.sku_id == sku_id]

    def clear(self) -> None:
        from boto3.dynamodb.conditions import Key

        resp = self.table.query(
            KeyConditionExpression=Key("shop_id").eq(self.shop_id),
            ProjectionExpression="shop_id, sk",
        )
        with self.table.batch_writer() as batch:
            for it in resp.get("Items", []):
                batch.delete_item(Key={"shop_id": it["shop_id"], "sk": it["sk"]})
