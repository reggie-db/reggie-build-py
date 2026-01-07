"""
OpenAPI code generation utilities.

Generates FastAPI code from OpenAPI specifications and syncs generated files
with change detection. This module provides:
- Code generation from OpenAPI specs (local files or URLs)
- File synchronization with hash-based change detection
- Watch mode for continuous regeneration
- Custom Jinja2 templates for FastAPI code generation

Generated code includes:
- FastAPI router with type-safe endpoints
- Pydantic models from schemas
- Abstract API contract classes for implementation
"""

import hashlib
import json
import re
import shutil
import subprocess
import warnings
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Annotated
from urllib.parse import urlparse

import requests
import typer

from reggie_build import utils, workspaces

warnings.filterwarnings(
    "ignore",
    message="Valid config keys have changed in V2",
    category=UserWarning,
    module="pydantic",
)


LOG = utils.logger(__file__)

app = typer.Typer(help="OpenAPI code generation utilities.")

_TIMESTAMP_RE = re.compile(rb"^\s*#\s*timestamp:.*$")


@app.command()
def generate(
    ctx: typer.Context,
    input_spec: Annotated[
        str,
        typer.Argument(
            help=(
                "Path or URL to the OpenAPI specification (YAML or JSON). "
                "May be a local file path or an HTTP(S) URL."
            ),
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Argument(
            help="Destination directory for generated code.",
        ),
    ] = None,
    template_dir: Annotated[
        Path,
        typer.Option(
            "--template-dir",
            help="Optional template directory for fastapi-code-generator.",
        ),
    ] = None,
    watch: Annotated[
        bool,
        typer.Option(
            "--watch",
            help="Watch a local spec file for changes and regenerate on updates.",
        ),
    ] = False,
):
    """
    Generate FastAPI code from an OpenAPI specification and sync changes.

    This command generates Python code from an OpenAPI spec, creating FastAPI
    routes and Pydantic models. It uses hash-based change detection to only
    update the output directory when files actually change.

    In watch mode, the command monitors the spec file and regenerates code
    whenever changes are detected.
    """
    tmpl = template_dir or (Path(__file__).parent / "openapi_template")

    resolved_input, temporary_hash = _resolve_input_spec(input_spec)
    try:
        if watch and temporary_hash:
            raise ValueError("--watch is only supported for local file paths")

        if not output_dir:
            # Generate a unique directory name if none is provided
            dir_name = f"openapi_{temporary_hash}"
            root_node = workspaces.root_node()
            output_dir = root_node.path / ".dev-local" / dir_name

        def _generate():
            """
            Inner function to handle the code generation and synchronization.
            """
            with TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp)
                LOG.info(f"Generating code: {resolved_input} → {output_dir}")
                args = [
                    "uv",
                    "tool",
                    "run",
                    "--from",
                    "fastapi-code-generator",
                    "--with",
                    "click<8.2.0",
                    "--",
                    "fastapi-codegen",
                    "--template-dir",
                    tmpl,
                    "--input",
                    resolved_input,
                    "--output",
                    tmp_dir,
                ]
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                assert proc.stdout is not None

                for line in proc.stdout:
                    LOG.info(line.rstrip())

                rc = proc.wait()
                if rc != 0:
                    raise subprocess.CalledProcessError(rc, args)
                (tmp_dir / "__init__.py").touch()
                sync_generated_code(tmp_dir, output_dir)

        if watch:
            for _ in utils.watch_file(resolved_input):
                _generate()
        else:
            _generate()
    finally:
        if temporary_hash:
            utils.run_catching(resolved_input.unlink)


def _resolve_input_spec(value: str) -> tuple[Path, str | None]:
    """
    Resolve an OpenAPI spec input as either a local path or a URL.

    Returns:
        (path, content_hash)
        content_hash is an md5 hex digest if the spec was downloaded, otherwise None
    """
    p = Path(value)
    if p.exists():
        return p.resolve(), None

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        LOG.info(f"Downloading OpenAPI spec from {value}")

        resp = requests.get(value, timeout=30)
        resp.raise_for_status()

        content = resp.content
        content_hash = hashlib.md5(content).hexdigest()

        try:
            json.loads(content)
            suffix = ".json"
        except json.decoder.JSONDecodeError:
            suffix = ".yaml"

        tmp = NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(content)
        tmp.flush()
        tmp.close()

        return Path(tmp.name), content_hash

    raise ValueError(f"Invalid OpenAPI spec path or URL: {value}")


def sync_generated_code(input_dir: Path, output_dir: Path) -> None:
    """
    Sync generated code from input_dir to output_dir if any relative file differs.

    Compares files using hash-based change detection and only performs a full
    copy if changes are detected. Logs all changed files for visibility.

    Args:
        input_dir: Source directory containing newly generated code
        output_dir: Destination directory to sync to
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"Missing input directory: {input_dir}")

    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()

    input_files = _list_files(input_dir)
    output_files = _list_files(output_dir)

    changed: list[str] = []
    for file in set(input_files + output_files):
        if _hash_file(input_dir, file) != _hash_file(output_dir, file):
            changed.append(file)

    if not changed:
        LOG.info("No changes detected")
        return

    LOG.info("Changed files:\n" + "\n".join(f"  {f}" for f in changed))

    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(input_dir, output_dir)
    LOG.info(f"Synchronized {output_dir}")


def _list_files(directory: Path) -> list[str]:
    """
    Return relative file paths from directory, skipping caches and compiled files.
    """
    if not directory.is_dir():
        return []

    rel_files = {
        str(p.relative_to(directory))
        for p in directory.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    return sorted(rel_files)


def _hash_file(dir: Path, rel_file: str) -> str:
    """
    Return SHA-256 hash for a relative file path, ignoring timestamp comments.
    """
    h = hashlib.sha256()
    file_path = dir / rel_file

    if file_path.is_file():
        with open(file_path, "rb") as f:
            for line in f:
                if not _TIMESTAMP_RE.match(line):
                    decoded = line.decode("utf-8", errors="ignore")
                    decoded = decoded.replace("\\'", '\\"').replace("'", '"')
                    h.update(decoded.encode())
    elif file_path.is_dir():
        h.update(b"|")

    return h.hexdigest()


if __name__ == "__main__":
    app()
