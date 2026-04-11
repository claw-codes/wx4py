# -*- coding: utf-8 -*-
r"""读取聊天记录。

使用步骤：
1. 把 `CHAT_NAME` 改成你的联系人或群名称。
2. 把 `TARGET_TYPE` 改成 `contact` 或 `group`。
3. 把 `MAX_COUNT` 改成想读取的消息条数。
4. 运行：
   `python examples\inspect\inspect_chat_history.py`

说明：
- 微信 Qt 版通常拿不到稳定的发送者信息，返回内容以消息文本为主。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


CHAT_NAME = "群名称"
TARGET_TYPE = "group"
MAX_COUNT = 50


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在读取聊天记录：{CHAT_NAME}")
        messages = wx.chat_window.get_chat_history(
            CHAT_NAME,
            target_type=TARGET_TYPE,
            max_count=MAX_COUNT,
        )

    print("读取结果：")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
