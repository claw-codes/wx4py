# -*- coding: utf-8 -*-
"""WeChat window management"""
import time

from .uia_wrapper import UIAWrapper
from .exceptions import WeChatNotFoundError
from ..utils.win32 import (
    find_wechat_window,
    bring_window_to_front,
    get_window_title,
    get_window_class,
    check_and_fix_registry,
    restart_wechat_process,
)
from ..utils.logger import get_logger
from ..config import OPERATION_INTERVAL

logger = get_logger(__name__)


class WeChatWindow:
    """WeChat window manager"""

    def __init__(self):
        """Initialize WeChat window manager"""
        self._hwnd: int = None
        self._uia: UIAWrapper = None
        self._initialized = False

    def connect(self) -> bool:
        """
        Connect to WeChat window.

        This method:
        1. Checks and fixes registry for UI Automation
        2. Finds WeChat window
        3. Brings window to front
        4. Initializes UIAutomation

        Returns:
            bool: True if connected successfully

        Raises:
            WeChatNotFoundError: If WeChat window not found
        """
        # Step 1: Check and fix registry
        logger.info("Checking registry for UI Automation...")
        modified = False
        try:
            modified = check_and_fix_registry()
            if modified:
                logger.info("Registry RunningState changed from 0 to 1")
            else:
                logger.debug("Registry RunningState is correct (not 0)")
        except Exception as e:
            logger.warning(f"Registry check failed: {e}")

        # Step 2: Find WeChat window
        logger.info("Finding WeChat window...")
        self._hwnd = find_wechat_window()
        if not self._hwnd:
            raise WeChatNotFoundError(
                "WeChat window not found. Please make sure WeChat is running."
            )

        logger.info(f"Found WeChat window: HWND={self._hwnd}")

        # Step 3: Bring to front
        bring_window_to_front(self._hwnd)
        time.sleep(OPERATION_INTERVAL)

        # Step 3.5: If accessibility registry was changed, restart WeChat and ask user to re-login.
        # In practice this is more reliable than soft-refreshing a potentially white-screen helper window.
        if modified:
            logger.warning(
                "RunningState changed during this connect; restarting WeChat for a clean UIA session."
            )
            restarted = restart_wechat_process(self._hwnd)
            self.disconnect()
            if restarted:
                raise WeChatNotFoundError(
                    "WeChat was restarted to apply accessibility settings. "
                    "Please log in again, keep WeChat in the foreground, then retry."
                )
            raise WeChatNotFoundError(
                "Accessibility settings changed and require a WeChat restart. "
                "Please manually restart WeChat, log in again, then retry."
            )

        # Step 4: Initialize UIAutomation
        logger.info("Initializing UIAutomation...")
        self._uia = UIAWrapper(self._hwnd)

        self._initialized = True
        logger.info("Connected to WeChat successfully")
        return True

    def disconnect(self) -> None:
        """Disconnect from WeChat window"""
        self._hwnd = None
        self._uia = None
        self._initialized = False
        logger.info("Disconnected from WeChat")

    @property
    def hwnd(self) -> int:
        """Get window handle"""
        if not self._initialized:
            raise WeChatNotFoundError("Not connected to WeChat")
        return self._hwnd

    @property
    def uia(self) -> UIAWrapper:
        """Get UIAutomation wrapper"""
        if not self._initialized:
            raise WeChatNotFoundError("Not connected to WeChat")
        return self._uia

    @property
    def is_connected(self) -> bool:
        """Check if connected"""
        return self._initialized and self._hwnd is not None

    @property
    def title(self) -> str:
        """Get window title"""
        if self._hwnd:
            return get_window_title(self._hwnd)
        return ""

    @property
    def class_name(self) -> str:
        """Get window class name"""
        if self._hwnd:
            return get_window_class(self._hwnd)
        return ""

    def refresh(self) -> bool:
        """
        Refresh connection to WeChat window.

        Returns:
            bool: True if refreshed successfully
        """
        self.disconnect()
        return self.connect()

    def activate(self) -> bool:
        """
        Bring WeChat window to front.

        Returns:
            bool: True if successful
        """
        if self._hwnd:
            return bring_window_to_front(self._hwnd)
        return False
