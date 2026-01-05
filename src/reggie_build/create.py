"""
Utilities for creating workspace resources.

This module provides commands to bootstrap new member projects with appropriate
directory structures and configuration files. It creates projects with:
- Standard Python src layout (src/<package_name>/)
- Configured pyproject.toml with dependencies
- Workspace integration for multi-project setups
"""

import pathlib
from typing import Annotated

import tomlkit
import typer
from benedict.dicts import benedict

from reggie_build import projects
from reggie_build.projects import Project
from reggie_build.utils import logger

LOG = logger(__file__)

app = typer.Typer(help="Create workspace resources.")


@app.command()
def member(
    name: Annotated[
        str,
        typer.Argument(
            help=(
                "Name of the project to create. Used as both the directory name "
                "and the project name."
            )
        ),
    ],
    path: Annotated[
        pathlib.Path,
        typer.Option(
            dir_okay=True,
            file_okay=False,
            help=(
                "Optional parent directory path within the workspace root. "
                "If omitted, the project is created in the workspace root."
            ),
        ),
    ] = None,
    project_dependencies: Annotated[
        list[str],
        typer.Option(
            "-pd",
            "--project-dependency",
            help=(
                "Optional list of existing workspace project names to include "
                "as dependencies in the new project's pyproject.toml."
            ),
        ),
    ] = None,
):
    """
    Create a new member project in the workspace.

    This command creates a new Python project with:
    - A pyproject.toml configuration file
    - Standard src layout (src/<package_name>/__init__.py)
    - Optional dependencies on other workspace projects

    The project name is used for both the directory and package name (with hyphens
    converted to underscores for the package).
    """
    if path:
        path = path.resolve()
        # Ensure the specified path is within the workspace root
        if not path.is_relative_to(projects.root_dir()):
            raise ValueError(f"Invalid path: {path}")
    else:
        path = projects.root_dir()

    project_dir = path / name
    pyproject_path = project_dir / projects.PYPROJECT_FILE_NAME

    # Don't overwrite existing projects
    if pyproject_path.exists():
        raise ValueError(f"Project already exists: {pyproject_path}")

    project_dir.mkdir(parents=True, exist_ok=True)
    LOG.info(f"Creating member project: {project_dir}")

    # Initialize pyproject.toml using tomlkit and benedict for easier manipulation
    pyproject = benedict(tomlkit.document(), keyattr_dynamic=True)
    pyproject["build-system"] = {}
    pyproject["project"] = {
        "name": name,
        "version": "0",
        "requires-python": ">=3.6",
    }

    if project_dependencies:
        # Add project dependencies as a multiline TOML array
        deps = tomlkit.array()
        deps.multiline(True)
        for dep in project_dependencies:
            dep_dir = projects.dir(dep)
            dep_project = Project(dep_dir)
            deps.append(dep_project.name)
        pyproject["project"]["dependencies"] = deps

    pyproject_path.write_text(tomlkit.dumps(pyproject))

    # Create the standard Python src layout and an __init__.py file
    package_dir = project_dir / "src" / name.replace("-", "_")
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").touch()

    LOG.info(f"Member project created: {name}")
