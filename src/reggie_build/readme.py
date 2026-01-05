#!/usr/bin/env python3
"""
Update README sentinel blocks with live `--help` output.
"""

from __future__ import annotations

import re
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

import typer

from reggie_build import projects
from reggie_build.utils import logger

LOG = logger(__file__)

app = typer.Typer(help="Update README --help sentinel blocks.")

# Regexes (private, help-sentinel specific)
_HELP_BLOCK_RE = re.compile(
    r"""
    \s*<!--\s*BEGIN:help\s+(?P<cmd>[^>]+?)\s*-->\s*
    (?P<body>.*?)
    \s*<!--\s*END:help\s+(?P=cmd)\s*-->\s*
    """,
    re.DOTALL | re.VERBOSE,
)

_HELP_OPTIONS_HEADER_RE = re.compile(r"\bOptions\b.*[-─]")
_HELP_OPTIONS_FOOTER_RE = re.compile(r"^\s*[-─╰╯]+")
_HELP_OPTIONS_HELP_ROW_RE = re.compile(r"^\s*[│|]?\s*--help\b")


def _run_help(cmd: str) -> tuple[str, str]:
    """
    Execute `<cmd> --help`, remove the `--help` option and drop empty Options
    sections, and return (cmd, formatted_help).
    """
    proc = subprocess.run(
        f"{cmd} --help",
        shell=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

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
                    not _HELP_OPTIONS_HELP_ROW_RE.search(l)
                    and not _HELP_OPTIONS_HEADER_RE.search(l)
                    and not _HELP_OPTIONS_FOOTER_RE.match(l)
                    and l.strip()
                    for l in options_block
                )

                if has_real_options:
                    for l in options_block:
                        if not _HELP_OPTIONS_HELP_ROW_RE.search(l):
                            out.append(l)

                options_block = []
                in_options = False

            continue

        out.append(line)

    output = "\n".join(out).strip()
    return cmd, f"```bash\n{output}\n```"


@app.command()
def update_help(
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
        help="Maximum number of parallel help commands.",
    ),
):
    """
    Update README help sentinel blocks.

    Help commands are executed in parallel, limited by --jobs.
    """
    if not readme.exists():
        readme = projects.root_dir() / readme
        if not readme.exists():
            raise ValueError(f"README file not found at {readme}")

    content = readme.read_text()

    commands: list[str] = [
        match.group("cmd") for match in _HELP_BLOCK_RE.finditer(content)
    ]

    if not commands:
        LOG.info("No help blocks found.")
        return

    LOG.info(f"Running {len(commands)} help commands with {jobs} workers.")

    help_map: dict[str, str] = {}

    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(_run_help, cmd): cmd for cmd in commands}

        for future in as_completed(futures):
            cmd, help_text = future.result()
            help_map[cmd] = help_text

    def _replace(match: re.Match) -> str:
        cmd = match.group("cmd")
        return (
            f"\n\n<!-- BEGIN:help {cmd} -->\n"
            f"{help_map[cmd]}\n"
            f"<!-- END:help {cmd} -->\n\n"
        )

    updated = _HELP_BLOCK_RE.sub(_replace, content)

    if updated == content:
        LOG.info("No changes detected. README is already up to date.")
        return

    LOG.info("README help blocks updated.")

    if write:
        readme.write_text(updated)
    else:
        LOG.info(updated)


def main():
    app()


if __name__ == "__main__":
    main()
