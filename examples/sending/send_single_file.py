# -*- coding: utf-8 -*-
r"""给联系人发送一个文件。

使用步骤：
1. 把 `TARGET_NAME` 改成你的联系人或群名称。
2. 把 `FILE_PATH` 改成你要发送的文件路径。
3. 如需发给群，把 `TARGET_TYPE` 改成 `group`。
4. 运行：
   `python examples\sending\send_single_file.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


TARGET_NAME = "文件传输助手"
TARGET_TYPE = "contact"
FILE_PATH = Path(r"E:\MyProject\me\测试\test_announcement.md")


def main() -> None:
    if not FILE_PATH.exists():
        raise FileNotFoundError(f"找不到文件：{FILE_PATH}")

    with WeChatClient(auto_connect=True) as wx:
        print(f"正在发送文件到：{TARGET_NAME}")
        wx.chat_window.send_file_to(TARGET_NAME, str(FILE_PATH), target_type=TARGET_TYPE)
        print("发送完成")


if __name__ == "__main__":
    main()
