# -*- coding: utf-8 -*-
"""Win32 API utilities"""
import win32gui
import win32con
import win32api
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


def find_wechat_window() -> int | None:
    """
    Find WeChat main window handle.

    Returns:
        int | None: Window handle or None if not found
    """
    # Method 1: By title
    hwnd = win32gui.FindWindow(None, '微信')
    if hwnd:
        return hwnd

    # Method 2: By class name
    hwnd = win32gui.FindWindow('Qt51514QWindowIcon', None)
    if hwnd:
        return hwnd

    return None


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