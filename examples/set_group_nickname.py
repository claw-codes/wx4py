"""
设置我在群里的昵称
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.group_manager.set_group_nickname("群名称", "新昵称")

wx.disconnect()
