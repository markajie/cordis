"""Command registry: broker pattern for slash commands."""
from typing import Any, Callable, Awaitable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandSpec:
    name: str
    help: str
    usage: str = ""
    choices: Callable[[], Sequence[dict]] | None = None


Run = Callable[[str], Awaitable[Any]]


class Commands:
    """Broker for slash commands. Plugins register commands; chat runs them."""

    def __init__(self):
        self._commands: dict[str, tuple[CommandSpec, Run]] = {}

    def register(self, spec: CommandSpec | dict, run: Run) -> Callable[[], None]:
        """Register a command. Returns a remover function."""
        if isinstance(spec, dict):
            spec = CommandSpec(**spec)
        self._commands[spec.name] = (spec, run)

        def remove():
            self._commands.pop(spec.name, None)

        return remove

    def specs(self) -> list[CommandSpec]:
        return [s for s, _ in self._commands.values()]

    async def run(self, line: str) -> Any:
        """Parse and execute a command line. Returns answer text or events."""
        parts = line.strip().split(None, 1)
        name = parts[0].lstrip('/')
        args = parts[1] if len(parts) > 1 else ""
        entry = self._commands.get(name)
        if entry is None:
            return f"Unknown command: /{name}"
        _, handler = entry
        return await handler(args)
