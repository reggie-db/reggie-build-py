"""
General utility functions for the reggie-build tool.

This module provides common functionality used across the workspace management
toolset including:
- Logging configuration with stdout/stderr separation
- File watching for continuous regeneration workflows
- Git integration for version strings and file tracking
- System-level operations like executable discovery
- Development environment helpers

The logger function configures logging with INFO to stdout and WARNING+ to stderr,
respecting the LOG_LEVEL environment variable.
"""

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
    """
    Get a configured logger instance.

    Args:
        name: Name of the logger. If omitted, defaults to the root project name.
              If "__main__", uses the current file name.

    Returns:
        A logging.Logger instance
    """
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
    """
    Configure the root logger with stdout and stderr handlers.

    Logs up to INFO level are directed to stdout, while WARNING and above
    are directed to stderr. Log level can be controlled via the LOG_LEVEL
    environment variable.

    This function uses functools.cache to ensure configuration only happens once.
    """
    log_level_env = os.getenv("LOG_LEVEL", "").upper()
    log_level = logging.getLevelNamesMapping().get(log_level_env, logging.INFO)

    class StdoutFilter(logging.Filter):
        """Filter that passes only INFO and below to stdout."""

        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno <= logging.INFO

    class StderrFilter(logging.Filter):
        """Filter that passes only WARNING and above to stderr."""

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
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[stdout_handler, stderr_handler],
    )
    handlers = {"stdout": stdout_handler, "stderr": stderr_handler}
    basic_config_handlers = []
    for name, handler in handlers.items():
        if handler in logging.root.handlers:
            basic_config_handlers.append(name)
    logging.root.debug(f"Basic config handlers: {basic_config_handlers}")


def dev_local() -> pathlib.Path:
    """
    Return the path to the dev-local directory in the workspace root.

    This directory is used for temporary development files and generated code,
    such as OpenAPI-generated projects.

    Returns:
        Path to the dev-local directory
    """
    root_dir = projects.root_dir()
    return root_dir / "dev-local"


def watch_file(src: pathlib.Path, interval: float = 2.0):
    """
    Yield the current file hash each time it changes.

    Continuously monitors a file and yields its SHA-256 hash whenever the
    content changes. Useful for watch mode operations that regenerate
    output when input files are modified.

    Args:
        src: Path to the file to watch
        interval: Time in seconds between checks (default 2.0)

    Yields:
        SHA-256 hex digest of the file content whenever it changes

    Raises:
        KeyboardInterrupt: Stops iteration cleanly on interrupt
    """

    def _hash(p: pathlib.Path) -> str:
        """
        Calculate the SHA-256 hash of a file.

        Args:
            p: Path to file to hash

        Returns:
            SHA-256 hex digest of file contents
        """
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
    """
    Get a list of all files tracked by git in the current repository.

    Returns:
        A list of Path objects for git-tracked files, or None if git fails.
    """
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
    """
    Locate an executable in the system path.

    Args:
        name: Name or path of the executable to find

    Returns:
        Path to the executable if found, otherwise None
    """
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
