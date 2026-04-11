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
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple

import win32api
import win32con
import win32gui
import win32process

from . import uiautomation as uia
from ..utils.clipboard_utils import set_text_to_clipboard
from ..utils.logger import get_logger

logger = get_logger(__name__)

WECHAT_EXE_NAMES = {"wechat.exe", "weixin.exe"}
MESSAGE_CLASSES = {
    "mmui::ChatTextItemView",
    "mmui::ChatBubbleItemView",
}
TIME_CLASS = "mmui::ChatItemView"
VK_V = 0x56


@dataclass(frozen=True)
class MessageEvent:
    """监听到的新消息。"""

    group: str
    content: str
    timestamp: float
    group_nickname: Optional[str] = None
    is_at_me: bool = False
    raw: object = None


@dataclass(frozen=True)
class _VisibleItem:
    kind: str
    name: str
    class_name: str
    runtime_id: Tuple[int, ...]
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


@dataclass(frozen=True)
class _ReplyTask:
    group: str
    content: str


class OutgoingMessageRegistry:
    """记录本库发送的消息，用于监听回流时忽略一次。"""

    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl_seconds = ttl_seconds
        self._records: Deque[_OutgoingRecord] = deque()

    def record(self, group: str, content: str) -> None:
        content = (content or "").strip()
        if not content:
            return
        self._records.append(
            _OutgoingRecord(
                group=group,
                content=content,
                expires_at=time.time() + self.ttl_seconds,
            )
        )

    def should_ignore(self, group: str, content: str) -> bool:
        now = time.time()
        content = (content or "").strip()
        while self._records and self._records[0].expires_at < now:
            self._records.popleft()

        for index, record in enumerate(self._records):
            if record.group == group and record.content == content:
                del self._records[index]
                return True
        return False


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


def _find_wechat_windows() -> List[Tuple[int, str, str]]:
    windows: List[Tuple[int, str, str]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = os.path.basename(_get_process_image_name(pid)).lower()
            title = win32gui.GetWindowText(hwnd) or ""
            class_name = win32gui.GetClassName(hwnd) or ""
        except Exception:
            return True

        if exe_name in WECHAT_EXE_NAMES and win32gui.IsWindowVisible(hwnd):
            windows.append((hwnd, title, class_name))
        return True

    win32gui.EnumWindows(callback, 0)
    return windows


def _find_window_by_title(title_keyword: str, exclude_hwnd: Optional[int] = None) -> Optional[int]:
    for hwnd, title, _class_name in _find_wechat_windows():
        if hwnd == exclude_hwnd:
            continue
        if title_keyword in title:
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
        elif cls in MESSAGE_CLASSES:
            kind = "message"
        else:
            continue
        items.append(
            _VisibleItem(
                kind=kind,
                name=name,
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


def _find_session_item(root, group_name: str):
    session_list = _find_session_list(root)
    if not session_list:
        return None

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


def _send_ctrl_v() -> None:
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)


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
        self.tick = tick
        self.batch_size = batch_size
        self.tail_size = tail_size
        self.outgoing_registry = OutgoingMessageRegistry(outgoing_ttl)
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
        for group in self.groups:
            if group in self.sessions:
                continue

            chat_already_open = False
            if self.reply_on_at and not self.group_nicknames.get(group):
                chat_already_open = self._read_group_nickname(group)

            hwnd = self._ensure_subwindow(group, chat_already_open=chat_already_open)
            root = uia.ControlFromHandle(hwnd)
            msg_list = _find_message_list(root)
            if not msg_list:
                raise RuntimeError(f"未找到群聊消息列表: {group}")
            baseline = _read_visible_items(msg_list)
            self.sessions[group] = _ListenSession(
                group=group,
                hwnd=hwnd,
                root=root,
                msg_list=msg_list,
                seen={item.key for item in baseline},
            )

    def _read_group_nickname(self, group: str) -> bool:
        """读取群昵称。

        ``GroupManager.get_group_nickname`` 本身会打开目标群聊并进入详情面板。
        返回 True 表示当前主窗口大概率已经停留在该群聊，可直接双击左侧会话项
        打开独立窗口，避免再次搜索同一个群。
        """
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

    def _ensure_subwindow(self, group: str, chat_already_open: bool = False) -> int:
        main_hwnd = self.client.window.hwnd
        hwnd = _find_window_by_title(group, exclude_hwnd=main_hwnd)
        if hwnd:
            return hwnd

        if not chat_already_open:
            if not self.client.chat_window.open_chat(group, target_type="group"):
                raise RuntimeError(f"打开群聊失败: {group}")
            time.sleep(0.8)

        item = _find_session_item(self.client.window.uia.root, group)
        if not item and chat_already_open:
            logger.debug(f"当前会话项未找到，重新搜索打开群聊: {group}")
            if not self.client.chat_window.open_chat(group, target_type="group"):
                raise RuntimeError(f"打开群聊失败: {group}")
            time.sleep(0.8)
            item = _find_session_item(self.client.window.uia.root, group)

        if not item or not _double_click_control(item):
            raise RuntimeError(f"打开独立聊天窗口失败: {group}")

        deadline = time.time() + 5
        while time.time() < deadline:
            hwnd = _find_window_by_title(group, exclude_hwnd=main_hwnd)
            if hwnd:
                return hwnd
            time.sleep(0.2)
        raise RuntimeError(f"等待独立聊天窗口超时: {group}")

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
        event = MessageEvent(
            group=session.group,
            content=item.name,
            timestamp=time.time(),
            group_nickname=self.group_nicknames.get(session.group),
            is_at_me=self._is_at_me(session.group, item.name),
            raw=item.control,
        )
        try:
            reply = self.on_message(event)
        except Exception as exc:
            logger.exception(f"消息回调执行失败: {session.group}: {exc}")
            return

        if self.auto_reply and reply and self._should_send_reply(event):
            self.enqueue_reply(session.group, str(reply))

    def _is_at_me(self, group: str, content: str) -> bool:
        nickname = self.group_nicknames.get(group)
        if not nickname:
            return False
        return f"@{nickname}" in content or f"@{nickname}\u2005" in content

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

        sent = self._send_in_subwindow(session, content)
        if sent and self.ignore_client_sent:
            self.outgoing_registry.record(group, content)
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

        try:
            try:
                edit.Click(simulateMove=False)
            except Exception:
                edit.SetFocus()
            time.sleep(0.1)
            edit.SendKeys("{Ctrl}a")
            time.sleep(0.05)
            edit.SendKeys("{Delete}")
            time.sleep(0.05)
        except Exception:
            pass

        if not set_text_to_clipboard(content):
            logger.error("写入回复到剪贴板失败")
            return False

        try:
            _send_ctrl_v()
            time.sleep(0.1)
            edit.SendKeys("{Enter}")
            time.sleep(0.2)
            return True
        except Exception as exc:
            logger.error(f"发送群聊回复失败: {session.group}: {exc}")
            return False

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
