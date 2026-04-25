# -*- coding: utf-8 -*-
"""
PaddleOCR 使用示例
"""
import os
import sys

# 添加项目根目录到路径
project_root = r'D:\yeafel\pycharmWorkspace\wx4py'
sys.path.insert(0, project_root)

# 确保项目包可以被正确导入
os.chdir(project_root)

# 现在可以直接导入
from src.utils.ocr_utils import recognize_text, recognize_sender

# 测试图片
test_image = r'D:\yeafel\pycharmWorkspace\wx4py\ocr_debug_screenshot.png'

print("=" * 50)
print("PaddleOCR 使用示例")
print("=" * 50)

# 识别所有文字
print("\n【识别所有文字】")
texts = recognize_text(test_image)
for text, confidence in texts:
    print(f"  {text} (置信度: {confidence:.2f})")

# 识别发送者
print("\n【识别发送者昵称】")
sender = recognize_sender(test_image)
if sender:
    print(f"  发送者: {sender}")
else:
    print("  未识别到发送者")

print("\n" + "=" * 50)
