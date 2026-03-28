"""
发送消息给联系人
"""
import sys
from pathlib import Path

# 支持源码直接运行
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.chat_window.send_to("文件传输助手", "Hello!", target_type='contact')

wx.disconnect()
