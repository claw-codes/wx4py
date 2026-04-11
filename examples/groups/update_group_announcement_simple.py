# -*- coding: utf-8 -*-
r"""直接用纯文本更新群公告。

使用步骤：
1. 把 `GROUP_NAME` 改成你的群名称。
2. 把 `ANNOUNCEMENT` 改成你要设置的公告内容。
3. 运行：
   `python examples\groups\update_group_announcement_simple.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


GROUP_NAME = "测试龙虾1"
ANNOUNCEMENT = "欢迎加入！请遵守群规。"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print(f"正在更新群公告：{GROUP_NAME}")
        wx.group_manager.modify_announcement_simple(GROUP_NAME, ANNOUNCEMENT)
        print("更新完成")


if __name__ == "__main__":
    main()
