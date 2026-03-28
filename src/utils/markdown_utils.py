# -*- coding: utf-8 -*-
"""Markdown and clipboard utilities"""
import markdown
import win32clipboard
from bs4 import BeautifulSoup


def markdown_to_html(md_content: str) -> str:
    """
    Convert markdown to styled HTML.

    Args:
        md_content: Markdown content string

    Returns:
        HTML string with inline styles
    """
    # Convert markdown to HTML
    html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])

    # Add inline styles for better rendering
    styled_html = html_body

    # Style tables
    styled_html = styled_html.replace(
        '<table>',
        '<table style="border-collapse: collapse; width: 100%; margin: 10px 0;">'
    )
    styled_html = styled_html.replace(
        '<th>',
        '<th style="border: 1px solid #ddd; padding: 8px; background-color: #f5f5f5; text-align: left;">'
    )
    styled_html = styled_html.replace(
        '<td>',
        '<td style="border: 1px solid #ddd; padding: 8px;">'
    )

    # Style headers
    styled_html = styled_html.replace(
        '<h1>',
        '<h1 style="font-size: 20px; font-weight: bold; margin: 15px 0 10px 0;">'
    )
    styled_html = styled_html.replace(
        '<h2>',
        '<h2 style="font-size: 16px; font-weight: bold; margin: 12px 0 8px 0;">'
    )
    styled_html = styled_html.replace(
        '<h3>',
        '<h3 style="font-size: 14px; font-weight: bold; margin: 10px 0 6px 0;">'
    )

    return styled_html


def copy_html_to_clipboard(html: str) -> bool:
    """
    Copy HTML to clipboard in CF_HTML format for Windows.

    This allows pasting formatted content into applications like WeChat.

    Args:
        html: HTML content string

    Returns:
        True if successful
    """
    # Create CF_HTML format with proper header
    html_with_fragment = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<!--StartFragment-->
{html}
<!--EndFragment-->
</body>
</html>'''

    html_bytes = html_with_fragment.encode('utf-8')

    # Create header template
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:000000000\r\n"
        "EndHTML:{end_html:09d}\r\n"
        "StartFragment:000000000\r\n"
        "EndFragment:{end_fragment:09d}\r\n"
    )

    # Calculate offsets
    start_html = len(header_template.format(end_html=0, end_fragment=0).encode('utf-8'))
    end_html = start_html + len(html_bytes)

    start_fragment = html_with_fragment.find('<!--StartFragment-->')
    end_fragment = html_with_fragment.find('<!--EndFragment-->')

    if start_fragment != -1 and end_fragment != -1:
        start_fragment = start_html + start_fragment + len('<!--StartFragment-->')
        end_fragment = start_html + end_fragment

    # Create final header
    header = (
        f"Version:0.9\r\n"
        f"StartHTML:{start_html:09d}\r\n"
        f"EndHTML:{end_html:09d}\r\n"
        f"StartFragment:{start_fragment:09d}\r\n"
        f"EndFragment:{end_fragment:09d}\r\n"
    )

    # Combine header and HTML
    cf_html = header.encode('utf-8') + html_bytes

    # Open clipboard and set data
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()

        # Register and set HTML format
        cf_html_format = win32clipboard.RegisterClipboardFormat("HTML Format")
        win32clipboard.SetClipboardData(cf_html_format, cf_html)

        # Also set plain text as fallback
        soup = BeautifulSoup(html, 'html.parser')
        plain_text = soup.get_text(separator='\n')
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, plain_text)

        return True
    finally:
        win32clipboard.CloseClipboard()


def read_markdown_file(file_path: str) -> str:
    """
    Read markdown file content.

    Args:
        file_path: Path to markdown file

    Returns:
        Markdown content string
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()