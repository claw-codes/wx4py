# -*- coding: utf-8 -*-
"""
Example: Set group announcement from markdown file

This scripts demonstrates how to set a WeChat group announcement
from a markdown file with proper formatting preservation.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 使用库正式导入是这样的方式
# from wx4py import WeChatClient

# 拉取代码直接测试的话，IDE里使用这样的
from src import WeChatClient


def main():
    """Set announcement from markdown file"""
    try:
        # Initialize client
        wx = WeChatClient()
        print("Connecting to WeChat...")
        wx.connect()
        print("Connected!")

        # Set announcement from markdown file
        md_file = "D:\\project\\me\\wechat-skill_bak\\test_announcement.md"
        group_name = "群名称"

        print(f"\nSetting announcement for: {group_name}")
        print(f"From file: {md_file}")

        success = wx.group_manager.set_announcement_from_markdown(
            group_name=group_name,
            md_file_path=str(md_file)
        )

        if success:
            print("\n[SUCCESS] Announcement set successfully!")
        else:
            print("\n[FAILED] Failed to set announcement")

        wx.disconnect()

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
