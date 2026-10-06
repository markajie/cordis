"""Event bus, dispatch modes, and event augmentation types.

The EventsService provides five dispatch modes for flexible event handling:
- emit: Synchronous fire-and-forget
- parallel: Concurrent execution, wait for all
- serial: Sequential execution, stop on bail value
- bail: Synchronous, stop on first bail value
- waterfall: Chain listeners around a final callback

Key features:
- Listener registration with automatic cleanup via fiber effects
- Context filtering for scoped event delivery
- Support for both sync and async listeners
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from cordis.utils import symbols

if TYPE_CHECKING:
    from cordis.context import Context
    from cordis.fiber import Fiber, FiberState


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

DispatchMode = Literal['emit', 'parallel', 'serial', 'bail', 'waterfall']
"""Event dispatch strategy used by the event service."""


@dataclass
class EventOptions:
    """Options accepted by ctx.on() and ctx.once()."""
    prepend: bool = False
    global_: bool = False  # Use global_ to avoid Python keyword conflict


@dataclass
class Hook:
    """Registered listener record stored by the event service."""
    ctx: Context
    callback: Callable[..., Any]
    prepend: bool = False
    global_: bool = False


def is_bailed(value: Any) -> bool:
    """Return whether an event result should stop a bail-style dispatch.

    Returns True unless value is None or False.
    Mirrors ts_version isBailed().
    """
    return value is not None and value is not False


# ---------------------------------------------------------------------------
# EventsService
# ---------------------------------------------------------------------------

class EventsService:
    """Event bus installed as ctx.events and mixed into every context.

    The service supports concurrent, synchronous, serial, bail, and waterfall
    dispatch and automatically disposes listeners with their owning fiber.

    Mirrors ts_version EventsService.
    """

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._hooks: dict[str, list[Hook]] = {}

        # Set up tracker for traceable proxy
        object.__setattr__(self, symbols.tracker, {
            'property': '_ctx',
            'noShadow': True,
        })

    def dispatch(self, type_: str, args: list[Any]) -> list[Callable[..., Any]]:
        """Resolve listeners for one dispatch and apply context filtering.

        Args:
            type_: The dispatch mode, reported on internal/dispatch.
            args: The raw dispatch arguments; consumed up to the event name.

        Returns:
            The matching listener callbacks, bound to the dispatch thisArg.

        Mirrors ts_version EventsService.dispatch().
        """
        # Extract optional thisArg: must be a Context (has _brand) or have a filter symbol.
        # This avoids treating plain values (int, list, etc.) as thisArg.
        this_arg = None
        if args and (getattr(args[0], '_brand', None) is not None or hasattr(args[0], symbols.filter)):
            this_arg = args.pop(0)

        # Extract event name
        if not args:
            return []
        name = args.pop(0)

        # Emit internal/dispatch for non-internal events
        if isinstance(name, str) and not name.startswith('internal/'):
            self.emit('internal/dispatch', type_, name, list(args), this_arg)

        # Get filter from thisArg if present
        filter_fn = getattr(this_arg, symbols.filter, None) if this_arg is not None else None

        # Get hooks for this event and apply context filtering
        hooks = self._hooks.get(name, [])
        result = []
        for hook in hooks:
            if not hook.global_ and filter_fn is not None and not filter_fn(hook.ctx):
                continue
            result.append(hook.callback)

        return result

    async def parallel(self, *args: Any) -> None:
        """Run listeners concurrently and wait for all of them.

        Mirrors ts_version EventsService.parallel().
        """
        dispatch_args = list(args)
        callbacks = self.dispatch('parallel', dispatch_args)

        if not callbacks:
            return

        # Run all callbacks concurrently
        tasks = []
        for cb in callbacks:
            result = cb(*dispatch_args)
            if asyncio.iscoroutine(result):
                tasks.append(result)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                raise ExceptionGroup("parallel dispatch errors", errors)

    def emit(self, *args: Any) -> None:
        """Run listeners synchronously without waiting for returned promises.

        Mirrors ts_version EventsService.emit().
        """
        # Convert to list so dispatch can modify it
        dispatch_args = list(args)
        callbacks = self.dispatch('emit', dispatch_args)

        # dispatch_args has been modified by dispatch (thisArg and name removed)
        # Use the modified args for callback invocation (matches ts_version behavior)
        for cb in callbacks:
            cb(*dispatch_args)

    async def serial(self, *args: Any) -> Any:
        """Run listeners in order, awaiting each, until one returns a bail value.

        Mirrors ts_version EventsService.serial().
        """
        dispatch_args = list(args)
        callbacks = self.dispatch('serial', dispatch_args)

        for cb in callbacks:
            result = cb(*dispatch_args)
            if asyncio.iscoroutine(result):
                result = await result
            if is_bailed(result):
                return result

        return None

    def bail(self, *args: Any) -> Any:
        """Run listeners synchronously until one returns a bail value.

        Mirrors ts_version EventsService.bail().
        """
        dispatch_args = list(args)
        callbacks = self.dispatch('bail', dispatch_args)

        for cb in callbacks:
            result = cb(*dispatch_args)
            if is_bailed(result):
                return result

        return None

    def waterfall(self, *args: Any, inner: Callable[..., Any] | None = None) -> Any:
        """Compose listeners around the final next callback.

        The innermost callback can be passed as the ``inner`` keyword argument
        or as the last positional argument.  Listeners run outermost-first; a
        listener that does not call next() vetoes the rest of the chain.

        Mirrors ts_version EventsService.waterfall().
        """
        dispatch_args = list(args)
        callbacks = self.dispatch('waterfall', dispatch_args)

        # Resolve innermost callback: kwarg takes priority, else last positional arg
        if inner is None:
            inner = dispatch_args.pop() if dispatch_args else lambda: None

        # Build the chain: each listener receives (*dispatch_args, next_fn)
        cbs = list(callbacks)

        def next_fn() -> Any:
            if cbs:
                cb = cbs.pop(0)
                return cb(*dispatch_args, next_fn)
            return inner()

        return next_fn()

    def register(self, label: str, hooks: list[Hook], callback: Callable[..., Any],
                 options: EventOptions | None = None) -> Callable[[], bool]:
        """Store a listener record.

        Simplified from ts_version: directly register without effect wrapper.
        The disposer removes the listener when called.

        Mirrors ts_version EventsService.register() but simplified.
        """
        if options is None:
            options = EventOptions()

        hook = Hook(
            ctx=self._ctx,
            callback=callback,
            prepend=options.prepend,
            global_=options.global_,
        )
        
        # Add hook to list
        if options.prepend:
            hooks.insert(0, hook)
        else:
            hooks.append(hook)

        def unregister() -> bool:
            return self.unregister(hooks, callback)

        return unregister

    def unregister(self, hooks: list[Hook], callback: Callable[..., Any]) -> bool:
        """Remove a stored listener record.

        Mirrors ts_version EventsService.unregister().
        """
        for i, hook in enumerate(hooks):
            if hook.callback is callback:
                hooks.pop(i)
                return True
        return False

    def on(self, name: str, listener: Callable[..., Any],
           options: bool | EventOptions | None = None) -> Callable[[], bool]:
        """Register an event listener owned by the current fiber.

        The listener is removed automatically when the fiber unloads.

        Mirrors ts_version EventsService.on().
        """
        # Normalize options
        if isinstance(options, bool):
            options = EventOptions(prepend=options)
        elif options is None:
            options = EventOptions()

        # Determine the owning fiber: prefer _loading_fiber (the plugin being loaded),
        # fall back to the context's own fiber.
        fiber = getattr(self._ctx, '_loading_fiber', None) or self._ctx.fiber
        if fiber is not None:
            fiber.assert_active()

        # Bind listener through reflect
        reflect = self._ctx.reflect
        if reflect is not None:
            listener = reflect.bind(listener)

        # Check for internal/listener interception (skip for now, no internal listeners registered)
        # result = self.bail(self._ctx, 'internal/listener', name, listener, options)
        # if result is not None:
        #     return result

        # Get or create hooks list
        if name not in self._hooks:
            self._hooks[name] = []
        hooks = self._hooks[name]

        label = f"ctx.on({name!r})"
        disposer = self.register(label, hooks, listener, options)

        # Auto-register as fiber effect so listener is removed on unload
        if fiber is not None:
            fiber.effect(lambda d=disposer: lambda: d(), label)

        return disposer

    def once(self, name: str, listener: Callable[..., Any],
             options: bool | EventOptions | None = None) -> Callable[[], bool]:
        """Register an event listener that disposes itself after the first call.

        Mirrors ts_version EventsService.once().
        """
        dispose: Callable[[], bool] | None = None

        def wrapper(*args: Any) -> Any:
            if dispose is not None:
                dispose()
            return listener(*args)

        dispose = self.on(name, wrapper, options)
        return dispose

