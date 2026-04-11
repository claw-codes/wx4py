# 快速开始

## 1️⃣ 安装

```bash
pip install wx4py
```

## 2️⃣ 基本使用

```python
from wx4py import WeChatClient

with WeChatClient() as wx:
    # 发消息
    wx.chat_window.send_to("文件传输助手", "Hello!")

    # 批量群发
    wx.chat_window.batch_send(["群1", "群2"], "通知内容", target_type='group')

    # 发文件
    wx.chat_window.send_file_to("文件传输助手", r"C:\file.pdf")

    # 获取聊天记录
    messages = wx.chat_window.get_chat_history("工作群", target_type='group', since='today')
```

## 3️⃣ 在 AI 中使用

在 Claude Code 或 OpenClaw 中：

```
使用 wx4-skill 向这3个群发送通知：群1、群2、群3
消息：明天下午3点开会
```

AI 会自动生成代码并执行！

## 📚 更多

- 完整功能：[README.md](../../README.md)
- 接口文档：[API_GUIDE.md](./API_GUIDE.md)
- AI Skill：[wx4-skill/SKILL.md](../../wx4-skill/SKILL.md)
- 示例代码：[examples/](../../examples/)

## 🔧 构建和发布

```bash
# 构建
pip install build
python -m build

# 本地测试
pip install dist/*.whl

# 发布到 PyPI
pip install twine
twine upload dist/*
```
