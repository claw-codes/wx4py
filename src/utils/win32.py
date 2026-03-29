# -*- coding: utf-8 -*-
"""Win32 API utilities"""
import time
import os
import subprocess

import win32gui
import win32con
import win32process
import winreg

from ..core.exceptions import RegistryError


def check_and_fix_registry() -> bool:
    """
    Check and fix registry for UI Automation.

    Checks RunningState in HKCU\\SOFTWARE\\Microsoft\\Narrator\\NoRoam
    If value is 0, sets it to 1.

    Returns:
        bool: True if registry was modified, False if no change needed
    """
    reg_path = r"SOFTWARE\Microsoft\Narrator\NoRoam"
    key_name = "RunningState"

    try:
        # Open registry key
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            reg_path,
            0,
            winreg.KEY_READ | winreg.KEY_WRITE
        )

        try:
            # Try to read existing value
            value, _ = winreg.QueryValueEx(key, key_name)

            if value == 0:
                # Set to 1
                winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
                return True

            winreg.CloseKey(key)
            return False

        except FileNotFoundError:
            # Key doesn't exist, create it with value 1
            winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
            return True

    except PermissionError as e:
        raise RegistryError(f"Permission denied accessing registry: {e}")
    except Exception as e:
        raise RegistryError(f"Failed to access registry: {e}")


def _get_process_image_name(pid: int) -> str:
    """Best-effort resolve executable full path by pid."""
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
    """Score a candidate top-level window; higher means more likely main WeChat."""
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


def find_wechat_window() -> int | None:
    """
    Find WeChat main window handle.

    Avoid selecting WeChatAppEx (white screen helper window) when both
    helper and main Weixin window are present.

    Returns:
        int | None: Window handle or None if not found
    """
    candidates: list[tuple[int, int, str, str, str]] = []

    def _enum_cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd) or ""
        class_name = win32gui.GetClassName(hwnd) or ""

        # Quick prefilter to reduce process lookups
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

    # Legacy fallback
    hwnd = win32gui.FindWindow('Qt51514QWindowIcon', None)
    if hwnd:
        return hwnd

    hwnd = win32gui.FindWindow(None, '微信')
    if hwnd:
        return hwnd

    return None


def restart_wechat_process(hwnd: int) -> bool:
    """
    Restart WeChat process for a specific window handle.

    Args:
        hwnd: WeChat window handle

    Returns:
        bool: True if restart command succeeded
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_path = _get_process_image_name(pid)
        if not exe_path or not os.path.exists(exe_path):
            return False

        # Terminate current process tree
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        time.sleep(1.0)

        # Relaunch WeChat executable
        subprocess.Popen([exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        return True
    except Exception:
        return False


def bring_window_to_front(hwnd: int) -> bool:
    """
    Bring window to front and restore if minimized.

    Args:
        hwnd: Window handle

    Returns:
        bool: True if successful
    """
    try:
        # Show window
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # Bring to front
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def get_window_title(hwnd: int) -> str:
    """Get window title by handle"""
    return win32gui.GetWindowText(hwnd)


def get_window_class(hwnd: int) -> str:
    """Get window class name by handle"""
    return win32gui.GetClassName(hwnd)


def is_window_visible(hwnd: int) -> bool:
    """Check if window is visible"""
    return win32gui.IsWindowVisible(hwnd) != 0
