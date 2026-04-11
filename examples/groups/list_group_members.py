# -*- coding: utf-8 -*-
r"""读取群成员列表。

使用步骤：
1. 把 `GROUP_NAME` 改成你的群名称。
2. 运行：
   `python examples\groups\list_group_members.py`

说明：
- 如果群成员很多，库内部会自动尝试展开“查看更多”。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


GROUP_NAME = "群名称"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在读取群成员：{GROUP_NAME}")
        members = wx.group_manager.get_group_members(GROUP_NAME)

    print(f"共获取到 {len(members)} 名成员：")
    for member in members:
        print(f"- {member}")


if __name__ == "__main__":
    main()
