# -*- coding: utf-8 -*-
r"""给联系人发送一条文本消息。

使用步骤：
1. 把 `CONTACT_NAME` 改成你的联系人名称。
2. 把 `MESSAGE` 改成你想发送的内容。
3. 运行：
   `python examples\sending\send_contact_message.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


CONTACT_NAME = "文件传输助手"
MESSAGE = "你好，这是一条测试消息。"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在给联系人发送消息：{CONTACT_NAME}")
        wx.chat_window.send_to(CONTACT_NAME, MESSAGE, target_type="contact")
        print("发送完成")


if __name__ == "__main__":
    main()
