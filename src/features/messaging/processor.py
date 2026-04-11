# -*- coding: utf-8 -*-
"""微信群消息处理管线。

该模块把“监听、回复、转发”等能力统一到一套 handler/action 管线里：
1. ``WeChatGroupListener`` 负责稳定监听消息。
2. 各个 handler 负责把消息转换为一个或多个 action。
3. ``WeChatGroupProcessor`` 统一串行执行 action，避免发送抢占窗口。

这样可以自然组合出：
- 只监听
- 监听 + 自动回复
- 监听 + 转发
- 监听 + 转发 + AI 回复
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Union

from .listener import MessageEvent, WeChatGroupListener
from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class MessageAction:
    """消息处理动作基类。"""


@dataclass(frozen=True)
class ReplyAction(MessageAction):
    """回复当前来源群。"""

    group: str
    content: str


@dataclass(frozen=True)
class ForwardAction(MessageAction):
    """转发到指定目标。"""

    target_name: str
    target_type: str
    content: str
    source_group: str


class MessageHandler:
    """消息处理器基类。"""

    requires_group_nickname: bool = False

    def handle(self, event: MessageEvent) -> Optional[Union[MessageAction, Sequence[MessageAction]]]:
        raise NotImplementedError

    def set_action_emitter(self, emit_action) -> None:
        """注入动作下发器，供异步 handler 使用。"""
        return None

    def stop(self) -> None:
        """停止 handler 内部资源。"""
        return None


class CallbackHandler(MessageHandler):
    """把简单回调适配为 handler。"""

    def __init__(
        self,
        callback: Callable[[MessageEvent], object],
        *,
        auto_reply: bool = False,
        reply_on_at: bool = False,
    ):
        self.callback = callback
        self.auto_reply = auto_reply
        self.reply_on_at = reply_on_at
        self.requires_group_nickname = bool(
            reply_on_at or getattr(callback, "reply_on_at", False)
        )

    def handle(self, event: MessageEvent):
        result = self.callback(event)
        return self._build_actions(event, result)

    def _build_actions(self, event: MessageEvent, result):
        if isinstance(result, MessageAction):
            return result
        if isinstance(result, (list, tuple)):
            return list(result)
        if not self.auto_reply:
            return None

        text = str(result or "").strip()
        if not text:
            return None
        if self.reply_on_at and not event.is_at_me:
            return None
        return ReplyAction(group=event.group, content=text)


class AsyncCallbackHandler(CallbackHandler):
    """异步回调处理器。

    适合 AI 调用、网络请求等慢操作。监听主链只负责把消息投递到工作队列，
    真正的回调在后台 worker 中执行，产出的动作再回到统一 action 队列。
    """

    def __init__(
        self,
        callback: Callable[[MessageEvent], object],
        *,
        auto_reply: bool = False,
        reply_on_at: bool = False,
        queue_size: int = 0,
    ):
        super().__init__(callback, auto_reply=auto_reply, reply_on_at=reply_on_at)
        self._jobs: "queue.Queue[Optional[MessageEvent]]" = queue.Queue(maxsize=queue_size)
        self._emit_action = None
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def set_action_emitter(self, emit_action) -> None:
        self._emit_action = emit_action
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def handle(self, event: MessageEvent):
        try:
            self._jobs.put_nowait(event)
        except queue.Full:
            logger.warning("异步回调队列已满，丢弃消息: %s", event.group)
        return None

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=5)

    def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue

            if event is None:
                self._jobs.task_done()
                continue

            try:
                result = self.callback(event)
                for action in WeChatGroupProcessor._normalize_actions(self._build_actions(event, result)):
                    if self._emit_action:
                        self._emit_action(action)
            except Exception as exc:
                logger.exception("异步消息处理失败: %s: %s", event.group, exc)
            finally:
                self._jobs.task_done()


class WeChatGroupProcessor:
    """统一的微信群消息处理器。"""

    def __init__(
        self,
        client,
        groups: Iterable[str],
        handlers: Iterable[MessageHandler],
        *,
        ignore_client_sent: bool = True,
        group_nicknames=None,
        tick: float = 0.1,
        batch_size: int = 8,
        tail_size: int = 8,
    ):
        self.client = client
        self.groups = list(dict.fromkeys(groups))
        self.handlers = list(handlers)
        if not self.groups:
            raise ValueError("至少需要一个监听群聊")
        if not self.handlers:
            raise ValueError("至少需要一个消息处理器")

        self.ignore_client_sent = ignore_client_sent
        self.group_nicknames = dict(group_nicknames or {})
        self.tick = tick
        self.batch_size = batch_size
        self.tail_size = tail_size

        self._listener: Optional[WeChatGroupListener] = None
        self._action_queue: "queue.Queue[MessageAction]" = queue.Queue()
        self._stop_event = threading.Event()
        self._sender_thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._listener is not None and self._listener.is_running

    def start(self, block: bool = False) -> "WeChatGroupProcessor":
        self._stop_event.clear()
        self._start_sender()
        for handler in self.handlers:
            handler.set_action_emitter(self._action_queue.put)
        self._listener = WeChatGroupListener(
            self.client,
            self.groups,
            self._dispatch_message,
            auto_reply=False,
            ignore_client_sent=self.ignore_client_sent,
            reply_on_at=self._needs_group_nickname(),
            group_nicknames=self.group_nicknames,
            tick=self.tick,
            batch_size=self.batch_size,
            tail_size=self.tail_size,
        )
        self._listener.start(block=False)

        if block:
            try:
                while not self._stop_event.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener:
            self._listener.stop()
        for handler in self.handlers:
            handler.stop()
        if self._sender_thread and self._sender_thread.is_alive():
            self._sender_thread.join(timeout=5)

    def _needs_group_nickname(self) -> bool:
        return any(getattr(handler, "requires_group_nickname", False) for handler in self.handlers)

    def _dispatch_message(self, event: MessageEvent) -> None:
        registry = getattr(self.client, "outgoing_registry", None)
        if self.ignore_client_sent and registry and registry.should_ignore(event.group, event.content):
            return

        for handler in self.handlers:
            try:
                actions = handler.handle(event)
            except Exception as exc:
                logger.exception(f"消息处理器执行失败: {event.group}: {exc}")
                continue

            for action in self._normalize_actions(actions):
                self._action_queue.put(action)

    @staticmethod
    def _normalize_actions(actions) -> List[MessageAction]:
        if not actions:
            return []
        if isinstance(actions, MessageAction):
            return [actions]
        return [action for action in actions if isinstance(action, MessageAction)]

    def _start_sender(self) -> None:
        if self._sender_thread and self._sender_thread.is_alive():
            return
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._sender_thread.start()

    def _send_loop(self) -> None:
        while not self._stop_event.is_set() or not self._action_queue.empty():
            try:
                action = self._action_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._execute_action(action)
            except Exception as exc:
                logger.exception(f"消息动作执行失败: {exc}")
            finally:
                self._action_queue.task_done()

    def _execute_action(self, action: MessageAction) -> None:
        if isinstance(action, ReplyAction):
            self._execute_reply(action)
            return
        if isinstance(action, ForwardAction):
            self._execute_forward(action)
            return
        logger.warning(f"忽略未知动作类型: {type(action).__name__}")

    def _execute_reply(self, action: ReplyAction) -> None:
        if not self._listener:
            return
        text = (action.content or "").strip()
        if not text:
            return
        sent = self._listener.reply(action.group, text)
        if sent:
            return

    def _execute_forward(self, action: ForwardAction) -> None:
        text = (action.content or "").strip()
        if not text:
            return

        self._record_group_send(action)

        sent = self.client.chat_window.send_to(
            action.target_name,
            text,
            target_type=action.target_type,
        )
        if not sent:
            logger.warning(f"[{action.source_group} -> {action.target_name}] 转发失败")
            return

        logger.info(f"[{action.source_group} -> {action.target_name}] 已转发")

    def _record_group_send(self, action: ForwardAction) -> None:
        if not self._listener:
            return
        if action.target_type != "group":
            return
        if action.target_name not in self.groups:
            return
        registry = getattr(self.client, "outgoing_registry", None)
        if registry:
            registry.record(action.target_name, action.content)
