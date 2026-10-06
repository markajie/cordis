"""Chat plugin wiring — interactive session management.

Registers the chat session as a background task bound to the ``done`` service.
The ``done`` service is an :class:`asyncio.Task` that completes when the user
exits the chat (EOF, Ctrl-C, or /quit), which the bootstrap uses to know when
the interactive session has finished.

Dependencies (declared via ``inject``):

* ``loop``     — agent loop with ``async reply(message) -> AsyncIterator[event]``
* ``commands`` — slash-command broker with ``async run(line) -> answer``

This plugin does NOT register any commands. Commands are registered by the
``commands`` plugin (the broker's operator). Chat only consumes them.

adapted to cordis-harness's function plugin + ``ctx.fiber.effect()`` pattern.
"""

from __future__ import annotations

import asyncio

from .session import converse

name = "chat"
inject = ["loop", "commands"]


def apply(ctx, config):
    """Plugin entry point — start the chat session and bind ``done``."""

    def setup():
        """Effect: start the chat task; cleanup cancels it."""
        task = asyncio.create_task(
            converse(ctx.loop, ctx.commands),
            name="chat-session",
        )

        # Register the task as 'done' so bootstrap can await it.
        dispose_provide = ctx.reflect.provide("done", task)

        def dispose():
            if not task.done():
                task.cancel()
            dispose_provide()

        return dispose

    ctx.fiber.effect(setup, "chat-session")
