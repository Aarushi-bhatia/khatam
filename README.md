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
4. Escalate only genuine ties to a **Strands agent**.

### Measured — and what the measurements are worth

| Suite | Result | What it actually proves |
|---|---|---|
| `test_matcher.py` — 36 authored phrases | **36/36** | Least of the three. I wrote both these phrases *and* the 363 catalogue aliases, so it partly measures whether the system handles the failures its author anticipated |
| `test_holdout.py` — 234 mechanical corruptions | **98.3% top-1** | Honest for spelling: corruptions derived from the canonical name, with any that an existing alias already covered discarded. But corrupting a full product title is an easier task than the real one |
| `test_vocabulary_gap.py` — 20 everyday words | **95% → 20%** with aliases stripped | The one that matters, and the one we fail |

Deterministic path latency is ~7ms, and 89% of utterances resolve without any
model call.

### The gap the numbers exposed

Nobody at a counter says "Maggi 2-Minute Noodles". They say *maggi* — and for
a great many products the spoken word shares no letters at all with the label
on the box: milk is *doodh*, soap is *sabun*, matches are *maachis*.

Strip the hand-written aliases and the matcher drops from **95% to 20%** on
exactly those words. No amount of phonetic normalisation gets from *doodh* to
"Amul Taaza Toned Milk", because that is a vocabulary problem, not a spelling
one.

So the phonetic matcher is not the clever part. **The 363 hand-written aliases
are** — and a real 500-SKU shop needs roughly 2,400 of them that nobody is
ever going to type.

### Where the model earns its place

Not in the escalation path. On the four ambiguous cases the deterministic
fallback picks correctly anyway (4/4), so on that test set deleting the agent
entirely would change no outcome — worth stating plainly rather than hiding.

It earns its place **generating the aliases**. `test_alias_generation.py` runs
the experiment: throw away the hand-written aliases for the 20 SKUs behind the
colloquial test words, regenerate them from brand + name + pack alone, and
re-score.

| Catalogue | Everyday words found |
|---|---|
| Hand-written aliases (363 of them, by me) | **19/20 — 95%** |
| No aliases at all | **4/20 — 20%** |
| **Model-generated** | **19/20 — 95%** |

**The model recovers 100% of the gap a human had filled by hand** — 20 SKUs in
3 batched calls, 12 seconds. The single word both versions miss is *kaapi*.

That is a job no lookup table can do, and it is what makes a 500-SKU catalogue
usable without anyone typing 2,400 aliases. It is also a one-time onboarding
batch, so it can be slow and cheap — which is why it batches seven products
per call rather than one.

Run it yourself: `python3 tools/generate_aliases.py --limit 10 --dry-run`

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

The velocity model recovers the cadences in the event log — seeded Maggi at
6.0 days, learned 6.51; milk 2.0 → 1.98. **This is a round-trip check, not
validation:** `seed.py` draws gaps from a Gaussian and `velocity.py` takes the
median, so recovery is arithmetic working, not evidence about real demand.
Real kirana demand is bursty, weekday-shaped and festival-shaped, and how this
estimator behaves against that is untested.

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
               │   │ Strands Agent (adjudicator) │  structured output,
               │   │ provider.py picks the model │  constrained to candidates
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
with the event ledger in **DynamoDB**. API Gateway
rather than a Lambda Function URL because this account blocks public function URLs —
and HTTPS is not optional here: the Web Speech API refuses to open a microphone on
a plain-http origin, so the core interaction would simply not work.

**AWS open source:**

- **[Strands Agents SDK](https://github.com/strands-agents/sdk-python)** — two
  agents: the alias generator that makes the catalogue usable at all, and the
  adjudicator that settles the ambiguous 11%. Both use `structured_output`
  against a Pydantic schema.
- **`strands.models.BedrockModel`** — the intended provider. This account was
  never cleared for Bedrock: every model, Anthropic *and* Amazon's own Nova,
  returns a bare `Operation not allowed`. `provider.py` therefore probes
  Bedrock with a real call and falls through to Gemini, then to a local Ollama
  model. Swapping providers is one line because Strands abstracts it — which
  is the reason the project still has a working model path.
- **boto3** — credential resolution and the Bedrock runtime probe.

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

### Which model answers

`provider.py` tries **Bedrock → Gemini → Ollama** and takes the first that
actually works. It probes Bedrock with a real call rather than trusting that
credentials resolved, because on this account they do and the invoke still
fails. The status badge in the app names whichever provider replied.

```bash
# Bedrock, if your account is cleared for it
export AWS_REGION=us-east-1
export KHATAM_BEDROCK_MODEL=us.anthropic.claude-opus-5

# or a key in .env (gitignored)
echo 'GEMINI_API_KEY=...' > .env

# or fully local
ollama pull qwen2.5:3b

# force one, skipping the chain
export KHATAM_PROVIDER=gemini
```

## Identity, and what passes for auth

There is no login, deliberately. A kirana owner will not manage a password,
and many don't use email — the only sign-in this user has ever completed is
phone-and-OTP. So the demo does the smallest honest thing: **every browser
mints its own shop id** and keeps it in localStorage. The public link is
shared; the ledgers behind it are not. Open it in two browsers and you get two
shops.

That keeps the data model genuinely per-shop (`shop_id` is the DynamoDB
partition key), so adding phone-and-OTP later changes only *where the id comes
from* — nothing below `_shop_id()` in `api.py` moves.

And if the real front door turns out to be a WhatsApp voice note, as it
probably should, there is no login at all: the number he messages from *is*
the shop.

The shopper-facing view needs no identity by design. Checking whether a nearby
shop has Maggi should never require an account.

## Known limitations

- **One shop per browser, not per person.** Clear your storage and you get a
  new shop. Fine for a demo, not for money.
- **The history is seeded.** See below.
- **A browser is the wrong front door.** Nobody types a URL twenty times a
  day. The engine doesn't care where the words arrive from; only the door
  changes.
- **Speech is browser-side** (Web Speech API), not Transcribe. That's the
  Ship It upgrade.

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
