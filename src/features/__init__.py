# -*- coding: utf-8 -*-
"""微信业务能力。"""

from .base import BasePage
from .chat import ChatWindow, SearchResult
from .groups import GroupManager

__all__ = ["BasePage", "ChatWindow", "SearchResult", "GroupManager"]
