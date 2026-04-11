# -*- coding: utf-8 -*-
r"""给群聊发送一条文本消息。

使用步骤：
1. 把 `GROUP_NAME` 改成你的群名称。
2. 把 `MESSAGE` 改成你想发送的内容。
3. 运行：
   `python examples\sending\send_group_message.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


GROUP_NAME = "群名称"
MESSAGE = "大家好，这是一条群消息测试。"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在给群发送消息：{GROUP_NAME}")
        wx.chat_window.send_to(GROUP_NAME, MESSAGE, target_type="group")
        print("发送完成")


if __name__ == "__main__":
    main()
