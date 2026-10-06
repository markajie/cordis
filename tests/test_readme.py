#!/usr/bin/env python3
"""
Verify every code example and API listed in cordis/README.md.
Each section is tested independently; failures are collected and reported at the end.
"""

import asyncio
import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cordis import (
    create_context, Context, Service, FiberState,
    symbols, DisposableList,
)

failures = []


def run_test(name, fn):
    """Run a test function, collect failures."""
    try:
        if asyncio.iscoroutinefunction(fn):
            asyncio.run(fn())
        else:
            fn()
        print(f"  [OK] {name}")
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()
        failures.append((name, e))


# =========================================================================
# Quick Start
# =========================================================================
print("\n=== Quick Start ===")


async def test_quick_start():
    ctx = create_context()

    def greeting_plugin(ctx, config):
        name = config.get('name', 'World')
        ctx.logger.info(f"Hello, {name}!")

        def cleanup():
            ctx.logger.info("Goodbye!")
        return cleanup

    fiber = ctx.registry.plugin(greeting_plugin, {'name': 'Cordis'})
    await fiber.await_settled()


run_test("Quick Start example", test_quick_start)


# =========================================================================
# Context
# =========================================================================
print("\n=== Context ===")


def test_context_access():
    ctx = create_context()
    logger = ctx.logger
    registry = ctx.registry
    events = ctx.events
    assert logger is not None
    assert registry is not None
    assert events is not None


run_test("Context service access", test_context_access)


def test_context_child():
    ctx = create_context()
    child = ctx.extend({'custom': 'value'})
    isolated = ctx.isolate('myservice')
    intercepted = ctx.intercept('logger', {'level': 2})
    assert child is not ctx
    assert isolated[symbols.isolate].get('myservice') is not None
    assert intercepted[symbols.intercept].get('logger') == {'level': 2}


run_test("Context extend/isolate/intercept", test_context_child)


def test_context_is():
    ctx = create_context()
    assert Context.is_context(ctx) is True
    assert Context.is_context(None) is False
    assert Context.is_context("string") is False


run_test("Context.is_context()", test_context_is)


def test_context_symbols():
    ctx = create_context()
    iso_map = ctx[symbols.isolate]
    int_map = ctx[symbols.intercept]
    assert isinstance(iso_map, dict)
    assert isinstance(int_map, dict)


run_test("ctx[symbols.isolate/intercept]", test_context_symbols)


# =========================================================================
# Plugins
# =========================================================================
print("\n=== Plugins ===")


async def test_function_plugin():
    ctx = create_context()

    def my_plugin(ctx, config):
        return lambda: None  # disposer

    fiber = ctx.registry.plugin(my_plugin, {})
    await fiber.await_settled()
    assert fiber.state == FiberState.ACTIVE


run_test("Function plugin", test_function_plugin)


async def test_class_plugin():
    ctx = create_context()

    class MyPlugin:
        def __init__(self, ctx, config):
            self.ctx = ctx

        def start(self):
            pass

    fiber = ctx.registry.plugin(MyPlugin, {})
    await fiber.await_settled()


run_test("Class plugin", test_class_plugin)


async def test_object_plugin():
    ctx = create_context()

    class MyPluginObject:
        def apply(self, ctx, config):
            pass

    fiber = ctx.registry.plugin(MyPluginObject(), {})
    await fiber.await_settled()


run_test("Object plugin", test_object_plugin)


# =========================================================================
# Services
# =========================================================================
print("\n=== Services ===")


def test_service_base():
    ctx = create_context()

    class DatabaseService(Service):
        def __init__(self, ctx):
            super().__init__(ctx, 'database')
            self.connection = None

        def connect(self):
            self.connection = "mock_connection"

        def query(self, sql):
            return f"result of {sql}"

    svc = DatabaseService(ctx)
    db = ctx.reflect.get('database')
    assert db is not None


run_test("Service base class + reflect.get", test_service_base)


# =========================================================================
# Events
# =========================================================================
print("\n=== Events ===")


def test_events_on_emit():
    ctx = create_context()
    received = []
    dispose = ctx.events.on('user/login', lambda user: received.append(user))
    ctx.events.emit('user/login', 'alice')
    assert received == ['alice']
    dispose()
    ctx.events.emit('user/login', 'charlie')
    assert received == ['alice']  # Not received after dispose


run_test("events.on + emit + dispose", test_events_on_emit)


async def test_events_parallel():
    ctx = create_context()
    results = []

    async def listener(user):
        results.append(user)

    ctx.events.on('user/login', listener)
    await ctx.events.parallel('user/login', 'bob')
    assert results == ['bob']


run_test("events.parallel", test_events_parallel)


async def test_events_serial():
    ctx = create_context()
    results = []

    async def listener(data):
        results.append(data)
        return None  # No bail

    ctx.events.on('check', listener)
    result = await ctx.events.serial('check', 'test_data')
    assert results == ['test_data']


run_test("events.serial", test_events_serial)


def test_events_bail():
    ctx = create_context()

    def validator(input_val):
        if input_val == 'bad':
            return 'invalid'
        return None

    ctx.events.on('validate', validator)
    result = ctx.events.bail('validate', 'good')
    assert result is None
    result = ctx.events.bail('validate', 'bad')
    assert result == 'invalid'


run_test("events.bail", test_events_bail)


def test_events_waterfall():
    ctx = create_context()

    def transformer(data, next_fn):
        return next_fn()

    ctx.events.on('transform', transformer)

    def inner():
        return 'original'

    result = ctx.events.waterfall('transform', 'data', inner=inner)
    assert result == 'original'


run_test("events.waterfall with inner=", test_events_waterfall)


# =========================================================================
# Effects and Cleanup
# =========================================================================
print("\n=== Effects and Cleanup ===")


async def test_effects():
    ctx = create_context()
    cleaned_up = []

    def my_plugin(ctx, config):
        resource = "my_resource"

        def dispose():
            cleaned_up.append(resource)

        ctx.fiber.effect(lambda: dispose, "release resource")
        return dispose

    fiber = ctx.registry.plugin(my_plugin, {})
    await fiber.await_settled()
    assert len(cleaned_up) == 0

    await fiber.dispose()
    assert "my_resource" in cleaned_up


run_test("Effects and cleanup", test_effects)


# =========================================================================
# Logging
# =========================================================================
print("\n=== Logging ===")


def test_logging_basic():
    ctx = create_context()
    logger = ctx.logger('my-component')
    logger.debug("Debug info")
    logger.info("Information")
    logger.warn("Warning")
    logger.error("Error")


run_test("Logging basic levels", test_logging_basic)


def test_logging_custom_exporter():
    ctx = create_context()
    exported = []

    class FileExporter:
        colors = None
        max_length = 10240
        levels = None
        formatters = None

        def export(self, message):
            exported.append(f"{message.ts} [{message.type}] {message.name}: {message.args}")

    ctx.logger.exporter(FileExporter())
    ctx.logger.info("test message")
    assert len(exported) > 0


run_test("Custom exporter", test_logging_custom_exporter)


# =========================================================================
# API Reference - Fiber
# =========================================================================
print("\n=== API Reference: Fiber ===")


async def test_fiber_api():
    ctx = create_context()

    def p(ctx, config):
        return lambda: None

    p.name = 'test-fiber-api'
    fiber = ctx.registry.plugin(p, {})
    await fiber.await_settled()

    # fiber.name
    assert isinstance(fiber.name, str)

    # fiber.state
    assert fiber.state == FiberState.ACTIVE

    # fiber.effect
    disposed = []
    fiber.effect(lambda: lambda: disposed.append(1), "test effect")

    # fiber.get_effects
    effects = fiber.get_effects()
    assert isinstance(effects, list)

    # fiber.await_settled
    await fiber.await_settled()

    # fiber.update
    fiber.update({'new': 'config'})
    await fiber.await_settled()

    # fiber.restart
    await fiber.restart()


run_test("Fiber API (name/state/effect/get_effects/await_settled/update/restart)", test_fiber_api)


# =========================================================================
# API Reference: EventsService
# =========================================================================
print("\n=== API Reference: EventsService ===")


async def test_events_once():
    ctx = create_context()
    received = []
    ctx.events.once('one-shot', lambda msg: received.append(msg))
    ctx.events.emit('one-shot', 'first')
    ctx.events.emit('one-shot', 'second')
    assert received == ['first']


run_test("events.once", test_events_once)


# =========================================================================
# API Reference: ReflectService
# =========================================================================
print("\n=== API Reference: ReflectService ===")


def test_reflect_provide_get_set():
    ctx = create_context()
    ctx.reflect.provide('test-svc', 42)
    val = ctx.reflect.get('test-svc', strict=False)
    assert val == 42
    ctx.reflect.set('test-svc', 99)
    val2 = ctx.reflect.get('test-svc', strict=False)
    assert val2 == 99


run_test("reflect.provide/get/set", test_reflect_provide_get_set)


def test_reflect_accessor():
    ctx = create_context()
    _value = [10]
    ctx.reflect.accessor(
        'computed',
        get=lambda receiver, error: _value[0],
        set=lambda v, receiver, error: (_value.__setitem__(0, v), True)[1],
    )
    val = ctx.reflect.get('computed', strict=False)
    assert val == 10


run_test("reflect.accessor", test_reflect_accessor)


def test_reflect_notify():
    ctx = create_context()
    ctx.reflect.provide('notify-svc', 'hello')
    fibers = ctx.reflect.notify(['notify-svc'])
    assert isinstance(fibers, list)


run_test("reflect.notify", test_reflect_notify)


def test_reflect_trace_bind():
    ctx = create_context()
    traced = ctx.reflect.trace(42)
    assert traced == 42  # Non-traceable values pass through

    bound = ctx.reflect.bind(lambda x: x * 2)
    assert bound(5) == 10


run_test("reflect.trace/bind", test_reflect_trace_bind)


# =========================================================================
# API Reference: RegistryService
# =========================================================================
print("\n=== API Reference: RegistryService ===")


async def test_registry_api():
    ctx = create_context()

    def p1(ctx, config):
        return lambda: None

    # registry.plugin
    fiber = ctx.registry.plugin(p1, {})
    await fiber.await_settled()

    # registry.has
    assert ctx.registry.has(p1) is True

    # registry.get
    runtime = ctx.registry.get(p1)
    assert runtime is not None

    # registry.resolve
    cb = ctx.registry.resolve(p1)
    assert cb is p1

    # registry.delete
    ctx.registry.delete(p1)
    assert ctx.registry.has(p1) is False


run_test("registry.plugin/has/get/resolve/delete", test_registry_api)


async def test_registry_inject():
    ctx = create_context()

    # Provide a service first
    ctx.reflect.provide('dep-svc', 'dep-value')

    called = []

    def callback(ctx):
        called.append(True)
        return lambda: None

    fiber = ctx.registry.inject(['dep-svc'], callback)
    await fiber.await_settled()


run_test("registry.inject", test_registry_inject)


# =========================================================================
# API Reference: LoggerService
# =========================================================================
print("\n=== API Reference: LoggerService ===")


def test_logger_service_api():
    ctx = create_context()

    # logger(name?)
    named = ctx.logger('custom-name')
    assert named.name == 'custom-name'

    default = ctx.logger()
    assert default is not None

    # logger.error/info/warn/debug
    ctx.logger.error("err")
    ctx.logger.info("inf")
    ctx.logger.warn("wrn")
    ctx.logger.debug("dbg")


run_test("LoggerService API", test_logger_service_api)


# =========================================================================
# API Reference: Service
# =========================================================================
print("\n=== API Reference: Service ===")


def test_service_api():
    ctx = create_context()

    class MySvc(Service):
        def __init__(self, ctx):
            super().__init__(ctx, 'my-svc')

    svc = MySvc(ctx)
    assert svc.name == 'my-svc'
    assert svc.ctx is ctx


run_test("Service.name / Service.ctx", test_service_api)


# =========================================================================
# API Reference: Symbols
# =========================================================================
print("\n=== API Reference: Symbols ===")


def test_symbols():
    assert symbols.tracker == "_cordis_tracker"
    assert symbols.invoke == "_cordis_invoke"
    assert symbols.effect == "_cordis_effect"
    assert symbols.filter == "_cordis_filter"
    assert symbols.isolate == "_cordis_isolate"
    assert symbols.intercept == "_cordis_intercept"
    assert symbols.init == "_cordis_init"
    assert symbols.check == "_cordis_check"
    assert symbols.config == "_cordis_config"
    assert symbols.shadow == "_cordis_shadow"
    assert symbols.original == "_cordis_original"


run_test("All symbols exist", test_symbols)


# =========================================================================
# API Reference: DisposableList
# =========================================================================
print("\n=== API Reference: DisposableList ===")


def test_disposable_list():
    dl = DisposableList()

    # push
    r1 = dl.push("a")
    r2 = dl.push("b")
    assert len(dl) == 2

    # iter
    assert list(dl) == ["a", "b"]

    # delete
    assert dl.delete("a") is True
    assert len(dl) == 1

    # clear
    dl.push("c")
    cleared = dl.clear()
    assert cleared == ["c", "b"]  # Reverse order
    assert len(dl) == 0


run_test("DisposableList push/delete/clear/len/iter", test_disposable_list)


# =========================================================================
# API Reference: New APIs (fibers, provide)
# =========================================================================
print("\n=== API Reference: New APIs ===")


async def test_registry_fibers():
    ctx = create_context()

    def p(ctx, config):
        return lambda: None

    p.name = 'fibers-test'
    fiber = ctx.registry.plugin(p, {})
    await fiber.await_settled()

    fibers = ctx.registry.fibers
    assert isinstance(fibers, list)
    assert any(f.name == 'fibers-test' for f in fibers)


run_test("registry.fibers property", test_registry_fibers)


async def test_fiber_provide():
    ctx = create_context()

    class Svc(Service):
        def __init__(self, ctx):
            super().__init__(ctx, 'prov-test')

    def p(ctx, config):
        Svc(ctx)
        return lambda: None

    p.name = 'provide-test'
    fiber = ctx.registry.plugin(p, {})
    await fiber.await_settled()

    prov = fiber.provide
    assert isinstance(prov, list)
    assert 'prov-test' in prov


run_test("fiber.provide property", test_fiber_provide)


# =========================================================================
# ctx.plugin shorthand
# =========================================================================
print("\n=== ctx.registry.plugin ===")


async def test_registry_plugin():
    """Verify ctx.registry.plugin() works for loading plugins."""
    ctx = create_context()

    def p(ctx, config):
        return lambda: None

    fiber = ctx.registry.plugin(p, {})
    await fiber.await_settled()
    assert fiber.state == FiberState.ACTIVE


run_test("ctx.registry.plugin()", test_registry_plugin)


# =========================================================================
# Summary
# =========================================================================
print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} test(s)")
    for name, err in failures:
        print(f"  - {name}: {err}")
    sys.exit(1)
else:
    print("All README examples and APIs verified! [OK]")
print("=" * 60)
