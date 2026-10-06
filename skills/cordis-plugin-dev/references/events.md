# Cordis 事件系统详解

## 目录

1. [五种派发模式](#五种派发模式)
2. [监听器注册](#监听器注册)
3. [上下文过滤](#上下文过滤)
4. [内置事件](#内置事件)
5. [事件命名约定](#事件命名约定)
6. [实战模式](#实战模式)

---

## 五种派发模式

Cordis 提供五种事件派发策略，覆盖从简单通知到复杂管道的各种场景。

### 1. emit - 同步触发即忘

```python
ctx.events.emit('user/login', user_data)
```

- **同步执行**所有监听器
- 不等待异步返回值
- 适合：日志、指标上报、非关键通知

### 2. parallel - 并发执行

```python
await ctx.events.parallel('data/process', items)
```

- **并发执行**所有监听器
- 等待所有完成（`asyncio.gather`）
- 任一失败抛出 `ExceptionGroup`
- 适合：并行处理、批量操作

### 3. serial - 顺序执行 + bail

```python
result = await ctx.events.serial('request/handle', request)
if result is not None:
    return result  # 某个监听器返回了值，停止后续
```

- **按注册顺序**依次执行
- 遇到 bail 值（非 `None` 且非 `False`）立即停止
- 返回第一个 bail 值
- 适合：责任链、权限检查、处理器选择

### 4. bail - 同步 bail

```python
handler = ctx.events.bail('handler/select', request_type)
if handler:
    handler(request)
```

- **同步执行**，遇到 bail 值立即停止
- 与 `serial` 类似但不支持异步
- 适合：快速决策、同步拦截

### 5. waterfall - 管道组合

```python
result = ctx.events.waterfall(
    'transform/text',
    text,
    inner=lambda t: default_transform(t)
)
```

- 监听器**层层包裹**内部回调
- 每个监听器接收 `(*args, next_fn)`
- 调用 `next_fn()` 继续链，不调用则中断
- 适合：中间件、数据转换管道、请求拦截

### Waterfall 详解

```python
# 注册监听器（外层先执行）
ctx.events.on('transform/text', lambda text, next: f"[{next(text)}]")
ctx.events.on('transform/text', lambda text, next: next(text).upper())

# 执行
result = ctx.events.waterfall('transform/text', 'hello', inner=lambda t: t)
# 流程: "[HELLO]" ← 第一个监听器包裹第二个的结果
#   第二个: "HELLO" ← upper(inner("hello"))
#   inner: "hello"
```

监听器可以修改参数后再传给 next：

```python
ctx.events.on('process', lambda data, next: next({**data, 'modified': True}))
```

---

## 监听器注册

### on() - 持久监听

```python
dispose = ctx.events.on('event/name', callback, options=None)
```

| 参数 | 说明 |
|------|------|
| `name` | 事件名 |
| `callback` | 监听器函数 |
| `options` | `bool` (prepend) 或 `EventOptions(prepend=False, global_=False)` |

返回值是 disposer 函数，但通常不需要手动调用——监听器随 fiber 卸载自动移除。

### once() - 一次性监听

```python
ctx.events.once('app/ready', lambda: print("Ready!"))
```

第一次触发后自动注销。

### 选项说明

```python
from cordis import EventOptions

# prepend: 插入到监听器列表头部（默认追加到尾部）
ctx.events.on('event', callback, EventOptions(prepend=True))

# global_: 跨隔离作用域接收事件
ctx.events.on('event', callback, EventOptions(global_=True))
```

### 自动清理

监听器通过 fiber effect 自动管理生命周期：

```python
def apply(ctx, config):
    # 这个监听器会在插件卸载时自动移除
    ctx.events.on('some/event', handler)
    
    # 无需手动 dispose，除非需要提前移除
    early_dispose = ctx.events.on('other/event', other_handler)
    # ... 某些条件下
    early_dispose()  # 提前移除
```

---

## 上下文过滤

事件派发支持基于上下文的过滤，确保监听器只收到相关作用域的事件。

### 过滤规则

当使用 `thisArg` 派发事件时：

```python
ctx.events.emit(some_ctx, 'event/name', data)
```

只有满足以下条件的监听器会被调用：
- `global_=True` 的监听器始终接收
- 监听器的 `hook.ctx` 与 `thisArg` 在同一隔离作用域

### 实际示例

```python
# 租户 A 的上下文
tenant_a = ctx.isolate('database', 'tenant-a')
tenant_a.events.on('query/executed', log_query)

# 租户 B 的上下文
tenant_b = ctx.isolate('database', 'tenant-b')
tenant_b.events.on('query/executed', log_query)

# 在 tenant_a 中派发，只有 tenant_a 的监听器收到
tenant_a.events.emit(tenant_a, 'query/executed', query_info)
```

---

## 内置事件

框架内部使用的事件，以 `internal/` 前缀标识：

| 事件 | 参数 | 模式 | 说明 |
|------|------|------|------|
| `internal/plugin` | `(fiber)` | emit | Fiber 创建或销毁 |
| `internal/status` | `(fiber, old_state)` | emit | Fiber 状态变更 |
| `internal/config` | `(config, next)` | waterfall | 配置解析拦截 |
| `internal/service` | `(name, value)` | emit | 服务注册/更新 |
| `internal/update` | `(config, no_save, next)` | waterfall | Fiber 配置更新 |
| `internal/get` | `(ctx, name, error, next)` | waterfall | 服务读取拦截 |
| `internal/set` | `(ctx, name, value, error, next)` | waterfall | 服务写入拦截 |
| `internal/listener` | `(name, listener, options)` | bail | 监听器注册拦截 |
| `internal/dispatch` | `(mode, name, args, this_arg)` | emit | 事件派发诊断 |

### 拦截示例

```python
# 拦截所有服务读取
ctx.events.on('internal/get', lambda ctx, name, error, next: (
    print(f"Reading {name}"),
    next()
)[-1])

# 拦截配置解析
ctx.events.on('internal/config', lambda config, next: {
    **next(config),
    'injected_key': 'value'
})
```

---

## 事件命名约定

推荐使用 `<domain>/<action>` 格式：

```
✅ user/login
✅ tools/pre-execute
✅ llm/response-received
✅ app/ready

❌ login          (缺少 domain)
❌ user_login     (应使用 /)
❌ USER/LOGIN     (避免大写)
```

---

## 实战模式

### 权限检查管道

```python
# 注册多个检查器
ctx.events.on('access/check', lambda req, next: (
    'denied' if not req.user else next()
))
ctx.events.on('access/check', lambda req, next: (
    'denied' if req.user.role != 'admin' else next()
))

# 执行检查
result = await ctx.events.serial('access/check', request)
if result == 'denied':
    return Response(403)
```

### 数据转换管道

```python
# 注册转换器（注意顺序：后注册的更靠近 inner）
ctx.events.on('transform/response', lambda data, next: {
    **next(data),
    'timestamp': time.time()
})
ctx.events.on('transform/response', lambda data, next: {
    **next(data),
    'version': 'v2'
})

# 执行转换
response = ctx.events.waterfall(
    'transform/response',
    raw_data,
    inner=lambda d: format_response(d)
)
```

### 插件间通信

```python
# Plugin A: 发布事件
class Publisher(Service):
    def notify(self, message):
        self.ctx.events.emit('notification/new', message)

# Plugin B: 订阅事件
name = 'notification-handler'
inject = []  # 不依赖 publisher

def apply(ctx, config):
    ctx.events.on('notification/new', lambda msg: send_email(msg))
```

### 条件性事件处理

```python
# 只在特定条件下处理
ctx.events.on('request/incoming', lambda req, next: (
    next(req) if req.path.startswith('/api') else None
))
```
