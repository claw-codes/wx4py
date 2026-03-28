# -*- coding: utf-8 -*-
"""
wx4py Client

Main entry point for wx4py.
"""
from .core.window import WeChatWindow
from .core.exceptions import WeChatError, WeChatNotFoundError
from .pages.chat_window import ChatWindow
from .pages.group_manager import GroupManager
from .utils.logger import get_logger

logger = get_logger(__name__)


class WeChatClient:
    """
    wx4py Client

    Main class for automating WeChat on Windows.

    Usage:
        wx = WeChatClient()
        wx.connect()

        # Send message to contact
        wx.chat_window.send_to("大号", "Hello!")

        # Send message to group
        wx.chat_window.send_to("测试群", "Hello!", target_type='group')

        # Batch send
        wx.chat_window.batch_send(["群1", "群2"], "Hello!")
    """

    def __init__(self, auto_connect: bool = False):
        """
        Initialize WeChat client.

        Args:
            auto_connect: If True, automatically connect on initialization
        """
        self._window = WeChatWindow()
        self._chat_window: ChatWindow = None
        self._group_manager: GroupManager = None

        if auto_connect:
            self.connect()

    def connect(self) -> bool:
        """
        Connect to WeChat window.

        This will:
        1. Check and fix registry (RunningState)
        2. Find and bind to WeChat window
        3. Initialize UIAutomation

        Returns:
            bool: True if connected successfully

        Raises:
            WeChatNotFoundError: If WeChat not found
        """
        logger.info("Connecting to WeChat...")
        result = self._window.connect()
        if result:
            self._chat_window = ChatWindow(self._window)
            self._group_manager = GroupManager(self._window)
        return result

    def disconnect(self) -> None:
        """Disconnect from WeChat window"""
        self._window.disconnect()
        self._chat_window = None
        self._group_manager = None
        logger.info("Disconnected from WeChat")

    @property
    def window(self) -> WeChatWindow:
        """Get window manager"""
        return self._window

    @property
    def chat_window(self) -> ChatWindow:
        """Get chat window page for sending messages"""
        if not self._chat_window:
            raise WeChatNotFoundError("Not connected to WeChat")
        return self._chat_window

    @property
    def group_manager(self) -> GroupManager:
        """Get group manager for group operations"""
        if not self._group_manager:
            raise WeChatNotFoundError("Not connected to WeChat")
        return self._group_manager

    @property
    def is_connected(self) -> bool:
        """Check if connected to WeChat"""
        return self._window.is_connected

    def __enter__(self):
        """Context manager entry"""
        if not self.is_connected:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
        return False