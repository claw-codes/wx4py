"""
发送单个文件
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.chat_window.send_file_to("文件传输助手", r"D:\path\test_send_file.txt")

wx.disconnect()
