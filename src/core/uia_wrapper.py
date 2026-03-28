# -*- coding: utf-8 -*-
"""UIAutomation wrapper for WeChat"""
import sys
import os

from . import uiautomation as uia

from .exceptions import ControlNotFoundError
from ..config import SEARCH_TIMEOUT
from ..utils.logger import get_logger

logger = get_logger(__name__)


class UIAWrapper:
    """Wrapper for UIAutomation operations"""

    def __init__(self, hwnd: int = None):
        """
        Initialize UIA wrapper.

        Args:
            hwnd: Optional window handle to bind
        """
        self._root: uia.WindowControl = None
        if hwnd:
            self.bind(hwnd)

    def bind(self, hwnd: int) -> None:
        """
        Bind to a window by handle.

        Args:
            hwnd: Window handle
        """
        self._root = uia.ControlFromHandle(hwnd)
        if not self._root:
            raise ControlNotFoundError(f"Cannot get UIAutomation control from handle {hwnd}")
        logger.debug(f"Bound to window: {self._root.Name}")

    @property
    def root(self) -> uia.WindowControl:
        """Get root control"""
        return self._root

    def find_control(self, control_type: str = None, name: str = None,
                     class_name: str = None, automation_id: str = None,
                     timeout: float = None) -> uia.Control:
        """
        Find a control by attributes.

        Args:
            control_type: Control type (Button, Edit, etc.)
            name: Control name
            class_name: Control class name
            automation_id: Automation ID
            timeout: Search timeout in seconds

        Returns:
            Control if found

        Raises:
            ControlNotFoundError: If control not found
        """
        timeout = timeout or SEARCH_TIMEOUT
        kwargs = {'searchDepth': 10}

        if name:
            kwargs['Name'] = name
        if class_name:
            kwargs['ClassName'] = class_name
        if automation_id:
            kwargs['AutomationId'] = automation_id

        # Get control by type
        control_type = control_type or 'Control'
        getter = getattr(self._root, f'{control_type}Control', None)
        if not getter:
            getter = self._root.Control

        ctrl = getter(**kwargs)
        if ctrl.Exists(maxSearchSeconds=timeout):
            return ctrl

        raise ControlNotFoundError(
            f"Control not found: type={control_type}, name={name}, "
            f"class={class_name}, id={automation_id}"
        )

    def find_all_controls(self, control_type: str = None, **kwargs) -> list:
        """
        Find all matching controls.

        Args:
            control_type: Control type
            **kwargs: Additional filter arguments

        Returns:
            List of controls
        """
        getter = getattr(self._root, f'{control_type}Control', self._root.Control)
        ctrl = getter(searchDepth=10, **kwargs)
        return ctrl.GetChildren() if ctrl.Exists() else []

    def click(self, control: uia.Control) -> bool:
        """
        Click a control.

        Args:
            control: Control to click

        Returns:
            bool: True if successful
        """
        try:
            control.Click()
            logger.debug(f"Clicked control: {control.Name}")
            return True
        except Exception as e:
            logger.error(f"Failed to click control: {e}")
            return False

    def send_keys(self, control: uia.Control, text: str) -> bool:
        """
        Send keys to a control.

        Args:
            control: Target control
            text: Text to send

        Returns:
            bool: True if successful
        """
        try:
            control.SendKeys(text)
            logger.debug(f"Sent keys to control: {text[:20]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send keys: {e}")
            return False