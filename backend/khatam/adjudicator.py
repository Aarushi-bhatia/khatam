"""The 11%: a Strands agent that settles genuinely ambiguous matches.

The deterministic matcher in `matcher.py` resolves roughly nine in ten
utterances on its own. It escalates only when two SKUs in *this shop* are
both plausible readings of what was said — "chai patti" when the shop
stocks Red Label and Tata Gold, "tel" when it stocks Parachute and Dabur
Amla.

Those are the cases a human would also hesitate on, and they are the only
ones worth a model call. Everything else never leaves the process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import BaseModel, Field

# Regional inference profile + model. Bedrock model IDs are account- and
# region-specific, so keep this overridable rather than hard-coded.
DEFAULT_MODEL_ID = os.environ.get(
    "KHATAM_BEDROCK_MODEL", "apac.anthropic.claude-opus-5"
)
DEFAULT_REGION = os.environ.get("AWS_REGION", "ap-south-1")

SYSTEM_PROMPT = """\
You disambiguate what a kirana (Indian corner shop) owner just said into \
exactly one product from HIS OWN shop's catalogue.

He speaks Hinglish — Hindi grammar, English brand names — and the speech-to-text \
that produced this phrase mangles Indian brand names badly. Treat the phrase as \
approximate. The candidate list is closed: the answer is one of them, or none.

How to choose:
- Prefer the candidate whose spoken form a Hindi speaker would actually say.
- Generic Hindi words name a category, not a brand: "tel" is any oil, "chai patti" \
is any loose tea, "sabun" is any soap. When the phrase is generic and several \
brands fit, pick the one with the higher fuzzy score only if it is clearly ahead; \
otherwise return null so we can ask him.
- Pack-size words matter: "bada"/"family" means the large pack, "chhota" the small.
- A unit word can be part of the product's identity — "shampoo ki patti" is the \
sachet strip, not the bottle.

Return null for sku_id when you genuinely cannot tell. Asking him is cheap; \
silently logging the wrong product corrupts the reorder list.
"""


class Adjudication(BaseModel):
    """Structured verdict from the agent."""

    sku_id: str | None = Field(
        description="Chosen SKU id from the candidate list, or null if unclear."
    )
    confidence: float = Field(description="0.0-1.0 confidence in the choice.")
    reason: str = Field(description="One short sentence, plain English.")


@dataclass
class AdjudicationResult:
    sku_id: str | None
    confidence: float
    reason: str
    decided_by: str          # "model" | "fallback"


class Adjudicator:
    """Lazily-built Strands agent; degrades to a deterministic choice.

    The fallback exists so the app is never blocked on cloud access — it
    takes the matcher's top candidate and says so honestly, rather than
    pretending a model was consulted.
    """

    def __init__(self, model_id: str | None = None, region: str | None = None):
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.region = region or DEFAULT_REGION
        self.provider: str | None = None     # set once a model is built
        self._agent = None
        self._unavailable_reason: str | None = None
        self._verified: bool | None = None      # None = built, never called

    @property
    def available(self) -> bool:
        return self._build() is not None and self._verified is not False

    @property
    def status(self) -> str:
        """What we can honestly claim about Bedrock right now.

        Having credentials is not the same as being able to invoke a model —
        model access is a separate console toggle, and the failure only shows
        up on the first real call. Reporting "live" before one has succeeded
        would be a badge that lies.
        """
        if self._build() is None:
            return "unavailable"
        if self._verified is True:
            return "live"
        if self._verified is False:
            return "unavailable"
        return "ready"

    def _build(self):
        if self._agent is not None:
            return self._agent
        if self._unavailable_reason:
            return None
        try:
            from strands import Agent

            from .provider import build_model

            model, label = build_model()          # Bedrock, else local Ollama
            self.provider = label
            self._agent = Agent(model=model, system_prompt=SYSTEM_PROMPT)
            return self._agent
        except Exception as exc:                      # pragma: no cover
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
            return None

    @staticmethod
    def _prompt(raw: str, phrase: str, candidates, catalogue) -> str:
        lines = []
        for c in candidates:
            sku = catalogue.by_id(c.sku_id) or {}
            aliases = ", ".join(sku.get("aliases", [])[:6])
            lines.append(
                f'- id={c.sku_id} | {c.label} | fuzzy={c.score:.2f} | said as: {aliases}'
            )
        return (
            f"Shopkeeper said: \"{raw}\"\n"
            f"Product phrase after stripping quantity and verb: \"{phrase}\"\n\n"
            f"Candidates from his catalogue:\n" + "\n".join(lines)
        )

    def adjudicate(self, raw: str, phrase: str, candidates, catalogue) -> AdjudicationResult:
        if not candidates:
            return AdjudicationResult(None, 0.0, "nothing close in this shop's catalogue", "fallback")

        agent = self._build()
        if agent is None:
            top = candidates[0]
            return AdjudicationResult(
                sku_id=top.sku_id,
                confidence=min(top.score, 0.7),
                reason=f"best fuzzy match ({self._unavailable_reason})",
                decided_by="fallback",
            )

        try:
            verdict = agent.structured_output(
                Adjudication, self._prompt(raw, phrase, candidates, catalogue)
            )
        except Exception as exc:                      # pragma: no cover
            self._verified = False
            self._unavailable_reason = type(exc).__name__
            top = candidates[0]
            return AdjudicationResult(
                sku_id=top.sku_id,
                confidence=min(top.score, 0.7),
                reason=f"model call failed ({type(exc).__name__}), used best fuzzy match",
                decided_by="fallback",
            )

        self._verified = True

        valid = {c.sku_id for c in candidates}
        if verdict.sku_id is not None and verdict.sku_id not in valid:
            # The agent is told the list is closed; if it invents an id we
            # treat it as "unclear" rather than trusting it.
            return AdjudicationResult(
                None, 0.0, "model returned an id outside the candidate list", "model"
            )

        return AdjudicationResult(
            sku_id=verdict.sku_id,
            confidence=verdict.confidence,
            reason=verdict.reason,
            decided_by="model",
        )
