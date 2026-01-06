"""
Workspace discovery and metadata utilities.

This module provides classes and functions for discovering Python workspaces
using `uv workspace metadata` command. Features include:
- Workspace metadata discovery from uv
- Workspace project information (name, path, project flag)
- Git repository name detection as fallback
- Automatic root project detection

The WorkspaceMetadata and WorkspaceProject classes provide structured access to
workspace information without directly parsing pyproject.toml files.
"""

import functools
import json
import pathlib
import subprocess
from dataclasses import dataclass
from os import PathLike
from urllib.parse import urlparse

from reggie_build import utils

LOG = utils.logger(__file__)


@dataclass
class WorkspaceProject:
    """
    Represents a single project within a workspace.

    Attributes:
        name: Project name
        path: Absolute path to the project directory
        project: Whether this is a Python project (has pyproject.toml with [project])
    """

    name: str
    path: pathlib.Path
    project: bool = True

    def __post_init__(self):
        assert self.name
        assert self.path.is_dir()

    @classmethod
    def from_dict(cls, member_data: dict) -> "WorkspaceProject":
        """Create a WorkspaceProject from uv workspace metadata dict."""
        return cls(name=member_data["name"], path=pathlib.Path(member_data["path"]))


@dataclass
class WorkspaceMetadata:
    """
    Represents workspace metadata from uv including root and member projects.

    Attributes:
        workspace_root: Absolute path to the workspace root directory
        members: List of all workspace projects, including the root
    """

    workspace_root: pathlib.Path
    members: list[WorkspaceProject]

    def __post_init__(self):
        """
        Validate workspace root and ensure a root project exists.

        If no root project is found, creates one using git repo name or directory name.
        """
        assert self.workspace_root.is_dir()
        if self._root(validate=True) is None:
            name = _git_repo_name()
            if not name:
                name = self.workspace_root.name
            self.members.append(
                WorkspaceProject(name=name, path=self.workspace_root, project=False)
            )

    @property
    def root(self):
        """Get the root workspace project."""
        return self._root(validate=False)

    def _root(self, validate: bool = False) -> WorkspaceProject | None:
        """
        Find the root project matching the workspace_root path.

        Args:
            validate: If True, raises ValueError if multiple roots found

        Returns:
            The root WorkspaceProject or None if not found
        """
        root: WorkspaceProject | None = None
        for member in self.members:
            if self.workspace_root == member.path:
                if root is None:
                    root = member
                    if not validate:
                        break
                else:
                    raise ValueError(f"Multiple workspace roots found: {self}")
        return root

    @classmethod
    def from_dict(cls, metadata_data: dict) -> "WorkspaceMetadata":
        """Create WorkspaceMetadata from uv workspace metadata dict."""
        workspace_root = pathlib.Path(metadata_data["workspace_root"])
        members = []
        members_data = metadata_data.get("members", [])
        for member_data in members_data:
            members.append(WorkspaceProject.from_dict(member_data))
        return cls(workspace_root=workspace_root, members=members)


def metadata(cwd: PathLike | str | None = None):
    """
    Get workspace metadata for the current or specified directory.

    Args:
        cwd: Working directory to discover workspace from, or None for current directory

    Returns:
        WorkspaceMetadata with root and member project information
    """
    return _metadata(cwd=cwd) if cwd else _metadata_default()


@functools.cache
def _metadata_default():
    """Cached version of _metadata() for the current directory."""
    metadata = _metadata()
    LOG.info(f"Workspace metadata loaded: {metadata.workspace_root}")
    return metadata


def _metadata(cwd: PathLike | str | None = None) -> WorkspaceMetadata:
    """
    Execute uv workspace metadata command and parse the result.

    Args:
        cwd: Working directory to run command in

    Returns:
        WorkspaceMetadata parsed from uv output
    """
    args = ["uv", "workspace", "metadata"]
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert proc.stdout is not None
    assert proc.stderr is not None

    # Read stderr asynchronously-like (interleaved is fine here)
    for line in proc.stderr:
        LOG.debug(line.rstrip())

    # Now read stdout fully
    stdout = proc.stdout.read()

    ret = proc.wait()
    if ret != 0:
        raise subprocess.CalledProcessError(ret, args)

    metadata_data = json.loads(stdout)
    return WorkspaceMetadata.from_dict(metadata_data)


@functools.cache
def _git_repo_name() -> str | None:
    """
    Extract repository name from git remote origin URL.

    Supports:
    - git@github.com:owner/repo.git
    - https://github.com/owner/repo.git

    Returns repo name without `.git`, or None.
    """
    try:
        origin_url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            text=True,
        ).strip()
    except Exception:
        return None

    if not origin_url:
        return None

    # Normalize SSH form to URL so urlparse can handle it
    if origin_url.startswith("git@"):
        # git@github.com:owner/repo.git -> ssh://git@github.com/owner/repo.git
        origin_url = "ssh://" + origin_url.replace(":", "/", 1)

    try:
        parsed = urlparse(origin_url)
    except Exception:
        return None
    if not parsed.path:
        return None

    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return name.removesuffix(".git")


if "__main__" == __name__:
    metadata = metadata("/Users/reggie.pierce/Projects/reggie-bricks-py")
    print(metadata)
    print(metadata.root)
