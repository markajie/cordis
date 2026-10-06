# Cordis Harness 开发指引

## 项目概述

Cordis Harness 是一个基于 Cordis 框架的 AI 编码助手运行时。配置使用 `cordis.json` 而非 TOML layer 文件。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Cordis Harness App                        │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                  cordis.json (配置)                      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │  models   │ │  agent   │ │  kernel  │ │   context      │  │
│  │ (LLM服务) │ │ (对话循环)│ │ (代码执行)│ │  (项目上下文)   │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘  │
│       ▲            ▲            ▲              ▲             │
│       │            │            │              │             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │
│  │ commands │ │   chat   │ │transcript│                     │
│  │ (命令注册)│ │ (会话管理)│ │ (历史记录)│                     │
│  └──────────┘ └──────────┘ └──────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

## 核心设计原则

### 1. 插件隔离（Plugin Layering）
- **每个插件是独立模块**，不直接 import 其他插件
- 插件间通过 **服务名（字符串）** 和 **Protocol（接口）** 约定交互
- 共享的类型定义放在 `cordis_harness/types.py`

### 2. 两半结构（Two Halves）
- **值模块**（如 `llm.py`, `kernel.py`）：纯业务逻辑，**不 import cordis**
- **接线模块**（`wiring.py` 或 `__init__.py`）：使用 cordis API 注册服务和监听事件

### 3. 配置驱动
- 所有配置来自 `cordis.json`，不硬编码
- 插件通过 `config` 参数接收自己的配置片段
- 支持环境变量覆盖敏感值（API keys）

### 4. 生命周期管理
- 使用 `ctx.fiber.effect()` 管理资源（连接、进程、文件句柄）
- 返回 disposer 函数用于清理
- 事件监听器随 fiber 卸载自动移除

## Cordis API 速查

### 创建根上下文
```python
from cordis import create_context
ctx = create_context()
```

### 函数插件
```python
name = 'my-plugin'
inject = ['some-service']

def apply(ctx, config):
    ctx.logger.info("loaded")
    def dispose():
        ctx.logger.info("unloaded")
    return dispose
```

### Service 类插件
```python
from cordis import Service

name = 'my-service'
provide = ['my-api']

class MyService(Service):
    def __init__(self, ctx):
        super().__init__(ctx, 'my-api')
```

### 加载插件
```python
fiber = ctx.plugin(my_plugin, {'key': 'value'})
await fiber.await_settled()
```

### 事件系统
```python
# 监听
ctx.events.on('event/name', handler)

# 派发
ctx.events.emit('event/name', data)          # 同步
await ctx.events.parallel('event/name', data) # 并发
result = await ctx.events.serial('event/name', data)  # 顺序+bail
```

### Effect 资源管理
```python
def apply(ctx, config):
    def setup():
        conn = open_connection()
        return lambda: conn.close()
    ctx.fiber.effect(setup, 'connection')
```

## 插件清单与职责

| 插件 | 服务名 | 依赖 | 职责 |
|------|--------|------|------|
| `models` | `model` | - | LLM 模型调用（OpenAI/Claude） |
| `agent` | `loop` | `model`, `kernel`, `transcript`, `system` | Agent 对话循环 |
| `kernel` | `kernel` | - | Python 代码执行沙箱 |
| `context` | `system` | `kernel` | 项目上下文（工作目录、CLAUDE.md） |
| `commands` | `commands` | - | 斜杠命令注册表（Broker 模式） |
| `chat` | `done` | `loop`, `input`, `output`, `commands` | 交互式会话管理 |
| `transcript` | `transcript` | - | 对话历史持久化 |

## 配置文件格式（cordis.json）

```json
{
  "models": {
    "default": "gpt-4o",
    "providers": {
      "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY"
      }
    }
  },
  "agent": {
    "max_nudges": 2
  },
  "kernel": {
    "sandbox": true,
    "timeout": 30
  },
  "context": {
    "project_dir": ".",
    "instructions_file": "CLAUDE.md"
  },
  "transcript": {
    "path": ".cordis/transcript.jsonl"
  }
}
```

## 数据流

```
用户输入 → chat.read() → loop.reply(message)
                              ↓
                         model.complete(messages, tools)
                              ↓
                         [text / tool_call / stop]
                              ↓
                    tool_call → kernel.run(code) → result
                              ↓
                         transcript.append(message)
                              ↓
                         chat.show(events) → 用户看到输出
```

## 事件清单

| 事件名 | 模式 | 参数 | 说明 |
|--------|------|------|------|
| `harness/ready` | emit | - | 所有插件就绪 |
| `harness/shutdown` | emit | - | 即将关闭 |
| `chat/message` | emit | `(message)` | 新消息 |
| `chat/turn-start` | emit | `(turn_id)` | 回合开始 |
| `chat/turn-end` | emit | `(turn_id, events)` | 回合结束 |
| `kernel/cell-start` | emit | `(code)` | 代码执行开始 |
| `kernel/cell-end` | emit | `(code, output, error)` | 代码执行结束 |
| `model/request` | emit | `(messages, tools)` | LLM 请求 |
| `model/response` | emit | `(chunks)` | LLM 响应 |

## 开发规范

### 命名约定
- 插件目录：`cordis_harness/plugins/<name>/`
- 服务名：kebab-case（`my-service`）
- 事件名：`<domain>/<action>`（`chat/message`）
- 文件名：snake_case

### 类型约定
- 跨插件数据类型用 `TypedDict` 或 `Protocol`
- 定义在 `cordis_harness/types.py` 或各插件的 `types.py`
- 不使用 dataclass 做跨插件通信（保持结构化兼容）

### 错误处理
- 可恢复错误：带 `kind` 和 `message` 属性的异常
- 不可恢复错误：普通异常，向上传播
- 日志使用 `ctx.logger.error/warn/info/debug`

### 测试
- 每个插件有 `tests/` 目录
- 使用 fakes/mock 替代外部依赖
- 测试文件命名：`test_<feature>.py`

## 目录结构

```
cordis-harness/
├── AGENTS.md                    # 本文件
├── cordis.json                  # 运行时配置
├── pyproject.toml               # 项目元数据和依赖
├── src/
│   └── cordis_harness/
│       ├── __init__.py          # 入口点 main()
│       ├── __main__.py          # python -m 支持
│       ├── types.py             # 共享类型定义
│       ├── bootstrap.py         # 启动逻辑
│       ├── config.py            # 配置加载
│       └── plugins/
│           ├── models/          # LLM 模型服务
│           │   ├── __init__.py  # wiring
│           │   ├── llm.py       # 纯业务逻辑
│           │   └── types.py
│           ├── agent/           # Agent 循环
│           │   ├── __init__.py
│           │   ├── loop.py
│           │   └── types.py
│           ├── kernel/          # 代码执行
│           │   ├── __init__.py
│           │   ├── executor.py
│           │   └── types.py
│           ├── context/         # 项目上下文
│           │   ├── __init__.py
│           │   └── project.py
│           ├── commands/        # 命令注册表
│           │   ├── __init__.py
│           │   └── registry.py
│           ├── chat/            # 会话管理
│           │   ├── __init__.py
│           │   └── session.py
│           └── transcript/      # 历史记录
│               ├── __init__.py
│               └── store.py
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_agent.py
    ├── test_kernel.py
    └── ...
```

Cordis Harness 说明

| Cordis Harness | 说明 |
|-------------------|------|
| `ctx.plugin()` + `Service` 或函数插件 | 简化为直接注册 |
| `ctx.fiber.effect()` | 资源管理 |
| `ctx.fiber.effect()` + 注册回调 | Broker 模式 |
| `asyncio.create_task()` + effect cleanup | 后台任务 |
| `cordis.json` | JSON 配置 |
| `create_context()` + `ctx.plugin()` | 简化启动 |
| 手动 reload 或文件监控 | 可选热重载 |
| Fiber | 插件实例 |
| `typing.Protocol` | 相同 |
| `types.py` + AGENTS.md | 内联到代码 |

## 快速开始

```bash
# 安装依赖
cd cordis-harness
pip install -e .

# 运行
python -m cordis_harness

# 或使用 CLI
cordis-harness
```
