# -*- coding: utf-8 -*-
"""Windows 原生托盘恢复工具。

背景：
    微信隐藏到托盘后，如果直接对主窗口执行 ShowWindow / SetForegroundWindow，
    部分机器会出现“窗口恢复了但内容是黑的”的问题。手动点击托盘图标则正常。

核心思路：
    Windows 托盘图标通常通过 Shell_NotifyIcon 注册到 Explorer。
    Explorer 的通知区域内部使用 ToolbarWindow32 保存托盘按钮，每个按钮的
    dwData 通常能解析出应用注册托盘图标时传入的：

    1. hWnd：接收托盘回调消息的应用窗口
    2. uID：托盘图标 ID
    3. callbackMessage：应用自定义的托盘回调消息

    拿到这三个值后，直接向 hWnd 投递 callbackMessage，并把鼠标事件放到
    lParam 中，就等价于“用户点击了真实托盘图标”。

适用场景：
    该方案不依赖任务栏 UIA 控件，也不依赖 MyDockFinder 等第三方 Dock 的
    界面结构。只要 Explorer 原生托盘数据仍存在，即使系统任务栏被隐藏，
    仍有机会恢复微信窗口。

风险边界：
    ToolbarWindow32 内部数据结构不是 Microsoft 公开 API。Windows 版本、
    进程位数或 Shell 实现变化都可能导致解析失败。因此本模块只能作为
    安全兜底：成功则恢复窗口，失败必须返回 False，不应影响主流程。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import struct
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import win32con
import win32gui
import win32process

from .logger import get_logger

logger = get_logger(__name__)

# 微信不同安装包/版本可能使用 Weixin.exe 或 WeChat.exe。
# 文本提示用于兜底匹配标题、类名等辅助信息。
WECHAT_EXE_NAMES = {"wechat.exe", "weixin.exe"}
WECHAT_TEXT_HINTS = ("WeChat", "Weixin", "微信")

WM_USER = 0x0400

# ToolbarWindow32 消息：
# - TB_BUTTONCOUNT 获取工具栏按钮数量
# - TB_GETBUTTON 把指定索引的 TBBUTTON 写入调用方提供的内存地址
# 这里读取的是 Explorer 进程内的 ToolbarWindow32，所以需要在 Explorer
# 进程中分配远程内存，再通过 ReadProcessMemory 读回来。
TB_GETBUTTON = WM_USER + 23
TB_BUTTONCOUNT = WM_USER + 24

# 读取 Explorer 进程内存所需权限。只读托盘按钮数据，不写应用文件。
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# VirtualAllocEx / VirtualFreeEx 参数。
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

REMOTE_BUFFER_SIZE = 4096

# 诊断结果显示微信通常在双击事件时恢复。这里仍按真实点击序列投递：
# 先 down/up，再投递 double click，兼容不同版本的托盘回调处理逻辑。
TRAY_RESTORE_EVENTS = (
    ("WM_LBUTTONDOWN", win32con.WM_LBUTTONDOWN),
    ("WM_LBUTTONUP", win32con.WM_LBUTTONUP),
    ("WM_LBUTTONDBLCLK", win32con.WM_LBUTTONDBLCLK),
)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_int
kernel32.VirtualAllocEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_uint32,
]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
]
kernel32.VirtualFreeEx.restype = ctypes.c_int
kernel32.ReadProcessMemory.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = ctypes.c_int
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_wchar_p,
    ctypes.POINTER(ctypes.c_uint32),
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
user32.SendMessageW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_size_t,
    ctypes.c_size_t,
]
user32.SendMessageW.restype = ctypes.c_size_t


@dataclass(frozen=True)
class _ToolbarInfo:
    """Explorer 中一个原生托盘工具栏窗口。"""

    hwnd: int
    pid: int


@dataclass(frozen=True)
class _TrayButton:
    """从 ToolbarWindow32 按钮数据中解析出的微信托盘项。"""

    toolbar_hwnd: int
    index: int
    id_command: int
    dw_data: int
    hwnd: int
    uid: int
    callback_msg: int
    exe_path: str
    title: str
    class_name: str

    @property
    def summary(self) -> str:
        return (
            f"toolbar=0x{self.toolbar_hwnd:08X} index={self.index} "
            f"idCommand=0x{self.id_command:X} dwData=0x{self.dw_data:X} "
            f"target_hwnd=0x{self.hwnd:08X} uid=0x{self.uid:X} "
            f"callback=0x{self.callback_msg:X} class={self.class_name!r} "
            f"title={self.title!r} exe={self.exe_path!r}"
        )


def _open_toolbar_process(pid: int) -> Optional[int]:
    """打开 Explorer 托盘工具栏所在进程，用于读取其内存。"""
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION
        | PROCESS_VM_OPERATION
        | PROCESS_VM_READ
        | PROCESS_VM_WRITE,
        0,
        pid,
    )
    return int(handle) if handle else None


def _close_handle(handle: int) -> None:
    """关闭 Win32 句柄，避免句柄泄漏。"""
    if handle:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _get_process_image_name(pid: int) -> str:
    """通过 pid 获取进程可执行文件路径，用于判断托盘项是否属于微信。"""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return ""

    try:
        size = ctypes.c_uint32(1024)
        buf = ctypes.create_unicode_buffer(1024)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        kernel32.CloseHandle(handle)


def _read_remote(handle: int, address: int, size: int) -> bytes:
    """读取目标进程指定地址处的内存。读取失败时返回空 bytes。"""
    if not address:
        return b""

    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(
        ctypes.c_void_p(handle),
        ctypes.c_void_p(address),
        buf,
        size,
        ctypes.byref(read),
    )
    if not ok:
        return b""
    return buf.raw[: read.value]


def _enum_child_windows(parent: int) -> List[int]:
    """枚举指定窗口的全部子窗口。"""
    result: List[int] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        result.append(hwnd)
        return True

    win32gui.EnumChildWindows(parent, callback, 0)
    return result


def _enum_native_tray_toolbars() -> List[_ToolbarInfo]:
    """查找 Explorer 原生通知区域中的 ToolbarWindow32。

    常见位置：
        - Shell_TrayWnd：主任务栏通知区域
        - NotifyIconOverflowWindow：隐藏图标弹出区

    MyDockFinder 隐藏系统任务栏时，Shell_TrayWnd 可能不可见，但窗口和按钮
    数据仍可能存在，因此这里不要求工具栏必须可见。
    """
    roots = []
    shell = win32gui.FindWindow("Shell_TrayWnd", None)
    overflow = win32gui.FindWindow("NotifyIconOverflowWindow", None)
    if shell:
        roots.append(shell)
    if overflow:
        roots.append(overflow)

    toolbars: List[_ToolbarInfo] = []
    seen = set()
    for root in roots:
        for child in _enum_child_windows(root):
            if child in seen:
                continue
            try:
                class_name = win32gui.GetClassName(child) or ""
            except Exception:
                continue
            if class_name != "ToolbarWindow32":
                continue
            _, pid = win32process.GetWindowThreadProcessId(child)
            seen.add(child)
            toolbars.append(_ToolbarInfo(hwnd=child, pid=pid))
    return toolbars


def _parse_tbbutton(data: bytes) -> Optional[Tuple[int, int]]:
    """解析 ToolbarWindow32 的 TBBUTTON，返回 (idCommand, dwData)。

    这里只取两个字段：
        - idCommand：工具栏按钮命令 ID，主要用于日志定位。
        - dwData：Explorer 保存的托盘项私有数据指针，后续会继续读取。

    TBBUTTON 在 32 位和 64 位进程中的字段偏移不同，所以需要按当前 Python
    进程位数分别解析。
    """
    if ctypes.sizeof(ctypes.c_void_p) == 8 and len(data) >= 32:
        id_command = struct.unpack_from("<i", data, 4)[0]
        dw_data = struct.unpack_from("<Q", data, 16)[0]
        return id_command, dw_data

    if len(data) >= 20:
        id_command = struct.unpack_from("<i", data, 4)[0]
        dw_data = struct.unpack_from("<I", data, 12)[0]
        return id_command, dw_data

    return None


def _parse_traydata_candidates(data: bytes) -> List[Tuple[int, int, int]]:
    """从 dwData 指向的数据中解析可能的 (hwnd, uid, callback_msg)。

    Explorer 内部托盘数据结构没有公开文档。已验证的常见布局是：
        - 64 位：HWND 在偏移 0，uID 在偏移 8，callbackMessage 在偏移 12
        - 32 位：HWND 在偏移 0，uID 在偏移 4，callbackMessage 在偏移 8

    为了兼容部分系统上的填充/前置指针，这里还额外尝试了 64 位偏移 8 的布局。
    返回多个候选，由后续逻辑用窗口句柄、进程路径、类名和标题过滤。
    """
    candidates: List[Tuple[int, int, int]] = []

    if ctypes.sizeof(ctypes.c_void_p) == 8 and len(data) >= 24:
        # 常见 64 位布局：HWND、UINT uID、UINT callbackMessage。
        candidates.append(
            (
                struct.unpack_from("<Q", data, 0)[0],
                struct.unpack_from("<I", data, 8)[0],
                struct.unpack_from("<I", data, 12)[0],
            )
        )

        # 部分系统版本可能在前面有额外指针或填充，保留偏移兜底。
        if len(data) >= 32:
            candidates.append(
                (
                    struct.unpack_from("<Q", data, 8)[0],
                    struct.unpack_from("<I", data, 16)[0],
                    struct.unpack_from("<I", data, 20)[0],
                )
            )

    if len(data) >= 12:
        candidates.append(
            (
                struct.unpack_from("<I", data, 0)[0],
                struct.unpack_from("<I", data, 4)[0],
                struct.unpack_from("<I", data, 8)[0],
            )
        )

    return candidates


def _is_likely_wechat_target(hwnd: int) -> Tuple[bool, str, str, str]:
    """判断托盘回调目标窗口是否属于微信。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False, "", "", ""

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_path = _get_process_image_name(pid)
        title = win32gui.GetWindowText(hwnd) or ""
        class_name = win32gui.GetClassName(hwnd) or ""
    except Exception:
        return False, "", "", ""

    exe_name = os.path.basename(exe_path).lower()
    text = f"{exe_name} {title} {class_name}"
    matched = exe_name in WECHAT_EXE_NAMES or any(hint in text for hint in WECHAT_TEXT_HINTS)
    return matched, exe_path, title, class_name


def _read_toolbar_buttons(toolbar: _ToolbarInfo) -> List[_TrayButton]:
    """读取一个 ToolbarWindow32 中的微信托盘按钮。

    关键步骤：
        1. 打开 Explorer 进程。
        2. 在 Explorer 进程中分配一段临时内存。
        3. 发送 TB_GETBUTTON，让 ToolbarWindow32 把 TBBUTTON 写入这段内存。
        4. 从 Explorer 进程读回 TBBUTTON，再继续读取 dwData 指向的数据。
        5. 从 dwData 中解析托盘回调目标，并过滤出微信。
    """
    handle = _open_toolbar_process(toolbar.pid)
    if not handle:
        logger.debug(f"无法打开托盘工具栏进程: pid={toolbar.pid}")
        return []

    remote = kernel32.VirtualAllocEx(
        ctypes.c_void_p(handle),
        None,
        REMOTE_BUFFER_SIZE,
        MEM_COMMIT | MEM_RESERVE,
        PAGE_READWRITE,
    )
    if not remote:
        _close_handle(handle)
        logger.debug(f"无法在托盘工具栏进程中分配内存: pid={toolbar.pid}")
        return []

    buttons: List[_TrayButton] = []
    seen = set()
    try:
        count = user32.SendMessageW(ctypes.c_void_p(toolbar.hwnd), TB_BUTTONCOUNT, 0, 0)
        logger.debug(f"读取原生托盘工具栏: hwnd=0x{toolbar.hwnd:08X}, buttons={count}")

        for index in range(int(count)):
            user32.SendMessageW(ctypes.c_void_p(toolbar.hwnd), TB_GETBUTTON, index, int(remote))
            parsed = _parse_tbbutton(_read_remote(handle, int(remote), 64))
            if not parsed:
                continue

            id_command, dw_data = parsed
            if not dw_data:
                continue

            raw_data = _read_remote(handle, dw_data, 128)
            for target_hwnd, uid, callback_msg in _parse_traydata_candidates(raw_data):
                if not callback_msg:
                    continue
                matched, exe_path, title, class_name = _is_likely_wechat_target(target_hwnd)
                if not matched:
                    continue

                key = (target_hwnd, uid, callback_msg)
                if key in seen:
                    continue
                seen.add(key)

                buttons.append(
                    _TrayButton(
                        toolbar_hwnd=toolbar.hwnd,
                        index=index,
                        id_command=id_command,
                        dw_data=dw_data,
                        hwnd=target_hwnd,
                        uid=uid,
                        callback_msg=callback_msg,
                        exe_path=exe_path,
                        title=title,
                        class_name=class_name,
                    )
                )
    finally:
        kernel32.VirtualFreeEx(ctypes.c_void_p(handle), ctypes.c_void_p(int(remote)), 0, MEM_RELEASE)
        _close_handle(handle)

    return buttons


def _find_wechat_native_tray_buttons() -> List[_TrayButton]:
    """从所有原生托盘工具栏中收集微信托盘候选项。"""
    buttons: List[_TrayButton] = []
    for toolbar in _enum_native_tray_toolbars():
        buttons.extend(_read_toolbar_buttons(toolbar))
    return buttons


def _is_wechat_main_window_visible() -> bool:
    """检查微信主界面是否已经恢复为可见状态。"""
    def callback(hwnd: int, result: List[bool]) -> bool:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = os.path.basename(_get_process_image_name(pid)).lower()
            class_name = win32gui.GetClassName(hwnd) or ""
        except Exception:
            return True

        if exe_name in WECHAT_EXE_NAMES and win32gui.IsWindowVisible(hwnd):
            if "TrayIconMessageWindow" not in class_name:
                result[0] = True
                return False
        return True

    result = [False]
    win32gui.EnumWindows(callback, result)
    return result[0]


def restore_wechat_from_native_tray(wait_after_event: float = 0.8) -> bool:
    """通过 Explorer 原生托盘数据恢复微信窗口。

    该函数只负责“模拟托盘点击”。它不做窗口强制显示或前台激活，避免再次
    触发黑窗口问题。调用方应在返回后继续轮询微信主窗口是否可见。

    Returns:
        bool: 检测到微信窗口恢复，或至少成功投递过微信托盘消息时返回 True。
    """
    try:
        buttons = _find_wechat_native_tray_buttons()
    except Exception as exc:
        logger.debug(f"读取原生托盘数据失败: {exc}")
        return False

    if not buttons:
        logger.debug("未从原生托盘数据中找到微信图标")
        return False

    logger.info("尝试通过原生托盘消息恢复微信窗口")
    any_posted = False
    for button in buttons:
        logger.debug(f"微信原生托盘候选: {button.summary}")
        for label, event in TRAY_RESTORE_EVENTS:
            try:
                win32gui.PostMessage(button.hwnd, button.callback_msg, button.uid, event)
                logger.debug(
                    f"已投递微信托盘消息: event={label}, "
                    f"hwnd=0x{button.hwnd:08X}, callback=0x{button.callback_msg:X}, uid=0x{button.uid:X}"
                )
                any_posted = True
                time.sleep(wait_after_event)
                if _is_wechat_main_window_visible():
                    return True
            except Exception as exc:
                logger.debug(f"投递微信托盘消息失败: {exc}")

    return any_posted
