# -*- coding: utf-8 -*-
"""
UIA 强制刷新工具

尝试使用 Windows UIA COM 接口强制刷新 UIA 缓存和提供程序。
"""

import ctypes
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# UIA COM 接口定义
try:
    import comtypes
    from comtypes.client import CreateObject, GetModule
    from comtypes.gen import UIAutomationClient as UIA
    
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
    logger.warning("comtypes 或 UIAutomationClient 不可用，将使用回退方法")


def refresh_uia_for_window(hwnd: int, max_retries: int = 3) -> bool:
    """
    尝试强制刷新指定窗口的 UIA。
    
    Args:
        hwnd: 窗口句柄
        max_retries: 最大重试次数
        
    Returns:
        bool: 是否成功刷新
    """
    if not UIA_AVAILABLE:
        return _refresh_uia_fallback(hwnd)
    
    try:
        # 获取 UIA 自动化对象
        automation = CreateObject("{FF48DBA4-60EF-4201-BB87-92DD1D9F2A9A}", 
                                   interface=UIA.CUIAutomation)
        
        for attempt in range(max_retries):
            logger.info(f"UIA 刷新尝试 {attempt + 1}/{max_retries}")
            
            try:
                # 尝试从窗口句柄获取元素
                element = automation.GetRootElement()
                
                # 尝试找到目标窗口元素
                # 使用 FindFirst 在根元素下查找
                condition = automation.CreatePropertyCondition(
                    UIA.UIA_NativeWindowHandlePropertyId, 
                    hwnd
                )
                
                target_element = element.FindFirst(UIA.TreeScope_Descendants, condition)
                
                if target_element:
                    logger.info("成功获取目标窗口的 UIA 元素")
                    
                    # 尝试刷新元素缓存
                    try:
                        # 获取元素的一些属性来强制刷新
                        target_element.CurrentName
                        target_element.CurrentClassName
                        target_element.CurrentControlType
                        
                        logger.info("UIA 元素属性读取成功，刷新可能有效")
                        return True
                    except Exception as e:
                        logger.warning(f"读取 UIA 元素属性失败: {e}")
                else:
                    logger.warning("未找到目标窗口的 UIA 元素")
                    
            except Exception as e:
                logger.warning(f"UIA 刷新尝试 {attempt + 1} 失败: {e}")
                
            if attempt < max_retries - 1:
                wait_time = 0.5 * (attempt + 1)
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                
        logger.error(f"所有 {max_retries} 次 UIA 刷新尝试均失败")
        return False
        
    except Exception as e:
        logger.error(f"UIA 刷新过程中发生严重错误: {e}")
        return _refresh_uia_fallback(hwnd)


def _refresh_uia_fallback(hwnd: int) -> bool:
    """
    UIA 刷新的回退方法，不使用 COM 接口。
    
    通过发送 Windows 消息来尝试触发 UIA 重建。
    
    Args:
        hwnd: 窗口句柄
        
    Returns:
        bool: 是否成功
    """
    import win32gui
    import win32con
    
    try:
        logger.info("使用回退方法尝试刷新 UIA...")
        
        # 确保窗口可见
        if not win32gui.IsWindowVisible(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            time.sleep(0.5)
        
        # 尝试发送 WM_GETOBJECT 消息
        # 这会触发 UIA 框架重新获取对象
        try:
            result = win32gui.SendMessage(hwnd, win32con.WM_GETOBJECT, 0, 0)
            logger.info(f"WM_GETOBJECT 返回: {result}")
        except Exception as e:
            logger.warning(f"WM_GETOBJECT 失败: {e}")
        
        # 尝试让窗口获得焦点
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"SetForegroundWindow 失败: {e}")
        
        logger.info("回退方法执行完成，但无法保证 UIA 已刷新")
        return False  # 回退方法无法确定是否成功
        
    except Exception as e:
        logger.error(f"回退方法执行失败: {e}")
        return False


# 导出主要函数
__all__ = ['refresh_uia_for_window', 'UIA_AVAILABLE']
