# -*- coding: utf-8 -*-
"""Chat window page for WeChat"""
import hashlib
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional

import win32api
import win32con

from .base import BasePage
from ..core.exceptions import ControlNotFoundError, TargetNotFoundError
from ..config import (
    ALLOWED_GROUPS,
    BATCH_SEND_INTERVAL_MAX,
    BATCH_SEND_INTERVAL_MIN,
    OPERATION_INTERVAL,
    SEARCH_RETRY_COUNT,
    SEARCH_RETRY_DELAY_MAX,
    SEARCH_RETRY_DELAY_MIN,
    SEARCH_TIMEOUT,
    SEND_DEDUP_WINDOW_SECONDS,
    SEND_JITTER_MAX,
    SEND_JITTER_MIN,
    SEND_RECONNECT_RETRY_COUNT,
    SEND_RETRY_COUNT,
)
from ..utils.clipboard_utils import set_files_to_clipboard, set_text_to_clipboard
from ..utils.logger import get_logger, log_send_audit

logger = get_logger(__name__)
VK_V = 0x56


# Search result group names
GROUP_CONTACTS = '联系人'
GROUP_CHATS = '群聊'
GROUP_FUNCTIONS = '功能'
GROUP_NETWORK = '搜索网络结果'
GROUP_HISTORY = '聊天记录'

ALL_GROUP_NAMES = [GROUP_CONTACTS, GROUP_CHATS, GROUP_FUNCTIONS, GROUP_NETWORK, GROUP_HISTORY]


@dataclass
class SearchResult:
    """Search result item"""
    name: str
    ctrl: object  # UIAutomation control
    item_type: str  # 'contact', 'function', 'network'
    auto_id: str
    group: str


@dataclass(frozen=True)
class SendRequest:
    """Normalized send request payload."""
    target: str
    message: str
    target_type: str


@dataclass(frozen=True)
class ChatHistoryRange:
    """Timestamp matching rules for chat history collection."""
    in_range_prefixes: Optional[set[str]]
    too_new_prefixes: set[str]


class ChatWindow(BasePage):
    """
    Chat window page for sending messages.

    Usage:
        wx = WeChatClient()
        wx.connect()

        # Send to contact
        wx.chat_window.send_to("大号", "Hello!")

        # Send to group
        wx.chat_window.send_to("测试群", "Hello!", target_type='group')

        # Batch send
        wx.chat_window.batch_send(["群1", "群2"], "Hello!")
    """

    def __init__(self, window):
        super().__init__(window)
        self._last_search_results: Dict[str, List[SearchResult]] = {}
        self._run_id = str(uuid.uuid4())
        self._recent_send_records: Dict[str, float] = {}

    # ==================== Private Methods ====================

    def _sleep_with_jitter(self, minimum: float, maximum: float) -> float:
        """Sleep for a random duration inside the given range."""
        delay = random.uniform(minimum, maximum)
        time.sleep(delay)
        return delay

    def _log_send_phase(
        self,
        target: str,
        attempt: int,
        phase: str,
        success: bool,
        started_at: float,
        exception: Optional[Exception] = None,
    ) -> None:
        """Write structured send audit log."""
        payload = {
            "run_id": self._run_id,
            "target": target,
            "attempt": attempt,
            "phase": phase,
            "success": success,
            "exception_type": type(exception).__name__ if exception else "",
            "exception_msg": str(exception) if exception else "",
            "elapsed_ms": int((time.time() - started_at) * 1000),
        }
        log_send_audit(payload)

    def _normalize_target(self, target: str, target_type: str) -> str:
        """Validate and normalize target."""
        normalized_target = (target or "").strip()
        if not normalized_target:
            raise ValueError("target must not be empty")
        if target_type == "group" and ALLOWED_GROUPS and normalized_target not in ALLOWED_GROUPS:
            raise ValueError(
                f"group '{normalized_target}' is not in WECHAT_ALLOWED_GROUPS"
            )
        return normalized_target

    def _normalize_message(self, message: str) -> str:
        """Validate and normalize message."""
        normalized_message = (message or "").strip()
        if not normalized_message:
            raise ValueError("message must not be empty")
        return normalized_message

    def _normalize_send_args(
        self, target: str, message: str, target_type: str
    ) -> SendRequest:
        """Validate and normalize send arguments."""
        if target_type not in ("contact", "group"):
            raise ValueError("target_type must be 'contact' or 'group'")

        return SendRequest(
            target=self._normalize_target(target, target_type),
            message=self._normalize_message(message),
            target_type=target_type,
        )

    def _make_send_record_key(self, target: str, message: str) -> str:
        """Build deduplication key for a send operation."""
        content_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
        return f"{target}:{content_hash}"

    def _was_sent_recently(self, target: str, message: str) -> bool:
        """Check whether the same content was sent recently."""
        key = self._make_send_record_key(target, message)
        sent_at = self._recent_send_records.get(key)
        if not sent_at:
            return False
        return (time.time() - sent_at) <= SEND_DEDUP_WINDOW_SECONDS

    def _remember_successful_send(self, target: str, message: str) -> None:
        """Remember a successful send for duplicate suppression."""
        now = time.time()
        cutoff = now - SEND_DEDUP_WINDOW_SECONDS
        self._recent_send_records = {
            key: ts for key, ts in self._recent_send_records.items() if ts >= cutoff
        }
        self._recent_send_records[self._make_send_record_key(target, message)] = now

    def _send_ctrl_hotkey(self, key_code: int) -> None:
        """Press Ctrl+<key> once via Win32 for more stable text paste."""
        import win32api
        import win32con

        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(key_code, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(key_code, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _rebuild_uia_session(self) -> bool:
        """Reconnect UIA session and recover window focus."""
        logger.warning("Rebuilding WeChat UIA session")
        return self._window.refresh()

    def _sleep_between_batch_targets(self) -> None:
        """Sleep between batch targets to reduce UI contention."""
        time.sleep(random.uniform(BATCH_SEND_INTERVAL_MIN, BATCH_SEND_INTERVAL_MAX))

    def _sleep_before_send_attempt(self) -> None:
        """Sleep briefly before each send attempt."""
        self._sleep_with_jitter(SEND_JITTER_MIN, SEND_JITTER_MAX)

    def _sleep_before_send_retry(self) -> None:
        """Sleep briefly before retrying after a failed attempt."""
        self._sleep_with_jitter(SEARCH_RETRY_DELAY_MIN, SEARCH_RETRY_DELAY_MAX)

    def _find_target_result(
        self, results: Dict[str, List[SearchResult]], target: str, target_type: str
    ) -> Optional[SearchResult]:
        """Find the matching search result for the target."""
        primary_group = GROUP_CHATS if target_type == 'group' else GROUP_CONTACTS

        for item in results.get(primary_group, []):
            if target in item.name:
                return item

        if target_type == 'contact':
            for item in results.get(GROUP_FUNCTIONS, []):
                if target in item.name:
                    return item

        return None

    def _prepare_chat_input_for_paste(self):
        """Focus and clear the chat input before pasting content."""
        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("Chat input not found")
            return None

        chat_input.Click()
        time.sleep(OPERATION_INTERVAL)
        chat_input.SendKeys('{Ctrl}a')
        chat_input.SendKeys('{Delete}')
        time.sleep(OPERATION_INTERVAL)
        return chat_input

    def _paste_text_into_chat_input(self, text: str, log_error: str = "Failed to write message to clipboard") -> bool:
        """Paste text into the currently focused chat input via clipboard."""
        if not set_text_to_clipboard(text):
            logger.error(log_error)
            return False

        self._send_ctrl_hotkey(VK_V)
        time.sleep(OPERATION_INTERVAL)
        return True

    def _run_send_phase(
        self,
        request: SendRequest,
        attempt: int,
        phase: str,
        action: Callable[[], bool],
        error_message: str,
    ) -> bool:
        """Execute one send phase and write audit logs."""
        started_at = time.time()
        try:
            if not action():
                raise ControlNotFoundError(error_message)
        except Exception as exc:
            self._log_send_phase(
                request.target,
                attempt,
                phase,
                False,
                started_at,
                exc,
            )
            raise

        self._log_send_phase(request.target, attempt, phase, True, started_at)
        return True

    def _send_once(self, request: SendRequest, attempt: int) -> bool:
        """Run one full send attempt."""
        self._sleep_before_send_attempt()

        try:
            self._run_send_phase(
                request,
                attempt,
                "open",
                lambda: self._open_chat_with_status(
                    request.target, request.target_type
                ),
                "failed to open chat",
            )
            self._run_send_phase(
                request,
                attempt,
                "send",
                lambda: self.send_message(request.message),
                "failed to send message",
            )
        except TargetNotFoundError as exc:
            logger.warning(
                f"Send aborted for '{request.target}' ({attempt}): {exc}"
            )
            raise
        except Exception as exc:
            logger.warning(
                f"Send attempt failed for '{request.target}' ({attempt}): {exc}"
            )
            return False

        self._remember_successful_send(request.target, request.message)
        return True

    def _send_with_retry_range(
        self, request: SendRequest, attempts: range
    ) -> bool:
        """Run a range of send attempts against the current UIA session."""
        attempt_list = list(attempts)

        for index, attempt in enumerate(attempt_list):
            if self._send_once(request, attempt):
                return True
            if index < len(attempt_list) - 1:
                self._sleep_before_send_retry()

        return False

    def _send_with_reconnect_fallback(self, request: SendRequest) -> bool:
        """Run normal send retries, then rebuild the UIA session and retry once more."""
        initial_attempts = range(1, SEND_RETRY_COUNT + 1)
        if self._send_with_retry_range(request, initial_attempts):
            return True

        if SEND_RECONNECT_RETRY_COUNT <= 0:
            return False

        self._rebuild_uia_session()
        reconnect_attempts = range(
            SEND_RETRY_COUNT + 1,
            SEND_RETRY_COUNT + SEND_RECONNECT_RETRY_COUNT + 1,
        )
        return self._send_with_retry_range(request, reconnect_attempts)

    def _open_chat_with_status(self, target: str, target_type: str = 'contact') -> bool:
        """Open chat and preserve TargetNotFoundError for send workflow control."""
        return self.open_chat(target, target_type, raise_on_target_not_found=True)

    def _get_search_edit(self, retries: int = SEARCH_RETRY_COUNT):
        """Get main search box control (not the one in group detail panel)."""

        def find_edits(ctrl, results):
            try:
                if ctrl.ControlTypeName == 'EditControl':
                    # Different WeChat builds may use different class names for search box.
                    if ctrl.ClassName in ('mmui::XValidatorTextEdit', 'mmui::XTextEdit') or (ctrl.Name or '').find('搜索') >= 0:
                        results.append(ctrl)
                for child in ctrl.GetChildren():
                    find_edits(child, results)
            except Exception:
                # Ignore transient UIA traversal errors
                return

        for attempt in range(1, retries + 1):
            edits = []
            find_edits(self.root, edits)

            for edit in edits:
                # Some builds may not expose Name='搜索' consistently; allow blank name as fallback.
                if edit.Name not in ('搜索', ''):
                    continue

                # Check if this is in group detail panel (ChatRoomMemberInfoView)
                parent = edit.GetParentControl()
                grandparent = parent.GetParentControl() if parent else None

                if grandparent and 'ChatRoomMemberInfoView' in (grandparent.ClassName or ''):
                    # This is "搜索群成员" in group detail panel
                    # Close the panel first
                    logger.debug("Group detail panel is open, closing...")
                    edit.SendKeys('{Esc}')
                    time.sleep(0.5)
                    continue

                # This is likely the main search box
                if edit.Exists(maxSearchSeconds=1):
                    return edit

            # Recovery between attempts: try returning to main surface and refocus window
            try:
                self.root.SendKeys('{Esc}')
                time.sleep(0.2)
                self.root.SendKeys('{Esc}')
                time.sleep(0.2)
                # Force-open global search in some builds where search box is lazily created
                self.root.SendKeys('{Ctrl}f')
            except Exception:
                pass
            self._window.activate()
            time.sleep(0.5)
            logger.debug(f"Search box not found, retrying ({attempt}/{retries})")

        logger.warning("Search box not found")
        return None

    def _get_chat_input(self):
        """Get chat input field"""
        edit = self.root.EditControl(AutomationId='chat_input_field')
        return edit if edit.Exists(maxSearchSeconds=SEARCH_TIMEOUT) else None

    def _get_search_popup(self):
        """Get search popup window"""
        popup = self.root.WindowControl(ClassName='mmui::SearchContentPopover')
        return popup if popup.Exists(maxSearchSeconds=SEARCH_TIMEOUT) else None

    def _parse_search_results(self, items) -> Dict[str, List[SearchResult]]:
        """
        Parse search results into groups.

        Args:
            items: List items from search list

        Returns:
            Dict mapping group name to list of SearchResult
        """
        groups: Dict[str, List[SearchResult]] = {}
        current_group: Optional[str] = None

        for item in items:
            class_name = item.ClassName or ""
            name = item.Name or ""
            auto_id = item.AutomationId or ""

            # Group header: XTableCell without AutoId
            if class_name == 'mmui::XTableCell' and not auto_id:
                if name in ALL_GROUP_NAMES:
                    current_group = name
                    groups[current_group] = []
                    logger.debug(f"Found group: {name}")
                    continue
                elif '查看全部' in name:
                    # Skip "查看全部" button
                    continue
                else:
                    # Network search result item
                    if current_group == GROUP_NETWORK:
                        result = SearchResult(
                            name=name,
                            ctrl=item,
                            item_type='network',
                            auto_id='',
                            group=GROUP_NETWORK
                        )
                        groups.setdefault(GROUP_NETWORK, []).append(result)
                    continue

            # Function item: XTableCell with search_item_function AutoId
            if auto_id.startswith('search_item_function'):
                result = SearchResult(
                    name=name,
                    ctrl=item,
                    item_type='function',
                    auto_id=auto_id,
                    group=GROUP_FUNCTIONS
                )
                groups.setdefault(GROUP_FUNCTIONS, []).append(result)
                logger.debug(f"Found function item: {name}")
                continue

            # Contact/Chat item: SearchContentCellView with AutoId
            if 'SearchContentCellView' in class_name:
                if auto_id.startswith('search_item_'):
                    # Contact or group chat
                    result = SearchResult(
                        name=name,
                        ctrl=item,
                        item_type='contact',
                        auto_id=auto_id,
                        group=current_group or '未知'
                    )
                    groups.setdefault(current_group or '未知', []).append(result)
                    logger.debug(f"Found contact item: {name} in {current_group}")

        return groups

    def _input_search(self, keyword: str) -> bool:
        """
        Input search keyword.

        Args:
            keyword: Search keyword

        Returns:
            bool: True if successful
        """
        search_edit = self._get_search_edit(retries=SEARCH_RETRY_COUNT)
        if not search_edit:
            logger.error("Search box not found")
            return False

        search_edit.Click()
        time.sleep(OPERATION_INTERVAL)
        search_edit.SendKeys('{Ctrl}a')
        search_edit.SendKeys('{Delete}')
        search_edit.SendKeys(keyword)
        time.sleep(1.5)  # Wait for results

        return True

    def _clear_search(self):
        """Clear search input"""
        search_edit = self._get_search_edit()
        if search_edit:
            search_edit.SendKeys('{Esc}')

    # ==================== Public Methods ====================

    def search(self, keyword: str) -> Dict[str, List[SearchResult]]:
        """
        Search and return all results grouped.

        Args:
            keyword: Search keyword

        Returns:
            Dict mapping group name to list of SearchResult
        """
        logger.info(f"Searching: {keyword}")

        if not self._input_search(keyword):
            return {}

        popup = self._get_search_popup()
        if not popup:
            logger.warning("Search popup not found")
            return {}

        search_list = popup.ListControl(AutomationId='search_list')
        if not search_list.Exists():
            logger.warning("Search list not found")
            return {}

        items = search_list.GetChildren()
        results = self._parse_search_results(items)
        self._last_search_results = results

        # Log results
        for group, items in results.items():
            logger.debug(f"Group '{group}': {len(items)} items")

        return results

    def _open_chat_once(self, target: str, target_type: str = 'contact') -> bool:
        """Single attempt to search and open a chat."""
        group_name = GROUP_CHATS if target_type == 'group' else GROUP_CONTACTS
        logger.info(f"Opening chat: {target} (type: {target_type})")

        results = self.search(target)
        target_result = self._find_target_result(results, target, target_type)

        if not target_result:
            self._clear_search()
            raise TargetNotFoundError(f"'{target}' not found in '{group_name}' group")

        logger.debug(f"Clicking: {target_result.name}")
        target_result.ctrl.Click()
        time.sleep(1)

        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("Chat input not found after opening chat")
            return False

        logger.info(f"Chat opened: {target}")
        return True

    def open_chat(
        self,
        target: str,
        target_type: str = 'contact',
        raise_on_target_not_found: bool = False,
    ) -> bool:
        """
        Search and open chat with target.

        Args:
            target: Contact or group name
            target_type: 'contact' or 'group'
            raise_on_target_not_found: If True, preserve TargetNotFoundError for
                callers that need to distinguish a missing target from transient
                UI failures.

        Returns:
            bool: True if successful
        """
        for attempt in range(1, SEARCH_RETRY_COUNT + 1):
            try:
                if self._open_chat_once(target, target_type):
                    return True
            except TargetNotFoundError:
                if raise_on_target_not_found:
                    raise
                logger.error(f"Target chat not found: '{target}'")
                return False

            self._clear_search()
            self._window.activate()
            delay = self._sleep_with_jitter(
                SEARCH_RETRY_DELAY_MIN, SEARCH_RETRY_DELAY_MAX
            )
            logger.debug(
                f"Open chat retry scheduled for '{target}' "
                f"({attempt}/{SEARCH_RETRY_COUNT}, slept {delay:.2f}s)"
            )

        logger.error(f"Failed to open chat after retries: {target}")
        self._clear_search()
        return False

    def send_message(self, message: str) -> bool:
        """
        Send message in current chat.

        Args:
            message: Message to send

        Returns:
            bool: True if successful
        """
        logger.info(f"Sending message: {message[:20]}...")

        chat_input = self._prepare_chat_input_for_paste()
        if not chat_input:
            return False

        if not self._paste_text_into_chat_input(message):
            return False

        chat_input.SendKeys('{Enter}')
        time.sleep(OPERATION_INTERVAL)

        logger.info("Message sent")
        return True

    def send_to(self, target: str, message: str, target_type: str = 'contact') -> bool:
        """
        Open chat and send message.

        Args:
            target: Contact or group name
            message: Message to send
            target_type: 'contact' or 'group'

        Returns:
            bool: True if successful
        """
        request = self._normalize_send_args(target, message, target_type)

        if self._was_sent_recently(request.target, request.message):
            logger.warning(
                f"Skipping duplicate send within {SEND_DEDUP_WINDOW_SECONDS}s: {request.target}"
            )
            return True

        try:
            if self._send_with_reconnect_fallback(request):
                return True
        except TargetNotFoundError:
            logger.error(f"Target chat not found: '{request.target}'")
            return False

        logger.error(f"Failed to send message to '{request.target}' after retries")
        return False

    def batch_send(self, targets: List[str], message: str, target_type: str = 'group') -> Dict[str, bool]:
        """

        Send message to multiple targets.

        Args:
            targets: List of contact or group names
            message: Message to send
            target_type: 'contact' or 'group'

        Returns:
            Dict mapping target name to success status
        """
        logger.info(f"Batch sending to {len(targets)} targets")

        normalized_message = self._normalize_message(message)

        results = {}
        for target in targets:
            success = self.send_to(target, normalized_message, target_type)
            results[target] = success
            self._sleep_between_batch_targets()

        # Summary
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"Batch send complete: {success_count}/{len(targets)} successful")

        return results

    @property
    def last_search_results(self) -> Dict[str, List[SearchResult]]:
        """Get last search results"""
        return self._last_search_results

    def send_file(self, file_path, message: str = None) -> bool:
        """
        Send file in current chat.

        Args:
            file_path: Path to file (or list of paths)
            message: Optional message to send with the file

        Returns:
            bool: True if successful
        """
        logger.info(f"Sending file: {file_path}")

        chat_input = self._prepare_chat_input_for_paste()
        if not chat_input:
            return False

        if not self._set_files_to_clipboard(file_path):
            return False

        time.sleep(0.2)

        self._send_ctrl_hotkey(VK_V)
        time.sleep(0.5)

        # Add message if provided
        normalized_message = self._normalize_message(message) if message is not None else ""
        if normalized_message:
            if not self._paste_text_into_chat_input(
                normalized_message,
                log_error="Failed to write file message to clipboard",
            ):
                return False

        # Press Enter to send
        chat_input.SendKeys('{Enter}')
        time.sleep(0.5)

        logger.info("File sent")
        return True

    def _set_files_to_clipboard(self, file_path) -> bool:
        """Set file paths to clipboard and surface failures consistently."""
        try:
            copied = set_files_to_clipboard(file_path)
        except ValueError as exc:
            logger.error(str(exc))
            return False

        if not copied:
            logger.error("Failed to copy file paths to clipboard")
            return False

        return True

    def send_file_to(self, target: str, file_path, target_type: str = 'contact', message: str = None) -> bool:
        """
        Open chat and send file.

        Args:
            target: Contact or group name
            file_path: Path to file (or list of paths)
            target_type: 'contact' or 'group'
            message: Optional message to send with the file

        Returns:
            bool: True if successful
        """
        if not self.open_chat(target, target_type):
            return False
        return self.send_file(file_path, message)

    def _get_chat_history_range(self, since: str) -> ChatHistoryRange:
        """Resolve timestamp prefix rules for a chat history query."""
        range_in = {
            'today': {'今天'},
            'yesterday': {'昨天'},
            'week': {'今天', '昨天', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'},
            'all': None,
        }
        range_too_new = {
            'today': set(),
            'yesterday': {'今天'},
            'week': set(),
            'all': set(),
        }
        return ChatHistoryRange(
            in_range_prefixes=range_in.get(since, range_in['today']),
            too_new_prefixes=range_too_new.get(since, set()),
        )

    def _normalize_history_timestamp(self, ts: str, today: date, yesterday: date) -> str:
        """Normalize long-form timestamps to the short prefixes used by range filters."""
        if re.match(r'^\d{1,2}:\d{2}', ts):
            return '今天'

        match = re.match(r'^(\d{1,2})月(\d{1,2})日', ts)
        if not match:
            return ts

        month, day = int(match.group(1)), int(match.group(2))
        try:
            normalized_date = date(today.year, month, day)
        except ValueError:
            return ts

        if normalized_date == today:
            return '今天'
        if normalized_date == yesterday:
            return '昨天'

        weekday_map = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
        return weekday_map[normalized_date.weekday()]

    def _get_history_timestamp_state(
        self,
        ts: str,
        history_range: ChatHistoryRange,
        today: date,
        yesterday: date,
    ) -> str:
        """Return whether a timestamp is in range, newer than range, or too old."""
        if not ts or history_range.in_range_prefixes is None:
            return 'in_range'

        effective = self._normalize_history_timestamp(ts, today, yesterday)
        if any(effective.startswith(prefix) for prefix in history_range.too_new_prefixes):
            return 'too_new'
        if any(effective.startswith(prefix) for prefix in history_range.in_range_prefixes):
            return 'in_range'
        return 'too_old'

    def _get_chat_message_list(self):
        """Get the chat message list control if available."""
        msg_list = self.root.ListControl(AutomationId='chat_message_list')
        if not msg_list.Exists(maxSearchSeconds=2):
            logger.error("chat_message_list not found")
            return None
        return msg_list

    def _get_message_list_center(self, msg_list) -> tuple[int, int]:
        """Return the center point of the message list for wheel scrolling."""
        rect = msg_list.BoundingRectangle
        return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2

    def _read_visible_chat_items(self, msg_list) -> list[tuple[str, str]]:
        """Read visible timestamp and message items from the current chat view."""
        time_cls = 'mmui::ChatItemView'
        msg_types = {'mmui::ChatTextItemView', 'mmui::ChatBubbleItemView'}
        time_re = re.compile(r'^(今天|昨天|星期[一二三四五六日]|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{4}年|\d{1,2}:\d{2})')

        items = []
        try:
            for child in msg_list.GetChildren():
                cls = child.ClassName or ""
                name = child.Name or ""
                if cls == time_cls:
                    kind = 'time' if time_re.match(name) else 'system'
                    items.append((kind, name))
                elif cls in msg_types:
                    kind = 'text' if 'Text' in cls else 'link'
                    items.append((kind, name))
        except Exception:
            return []
        return items

    def _scroll_message_list(self, cx: int, cy: int, delta: int, steps: int, step_delay: float, settle_time: float) -> None:
        """Scroll the message list with consistent cursor placement and timing."""
        win32api.SetCursorPos((cx, cy))
        for _ in range(steps):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
            time.sleep(step_delay)
        time.sleep(settle_time)

    def _scroll_message_list_to_bottom(self, msg_list, cx: int, cy: int) -> None:
        """Scroll to the newest visible messages before collecting history."""
        logger.debug("Scrolling to bottom...")
        previous_bottom = None
        stuck_count = 0
        while stuck_count < 3:
            try:
                children = list(msg_list.GetChildren())
                current_bottom = (children[-1].Name or '') if children else ''
            except Exception:
                current_bottom = ''

            if current_bottom == previous_bottom:
                stuck_count += 1
            else:
                stuck_count = 0

            previous_bottom = current_bottom
            self._scroll_message_list(cx, cy, delta=-360, steps=5, step_delay=0.05, settle_time=0.4)

        logger.debug("Reached bottom, starting upward collection.")
        time.sleep(0.3)

    def get_chat_history(self, target: str, target_type: str = 'contact',
                         since: str = 'today', max_count: int = 500) -> list:
        """
        Get chat history for a contact or group.

        Scrolls up until messages older than `since` are reached, then stops.
        Returns messages in chronological order (oldest first) as JSON-serialisable dicts.

        Each item:
            {
                'type':    'text' | 'link' | 'system',
                'content': str,    # full message text
                'time':    str,    # timestamp label attached to this message
            }

        Args:
            target:      Contact or group name
            target_type: 'contact' or 'group'
            since:       Date range to collect.
                         'today'     – only today's messages
                         'yesterday' – only yesterday's messages
                         'week'      – since 星期X (this week)
                         'all'       – keep scrolling until no new messages appear
            max_count:   Hard limit on number of messages returned (safety cap)

        Limitations:
            Sender names are not exposed by WeChat's Qt UIA provider.

        Returns:
            list[dict]
        """
        history_range = self._get_chat_history_range(since)
        today = date.today()
        yesterday = today - timedelta(days=1)

        if not self.open_chat(target, target_type):
            logger.error(f"Failed to open chat: {target}")
            return []
        time.sleep(1)

        msg_list = self._get_chat_message_list()
        if not msg_list:
            return []

        cx, cy = self._get_message_list_center(msg_list)

        # collected newest-first while scrolling; reversed at the end
        collected:   list = []
        seen_keys:   set  = set()   # (time_label, content) to deduplicate
        current_ts:  str  = ""
        prev_top:    str  = None    # content of first visible item, scroll-position indicator
        stuck_count: int  = 0

        # Focus the list without clicking (click would trigger image/link items)
        msg_list.SetFocus()
        time.sleep(0.3)

        # Scroll to bottom first so we always start from the newest messages
        self._scroll_message_list_to_bottom(msg_list, cx, cy)

        stop_reason = ''
        while True:
            batch = self._read_visible_chat_items(msg_list)
            stop_now = False

            # Detect scroll progress by the first visible item changing
            top_item = batch[0][1] if batch else ''
            if top_item == prev_top:
                stuck_count += 1
            else:
                stuck_count = 0
            prev_top = top_item

            # Process the batch — iterate top-to-bottom (oldest first in view)
            for kind, name in batch:
                if kind == 'time':
                    current_ts = name
                    state = self._get_history_timestamp_state(
                        current_ts,
                        history_range,
                        today,
                        yesterday,
                    )
                    if state == 'too_old':
                        stop_now = True
                        break
                    continue   # too_new or in_range: update ts, keep going

                state = self._get_history_timestamp_state(
                    current_ts,
                    history_range,
                    today,
                    yesterday,
                )
                if state == 'too_old':
                    stop_now = True
                    break
                if state == 'too_new':
                    continue   # skip messages newer than target range

                key = (current_ts, name)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                collected.append({
                    'type':    kind,
                    'content': name,
                    'time':    current_ts,
                })

            msg_count = len(collected)
            logger.debug(
                f"  scroll: total={msg_count}, ts='{current_ts}', "
                f"top='{top_item[:30]}', stuck={stuck_count}"
            )

            if stop_now:
                stop_reason = f"hit older timestamp '{current_ts}' (since='{since}')"
                break
            if msg_count >= max_count:
                stop_reason = f"hit max_count={max_count}"
                break
            if stuck_count >= 5:
                stop_reason = "reached top (first visible item unchanged after 5 scrolls)"
                break

            self._scroll_message_list(cx, cy, delta=360, steps=5, step_delay=0.1, settle_time=0.8)

        logger.info(
            f"get_chat_history: {len(collected)} items from '{target}' "
            f"(since='{since}', stop='{stop_reason}')"
        )

        collected.reverse()   # oldest first
        return collected
