"""
插件：AgentLoop（Service 类 / Consumer）

消费 ctx.llm + ctx.tools，串起一次"对话"。
只知道这两个接口，不知道 Provider 是 DeepSeek 还是 Echo，
也不知道有哪些工具 —— 完全解耦。

对应 Cordis 的 packages/core/agent-loop。
"""

from cordis import Service

name = 'agent-loop'
inject = ['llm', 'tools']
provide = ['agents']


class AgentLoop(Service):
    """Agent 循环：LLM 调用 → tool_call → 执行工具 → 回传结果"""

    def __init__(self, ctx):
        super().__init__(ctx, 'agents')

    async def run(self, user_input: str, max_turns: int = 5) -> str:
        """
        执行一次完整的 agent 循环。

        1. 发 user_input 给 LLM
        2. 如果 LLM 返回 tool_call → 执行工具 → 把结果回传 LLM
        3. 如果 LLM 返回文本 → 结束
        4. 最多循环 max_turns 次
        """
        messages = [{'role': 'user', 'content': user_input}]

        for turn in range(max_turns):
            chunks = list(self.ctx.llm.stream(messages))

            tool_calls = [c for c in chunks if c.get('type') == 'tool_call']
            text_chunks = [c for c in chunks if c.get('type') == 'text']

            if tool_calls:
                # LLM 要求执行工具
                for tc in tool_calls:
                    tool_name = tc['tool']
                    tool_args = tc.get('args', {})

                    result = await self.ctx.tools.execute(tool_name, tool_args)

                    messages.append({
                        'role': 'tool',
                        'tool_name': tool_name,
                        'content': str(result),
                    })
            else:
                # LLM 返回最终文本
                return ''.join(c.get('content', '') for c in text_chunks)

        return '[max turns reached]'
