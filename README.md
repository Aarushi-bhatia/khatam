# Khatam

**A kirana shopkeeper says three words. A neighbourhood finds out what's on the shelf.**

Built for **First Commit** (Bharat Builds Tour × AWS), 17–20 September 2026.

**Live:** https://c61v7k71qk.execute-api.us-east-1.amazonaws.com

---

## The problem

Ask a shopkeeper to track inventory and he won't. He has run that shop for
fifteen years by feel, and every inventory app ever pushed at him has asked for
work up front in exchange for a payoff he can't see.

The pain is narrower than "inventory". It lands on **Friday, when the distributor
turns up** and asks *"kya chahiye?"* — and he has ninety seconds to reconstruct a
week from memory while walking his own aisles. Fast movers get forgotten (Maggi
ran out Tuesday; every customer who asked on Wednesday walked to the next shop).
Slow movers get re-ordered, because they're *visible* on the shelf.

Razorpay's [Fix My Itch](https://razorpay.com/m/fix-my-itch/) survey of 50,000
people ranks both halves of this:

| Rank | Itch score | Problem |
|---|---|---|
| **#24 of 141** | 83.0 | *"Why do shoppers visit stores only to find items unavailable?"* |
| **#135 of 141** | 61.5 | *"How can kirana stores predict restocking needs using past sales data?"* |

A hundred and eleven ranks apart, and they are the same problem. The shopkeeper
side scores low because kirana owners don't fill in consumer surveys — not
because it doesn't hurt.

## The insight

When the last packet of something leaves the shop, **he already says it out
loud.** *"Arre, Maggi khatam ho gaya."* To his son, to the customer, to nobody.

That utterance already exists. Khatam just gives it somewhere to land — and in
the same three seconds it produces the real-time shelf data that problem #24
says doesn't exist anywhere in India.

> He gets a reorder list that builds itself.
> The neighbourhood gets to know what's actually in stock.
> One voice note does both.

## What it does

- **Counter** — tap, say *"Maggi khatam"*, confirm. Three seconds, no typing.
- **Friday list** — everything he flagged, **plus what we predict is about to run
  out** from that shop's learned rhythm, plus the money parked in dead stock.
- **Nearby** — the shopper-facing view of the shelf, built from nothing but the
  voice log.

---

## The interesting part: repairing bad Hinglish transcription

Speech-to-text mangles Indian brand names. Real input looks like
`"do parle gee wala bada packet gaya"` — Hindi grammar, English brands, local
units (*patti*, *goli*, *dabba*, *adha kilo*).

The usual answer is a better speech model. **We didn't need one.** A kirana
stocks a few hundred products, so we let transcription be wrong and repair it
against a closed set that small:

1. Normalise both the phrase and every catalogue alias into a lossy phonetic
   space — aspirated consonants collapse (`ph→f`, `kh→k`), `v/w` and `j/z` fold
   together, repeated letters and vowel length are discarded.
2. Score against a **consonant skeleton** too, so `maggi` / `meggi` / `magi` all
   reduce to `mg` and rescue each other.
3. Rank every SKU in *this shop's* catalogue. Auto-accept on a clear winner.
4. Escalate only genuine ties to a **Strands agent** on Bedrock.

### Measured

| | |
|---|---|
| Noisy transcriptions resolved correctly | **36 / 36** (SKU, direction and quantity) |
| Auto-accepted with no model call | **32** (89%) |
| Escalated to the agent | **4** (11%) |
| Deterministic path latency | ~7 ms |

The four escalations are exactly the ones a human would hesitate on:

| Utterance | Genuine ambiguity |
|---|---|
| `chai patti khatam ho gayi` | Red Label vs Tata Tea Gold — both are *chai patti* |
| `parashoot tel khatam` | Parachute vs Dabur Amla — both are *tel* |
| `nariyal tel khatam ho gaya` | same |
| `shampoo ki patti khatam` | Clinic Plus bottle vs the 30-sachet strip |

**A smaller answer set beat a better model.** That's the whole technical thesis.

### Three bugs worth recording

- `"plus"` as a restock marker collided with the brand **Clinic Plus** — every
  mention of it registered as a delivery.
- `"aya"` (arrived) is a substring of `"gaya"` (went), so substring search
  flipped the direction of every sentence ending in *"ho gaya"*.
- Then the inverse: `"aa gaya"` **contains** `"gaya"` and the nested match starts
  *later*, so "latest marker wins" got it backwards again.

Overlapping markers now resolve to the longer span before position is
considered. See [`parse.py`](backend/khatam/parse.py).

---

## What we don't model, on purpose

There is **no `on_hand` column.** He never counts anything — he says *khatam*
when the last one leaves and *aa gaya* when the distributor drops off. Any
absolute stock number we stored would be a fiction.

What three seconds of speech can honestly buy is **rhythm**: how long a restock
of each item lasts. That's enough for a reorder list, and the shopper view says
*"last restocked 2 days ago, not reported out"* rather than inventing a count.

The velocity model recovers real cadences from the event log — seeded Maggi at
6.0 days, learned 6.51; milk 2.0 → 1.98; Red Label 12.0 → 12.55.

---

## Architecture

```
          voice (Web Speech API, hi-IN)
                    │
                    ▼
         ┌──────────────────────┐
         │  parse.py            │  direction · quantity · unit · product phrase
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │  matcher.py          │  phonetic normalise → rank this shop's SKUs
         └──────────┬───────────┘
              89% ──┴── 11%
               │        ▼
               │   ┌─────────────────────────────┐
               │   │ Strands Agent + BedrockModel │  structured output,
               │   │ (adjudicator.py)             │  constrained to candidates
               │   └─────────────┬───────────────┘
               ▼                 ▼
         ┌──────────────────────────┐
         │  ledger.py  (JSONL)      │  append-only event log
         └──────────┬───────────────┘
                    ▼
         ┌──────────────────────────┐
         │  velocity.py             │  cadence · reorder list · dead stock
         └──────────┬───────────────┘
                    ▼
            FastAPI  →  single-file PWA
```

The ledger is shaped as a DynamoDB table keyed on `(shop_id, ts#event_id)`, and
`pipeline.py` is the seam both the local server and Lambda handlers sit on — so
the Ship It path is a change of storage class, not of model.

## AWS

Deployed on **Lambda** (the same FastAPI app via Mangum) behind **API Gateway**,
with the event ledger in **DynamoDB** and the agent calling **Bedrock**. API Gateway
rather than a Lambda Function URL because this account blocks public function URLs —
and HTTPS is not optional here: the Web Speech API refuses to open a microphone on
a plain-http origin, so the core interaction would simply not work.

**AWS open source:**

- **[Strands Agents SDK](https://github.com/strands-agents/sdk-python)** — the
  adjudicator agent (`strands.Agent` + `structured_output` against a Pydantic
  schema) that settles the 11% the deterministic layer can't.
- **`strands.models.BedrockModel`** — Bedrock as the agent's model provider,
  region and model id via `AWS_REGION` / `KHATAM_BEDROCK_MODEL`.
- **boto3** — credential resolution and the Bedrock runtime session.

Without credentials on the machine the agent degrades to the top fuzzy match and
**labels itself as having done so** (`decided_by: "fallback"`), rather than
quietly pretending a model was consulted.

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn api:app --app-dir backend --port 8420 --reload
```

Open <http://localhost:8420>. Try typing:

```
maggi khatam
do parle gee wala bada packet gaya
chai patti khatam ho gayi
das maggi aa gaya
```

Tests:

```bash
python3 tests/test_matcher.py     # 36 noisy transcriptions
python3 tests/test_velocity.py    # cadence, reorder list, dead stock
```

To put the agent on real Bedrock:

```bash
export AWS_REGION=ap-south-1
export KHATAM_BEDROCK_MODEL=apac.anthropic.claude-opus-5
aws configure            # then enable model access in the Bedrock console
```

## Honesty about the demo

The 70 days of history behind the Friday list is **seeded** — a shop on day one
has no past, and the velocity model needs one. Every seeded event is tagged
`source="seed"` in the ledger and the app says so on screen. Everything you
speak or type at the counter is real, and lands in the same log.

## What Ship It would add

S3 + **Transcribe** (hi-IN) replacing browser speech · **DynamoDB** for the
ledger · **EventBridge** nightly for the velocity job · **Lambda + API Gateway**
· **Amplify Hosting** · **Cognito** per shop. Estimated ~₹0.42 per shop per
month at twenty utterances a day, scaling to zero between customers — which
matters when your user earns in hundreds.
