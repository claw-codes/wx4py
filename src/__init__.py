# -*- coding: utf-8 -*-
"""
wx4py - Python 微信自动化工具

基于 UIAutomation 的微信自动化 Python 库，支持 Windows Qt 版本微信客户端。
"""

from ._version import __version__
from .ai import AIClient, AIConfig, AIResponder
from .client import WeChatClient
from .features.messaging.forwarder import (
    ForwardPayload,
    ForwardRuleHandler,
    ForwardTarget,
    GroupForwardRule,
)
from .features.messaging.listener import MessageEvent, WeChatGroupListener
from .features.messaging.processor import (
    AsyncCallbackHandler,
    CallbackHandler,
    ForwardAction,
    MessageAction,
    MessageHandler,
    ReplyAction,
    WeChatGroupProcessor,
)
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
    "MessageAction",
    "ReplyAction",
    "ForwardAction",
    "MessageHandler",
    "CallbackHandler",
    "AsyncCallbackHandler",
    "WeChatGroupProcessor",
    "ForwardTarget",
    "ForwardPayload",
    "GroupForwardRule",
    "ForwardRuleHandler",
    "WeChatError",
    "WeChatNotFoundError",
    "WeChatNotConnectedError",
    "ControlNotFoundError",
    "TargetNotFoundError",
    "RegistryError",
]
