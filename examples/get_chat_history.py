"""
获取聊天记录

注意: 微信 Qt 版不暴露发送者信息，每条消息只有内容和时间戳。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

messages = wx.chat_window.get_chat_history("群名称", target_type="group", max_count=50)

print(messages)

wx.disconnect()
