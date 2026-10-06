"""Agent conversation loop: model consumption, turn classification, tool execution.

Pure business logic — **no cordis imports**.  The loop depends on its
collaborators exclusively through :class:`typing.Protocol` contracts so it
can be tested with fakes and reused outside the Cordis runtime.

"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Protocol, Sequence, runtime_checkable


# ---------------------------------------------------------------------------
# Dependency protocols (consumer-side contracts)
# ---------------------------------------------------------------------------


@runtime_checkable
class Model(Protocol):
    """Async streaming LLM completion interface."""

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]: ...


@runtime_checkable
class Python(Protocol):
    """Code-execution kernel contract."""

    @property
    def spec(self) -> dict[str, Any]: ...

    @property
    def confined(self) -> bool: ...

    def instructions(self) -> str: ...

    def run(self, code: str) -> str: ...


@runtime_checkable
class Transcript(Protocol):
    """Append-only conversation history."""

    @property
    def messages(self) -> Sequence[dict[str, Any]]: ...

    def append(self, message: dict[str, Any]) -> None: ...


@runtime_checkable
class System(Protocol):
    """System-prompt provider."""

    def text(self) -> str: ...


# ---------------------------------------------------------------------------
# Event types yielded by LoopModel.reply()
# ---------------------------------------------------------------------------
# Consumers iterate over these dicts; the ``type`` key discriminates:
#
#   text         – incremental model text      {"type": "text", "text": "..."}
#   thinking     – model reasoning trace       {"type": "thinking", "text": "..."}
#   tool_call    – model requested a tool      {"type": "tool_call", "id": ..., "name": ..., "input": ...}
#   tool_result  – kernel execution result     {"type": "tool_result", "call_id": ..., "content": ..., "is_error": bool}
#   usage        – token / cost stats          {"type": "usage", ...}
#   stop         – model finished              {"type": "stop", "reason": "..."}
#   note         – meta-information            {"type": "note", "text": "..."}


# ---------------------------------------------------------------------------
# Loop implementation
# ---------------------------------------------------------------------------


class LoopModel:
    """The agent loop: consumes a model, executes tools, manages transcript.

    Parameters
    ----------
    model:
        Streaming LLM backend satisfying :class:`Model`.
    kernel:
        Code-execution kernel satisfying :class:`Python`.
    transcript:
        Conversation history satisfying :class:`Transcript`.
    system:
        System-prompt provider satisfying :class:`System`.
    max_nudges:
        Maximum number of retry nudges when the model returns an empty or
        undecodable turn before giving up.
    """

    def __init__(
        self,
        model: Model,
        kernel: Python,
        transcript: Transcript,
        system: System,
        *,
        max_nudges: int = 2,
    ) -> None:
        self._model = model
        self._kernel = kernel
        self._transcript = transcript
        self._system = system
        self._max_nudges = max_nudges

    # -- public API ----------------------------------------------------------

    async def reply(self, message: str) -> AsyncIterator[dict[str, Any]]:
        """Process a user *message* and yield events until the turn is answered.

        The generator drives the full agentic cycle:

        1. Append the user message to the transcript.
        2. Build the system prompt from context + kernel instructions.
        3. Call ``model.complete(messages, [kernel.spec])``.
        4. If the model emits tool calls → execute them via ``kernel.run()``,
           append results, and loop back to step 2.
        5. If the model emits a text answer → append it and stop.
        6. If the model is silent / truncated → nudge up to *max_nudges* times.
        """
        # Append user message
        self._transcript.append({"role": "user", "content": message})
        yield {"type": "note", "text": ""}  # signal turn start

        nudge_count = 0

        while True:
            # -- build prompt ------------------------------------------------
            system_text = self._system.text()
            kernel_instructions = self._kernel.instructions()
            if kernel_instructions:
                full_system = f"{system_text}\n\n{kernel_instructions}"
            else:
                full_system = system_text

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": full_system},
            ]
            messages.extend(self._transcript.messages)

            # -- call model --------------------------------------------------
            turn_text = ""
            tool_calls: list[dict[str, Any]] = []

            try:
                async for chunk in self._model.complete(messages, [self._kernel.spec]):
                    chunk_type = chunk.get("type")

                    if chunk_type == "text":
                        turn_text += chunk.get("text", "")
                        yield chunk

                    elif chunk_type == "tool_call":
                        tool_calls.append(chunk)
                        yield chunk

                    elif chunk_type == "thinking":
                        yield chunk

                    elif chunk_type == "usage":
                        yield chunk

                    elif chunk_type == "stop":
                        yield chunk
            except Exception as model_error:
                error_msg = str(model_error)
                yield {"type": "note", "text": f"Model error: {error_msg}"}
                self._transcript.append({"role": "assistant", "content": f"[Error: {error_msg}]"})
                return

            # -- classify turn -----------------------------------------------

            if tool_calls:
                # ACT: execute every tool call, append results, continue loop
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": turn_text or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("input", {})),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                self._transcript.append(assistant_msg)

                for tc in tool_calls:
                    tool_name = tc.get("name", "")
                    call_id = tc["id"]

                    if tool_name == "python":
                        code = tc.get("input", {}).get("code", "")
                        result = self._kernel.run(code)
                        is_error = result.startswith("Error:")
                    else:
                        result = f"Unknown tool: {tool_name}"
                        is_error = True

                    yield {
                        "type": "tool_result",
                        "call_id": call_id,
                        "content": result,
                        "is_error": is_error,
                    }
                    self._transcript.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result,
                    })

                # Continue the while-loop for the next model step.

            elif turn_text.strip():
                # ANSWERED: substantive text response — done.
                self._transcript.append({"role": "assistant", "content": turn_text})
                return

            else:
                # SILENT / TRUNCATED: nudge the model to produce output.
                if nudge_count >= self._max_nudges:
                    self._transcript.append(
                        {"role": "assistant", "content": turn_text or "(no response)"}
                    )
                    yield {
                        "type": "note",
                        "text": "Model gave no usable response after retries.",
                    }
                    return

                nudge_count += 1
                feedback = (
                    "Your last response was empty or incomplete. "
                    "Please provide a substantive response or use the python tool."
                )
                self._transcript.append(
                    {"role": "user", "content": "", "feedback": feedback}
                )
