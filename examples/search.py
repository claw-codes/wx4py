"""
搜索联系人 / 群聊

search() 返回按分组划分的结果字典，key 为分组名（联系人、群聊、功能等）。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

results = wx.chat_window.search("张三")

for group_name, items in results.items():
    print(f"[{group_name}]")
    for item in items:
        print(f"  {item.name}")

# 只取联系人分组
contacts = results.get("联系人", [])
groups   = results.get("群聊", [])
print(f"\n联系人: {len(contacts)} 条，群聊: {len(groups)} 条")

wx.disconnect()
