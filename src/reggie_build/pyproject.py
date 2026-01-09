import filecmp
import logging
import pathlib
import shutil
import subprocess
from dataclasses import dataclass, field
from tempfile import NamedTemporaryFile
from typing import Mapping
from urllib.parse import urlparse

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Table

from reggie_build import workspace

"""
Utility for managing and manipulating pyproject.toml files.

This module provides the PyProject class for high-level operations on
pyproject.toml files, including reading, updating, and persisting changes
while preserving formatting using tomlkit.
"""

LOG = logging.getLogger(__name__)
FILE_NAME = "pyproject.toml"
_MAX_BLANK_LINES = 1
_INDENT = " " * 4


@dataclass
class TableNode:
    """
    Represents a node in a TOML table hierarchy.

    Provides utilities for navigating and modifying nested TOML tables,
    specifically for removing and pruning empty tables.
    """

    table: Table
    _parent_entry: tuple["TableNode", str] | None = field(default=None)

    def remove(self) -> bool:
        """
        Remove the current table from its parent node.
        """
        if parent_entry := self._parent_entry:
            parent, key = parent_entry
            if key in parent.table:
                parent.table.pop(key)
                return True
        return False

    def prune(self) -> bool:
        """
        Recursively remove this table and its parents if they are empty.
        """
        mod = False
        if not self.table and self.remove():
            mod = True
        if parent_entry := self._parent_entry:
            if parent_entry[0].prune():
                mod = True
        return mod


class PyProject:
    """
    Interface for interacting with a pyproject.toml file.

    Handles lazy loading, modification, and persistence of project metadata
    using tomlkit for round-trip compatibility and taplo for formatting.
    """

    def __init__(self, path: pathlib.Path):
        """
        Initialize a PyProject instance.
        """
        self.path = _file_path(path)
        self._data: TOMLDocument | None = None

    @property
    def data(self) -> TOMLDocument:
        """
        Lazily load and return the TOML data from the pyproject.toml file.
        """
        if self._data is None:
            LOG.debug("Reading: %s", self.path)
            with self.path.open("rb") as f:
                self._data = tomlkit.load(f)
        return self._data

    def persist(
        self, destination_path: pathlib.Path = None, force_format: bool = False
    ) -> bool:
        """
        Save the current state of the project configuration to disk.

        If the content has changed, it writes to a temporary file, formats it
        using taplo, and then moves it to the destination.
        """
        if destination_path is None:
            destination_path = self.path
        else:
            destination_path = _file_path(destination_path)
        if data := self._data:
            LOG.debug("Persisting: %s", destination_path)
            temp_path = pathlib.Path(
                NamedTemporaryFile(delete=False, suffix=".toml").name
            )
            mod = False
            try:
                with temp_path.open("w") as f:
                    tomlkit.dump(data, f)
                _format(temp_path)
                diff = not filecmp.cmp(temp_path, destination_path, shallow=False)
                if diff:
                    shutil.move(temp_path, destination_path)
                    mod = True
            finally:
                if not mod:
                    temp_path.unlink()
            self._data = None
            return mod
        elif force_format:
            mtime = destination_path.stat().st_mtime
            _format(destination_path)
            return mtime != destination_path.stat().st_mtime
        else:
            return False

    def table(self, *keys: str, create: bool = False) -> TableNode | None:
        """
        Navigate to a specific table in the TOML hierarchy.

        Optionally creates the table path if it doesn't exist.
        """
        cur_node = TableNode(self.data)
        for key in keys:
            cur_table = cur_node.table
            value = cur_table.get(key, None)
            if not isinstance(value, Mapping):
                if create:
                    value = tomlkit.table(True)
                    if key in cur_table:
                        cur_table.remove(key)
                    else:
                        cur_table.add(key, value)
                else:
                    return None
            cur_node = TableNode(value, _parent_entry=(cur_node, key))
        return cur_node

    def __repr__(self):
        if data := self._data:
            name = data.get("project", {}).get("name", "[UNKNOWN]")
        else:
            name = "[UNLOADED]"
        return f"{self.__class__.__name__}(name={name} path={self.path})"


@dataclass
class PyProjectTree:
    """
    Represents the hierarchical structure of a uv workspace.

    Includes the root project and all discovered member projects.
    """

    name: str
    root: PyProject
    filtered: bool = field(default=False, init=False)
    members: dict[str, PyProject] = field(default_factory=dict)

    def projects(self) -> list[PyProject]:
        """
        Return a list of all projects in the tree, starting with the root.
        """
        return [self.root, *self.members.values()]

    def filter_members(
        self, names: list[str] | None, required: bool = False
    ) -> "PyProjectTree":
        """
        Filter the members dictionary to only include specified names.

        Args:
            names: List of member names to keep. If None, no filtering is performed.
            required: If True, raises ValueError if a specified name is not found.
        """
        if not names:
            return self
        members_copy: dict[str, PyProject] = {}
        for name in [names, *self.members.keys()]:
            if name in members_copy:
                continue
            member_proj = self.members.get(name, None)
            if member_proj is None:
                if required:
                    raise ValueError("Member %s not found" % name)
                continue
            members_copy[name] = member_proj
        pyproject_tree_copy = PyProjectTree(
            name=name, root=self.root, members=members_copy
        )
        pyproject_tree_copy.filtered = True
        return pyproject_tree_copy


def tree(metadata: workspace.Metadata | None = None) -> PyProjectTree:
    """
    Discover and load all projects within a uv workspace into a tree.

    Args:
        metadata: Optional workspace metadata. If omitted, it is retrieved automatically.
    """
    if metadata is None:
        metadata = workspace.metadata()
    root_proj_name: str | None = None
    member_projs: dict[str, PyProject] = {}
    for member in metadata.members:
        if metadata.workspace_root == member.path:
            root_proj_name = member.name
            continue
        member_projs[member.name] = PyProject(member.path)
    root_proj: PyProject = PyProject(metadata.workspace_root)
    return PyProjectTree(
        name=root_proj_name or _git_repo_name(root_proj.path) or root_proj.path.name,
        root=root_proj,
        members=member_projs,
    )


def _git_repo_name(path: pathlib.Path) -> str | None:
    """
    Attempt to determine the git repository name from the origin remote URL.
    """
    args = ["git", "remote", "get-url", "origin"]
    cwd = path.parent if path.is_file() else path
    try:
        proc = subprocess.run(
            args, cwd=cwd, check=False, text=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        LOG.debug("Git remote url lookup failed - args:%s", args, exc_info=True)
        return None
    if proc.returncode != 0:
        LOG.debug("Git remote url lookup failed - args:%s stderr:%s", args, proc.stderr)
        return None
    git_origin_url = proc.stdout.strip()
    if git_origin_url:
        # Normalize SSH form to URL so urlparse can handle it
        if git_origin_url.startswith("git@"):
            # git@github.com:owner/repo.git -> ssh://git@github.com/owner/repo.git
            git_origin_url = "ssh://" + git_origin_url.replace(":", "/", 1)
        git_origin_url_path = urlparse(git_origin_url).path
        if git_origin_url_path:
            repo_name = (
                git_origin_url_path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            )
            if repo_name:
                return repo_name
    LOG.debug(
        "Git remote url not found - git_origin_url:%s args:%s", git_origin_url, args
    )
    return None


def _format(path: pathlib.Path):
    """
    Apply taplo formatting to a TOML file with workspace-specific options.
    """
    fmt_stdout = subprocess.check_output(
        [
            "taplo",
            "fmt",
            "--option",
            f"allowed_blank_lines={_MAX_BLANK_LINES}",
            "--option",
            f"indent_string={_INDENT}",
            str(path.absolute()),
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    LOG.debug("Taplo format: %s", fmt_stdout.strip())


def _file_path(path: pathlib.Path) -> pathlib.Path:
    """
    Normalize a path to a pyproject.toml file, creating parent directories if needed.
    """
    if path.is_dir():
        return path / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


if __name__ == "__main__":
    print(_git_repo_name(pathlib.Path.cwd()))
