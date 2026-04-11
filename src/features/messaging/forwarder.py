# -*- coding: utf-8 -*-
"""微信群消息转发。

对外统一面向“消息转发”场景，不要求调用方预先区分文本、图片、卡片等具体类型。
当前版本稳定支持可提取文本内容的消息转发；未来如果补充更丰富的消息解析能力，
只需要扩展内部的消息构造与发送逻辑，不需要改动对外规则接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Union

from .listener import MessageEvent
from .processor import ForwardAction, MessageHandler
from ...utils.logger import get_logger

logger = get_logger(__name__)

RulePredicate = Callable[[MessageEvent], bool]
RuleTransform = Callable[[MessageEvent], Optional[Union[str, "ForwardPayload"]]]


@dataclass(frozen=True)
class ForwardTarget:
    """转发目标。"""

    name: str
    target_type: str = "group"

    def __post_init__(self) -> None:
        if self.target_type not in {"group", "contact"}:
            raise ValueError(f"不支持的目标类型: {self.target_type}")


@dataclass(frozen=True)
class ForwardPayload:
    """统一的转发载荷。

    当前版本只要求 ``rendered_text`` 可发送；后续若支持更复杂的消息形态，
    可以继续在该对象上扩展上下文与附加数据，而不必改动规则接口。
    """

    rendered_text: str
    source_group: str
    event: MessageEvent
    metadata: Dict[str, object] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.rendered_text or "").strip()


@dataclass
class GroupForwardRule:
    """单条群消息转发规则。"""

    source_group: str
    targets: Sequence[Union[str, ForwardTarget]]
    target_type: str = "group"
    mode: str = "all"
    keywords: Sequence[str] = field(default_factory=tuple)
    exclude_keywords: Sequence[str] = field(default_factory=tuple)
    require_at: bool = False
    prefix_template: str = "[来自 {source_group}] "
    predicate: Optional[RulePredicate] = None
    transform: Optional[RuleTransform] = None
    name: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.targets, (str, ForwardTarget)):
            object.__setattr__(self, "targets", [self.targets])
        if self.mode not in {"all", "keyword", "mention", "custom"}:
            raise ValueError(f"不支持的规则模式: {self.mode}")
        if self.target_type not in {"group", "contact"}:
            raise ValueError(f"不支持的默认目标类型: {self.target_type}")
        if not self.targets:
            raise ValueError("转发规则至少需要一个目标")
        if self.mode == "keyword" and not self.keywords:
            raise ValueError("keyword 模式需要提供 keywords")
        if self.mode == "custom" and not self.predicate:
            raise ValueError("custom 模式需要提供 predicate")

    @property
    def rule_name(self) -> str:
        return self.name or self.source_group

    def iter_targets(self) -> List[ForwardTarget]:
        normalized: List[ForwardTarget] = []
        for target in self.targets:
            if isinstance(target, ForwardTarget):
                normalized.append(target)
            else:
                normalized.append(ForwardTarget(str(target), self.target_type))
        return normalized

    def matches(self, event: MessageEvent) -> bool:
        if event.group != self.source_group:
            return False

        content = (event.content or "").strip()
        if not content:
            return False

        if any(word for word in self.exclude_keywords if word and word in content):
            return False

        require_at = self.require_at or self.mode == "mention"
        if require_at and not event.is_at_me:
            return False

        if self.mode == "keyword":
            if not any(word for word in self.keywords if word and word in content):
                return False

        if self.mode == "custom" and self.predicate and not self.predicate(event):
            return False

        if self.mode != "custom" and self.predicate and not self.predicate(event):
            return False

        return True

    def build_payload(self, event: MessageEvent) -> Optional[ForwardPayload]:
        if self.transform:
            result = self.transform(event)
            if result is None:
                return None
            if isinstance(result, ForwardPayload):
                return result if not result.is_empty else None
            text = str(result).strip()
            if not text:
                return None
            return ForwardPayload(
                rendered_text=text,
                source_group=event.group,
                event=event,
            )

        text = self.prefix_template.format(source_group=event.group) + event.content
        text = text.strip()
        if not text:
            return None
        return ForwardPayload(
            rendered_text=text,
            source_group=event.group,
            event=event,
        )


class ForwardRuleHandler(MessageHandler):
    """把转发规则适配为统一消息处理器。"""

    def __init__(
        self,
        rules: Iterable[GroupForwardRule],
    ):
        self.rules = list(rules)
        if not self.rules:
            raise ValueError("至少需要一条转发规则")
        self.requires_group_nickname = any(
            rule.require_at or rule.mode == "mention" for rule in self.rules
        )

    def handle(self, event: MessageEvent):
        logger.info(f"[{event.group}] {event.content}")
        actions = []
        for rule in self.rules:
            if not rule.matches(event):
                continue

            payload = rule.build_payload(event)
            if not payload:
                continue

            for target in rule.iter_targets():
                actions.append(
                    ForwardAction(
                        target_name=target.name,
                        target_type=target.target_type,
                        content=payload.rendered_text,
                        source_group=payload.source_group,
                    )
                )
        return actions
