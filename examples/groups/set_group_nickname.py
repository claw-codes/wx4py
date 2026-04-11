# -*- coding: utf-8 -*-
r"""设置我在群里的昵称。

使用步骤：
1. 把 `GROUP_NAME` 改成你的群名称。
2. 把 `NEW_NICKNAME` 改成你想设置的新群昵称。
3. 运行：
   `python examples\groups\set_group_nickname.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


GROUP_NAME = "测试龙虾1"
NEW_NICKNAME = "新昵称"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在设置群昵称，群名：{GROUP_NAME}")
        wx.group_manager.set_group_nickname(GROUP_NAME, NEW_NICKNAME)
        print("设置完成")


if __name__ == "__main__":
    main()
