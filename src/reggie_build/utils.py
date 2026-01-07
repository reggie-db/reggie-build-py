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
from os import PathLike
from typing import Any, Callable, Mapping, MutableMapping, TextIO, TypeVar
from urllib.parse import urlparse

import typer

T = TypeVar("T")
# Default version string used when git version cannot be determined
DEFAULT_VERSION = "0.0.1"


def logger(name: str | None = None, validate_name: bool = True) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Name of the logger. If omitted, defaults to the root project name.
              If "__main__", uses the current file name.
        validate_name: whether to validate the logger name

    Returns:
        A logging.Logger instance
    """
    _configure_root_logger()
    if not name:
        name = pathlib.Path.cwd().name
    elif validate_name:
        if name == "__main__":
            name = __file__
        name_file = run_catching(pathlib.Path, name)
        if name_file and name_file.is_file():
            name = name_file.stem
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

    def _create_handler(
        stream: TextIO,
        level: int,
        filter_fn: Callable[[logging.LogRecord], bool] | None = None,
    ) -> logging.Handler:
        """Create a stream handler with optional filter."""
        handler = logging.StreamHandler(stream)  # type: ignore[arg-type]
        handler.setLevel(level)
        if filter_fn is not None:
            handler.addFilter(filter_fn)
        return handler

    handlers = [
        _create_handler(
            sys.stdout, logging.DEBUG, lambda record: record.levelno <= logging.INFO
        ),
        _create_handler(
            sys.stderr, logging.WARNING, lambda record: record.levelno > logging.INFO
        ),
    ]

    log_level_env = os.getenv("LOG_LEVEL", "").upper()
    log_level = logging.getLevelNamesMapping().get(log_level_env, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _log():
    """Get the internal utils logger for debug output."""
    return logger("utils", validate_name=False)


def _run_catching_handler(e: Exception, message: str = None) -> T:
    _log().debug(message or "Exception suppressed", e)
    return None


def run_catching(
    fn: Callable[..., T],
    *args: Any,
    exception_handler: Callable[[Exception], T] | None = _run_catching_handler,
    **kwargs: Any,
) -> T:
    """
    Catch an exception and return a default value.

    Args:
        fn: Function to call
        *args: Arguments to pass to the function
        exception_handler: Handler to call if exception is raised, defaults debug logging and returning None to None
        **kwargs: Keyword arguments to pass to the function
    Returns:
        The result of the function call, or None if an exception was caught
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if exception_handler is not None:
            return exception_handler(e)


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
    if data:
        path_len = len(path)
        current_data: Mapping = data
        for path_idx in range(path_len):
            key = path[path_idx]
            next_value = current_data.get(key, None)
            if path_idx == path_len - 1:
                return next_value if next_value is not None else default
            elif isinstance(next_value, Mapping):
                current_data = next_value
            else:
                break
    return default


def mapping_set(data: MutableMapping, *path: str, value: Any) -> bool:
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
    if path:
        path_len = len(path)
        current_data: MutableMapping = data
        for path_idx in range(path_len):
            key = path[path_idx]
            next_value = current_data.get(key, None)
            if path_idx == path_len - 1:
                if next_value is value:
                    return False
                else:
                    current_data[key] = value
                    return True
            else:
                if not isinstance(next_value, MutableMapping):
                    next_value = {}
                    current_data[key] = next_value
                current_data = next_value
    return False


def mapping_merge(left: MutableMapping, right: Mapping | None) -> bool:
    """
    Deep merge right mapping into left, mutating left in place.

    Recursively merges nested mappings. Non-mapping values from right
    overwrite values in left.

    Args:
        left: Mapping to update in place
        right: Mapping whose values take precedence, or None

    Returns:
        True if any modifications were made, False otherwise

    Example:
        left = {"a": {"b": 1}, "c": 2}
        right = {"a": {"d": 3}, "c": 4}
        mapping_merge(left, right)
        # left is now {"a": {"b": 1, "d": 3}, "c": 4}
    """
    mod = False
    if right:
        for key, value in right.items():
            if key in left and isinstance(value, Mapping):
                left_value = left[key]
                if isinstance(left_value, Mapping):
                    if not isinstance(left_value, MutableMapping):
                        left_value = {**left_value}
                        left[key] = left_value
                    mapping_merge(left_value, value)
                    continue
            left[key] = value
    return mod


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

    def _is_collection(value: Any, mutable: bool = False) -> bool:
        """Check if a value is a collection."""
        return isinstance(
            value, (list, set, tuple, MutableMapping if mutable else Mapping)
        )

    def _is_empty(value: Any) -> bool:
        """Check if a value is an empty collection."""
        return value is None or (_is_collection(value) and len(value) == 0)

    def _prune(value: Any) -> bool:
        """Recursively prune a value and return (pruned_value, was_modified)."""
        if not _is_collection(value, True):
            return False
        mod = False
        if isinstance(value, MutableMapping):
            for k in list(value.keys()):
                v = value[k]
                if _is_empty(v):
                    del value[k]
                    mod = True
                elif _prune(v):
                    mod = True
        else:
            for i in reversed(range(len(value))):
                v = value[i]
                if _is_empty(v):
                    del value[i]
                    mod = True
                elif _prune(v):
                    mod = True
        return mod

    return _prune(data)


def command_is_help(ctx: typer.Context) -> bool:
    """Check if the command was invoked with --help flag."""
    help_option_names = ctx.help_option_names or ["--help"]
    if help_option_names and any(arg in help_option_names for arg in sys.argv):
        return True
    return False


def command_meta_cache(
    ctx: typer.Context,
    key: str,
    value_factory: Callable[[], T],
    on_close: Callable[[T], None] = None,
) -> T:
    """
    Cache a value in the context metadata with optional cleanup on close.

    Useful for expensive operations that should only run once per command
    invocation, with automatic cleanup when the command completes.

    Args:
        ctx: Typer context
        key: Cache key for storing the value
        value_factory: Function to create the value if not cached
        on_close: Optional callback to run when context closes

    Returns:
        Cached or newly created value
    """
    if key not in ctx.meta:
        value = value_factory()
        _log().debug("Meta cache update: key:%s value:%s", key, value)
        ctx.meta[key] = value
        if on_close is not None:
            ctx.call_on_close(lambda: on_close(value))
        return value
    else:
        return ctx.meta[key]


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
                _log().debug("File updated: %s", src)
                yield current
            time.sleep(interval)
        except FileNotFoundError:
            time.sleep(interval)
        except KeyboardInterrupt:
            return


def git_repo_name(cwd: pathlib.Path | str | None = None) -> str | None:
    """
    Extract repository name from git remote origin URL.

    Supports:
    - git@github.com:owner/repo.git
    - https://github.com/owner/repo.git

    Returns repo name without `.git`, or None.
    """
    git_exec = which("git")
    if not git_exec:
        return None
    origin_url = run_catching(exec, [git_exec, "remote", "get-url", "origin"], cwd=cwd)
    if not origin_url:
        return None

    # Normalize SSH form to URL so urlparse can handle it
    if origin_url.startswith("git@"):
        # git@github.com:owner/repo.git -> ssh://git@github.com/owner/repo.git
        origin_url = "ssh://" + origin_url.replace(":", "/", 1)

    parsed = run_catching(urlparse, origin_url)
    if not parsed or not parsed.path:
        return None

    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return name.removesuffix(".git") or None


def git_files(cwd: pathlib.Path | str | None = None) -> list[pathlib.Path] | None:
    """
    Build a workspace version string from git commit hash.

    Constructs a version string in the format <default_version>+g<short_rev> using
    the current git commit hash. Returns None if git is unavailable or the command
    fails.

    Returns:
        Version string like "0.0.1+g767bd46" or None if git is unavailable
    """
    git_exec = which("git")
    if not git_exec:
        return None
    out = run_catching(exec, [git_exec, "ls-files"], cwd=cwd)
    lines = (line.strip() for line in out.splitlines())
    return [pathlib.Path(line) for line in lines if line]


def git_version(cwd: pathlib.Path | str | None = None) -> str | None:
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
        status = run_catching(exec, [git_exec, "status", "--porcelain"], cwd=cwd)
        if status:
            modified = True
        head_arg = "HEAD" if modified else "HEAD~1"
        rev = run_catching(exec, [git_exec, "rev-parse", "--short", head_arg], cwd=cwd)
        if rev:
            return f"{DEFAULT_VERSION}+g{rev}"
    return None


def exec(
    args: list[Any] | str,
    cwd: os.PathLike | str | None = None,
    stderr_log_level: int | None = logging.DEBUG,
    strip: bool = True,
) -> str:
    """
    Execute a command and return stdout, logging stderr.

    Args:
        args: Command and arguments as list or single string
        cwd: Working directory to run command in
        stderr_log_level: Log level for stderr output, or None to suppress
        strip: strip output, defaults to True

    Returns:
        Command stdout as a string (trailing whitespace stripped)

    Raises:
        CalledProcessError: If command exits with non-zero status
    """
    if isinstance(args, str):
        process_args = [args]
    else:
        process_args = [
            os.fspath(arg) if isinstance(arg, PathLike) else str(arg) for arg in args
        ]
    _log().debug("Executing command: %s", process_args)
    proc = subprocess.Popen(
        process_args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if stderr_log_level is not None else None,
        text=True,
    )

    if stderr_log_level is not None:
        for line in proc.stderr:
            _log().log(stderr_log_level, line.rstrip())
    stdout = proc.stdout.read()
    if strip:
        stdout = stdout.strip()
    ret = proc.wait()
    if ret != 0:
        raise subprocess.CalledProcessError(ret, args)
    return stdout.rstrip()


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
    _log().warning(f"Executable not found: {name}")
    return None
