# Cordis 插件模式详解

## 目录

1. [模块级属性](#模块级属性)
2. [函数插件](#函数插件)
3. [类插件（Service）](#类插件service)
4. [对象插件](#对象插件)
5. [依赖注入](#依赖注入)
6. [配置管理](#配置管理)
7. [插件组合模式](#插件组合模式)

---

## 模块级属性

每个插件文件可以声明以下模块级属性，框架会自动读取：

| 属性 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 插件名称，用于日志、调试和 fiber.name |
| `inject` | `list[str] \| dict[str, Any]` | 依赖的服务列表或带配置的映射 |
| `provide` | `list[str]` | 此插件提供的服务名列表（仅 Service 类需要） |
| `Config` | `class` | 配置验证/合并类（可选） |

### 示例

```python
# my_plugin.py
name = 'my-awesome-plugin'
inject = ['database', 'cache']
provide = ['my-api']

class Config:
    """可选的配置验证类"""
    @staticmethod
    def merge(*configs):
        result = {}
        for cfg in configs:
            if isinstance(cfg, dict):
                result.update(cfg)
        return result
```

---

## 函数插件

最简单的插件形式，适合初始化逻辑、适配器注册或简单功能。

### 签名

```python
def apply(ctx: Context, config: Any) -> Disposable | None
```

- `ctx`: 当前上下文，包含所有服务
- `config`: 插件配置（来自 `ctx.plugin()` 的第二个参数）
- 返回值: 可选的 disposer 函数，在插件卸载时调用

### 完整示例

```python
"""plugins/analytics.py"""

name = 'analytics'
inject = ['logger']

def apply(ctx, config):
    """分析插件：追踪用户行为"""
    endpoint = config.get('endpoint', 'https://analytics.example.com')
    
    # 初始化客户端
    client = AnalyticsClient(endpoint)
    
    # 监听事件
    dispose_listener = ctx.events.on('user/action', lambda action: client.track(action))
    
    ctx.logger.info(f"Analytics enabled: {endpoint}")
    
    # 返回清理函数
    def dispose():
        dispose_listener()
        client.close()
        ctx.logger.info("Analytics disabled")
    
    return dispose
```

### 何时使用函数插件

- ✅ 注册适配器到现有服务（如 LLM Provider）
- ✅ 设置事件监听器
- ✅ 简单的初始化/清理逻辑
- ❌ 需要提供新的服务 API → 用 Service 类
- ❌ 需要复杂的状态管理 → 用 Service 类

---

## 类插件（Service）

提供可复用服务的标准方式。继承 `Service` 基类获得自动注册和生命周期管理。

### 基本结构

```python
from cordis import Service

name = 'my-service'
provide = ['my-api']

class MyService(Service):
    def __init__(self, ctx):
        # 必须调用 super().__init__，第二个参数是服务名
        super().__init__(ctx, 'my-api')
        
        # 初始化内部状态
        self._data = {}
    
    # 公开 API 方法
    def get(self, key):
        return self._data.get(key)
    
    def set(self, key, value):
        self._data[key] = value
```

### Service 基类提供的能力

1. **自动注册**: `super().__init__(ctx, name)` 将实例注册为 `ctx.<name>`
2. **自动清理**: 服务随 owning fiber 卸载而注销
3. **拦截配置**: 通过 `_resolve_config()` 获取祖先上下文的 intercept 配置
4. **可调用支持**: 定义 `symbols.invoke` 使服务可直接调用

### 高级：可调用服务

```python
from cordis import Service, symbols

class Greeter(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'greeter')
    
    # 定义 invoke 使服务可调用: ctx.greeter("World")
    def _invoke_impl(self, name: str) -> str:
        return f"Hello, {name}!"
    
    # 绑定到 symbols.invoke
    setattr(_invoke_impl, symbols.invoke, True)  # 或在类级别设置
```

更简洁的方式：

```python
class Greeter(Service):
    invoke = symbols.invoke  # 类级别声明
    
    def __init__(self, ctx):
        super().__init__(ctx, 'greeter')
    
    def __call__(self, name: str) -> str:
        return f"Hello, {name}!"
```

---

## 对象插件

带有 `apply` 方法的对象，适合需要预配置的插件工厂。

```python
class PluginFactory:
    def __init__(self, prefix):
        self.prefix = prefix
    
    def apply(self, ctx, config):
        ctx.logger.info(f"{self.prefix}: loaded")
        return lambda: ctx.logger.info(f"{self.prefix}: unloaded")

# 使用
factory = PluginFactory("[MyPlugin]")
ctx.plugin(factory, {})
```

---

## 依赖注入

Cordis 的核心特性：插件只声明需要什么，框架确保依赖可用后才启动。

### 声明依赖

```python
# 方式1：列表形式（仅声明依赖，无配置）
inject = ['database', 'cache', 'logger']

# 方式2：字典形式（带 intercept 配置）
inject = {
    'database': {'pool_size': 10},
    'cache': {'ttl': 3600},
    'logger': None  # 无额外配置
}

# 方式3：装饰器（类插件）
from cordis import inject_decorator

@inject_decorator('database')
@inject_decorator('cache', {'ttl': 3600})
class MyPlugin(Service):
    ...
```

### 依赖解析流程

1. 插件声明 `inject = ['database']`
2. Fiber 创建时检查 `ctx.reflect.get('database')`
3. 如果服务不可用，Fiber 进入 `PENDING` 状态
4. 当 `database` 服务被 provide 后，Fiber 自动转为 `LOADING` → `ACTIVE`
5. 如果 `database` 被卸载，Fiber 自动 `UNLOADING` → 等待重新可用

### 访问依赖

```python
name = 'consumer'
inject = ['llm', 'tools']

class Consumer(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'consumer')
        # 此时 ctx.llm 和 ctx.tools 已保证存在且 ACTIVE
    
    async def process(self, input_text):
        # 直接使用依赖服务
        response = await self.ctx.llm.generate(input_text)
        tools = self.ctx.tools.list_tools()
        return response
```

---

## 配置管理

### 传递配置

```python
# 加载插件时传入配置
ctx.plugin(my_plugin, {
    'endpoint': 'https://api.example.com',
    'timeout': 30,
    'retries': 3
})
```

### 在插件中读取配置

```python
def apply(ctx, config):
    endpoint = config.get('endpoint', 'default-endpoint')
    timeout = config.get('timeout', 10)
```

### Intercept 配置（高级）

允许祖先上下文覆盖后代插件的配置：

```python
# 父上下文设置 intercept
parent_ctx = ctx.intercept('my-service', {'debug': True})

# 在子上下文中加载插件，会自动合并 intercept 配置
child_fiber = parent_ctx.plugin(MyService, {'port': 8080})
# MyService 看到的配置: {'debug': True, 'port': 8080}
```

Service 类通过 `_resolve_config()` 获取合并后的配置：

```python
class MyService(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'my-service')
        config = self._resolve_config()
        self.debug = config.get('debug', False)
```

---

## 插件组合模式

### Provider 模式

一个服务可以有多个实现（Provider），消费者只依赖接口：

```python
# llm_runtime.py - 定义接口
class LLMRuntime(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'llm')
        self._adapters = {}
    
    def register_adapter(self, providers, adapter):
        for p in providers:
            self._adapters[p] = adapter
    
    def stream(self, messages, provider='default'):
        adapter = self._adapters.get(provider)
        return adapter.stream(messages)

# llm_deepseek.py - Provider 实现
name = 'llm-deepseek'
inject = ['llm']

def apply(ctx, config):
    adapter = DeepSeekAdapter(config)
    ctx.llm.register_adapter(['deepseek'], adapter)

# agent_loop.py - 消费者（不知道具体 Provider）
name = 'agent-loop'
inject = ['llm']

class AgentLoop(Service):
    async def run(self, messages):
        # 不关心是 DeepSeek 还是其他 Provider
        return list(self.ctx.llm.stream(messages))
```

### Waterfall 管道模式

使用事件构建处理管道：

```python
# tools_runtime.py
async def execute(self, tool_name, args):
    exec_ctx = {'tool_name': tool_name, 'args': args}
    
    # 前置检查
    pre_result = await self.ctx.events.serial('tools/pre-execute', exec_ctx)
    if pre_result == 'denied':
        return 'denied'
    
    # 执行（允许拦截）
    result = self.ctx.events.waterfall(
        'tools/execute',
        exec_ctx,
        inner=lambda ctx=exec_ctx: self._tools[tool_name]['handler'](ctx['args'])
    )
    
    # 后置处理
    self.ctx.events.emit('tools/post-execute', exec_ctx, result)
    
    return result
```

### 动态注册模式

服务允许其他插件动态注册资源，并自动跟踪生命周期：

```python
class Tools(Service):
    def register(self, tool_def):
        tool_name = tool_def['name']
        
        # 关键：effect 注册到 CALLER 的 fiber，不是 service 的 fiber
        root = self.ctx.root
        caller_fiber = getattr(root, '_loading_fiber', None) or self.ctx.fiber
        
        def setup():
            self._tools[tool_name] = tool_def
            return lambda: self._tools.pop(tool_name, None)
        
        return caller_fiber.effect(setup, f'tools.register({tool_name!r})')
```

这样当调用者插件卸载时，注册的工具自动移除。
