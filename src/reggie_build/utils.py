"""
General utility functions for the reggie-build tool.

This module provides common functionality used across the workspace management
toolset including:
- Logging configuration with stdout/stderr separation
- File watching for continuous regeneration workflows
- Git integration for version strings and file tracking
- System-level operations like executable discovery
- Development environment helpers
- Dictionary path utilities for nested key access

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
from typing import Any, Mapping

import tomlkit
import typer

from reggie_build import projects

# Default version string used when git version cannot be determined
DEFAULT_VERSION = "0.0.1"


def clean_text(text: str) -> str:
    text = "" if text is None else text.strip()
    if text:
        lines = text.splitlines()
        out = []
        for line in lines:
            line = line.rstrip()
            if line or (out and out[-1]):
                out.append(line)
        text = "\n".join(out).rstrip()
    return text + "\n" if text else ""


def mapping_get(data: Mapping | None, *path: str, default: Any = None) -> Any:
    """
    Get a value from a nested dictionary or TOML document using a path of keys.

    Args:
        data: Dictionary or TOML document to traverse, or None
        *path: Sequence of keys to traverse
        default: Value to return if path not found

    Returns:
        Value at the path, or default if not found

    Example:
        dict_get({"a": {"b": {"c": 1}}}, "a", "b", "c") returns 1
        dict_get({"a": {"b": {}}}, "a", "b", "c", default=0) returns 0
    """
    if not data:
        return default

    current = data
    for key in path:
        if not isinstance(current, (dict, tomlkit.TOMLDocument)):
            return default
        current = current.get(key)
        if current is None:
            return default

    return current


def mapping_set(data: Mapping, *path: str, value: Any) -> bool:
    """
    Set a value in a nested dictionary using a path of keys.

    Creates intermediate dictionaries as needed.

    Args:
        data: Dictionary to modify
        *path: Sequence of keys to traverse, last key is where value is set
        value: Value to set at the path

    Example:
        d = {}
        dict_set(d, "a", "b", "c", value=1)
        # d is now {"a": {"b": {"c": 1}}}
    """
    if not path:
        return False

    current = data
    for key in path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    current[path[-1]] = value

    return True


def mapping_update(left: Mapping, right: Mapping | None) -> Mapping:
    """
    Deep update `left` with values from `right`, mutating `left` in place.

    Rules:
    - If right is None, return left unchanged.
    - Nested mappings are merged recursively.
    - Non-mapping values from right overwrite left.

    Args:
        left: Mapping to update in place
        right: Mapping whose values take precedence, or None

    Returns:
        The updated mapping (same object as left, unless left was None)
    """
    if right is None:
        return left

    for key, value in right.items():
        if (
            key in left
            and isinstance(left[key], Mapping)
            and isinstance(value, Mapping)
        ):
            mapping_update(left[key], value)
        else:
            left[key] = value

    return left


def mapping_prune(data: Mapping | None) -> bool:
    """
    Recursively remove empty collections from a nested mapping.

    Removes dictionaries, lists, sets, and tuples that are empty after pruning.
    Preserves non-collection types and collections with content.

    Args:
        data: Mapping to prune in place

    Returns:
        True if any modifications were made, False otherwise

    Example:
        d = {"a": {}, "b": {"c": 1}, "d": []}
        mapping_prune(d)  # returns True, d is now {"b": {"c": 1}}
    """

    def _is_empty(value: Any) -> bool:
        """Check if a value is an empty collection."""
        return isinstance(value, (list, set, tuple, Mapping)) and len(value) == 0

    if _is_empty(data):
        return False

    def _prune(value):
        """Recursively prune a value and return (pruned_value, was_modified)."""
        if isinstance(value, Mapping):
            modified = False
            pruned = {}
            for k, v in value.items():
                pruned_v, v_modified = _prune(v)
                if v_modified:
                    modified = True
                # Only include if not an empty collection
                if not _is_empty(pruned_v):
                    pruned[k] = pruned_v
                else:
                    modified = True
            return pruned, modified or len(pruned) != len(value)
        elif isinstance(value, list):
            modified = False
            pruned = []
            for item in value:
                pruned_item, item_modified = _prune(item)
                if item_modified:
                    modified = True
                # Only include if not an empty collection
                if not _is_empty(pruned_item):
                    pruned.append(pruned_item)
                else:
                    modified = True
            return pruned, modified or len(pruned) != len(value)
        else:
            return value, False

    modified = False
    keys_to_remove = []

    for key, value in list(data.items()):
        pruned_value, value_modified = _prune(value)
        if value_modified:
            modified = True
        # Remove if empty collection
        if _is_empty(pruned_value):
            keys_to_remove.append(key)
            modified = True
        elif value_modified or pruned_value != value:
            data[key] = pruned_value
            modified = True

    for key in keys_to_remove:
        del data[key]

    return modified


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
    root_dir = projects.root().file.parent
    return root_dir / "dev-local"


def is_help(ctx: typer.Context) -> bool:
    help_option_names = ctx.help_option_names
    return help_option_names and any(arg in help_option_names for arg in sys.argv)


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
        modified = False
        try:
            status = subprocess.check_output(
                [str(git_exec), "status", "--porcelain"],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                text=True,
            )
            if status.strip():
                modified = True
        except Exception:
            pass
        try:
            head_arg = "HEAD" if modified else "HEAD~1"
            rev = subprocess.check_output(
                [str(git_exec), "rev-parse", "--short", head_arg],
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
