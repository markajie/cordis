---
name: cordis-plugin-dev
description: |
  Cordis Python 插件开发指南。用于创建、调试和优化 Cordis 框架插件。
  当用户提到以下任何内容时触发此技能：
  - "cordis 插件"、"cordis plugin"、"写一个插件"
  - "Service 类"、"继承 Service"、"ctx.provide"
  - "fiber"、"生命周期"、"effect"、"disposer"
  - "事件监听"、"ctx.events.on"、"emit/parallel/serial/bail/waterfall"
  - "依赖注入"、"inject"、"插件配置"
  - 任何涉及 Cordis 框架的 Python 插件开发任务
  
  即使用户没有明确说 "cordis"，只要涉及上述概念也应触发。
  这是 Cordis 生态的核心开发技能，所有功能都以插件形式构建。
---

# Cordis 插件开发指南

Cordis 是一个基于依赖注入和生命周期管理的 Python 插件框架。所有功能都通过插件实现，插件之间通过服务（Service）和事件（Events）解耦通信。

## 核心架构速览

```
┌─────────────────────────────────────────────────────────┐
│                      Context (ctx)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐ │
│  │   reflect   │ │   events    │ │      registry       │ │
│  │ (服务注册)   │ │  (事件总线)  │ │    (插件管理)        │ │
│  └─────────────┘ └─────────────┘ └─────────────────────┘ │
│  ┌─────────────┐ ┌─────────────┐                         │
│  │   logger    │ │    fiber    │                         │
│  │  (日志服务)  │ │ (生命周期)   │                         │
│  └─────────────┘ └─────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

## 快速开始：三种插件模式

### 1. 函数插件（最简单）

适合简单的初始化逻辑或适配器注册：

```python
name = 'my-plugin'
inject = ['some-service']  # 声明依赖

def apply(ctx, config):
    """插件入口，返回 disposer 用于清理"""
    ctx.logger.info("插件已加载")
    
    # 注册资源...
    
    def dispose():
        ctx.logger.info("插件已卸载")
    
    return dispose
```

### 2. Service 类插件（推荐）

适合提供可复用服务的插件：

```python
from cordis import Service

name = 'my-service'
provide = ['my-api']  # 声明提供的服务名

class MyService(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'my-api')  # 自动注册到 ctx.my_api
    
    def do_something(self):
        return "result"
```

### 3. 带依赖注入的插件

```python
name = 'consumer'
inject = ['llm', 'tools']  # 等待这些服务可用后才启动

class Consumer(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'consumer')
        # 此时 ctx.llm 和 ctx.tools 已保证可用
    
    async def run(self):
        result = await self.ctx.llm.generate("hello")
        return result
```

## 关键概念索引

根据你需要了解的内容，阅读对应的参考文档：

| 你想了解... | 参考文档 |
|------------|---------|
| 插件的三种写法、模块级属性、配置验证 | [references/plugin-patterns.md](references/plugin-patterns.md) |
| Service 基类、provide/inject、服务隔离 | [references/services.md](references/services.md) |
| 五种事件派发模式、监听器注册 | [references/events.md](references/events.md) |
| Fiber 状态机、effect 系统、资源清理 | [references/lifecycle.md](references/lifecycle.md) |

## 常见场景速查

### 注册一个服务

```python
from cordis import Service

class Database(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'database')
        self.pool = create_pool()
    
    def query(self, sql):
        return self.pool.execute(sql)
```

### 监听事件

```python
def apply(ctx, config):
    # 自动随 fiber 卸载而移除
    ctx.events.on('user/login', lambda user: ctx.logger.info(f"{user} logged in"))
    
    # 一次性监听
    ctx.events.once('app/ready', lambda: ctx.logger.info("App ready!"))
```

### 使用 effect 管理资源

```python
def apply(ctx, config):
    def setup():
        conn = open_connection()
        
        def cleanup():
            conn.close()
        
        return cleanup
    
    ctx.fiber.effect(setup, 'database-connection')
```

### 声明依赖

```python
# 方式1：模块级 inject
name = 'my-plugin'
inject = ['database', 'cache']

# 方式2：字典形式带配置
inject = {'database': {'pool_size': 10}, 'cache': None}

# 方式3：装饰器（类插件）
from cordis import inject_decorator

@inject_decorator('logger')
class MyPlugin:
    ...
```

## 开发检查清单

创建新插件时确认：

- [ ] 设置了 `name` 属性（用于日志和调试）
- [ ] 正确声明了 `inject`（依赖的服务）或 `provide`（提供的服务）
- [ ] Service 类调用了 `super().__init__(ctx, name)`
- [ ] 异步操作使用了 `async/await`
- [ ] 资源清理通过 effect 或返回 disposer 实现
- [ ] 没有在插件中硬编码其他插件的实现细节

## 完整示例

查看 `cordis/src/tests/demo/plugins/` 目录中的真实插件：
- `llm_echo.py` - 函数插件示例（Provider 模式）
- `tools_runtime.py` - Service 插件示例（工具注册表）
- `agent_loop.py` - 消费者插件示例（依赖注入）
