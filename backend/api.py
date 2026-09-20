"""Local dev server. Same handlers the Lambda entrypoints call."""
from __future__ import annotations

import os, pathlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from khatam.pipeline import Khatam
from khatam.ledger import EventStore, derive_state
from khatam import seed

# Locally api.py lives in backend/, so the project root is one level up.
# In Lambda everything is flattened into /var/task, so the root is api.py's
# own directory. Detect rather than assume.
_HERE = pathlib.Path(__file__).resolve().parent
ROOT = _HERE if (_HERE / "data").is_dir() else _HERE.parent

# /var/task is read-only; only /tmp is writable. Irrelevant when KHATAM_TABLE
# is set (DynamoDB), but the local store is still constructed first.
LEDGER = (pathlib.Path("/tmp") if os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
          else ROOT / "data") / "ledger.jsonl"

app = FastAPI(title="Khatam", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

CATALOG = ROOT / "data" / "catalog.json"
TABLE = os.environ.get("KHATAM_TABLE")          # set => DynamoDB, unset => local file

kh = Khatam(CATALOG, LEDGER)
if TABLE:
    from khatam.ledger import DynamoEventStore
    kh.store = DynamoEventStore(TABLE, kh.catalogue.shop_id,
                                region=os.environ.get("AWS_REGION"))

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


# --- Lambda entrypoint ----------------------------------------------------
# Mangum adapts the same ASGI app to Lambda's event shape, so the deployed
# path runs byte-identical handler code to `uvicorn api:app` locally.
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:      # local dev without mangum installed
    handler = None
