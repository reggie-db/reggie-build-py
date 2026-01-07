"""
Project synchronization and formatting utilities.

This module provides commands to synchronize configuration files (like pyproject.toml)
across multiple projects in a workspace. Features include:
- Syncing build-system configuration from root to member projects
- Converting member project dependencies to workspace references
- Synchronizing tool configurations
- Running ruff formatter on Python files
- Managing version strings across projects

Commands use the projects.project() and workspaces.node() functions for
streamlined access with context caching. All sync operations automatically
persist changes via context callbacks.
"""

import inspect
import logging
import pathlib
import re
from copy import deepcopy
from typing import Annotated, Any, Callable, Mapping

import typer
from typer.models import CommandInfo

from reggie_build import projects, utils, workspaces
from reggie_build.projects import PyProject

LOG = utils.logger(__file__)


def _projects_meta(ctx: typer.Context) -> list[PyProject]:
    """Get the list of projects from context metadata."""
    return ctx.meta.setdefault("pyprojects", [])


def _projects_option_callback(ctx: typer.Context, node_names: list[str]) -> list[str]:
    """
    Validate and expand project names option.

    Validates that all specified node names exist, and expands empty
    list to all workspace nodes.

    Args:
        ctx: Typer context
        node_names: List of node names from --project option

    Returns:
        List of validated node names (expanded if empty)
    """
    if node_names:
        for node_name in node_names:
            if not workspaces.node(node_name, ctx=ctx):
                raise typer.BadParameter(f"Workspace node not found: {node_name}")
    else:
        root_node = workspaces.root_node(ctx=ctx)
        node_names = [node.name for node in root_node.nodes()]
    return node_names


_PROJECTS_OPTION = Annotated[
    list[str],
    typer.Option(
        "-p",
        "--project",
        callback=_projects_option_callback,
        help="Optional list of workspace node/project names to sync",
    ),
]


app = typer.Typer()


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
        if not utils.command_is_help(ctx):
            _log_command(invoked_subcommand)
            _projects_meta(ctx).clear()
    else:
        # persist handled by callbacks
        all(ctx, sync_projects)


def all(ctx: typer.Context, projs: list[str]):
    """
    Execute all registered sync commands for the specified projects.

    Iterates through all commands registered with the app and invokes them.
    Commands must accept ctx and projs parameters.

    Args:
        ctx: Typer context for caching and coordination
        projs: List of project/node names to sync
    """
    for cmd in app.registered_commands:
        _log_command(cmd)
        callback = cmd.callback
        sig = inspect.signature(callback)
        callback(ctx, projs) if len(sig.parameters) >= 2 else callback(ctx)


def _log_command(cmd: CommandInfo | str):
    """Log which sync command is being executed."""
    if isinstance(cmd, CommandInfo):
        cmd_name = cmd.name
        if not cmd_name:
            cmd_name = getattr(cmd.callback, "__name__", None)
            if cmd_name:
                cmd_name = cmd_name.replace("_", "-")
    else:
        cmd_name = cmd
    LOG.info(f"Syncing {cmd_name}")


@app.command()
def build_system(
    ctx: typer.Context,
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Sync build-system config from root to member projects.

    Copies the [build-system] section from the root pyproject.toml to all selected
    projects, ensuring consistent build tooling across the workspace.
    """
    key = "build-system"
    root_pyproject = projects.project(ctx=ctx)
    root_data = root_pyproject.get(key, None)
    if not root_data:
        LOG.warning("No build-system section found")
        return

    def _set(p: PyProject):
        """Update the build-system section for a project."""
        p[key] = deepcopy(root_data)

    _update_projects(ctx, sync_projects, _set, exclude_root=True)


@app.command()
def member_project_dependencies(
    ctx: typer.Context,
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Sync member project dependencies to workspace file references.

    Converts member project dependencies to file:// references using
    ${PROJECT_ROOT} placeholders and updates tool.uv.sources accordingly.
    """
    root_node = workspaces.root_node(ctx=ctx)
    member_project_names = [node.name for node in root_node.members]

    def parse_dep_name(dep: str) -> str | None:
        """Extract project name from dependency string (handles file:// format)."""
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

    _update_projects(ctx, sync_projects, _set, exclude_root=True)


@app.command()
def member_project_tool(
    ctx: typer.Context,
    sync_projects: _PROJECTS_OPTION = None,
):
    """
    Sync tool.member-project config from root to member projects.

    Copies the [tool.member-project] section from the root pyproject.toml to all
    selected member projects.
    """
    root_data = projects.project(ctx=ctx)
    data = utils.mapping_get(root_data, "tool", "member-project")

    def _set(p: PyProject):
        """Merge tool.member-project section into project."""
        utils.mapping_merge(p, data)

    _update_projects(ctx, sync_projects, _set, exclude_root=True)


@app.command()
def ruff(
    _: typer.Context,
    require: Annotated[
        bool,
        typer.Option(
            hidden=True,
            help="Fail if ruff not installed.",
        ),
    ] = True,
):
    """
    Run ruff formatter on git tracked Python files.

    Formats all Python files tracked by git using ruff.
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
        LOG.warning("git file lookup failed")
        return

    def _exec(arg: Any, options: list[Any], py_files: list[pathlib.Path]):
        out = utils.exec([ruff, arg, *options, *py_files])
        message = ("ruff: %s", out)

        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug(*message)
        elif any(
            re.search(p, out, re.IGNORECASE) for p in (r"\breformatted\b", r"\bfixed\b")
        ):
            LOG.info(*message)

    run_arg_options = {
        "check": [
            "--select",
            "UP007,UP006,F401,I",
            "--fix",
        ],
        "format": [],
    }
    py_files_buffer: list[pathlib.Path] = []
    total = len(git_files)
    for arg, options in run_arg_options.items():
        for idx, f in enumerate(git_files, 1):
            if f.name.endswith(".py"):
                py_files_buffer.append(f)
            if py_files_buffer and (idx % 100 == 0 or idx == total):
                _exec(arg, options, py_files_buffer)
                py_files_buffer.clear()


@app.command()
def version(
    ctx: typer.Context,
    sync_projects: _PROJECTS_OPTION = None,
    version: Annotated[
        str,
        typer.Argument(
            help=f"Version string (e.g. 1.2.3). Defaults to git or {utils.DEFAULT_VERSION}.",
        ),
    ] = None,
):
    """
    Sync project versions across selected projects.

    Updates the version field in pyproject.toml. If no version specified,
    derives from git commit hash or uses default.
    """
    if not version:
        version = utils.git_version() or utils.DEFAULT_VERSION

    def _set(pyproject: PyProject):
        """Update the project version."""
        project = pyproject.get("project", None)
        if not project:
            return
        pyproject_version = project.get("version", None)
        if version != pyproject_version:
            utils.mapping_set(pyproject, "project", "version", value=version)
            pyproject_name = pyproject.get("project", {}).get(
                "name", pyproject.path.parent.name
            )
            LOG.info(
                f"Updated {pyproject_name} version: {pyproject_version} -> {version}"
            )

    _update_projects(ctx, sync_projects, _set)


def _update_projects(
    ctx: typer.Context,
    node_names: list[str] | None,
    pyproject_fn: Callable[[PyProject], None],
    exclude_root: bool = False,
):
    """
    Apply a pyproject update function to multiple projects.

    Loads each project using projects.project() with context caching,
    then applies the modification function. Persistence happens
    automatically via context callbacks.

    Args:
        ctx: Typer context for caching
        node_names: List of node names to update
        pyproject_fn: Function that modifies a PyProject
        exclude_root: Whether to skip the root node
    """
    for node_name in node_names:
        if exclude_root:
            node = workspaces.node(node_name, ctx=ctx)
            if node and node.root:
                continue
        proj = projects.project(node_name, ctx=ctx)
        pyproject_fn(proj)


if __name__ == "__main__":
    from typer.testing import CliRunner

    runner = CliRunner()
    runner.invoke(app, [], catch_exceptions=False)
