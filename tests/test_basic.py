#!/usr/bin/env python3
"""
Basic test for cordis Python implementation.
Tests the core interfaces matching ts_version.
"""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cordis import Context, FiberState, Service, create_context, symbols


def test_context_creation():
    """Test that Context can be created."""
    print("Test 1: Context creation...")
    ctx = create_context()
    assert ctx is not None
    assert ctx.fiber is not None
    assert ctx.reflect is not None
    assert ctx.registry is not None
    assert ctx.events is not None
    assert ctx.logger is not None
    print("  [OK] Context created with all services")


def test_context_is():
    """Test Context.is_context() method."""
    print("\nTest 2: Context.is_context()...")
    ctx = create_context()
    assert Context.is_context(ctx) == True
    assert Context.is_context(None) == False
    assert Context.is_context("not a context") == False
    print("  [OK] Context.is_context() works correctly")


def test_context_extend():
    """Test Context.extend()."""
    print("\nTest 3: Context.extend()...")
    ctx = create_context()
    child = ctx.extend({'custom': 'value'})
    assert child is not ctx
    assert child.root is ctx.root
    print("  [OK] Context.extend() works correctly")


def test_context_isolate():
    """Test Context.isolate()."""
    print("\nTest 4: Context.isolate()...")
    ctx = create_context()
    isolated = ctx.isolate('myservice')
    # Use __getitem__ to access isolate map
    assert isolated[symbols.isolate].get('myservice') is not None
    print("  [OK] Context.isolate() works correctly")


def test_context_intercept():
    """Test Context.intercept()."""
    print("\nTest 5: Context.intercept()...")
    ctx = create_context()
    intercepted = ctx.intercept('myservice', {'key': 'value'})
    # Use __getitem__ to access intercept map
    assert intercepted[symbols.intercept].get('myservice') == {'key': 'value'}
    print("  [OK] Context.intercept() works correctly")


def test_fiber_state():
    """Test FiberState enum."""
    print("\nTest 6: FiberState enum...")
    assert FiberState.PENDING == 0
    assert FiberState.LOADING == 1
    assert FiberState.ACTIVE == 2
    assert FiberState.FAILED == 3
    assert FiberState.DISPOSED == 4
    assert FiberState.UNLOADING == 5
    print("  [OK] FiberState enum values correct")


def test_events_service():
    """Test EventsService basic functionality."""
    print("\nTest 7: EventsService...")
    ctx = create_context()
    
    # Test on/emit
    received = []
    def listener(msg):
        received.append(msg)
    
    dispose = ctx.events.on('test/event', listener)
    ctx.events.emit('test/event', 'hello')
    assert len(received) == 1, f"Expected 1 message, got {len(received)}"
    assert received[0] == 'hello'
    
    # Test dispose - need to run in event loop since dispose is async
    result = dispose()
    if result is not None and asyncio.iscoroutine(result):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(result)
        finally:
            loop.close()
    
    ctx.events.emit('test/event', 'world')
    assert len(received) == 1, f"Expected 1 message after dispose, got {len(received)}"
    
    print("  [OK] EventsService on/emit/dispose works")


async def test_async_events():
    """Test async event dispatch."""
    print("\nTest 8: Async events...")
    ctx = create_context()
    
    results = []
    
    async def async_listener(msg):
        await asyncio.sleep(0.01)
        results.append(msg)
    
    ctx.events.on('async/event', async_listener)
    await ctx.events.parallel('async/event', 'test')
    
    assert len(results) == 1
    assert results[0] == 'test'
    print("  [OK] Async events work correctly")


def test_logger():
    """Test LoggerService."""
    print("\nTest 9: LoggerService...")
    ctx = create_context()
    
    # Test callable logger
    logger = ctx.logger('test-logger')
    assert logger.name == 'test-logger'
    
    # Test severity methods exist
    assert hasattr(logger, 'error')
    assert hasattr(logger, 'info')
    assert hasattr(logger, 'warn')
    assert hasattr(logger, 'debug')
    
    # Test logging (should not raise)
    logger.info("Test message")
    
    print("  [OK] LoggerService works correctly")


def test_service_base():
    """Test Service base class."""
    print("\nTest 10: Service base class...")
    
    class MyService(Service):
        def __init__(self, ctx):
            super().__init__(ctx, 'my-service')
            self.value = 42
    
    ctx = create_context()
    svc = MyService(ctx)
    
    assert svc.name == 'my-service'
    assert svc.ctx is ctx
    
    # Service should be registered - check via reflect store directly
    impl = ctx.reflect._get_impl('my-service', strict=False)
    assert impl is not None, "Service should be registered in reflect store"
    assert impl.value is svc, "Registered value should be the service instance"
    
    print("  [OK] Service base class works correctly")


def test_registry():
    """Test RegistryService."""
    print("\nTest 11: RegistryService...")
    ctx = create_context()
    
    # Test plugin registration
    def my_plugin(ctx, config):
        pass
    
    fiber = ctx.registry.plugin(my_plugin, {})
    assert fiber is not None
    assert fiber.uid is not None
    
    # Test has/get
    assert ctx.registry.has(my_plugin) == True
    runtime = ctx.registry.get(my_plugin)
    assert runtime is not None
    
    print("  [OK] RegistryService works correctly")


def test_reflect_provide():
    """Test ReflectService.provide()."""
    print("\nTest 12: ReflectService.provide()...")
    ctx = create_context()
    
    # Provide a service
    effect_dispose = ctx.reflect.provide('test-service', {'key': 'value'})
    
    # Should be retrievable
    value = ctx.reflect.get('test-service', strict=False)
    assert value == {'key': 'value'}, f"Expected {{'key': 'value'}}, got {value}"
    
    # Test that we can update the value
    ctx.reflect.set('test-service', {'key': 'new-value'})
    value2 = ctx.reflect.get('test-service', strict=False)
    assert value2 == {'key': 'new-value'}, f"Expected {{'key': 'new-value'}}, got {value2}"
    
    print("  [OK] ReflectService.provide() works correctly")


def main():
    print("=" * 60)
    print("Cordis Python Implementation Tests")
    print("=" * 60)
    
    try:
        test_context_creation()
        test_context_is()
        test_context_extend()
        test_context_isolate()
        test_context_intercept()
        test_fiber_state()
        test_events_service()
        
        # Run async tests with a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(test_async_events())
        finally:
            loop.close()
        
        test_logger()
        test_service_base()
        test_registry()
        test_reflect_provide()
        
        print("\n" + "=" * 60)
        print("All tests passed! [OK]")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
