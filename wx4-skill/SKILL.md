---
name: wx4-skill
description: 微信自动化操作 skill，用于帮助用户快速完成微信消息群发、文件发送、群管理、聊天记录获取、多群监听、AI 自动回复等自动化任务。当用户需要批量发送微信消息、管理微信群、获取聊天记录、监听群消息、或接入 AI 群聊机器人时使用此 skill。
---

# 微信自动化操作 Skill

## ⚠️ 使用前必读：安装检查

**在执行任何操作前，必须先确认 wx4py 库已安装。**

### 步骤1：检查是否已安装

```python
try:
    from wx4py import WeChatClient
    print("✅ wx4py 已安装")
except ImportError:
    print("❌ 未安装 wx4py")
```

### 步骤2：如果未安装，执行安装

```bash
# 方法1：从 PyPI 安装（推荐）
pip install wx4py

# 方法2：从 GitHub 安装（最新版）
pip install git+https://github.com/claw-codes/wx4py.git

# 方法3：从本地安装
cd /path/to/wx4py
pip install .
```

### 步骤3：验证安装成功

```python
from wx4py import WeChatClient

# 测试导入
print("✅ 安装成功！")

# 检查版本（可选）
import wx4py
print(f"版本: {wx4py.__version__}")
```

**重要提示**：
- 如果用户提示 `ModuleNotFoundError: No module named 'wx4py'`，说明未安装
- 必须先安装库再执行后续操作
- 安装只需要一次，后续无需重复

---

## 概述

本 skill 基于 wx4py 库，帮助用户通过 Python 代码自动化控制 Windows 微信客户端，完成重复性的消息发送、群管理等任务。

**适用场景**：
- 批量群发通知到多个群或联系人
- 定时发送文件、图片、消息
- 获取和分析聊天记录
- 管理群公告、群昵称、免打扰等设置
- 监听多个群聊消息，并在被 @ 时自动回复
- 接入 OpenAI 兼容接口或自定义 AI 回调，构建群聊机器人
- 自动化日常微信操作

**前置要求**：
- Windows 系统
- 微信 PC 客户端已安装并登录（Qt 版本，已测试 4.1.7.59、4.1.8.29）
- Python >=3.9
- 终端、编辑器、脚本文件统一使用 UTF-8 编码环境，避免中文消息、群名、文件名出现乱码

**编码环境建议**：
- Python 源码文件保存为 UTF-8
- PowerShell / 终端优先使用 UTF-8 编码
- 读写文本、JSON、Markdown 文件时显式指定 `encoding='utf-8'`
- 如果要输出中文日志或生成中文文件内容，优先验证终端和编辑器都已切换到 UTF-8

## 核心功能

### 1. 消息发送

#### 发送单条消息到联系人或群
```python
from wx4py import WeChatClient

wx = WeChatClient()
wx.connect()

# 发送给联系人
wx.chat_window.send_to("文件传输助手", "测试消息")

# 发送到群
wx.chat_window.send_to("工作群", "下午3点开会", target_type='group')

wx.disconnect()
```

#### 批量群发消息
```python
wx = WeChatClient()
wx.connect()

# 批量发送到多个群
groups = ["群1", "群2", "群3"]
message = "重要通知：明天放假"
wx.chat_window.batch_send(groups, message)

# 批量发送到多个联系人
contacts = ["张三", "李四", "王五"]
wx.chat_window.batch_send(contacts, "周末聚餐通知", target_type='contact')

wx.disconnect()
```

### 2. 文件发送

#### 发送单个文件
```python
wx = WeChatClient()
wx.connect()

# 发送文件给联系人
wx.chat_window.send_file_to("文件传输助手", r"C:\reports\weekly.pdf")

# 发送文件到群
wx.chat_window.send_file_to("工作群", r"C:\data.xlsx", target_type='group', message='可以携带消息')

wx.disconnect()
```

#### 批量发送多个文件
```python
wx = WeChatClient()
wx.connect()

# 发送多个文件
files = [
    r"C:\images\photo1.png",
    r"C:\images\photo2.png",
    r"C:\documents\report.pdf"
]
wx.chat_window.send_file_to("文件传输助手", files)

wx.disconnect()
```

### 3. 聊天记录获取

#### 获取指定时间范围的聊天记录
```python
wx = WeChatClient()
wx.connect()

# 获取今天的聊天记录
messages = wx.chat_window.get_chat_history(
    target="工作群",
    target_type='group',
    since='today'  # 'today' | 'yesterday' | 'week' | 'all'
)

# 处理消息
for msg in messages:
    print(f"[{msg['time']}] {msg['content']}")

wx.disconnect()
```

**返回格式**：
```python
{
    "type": "text",      # text / link / system
    "content": "消息内容",
    "time": "今天 15:30"
}
```

### 4. 群管理

#### 获取群成员列表
```python
wx = WeChatClient()
wx.connect()

members = wx.group_manager.get_group_members("工作群")
print(f"群成员数量：{len(members)}")
for member in members:
    print(member)

wx.disconnect()
```

#### 修改群昵称
```python
wx = WeChatClient()
wx.connect()

wx.group_manager.set_group_nickname("工作群", "张三的小号")

wx.disconnect()
```

#### 获取群昵称
```python
wx = WeChatClient()
wx.connect()

nickname = wx.group_manager.get_group_nickname("工作群")
print(f"我在本群的昵称：{nickname}")

wx.disconnect()
```

#### 设置消息免打扰
```python
wx = WeChatClient()
wx.connect()

# 开启免打扰
wx.group_manager.set_do_not_disturb("工作群", enable=True)

# 关闭免打扰
wx.group_manager.set_do_not_disturb("工作群", enable=False)

wx.disconnect()
```

#### 置顶/取消置顶聊天
```python
wx = WeChatClient()
wx.connect()

# 置顶聊天
wx.group_manager.set_pin_chat("工作群", enable=True)

# 取消置顶
wx.group_manager.set_pin_chat("工作群", enable=False)

wx.disconnect()
```

#### 修改群公告（如果修改不成功，很大概率是因为不是管理员的原因）
```python
wx = WeChatClient()
wx.connect()

# 优先使用这种方式，从 Markdown 文件设置公告（支持表格、列表等格式）
wx.group_manager.set_announcement_from_markdown("工作群", "markdown文件路径")

# 直接设置文本公告
wx.group_manager.modify_announcement_simple("工作群", "本群禁止发广告，违者移出")

wx.disconnect()
```

### 5. 群聊监听与 AI 自动回复

#### 监听多个群聊消息
```python
from wx4py import CallbackHandler, MessageEvent, WeChatClient

groups = ["工作群1", "工作群2", "工作群3"]

def on_message(event: MessageEvent):
    print(f"[{event.group}] {event.content}")
    return ""  # 只监听，不自动回复

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        groups,
        [CallbackHandler(on_message)],
        block=True,
    )
```

#### 只在被 @ 时自动回复
```python
from wx4py import AsyncCallbackHandler, MessageEvent, WeChatClient

groups = ["工作群1", "工作群2"]

def reply(event: MessageEvent):
    if not event.is_at_me:
        return ""
    return f"收到：{event.content}"

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        groups,
        [AsyncCallbackHandler(reply, auto_reply=True, reply_on_at=True)],
        block=True,
    )
```

#### 监听指定群消息并转发给指定联系人或群
```python
from wx4py import ForwardRuleHandler, GroupForwardRule, WeChatClient

rules = [
    GroupForwardRule(
        source_group="告警群",
        targets=["值班同学"],
        target_type="contact",
        prefix_template="[告警群] ",
    ),
    GroupForwardRule(
        source_group="项目群A",
        targets=["项目群B"],
        target_type="group",
        prefix_template="[项目群A] ",
    ),
]

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["告警群", "项目群A"],
        [ForwardRuleHandler(rules)],
        block=True,
    )
```

**适用场景**：
- 监听告警群，把消息转发给值班联系人
- 监听业务群，把消息同步到另一个群
- 针对不同来源群，配置不同的联系人或群作为目标

#### 使用内置 AIClient 接入 OpenAI 兼容接口
```python
import os
from wx4py import AIClient, AIConfig, AIResponder, AsyncCallbackHandler, WeChatClient

ai = AIClient(
    AIConfig(
        base_url="https://api.example.com/v1",
        api_format="completions",
        model="your-model-id",
        api_key=os.environ["AI_API_KEY"],
        enable_thinking=False,
    )
)

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["工作群"],
        [
            AsyncCallbackHandler(
                AIResponder(ai, context_size=8, reply_on_at=True),
                auto_reply=True,
            )
        ],
        block=True,
    )
```

#### 使用自定义 AI 或业务系统
```python
from wx4py import AsyncCallbackHandler, MessageEvent, WeChatClient

def custom_reply(event: MessageEvent):
    if not event.is_at_me:
        return ""

    # 这里可以调用公司内部接口、其他 AI SDK 或业务系统。
    return f"自定义回复：{event.content}"

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["工作群"],
        [AsyncCallbackHandler(custom_reply, auto_reply=True, reply_on_at=True)],
        block=True,
    )
```

**实现说明**：
- 每个群优先打开独立聊天窗口，适合同时监听多个群。
- 自动回复通过发送队列串行执行，避免多个群同时回复时抢占窗口。
- 本库发送的消息会自动记录，避免机器人监听到自己的回复后再次触发。

### 6. 群聊消息发送者识别（OCR）

微信 4.x 的 UI Automation 不直接暴露发送者信息，但 wx4py 通过 **OCR 截图识别 + MemberRegistry 昵称匹配** 的方式，可以识别群聊消息的发送者昵称和微信ID。

#### 基本使用

```python
from wx4py import MemberRegistry, WeChatClient
from wx4py.features.messaging.listener import WeChatGroupListener

# 创建成员注册表
registry = MemberRegistry()
registry.load_from_file("group_members.json")

def on_message(event):
    if event.sender_name:
        if event.sender_wxid:
            print(f"[{event.group}] {event.sender_name} ({event.sender_wxid}): {event.content}")
        else:
            print(f"[{event.group}] {event.sender_name}: {event.content}")
    else:
        print(f"[{event.group}] 未知发送者: {event.content}")

with WeChatClient(auto_connect=True) as wx:
    listener = WeChatGroupListener(
        client=wx,
        groups=["工作群", "项目群"],
        member_registry=registry,
        on_message=on_message,
    )
    listener.start(block=True)
```

#### 结合 AI 自动回复（带发送者识别）

```python
from wx4py import MemberRegistry, WeChatClient
from wx4py.features.messaging.listener import WeChatGroupListener

registry = MemberRegistry()
registry.load_from_file("group_members.json")

def reply_with_sender(event):
    if not event.is_at_me:
        return ""
    
    # 可以根据发送者做个性化回复
    sender = event.sender_name or "有人"
    content = event.content
    if event.group_nickname:
        content = content.replace(f"@{event.group_nickname}", "").strip()
    
    return f"{sender}，收到你的消息：{content}"

with WeChatClient(auto_connect=True) as wx:
    listener = WeChatGroupListener(
        client=wx,
        groups=["工作群"],
        member_registry=registry,
        on_message=reply_with_sender,
        auto_reply=True,
        reply_on_at=True,
    )
    listener.start(block=True)
```

**注意事项**：
- 需要安装 PaddleOCR：`pip install paddlepaddle paddleocr`
- 首次监听会自动注册群成员（点击头像获取微信ID，需要成员公开微信ID）
- 成员信息保存在 `group_members.json`
- 如果发送者未注册微信ID，`sender_wxid` 为 None
- 自己发送的消息会被识别为 `sender_name="自己"`

## 使用模式

### 推荐：使用上下文管理器
```python
from wx4py import WeChatClient

with WeChatClient() as wx:
    # 自动连接和断开
    wx.chat_window.send_to("文件传输助手", "Hello!")
```

### 手动连接管理
```python
wx = WeChatClient()
wx.connect()

try:
    # 执行操作
    wx.chat_window.send_to("文件传输助手", "Hello!")
finally:
    wx.disconnect()
```

## 实用脚本示例

### 示例1：定时群发通知
```python
from wx4py import WeChatClient
import schedule
import time

def send_daily_notification():
    with WeChatClient() as wx:
        groups = ["工作群1", "工作群2", "工作群3"]
        message = "早安！今日工作提醒..."
        wx.chat_window.batch_send(groups, message, target_type='group')
        print("通知已发送")

# 每天早上9点发送
schedule.every().day.at("09:00").do(send_daily_notification)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### 示例2：收集昨天的聊天记录并保存
```python
from wx4py import WeChatClient
import json
from datetime import datetime

with WeChatClient() as wx:
    # 获取昨天的聊天记录
    messages = wx.chat_window.get_chat_history(
        target="工作群",
        target_type='group',
        since='yesterday'
    )

    # 保存到文件
    filename = f"chat_history_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    print(f"已保存 {len(messages)} 条消息到 {filename}")
```

### 示例3：批量发送文件到多个群
```python
from wx4py import WeChatClient
import os

# 准备要发送的文件
files_dir = r"C:\weekly_reports"
files = [os.path.join(files_dir, f) for f in os.listdir(files_dir) if f.endswith('.pdf')]

groups = ["管理群", "开发群", "产品群"]

with WeChatClient() as wx:
    for group in groups:
        print(f"正在向 {group} 发送文件...")
        wx.chat_window.send_file_to(group, files, target_type='group')
        print(f"已完成 {group}")
```

## 注意事项

### 操作限制
- 仅支持 Windows 系统
- 需要微信客户端已登录
- 操作期间不要手动操作微信窗口
- 发送者识别需要安装 PaddleOCR（`pip install paddlepaddle paddleocr`）

### 最佳实践
- 使用上下文管理器确保连接正确释放
- 批量操作时添加适当延迟，避免操作过快
- 重要操作前先测试小范围验证
- 群聊机器人优先使用 `reply_on_at=True`，避免普通群消息触发自动回复
- AI 回调耗时会影响监听延迟，大规模群监听时建议使用响应更快的模型或业务接口
- 捕获异常并记录日志
- 需要系统查看方法说明时，优先参考 `docs/guide/API_GUIDE.md`

### 异常处理
```python
from wx4py import WeChatClient, WeChatNotFoundError, ControlNotFoundError

try:
    with WeChatClient() as wx:
        wx.chat_window.send_to("目标", "消息")
except WeChatNotFoundError:
    print("错误：未找到微信窗口，请确保微信已打开并登录")
except ControlNotFoundError as e:
    print(f"错误：未找到控件 - {e}")
except Exception as e:
    print(f"未知错误：{e}")
```

## 工作流程指导

当用户请求微信自动化任务时，按以下步骤操作：

1. **理解需求**
   - 确认目标（联系人/群组）
   - 确认操作类型（发消息/发文件/获取记录/管理设置）
   - 确认是否批量操作

2. **编写脚本**
   - 使用上述示例作为模板
   - 添加必要的错误处理
   - 考虑操作延迟和频率限制

3. **验证和测试**
   - 先用小范围测试（如"文件传输助手"）
   - 确认脚本正确运行后再扩大范围

4. **执行和反馈**
   - 运行脚本并观察结果
   - 提供清晰的执行反馈
   - 必要时保存日志

## 快速参考

| 操作 | 方法 | 示例 |
|------|------|------|
| 发消息给联系人 | `chat_window.send_to(target, message)` | `wx.chat_window.send_to("张三", "Hi")` |
| 发消息到群 | `chat_window.send_to(target, message, target_type='group')` | `wx.chat_window.send_to("工作群", "Hi", target_type='group')` |
| 批量群发 | `chat_window.batch_send(targets, message, target_type)` | `wx.chat_window.batch_send(["群1", "群2"], "Hi", target_type='group')` |
| 发送文件 | `chat_window.send_file_to(target, file_path)` | `wx.chat_window.send_file_to("张三", r"C:\file.pdf")` |
| 获取聊天记录 | `chat_window.get_chat_history(target, target_type, since)` | `wx.chat_window.get_chat_history("工作群", 'group', 'today')` |
| 获取群成员 | `group_manager.get_group_members(group_name)` | `wx.group_manager.get_group_members("工作群")` |
| 获取群昵称 | `group_manager.get_group_nickname(group_name)` | `wx.group_manager.get_group_nickname("工作群")` |
| 设置群昵称 | `group_manager.set_group_nickname(group_name, nickname)` | `wx.group_manager.set_group_nickname("工作群", "小张")` |
| 消息免打扰 | `group_manager.set_do_not_disturb(group_name, enable)` | `wx.group_manager.set_do_not_disturb("工作群", True)` |
| 置顶聊天 | `group_manager.set_pin_chat(group_name, enable)` | `wx.group_manager.set_pin_chat("工作群", True)` |
| 修改群公告 | `group_manager.modify_announcement_simple(group_name, content)` | `wx.group_manager.modify_announcement_simple("工作群", "新公告")` |
| 监听/处理多个群聊 | `process_groups(groups, handlers, block=True)` | `wx.process_groups(["群1"], [handler], block=True)` |
| 监听群消息并转发 | `process_groups(groups, [ForwardRuleHandler(rules)], block=True)` | `wx.process_groups(["群1"], [ForwardRuleHandler(rules)], block=True)` |
| 自动回复群聊 | `AsyncCallbackHandler(reply_func, auto_reply=True)` | `AsyncCallbackHandler(reply, auto_reply=True, reply_on_at=True)` |
| AI 自动回复 | `AIResponder(ai_client, context_size=8)` | `AsyncCallbackHandler(AIResponder(ai, context_size=8, reply_on_at=True), auto_reply=True)` |
| 发送者识别 | `WeChatGroupListener(member_registry=registry)` | `WeChatGroupListener(wx, groups, member_registry=registry, on_message=handler)` |

## 常见问题

**Q: 脚本运行时提示找不到微信窗口？**
A: 确保微信已打开并登录，窗口不要最小化。

**Q: 批量发送时部分失败？**
A: 检查目标名称是否正确，建议在每次发送间添加延迟。

**Q: 中文消息、群名或导出文件出现乱码？**
A: 先确认终端、编辑器、Python 源文件和读写文件逻辑都使用 UTF-8；写文件时显式传入 `encoding='utf-8'`，避免依赖系统默认编码。

**Q: 可以获取图片和语音消息吗？**
A: 目前主要支持文本消息，图片和语音的完整获取受限于微信 UIA。

**Q: AI 自动回复会回复所有群消息吗？**
A: 不会，推荐传入 `reply_on_at=True`。普通消息只监听，只有群消息 @ 当前群昵称时才会触发回复。

**Q: 可以不用内置 AIClient，接入自己的 AI 服务吗？**
A: 可以。`process_groups()` 接收任意 handler；最简单的方式是使用 `AsyncCallbackHandler` 包装你自己的回调，回调返回字符串即可入队发送。

**Q: 多个群同时触发回复会抢占窗口吗？**
A: 自动回复会进入发送队列串行执行，避免多个独立聊天窗口同时发送导致焦点抢占。

**Q: 脚本可以在后台运行吗？**
A: 微信窗口需要在前台才能进行 UI 自动化操作。
