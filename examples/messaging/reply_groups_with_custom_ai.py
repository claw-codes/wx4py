# -*- coding: utf-8 -*-
r"""接入你自己的 AI 服务做群聊自动回复。

使用步骤：
1. 把 `GROUPS` 改成你要监听的群名称列表。
2. 把 `call_your_ai_service()` 改成你的真实 AI 调用。
3. 运行：
   `python examples\messaging\reply_groups_with_custom_ai.py`

说明：
- 普通消息只监听不回复。
- 只有被 @ 时才调用你的 AI 服务。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import AsyncCallbackHandler, MessageEvent, WeChatClient


GROUPS = ["群名称1", "群名称2", "群名称3"]


def call_your_ai_service(group: str, message: str) -> str:
    """这里替换成你的真实 AI 调用。"""
    return f"收到：{message}"


def custom_reply(event: MessageEvent) -> str:
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


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print("开始监听群消息，并在被 @ 时调用自定义 AI...")
        wx.process_groups(
            GROUPS,
            [
                AsyncCallbackHandler(
                    custom_reply,
                    auto_reply=True,
                    reply_on_at=True,
                )
            ],
            block=True,
            tick=0.1,
            batch_size=8,
            tail_size=8,
        )


if __name__ == "__main__":
    main()
