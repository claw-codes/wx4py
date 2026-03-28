"""
发送消息到群聊
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.chat_window.send_to("群名称", "Hello!", target_type='group')

wx.disconnect()
