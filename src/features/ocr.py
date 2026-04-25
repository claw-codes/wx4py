# -*- coding: utf-8 -*-
"""微信昵称OCR识别模块

使用Windows内置OCR引擎，无需安装第三方依赖。
Windows 10/11自带中文OCR支持。

使用方法:
    from src.features.ocr import WeChatNicknameOCR
    ocr = WeChatNicknameOCR()
    nickname = ocr.recognize_nickname(screenshot, msg_rect)
"""

import os
import subprocess
import tempfile
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class WindowsOCR:
    """Windows内置OCR引擎

    注意：由于PowerShell 5.1与WinRT异步操作的互操作限制，
    Windows.Media.Ocr可能无法正常工作。
    """

    @classmethod
    def recognize(cls, image_path: str) -> str:
        """
        使用Windows OCR识别图片中的文字

        Args:
            image_path: 图片文件路径

        Returns:
            识别出的文字，失败返回空字符串
        """
        if not os.path.exists(image_path):
            logger.warning(f"图片文件不存在: {image_path}")
            return ""

        # 尝试使用Windows.Media.Ocr
        # 注意：由于PowerShell与WinRT异步操作的互操作问题，此功能可能无法正常工作
        try:
            result = cls._recognize_with_winrt(image_path)
            if result:
                return result
        except Exception as e:
            logger.debug(f"WinRT OCR失败: {e}")

        # 备用方案：使用剪贴板传递图片
        try:
            result = cls._recognize_via_clipboard(image_path)
            if result:
                return result
        except Exception as e:
            logger.debug(f"剪贴板OCR失败: {e}")

        return ""

    @classmethod
    def _recognize_with_winrt(cls, image_path: str) -> str:
        """使用Windows.Media.Ocr进行识别"""
        ps_script = r'''
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null

$imgPath = '{image_path}'

try {{
    # 创建异步操作并等待
    $fileTask = [Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)
    Start-Sleep -Milliseconds 500
    $file = $fileTask.GetAwaiter().GetResult()
    
    $streamTask = $file.OpenReadAsync()
    Start-Sleep -Milliseconds 500
    $stream = $streamTask.GetAwaiter().GetResult()
    
    $decoderTask = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
    Start-Sleep -Milliseconds 500
    $decoder = $decoderTask.GetAwaiter().GetResult()
    
    $bitmapTask = $decoder.GetPixelBitmapAsync()
    Start-Sleep -Milliseconds 500
    $bitmap = $bitmapTask.GetAwaiter().GetResult()
    
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {{
        Write-Output "NO_ENGINE"
    }} else {{
        $ocrTask = $engine.RecognizeAsync($bitmap)
        Start-Sleep -Milliseconds 1000
        $result = $ocrTask.GetAwaiter().GetResult()
        Write-Output $result.Text
    }}
}} catch {{
    Write-Output "ERROR: $($_.Exception.Message)"
}}
'''.format(image_path=image_path.replace('\\', '\\\\'))

        result = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            if output.startswith("ERROR:"):
                raise Exception(output)
            elif output == "NO_ENGINE":
                raise Exception("OCR引擎不可用")
            return output
        raise Exception(result.stderr)

    @classmethod
    def _recognize_via_clipboard(cls, image_path: str) -> str:
        """通过剪贴板传递图片进行OCR识别"""
        # 这个方法尝试将图片放入剪贴板，然后使用Windows的照片应用
        # 但由于需要WinRT OCR，目前也无法工作
        raise NotImplementedError("剪贴板OCR方案暂未实现")

    @classmethod
    def is_available(cls) -> bool:
        """检查Windows OCR是否可用"""
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null; Write-Host 'OK'"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and "OK" in result.stdout
        except Exception:
            return False


class WeChatNicknameOCR:
    """
    微信昵称OCR识别器

    用于从微信群聊消息气泡的截图区域识别发送者昵称。
    只需要截取消息气泡上方的昵称区域即可。

    使用方法:
        ocr = WeChatNicknameOCR()
        # screenshot: PIL Image对象
        # msg_rect: 消息气泡的(BoundingRectangle)
        nickname = ocr.recognize_from_screenshot(screenshot, msg_rect)
    """

    # 昵称区域相对消息气泡的偏移
    # 微信群聊中，昵称通常在消息气泡上方约10-25像素
    NICKNAME_TOP_OFFSET = -25  # 消息气泡上方的偏移
    NICKNAME_BOTTOM_OFFSET = -5  # 到气泡顶部

    # 昵称区域宽度（从头像右侧开始）
    NICKNAME_LEFT_OFFSET = 45  # 消息左边缘+头像宽度
    NICKNAME_WIDTH = 150  # 昵称区域宽度

    @classmethod
    def recognize_from_screenshot(cls, screenshot, msg_rect) -> str:
        """
        从截图识别消息发送者昵称

        Args:
            screenshot: PIL Image对象，微信窗口截图
            msg_rect: 消息气泡的BoundingRectangle

        Returns:
            识别出的昵称，失败返回空字符串
        """
        try:
            # 计算昵称区域
            # 昵称在消息气泡上方，头像右侧
            nick_top = msg_rect.top + cls.NICKNAME_TOP_OFFSET
            nick_bottom = msg_rect.top + cls.NICKNAME_BOTTOM_OFFSET
            nick_left = msg_rect.left + cls.NICKNAME_LEFT_OFFSET
            nick_right = nick_left + cls.NICKNAME_WIDTH

            # 确保坐标在截图范围内
            if nick_top < 0 or nick_right > screenshot.width:
                logger.debug("昵称区域超出截图范围")
                return ""

            # 裁剪昵称区域
            nickname_region = screenshot.crop((
                max(0, nick_left),
                max(0, nick_top),
                min(screenshot.width, nick_right),
                min(screenshot.height, nick_bottom)
            ))

            # 保存临时文件用于OCR
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                temp_path = f.name

            try:
                nickname_region.save(temp_path, 'PNG')
                text = WindowsOCR.recognize(temp_path)

                # 清理OCR结果
                if text:
                    text = text.strip()
                    # 移除可能的换行符和多余空格
                    text = ' '.join(text.split())

                return text
            finally:
                # 删除临时文件
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"昵称识别异常: {e}")
            return ""

    @classmethod
    def recognize_from_file(cls, image_path: str, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """
        从图片文件识别昵称

        Args:
            image_path: 图片文件路径
            region: 可选，指定裁剪区域(left, top, right, bottom)

        Returns:
            识别出的昵称
        """
        try:
            from PIL import Image
        except ImportError:
            logger.error("需要安装Pillow: pip install Pillow")
            return ""

        try:
            img = Image.open(image_path)

            if region:
                img = img.crop(region)

            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                temp_path = f.name

            try:
                img.save(temp_path, 'PNG')
                return WindowsOCR.recognize(temp_path)
            finally:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"文件识别异常: {e}")
            return ""

    @classmethod
    def is_available(cls) -> bool:
        """检查OCR功能是否可用"""
        return WindowsOCR.is_available()


# 便捷函数
def recognize_wechat_nickname(screenshot, msg_rect) -> str:
    """
    识别微信消息发送者昵称

    Args:
        screenshot: PIL Image对象，微信窗口截图
        msg_rect: 消息气泡的BoundingRectangle

    Returns:
        识别出的昵称，失败返回空字符串
    """
    return WeChatNicknameOCR.recognize_from_screenshot(screenshot, msg_rect)


def is_ocr_available() -> bool:
    """检查OCR功能是否可用"""
    return WeChatNicknameOCR.is_available()
