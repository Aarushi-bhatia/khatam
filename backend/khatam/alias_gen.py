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
- the everyday Hindi word, romanised as people type it (doodh, sabun, namak, \
anda, maachis, cheeni, tel, atta, chawal)
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


def aliases_for(agent, sku: dict) -> list[str]:
    prompt = (
        f"Product: {sku['brand']} {sku['name']}\n"
        f"Pack: {sku['pack']}\n"
        f"Category: {sku['category']}\n\n"
        "List the spoken forms."
    )
    result = agent.structured_output(Aliases, prompt)
    return _clean(result.aliases)
