"""Base service class and service lifecycle symbols.

The Service base class provides automatic registration and intercept config resolution.
Services extend this class to gain automatic context integration and lifecycle management.

Key features:
- Automatic registration with ctx.reflect.provide()
- Intercept config resolution from ancestor contexts
- Callable service support via symbols.invoke
- Cross-realm instance checking
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar

from cordis.utils import symbols

if TYPE_CHECKING:
    from cordis.context import Context


class Service(ABC):
    """Base class for services that expose a named API on ctx.

    Subclasses call super().__init__(ctx, name) from their constructor. The service
    is registered immediately and is automatically removed with the owning fiber.

    Mirrors ts_version Service class.
    """

    # Class-level symbol references (mirrors static readonly in TS)
    init: ClassVar[Any] = symbols.init
    check: ClassVar[Any] = symbols.check
    config: ClassVar[Any] = symbols.config
    invoke: ClassVar[Any] = symbols.invoke
    extend: ClassVar[Any] = symbols.extend
    tracker: ClassVar[Any] = symbols.tracker
    resolveConfig: ClassVar[Any] = symbols.resolveConfig

    def __init__(self, ctx: Context, name: str | None = None) -> None:
        """Register this instance as name in the current context.

        Calls ctx.reflect.provide(name, self, self[Service.check]), so the
        service is unregistered automatically when the owning fiber unloads.

        Args:
            ctx: The context to register in (stored as self.ctx).
            name: The service name; defaults to the class's provide attribute.
        """
        if name is None:
            name = getattr(self.__class__, 'provide', None)
            if name is None:
                name = self.__class__.__name__.lower()

        self.ctx = ctx
        self.name = name

        # Set up tracker
        tracker = {
            'associate': name,
            'property': 'ctx',
        }

        # Check if service has invoke method (callable service)
        if getattr(self, symbols.invoke, None) is not None:
            # Make the service callable
            self._make_callable(tracker)

        object.__setattr__(self, symbols.tracker, tracker)

        # Get check predicate
        check_fn = getattr(self, symbols.check, None)

        # Register with reflect
        ctx.reflect.provide(name, self, check_fn)

    def _make_callable(self, tracker: dict) -> None:
        """Make this service instance callable through symbols.invoke."""
        if callable(self):
            return  # Already wrapped

        original_class = self.__class__

        class CallableService(original_class):
            def __call__(self_inner, *args: Any, **kwargs: Any) -> Any:
                invoke = getattr(self, symbols.invoke, None)
                if invoke is not None:
                    return invoke(*args, **kwargs)
                raise TypeError(f"Service '{self.name}' is not callable")

        self.__class__ = CallableService

    def _filter(self, ctx: Context) -> bool:
        """Check if a context is in the same isolation scope as this service.

        Mirrors ts_version Service[symbols.filter]().
        """
        return ctx._isolate.get(self.name) == self.ctx._isolate.get(self.name)

    def _extend(self, props: dict | None = None) -> Service:
        """Create an extended service instance with additional properties.

        Mirrors ts_version Service[symbols.extend]().
        """
        new_instance = object.__new__(self.__class__)
        # Copy instance attributes (not class methods/properties)
        new_instance.__dict__.update(self.__dict__)
        if props:
            new_instance.__dict__.update(props)
        return new_instance

    def _resolve_config(self, base: Any = None, head: Any = None) -> Any:
        """Merge intercept config from ancestors with optional base and head values.

        Walks up the parent context chain collecting intercept configs for this
        service name. Root entries apply first; base is prepended and head appended.
        Uses Config.merge when the service declares one, otherwise shallow merge.

        Mirrors ts_version Service[symbols.resolveConfig]().
        """
        configs: list[Any] = []

        # Walk up the parent context chain collecting intercept configs
        ctx: Context | None = self.ctx
        while ctx is not None:
            intercept = ctx._intercept_map
            if self.name in intercept:
                configs.insert(0, intercept[self.name])
            ctx = ctx._parent

        if base is not None:
            configs.insert(0, base)
        if head is not None:
            configs.append(head)

        # Check for custom merge function
        config_class = getattr(self, 'Config', None)
        if config_class is not None and hasattr(config_class, 'merge'):
            return config_class.merge(*configs)

        # Shallow merge
        result: dict[str, Any] = {}
        for cfg in configs:
            if isinstance(cfg, dict):
                result.update(cfg)
        return result

    @classmethod
    def __instancecheck__(cls, instance: Any) -> bool:
        """Custom instance check for cross-realm support.

        Mirrors ts_version Service[Symbol.hasInstance]().
        """
        if instance is None:
            return False

        # Walk the class hierarchy
        current = type(instance)
        while current is not None:
            if current is cls:
                return True
            current = current.__base__

        return False
