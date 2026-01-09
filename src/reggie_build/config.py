import functools
import logging
import os
import sys
from typing import Callable, TextIO

"""
Configuration and logging initialization for reggie-build.

This module sets up the logging configuration. The init() function is cached
and intended to be automatically loaded by a site customizer, though it can
also be called manually as needed.
"""

LOG_LEVEL_ENV_NAME = "LOG_LEVEL"


@functools.cache
def init():
    """
    Initialize the logging configuration for the application.

    This function sets up handlers for both stdout (INFO only) and stderr
    (all other levels) with specific formatting and date formats. It uses
    the LOG_LEVEL environment variable to determine the global logging level,
    defaulting to INFO.
    """
    date_format = "%Y-%m-%d %H:%M:%S"
    format_stdout = "%(message)s"
    format_stderr = (
        "%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s:%(lineno)d - %(message)s"
    )
    log_level_env = os.getenv(LOG_LEVEL_ENV_NAME, "").upper()
    log_level = logging.getLevelNamesMapping().get(log_level_env, logging.INFO)

    def _create_handler(
        stream: TextIO,
        level: int,
        format: str,
        filter_fn: Callable[[logging.LogRecord], bool] | None = None,
    ) -> logging.Handler:
        handler = logging.StreamHandler(stream)  # type: ignore[arg-type]
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(format))
        if filter_fn is not None:
            handler.addFilter(filter_fn)
        return handler

    handlers = [
        _create_handler(
            sys.stdout,
            logging.INFO,
            format_stdout,
            lambda record: record.levelno == logging.INFO,
        ),
        _create_handler(
            sys.stderr,
            logging.DEBUG,
            format_stderr,
            lambda record: record.levelno != logging.INFO,
        ),
    ]

    logging.basicConfig(
        level=log_level,
        datefmt=date_format,
        handlers=handlers,
    )
