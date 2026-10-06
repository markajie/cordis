"""Agent plugin: conversation loop service.

Registers the ``loop`` service on the Cordis context.  The service wraps
the pure :class:`~cordis_harness.plugins.agent.loop.LoopModel` and exposes
an async :pymeth:`reply` generator that drives the full agent turn.

Dependencies (declared via *inject*): ``model``, ``kernel``, ``transcript``,
``system`` — all must be available before this plugin starts.

Config keys (from ``cordis.json`` → ``agent`` section):

* ``max_nudges`` (int, default 2) — retry limit for silent / truncated turns.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from cordis import Service

from .loop import LoopModel

name = "agent"
inject = ["model", "kernel", "transcript", "system"]


class AgentService(Service):
    """Cordis service wrapper around :class:`LoopModel`.

    Registered under the service name ``loop``; other plugins access it as
    ``ctx.loop`` and call :pymeth:`reply` to drive a conversation turn.
    """

    def __init__(self, ctx: Any, config: dict[str, Any] | None = None) -> None:
        super().__init__(ctx, "loop")
        cfg = config or {}
        self._loop = LoopModel(
            model=ctx.model,
            kernel=ctx.kernel,
            transcript=ctx.transcript,
            system=ctx.system,
            max_nudges=cfg.get("max_nudges", 2),
        )

    async def reply(self, message: str) -> AsyncIterator[dict[str, Any]]:
        """Process a user *message* and yield events until the turn completes.

        Delegates directly to :meth:`LoopModel.reply`; see that method for
        the full event protocol.
        """
        async for event in self._loop.reply(message):
            yield event


def apply(ctx: Any, config: dict[str, Any] | None) -> None:
    """Plugin entry point — instantiate and register the agent service."""
    AgentService(ctx, config)
