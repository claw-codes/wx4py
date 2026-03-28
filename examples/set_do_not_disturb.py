"""
设置群消息免打扰
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.group_manager.set_do_not_disturb("群名称", enable=True)

wx.disconnect()
