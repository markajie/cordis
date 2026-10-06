"""Commands plugin wiring — broker + built-in operator commands.

The ``commands`` service is the slash-command broker (registry.py).
This module also registers the built-in operator commands (/quit, /help)
 contributes to ``commands:registry``.
"""

from __future__ import annotations

from cordis import Service

from .registry import Commands

name = "commands"


# ---------------------------------------------------------------------------
# Built-in command handlers (pure async functions, no cordis imports)
# ---------------------------------------------------------------------------

async def _quit_handler(args: str) -> list[dict]:
    """/quit — say bye bye and signal the chat session to exit."""
    return [
        {"type": "note", "text": "bye bye 👋"},
        {"type": "quit"},
    ]


# ---------------------------------------------------------------------------
# Service wrapper
# ---------------------------------------------------------------------------

class CommandsService(Service):
    """Cordis service wrapping the pure Commands broker."""

    def __init__(self, ctx):
        super().__init__(ctx, "commands")
        self._impl = Commands()

    def register(self, spec, run):
        return self._impl.register(spec, run)

    def specs(self):
        return self._impl.specs()

    async def run(self, line):
        return await self._impl.run(line)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def apply(ctx, config):
    """Register the commands broker and built-in operator commands."""
    svc = CommandsService(ctx)

    # Register built-in commands via the broker (acquire pattern).
    # Each registration returns a remover that runs as a fiber effect,
    # so commands are automatically unregistered when this plugin unloads.

    remove_quit = svc.register(
        {"name": "quit", "help": "Exit the conversation", "usage": ""},
        _quit_handler,
    )
    ctx.fiber.effect(lambda: remove_quit, "commands.quit")

    # /help needs access to the commands service to list specs dynamically.
    async def help_handler(args: str) -> str:
        specs = svc.specs()
        if not specs:
            return "No commands registered."
        lines = ["Available commands:"]
        for s in specs:
            usage = f" {s.usage}" if s.usage else ""
            lines.append(f"  /{s.name}{usage} — {s.help}")
        return "\n".join(lines)

    remove_help = svc.register(
        {"name": "help", "help": "List available commands", "usage": ""},
        help_handler,
    )
    ctx.fiber.effect(lambda: remove_help, "commands.help")
