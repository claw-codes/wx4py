# -*- coding: utf-8 -*-
"""Win32 API 工具"""
import ctypes
import ctypes.wintypes
import time
import os
import subprocess

import win32gui
import win32con
import win32process
import winreg
from typing import List, Literal, Optional, Tuple

from ..core.exceptions import RegistryError


def ensure_screen_reader_flag() -> bool:
    """
    确保系统级屏幕阅读器标志（SPI_SETSCREENREADER）为开启状态。

    该标志用于告诉当前 Windows 会话“存在屏幕阅读器正在运行”。
    某些 Qt 应用（包括微信 4.x）会在启动时读取这个标志，
    决定是否暴露更完整的辅助功能 / UIAutomation 控件树。

    注意：
        该函数只修正当前系统会话中的辅助功能环境，
        不作为“是否必须重启微信”的判断依据。

    Returns:
        bool: 标志原本为关闭并已开启时返回 True，否则返回 False。
    """
    SPI_GETSCREENREADER = 0x0046
    SPI_SETSCREENREADER = 0x0047
    SPIF_UPDATEINIFILE = 0x01
    SPIF_SENDCHANGE = 0x02

    pvParam = ctypes.wintypes.BOOL()
    ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETSCREENREADER, 0, ctypes.byref(pvParam), 0
    )

    if pvParam.value:
        return False

    ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETSCREENREADER, 1, 0, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )
    return True


def check_and_fix_registry() -> Literal["unchanged", "fixed_zero", "created_missing"]:
    """
    检查并修复 UI Automation 的注册表设置。

    检查 HKCU\\SOFTWARE\\Microsoft\\Narrator\\NoRoam 中的 RunningState，
    如果值为 0 则设置为 1。

    Returns:
        Literal["unchanged", "fixed_zero", "created_missing"]:
            "unchanged": RunningState 已存在且无需修改
            "fixed_zero": RunningState 原值为 0，已修复为 1
            "created_missing": RunningState 缺失，已创建为 1
    """
    reg_path = r"SOFTWARE\Microsoft\Narrator\NoRoam"
    key_name = "RunningState"

    try:
        # 打开注册表键
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            reg_path,
            0,
            winreg.KEY_READ | winreg.KEY_WRITE
        )

        try:
            # 读取当前值
            value, _ = winreg.QueryValueEx(key, key_name)

            if value == 0:
                # 设置为 1
                winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
                return "fixed_zero"

            winreg.CloseKey(key)
            return "unchanged"

        except FileNotFoundError:
            # 键不存在，创建并设置为 1
            winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
            return "created_missing"

    except PermissionError as e:
        raise RegistryError(f"访问注册表时权限被拒绝: {e}")
    except Exception as e:
        raise RegistryError(f"访问注册表失败: {e}")


def _get_process_image_name(pid: int) -> str:
    """尽力通过 pid 解析可执行文件完整路径。"""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    query_name = kernel32.QueryFullProcessImageNameW
    query_name.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    query_name.restype = ctypes.c_int

    handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return ""

    try:
        size = ctypes.c_uint32(1024)
        buf = ctypes.create_unicode_buffer(1024)
        ok = query_name(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        close_handle(handle)


def _wechat_window_score(hwnd: int, title: str, class_name: str, exe_path: str) -> int:
    """为候选的顶层窗口评分；分数越高越可能是微信主窗口。"""
    score = 0
    exe_name = os.path.basename(exe_path).lower()

    if exe_name in {"weixin.exe", "wechat.exe"}:
        score += 100
    if exe_name == "wechatappex.exe":
        score -= 200

    if class_name.startswith("Qt"):
        score += 30
    if "微信" in title:
        score += 10

    if not win32gui.IsWindowVisible(hwnd):
        score -= 20

    return score


def find_wechat_window() -> Optional[int]:
    """
    查找微信主窗口句柄。

    当 WeChatAppEx（白屏辅助窗口）和主窗口同时存在时，
    避免选择错误的窗口。

    Returns:
        Optional[int]: 窗口句柄，未找到时返回 None
    """
    candidates: List[Tuple[int, int, str, str, str]] = []

    def _enum_cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd) or ""
        class_name = win32gui.GetClassName(hwnd) or ""

        # 快速预筛选以减少进程查询
        if ("微信" not in title) and (not class_name.startswith("Qt")) and ("WeChat" not in class_name):
            return True

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_path = _get_process_image_name(pid)
        except Exception:
            pid = 0
            exe_path = ""

        score = _wechat_window_score(hwnd, title, class_name, exe_path)
        if score > -150:
            candidates.append((score, hwnd, title, class_name, exe_path))
        return True

    win32gui.EnumWindows(_enum_cb, None)

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # 历史兼容回退
    hwnd = win32gui.FindWindow('Qt51514QWindowIcon', None)
    if hwnd:
        return hwnd

    hwnd = win32gui.FindWindow(None, '微信')
    if hwnd:
        return hwnd

    return None


def restart_wechat_process(hwnd: int) -> bool:
    """
    重启指定窗口句柄对应的微信进程。

    Args:
        hwnd: 微信窗口句柄

    Returns:
        bool: 重启命令执行成功返回 True
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_path = _get_process_image_name(pid)
        if not exe_path or not os.path.exists(exe_path):
            return False

        # 结束当前进程树
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        time.sleep(1.0)

        # 重新启动微信可执行文件
        subprocess.Popen([exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        return True
    except Exception:
        return False


def bring_window_to_front(hwnd: int) -> bool:
    """
    将窗口置于前台。

    处理三种情况：
    1. 窗口已最小化 → SW_RESTORE 恢复
    2. 窗口隐藏到托盘（SW_HIDE 状态） → 先 SW_SHOW 再 SW_RESTORE
    3. 窗口正常显示 → 直接 SetForegroundWindow

    Args:
        hwnd: 窗口句柄

    Returns:
        bool: 成功时返回 True
    """
    try:
        # 如果窗口不可见（隐藏到托盘），先 SW_SHOW 使其可见
        if not win32gui.IsWindowVisible(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            time.sleep(0.15)
        # 恢复窗口（处理最小化状态）
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # 置于前台
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def get_window_title(hwnd: int) -> str:
    """通过句柄获取窗口标题"""
    return win32gui.GetWindowText(hwnd)


def get_window_class(hwnd: int) -> str:
    """通过句柄获取窗口类名"""
    return win32gui.GetClassName(hwnd)


def is_window_visible(hwnd: int) -> bool:
    """检查窗口是否可见"""
    return win32gui.IsWindowVisible(hwnd) != 0


def _purge_ghost_tray_icons():
    """
    清理系统通知区域中的幽灵图标。

    微信多次启动/关闭后，通知区域可能残留失效的"幽灵图标"（ghost icons）。
    正常情况下，当用户鼠标扫过通知区域时 Windows Explorer 会自动清理这些图标，
    但如果用户使用 myDockFinder 等工具隐藏了 Windows 任务栏，鼠标永远不会
    扫过通知区域，幽灵图标就会不断累积。

    此方法通过向通知区域的 ToolbarWindow32 控件发送 WM_MOUSEMOVE 消息来
    模拟鼠标扫过，触发 Windows Explorer 的幽灵图标清理机制。
    """
    WM_MOUSEMOVE = 0x0200
    WM_MOUSELEAVE = 0x02A3

    def _sweep_toolbar(toolbar_hwnd):
        if not toolbar_hwnd:
            return
        try:
            rect = win32gui.GetClientRect(toolbar_hwnd)
            w = rect[2]
            h = rect[3]
            if w <= 0 or h <= 0:
                return
            y = h // 2
            # 每 8 像素发送一次 WM_MOUSEMOVE，模拟鼠标从左到右扫过
            for x in range(0, w + 1, 8):
                lParam = (y << 16) | (x & 0xFFFF)
                try:
                    win32gui.SendMessage(toolbar_hwnd, WM_MOUSEMOVE, 0, lParam)
                except Exception:
                    pass
            # 发送 WM_MOUSELEAVE 完成清理
            try:
                win32gui.SendMessage(toolbar_hwnd, WM_MOUSELEAVE, 0, 0)
            except Exception:
                pass
        except Exception:
            pass

    # 清理主通知区域
    shell_tray = win32gui.FindWindow('Shell_TrayWnd', None)
    if shell_tray:
        tray_notify = win32gui.FindWindowEx(shell_tray, 0, 'TrayNotifyWnd', None)
        if tray_notify:
            sys_pager = win32gui.FindWindowEx(tray_notify, 0, 'SysPager', None)
            if sys_pager:
                toolbar = win32gui.FindWindowEx(
                    sys_pager, 0, 'ToolbarWindow32', None
                )
                _sweep_toolbar(toolbar)

    # 清理溢出区域
    overflow = win32gui.FindWindow('NotifyIconOverflowWindow', None)
    if overflow:
        toolbar = win32gui.FindWindowEx(
            overflow, 0, 'ToolbarWindow32', None
        )
        _sweep_toolbar(toolbar)

    # 给 Explorer 一点时间完成清理
    time.sleep(0.3)


def activate_wechat_via_tray_icon() -> bool:
    """
    通过系统通知区域的微信托盘图标唤醒微信窗口。

    当微信窗口被关闭（隐藏到系统托盘）时，单纯的 ShowWindow 无法
    恢复 Qt 辅助功能树。此方法通过 UIA 查找通知区域中的微信图标
    并调用 Invoke 操作，等效于用户手动点击托盘图标，从而触发微信
    内部的窗口显示逻辑，使 UIA 控件树正确恢复。

    此方法不依赖键盘快捷键，也不依赖任务栏的可见性（兼容
    myDockFinder 等隐藏任务栏的工具），因为底层 Shell_TrayWnd
    窗口始终存在。

    在查找微信图标之前，会先清理通知区域的幽灵图标（ghost icons），
    避免 invoke 到失效的残留图标上。

    Returns:
        bool: 成功触发托盘图标点击返回 True
    """
    # 延迟导入，避免循环依赖（uiautomation 模块较重）
    from ..core import uiautomation as uia

    # 先清理幽灵图标，确保后续查找到的是真实有效的微信图标
    _purge_ghost_tray_icons()

    def _find_wechat_icon(ctrl, depth=0):
        """递归查找名称包含'微信'的按钮控件"""
        if depth > 8:
            return None
        try:
            name = ctrl.Name or ''
            if '微信' in name and ctrl.ControlTypeName == 'ButtonControl':
                return ctrl
        except Exception:
            pass
        try:
            for ch in ctrl.GetChildren():
                result = _find_wechat_icon(ch, depth + 1)
                if result:
                    return result
        except Exception:
            pass
        return None

    def _invoke_icon(icon):
        """尝试多种方式触发托盘图标"""
        # 方式1：InvokePattern
        try:
            pat = icon.GetInvokePattern()
            if pat:
                pat.Invoke()
                return True
        except Exception:
            pass
        # 方式2：Click
        try:
            icon.Click()
            return True
        except Exception:
            pass
        return False

    # 在主通知区域精确查找（限定在 TrayNotifyWnd 下，避免匹配任务栏按钮）
    shell_tray = win32gui.FindWindow('Shell_TrayWnd', None)
    if shell_tray:
        tray_notify = win32gui.FindWindowEx(
            shell_tray, 0, 'TrayNotifyWnd', None
        )
        if tray_notify:
            tray_root = uia.ControlFromHandle(tray_notify)
            icon = _find_wechat_icon(tray_root)
            if icon and _invoke_icon(icon):
                return True

    # 在溢出区域查找
    overflow = win32gui.FindWindow('NotifyIconOverflowWindow', None)
    if overflow:
        of_root = uia.ControlFromHandle(overflow)
        icon = _find_wechat_icon(of_root)
        if icon and _invoke_icon(icon):
            return True

    return False


def minimize_window(hwnd: int) -> bool:
    """
    最小化指定窗口。

    Args:
        hwnd: 窗口句柄

    Returns:
        bool: 成功时返回 True
    """
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return True
    except Exception:
        return False
