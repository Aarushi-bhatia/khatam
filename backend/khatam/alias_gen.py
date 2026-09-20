"""Generate the words a shopkeeper actually uses for a product.

This is the job that earns the model its place. `test_vocabulary_gap.py`
measures the problem: strip the hand-written aliases and the matcher drops
from 95% to 20% on everyday words, because no amount of phonetic
normalisation gets from "doodh" to "Amul Taaza Toned Milk". That is a
vocabulary gap, not a spelling one.

Those aliases exist today because a human typed 363 of them. A 500-SKU shop
needs roughly 2,400 and will never get them that way. A language model given
"Amul Taaza Toned Milk 500ml" produces "doodh, milk, amul milk, taza" in one
call — which is a thing no lookup table can do, and the reason this is the
model's job rather than the matcher's.

It is also a batch job, run once at onboarding, so it can be slow and cheap.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SYSTEM_PROMPT = """\
You list the words an Indian kirana (corner shop) owner actually says out loud \
for a product, so a voice app can recognise them.

Give the spoken forms, not the label on the box. Include:
- the bare everyday Hindi word ON ITS OWN, romanised as people type it: just \
"doodh", not "amul doodh"; just "sabun", not "lifebuoy sabun". This one matters \
most — a customer asks for the generic thing, not the brand. Always include it \
as a standalone entry when one exists (doodh, sabun, namak, anda, maachis, \
cheeni, tel, atta, chawal, chai patti, makhan, dahi, haldi, mirchi, pani)
- the short brand name people really use ("parle g", not "Parle-G Biscuit \
50g"; "lays", not "Lays Magic Masala Chips")
- common misspellings speech-to-text produces on Indian English (colget, \
kurkuray, sarf, parashoot, meggi)
- a pack-size word only when the shop stocks more than one size ("bada", \
"chhota")

Rules:
- lowercase, no punctuation beyond single spaces
- 4 to 8 entries, most common first
- no duplicates, nothing longer than three words
- do NOT include the full product title, and do NOT invent brands
"""


class Aliases(BaseModel):
    aliases: list[str] = Field(
        description="Spoken forms, lowercase, most common first, 4-8 entries."
    )


class SkuAliases(BaseModel):
    sku_id: str = Field(description="The id exactly as given in the input.")
    aliases: list[str] = Field(description="4-8 spoken forms, most common first.")


class AliasBatch(BaseModel):
    items: list[SkuAliases] = Field(description="One entry per product, all of them.")


def _clean(raw: list[str], limit: int = 8) -> list[str]:
    out, seen = [], set()
    for a in raw:
        a = " ".join(str(a).lower().split())
        if not a or len(a.split()) > 3 or a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out[:limit]


def build_agent():
    """(agent, provider_label). Raises if no provider is reachable."""
    from strands import Agent

    from .provider import build_model

    model, label = build_model()
    return Agent(model=model, system_prompt=SYSTEM_PROMPT), label


def aliases_for(agent, sku: dict, attempts: int = 4) -> list[str]:
    prompt = (
        f"Product: {sku['brand']} {sku['name']}\n"
        f"Pack: {sku['pack']}\n"
        f"Category: {sku['category']}\n\n"
        "List the spoken forms."
    )
    # Gemini's free tier 503s under load often enough that one attempt is not
    # enough for a 78-SKU batch.
    import time

    last = None
    for i in range(attempts):
        try:
            return _clean(agent.structured_output(Aliases, prompt).aliases)
        except Exception as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise last


def aliases_for_batch(agent, skus: list[dict], attempts: int = 5) -> dict[str, list[str]]:
    """Aliases for many products in one call.

    Per-product calls exhaust a free-tier quota almost immediately — and this
    is an onboarding batch job, not a request path, so there is no reason to
    make one call per SKU. Ten products per call turns a 78-SKU catalogue into
    eight requests.
    """
    import time

    lines = [
        f"{s['id']} | {s['brand']} {s['name']} | pack {s['pack']} | {s['category']}"
        for s in skus
    ]
    prompt = (
        "For EACH product below, list the spoken forms. Return one entry per "
        "product, using the id exactly as given.\n\n" + "\n".join(lines)
    )

    last = None
    for i in range(attempts):
        try:
            batch = agent.structured_output(AliasBatch, prompt)
            return {
                item.sku_id: _clean(item.aliases)
                for item in batch.items
                if item.sku_id in {s["id"] for s in skus}
            }
        except Exception as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(5 * (i + 1))      # 429s need real backoff, not 1s
    raise last
