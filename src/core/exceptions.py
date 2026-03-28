# -*- coding: utf-8 -*-
"""Custom exceptions for wx4py"""


class WeChatError(Exception):
    """Base exception for wx4py"""
    pass


class WeChatNotFoundError(WeChatError):
    """WeChat window not found"""
    pass


class WeChatNotConnectedError(WeChatError):
    """WeChat not connected or initialized"""
    pass


class UIAError(WeChatError):
    """UIAutomation related error"""
    pass


class ControlNotFoundError(UIAError):
    """UI control not found"""
    pass


class RegistryError(WeChatError):
    """Registry operation error"""
    pass