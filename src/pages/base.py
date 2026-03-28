# -*- coding: utf-8 -*-
"""Base page class for WeChat UI pages"""
import time
from ..config import OPERATION_INTERVAL


class BasePage:
    """Base class for page objects"""

    def __init__(self, window):
        """
        Initialize base page.

        Args:
            window: WeChatWindow instance
        """
        self._window = window

    @property
    def uia(self):
        """Get UIAutomation wrapper"""
        return self._window.uia

    @property
    def root(self):
        """Get root control"""
        return self._window.uia.root

    def wait(self, seconds: float = None):
        """Wait for a moment"""
        time.sleep(seconds or OPERATION_INTERVAL)
        return self

    def find_control(self, control_type: str = None, **kwargs):
        """Find a control"""
        return self.uia.find_control(control_type, **kwargs)