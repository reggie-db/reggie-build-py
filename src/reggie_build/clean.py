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

from reggie_build import workspaces
from reggie_build.utils import logger

LOG = logger(__file__)

app = typer.Typer(help="Clean workspace resources.")


@app.command()
def build_artifacts(ctx: typer.Context):
    """
    Remove Python build artifacts from the workspace.

    This command recursively walks the workspace directory tree and removes:
    - Virtual environment directories (.venv)
    - Python bytecode cache directories (__pycache__)
    - Python egg-info directories

    It protects the root .venv directory from deletion.
    """
    root_node = workspaces.root_node(ctx=ctx)
    root_dir = root_node.path
    root_venv = root_dir / ".venv"

    excludes = [
        # Exclude the root virtual environment to avoid accidental deletion
        lambda p: p.name == ".venv" and p.parent == root_dir,
    ]

    matchers = [
        # Match any directory named .venv (except the excluded root one)
        lambda p: p.name == ".venv",
        # Match __pycache__ directories, but ignore those inside the root virtual environment
        lambda p: p.name == "__pycache__" and p.parent != root_venv,
        # Match Python egg-info directories
        lambda p: p.name.endswith(".egg-info"),
        # Match root dist folder
        lambda p: p.name == "dist" and p.is_dir() and p.parent == root_dir,
    ]

    for root_path, dir_names, _ in os.walk(root_dir):
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
