"""
插件：llm-logger（函数插件 / waterfall 拦截）

通过 ctx.on('llm/stream', ...) 拦截每次 LLM 调用，打印日志。

演示 waterfall 洋葱模型：
  前置（记请求）→ next() 委派 → 后置（记耗时）

卸载时 listener 自动被 fiber teardown 摘除。

对应 Cordis 里各种挂 llm/stream 的审计/重试插件。
"""

import time

name = 'llm-logger'
inject = ['llm']


def apply(ctx, config):
    """挂 waterfall listener 到 llm/stream"""

    def log_stream(options, next_fn):
        # ── 前置 ──
        model = options.get('model', '?')
        msg_count = len(options.get('messages', []))
        print(f'  [llm-logger] >>> stream: model={model}, messages={msg_count}')
        start = time.time()

        # ── 委派（必须调 next_fn，否则整条链断在这里）──
        stream = next_fn()

        # ── 后置 ──
        elapsed = time.time() - start
        chunks = list(stream)
        print(f'  [llm-logger] <<< stream done: {len(chunks)} chunks, '
              f'{elapsed:.3f}s')

        return iter(chunks)

    ctx.events.on('llm/stream', log_stream)
