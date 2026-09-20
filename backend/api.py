"""Local dev server. Same handlers the Lambda entrypoints call."""
from __future__ import annotations

import pathlib, time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from khatam.pipeline import Khatam
from khatam.ledger import EventStore, derive_state
from khatam import seed

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "ledger.jsonl"

app = FastAPI(title="Khatam", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

kh = Khatam(ROOT / "data" / "catalog.json", LEDGER)

# First run: lay down a plausible history so the velocity model has something
# to learn from. Every seeded event is tagged source="seed".
if not kh.store.all():
    kh.store.extend(seed.generate())


class Utterance(BaseModel):
    text: str

class Commit(BaseModel):
    sku_id: str
    direction: str = "out"
    quantity: float = 1.0
    raw_text: str = ""
    confidence: float = 1.0
    decided_by: str = "human"


@app.get("/api/stats")
def stats():
    return kh.stats()

@app.post("/api/interpret")
def interpret(u: Utterance):
    return kh.interpret(u.text)

@app.post("/api/commit")
def commit(c: Commit):
    return kh.commit(c.sku_id, c.direction, c.quantity, c.raw_text, c.confidence, c.decided_by)

@app.get("/api/reorder")
def reorder():
    return {"items": kh.reorder(), "dead_stock": kh.dead_stock()}

@app.get("/api/recent")
def recent(limit: int = 20):
    return {"events": kh.recent(limit)}

@app.get("/api/shelf")
def shelf(q: str = "", limit: int = 20):
    return {"rows": kh.shelf(q, limit)}

@app.post("/api/reset")
def reset():
    kh.store.clear()
    kh.store.extend(seed.generate())
    return {"ok": True, "events": len(kh.store.all())}


# Mounted last so the /api/* routes above win.
from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="ui")
