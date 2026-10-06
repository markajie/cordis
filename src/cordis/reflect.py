"""Reflection and service-resolution layer installed as ctx.reflect.

The ReflectService powers the context proxy, service registration, accessors, and mixins.
It enables dynamic service resolution and property access on Context objects.

Key features:
- Service registration via provide() with automatic cleanup
- Service resolution via get() with strict/non-strict modes
- Accessor properties for computed values
- Mixin support for exposing service methods on context
- Traceable wrappers for context-aware method calls
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from cordis.utils import symbols

if TYPE_CHECKING:
    from cordis.context import Context
    from cordis.fiber import Fiber, FiberState


# ---------------------------------------------------------------------------
# Traceable wrapper (simplified from utils.py)
# ---------------------------------------------------------------------------

def _get_traceable(ctx: Context, value: Any) -> Any:
    """Wrap value to bind context for method calls.
    
    If value has tracker metadata, wrap it so method calls see correct context.
    Otherwise return value unchanged.
    """
    if value is None:
        return value
    
    tracker = getattr(value, symbols.tracker, None)
    if tracker is None:
        return value
    
    return _TraceableWrapper(ctx, value, tracker)


class _TraceableWrapper:
    """Wrapper that intercepts attribute access to rebind context."""
    
    __slots__ = ('_ctx', '_target', '_tracker')
    
    def __init__(self, ctx: Context, target: Any, tracker: dict) -> None:
        object.__setattr__(self, '_ctx', ctx)
        object.__setattr__(self, '_target', target)
        object.__setattr__(self, '_tracker', tracker)
    
    def __getattr__(self, name: str) -> Any:
        ctx = object.__getattribute__(self, '_ctx')
        target = object.__getattribute__(self, '_target')
        tracker = object.__getattribute__(self, '_tracker')
        
        # Special attributes
        if name == symbols.original:
            return target
        if name == tracker.get('property'):
            return ctx
        
        # Associated properties (e.g., "logger.name")
        associate = tracker.get('associate')
        if associate:
            assoc_key = f"{associate}.{name}"
            if hasattr(ctx, 'reflect') and ctx.reflect is not None:
                props = getattr(ctx.reflect, 'props', {})
                if assoc_key in props:
                    return getattr(ctx, assoc_key)
        
        # Get from target
        inner_value = getattr(target, name)
        
        # Recursively wrap if has tracker
        inner_tracker = getattr(inner_value, symbols.tracker, None)
        if inner_tracker is not None:
            return _TraceableWrapper(ctx, inner_value, inner_tracker)
        
        # Wrap methods to trace results
        if not tracker.get('noShadow') and callable(inner_value):
            @functools.wraps(inner_value)
            def traced_method(*args: Any, **kwargs: Any) -> Any:
                result = inner_value(*args, **kwargs)
                return _get_traceable(ctx, result)
            return traced_method
        
        return inner_value
    
    def __setattr__(self, name: str, value: Any) -> None:
        target = object.__getattribute__(self, '_target')
        setattr(target, name, value)
    
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        target = object.__getattribute__(self, '_target')
        invoke = getattr(target, symbols.invoke, None)
        if invoke is not None:
            return invoke(*args, **kwargs)
        return target(*args, **kwargs)
    
    def __repr__(self) -> str:
        target = object.__getattribute__(self, '_target')
        return f"Traceable({target!r})"



# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class PropertyService:
    """Service property backed by a provided implementation."""
    type: Literal['service'] = 'service'


@dataclass
class PropertyAccessor:
    """Computed context property backed by custom get/set hooks."""
    type: Literal['accessor'] = 'accessor'
    get: Callable[..., Any] | None = None
    set: Callable[..., bool] | None = None


Property = PropertyService | PropertyAccessor


@dataclass
class Impl:
    """Concrete service implementation record stored in the root reflect service."""
    name: str
    fiber: Fiber
    value: Any = None
    check: Callable[[], bool] | None = None


# ---------------------------------------------------------------------------
# ReflectService
# ---------------------------------------------------------------------------

class ReflectService:
    """Reflection and service-resolution layer installed as ctx.reflect.

    This service powers the context proxy, service registration, accessors, and
    the mixins that expose core service methods directly on ctx.

    Mirrors ts_version ReflectService.
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.store: dict[Any, Impl] = {}  # isolation label -> Impl
        self.props: dict[str, Property] = {}

        # Set up tracker for traceable proxy
        object.__setattr__(self, symbols.tracker, {
            'property': 'ctx',
            'noShadow': True,
        })

    def get(self, name: str, strict: bool = True) -> Any:
        """Read a service or accessor from the store.

        Checks the service store first; if not found, checks registered
        accessors and invokes their get hook.

        Mirrors ts_version ReflectService.get().
        """
        impl = self._get_impl(name, strict)
        if impl is not None:
            return _get_traceable(self.ctx, impl.value)

        # Check for accessor property
        prop = self.props.get(name)
        if prop is not None and isinstance(prop, PropertyAccessor) and prop.get is not None:
            return prop.get(self.ctx, None)

        return None

    def _get_impl(self, name: str, strict: bool = True) -> Impl | None:
        """Get the implementation record for a service."""
        isolate_map = self.ctx._isolate
        key = isolate_map.get(name)
        if key is None:
            return None

        impl = self.store.get(key)
        if impl is None:
            return None

        if strict:
            fiber_state = impl.fiber.state if hasattr(impl.fiber, 'state') else None
            from cordis.fiber import FiberState
            if fiber_state != FiberState.ACTIVE:
                return None

        return impl

    def set(self, name: str, value: Any, error: Exception | None = None) -> bool:
        """Overwrite a provided service's value or invoke an accessor's set hook.

        Mirrors ts_version ReflectService.set().
        """
        # Check for accessor first
        prop = self.props.get(name)
        if prop is not None and isinstance(prop, PropertyAccessor):
            if prop.set is not None:
                return prop.set(value, self.ctx, error)
            return False

        isolate_map = self.ctx._isolate
        key = isolate_map.get(name)
        if key is None:
            raise ValueError(f'cannot set property "{name}" without provide')

        impl = self.store.get(key)
        if impl is None:
            raise ValueError(f'cannot set property "{name}" without provide')

        if impl.fiber is not self.ctx.fiber:
            raise ValueError(f'cannot set property "{name}" in multiple fibers')

        impl.value = value
        return True

    def provide(self, name: str, value: Any = None, check: Callable[[], bool] | None = None) -> Callable[[], Any]:
        """Register a service implementation owned by the current fiber.

        The service becomes visible to dependents in the same isolation scope
        once the fiber is active; it is unregistered when the returned disposer
        runs or the fiber unloads.

        Mirrors ts_version ReflectService.provide().
        """
        # Use _loading_fiber (the plugin being loaded) if available,
        # otherwise fall back to the context's own fiber.
        fiber = getattr(self.ctx, '_loading_fiber', None) or self.ctx.fiber

        def do_provide() -> Callable[[], Any]:
            # Register property
            if name not in self.props:
                self.props[name] = PropertyService()
            elif self.props[name].type != 'service':
                raise ValueError(f'property "{name}" is already declared as {self.props[name].type}')

            self.props[name] = PropertyService()

            # Set up isolation key
            root_isolate = self.ctx.root._isolate
            if name not in root_isolate:
                root_isolate[name] = object()  # Unique symbol-like key

            isolate_map = self.ctx._isolate
            key = isolate_map.get(name, root_isolate.get(name))

            # Check for existing registration
            if key in self.store:
                existing = self.store[key]
                raise ValueError(f'service "{name}" has been registered at <{existing.fiber.name}>')

            # Create and store implementation
            impl = Impl(name=name, value=value, fiber=fiber, check=check)
            self.store[key] = impl

            # Add to fiber's store
            if fiber.store is not None:
                fiber.store[name] = impl

            # Notify dependents if active
            from cordis.fiber import FiberState
            if fiber.state == FiberState.ACTIVE:
                self.notify([name])

            def dispose() -> None:
                # Remove from store
                self.store.pop(key, None)

                # Notify dependents and schedule their settlement
                fibers = self.notify([name])

                # Schedule dependent settlement as background tasks
                import asyncio
                for f in fibers:
                    try:
                        asyncio.create_task(f.await_settled())
                    except RuntimeError:
                        pass  # No running loop

                # Remove from fiber's store
                if fiber.store is not None:
                    fiber.store.pop(name, None)

            return dispose

        # Register as an effect on the fiber
        return fiber.effect(do_provide, f'ctx.provide({name!r})')

    def notify(self, names: list[str], filter_fn: Callable[[Context, str], bool] | None = None) -> list[Fiber]:
        """Re-evaluate every fiber that requires one of the given services.

        Mirrors ts_version ReflectService.notify().
        """
        if filter_fn is None:
            def default_filter(ctx: Context, name: str) -> bool:
                return ctx._isolate.get(name) == self.ctx._isolate.get(name)
            filter_fn = default_filter

        fibers: list[Fiber] = []

        # Get registry from context
        registry = self.ctx.registry
        if registry is None:
            return fibers

        for runtime in registry.values():
            for fiber in runtime.fibers:
                has_update = False
                for name in names:
                    if name not in fiber.inject:
                        continue
                    if not filter_fn(fiber.ctx, name):
                        continue
                    has_update = True
                    fiber._check_impl(name)

                if has_update:
                    fiber._refresh()
                    fibers.append(fiber)

        # Emit internal/service events
        for name in names:
            impl = self._get_impl(name, strict=False)
            value = impl.value if impl else None
            if self.ctx.events is not None:
                self.ctx.events.emit('internal/service', name, value)

        return fibers

    def accessor(self, name: str, get: Callable[..., Any], set: Callable[..., bool] | None = None) -> Callable[[], None]:
        """Define a computed context property backed by get/set hooks.

        Mirrors ts_version ReflectService.accessor().
        """
        fiber = self.ctx.fiber

        def do_accessor() -> Callable[[], None]:
            if name in self.props:
                raise ValueError(f'property "{name}" is already declared as {self.props[name].type}')

            self.props[name] = PropertyAccessor(type='accessor', get=get, set=set)

            def dispose() -> None:
                self.props.pop(name, None)

            return dispose

        return fiber.effect(do_accessor, f'ctx.accessor({name!r})')

    def mixin(self, source: str | Any, mixins: list[str] | dict[str, str]) -> Callable[[], None]:
        """Expose selected members of a service directly on ctx.

        Mirrors ts_version ReflectService.mixin().
        """
        fiber = self.ctx.fiber

        def do_mixin() -> Callable[[], None]:
            disposers: list[Callable[[], None]] = []

            if isinstance(mixins, list):
                entries = [(key, key) for key in mixins]
            else:
                entries = list(mixins.items())

            for source_key, target_key in entries:
                def make_getter(sk: str) -> Callable[..., Any]:
                    def getter(receiver: Any, error: Exception) -> Any:
                        if isinstance(source, str):
                            service = getattr(self.ctx, source, None)
                        else:
                            service = source
                        if service is None:
                            return None
                        value = getattr(service, sk, None)
                        if callable(value):
                            return functools.partial(value, __self=service)
                        return value
                    return getter

                def make_setter(sk: str) -> Callable[..., bool]:
                    def setter(value: Any, receiver: Any, error: Exception) -> bool:
                        if isinstance(source, str):
                            service = getattr(self.ctx, source, None)
                        else:
                            service = source
                        if service is None:
                            return False
                        setattr(service, sk, value)
                        return True
                    return setter

                disposer = self.accessor(target_key, make_getter(source_key), make_setter(source_key))
                disposers.append(disposer)

            def dispose() -> None:
                for d in disposers:
                    d()

            return dispose

        return fiber.effect(do_mixin, f'ctx.mixin({source!r})')

    def trace(self, value: Any) -> Any:
        """Attach this context's tracing wrapper to a value.

        Mirrors ts_version ReflectService.trace().
        """
        return _get_traceable(self.ctx, value)

    def bind(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a callback so calls trace this and arguments to this context.

        Mirrors ts_version ReflectService.bind().
        """
        @functools.wraps(callback)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            traced_args = [self.trace(arg) for arg in args]
            traced_kwargs = {k: self.trace(v) for k, v in kwargs.items()}
            return callback(*traced_args, **traced_kwargs)
        return wrapper

