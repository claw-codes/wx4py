# -*- coding: utf-8 -*-
"""微信窗口管理"""
import time

from .uia_wrapper import UIAWrapper
from .exceptions import WeChatNotFoundError
from .win32 import (
    find_wechat_window,
    bring_window_to_front,
    get_window_title,
    get_window_class,
    is_window_visible,
    check_and_fix_registry,
    ensure_screen_reader_flag,
    restart_wechat_process,
)
from .tray import restore_wechat_from_native_tray
from ..utils.logger import get_logger
from ..config import OPERATION_INTERVAL
from . import uiautomation as uia

logger = get_logger(__name__)

# UIA 健康检查：控件树最少需要的节点数
# 正常微信窗口控件树远超此阈值；如果只有根窗口 + MMUIRenderSubWindowHW = 2 个节点，
# 说明 Qt 辅助功能未加载，需要重启微信。
_MIN_UIA_TREE_NODES = 5
_TRAY_SEARCH_TIMEOUT_SECONDS = 0.2
_TRAY_OVERFLOW_WAIT_SECONDS = 0.8
_TRAY_RESTORE_SETTLE_SECONDS = 0.5
_TRAY_POST_RESTORE_WAIT_SECONDS = 1.0
_TRAY_ICON_KEYWORDS = ("微信", "WeChat")
_TRAY_EXPAND_KEYWORDS = (
    "显示隐藏的图标",
    "Show hidden icons",
    "通知区域溢出",
    "通知 V 形",
    "V 形",
)


def _count_uia_descendants(ctrl, max_depth=4, limit=20):
    """快速递归统计控件树节点数，用于健康检查。

    Args:
        ctrl: 根控件
        max_depth: 最大递归深度
        limit: 达到此数量后提前返回（无需全部遍历）

    Returns:
        int: 发现的控件节点数
    """
    count = 0
    stack = [(ctrl, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count >= limit:
            return count
        if depth >= max_depth:
            continue
        try:
            children = node.GetChildren()
            if children:
                for ch in children:
                    stack.append((ch, depth + 1))
        except Exception:
            pass
    return count


def _should_restart_after_registry_fix(registry_status: str) -> bool:
    """判断注册表修复后是否必须重启微信。"""
    return registry_status == "fixed_zero"


class WeChatWindow:
    """微信窗口管理器"""

    def __init__(self):
        """初始化微信窗口管理器"""
        self._hwnd: int = None
        self._uia: UIAWrapper = None
        self._initialized = False

    @staticmethod
    def _safe_control_text(control, attr: str) -> str:
        """安全读取 UIA 控件属性。"""
        try:
            return str(getattr(control, attr, "") or "")
        except Exception:
            return ""

    @staticmethod
    def _get_control_children(control) -> list:
        """安全获取 UIA 子控件。"""
        try:
            return control.GetChildren()
        except Exception:
            return []

    def _is_wechat_tray_item(self, control) -> bool:
        """判断控件是否看起来像微信托盘图标。"""
        text = " ".join((
            self._safe_control_text(control, "Name"),
            self._safe_control_text(control, "ClassName"),
        )).strip()
        return bool(text) and any(keyword in text for keyword in _TRAY_ICON_KEYWORDS)

    def _is_tray_expand_button(self, control) -> bool:
        """判断控件是否是托盘隐藏区展开按钮。"""
        text = " ".join((
            self._safe_control_text(control, "Name"),
            self._safe_control_text(control, "ClassName"),
            self._safe_control_text(control, "ControlTypeName"),
        )).strip()
        if not text:
            return False
        if any(keyword in text for keyword in _TRAY_EXPAND_KEYWORDS):
            return True
        return (
            self._safe_control_text(control, "ClassName") in {"Button", "Chevron", "TrayChevron"}
            and "通知" in self._safe_control_text(control, "Name")
        )

    def _click_control(self, control, action_name: str) -> bool:
        """统一处理 UIA 控件点击日志。"""
        try:
            control.Click()
            logger.debug(f"{action_name}成功")
            return True
        except Exception as exc:
            logger.debug(f"{action_name}失败: {exc}")
            return False

    def _find_wechat_tray_item_in_toolbar(self, toolbar):
        """在任务栏工具栏中快速查找微信托盘图标。"""
        for child in self._get_control_children(toolbar):
            if self._is_wechat_tray_item(child):
                return child
        return None

    def _find_wechat_tray_item_in_tree(self, root, max_depth: int = 6):
        """遍历托盘控件树，兜底查找微信图标。"""
        try:
            for control, _depth in uia.WalkControl(root, includeTop=True, maxDepth=max_depth):
                if self._is_wechat_tray_item(control):
                    return control
        except Exception as exc:
            logger.debug(f"遍历托盘控件树失败: {exc}")
        return None

    def _find_wechat_tray_item_in_container(self, container):
        """在托盘容器中查找微信图标。"""
        for child in self._get_control_children(container):
            class_name = self._safe_control_text(child, "ClassName")
            control_type = self._safe_control_text(child, "ControlTypeName")
            if class_name == 'ToolbarWindow32' or control_type == 'ToolBarControl':
                candidate = self._find_wechat_tray_item_in_toolbar(child)
                if candidate:
                    return candidate
            if self._is_wechat_tray_item(child):
                return child
        return self._find_wechat_tray_item_in_tree(container)

    def _find_tray_expand_button(self, tray):
        """查找托盘隐藏区展开按钮。"""
        for child in self._get_control_children(tray):
            if self._is_tray_expand_button(child):
                return child
        return None

    def _get_tray_overflow_root(self):
        """获取托盘隐藏区窗口。"""
        candidates = [
            uia.PaneControl(searchDepth=1, ClassName='NotifyIconOverflowWindow'),
            uia.WindowControl(searchDepth=1, ClassName='NotifyIconOverflowWindow'),
        ]
        for candidate in candidates:
            if candidate.Exists(maxSearchSeconds=_TRAY_SEARCH_TIMEOUT_SECONDS):
                return candidate
        return None

    def _find_wechat_tray_item(self):
        """查找微信托盘图标，必要时自动展开隐藏区。"""
        tray = uia.PaneControl(searchDepth=3, ClassName='TrayNotifyWnd')
        if tray.Exists(maxSearchSeconds=_TRAY_SEARCH_TIMEOUT_SECONDS):
            candidate = self._find_wechat_tray_item_in_container(tray)
            if candidate:
                return candidate

            expand_button = self._find_tray_expand_button(tray)
            if expand_button and self._click_control(expand_button, "点击托盘展开按钮"):
                deadline = time.time() + _TRAY_OVERFLOW_WAIT_SECONDS
                while time.time() < deadline:
                    overflow = self._get_tray_overflow_root()
                    if overflow:
                        candidate = self._find_wechat_tray_item_in_container(overflow)
                        if candidate:
                            return candidate
                    time.sleep(0.1)

        overflow = self._get_tray_overflow_root()
        if overflow:
            return self._find_wechat_tray_item_in_container(overflow)
        return None

    def _restore_via_tray_icon(self) -> bool:
        """通过托盘图标恢复微信。"""
        restored = restore_wechat_from_native_tray()
        if restored:
            time.sleep(_TRAY_RESTORE_SETTLE_SECONDS)
            return True

        logger.debug("原生托盘消息恢复失败，尝试 UIA 托盘图标点击")
        tray_item = self._find_wechat_tray_item()
        if tray_item:
            logger.info("检测到微信主窗口不可见，尝试通过托盘图标恢复")
            if self._click_control(tray_item, "点击微信托盘图标"):
                time.sleep(_TRAY_RESTORE_SETTLE_SECONDS)
                return True
            logger.debug("UIA 托盘图标点击失败")

        logger.debug("未能通过托盘恢复微信窗口")
        return False

    def _activate_hwnd(self, hwnd: int) -> bool:
        """激活指定窗口，托盘隐藏时优先走托盘恢复。"""
        if not hwnd:
            return False

        if not is_window_visible(hwnd):
            if not self._restore_via_tray_icon():
                logger.warning("检测到微信窗口不可见，但未能通过托盘图标恢复，已跳过窗口兜底激活。")
                return False

            deadline = time.time() + _TRAY_OVERFLOW_WAIT_SECONDS
            while time.time() < deadline:
                refreshed_hwnd = find_wechat_window()
                if refreshed_hwnd and is_window_visible(refreshed_hwnd):
                    self._hwnd = refreshed_hwnd
                    time.sleep(_TRAY_POST_RESTORE_WAIT_SECONDS)
                    return True
                time.sleep(0.1)

            logger.warning("托盘图标点击后，微信窗口仍未恢复为可见状态。")
            return False

        return bring_window_to_front(hwnd)

    def _try_click_login_button(self, hwnd: int) -> bool:
        """
        尝试在登录界面点击"进入微信"按钮。

        当微信重启后显示登录界面（非主界面）时，
        尝试通过 UIA 查找并点击"进入微信"按钮。

        Args:
            hwnd: 微信窗口句柄

        Returns:
            bool: 成功点击按钮返回 True
        """
        try:
            # 尝试获取窗口的 UIA 控件
            root = uia.ControlFromHandle(hwnd)
            if not root:
                return False

            # 查找名称包含"进入微信"的按钮
            # 使用递归搜索查找所有子按钮
            def find_button(ctrl, depth=0):
                if depth > 10:  # 限制搜索深度（按钮可能在第8层）
                    return None

                # 检查当前控件是否是按钮
                try:
                    if ctrl.ControlTypeName == 'ButtonControl':
                        name = ctrl.Name or ""
                        if '进入微信' in name:
                            logger.debug(f"找到'进入微信'按钮，深度={depth}")
                            return ctrl
                except Exception:
                    pass

                # 递归搜索子控件
                try:
                    children = ctrl.GetChildren()
                    for child in children:
                        result = find_button(child, depth + 1)
                        if result:
                            return result
                except Exception:
                    pass

                return None

            button = find_button(root)
            if button:
                logger.info("检测到登录界面，尝试点击'进入微信'按钮...")
                try:
                    # 尝试多种点击方式
                    try:
                        button.Click()
                    except Exception:
                        try:
                            button.Click(simulateMove=False)
                        except Exception:
                            # 回退：尝试获取按钮位置并直接点击
                            try:
                                rect = button.BoundingRectangle
                                if rect:
                                    import win32api
                                    import win32con
                                    x = (rect.left + rect.right) // 2
                                    y = (rect.top + rect.bottom) // 2
                                    win32api.SetCursorPos((x, y))
                                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                                    time.sleep(0.1)
                                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                            except Exception:
                                pass

                    logger.info("已点击'进入微信'按钮，等待登录完成...")
                    return True
                except Exception as e:
                    logger.debug(f"点击登录按钮失败: {e}")
                    return False

            return False
        except Exception as e:
            logger.debug(f"尝试点击登录按钮异常: {e}")
            return False

    def _wait_for_main_window(self, timeout: int = 20):
        """等待微信主窗口出现。

        点击"进入微信"按钮后，微信会从登录窗口切换到主窗口，
        HWND 会改变，需要重新查找并绑定。

        Args:
            timeout: 最大等待时间（秒）
        """
        logger.info("等待微信主窗口出现...")
        for i in range(timeout):
            time.sleep(0.5)  # 缩短检测间隔
            hwnd = find_wechat_window()
            if hwnd:
                cls = get_window_class(hwnd)
                if 'MainWindow' in cls:
                    logger.info(f"主窗口已出现: HWND={hwnd}")
                    self._hwnd = hwnd
                    self._activate_hwnd(hwnd)
                    time.sleep(0.3)
                    return
                if i % 10 == 0:
                    logger.debug(f"等待登录完成... 当前窗口: {cls}")
        # 超时后尝试接受任何微信窗口
        hwnd = find_wechat_window()
        if hwnd:
            self._hwnd = hwnd
            logger.warning(f"未检测到 MainWindow，使用当前窗口: HWND={hwnd}")
        else:
            logger.warning("等待主窗口超时")

    def _restart_and_reconnect(self):
        """重启微信并等待重新连接。

        流程：
        1. 结束当前微信进程
        2. 等待新进程启动并出现窗口
        3. 重新绑定 UIA

        Raises:
            WeChatNotFoundError: 重启失败或等待超时时抛出
        """
        restarted = restart_wechat_process(self._hwnd)
        self.disconnect()
        if not restarted:
            raise WeChatNotFoundError(
                "辅助功能设置已变更但无法自动重启微信。"
                "请手动重启微信后重试。"
            )

        # 等待微信主窗口出现（最多等待 30 秒）
        # 微信重启后先出现 LoginWindow（登录界面），
        # 点击"进入微信"后才会变为 MainWindow，HWND 也会改变。
        logger.info("微信已重启，等待主窗口出现...")
        hwnd = None
        login_clicked = False
        login_button_clicked_at = None
        
        for i in range(30):
            time.sleep(1)
            hwnd = find_wechat_window()
            if hwnd:
                cls = get_window_class(hwnd)
                if 'MainWindow' in cls:
                    logger.debug(f"检测到主窗口: HWND={hwnd}, ClassName={cls}")
                    break
                # 检测是否是登录界面（非主窗口但是微信窗口）
                if not login_clicked and ('Login' in cls or 'Qt' in cls):
                    # 尝试点击"进入微信"按钮
                    if self._try_click_login_button(hwnd):
                        login_clicked = True
                        login_button_clicked_at = i
                        # 点击后继续等待，不重置 hwnd
                        continue
                # 仍然是登录窗口，继续等待
                if i % 5 == 0:
                    logger.debug(f"等待登录完成... 当前窗口: {cls}")
                hwnd = None  # 重置，继续等待主窗口

        if not hwnd:
            # 最后兜底：接受任何微信窗口
            hwnd = find_wechat_window()

        if not hwnd:
            raise WeChatNotFoundError(
                "微信已重启但主窗口未出现，请确认微信已登录后重试。"
            )

        # 等待窗口稳定
        self._activate_hwnd(hwnd)
        time.sleep(0.5)

        self._hwnd = hwnd
        logger.info(f"微信重启完成，新窗口: HWND={hwnd}")

        # 重新初始化 UIA，并多次重试健康检查
        # 微信登录完成后 Qt 可能需要额外时间来完全初始化 UIA 控件树
        node_count = 0
        for check in range(10):
            self._uia = UIAWrapper(self._hwnd)
            node_count = _count_uia_descendants(self._uia.root)
            logger.debug(f"重启后 UIA 健康检查 ({check + 1}/10): 节点数={node_count}")
            if node_count >= _MIN_UIA_TREE_NODES:
                self._initialized = True
                logger.info("成功连接到微信（重启后）")
                return
            time.sleep(0.5)  # 缩短等待间隔

        raise WeChatNotFoundError(
            f"微信重启后 UIA 控件树仍然为空（{node_count} 个节点）。"
            "请确认微信已完全登录并显示主界面后重试。"
        )

    def connect(self) -> bool:
        """
        连接微信窗口。

        流程：
        1. 修复辅助功能环境（注册表 + 屏幕阅读器标志）
        2. 查找并激活微信窗口
        3. 如有必要，重启并在内部完成重连
        4. 检查登录态并初始化 UIAutomation
        5. 记录 UIA 健康状态

        Returns:
            bool: 连接成功返回 True

        Raises:
            WeChatNotFoundError: 找不到微信窗口或重连失败时抛出
        """
        # 第1步：修复辅助功能环境。
        # 这里只会把环境修正到可用状态；是否必须重启微信，
        # 只取决于 RunningState 是否从 0 修复为 1。
        logger.info("正在检查辅助功能环境...")
        registry_status = "unchanged"
        try:
            registry_status = check_and_fix_registry()
            if registry_status == "fixed_zero":
                logger.info("注册表 RunningState 已从 0 修复为 1")
            elif registry_status == "created_missing":
                logger.info("注册表 RunningState 缺失，已创建为 1")
            else:
                logger.debug("注册表 RunningState 已正确设置")
        except Exception as e:
            logger.warning(f"注册表检查失败: {e}")

        # 第2步：修复当前系统会话中的屏幕阅读器标志。
        # 该标志用于帮助 Qt 应用暴露更完整的辅助功能树，
        # 但不作为“是否必须重启微信”的判断依据。
        try:
            screen_reader_changed = ensure_screen_reader_flag()
            if screen_reader_changed:
                logger.info("系统屏幕阅读器标志原为关闭，已开启")
            else:
                logger.debug("系统屏幕阅读器标志已处于开启状态")
        except Exception as e:
            logger.warning(f"屏幕阅读器标志检查失败: {e}")

        # 只有 RunningState 原值为 0 时，才要求重启微信使修复生效。
        settings_changed = _should_restart_after_registry_fix(registry_status)

        # 第3步：查找并激活微信窗口。
        logger.info("正在查找微信窗口...")
        self._hwnd = find_wechat_window()
        if not self._hwnd:
            raise WeChatNotFoundError(
                "未找到微信窗口，请确保微信正在运行。"
            )

        logger.info(f"找到微信窗口: HWND={self._hwnd}")
        self._activate_hwnd(self._hwnd)
        time.sleep(OPERATION_INTERVAL)

        # 第4步：如有必要，重启并在 _restart_and_reconnect 内部完成重连。
        if settings_changed:
            logger.warning("检测到 RunningState 原值为 0，正在重启微信以使修复生效...")
            self._restart_and_reconnect()
            return True

        # 第5步：检测是否仍停留在登录界面。
        cls = get_window_class(self._hwnd)
        if 'MainWindow' not in cls:
            logger.info(f"当前窗口不是主窗口（ClassName={cls}），检查是否在登录界面...")
            if self._try_click_login_button(self._hwnd):
                # 成功点击登录按钮后，等待主窗口出现并重新绑定。
                self._wait_for_main_window()

        # 第6步：初始化 UIAutomation。
        logger.info("正在初始化 UIAutomation...")
        self._uia = UIAWrapper(self._hwnd)

        # 第7步：记录 UIA 健康状态。
        # 这里只记录节点数，不再仅凭节点数直接触发重启。（检测准确度不够，即使这里检测只有1个节点，后续流程还是能正常走）
        node_count = _count_uia_descendants(self._uia.root)
        logger.debug(f"UIA 健康检查: 控件树节点数={node_count}")
        if node_count < _MIN_UIA_TREE_NODES:
            logger.warning(
                f"UIA 控件树较少（仅 {node_count} 个节点），"
                "继续按当前会话执行，不再仅凭该检测结果触发重启。"
            )

        self._initialized = True
        logger.info("成功连接到微信")
        return True

    def disconnect(self) -> None:
        """断开微信窗口连接"""
        self._hwnd = None
        self._uia = None
        self._initialized = False
        logger.info("已断开微信连接")

    @property
    def hwnd(self) -> int:
        """获取窗口句柄"""
        if not self._initialized:
            raise WeChatNotFoundError("未连接到微信")
        return self._hwnd

    @property
    def uia(self) -> UIAWrapper:
        """获取 UIAutomation 封装器"""
        if not self._initialized:
            raise WeChatNotFoundError("未连接到微信")
        return self._uia

    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._initialized and self._hwnd is not None

    @property
    def title(self) -> str:
        """获取窗口标题"""
        if self._hwnd:
            return get_window_title(self._hwnd)
        return ""

    @property
    def class_name(self) -> str:
        """获取窗口类名"""
        if self._hwnd:
            return get_window_class(self._hwnd)
        return ""

    def refresh(self) -> bool:
        """
        刷新微信窗口连接。

        Returns:
            bool: 刷新成功返回 True
        """
        self.disconnect()
        return self.connect()

    def activate(self) -> bool:
        """
        将微信窗口置于前台。

        Returns:
            bool: 成功时返回 True
        """
        if self._hwnd:
            return self._activate_hwnd(self._hwnd)
        return False
