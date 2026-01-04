import functools
import hashlib
import logging
import os
import pathlib
import sys
import time

from scripts import projects


def logger(name: str | None = None):
    _configure_root_logger()
    if not name:
        name = projects.root().name
    else:
        try:
            name_file = pathlib.Path(name)
            if name_file.is_file():
                name = name_file.stem
        except Exception:
            pass
    return logging.getLogger(name)


@functools.cache
def _configure_root_logger() -> int:
    log_level_env = os.getenv("LOG_LEVEL", "").upper()
    log_level = logging.getLevelNamesMapping().get(log_level_env, logging.INFO)

    class StdoutFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno <= logging.INFO

    class StderrFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno > logging.INFO

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(StdoutFilter())

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.addFilter(StderrFilter())

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[stdout_handler, stderr_handler],
    )

    basic_config_count = 0
    for handler in [stdout_handler, stderr_handler]:
        if handler in logging.root.handlers:
            basic_config_count += 1
    return basic_config_count


def watch_file(src: pathlib.Path, interval: float = 2.0):
    """Yield the current file hash each time it changes"""

    def _hash(p: pathlib.Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    last_hash = None
    while True:
        try:
            current = _hash(src)
            if current != last_hash:
                last_hash = current
                yield current
            time.sleep(interval)
        except FileNotFoundError:
            time.sleep(interval)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    logger(__name__).info("test")
