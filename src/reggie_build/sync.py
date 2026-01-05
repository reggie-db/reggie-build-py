"""
Project synchronization and formatting utilities.

This module provides commands to synchronize configuration files (like pyproject.toml)
across multiple projects in a workspace. Features include:
- Syncing build-system configuration from root to member projects
- Converting member project dependencies to workspace references
- Synchronizing tool configurations
- Running ruff formatter on Python files
- Managing version strings across projects

Commands can be run individually or all at once via the main sync callback.
"""

import inspect
import re
import subprocess
from copy import deepcopy
from typing import Annotated, Callable, Iterable, Mapping

import typer

from reggie_build import projects, utils
from reggie_build.projects import Project
from reggie_build.utils import logger

LOG = logger(__file__)

app = typer.Typer()


_PROJECTS_OPTION = Annotated[list[str], projects.option()]


@app.callback(invoke_without_command=True)
def sync(
    ctx: typer.Context,
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Synchronize all configuration across member projects.

    When run without a subcommand, executes all registered sync commands against
    the selected projects. This includes build-system config, dependencies,
    tool settings, formatting, and versioning.

    Use --project to limit which projects are affected, or omit to sync all
    workspace members.
    """
    if ctx.invoked_subcommand is not None:
        return
    _sync(sync_projects)


def _sync(sync_projects: _PROJECTS_OPTION = None):
    """
    Execute all registered sync commands for the specified projects.

    Iterates through all commands registered with the app and invokes them,
    passing the project list if the command accepts parameters.

    Args:
        sync_projects: Optional list of project identifiers to sync
    """
    projs = list(_projects(sync_projects))
    for cmd in app.registered_commands:
        callback = cmd.callback
        callback_name = getattr(callback, "__name__", None)
        LOG.info(f"Syncing {callback_name}")
        sig = inspect.signature(callback)
        callback(projs) if len(sig.parameters) >= 1 else callback()


@app.command()
def build_system(
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Synchronize build-system configuration from the root project to member projects.

    Copies the [build-system] section from the root pyproject.toml to all selected
    projects, ensuring consistent build tooling across the workspace.
    """
    key = "build-system"
    data = projects.root().pyproject.get(key, None)
    if not data:
        LOG.warning("No build-system section found")
        return

    def _set(p: Project):
        """Update the build-system section for a project."""
        p.pyproject.merge({key: deepcopy(data)}, overwrite=True)

    _update_projects(_set, sync_projects, include_scripts=True)


@app.command()
def member_project_dependencies(
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Synchronize member project dependencies to use workspace file references.

    Converts member project dependencies to file:// references using
    ${PROJECT_ROOT} placeholders and updates tool.uv.sources accordingly.
    """
    member_project_names = [p.name for p in projects.root().members()]

    def parse_dep_name(dep: str) -> str | None:
        """
        Parse a dependency string to extract the project name.

        Handles both simple dependency names and file:// references.

        Args:
            dep: Dependency string from pyproject.toml

        Returns:
            Extracted project name or the original string if not a file reference
        """
        m = re.match(r"^\s*([\w\-\.\[\]]+)\s*@\s*file://", dep)
        return m.group(1) if m else dep

    def _set(p: Project):
        """Update member project dependencies for a project."""
        doc = p.pyproject
        deps = doc.get("project.dependencies", [])
        member_deps: list[str] = []

        for i in range(len(deps)):
            dep = parse_dep_name(deps[i])
            if dep not in member_project_names:
                continue
            # Use a relative file reference with a placeholder for the workspace root
            deps[i] = f"{dep} @ file://${{PROJECT_ROOT}}/../{dep}"
            member_deps.append(dep)

        sources = doc.get("tool.uv.sources", None)
        if isinstance(sources, Mapping):
            # Clean up obsolete workspace sources
            for k in list(sources.keys()):
                if k not in member_deps and sources[k].get("workspace") is True:
                    del sources[k]

        if member_deps:
            # Add or update tool.uv.sources for workspace members
            data = {}
            for dep in member_deps:
                (
                    data.setdefault("tool", {})
                    .setdefault("uv", {})
                    .setdefault("sources", {})
                    .setdefault(dep, {})
                )["workspace"] = True
            p.pyproject.merge(data)

    _update_projects(_set, sync_projects)


@app.command()
def member_project_tool(
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Synchronize tool.member-project configuration from the root project to member projects.

    Copies the [tool.member-project] section from the root pyproject.toml to all
    selected projects.
    """

    def _set(p: Project):
        """Update the tool.member-project section for a project."""
        data = projects.root().pyproject.get("tool.member-project", None)
        if data:
            p.pyproject.merge(deepcopy(data), overwrite=True)

    _update_projects(_set, sync_projects)


@app.command()
def ruff(
    require: Annotated[
        bool,
        typer.Option(
            hidden=True,
            help="Fail if ruff is not installed.",
        ),
    ] = True,
):
    """
    Run ruff formatter on git-tracked Python files.

    Formats all Python files tracked by git using the ruff formatter.
    If ruff is not installed, either warns or fails depending on the
    require parameter.
    """
    if not utils.which("ruff"):
        message = "ruff not installed"
        if require:
            raise ValueError(message)
        LOG.warning(message)
        return

    git_files = utils.git_files()
    if not git_files:
        return

    py_files = [str(f) for f in git_files if f.name.endswith(".py")]
    proc = subprocess.run(
        ["ruff", "format", *py_files],
        check=True,
        stdout=subprocess.PIPE,
    )
    stdout = proc.stdout.decode("utf-8").strip()
    if stdout:
        LOG.info(f"ruff: {stdout}")


@app.command()
def version(
    sync_projects: _PROJECTS_OPTION = None,
    version: Annotated[
        str,
        typer.Argument(
            help="Version string to apply (e.g. 1.2.3 or 0.0.1+gabc123). "
            f"If omitted, derived from git or defaults to {utils.DEFAULT_VERSION}.",
        ),
    ] = None,
):
    """
    Synchronize project versions across selected projects.

    Updates the version field in pyproject.toml for all selected projects.
    If no version is specified, attempts to derive one from git commit hash
    or uses the default version.
    """
    if not version:
        version = utils.git_version() or utils.DEFAULT_VERSION

    def _set(p: Project):
        """Update the project version."""
        p.pyproject.merge({"project": {"version": version}}, overwrite=True)

    _update_projects(_set, sync_projects)


def _update_projects(
    pyproject_fn: Callable[[Project], None],
    projs: Iterable[Project | str] | None,
    include_scripts: bool = False,
):
    """
    Apply a pyproject update function to multiple projects.

    Helper function that iterates through projects and applies a given
    modification function to each one, optionally excluding the scripts project.

    Args:
        pyproject_fn: Function that takes a Project and modifies its pyproject
        projs: Project identifiers to update
        include_scripts: Whether to include the scripts project in updates
    """
    for proj in _projects(projs):
        if not include_scripts and proj.is_scripts:
            continue
        pyproject_fn(proj)


def _projects(
    projs: Iterable[Project | str] | None = None,
) -> Iterable[Project]:
    """
    Resolve project identifiers into Project objects.

    Converts a mix of Project instances and string identifiers into
    a consistent stream of Project objects.

    Args:
        projs: Optional list of projects or project identifiers. If None,
               defaults to all workspace members.

    Yields:
        Project instances for each resolved project
    """
    if not projs:
        projs = projects.root().members()

    for proj in projs:
        if isinstance(proj, Project):
            yield proj
            continue

        LOG.debug(f"Resolving project identifier: {proj}")
        project_dir = projects.dir(proj)
        if not project_dir:
            raise ValueError(f"Project {proj} not found")
        yield Project(project_dir)
