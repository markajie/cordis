"""Interactive chat session: input/output orchestration.

Pure business logic — no cordis imports.  The chat row reads user input,
dispatches ``/commands`` to the commands service, sends regular messages to
``loop.reply()``, and shows streamed events through an output callable.


* **Loop** — any object with ``async reply(message) -> AsyncIterator[event]``
* **Commands** — any object with ``async run(line) -> str | Sequence[event]``
* **Input / Output** — injected callables so the session is fully testable
  without a terminal.

Ctrl-C (``KeyboardInterrupt``) and EOF (``EOFError`` / ``None`` return) end
the loop gracefully.  Recoverable errors from ``loop.reply`` are displayed
and the conversation continues; anything else propagates.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

__all__ = [
    "Event",
    "Loop",
    "Commands",
    "converse",
    "is_command",
    "default_output",
]

# ---------------------------------------------------------------------------
# Contracts (Protocol types for static checking & documentation)
# ---------------------------------------------------------------------------

type Event = Mapping[str, Any]
"""One thing that happened in a turn.  Passed through unread by the chat row."""


@runtime_checkable
class Loop(Protocol):
    """What the chat row needs of the ``loop`` value."""

    def reply(self, message: str) -> AsyncIterator[Event]: ...


@runtime_checkable
class Commands(Protocol):
    """What the chat row needs of the ``commands`` value."""

    async def run(self, line: str) -> str | Sequence[Event]: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_command(line: str) -> bool:
    """Whether *line* is a slash command for the harness rather than the model.

    A valid command starts with ``/`` followed by one or more ASCII letters
    or hyphens, then whitespace or end-of-string.  This prevents pasted paths
    like ``/tmp/app.py is broken`` from being misinterpreted.
    """
    head = line.strip().split(maxsplit=1)[0] if line.strip() else ""
    return (
        len(head) > 1
        and head[0] == "/"
        and head[1].isalpha()
        and all(c.isalpha() or c == "-" for c in head[1:])
    )


def _answered(answer: str | Sequence[Event]) -> list[Event]:
    """Normalise a command answer into a list of events to display.

    A plain string becomes a single ``note`` event; an iterable of events is
    returned as-is.
    """
    if isinstance(answer, str):
        return [{"type": "note", "text": answer}]
    return list(answer)


# ---------------------------------------------------------------------------
# Default terminal output
# ---------------------------------------------------------------------------

def default_output(event: Event) -> None:
    """Render *event* to stdout in a human-readable terminal format.

    This is the fallback when no custom ``output_fn`` is supplied to
    :func:`converse`.  It handles the standard event types emitted by the
    agent loop:

    * ``text``        — streamed assistant text (printed without newline)
    * ``thinking``    — internal reasoning (suppressed by default)
    * ``tool_call``   — tool invocation summary
    * ``tool_result`` — tool output with success/error indicator
    * ``note``        — informational message
    * ``stop``        — turn boundary (emits trailing newline)
    * ``usage``       — token usage stats (suppressed by default)
    """
    event_type = event.get("type", "")

    if event_type == "text":
        print(event.get("text", ""), end="", flush=True)

    elif event_type == "thinking":
        pass  # suppressed by default

    elif event_type == "tool_call":
        name = event.get("name", "?")
        inp = event.get("input", {})
        code = inp.get("code", "")
        snippet = code[:100]
        suffix = "..." if len(code) > 100 else ""
        print(f"\n🔧 {name}({snippet}{suffix})", flush=True)

    elif event_type == "tool_result":
        content = event.get("content", "")
        is_error = event.get("is_error", False)
        prefix = "❌" if is_error else "✅"
        display = content[:500] + "..." if len(content) > 500 else content
        print(f"{prefix} {display}", flush=True)

    elif event_type == "note":
        text = event.get("text", "")
        if text:
            print(f"\n💬 {text}", flush=True)

    elif event_type == "stop":
        print("", flush=True)  # trailing newline after response

    elif event_type == "usage":
        pass  # suppressed by default


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------

async def converse(
    loop: Loop,
    commands: Commands,
    *,
    input_fn: Callable[[], str | None] | None = None,
    output_fn: Callable[[Event], None] | None = None,
) -> None:
    """Run the interactive chat loop until input is exhausted.

    Parameters
    ----------
    loop:
        Object whose ``reply(message)`` returns an async iterator of events.
    commands:
        Object whose ``run(line)`` executes a slash command and returns an
        answer (string or sequence of events).
    input_fn:
        Synchronous callable returning the next user line, or ``None`` to
        signal EOF.  Defaults to ``input()`` with a ``> `` prompt.
    output_fn:
        Callable accepting a single event dict for display.  Defaults to
        :func:`default_output`.

    Behaviour
    ---------
    * Blank lines are silently skipped.
    * Lines matching :func:`is_command` are dispatched to *commands*; the
      answer is rendered through *output_fn*.
    * All other lines are sent to ``loop.reply()``; events are streamed to
      *output_fn*.
    * ``KeyboardInterrupt`` and ``EOFError`` from *input_fn* end the loop.
    * Exceptions from ``loop.reply()`` that carry ``kind`` and ``message``
      attributes (recoverable errors) are shown and the loop continues.
    * Any other exception propagates to the caller.
    """
    if input_fn is None:
        prompt = "> " if not sys.stdin.isatty() else "\n> "
        input_fn = lambda: input(prompt)

    if output_fn is None:
        output_fn = default_output

    while True:
        # -- read next line --------------------------------------------------
        try:
            line = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if line is None:
            break

        line = line.strip()
        if not line:
            continue

        # -- command dispatch ------------------------------------------------
        if is_command(line):
            try:
                answer = await commands.run(line)
                should_quit = False
                for event in _answered(answer):
                    if event.get("type") == "quit":
                        should_quit = True
                    else:
                        output_fn(event)
                if should_quit:
                    break
            except Exception as exc:
                output_fn({"type": "note", "text": f"Command error: {exc}"})
            continue

        # -- regular message → agent loop ------------------------------------
        try:
            async for event in loop.reply(line):
                output_fn(event)
        except Exception as exc:
            # Recoverable errors (kind + message) are shown; others propagate.
            kind = getattr(exc, "kind", None)
            if kind is not None:
                message = getattr(exc, "message", str(exc))
                output_fn({"type": "note", "text": f"[{kind}] {message}"})
            else:
                raise
