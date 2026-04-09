# -*- coding: utf-8 -*-
"""微信窗口管理"""
import time

from .uia_wrapper import UIAWrapper
from .exceptions import WeChatNotFoundError
from ..utils.win32 import (
    find_wechat_window,
    bring_window_to_front,
    get_window_title,
    get_window_class,
    is_window_visible,
    activate_wechat_via_tray_icon,
    check_and_fix_registry,
    ensure_screen_reader_flag,
    restart_wechat_process,
)
from ..utils.logger import get_logger
from ..config import OPERATION_INTERVAL
from . import uiautomation as uia

logger = get_logger(__name__)

# UIA 健康检查：控件树最少需要的节点数
# 正常微信窗口控件树远超此阈值；如果只有根窗口 + MMUIRenderSubWindowHW = 2 个节点，
# 说明 Qt 辅助功能未加载，需要重启微信。
_MIN_UIA_TREE_NODES = 5


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


class WeChatWindow:
    """微信窗口管理器"""

    def __init__(self):
        """初始化微信窗口管理器"""
        self._hwnd: int = None
        self._uia: UIAWrapper = None
        self._initialized = False

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
                    bring_window_to_front(hwnd)
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

    def _try_wake_and_retry_uia(self, initial_node_count: int) -> int:
        """尝试唤醒隐藏到托盘的微信窗口，并重试 UIA 健康检查。

        微信窗口被"关闭"（实际是隐藏到系统托盘）后，UIA 控件树不可访问。
        单纯的 ShowWindow 无法恢复 Qt 辅助功能树，因为 Qt 内部状态未同步更新。
        此方法通过 UIA 访问系统通知区域并调用微信托盘图标的
        Invoke 操作，等效于用户手动点击托盘图标，从而触发微信内部
        的窗口显示逻辑，使 Qt 辅助功能树正确恢复。

        此方法不依赖键盘快捷键，也不依赖任务栏的可见性，
        兼容 myDockFinder 等隐藏任务栏的工具。

        Args:
            initial_node_count: 初始检测到的 UIA 节点数

        Returns:
            int: 唤醒后检测到的 UIA 节点数
        """
        if not self._hwnd:
            return initial_node_count

        visible = is_window_visible(self._hwnd)
        logger.info(
            f"UIA 节点不足（{initial_node_count} 个），"
            f"窗口可见性={visible}，尝试通过托盘图标唤醒微信..."
        )

        # 通过 UIA 访问系统通知区域并触发微信托盘图标的 Invoke
        # 托盘图标是 toggle 行为：可见时点击会隐藏，隐藏时点击会显示。
        # 因此必须先确保窗口是隐藏的，这样托盘图标点击才会触发显示逻辑。
        import win32gui
        import win32con
        try:
            if is_window_visible(self._hwnd):
                win32gui.ShowWindow(self._hwnd, win32con.SW_HIDE)
                time.sleep(0.3)
        except Exception:
            pass

        try:
            activated = activate_wechat_via_tray_icon()
            if not activated:
                logger.warning("未找到微信托盘图标，尝试 SW_SHOW + SW_RESTORE 回退...")
                bring_window_to_front(self._hwnd)
        except Exception as e:
            logger.warning(f"托盘图标唤醒失败: {e}，尝试 SW_SHOW + SW_RESTORE 回退...")
            bring_window_to_front(self._hwnd)

        # 唤醒后多次重试 UIA 健康检查
        # 窗口显示后 Qt 可能需要少量时间重建辅助功能树
        node_count = initial_node_count
        for attempt in range(6):
            time.sleep(0.5)
            # 重新创建 UIA wrapper 以获取最新的控件树
            self._uia = UIAWrapper(self._hwnd)
            node_count = _count_uia_descendants(self._uia.root)
            logger.debug(
                f"唤醒后 UIA 重试 ({attempt + 1}/6): 节点数={node_count}"
            )
            if node_count >= _MIN_UIA_TREE_NODES:
                logger.info(
                    f"窗口唤醒成功，UIA 控件树已恢复（{node_count} 个节点）"
                )
                return node_count

        logger.warning(
            f"窗口唤醒后 UIA 仍不可用（{node_count} 个节点），"
            "可能是 Qt 辅助功能未初始化，需要重启微信。"
        )
        return node_count

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
        bring_window_to_front(hwnd)
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
        1. 检查并修复注册表中的 UI Automation 设置
        2. 确保系统屏幕阅读器标志已开启
        3. 查找微信窗口
        4. 将窗口置于前台
        5. 如果设置有变更，重启微信
        6. 初始化 UIAutomation
        7. 健康检查：验证 UIA 控件树是否可用

        Returns:
            bool: 连接成功返回 True

        Raises:
            WeChatNotFoundError: 找不到微信窗口或需要重启微信时抛出
        """
        # 第1步：检查并修复注册表
        logger.info("正在检查注册表中的 UI Automation 设置...")
        registry_modified = False
        try:
            registry_modified = check_and_fix_registry()
            if registry_modified:
                logger.info("注册表 RunningState 已从 0 修改为 1")
            else:
                logger.debug("注册表 RunningState 已正确设置")
        except Exception as e:
            logger.warning(f"注册表检查失败: {e}")

        # 第2步：确保系统屏幕阅读器标志开启
        # Qt 应用（含微信 4.x）在启动时检查此标志，
        # 如果标志关闭则不会创建辅助功能对象。
        screen_reader_changed = False
        try:
            screen_reader_changed = ensure_screen_reader_flag()
            if screen_reader_changed:
                logger.info("系统屏幕阅读器标志原为关闭，已开启")
            else:
                logger.debug("系统屏幕阅读器标志已处于开启状态")
        except Exception as e:
            logger.warning(f"屏幕阅读器标志检查失败: {e}")

        # 如果任一设置被修改，微信需要重启才能生效
        settings_changed = registry_modified or screen_reader_changed

        # 第3步：查找微信窗口
        logger.info("正在查找微信窗口...")
        self._hwnd = find_wechat_window()
        if not self._hwnd:
            raise WeChatNotFoundError(
                "未找到微信窗口，请确保微信正在运行。"
            )

        logger.info(f"找到微信窗口: HWND={self._hwnd}")

        # 第4步：将窗口置于前台
        bring_window_to_front(self._hwnd)
        time.sleep(OPERATION_INTERVAL)

        # 第5步：如果设置有变更，重启微信并自动重连
        if settings_changed:
            logger.warning("辅助功能设置已变更，正在重启微信以使其生效...")
            self._restart_and_reconnect()
            self._initialized = True
            logger.info("成功连接到微信（重启后）")
            return True

        # 第6步：检测是否在登录界面
        # 微信 UIA 失效后重新运行时，窗口可能仍显示登录界面，
        # 需要先点击"进入微信"按钮完成登录。
        cls = get_window_class(self._hwnd)
        if 'MainWindow' not in cls:
            logger.info(f"当前窗口不是主窗口（ClassName={cls}），检查是否在登录界面...")
            if self._try_click_login_button(self._hwnd):
                # 成功点击登录按钮，等待主窗口出现
                self._wait_for_main_window()

        # 第7步：初始化 UIAutomation
        logger.info("正在初始化 UIAutomation...")
        self._uia = UIAWrapper(self._hwnd)

        # 第8步：UIA 健康检查
        # 微信窗口被关闭（隐藏到托盘）时，UIA 控件树不可访问。
        # 需要通过 SW_SHOW + SW_RESTORE 显示窗口后重试。
        node_count = _count_uia_descendants(self._uia.root)
        logger.debug(f"UIA 健康检查: 控件树节点数={node_count}")

        if node_count < _MIN_UIA_TREE_NODES:
            # 尝试唤醒隐藏窗口并重试 UIA
            node_count = self._try_wake_and_retry_uia(node_count)

        if node_count < _MIN_UIA_TREE_NODES:
            logger.warning(
                f"UIA 控件树几乎为空（仅 {node_count} 个节点）。"
                "微信进程的辅助功能已失效，必须重启才能恢复。"
                "正在重启微信（建议启用微信自动登录以实现无人值守）..."
            )
            self._restart_and_reconnect()

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
            return bring_window_to_front(self._hwnd)
        return False
