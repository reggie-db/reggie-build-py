import logging
import os
import pathlib
import re
import subprocess
from collections import defaultdict
from copy import deepcopy
from typing import Annotated, Collection

import typer
from mergedeep import merge

from reggie_build import pyproject
from reggie_build.pyproject import PyProject, PyProjectTree

"""
Sync utility for managing multiple pyproject.toml files in a uv workspace.

This module provides tools to synchronize versions, build systems, tool settings,
and dependencies across the root project and its member projects.
"""

LOG = logging.getLogger(__name__)

app = typer.Typer()


@app.callback(invoke_without_command=True)
def sync(
    names: Annotated[
        list[str] | None,
        typer.Option("--name", "-n", help="Specific member project names to sync."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(help="Sync version from git history to all member projects."),
    ] = True,
    build_system: Annotated[
        bool,
        typer.Option(
            help="Sync [build-system] from root project to all member projects."
        ),
    ] = True,
    member_project_tool: Annotated[
        bool,
        typer.Option(
            help="Sync [tool.member-project] from root project to all member projects."
        ),
    ] = True,
    member_project_dependencies: Annotated[
        bool,
        typer.Option(
            help="Sync internal member dependencies to use file:// paths and uv workspace sources."
        ),
    ] = True,
    member_paths: Annotated[
        bool,
        typer.Option(help="Sync member path patterns"),
    ] = True,
    format_python: Annotated[
        bool,
        typer.Option(help="Run ruff format and check on all projects."),
    ] = True,
    format_pyproject: Annotated[
        bool,
        typer.Option(help="Format pyproject.toml files using taplo."),
    ] = True,
    root_dir: Annotated[
        pathlib.Path | None,
        typer.Option("--root-dir", "-r", hidden=True, help="Root directory."),
    ] = None,
    output_dir: Annotated[
        pathlib.Path | None,
        typer.Option("--output-dir", "-o", hidden=True, help="Output directory."),
    ] = None,
    new_pyprojects: Annotated[
        dict[str, PyProject] | None,
        typer.Option(hidden=True, parser=lambda _: None),
    ] = None,
):
    """
    Synchronize project configurations across the workspace.

    This command performs several synchronization tasks to keep member projects
    aligned with the root project settings and ensure consistent dependencies.
    """
    if root_dir:
        os.chdir(root_dir)
    if output_dir:
        output_dir = output_dir.absolute()
    unfiltered_pyproject_tree = pyproject.tree()
    if new_pyprojects:
        for name, proj in new_pyprojects.items():
            unfiltered_pyproject_tree.members[name] = proj
    pyproject_tree = unfiltered_pyproject_tree.filter_members(names)
    LOG.debug("Syncing projects: %s", pyproject_tree)
    if version:
        sync_version(pyproject_tree.projects())
    if build_system:
        sync_build_system(pyproject_tree)
    if member_project_tool:
        sync_member_project_tool(pyproject_tree)
    if member_project_dependencies:
        sync_member_project_dependencies(unfiltered_pyproject_tree, pyproject_tree)
    if member_paths:
        sync_member_paths(unfiltered_pyproject_tree)
    if format_python:
        ruff_format(pyproject_tree.projects())
    for proj_name, proj in {
        pyproject_tree.name: pyproject_tree.root,
        **pyproject_tree.members,
    }.items():
        destination_path = output_dir / proj.path if output_dir else None
        if proj.persist(
            destination_path=destination_path,
            force_format=format_pyproject,
        ):
            LOG.info(
                "Project updated - name:%s path:%s",
                proj_name,
                destination_path or proj.path,
            )


def sync_version(projs: Collection[PyProject], version: str | None = None):
    """
    Update the version field in the [project] table for a collection of projects.

    If no version is provided, it is generated automatically from the git history.
    """
    for proj in projs:
        project_data = proj.data.get("project", None)
        if project_data is not None:
            key = "version"

            if version is None:
                version = _version()
            current_version = project_data.get(key, None)
            if current_version == version:
                continue
            project_data[key] = version
            LOG.debug(
                "Updated version - key:%s proj:%s version:%s previous_version:%s",
                key,
                proj,
                version,
                current_version,
            )


def _version():
    """
    Generate a version string based on git HEAD and working directory state.

    Uses '0.0.1+g{rev}' format where {rev} is the short hash of HEAD
    (or HEAD~1 if the working directory is modified).
    """
    git_status_args = ["git", "status", "--porcelain"]
    proc = subprocess.Popen(
        git_status_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1,
        text=True,
    )
    modified = False
    for line in proc.stdout:
        line = line.strip()
        if line:
            LOG.debug("Git status - args:%s line:%s", git_status_args, line)
            modified = True
            break
    proc.terminate()
    proc.wait()
    head_arg = "HEAD" if modified else "HEAD~1"
    rev_parse_args = ["git", "rev-parse", "--short", head_arg]
    rev = subprocess.check_output(rev_parse_args, text=True).strip()
    LOG.debug("Rev parse - args:%s rev:%s", rev_parse_args, rev)
    return f"0.0.1+g{rev}"


def sync_build_system(pyproject_tree: PyProjectTree):
    """
    Synchronize the [build-system] table from the root project to all member projects.
    """
    key = "build-system"
    data = pyproject_tree.root.data.get(key, {})
    LOG.debug("Build system - key:%s data:%s", key, data)
    if data:
        for member in pyproject_tree.members.values():
            member.data[key] = deepcopy(data)


def sync_member_project_tool(pyproject_tree: PyProjectTree):
    """
    Merge the [tool.member-project] configuration from root to all member projects.
    """
    member_project_data = pyproject_tree.root.data.get("tool", {}).get(
        "member-project", {}
    )
    LOG.debug("Member project data: %s", member_project_data)
    if member_project_data:
        for member in pyproject_tree.members.values():
            merge(member.data, member_project_data)


def sync_member_project_dependencies(
    unfiltered_pyproject_tree: PyProjectTree, pyproject_tree: PyProjectTree
):
    """
    Update internal dependencies within the workspace to use relative file:// paths.

    This ensures that projects can correctly reference each other without
    relying on external registry versions.
    """
    if unfiltered_pyproject_tree.filtered:
        raise ValueError(
            "Unfiltered workspace tree required for member project dependencies sync"
        )
    for proj in pyproject_tree.projects():
        _sync_member_project_dependencies(unfiltered_pyproject_tree, proj)


def _sync_member_project_dependencies(pyproject_tree: PyProjectTree, proj: PyProject):
    """
    Internal helper to synchronize dependencies and uv sources for a specific project.
    """
    member_dependencies: list[str] = []
    dependencies = proj.data.get("project", {}).get("dependencies", [])
    if dependencies:
        for idx, dependency in enumerate(dependencies):
            dep = _parse_dependency_name(dependencies[idx])
            dep_proj = (
                pyproject_tree.root
                if dep == pyproject_tree.name
                else pyproject_tree.members.get(dep, None)
            )
            if dep_proj:
                dependencies[idx] = _member_dependency(proj, dep, dep_proj)
                member_dependencies.append(dep)

    sources_node = proj.table("tool", "uv", "sources", create=bool(member_dependencies))
    if sources_node:
        workspace_key = "workspace"
        source_table = sources_node.table
        for dep in list(source_table.keys()):
            workspace_value = source_table.get(dep, {}).get(workspace_key, None)
            if workspace_value is True and dep not in member_dependencies:
                source_table.remove(dep)
                LOG.debug(
                    "Removed source - key:%s proj:%s dependency:%s",
                    workspace_key,
                    proj,
                    dep,
                )
        for member_dependency in member_dependencies:
            source = {member_dependency: {workspace_key: True}}
            source_table.update(source)
        if sources_node.prune():
            LOG.debug(
                "Pruned source - key:%s proj:%s",
                workspace_key,
                proj,
            )


def sync_member_paths(
    unfiltered_pyproject_tree: PyProjectTree,
):
    if unfiltered_pyproject_tree.filtered:
        raise ValueError("Unfiltered workspace tree required for member path sync")
    root_proj = unfiltered_pyproject_tree.root
    root_dir = root_proj.path.parent
    unfiltered_members = unfiltered_pyproject_tree.members
    members: list[str] = []
    for dir in _sync_member_paths(
        root_dir, [p.path.parent for p in unfiltered_members.values()]
    ):
        member = str(os.path.relpath(dir, root_dir))
        exact = (dir / pyproject.FILE_NAME).exists()
        if not exact:
            member += "/*"
        members.append(member)
    members.sort(key=lambda s: (not s.endswith("*"), s))
    members_key = "members"
    workspace_table = root_proj.table("tool", "uv", "workspace", create=True).table
    if members_key in workspace_table:
        if members:
            member_table = workspace_table[members_key]
            member_table.clear()
            member_table.extend(members)
        else:
            workspace_table.remove(members_key)
    else:
        workspace_table.update({members_key: members})


def _sync_member_paths(
    root: pathlib.Path, paths: list[pathlib.Path]
) -> set[pathlib.Path]:
    root = root.resolve()
    paths = {p.resolve() for p in paths if p != root}

    # Ensure all paths are under root
    if not all(p.is_relative_to(root) for p in paths):
        raise ValueError("All paths must be under root")

    # Work with paths relative to root
    rels = {p.relative_to(root) for p in paths}

    changed = True
    while changed:
        changed = False
        by_parent: dict[pathlib.Path, set[pathlib.Path]] = defaultdict(set)

        for p in rels:
            by_parent[p.parent].add(p)

        for parent, children in by_parent.items():
            # Never collapse to root
            if parent == pathlib.Path("."):
                continue

            # All siblings under parent are present
            names = {c.name for c in children}
            expected = {parent / name for name in names}

            if children == expected and len(children) > 1:
                rels -= children
                rels.add(parent)
                changed = True
                break

    return rels


def _parse_dependency_name(dep: str) -> str | None:
    """
    Extract the project name from a dependency string, handling file:// formats.
    """
    m = re.match(r"^\s*([\w\-\.\[\]]+)\s*@\s*file://", dep)
    return m.group(1) if m else dep


def _member_dependency(member_proj: PyProject, dep: str, dep_proj: PyProject):
    """
    Format an internal workspace dependency as a file:// URI with PROJECT_ROOT variable.
    """
    member_proj_dir = member_proj.path.parent.resolve(strict=False)
    dep_proj_dir = dep_proj.path.parent.resolve(strict=False)
    relative_path = os.path.relpath(dep_proj_dir, member_proj_dir)
    member_dependency = f"{dep} @ file://$" + "{PROJECT_ROOT}/" + str(relative_path)
    return member_dependency


def ruff_format(projs: list[PyProject]):
    """
    Execute ruff formatting and linting fixes on a collection of projects.
    """
    for proj in projs:
        _ruff_format(proj.path.parent)


def _ruff_format(path: pathlib.Path):
    """
    Internal helper to run ruff check and ruff format on a specific directory.
    """
    check_select = ["UP007", "UP006", "F401", "I"]
    run_arg_options = {
        "check": [
            "--select",
            ",".join(check_select),
            "--fix",
        ],
        "format": [],
    }
    for arg, options in run_arg_options.items():
        stdout = subprocess.check_output(["ruff", arg, *options], text=True).strip()
        LOG.debug("Ruff format - arg:%s path:%s output:%s", arg, path, stdout)


if "__main__" == __name__:
    from typer.testing import CliRunner

    from reggie_build import cli

    runner = CliRunner()
    runner.invoke(
        cli.app,
        [
            "sync",
            "-o",
            "./.dev-local",
            "-r",
            "/Users/reggie.pierce/Projects/reggie-bricks-py",
        ],
        catch_exceptions=False,
    )
    LOG.info("Complete")
