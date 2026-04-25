# -*- coding: utf-8 -*-
"""
群聊消息监听示例：OCR 识别发送者昵称和微信ID

本示例展示了如何使用 OCR + MemberRegistry 来识别消息发送者。

发送者识别流程（自动）：
1. 使用 PaddleOCR 截图识别消息发送者昵称
2. 通过 MemberRegistry 精确匹配或模糊匹配获取微信ID
3. 如果 MemberRegistry 中没有注册成员，自动注册群成员

自动注册流程：
- 首次监听某个群时，会自动获取群成员列表
- 逐个点击成员头像获取微信ID（需要成员公开微信ID）
- 保存到 group_members.json 文件

前置要求：
- 微信 4.x 的 UI Automation 不暴露发送者信息
- 解决方案：使用 OCR 识别昵称 + MemberRegistry 关联微信ID
- PaddleOCR 需要安装：pip install paddlepaddle paddleocr
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import MemberRegistry, WeChatClient
from src.features.messaging.listener import WeChatGroupListener


# 配置要监听的群聊列表（可以添加多个群）
GROUPS = [
    "群名称1",  # 修改为你要监听的群名称
    # "群名称2",
    # "群名称3",
]


def on_message(event):
    """消息回调函数，演示如何获取发送者信息"""
    print(f"\n{'='*60}")
    print(f"收到消息!")
    print(f"  群聊: {event.group}")
    if event.sender_name:
        if event.sender_wxid:
            print(f"  发送者: {event.sender_name} ({event.sender_wxid})")
        else:
            print(f"  发送者: {event.sender_name} (微信ID未注册)")
    else:
        print(f"  发送者: [未知]")
    print(f"  消息内容: {event.content[:100]}")
    print(f"  是否 @ 我: {event.is_at_me}")
    print(f"{'='*60}")


def main():
    """主函数"""
    # 创建成员注册表
    registry = MemberRegistry()

    # 尝试从文件加载已保存的成员信息
    members_file = "group_members.json"
    if Path(members_file).exists():
        registry.load_from_file(members_file)
        total_members = sum(len(members) for members in registry._members.values())
        if total_members > 0:
            print(f"✓ 已从 {members_file} 加载 {total_members} 名群成员")

    # 创建客户端并启动监听
    with WeChatClient(auto_connect=True) as wx:
        print(f"\n开始监听群聊: {', '.join(GROUPS)}")
        print("=" * 60)
        print("说明:")
        print("  - 首次监听会自动注册群成员（需要一些时间）")
        print("  - 成员信息保存在 group_members.json")
        print("  - 发送者识别使用 OCR + 模糊匹配")
        print("=" * 60)
        print()

        # 创建监听器（会自动注册群成员）
        listener = WeChatGroupListener(
            client=wx,
            groups=GROUPS,
            on_message=on_message,
            member_registry=registry,
            auto_reply=False,  # 只监听，不自动回复
            # 如果需要 AI 自动回复，可以设置：
            # auto_reply=True,
            # reply_on_at=True,  # 只在被 @ 时回复
        )

        # 开始监听
        listener.start(block=True)


if __name__ == "__main__":
    main()
