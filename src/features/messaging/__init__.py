# -*- coding: utf-8 -*-
"""消息监听、处理与转发。"""

from .forwarder import (
    ForwardPayload,
    ForwardRuleHandler,
    ForwardTarget,
    GroupForwardRule,
)
from .listener import (
    MemberRegistry,
    MessageEvent,
    WeChatGroupListener,
    parse_message_name,
)
from .processor import (
    AsyncCallbackHandler,
    CallbackHandler,
    ForwardAction,
    MessageAction,
    MessageHandler,
    ReplyAction,
    WeChatGroupProcessor,
)

__all__ = [
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
    "MemberRegistry",
    "parse_message_name",
]
