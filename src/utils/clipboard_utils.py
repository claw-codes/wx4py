# -*- coding: utf-8 -*-
"""Clipboard utilities for clipboard operations"""
import os
import struct
import win32clipboard
import win32con


def set_files_to_clipboard(file_paths):
    """
    Set file paths to clipboard in CF_HDROP format.

    This allows pasting files into applications like WeChat chat input.

    Args:
        file_paths: Single file path string or list of file paths

    Returns:
        bool: True if successful

    Raises:
        ValueError: If file path doesn't exist
    """
    # Convert single string to list
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    # Validate file paths
    valid_paths = []
    for path in file_paths:
        if os.path.exists(path):
            valid_paths.append(os.path.abspath(path))
        else:
            raise ValueError(f"File not found: {path}")

    if not valid_paths:
        return False

    try:
        # Open clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()

        # Build DROPFILES header (20 bytes)
        # pFiles offset, pt.x, pt.y, fNC, fWide
        offset = 20
        dropfiles_header = struct.pack('<LLLLL', offset, 0, 0, 0, 1)

        # Build file path list (Unicode, double-null terminated)
        file_list = []
        for path in valid_paths:
            file_list.append(path.encode('utf-16le'))
            file_list.append(b'\x00\x00')  # Null terminator

        # Extra double-null as list end marker
        file_list.append(b'\x00\x00')

        # Combine all data
        file_data = b''.join(file_list)
        hdrop_data = dropfiles_header + file_data

        # Set to clipboard
        win32clipboard.SetClipboardData(win32con.CF_HDROP, hdrop_data)

        return True

    except Exception:
        return False

    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


def set_text_to_clipboard(text: str) -> bool:
    """
    Set Unicode text to clipboard.

    Args:
        text: Text content

    Returns:
        bool: True if successful
    """
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        return True
    except Exception:
        return False
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
