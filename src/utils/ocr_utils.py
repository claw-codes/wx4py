# -*- coding: utf-8 -*-
"""
OCR工具模块 - 基于PaddleOCR
"""
import os
import time
import threading
import queue
from typing import List, Tuple, Optional, Callable


class OCRTool:
    """轻量级OCR工具类，用于识别图片中的文字"""

    _instance: Optional['OCRTool'] = None
    _ocr = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._ocr is None:
            self._initialize()

    def _initialize(self):
        """初始化PaddleOCR引擎"""
        try:
            from paddleocr import PaddleOCR

            # 禁用角度分类以提高速度（群聊消息通常不需要）
            self._ocr = PaddleOCR(
                lang='ch',
                use_angle_cls=False,
                show_log=False,
                det_db_thresh=0.3,  # 检测阈值，降低可提高召回率
                rec_batch_num=6     # 批处理大小
            )
            print("OCR工具初始化完成")
        except ImportError as e:
            raise ImportError(
                "PaddleOCR未安装。请运行: pip install paddleocr==2.7.3\n"
                "注意：paddleocr需要paddlepaddle支持: pip install paddlepaddle==2.6.2"
            ) from e
        except Exception as e:
            raise RuntimeError(f"OCR初始化失败: {e}") from e

    def recognize(self, image_path: str) -> List[Tuple[str, float]]:
        """
        识别图片中的文字

        Args:
            image_path: 图片路径

        Returns:
            List of (text, confidence, bounding_box) tuples
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")

        try:
            result = self._ocr.ocr(image_path)

            if not result or not result[0]:
                return []

            # 提取文字、置信度和位置
            texts = []
            for line in result[0]:
                text = line[1][0].strip()
                confidence = line[1][1]
                bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                if text:  # 过滤空字符串
                    texts.append((text, confidence, bbox))

            return texts

        except Exception as e:
            raise RuntimeError(f"OCR识别失败: {e}") from e

    def recognize_sender(self, image_path: str) -> Optional[str]:
        """
        识别微信消息发送者昵称

        这个方法专门针对微信截图格式进行了优化，
        会尝试从消息行中提取"昵称:"格式的内容

        Args:
            image_path: 截图路径

        Returns:
            发送者昵称，如果未识别到返回None
        """
        texts = self.recognize(image_path)

        for text, confidence, bbox in texts:
            # 匹配 "昵称:" 格式
            if ':' in text:
                parts = text.split(':', 1)
                if len(parts[0]) <= 20 and confidence > 0.8:
                    # 排除时间格式 (如 "20:10")
                    if not parts[0].replace(' ', '').replace(':', '').isdigit():
                        return parts[0].strip()

        return None

    def find_sender_in_region(self, image_path: str, region_top: int) -> Optional[str]:
        """
        在指定区域查找发送者昵称

        微信群聊消息格式通常是：
        - 昵称: 消息内容
        - 或者多行消息：昵称在左上角

        Args:
            image_path: 截图路径
            region_top: 消息区域的顶部Y坐标（用于过滤）

        Returns:
            发送者昵称
        """
        texts = self.recognize(image_path)

        # 按Y坐标排序（从上到下）
        texts.sort(key=lambda x: x[2][0][1] if x[2] else 0)

        for text, confidence, bbox in texts:
            # 匹配 "昵称:" 格式
            if confidence < 0.75:
                continue

            if ':' in text:
                parts = text.split(':', 1)
                nickname = parts[0].strip()

                # 昵称长度合理（排除时间）
                if 1 < len(nickname) <= 20 and not nickname.replace(' ', '').replace(':', '').isdigit():
                    return nickname

        return None


# 全局单例
_ocr_tool: Optional[OCRTool] = None


def get_ocr_tool() -> OCRTool:
    """获取OCR工具单例"""
    global _ocr_tool
    if _ocr_tool is None:
        _ocr_tool = OCRTool()
    return _ocr_tool


def recognize_text(image_path: str) -> List[Tuple[str, float]]:
    """快捷函数：识别图片文字"""
    return get_ocr_tool().recognize(image_path)


def recognize_sender(image_path: str) -> Optional[str]:
    """快捷函数：识别发送者昵称"""
    return get_ocr_tool().recognize_sender(image_path)


def find_sender_in_region(image_path: str, region_top: int = 0) -> Optional[str]:
    """快捷函数：在指定区域查找发送者"""
    return get_ocr_tool().find_sender_in_region(image_path, region_top)


# ============================================================
# 异步OCR发送者识别器
# ============================================================

class AsyncOcrResolver:
    """
    异步OCR发送者识别器

    用于在后台线程中通过OCR识别消息发送者。
    避免阻塞主监听循环。

    使用方法:
        resolver = AsyncOcrResolver(callback=on_sender_resolved)

        # 收到新消息时
        resolver.resolve_sender(image_path, msg_rect, session_id)

        # 停止时
        resolver.stop()
    """

    def __init__(self, callback: Optional[Callable[[str, str, str], None]] = None):
        """
        Args:
            callback: 识别完成回调，签名为 (session_id, sender_name, image_path)
        """
        self.callback = callback
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self):
        """启动后台处理线程"""
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        """停止后台处理"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._running = False

    def resolve_sender(self, image_path: str, msg_rect, session_id: str = ""):
        """
        请求识别发送者

        Args:
            image_path: 截图路径
            msg_rect: 消息区域的BoundingRectangle
            session_id: 会话标识（用于回调匹配）
        """
        if not self._running:
            self.start()

        # 计算昵称区域（消息气泡上方）
        # 昵称通常在消息气泡上方约20-30像素，头像右侧
        try:
            nickname_region = (
                msg_rect.left + 50,   # 左边留出头像位置
                max(0, msg_rect.top - 30),  # 上偏移
                msg_rect.right,       # 右边
                msg_rect.top + 5      # 到消息气泡顶部
            )
        except Exception:
            nickname_region = None

        self._queue.put({
            'image_path': image_path,
            'msg_rect': msg_rect,
            'nickname_region': nickname_region,
            'session_id': session_id
        })

    def _run(self):
        """后台处理循环"""
        import tempfile
        from PIL import Image

        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            image_path = task['image_path']
            msg_rect = task['msg_rect']
            session_id = task['session_id']
            nickname_region = task['nickname_region']

            try:
                # 如果有区域限制，先裁剪
                if nickname_region:
                    img = Image.open(image_path)
                    cropped = img.crop(nickname_region)

                    # 保存临时文件
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                        temp_path = f.name

                    cropped.save(temp_path, 'PNG')
                    image_to_process = temp_path
                else:
                    image_to_process = image_path
                    temp_path = None

                # OCR识别
                sender_name = find_sender_in_region(image_to_process, region_top=0)

                # 回调
                if self.callback and sender_name:
                    self.callback(session_id, sender_name, image_path)

            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(f"OCR识别失败: {e}")

            finally:
                # 清理临时文件
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
