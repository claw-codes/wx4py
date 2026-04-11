# -*- coding: utf-8 -*-
"""工具模块"""

from .clipboard_utils import set_files_to_clipboard, set_text_to_clipboard
from .logger import get_logger
from .markdown_utils import copy_html_to_clipboard, markdown_to_html, read_markdown_file

__all__ = [
    "get_logger",
    "set_text_to_clipboard",
    "set_files_to_clipboard",
    "markdown_to_html",
    "copy_html_to_clipboard",
    "read_markdown_file",
]
