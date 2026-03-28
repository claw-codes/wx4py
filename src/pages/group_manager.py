# -*- coding: utf-8 -*-
"""Group management functionality for WeChat"""
import time
import win32gui
import win32api
import win32con
from typing import Optional

from .base import BasePage
from ..utils.logger import get_logger
from ..core.uiautomation import ControlFromHandle as control_from_handle, GetFocusedControl, PatternId, ToggleState

logger = get_logger(__name__)


class GroupManager(BasePage):
    """
    Group management operations.

    Usage:
        wx = WeChatClient()
        wx.connect()

        # Modify group announcement
        wx.group_manager.modify_announcement("测试群", "新公告内容")
    """

    # Relative position ratios for "完成" button in announcement popup
    COMPLETE_BTN_X_RATIO = 0.90  # 90% from left edge
    COMPLETE_BTN_Y_RATIO = 0.09  # 9% from top edge (below title bar)

    def __init__(self, window):
        super().__init__(window)

    def _find_announcement_window(self) -> Optional[dict]:
        """Find announcement popup window"""
        windows = []

        def enum_callback(hwnd, results):
            title = win32gui.GetWindowText(hwnd)
            if '公告' in title:
                results.append({'hwnd': hwnd, 'title': title})

        win32gui.EnumWindows(enum_callback, windows)
        return windows[0] if windows else None

    def _click_at_position(self, x: int, y: int):
        """Click at screen coordinates"""
        print(f"[CLICK] Position: ({x}, {y})")
        win32api.SetCursorPos((x, y))
        time.sleep(0.2)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _find_and_activate_button(self, popup, button_name: str) -> bool:
        """
        Find a button by Tab navigation and activate it with Enter key.

        Args:
            popup: The popup control
            button_name: Name of the button to find (e.g., '完成', '编辑群公告', '发布')

        Returns:
            bool: True if button found and activated
        """
        logger.info(f"Looking for '{button_name}' button via Tab navigation...")

        # Focus popup
        popup_rect = popup.BoundingRectangle
        if popup_rect:
            center_x = (popup_rect.left + popup_rect.right) // 2
            center_y = (popup_rect.top + popup_rect.bottom) // 2
            self._click_at_position(center_x, center_y)
            time.sleep(0.5)

        # Tab through controls to find the button
        for tab_count in range(20):
            print(f"[TAB] Navigation #{tab_count + 1}...")

            # Send Tab key
            win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)
            time.sleep(0.15)
            win32api.keybd_event(win32con.VK_TAB, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)

            # Check if target button is now visible
            all_controls = []

            def find_controls(ctrl, results, depth=0):
                if depth > 20:
                    return
                results.append(ctrl)
                try:
                    for child in ctrl.GetChildren():
                        find_controls(child, results, depth + 1)
                except:
                    pass

            find_controls(popup, all_controls)

            for ctrl in all_controls:
                if ctrl.Name == button_name:
                    print(f"[FOUND] '{button_name}' at Tab #{tab_count + 1}")
                    logger.info(f"Found '{button_name}' button at Tab #{tab_count + 1}")

                    # Try both Space and Enter to activate it
                    for key_name, key_code in [("Space", win32con.VK_SPACE), ("Return", win32con.VK_RETURN)]:
                        print(f"[ACTION] Pressing {key_name} to activate '{button_name}'...")
                        logger.info(f"Pressing {key_name} to activate '{button_name}'...")

                        win32api.keybd_event(key_code, 0, 0, 0)
                        time.sleep(0.1)
                        win32api.keybd_event(key_code, 0, win32con.KEYEVENTF_KEYUP, 0)
                        time.sleep(0.5)

                    print(f"[SUCCESS] '{button_name}' activated!")
                    time.sleep(1)
                    return True

        print(f"[FAIL] Could not find '{button_name}' button after 20 tabs")
        logger.error(f"Could not find '{button_name}' button")
        return False

    def get_group_members(self, group_name: str) -> list:
        """
        Get all members of a group chat.

        Clicks 聊天信息 to open the detail panel, triggers 查看更多 (if present)
        via Tab navigation to expand the full member list, then scrolls through
        the QFReuseGridWidget to collect all visible members.

        Args:
            group_name: Name of the group

        Returns:
            list[str]: Member display names (昵称 or 备注名)
        """
        from .chat_window import ChatWindow

        logger.info(f"Getting members for group: {group_name}")

        # Step 1: Open group
        chat_window = ChatWindow(self._window)
        if not chat_window.open_chat(group_name, target_type='group'):
            logger.error(f"Failed to open group: {group_name}")
            return []
        time.sleep(1)

        # Step 2: Open group detail panel
        if not self._open_group_detail():
            return []

        # Step 3: Find detail panel and try to expand via 查看更多
        info_view = self.root.GroupControl(ClassName='mmui::ChatRoomMemberInfoView')
        if not info_view.Exists(maxSearchSeconds=2):
            logger.error("ChatRoomMemberInfoView not found")
            return []

        info_view.SetFocus()
        time.sleep(0.3)

        # Tab to 查看更多 (virtualized, FindFirst won't work)
        for i in range(10):
            win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(win32con.VK_TAB, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            focused = GetFocusedControl()
            if focused and '查看更多' in (focused.Name or ''):
                logger.info(f"Found 查看更多 at Tab #{i + 1}, triggering...")
                win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
                time.sleep(0.1)
                win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(1)
                break
        else:
            logger.info("查看更多 not found, collecting visible members only")

        # Step 4: Find member list by AutomationId (works after expand too)
        member_list = self.root.ListControl(AutomationId='chat_member_list')
        if not member_list.Exists(maxSearchSeconds=2):
            logger.error("chat_member_list not found")
            return []

        # Step 5: Scroll and collect all members
        rect = member_list.BoundingRectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2

        # Scroll to top first
        win32api.SetCursorPos((cx, cy))
        for _ in range(10):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 120 * 3, 0)
            time.sleep(0.1)
        time.sleep(0.5)

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

            # Scroll one row at a time and wait for Qt to render
            win32api.SetCursorPos((cx, cy))
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, -120, 0)
            time.sleep(0.6)

        members = sorted(all_members)
        logger.info(f"Collected {len(members)} members from group: {group_name}")
        return members

    def _open_group_detail(self) -> bool:
        """Open group detail panel"""
        info_btn = self.root.ButtonControl(Name='聊天信息')
        if not info_btn.Exists(maxSearchSeconds=2):
            logger.error("聊天信息 button not found")
            return False

        info_btn.Click()
        time.sleep(2)
        return True

    def _click_announcement_button(self) -> bool:
        """Click announcement button in group detail panel using Tab navigation"""
        info_view = self.root.GroupControl(ClassName='mmui::ChatRoomMemberInfoView')
        if not info_view.Exists():
            logger.error("ChatRoomMemberInfoView not found")
            return False

        # Focus the panel without clicking (avoids triggering child controls)
        info_view.SetFocus()
        time.sleep(0.3)

        # Use Tab navigation + GetFocusedControl to find "群公告" button
        logger.info("Looking for '群公告' button via Tab navigation...")

        for tab_count in range(30):
            win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(win32con.VK_TAB, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)

            focused = GetFocusedControl()
            if focused is None:
                continue

            name = focused.Name or ""
            if "群公告" in name:
                logger.info(f"Found '群公告' at Tab #{tab_count + 1}")
                win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
                time.sleep(0.1)
                win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(2)
                return True

        logger.error("Could not find '群公告' button")
        return False

    def _click_edit_button(self, popup) -> bool:
        """Click '编辑群公告' button if existing announcement is shown.

        Uses Tab navigation to find and Enter to activate the button.
        """
        # First, check if we're already in edit mode (wide edit box)
        edit = popup.EditControl(AutomationId='xeditorInputId')
        if edit and edit.Exists(maxSearchSeconds=1):
            rect = edit.BoundingRectangle
            if rect and (rect.right - rect.left) > 50:
                logger.debug("Already in edit mode")
                return True

        # Use Tab + Enter to activate edit button
        return self._find_and_activate_button(popup, '编辑群公告')

    def _input_announcement_content(self, popup, content: str = None, paste_from_clipboard: bool = False) -> bool:
        """Input announcement content into edit field using clipboard paste

        Args:
            popup: The popup control
            content: Text content to paste (ignored if paste_from_clipboard is True)
            paste_from_clipboard: If True, paste directly from current clipboard content
        """
        edit = popup.EditControl(AutomationId='xeditorInputId')
        if not edit.Exists(maxSearchSeconds=2):
            logger.error("Announcement edit field not found")
            return False

        edit.Click()
        time.sleep(0.5)

        # Select all first (Ctrl+A)
        VK_A = 0x41
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(VK_A, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(VK_A, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.3)

        # Copy content to clipboard (unless pasting from existing clipboard)
        if not paste_from_clipboard and content:
            import pyperclip
            pyperclip.copy(content)
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

        return True

    def _click_complete_button(self, hwnd: int) -> bool:
        """Click '完成' button in announcement popup using Tab + Enter"""
        popup = control_from_handle(hwnd)

        if not popup:
            logger.error("Could not get popup control for complete button")
            return False

        # Use Tab + Enter to activate complete button
        return self._find_and_activate_button(popup, '完成')

    def _click_publish_button(self, popup) -> bool:
        """Click '发布' button in confirm dialog"""
        # Find '取消' button first
        all_controls = []
        def find_controls(ctrl, results, depth=0):
            if depth > 15:
                return
            results.append(ctrl)
            for child in ctrl.GetChildren():
                find_controls(child, results, depth + 1)

        find_controls(popup, all_controls)

        cancel_btn = None
        for ctrl in all_controls:
            name = ctrl.Name or ""
            auto_id = ctrl.AutomationId or ""
            if '取消' in name or auto_id == 'js_wrap_btn':
                cancel_btn = ctrl
                break

        if not cancel_btn:
            logger.error("Confirm dialog not found")
            return False

        rect = cancel_btn.BoundingRectangle
        btn_width = rect.right - rect.left
        gap = 20

        # '发布' button is to the right of '取消'
        publish_x = rect.right + gap + btn_width // 2
        publish_y = (rect.top + rect.bottom) // 2

        logger.debug(f"Clicking '发布' at ({publish_x}, {publish_y})")
        self._click_at_position(publish_x, publish_y)
        time.sleep(2)
        return True

    def modify_announcement_simple(self, group_name: str, announcement: str = None, paste_from_clipboard: bool = False) -> bool:
        """
        Simple announcement modification.

        If group has no announcement yet: direct input, complete, publish
        If group has existing announcement: trigger edit button, input, complete, publish

        Usage:
            wx.group_manager.modify_announcement_simple("群名", "新公告内容")
        """
        from .chat_window import ChatWindow

        logger.info(f"Modifying announcement for group: {group_name}")

        # Step 1: Open group chat
        chat_window = ChatWindow(self._window)
        if not chat_window.open_chat(group_name, target_type='group'):
            logger.error(f"Failed to open group: {group_name}")
            return False

        time.sleep(1)

        # Step 2: Open group detail panel
        if not self._open_group_detail():
            return False

        # Step 3: Click announcement button
        if not self._click_announcement_button():
            return False

        # Step 4: Find announcement popup
        popup_info = self._find_announcement_window()
        if not popup_info:
            logger.error("Announcement popup not found")
            return False

        hwnd = popup_info['hwnd']
        popup = control_from_handle(hwnd)

        # Step 5: Check if there's existing content by Tab navigation
        # Tab through to find "编辑群公告" button
        print("[DEBUG] Checking for existing content via Tab navigation...")
        has_existing_content = False

        # Focus popup first
        popup_rect = popup.BoundingRectangle
        if popup_rect:
            center_x = (popup_rect.left + popup_rect.right) // 2
            center_y = (popup_rect.top + popup_rect.bottom) // 2
            self._click_at_position(center_x, center_y)
            time.sleep(0.3)

        # Tab through to find edit button
        for tab_count in range(15):
            win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)
            time.sleep(0.1)
            win32api.keybd_event(win32con.VK_TAB, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.2)

            # Check if edit button exists now
            all_controls = []
            def find_controls(ctrl, results, depth=0):
                if depth > 20:
                    return
                results.append(ctrl)
                try:
                    for child in ctrl.GetChildren():
                        find_controls(child, results, depth + 1)
                except:
                    pass

            find_controls(popup, all_controls)

            for ctrl in all_controls:
                if ctrl.Name == '编辑群公告':
                    has_existing_content = True
                    print(f"[DEBUG] Found edit button at Tab #{tab_count + 1}, has_existing_content=True")
                    break

            if has_existing_content:
                break

        print(f"[DEBUG] Final: has_existing_content={has_existing_content}")
        logger.info(f"Has existing content: {has_existing_content}")

        # Step 6: If there's existing content, trigger edit button first
        if has_existing_content:
            logger.info("Triggering edit button for existing announcement...")
            # Edit button is already visible from Tab navigation, just press Enter to activate
            win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
            time.sleep(0.1)
            win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(1)

        # Step 7: Input announcement content
        if not self._input_announcement_content(popup, announcement, paste_from_clipboard):
            return False

        # Step 8: Click "完成" button
        if not self._click_complete_button(hwnd):
            return False

        # Step 9: Click "发布" button in confirm dialog
        if not self._click_publish_button(popup):
            return False

        logger.info(f"Announcement modified successfully for group: {group_name}")
        return True

    def modify_announcement(self, group_name: str, announcement: str) -> bool:
        """
        Modify group announcement.

        Args:
            group_name: Name of the group
            announcement: New announcement content

        Returns:
            bool: True if successful
        """
        from .chat_window import ChatWindow

        logger.info(f"Modifying announcement for group: {group_name}")

        # Step 1: Open group chat
        chat_window = ChatWindow(self._window)
        if not chat_window.open_chat(group_name, target_type='group'):
            logger.error(f"Failed to open group: {group_name}")
            return False

        time.sleep(1)

        # Step 2: Open group detail panel
        if not self._open_group_detail():
            return False

        # Step 3: Click announcement button
        if not self._click_announcement_button():
            return False

        # Step 4: Find announcement popup
        popup_info = self._find_announcement_window()
        if not popup_info:
            logger.error("Announcement popup not found")
            return False

        hwnd = popup_info['hwnd']
        popup = control_from_handle(hwnd)

        # Step 5: Check if this is a new announcement or editing existing one
        edit_box = popup.EditControl(AutomationId='xeditorInputId')
        is_new_announcement = False

        if edit_box and edit_box.Exists(maxSearchSeconds=1):
            # Try to get the content by looking at the parent's text
            try:
                # Get all controls and look for the announcement content display
                all_controls = []
                def find_controls(ctrl, results, depth=0):
                    if depth > 20:
                        return
                    results.append(ctrl)
                    try:
                        for child in ctrl.GetChildren():
                            find_controls(child, results, depth + 1)
                    except:
                        pass

                find_controls(popup, all_controls)

                # Look for text control with announcement content
                has_content = False
                for ctrl in all_controls:
                    name = ctrl.Name or ""
                    # If there's a control with non-empty name that looks like announcement
                    if name and len(name) > 5 and "自动化" in name or "test" in name.lower():
                        has_content = True
                        logger.info(f"Found existing announcement content: {name[:50]}")
                        break

                if has_content:
                    is_new_announcement = False
                    logger.info("Editing existing announcement")
                else:
                    is_new_announcement = True
                    logger.info("New announcement (no existing content)")
            except:
                # Default to assuming it's new if we can't determine
                is_new_announcement = True

        # Step 6: If editing existing announcement, activate edit mode
        if not is_new_announcement:
            logger.info("Activating edit mode for existing announcement...")
            if not self._click_edit_button(popup):
                logger.error("Failed to activate edit mode")
                return False

        # Step 7: Input announcement content
        if not self._input_announcement_content(popup, announcement, paste_from_clipboard=False):
            return False

        # Step 8: Click "完成" button
        if not self._click_complete_button(hwnd):
            return False

        # Step 9: Click "发布" button in confirm dialog
        if not self._click_publish_button(popup):
            return False

        logger.info(f"Announcement modified successfully for group: {group_name}")
        return True
    def set_announcement_from_markdown(self, group_name: str, md_file_path: str) -> bool:
        """
        Set group announcement from a markdown file.

        Converts markdown to HTML and pastes it to preserve formatting.
        Supports tables, lists, headers, and images.

        Args:
            group_name: Name of the group
            md_file_path: Path to the markdown file

        Returns:
            bool: True if successful

        Usage:
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

        logger.info(f"Setting announcement from file: {md_file_path}")

        # Read markdown file
        md_content = read_markdown_file(md_file_path)

        # Convert to HTML
        html_content = markdown_to_html(md_content)

        # Copy HTML to clipboard
        if not copy_html_to_clipboard(html_content):
            logger.error("Failed to copy HTML to clipboard")
            return False

        logger.info("HTML copied to clipboard")

        # Use paste_from_clipboard mode
        return self.modify_announcement_simple(
            group_name=group_name,
            paste_from_clipboard=True
        )

    def _tab_to_control(self, target_name: str, max_tabs: int = 30):
        """
        Tab navigate until a control with target_name has keyboard focus.
        Uses GetFocusedControl() for accurate detection of virtualized controls.

        Returns the focused control if found, None otherwise.
        Callers can use as bool: `if not self._tab_to_control(...)`.
        """
        for i in range(max_tabs):
            win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(win32con.VK_TAB, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)

            focused = GetFocusedControl()
            if focused and target_name in (focused.Name or ""):
                logger.info(f"Found '{target_name}' at Tab #{i + 1}")
                return focused

        logger.error(f"Could not find '{target_name}' after {max_tabs} tabs")
        return None

    def set_group_nickname(self, group_name: str, nickname: str) -> bool:
        """
        Set my nickname in a group chat.

        Flow:
          1. Open group → open detail panel
          2. Tab to '我在本群的昵称' → Enter to activate inline edit
          3. Ctrl+A + type nickname + Enter
          4. Click '修改' in the confirmation dialog

        Args:
            group_name: Name of the group
            nickname:   New nickname to set

        Returns:
            bool: True if successful
        """
        from .chat_window import ChatWindow
        import pyperclip

        logger.info(f"Setting nickname '{nickname}' in group: {group_name}")

        # Step 1: Open group chat
        chat_window = ChatWindow(self._window)
        if not chat_window.open_chat(group_name, target_type='group'):
            logger.error(f"Failed to open group: {group_name}")
            return False
        time.sleep(1)

        # Step 2: Open group detail panel
        if not self._open_group_detail():
            return False

        # Step 3: Focus the detail panel
        info_view = self.root.GroupControl(ClassName='mmui::ChatRoomMemberInfoView')
        if not info_view.Exists(maxSearchSeconds=2):
            logger.error("ChatRoomMemberInfoView not found")
            return False

        # Focus the panel without clicking (avoids triggering child controls)
        info_view.SetFocus()
        time.sleep(0.3)

        # Step 4: Tab to "我在本群的昵称"
        if not self._tab_to_control('我在本群的昵称'):
            return False

        # Step 5: Enter → activate inline edit
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)

        # Step 6: Ctrl+A to select all existing text, then paste new nickname
        VK_A = 0x41
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(VK_A, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(VK_A, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)

        pyperclip.copy(nickname)
        time.sleep(0.1)
        VK_V = 0x56
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.3)

        # Step 7: Enter → submit → triggers confirmation dialog
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(1)

        # Step 8: Find "修改" button in the confirmation dialog (embedded in main window)
        deadline = time.time() + 3.0
        confirm_btn = None
        while time.time() < deadline:
            btn = self.root.ButtonControl(Name='修改')
            if btn.Exists(maxSearchSeconds=0.2):
                confirm_btn = btn
                break
            time.sleep(0.2)

        if not confirm_btn:
            logger.error("Nickname confirmation dialog not found")
            return False

        confirm_btn.Click()
        logger.info(f"Nickname set to '{nickname}' successfully")
        time.sleep(1)
        return True

    def _set_toggle_in_detail_panel(self, group_name: str, control_name: str, enable: bool) -> bool:
        """
        Open group detail panel and set a toggle switch (CheckBoxControl) by name.

        Used for 消息免打扰 / 置顶聊天.
        Does nothing if the current state already matches the desired state.
        """
        from .chat_window import ChatWindow

        logger.info(f"Setting '{control_name}'={'开启' if enable else '关闭'} for group: {group_name}")

        # Step 1: Open group
        chat_window = ChatWindow(self._window)
        if not chat_window.open_chat(group_name, target_type='group'):
            logger.error(f"Failed to open group: {group_name}")
            return False
        time.sleep(1)

        # Step 2: Open group detail panel
        if not self._open_group_detail():
            return False

        # Step 3: Focus the detail panel
        info_view = self.root.GroupControl(ClassName='mmui::ChatRoomMemberInfoView')
        if not info_view.Exists(maxSearchSeconds=2):
            logger.error("ChatRoomMemberInfoView not found")
            return False
        info_view.SetFocus()
        time.sleep(0.3)

        # Step 4: Tab to the target toggle control
        ctrl = self._tab_to_control(control_name)
        if not ctrl:
            return False

        # Step 5: Read current state
        p = ctrl.GetPattern(PatternId.TogglePattern)
        if not p:
            logger.error(f"'{control_name}' does not support TogglePattern")
            return False

        current = p.ToggleState == ToggleState.On
        if current == enable:
            logger.info(f"'{control_name}' already {'开启' if enable else '关闭'}, no action needed")
            return True

        # Step 6: Press Space to toggle (Qt's TogglePattern.Toggle() is non-functional)
        win32api.keybd_event(win32con.VK_SPACE, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(win32con.VK_SPACE, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)

        # Step 7: Verify by re-reading focus
        new_ctrl = GetFocusedControl()
        if new_ctrl:
            new_p = new_ctrl.GetPattern(PatternId.TogglePattern)
            new_state = new_p.ToggleState == ToggleState.On if new_p else enable
            if new_state != enable:
                logger.error(f"'{control_name}' toggle failed, state is still {'开启' if new_state else '关闭'}")
                return False

        logger.info(f"'{control_name}' set to {'开启' if enable else '关闭'} successfully")
        return True

    def set_do_not_disturb(self, group_name: str, enable: bool) -> bool:
        """
        Enable or disable Do Not Disturb (消息免打扰) for a group.

        Args:
            group_name: Name of the group
            enable: True to enable, False to disable
        """
        return self._set_toggle_in_detail_panel(group_name, '消息免打扰', enable)

    def set_pin_chat(self, group_name: str, enable: bool) -> bool:
        """
        Enable or disable Pin Chat (置顶聊天) for a group.

        Args:
            group_name: Name of the group
            enable: True to pin, False to unpin
        """
        return self._set_toggle_in_detail_panel(group_name, '置顶聊天', enable)
