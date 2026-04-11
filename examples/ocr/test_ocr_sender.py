# -*- coding: utf-8 -*-
"""
OCR发送者识别测试

这个脚本用于测试PaddleOCR是否能正确识别微信群聊消息的发送者昵称。

测试步骤：
1. 手动截取包含微信群聊消息的截图
2. 运行此脚本进行OCR识别
3. 检查是否能正确识别发送者昵称
"""
import os
import sys
import tempfile

# 添加项目根目录到路径
project_root = r'D:\yeafel\pycharmWorkspace\wx4py'
sys.path.insert(0, project_root)
os.chdir(project_root)

from src.utils.ocr_utils import recognize_text, recognize_sender, find_sender_in_region, get_ocr_tool

def test_existing_screenshot():
    """测试已有的截图"""
    test_image = r'D:\yeafel\pycharmWorkspace\wx4py\ocr_debug_screenshot.png'

    if not os.path.exists(test_image):
        print(f"测试图片不存在: {test_image}")
        print("请提供测试图片路径")
        return

    print("=" * 60)
    print("测试OCR发送者识别")
    print("=" * 60)

    print(f"\n测试图片: {test_image}")
    print("\n【识别所有文字】")
    texts = recognize_text(test_image)
    for text, confidence, bbox in texts:
        print(f"  [{confidence:.2f}] {text}")

    print("\n【识别发送者昵称 - recognize_sender】")
    sender = recognize_sender(test_image)
    print(f"  识别结果: {sender}")

    print("\n【识别发送者昵称 - find_sender_in_region】")
    sender2 = find_sender_in_region(test_image, region_top=0)
    print(f"  识别结果: {sender2}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


def test_custom_screenshot():
    """测试用户提供的截图"""
    print("\n请输入截图文件路径（或直接回车使用默认测试图片）:")
    image_path = input().strip()

    if not image_path:
        test_existing_screenshot()
        return

    if not os.path.exists(image_path):
        print(f"文件不存在: {image_path}")
        return

    print(f"\n测试图片: {image_path}")
    print("\n【识别所有文字】")
    texts = recognize_text(image_path)
    for text, confidence, bbox in texts:
        print(f"  [{confidence:.2f}] {text}")

    print("\n【识别发送者昵称 - recognize_sender】")
    sender = recognize_sender(image_path)
    print(f"  识别结果: {sender}")

    print("\n【识别发送者昵称 - find_sender_in_region】")
    sender2 = find_sender_in_region(image_path, region_top=0)
    print(f"  识别结果: {sender2}")


def test_ocr_speed():
    """测试OCR速度"""
    test_image = r'D:\yeafel\pycharmWorkspace\wx4py\ocr_debug_screenshot.png'

    if not os.path.exists(test_image):
        print(f"测试图片不存在")
        return

    import time

    # 初始化OCR引擎（首次会下载模型）
    print("\n初始化OCR引擎...")
    start = time.time()
    _ = get_ocr_tool()
    init_time = time.time() - start
    print(f"初始化耗时: {init_time:.2f}秒")

    # 测试识别速度
    print("\n测试OCR识别速度（10次）...")
    times = []
    for i in range(10):
        start = time.time()
        texts = recognize_text(test_image)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"  第{i+1}次: {elapsed:.3f}秒")

    avg_time = sum(times) / len(times)
    print(f"\n平均耗时: {avg_time:.3f}秒")


if __name__ == '__main__':
    print("OCR发送者识别测试")
    print("1. 测试已有截图")
    print("2. 测试自定义截图")
    print("3. 测试OCR速度")
    print()

    choice = input("请选择 (1/2/3): ").strip()

    if choice == '1':
        test_existing_screenshot()
    elif choice == '2':
        test_custom_screenshot()
    elif choice == '3':
        test_ocr_speed()
    else:
        test_existing_screenshot()
