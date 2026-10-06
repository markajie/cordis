# Cordis 生命周期管理

## 目录

1. [Fiber 状态机](#fiber-状态机)
2. [Effect 系统](#effect-系统)
3. [资源清理模式](#资源清理模式)
4. [依赖追踪与刷新](#依赖追踪与刷新)
5. [错误处理](#错误处理)
6. [高级生命周期操作](#高级生命周期操作)

---

## Fiber 状态机

每个插件实例对应一个 Fiber，经历以下状态转换：

```
    ┌──────────┐
    │ PENDING  │ ← 初始状态 / 依赖不可用
    └────┬─────┘
         │ 依赖就绪
         ▼
    ┌──────────┐
    │ LOADING  │ ← 正在执行插件回调
    └────┬─────┘
         │ 成功
         ▼
    ┌──────────┐     依赖变更/配置更新
    │ ACTIVE   │ ◄────────────────────┐
    └────┬─────┘                      │
         │ dispose() / 依赖失效        │
         ▼                            │
    ┌──────────┐                      │
    │UNLOADING │ ─────────────────────┘
    └────┬─────┘   (重新加载)
         │ 清理完成
         ▼
    ┌──────────┐
    │ DISPOSED │ ← 终态（uid = None）
    └──────────┘
    
    ┌──────────┐
    │ FAILED   │ ← 加载失败（error != None）
    └──────────┘
```

### 状态说明

| 状态 | 含义 | 可执行操作 |
|------|------|-----------|
| `PENDING` | 等待依赖可用 | 无 |
| `LOADING` | 正在执行插件回调 | 等待 |
| `ACTIVE` | 正常运行 | effect, provide, on |
| `UNLOADING` | 正在运行 disposer | 等待 |
| `DISPOSED` | 已销毁 | 无 |
| `FAILED` | 加载出错 | 检查 error |

### 检查状态

```python
fiber = ctx.plugin(my_plugin, config)

# 等待稳定（加载完成或失败）
await fiber.await_settled()

# 检查当前状态
if fiber.state == FiberState.ACTIVE:
    print("Plugin is running")

# 检查错误
if fiber.error:
    print(f"Failed: {fiber.error}")
```

---

## Effect 系统

Effect 是 Cordis 的资源管理核心。每个 effect 注册一个 setup/cleanup 对，cleanup 在 fiber 卸载时按**逆序**执行。

### 基本用法

```python
def apply(ctx, config):
    def setup():
        # 分配资源
        conn = open_connection()
        
        # 返回清理函数
        def cleanup():
            conn.close()
        
        return cleanup
    
    # 注册 effect
    ctx.fiber.effect(setup, 'database-connection')
```

### Effect 签名

```python
fiber.effect(execute: Callable[[], Effect], label: str = 'anonymous') -> Disposable
```

- `execute`: 返回 disposer（单个）、disposer 列表、或 async coroutine
- `label`: 诊断标签，用于调试
- 返回: wrapper disposer，调用它会立即运行内部所有 disposer

### 返回值类型

```python
# 1. 单个 disposer
def setup():
    resource = acquire()
    return lambda: release(resource)

# 2. 多个 disposer
def setup():
    r1 = acquire1()
    r2 = acquire2()
    return [lambda: release1(r1), lambda: release2(r2)]

# 3. Async setup
async def setup():
    conn = await async_connect()
    return lambda: conn.close()

# 4. 无清理需求
def setup():
    initialize_something()
    return None  # 或不返回
```

### Effect 嵌套

Effect 可以嵌套，内层 effect 的 cleanup 在外层之前执行：

```python
def apply(ctx, config):
    def outer_setup():
        ctx.logger.info("Outer setup")
        
        # 内层 effect
        ctx.fiber.effect(lambda: (
            ctx.logger.info("Inner setup"),
            lambda: ctx.logger.info("Inner cleanup")
        )[-1], 'inner')
        
        return lambda: ctx.logger.info("Outer cleanup")
    
    ctx.fiber.effect(outer_setup, 'outer')
```

卸载顺序: Inner cleanup → Outer cleanup

---

## 资源清理模式

### 模式1：函数插件返回 disposer

```python
def apply(ctx, config):
    client = create_client()
    
    def dispose():
        client.close()
    
    return dispose
```

### 模式2：Service 中使用 effect

```python
class Database(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'database')
        self.ctx.fiber.effect(self._init_pool, 'db-pool')
    
    def _init_pool(self):
        self.pool = create_pool()
        return lambda: self.pool.shutdown()
```

### 模式3：事件监听器自动清理

```python
def apply(ctx, config):
    # 监听器随 fiber 卸载自动移除
    ctx.events.on('some/event', handler)
    # 无需手动 dispose
```

### 模式4：动态注册的清理

当服务允许其他插件注册资源时，将 effect 绑定到**调用者**的 fiber：

```python
class Registry(Service):
    def register(self, item):
        # 获取调用者的 fiber
        root = self.ctx.root
        caller_fiber = getattr(root, '_loading_fiber', None) or self.ctx.fiber
        
        def setup():
            self._items.append(item)
            return lambda: self._items.remove(item)
        
        # 绑定到调用者 fiber，而非 service fiber
        return caller_fiber.effect(setup, f'registry.register({item.name!r})')
```

这样当调用者插件卸载时，注册的项自动移除。

### 模式5：AsyncExitStack（复杂异步资源）

```python
from contextlib import AsyncExitStack

class ComplexService(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'complex')
        self._stack = AsyncExitStack()
        
        self.ctx.fiber.effect(self._setup, 'complex-resources')
    
    async def _setup(self):
        self.conn = await self._stack.enter_async_context(async_connect())
        self.cache = await self._stack.enter_async_context(async_cache())
        
        async def cleanup():
            await self._stack.aclose()
        
        return cleanup
```

---

## 依赖追踪与刷新

Fiber 自动追踪其 `inject` 声明的依赖，并在依赖变化时响应。

### 依赖可用 → 启动

```python
# Plugin A: 提供 database
name = 'database'
provide = ['database']
class Database(Service): ...

# Plugin B: 依赖 database
name = 'app'
inject = ['database']

# 即使 App 先加载，也会等 Database 就绪后才 ACTIVE
ctx.plugin(App, {})
ctx.plugin(Database, {})  # Database ACTIVE → App 自动 LOADING → ACTIVE
```

### 依赖失效 → 暂停

```python
# 如果 Database 被卸载
db_fiber.dispose()
# App 自动 UNLOADING → PENDING（等待 database 重新可用）
```

### 依赖恢复 → 重启

```python
# 重新加载 Database
ctx.plugin(Database, {'new_config': True})
# App 自动 LOADING → ACTIVE（使用新的 database 实例）
```

### Epoch 机制

Fiber 通过 epoch 字符串追踪依赖版本：

```
epoch = ":1:5:3"  # 表示 inject 的三个服务的 fiber uid
```

- 任一依赖的 uid 变化 → epoch 变化 → 触发 unload/reload
- 依赖不可用 → epoch = `__INACTIVE__` → 进入 PENDING

---

## 错误处理

### 加载失败

```python
fiber = ctx.plugin(my_plugin, config)
await fiber.await_settled()

if fiber.error:
    print(f"Plugin failed: {fiber.error}")
    print(f"State: {fiber.state}")  # FAILED
```

### 错误传播

- 插件回调中的异常被捕获并存储在 `fiber.error`
- `await_settled()` 会重新抛出错误
- 错误不会传播到其他插件

### 重试机制

Cordis 不内置重试，但可以通过事件实现：

```python
ctx.events.on('internal/status', lambda fiber, old_state: (
    retry_plugin(fiber) if fiber.state == FiberState.FAILED else None
))
```

---

## 高级生命周期操作

### update() - 热更新配置

```python
fiber = ctx.plugin(my_plugin, {'port': 8080})
await fiber.await_settled()

# 更新配置，触发 reload
fiber.update({'port': 9090})
await fiber.await_settled()
```

流程: ACTIVE → UNLOADING → (cleanup) → LOADING → ACTIVE

### restart() - 重启插件

```python
await fiber.restart()
```

等价于 `dispose()` + 立即 reload，但保持 fiber 对象不变。

### dispose() - 永久销毁

```python
await fiber.dispose()
# fiber.uid = None, state = DISPOSED
# 无法再使用此 fiber
```

### await_settled() - 等待稳定

```python
# 等待当前加载/卸载完成
await fiber.await_settled()

# 如果有错误，会抛出
try:
    await fiber.await_settled()
except Exception as e:
    print(f"Plugin error: {e}")
```

### 监听生命周期事件

```python
# 监听所有插件的状态变化
ctx.events.on('internal/status', lambda fiber, old_state: (
    print(f"{fiber.name}: {old_state.name} → {fiber.state.name}")
))

# 监听插件创建/销毁
ctx.events.on('internal/plugin', lambda fiber: (
    print(f"Plugin {'created' if fiber.uid else 'disposed'}: {fiber.name}")
))
```

---

## 调试技巧

### 查看 Fiber 信息

```python
print(fiber)           # Fiber<my-plugin#3 state=ACTIVE>
print(fiber.name)      # "my-plugin"
print(fiber.uid)       # 3
print(fiber.provide)   # ['my-service']
print(fiber.inject)    # {'database': None, 'cache': None}
```

### 查看所有活跃 Fiber

```python
for fiber in ctx.registry.fibers:
    print(f"{fiber.name}: {fiber.state.name}")
```

### 查看 Effect 树

```python
effects = fiber.get_effects()
for effect_meta in effects:
    print(effect_meta.label)
    for child in effect_meta.children:
        print(f"  └─ {child.label}")
```
