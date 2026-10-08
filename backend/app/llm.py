"""Thin wrapper around the Anthropic SDK.

Two entry points:
  * structured(): one-shot call that returns JSON validated against a Pydantic model.
  * agent_turn(): one turn of the agent loop (tools + adaptive thinking).

All calls go through the beta namespace so we can opt into server-side refusal
fallbacks (`fallbacks="default"`), which re-run a declined request on Anthropic's
recommended fallback model instead of failing.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

FALLBACK_BETA = "server-side-fallback-2026-07-01"
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the model cannot produce a usable answer."""


class LLMUnavailable(LLMError):
    """Raised when no credentials are configured or the API cannot be reached."""


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        try:
            _client = anthropic.Anthropic(max_retries=3)
        except anthropic.AnthropicError as e:  # missing credentials
            raise LLMUnavailable(str(e)) from e
    return _client


def _common_kwargs(effort: str) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "model": settings.llm_model,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort},
    }
    if settings.llm_server_fallbacks:
        kw["betas"] = [FALLBACK_BETA]
        kw["fallbacks"] = "default"
    return kw


def _call(**kwargs: Any):
    """Streamed request (long outputs never hit HTTP timeouts) with typed error mapping."""
    client = get_client()
    try:
        with client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable("Anthropic credentials are missing or invalid. Set ANTHROPIC_API_KEY.") from e
    except anthropic.PermissionDeniedError as e:
        raise LLMUnavailable(f"API key lacks permission: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Rate limited by the Anthropic API; try again shortly.") from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"Bad request to the model: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("Cannot reach the Anthropic API.") from e
    except TypeError as e:  # raised by the SDK when no credential source resolves
        raise LLMUnavailable("No Anthropic credentials found. Set ANTHROPIC_API_KEY and restart the backend.") from e

    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise LLMError(f"The model declined this request ({getattr(details, 'category', None) or 'policy'}).")
    return message


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic schema into the subset accepted by structured outputs:
    refs inlined, every property required, additionalProperties false, no defaults."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "default", "examples")}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"].keys())
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)


def structured(
    *,
    system: str,
    content: str | list[dict[str, Any]],
    output: type[T],
    effort: str | None = None,
    max_tokens: int = 32000,
    tools: list[dict[str, Any]] | None = None,
) -> T:
    kwargs = _common_kwargs(effort or settings.llm_effort_tasks)
    kwargs.update(
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={**kwargs["output_config"], "format": {"type": "json_schema", "schema": strict_schema(output)}},
    )
    if tools:
        kwargs["tools"] = tools

    message = _call(**kwargs)
    # pause_turn can happen when server tools (web search) run long; resume it.
    for _ in range(3):
        if message.stop_reason != "pause_turn":
            break
        kwargs["messages"] = [*kwargs["messages"], {"role": "assistant", "content": message.content}]
        message = _call(**kwargs)

    if message.stop_reason == "max_tokens":
        raise LLMError("Model output was truncated (max_tokens).")
    texts = [b.text for b in message.content if b.type == "text"]
    if not texts:
        raise LLMError("Model returned no text output.")
    try:
        return output.model_validate(json.loads(texts[-1]))
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("Structured output failed validation: %s", e)
        raise LLMError("Model output did not match the expected schema.") from e


def freeform(*, system: str, content: str, tools: list[dict[str, Any]] | None = None, effort: str | None = None,
             max_tokens: int = 16000):
    """Unstructured call (e.g. web research); returns the final message after resuming pause_turn."""
    kwargs = _common_kwargs(effort or settings.llm_effort_tasks)
    kwargs.update(max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}])
    if tools:
        kwargs["tools"] = tools
    message = _call(**kwargs)
    blocks = list(message.content)
    for _ in range(3):
        if message.stop_reason != "pause_turn":
            break
        kwargs["messages"] = [*kwargs["messages"], {"role": "assistant", "content": message.content}]
        message = _call(**kwargs)
        blocks += list(message.content)
    return blocks


def agent_turn(*, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int = 32000):
    kwargs = _common_kwargs(settings.llm_effort_agent)
    kwargs.update(
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=tools,
        cache_control={"type": "ephemeral"},
    )
    return _call(**kwargs)


def web_search_tool(max_uses: int = 5) -> list[dict[str, Any]]:
    if not settings.llm_enable_web_search:
        return []
    return [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}]
