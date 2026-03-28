"""
修改群公告（纯文本）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src import WeChatClient

wx = WeChatClient()
wx.connect()

wx.group_manager.modify_announcement_simple("群名称", "欢迎加入！请遵守群规。")

wx.disconnect()
