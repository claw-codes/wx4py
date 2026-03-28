# -*- coding: utf-8 -*-
"""Configuration for wx4py"""
import os

# WeChat window class names (new Qt-based version)
WECHAT_WINDOW_CLASS = 'Qt51514QWindowIcon'
WECHAT_MAIN_CLASS = 'mmui::MainWindow'
WECHAT_WINDOW_TITLE = '微信'

# Registry settings for UI Automation
REGISTRY_PATH = r"SOFTWARE\Microsoft\Narrator\NoRoam"
REGISTRY_KEY = "RunningState"

# Timeouts (seconds)
DEFAULT_TIMEOUT = 10
SEARCH_TIMEOUT = 5
OPERATION_INTERVAL = 0.3

# UI Automation IDs
MAIN_TABBAR_ID = 'main_tabbar'
MAIN_SPLITTER_ID = 'main_window_main_splitter_view'
SUB_SPLITTER_ID = 'main_window_sub_splitter_view'

# Logging
LOG_LEVEL = os.environ.get('WECHAT_LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'