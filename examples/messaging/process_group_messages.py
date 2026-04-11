# -*- coding: utf-8 -*-
r"""在一个处理器里同时做群消息转发和 AI 回复。

使用步骤：
1. 先设置环境变量：
   - `SILICONFLOW_API_KEY`
2. 把下面的群名、联系人名改成你自己的。
3. 运行：
   `python examples\messaging\process_group_messages.py`

说明：
- 所有消息都会先转发给指定联系人。
- 只有被 @ 时，才会调用 AI 在群里回复。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import (
    AIClient,
    AIConfig,
    AIResponder,
    AsyncCallbackHandler,
    ForwardRuleHandler,
    GroupForwardRule,
    WeChatClient,
)


LISTEN_GROUPS = ["测试龙虾1"]
FORWARD_TARGET = "大号"


def build_ai_handler() -> AsyncCallbackHandler:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("请先设置环境变量 SILICONFLOW_API_KEY")

    responder = AIResponder(
        AIClient(
            AIConfig(
                base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
                api_format="completions",
                model=os.getenv("SILICONFLOW_MODEL", "Pro/deepseek-ai/DeepSeek-V3.2"),
                api_key=api_key,
                enable_thinking=False,
            )
        ),
        context_size=8,
        reply_on_at=True,
    )
    return AsyncCallbackHandler(responder, auto_reply=True)


def main() -> None:
    rules = [
        GroupForwardRule(
            source_group=LISTEN_GROUPS[0],
            targets=[FORWARD_TARGET],
            target_type="contact",
            prefix_template="[群消息转发] ",
        )
    ]

    with WeChatClient(auto_connect=True) as wx:
        print("开始监听群消息：转发 + AI 回复")
        wx.process_groups(
            LISTEN_GROUPS,
            [
                ForwardRuleHandler(rules),
                build_ai_handler(),
            ],
            block=True,
            tick=0.1,
            batch_size=8,
            tail_size=8,
        )


if __name__ == "__main__":
    main()
