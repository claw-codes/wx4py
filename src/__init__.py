# -*- coding: utf-8 -*-
"""
wx4py - Python 微信自动化工具

基于 UIAutomation 的微信自动化 Python 库，支持 Windows Qt 版本微信客户端。
"""

from ._version import __version__
from .ai import AIClient, AIConfig, AIResponder
from .client import WeChatClient
from .core.listener import MessageEvent, WeChatGroupListener
from .core.exceptions import (
    WeChatError,
    WeChatNotFoundError,
    WeChatNotConnectedError,
    ControlNotFoundError,
    TargetNotFoundError,
    RegistryError,
)

__author__ = "wx4py Team"

__all__ = [
    "WeChatClient",
    "AIClient",
    "AIConfig",
    "AIResponder",
    "MessageEvent",
    "WeChatGroupListener",
    "WeChatError",
    "WeChatNotFoundError",
    "WeChatNotConnectedError",
    "ControlNotFoundError",
    "TargetNotFoundError",
    "RegistryError",
]
