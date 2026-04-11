# wx4py 接口文档

这份文档面向第一次接触 `wx4py` 的用户。

如果你只想先跑起来，先看：

- [QUICKSTART.md](E:/MyProject/me/wx4py/docs/guide/QUICKSTART.md)
- [examples/README.md](E:/MyProject/me/wx4py/examples/README.md)

如果你想知道：

- `WeChatClient` 怎么用
- 能发什么消息
- 能做哪些群管理操作
- 群监听、转发、AI 回复怎么组合

就看这份文档。

---

## 1. 使用前准备

运行环境：

- Windows 10 / 11
- Python 3.9+
- 已安装并登录微信 4.x

安装：

```bash
pip install wx4py
```

如果你是直接拉源码运行：

```bash
pip install -e .
```

---

## 2. 先理解三个核心对象

你可以把 `wx4py` 理解成 3 层：

1. `WeChatClient`
   - 总入口
   - 负责连接微信、断开微信、启动群消息处理

2. `wx.chat_window`
   - 负责聊天相关操作
   - 比如搜索、打开聊天、发消息、发文件、读取聊天记录

3. `wx.group_manager`
   - 负责群管理相关操作
   - 比如获取群成员、修改群公告、设置群昵称、免打扰、置顶

最常见写法是：

```python
from wx4py import WeChatClient

with WeChatClient(auto_connect=True) as wx:
    wx.chat_window.send_to("文件传输助手", "测试成功")
```

这里的意思是：

- 创建客户端
- 自动连接微信
- 做完操作后自动断开

---

## 3. WeChatClient

导入方式：

```python
from wx4py import WeChatClient
```

### 3.1 创建客户端

```python
wx = WeChatClient()
```

或者：

```python
wx = WeChatClient(auto_connect=True)
```

参数说明：

- `auto_connect`
  - `False`：只创建对象，不立即连接
  - `True`：创建对象时自动连接微信

### 3.2 connect()

连接微信。

```python
wx.connect()
```

返回值：

- `True`：连接成功

常见使用方式：

```python
wx = WeChatClient()
wx.connect()
```

### 3.3 disconnect()

断开微信连接。

```python
wx.disconnect()
```

如果你用了 `with WeChatClient(...) as wx:`，一般不需要手动调用。

### 3.4 is_connected

判断当前是否已经连接。

```python
if wx.is_connected:
    print("已连接")
```

### 3.5 chat_window

拿到聊天操作对象。

```python
wx.chat_window.send_to("文件传输助手", "你好")
```

### 3.6 group_manager

拿到群管理对象。

```python
wx.group_manager.get_group_members("测试群")
```

### 3.7 process_groups()

统一的群消息处理入口。

你可以把它理解成：

- 监听多个群
- 收到消息后交给一个或多个 handler 处理
- handler 可以做：
  - 只监听
  - 转发
  - 自动回复
  - AI 回复
  - 多个动作组合

基本写法：

```python
wx.process_groups(
    ["测试龙虾1", "测试龙虾2"],
    [handler1, handler2],
    block=True,
)
```

参数说明：

- `groups`
  - 要监听的群名称列表
- `handlers`
  - 消息处理器列表
- `ignore_client_sent`
  - 是否忽略本库自己刚发出的消息回流
  - 默认 `True`
- `block`
  - `True`：阻塞当前线程，适合机器人常驻运行
  - `False`：后台运行，马上返回处理器对象
- 其他常见调度参数：
  - `tick`
  - `batch_size`
  - `tail_size`

最小监听示例：

```python
from wx4py import CallbackHandler, WeChatClient


def on_message(event):
    print(f"[{event.group}] {event.content}")


with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [CallbackHandler(on_message)],
        block=True,
    )
```

---

## 4. chat_window：聊天相关接口

`wx.chat_window` 负责：

- 搜索联系人 / 群
- 打开聊天
- 发消息
- 发文件
- 批量发送
- 读取聊天记录

---

### 4.1 search(keyword)

搜索联系人、群聊、功能入口等。

```python
results = wx.chat_window.search("张三")
```

返回值：

- 一个字典
- key 是分组名，比如：
  - `联系人`
  - `群聊`
  - `功能`
- value 是搜索结果对象列表

示例：

```python
results = wx.chat_window.search("张三")

for group_name, items in results.items():
    print(group_name)
    for item in items:
        print(item.name)
```

参考示例：

- [search_chats.py](E:/MyProject/me/wx4py/examples/inspect/search_chats.py)

---

### 4.2 open_chat(target, target_type="contact")

打开一个联系人或群聊。

```python
wx.chat_window.open_chat("文件传输助手")
wx.chat_window.open_chat("测试群", target_type="group")
```

参数说明：

- `target`
  - 联系人名或群名
- `target_type`
  - `"contact"`：联系人
  - `"group"`：群聊

返回值：

- `True`：打开成功
- `False`：打开失败

适合场景：

- 你要先打开聊天，再做别的操作
- 比如读取历史记录、发送消息、发送文件

---

### 4.3 send_message(message)

在“当前已经打开的聊天窗口”里发送一条消息。

```python
wx.chat_window.open_chat("文件传输助手")
wx.chat_window.send_message("你好")
```

注意：

- 这个方法不会帮你搜索目标
- 你必须先确保当前聊天就是你想发送的对象

返回值：

- `True`：发送成功
- `False`：发送失败

---

### 4.4 send_to(target, message, target_type="contact")

最常用的发消息方法。

它会：

1. 搜索并打开聊天
2. 发送消息

```python
wx.chat_window.send_to("文件传输助手", "测试成功")
wx.chat_window.send_to("测试群", "收到", target_type="group")
```

参数说明：

- `target`
  - 联系人名或群名
- `message`
  - 要发送的文本
- `target_type`
  - `"contact"` 或 `"group"`

返回值：

- `True`：发送成功
- `False`：发送失败

参考示例：

- [send_contact_message.py](E:/MyProject/me/wx4py/examples/sending/send_contact_message.py)
- [send_group_message.py](E:/MyProject/me/wx4py/examples/sending/send_group_message.py)

---

### 4.5 batch_send(targets, message, target_type="group")

向多个目标发送同一条消息。

```python
results = wx.chat_window.batch_send(
    ["测试龙虾1", "测试龙虾2", "测试龙虾3"],
    "今晚 8 点开会",
    target_type="group",
)
```

返回值：

- 一个字典
- key 是目标名称
- value 是是否发送成功

例如：

```python
{
    "测试龙虾1": True,
    "测试龙虾2": True,
    "测试龙虾3": False,
}
```

参考示例：

- [send_batch_messages.py](E:/MyProject/me/wx4py/examples/sending/send_batch_messages.py)

---

### 4.6 send_file(file_path, message=None)

给“当前已经打开的聊天窗口”发送文件。

```python
wx.chat_window.open_chat("文件传输助手")
wx.chat_window.send_file(r"C:\demo\test.pdf")
```

参数说明：

- `file_path`
  - 单个文件路径
  - 或文件路径列表
- `message`
  - 可选
  - 跟文件一起发送的一段文字

注意：

- 当前聊天必须已经打开
- 如果你不想自己先打开聊天，请用 `send_file_to()`

---

### 4.7 send_file_to(target, file_path, target_type="contact", message=None)

搜索并打开聊天，然后发送文件。

```python
wx.chat_window.send_file_to(
    "文件传输助手",
    r"C:\demo\test.pdf",
)
```

也支持多个文件：

```python
wx.chat_window.send_file_to(
    "文件传输助手",
    [r"C:\a.pdf", r"C:\b.pdf"],
    message="请查收",
)
```

参考示例：

- [send_single_file.py](E:/MyProject/me/wx4py/examples/sending/send_single_file.py)
- [send_multiple_files.py](E:/MyProject/me/wx4py/examples/sending/send_multiple_files.py)

---

### 4.8 get_chat_history(target, target_type="contact", since="today", max_count=500)

读取联系人或群聊的聊天记录。

```python
messages = wx.chat_window.get_chat_history(
    "测试群",
    target_type="group",
    since="week",
    max_count=100,
)
```

参数说明：

- `target`
  - 联系人名或群名
- `target_type`
  - `"contact"` 或 `"group"`
- `since`
  - `"today"`：今天
  - `"yesterday"`：昨天
  - `"week"`：本周
  - `"all"`：尽可能全部
- `max_count`
  - 最多返回多少条

返回值：

- 一个列表
- 每条记录是字典，例如：

```python
{
    "type": "text",
    "content": "你好",
    "time": "今天 12:30",
}
```

注意：

- 微信 Qt 版通常拿不到稳定的发送者信息
- 所以返回结果以消息内容和时间为主

参考示例：

- [inspect_chat_history.py](E:/MyProject/me/wx4py/examples/inspect/inspect_chat_history.py)

---

## 5. group_manager：群管理接口

`wx.group_manager` 负责：

- 获取群成员
- 修改群公告
- 从 Markdown 设置群公告
- 设置群昵称
- 读取群昵称
- 设置免打扰
- 设置置顶

---

### 5.1 get_group_members(group_name)

获取群成员列表。

```python
members = wx.group_manager.get_group_members("测试群")
print(members)
```

返回值：

- `list[str]`

参考示例：

- [list_group_members.py](E:/MyProject/me/wx4py/examples/groups/list_group_members.py)

---

### 5.2 modify_announcement_simple(group_name, announcement)

直接用纯文本修改群公告。

```python
wx.group_manager.modify_announcement_simple(
    "测试群",
    "欢迎加入，请遵守群规。",
)
```

返回值：

- `True`：成功
- `False`：失败

参考示例：

- [update_group_announcement_simple.py](E:/MyProject/me/wx4py/examples/groups/update_group_announcement_simple.py)

---

### 5.3 modify_announcement(group_name, announcement)

功能上也是修改群公告。

```python
wx.group_manager.modify_announcement("测试群", "新公告")
```

说明：

- 这是对 `modify_announcement_simple()` 的一层薄封装
- 普通用户直接用 `modify_announcement_simple()` 就够了

---

### 5.4 set_announcement_from_markdown(group_name, md_file_path)

从 Markdown 文件设置群公告。

```python
wx.group_manager.set_announcement_from_markdown(
    "测试群",
    r"C:\demo\announcement.md",
)
```

适合场景：

- 你已经把群公告写在 `.md` 文件里
- 希望保留标题、列表、表格等格式

返回值：

- `True`：成功
- `False`：失败

参考示例：

- [update_group_announcement_from_markdown.py](E:/MyProject/me/wx4py/examples/groups/update_group_announcement_from_markdown.py)

---

### 5.5 set_group_nickname(group_name, nickname)

设置“我在本群的昵称”。

```python
wx.group_manager.set_group_nickname("测试群", "新昵称")
```

返回值：

- `True`：成功
- `False`：失败

参考示例：

- [set_group_nickname.py](E:/MyProject/me/wx4py/examples/groups/set_group_nickname.py)

---

### 5.6 get_group_nickname(group_name)

获取“我在本群的昵称”。

```python
nickname = wx.group_manager.get_group_nickname("测试群")
print(nickname)
```

返回值：

- 成功：返回字符串
- 失败：返回 `None`

这个接口在群机器人场景里很重要，因为：

- 判断“是否有人 @ 我”
- 需要先知道你在这个群里的实际昵称

---

### 5.7 set_do_not_disturb(group_name, enable)

设置群消息免打扰。

```python
wx.group_manager.set_do_not_disturb("测试群", enable=True)
```

参数说明：

- `enable=True`
  - 开启免打扰
- `enable=False`
  - 关闭免打扰

参考示例：

- [set_group_do_not_disturb.py](E:/MyProject/me/wx4py/examples/groups/set_group_do_not_disturb.py)

---

### 5.8 set_pin_chat(group_name, enable)

设置聊天置顶或取消置顶。

```python
wx.group_manager.set_pin_chat("测试群", enable=True)
```

参数说明：

- `enable=True`
  - 置顶
- `enable=False`
  - 取消置顶

参考示例：

- [set_chat_pinned.py](E:/MyProject/me/wx4py/examples/groups/set_chat_pinned.py)

---

## 6. 群消息处理：监听、转发、自动回复

这部分是 `wx4py` 里最适合做机器人的能力。

统一入口只有一个：

```python
wx.process_groups(...)
```

你需要准备的是：

- 要监听哪些群
- 收到消息后用哪些 handler 处理

---

## 7. MessageEvent：监听到的消息长什么样

在群监听回调里，你拿到的是 `MessageEvent`。

常用字段：

- `event.group`
  - 来源群名
- `event.content`
  - 消息文本
- `event.timestamp`
  - 收到消息时的时间戳
- `event.group_nickname`
  - 你在该群里的昵称
- `event.is_at_me`
  - 这条消息是否 @ 了你

示例：

```python
def on_message(event):
    print(event.group)
    print(event.content)
    print(event.is_at_me)
```

---

## 8. CallbackHandler：把普通函数变成消息处理器

最简单的 handler。

### 8.1 只监听，不自动回复

```python
from wx4py import CallbackHandler, WeChatClient


def on_message(event):
    print(f"[{event.group}] {event.content}")


with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [CallbackHandler(on_message)],
        block=True,
    )
```

### 8.2 回调返回字符串，自动回复

```python
from wx4py import CallbackHandler, WeChatClient


def on_message(event):
    if "你好" in event.content:
        return "你好呀"
    return ""


with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [CallbackHandler(on_message, auto_reply=True)],
        block=True,
    )
```

参数说明：

- `callback`
  - 收到消息后的处理函数
- `auto_reply`
  - 是否把回调返回的字符串自动发回群里
- `reply_on_at`
  - 只有被 @ 时才回复

---

## 9. AsyncCallbackHandler：适合 AI、网络请求等慢操作

如果你的回调会：

- 调 AI
- 调 HTTP 接口
- 调数据库

建议用 `AsyncCallbackHandler`，不要用同步 `CallbackHandler`。

原因：

- 同步回调会阻塞监听主链
- 异步回调不会卡住其他群的消息监听

示例：

```python
from wx4py import AsyncCallbackHandler, WeChatClient


def slow_reply(event):
    return "收到"


with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [AsyncCallbackHandler(slow_reply, auto_reply=True)],
        block=True,
    )
```

---

## 10. 群消息转发

转发能力由下面几个对象组成：

- `ForwardTarget`
- `GroupForwardRule`
- `ForwardRuleHandler`

### 10.1 ForwardTarget

表示转发目标。

```python
from wx4py import ForwardTarget

target = ForwardTarget("大号", target_type="contact")
```

参数说明：

- `name`
  - 目标名称
- `target_type`
  - `"contact"` 或 `"group"`

如果一条规则里的目标类型都相同，也可以不手动写 `ForwardTarget`，直接写字符串。

---

### 10.2 GroupForwardRule

表示一条转发规则。

最简单写法：

```python
from wx4py import GroupForwardRule

rule = GroupForwardRule(
    source_group="测试龙虾1",
    targets=["大号"],
    target_type="contact",
)
```

常用参数说明：

- `source_group`
  - 来源群名
- `targets`
  - 转发目标列表
  - 可以是字符串，也可以是 `ForwardTarget`
- `target_type`
  - 当 `targets` 是纯字符串时，默认按这个类型处理
- `mode`
  - `"all"`：全部转发
  - `"keyword"`：命中关键词才转发
  - `"mention"`：被 @ 才转发
  - `"custom"`：自定义判断
- `keywords`
  - `mode="keyword"` 时使用
- `exclude_keywords`
  - 命中这些词就不转发
- `require_at`
  - 是否要求被 @
- `prefix_template`
  - 转发前缀模板
- `predicate`
  - 自定义判断函数
- `transform`
  - 自定义转发内容构造函数

### 10.3 ForwardRuleHandler

把多条转发规则挂到 `process_groups()` 里。

```python
from wx4py import ForwardRuleHandler, GroupForwardRule, WeChatClient

rules = [
    GroupForwardRule(
        source_group="测试龙虾1",
        targets=["大号"],
        target_type="contact",
        prefix_template="[测试龙虾1] ",
    )
]

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [ForwardRuleHandler(rules)],
        block=True,
    )
```

参考示例：

- [forward_group_messages.py](E:/MyProject/me/wx4py/examples/messaging/forward_group_messages.py)

---

## 11. AI 自动回复

AI 相关主要有 3 个对象：

- `AIConfig`
- `AIClient`
- `AIResponder`

---

### 11.1 AIConfig

AI 接口配置。

```python
from wx4py import AIConfig

config = AIConfig(
    base_url="https://api.siliconflow.cn/v1",
    model="Pro/deepseek-ai/DeepSeek-V3.2",
    api_key="你的 API Key",
    api_format="completions",
)
```

常用参数说明：

- `base_url`
  - 你的 AI 服务地址
- `model`
  - 模型 ID
- `api_key`
  - 接口密钥
- `api_format`
  - `"completions"`
  - `"responses"`
  - `"anthropic"`
- `system_prompt`
  - 系统提示词
- `temperature`
  - 温度
- `max_tokens`
  - 最多返回多少 token
- `timeout`
  - 超时时间
- `enable_thinking`
  - 是否开启思考模式

---

### 11.2 AIClient

真正发送 HTTP 请求调用模型。

```python
from wx4py import AIClient, AIConfig

client = AIClient(
    AIConfig(
        base_url="https://api.siliconflow.cn/v1",
        model="Pro/deepseek-ai/DeepSeek-V3.2",
        api_key="你的 API Key",
        api_format="completions",
    )
)
```

最直接的调用：

```python
reply = client.chat([
    {"role": "user", "content": "你好"}
])
```

---

### 11.3 AIResponder

把 AIClient 包装成群消息回调。

它会自动：

- 读取消息内容
- 维护每个群自己的上下文
- 在需要时去掉 `@你的群昵称`
- 返回 AI 回复文本

示例：

```python
from wx4py import AIClient, AIConfig, AIResponder

responder = AIResponder(
    AIClient(
        AIConfig(
            base_url="https://api.siliconflow.cn/v1",
            model="Pro/deepseek-ai/DeepSeek-V3.2",
            api_key="你的 API Key",
            api_format="completions",
        )
    ),
    context_size=8,
    reply_on_at=True,
)
```

参数说明：

- `client`
  - `AIClient` 实例
- `context_size`
  - 每个群保留多少轮上下文
- `reply_on_at`
  - 是否只有被 @ 时才返回回复

---

### 11.4 AI 自动回复完整示例

```python
from wx4py import AIClient, AIConfig, AIResponder, AsyncCallbackHandler, WeChatClient

responder = AIResponder(
    AIClient(
        AIConfig(
            base_url="https://api.siliconflow.cn/v1",
            model="Pro/deepseek-ai/DeepSeek-V3.2",
            api_key="你的 API Key",
            api_format="completions",
            enable_thinking=False,
        )
    ),
    context_size=8,
    reply_on_at=True,
)

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [AsyncCallbackHandler(responder, auto_reply=True)],
        block=True,
    )
```

参考示例：

- [reply_groups_with_ai.py](E:/MyProject/me/wx4py/examples/messaging/reply_groups_with_ai.py)

---

## 12. 自定义 AI 接入

如果你不想用内置 `AIClient`，也没问题。

你只需要提供一个函数：

- 输入：`MessageEvent`
- 输出：字符串

示例：

```python
from wx4py import AsyncCallbackHandler, WeChatClient


def custom_reply(event):
    if not event.is_at_me:
        return ""
    return "收到，我来处理。"


with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [AsyncCallbackHandler(custom_reply, auto_reply=True, reply_on_at=True)],
        block=True,
    )
```

参考示例：

- [reply_groups_with_custom_ai.py](E:/MyProject/me/wx4py/examples/messaging/reply_groups_with_custom_ai.py)

---

## 13. 组合使用：转发 + AI 回复

这是当前最推荐的群机器人用法。

同一个 `process_groups()` 里可以挂多个 handler：

```python
from wx4py import (
    AIClient,
    AIConfig,
    AIResponder,
    AsyncCallbackHandler,
    ForwardRuleHandler,
    GroupForwardRule,
    WeChatClient,
)

rules = [
    GroupForwardRule(
        source_group="测试龙虾1",
        targets=["大号"],
        target_type="contact",
        prefix_template="[群消息转发] ",
    )
]

responder = AIResponder(
    AIClient(
        AIConfig(
            base_url="https://api.siliconflow.cn/v1",
            model="Pro/deepseek-ai/DeepSeek-V3.2",
            api_key="你的 API Key",
            api_format="completions",
        )
    ),
    context_size=8,
    reply_on_at=True,
)

with WeChatClient(auto_connect=True) as wx:
    wx.process_groups(
        ["测试龙虾1"],
        [
            ForwardRuleHandler(rules),
            AsyncCallbackHandler(responder, auto_reply=True),
        ],
        block=True,
    )
```

效果是：

- 所有群消息先转发给指定联系人
- 只有被 @ 时，AI 才在群里回复

参考示例：

- [process_group_messages.py](E:/MyProject/me/wx4py/examples/messaging/process_group_messages.py)

---

## 14. 常见问题

### 14.1 为什么推荐 `with WeChatClient(...) as wx`

因为这样不容易忘记断开连接。

推荐：

```python
with WeChatClient(auto_connect=True) as wx:
    ...
```

不推荐：

```python
wx = WeChatClient()
wx.connect()
...
```

除非你明确知道什么时候要手动 `disconnect()`。

### 14.2 群机器人为什么只建议用 `process_groups()`

因为现在已经统一了：

- 监听
- 转发
- 自动回复
- AI 回复

都走这一套消息处理管线。

### 14.3 `send_message()` 和 `send_to()` 有什么区别

- `send_message()`
  - 当前聊天已经打开时使用
- `send_to()`
  - 自动搜索并打开目标后再发送

一般用户更常用 `send_to()`。

### 14.4 为什么有时候拿不到发送者是谁

因为微信 4.x 的 Qt UIA 对外暴露的信息有限。

目前稳定能力主要是：

- 读取消息文本
- 判断是否 @ 我
- 读取群昵称

但“稳定获取发送者昵称”并不是当前版本强保证能力。

---

## 15. 推荐从哪些示例开始看

如果你是第一次使用，建议按这个顺序看：

1. [send_contact_message.py](E:/MyProject/me/wx4py/examples/sending/send_contact_message.py)
   - 先验证能不能正常连接微信并发送一条消息
2. [forward_group_messages.py](E:/MyProject/me/wx4py/examples/messaging/forward_group_messages.py)
   - 看群消息转发
3. [reply_groups_with_ai.py](E:/MyProject/me/wx4py/examples/messaging/reply_groups_with_ai.py)
   - 看 AI 自动回复
4. [process_group_messages.py](E:/MyProject/me/wx4py/examples/messaging/process_group_messages.py)
   - 看“转发 + AI 回复”的完整组合

---

## 16. 一句总结

如果你只记住一件事，就记住这三条：

1. 发消息、发文件、读聊天记录，看 `wx.chat_window`
2. 改群公告、取群成员、改群昵称，看 `wx.group_manager`
3. 做群监听、转发、AI 回复，看 `wx.process_groups()`
