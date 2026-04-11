# -*- coding: utf-8 -*-
r"""给联系人或群聊一次发送多个文件。

使用步骤：
1. 把 `TARGET_NAME` 改成你的联系人或群名称。
2. 把 `FILE_PATHS` 改成你要发送的文件路径列表。
3. 可选：把 `EXTRA_MESSAGE` 改成要附带发送的说明文字。
4. 运行：
   `python examples\sending\send_multiple_files.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


TARGET_NAME = "文件传输助手"
TARGET_TYPE = "contact"
FILE_PATHS = [
    Path(r"E:\MyProject\me\测试\test_announcement.md"),
    Path(r"E:\MyProject\me\测试\test_announcement.md"),
]
EXTRA_MESSAGE = "这是随文件一起发送的说明。"


def main() -> None:
    missing_files = [str(path) for path in FILE_PATHS if not path.exists()]
    if missing_files:
        raise FileNotFoundError(f"下面这些文件不存在：{missing_files}")

    with WeChatClient(auto_connect=True) as wx:
        print(f"正在发送多个文件到：{TARGET_NAME}")
        wx.chat_window.send_file_to(
            TARGET_NAME,
            [str(path) for path in FILE_PATHS],
            message=EXTRA_MESSAGE,
            target_type=TARGET_TYPE,
        )
        print("发送完成")


if __name__ == "__main__":
    main()
