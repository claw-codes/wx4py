"""
获取群成员列表

注意: 如果群成员超过默认展示数量，需要先触发"查看更多"才能获取完整列表。
      get_group_members 内部已自动处理。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

members = wx.group_manager.get_group_members("群名称")

print(f"共 {len(members)} 名成员:")
for m in members:
    print(f"  {m}")

wx.disconnect()
