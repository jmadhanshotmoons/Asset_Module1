"""Claude fallback for missing Category / Subcategory / Asset Type.

Only rows that still have a gap after the deterministic lookups are sent. Credentials are
Punctualiti's own and come from environment variables (or a local, git-ignored .env); they
are never stored in code. Two ways to reach Claude:

  * Claude API      ANTHROPIC_API_KEY
  * Amazon Bedrock  AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_REGION, + AWS_SESSION_TOKEN
                    for temporary credentials)

PUNCTUALITI_AI_PROVIDER=anthropic|bedrock forces one; otherwise the Claude API key wins if both
are set. With no credentials nothing is sent and the gaps stay red.

Models: PUNCTUALITI_AI_MODEL (Claude API, default claude-opus-5-5) and PUNCTUALITI_BEDROCK_MODEL
(Bedrock inference profile, default global.anthropic.claude-opus-4-6-v1, the most capable model
enabled on Punctualiti's AWS account as of Nov 2026; switch to global.anthropic.claude-opus-5-5
once it is enabled under Bedrock "Model access").
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

ANTHROPIC, BEDROCK = "anthropic", "bedrock"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-opus-4-6-v1"
BATCH_SIZE = 60

_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category": {"type": "string"},
                    "subcategory": {"type": "string"},
                    "asset_type": {"type": "string"},
                },
                "required": ["id", "category", "subcategory", "asset_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

_INSTRUCTIONS = """You classify facility-management assets for Punctualiti's asset master.

For each asset in `assets`, fill in category, subcategory and asset_type.
- Values the client already gave are in the input; return them unchanged.
- Reuse the client's own naming wherever it fits: `examples` shows how this client names
  categories, subcategories and asset types. Prefer an existing value over a new one.
- category is the broad discipline (e.g. Electrical, HVAC, Fire, Plumbing, Security, Housekeeping).
- subcategory is the equipment family (e.g. UPS, Fire Extinguisher, Exhaust Fan).
- asset_type is the kind of equipment, never a location or a person (e.g. UPS, ACB, Pump).
- If you cannot tell, return an empty string for that field. A blank is reviewed by a person;
  a wrong value may be uploaded by mistake.
Return one result per input id."""


@dataclass
class Suggestion:
    category: str
    subcategory: str
    asset_type: str


def provider() -> str | None:
    """Which Claude provider the current environment is set up for, or None."""
    forced = os.environ.get("PUNCTUALITI_AI_PROVIDER", "").strip().lower()
    has_api = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_aws = bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
    if forced == ANTHROPIC:
        return ANTHROPIC if has_api else None
    if forced == BEDROCK:
        return BEDROCK if has_aws else None
    if has_api:
        return ANTHROPIC
    if has_aws:
        return BEDROCK
    return None


def api_key_configured() -> bool:
    return provider() is not None


def describe() -> str:
    """Short status line for the UI / CLI (never includes secrets)."""
    p = provider()
    if p == ANTHROPIC:
        return f"Claude API ({_model(p)})"
    if p == BEDROCK:
        return f"Amazon Bedrock, {_region()} ({_model(p)})"
    return "Not set up: add a Claude API key or AWS keys to .env"


def _region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _model(p: str) -> str:
    if p == BEDROCK:
        return os.environ.get("PUNCTUALITI_BEDROCK_MODEL") or DEFAULT_BEDROCK_MODEL
    return os.environ.get("PUNCTUALITI_AI_MODEL") or DEFAULT_MODEL


def _client(p: str):
    import anthropic

    if p == BEDROCK:
        # Bedrock runtime (InvokeModel) client: it accepts the cross-region inference
        # profiles (global./us.) this account is enabled for.
        return anthropic.AnthropicBedrock(
            aws_access_key=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
            aws_region=_region(),
        )
    return anthropic.Anthropic()


def _request(client, p: str, payload: str):
    model = _model(p)
    output_config = {"format": {"type": "json_schema", "schema": _SCHEMA}}
    if "haiku-4-5" not in model:  # Haiku 4.5 rejects the effort setting
        output_config["effort"] = "low"
    params = dict(
        model=model,
        max_tokens=16000,
        output_config=output_config,
        system=_INSTRUCTIONS,
        messages=[{"role": "user", "content": payload}],
    )
    if p == ANTHROPIC:
        # Server-side refusal fallback exists on the Claude API only (not on Bedrock).
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
    return client.messages.create(**params)


class AIUnavailable(Exception):
    """Raised with a short reason the reviewer can read in the cell note."""


def classify(items: list[dict], examples: list[dict]) -> dict[str, Suggestion]:
    """items: [{id, asset_name, category, subcategory, asset_type}] with '' for missing fields."""
    if not items:
        return {}
    p = provider()
    if p is None:
        raise AIUnavailable("AI not set up (no Claude API key or AWS keys)")

    import anthropic

    client = _client(p)
    out: dict[str, Suggestion] = {}
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        payload = json.dumps({"examples": examples, "assets": batch}, ensure_ascii=False)
        try:
            response = _request(client, p, payload)
        except anthropic.AuthenticationError:
            raise AIUnavailable("Credentials were rejected (check the key in .env)")
        except anthropic.PermissionDeniedError:
            raise AIUnavailable("Credentials lack permission for this model"
                                + (" (enable it in Bedrock model access)" if p == BEDROCK else ""))
        except anthropic.NotFoundError:
            raise AIUnavailable(f"Model {_model(p)} not found" + (f" in {_region()}" if p == BEDROCK else ""))
        except anthropic.RateLimitError:
            raise AIUnavailable("Claude API rate limit reached; try again shortly")
        except anthropic.APIStatusError as e:
            raise AIUnavailable(f"Claude API error {e.status_code}")
        except anthropic.APIConnectionError:
            raise AIUnavailable("Could not reach Claude (network)")
        except Exception as e:  # e.g. botocore credential errors on Bedrock
            raise AIUnavailable(f"AI call failed ({type(e).__name__})")

        if response.stop_reason != "end_turn":
            raise AIUnavailable(f"Claude stopped early ({response.stop_reason})")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise AIUnavailable("Claude returned an unreadable answer")
        for r in data.get("results", []):
            out[str(r["id"])] = Suggestion(
                r.get("category", "").strip(), r.get("subcategory", "").strip(), r.get("asset_type", "").strip()
            )
    return out
