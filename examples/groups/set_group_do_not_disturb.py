# -*- coding: utf-8 -*-
r"""设置群消息免打扰。

使用步骤：
1. 把 `GROUP_NAME` 改成你的群名称。
2. 把 `ENABLE` 改成：
   - `True`：开启免打扰
   - `False`：关闭免打扰
3. 运行：
   `python examples\groups\set_group_do_not_disturb.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


GROUP_NAME = "群名称"
ENABLE = True


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        action_text = "开启" if ENABLE else "关闭"
        print(f"正在{action_text}群免打扰：{GROUP_NAME}")
        wx.group_manager.set_do_not_disturb(GROUP_NAME, enable=ENABLE)
        print("设置完成")


if __name__ == "__main__":
    main()
