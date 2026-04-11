# -*- coding: utf-8 -*-
r"""用 Markdown 文件更新微信群公告。

适合小白直接改配置后运行。

使用步骤：
1. 先把 `GROUP_NAME` 改成你的群名称。
2. 再把 `MARKDOWN_FILE` 改成你的 Markdown 文件路径。
3. 运行：
   `python examples\groups\update_group_announcement_from_markdown.py`

说明：
- 这个示例会连接已登录的微信。
- Markdown 文件里的内容会被读取后写入群公告。
- 如果路径或群名不对，脚本会直接报错并打印原因。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 支持直接从源码目录运行
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


# 这里改成你的群名称
GROUP_NAME = "测试龙虾1"

# 这里改成你的 Markdown 文件路径
MARKDOWN_FILE = Path(r"E:\MyProject\me\测试\test_announcement.md")


def main() -> None:
    """读取 Markdown 文件并更新指定群的群公告。"""
    if not MARKDOWN_FILE.exists():
        raise FileNotFoundError(f"找不到 Markdown 文件：{MARKDOWN_FILE}")

    wx = WeChatClient()
    try:
        print("正在连接微信...")
        wx.connect()
        print("微信连接成功")

        print(f"准备更新群公告，群名：{GROUP_NAME}")
        print(f"Markdown 文件：{MARKDOWN_FILE}")

        success = wx.group_manager.set_announcement_from_markdown(
            group_name=GROUP_NAME,
            md_file_path=str(MARKDOWN_FILE),
        )

        if success:
            print("群公告更新成功")
        else:
            print("群公告更新失败")
    except Exception as exc:
        print(f"执行失败：{exc}")
        traceback.print_exc()
    finally:
        wx.disconnect()


if __name__ == "__main__":
    main()
