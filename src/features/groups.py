# -*- coding: utf-8 -*-
"""微信群组管理功能"""
import time
import win32gui
import win32api
import win32con
from typing import Optional

from .base import BasePage
from ..utils.logger import get_logger
from ..core.uiautomation import ControlFromHandle as control_from_handle, GetFocusedControl, PatternId, ToggleState, WalkControl

logger = get_logger(__name__)


class GroupManager(BasePage):
    """
    群组管理操作。

    用法:
        wx = WeChatClient()
        wx.connect()

        # 修改群公告
        wx.group_manager.modify_announcement("测试群", "新公告内容")
    """

    # 群公告弹窗中"完成"按钮的相对位置比例
    COMPLETE_BTN_X_RATIO = 0.90  # 距左边缘 90%
    COMPLETE_BTN_Y_RATIO = 0.09  # 距顶部边缘 9%（标题栏下方）

    def __init__(self, window):
        super().__init__(window)

    def _press_key(self, key_code: int, hold_time: float = 0.1) -> None:
        """按下并释放一个虚拟按键。"""
        win32api.keybd_event(key_code, 0, 0, 0)
        time.sleep(hold_time)
        win32api.keybd_event(key_code, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _send_ctrl_combo(self, key_code: int, settle_time: float = 0.3) -> None:
        """发送 Ctrl+<key> 组合键并短暂等待 UI 更新。"""
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(key_code, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(key_code, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(settle_time)

    def _walk_controls(self, root, max_depth: int = 20) -> list:
        """防御性地收集控件树。"""
        results = []

        def _visit(ctrl, depth: int) -> None:
            if depth > max_depth:
                return
            results.append(ctrl)
            try:
                for child in ctrl.GetChildren():
                    _visit(child, depth + 1)
            except Exception:
                return

        _visit(root, 0)
        return results

    def _focus_control_center(self, ctrl) -> None:
        """通过点击中心点来聚焦弹窗。"""
        rect = ctrl.BoundingRectangle
        if not rect:
            return
        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2
        self._click_at_position(center_x, center_y)
        time.sleep(0.3)

    def _open_group_chat(self, group_name: str) -> bool:
        """打开群聊，使用统一的日志记录。"""
        from .chat import ChatWindow

        chat_window = ChatWindow(self._window)
        if not chat_window.open_chat(group_name, target_type='group'):
            logger.error(f"打开群聊失败: {group_name}")
            return False
        time.sleep(1)
        return True

    def _get_group_detail_view(self, timeout: float = 2):
        """获取群详情面板（如果存在）。"""
        # 尝试多个可能的类名以兼容不同微信版本
        possible_class_names = [
            'mmui::ChatRoomMemberInfoView',
            'mmui::GroupInfoView',
            'mmui::ChatRoomInfoView',
            'mmui::XGroupDetailPanel',
        ]

        for class_name in possible_class_names:
            try:
                info_view = self.root.GroupControl(ClassName=class_name)
                if info_view.Exists(maxSearchSeconds=0.5):
                    return info_view
            except Exception:
                continue

        logger.error("未找到 ChatRoomMemberInfoView")
        return None

    def _open_and_focus_group_detail(self, group_name: str):
        """打开群聊、显示详情面板并聚焦该面板。"""
        if not self._open_group_chat(group_name):
            return None
        if not self._open_group_detail():
            return None

        info_view = self._get_group_detail_view()
        if not info_view:
            return None

        info_view.SetFocus()
        time.sleep(0.3)
        return info_view

    def _find_button_with_deadline(self, button_name: str, timeout: float = 3.0):
        """在主窗口中轮询查找按钮直到超时。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            button = self.root.ButtonControl(Name=button_name)
            if button.Exists(maxSearchSeconds=0.2):
                return button
            time.sleep(0.2)
        return None

    def _get_member_list(self):
        """获取群成员列表控件（如果存在）。"""
        # 尝试多个可能的 AutomationId 以兼容不同微信版本
        possible_ids = ['chat_member_list', 'member_list', 'group_member_list', 'list']
        possible_class_names = ['mmui::QFReuseGridWidget', 'mmui::XListView', 'mmui::XListWidget']

        # 先按 AutomationId 查找
        for auto_id in possible_ids:
            try:
                member_list = self.root.ListControl(AutomationId=auto_id)
                if member_list.Exists(maxSearchSeconds=0.5):
                    return member_list
            except Exception:
                continue

        # 按 ClassName 查找
        for class_name in possible_class_names:
            try:
                member_list = self.root.ListControl(ClassName=class_name)
                if member_list.Exists(maxSearchSeconds=0.5):
                    return member_list
            except Exception:
                continue

        # 最后兜底：在群详情区域查找任意 ListControl
        try:
            children = self.root.GetChildren()
            for ctrl in children:
                if ctrl.ControlTypeName == 'ListControl':
                    return ctrl
        except Exception:
            pass

        logger.error("未找到 chat_member_list")
        return None

    def _scroll_list(self, ctrl, delta: int, steps: int, step_delay: float, settle_time: float) -> None:
        """通过鼠标滚轮滚动列表控件。"""
        rect = ctrl.BoundingRectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        win32api.SetCursorPos((cx, cy))
        for _ in range(steps):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
            time.sleep(step_delay)
        time.sleep(settle_time)

    def _find_announcement_window(self) -> Optional[dict]:
        """查找群公告弹窗。"""
        windows = []

        def enum_callback(hwnd, results):
            title = win32gui.GetWindowText(hwnd)
            if '公告' in title:
                results.append({'hwnd': hwnd, 'title': title})

        win32gui.EnumWindows(enum_callback, windows)
        return windows[0] if windows else None

    def _get_announcement_popup(self):
        """打开面板后获取群公告弹窗控件和 hwnd。"""
        popup_info = self._find_announcement_window()
        if not popup_info:
            logger.error("未找到群公告弹窗")
            return None, None

        hwnd = popup_info['hwnd']
        popup = control_from_handle(hwnd)
        if not popup:
            logger.error("无法获取群公告弹窗控件")
            return None, None
        return popup, hwnd

    def _click_at_position(self, x: int, y: int):
        """在屏幕坐标处点击。"""
        logger.debug(f"在屏幕位置 ({x}, {y}) 点击")
        win32api.SetCursorPos((x, y))
        time.sleep(0.2)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _double_click_at_position(self, x: int, y: int):
        """在屏幕坐标处双击。"""
        logger.debug(f"在屏幕位置 ({x}, {y}) 双击")
        win32api.SetCursorPos((x, y))
        time.sleep(0.2)
        # 第一次点击
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.1)
        # 第二次点击
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _right_click_at_position(self, x: int, y: int):
        """在屏幕坐标处右键单击。"""
        logger.debug(f"在屏幕位置 ({x}, {y}) 右键单击")
        win32api.SetCursorPos((x, y))
        time.sleep(0.2)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    def _get_group_display_name(self, group_name: str) -> str:
        """获取群的显示名称（用于比较窗口名称）。"""
        # 群名称通常就是显示名称
        return group_name

    def _find_and_activate_button(self, popup, button_name: str) -> bool:
        """
        通过 Tab 导航查找按钮并用 Enter 键激活。

        Args:
            popup: 弹窗控件
            button_name: 要查找的按钮名称（如 '完成'、'编辑群公告'、'发布'）

        Returns:
            bool: 找到并激活按钮时返回 True
        """
        logger.info(f"通过 Tab 导航查找 '{button_name}' 按钮...")

        # 聚焦弹窗
        self._focus_control_center(popup)
        time.sleep(0.2)

        # 通过 Tab 遍历控件查找目标按钮
        for tab_count in range(20):
            self._press_key(win32con.VK_TAB, hold_time=0.15)
            time.sleep(0.3)

            # 检查目标按钮是否已可见
            all_controls = self._walk_controls(popup)

            for ctrl in all_controls:
                if ctrl.Name == button_name:
                    logger.info(f"在第 {tab_count + 1} 次 Tab 找到 '{button_name}' 按钮")

                    # 尝试 Space 和 Enter 两种方式激活
                    for key_name, key_code in [("Space", win32con.VK_SPACE), ("Return", win32con.VK_RETURN)]:
                        logger.info(f"按 {key_name} 激活 '{button_name}'...")
                        self._press_key(key_code)
                        time.sleep(0.5)

                    time.sleep(1)
                    return True

        logger.error(f"未找到 '{button_name}' 按钮")
        return False

    def get_group_members(self, group_name: str) -> list:
        """
        获取群聊的所有成员。

        点击"聊天信息"打开详情面板，通过 Tab 导航触发"查看更多"（如果存在）
        以展开完整成员列表，然后滚动 QFReuseGridWidget 收集所有可见成员。

        Args:
            group_name: 群名称

        Returns:
            list[str]: 成员显示名称（昵称或备注名）
        """
        logger.info(f"获取群成员: {group_name}")

        # 第1步：打开群详情面板并聚焦
        info_view = self._open_and_focus_group_detail(group_name)
        if not info_view:
            return []

        # 第2步：Tab 导航到"查看更多"（虚拟化控件，FindFirst 无法直接查找）
        for i in range(10):
            self._press_key(win32con.VK_TAB, hold_time=0.05)
            time.sleep(0.3)
            focused = GetFocusedControl()
            if focused and '查看更多' in (focused.Name or ''):
                logger.info(f"Found 查看更多 at Tab #{i + 1}, triggering...")
                self._press_key(win32con.VK_RETURN)
                time.sleep(1)
                break
        else:
            logger.info("查看更多 not found, collecting visible members only")

        # 第3步：通过 AutomationId 查找成员列表（展开后同样有效）
        member_list = self._get_member_list()
        if not member_list:
            return []

        # 第4步：滚动并收集所有成员
        self._scroll_list(member_list, delta=120 * 3, steps=10, step_delay=0.1, settle_time=0.5)

        all_members = set()
        no_new_count = 0

        while no_new_count < 5:
            current = set()
            try:
                for child in member_list.GetChildren():
                    name = child.Name or ""
                    if name and child.ClassName == 'mmui::ChatMemberCell':
                        current.add(name)
            except Exception:
                pass

            new = current - all_members
            if new:
                all_members.update(new)
                no_new_count = 0
            else:
                no_new_count += 1

            # 每次滚动一行，等待 Qt 渲染
            self._scroll_list(member_list, delta=-120, steps=1, step_delay=0.0, settle_time=0.6)

        members = sorted(all_members)
        logger.info(f"从群 {group_name} 收集到 {len(members)} 名成员")
        return members

    def get_group_member_count(self, group_name: str) -> int:
        """
        快速获取群成员数量（不获取详细信息）。

        通过滚动成员列表统计成员数量，比 get_group_members 更快。

        Args:
            group_name: 群名称

        Returns:
            int: 群成员数量，失败返回 -1
        """
        logger.info(f"获取群成员数量: {group_name}")

        # 第1步：打开群详情面板并聚焦
        info_view = self._open_and_focus_group_detail(group_name)
        if not info_view:
            logger.error("打开群详情面板失败")
            return -1

        time.sleep(0.5)

        # 第2步：获取成员列表控件
        member_list = self._get_member_list()
        if not member_list:
            logger.error("获取成员列表失败")
            return -1

        # 第3步：滚动到顶部
        self._scroll_list(member_list, delta=120 * 10, steps=5, step_delay=0.1, settle_time=0.5)
        time.sleep(0.5)

        # 第4步：统计所有成员（只统计数量，不保存详细信息）
        all_members = set()
        no_new_count = 0

        while no_new_count < 5:
            current = set()
            try:
                for child in member_list.GetChildren():
                    try:
                        if child.ClassName == 'mmui::ChatMemberCell':
                            name = child.Name or ""
                            if name:
                                current.add(name)
                    except:
                        pass
            except:
                pass

            new = current - all_members
            if new:
                all_members.update(new)
                no_new_count = 0
            else:
                no_new_count += 1

            # 每次滚动一行
            self._scroll_list(member_list, delta=-120, steps=1, step_delay=0.0, settle_time=0.4)

        # 关闭群详情面板（只按一次 ESC，避免关闭独立窗口）
        self._close_popup()

        count = len(all_members)
        logger.info(f"群 '{group_name}' 成员数量: {count}")
        return count

    def get_all_members_wxid(self, group_name: str) -> dict:
        """
        一次性获取群所有成员的昵称和微信ID。

        打开群详情后依次遍历每个成员，点击资料卡获取微信ID。
        效率比单独调用 get_member_wxid 高很多。

        Args:
            group_name: 群名称

        Returns:
            dict: {昵称: 微信ID} 的字典，微信ID可能为空字符串（未加好友的情况）
        """
        logger.info(f"开始获取群 '{group_name}' 所有成员的微信ID...")

        result = {}

        # 第1步：打开群详情面板并聚焦
        info_view = self._open_and_focus_group_detail(group_name)
        if not info_view:
            logger.error("打开群详情面板失败")
            return result

        time.sleep(0.5)

        # 第2步：获取成员列表控件
        member_list = self._get_member_list()
        if not member_list:
            logger.error("获取成员列表失败")
            return result

        # 第3步：滚动到顶部
        self._scroll_list(member_list, delta=120 * 10, steps=5, step_delay=0.1, settle_time=0.5)
        time.sleep(1)

        # 第4步：收集所有可见成员控件（按位置排序）
        all_member_ctrls = {}  # {昵称: 控件}
        no_new_count = 0

        while no_new_count < 5:
            current_ctrls = {}
            try:
                children = member_list.GetChildren()
                for child in children:
                    try:
                        if child.ClassName == 'mmui::ChatMemberCell':
                            name = child.Name or ""
                            if name and name not in all_member_ctrls:
                                rect = child.BoundingRectangle
                                if rect:
                                    current_ctrls[name] = child
                    except:
                        pass
            except:
                pass

            if current_ctrls:
                all_member_ctrls.update(current_ctrls)
                no_new_count = 0
            else:
                no_new_count += 1

            # 每次滚动一行
            self._scroll_list(member_list, delta=-120, steps=1, step_delay=0.0, settle_time=0.6)

        logger.info(f"找到 {len(all_member_ctrls)} 名群成员，开始依次获取微信ID...")

        # 第5步：依次点击每个成员获取微信ID
        # 需要重新滚动并按顺序处理
        member_names = sorted(all_member_ctrls.keys())

        for i, member_name in enumerate(member_names):
            try:
                # 查找该成员控件（可能需要滚动）
                target_ctrl = self._find_member_in_list(member_list, member_name)
                if not target_ctrl:
                    logger.warning(f"未找到成员控件: {member_name}")
                    result[member_name] = ""  # 即使找不到控件也注册昵称
                    continue

                # 点击成员打开资料卡
                wxid = self._click_and_get_wxid(target_ctrl, member_name)
                result[member_name] = wxid or ""

                if wxid:
                    logger.info(f"成员 [{i+1}/{len(member_names)}]: {member_name} -> {wxid}")
                else:
                    logger.info(f"成员 [{i+1}/{len(member_names)}]: {member_name} (微信ID未公开)")

                time.sleep(0.3)

            except Exception as e:
                logger.warning(f"获取成员 {member_name} 微信ID失败: {e}")
                result[member_name] = ""  # 失败也注册昵称

        # 关闭群详情面板（只按一次 ESC，避免关闭独立窗口）
        self._close_popup()

        logger.info(f"完成注册，共 {len(result)} 名成员，其中 {sum(1 for v in result.values() if v)} 名获取到微信ID")
        return result

    def _find_member_in_list(self, member_list, member_name: str, max_scroll: int = 30):
        """在成员列表中查找指定成员控件。"""
        # 先滚动到顶部
        self._scroll_list(member_list, delta=120 * 10, steps=5, step_delay=0.1, settle_time=0.5)
        time.sleep(0.5)

        clean_name = member_name.strip()

        for _ in range(max_scroll):
            try:
                children = member_list.GetChildren()
                for child in children:
                    try:
                        if child.ClassName == 'mmui::ChatMemberCell':
                            child_name = child.Name or ""
                            if clean_name and clean_name in child_name:
                                return child
                    except:
                        pass
            except:
                pass

            # 向下滚动
            self._scroll_list(member_list, delta=-120, steps=1, step_delay=0.1, settle_time=0.3)

        return None

    def _click_and_get_wxid(self, target_ctrl, member_name: str) -> Optional[str]:
        """点击成员控件并从资料卡获取微信ID。"""
        rect = target_ctrl.BoundingRectangle
        if not rect:
            return None

        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2

        logger.info(f"点击成员 {member_name} at ({center_x}, {center_y})")

        # 尝试右键菜单
        self._right_click_at_position(center_x, center_y)
        time.sleep(0.8)

        # 查找右键菜单
        context_menu = None
        for pattern in ['mmui::CPopupMenu', 'mmui::CMenu', 'mmui::PopupMenu']:
            try:
                menu = self.root.WindowControl(ClassName=pattern)
                if menu.Exists(maxSearchSeconds=0.3):
                    context_menu = menu
                    logger.debug(f"找到右键菜单: {pattern}")
                    break
            except:
                pass

        profile_opened = False

        if context_menu:
            # 查找"查看个人资料"选项
            found_profile_option = False
            for ctrl, depth in WalkControl(context_menu, includeTop=False, maxDepth=5):
                try:
                    name = ctrl.Name or ""
                    if "查看个人资料" in name or "查看资料" in name:
                        logger.info(f"找到'{name}'选项，点击")
                        ctrl.Click(simulateMove=False)
                        time.sleep(1.5)
                        profile_opened = True
                        found_profile_option = True
                        break
                except:
                    pass

            if not found_profile_option:
                logger.debug("右键菜单中没有找到'查看个人资料'选项")
                # 关闭菜单，尝试直接单击
                self._close_popup()
                time.sleep(0.3)
        else:
            logger.debug("未找到右键菜单，尝试直接单击")

        if not profile_opened:
            # 直接单击打开资料卡
            self._click_at_position(center_x, center_y)
            time.sleep(1.5)

        # 查找资料卡窗口（多种方式）
        profile_card = None
        profile_patterns = [
            'mmui::ProfileUniquePop',
            'mmui::ContactProfileView',
            'mmui::ProfileCardView',
            'mmui::SessionProfileFrame',
        ]

        for pattern in profile_patterns:
            try:
                ctrl = self.root.WindowControl(ClassName=pattern)
                if ctrl.Exists(maxSearchSeconds=0.5):
                    profile_card = ctrl
                    logger.info(f"找到资料卡窗口: {pattern}")
                    break
            except:
                pass

        # 如果没有找到资料卡，可能打开了私聊窗口
        if not profile_card:
            logger.debug("未找到资料卡窗口，检查是否打开了私聊窗口或详情面板")
            # 尝试从私聊窗口或详情面板获取微信ID
            wxid = self._get_wxid_from_chat_window(member_name)
            self._close_popup()  # 关闭窗口
            return wxid

        # 从资料卡中提取微信号
        # 微信号不一定是 wxid_ 开头，需要找"微信号："标签后面的文本
        wxid = None
        try:
            # 方法1: 找"微信号："标签，然后取下一个 ContactProfileTextView 的值
            found_label = False
            for ctrl, depth in WalkControl(profile_card, includeTop=False, maxDepth=15):
                try:
                    ctrl_name = ctrl.Name or ""
                    ctrl_class = ctrl.ClassName or ""
                    
                    # 找到"微信号："标签
                    if "微信号" in ctrl_name:
                        found_label = True
                        logger.debug(f"找到微信号标签: '{ctrl_name}'")
                        continue
                    
                    # 标签后面的第一个 ContactProfileTextView 就是微信号
                    if found_label and ctrl_class == 'mmui::ContactProfileTextView':
                        wxid = ctrl_name.strip()
                        logger.info(f"找到微信号: {wxid}")
                        break
                except:
                    pass

            # 方法2: 如果没找到，尝试找"微信号："标签的兄弟控件
            if not wxid:
                # 遍历查找包含"微信号："的 XTextView，然后找同一父容器中的 ContactProfileTextView
                for ctrl, depth in WalkControl(profile_card, includeTop=False, maxDepth=15):
                    try:
                        ctrl_name = ctrl.Name or ""
                        if "微信号" in ctrl_name:
                            # 获取父容器
                            parent = ctrl.GetParentControl()
                            if parent:
                                # 遍历父容器的子控件
                                for child in parent.GetChildren():
                                    child_class = child.ClassName or ""
                                    child_name = child.Name or ""
                                    if child_class == 'mmui::ContactProfileTextView' and child_name:
                                        # 确保不是标签本身
                                        if "微信号" not in child_name:
                                            wxid = child_name.strip()
                                            logger.info(f"通过兄弟控件找到微信号: {wxid}")
                                            break
                            if wxid:
                                break
                    except:
                        pass
        except Exception as e:
            logger.error(f"提取微信号失败: {e}")

        # 关闭资料卡
        self._close_popup()
        time.sleep(0.3)

        if not wxid:
            logger.warning(f"未能在资料卡中找到 {member_name} 的微信号")

        return wxid

    def _get_wxid_from_chat_window(self, expected_name: str) -> Optional[str]:
        """从私聊窗口或详情面板获取微信ID（当打开的是私聊而非资料卡时）。"""
        try:
            # 检查窗口标题
            window_name = self.root.Name or ""
            logger.debug(f"当前窗口标题: {window_name}")

            # 尝试直接在当前窗口中查找微信号（找"微信号："标签后面的文本）
            found_label = False
            for ctrl, depth in WalkControl(self.root, includeTop=False, maxDepth=20):
                try:
                    ctrl_name = ctrl.Name or ""
                    ctrl_class = ctrl.ClassName or ""
                    
                    if "微信号" in ctrl_name:
                        found_label = True
                        continue
                    
                    if found_label and ctrl_class == 'mmui::ContactProfileTextView':
                        wxid = ctrl_name.strip()
                        logger.info(f"在当前窗口找到微信号: {wxid}")
                        return wxid
                except:
                    pass

            # 如果当前窗口是私聊窗口，尝试打开详情面板
            if expected_name in window_name or window_name != "微信":
                logger.debug(f"可能打开了私聊窗口: {window_name}")

                # 尝试点击"聊天信息"按钮打开详情面板
                for btn_name in ['聊天信息', '信息', '详情']:
                    try:
                        btn = self.root.ButtonControl(Name=btn_name)
                        if btn.Exists(maxSearchSeconds=0.3):
                            logger.info(f"点击'{btn_name}'按钮")
                            btn.Click(simulateMove=False)
                            time.sleep(1.5)
                            break
                    except:
                        pass

                # 在详情面板中查找微信号（同样的逻辑）
                found_label = False
                for ctrl, depth in WalkControl(self.root, includeTop=False, maxDepth=20):
                    try:
                        ctrl_name = ctrl.Name or ""
                        ctrl_class = ctrl.ClassName or ""
                        
                        if "微信号" in ctrl_name:
                            found_label = True
                            continue
                        
                        if found_label and ctrl_class == 'mmui::ContactProfileTextView':
                            wxid = ctrl_name.strip()
                            logger.info(f"从详情面板找到微信号: {wxid}")
                            return wxid
                    except:
                        pass

        except Exception as e:
            logger.debug(f"从私聊窗口获取微信ID失败: {e}")

        return None

    def get_member_wxid(self, group_name: str, member_name: str) -> Optional[str]:
        """
        获取群成员的微信ID。

        通过点击成员头像打开资料卡，从资料卡中提取微信号。

        注意：如果要获取多个成员的微信ID，建议使用 get_all_members_wxid 方法，
        它会一次性打开群详情后遍历所有成员，效率更高。

        Args:
            group_name: 群名称
            member_name: 成员昵称

        Returns:
            Optional[str]: 成员的微信ID（如 wxid_xxx），如果未找到返回 None
        """
        logger.info(f"获取成员微信ID: {member_name} 在群 {group_name}")

        # 第1步：打开群详情面板并聚焦
        info_view = self._open_and_focus_group_detail(group_name)
        if not info_view:
            logger.error("打开群详情面板失败")
            return None

        time.sleep(0.5)

        # 第2步：获取成员列表
        member_list = self._get_member_list()
        if not member_list:
            logger.error("获取成员列表失败")
            return None

        # 第3步：滚动到可见区域（确保目标成员可见）
        # 先滚动到顶部
        self._scroll_list(member_list, delta=120 * 10, steps=5, step_delay=0.1, settle_time=0.5)

        time.sleep(1)  # 额外等待UI更新

        # 第4步：查找目标成员
        target_ctrl = None
        max_scroll_attempts = 30  # 增加滚动次数
        scroll_count = 0

        # 清理昵称中的空白字符
        clean_name = member_name.strip()
        logger.info(f"正在查找成员: '{clean_name}'")

        while scroll_count < max_scroll_attempts:
            # 在当前可见的成员中查找
            for child in member_list.GetChildren():
                try:
                    if child.ClassName == 'mmui::ChatMemberCell':
                        child_name = child.Name or ""
                        # 使用部分匹配，包含目标昵称即可
                        if clean_name and clean_name in child_name:
                            target_ctrl = child
                            logger.info(f"找到成员: '{child_name}' (目标: '{clean_name}')")
                            break
                except:
                    pass

            if target_ctrl:
                break

            # 未找到，向上滚动一行
            logger.debug(f"滚动第 {scroll_count + 1} 次，查找: '{clean_name}'")
            self._scroll_list(member_list, delta=-120, steps=1, step_delay=0.1, settle_time=0.5)
            scroll_count += 1
            time.sleep(0.2)  # 额外等待

        if not target_ctrl:
            logger.error(f"未在成员列表中找到: {member_name}")
            return None

        # 第5步：点击成员头像打开资料卡
        rect = target_ctrl.BoundingRectangle
        if not rect:
            logger.error("无法获取成员位置")
            return None

        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2

        logger.info(f"点击成员 {member_name} at ({center_x}, {center_y})")

        # 首先尝试右键菜单 -> "查看个人资料"（最可靠的方式）
        logger.debug("尝试方式1: 右键菜单")
        self._right_click_at_position(center_x, center_y)
        time.sleep(1)

        # 查找右键菜单
        context_menu = None
        for pattern in ['mmui::CPopupMenu', 'mmui::CMenu', 'mmui::PopupMenu']:
            try:
                menu = self.root.WindowControl(ClassName=pattern)
                if menu.Exists(maxSearchSeconds=0.5):
                    context_menu = menu
                    logger.debug(f"找到右键菜单: {pattern}")
                    break
            except:
                pass

        if context_menu:
            # 查找"查看个人资料"选项
            for ctrl, depth in WalkControl(context_menu, includeTop=False, maxDepth=5):
                try:
                    name = ctrl.Name or ""
                    if "查看个人资料" in name or "查看资料" in name:
                        logger.info("找到'查看个人资料'选项，点击")
                        ctrl.Click(simulateMove=False)
                        time.sleep(1.5)
                        break
                except:
                    pass
        else:
            # 如果没有右键菜单，尝试直接单击
            logger.debug("尝试方式2: 直接单击")
            self._close_popup()
            time.sleep(0.3)
            self._click_at_position(center_x, center_y)
            time.sleep(1.5)

        # 第6步：查找资料卡窗口
        profile_card = None
        profile_patterns = [
            'mmui::ProfileUniquePop',
            'mmui::ContactProfileView',
            'mmui::ProfileCardView',
        ]

        for pattern in profile_patterns:
            try:
                ctrl = self.root.WindowControl(ClassName=pattern)
                if ctrl.Exists(maxSearchSeconds=0.5):
                    profile_card = ctrl
                    logger.debug(f"找到资料卡窗口: {pattern}")
                    break
            except:
                pass

        # 如果没有找到资料卡，可能打开了私聊窗口
        if not profile_card:
            logger.debug("未找到资料卡，检查是否打开了私聊窗口")
            # 私聊窗口的名称就是成员昵称
            try:
                window_name = self.root.Name
                if window_name and window_name != self._get_group_display_name(group_name):
                    logger.info(f"打开了私聊窗口: {window_name}")
                    # 在私聊窗口中查找"更多信息"或直接从UI中查找微信ID
                    # 先尝试按两次ESC回到群聊
                    self._close_popup()
                    time.sleep(0.5)
                    # 关闭私聊后重新打开群详情
                    info_view = self._open_and_focus_group_detail(group_name)
                    if info_view:
                        time.sleep(0.5)
                        # 在群详情中查找该成员，尝试其他方式
                        pass
            except:
                pass

        if not profile_card:
            logger.error("未找到资料卡窗口")
            self._close_popup()
            return None

        # 第7步：从资料卡中提取微信号
        wxid = None

        try:
            # 深度搜索微信号控件（只匹配以 wxid_ 开头的）
            for ctrl, depth in WalkControl(profile_card, includeTop=False, maxDepth=10):
                try:
                    if ctrl.ClassName == 'mmui::ContactProfileTextView':
                        name = ctrl.Name or ""
                        # 微信号必须以 wxid_ 开头
                        if name.startswith('wxid_'):
                            wxid = name
                            logger.debug(f"找到微信号: {wxid}")
                            break
                except:
                    pass
        except Exception as e:
            logger.error(f"提取微信号失败: {e}")

        # 第8步：关闭资料卡
        self._close_popup()

        if wxid:
            logger.info(f"成功获取 {member_name} 的微信ID: {wxid}")
        else:
            logger.warning(f"未能获取 {member_name} 的微信ID（可能未公开）")

        return wxid

    def _close_popup(self) -> None:
        """关闭弹出的资料卡或其他弹窗（按 ESC）"""
        try:
            win32api.keybd_event(win32con.VK_ESCAPE, 0, 0, 0)
            time.sleep(0.1)
            win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"关闭弹窗失败: {e}")

    def _open_group_detail(self) -> bool:
        """打开群详情面板。"""
        # 尝试多个可能的按钮名称以兼容不同微信版本
        possible_names = ['聊天信息', '群聊信息', '信息', '详情']

        info_btn = None
        for name in possible_names:
            try:
                btn = self.root.ButtonControl(Name=name)
                if btn.Exists(maxSearchSeconds=0.5):
                    info_btn = btn
                    break
            except Exception:
                continue

        if not info_btn:
            logger.error("聊天信息 button not found")
            return False

        try:
            info_btn.Click(simulateMove=False)
        except Exception as e:
            logger.debug(f"Click 点击失败，尝试 SetFocus: {e}")
            try:
                info_btn.SetFocus()
                import win32con
                win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception as e2:
                logger.error(f"打开群详情失败: {e2}")
                return False

        time.sleep(1.5)
        return True

    def _click_announcement_button(self) -> bool:
        """通过 Tab 导航点击群详情面板中的群公告按钮。"""
        info_view = self._get_group_detail_view(timeout=2)
        if not info_view:
            return False

        # 聚焦面板但不点击（避免触发子控件）
        info_view.SetFocus()
        time.sleep(0.3)

        # 使用 Tab 导航 + GetFocusedControl 查找"群公告"按钮
        logger.info("通过 Tab 导航查找'群公告'按钮...")

        for tab_count in range(30):
            self._press_key(win32con.VK_TAB, hold_time=0.05)
            time.sleep(0.3)

            focused = GetFocusedControl()
            if focused is None:
                continue

            name = focused.Name or ""
            if "群公告" in name:
                logger.info(f"在第 {tab_count + 1} 次 Tab 找到'群公告'")
                self._press_key(win32con.VK_RETURN)
                time.sleep(2)
                return True

        logger.error("未找到'群公告'按钮")
        return False

    def _click_edit_button(self, popup) -> bool:
        """点击'编辑群公告'按钮（如果显示了已有公告）。

        使用 Tab 导航查找并用 Enter 激活按钮。
        """
        # 首先检查是否已在编辑模式（宽编辑框）
        possible_ids = ['xeditorInputId', 'announcement_input', 'edit_input', 'input_field']
        in_edit_mode = False

        for auto_id in possible_ids:
            try:
                edit = popup.EditControl(AutomationId=auto_id)
                if edit.Exists(maxSearchSeconds=0.3):
                    rect = edit.BoundingRectangle
                    if rect and (rect.right - rect.left) > 50:
                        logger.debug("已处于编辑模式")
                        in_edit_mode = True
                        break
            except Exception:
                continue

        if in_edit_mode:
            return True

        # 使用 Tab + Enter 激活编辑按钮
        return self._find_and_activate_button(popup, '编辑群公告')

    def _input_announcement_content(self, popup, content: str = None, paste_from_clipboard: bool = False) -> bool:
        """将公告内容输入到编辑字段中（通过剪贴板粘贴）。

        Args:
            popup: 弹窗控件
            content: 要粘贴的文本内容（paste_from_clipboard 为 True 时忽略）
            paste_from_clipboard: 为 True 时直接从当前剪贴板内容粘贴
        """
        # 尝试多个可能的 AutomationId 以兼容不同微信版本
        possible_ids = ['xeditorInputId', 'announcement_input', 'edit_input', 'input_field']
        possible_class_names = ['mmui::XTextEdit', 'mmui::XValidatorTextEdit', 'mmui::XEditEx']

        edit = None
        for auto_id in possible_ids:
            try:
                e = popup.EditControl(AutomationId=auto_id)
                if e.Exists(maxSearchSeconds=0.5):
                    edit = e
                    break
            except Exception:
                continue

        if not edit:
            for class_name in possible_class_names:
                try:
                    e = popup.EditControl(ClassName=class_name)
                    if e.Exists(maxSearchSeconds=0.5):
                        edit = e
                        break
                except Exception:
                    continue

        if not edit:
            logger.error("未找到公告编辑字段")
            return False

        try:
            edit.Click(simulateMove=False)
        except Exception:
            try:
                edit.SetFocus()
            except Exception:
                pass

        time.sleep(0.3)

        self._send_ctrl_combo(0x41, settle_time=0.2)

        # 将内容复制到剪贴板（除非直接从已有剪贴板粘贴）
        if not paste_from_clipboard and content:
            import pyperclip
            pyperclip.copy(content)
            time.sleep(0.15)

        self._send_ctrl_combo(0x56, settle_time=0.4)

        return True

    def _click_complete_button(self, hwnd: int) -> bool:
        """通过 Tab + Enter 点击群公告弹窗中的'完成'按钮。"""
        popup = control_from_handle(hwnd)

        if not popup:
            logger.error("无法获取弹窗控件以点击完成按钮")
            return False

        # 使用 Tab + Enter 激活完成按钮
        return self._find_and_activate_button(popup, '完成')

    def _click_publish_button(self, popup) -> bool:
        """点击确认对话框中的'发布'按钮。"""
        # 先查找'取消'按钮
        all_controls = self._walk_controls(popup, max_depth=15)

        cancel_btn = None
        for ctrl in all_controls:
            name = ctrl.Name or ""
            auto_id = ctrl.AutomationId or ""
            if '取消' in name or auto_id == 'js_wrap_btn':
                cancel_btn = ctrl
                break

        if not cancel_btn:
            logger.error("未找到确认对话框")
            return False

        rect = cancel_btn.BoundingRectangle
        btn_width = rect.right - rect.left
        gap = 20

        # '发布'按钮在'取消'按钮右侧
        publish_x = rect.right + gap + btn_width // 2
        publish_y = (rect.top + rect.bottom) // 2

        logger.debug(f"点击'发布'按钮位置 ({publish_x}, {publish_y})")
        self._click_at_position(publish_x, publish_y)
        time.sleep(2)
        return True

    def _has_existing_announcement(self, popup, max_tabs: int = 15) -> bool:
        """检测弹窗中是否存在已有公告的编辑操作。"""
        self._focus_control_center(popup)

        for _ in range(max_tabs):
            self._press_key(win32con.VK_TAB)
            time.sleep(0.2)
            for ctrl in self._walk_controls(popup):
                if ctrl.Name == '编辑群公告':
                    return True
        return False

    def modify_announcement_simple(self, group_name: str, announcement: str = None, paste_from_clipboard: bool = False) -> bool:
        """
        简单的群公告修改。

        如果群还没有公告：直接输入 → 完成 → 发布
        如果群已有公告：触发编辑按钮 → 输入 → 完成 → 发布

        用法:
            wx.group_manager.modify_announcement_simple("群名", "新公告内容")
        """
        logger.info(f"修改群公告: {group_name}")

        # 第1步：打开并聚焦群详情面板
        if not self._open_and_focus_group_detail(group_name):
            return False

        # 第2步：点击群公告按钮
        if not self._click_announcement_button():
            return False

        # 第3步：查找群公告弹窗
        popup, hwnd = self._get_announcement_popup()
        if not popup:
            return False

        # 第4步：通过 Tab 导航检查是否有已有内容
        has_existing_content = self._has_existing_announcement(popup)

        logger.info(f"是否有已有内容: {has_existing_content}")

        # 第5步：如果有已有内容，先触发编辑按钮
        if has_existing_content:
            logger.info("触发编辑按钮处理已有公告...")
            # Tab 导航已找到编辑按钮，直接按 Enter 激活
            self._press_key(win32con.VK_RETURN)
            time.sleep(1)

        # 第6步：输入公告内容
        if not self._input_announcement_content(popup, announcement, paste_from_clipboard):
            return False

        # 第7步：点击"完成"按钮
        if not self._click_complete_button(hwnd):
            return False

        # 第8步：点击确认对话框中的"发布"按钮
        if not self._click_publish_button(popup):
            return False

        logger.info(f"群公告修改成功: {group_name}")
        self._minimize_window()
        return True

    def modify_announcement(self, group_name: str, announcement: str) -> bool:
        """
        修改群公告。

        Args:
            group_name: 群名称
            announcement: 新公告内容

        Returns:
            bool: 成功时返回 True
        """
        return self.modify_announcement_simple(
            group_name=group_name,
            announcement=announcement,
            paste_from_clipboard=False,
        )

    def set_announcement_from_markdown(self, group_name: str, md_file_path: str) -> bool:
        """
        从 Markdown 文件设置群公告。

        将 Markdown 转换为 HTML 并粘贴以保留格式。
        支持表格、列表、标题和图片。

        Args:
            group_name: 群名称
            md_file_path: Markdown 文件路径

        Returns:
            bool: 成功时返回 True

        用法:
            wx.group_manager.set_announcement_from_markdown(
                "测试群",
                "path/to/announcement.md"
            )
        """
        from ..utils.markdown_utils import (
            read_markdown_file,
            markdown_to_html,
            copy_html_to_clipboard
        )

        logger.info(f"从文件设置群公告: {md_file_path}")

        # 读取 Markdown 文件
        md_content = read_markdown_file(md_file_path)

        # 转换为 HTML
        html_content = markdown_to_html(md_content)

        # 将 HTML 复制到剪贴板
        if not copy_html_to_clipboard(html_content):
            logger.error("复制 HTML 到剪贴板失败")
            return False

        logger.info("HTML 已复制到剪贴板")

        # 使用从剪贴板粘贴模式
        return self.modify_announcement_simple(
            group_name=group_name,
            paste_from_clipboard=True
        )

    def _tab_to_control(self, target_name: str, max_tabs: int = 30):
        """
        通过 Tab 导航直到目标控件获得键盘焦点。
        使用 GetFocusedControl() 精确检测虚拟化控件。

        找到时返回聚焦的控件，否则返回 None。
        调用方可作为布尔值使用：`if not self._tab_to_control(...)`。
        """
        for i in range(max_tabs):
            self._press_key(win32con.VK_TAB, hold_time=0.05)
            time.sleep(0.3)

            focused = GetFocusedControl()
            if focused and target_name in (focused.Name or ""):
                logger.info(f"在第 {i + 1} 次 Tab 找到 '{target_name}'")
                return focused

        logger.error(f"经过 {max_tabs} 次 Tab 后未找到 '{target_name}'")
        return None

    def set_group_nickname(self, group_name: str, nickname: str) -> bool:
        """
        设置我在群聊中的昵称。

        流程:
          1. 打开群聊 → 打开详情面板
          2. Tab 导航到'我在本群的昵称' → Enter 激活内联编辑
          3. Ctrl+A + 输入昵称 + Enter
          4. 点击确认对话框中的'修改'

        Args:
            group_name: 群名称
            nickname:   要设置的新昵称

        Returns:
            bool: 成功时返回 True
        """
        import pyperclip

        logger.info(f"设置群昵称 '{nickname}' 在群: {group_name}")

        # 第1步：打开并聚焦群详情面板
        if not self._open_and_focus_group_detail(group_name):
            return False

        # 第2步：Tab 导航到"我在本群的昵称"
        if not self._tab_to_control('我在本群的昵称'):
            return False

        # 第3步：Enter → 激活内联编辑
        self._press_key(win32con.VK_RETURN)
        time.sleep(0.5)

        # 第4步：Ctrl+A 全选已有文本，然后粘贴新昵称
        self._send_ctrl_combo(0x41, settle_time=0.2)

        pyperclip.copy(nickname)
        time.sleep(0.1)
        self._send_ctrl_combo(0x56, settle_time=0.3)

        # 第5步：Enter → 提交 → 触发确认对话框
        self._press_key(win32con.VK_RETURN)
        time.sleep(1)

        # 第6步：在确认对话框中查找"修改"按钮（嵌入在主窗口中）
        confirm_btn = self._find_button_with_deadline('修改')
        if not confirm_btn:
            logger.error("未找到昵称确认对话框")
            return False

        confirm_btn.Click()
        logger.info(f"群昵称已设置为 '{nickname}'")
        time.sleep(1)
        self._minimize_window()
        return True

    def get_group_nickname(self, group_name: str) -> Optional[str]:
        """
        获取我在群聊中的昵称。

        复用设置群昵称的同一条路径：打开群详情面板，Tab 定位到
        "我在本群的昵称"，再尽量从当前控件或内联编辑框读取值。

        Args:
            group_name: 群名称

        Returns:
            Optional[str]: 读取成功返回群昵称，失败返回 None。
        """
        logger.info(f"获取我在群 '{group_name}' 中的昵称")

        if not self._open_and_focus_group_detail(group_name):
            return None

        ctrl = self._tab_to_control('我在本群的昵称')
        if not ctrl:
            return None

        nickname = self._extract_group_nickname_from_control(ctrl)
        if nickname:
            logger.info(f"读取到群昵称: {nickname}")
            return nickname

        # 有些版本需要进入内联编辑后，EditControl 才暴露当前昵称。
        try:
            self._press_key(win32con.VK_RETURN)
            time.sleep(0.5)
            focused = GetFocusedControl()
            nickname = self._extract_group_nickname_from_control(focused)
            self._press_key(win32con.VK_ESCAPE)
            if nickname:
                logger.info(f"从内联编辑框读取到群昵称: {nickname}")
                return nickname
        except Exception as exc:
            logger.debug(f"从内联编辑框读取群昵称失败: {exc}")

        logger.warning(f"未能读取群昵称: {group_name}")
        return None

    def _extract_group_nickname_from_control(self, ctrl) -> Optional[str]:
        """从聚焦控件中提取群昵称。"""
        if not ctrl:
            return None

        try:
            pattern = ctrl.GetPattern(PatternId.ValuePattern)
            if pattern:
                value = (pattern.Value or "").strip()
                if value and value != "我在本群的昵称":
                    return value
        except Exception:
            pass

        try:
            name = (ctrl.Name or "").strip()
        except Exception:
            return None

        if not name:
            return None

        marker = "我在本群的昵称"
        if marker not in name:
            return name

        parts = [
            part.strip()
            for part in name.replace("\r", "\n").split("\n")
            if part.strip() and part.strip() != marker
        ]
        if parts:
            return parts[-1]

        compact = name.replace(marker, "").strip(" ：:\n\t")
        return compact or None

    def _set_toggle_in_detail_panel(self, group_name: str, control_name: str, enable: bool) -> bool:
        """
        打开群详情面板并按名称设置开关控件（CheckBoxControl）。

        用于 消息免打扰 / 置顶聊天。
        如果当前状态已与目标状态一致则不执行操作。
        """
        logger.info(f"设置 '{control_name}'={'开启' if enable else '关闭'} 群: {group_name}")

        # 第1步：打开并聚焦群详情面板
        if not self._open_and_focus_group_detail(group_name):
            return False

        # 第2步：Tab 导航到目标开关控件
        ctrl = self._tab_to_control(control_name)
        if not ctrl:
            return False

        # 第3步：读取当前状态
        p = ctrl.GetPattern(PatternId.TogglePattern)
        if not p:
            logger.error(f"'{control_name}' 不支持 TogglePattern")
            return False

        current = p.ToggleState == ToggleState.On
        if current == enable:
            logger.info(f"'{control_name}' 已经是{'开启' if enable else '关闭'}状态，无需操作")
            return True

        # 第4步：按空格键切换（Qt 的 TogglePattern.Toggle() 无效）
        self._press_key(win32con.VK_SPACE)
        time.sleep(0.5)

        # 第5步：重新读取焦点以验证
        new_ctrl = GetFocusedControl()
        if new_ctrl:
            new_p = new_ctrl.GetPattern(PatternId.TogglePattern)
            new_state = new_p.ToggleState == ToggleState.On if new_p else enable
            if new_state != enable:
                logger.error(f"'{control_name}' toggle failed, state is still {'开启' if new_state else '关闭'}")
                return False

        logger.info(f"'{control_name}' set to {'开启' if enable else '关闭'} successfully")
        self._minimize_window()
        return True

    def set_do_not_disturb(self, group_name: str, enable: bool) -> bool:
        """
        启用或禁用群的消息免打扰。

        Args:
            group_name: 群名称
            enable: True 启用，False 禁用
        """
        return self._set_toggle_in_detail_panel(group_name, '消息免打扰', enable)

    def set_pin_chat(self, group_name: str, enable: bool) -> bool:
        """
        启用或禁用群的置顶聊天。

        Args:
            group_name: 群名称
            enable: True 置顶，False 取消置顶
        """
        return self._set_toggle_in_detail_panel(group_name, '置顶聊天', enable)
