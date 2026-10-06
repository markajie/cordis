"""OpenAI-compatible LLM client with streaming support.

Pure business logic — no cordis imports. Works with any OpenAI-compatible
/chat/completions endpoint (OpenAI, OpenRouter, Groq, Ollama /v1, etc.).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator


class OpenAIModel:
    """OpenAI-compatible chat completion client.

    Streams chunks as dicts with a ``type`` key:

    * ``{"type": "text", "text": "..."}``
    * ``{"type": "tool_call", "id": "...", "name": "...", "input": {...}}``
    * ``{"type": "stop", "reason": "end_turn" | "tool_calls" | ...}``
    """

    def __init__(self, model_id: str, base_url: str, api_key: str | None = None):
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def complete(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        """Stream chat completion chunks from the provider."""
        import httpx

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]

        url = f"{self._base_url}/chat/completions"

        # Accumulate tool calls across streaming deltas
        pending_tool_calls: dict[int, dict[str, Any]] = {}

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", url, json=body, headers=headers
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    raise RuntimeError(
                        f"Model '{self._model_id}' returned HTTP {response.status_code}: "
                        f"{response.text[:500]}"
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        for tc in pending_tool_calls.values():
                            yield _finalize_tool_call(tc)
                        yield {"type": "stop", "reason": "end_turn"}
                        return

                    chunk = json.loads(data)

                    choices = chunk.get("choices")
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})

                    # Text content
                    content = delta.get("content")
                    if content:
                        yield {"type": "text", "text": content}

                    # Tool calls (arrive incrementally — accumulate by index)
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        for tc_delta in tool_calls:
                            idx = tc_delta.get("index", 0)
                            if idx not in pending_tool_calls:
                                pending_tool_calls[idx] = {
                                    "id": tc_delta.get("id", ""),
                                    "name": tc_delta.get("function", {}).get("name", ""),
                                    "args_parts": [],
                                }
                            entry = pending_tool_calls[idx]
                            if tc_delta.get("id"):
                                entry["id"] = tc_delta["id"]
                            func = tc_delta.get("function", {})
                            if func.get("name"):
                                entry["name"] = func["name"]
                            args_str = func.get("arguments", "")
                            if args_str:
                                entry["args_parts"].append(args_str)

                    # Finish reason
                    finish = choice.get("finish_reason")
                    if finish:
                        for tc in pending_tool_calls.values():
                            yield _finalize_tool_call(tc)
                        yield {"type": "stop", "reason": finish}
                        return


def _finalize_tool_call(entry: dict[str, Any]) -> dict[str, Any]:
    """Parse accumulated tool call arguments into a finalized tool_call event."""
    args_raw = "".join(entry.get("args_parts", []))
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError:
        args = {"_raw": args_raw, "_parse_error": True}

    return {
        "type": "tool_call",
        "id": entry.get("id", "call_unknown"),
        "name": entry.get("name", ""),
        "input": args,
    }


class UnusableModel:
    """A model that cannot be used; every call raises a descriptive error.

    Used when configuration is missing or invalid so the service still binds
    and the caller gets an actionable message instead of an import-time crash.
    """

    def __init__(self, name: str, problem: str):
        self._name = name
        self._problem = problem

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[dict]:
        """Raise on first iteration so ``async for`` callers get a clear error.

        The unreachable ``yield`` makes this an async generator (matching
        :meth:`OpenAIModel.complete`'s return type).  Without it the method
        would return a plain coroutine instead of an async iterator.
        """
        raise RuntimeError(
            f"Model '{self._name}' is unavailable: {self._problem}"
        )
        yield  # noqa: E501 — unreachable; required for async-generator typing
