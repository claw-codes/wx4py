# -*- coding: utf-8 -*-
r"""设置聊天置顶或取消置顶。

使用步骤：
1. 把 `CHAT_NAME` 改成你的联系人或群名称。
2. 把 `ENABLE` 改成：
   - `True`：置顶
   - `False`：取消置顶
3. 运行：
   `python examples\groups\set_chat_pinned.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


CHAT_NAME = "测试龙虾1"
ENABLE = True


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        action_text = "置顶" if ENABLE else "取消置顶"
        print(f"正在{action_text}聊天：{CHAT_NAME}")
        wx.group_manager.set_pin_chat(CHAT_NAME, enable=ENABLE)
        print("设置完成")


if __name__ == "__main__":
    main()
