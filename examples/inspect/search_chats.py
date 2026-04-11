# -*- coding: utf-8 -*-
r"""搜索联系人或群聊。

使用步骤：
1. 把 `KEYWORD` 改成你要搜索的关键词。
2. 运行：
   `python examples\inspect\search_chats.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


KEYWORD = "张三"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在搜索：{KEYWORD}")
        results = wx.chat_window.search(KEYWORD)

    for group_name, items in results.items():
        print(f"[{group_name}]")
        for item in items:
            print(f"- {item.name}")

    contacts = results.get("联系人", [])
    groups = results.get("群聊", [])
    print(f"\n联系人 {len(contacts)} 个，群聊 {len(groups)} 个")


if __name__ == "__main__":
    main()
