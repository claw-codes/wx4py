"""
批量发送消息到多个群
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

results = wx.chat_window.batch_send(
    targets=["群聊1", "群聊2", "群聊3"],
    message="通知：今晚8点开会",
    target_type='group',
)

for name, ok in results.items():
    print(f"{name}: {'成功' if ok else '失败'}")

wx.disconnect()
