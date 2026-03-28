# -*- coding: utf-8 -*-
"""Core module - window management and UIAutomation wrapper"""

from .window import WeChatWindow
from .uia_wrapper import UIAWrapper
from .exceptions import (
    WeChatError,
    WeChatNotFoundError,
    WeChatNotConnectedError,
    UIAError,
    ControlNotFoundError,
    RegistryError,
)

__all__ = [
    "WeChatWindow",
    "UIAWrapper",
    "WeChatError",
    "WeChatNotFoundError",
    "WeChatNotConnectedError",
    "UIAError",
    "ControlNotFoundError",
    "RegistryError",
]