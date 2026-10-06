# Cordis Python Framework

## Overview

Cordis is a Python plugin framework with dependency injection and lifecycle management. It provides a context-based plugin system with service resolution, event dispatch, and fiber-based lifecycle management.

## Architecture

### Core Components

1. **Context** - The central dependency container
   - Service resolution via attribute access
   - Child context creation (extend, isolate, intercept)
   - Symbol-keyed access for internal maps

2. **Fiber** - Plugin runtime instance
   - Lifecycle states: PENDING → LOADING → ACTIVE → UNLOADING → DISPOSED/FAILED
   - Effect system for resource management
   - Dependency tracking and refresh

3. **EventsService** - Event bus with five dispatch modes
   - emit: Synchronous fire-and-forget
   - parallel: Concurrent execution
   - serial: Sequential with bail support
   - bail: Synchronous bail on first value
   - waterfall: Chain listeners around callback

4. **ReflectService** - Service registration and resolution
   - provide() for service registration
   - get()/set() for service access
   - accessor() for computed properties
   - mixin() for exposing service methods

5. **RegistryService** - Plugin management
   - plugin() for loading plugins
   - inject() for dependency injection
   - Runtime tracking and lifecycle

6. **LoggerService** - Structured logging
   - Named loggers
   - Severity levels (error, info, warn, debug)
   - Configurable exporters

7. **Service** - Base class for services
   - Automatic registration
   - Intercept config resolution
   - Callable service support

## Public API

### Context

```python
from cordis import create_context

ctx = create_context()

# Create child contexts
child = ctx.extend({'custom': 'value'})
isolated = ctx.isolate('myservice')
intercepted = ctx.intercept('logger', {'level': 2})

# Access services
service = ctx.reflect.get('myservice', strict=False)
```

### Events

```python
# Register listener
dispose = ctx.events.on('my/event', lambda msg: print(msg))

# Dispatch events
ctx.events.emit('my/event', 'hello')           # sync
await ctx.events.parallel('my/event', 'data')  # async concurrent
result = ctx.events.bail('my/event', 'check')  # sync bail
```

### Plugins

```python
# Function plugin
def my_plugin(ctx, config):
    ctx.logger.info("Loaded!")
    return lambda: ctx.logger.info("Unloaded")

fiber = ctx.plugin(my_plugin, {'key': 'value'})
await fiber.await_settled()

# Class plugin
class MyPlugin:
    def __init__(self, ctx, config):
        self.ctx = ctx
    
    def start(self):
        pass

fiber = ctx.plugin(MyPlugin, {})
```

### Services

```python
from cordis import Service

class MyService(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'my-service')
        self.value = 42

# Service is automatically registered
svc = ctx.reflect.get('my-service')
```

### Logging

```python
# Get named logger
logger = ctx.logger('my-component')

# Log messages
logger.info("Information message")
logger.error("Error occurred")
logger.debug("Debug details")

# Register custom exporter
def my_exporter(message):
    print(f"[{message.type}] {message.name}: {message.args}")

ctx.logger.exporter(my_exporter)
```

## Symbols

Internal symbols are string constants with `_cordis_` prefix:

```python
from cordis import symbols

# Access symbol values
symbols.tracker    # "_cordis_tracker"
symbols.invoke     # "_cordis_invoke"
symbols.effect     # "_cordis_effect"
```

## DisposableList

O(1) deletion collection for managing disposers:

```python
from cordis import DisposableList

dl = DisposableList()
remove = dl.push(some_disposable)

# Later
remove()  # Remove specific item
items = dl.clear()  # Get all in reverse order
```

## File Structure

```
cordis/
├── src/
│   └── cordis/
│       ├── __init__.py      # Public exports
│       ├── utils.py         # symbols, DisposableList
│       ├── context.py       # Context class
│       ├── events.py        # EventsService
│       ├── fiber.py         # Fiber class
│       ├── reflect.py       # ReflectService
│       ├── registry.py      # RegistryService
│       ├── service.py       # Service base class
│       └── logger.py        # LoggerService
├── tests/                   # Test files
└── README.md               # This file
```

## Design Principles

1. **Simplicity** - Keep related code together, minimize indirection
2. **Pythonic** - Use Python native features (dataclass, AsyncExitStack, etc.)
3. **Explicit** - Avoid magic, make behavior clear
4. **Testable** - Each component can be tested independently

## Testing

Run tests with:

```bash
cd cordis
python src/tests/test_basic.py
```

All 12 core tests should pass:
- Context creation and methods
- EventsService dispatch modes
- LoggerService functionality
- Service base class
- RegistryService plugin loading
- ReflectService provide/get
