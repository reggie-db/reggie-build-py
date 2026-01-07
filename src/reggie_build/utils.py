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
import threading
import time
from collections import deque
from collections.abc import Iterator
from os import PathLike
from typing import Any, Callable, Mapping, MutableMapping, TextIO, TypeVar
from urllib.parse import urlparse

import typer

T = TypeVar("T")
# Default version string used when git version cannot be determined
DEFAULT_VERSION = "0.0.1"
_SENTINEL = object()


def logger(name: str | None = None, validate_name: bool = True) -> logging.Logger:
    """
    Get a configured logger instance.

    Configures a logger with stdout for INFO and stderr for WARNING and above.
    The log level can be controlled via the LOG_LEVEL environment variable.

    Args:
        name: Name of the logger. Defaults to the current directory name.
              If "__main__", uses the stem of the current file.
        validate_name: Whether to validate and potentially shorten the logger name.

    Returns:
        A configured logging.Logger instance.
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
    are directed to stderr.
    """

    def _create_handler(
        stream: TextIO,
        level: int,
        filter_fn: Callable[[logging.LogRecord], bool] | None = None,
    ) -> logging.Handler:
        """Create a stream handler with an optional filter."""
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


def _logger():
    """Get the internal utils logger for debug output."""
    return logger("utils", validate_name=False)


def _run_catching_handler(e: Exception, message: str = None) -> T:
    """Default handler for run_catching that logs errors at DEBUG level."""
    _logger().debug(message or "Exception suppressed", e)
    return None


def run_catching(
    fn: Callable[..., T],
    *args: Any,
    exception_handler: Callable[[Exception], T] | None = _run_catching_handler,
    **kwargs: Any,
) -> T:
    """
    Execute a function and catch exceptions with a handler.

    Simplifies error handling for operations where a failure should not stop
    execution, such as optional git integration or file cleanups.

    Args:
        fn: Function to call.
        *args: Positional arguments for the function.
        exception_handler: Callback to handle exceptions. Defaults to logging and returning None.
        **kwargs: Keyword arguments for the function.

    Returns:
        The function result, or the result of the exception handler on failure.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if exception_handler is not None:
            return exception_handler(e)


def clean_text(text: str) -> str:
    """
    Normalize text formatting for consistent output.

    Ensures that generated text, such as TOML files, has consistent
    indentation, trailing whitespace, and newlines.

    Args:
        text: Input text to clean.

    Returns:
        The normalized text with a single trailing newline.
    """
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
    Retrieve a value from a nested mapping using a path of keys.

    Safely traverses nested dictionary or TOML structures without raising
    KeyError. Returns the default value if any key in the path is missing.

    Args:
        data: Dictionary or TOML document to traverse, or None.
        *path: Sequence of keys to traverse.
        default: Value to return if path not found.

    Returns:
        Value at the path, or default if not found.

    Example:
        mapping_get({"a": {"b": 1}}, "a", "b") returns 1
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

    Creates intermediate dictionaries as needed. Useful for programmatically
    updating configuration files.

    Args:
        data: Dictionary or mutable mapping to modify.
        *path: Sequence of keys to traverse, where the last key is the target.
        value: Value to set at the path.

    Returns:
        True if the mapping was modified, False if the value was already the same.

    Example:
        d = {}
        mapping_set(d, "a", "b", value=1)
        # d is now {"a": {"b": 1}}
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
    Deep merge two mappings where values from the right take precedence.

    Combines multiple configuration sources into a single mapping while
    preserving the nested structure. Left is updated in place.

    Args:
        left: Mapping to update in place.
        right: Mapping whose values take precedence, or None.

    Returns:
        True if any modifications were made, False otherwise.

    Example:
        left = {"a": 1}
        right = {"b": 2}
        mapping_merge(left, right)
        # left is now {"a": 1, "b": 2}
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
                    if mapping_merge(left_value, value):
                        mod = True
                    continue
            if key not in left or left[key] != value:
                left[key] = value
                mod = True
    return mod


def mapping_prune(data: Mapping | None) -> bool:
    """
    Recursively remove empty collections from a nested mapping.

    Removes dictionaries, lists, sets, and tuples that are empty after pruning.
    Helps keep configuration files lean.

    Args:
        data: Mapping to prune in place.

    Returns:
        True if any modifications were made, False otherwise.

    Example:
        d = {"a": {}, "b": 1}
        mapping_prune(d)  # returns True, d is now {"b": 1}
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
        """Recursively prune a value and return True if modified."""
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
    """Check if the command was invoked with the --help flag."""
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
    Cache a value in the Typer context metadata with optional cleanup.

    Stores a value that should only be computed once per command invocation.
    Automatically handles cleanup when the command completes if `on_close` is provided.

    Args:
        ctx: Typer context.
        key: Cache key for storage.
        value_factory: Function to create the value if not already cached.
        on_close: Optional callback for cleanup when the context closes.

    Returns:
        The cached or newly created value.
    """
    if key not in ctx.meta:
        value = value_factory()
        _logger().debug("Meta cache update: key:%s value:%s", key, value)
        ctx.meta[key] = value
        if on_close is not None:
            ctx.call_on_close(lambda: on_close(value))
        return value
    else:
        return ctx.meta[key]


def watch_file(src: pathlib.Path, interval: float = 2.0) -> Iterator[str]:
    """
    Monitor a file and yield its hash whenever it changes.

    Continuously tracks a file's content and yields a SHA256 digest on modification.
    Useful for watch mode operations that trigger regeneration based on file changes.

    Args:
        src: Path to the file to watch.
        interval: Time in seconds between checks (default 2.0).

    Yields:
        SHA256 hex digest of the file content whenever it changes.

    Raises:
        KeyboardInterrupt: Stops iteration cleanly on interrupt.
    """

    def _hash(p: pathlib.Path) -> str:
        """Calculate the SHA256 hash of a file."""
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
                _logger().debug("File updated: %s", src)
                yield current
            time.sleep(interval)
        except FileNotFoundError:
            time.sleep(interval)
        except KeyboardInterrupt:
            return


def git_repo_name(cwd: pathlib.Path | str | None = None) -> str | None:
    """
    Extract the repository name from the git remote origin URL.

    Attempts to determine the repository name from common git remote formats
    (SSH or HTTPS). Returns the name without the `.git` suffix.

    Args:
        cwd: Directory to run git discovery in.

    Returns:
        The repository name, or None if git is unavailable or the name cannot be found.
    """
    git_exec = which("git")
    if not git_exec:
        return None
    origin_url = run_catching(
        process_run, [git_exec, "remote", "get-url", "origin"], cwd=cwd
    )
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
    Get a list of all files tracked by git in the repository.

    Provides a list of files that are currently part of the git repository,
    respecting `.gitignore` rules.

    Args:
        cwd: Directory for git discovery.

    Returns:
        List of paths to git tracked files, or None if git is unavailable.
    """
    git_exec = which("git")
    if not git_exec:
        return None
    out = run_catching(process_run, [git_exec, "ls-files"], cwd=cwd)
    if out is None:
        return None
    lines = (line.strip() for line in out.splitlines())
    return [pathlib.Path(line) for line in lines if line]


def git_version(cwd: pathlib.Path | str | None = None) -> str | None:
    """
    Generate a version string based on the current git commit.

    Constructs a development version string using the project's base version
    and the git short hash.

    Args:
        cwd: Directory for git discovery.

    Returns:
        Version string (e.g., "0.0.1+g767bd46") or None if git is unavailable.
    """
    git_exec = which("git")
    if git_exec:
        modified = False
        status = run_catching(process_run, [git_exec, "status", "--porcelain"], cwd=cwd)
        if status:
            modified = True
        head_arg = "HEAD" if modified else "HEAD~1"
        rev = run_catching(
            process_run, [git_exec, "rev-parse", "--short", head_arg], cwd=cwd
        )
        if rev:
            return f"{DEFAULT_VERSION}+g{rev}"
    return None


def process_run(
    args: list[Any] | str,
    cwd: os.PathLike | str | None = None,
    stderr_log_level: int | None = logging.DEBUG,
    check: bool = True,
    strip: bool = True,
) -> str:
    """
    Execute a command synchronously and return its stdout as a string.

    Captures the full output of a process for further use in the application.
    Ideal for commands where you need the complete result at once.

    Args:
        args: Command and arguments as a list or a single string.
        cwd: Directory to run the command in.
        stderr_log_level: Log level for stderr output (default DEBUG). Set to None to suppress.
        check: If True, raises subprocess.CalledProcessError on non-zero exit.
        strip: Whether to strip leading/trailing whitespace from the output.

    Returns:
        The command's stdout as a string.

    Raises:
        subprocess.CalledProcessError: If check is True and the command fails.
    """
    lines = list(
        process_start(args, cwd=cwd, stderr_log_level=stderr_log_level, check=check)
    )
    output = "\n".join(lines)
    if strip:
        output = output.strip()
    return output


def process_start(
    args: list[Any] | str,
    cwd: os.PathLike | str | None = None,
    stdout_log_level: int | None = None,
    stderr_log_level: int | None = logging.DEBUG,
    check: bool = True,
) -> Iterator[str]:
    """
    Execute a command and yield its stdout line by line.

    Runs a subprocess and provides its output incrementally through an iterator.
    Suitable for long-running commands or when real-time output processing
    or logging is required.

    Args:
        args: Command and arguments as a list or a single string.
        cwd: Directory to run the command in.
        stdout_log_level: Logging level for stdout. If set, each line is also logged.
        stderr_log_level: Log level for stderr output (default DEBUG). Set to None to suppress.
        check: If True, raises subprocess.CalledProcessError on non-zero exit.

    Yields:
        Each line of the command's stdout.

    Raises:
        subprocess.CalledProcessError: If check is True and the command fails.
    """
    if isinstance(args, str):
        process_args = [args]
    else:
        process_args = [
            os.fspath(arg) if isinstance(arg, PathLike) else str(arg) for arg in args
        ]
    _logger().debug("Executing command: %s", process_args)
    proc = subprocess.Popen(
        process_args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if stderr_log_level is not None else subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    thread: threading.Thread | None = None
    try:
        if stderr_log_level is not None:
            thread = threading.Thread(
                target=lambda s, lvl: deque(_process_read_stream(s, lvl), maxlen=0),
                args=(proc.stderr, stderr_log_level),
                daemon=True,
            )
            thread.start()
        # noinspection PyTypeChecker
        yield from _process_read_stream(proc.stdout, stdout_log_level)
    finally:
        for out_stream in [proc.stdout, proc.stderr]:
            if out_stream:
                run_catching(out_stream.close)
        if thread:
            thread.join()
        ret = proc.wait()

        if check and ret != 0:
            raise subprocess.CalledProcessError(
                ret,
                process_args,
            )


def _process_read_stream(out_stream: TextIO, log_level: int | None) -> Iterator[str]:
    """
    Internal helper to read lines from a stream and optionally log them.

    Args:
        out_stream: The stream to read from
        log_level: The log level to use for each line, or None to skip logging

    Yields:
        Each line read from the stream
    """
    log = _logger() if log_level is not None else None
    for out_line in iter(out_stream.readline, ""):
        out_line = out_line.rstrip()
        if log:
            log.log(log_level, out_line)
        yield out_line


@functools.lru_cache(maxsize=None)
def which(name: str) -> pathlib.Path | None:
    """
    Locate an executable in the system path.

    Finds the absolute path to a tool (like `git` or `ruff`) needed by the CLI.
    Caches results to avoid repeated filesystem lookups.

    Args:
        name: Name or path of the executable to find.

    Returns:
        Path to the executable if found, otherwise None.
    """
    path = run_catching(shutil.which, name)
    if path:
        return pathlib.Path(path)
    else:
        file = pathlib.Path(name)
        if file.is_file() and os.access(file, os.X_OK):
            return file
    _logger().warning(f"Executable not found: {name}")
    return None


if "__main__" == __name__:
    for line in process_start(
        [
            "bash",
            "-c",
            'ls -all / && i=1; while [ $i -le 10 ]; do if [ $((i % 2)) -eq 0 ]; then echo "hello world (stderr)" >&2; else echo "hello world (stdout)"; fi; i=$((i+1)); sleep 1; done',
        ],
        stdout_log_level=logging.INFO,
        stderr_log_level=logging.WARNING,
    ):
        print(line)
