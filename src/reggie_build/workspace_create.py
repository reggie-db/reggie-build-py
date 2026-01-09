import logging
import os
import pathlib
from typing import Annotated

import tomlkit
import typer

from reggie_build import pyproject, workspace, workspace_sync

"""
Utilities for creating workspace member projects.

Provides a command to bootstrap new member projects within a uv workspace,
setting up the directory structure, package layout, and dependencies.
"""

LOG = logging.getLogger(__name__)
_PATH = pathlib.Path("packages")


app = typer.Typer()


@app.callback(invoke_without_command=True)
def create(
    name: Annotated[
        str,
        typer.Argument(
            help="The name of the new project (used for directory and package name)."
        ),
    ],
    path: Annotated[
        pathlib.Path | None,
        typer.Option(
            "--path",
            "-p",
            help="Optional parent directory within the workspace root. Defaults to root.",
        ),
    ] = _PATH,
    project_dependencies: Annotated[
        list[str] | None,
        typer.Option(
            "--project-dependency",
            "-pd",
            help="List of existing workspace projects to depend on.",
        ),
    ] = None,
) -> None:
    """
    Create a new member project in the workspace.

    Sets up a pyproject.toml and a standard src/<package>/__init__.py layout.
    Internal workspace dependencies are automatically synchronized after creation.
    """

    metadata = workspace.metadata()
    root_dir = metadata.workspace_root
    path = root_dir / path
    # Ensure the specified path is within the workspace root
    if not path.is_relative_to(root_dir):
        raise ValueError(f"Path must be relative to root - root:{root_dir} path:{path}")

    project_dir = path / name
    pyproject_path = project_dir / pyproject.FILE_NAME

    # Don't overwrite existing projects
    if pyproject_path.exists():
        raise ValueError(f"Project already exists: {pyproject_path}")

    project_dir.mkdir(parents=True, exist_ok=True)
    LOG.info("Creating member project: %s", project_dir)

    # Initialize pyproject.toml
    pyproject_data = {
        "project": {
            "name": name,
            "version": "0",
            "requires-python": ">=3.6",
        },
    }
    pyproject_tree = pyproject.tree(metadata=metadata)
    if project_dependencies:
        # Add project dependencies as a multiline TOML array

        deps = tomlkit.array()
        deps.multiline(True)
        project_tree_names = [
            pyproject_tree.name,
            *pyproject_tree.members.keys(),
        ]
        for dep in project_dependencies:
            if dep not in project_tree_names:
                raise ValueError(f"Invalid project dependency: {dep}")
            deps.append(dep)
        pyproject_data["project"]["dependencies"] = deps

    pyproject_path.write_text(tomlkit.dumps(pyproject_data))

    # Create the standard Python src layout and an __init__.py file
    package_dir = project_dir / "src" / name.replace("-", "_")
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").touch()
    workspace_sync.sync(new_pyprojects={name: pyproject.PyProject(pyproject_path)})
    LOG.info("Member project created: %s", name)


if "__main__" == __name__:
    os.chdir("/Users/reggie.pierce/Projects/reggie-bricks-py")
    if True:
        create(
            "cool-dude",
            path=workspace.root_dir() / "packages/cool",
            project_dependencies=["reggie-cv"],
        )
    else:
        from typer.testing import CliRunner

        from reggie_build import cli

        runner = CliRunner()
        runner.invoke(
            cli.app,
            [
                "create",
                "cool-dude",
                "-pd",
                "reggie-build",
                # "-r",
                # "/Users/reggie.pierce/Projects/reggie-bricks-py",
            ],
            catch_exceptions=False,
        )
    LOG.info("Complete")
