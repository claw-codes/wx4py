# -*- coding: utf-8 -*-
"""微信聊天窗口页面"""
import hashlib
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Set, Tuple

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


# 搜索结果分组名称
GROUP_CONTACTS = '联系人'
GROUP_CHATS = '群聊'
GROUP_FUNCTIONS = '功能'
GROUP_NETWORK = '搜索网络结果'
GROUP_HISTORY = '聊天记录'
GROUP_FREQUENT = '最常使用'

ALL_GROUP_NAMES = [GROUP_CONTACTS, GROUP_CHATS, GROUP_FUNCTIONS, GROUP_NETWORK, GROUP_HISTORY, GROUP_FREQUENT]


@dataclass
class SearchResult:
    """搜索结果项"""
    name: str
    ctrl: object  # UIAutomation 控件
    item_type: str  # 'contact', 'function', 'network'
    auto_id: str
    group: str


@dataclass(frozen=True)
class SendRequest:
    """已规范化的发送请求载荷。"""
    target: str
    message: str
    target_type: str


@dataclass(frozen=True)
class ChatHistoryRange:
    """聊天记录采集的时间戳匹配规则。"""
    in_range_prefixes: Optional[Set[str]]
    too_new_prefixes: Set[str]


class ChatWindow(BasePage):
    """
    微信聊天窗口页面，用于发送消息。

    用法:
        wx = WeChatClient()
        wx.connect()

        # 发送给联系人
        wx.chat_window.send_to("大号", "Hello!")

        # 发送给群聊
        wx.chat_window.send_to("测试群", "Hello!", target_type='group')

        # 批量发送
        wx.chat_window.batch_send(["群1", "群2"], "Hello!")
    """

    def __init__(self, window):
        super().__init__(window)
        self._last_search_results: Dict[str, List[SearchResult]] = {}
        self._run_id = str(uuid.uuid4())
        self._recent_send_records: Dict[str, float] = {}

    # ==================== 私有方法 ====================

    def _sleep_with_jitter(self, minimum: float, maximum: float) -> float:
        """在给定范围内随机睡眠。"""
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
        """写入结构化发送审计日志。"""
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
        """验证并规范化目标。"""
        normalized_target = (target or "").strip()
        if not normalized_target:
            raise ValueError("target must not be empty")
        if target_type == "group" and ALLOWED_GROUPS and normalized_target not in ALLOWED_GROUPS:
            raise ValueError(
                f"group '{normalized_target}' is not in WECHAT_ALLOWED_GROUPS"
            )
        return normalized_target

    def _normalize_message(self, message: str) -> str:
        """验证并规范化消息。"""
        normalized_message = (message or "").strip()
        if not normalized_message:
            raise ValueError("message must not be empty")
        return normalized_message

    def _normalize_send_args(
        self, target: str, message: str, target_type: str
    ) -> SendRequest:
        """验证并规范化发送参数。"""
        if target_type not in ("contact", "group"):
            raise ValueError("target_type must be 'contact' or 'group'")

        return SendRequest(
            target=self._normalize_target(target, target_type),
            message=self._normalize_message(message),
            target_type=target_type,
        )

    def _make_send_record_key(self, target: str, message: str) -> str:
        """构建发送操作的去重键。"""
        content_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
        return f"{target}:{content_hash}"

    def _was_sent_recently(self, target: str, message: str) -> bool:
        """检查相同内容是否在近期已发送。"""
        key = self._make_send_record_key(target, message)
        sent_at = self._recent_send_records.get(key)
        if not sent_at:
            return False
        return (time.time() - sent_at) <= SEND_DEDUP_WINDOW_SECONDS

    def _remember_successful_send(self, target: str, message: str) -> None:
        """记录成功发送，用于重复抑制。"""
        now = time.time()
        cutoff = now - SEND_DEDUP_WINDOW_SECONDS
        self._recent_send_records = {
            key: ts for key, ts in self._recent_send_records.items() if ts >= cutoff
        }
        self._recent_send_records[self._make_send_record_key(target, message)] = now

    def _send_ctrl_hotkey(self, key_code: int) -> None:
        """通过 Win32 按一次 Ctrl+<key>，用于更稳定的文本粘贴。"""
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
        """重建 UIA 会话并恢复窗口焦点。"""
        logger.warning("正在重建微信 UIA 会话")
        return self._window.refresh()

    def _sleep_between_batch_targets(self) -> None:
        """批量目标间睡眠，减少 UI 争用。"""
        time.sleep(random.uniform(BATCH_SEND_INTERVAL_MIN, BATCH_SEND_INTERVAL_MAX))

    def _sleep_before_send_attempt(self) -> None:
        """每次发送尝试前简短睡眠。"""
        self._sleep_with_jitter(SEND_JITTER_MIN, SEND_JITTER_MAX)

    def _sleep_before_send_retry(self) -> None:
        """重试失败后简短睡眠。"""
        self._sleep_with_jitter(SEARCH_RETRY_DELAY_MIN, SEARCH_RETRY_DELAY_MAX)

    def _find_target_result(
        self, results: Dict[str, List[SearchResult]], target: str, target_type: str
    ) -> Optional[SearchResult]:
        """在搜索结果中查找匹配的目标，优先级：最常使用 > 联系人/群聊 > 功能"""
        # 优先级1：最常使用（最高）
        for item in results.get(GROUP_FREQUENT, []):
            if target in item.name:
                return item

        # 优先级2：联系人/群聊
        primary_group = GROUP_CHATS if target_type == 'group' else GROUP_CONTACTS
        for item in results.get(primary_group, []):
            if target in item.name:
                return item

        # 优先级3：功能
        if target_type == 'contact':
            for item in results.get(GROUP_FUNCTIONS, []):
                if target in item.name:
                    return item

        return None

    def _prepare_chat_input_for_paste(self):
        """聚焦并清空聊天输入框，为粘贴内容做准备。"""
        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("未找到聊天输入框")
            return None

        try:
            # Try to focus the input
            try:
                chat_input.Click(simulateMove=False)
            except Exception:
                try:
                    chat_input.SetFocus()
                except Exception:
                    pass

            time.sleep(0.2)

            # Clear existing content
            try:
                chat_input.SendKeys('{Ctrl}a')
                time.sleep(0.1)
                chat_input.SendKeys('{Delete}')
                time.sleep(0.1)
            except Exception as e:
                logger.debug(f"清空聊天输入框失败: {e}")

            return chat_input
        except Exception as e:
            logger.error(f"准备聊天输入框失败: {e}")
            return None

    def _paste_text_into_chat_input(self, text: str, log_error: str = "写入消息到剪贴板失败") -> bool:
        """通过剪贴板将文本粘贴到当前聚焦的聊天输入框。"""
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
        """执行一个发送阶段并写入审计日志。"""
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
        """执行一次完整的发送尝试。"""
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
        """在当前 UIA 会话中执行一系列发送尝试。"""
        attempt_list = list(attempts)

        for index, attempt in enumerate(attempt_list):
            if self._send_once(request, attempt):
                return True
            if index < len(attempt_list) - 1:
                self._sleep_before_send_retry()

        return False

    def _send_with_reconnect_fallback(self, request: SendRequest) -> bool:
        """先执行常规发送重试，失败后重建 UIA 会话再重试。"""
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
        """打开聊天并保留 TargetNotFoundError，用于发送工作流控制。"""
        return self.open_chat(target, target_type, raise_on_target_not_found=True)

    def _get_search_edit(self, retries: int = SEARCH_RETRY_COUNT):
        """获取主搜索框控件（不是群详情面板中的搜索框）。"""

        def find_all_edits(ctrl, results, depth=0, max_depth=15):
            """递归查找所有编辑控件。"""
            if depth > max_depth:
                return
            try:
                if not ctrl:
                    return
            # 检查是否是 EditControl
                try:
                    if ctrl.ControlTypeName == 'EditControl':
                        results.append(ctrl)
                except Exception:
                    pass

                # 获取子控件并递归
                try:
                    children = ctrl.GetChildren()
                    if children:
                        for child in children:
                            find_all_edits(child, results, depth + 1, max_depth)
                except Exception:
                    pass
            except Exception:
                return

        def is_in_group_detail_panel(edit) -> bool:
            """检查编辑控件是否在群详情面板内。"""
            try:
                current = edit.GetParentControl()
                depth = 0
                while current and depth < 10:
                    class_name = current.ClassName or ''
                    if any(x in class_name for x in ['ChatRoomMemberInfoView', 'GroupInfoView', 'ChatRoomInfoView']):
                        return True
                    current = current.GetParentControl()
                    depth += 1
            except Exception:
                pass
            return False

        def is_likely_search_box(edit) -> bool:
            """判断此编辑控件是否可能是主搜索框。"""
            try:
                class_name = edit.ClassName or ''
                name = edit.Name or ''

                # 排除已知的非搜索编辑控件
                if any(x in class_name for x in ['ChatItem', 'ChatBubble', 'Message']):
                    return False

                # 如果名称包含 '搜索'，很可能是搜索框
                if '搜索' in name:
                    return True

                # 如果在群详情面板中，不是主搜索框
                if is_in_group_detail_panel(edit):
                    return False

                # 微信 Qt UI 中，搜索框通常在窗口顶部附近
                try:
                    edit_rect = edit.BoundingRectangle
                    root_rect = self.root.BoundingRectangle
                    if edit_rect and root_rect:
                        # 搜索框通常在窗口顶部区域
                        if edit_rect.top < root_rect.top + root_rect.height() * 0.3:
                            # 并且宽度合理
                            if edit_rect.right - edit_rect.left > 100:
                                return True
                except Exception:
                    pass

                # 如果类名匹配已知模式
                if class_name.startswith('mmui::') and 'Edit' in class_name:
                    # 额外检查：不在群详情中
                    if not is_in_group_detail_panel(edit):
                        return True

            except Exception:
                pass
            return False

        for attempt in range(1, retries + 1):
            all_edits = []
            try:
                find_all_edits(self.root, all_edits)
                logger.debug(f"找到 {len(all_edits)} 个编辑控件")
            except Exception as e:
                logger.debug(f"查找编辑控件出错: {e}")

            # 第一轮：按名称 '搜索' 查找
            for edit in all_edits:
                try:
                    name = edit.Name or ''
                    if '搜索' in name and not is_in_group_detail_panel(edit):
                        logger.debug(f"通过名称找到搜索框: {name}")
                        return edit
                except Exception:
                    pass

            # 第二轮：使用启发式查找主搜索框
            candidates = []
            for edit in all_edits:
                try:
                    if is_likely_search_box(edit):
                        # 为候选结果评分
                        score = 0
                        rect = edit.BoundingRectangle
                        root_rect = self.root.BoundingRectangle

                        if rect and root_rect:
                            # 优先选择靠近顶部的编辑框
                            relative_top = (rect.top - root_rect.top) / root_rect.height()
                            if relative_top < 0.2:  # 窗口顶部 20%
                                score += 100
                            elif relative_top < 0.4:  # 窗口顶部 40%
                                score += 50

                            # 优先选择较宽的编辑框（搜索框通常较宽）
                            width = rect.right - rect.left
                            if width > 200:
                                score += 50
                            elif width > 100:
                                score += 25

                        # 优先选择 mmui 类名的编辑框
                        class_name = edit.ClassName or ''
                        if 'mmui::' in class_name:
                            score += 20

                        candidates.append((score, edit))
                except Exception:
                    pass

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_edit = candidates[0][1]
                logger.debug(f"选择得分为 {candidates[0][0]} 的搜索框")
                return best_edit

            # 尝试间恢复操作
            try:
                # 关闭任何打开的面板
                self.root.SendKeys('{Esc}')
                time.sleep(0.2)
                self.root.SendKeys('{Esc}')
                time.sleep(0.2)
                # 强制打开全局搜索
                self.root.SendKeys('{Ctrl}f')
                time.sleep(0.5)
            except Exception:
                pass

            self._window.activate()
            time.sleep(0.5)
            logger.debug(f"未找到搜索框，重试中 ({attempt}/{retries})")

        logger.warning("未找到搜索框")
        return None

    def _get_chat_input(self):
        """获取聊天输入框"""
        # 尝试多种方法查找聊天输入框，以兼容不同微信版本
        possible_ids = ['chat_input_field', 'input_field', 'msg_input', 'edit_input']
        possible_class_names = ['mmui::XTextEdit', 'mmui::XValidatorTextEdit', 'mmui::XEditEx', 'mmui::XRichEdit']

        # 先按 AutomationId 查找
        for auto_id in possible_ids:
            try:
                edit = self.root.EditControl(AutomationId=auto_id)
                if edit.Exists(maxSearchSeconds=0.5):
                    return edit
            except Exception:
                continue

        # 按 ClassName 查找
        for class_name in possible_class_names:
            try:
                edit = self.root.EditControl(ClassName=class_name)
                # 额外检查：聊天输入框应在窗口下半部分
                if edit.Exists(maxSearchSeconds=0.5):
                    rect = edit.BoundingRectangle
                    root_rect = self.root.BoundingRectangle
                    # 聊天输入框通常在窗口下半部
                    if rect and root_rect and rect.top > (root_rect.top + root_rect.height() * 0.5):
                        return edit
            except Exception:
                continue

        # 最后手段：查找所有 EditControl 并挑选最可能是聊天输入框的
        try:
            edits = self.root.GetChildren()
            candidates = []
            for ctrl in edits:
                if ctrl.ControlTypeName == 'EditControl':
                    rect = ctrl.BoundingRectangle
                    root_rect = self.root.BoundingRectangle
                    if rect and root_rect:
                        # 优先选择底部区域的编辑框
                        score = rect.top - root_rect.top
                        candidates.append((score, ctrl))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]
        except Exception:
            pass

        return None

    def _get_search_popup(self):
        """获取搜索弹出窗口"""
        # 尝试多种可能的类名查找搜索弹出窗口，以兼容不同微信版本
        possible_class_names = [
            'mmui::SearchContentPopover',
            'mmui::SearchPopover',
            'mmui::XSearchPopup',
            'mmui::XPopupWindow',
        ]

        for class_name in possible_class_names:
            try:
                popup = self.root.WindowControl(ClassName=class_name)
                if popup.Exists(maxSearchSeconds=0.5):
                    return popup
            except Exception:
                continue

        # 回退：尝试按 AutomationId 或其他属性查找
        try:
            popup = self.root.WindowControl(AutomationId='search_popup')
            if popup.Exists(maxSearchSeconds=0.5):
                return popup
        except Exception:
            pass

        return None

    def _parse_search_results(self, items) -> Dict[str, List[SearchResult]]:
        """
        解析搜索结果并分组。

        Args:
            items: 搜索列表中的子项

        Returns:
            分组名到 SearchResult 列表的字典
        """
        groups: Dict[str, List[SearchResult]] = {}
        current_group: Optional[str] = None

        for item in items:
            class_name = item.ClassName or ""
            name = item.Name or ""
            auto_id = item.AutomationId or ""

            # 分组标题：没有 AutoId 的 XTableCell
            if class_name == 'mmui::XTableCell' and not auto_id:
                if name in ALL_GROUP_NAMES:
                    current_group = name
                    groups[current_group] = []
                    logger.debug(f"找到分组: {name}")
                    continue
                elif '查看全部' in name:
                    # 跳过 "查看全部" 按钮
                    continue
                else:
                    # 网络搜索结果项
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

            # 功能项：带 search_item_function AutoId 的 XTableCell
            if auto_id.startswith('search_item_function'):
                result = SearchResult(
                    name=name,
                    ctrl=item,
                    item_type='function',
                    auto_id=auto_id,
                    group=GROUP_FUNCTIONS
                )
                groups.setdefault(GROUP_FUNCTIONS, []).append(result)
                logger.debug(f"找到功能项: {name}")
                continue

            # 联系人/群聊项：带 AutoId 的 SearchContentCellView
            if 'SearchContentCellView' in class_name:
                if auto_id.startswith('search_item_'):
                    # 联系人或群聊
                    result = SearchResult(
                        name=name,
                        ctrl=item,
                        item_type='contact',
                        auto_id=auto_id,
                        group=current_group or '未知'
                    )
                    groups.setdefault(current_group or '未知', []).append(result)
                    logger.debug(f"找到联系人项: {name} 在 {current_group}")

        return groups

    def _input_search(self, keyword: str) -> bool:
        """
        输入搜索关键词。

        Args:
            keyword: 搜索关键词

        Returns:
            bool: 成功时返回 True
        """
        search_edit = self._get_search_edit(retries=SEARCH_RETRY_COUNT)
        if not search_edit:
            logger.error("未找到搜索框")
            return False

        try:
            # 尝试多种方式聚焦搜索框
            focused = False

            # 方法 1：Click 点击
            try:
                search_edit.Click(simulateMove=False)
                focused = True
            except Exception as e1:
                logger.debug(f"Click 点击失败: {e1}")

            # 方法 2：SetFocus
            if not focused:
                try:
                    search_edit.SetFocus()
                    focused = True
                except Exception as e2:
                    logger.debug(f"SetFocus 聚焦失败: {e2}")

            # 方法 3：用 Ctrl+F 确保搜索激活
            try:
                self.root.SendKeys('{Ctrl}f')
                time.sleep(0.3)
            except Exception:
                pass

            time.sleep(0.3)

            # 使用多种方法清除已有内容
            try:
                # 尝试 Ctrl+A 然后 Delete
                search_edit.SendKeys('{Ctrl}a')
                time.sleep(0.1)
                search_edit.SendKeys('{Delete}')
                time.sleep(0.1)
            except Exception as e:
                logger.debug(f"使用 Ctrl+A/Delete 清除搜索框失败: {e}")
                try:
                    # 回退：全选并输入
                    search_edit.SendKeys('{Ctrl}a')
                    time.sleep(0.1)
                except Exception:
                    pass

            # 输入关键词
            try:
                search_edit.SendKeys(keyword)
            except Exception as e:
                logger.error(f"向搜索框发送按键失败: {e}")
                return False

            time.sleep(1.0)  # 等待搜索结果

            return True
        except Exception as e:
            logger.error(f"输入搜索关键词失败: {e}")
            return False

    def _clear_search(self):
        """清除搜索输入"""
        search_edit = self._get_search_edit()
        if search_edit:
            search_edit.SendKeys('{Esc}')

    # ==================== 公开方法 ====================

    def search(self, keyword: str) -> Dict[str, List[SearchResult]]:
        """
        搜索并返回按分组归类的全部结果。

        Args:
            keyword: 搜索关键词

        Returns:
            Dict: 分组名称 -> SearchResult 列表的映射
        """
        logger.info(f"搜索: {keyword}")

        if not self._input_search(keyword):
            return {}

        popup = self._get_search_popup()
        if not popup:
            logger.warning("未找到搜索弹出面板")
            return {}

        # 尝试多个可能的 AutomationId 查找搜索列表
        search_list = None
        possible_list_ids = ['search_list', 'search_result_list', 'result_list', 'list']

        for list_id in possible_list_ids:
            try:
                lst = popup.ListControl(AutomationId=list_id)
                if lst.Exists(maxSearchSeconds=0.5):
                    search_list = lst
                    break
            except Exception:
                continue

        # 若按 ID 未找到，尝试在弹出面板中查找任意 ListControl
        if not search_list:
            try:
                lists = popup.GetChildren()
                for ctrl in lists:
                    if ctrl.ControlTypeName == 'ListControl':
                        search_list = ctrl
                        break
            except Exception:
                pass

        if not search_list:
            logger.warning("未找到搜索列表")
            return {}

        try:
            items = search_list.GetChildren()
        except Exception as e:
            logger.warning(f"获取搜索列表子控件失败: {e}")
            return {}
        results = self._parse_search_results(items)
        self._last_search_results = results

        # 记录结果
        for group, items in results.items():
            logger.debug(f"分组 '{group}': {len(items)} 条")

        return results

    def _open_chat_once(self, target: str, target_type: str = 'contact') -> bool:
        """单次尝试搜索并打开聊天。"""
        group_name = GROUP_CHATS if target_type == 'group' else GROUP_CONTACTS
        logger.info(f"正在打开聊天: {target} (类型: {target_type})")

        results = self.search(target)
        target_result = self._find_target_result(results, target, target_type)

        if not target_result:
            self._clear_search()
            raise TargetNotFoundError(f"'{target}' not found in '{group_name}' group")

        logger.debug(f"点击: {target_result.name}")

        # 尝试多种点击方式以提升兼容性
        click_success = False
        try:
            # 方法 1：标准 Click
            target_result.ctrl.Click()
            click_success = True
        except Exception as e1:
            logger.debug(f"标准 Click 失败: {e1}")
            try:
                # 方法 2：Click(simulateMove=False)
                target_result.ctrl.Click(simulateMove=False)
                click_success = True
            except Exception as e2:
                logger.debug(f"简单 Click 失败: {e2}")
                try:
                    # 方法 3：DoubleClick 兜底
                    target_result.ctrl.DoubleClick(simulateMove=False)
                    click_success = True
                except Exception as e3:
                    logger.error(f"所有点击方式均失败: {e3}")

        if not click_success:
            return False

        time.sleep(0.8)

        chat_input = self._get_chat_input()
        if not chat_input:
            logger.error("打开聊天后未找到输入框")
            return False

        logger.info(f"聊天已打开: {target}")
        return True

    def open_chat(
        self,
        target: str,
        target_type: str = 'contact',
        raise_on_target_not_found: bool = False,
    ) -> bool:
        """
        搜索并打开与目标的聊天。

        Args:
            target: 联系人或群名称
            target_type: 'contact' 或 'group'
            raise_on_target_not_found: 为 True 时保留 TargetNotFoundError，
                以便调用方区分"找不到目标"和"暂时性 UI 故障"。

        Returns:
            bool: 成功时返回 True
        """
        for attempt in range(1, SEARCH_RETRY_COUNT + 1):
            try:
                if self._open_chat_once(target, target_type):
                    return True
            except TargetNotFoundError:
                if raise_on_target_not_found:
                    raise
                logger.error(f"未找到目标聊天: '{target}'")
                return False

            self._clear_search()
            self._window.activate()
            delay = self._sleep_with_jitter(
                SEARCH_RETRY_DELAY_MIN, SEARCH_RETRY_DELAY_MAX
            )
            logger.debug(
                f"打开聊天重试已计划: '{target}' "
                f"({attempt}/{SEARCH_RETRY_COUNT}, 等待 {delay:.2f}秒)"
            )

        logger.error(f"重试后仍无法打开聊天: {target}")
        self._clear_search()
        return False

    def send_message(self, message: str) -> bool:
        """
        在当前聊天中发送消息。

        Args:
            message: 要发送的消息

        Returns:
            bool: 成功时返回 True
        """
        logger.info(f"发送消息: {message[:20]}...")

        chat_input = self._prepare_chat_input_for_paste()
        if not chat_input:
            return False

        if not self._paste_text_into_chat_input(message):
            return False

        # 尝试多种方式发送消息
        try:
            chat_input.SendKeys('{Enter}')
        except Exception as e:
            logger.debug(f"SendKeys Enter 失败: {e}")
            try:
                # 兜底：尝试 Ctrl+Enter
                chat_input.SendKeys('{Ctrl}{Enter}')
            except Exception as e2:
                logger.error(f"发送消息失败: {e2}")
                return False

        time.sleep(0.3)

        logger.info("消息已发送")
        return True

    def send_to(self, target: str, message: str, target_type: str = 'contact') -> bool:
        """
        打开聊天并发送消息。

        Args:
            target: 联系人或群名称
            message: 要发送的消息
            target_type: 'contact' 或 'group'

        Returns:
            bool: 成功时返回 True
        """
        request = self._normalize_send_args(target, message, target_type)

        if self._was_sent_recently(request.target, request.message):
            logger.warning(
                f"跳过 {SEND_DEDUP_WINDOW_SECONDS} 秒内的重复发送: {request.target}"
            )
            return True

        try:
            if self._send_with_reconnect_fallback(request):
                return True
        except TargetNotFoundError:
            logger.error(f"未找到目标聊天: '{request.target}'")
            return False

        logger.error(f"重试后仍无法向 '{request.target}' 发送消息")
        return False

    def batch_send(self, targets: List[str], message: str, target_type: str = 'group') -> Dict[str, bool]:
        """
        向多个目标发送消息。

        Args:
            targets: 联系人或群名称列表
            message: 要发送的消息
            target_type: 'contact' 或 'group'

        Returns:
            Dict: 目标名称 -> 发送是否成功的映射
        """
        logger.info(f"批量发送到 {len(targets)} 个目标")

        normalized_message = self._normalize_message(message)

        results = {}
        for target in targets:
            success = self.send_to(target, normalized_message, target_type)
            results[target] = success
            self._sleep_between_batch_targets()

        # 汇总结果
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"批量发送完成: {success_count}/{len(targets)} 成功")

        return results

    @property
    def last_search_results(self) -> Dict[str, List[SearchResult]]:
        """获取上次搜索结果"""
        return self._last_search_results

    def send_file(self, file_path, message: str = None) -> bool:
        """
        在当前聊天中发送文件。

        Args:
            file_path: 文件路径（或路径列表）
            message: 可选的附加消息

        Returns:
            bool: 成功时返回 True
        """
        logger.info(f"发送文件: {file_path}")

        chat_input = self._prepare_chat_input_for_paste()
        if not chat_input:
            return False

        if not self._set_files_to_clipboard(file_path):
            return False

        time.sleep(0.2)

        self._send_ctrl_hotkey(VK_V)
        time.sleep(0.5)

        # 如果提供了附加消息则追加
        normalized_message = self._normalize_message(message) if message is not None else ""
        if normalized_message:
            if not self._paste_text_into_chat_input(
                normalized_message,
                log_error="写入文件消息到剪贴板失败",
            ):
                return False

        # 按回车发送
        chat_input.SendKeys('{Enter}')
        time.sleep(0.5)

        logger.info("文件已发送")
        return True

    def _set_files_to_clipboard(self, file_path) -> bool:
        """将文件路径设置到剪贴板，并统一处理失败情况。"""
        try:
            copied = set_files_to_clipboard(file_path)
        except ValueError as exc:
            logger.error(str(exc))
            return False

        if not copied:
            logger.error("复制文件路径到剪贴板失败")
            return False

        return True

    def send_file_to(self, target: str, file_path, target_type: str = 'contact', message: str = None) -> bool:
        """
        打开聊天并发送文件。

        Args:
            target: 联系人或群名称
            file_path: 文件路径（或路径列表）
            target_type: 'contact' 或 'group'
            message: 可选的附加消息

        Returns:
            bool: 成功时返回 True
        """
        if not self.open_chat(target, target_type):
            return False
        return self.send_file(file_path, message)

    def _get_chat_history_range(self, since: str) -> ChatHistoryRange:
        """根据 since 参数解析聊天记录时间戳前缀规则。"""
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
        """将长格式时间戳标准化为范围过滤器使用的短前缀。"""
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
        """返回时间戳是在范围内、比范围新、还是太旧。"""
        if not ts or history_range.in_range_prefixes is None:
            return 'in_range'

        effective = self._normalize_history_timestamp(ts, today, yesterday)
        if any(effective.startswith(prefix) for prefix in history_range.too_new_prefixes):
            return 'too_new'
        if any(effective.startswith(prefix) for prefix in history_range.in_range_prefixes):
            return 'in_range'
        return 'too_old'

    def _get_chat_message_list(self):
        """获取聊天消息列表控件（如果可用）。"""
        msg_list = self.root.ListControl(AutomationId='chat_message_list')
        if not msg_list.Exists(maxSearchSeconds=2):
            logger.error("未找到 chat_message_list")
            return None
        return msg_list

    def _get_message_list_center(self, msg_list) -> Tuple[int, int]:
        """返回消息列表的中心点，用于滚轮滚动。"""
        rect = msg_list.BoundingRectangle
        return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2

    def _read_visible_chat_items(self, msg_list) -> List[Tuple[str, str]]:
        """读取当前聊天视图中可见的时间戳和消息项。"""
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
        """以一致的光标位置和时序滚动消息列表。"""
        win32api.SetCursorPos((cx, cy))
        for _ in range(steps):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
            time.sleep(step_delay)
        time.sleep(settle_time)

    def _scroll_message_list_to_bottom(self, msg_list, cx: int, cy: int) -> None:
        """在采集历史记录前先滚动到最新消息。"""
        logger.debug("滚动到底部...")
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

        logger.debug("已到达底部，开始向上采集。")
        time.sleep(0.3)

    def get_chat_history(self, target: str, target_type: str = 'contact',
                         since: str = 'today', max_count: int = 500) -> list:
        """
        获取联系人或群的聊天记录。

        向上滚动直到遇到早于 `since` 的消息后停止。
        返回按时间顺序排列（最旧在前）的可 JSON 序列化字典列表。

        每个条目:
            {
                'type':    'text' | 'link' | 'system',
                'content': str,    # 完整消息文本
                'time':    str,    # 附属于该消息的时间戳标签
            }

        Args:
            target:      联系人或群名称
            target_type: 'contact' 或 'group'
            since:       采集的日期范围。
                         'today'     – 仅今天的消息
                         'yesterday' – 仅昨天的消息
                         'week'      – 本周以来（星期X）
                         'all'       – 持续滚动直到没有新消息
            max_count:   返回消息数量的硬限制（安全上限）

        限制:
            微信的 Qt UIA 提供程序不暴露发送者名称。

        Returns:
            list[dict]
        """
        history_range = self._get_chat_history_range(since)
        today = date.today()
        yesterday = today - timedelta(days=1)

        if not self.open_chat(target, target_type):
            logger.error(f"无法打开聊天: {target}")
            return []
        time.sleep(1)

        msg_list = self._get_chat_message_list()
        if not msg_list:
            return []

        cx, cy = self._get_message_list_center(msg_list)

        # 滚动采集时按最新在前顺序，最终反转
        collected:   list = []
        seen_keys:   set  = set()   # (time_label, content) 用于去重
        current_ts:  str  = ""
        prev_top:    str  = None    # 第一个可见项的内容，滚动位置指示器
        stuck_count: int  = 0

        # 聚焦列表但不点击（点击会触发图片/链接项）
        msg_list.SetFocus()
        time.sleep(0.3)

        # 先滚动到底部，确保从最新消息开始
        self._scroll_message_list_to_bottom(msg_list, cx, cy)

        stop_reason = ''
        while True:
            batch = self._read_visible_chat_items(msg_list)
            stop_now = False

            # 通过第一个可见项是否变化来检测滚动进度
            top_item = batch[0][1] if batch else ''
            if top_item == prev_top:
                stuck_count += 1
            else:
                stuck_count = 0
            prev_top = top_item

            # 处理当前批次 — 从上到下遍历（视图中最旧在前）
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

        collected.reverse()   # 最旧在前
        return collected
