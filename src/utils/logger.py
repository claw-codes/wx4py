# -*- coding: utf-8 -*-
"""Logging utilities"""
import logging
import sys

from ..config import LOG_LEVEL, LOG_FORMAT


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    return logger