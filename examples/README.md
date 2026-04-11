# Examples

示例脚本已按用途归类：

- `sending/`
  - 基础发送能力：给联系人/群发消息、发送文件、批量发送。
- `groups/`
  - 群管理能力：群成员、群公告、免打扰、置顶、群昵称。
- `messaging/`
  - 消息处理能力：群监听、消息转发、AI 自动回复、组合处理管线。
- `inspect/`
  - 检查与调试：搜索、聊天记录读取。

推荐从这些脚本开始：

- `python examples\sending\send_contact_message.py`
  - 最小发送冒烟验证。
- `python examples\messaging\forward_group_messages.py`
  - 群消息转发示例。
- `python examples\messaging\reply_groups_with_ai.py`
  - 接入 AI 的群聊自动回复。
- `python examples\messaging\process_group_messages.py`
  - 转发 + AI 回复的统一处理管线示例。

说明：

- 所有示例都支持直接从源码目录运行。
- 所有示例都把“需要你修改的内容”放在脚本顶部，先改顶部常量，再运行。
- 运行前请先按脚本注释修改联系人名、群名、文件路径和环境变量。
