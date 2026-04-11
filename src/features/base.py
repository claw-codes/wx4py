# -*- coding: utf-8 -*-
"""微信 UI 页面基类"""
import time
from ..config import OPERATION_INTERVAL
from ..core.win32 import minimize_window


class BasePage:
    """页面对象基类"""

    def __init__(self, window):
        """
        初始化基础页面。

        Args:
            window: WeChatWindow 实例
        """
        self._window = window

    @property
    def uia(self):
        """获取 UIAutomation 封装器"""
        return self._window.uia

    @property
    def root(self):
        """获取根控件"""
        return self._window.uia.root

    def wait(self, seconds: float = None):
        """等待指定时间"""
        time.sleep(seconds or OPERATION_INTERVAL)
        return self

    def find_control(self, control_type: str = None, **kwargs):
        """查找控件"""
        return self.uia.find_control(control_type, **kwargs)

    def _minimize_window(self) -> bool:
        """最小化微信窗口，保护用户隐私"""
        try:
            hwnd = self._window.hwnd
            if hwnd:
                return minimize_window(hwnd)
        except Exception:
            pass
        return False
