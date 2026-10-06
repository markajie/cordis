"""Plugin fiber lifecycle, effects, and config validation helpers.

The Fiber class manages plugin lifecycle, effect registration, and dependency tracking.
A fiber represents a running plugin instance with its own state machine and cleanup logic.

Key features:
- Lifecycle states: PENDING → LOADING → ACTIVE → UNLOADING → DISPOSED/FAILED
- Effect system for resource management with automatic cleanup
- Dependency tracking and refresh on service changes
- Async support for plugin initialization and teardown
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from cordis.utils import DisposableList, symbols

if TYPE_CHECKING:
    from cordis.context import Context
    from cordis.reflect import Impl
    from cordis.registry import PluginRuntime


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

INACTIVE = '__INACTIVE__'


class FiberState(IntEnum):
    """Lifecycle state for one plugin fiber."""
    PENDING = 0
    LOADING = 1
    ACTIVE = 2
    FAILED = 3
    DISPOSED = 4
    UNLOADING = 5


@dataclass
class EffectMeta:
    """Tree node used to expose nested effect labels for diagnostics."""
    label: str
    children: list[EffectMeta] = field(default_factory=list)


Disposable = Callable[[], Any]
Effect = Disposable | Iterable[Disposable] | Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CordisError(Exception):
    """Framework error with a stable machine-readable code."""
    CODES = {'INACTIVE_EFFECT': 'cannot create effect on inactive context'}

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or self.CODES.get(code, code))


class ValidationError(TypeError):
    """Error raised when plugin configuration fails validation."""
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        lines = ['invalid config:']
        for issue in issues:
            path = issue.get('path')
            msg = issue.get('message', str(issue))
            if path:
                lines.append(f"  - {msg} (at {'.'.join(path)})")
            else:
                lines.append(f"  - {msg}")
        super().__init__('\n'.join(lines))


def resolve_config(runtime: PluginRuntime | None, config: Any) -> Any:
    """Validate and normalize config for a plugin runtime."""
    if runtime is None or not hasattr(runtime, 'Config') or runtime.Config is None:
        return config
    return config


# ---------------------------------------------------------------------------
# Fiber class - Simple state machine with lifecycle management
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Fiber:
    """A plugin running. Mutable state machine.

    Fiber holds state, lifecycle logic is managed through state transitions.
    """

    parent: Context
    config: Any
    inject: dict[str, Any]
    runtime: PluginRuntime | None
    uid: int | None = None
    ctx: Context = field(init=False)
    state: FiberState = FiberState.PENDING
    store: dict[str, Impl] | None = None
    inertia: asyncio.Future[None] | None = None
    error: Exception | None = None

    # Internal state
    _config: Any = field(init=False, repr=False)
    _disposables: DisposableList = field(default_factory=DisposableList, repr=False)
    _store: dict[str, Impl] = field(default_factory=dict, repr=False)
    _runner_epoch: str | bool = field(default=INACTIVE, repr=False)

    def __post_init__(self) -> None:
        self._config = self.config

        if self.runtime is not None:
            # Plugin fiber
            self.uid = self.parent.registry.next_uid() if self.parent.registry else 1
            self.ctx = self.parent.extend({'fiber': self})

            # Set up intercept map for injected services
            if self.inject:
                new_intercept = dict(self.parent._intercept)
                for name, cfg in self.inject.items():
                    if cfg is not None:
                        new_intercept[name] = cfg
                object.__setattr__(self.ctx, '_intercept_map', new_intercept)

            # Set _loading_fiber on child context so plugins can access it directly.
            # Root context's _loading_fiber is set dynamically in _reload() around
            # plugin execution so services (which hold root ref) can find it too.
            object.__setattr__(self.ctx, '_loading_fiber', self)

            # Register this fiber in its runtime's fiber list
            self._runtime_fiber_remover = self.runtime.fibers.push(self)

            # Register in registry's global fiber list
            if self.parent.registry is not None:
                self._registry_fiber_remover = self.parent.registry._all_fibers.push(self)
            else:
                self._registry_fiber_remover = None

            # Create dispose function
            self.dispose = self._create_dispose()

            # Emit internal/plugin event (best effort)
            if self.parent.events is not None:
                self.parent.events.emit('internal/plugin', self)

            # Check dependencies
            if self.uid is not None:
                parent_fiber = self.parent.fiber
                if parent_fiber is None or parent_fiber.state != FiberState.UNLOADING:
                    for name in self.inject.keys():
                        self._check_impl(name)
                    self._refresh()
        else:
            # Root fiber
            self.uid = 0
            self.ctx = self.parent
            self.state = FiberState.ACTIVE
            self.store = {}
            self._runner_epoch = ''
            self.dispose = lambda: self.restart()

    @property
    def provide(self) -> list[str]:
        """List of service names this fiber provides."""
        return list(self.store.keys()) if self.store else []

    @property
    def name(self) -> str:
        """The plugin's display name."""
        fiber: Fiber = self
        while True:
            if fiber.runtime is not None and hasattr(fiber.runtime, 'name') and fiber.runtime.name:
                return fiber.runtime.name
            if fiber.parent is None or fiber.parent.fiber is fiber:
                break
            fiber = fiber.parent.fiber
        return 'root'

    def assert_active(self) -> None:
        """Throw if the fiber has already been disposed."""
        if self.uid is None:
            raise CordisError('INACTIVE_EFFECT')

    def effect(self, execute: Callable[[], Effect], label: str = 'anonymous') -> Disposable:
        """Register a cleanup-aware effect on this fiber.

        Simple implementation: execute returns disposer(s), we collect them.
        Disposers run in reverse order when fiber unloads.
        """
        self.assert_active()
        if self.state == FiberState.UNLOADING:
            raise CordisError('INACTIVE_EFFECT')

        disposables: list[Disposable] = []
        meta = EffectMeta(label=label)

        def dispose() -> None:
            """Run all disposers in reverse order."""
            for d in reversed(disposables):
                result = d()
                if asyncio.iscoroutine(result):
                    # Schedule but don't block
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        pass  # No loop, ignore async cleanup

        # Execute the effect body and collect disposers
        result = execute()

        if callable(result):
            disposables.append(result)
        elif result is not None and isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
            for item in result:
                if callable(item):
                    disposables.append(item)
        elif asyncio.iscoroutine(result):
            # Async effect - schedule collection
            async def collect_async():
                r = await result
                if callable(r):
                    disposables.append(r)
                elif isinstance(r, Iterable) and not isinstance(r, (str, bytes)):
                    for item in r:
                        if callable(item):
                            disposables.append(item)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(collect_async())
            except RuntimeError:
                pass

        # Register the wrapper disposer
        self._disposables.push(dispose)

        # Attach metadata
        object.__setattr__(dispose, symbols.effect, meta)

        return dispose

    def get_effects(self) -> list[EffectMeta]:
        """Return metadata for currently registered effects."""
        result = []
        for dispose in self._disposables:
            meta = getattr(dispose, symbols.effect, None)
            if meta is not None:
                result.append(meta)
        return result

    def _check_impl(self, name: str) -> None:
        """Check if a required service implementation is available."""
        reflect = self.ctx.reflect
        if reflect is None:
            return

        impl = reflect._get_impl(name, strict=True)
        if impl is None:
            self._store.pop(name, None)
            return

        if hasattr(impl, 'check') and impl.check is not None:
            if not impl.check():
                self._store.pop(name, None)
                return

        self._store[name] = impl

    def _refresh(self) -> None:
        """Recompute the epoch from current dependencies."""
        epoch: str | bool = ''
        for name in self.inject.keys():
            impl = self._store.get(name)
            if impl is None:
                epoch = INACTIVE
                break
            fiber_uid = impl.fiber.uid if hasattr(impl, 'fiber') and impl.fiber else 0
            epoch += f':{fiber_uid}'

        self._set_epoch(epoch)

    def _set_epoch(self, epoch: str | bool) -> None:
        """Update the runner epoch and trigger state transitions."""
        old_epoch = self._runner_epoch
        if epoch == old_epoch:
            return

        self._runner_epoch = epoch

        if self.inertia is not None:
            return

        if epoch != INACTIVE and old_epoch == INACTIVE:
            self._update_state(lambda: FiberState.LOADING)
            try:
                loop = asyncio.get_running_loop()
                self.inertia = loop.create_task(self._reload())
            except RuntimeError:
                pass  # No loop, defer loading
        else:
            self._update_state(lambda: FiberState.UNLOADING)
            try:
                loop = asyncio.get_running_loop()
                self.inertia = loop.create_task(self._unload())
            except RuntimeError:
                pass

    def _update_state(self, callback: Callable[[], FiberState | None]) -> None:
        """Update fiber state and emit status event."""
        old_state = self.state
        new_state = callback()
        if new_state is not None:
            self.state = new_state
        else:
            if self.uid is None:
                self.state = FiberState.DISPOSED
            elif self.error is not None:
                self.state = FiberState.FAILED
            elif self._runner_epoch != INACTIVE:
                self.state = FiberState.ACTIVE
            else:
                self.state = FiberState.PENDING

        if old_state == self.state:
            return

        if self.ctx.events is not None:
            self.ctx.events.emit('internal/status', self, old_state)

    async def _reload(self) -> None:
        """Load the plugin: validate config, execute callback, become ACTIVE."""
        self.store = dict(self._store)
        old_epoch = self._runner_epoch

        try:
            await asyncio.sleep(0)  # Yield to allow cancellation

            if self._runner_epoch == old_epoch:
                self.config = resolve_config(self.runtime, self._config)
                # Set _loading_fiber on root so services can find the current fiber
                root = self.parent.root if self.parent else None
                if root is not None:
                    object.__setattr__(root, '_loading_fiber', self)
                try:
                    result = self._execute_plugin()
                    if asyncio.iscoroutine(result):
                        await result
                finally:
                    if root is not None:
                        object.__setattr__(root, '_loading_fiber', None)
                self.error = None

        except Exception as e:
            if self.ctx.logger:
                self.ctx.logger.error(e)
            self.error = e
            # Only mark inactive if epoch hasn't been updated externally
            if self._runner_epoch == old_epoch:
                self._runner_epoch = INACTIVE

        if self._runner_epoch == old_epoch:
            self.inertia = None
            self._update_state(lambda: None)
        else:
            self.inertia = asyncio.create_task(self._unload())
            self._update_state(lambda: FiberState.UNLOADING)

    async def _unload(self) -> None:
        """Unload the plugin: run all disposers in reverse order."""
        for dispose in self._disposables.clear():
            result = dispose()
            if asyncio.iscoroutine(result):
                await result

        self.store = None

        if self._runner_epoch == INACTIVE:
            self.inertia = None
            self._update_state(lambda: None)
        else:
            self.inertia = asyncio.create_task(self._reload())
            self._update_state(lambda: FiberState.LOADING)

    def _execute_plugin(self) -> Any:
        """Execute the plugin callback."""
        if self.runtime is None:
            return None

        callback = self.runtime.callback

        # Check if callback is a class (constructor)
        if isinstance(callback, type):
            instance = callback(self.ctx, self.config)
            init_hooks = getattr(instance, symbols.initHooks, [])
            for hook in init_hooks:
                hook()
            init = getattr(instance, symbols.init, None)
            if init is not None:
                return init()
            return None
        else:
            return callback(self.ctx, self.config)

    def _create_dispose(self) -> Callable[[], Any]:
        """Create the dispose function for this fiber."""
        async def do_dispose() -> None:
            self.uid = None
            if self.ctx.events is not None:
                self.ctx.events.emit('internal/plugin', self)

            # Remove from registry's global fiber list
            if getattr(self, '_registry_fiber_remover', None) is not None:
                self._registry_fiber_remover()

            if self.runtime is not None and hasattr(self.runtime, 'fibers'):
                self.runtime.fibers.delete(self)
                if self.ctx.registry and self.ctx.registry.has(self.runtime.callback):
                    if not self.runtime.fibers.length:
                        self.ctx.registry.delete(self.runtime.callback)

            self._set_epoch(INACTIVE)

            if self.inertia is None:
                self._update_state(lambda: FiberState.UNLOADING)
                self.inertia = asyncio.create_task(self._unload())

            while self.inertia is not None:
                await self.inertia

        return do_dispose

    async def await_settled(self) -> Fiber:
        """Wait for current lifecycle work and rethrow startup errors."""
        while self.inertia is not None:
            await self.inertia
        if self.error is not None:
            raise self.error
        return self

    async def restart(self) -> None:
        """Dispose and immediately reload this plugin."""
        self.assert_active()
        self._set_epoch(INACTIVE)
        self._refresh()
        await self.await_settled()

    def update(self, config: Any, no_save: bool = False) -> None:
        """Validate and apply new config, then restart the plugin."""
        self.assert_active()
        self._config = config

        if self.state != FiberState.ACTIVE:
            self.error = None
            self._set_epoch(INACTIVE)
            self._refresh()
            return

        config = resolve_config(self.runtime, config)

        def do_update() -> None:
            self.config = config
            self.error = None
            asyncio.create_task(self.restart())

        if self.ctx.events is not None:
            self.ctx.events.waterfall(self, 'internal/update', config, no_save, do_update)
        else:
            do_update()

    def __repr__(self) -> str:
        return f"Fiber<{self.name}#{self.uid} state={self.state.name}>"
