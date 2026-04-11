# -*- coding: utf-8 -*-
r"""接入 AI 做群聊自动回复。

使用步骤：
1. 先设置环境变量：
   - `SILICONFLOW_API_KEY`
2. 把 `GROUPS` 改成你要监听的群名称列表。
3. 运行：
   `python examples\messaging\reply_groups_with_ai.py`

说明：
- 只有被 @ 时才会触发 AI 回复。
- 其余消息只监听，不自动回复。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import AIClient, AIConfig, AIResponder, AsyncCallbackHandler, WeChatClient


GROUPS = ["测试龙虾1", "测试龙虾2", "测试龙虾3"]


def build_responder() -> AIResponder:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("请先设置环境变量 SILICONFLOW_API_KEY")

    ai = AIClient(
        AIConfig(
            base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            api_format="completions",
            model=os.getenv("SILICONFLOW_MODEL", "Pro/deepseek-ai/DeepSeek-V3.2"),
            api_key=api_key,
            temperature=0.7,
            max_tokens=300,
            enable_thinking=False,
        )
    )
    return AIResponder(ai, context_size=8, reply_on_at=True)


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print("开始监听群消息，并在被 @ 时调用 AI 回复...")
        wx.process_groups(
            GROUPS,
            [
                AsyncCallbackHandler(
                    build_responder(),
                    auto_reply=True,
                )
            ],
            block=True,
            tick=0.1,
            batch_size=8,
            tail_size=8,
        )


if __name__ == "__main__":
    main()
