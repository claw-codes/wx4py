# -*- coding: utf-8 -*-
"""微信群聊监听与自动回复。

该模块实现的是已经在诊断脚本中验证过的方案：
1. 每个群聊打开一个独立聊天窗口。
2. 每个窗口固定缓存 ``chat_message_list``。
3. 使用单调度器按时间片分片轮询多个窗口。
4. 自动回复时记录本库发送的消息，监听回流时只忽略一次。

注意：
    微信 4.x 的 Qt UIA 对消息方向/发送者暴露不足，无法稳定识别用户手动
    发送的“自己消息”。因此这里默认只忽略“本库发送并记录过”的消息。
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple

import win32api
import win32con
import win32gui
import win32process

from ...core import uiautomation as uia
from ..chat import ChatWindow
from ...utils.logger import get_logger

logger = get_logger(__name__)

# 截图临时目录
_SCREENSHOT_DIR = os.path.join(os.environ.get('TEMP', os.environ.get('TMP', '.')), 'wx4py_screenshots')
_MAX_SCREENSHOTS = 100  # 最大保留截图数量


def _cleanup_screenshots():
    """清理旧的截图文件，保留最新的 _MAX_SCREENSHOTS 个"""
    try:
        if not os.path.exists(_SCREENSHOT_DIR):
            return
        
        # 获取所有截图文件及其修改时间
        files = []
        for f in os.listdir(_SCREENSHOT_DIR):
            if f.endswith('.png'):
                path = os.path.join(_SCREENSHOT_DIR, f)
                try:
                    mtime = os.path.getmtime(path)
                    files.append((mtime, path))
                except Exception:
                    pass
        
        # 如果文件数量超过限制，删除最旧的
        if len(files) > _MAX_SCREENSHOTS:
            files.sort()  # 按修改时间排序（最旧的在前）
            to_delete = files[:-_MAX_SCREENSHOTS]
            for _, path in to_delete:
                try:
                    os.remove(path)
                except Exception:
                    pass
            logger.debug(f"清理了 {len(to_delete)} 个旧截图文件")
    except Exception as e:
        logger.debug(f"清理截图失败: {e}")


def _delete_screenshot(path: str):
    """删除截图文件"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _get_screenshot_path() -> str:
    """获取截图保存路径"""
    if not os.path.exists(_SCREENSHOT_DIR):
        try:
            os.makedirs(_SCREENSHOT_DIR)
        except Exception:
            pass
    
    # 清理旧截图
    _cleanup_screenshots()
    
    import uuid
    return os.path.join(_SCREENSHOT_DIR, f'{uuid.uuid4().hex[:8]}.png')


def _capture_window_region(hwnd: int, left: int, top: int, right: int, bottom: int) -> Optional[str]:
    """
    截取窗口指定区域

    Args:
        hwnd: 窗口句柄
        left, top, right, bottom: 截取区域坐标（屏幕坐标）

    Returns:
        截图保存的临时文件路径，失败返回None
    """
    try:
        from PIL import Image, ImageGrab

        # 检查窗口状态
        import win32gui
        try:
            # 获取窗口区域
            win_rect = win32gui.GetWindowRect(hwnd)
            # 如果是最小化窗口（坐标为负），需要特殊处理
            if win_rect[0] < 0 or win_rect[1] < 0:
                logger.info(f"窗口最小化，使用PrintWindow截取整个窗口")
                # 截取整个窗口，返回 (路径, 宽度, 高度)
                return _capture_window_full(hwnd)
        except Exception as e:
            logger.debug(f"获取窗口信息失败: {e}")

        # 方法1：使用PIL的ImageGrab（简单但可能被遮挡）
        try:
            screenshot = ImageGrab.grab(bbox=(left, top, right, bottom), include_layered_windows=False, all_screens=False)
            temp_path = _get_screenshot_path()
            screenshot.save(temp_path, 'PNG')
            return temp_path
        except Exception:
            pass

        # 方法2：使用Win32 API直接绘制窗口（不被遮挡）
        return _capture_window_dc(hwnd, left, top, right, bottom)

    except Exception as e:
        logger.debug(f"截图失败: {e}")
        return None


def _capture_window_full(hwnd: int) -> Optional[Tuple[str, int, int]]:
    """
    使用PrintWindow API截取整个窗口内容（完全静默，不改变窗口状态）

    即使窗口最小化，也能通过PrintWindow获取窗口内容的位图。
    不会恢复或最小化窗口，完全静默操作。

    Args:
        hwnd: 窗口句柄

    Returns:
        Tuple[截图路径, 窗口宽度, 窗口高度]，失败返回None
    """
    import ctypes

    try:
        import win32gui
        import win32ui
        import win32con
        from PIL import Image

        user32 = ctypes.windll.user32

        # 检查窗口状态
        win_rect = win32gui.GetWindowRect(hwnd)

        # 获取窗口客户区大小
        # 对于最小化的窗口，GetClientRect 返回的是图标化后的大小
        # 需要使用 GetWindowRect 来获取实际窗口大小
        win_rect = win32gui.GetWindowRect(hwnd)
        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)

        # 转换为屏幕坐标
        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (client_left, client_top))
        screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (client_right, client_bottom))

        width = screen_right - screen_left
        height = screen_bottom - screen_top

        # 检查窗口是否最小化（坐标为负）
        is_minimized = win_rect[0] < 0 or win_rect[1] < 0

        # 对于最小化的窗口，使用窗口的实际大小
        # GetWindowRect 返回的宽度/高度是正确的
        if is_minimized or width < 0 or height < 0:
            # 使用窗口矩形计算大小
            width = win_rect[2] - win_rect[0]
            height = win_rect[3] - win_rect[1]
            # 取绝对值
            width = abs(width)
            height = abs(height)
            # 对于最小化的 Qt 窗口，通常是 598x640 左右
            if width < 100 or height < 100:
                width = 598
                height = 640

        # 如果窗口是最小化的，将其移到屏幕边缘可见位置（不触发激活）
        # 这样 PrintWindow 可以正确截取窗口内容
        moved_to_edge = False
        saved_rect = None
        if is_minimized:
            logger.info(f"检测到窗口最小化，尝试恢复窗口进行截图")
            try:
                # 获取当前窗口位置（即使是最小化也能获取）
                win_rect = win32gui.GetWindowRect(hwnd)
                saved_rect = win_rect
                logger.info(f"最小化窗口原始位置: {win_rect}")

                # 获取屏幕大小
                screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
                screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
                logger.info(f"屏幕大小: {screen_w}x{screen_h}")

                # 先恢复窗口到正常状态
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                logger.info("窗口已恢复")
                time.sleep(0.2)

                # 将窗口移到屏幕右下角（不遮挡主屏幕）
                new_x = max(0, screen_w - width)
                new_y = max(0, screen_h - height)
                logger.info(f"移动窗口到: ({new_x}, {new_y})")

                win32gui.SetWindowPos(hwnd, 0, new_x, new_y, width, height, 0)
                moved_to_edge = True
                logger.info(f"窗口已移动到屏幕边缘，位置: ({new_x}, {new_y})")

                # 等待窗口渲染
                time.sleep(0.2)

                # 验证窗口位置
                new_rect = win32gui.GetWindowRect(hwnd)
                logger.info(f"窗口当前位置: {new_rect}")

            except Exception as e:
                logger.info(f"移动窗口失败: {e}")
                import traceback
                traceback.print_exc()

        if width <= 0 or height <= 0:
            logger.debug(f"窗口大小无效: {width}x{height}")
            return None

        # 创建设备上下文
        hwndDC = win32gui.GetDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()

        # 创建位图
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        # 绘制窗口内容（使用ctypes调用PrintWindow）
        # PrintWindow 可以在窗口最小化时捕获内容
        user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

        # 转换为Pil图像
        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = Image.frombytes('RGBA', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRA')

        # 保存到文件
        temp_path = _get_screenshot_path()
        img.save(temp_path, 'PNG')

        logger.info(f"截图成功，尺寸: {width}x{height}")

        # 清理
        try:
            win32gui.ReleaseDC(hwnd, hwndDC)
        except Exception:
            pass
        try:
            saveDC.DeleteDC()
        except Exception:
            pass
        try:
            mfcDC.DeleteDC()
        except Exception:
            pass

        # 如果之前移动了窗口，将窗口移回原位
        # 注意：不要在此处最小化窗口，因为调用方可能需要使用UIA获取控件坐标
        # 调用方应在OCR完成后自行决定是否最小化窗口
        if moved_to_edge and saved_rect:
            try:
                # 不恢复最小化，保持窗口可见以便UIA获取正确坐标
                # win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                logger.debug("窗口保持可见（不恢复最小化，以便UIA获取正确坐标）")
            except Exception as e:
                logger.info(f"恢复窗口最小化失败: {e}")

        return (temp_path, width, height)

    except Exception as e:
        logger.debug(f"PrintWindow截图失败: {e}")
        import traceback
        traceback.print_exc()

        # 注意：不在异常处理中最小化窗口
        # if moved_to_edge:
        #     try:
        #         win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        #     except Exception:
        #         pass

        return None


def _capture_window_dc(hwnd: int, left: int, top: int, right: int, bottom: int) -> Optional[str]:
    """
    使用Win32 API直接绘制窗口内容到图片（不被遮挡）

    Args:
        hwnd: 窗口句柄
        left, top, right, bottom: 截取区域坐标

    Returns:
        截图保存的临时文件路径
    """
    import ctypes
    from ctypes import wintypes

    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # 获取窗口设备上下文
        hwndDC = user32.GetDC(hwnd)
        if not hwndDC:
            return None

        try:
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return None

            # 创建内存设备上下文
            mfcDC = gdi32.CreateCompatibleDC(hwndDC)
            if not mfcDC:
                return None

            try:
                # 创建位图
                hBitmap = gdi32.CreateCompatibleBitmap(hwndDC, width, height)
                if not hBitmap:
                    return None

                try:
                    # 选择位图到内存DC
                    gdi32.SelectObject(mfcDC, hBitmap)

                    # 绘制窗口内容到内存DC
                    result = user32.PrintWindow(hwnd, mfcDC, 2)  # 2 = PW_CLIENTONLY | PW_RENDERFULLCONTENT

                    if result:
                        # 移动绘制内容到正确位置
                        gdi32.BitBlt(mfcDC, 0, 0, width, height, hwndDC, left, top, 0x00CC0020)  # SRCCOPY

                        # 转换为PIL Image
                        from PIL import Image
                        bmpinfo = ctypes.create_string_buffer(40)
                        bmi = ctypes.Structure.from_buffer(bmpinfo)
                        bmi.bmiHeader.biSize = ctypes.sizeof(bmi.bmiHeader)
                        bmi.bmiHeader.biWidth = width
                        bmi.bmiHeader.biHeight = -height  # 负值表示从上到下
                        bmi.bmiHeader.biPlanes = 1
                        bmi.bmiHeader.biBitCount = 32
                        bmi.bmiHeader.biCompression = 0  # BI_RGB

                        # 获取位图数据
                        bits = ctypes.create_string_buffer(width * height * 4)
                        gdi32.GetDIBits(mfcDC, hBitmap, 0, height, bits, ctypes.byref(bmi), 0)

                        # 创建PIL Image
                        img = Image.frombytes('RGBA', (width, height), bits, 'raw', 'BGRA')

                        # 保存到文件
                        temp_path = _get_screenshot_path()
                        img.save(temp_path, 'PNG')
                        return temp_path
                finally:
                    gdi32.DeleteObject(hBitmap)
            finally:
                gdi32.DeleteDC(mfcDC)
        finally:
            user32.ReleaseDC(hwnd, hwndDC)

    except Exception as e:
        logger.debug(f"Win32截图失败: {e}")
        return None


def _get_main_window_hwnd() -> Optional[int]:
    """获取微信主窗口句柄"""
    try:
        for hwnd, title, class_name in _find_wechat_windows():
            if "微信" in title or "WeChat" in title:
                return hwnd
    except Exception:
        pass
    return None


def _ocr_recognize_sender(image_path: str) -> Optional[str]:
    """
    使用PaddleOCR识别发送者昵称

    Args:
        image_path: 截图路径

    Returns:
        发送者昵称，失败返回None
    """
    try:
        from ...utils.ocr_utils import recognize_sender
        return recognize_sender(image_path)
    except ImportError as e:
        logger.debug(f"PaddleOCR未安装: {e}")
        return None
    except Exception as e:
        logger.debug(f"OCR识别失败: {e}")
        return None


def _right_click_at_position(x: int, y: int):
    """在屏幕坐标处右键单击。"""
    win32api.SetCursorPos((x, y))
    time.sleep(0.2)
    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.1)
    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def _close_popup():
    """关闭弹出的菜单或其他弹窗（按 ESC）。"""
    try:
        win32api.keybd_event(win32con.VK_ESCAPE, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.3)
    except Exception as e:
        logger.debug(f"关闭弹窗失败: {e}")

WECHAT_EXE_NAMES = {"wechat.exe", "weixin.exe"}
MESSAGE_CLASSES = {
    "mmui::ChatTextItemView",
    "mmui::ChatBubbleItemView",
}
TIME_CLASS = "mmui::ChatItemView"


def parse_message_name(raw_name: str) -> Tuple[Optional[str], str]:
    """解析消息项的 Name 属性，提取发送者昵称和消息内容。

    微信消息气泡的 Name 属性格式为：
    - `[消息内容]`（普通消息，没有发送者信息）
    - `[@被@的人] 消息内容`（当消息 @ 某人时，Name 只包含被 @ 的人，不是发送者！）

    重要：由于微信 UI 限制，无法直接从 Name 属性获取发送者昵称。
    当消息包含 @ 时，Name 格式为 "@被@的人 消息内容"，这里的 "被@的人" 不是发送者！

    Args:
        raw_name: 消息项的原始 Name 属性值

    Returns:
        Tuple[发送者昵称或None, 消息内容]
        注意：由于 UI 限制，发送者昵称在大多数情况下返回 None
    """
    if not raw_name:
        return None, ""

    raw_name = raw_name.strip()
    if not raw_name:
        return None, ""

    # 保留原始消息内容（包含 @ 信息），以便 _is_at_me 能正确判断是否被 @
    # 上游原始版本直接用 item.name 作为内容，这里保持一致
    return None, raw_name


@dataclass(frozen=True)
class MessageEvent:
    """监听到的新消息。"""

    group: str
    content: str
    timestamp: float
    sender_name: Optional[str] = None
    """消息发送者的显示昵称（从消息气泡的 Name 属性中提取）。"""

    sender_wxid: Optional[str] = None
    """消息发送者的微信ID（如果已通过 MemberRegistry 关联）。"""

    group_nickname: Optional[str] = None
    """机器人在本群中的昵称（用于判断是否被 @）。"""

    is_at_me: bool = False
    """是否 @ 了机器人。"""

    raw: object = None
    """原始 UI 控件对象，包含完整的消息项信息。"""


@dataclass(frozen=True)
class _VisibleItem:
    kind: str
    name: str
    class_name: str
    runtime_id: Tuple[int, ...]
    sender_name: Optional[str] = None
    """消息发送者昵称（仅当 kind="message" 时有值）。"""
    control: object = None

    @property
    def key(self) -> Tuple[Tuple[int, ...], str, str]:
        return self.runtime_id, self.class_name, self.name


@dataclass
class _ListenSession:
    group: str
    hwnd: int
    root: object
    msg_list: object
    seen: Set[Tuple[Tuple[int, ...], str, str]]
    new_count: int = 0
    scan_count: int = 0
    fail_count: int = 0
    last_message_at: float = field(default_factory=time.time)
    next_scan_at: float = field(default_factory=time.time)
    interval: float = 0.3


@dataclass
class _OutgoingRecord:
    group: str
    content: str
    expires_at: float
    remaining_hits: int


@dataclass(frozen=True)
class _ReplyTask:
    group: str
    content: str


class OutgoingMessageRegistry:
    """记录本库发送的消息，用于监听回流时忽略一次。"""

    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl_seconds = ttl_seconds
        self._records: Deque[_OutgoingRecord] = deque()

    def record(self, group: str, content: str, max_hits: int = 8) -> None:
        content = _normalize_message_text(content)
        if not content:
            return
        record = _OutgoingRecord(
            group=group,
            content=content,
            expires_at=time.time() + self.ttl_seconds,
            remaining_hits=max_hits,
        )
        self._records.append(record)

    def should_ignore(self, group: str, content: str) -> bool:
        now = time.time()
        content = _normalize_message_text(content)
        while self._records and self._records[0].expires_at < now:
            self._records.popleft()

        for index, record in enumerate(self._records):
            if record.group != group:
                continue
            if _is_same_outgoing_message(record.content, content):
                record.remaining_hits -= 1
                if record.remaining_hits <= 0:
                    del self._records[index]
                return True
        return False


class MemberRegistry:
    """群成员注册表，用于关联昵称和微信ID。

    由于微信 UI 自动化无法直接获取消息发送者的微信ID，
    本类提供手动注册和自动学习两种方式来建立昵称到微信ID的映射。

    使用方式：
    1. 手动注册：手动添加 {群名: {昵称: wxid}} 的映射
    2. 自动学习：当监听到消息时，如果发送者在注册表中不存在，
       会自动添加到待确认列表，供后续手动确认或关联

    用法示例：
        registry = MemberRegistry()

        # 手动添加成员
        registry.add_member("测试群", "张三", "wxid_xxx")

        # 从文件加载成员
        registry.load_from_file("members.json")

        # 在监听器中使用
        listener = WeChatGroupListener(
            client, groups, on_message,
            member_registry=registry
        )
    """

    def __init__(self):
        # {群名: {昵称: wxid}}
        self._members: Dict[str, Dict[str, str]] = {}
        # 缓存 {群名: {wxid: 昵称}}（反向索引）
        self._members_by_wxid: Dict[str, Dict[str, str]] = {}
        # 锁
        self._lock = threading.Lock()

    def add_member(self, group: str, name: str, wxid: str) -> None:
        """添加群成员到注册表。

        Args:
            group: 群名称
            name: 成员昵称
            wxid: 成员的微信ID（可为空字符串，表示未获取到）
        """
        with self._lock:
            if group not in self._members:
                self._members[group] = {}
                self._members_by_wxid[group] = {}
            self._members[group][name] = wxid
            # 只有非空微信ID才添加到反向索引
            if wxid:
                self._members_by_wxid[group][wxid] = name

    def get_wxid(self, group: str, name: str) -> Optional[str]:
        """根据群名和昵称获取微信ID。

        Args:
            group: 群名称
            name: 成员昵称

        Returns:
            微信ID，如果不存在则返回 None
        """
        with self._lock:
            return self._members.get(group, {}).get(name)

    def get_name_by_wxid(self, group: str, wxid: str) -> Optional[str]:
        """根据群名和微信ID获取昵称。

        Args:
            group: 群名称
            wxid: 成员的微信ID

        Returns:
            昵称，如果不存在则返回 None
        """
        with self._lock:
            return self._members_by_wxid.get(group, {}).get(wxid)

    def load_from_dict(self, data: Dict[str, Dict[str, str]]) -> None:
        """从字典加载成员数据。

        格式: {群名: {昵称: wxid}}

        Args:
            data: 成员数据字典
        """
        with self._lock:
            for group, members in data.items():
                if group not in self._members:
                    self._members[group] = {}
                    self._members_by_wxid[group] = {}
                for name, wxid in members.items():
                    self._members[group][name] = wxid
                    # 只有非空微信ID才添加到反向索引
                    if wxid:
                        self._members_by_wxid[group][wxid] = name

    def load_from_file(self, filepath: str) -> bool:
        """从 JSON 文件加载成员数据。

        Args:
            filepath: JSON 文件路径

        Returns:
            是否加载成功
        """
        import json
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.load_from_dict(data)
            logger.info(f"从 {filepath} 加载了 {len(data)} 个群的成员信息")
            return True
        except Exception as e:
            logger.warning(f"加载成员文件失败: {e}")
            return False

    def save_to_file(self, filepath: str) -> bool:
        """保存成员数据到 JSON 文件。

        Args:
            filepath: JSON 文件路径

        Returns:
            是否保存成功
        """
        import json
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self._members, f, ensure_ascii=False, indent=2)
            logger.info(f"成员信息已保存到 {filepath}")
            return True
        except Exception as e:
            logger.warning(f"保存成员文件失败: {e}")
            return False

    def to_dict(self) -> Dict[str, Dict[str, str]]:
        """导出成员数据为字典。

        Returns:
            成员数据字典
        """
        with self._lock:
            return {k: v.copy() for k, v in self._members.items()}

    def fuzzy_match_member(self, group: str, nickname: str, threshold: float = 0.6) -> Optional[Tuple[str, str]]:
        """
        使用相似度匹配查找群成员。

        当 OCR 识别的昵称可能不完整或有误差时，使用模糊匹配
        找到最相似的已注册成员。

        Args:
            group: 群名称
            nickname: OCR 识别到的昵称（可能不完整）
            threshold: 相似度阈值（0-1），默认 0.6

        Returns:
            Tuple[匹配的昵称, 微信ID]，如果未找到返回 None
        """
        if not nickname:
            return None

        with self._lock:
            group_members = self._members.get(group, {})
            if not group_members:
                return None

        best_match = None
        best_score = 0.0

        for member_name, wxid in group_members.items():
            # 计算相似度
            score = self._similarity(nickname, member_name)
            if score > best_score and score >= threshold:
                best_score = score
                best_match = (member_name, wxid)

        if best_match:
            logger.debug(f"模糊匹配: '{nickname}' -> '{best_match[0]}' (相似度: {best_score:.2f})")

        return best_match

    def _similarity(self, s1: str, s2: str) -> float:
        """
        计算两个字符串的相似度。

        使用多种方法综合计算：
        1. 包含关系：如果一个字符串包含另一个，提高分数
        2. 编辑距离：计算 Levenshtein 相似度
        3. 首尾字符匹配：昵称通常首尾字符更重要
        """
        if not s1 or not s2:
            return 0.0

        s1 = s1.strip()
        s2 = s2.strip()

        if s1 == s2:
            return 1.0

        # 包含关系
        if s1 in s2 or s2 in s1:
            shorter_len = min(len(s1), len(s2))
            longer_len = max(len(s1), len(s2))
            contain_score = shorter_len / longer_len
        else:
            contain_score = 0.0

        # Levenshtein 相似度
        edit_sim = self._levenshtein_similarity(s1, s2)

        # 首尾字符匹配
        prefix_score = 0.0
        if s1[0] == s2[0]:
            prefix_score = 0.2
        suffix_score = 0.0
        if s1[-1] == s2[-1]:
            suffix_score = 0.2

        # 综合评分
        final_score = max(contain_score, edit_sim) + prefix_score + suffix_score
        return min(final_score, 1.0)

    def _levenshtein_similarity(self, s1: str, s2: str) -> float:
        """计算 Levenshtein 相似度（0-1）"""
        if not s1 or not s2:
            return 0.0

        # 优化：限制长度差
        if abs(len(s1) - len(s2)) > max(len(s1), len(s2)) * 0.5:
            return 0.0

        # 动态规划计算编辑距离
        m, n = len(s1), len(s2)
        if m < n:
            s1, s2 = s2, s1
            m, n = n, m

        # 只保存两行
        prev = list(range(n + 1))
        for i in range(1, m + 1):
            curr = [i] + [0] * n
            for j in range(1, n + 1):
                if s1[i - 1] == s2[j - 1]:
                    curr[j] = prev[j - 1]
                else:
                    curr[j] = min(prev[j], curr[j - 1], prev[j - 1]) + 1
            prev = curr

        edit_distance = prev[n]
        max_len = max(m, n)
        return 1.0 - (edit_distance / max_len)


def _normalize_message_text(content: str) -> str:
    """归一化消息文本，提升本库发送回流识别的稳定性。"""
    text = str(content or "")
    text = text.replace("\u2005", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_same_outgoing_message(expected: str, actual: str) -> bool:
    """判断回流消息是否可视为本库刚发送的同一条消息。"""
    if not expected or not actual:
        return False
    if expected == actual:
        return True

    # 微信 UIA 在部分版本上会对长文本、多行文本做轻微归一化或裁剪，
    # 这里允许“包含关系”命中，避免机器人自己的回复再次触发监听链路。
    shorter, longer = sorted((expected, actual), key=len)
    if len(shorter) < 12:
        return False
    return shorter in longer


def _safe_text(control, attr: str) -> str:
    try:
        return str(getattr(control, attr, "") or "")
    except Exception:
        return ""


def _safe_children(control) -> list:
    try:
        return list(control.GetChildren())
    except Exception:
        return []


def _safe_runtime_id(control) -> Tuple[int, ...]:
    try:
        return tuple(control.GetRuntimeId() or ())
    except Exception:
        return ()


def _get_process_image_name(pid: int) -> str:
    """通过 pid 获取进程路径。"""
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
    except Exception:
        return ""


def _find_wechat_windows(include_hidden: bool = True) -> List[Tuple[int, str, str]]:
    windows: List[Tuple[int, str, str]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = os.path.basename(_get_process_image_name(pid)).lower()
            title = win32gui.GetWindowText(hwnd) or ""
            class_name = win32gui.GetClassName(hwnd) or ""
        except Exception:
            return True

        if exe_name in WECHAT_EXE_NAMES:
            # 检查可见性（可选，因为独立窗口可能被最小化）
            if include_hidden or win32gui.IsWindowVisible(hwnd):
                windows.append((hwnd, title, class_name))
        return True

    win32gui.EnumWindows(callback, 0)
    return windows


def _find_window_by_title(title_keyword: str, exclude_hwnd: Optional[int] = None) -> Optional[int]:
    """根据标题关键词查找微信窗口。
    
    独立聊天窗口的标题可能是:
    - 纯群名: "家庭龙虾"
    - 群名+未读数: "家庭龙虾 (3)"
    - 其他格式
    
    注意：当独立窗口存在时，主窗口的标题也可能变成群名！
    所以必须通过 exclude_hwnd 排除主窗口，而不是仅靠标题判断。
    """
    for hwnd, title, _class_name in _find_wechat_windows():
        # 排除主窗口（通过句柄，而不是标题）
        if exclude_hwnd is not None and hwnd == exclude_hwnd:
            continue
            
        # 标题完全匹配
        if title == title_keyword:
            logger.debug(f"找到独立窗口: '{title}' (hwnd={hwnd})")
            return hwnd
        # 标题包含群名（独立窗口格式如 "家庭龙虾 (3)"）
        if title_keyword in title:
            # 检查是否是独立窗口格式（群名 + 可选的后缀）
            # 匹配 "群名" 或 "群名 (数字)" 格式
            if re.match(rf'^{re.escape(title_keyword)}(\s*\(\d+\))?$', title):
                logger.debug(f"模式匹配独立窗口: '{title}' (hwnd={hwnd})")
                return hwnd
    
    return None


def _find_message_list(root):
    """查找聊天消息列表。"""
    try:
        msg_list = root.ListControl(AutomationId="chat_message_list")
        if msg_list.Exists(maxSearchSeconds=1):
            return msg_list
    except Exception:
        pass

    candidates = []
    try:
        for control, depth in uia.WalkControl(root, includeTop=True, maxDepth=8):
            if _safe_text(control, "ControlTypeName") != "ListControl":
                continue
            score = 0
            for child in _safe_children(control)[-12:]:
                cls = _safe_text(child, "ClassName")
                if cls in MESSAGE_CLASSES:
                    score += 10
                elif cls == TIME_CLASS:
                    score += 2
            if score:
                candidates.append((score, depth, control))
    except Exception:
        return None

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][2]


def _read_visible_items(msg_list) -> List[_VisibleItem]:
    items: List[_VisibleItem] = []
    for child in _safe_children(msg_list):
        cls = _safe_text(child, "ClassName")
        name = _safe_text(child, "Name").strip()
        if not name:
            continue
        if cls == TIME_CLASS:
            kind = "time/system"
            sender_name = None
        elif cls in MESSAGE_CLASSES:
            kind = "message"
            # 解析消息，提取发送者昵称
            sender_name, _ = parse_message_name(name)
        else:
            continue
        items.append(
            _VisibleItem(
                kind=kind,
                name=name,
                sender_name=sender_name,
                class_name=cls,
                runtime_id=_safe_runtime_id(child),
                control=child,
            )
        )
    return items


def _find_session_list(root):
    """查找微信左侧会话列表。"""
    try:
        session_list = root.ListControl(AutomationId="session_list")
        if session_list.Exists(maxSearchSeconds=1):
            return session_list
    except Exception:
        pass

    try:
        for control, _depth in uia.WalkControl(root, includeTop=True, maxDepth=6):
            if _safe_text(control, "ControlTypeName") != "ListControl":
                continue
            if _safe_text(control, "AutomationId") == "session_list" or _safe_text(control, "Name") == "会话":
                return control
    except Exception:
        return None
    return None


def _find_session_item(root, group_name: str, scroll_to_top: bool = True):
    """查找会话列表中的群聊项。

    Args:
        root: UIA 根控件
        group_name: 群名称
        scroll_to_top: 是否先滚动列表到顶部（确保置顶群聊可见）

    Returns:
        会话项控件，未找到返回 None
    """
    session_list = _find_session_list(root)
    if not session_list:
        return None

    # 滚动到顶部，确保置顶的群聊可见
    if scroll_to_top:
        try:
            # 使用 SendKeys 发送 Home 键滚动到顶部
            session_list.SetFocus()
            time.sleep(0.1)
            # 多按几次 Home 键确保滚动到最顶部
            for _ in range(3):
                session_list.SendKeys("{Home}", waitTime=0.1)
                time.sleep(0.1)
            logger.debug("已将会话列表滚动到顶部")
        except Exception as e:
            logger.debug(f"滚动会话列表失败: {e}")

    candidates = []
    try:
        for control, depth in uia.WalkControl(session_list, includeTop=False, maxDepth=3):
            if _safe_text(control, "ControlTypeName") != "ListItemControl":
                continue
            name = _safe_text(control, "Name")
            cls = _safe_text(control, "ClassName")
            score = 0
            if group_name in name:
                score += 100
            if "Session" in cls or "Conversation" in cls or "Cell" in cls:
                score += 30
            try:
                if control.IsSelected:
                    score += 80
            except Exception:
                pass
            if score:
                candidates.append((score, depth, control))
    except Exception:
        return None

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][2]


def _double_click_control(control) -> bool:
    try:
        control.DoubleClick(simulateMove=False)
        return True
    except Exception:
        pass

    try:
        rect = control.BoundingRectangle
        x = (rect.left + rect.right) // 2
        y = (rect.top + rect.bottom) // 2
        win32api.SetCursorPos((x, y))
        for _ in range(2):
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.08)
        return True
    except Exception:
        return False
class WeChatGroupListener:
    """微信群聊监听器。"""

    def __init__(
        self,
        client,
        groups: Iterable[str],
        on_message: Callable[[MessageEvent], Optional[str]],
        *,
        auto_reply: bool = True,
        ignore_client_sent: bool = True,
        reply_on_at: bool = False,
        group_nicknames: Optional[Dict[str, str]] = None,
        member_registry: Optional[MemberRegistry] = None,
        outgoing_ttl: float = 60.0,
        tick: float = 0.1,
        batch_size: int = 8,
        tail_size: int = 8,
    ):
        self.client = client
        self.groups = list(dict.fromkeys(groups))
        self.on_message = on_message
        self.auto_reply = auto_reply
        self.ignore_client_sent = ignore_client_sent
        self.reply_on_at = reply_on_at
        self.group_nicknames = dict(group_nicknames or {})
        self.member_registry = member_registry
        self.tick = tick
        self.batch_size = batch_size
        self.tail_size = tail_size
        shared_registry = getattr(self.client, "outgoing_registry", None)
        self.outgoing_registry = shared_registry or OutgoingMessageRegistry(outgoing_ttl)
        self.sessions: Dict[str, _ListenSession] = {}
        self._reply_queue: "queue.Queue[_ReplyTask]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sender_thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, block: bool = False) -> "WeChatGroupListener":
        """启动监听。"""
        self._open_sessions()
        self._stop_event.clear()
        self._start_sender()
        if block:
            try:
                self._run_loop()
            finally:
                self.stop()
        else:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        """停止监听。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._sender_thread and self._sender_thread.is_alive():
            self._sender_thread.join(timeout=5)

    def run_forever(self) -> None:
        """阻塞当前线程持续监听，直到 Ctrl+C。"""
        try:
            if not self.is_running:
                self.start(block=True)
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def _open_sessions(self) -> None:
        # 关键修复：启动阶段先关闭所有独立窗口，在主窗口上完成所有操作后再重新打开
        # 避免独立窗口存在时操作主窗口触发托盘恢复循环
        logger.info("启动阶段：关闭所有独立窗口...")
        closed_windows = self._close_all_independent_windows()
        logger.info(f"已关闭 {len(closed_windows)} 个独立窗口")
        
        # 关键修复：关闭独立窗口后，确保主窗口可见
        from src.core.win32 import find_wechat_window
        from src.core.tray import restore_wechat_from_native_tray
                
        # 关闭所有独立窗口后，等待一下让微信自动恢复主窗口
        time.sleep(1.0)
                
        main_hwnd = find_wechat_window()
        main_class_name = win32gui.GetClassName(main_hwnd) if main_hwnd else ""
        main_window_title = win32gui.GetWindowText(main_hwnd) if main_hwnd else ""
        logger.info(f"find_wechat_window 返回: {main_hwnd}, ClassName={main_class_name}, 标题='{main_window_title}'")
                
        # 检查是否是真正的主窗口（标题为"微信"且 ClassName 是 Qt51514QWindowIcon）
        is_main_window = main_hwnd and main_window_title == "微信" and main_class_name == "Qt51514QWindowIcon"
                
        if not is_main_window:
            logger.info("当前窗口不是主窗口（可能是独立窗口），尝试通过托盘恢复主窗口...")
            # 关闭当前的独立窗口
            if main_hwnd:
                logger.info(f"关闭独立窗口: {main_hwnd}")
                win32gui.PostMessage(main_hwnd, win32con.WM_CLOSE, 0, 0)
                time.sleep(1.0)
                    
            # 通过托盘恢复主窗口
            if restore_wechat_from_native_tray():
                time.sleep(2.5)
                main_hwnd = find_wechat_window()
                main_class_name = win32gui.GetClassName(main_hwnd) if main_hwnd else ""
                main_window_title = win32gui.GetWindowText(main_hwnd) if main_hwnd else ""
                logger.info(f"托盘恢复后: {main_hwnd}, ClassName={main_class_name}, 标题='{main_window_title}'")
        
        if main_hwnd and main_hwnd != self.client.window.hwnd:
            logger.info(f"主窗口句柄已更新: {self.client.window.hwnd} -> {main_hwnd}")
            self.client.window._hwnd = main_hwnd
        
        if not win32gui.IsWindowVisible(main_hwnd):
            logger.info("主窗口不可见，恢复主窗口")
            # 使用 activate() 恢复主窗口（比 ShowWindow 更可靠）
            self.client.window.activate()
            # 关键修复：等待 UIA 树完全加载
            time.sleep(2.5)
            logger.info("主窗口已恢复")
        
        # 统一读取群昵称（此时只有主窗口，不会有托盘恢复循环）
        # 始终加载群昵称，因为 is_at_me 属性在消息事件中会用到
        logger.info("启动阶段统一读取群昵称...")
        for group in self.groups:
            if not self.group_nicknames.get(group):
                logger.info(f"读取群昵称: {group}")
                self._read_group_nickname(group)
        logger.info(f"群昵称加载完成: {list(self.group_nicknames.keys())}")

        # 第一步：为所有群注册成员（此时主窗口可见，不会有托盘恢复循环）
        if self.member_registry:
            logger.info("启动阶段：统一注册所有群成员...")
            for group in self.groups:
                self._register_group_members(group)
            logger.info("所有群成员注册完成")

        # 第二步：批量打开独立窗口
        # 策略：逐个打开独立窗口，_ensure_subwindow 会自动处理主窗口恢复
        logger.info("启动阶段：批量打开独立窗口...")
        all_sessions = {}

        for i, group in enumerate(self.groups):
            if group in self.sessions:
                continue

            logger.info(f"正在为群 '{group}' 打开独立窗口 ({i+1}/{len(self.groups)})...")

            try:
                # _ensure_subwindow 内部会自动确保主窗口可见再操作
                hwnd = self._ensure_subwindow(group, chat_already_open=True)

                root = uia.ControlFromHandle(hwnd)
                msg_list = _find_message_list(root)
                if not msg_list:
                    raise RuntimeError(f"未找到群聊消息列表: {group}")
                baseline = _read_visible_items(msg_list)

                all_sessions[group] = _ListenSession(
                    group=group,
                    hwnd=hwnd,
                    root=root,
                    msg_list=msg_list,
                    seen={item.key for item in baseline},
                )
                logger.info(f"已为群 '{group}' 创建监听 session (hwnd={hwnd})")

                # 增加窗口间等待时间，避免微信资源竞争
                if i < len(self.groups) - 1:
                    time.sleep(1.5)

            except Exception as e:
                logger.error(f"为群 '{group}' 打开独立窗口失败: {e}")
                # 继续尝试其他群，而不是直接失败
                continue

        if not all_sessions:
            raise RuntimeError("未能成功打开任何独立窗口")

        # 保存所有 session
        self.sessions.update(all_sessions)
        logger.info(f"所有独立窗口打开完成，共 {len(self.sessions)} 个监听 session")

    def _read_group_nickname(self, group: str) -> bool:
        """读取群昵称。

        ``GroupManager.get_group_nickname`` 本身会打开目标群聊并进入详情面板。
        返回 True 表示当前主窗口大概率已经停留在该群聊，可直接双击左侧会话项
        打开独立窗口，避免再次搜索同一个群。
        """
        # 注意：_ensure_main_window_visible 已在 _open_sessions 开头统一调用
        # 这里不再重复调用，避免反复最小化/恢复窗口

        try:
            nickname = self.client.group_manager.get_group_nickname(group)
        except Exception as exc:
            logger.warning(f"读取群昵称失败: {group}: {exc}")
            return False

        if nickname:
            self.group_nicknames[group] = nickname
        else:
            logger.warning(f"未读取到群昵称，无法精确判断是否 @ 我: {group}")
        return True

    def _register_group_members(self, group: str) -> int:
        """
        注册群成员到 MemberRegistry。

        使用 get_all_members_wxid 一次性获取所有成员的昵称和微信ID。
        效率高，不需要为每个成员单独打开群详情。

        启动时会检查 group_members.json 中该群的成员数量是否与实际一致，
        如果不一致则重新获取。

        Args:
            group: 群名称

        Returns:
            成功获取微信ID的成员数量
        """
        if not self.member_registry:
            return 0

        # 检查是否已有注册信息
        existing = self.member_registry._members.get(group, {})
        
        if len(existing) > 0:
            # 已有注册信息，验证成员数量是否一致
            try:
                # 获取当前群的实际成员数量
                actual_count = self.client.group_manager.get_group_member_count(group)
                registered_count = len(existing)
                
                # 如果获取失败（返回负数或None），跳过验证
                if not actual_count or actual_count < 0:
                    logger.warning(
                        f"群 '{group}' 获取成员数量失败（返回{actual_count}），跳过验证"
                    )
                    registered_with_wxid = sum(1 for v in existing.values() if v)
                    return registered_with_wxid
                
                if actual_count != registered_count:
                    logger.info(
                        f"群 '{group}' 成员数量变化: 已注册 {registered_count} 名，实际 {actual_count} 名，重新注册..."
                    )
                    # 清空旧数据，重新注册
                    self.member_registry._members[group] = {}
                else:
                    # 成员数量一致，跳过重新注册
                    registered_with_wxid = sum(1 for v in existing.values() if v)
                    logger.info(
                        f"群 '{group}' 已有 {registered_count} 名成员注册（{registered_with_wxid} 名有微信ID），数量一致，跳过验证"
                    )
                    return registered_with_wxid
            except Exception as e:
                logger.warning(f"获取群成员数量失败，跳过验证: {e}")
                registered_with_wxid = sum(1 for v in existing.values() if v)
                return registered_with_wxid

        logger.info(f"开始注册群 '{group}' 的成员...")

        try:
            # 一次性获取所有成员的昵称和微信ID
            members = self.client.group_manager.get_all_members_wxid(group)
            if not members:
                logger.warning(f"未获取到群 '{group}' 的成员列表")
                return 0

            logger.info(f"获取到 {len(members)} 名群成员，开始注册...")

            # 注册所有成员（包括没有微信ID的）
            success_count = 0
            for member_name, wxid in members.items():
                # 即使微信ID为空也注册昵称，方便后续 OCR 匹配
                self.member_registry.add_member(group, member_name, wxid)
                if wxid:
                    success_count += 1

            # 保存到文件
            members_file = "group_members.json"
            self.member_registry.save_to_file(members_file)
            logger.info(f"已注册 {len(members)} 名成员到 {members_file}，其中 {success_count} 名获取到微信ID")

            return success_count

        except Exception as e:
            logger.error(f"注册群成员失败: {e}")
            return 0
    def _ensure_main_window_visible(self) -> None:
        """确保微信主窗口可见，避免操作主窗口时反复触发托盘恢复逻辑。

        当独立聊天窗口存在时，微信主窗口可能被隐藏或最小化，
        后续操作主窗口（如注册群成员）会触发 _activate_hwnd 中的
        托盘恢复逻辑，导致反复日志输出且无法成功恢复。

        解决方案：先最小化所有独立聊天窗口，再恢复主窗口。
        微信在有独立窗口可见时会自动隐藏主窗口，所以必须先最小化独立窗口。
        操作完成后，_ensure_subwindow 会重新打开独立窗口。
        """
        try:
            # 第1步：最小化所有独立窗口
            self._minimize_independent_windows()
            
            # 第2步：重新查找主窗口（因为当前 self.client.window.hwnd 可能是独立窗口）
            from src.core.win32 import find_wechat_window
            main_hwnd = find_wechat_window()
            if not main_hwnd:
                logger.warning("未找到主窗口")
                return
            
            # 如果主窗口句柄变化了，更新 client.window._hwnd
            if main_hwnd != self.client.window._hwnd:
                logger.info(f"主窗口句柄已更新: {self.client.window._hwnd} -> {main_hwnd}")
                self.client.window._hwnd = main_hwnd
            
            # 第3步：确保主窗口可见
            if not win32gui.IsWindowVisible(main_hwnd):
                logger.info("主窗口不可见，尝试恢复（已最小化独立窗口）")
                # 使用 activate() 恢复主窗口（比 ShowWindow 更可靠）
                self.client.window._hwnd = main_hwnd
                self.client.window.activate()
                time.sleep(2.5)

                if win32gui.IsWindowVisible(main_hwnd):
                    logger.info("主窗口已恢复可见")
                    # 关键修复：主窗口恢复后等待 UIA 树完全加载
                    # 避免后续 open_chat 找不到搜索框
                    time.sleep(2.0)
                else:
                    logger.warning("主窗口恢复失败")
            else:
                logger.debug("主窗口已可见，独立窗口已最小化")
                # 即使主窗口可见，也等待一下确保 UIA 树稳定
                time.sleep(1.0)
        except Exception as e:
            logger.debug(f"确保主窗口可见失败: {e}")

    def _close_all_independent_windows(self) -> List[int]:
        """关闭所有独立聊天窗口（除了主窗口）。
        
        Returns:
            已关闭的窗口句柄列表
        """
        closed_hwnds = []
        try:
            main_hwnd = self.client.window.hwnd
            
            # 枚举所有微信窗口
            for hwnd, title, class_name in _find_wechat_windows():
                # 跳过主窗口
                if hwnd == main_hwnd:
                    continue
                # 只关闭 Qt 窗口（独立聊天窗口）
                if not class_name.startswith("Qt"):
                    continue
                # 跳过系统窗口（通过标题识别）
                if title in ('Weixin', 'WxTrayIconMessageWindow', '微信', ''):
                    continue
                # 关闭窗口
                logger.info(f"关闭独立窗口: '{title}' (hwnd={hwnd})")
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                closed_hwnds.append(hwnd)
            
            if closed_hwnds:
                time.sleep(0.5)  # 等待窗口关闭完成
        except Exception as e:
            logger.debug(f"关闭独立窗口失败: {e}")
        
        return closed_hwnds

    def _minimize_independent_windows(self, force_all: bool = False) -> None:
        """最小化所有独立聊天窗口，使微信主窗口可以保持可见。

        微信4.x的行为：当有独立聊天窗口可见时，主窗口会被自动隐藏。
        在需要操作主窗口时，必须先最小化这些独立窗口。

        Args:
            force_all: 如果为 True，最小化所有标题可能为群名的窗口（不限于 self.groups）
        """
        try:
            main_hwnd = self.client.window.hwnd
            minimized = 0

            # 1. 先最小化 self.sessions 中已注册的独立窗口
            for group, session in self.sessions.items():
                if session.hwnd and session.hwnd != main_hwnd:
                    if win32gui.IsWindow(session.hwnd):
                        logger.debug(f"最小化独立窗口: {group} (hwnd={session.hwnd})")
                        win32gui.ShowWindow(session.hwnd, win32con.SW_MINIMIZE)
                        minimized += 1

            # 2. 通过 Win32 API 枚举所有微信窗口，找到残留的独立窗口
            known_hwnds = {main_hwnd}
            for session in self.sessions.values():
                if session.hwnd:
                    known_hwnds.add(session.hwnd)

            for hwnd, title, class_name in _find_wechat_windows():
                if hwnd in known_hwnds:
                    continue
                # 根据 force_all 参数决定是否检查群名
                if force_all:
                    # 最小化所有 Qt 窗口（可能是未知群名的独立窗口）
                    if not class_name.startswith("Qt"):
                        continue
                else:
                    # 只最小化标题匹配已知群名的窗口
                    if title not in self.groups:
                        continue
                # 最小化独立聊天窗口
                logger.info(f"最小化残留独立窗口: '{title}' (hwnd={hwnd})")
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                minimized += 1

            if minimized > 0:
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"最小化独立窗口失败: {e}")

    def _ensure_subwindow(self, group: str, chat_already_open: bool = False, max_retries: int = 2) -> int:
        """确保独立聊天窗口已打开。

        Args:
            group: 群名称
            chat_already_open: 主窗口是否已打开该群聊
            max_retries: 最大重试次数

        Returns:
            独立窗口句柄
        """
        main_hwnd = self.client.window.hwnd
        main_title = win32gui.GetWindowText(main_hwnd) or ""

        # 特殊情况：如果主窗口的标题就是群名，说明主窗口本身就是独立窗口
        # 这可能发生在：上次程序异常退出后，独立窗口被误识别为主窗口
        if main_title == group or re.match(rf'^{re.escape(group)}(\s*\(\d+\))?$', main_title):
            logger.debug(f"主窗口标题 '{main_title}' 匹配群名 '{group}'，直接使用")
            return main_hwnd

        # 先检查是否已有独立窗口
        hwnd = _find_window_by_title(group, exclude_hwnd=main_hwnd)
        if hwnd:
            logger.debug(f"找到独立窗口: {group} (hwnd={hwnd})")
            return hwnd

        logger.debug(f"未找到独立窗口 '{group}'，需要打开新窗口")

        last_error = None
        for attempt in range(max_retries):
            try:
                # 关键：在操作主窗口前，确保主窗口可见
                # 微信在有独立窗口可见时会自动隐藏主窗口
                # 必须先最小化所有独立窗口，再恢复主窗口
                self._ensure_main_window_visible()

                if not chat_already_open:
                    if not self.client.chat_window.open_chat(group, target_type="group"):
                        raise RuntimeError(f"打开群聊失败: {group}")
                    time.sleep(1.0)  # 增加等待时间

                item = _find_session_item(self.client.window.uia.root, group)
                if not item and chat_already_open:
                    logger.debug(f"当前会话项未找到，重新搜索打开群聊: {group}")
                    if not self.client.chat_window.open_chat(group, target_type="group"):
                        raise RuntimeError(f"打开群聊失败: {group}")
                    time.sleep(1.0)
                    item = _find_session_item(self.client.window.uia.root, group)

                if not item or not _double_click_control(item):
                    raise RuntimeError(f"打开独立聊天窗口失败: {group}")

                # 增加超时时间到 15 秒
                deadline = time.time() + 15
                while time.time() < deadline:
                    hwnd = _find_window_by_title(group, exclude_hwnd=main_hwnd)
                    if hwnd:
                        logger.info(f"成功打开独立窗口: {group} (hwnd={hwnd})")
                        return hwnd
                    time.sleep(0.3)

                raise RuntimeError(f"等待独立聊天窗口超时: {group}")

            except Exception as e:
                last_error = e
                logger.warning(f"打开独立窗口 '{group}' 失败 (尝试 {attempt + 1}/{max_retries}): {e}")

                # 重试前关闭可能残留的窗口
                try:
                    for hwnd, title, _ in _find_wechat_windows():
                        if group in title and hwnd != main_hwnd:
                            logger.info(f"关闭残留窗口: {title}")
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    time.sleep(0.5)
                except Exception:
                    pass

                # 等待一段时间后重试
                time.sleep(1.5)

        raise RuntimeError(f"打开独立窗口 '{group}' 失败，已重试 {max_retries} 次: {last_error}")

    def _run_loop(self) -> None:
        logger.info(f"开始监听群聊: {', '.join(self.groups)}")
        while not self._stop_event.is_set():
            now = time.time()
            for session in self._due_sessions(now):
                self._poll_session(session)
            time.sleep(self.tick)
        logger.info("群聊监听已停止")

    def _due_sessions(self, now: float) -> List[_ListenSession]:
        sessions = [
            session for session in self.sessions.values()
            if session.next_scan_at <= now
        ]
        sessions.sort(key=lambda session: session.next_scan_at)
        return sessions[:self.batch_size]

    def _poll_session(self, session: _ListenSession) -> None:
        session.scan_count += 1
        try:
            items = _read_visible_items(session.msg_list)
            if self.tail_size > 0:
                items = items[-self.tail_size:]
        except Exception as exc:
            session.fail_count += 1
            logger.debug(f"读取群聊消息失败: {session.group}: {exc}")
            return

        added = 0
        for item in items:
            if item.key in session.seen:
                continue
            session.seen.add(item.key)
            if item.kind != "message":
                continue
            if self.ignore_client_sent and self.outgoing_registry.should_ignore(session.group, item.name):
                continue
            added += 1
            session.new_count += 1
            self._handle_message(session, item)

        self._update_next_scan(session, added)

    def _handle_message(self, session: _ListenSession, item: _VisibleItem) -> None:
        # 解析消息内容（可能包含 @发送者 格式的前缀）
        _, content = parse_message_name(item.name)

        sender_wxid = None
        sender_name = None
        matched_by = None  # 记录匹配方式

        # 获取当前群的用户自己的昵称
        my_nickname = self.group_nicknames.get(session.group)

        # OCR识别发送者昵称（完全静默，无鼠标操作）
        ocr_sender = self._ocr_recognize_sender(session, item, content)

        if ocr_sender:
            sender_name = ocr_sender

            # 尝试精确匹配
            if self.member_registry:
                sender_wxid = self.member_registry.get_wxid(session.group, sender_name)
                if sender_wxid:
                    matched_by = "精确匹配"

            # 如果精确匹配失败，尝试模糊匹配
            if not sender_wxid and self.member_registry:
                fuzzy_result = self.member_registry.fuzzy_match_member(session.group, sender_name)
                if fuzzy_result:
                    matched_name, matched_wxid = fuzzy_result
                    # 更新为匹配到的昵称（可能更完整）
                    sender_name = matched_name
                    sender_wxid = matched_wxid
                    matched_by = "模糊匹配"

        # 如果 OCR 识别失败，或者识别结果无法匹配任何已注册成员，视为用户自己
        # 这种情况可能是：
        # 1. 用户自己@自己，OCR识别出错导致昵称乱码或识别失败
        # 2. OCR 识别的昵称与群成员列表中任何人都匹配不上
        if not sender_wxid and my_nickname:
            if ocr_sender and sender_name:
                logger.info(f"[{session.group}] OCR识别昵称 '{sender_name}' 未匹配到群成员，视为自己 ({my_nickname})")
            else:
                logger.info(f"[{session.group}] OCR识别失败，视为自己 ({my_nickname})")
            sender_name = my_nickname
            # 从 member_registry 中根据昵称查找自己的 wxid
            if self.member_registry:
                sender_wxid = self.member_registry.get_wxid(session.group, my_nickname)
            matched_by = "自己"

        # 打印结果
        if sender_name:
            if sender_wxid:
                logger.info(f"[{session.group}] {sender_name} ({sender_wxid}): {content[:50]} [{matched_by or '精确匹配'}]")
            else:
                logger.info(f"[{session.group}] {sender_name} (自己): {content[:50]}")
        else:
            logger.info(f"[{session.group}] [未知发送者]: {content[:50]}")

        event = MessageEvent(
            group=session.group,
            content=content,
            sender_name=sender_name,
            sender_wxid=sender_wxid,
            timestamp=time.time(),
            group_nickname=self.group_nicknames.get(session.group),
            is_at_me=self._is_at_me(session.group, content),
            raw=item.control,
        )
        try:
            reply = self.on_message(event)
        except Exception as exc:
            logger.exception(f"消息回调执行失败: {session.group}: {exc}")
            return

        if self.auto_reply and reply and self._should_send_reply(event):
            self.enqueue_reply(session.group, str(reply))

    def _get_sender_via_ui(self, session: _ListenSession, item: _VisibleItem) -> Optional[Tuple[str, Optional[str]]]:
        """
        通过点击消息气泡获取发送者信息（UI方式）

        Returns:
            Tuple[发送者昵称, 微信ID] 或 None
        """
        sender_name = None
        sender_wxid = None

        try:
            rect = item.control.BoundingRectangle
            if not rect:
                return None

            # 点击消息气泡
            center_x = rect.left + 30
            center_y = (rect.top + rect.bottom) // 2

            _right_click_at_position(center_x, center_y)
            time.sleep(1)

            # 查找右键菜单
            context_menu = None
            for pattern in ['mmui::CPopupMenu', 'mmui::CMenu', 'mmui::PopupMenu']:
                try:
                    menu = session.root.WindowControl(ClassName=pattern)
                    if menu.Exists(maxSearchSeconds=0.5):
                        context_menu = menu
                        break
                except:
                    pass

            if not context_menu:
                _close_popup()
                return None

            # 点击"查看个人资料"
            for ctrl, depth in uia.WalkControl(context_menu, includeTop=False, maxDepth=5):
                try:
                    name = ctrl.Name or ""
                    if "查看个人资料" in name or "查看资料" in name:
                        ctrl.Click(simulateMove=False)
                        time.sleep(1.5)
                        break
                except:
                    pass

            _close_popup()

            # 查找资料卡
            for pattern in ['mmui::ProfileUniquePop', 'mmui::ContactProfileView', 'mmui::ProfileCardView']:
                try:
                    ctrl = session.root.WindowControl(ClassName=pattern)
                    if ctrl.Exists(maxSearchSeconds=0.5):
                        sender_name = ctrl.Name
                        if sender_name:
                            sender_name = sender_name.strip()

                        # 获取微信ID
                        for child, _ in uia.WalkControl(ctrl, includeTop=False, maxDepth=10):
                            if child.ClassName == 'mmui::ContactProfileTextView':
                                wxid = child.Name or ""
                                if wxid.startswith('wxid_'):
                                    sender_wxid = wxid
                                    break
                        break
                except:
                    pass

            _close_popup()

            if sender_name:
                return (sender_name, sender_wxid)

        except Exception as e:
            logger.debug(f"UI方式获取发送者失败: {e}")

        return None

    def _ocr_recognize_sender(self, session: _ListenSession, item: _VisibleItem, message_content: str = None) -> Optional[str]:
        """
        使用PaddleOCR识别消息发送者昵称（纯后台，无鼠标操作）

        策略：
        1. 使用PrintWindow截取整个窗口（支持最小化窗口）
        2. 根据消息内容定位消息位置
        3. 在消息上方查找发送者昵称

        Args:
            session: 监听会话
            item: 消息项
            message_content: 已知的消息内容（用于定位）

        Returns:
            发送者昵称，失败返回None
        """
        import win32gui
        import datetime

        # 调试截图保存目录
        debug_dir = os.path.join(_SCREENSHOT_DIR, 'debug_ocr')
        try:
            os.makedirs(debug_dir, exist_ok=True)
        except Exception:
            debug_dir = _SCREENSHOT_DIR

        # 临时截图路径列表，用于最后清理
        temp_paths = []

        try:
            # 获取消息气泡的边界（屏幕坐标）
            msg_rect = item.control.BoundingRectangle
            if not msg_rect:
                logger.debug("无法获取消息区域边界")
                return None

            target_hwnd = session.hwnd

            # 保存窗口原始状态，用于判断是否需要在OCR完成后恢复最小化
            try:
                original_win_rect = win32gui.GetWindowRect(target_hwnd)
                was_minimized = original_win_rect[0] < 0 or original_win_rect[1] < 0
            except Exception:
                original_win_rect = None
                was_minimized = False

            # 获取窗口标题验证
            title = win32gui.GetWindowText(target_hwnd)
            class_name = win32gui.GetClassName(target_hwnd)
            win_rect = win32gui.GetWindowRect(target_hwnd)
            logger.debug(f"截图目标: HWND={target_hwnd}, 标题='{title}', 类名='{class_name}', 区域={win_rect}")

            # 无论窗口是否最小化，都使用 PrintWindow 截取目标窗口
            # 这样可以确保截取的是独立聊天窗口的内容，而不是屏幕上的其他内容
            logger.debug("使用PrintWindow截取目标窗口")
            capture_result = _capture_window_full(target_hwnd)
            if not capture_result:
                logger.debug("PrintWindow截图失败")
                return None

            full_path, full_w, full_h = capture_result
            temp_paths.append(full_path)  # 记录临时文件
            logger.debug(f"截图尺寸: {full_w}x{full_h}")

            # 保存完整截图用于调试
            from PIL import Image
            full_img = Image.open(full_path)
            timestamp = datetime.datetime.now().strftime('%H%M%S_%f')
            full_debug_path = os.path.join(debug_dir, f'full_{timestamp}.png')
            full_img.save(full_debug_path)

            # 获取窗口在屏幕上的实际位置
            # 注意：_capture_window_full 可能移动了窗口，需要重新获取 msg_rect
            # 否则用旧坐标 - 新坐标 = 错误的相对位置
            win_rect = win32gui.GetWindowRect(target_hwnd)
            win_left, win_top = win_rect[0], win_rect[1]
            logger.debug(f"窗口当前屏幕位置: ({win_left}, {win_top})")

            # 重新获取消息气泡坐标（窗口移动后UIA坐标已更新）
            try:
                msg_rect = item.control.BoundingRectangle
            except Exception:
                logger.warning("窗口移动后无法重新获取消息气泡坐标")
                return None

            if not msg_rect:
                logger.warning("窗口移动后消息气泡坐标为空")
                return None

            logger.info(f"消息气泡(屏幕坐标): ({msg_rect.left}, {msg_rect.top}) - ({msg_rect.right}, {msg_rect.bottom})")

            # 将屏幕坐标转换为截图内的相对坐标
            rel_left = msg_rect.left - win_left
            rel_top = msg_rect.top - win_top
            rel_right = msg_rect.right - win_left
            rel_bottom = msg_rect.bottom - win_top
            logger.info(f"消息气泡(截图相对坐标): ({rel_left}, {rel_top}) - ({rel_right}, {rel_bottom})")

            # 新策略：根据消息内容定位发送者昵称
            # 1. 对完整截图进行 OCR
            # 2. 找到消息内容的位置
            # 3. 在消息内容上方查找昵称
            from src.utils.ocr_utils import recognize_text
            texts = recognize_text(full_debug_path)
            logger.info(f"完整截图OCR识别到 {len(texts)} 个文本块")

            # 打印所有OCR结果用于调试
            logger.info("=== OCR原始识别结果 ===")
            for i, (text, confidence, bbox) in enumerate(texts):
                logger.info(f"  [{i}] text='{text}', conf={confidence:.2f}, bbox={bbox}")

            # 已知的消息内容
            # message_content 是传入的参数
            logger.info(f"待匹配的消息内容: '{message_content}' (长度: {len(message_content) if message_content else 0})")

            # 查找消息内容的位置
            # 当有多个相同内容的消息时，优先选择左侧的候选
            # 原因：别人的消息在左侧（left_x 较小），自己发的消息在右侧
            # UIA 不区分左右，所以可能匹配到自己发的同内容消息
            # 优先选择左侧候选，可以确保找到正确的发送者昵称
            msg_bbox = None
            msg_candidates = []
            for text, confidence, bbox in texts:
                if message_content and message_content in text:
                    msg_candidates.append((text, confidence, bbox))
                    logger.info(f"找到消息内容候选(完全匹配) '{text}' 位置: {bbox}")
                # 也尝试反向匹配（OCR结果在消息内容中）
                elif message_content and text in message_content:
                    msg_candidates.append((text, confidence, bbox))
                    logger.info(f"找到消息内容候选(部分匹配) '{text}' 位置: {bbox}")
                # 尝试归一化空格后匹配
                elif message_content:
                    normalized_content = message_content.replace("\u2005", "").replace("\xa0", "").strip()
                    normalized_text = text.replace("\u2005", "").replace("\xa0", "").strip()
                    if normalized_content in normalized_text or normalized_text in normalized_content:
                        msg_candidates.append((text, confidence, bbox))
                        logger.info(f"找到消息内容候选(归一化匹配) '{text}' 位置: {bbox}")

            if msg_candidates:
                # 先按 Y 坐标排序，找到与 UIA 气泡 Y 范围最接近的候选
                # UIA 气泡 Y 范围: rel_top ~ rel_bottom
                uia_y_center = (rel_top + rel_bottom) / 2
                # 按与 UIA Y 中心的距离排序，选最近的
                msg_candidates.sort(key=lambda x: abs((max(x[2][0][1], x[2][2][1]) + min(x[2][0][1], x[2][2][1])) / 2 - uia_y_center))
                # 在 Y 坐标最近的候选中，优先选择左侧的（left_x 较小的）
                # 别人的消息在左侧，如果有同内容的别人消息，应该选左侧的
                best_y_dist = abs((max(msg_candidates[0][2][0][1], msg_candidates[0][2][2][1]) + min(msg_candidates[0][2][0][1], msg_candidates[0][2][2][1])) / 2 - uia_y_center)
                close_candidates = [c for c in msg_candidates if abs((max(c[2][0][1], c[2][2][1]) + min(c[2][0][1], c[2][2][1])) / 2 - uia_y_center) <= best_y_dist + 30]
                # 在Y坐标接近的候选中，优先选择左侧的
                close_candidates.sort(key=lambda x: x[2][0][0])  # 按 left_x 升序
                msg_text, _, msg_bbox = close_candidates[0]
                logger.info(f"选择消息候选: '{msg_text}' 位置: {msg_bbox} (共{len(msg_candidates)}个候选, {len(close_candidates)}个Y接近)")

            # 如果找到了消息内容，在上方查找昵称
            sender = None
            if msg_bbox:
                # 消息气泡的坐标（OCR 识别到的消息内容位置）
                msg_top_y = msg_bbox[0][1]  # 左上角的 Y 坐标
                msg_left_x = msg_bbox[0][0]  # 左上角的 X 坐标
                msg_right_x = msg_bbox[1][0]  # 右上角的 X 坐标
                msg_center_x = (msg_left_x + msg_right_x) / 2

                logger.debug(f"消息气泡位置: top_y={msg_top_y}, left_x={msg_left_x}, right_x={msg_right_x}, center_x={msg_center_x}")

                # 不在这里提前判断"自己"，而是先查找昵称
                # 如果消息上方能找到昵称，说明是别人发的
                # 如果找不到昵称，再根据左右位置判断是否是"自己"

                logger.debug(f"消息气泡顶部 Y: {msg_top_y}, 左侧 X: {msg_left_x}")

                # 昵称在消息气泡上方约 5-50 像素
                # 查找在消息上方的文本
                nickname_candidates = []
                for text, confidence, bbox in texts:
                    # 文本的底部 Y 坐标
                    text_bottom_y = max(bbox[0][1], bbox[2][1])  # 左下或右下的 Y
                    text_top_y = min(bbox[0][1], bbox[2][1])

                    # 计算与消息的距离
                    distance = msg_top_y - text_bottom_y

                    # 调试：显示所有文本块的位置
                    logger.debug(f"文本 '{text}' 底部Y={text_bottom_y}, 距离消息={distance}px")

                    # 昵称应该在消息气泡正上方
                    # 微信群聊中，昵称距离消息顶部约 5-50 像素
                    # 上一条消息与本条消息之间的间距通常大于 60 像素
                    if text_bottom_y < msg_top_y and text_bottom_y > msg_top_y - 60:
                        # 距离太近可能是消息内容的一部分
                        if distance < 5:
                            continue
                        # 过滤非昵称文本
                        import re
                        # 排除与消息内容相同或非常相似的文本（不是昵称）
                        if message_content:
                            # 长度相近的文本很可能是消息内容而非昵称
                            if abs(len(text) - len(message_content)) <= 2 and len(text) >= 2:
                                continue
                            # 字符重叠过滤
                            if len(text) >= 3:
                                overlap = sum(1 for c in text if c in message_content) / len(text)
                                if overlap > 0.7 and len(text) >= 4:
                                    continue
                        # 排除时间格式
                        if re.match(r'^\d{1,2}:\d{2}$', text):
                            continue
                        # 排除纯数字
                        if text.replace(' ', '').isdigit():
                            continue
                        # 排除群名
                        if re.search(r'[（(]\s*\d+\s*[）)]', text):
                            continue
                        # 排除通知类
                        if '新消息' in text or '条新' in text:
                            continue
                        # 排除包含 @ 的文本（@ 提及内容，不是发送者昵称）
                        # 昵称不会包含 @ 符号
                        if '@' in text or text.startswith('\uff20'):
                            continue

                        # 昵称长度通常是 1-12 个字符（排除长文本）
                        if 1 <= len(text) <= 12:
                            nickname_candidates.append((text, confidence, distance, bbox))
                            logger.debug(f"昵称候选: '{text}', 距离消息: {distance}px")

                # 按距离排序，选择最近的
                if nickname_candidates:
                    nickname_candidates.sort(key=lambda x: x[2])
                    sender = nickname_candidates[0][0]
                    logger.info(f"60px搜索找到发送者: {sender}")
                else:
                    logger.info("60px搜索未找到发送者昵称")

            # 如果在消息上方 60 像素内没找到昵称，可能是连续消息
            # 尝试在更大的范围内查找最近的昵称
            if not sender and msg_bbox:
                logger.debug("在消息上方60像素内未找到昵称，尝试扩大搜索范围...")
                
                # 先判断消息的左右位置
                msg_left_x = msg_bbox[0][0]  # 消息左边界
                msg_right_x = msg_bbox[1][0]  # 消息右边界
                msg_center_x = (msg_left_x + msg_right_x) / 2
                # 使用消息中心位置判断左右：中心在右侧则是自己发的
                msg_is_right = msg_center_x > full_w * 0.5
                logger.info(f"消息位置: left_x={msg_left_x}, right_x={msg_right_x}, center_x={msg_center_x:.1f}, is_right={msg_is_right}")
                
                all_nickname_candidates = []
                for text, confidence, bbox in texts:
                    text_bottom_y = max(bbox[0][1], bbox[2][1])
                    text_left_x = bbox[0][0]  # 昵称左边界
                    distance = msg_top_y - text_bottom_y

                    # 在消息上方任意位置查找昵称（最大 500 像素）
                    if text_bottom_y < msg_top_y and text_bottom_y > msg_top_y - 500:
                        if distance < 5:
                            continue
                        import re
                        # 排除与消息内容相同或非常相似的文本
                        if message_content:
                            if abs(len(text) - len(message_content)) <= 2 and len(text) >= 2:
                                continue
                            if len(text) >= 3:
                                overlap = sum(1 for c in text if c in message_content) / len(text)
                                if overlap > 0.7 and len(text) >= 4:
                                    continue
                        if re.match(r'^\d{1,2}:\d{2}$', text):
                            continue
                        if text.replace(' ', '').isdigit():
                            continue
                        if re.search(r'[（(]\s*\d+\s*[）)]', text):
                            continue
                        if '新消息' in text or '条新' in text:
                            continue
                        # 排除包含 @ 的文本
                        if '@' in text or text.startswith('\uff20'):
                            continue
                        if 1 <= len(text) <= 12:
                            # 关键检查：昵称水平位置是否与消息一致
                            # 微信布局：别人的消息在左侧，昵称也在左侧（left_x 较小）
                            #          自己的消息在右侧，上方没有昵称
                            nick_is_left = text_left_x < full_w * 0.3
                            
                            if msg_is_right:
                                # 消息在右侧（自己发的），如果昵称在左侧，说明是别人消息的昵称
                                # 不应该匹配给自己
                                if nick_is_left:
                                    logger.debug(f"扩大搜索 - 跳过左侧昵称 '{text}' (left_x={text_left_x})，因为消息在右侧")
                                    continue
                            else:
                                # 消息在左侧（别人发的），昵称也应该在左侧
                                if not nick_is_left:
                                    logger.debug(f"扩大搜索 - 跳过右侧昵称 '{text}' (left_x={text_left_x})，因为消息在左侧")
                                    continue
                            
                            all_nickname_candidates.append((text, confidence, distance, bbox))
                            logger.debug(f"扩大搜索 - 昵称候选: '{text}', 距离: {distance}px, left_x: {text_left_x}")

                if all_nickname_candidates:
                    all_nickname_candidates.sort(key=lambda x: x[2])
                    sender = all_nickname_candidates[0][0]
                    logger.info(f"扩大搜索找到发送者: {sender}")
                else:
                    logger.info("扩大搜索(500px)未找到发送者昵称")
                    # 如果消息在右侧且找不到昵称，说明是自己发的
                    if msg_is_right:
                        logger.info(f"消息在右侧且未找到昵称，识别为'自己'")
                        return "自己"

            if sender:
                return sender

            # 所有昵称查找都失败，根据消息左右位置判断是否是自己发的
            # 微信布局规则：自己消息在右侧，别人消息在左侧
            # 只有在找不到昵称时才用位置判断
            if msg_bbox:
                msg_left_x = msg_bbox[0][0]  # 左上角的 X 坐标
                msg_right_x = msg_bbox[1][0]  # 右上角的 X 坐标
                msg_center_x = (msg_left_x + msg_right_x) / 2
                msg_center_ratio = msg_center_x / full_w
                if msg_center_x > full_w * 0.5:
                    logger.info(f"未找到昵称，消息中心在右侧（center_x={msg_center_x:.1f}, ratio={msg_center_ratio:.2f} > 0.5），识别为'自己'")
                    return "自己"
                else:
                    logger.info(f"未找到昵称，消息中心在左侧（center_x={msg_center_x:.1f}, ratio={msg_center_ratio:.2f}），无法识别发送者")
                    return None
            else:
                # msg_bbox 为空，无法判断
                logger.info("未找到消息内容位置，无法识别发送者")
                return None

        except Exception as e:
            logger.debug(f"OCR识别发送者异常: {e}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            # 清理临时截图文件
            for path in temp_paths:
                _delete_screenshot(path)

            # 如果窗口原本是最小化的，OCR完成后恢复最小化
            if was_minimized and session.hwnd and win32gui.IsWindow(session.hwnd):
                try:
                    current_rect = win32gui.GetWindowRect(session.hwnd)
                    # 如果窗口当前是可见的（不在最小化位置），恢复最小化
                    if current_rect[0] >= 0 and current_rect[1] >= 0:
                        win32gui.ShowWindow(session.hwnd, win32con.SW_MINIMIZE)
                        logger.debug("OCR完成后恢复窗口最小化")
                except Exception:
                    pass

    def _is_at_me(self, group: str, content: str) -> bool:
        nickname = self.group_nicknames.get(group)
        
        # 调试：打印 nickname 的实际值
        logger.info(f"_is_at_me DEBUG: group={repr(group)}, nickname={repr(nickname)}")
        logger.info(f"_is_at_me DEBUG: content={repr(content[:100] if content else content)}")
        
        if not nickname:
            logger.warning(f"_is_at_me: 群 '{group}' 未加载群昵称，无法判断是否被@")
            return False

        # 去除 nickname 两端的空白字符（防止意外空格）
        nickname = nickname.strip()
        
        # 归一化 content 中的特殊空格字符（微信在 @昵称 后可能使用 \u2005 等不可见空格）
        normalized = content.replace("\u2005", " ").replace("\xa0", " ").replace("\u200b", "")
        
        # 同时检查半角 @ 和全角 ＠
        at_patterns = [f"@{nickname}", f"\uff20{nickname}"]
        
        for at_pattern in at_patterns:
            if at_pattern in content or at_pattern in normalized:
                logger.info(f"_is_at_me: 群 '{group}' 匹配成功: {at_pattern}")
                return True
        
        
        # 详细调试：打印 Unicode 编码
        logger.info(f"_is_at_me: 群 '{group}' 未匹配到 @{nickname}")
        logger.info(f"_is_at_me: 检查的模式: {at_patterns}")
        logger.info(f"_is_at_me: content Unicode: {' '.join([f'U+{ord(c):04X}' for c in content[:20]])}")
        return False

    def _should_send_reply(self, event: MessageEvent) -> bool:
        if not self.reply_on_at:
            return True
        return event.is_at_me

    def _update_next_scan(self, session: _ListenSession, added: int) -> None:
        now = time.time()
        if added:
            session.last_message_at = now
            session.interval = 0.3
        else:
            idle_for = now - session.last_message_at
            if idle_for >= 120:
                session.interval = 3.0
            elif idle_for >= 30:
                session.interval = 1.0
            else:
                session.interval = 0.3
        session.next_scan_at = now + session.interval

    def reply(self, group: str, content: str) -> bool:
        """立即使用对应独立窗口回复群聊。

        注意：该方法会直接操作窗口、剪贴板和焦点。自动回复默认不直接调用它，
        而是进入发送队列，由单个 sender 线程串行发送，避免多个群同时回复时
        抢占窗口。
        """
        session = self.sessions.get(group)
        if not session:
            raise ValueError(f"未监听群聊: {group}")

        if self.ignore_client_sent:
            # 先登记，再发送，避免微信回流速度快于登记速度导致漏判。
            self.outgoing_registry.record(group, content)

        sent = self._send_in_subwindow(session, content)
        return sent

    def enqueue_reply(self, group: str, content: str) -> None:
        """将回复加入串行发送队列。"""
        content = (content or "").strip()
        if not content:
            return
        self._reply_queue.put(_ReplyTask(group=group, content=content))

    def _start_sender(self) -> None:
        if self._sender_thread and self._sender_thread.is_alive():
            return
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._sender_thread.start()

    def _send_loop(self) -> None:
        """串行发送回复，避免多个窗口同时争抢焦点/剪贴板。"""
        while not self._stop_event.is_set() or not self._reply_queue.empty():
            try:
                task = self._reply_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self.reply(task.group, task.content)
            except Exception as exc:
                logger.exception(f"发送队列回复失败: {task.group}: {exc}")
            finally:
                self._reply_queue.task_done()

    def _send_in_subwindow(self, session: _ListenSession, content: str) -> bool:
        root = session.root
        edit = self._find_chat_input(root)
        if not edit:
            logger.error(f"未找到聊天输入框: {session.group}")
            return False

        return ChatWindow.send_text_via_input(
            edit,
            content,
            clipboard_error="写入回复到剪贴板失败",
            send_error=f"发送群聊回复失败: {session.group}",
            logger_override=logger,
        )

    @staticmethod
    def _find_chat_input(root):
        possible_ids = ["chat_input_field", "input_field", "msg_input", "edit_input"]
        for auto_id in possible_ids:
            try:
                edit = root.EditControl(AutomationId=auto_id)
                if edit.Exists(maxSearchSeconds=0.3):
                    return edit
            except Exception:
                continue

        candidates = []
        try:
            root_rect = root.BoundingRectangle
            for control, _depth in uia.WalkControl(root, includeTop=True, maxDepth=8):
                if _safe_text(control, "ControlTypeName") != "EditControl":
                    continue
                rect = control.BoundingRectangle
                if rect.top < root_rect.top + root_rect.height() * 0.55:
                    continue
                width = rect.right - rect.left
                if width <= 100:
                    continue
                candidates.append((width, control))
        except Exception:
            return None

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
