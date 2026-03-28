"""
置顶 / 取消置顶聊天
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import (WeChatClient)

wx = WeChatClient()
wx.connect()

wx.group_manager.set_pin_chat("测试龙虾1", enable=True)

wx.disconnect()
