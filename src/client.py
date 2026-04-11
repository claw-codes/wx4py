# -*- coding: utf-8 -*-
"""
wx4py 客户端

wx4py 的主入口。
"""
from .core.exceptions import WeChatNotFoundError
from .core.window import WeChatWindow
from .features.chat import ChatWindow
from .features.groups import GroupManager
from .features.messaging.listener import OutgoingMessageRegistry
from .features.messaging.processor import MessageHandler, WeChatGroupProcessor
from .utils.logger import get_logger

logger = get_logger(__name__)


class WeChatClient:
    """
    wx4py 客户端

    用于在 Windows 上自动化操作微信的主类。

    用法:
        wx = WeChatClient()
        wx.connect()

        # 发送消息给联系人
        wx.chat_window.send_to("大号", "Hello!")

        # 发送消息给群聊
        wx.chat_window.send_to("测试群", "Hello!", target_type='group')

        # 批量发送
        wx.chat_window.batch_send(["群1", "群2"], "Hello!")
    """

    def __init__(self, auto_connect: bool = False):
        """
        初始化微信客户端。

        Args:
            auto_connect: 如果为 True，则在初始化时自动连接
        """
        self._window = WeChatWindow()
        self._chat_window: ChatWindow = None
        self._group_manager: GroupManager = None
        self._services = []
        self._outgoing_registry = OutgoingMessageRegistry(120.0)

        if auto_connect:
            self.connect()

    def connect(self) -> bool:
        """
        连接微信窗口。

        流程：
        1. 检查并修复注册表（RunningState）
        2. 查找并绑定微信窗口
        3. 初始化 UIAutomation

        Returns:
            bool: 连接成功返回 True

        Raises:
            WeChatNotFoundError: 未找到微信时抛出
        """
        logger.info("正在连接微信...")
        result = self._window.connect()
        if result:
            self._chat_window = ChatWindow(self._window)
            self._group_manager = GroupManager(self._window)
        return result

    def disconnect(self) -> None:
        """断开微信连接"""
        for service in list(self._services):
            service.stop()
        self._services.clear()
        self._window.disconnect()
        self._chat_window = None
        self._group_manager = None
        logger.info("已断开微信连接")

    def process_groups(
        self,
        groups,
        handlers,
        *,
        ignore_client_sent: bool = True,
        block: bool = False,
        **options,
    ) -> WeChatGroupProcessor:
        """统一处理多个群聊消息。

        Args:
            groups: 群聊名称列表。
            handlers: 一个或多个 MessageHandler。
            ignore_client_sent: 是否忽略本库发送后回流的消息。
            block: 是否阻塞当前线程运行监听循环。
            **options: 传给监听器的调度参数，例如 tick、batch_size、tail_size、
                reply_on_at、group_nicknames。

        Returns:
            WeChatGroupProcessor: 处理器实例，可调用 stop() 停止。
        """
        if not self.is_connected:
            self.connect()

        if isinstance(handlers, MessageHandler):
            normalized_handlers = [handlers]
        else:
            normalized_handlers = list(handlers)

        processor = WeChatGroupProcessor(
            self,
            groups,
            normalized_handlers,
            ignore_client_sent=ignore_client_sent,
            **options,
        )
        self._services.append(processor)
        return processor.start(block=block)

    @property
    def window(self) -> WeChatWindow:
        """获取窗口管理器"""
        return self._window

    @property
    def chat_window(self) -> ChatWindow:
        """获取聊天窗口页面，用于发送消息"""
        if not self._chat_window:
            raise WeChatNotFoundError("未连接到微信")
        return self._chat_window

    @property
    def group_manager(self) -> GroupManager:
        """获取群组管理器，用于群操作"""
        if not self._group_manager:
            raise WeChatNotFoundError("未连接到微信")
        return self._group_manager

    @property
    def is_connected(self) -> bool:
        """检查是否已连接微信"""
        return self._window.is_connected

    @property
    def outgoing_registry(self) -> OutgoingMessageRegistry:
        """获取客户端级共享的已发送消息注册表。"""
        return self._outgoing_registry

    def __enter__(self):
        """上下文管理器入口"""
        if not self.is_connected:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()
        return False
