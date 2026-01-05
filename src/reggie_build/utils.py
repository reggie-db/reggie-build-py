import functools
import hashlib
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import time

from reggie_build import projects

# Default version string used when git version cannot be determined
DEFAULT_VERSION = "0.0.1"


def logger(name: str | None = None):
    _configure_root_logger()
    if not name:
        name = projects.root().name
    else:
        if name == "__main__":
            name = __file__
        try:
            name_file = pathlib.Path(name)
            if name_file.is_file():
                name = name_file.stem
        except Exception:
            pass
    return logging.getLogger(name)


@functools.cache
def _configure_root_logger():
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
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[stdout_handler, stderr_handler],
    )
    handlers = {"stdout": stdout_handler, "stderr": stderr_handler}
    basic_config_handlers = []
    for name, handler in handlers.items():
        if handler in logging.root.handlers:
            basic_config_handlers.append(name)
    logging.root.debug(f"Basic config handlers: {basic_config_handlers}")


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


@functools.cache
def git_files() -> list[pathlib.Path] | None:
    git_exec = which("git")
    if git_exec:
        try:
            result = subprocess.run(
                [str(git_exec), "ls-files"],
                capture_output=True,
                text=True,
                check=True,
            )
            return [pathlib.Path(f) for f in result.stdout.splitlines() if f]
        except Exception:
            pass
    return None


def git_version() -> str | None:
    """
    Build a workspace version string from git commit hash.

    Constructs a version string in the format <default_version>+g<short_rev> using
    the current git commit hash. Returns None if git is unavailable or the command
    fails.

    Returns:
        Version string like "0.0.1+g767bd46" or None if git is unavailable
    """
    git_exec = which("git")
    if git_exec:
        try:
            rev = subprocess.check_output(
                [str(git_exec), "rev-parse", "--short", "HEAD"],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                text=True,
            ).strip()
            if rev:
                return f"{DEFAULT_VERSION}+g{rev}"
        except Exception:
            pass
    return None


@functools.lru_cache(maxsize=None)
def which(name: str) -> pathlib.Path | None:
    path = shutil.which(name)
    if path:
        return pathlib.Path(path)
    else:
        file = pathlib.Path(name)
        if file.is_file() and os.access(file, os.X_OK):
            return file
    logger(__file__).warning(f"Executable not found: {name}")
    return None


if __name__ == "__main__":
    logger(__name__).info("test")
    print(git_version())
    print(git_files())
    print(which("tunaf"))
