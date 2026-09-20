"""Which model the agents talk to, and whether one is reachable at all.

Bedrock is the intended provider. This account never got cleared for it —
every model, Anthropic and Amazon alike, returns a bare "Operation not
allowed" — so the same Strands agents fall back to a local Ollama model.
Strands makes that a one-line swap, which is the reason the project still has
a working model path at all.

Nothing above this module knows or cares which one answered.
"""

from __future__ import annotations

import os

BEDROCK_MODEL = os.environ.get("KHATAM_BEDROCK_MODEL", "us.anthropic.claude-opus-5")
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
OLLAMA_HOST = os.environ.get("KHATAM_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("KHATAM_OLLAMA_MODEL", "qwen2.5:3b")

# bedrock | ollama | auto
PREFERENCE = os.environ.get("KHATAM_PROVIDER", "auto").lower()


def _bedrock():
    import boto3

    session = boto3.Session()
    if session.get_credentials() is None:
        raise RuntimeError("no AWS credentials")

    # Building a BedrockModel succeeds whenever credentials resolve, which is
    # not the same as being allowed to invoke one — this account returns
    # "Operation not allowed" for every model, Anthropic and Amazon alike.
    # Without this probe the chain would pick Bedrock and then fail on every
    # real call instead of falling through to a provider that works.
    client = session.client("bedrock-runtime", region_name=BEDROCK_REGION)
    client.converse(
        modelId=BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": "ok"}]}],
        inferenceConfig={"maxTokens": 1},
    )

    from strands.models import BedrockModel

    return BedrockModel(model_id=BEDROCK_MODEL, region_name=BEDROCK_REGION), f"bedrock:{BEDROCK_MODEL}"


def _ollama():
    import ollama as _client

    # Fail fast if the daemon isn't up, rather than on the first agent call.
    names = [m.get("model") or m.get("name") for m in _client.Client(host=OLLAMA_HOST).list()["models"]]
    if not any((n or "").startswith(OLLAMA_MODEL.split(":")[0]) for n in names):
        raise RuntimeError(f"{OLLAMA_MODEL} not pulled (have: {names})")
    from strands.models.ollama import OllamaModel

    return OllamaModel(host=OLLAMA_HOST, model_id=OLLAMA_MODEL), f"ollama:{OLLAMA_MODEL}"


def build_model():
    """Return (model, label) for the first provider that actually works.

    Raises RuntimeError with every attempt's reason if none do — callers
    degrade gracefully rather than crash, but they get told why.
    """
    order = {"bedrock": [_bedrock], "ollama": [_ollama]}.get(PREFERENCE, [_bedrock, _ollama])
    problems = []
    for make in order:
        try:
            return make()
        except Exception as exc:
            problems.append(f"{make.__name__.strip('_')}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(problems))
