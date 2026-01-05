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
import sys
from copy import deepcopy
from itertools import chain
from typing import Annotated, Any, Callable, Iterable, Mapping

import click
import tomlkit
import typer
from benedict.dicts import benedict
from typer.models import CommandInfo

from reggie_build import projects, utils
from reggie_build.projects import Project
from reggie_build.utils import logger

LOG = logger(__file__)


def _sync_projects_option_callback(ctx: typer.Context, sync_projects: Iterable[Any]):
    """
    Callback for processing sync project options from CLI.

    Converts project identifiers to Project objects and stores them in context metadata
    for later use by the sync result callback.

    Args:
        ctx: Typer context object containing command metadata
        sync_projects: Iterable of project identifiers (names or Project objects)

    Returns:
        List of Project objects
    """
    sync_projects_empty = not sync_projects
    sync_projects = list(_projects(sync_projects))
    ctx.meta["sync_projects"] = sync_projects
    sync_project_names = [] if sync_projects_empty else [p.name for p in sync_projects]
    sync_projects_log_key = "sync_projects_log"
    if sync_project_names and not ctx.meta.get(sync_projects_log_key, None):
        ctx.meta[sync_projects_log_key] = True
        LOG.info(f"Syncing projects: {', '.join(sync_project_names)}")

    return sync_projects


@click.pass_context
def _sync_result_callback(ctx: typer.Context, *_, **__):
    """
    Result callback for sync commands that persists project changes.

    This callback is invoked after sync commands complete to save any modifications
    made to project pyproject.toml files.

    Args:
        ctx: Typer context object containing command metadata
        _: Unused parameter (required by Typer callback signature)
    """
    if sync_projects := ctx.meta.get("sync_projects", None):
        _persist_projects(sync_projects)


def _persist_projects(projs: Iterable[Any] = None, prune: bool = True):
    """
    Save pyproject.toml changes to disk for specified projects.

    Writes the pyproject configuration back to the pyproject.toml file for each
    project, but only if the content has changed. Optionally prunes empty values
    from the configuration before saving.

    Args:
        projs: Optional iterable of project identifiers to persist.
               If None, persists all workspace member projects.
        prune: If True, removes empty values from configuration before saving
    """
    projects_updated = False
    for proj in _projects(projs):
        file = proj.pyproject_file
        doc = proj.pyproject
        # Remove empty values to keep configuration clean
        if prune and not proj.is_root and isinstance(doc, benedict):
            doc.clean(strings=False)
        text = tomlkit.dumps(doc)

        current_text = file.read_text() if file.exists() else None
        # Only write if content has changed
        if text != current_text:
            file.write_text(text)
            projects_updated = True
            LOG.info(f"Project updated:{file}")
    if not projects_updated:
        LOG.info("No changes made to projects")


app = typer.Typer(result_callback=_sync_result_callback)
_PROJECTS_OPTION = Annotated[
    list[str], projects.option(callback=_sync_projects_option_callback)
]


@app.callback(invoke_without_command=True)
def _sync_callback(
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
    if invoked_subcommand := ctx.invoked_subcommand:
        _sync_log(invoked_subcommand)
    else:
        sync(sync_projects)


def sync(sync_projects: _PROJECTS_OPTION = None):
    """
    Execute all registered sync commands for the specified projects.

    Iterates through all commands registered with the app and invokes them,
    passing the project list if the command accepts parameters.

    Args:
        sync_projects: Optional list of project identifiers to sync
    """
    projs = list(_projects(sync_projects))
    for cmd in app.registered_commands:
        _sync_log(cmd)
        callback = cmd.callback
        sig = inspect.signature(callback)
        callback(projs) if len(sig.parameters) >= 1 else callback()


def _sync_log(cmd: CommandInfo | str):
    if isinstance(cmd, CommandInfo):
        cmd_name = getattr(cmd.callback, "__name__", None)
    else:
        cmd_name = cmd
    LOG.info(f"Syncing {cmd_name}")


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
        LOG.info(
            f"Syncing member project dependencies - project:{p} root_project:{projects.root()} member_project_names: {member_project_names} deps:{deps}"
        )

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
    if stdout and "reformatted" in stdout:
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
        pyproject = p.pyproject
        pyproject_version = pyproject.get("project.version", None)
        if version != pyproject_version:
            p.pyproject.merge({"project": {"version": version}}, overwrite=True)
            LOG.info(f"Updated {p.name} version: {pyproject_version} -> {version}")

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


def _projects(projs: Iterable[Any] | None = None) -> Iterable[Project]:
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
        root_proj = projects.root()
        if root_proj.pyproject.get("project", None):
            projs = set(projs)
            projs.add(root_proj)

    for proj in projs:
        if isinstance(proj, Project):
            yield proj
            continue

        LOG.debug(f"Resolving project identifier: {proj}")
        project_dir = projects.dir(proj)
        if not project_dir:
            raise ValueError(f"Project {proj} not found")
        yield Project(project_dir)
