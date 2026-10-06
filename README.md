# Cordis

A Python plugin framework with dependency injection and lifecycle management.

## Installation

```bash
# From source
cd cordis
pip install -e .
```

## Quick Start

```python
from cordis import create_context

# Create root context
ctx = create_context()

# Define a simple plugin
def greeting_plugin(ctx, config):
    name = config.get('name', 'World')
    ctx.logger.info(f"Hello, {name}!")
    
    # Return cleanup function
    def cleanup():
        ctx.logger.info("Goodbye!")
    return cleanup

# Load the plugin
fiber = ctx.registry.plugin(greeting_plugin, {'name': 'Cordis'})

# Wait for plugin to be ready
import asyncio
asyncio.run(fiber.await_settled())
```

## Core Concepts

### Context

The Context is the central dependency container. It holds services and provides access to them via attribute resolution.

```python
ctx = create_context()

# Access services
logger = ctx.logger
registry = ctx.registry
events = ctx.events

# Create child contexts
child = ctx.extend({'custom': 'value'})
isolated = ctx.isolate('myservice')  # Independent scope
intercepted = ctx.intercept('logger', {'level': 2})  # Config override
```

### Plugins

Plugins are functions, classes, or objects that receive a context and configuration.

```python
# Function plugin
def my_plugin(ctx, config):
    # Setup code here
    return lambda: print("Cleanup")  # Return disposer

# Class plugin
class MyPlugin:
    def __init__(self, ctx, config):
        self.ctx = ctx
    
    def start(self):
        pass

# Object plugin
class MyPluginObject:
    def apply(self, ctx, config):
        pass

# Load plugins
ctx.registry.plugin(my_plugin, {})
ctx.registry.plugin(MyPlugin, {})
ctx.registry.plugin(MyPluginObject(), {})
```

### Services

Services extend the Service base class for automatic registration.

```python
from cordis import Service

class DatabaseService(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'database')
        self.connection = None
    
    def connect(self):
        self.connection = create_connection()
    
    def query(self, sql):
        return self.connection.execute(sql)

# Service is automatically registered as 'database'
db = ctx.reflect.get('database')
```

### Events

The event system supports five dispatch modes.

```python
# Register listener
dispose = ctx.events.on('user/login', lambda user: print(f"{user} logged in"))

# Dispatch modes
ctx.events.emit('user/login', 'alice')              # Sync, fire-and-forget
await ctx.events.parallel('user/login', 'bob')      # Async, all listeners
result = await ctx.events.serial('check', data)     # Async, stop on bail
result = ctx.events.bail('validate', input)         # Sync, stop on bail
result = ctx.events.waterfall('transform', data, fn) # Chain listeners

# Remove listener
dispose()
```

### Effects and Cleanup

Effects manage resources with automatic cleanup when fibers unload.

```python
def my_plugin(ctx, config):
    # Acquire resource
    resource = acquire_resource()
    
    # Register cleanup via effect (execute returns a disposer)
    ctx.fiber.effect(lambda: lambda: release_resource(resource), "release resource")
    
    # Or return disposer directly from the plugin
    return lambda: release_resource(resource)
```

### Logging

```python
# Get named logger
logger = ctx.logger('my-component')

# Log at different levels
logger.debug("Debug info")
logger.info("Information")
logger.warn("Warning")
logger.error("Error")

# Custom exporter
class FileExporter:
    def export(self, message):
        with open('app.log', 'a') as f:
            f.write(f"{message.ts} [{message.type}] {message.name}: {message.args}\n")

ctx.logger.exporter(FileExporter())
```

## API Reference

### Context

- `create_context()` - Create root context
- `Context.is_context(value)` - Check if value is a Context
- `ctx.extend(meta)` - Create child context with metadata
- `ctx.isolate(name, label?)` - Create isolated scope
- `ctx.intercept(name, config)` - Add intercept config
- `ctx[symbols.isolate]` - Access isolate map
- `ctx[symbols.intercept]` - Access intercept map

### Fiber

- `fiber.name` - Plugin display name
- `fiber.state` - Current lifecycle state
- `fiber.effect(execute, label?)` - Register effect
- `fiber.get_effects()` - Get effect metadata
- `fiber.await_settled()` - Wait for lifecycle to settle
- `fiber.restart()` - Restart plugin
- `fiber.update(config)` - Update plugin config

### EventsService

- `events.on(name, listener, options?)` - Register listener
- `events.once(name, listener, options?)` - Register one-time listener
- `events.emit(name, *args)` - Synchronous dispatch
- `events.parallel(name, *args)` - Concurrent async dispatch
- `events.serial(name, *args)` - Sequential async dispatch
- `events.bail(name, *args)` - Synchronous bail dispatch
- `events.waterfall(name, *args)` - Chain dispatch

### ReflectService

- `reflect.get(name, strict?)` - Get service
- `reflect.set(name, value)` - Set service value
- `reflect.provide(name, value?, check?)` - Register service
- `reflect.accessor(name, get, set?)` - Define accessor
- `reflect.mixin(source, mixins)` - Expose service methods
- `reflect.notify(names)` - Notify dependents
- `reflect.trace(value)` - Wrap value for tracing
- `reflect.bind(callback)` - Bind callback to context

### RegistryService

- `registry.plugin(plugin, config?)` - Load plugin
- `registry.inject(deps, callback)` - Inject dependencies
- `registry.resolve(plugin)` - Resolve plugin to callback
- `registry.get(plugin)` - Get plugin runtime
- `registry.has(plugin)` - Check if plugin exists
- `registry.delete(plugin)` - Unload plugin

### LoggerService

- `logger(name?)` - Get named logger
- `logger.exporter(exp)` - Register exporter
- `logger.error/info/warn/debug(...)` - Log messages

### Service

- `Service(ctx, name?)` - Base class constructor
- `service.name` - Service name
- `service.ctx` - Context reference

### Symbols

String constants for internal use:
- `symbols.tracker`, `symbols.invoke`, `symbols.effect`
- `symbols.filter`, `symbols.isolate`, `symbols.intercept`
- `symbols.init`, `symbols.check`, `symbols.config`
- `symbols.shadow`, `symbols.original`, `symbols.receiver`

### DisposableList

- `dl.push(value)` - Add item, return remover
- `dl.delete(value)` - Remove specific item
- `dl.clear()` - Remove all, return in reverse order
- `len(dl)` - Get count
- `iter(dl)` - Iterate items

## Design Principles

1. **Simplicity** - Keep related code together, minimize indirection
2. **Pythonic** - Use native Python features (dataclass, async/await, etc.)
3. **Explicit** - Avoid magic, make behavior clear and predictable
4. **Testable** - Each component can be tested independently

## Testing

```bash
cd cordis
python src/tests/test_basic.py
```

## License

MIT
