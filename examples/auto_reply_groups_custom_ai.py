# -*- coding: utf-8 -*-
"""自定义接入 AI 的群聊自动回复示例。

这个示例刻意不使用 wx4py 内置的 AIClient。
只要你提供一个接收 MessageEvent、返回字符串的函数，就可以接入任意 AI：
    - 自己的 HTTP 服务
    - OpenAI / SiliconFlow / Anthropic 等官方 SDK
    - 本地模型
    - 企业内部机器人接口

回调返回：
    - 非空字符串：wx4py 自动回复到对应群聊
    - "" 或 None：只监听，不回复
"""

from __future__ import annotations

import sys
from pathlib import Path

# 支持源码直接运行
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import MessageEvent, WeChatClient


GROUPS = ["群名称1", "群名称2", "群名称3"]


def call_your_ai_service(group: str, message: str) -> str:
    """替换成你的任意 AI 调用。

    例如：
        - requests.post("http://localhost:8000/chat", json={...})
        - openai_client.chat.completions.create(...)
        - your_company_bot.reply(...)

    这里只写一个假实现，方便看清接入点。
    """
    return f"收到：{message}"


def custom_reply(event: MessageEvent) -> str:
    """自定义回复逻辑。

    普通消息只打印监听日志；只有 @ 我时才调用自定义 AI。
    """
    print(f"[{event.group}] {event.content}", flush=True)

    if not event.is_at_me:
        return ""

    content = event.content
    if event.group_nickname:
        content = (
            content
            .replace(f"@{event.group_nickname}\u2005", "")
            .replace(f"@{event.group_nickname}", "")
            .strip()
        )

    return call_your_ai_service(event.group, content)


if __name__ == "__main__":
    wx = WeChatClient(auto_connect=True)
    try:
        wx.auto_reply_groups(
            GROUPS,
            custom_reply,
            block=True,
            reply_on_at=True,
            tick=0.1,
            batch_size=8,
            tail_size=8,
        )
    finally:
        wx.disconnect()
