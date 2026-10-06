"""Plugin registry, dependency injection, and plugin entrypoint types.

The RegistryService manages plugin registration, dependency injection, and fiber creation.
It normalizes plugin shapes (function, class, or object with apply method) and tracks
plugin runtimes.

Key features:
- Plugin registration with automatic fiber creation
- Dependency injection via inject configuration
- Plugin runtime tracking and lifecycle management
- Support for function, class, and object plugins
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from cordis.utils import DisposableList, symbols

if TYPE_CHECKING:
    from cordis.context import Context
    from cordis.fiber import Fiber


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Inject can be a list of service names or a dict mapping names to config
Inject = list[str] | dict[str, Any]


@dataclass
class PluginRuntime:
    """Mutable registry record shared by all fibers of one plugin callback."""
    name: str | None = None
    fibers: DisposableList = field(default_factory=DisposableList)
    callback: Callable[..., Any] | type = None  # type: ignore
    Config: Any = None


@runtime_checkable
class PluginObject(Protocol):
    """Object plugin with an apply(ctx, config) method."""
    def apply(self, ctx: Context, config: Any) -> Any: ...


Plugin = Callable[..., Any] | type | PluginObject
"""Supported plugin entrypoint shapes."""


# ---------------------------------------------------------------------------
# Inject decorator
# ---------------------------------------------------------------------------

def inject_decorator(name: str, config: Any = None) -> Callable[[Any], Any]:
    """Decorator for declaring service dependencies on classes or methods.

    Mirrors ts_version @Inject decorator.

    Usage:
        @inject('logger')
        class MyPlugin:
            ...

        @inject('database', {'pool_size': 10})
        async def my_plugin(ctx, config):
            ...
    """
    def decorator(target: Any) -> Any:
        if isinstance(target, type):
            # Class decorator: add to inject metadata
            if not hasattr(target, 'inject'):
                target.inject = {}
            target.inject[name] = config
        elif callable(target):
            # Function/method decorator
            if not hasattr(target, '_inject'):
                target._inject = {}
            target._inject[name] = config
        return target
    return decorator


def resolve_inject(inject: Inject | None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert array/object/class-inherited inject metadata into a plain map.

    Mirrors ts_version Inject.resolve().
    """
    if result is None:
        result = {}

    if inject is None:
        return result

    if isinstance(inject, list):
        for name in inject:
            result[name] = None
    elif isinstance(inject, dict):
        for name, config in inject.items():
            result[name] = config if config is not None else None
    elif hasattr(inject, 'inject'):
        # Class with inject attribute
        parent_inject = getattr(type(inject), 'inject', None)
        if parent_inject:
            resolve_inject(parent_inject, result)
        for name, config in inject.inject.items():
            result[name] = config if config is not None else None

    return result


# ---------------------------------------------------------------------------
# RegistryService
# ---------------------------------------------------------------------------

class RegistryService:
    """Plugin registry installed as ctx.registry and mixed into every context.

    It normalizes plugin shapes, tracks plugin runtimes, starts fibers, and
    exposes map-like inspection over active plugin callbacks.

    Mirrors ts_version RegistryService.
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._counter = 0
        self._internal: dict[Callable[..., Any], PluginRuntime] = {}
        self._all_fibers: DisposableList = DisposableList()

        # Set up tracker for traceable proxy
        object.__setattr__(self, symbols.tracker, {
            'property': 'ctx',
            'noShadow': True,
        })

    def next_uid(self) -> int:
        """Allocate and return the next fiber uid."""
        self._counter += 1
        return self._counter

    @property
    def size(self) -> int:
        """Number of registered plugin runtimes."""
        return len(self._internal)

    @property
    def fibers(self) -> list[Fiber]:
        """Return a snapshot list of all active fibers. O(1) access."""
        return list(self._all_fibers)

    def resolve(self, plugin: Plugin) -> Callable[..., Any] | None:
        """Resolve a supported plugin shape to its executable callback.

        Supports callables, objects with an apply method, and dicts with an
        'apply' key (used internally by inject()).

        Mirrors ts_version RegistryService.resolve().
        """
        if callable(plugin):
            return plugin
        if isinstance(plugin, dict):
            apply_fn = plugin.get('apply')
            if callable(apply_fn):
                return apply_fn
            return None
        if hasattr(plugin, 'apply') and callable(plugin.apply):
            return plugin.apply
        return None

    def get(self, plugin: Plugin) -> PluginRuntime | None:
        """Look up the runtime record for a plugin.

        Mirrors ts_version RegistryService.get().
        """
        key = self.resolve(plugin)
        if key is None:
            return None
        return self._internal.get(key)

    def has(self, plugin: Plugin) -> bool:
        """Check whether a plugin has a registered runtime.

        Mirrors ts_version RegistryService.has().
        """
        key = self.resolve(plugin)
        return key is not None and key in self._internal

    def delete(self, plugin: Plugin) -> PluginRuntime | None:
        """Dispose every running fiber for a plugin and remove its runtime record.

        Mirrors ts_version RegistryService.delete().
        """
        key = self.resolve(plugin)
        if key is None:
            return None

        runtime = self._internal.get(key)
        if runtime is None:
            return None

        del self._internal[key]

        for fiber in runtime.fibers:
            result = fiber.dispose()
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    pass  # No running loop; cleanup deferred

        return runtime

    def keys(self) -> Iterator[Callable[..., Any]]:
        """Iterate the registered plugin callbacks."""
        return iter(self._internal.keys())

    def values(self) -> Iterator[PluginRuntime]:
        """Iterate the registered plugin runtimes."""
        return iter(self._internal.values())

    def entries(self) -> Iterator[tuple[Callable[..., Any], PluginRuntime]]:
        """Iterate [callback, runtime] pairs."""
        return iter(self._internal.items())

    def for_each(self, callback: Callable[[PluginRuntime, Callable[..., Any]], None]) -> None:
        """Visit every registered runtime.

        Mirrors ts_version RegistryService.forEach().
        """
        for key, runtime in self._internal.items():
            callback(runtime, key)

    def inject(self, deps: Inject, callback: Callable[[Context], Any]) -> Fiber:
        """Start a callback once the requested dependencies are available.

        The callback receives only the context (not config), matching the
        documented signature ``Callable[[Context], Any]``.

        Mirrors ts_version RegistryService.inject().
        """
        # Wrap to match plugin signature (ctx, config) → callback(ctx)
        def wrapper(ctx, config):
            return callback(ctx)
        wrapper.__name__ = getattr(callback, '__name__', 'inject')
        return self.plugin({'inject': deps, 'apply': wrapper, 'name': wrapper.__name__})

    def plugin(self, plugin: Plugin, config: Any = None, get_outer_stack: Callable[[], list[str]] | None = None) -> Fiber:
        """Start a plugin in the current context and return its fiber.

        Creates (or reuses) the plugin's runtime record, then starts a new fiber
        under the current context.

        Mirrors ts_version RegistryService.plugin().
        """
        if get_outer_stack is None:
            get_outer_stack = lambda: []  # Simplified: no stack capture

        # Resolve plugin to callback
        callback = self.resolve(plugin)
        if callback is None:
            raise ValueError(f'invalid plugin, expect function or object with an "apply" method, received {type(plugin).__name__}')

        # Assert fiber is active
        self.ctx.fiber.assert_active()

        # Get or create runtime
        runtime = self._internal.get(callback)
        if runtime is None:
            if isinstance(plugin, dict):
                name = plugin.get('name')
                plugin_config = plugin.get('Config')
                plugin_inject = plugin.get('inject')
            else:
                name = getattr(plugin, 'name', None)
                plugin_config = getattr(plugin, 'Config', None)
                plugin_inject = getattr(plugin, 'inject', None)
            if name == 'apply':
                name = None
            runtime = PluginRuntime(
                name=name,
                callback=callback,
                Config=plugin_config,
            )
            self._internal[callback] = runtime

        # Resolve inject
        if isinstance(plugin, dict):
            inject_map = resolve_inject(plugin.get('inject'))
        else:
            inject_map = resolve_inject(getattr(plugin, 'inject', None))

        # Create fiber
        from cordis.fiber import Fiber
        fiber = Fiber(self.ctx, config, inject_map, runtime, get_outer_stack)

        return fiber

    def __len__(self) -> int:
        return self.size

    def __contains__(self, plugin: Plugin) -> bool:
        return self.has(plugin)

    def __iter__(self) -> Iterator[Callable[..., Any]]:
        return self.keys()
