"""
Utilities for cleaning workspace resources.

This module provides commands to remove build artifacts, temporary files,
and other generated resources from the workspace. It safely removes:
- Virtual environments (.venv directories)
- Python bytecode caches (__pycache__ directories)
- Egg info directories
"""

import os
import pathlib
import shutil

import typer

from reggie_build import projects
from reggie_build.utils import logger

LOG = logger(__file__)

app = typer.Typer(help="Clean workspace resources.")


@app.command()
def build_artifacts():
    """
    Remove Python build artifacts from the workspace.

    This command recursively walks the workspace directory tree and removes:
    - Virtual environment directories (.venv)
    - Python bytecode cache directories (__pycache__)
    - Python egg-info directories

    It protects the root .venv and scripts directory from deletion.
    """
    root = projects.root_dir()
    root_venv = root / ".venv"

    excludes = [
        # Exclude the root virtual environment to avoid accidental deletion
        lambda p: p.name == ".venv" and p.parent == root,
        # Exclude the scripts directory to avoid deleting the source code of this tool
        lambda p: projects.scripts_dir() in p.parents,
    ]

    matchers = [
        # Match any directory named .venv (except the excluded root one)
        lambda p: p.name == ".venv",
        # Match __pycache__ directories, but ignore those inside the root virtual environment
        lambda p: p.name == "__pycache__" and p.parent != root_venv,
        # Match Python egg-info directories
        lambda p: p.name.endswith(".egg-info"),
    ]

    for root_path, dir_names, _ in os.walk(root):
        path = pathlib.Path(root_path)

        # Skip excluded directories
        if any(f(path) for f in excludes):
            dir_names[:] = []
            continue

        # Delete matched artifact directories
        if any(f(path) for f in matchers):
            dir_names[:] = []
            LOG.info(f"Deleting directory: {path}")
            shutil.rmtree(path)
