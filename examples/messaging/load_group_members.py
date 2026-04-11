# -*- coding: utf-8 -*-
"""
群成员管理示例：自动获取群成员信息并关联微信ID

本示例展示了如何：
1. 获取群成员列表
2. 自动获取每个成员的微信ID（通过资料卡）
3. 保存和加载成员信息

使用说明：
运行本脚本后，会自动获取群成员列表，然后逐个点击成员头像获取微信ID。
注意：由于需要打开资料卡获取微信ID，速度较慢（约3-5秒/成员）。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import MemberRegistry, WeChatClient


def main():
    """主函数"""
    group_name = "家庭龙虾"
    members_file = "group_members.json"

    # 创建成员注册表
    registry = MemberRegistry()

    # 尝试从文件加载已保存的成员信息
    if Path(members_file).exists():
        registry.load_from_file(members_file)
        print(f"已加载 {len(registry._members.get(group_name, {}))} 名已注册的成员")
    else:
        print("未找到成员信息文件，将创建新文件")

    with WeChatClient(auto_connect=True) as wx:
        # 获取群成员列表
        print(f"\n正在获取群成员: {group_name}")
        members = wx.group_manager.get_group_members(group_name)

        if not members:
            print("未获取到群成员，请检查群名是否正确")
            return

        print(f"\n获取到 {len(members)} 名群成员:")
        for i, member in enumerate(members, 1):
            print(f"  {i}. {member}")

        # 检查需要获取微信ID的成员
        members_to_fetch = []
        for member in members:
            existing_wxid = registry.get_wxid(group_name, member)
            if existing_wxid:
                print(f"\n[已有] {member} -> {existing_wxid}")
            else:
                members_to_fetch.append(member)

        if members_to_fetch:
            print(f"\n需要获取微信ID的成员: {len(members_to_fetch)} 人")
            print("-" * 60)
            print("提示: 这将逐个打开成员资料卡获取微信ID")
            print("      速度较慢（约3-5秒/成员），请耐心等待...")
            print("-" * 60)

            # 逐个获取微信ID
            for i, member in enumerate(members_to_fetch, 1):
                print(f"\n[{i}/{len(members_to_fetch)}] 获取 {member} 的微信ID...")

                wxid = wx.group_manager.get_member_wxid(group_name, member)

                if wxid:
                    registry.add_member(group_name, member, wxid)
                    print(f"  ✓ 成功: {member} -> {wxid}")
                else:
                    print(f"  ✗ 失败: 无法获取 {member} 的微信ID")

                # 短暂等待让UI稳定
                import time
                time.sleep(1)

        # 保存成员信息到文件
        print(f"\n保存成员信息到 {members_file}...")
        registry.save_to_file(members_file)

        # 显示当前注册表内容
        registered_count = len(registry._members.get(group_name, {}))
        print(f"\n完成！当前已注册 {registered_count} / {len(members)} 名成员")

        # 显示所有成员
        print(f"\n所有成员信息:")
        print("=" * 60)
        for member in members:
            wxid = registry.get_wxid(group_name, member)
            if wxid:
                print(f"  {member:20s} -> {wxid}")
            else:
                print(f"  {member:20s} -> (未获取微信ID)")
        print("=" * 60)


if __name__ == "__main__":
    main()
