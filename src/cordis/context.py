"""Core context type and root context implementation.

The Context class is the central dependency container for Cordis plugins.
It provides service resolution through attribute access and supports
creating child contexts with isolated scopes or intercept configurations.

Key features:
- Service resolution via __getattr__ (delegates to ReflectService)
- Child context creation via extend(), isolate(), intercept()
- Symbol-keyed access for internal maps (__getitem__/__setitem__)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cordis.utils import symbols


if TYPE_CHECKING:
    from cordis.events import EventsService
    from cordis.fiber import Fiber
    from cordis.logger import LoggerService
    from cordis.reflect import ReflectService
    from cordis.registry import RegistryService


# Brand marker for Context.is() check
_CORDIS_CONTEXT_BRAND = object()


class Context:
    """Root and child dependency containers for Cordis plugins.

    A context provides service resolution through attribute access.
    Property reads go through the service resolver (reflect),
    while extend(), isolate(), and intercept() create scoped child
    contexts without mutating their parent.
    """

    # Class-level symbol references (mirrors static readonly in TS)
    effect = symbols.effect
    filter = symbols.filter
    isolate = symbols.isolate
    intercept = symbols.intercept

    def __init__(self) -> None:
        """Create the root context and install the built-in services."""
        # __setattr__ falls back to object.__setattr__ when reflect is None,
        # so plain assignment is safe during initialization.
        self._isolate_map: dict[str, Any] = {}
        self._intercept_map: dict[str, Any] = {}
        self._brand = _CORDIS_CONTEXT_BRAND
        self.root: Context = self
        self.baseUrl: Any = None
        self.fiber: Any = None
        self.reflect: Any = None
        self.registry: Any = None
        self.events: Any = None
        self.logger: Any = None
        self._parent: Context | None = None
        self._loading_fiber: Any = None

    @staticmethod
    def is_context(value: Any) -> bool:
        """Returns true for Cordis context instances.

        Works across realms and across multiple copies of cordis, because the
        brand is keyed by a unique object rather than by isinstance.
        
        Note: Use Context.is_context() instead of Context.is() since 'is' is
        a reserved keyword in Python.
        """
        if value is None:
            return False
        return getattr(value, '_brand', None) is _CORDIS_CONTEXT_BRAND

    def __repr__(self) -> str:
        fiber = object.__getattribute__(self, 'fiber')
        name = fiber.name if fiber is not None else 'root'
        return f"Context <{name}>"

    def __getattr__(self, name: str) -> Any:
        """Resolve service properties through the reflect service.

        This is the Python equivalent of the Proxy handler's get trap.
        Only called when the attribute is not found through normal lookup.
        """
        # Avoid infinite recursion for internal attributes
        if name.startswith('_'):
            raise AttributeError(name)

        reflect = object.__getattribute__(self, 'reflect')
        if reflect is not None:
            return reflect.get(name, strict=True)

        raise AttributeError(f"Context has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Set service properties through the reflect service.

        This is the Python equivalent of the Proxy handler's set trap.
        """
        # Internal attributes use object.__setattr__
        if name.startswith('_') or name in ('root', 'baseUrl', 'fiber', 'reflect', 'registry', 'events', 'logger'):
            object.__setattr__(self, name, value)
            return

        reflect = object.__getattribute__(self, 'reflect')
        if reflect is not None:
            reflect.set(name, value)
        else:
            object.__setattr__(self, name, value)

    def extend(self, meta: dict | None = None) -> Context:
        """Create a child context with extra metadata on top of the current scope.

        The child inherits every property of this context; own
        properties of meta shadow the inherited ones. The parent is not mutated.
        """
        if meta is None:
            meta = {}

        # Create a new context that inherits from this one
        child = Context.__new__(Context)

        # Copy all attributes from parent via __dict__ (bypasses custom __setattr__)
        child.__dict__.update(self.__dict__)
        child._parent = self

        # Apply meta overrides
        for key, value in meta.items():
            if key == symbols.isolate:
                child._isolate_map = value
            elif key == symbols.intercept:
                child._intercept_map = value
            else:
                child.__dict__[key] = value

        return child

    def isolate(self, name: str, label: Any = None) -> Context:
        """Create a child context with an independent service scope for name.

        Below the returned context, reads and writes of the service name
        resolve against the new label instead of the parent's, so a different
        implementation can be provided without affecting the parent scope.
        Passing the same label to two isolate() calls joins their scopes.
        """
        # Create new isolate map inheriting from parent
        parent_isolate = object.__getattribute__(self, '_isolate_map')
        new_isolate = dict(parent_isolate)

        # Generate a unique label if not provided
        if label is None:
            label = object()  # Unique sentinel

        new_isolate[name] = label

        return self.extend({symbols.isolate: new_isolate})

    def intercept(self, name: str, config: Any) -> Context:
        """Add service-specific intercept config for plugins started below this context.

        Plugins loaded under the returned context see config merged into the
        service's resolved config (ancestor entries first). The parent context
        is not affected.
        """
        # Create new intercept map inheriting from parent
        parent_intercept = object.__getattribute__(self, '_intercept_map')
        new_intercept = dict(parent_intercept)
        new_intercept[name] = config

        return self.extend({symbols.intercept: new_intercept})

    # -----------------------------------------------------------------------
    # Properties for accessing isolate/intercept maps (private interface)
    # -----------------------------------------------------------------------

    @property
    def _isolate(self) -> dict:
        """Get the isolate map (private interface)."""
        return self._isolate_map

    @property
    def _intercept(self) -> dict:
        """Get the intercept map (private interface)."""
        return self._intercept_map

    def __getitem__(self, key: Any) -> Any:
        """Support symbol-keyed access: ctx[symbols.isolate], ctx[symbols.intercept]."""
        if key is symbols.isolate:
            return self._isolate_map
        if key is symbols.intercept:
            return self._intercept_map
        if key is symbols.shadow:
            return self.__dict__.get(symbols.shadow)
        raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        """Support symbol-keyed assignment."""
        if key is symbols.isolate:
            self._isolate_map = value
        elif key is symbols.intercept:
            self._intercept_map = value
        elif key is symbols.shadow:
            self.__dict__[symbols.shadow] = value
        else:
            raise KeyError(key)


def _init_root_context() -> Context:
    """Initialize the root context with all built-in services.

    This function is called after all service modules are imported to avoid
    circular dependencies. It creates the root context and wires up all services.
    """
    # Import here to avoid circular imports
    from cordis.events import EventsService
    from cordis.fiber import Fiber
    from cordis.logger import LoggerService
    from cordis.reflect import ReflectService
    from cordis.registry import RegistryService

    ctx = Context()

    # Create the root fiber first (with empty inject and null runtime)
    fiber = Fiber(ctx, {}, {}, None, lambda: [])
    object.__setattr__(ctx, 'fiber', fiber)

    # Initialize services
    reflect = ReflectService(ctx)
    object.__setattr__(ctx, 'reflect', reflect)

    registry = RegistryService(ctx)
    object.__setattr__(ctx, 'registry', registry)

    events = EventsService(ctx)
    object.__setattr__(ctx, 'events', events)

    logger = LoggerService(ctx)
    object.__setattr__(ctx, 'logger', logger)

    # Clear root fiber's disposables (it's special)
    fiber._disposables.clear()

    return ctx
