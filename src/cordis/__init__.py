"""Cordis: A Python plugin framework with dependency injection and lifecycle management.

Cordis provides a context-based plugin system with service resolution, event dispatch,
and fiber-based lifecycle management. It enables building modular applications where
components can be dynamically loaded, unloaded, and reconfigured at runtime.

Key features:
- Context-based dependency injection
- Five event dispatch modes (emit, parallel, serial, bail, waterfall)
- Fiber lifecycle management with automatic cleanup
- Service registration and resolution
- Hot-reload support through plugin unloading/reloading

Usage:
    from cordis import create_context

    # Create root context
    ctx = create_context()

    # Define a plugin
    def my_plugin(ctx, config):
        ctx.logger.info("Plugin loaded!")
        return lambda: ctx.logger.info("Plugin unloaded")

    # Load plugin
    ctx.plugin(my_plugin, {})

Public API:
    - Context: The central dependency container
    - Fiber: Plugin runtime instance with lifecycle management
    - EventsService: Event bus with multiple dispatch modes
    - ReflectService: Service registration and resolution
    - RegistryService: Plugin management and dependency injection
    - LoggerService: Structured logging with exporters
    - Service: Base class for services
"""

from __future__ import annotations

# Core types and classes
from cordis.context import Context
from cordis.fiber import (
    CordisError,
    Disposable,
    Effect,
    EffectMeta,
    Fiber,
    FiberState,
    ValidationError,
    resolve_config,
)
from cordis.events import (
    DispatchMode,
    EventOptions,
    EventsService,
    Hook,
    is_bailed,
)
from cordis.reflect import (
    Impl,
    Property,
    PropertyAccessor,
    PropertyService,
    ReflectService,
)
from cordis.registry import (
    Inject,
    Plugin,
    PluginRuntime,
    RegistryService,
    inject_decorator,
    resolve_inject,
)
from cordis.service import Service
from cordis.logger import (
    C16,
    C256,
    DEFAULT_FORMATTERS,
    Exporter,
    Formatter,
    Logger,
    LoggerLevel,
    LoggerService,
    LoggerType,
    Message,
)
from cordis.utils import DisposableList, symbols

__all__ = [
    # Context
    'Context',

    # Fiber
    'Fiber',
    'FiberState',
    'CordisError',
    'ValidationError',
    'Disposable',
    'Effect',
    'EffectMeta',
    'resolve_config',

    # Events
    'EventsService',
    'DispatchMode',
    'EventOptions',
    'Hook',
    'is_bailed',

    # Reflect
    'ReflectService',
    'Impl',
    'Property',
    'PropertyService',
    'PropertyAccessor',

    # Registry
    'RegistryService',
    'Plugin',
    'PluginRuntime',
    'Inject',
    'inject_decorator',
    'resolve_inject',

    # Service
    'Service',

    # Logger
    'LoggerService',
    'Logger',
    'LoggerType',
    'LoggerLevel',
    'Message',
    'Exporter',
    'Formatter',
    'DEFAULT_FORMATTERS',
    'C16',
    'C256',

    # Utils (only public symbols and DisposableList)
    'symbols',
    'DisposableList',
]


def create_context() -> Context:
    """Create a new root context with all built-in services initialized.

    Returns:
        A fully initialized Context instance ready for plugin registration.

    Example:
        >>> ctx = create_context()
        >>> ctx.logger.info("Hello, World!")
    """
    from cordis.context import _init_root_context
    return _init_root_context()
