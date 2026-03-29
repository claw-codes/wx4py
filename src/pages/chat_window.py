# -*- coding: utf-8 -*-
"""Chat window page for WeChat"""
import time
from typing import List, Dict, Optional
from dataclasses import dataclass

from .base import BasePage
from ..core.exceptions import ControlNotFoundError
from ..config import SEARCH_TIMEOUT, OPERATION_INTERVAL
from ..utils.logger import get_logger

logger = get_logger(__name__)


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

    # ==================== Private Methods ====================

    def _get_search_edit(self, retries: int = 3):
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
        search_edit = self._get_search_edit(retries=3)
        if not search_edit:
            logger.error("Search box not found")
            return False

        search_edit.Click()
        time.sleep(OPERATION_INTERVAL)
        search_edit.SendKeys('{Ctrl}a')
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

    def open_chat(self, target: str, target_type: str = 'contact') -> bool:
        """
        Search and open chat with target.

        Args:
            target: Contact or group name
            target_type: 'contact' or 'group'

        Returns:
            bool: True if successful
        """
        group_name = GROUP_CHATS if target_type == 'group' else GROUP_CONTACTS
        logger.info(f"Opening chat: {target} (type: {target_type})")

        target_result = None

        # Search with one retry to absorb transient UIA state (e.g. focus/panel glitch)
        for attempt in range(1, 3):
            results = self.search(target)

            # Find in correct group
            group_items = results.get(group_name, [])
            target_result = None

            for item in group_items:
                if target in item.name:
                    target_result = item
                    break

            # If not found in expected group, try FUNCTIONS group (for File Transfer Helper etc.)
            if not target_result and target_type == 'contact':
                func_items = results.get(GROUP_FUNCTIONS, [])
                for item in func_items:
                    if target in item.name:
                        target_result = item
                        break

            if target_result:
                break

            logger.warning(
                f"'{target}' not found in '{group_name}' group (attempt {attempt}/2)"
            )
            self._clear_search()
            self._window.activate()
            time.sleep(0.8)

        if not target_result:
            logger.error(f"'{target}' not found in '{group_name}' group")
            self._clear_search()
            return False

        # Click to open chat
        logger.debug(f"Clicking: {target_result.name}")
        target_result.ctrl.Click()
        time.sleep(1)

        # Verify chat input exists
        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("Chat input not found after opening chat")
            return False

        logger.info(f"Chat opened: {target}")
        return True

    def send_message(self, message: str) -> bool:
        """
        Send message in current chat.

        Args:
            message: Message to send

        Returns:
            bool: True if successful
        """
        logger.info(f"Sending message: {message[:20]}...")

        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("Chat input not found")
            return False

        chat_input.Click()
        time.sleep(OPERATION_INTERVAL)
        chat_input.SendKeys('{Ctrl}a')
        chat_input.SendKeys(message)
        time.sleep(OPERATION_INTERVAL)
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
        if not self.open_chat(target, target_type):
            return False
        return self.send_message(message)

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

        results = {}
        for target in targets:
            success = self.send_to(target, message, target_type)
            results[target] = success
            if success:
                time.sleep(1)  # Interval between sends

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
        import win32api
        import win32con
        from ..utils.clipboard_utils import set_files_to_clipboard

        logger.info(f"Sending file: {file_path}")

        # Get chat input
        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("Chat input not found")
            return False

        # Click to focus
        chat_input.Click()
        time.sleep(0.3)

        # Set files to clipboard
        try:
            set_files_to_clipboard(file_path)
        except ValueError as e:
            logger.error(str(e))
            return False

        time.sleep(0.2)

        # Paste with Ctrl+V
        VK_V = 0x56
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)

        # Add message if provided
        if message:
            chat_input.SendKeys(message)
            time.sleep(0.3)

        # Press Enter to send
        chat_input.SendKeys('{Enter}')
        time.sleep(0.5)

        logger.info("File sent")
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
        import re
        import win32api
        import win32con
        from datetime import date, timedelta

        _TIME_CLS  = 'mmui::ChatItemView'
        _MSG_TYPES = {'mmui::ChatTextItemView', 'mmui::ChatBubbleItemView'}
        # Matches both short and long timestamp prefixes
        _TIME_RE   = re.compile(
            r'^(今天|昨天|星期[一二三四五六日]|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{4}年|\d{1,2}:\d{2})'
        )

        # Each since value defines:
        #   in_range  prefixes → collect messages with these timestamps
        #   too_old   prefixes → stop scrolling when seen (older than target)
        #   too_new   prefixes → skip but keep scrolling (newer than target)
        #
        # Recency order: 今天 > 昨天 > 星期X > MM/DD date > YYYY年 date
        _RANGE_IN = {
            'today':     {'今天'},
            'yesterday': {'昨天'},
            'week':      {'今天', '昨天', '星期一', '星期二', '星期三',
                          '星期四', '星期五', '星期六', '星期日'},
            'all':       None,
        }
        _RANGE_TOO_NEW = {
            'today':     set(),
            'yesterday': {'今天'},
            'week':      set(),
            'all':       set(),
        }

        in_range_prefixes  = _RANGE_IN.get(since, _RANGE_IN['today'])
        too_new_prefixes   = _RANGE_TOO_NEW.get(since, set())

        _BARE_TIME_RE = re.compile(r'^\d{1,2}:\d{2}')
        _MDAY_RE      = re.compile(r'^(\d{1,2})月(\d{1,2})日')

        _today     = date.today()
        _yesterday = _today - timedelta(days=1)

        _WEEKDAY_MAP = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']

        def _normalize_ts(ts: str) -> str:
            """
            Normalize long-form 'M月D日 星期X HH:MM' to its short-form prefix
            so range logic can treat both formats identically.
            """
            # Bare HH:MM → 今天
            if _BARE_TIME_RE.match(ts):
                return '今天'
            # Long form: e.g. "3月27日 星期五 11:59"
            m = _MDAY_RE.match(ts)
            if m:
                month, day = int(m.group(1)), int(m.group(2))
                try:
                    d = date(_today.year, month, day)
                except ValueError:
                    return ts
                if d == _today:
                    return '今天'
                if d == _yesterday:
                    return '昨天'
                # Within this week: return 星期X
                return _WEEKDAY_MAP[d.weekday()]
            return ts

        def _ts_state(ts: str) -> str:
            """Return 'in_range', 'too_new', or 'too_old'."""
            if not ts:
                return 'in_range'
            if in_range_prefixes is None:
                return 'in_range'
            effective = _normalize_ts(ts)
            if any(effective.startswith(p) for p in too_new_prefixes):
                return 'too_new'
            if any(effective.startswith(p) for p in in_range_prefixes):
                return 'in_range'
            return 'too_old'

        if not self.open_chat(target, target_type):
            logger.error(f"Failed to open chat: {target}")
            return []
        time.sleep(1)

        msg_list = self.root.ListControl(AutomationId='chat_message_list')
        if not msg_list.Exists(maxSearchSeconds=2):
            logger.error("chat_message_list not found")
            return []

        rect = msg_list.BoundingRectangle
        cx   = (rect.left + rect.right) // 2
        cy   = (rect.top  + rect.bottom) // 2

        # collected newest-first while scrolling; reversed at the end
        collected:   list = []
        seen_keys:   set  = set()   # (time_label, content) to deduplicate
        current_ts:  str  = ""
        prev_top:    str  = None    # content of first visible item, scroll-position indicator
        stuck_count: int  = 0

        def _read_visible():
            items = []
            try:
                for child in msg_list.GetChildren():
                    cls  = child.ClassName or ""
                    name = child.Name or ""
                    if cls == _TIME_CLS:
                        kind = 'time' if _TIME_RE.match(name) else 'system'
                        items.append((kind, name))
                    elif cls in _MSG_TYPES:
                        kind = 'text' if 'Text' in cls else 'link'
                        items.append((kind, name))
            except Exception:
                pass
            return items

        # Focus the list without clicking (click would trigger image/link items)
        msg_list.SetFocus()
        time.sleep(0.3)

        # Scroll to bottom first so we always start from the newest messages
        logger.debug("Scrolling to bottom...")
        _bottom_prev = None
        _bottom_stuck = 0
        while _bottom_stuck < 3:
            try:
                children = list(msg_list.GetChildren())
                _bottom_cur = (children[-1].Name or '') if children else ''
            except Exception:
                _bottom_cur = ''
            if _bottom_cur == _bottom_prev:
                _bottom_stuck += 1
            else:
                _bottom_stuck = 0
            _bottom_prev = _bottom_cur
            win32api.SetCursorPos((cx, cy))
            for _ in range(5):
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, -360, 0)
                time.sleep(0.05)
            time.sleep(0.4)
        logger.debug("Reached bottom, starting upward collection.")
        time.sleep(0.3)

        stop_reason = ''
        while True:
            batch    = _read_visible()
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
                    state = _ts_state(current_ts)
                    if state == 'too_old':
                        stop_now = True
                        break
                    continue   # too_new or in_range: update ts, keep going

                state = _ts_state(current_ts)
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

            win32api.SetCursorPos((cx, cy))
            for _ in range(5):
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 360, 0)
                time.sleep(0.1)
            time.sleep(0.8)

        logger.info(
            f"get_chat_history: {len(collected)} items from '{target}' "
            f"(since='{since}', stop='{stop_reason}')"
        )

        collected.reverse()   # oldest first
        return collected
