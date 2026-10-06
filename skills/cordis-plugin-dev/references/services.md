# Cordis Service 开发指南

## 目录

1. [Service 基类](#service-基类)
2. [服务注册与解析](#服务注册与解析)
3. [服务隔离](#服务隔离)
4. [Accessor 属性](#accessor-属性)
5. [Mixin 混入](#mixin-混入)
6. [最佳实践](#最佳实践)

---

## Service 基类

`Service` 是所有服务的基类，提供自动注册、生命周期管理和配置解析。

### 构造函数

```python
from cordis import Service

class MyService(Service):
    def __init__(self, ctx, name=None):
        super().__init__(ctx, name)
```

| 参数 | 说明 |
|------|------|
| `ctx` | 当前上下文（必须） |
| `name` | 服务名，默认为类名的 lowercase 或 `provide` 属性 |

### 自动行为

调用 `super().__init__(ctx, name)` 后：

1. 实例被注册为 `ctx.<name>`
2. 创建 tracker 元数据用于 traceable proxy
3. 如果定义了 `symbols.invoke`，服务变为可调用
4. 服务随 owning fiber 卸载而自动注销

### 类级别符号

Service 类暴露以下符号作为类属性：

```python
class MyService(Service):
    init = symbols.init        # 初始化钩子
    check = symbols.check      # 可用性检查谓词
    config = symbols.config    # 配置解析
    invoke = symbols.invoke    # 使服务可调用
    extend = symbols.extend    # 扩展服务
    tracker = symbols.tracker  # 追踪元数据
    resolveConfig = symbols.resolveConfig  # 配置合并
```

---

## 服务注册与解析

### provide() - 手动注册

当不使用 Service 基类时，可以用 `ctx.reflect.provide()` 手动注册：

```python
def apply(ctx, config):
    my_value = SomeObject()
    
    # 注册服务，返回 disposer
    dispose = ctx.reflect.provide('my-service', my_value)
    
    # 可选：提供可用性检查
    dispose = ctx.reflect.provide('my-service', my_value, check=lambda: my_value.is_ready())
    
    # dispose() 会注销服务并通知依赖者
```

### get() - 解析服务

```python
# 严格模式（默认）：服务不存在或不可用时抛异常
service = ctx.reflect.get('my-service')

# 非严格模式：返回 None
service = ctx.reflect.get('my-service', strict=False)
```

### set() - 更新服务值

```python
# 只能由 owning fiber 更新
ctx.reflect.set('my-service', new_value)
```

注意：只能在注册该服务的同一个 fiber 中调用 `set()`，否则抛出错误。

---

## 服务隔离

Cordis 支持服务隔离，允许在不同作用域中存在同名服务的不同实现。

### isolate() - 创建隔离作用域

```python
# 创建隔离的数据库作用域
isolated_ctx = ctx.isolate('database')

# 在此上下文中注册的 'database' 服务独立于父作用域
isolated_ctx.plugin(DatabasePlugin, {'host': 'localhost:5433'})

# 父上下文中的 database 不受影响
```

### 隔离规则

- 同一 `isolate(name, label)` 调用共享同一作用域
- 不同 label 创建独立作用域
- 未指定 label 时自动生成唯一标识
- 子上下文继承父上下文的隔离映射

### 使用场景

```python
# 多租户：每个租户有自己的数据库连接
for tenant in tenants:
    tenant_ctx = ctx.isolate('database', tenant.id)
    tenant_ctx.plugin(DatabasePlugin, {'host': tenant.db_host})
    tenant_ctx.plugin(AppPlugin, {})  # 使用租户专属的 database
```

---

## Accessor 属性

Accessor 允许定义计算属性，而非直接存储服务值。

### 定义 Accessor

```python
def apply(ctx, config):
    # 定义只读 accessor
    ctx.reflect.accessor(
        'current_user',
        get=lambda ctx, error: get_current_user_from_session()
    )
    
    # 定义读写 accessor
    ctx.reflect.accessor(
        'theme',
        get=lambda ctx, error: load_theme(),
        set=lambda value, ctx, error: save_theme(value) or True
    )
```

### Accessor vs Service

| 特性 | Service (provide) | Accessor |
|------|------------------|----------|
| 存储 | 具体值 | 计算逻辑 |
| 更新 | `set()` 覆盖值 | `set()` 调用 hook |
| 所有权 | Fiber | Fiber |
| 适用场景 | 对象实例 | 派生值、代理 |

---

## Mixin 混入

Mixin 将服务的方法直接暴露到 ctx 上，简化调用。

### 基本用法

```python
# 将 logger 的 info/error 方法混入 ctx
ctx.reflect.mixin('logger', ['info', 'error', 'warn', 'debug'])

# 现在可以直接调用
ctx.info("Hello")  # 等价于 ctx.logger.info("Hello")
```

### 重命名混入

```python
# 将 service.method 混入为 ctx.custom_name
ctx.reflect.mixin('my-service', {
    'do_something': 'custom_action',
    'get_data': 'fetch'
})

ctx.custom_action()  # 调用 my_service.do_something()
ctx.fetch()          # 调用 my_service.get_data()
```

### 混入对象（非服务）

```python
# 混入任意对象的方法
helper = HelperClass()
ctx.reflect.mixin(helper, ['method1', 'method2'])
```

---

## 最佳实践

### 1. 服务命名约定

- 使用 kebab-case: `'my-service'`, `'llm-runtime'`
- 避免与内置服务冲突: `reflect`, `events`, `registry`, `logger`
- 模块级 `provide` 与 `super().__init__` 的名称保持一致

### 2. 错误处理

```python
class MyService(Service):
    def query(self, sql):
        try:
            return self._pool.execute(sql)
        except ConnectionError as e:
            self.ctx.logger.error(f"Database error: {e}")
            raise  # 或返回默认值
```

### 3. 异步服务

```python
class AsyncService(Service):
    async def fetch_data(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()
```

消费者需要 `await`：

```python
data = await self.ctx.my_service.fetch_data(url)
```

### 4. 资源管理

在 Service 中使用 effect 管理内部资源：

```python
class Database(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'database')
        
        # 在 fiber 上注册 effect
        self.ctx.fiber.effect(self._setup_pool, 'db-pool')
    
    def _setup_pool(self):
        self._pool = create_pool()
        
        def cleanup():
            self._pool.close()
        
        return cleanup
```

### 5. 检查服务可用性

```python
# 在注入前检查
if ctx.reflect.get('optional-service', strict=False) is not None:
    ctx.optional_service.do_thing()
```

或在 Service 中定义 check 谓词：

```python
class MyService(Service):
    check = lambda self: self._ready
    
    def __init__(self, ctx):
        super().__init__(ctx, 'my-service')
        self._ready = False
    
    async def initialize(self):
        await self._connect()
        self._ready = True
```

### 6. 避免循环依赖

```
❌ A inject B, B inject A
✅ A inject B, B 通过事件通知 A
✅ 提取公共接口 C，A 和 B 都 inject C
```
