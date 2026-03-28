"""
import sys
"""
import sys
from pathlib import Path

# 支持源码直接运行
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.chat_window.send_file_to(
    "文件传输助手",
    [r"D:\path\test_send_file.txt", r"D:\path\微信图片_20260327102019.jpg"],
    message='携带信息'
)

wx.disconnect()
