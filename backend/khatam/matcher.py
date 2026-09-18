"""Match a spoken product phrase to a SKU in *this shop's* catalogue.

The whole idea: a general speech model has to pick from every word in the
language, but a kirana has a few hundred products. Scoring a mangled phrase
against a closed set that small turns a hard ASR problem into an easy
ranking problem — and the language model only has to adjudicate the cases
where ranking is genuinely ambiguous.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

from .normalize import skeleton, squash, tokens

# Confidence gates. Tuned in tests/test_matcher.py — if you move these,
# run the suite and look at what falls through to the model.
AUTO_ACCEPT = 0.82      # take the top candidate without asking anyone
NEEDS_MODEL = 0.55      # below the gate but plausible -> ask Bedrock
MIN_MARGIN = 0.08       # top must beat runner-up by this to auto-accept

_SIZE_UP = {"bada", "bara", "big", "large", "family", "jumbo", "badi"}
_SIZE_DOWN = {"chhota", "chota", "small", "mini", "chhoti", "choti"}


@dataclass
class Candidate:
    sku_id: str
    label: str
    score: float
    matched_alias: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchResult:
    phrase: str
    candidates: list[Candidate]
    decision: str                # "auto" | "model" | "confirm" | "unknown"
    top: Candidate | None = None

    @property
    def needs_model(self) -> bool:
        return self.decision == "model"


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


class Catalogue:
    def __init__(self, payload: dict):
        self.shop_id = payload.get("shop_id", "unknown")
        self.shop_name = payload.get("shop_name", "")
        self.skus = payload["skus"]
        self._index: list[tuple[dict, str, str, str]] = []
        for sku in self.skus:
            surfaces = set(sku.get("aliases", []))
            surfaces.add(f"{sku['brand']} {sku['name']}")
            surfaces.add(sku["name"])
            for surface in surfaces:
                self._index.append((sku, surface, squash(surface), skeleton(surface)))

    @classmethod
    def load(cls, path: str | Path) -> "Catalogue":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def __len__(self) -> int:
        return len(self.skus)

    def label(self, sku: dict) -> str:
        return f"{sku['brand']} {sku['name']} {sku['pack']}".strip()

    def by_id(self, sku_id: str) -> dict | None:
        return next((s for s in self.skus if s["id"] == sku_id), None)

    # -- scoring ----------------------------------------------------------

    def _surface_score(self, phrase: str, surface: str, sq: str, sk: str) -> float:
        p_sq, p_sk = squash(phrase), skeleton(phrase)
        if not p_sq:
            return 0.0

        vowel_level = _ratio(p_sq, sq)
        consonant_level = _ratio(p_sk, sk) if p_sk and sk else vowel_level
        score = 0.62 * vowel_level + 0.38 * consonant_level

        # Whole-alias containment is a strong signal: "do parle g wala bada"
        # contains "parle g" outright.
        if sq and sq in p_sq:
            score = max(score, 0.80 + 0.15 * (len(sq) / max(len(p_sq), 1)))

        # Shared word tokens (helps multi-word aliases).
        p_tokens, s_tokens = set(tokens(phrase)), set(tokens(surface))
        if p_tokens and s_tokens:
            overlap = len(p_tokens & s_tokens) / len(s_tokens)
            score += 0.10 * overlap

        return min(score, 1.0)

    def _size_adjust(self, phrase: str, sku: dict, score: float) -> float:
        """Nudge between pack variants of the same product."""
        words = set(tokens(phrase))
        pack = sku["pack"].lower()
        pack_numbers = _numbers(pack)
        said_numbers = _numbers(phrase)

        if said_numbers and pack_numbers:
            if said_numbers & pack_numbers:
                score += 0.12
            else:
                score -= 0.06

        is_big = any(k in pack for k in ("family", "kg", "pack")) or any(
            n for n in pack_numbers if n.isdigit() and int(n) >= 200
        )
        if words & _SIZE_UP:
            score += 0.09 if is_big else -0.09
        if words & _SIZE_DOWN:
            score += -0.09 if is_big else 0.09

        return max(0.0, min(score, 1.0))

    def rank(self, phrase: str, limit: int = 5) -> list[Candidate]:
        best_per_sku: dict[str, Candidate] = {}
        for sku, surface, sq, sk in self._index:
            raw = self._surface_score(phrase, surface, sq, sk)
            adjusted = self._size_adjust(phrase, sku, raw)
            existing = best_per_sku.get(sku["id"])
            if existing is None or adjusted > existing.score:
                best_per_sku[sku["id"]] = Candidate(
                    sku_id=sku["id"],
                    label=self.label(sku),
                    score=round(adjusted, 4),
                    matched_alias=surface,
                )
        ranked = sorted(best_per_sku.values(), key=lambda c: -c.score)
        return ranked[:limit]

    def match(self, phrase: str, limit: int = 5) -> MatchResult:
        ranked = self.rank(phrase, limit=limit)
        if not ranked or ranked[0].score < NEEDS_MODEL:
            return MatchResult(phrase, ranked, "unknown", ranked[0] if ranked else None)

        top = ranked[0]
        runner_up = ranked[1].score if len(ranked) > 1 else 0.0
        margin = top.score - runner_up

        if top.score >= AUTO_ACCEPT and margin >= MIN_MARGIN:
            return MatchResult(phrase, ranked, "auto", top)
        return MatchResult(phrase, ranked, "model", top)
