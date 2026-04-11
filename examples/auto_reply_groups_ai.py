# -*- coding: utf-8 -*-
"""接入 AI 的群聊自动回复示例。

运行前设置环境变量：
    PowerShell:
        $env:SILICONFLOW_API_KEY="你的 API Key"
        python examples\auto_reply_groups_ai.py

可选环境变量：
    SILICONFLOW_BASE_URL: 默认 https://api.siliconflow.cn/v1
    SILICONFLOW_MODEL:    默认 Pro/deepseek-ai/DeepSeek-V3.2
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 支持源码直接运行
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import AIClient, AIConfig, AIResponder, WeChatClient


GROUPS = ["群名称1", "群名称2", "群名称3"]


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


if __name__ == "__main__":
    wx = WeChatClient(auto_connect=True)
    try:
        wx.auto_reply_groups(
            GROUPS,
            build_responder(),
            block=True,
            reply_on_at=True,
            tick=0.1,
            batch_size=8,
            tail_size=8,
        )
    finally:
        wx.disconnect()
