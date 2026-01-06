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

import click
import typer
from typer.models import CommandInfo

from reggie_build import projects, utils, workspaces
from reggie_build.projects import PyProject
from reggie_build.utils import logger

LOG = logger(__file__)


class ProjectParamType(click.ParamType):
    name = "Project"

    def convert(self, value, param, ctx):
        workspace_metadata = workspaces.metadata()
        if value == workspace_metadata.root.name:
            return PyProject(source=workspace_metadata)
        for member in workspace_metadata.members:
            if member.name == value:
                return PyProject(source=member)
        return PyProject(source=workspaces.metadata(value))


def _projects_meta(ctx: typer.Context) -> list[PyProject]:
    return ctx.meta.setdefault("pyprojects", [])


def _projects_persist(pyprojects: Iterable[PyProject]):
    for pyproject in pyprojects:
        if pyproject.persist():
            LOG.info(f"Persisted {pyproject.file}")


def _projects_callback(ctx: typer.Context, pyprojects: list[PyProject]):
    if not pyprojects:
        pyprojects = list(projects.root().projects())
    if not pyprojects:
        raise typer.BadParameter("No projects found")
    _projects_meta(ctx).extend(pyprojects)
    return pyprojects


_PROJECTS_OPTION = Annotated[
    list[PyProject],
    typer.Option(
        "-p",
        "--project",
        click_type=ProjectParamType(),
        callback=_projects_callback,
        help="Optional list of project names or identifiers to sync",
    ),
]


@click.pass_context
def _result_callback(ctx: typer.Context, *_, **__):
    _projects_persist(_projects_meta(ctx))


app = typer.Typer(result_callback=_result_callback)


@app.callback(invoke_without_command=True)
def _callback(
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
        _log_command(invoked_subcommand)
        _projects_meta(ctx).clear()
    else:
        # persist handled by callbacks
        all(sync_projects, persist=False)


def all(projs: list[PyProject], persist: bool = True):
    """
    Execute all registered sync commands for the specified projects.

    Iterates through all commands registered with the app and invokes them,
    passing the project list if the command accepts parameters.

    Args:
        projs: List of project identifiers to sync
        persist: persist all projects
    """
    if not isinstance(projs, list):
        projs = list(projs)
    for cmd in app.registered_commands:
        _log_command(cmd)
        callback = cmd.callback
        sig = inspect.signature(callback)
        callback(projs) if len(sig.parameters) >= 1 else callback()
    if persist:
        _projects_persist(projs)


def _log_command(cmd: CommandInfo | str):
    if isinstance(cmd, CommandInfo):
        cmd_name = cmd.name
        if not cmd_name:
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
    data = projects.root().get(key, None)
    if not data:
        LOG.warning("No build-system section found")
        return

    def _set(p: PyProject):
        """Update the build-system section for a project."""
        p[key] = deepcopy(data)

    _update_projects(_set, sync_projects)


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

    def _set(pyproject: PyProject):
        """Update member project dependencies for a project."""

        deps = utils.mapping_get(pyproject, "project", "dependencies", default=[])
        member_deps: list[str] = []

        for i in range(len(deps)):
            dep = parse_dep_name(deps[i])
            if dep not in member_project_names:
                continue
            # Use a relative file reference with a placeholder for the workspace root
            deps[i] = f"{dep} @ file://${{PROJECT_ROOT}}/../{dep}"
            member_deps.append(dep)
        sources = utils.mapping_get(pyproject, "tool", "uv", "sources")
        if isinstance(sources, Mapping):
            # Clean up obsolete workspace sources
            for k in list(sources.keys()):
                if k not in member_deps and sources[k].get("workspace") is True:
                    del sources[k]

        if member_deps:
            # Add or update tool.uv.sources for workspace members
            for dep in member_deps:
                utils.mapping_set(
                    pyproject, "tool", "uv", "sources", dep, "workspace", value=True
                )

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
    data = utils.mapping_get(projects.root(), "tool", "member-project")

    def _set(p: PyProject):
        """Update the tool.member-project section for a project."""
        if not p.is_root and data:
            utils.mapping_update(p, data)

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
    ruff = utils.which("ruff")
    if not ruff:
        message = "ruff not installed"
        if require:
            raise ValueError(message)
        LOG.warning(message)
        return

    git_files = utils.git_files()
    if not git_files:
        return

    py_files = [str(f) for f in git_files if f.name.endswith(".py")]
    run_arg_options = {
        "check": [
            "--select",
            "UP007,UP006,F401,I",
            "--fix",
        ],
        "format": [],
    }
    for arg, options in run_arg_options.items():
        process_args = [str(ruff), arg, *py_files, *options]
        out = subprocess.check_output(
            process_args,
            text=True,
        ).strip()
        if out:
            LOG.info(f"ruff: {out}")


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

    def _set(pyproject: PyProject):
        """Update the project version."""
        pyproject_version = utils.mapping_get(pyproject, "project", "version")
        if version != pyproject_version:
            utils.mapping_set(pyproject, "project", "version", value=version)
            LOG.info(
                f"Updated {pyproject.name} version: {pyproject_version} -> {version}"
            )

    _update_projects(_set, sync_projects)


def _update_projects(
    pyproject_fn: Callable[[PyProject], None],
    projs: list[PyProject] | None,
):
    """
    Apply a pyproject update function to multiple projects.

    Helper function that iterates through projects and applies a given
    modification function to each one, optionally excluding the scripts project.

    Args:
        pyproject_fn: Function that takes a Project and modifies its pyproject
        projs: PyProject identifiers to update
    """
    for proj in projs:
        pyproject_fn(proj)


if __name__ == "__main__":
    from typer.testing import CliRunner

    runner = CliRunner()
    runner.invoke(app, ["-p", "reggie-build"], catch_exceptions=False)
