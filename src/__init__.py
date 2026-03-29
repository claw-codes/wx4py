# -*- coding: utf-8 -*-
"""
wx4py - Python 微信自动化工具

基于 UIAutomation 的微信自动化 Python 库，支持 Windows Qt 版本微信客户端。
"""

from .client import WeChatClient
from .core.exceptions import (
    WeChatError,
    WeChatNotFoundError,
    WeChatNotConnectedError,
    ControlNotFoundError,
    RegistryError,
)

__version__ = "0.1.2"
__author__ = "wx4py Team"

__all__ = [
    "WeChatClient",
    "WeChatError",
    "WeChatNotFoundError",
    "WeChatNotConnectedError",
    "ControlNotFoundError",
    "RegistryError",
]