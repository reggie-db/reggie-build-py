#!/usr/bin/env python3
"""
README documentation automation utilities.

This module provides commands to automatically update README files by executing
commands embedded in sentinel blocks and replacing the content with command output.
Supports parallel execution, smart help filtering, and selective updates.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path
from typing import Pattern

import typer

from reggie_build import config, workspace

LOG = logging.getLogger(__name__)

app = typer.Typer(help="Update README command sentinel blocks.")

# Sentinel regex (generic)
_CMD_BLOCK_RE = re.compile(
    r"""
    \s*<!--\s*BEGIN:cmd\s+(?P<cmd>[^>]+?)\s*-->\s*
    (?P<body>.*?)
    \s*<!--\s*END:cmd\s*-->\s*
    """,
    re.DOTALL | re.VERBOSE,
)


_HELP_OPTIONS_HEADER_RE = re.compile(r"\bOptions\b.*[-─]")
_HELP_OPTIONS_FOOTER_RE = re.compile(r"^\s*[-─╰╯]+")
_HELP_OPTIONS_HELP_ROW_RE = re.compile(r"^\s*[│|]?\s*--help\b")
_CODE_BLOCK_RE = re.compile(r"^([`~]{3,}).*?^\1", re.MULTILINE | re.DOTALL)


@app.callback(invoke_without_command=True)
def update_cmd(
    ctx: typer.Context,
    readme: Path = typer.Option(
        Path("README.md"),
        "--readme",
        "-r",
        help="Path to README file to update.",
        file_okay=True,
        dir_okay=False,
    ),
    write: bool = typer.Option(
        True,
        help="Write changes back to the README file.",
    ),
    jobs: int = typer.Option(
        max(1, cpu_count() - 1),
        "--jobs",
        "-j",
        help="Maximum number of parallel commands.",
    ),
    filter: str = typer.Option(
        None,
        "--filter",
        help="Regex to select which BEGIN:cmd blocks to update.",
    ),
):
    """
    Update README command sentinel blocks.

    Only blocks whose command matches --filter are executed and updated.
    """
    if not readme.exists():
        readme = workspace.root_dir() / readme
        if not readme.exists():
            raise ValueError(f"README file not found at {readme}")

    content = readme.read_text()
    code_ranges = [m.span() for m in _CODE_BLOCK_RE.finditer(content)]

    def is_in_code_block(pos: int) -> bool:
        return any(start <= pos < end for start, end in code_ranges)

    block_matches = [
        m for m in _CMD_BLOCK_RE.finditer(content) if not is_in_code_block(m.start())
    ]
    if not block_matches:
        LOG.info("No cmd blocks found")
        return

    filter_re: Pattern[str] | None = re.compile(filter) if filter else None

    selected_cmds: list[str] = []
    for m in block_matches:
        cmd = m.group("cmd")
        if filter_re and not filter_re.search(cmd):
            continue
        selected_cmds.append(cmd)

    if not selected_cmds:
        LOG.info("No cmd blocks matched filter")
        return

    LOG.info(
        "Running cmd blocks - count:%s total:%s jobs:%s",
        len(selected_cmds),
        len(block_matches),
        jobs,
    )

    output_map: dict[str, str] = {}

    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(_run_cmd, cmd): cmd for cmd in selected_cmds}

        for future in as_completed(futures):
            cmd, output = future.result()
            output_map[cmd] = output

    def _replace(match: re.Match) -> str:
        """Replace sentinel block content with executed command output."""
        if is_in_code_block(match.start()):
            return match.group(0)

        cmd = match.group("cmd")
        if cmd not in output_map:
            return match.group(0)  # untouched
        return f"\n\n<!-- BEGIN:cmd {cmd} -->\n{output_map[cmd]}\n<!-- END:cmd -->\n\n"

    updated = _CMD_BLOCK_RE.sub(_replace, content)

    if updated == content:
        LOG.info("No changes detected")
        return

    LOG.info("README command blocks updated")

    if write:
        readme.write_text(updated)
    else:
        LOG.info("README update: %s", updated)


def _run_cmd(cmd: str) -> tuple[str, str]:
    """
    Execute command and capture output in markdown code block format.

    For commands with --help, filters out the --help option row from
    output and removes empty Options sections.

    Args:
        cmd: Shell command to execute

    Returns:
        Tuple of (command, formatted_output) where formatted_output
        is wrapped in markdown code block
    """
    args = shlex.split(cmd)
    has_help = "--help" in args
    LOG.debug("Running cmd block - args:%s has_help:%s", args, has_help)
    env = os.environ.copy().update(
        {config.LOG_LEVEL_ENV_NAME: logging.getLevelName(logging.ERROR)}
    )
    proc = subprocess.run(
        cmd,
        shell=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    if has_help:
        lines = proc.stdout.splitlines()

        out: list[str] = []
        options_block: list[str] = []
        in_options = False

        for line in lines:
            if _HELP_OPTIONS_HEADER_RE.search(line):
                in_options = True
                options_block = [line]
                continue

            if in_options:
                options_block.append(line)

                if _HELP_OPTIONS_FOOTER_RE.match(line):
                    has_real_options = any(
                        not _HELP_OPTIONS_HELP_ROW_RE.search(opt_line)
                        and not _HELP_OPTIONS_HEADER_RE.search(opt_line)
                        and not _HELP_OPTIONS_FOOTER_RE.match(opt_line)
                        and opt_line.strip()
                        for opt_line in options_block
                    )

                    if has_real_options:
                        for opt_line in options_block:
                            if not _HELP_OPTIONS_HELP_ROW_RE.search(opt_line):
                                out.append(opt_line)

                    options_block = []
                    in_options = False

                continue

            out.append(line)

        output = "\n".join(out)
    else:
        output = proc.stdout

    return cmd, f"```shell\n{output.strip()}\n```"


def main():
    app()


if __name__ == "__main__":
    main()
