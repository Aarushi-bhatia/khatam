"""Local dev server and Lambda entrypoint — the same handlers either way."""
from __future__ import annotations

import copy
import os
import pathlib
import re

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from khatam import seed
from khatam.ledger import EventStore, SeededStore
from khatam.pipeline import Khatam

# Locally api.py lives in backend/, so the project root is one level up. In
# Lambda everything is flattened into /var/task, so the root is api.py's own
# directory. Detect rather than assume.
_HERE = pathlib.Path(__file__).resolve().parent
ROOT = _HERE if (_HERE / "data").is_dir() else _HERE.parent
IN_LAMBDA = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

CATALOG = ROOT / "data" / "catalog.json"
TABLE = os.environ.get("KHATAM_TABLE")          # set => DynamoDB, unset => local files
LOCAL_DIR = (pathlib.Path("/tmp") if IN_LAMBDA else ROOT / "data") / "shops"

app = FastAPI(title="Khatam", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], expose_headers=["*"],
)

# Catalogue parsing and the Strands agent are the expensive parts, so build
# one base instance and clone it per request with that shop's own store.
_base = Khatam(CATALOG, LOCAL_DIR / "unused.jsonl")
_SEED = seed.generate()

DEMO_SHOP = "demo"
_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _shop_id(header: str | None) -> str:
    """Anyone with the link gets their own shop, not a shared one.

    The id is minted in the browser and kept in localStorage — no account, no
    login. Swapping that for phone-and-OTP later changes only where the id
    comes from, not anything below this line.
    """
    return header if header and _SAFE.match(header) else DEMO_SHOP


def _for_shop(shop_id: str) -> Khatam:
    kh = copy.copy(_base)            # shares catalogue + adjudicator
    if TABLE:
        from khatam.ledger import DynamoEventStore
        inner = DynamoEventStore(TABLE, shop_id, region=os.environ.get("AWS_REGION"))
    else:
        inner = EventStore(LOCAL_DIR / f"{shop_id}.jsonl")
    kh.store = SeededStore(inner, _SEED)
    return kh


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
def stats(x_shop_id: str | None = Header(default=None)):
    kh = _for_shop(_shop_id(x_shop_id))
    out = kh.stats()
    out["shop_ref"] = _shop_id(x_shop_id)
    return out


@app.post("/api/interpret")
def interpret(u: Utterance, x_shop_id: str | None = Header(default=None)):
    return _for_shop(_shop_id(x_shop_id)).interpret(u.text)


@app.post("/api/commit")
def commit(c: Commit, x_shop_id: str | None = Header(default=None)):
    kh = _for_shop(_shop_id(x_shop_id))
    return kh.commit(c.sku_id, c.direction, c.quantity, c.raw_text,
                     c.confidence, c.decided_by)


@app.get("/api/reorder")
def reorder(x_shop_id: str | None = Header(default=None)):
    kh = _for_shop(_shop_id(x_shop_id))
    return {"items": kh.reorder(), "dead_stock": kh.dead_stock()}


@app.get("/api/recent")
def recent(limit: int = 20, x_shop_id: str | None = Header(default=None)):
    return {"events": _for_shop(_shop_id(x_shop_id)).recent(limit)}


@app.get("/api/shelf")
def shelf(q: str = "", limit: int = 20, x_shop_id: str | None = Header(default=None)):
    return {"rows": _for_shop(_shop_id(x_shop_id)).shelf(q, limit)}


@app.post("/api/reset")
def reset(x_shop_id: str | None = Header(default=None)):
    kh = _for_shop(_shop_id(x_shop_id))
    kh.store.clear()                 # only this shop's own events
    return {"ok": True}


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
