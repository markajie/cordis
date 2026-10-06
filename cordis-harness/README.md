# Cordis Harness

AI 编码助手运行时，基于 [Cordis](../cordis/) 插件框架构建。

配置使用 `cordis.json`。

## 快速开始

```bash
# 安装依赖
cd cordis-harness
pip install -e .

# 设置 API Key
export OPENAI_API_KEY="sk-..."

# 运行
python -m cordis_harness
# 或
cordis-harness
```

## 命令行选项

```
cordis-harness [--config FILE] [--model NAME] [--no-sandbox]
```

| 选项 | 说明 |
|------|------|
| `--config, -c` | 指定配置文件路径（默认 `./cordis.json`） |
| `--model, -m` | 覆盖默认模型名 |
| `--no-sandbox` | 禁用内核沙箱 |

## 架构

```
用户输入 → chat → agent.loop → model.complete() → LLM API
                              ↓
                         kernel.run(code) → Python 执行
                              ↓
                         transcript.append() → 历史记录
```

### 插件清单

| 插件 | 服务名 | 职责 |
|------|--------|------|
| transcript | `transcript` | 对话历史持久化（JSONL） |
| commands | `commands` | 斜杠命令注册表 |
| kernel | `kernel` | Python 代码执行 |
| context | `system` | 项目上下文（工作目录、CLAUDE.md） |
| models | `model` | LLM 模型调用（OpenAI 兼容） |
| agent | `loop` | Agent 对话循环 |
| chat | `done` | 交互式会话管理 |

## 配置

编辑 `cordis.json`：

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
  "agent": { "max_nudges": 2 },
  "kernel": { "sandbox": false, "timeout": 30 },
  "context": { "project_dir": ".", "instructions_file": "CLAUDE.md" },
  "transcript": { "path": null }
}
```

## 开发

参见 [AGENTS.md](AGENTS.md) 获取完整的开发指引和 API 参考。

参见 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 获取开发计划和进度。
