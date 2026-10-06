"""Shared type definitions for cordis-harness plugins.

These types define the contracts between plugins. Plugins agree on names and shapes,
not imports. Each consumer declares what it needs via Protocol; each provider just
has the methods.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Mapping, Protocol, Sequence, runtime_checkable


# ---------------------------------------------------------------------------
# Message & Event Types (used across agent, chat, transcript, models)
# ---------------------------------------------------------------------------

class ToolSpec(dict):
    """Tool specification for LLM function calling.

    Shape: {"name": str, "description": str, "parameters": <JSON Schema>}
    """


class ToolCall(dict):
    """A tool call from the model.

    Shape: {"id": str, "name": str, "input": Mapping}
    """


class Message(dict):
    """A conversation message.

    Shape: {
        "role": "user" | "assistant" | "tool",
        "content": str,
        "tool_calls"?: [ToolCall, ...],  # assistant only
        "call_id"?: str,                  # tool only
        "provider"?: Mapping,             # assistant: raw provider message
        "feedback"?: str,                 # user: loop feedback to model
    }
    """


class Chunk(dict):
    """A streaming chunk from a model step.

    Shapes:
        {"type": "text", "text": str}
        {"type": "thinking", "text": str}
        {"type": "tool_call", "id": str, "name": str, "input": Mapping, "error"?: str}
        {"type": "usage", "input_tokens": int, "output_tokens": int, ...}
        {"type": "stop", "reason": str}
        {"type": "message", "message": Mapping}
    """


class Event(dict):
    """An event in a reply stream (extends Chunk with shell events).

    Additional shapes beyond Chunk:
        {"type": "tool_result", "call_id": str, "content": str, "is_error": bool}
        {"type": "note", "text": str}
        {"type": "cleared"}
        {"type": "restarting", "rows": [str, ...]}
    """


# ---------------------------------------------------------------------------
# Plugin Protocols (consumer-side contracts)
# ---------------------------------------------------------------------------

@runtime_checkable
class ModelProtocol(Protocol):
    """What agent:loop needs of the model service."""

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> AsyncIterator[Chunk]: ...


@runtime_checkable
class KernelProtocol(Protocol):
    """What agent:loop needs of the kernel service."""

    @property
    def spec(self) -> ToolSpec: ...

    @property
    def confined(self) -> bool: ...

    def instructions(self) -> str: ...

    def run(self, code: str) -> str: ...


@runtime_checkable
class TranscriptProtocol(Protocol):
    """What agent:loop needs of the transcript service."""

    @property
    def messages(self) -> Sequence[Message]: ...

    def append(self, message: Message) -> None: ...


@runtime_checkable
class SystemProtocol(Protocol):
    """What agent:loop needs of the system/context service."""

    def text(self) -> str: ...


@runtime_checkable
class CommandsProtocol(Protocol):
    """What chat:session needs of the commands service."""

    def register(
        self, spec: dict | Any, run: Callable[..., Any]
    ) -> Callable[[], None]: ...

    def specs(self) -> list[Any]: ...

    async def run(self, line: str) -> Any: ...


@runtime_checkable
class LoopProtocol(Protocol):
    """What chat:session needs of the agent loop service."""

    async def reply(self, message: str) -> AsyncIterator[Event]: ...


@runtime_checkable
class InputProtocol(Protocol):
    """What chat:session needs of the input service."""

    def read(self) -> str | None: ...

    def interrupted(self) -> None: ...


@runtime_checkable
class OutputProtocol(Protocol):
    """What chat:session needs of the output service."""

    def show(self, events: AsyncIterator[Event]) -> None: ...

    def notice(self, message: str) -> None: ...

    def confirm(self, request: dict) -> bool: ...


# ---------------------------------------------------------------------------
# Recoverable Error
# ---------------------------------------------------------------------------

@runtime_checkable
class Recoverable(Protocol):
    """A failure the chat session shows to the user and recovers from."""

    @property
    def kind(self) -> str: ...

    @property
    def message(self) -> str: ...
