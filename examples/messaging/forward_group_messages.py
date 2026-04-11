# -*- coding: utf-8 -*-
r"""监听群消息并按规则转发。

使用步骤：
1. 按 `RULES` 里的格式改成你的群名和目标联系人。
2. 运行：
   `python examples\messaging\forward_group_messages.py`

说明：
- 第一条规则：测试龙虾1 的所有消息都转发。
- 第二条规则：测试龙虾2 只有命中关键词才转发。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import ForwardRuleHandler, ForwardTarget, GroupForwardRule, WeChatClient


RULES = [
    GroupForwardRule(
        source_group="测试龙虾1",
        targets=[ForwardTarget("大号", target_type="contact")],
        prefix_template="[测试龙虾1] ",
    ),
    GroupForwardRule(
        source_group="测试龙虾2",
        targets=["大号"],
        mode="keyword",
        keywords=["紧急", "严重", "告警"],
        prefix_template="[测试龙虾2] ",
    ),
]


def main() -> None:
    with WeChatClient(auto_connect=True) as wx:
        print("开始监听并转发群消息...")
        wx.process_groups(
            [rule.source_group for rule in RULES],
            [ForwardRuleHandler(RULES)],
            block=True,
            tick=0.1,
            batch_size=8,
            tail_size=8,
        )


if __name__ == "__main__":
    main()
