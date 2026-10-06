#!/usr/bin/env python3
"""
cordis-mini 演示 —— 五种机制完整展示

运行：cd cordis/src/tests/demo && python demo.py

演示内容：
  Round 1: 正常对话（LLM 返回 tool_call → 执行 bash → 回传 LLM → 最终回答）
  Round 2: 简单文本对话
  Round 3: 热更 —— 卸载 llm-logger（listener 自动摘除，日志消失）
  Round 4: 热更 —— 卸载 tool-bash（级联效应，工具从注册表消失）
"""

import asyncio
import importlib.util
import os
import sys

# 确保 cordis 包可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from cordis import create_context, FiberState


def hr(title: str):
    width = 60
    print(f'\n{"=" * width}')
    print(f'  {title}')
    print(f'{"=" * width}\n')


def show_fiber_status(ctx):
    """打印所有 fiber 的当前状态"""
    fibers = ctx.registry.fibers
    for f in fibers:
        inj = ', '.join(f.inject.keys()) if f.inject else 'none'
        prov = ', '.join(f.provide) if f.provide else 'none'
        effects = len(f._disposables)
        print(f'  {f.name:<18} {f.state.name:<10} '
              f'inject=[{inj}] provide=[{prov}] effects={effects}')


async def run_conversation(ctx, user_input: str):
    """执行一轮对话并打印完整链路"""
    print(f'  User: {user_input}\n')
    result = await ctx.agents.run(user_input)
    print(f'\n  Agent: {result}')


def load_plugin_module(plugins_dir: str, plugin_name: str):
    """Dynamically import a plugin module from the plugins directory."""
    spec = importlib.util.spec_from_file_location(
        plugin_name,
        os.path.join(plugins_dir, f'{plugin_name}.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_plugin(ctx, mod, config: dict):
    """Load a single plugin module into the context.

    Supports two shapes:
    - Service class: module defines a class that extends Service (has 'provide')
    - Function plugin: module defines apply(ctx, config)
    """
    plugin_name = getattr(mod, 'name', mod.__name__)

    # Check if module has a Service class (look for class with provide attribute)
    service_class = None
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, type) and hasattr(attr, '__mro__'):
            from cordis import Service as ServiceBase
            if issubclass(attr, ServiceBase) and attr is not ServiceBase:
                service_class = attr
                break

    if service_class is not None:
        # Service class plugin: instantiate it (self-registers via super().__init__)
        def service_plugin(ctx, config):
            instance = service_class(ctx)
            return None  # No disposer needed; Service handles its own lifecycle
        service_plugin.__name__ = plugin_name
        service_plugin.name = plugin_name
        ctx.registry.plugin(service_plugin, config)
    elif hasattr(mod, 'apply'):
        # Function plugin with apply(ctx, config)
        def func_plugin(ctx, config):
            mod.apply(ctx, config)
            return None
        func_plugin.__name__ = plugin_name
        func_plugin.name = plugin_name
        ctx.registry.plugin(func_plugin, config)
    else:
        raise ValueError(f'Plugin {plugin_name} has no Service class or apply() function')


def find_fiber_by_name(ctx, name: str):
    """Find a fiber by its runtime name."""
    for f in ctx.registry.fibers:
        if f.name == name:
            return f
    return None


async def main():
    hr('cordis-mini demo')

    # ═══ Bootstrap ═══════════════════════════════════════════
    print('[Bootstrap] creating root context...')
    ctx = create_context()

    plugins_dir = os.path.join(os.path.dirname(__file__), 'plugins')

    # Load plugins in dependency order (manual topological sort)
    # Layer 0: runtimes (no dependencies)
    # Layer 1: providers/consumers (depend on runtimes)
    # Layer 2: agent-loop (depends on llm + tools)
    plugin_order = [
        ('llm_runtime', {}),
        ('tools_runtime', {}),
        ('llm_echo', {'echo_prefix': '[ECHO]', 'provider': 'echo'}),
        ('tool_bash', {}),
        ('llm_logger', {}),
        ('agent_loop', {}),
    ]

    print('[Bootstrap] loading plugins (dependency order)...\n')
    for plugin_name, config in plugin_order:
        mod = load_plugin_module(plugins_dir, plugin_name)
        load_plugin(ctx, mod, config)

    # Wait for all fibers to settle
    for f in ctx.registry.fibers:
        if f.inertia is not None:
            await f.inertia

    # 打印 fiber 状态
    print('  Fiber status after bootstrap:')
    show_fiber_status(ctx)

    # 验证 ctx 上的服务
    print('\n  Services on ctx:')
    for svc in ['llm', 'tools', 'agents']:
        try:
            val = getattr(ctx, svc)
            print(f'    ctx.{svc} = {val.__class__.__name__}')
        except AttributeError:
            print(f'    ctx.{svc} = (not available)')

    # 验证可选服务查找
    creds = ctx.reflect.get('credentials', strict=False)
    print(f'    ctx.reflect.get("credentials") = {creds}  (optional, not installed)')

    # ═══ Round 1: LLM 返回 tool_call ═════════════════════════
    hr('Round 1: LLM returns tool_call')
    await run_conversation(ctx, 'list files in current directory')

    # ═══ Round 2: 简单文本对话 ═══════════════════════════════
    hr('Round 2: simple text reply')
    await run_conversation(ctx, 'hello')

    # ═══ Round 3: 热更 —— 卸载 llm-logger ═══════════════════
    hr('Round 3: hot-reload — disable llm-logger')
    print('  [SYSTEM] disabling llm-logger...')

    fiber = find_fiber_by_name(ctx, 'llm-logger')
    if fiber is not None:
        await fiber.dispose()

    print(f'  [SYSTEM] llm-logger fiber state: {fiber.state.name}')
    print(f'  [SYSTEM] llm/stream listeners: '
          f'{len(ctx.events._hooks.get("llm/stream", []))} '
          '(was 1, now 0 — listener auto-removed by teardown)\n')

    print('  Fiber status after unload:')
    show_fiber_status(ctx)

    print()
    await run_conversation(ctx, 'test hot reload')
    print('\n  ^ Notice: no [llm-logger] output — listener was torn down!')

    # ═══ Round 4: 热更 —— 卸载 tool-bash ════════════════════
    hr('Round 4: hot-reload — disable tool-bash')
    print('  [SYSTEM] disabling tool-bash...')

    fiber = find_fiber_by_name(ctx, 'tool-bash')
    if fiber is not None:
        await fiber.dispose()

    print(f'  [SYSTEM] tools available: {ctx.tools.list_tools()} '
          f'(was ["bash"], now empty — tool auto-removed)\n')

    print('  Fiber status after unload:')
    show_fiber_status(ctx)

    print('\n  [SYSTEM] trying tool call without bash tool...')
    await run_conversation(ctx, 'run echo test')
    print('\n  ^ The tool_call still goes through LLM, '
          'but tools.execute reports "not found"')

    # ═══ Summary ═════════════════════════════════════════════
    hr('Summary: five mechanisms demonstrated')
    print("""
  1. Everything is a Plugin
     - Service class: LlmRuntime, Tools, AgentLoop (extend Service)
     - Function plugin: llm-echo, tool-bash, llm-logger (export apply)

  2. Context as Service Registry
     - ctx.llm, ctx.tools, ctx.agents via __getattr__ (Proxy simulation)
     - ctx.reflect.get('credentials', strict=False) returns None for optional services

  3. inject Declares Dependencies
     - Manual topological order: llm-runtime/tools-runtime first,
       then llm-echo/tool-bash/llm-logger, then agent-loop
     - Order matters without a Loader

  4. Typed Events (five dispatch modes)
     - waterfall: llm/stream (llm-logger wraps with pre/post logging)
     - serial: tools/pre-execute (approval gate)
     - emit: tools/post-execute (notification)

  5. Reversible Effects (fiber as transaction)
     - Unloading llm-logger: listener auto-removed from llm/stream
     - Unloading tool-bash: tool auto-removed from registry
     - All teardown in reverse order (LIFO)
""")


if __name__ == '__main__':
    asyncio.run(main())
