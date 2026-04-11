# -*- coding: utf-8 -*-
r"""批量给多个群发送同一条消息。

使用步骤：
1. 把 `GROUP_NAMES` 改成你的群名称列表。
2. 把 `MESSAGE` 改成你想发送的内容。
3. 运行：
   `python examples\sending\send_batch_messages.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import WeChatClient


GROUP_NAMES = ["测试龙虾1", "测试龙虾2", "测试龙虾3"]
MESSAGE = "通知：今晚 8 点开会。"


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print("开始批量发送...")
        results = wx.chat_window.batch_send(
            targets=GROUP_NAMES,
            message=MESSAGE,
            target_type="group",
        )

    print("发送结果：")
    for name, success in results.items():
        print(f"- {name}: {'成功' if success else '失败'}")


if __name__ == "__main__":
    main()
