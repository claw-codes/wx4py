# -*- coding: utf-8 -*-
"""Configuration for wx4py"""
import os

# Timeouts (seconds)
SEARCH_TIMEOUT = 5
OPERATION_INTERVAL = 0.3

# Logging
LOG_LEVEL = os.environ.get('WECHAT_LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
