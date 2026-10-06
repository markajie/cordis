"""Bootstrap: load config, create context, wire up all plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cordis import create_context

from cordis_harness.config import get_plugin_config, load_config


async def boot(
    config_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Boot the harness: create context, load plugins in dependency order.

    Args:
        config_path: Path to cordis.json (used only when *config* is None).
        config: Pre-loaded configuration dict. When provided, *config_path*
            is ignored and no file I/O occurs.

    Returns the root context with all services registered.
    """
    if config is None:
        config = load_config(config_path)
    ctx = create_context()

    # Import plugins
    from cordis_harness.plugins import (
        transcript as transcript_plugin,
        commands as commands_plugin,
        kernel as kernel_plugin,
        context as context_plugin,
        models as models_plugin,
        agent as agent_plugin,
        chat as chat_plugin,
    )

    # Load plugins in dependency order via ctx.registry.plugin().
    # Await settle after each to ensure services are registered before dependents load.
    # 1. No dependencies
    f = ctx.registry.plugin(transcript_plugin, get_plugin_config(config, "transcript"))
    await f.await_settled()
    f = ctx.registry.plugin(commands_plugin, get_plugin_config(config, "commands"))
    await f.await_settled()
    f = ctx.registry.plugin(kernel_plugin, get_plugin_config(config, "kernel"))
    await f.await_settled()

    # 2. Depends on kernel
    f = ctx.registry.plugin(context_plugin, get_plugin_config(config, "context"))
    await f.await_settled()

    # 3. Independent but needed by agent
    f = ctx.registry.plugin(models_plugin, get_plugin_config(config, "models"))
    await f.await_settled()

    # 4. Depends on model, kernel, transcript, system
    f = ctx.registry.plugin(agent_plugin, get_plugin_config(config, "agent"))
    await f.await_settled()

    # 5. Depends on loop, commands
    f = ctx.registry.plugin(chat_plugin, get_plugin_config(config, "chat"))
    await f.await_settled()

    # Emit ready event
    ctx.events.emit("harness/ready")

    return ctx


async def run(
    config_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """Boot and run until the chat session ends."""
    ctx = await boot(config_path=config_path, config=config)

    try:
        # Wait for the 'done' service (bound by chat plugin)
        done = ctx.reflect.get("done", strict=False)
        if done is not None:
            await done
        else:
            ctx.logger.warn("No 'done' service found; exiting immediately")
    except KeyboardInterrupt:
        pass
    finally:
        ctx.events.emit("harness/shutdown")
