"""
Main entry point for the reggie-build CLI.

This module aggregates all subcommands from other modules and provides
a unified interface for workspace management. The CLI provides commands for:
- Cleaning build artifacts
- Creating new projects
- Synchronizing project configurations
- Generating FastAPI code from OpenAPI specifications
- Updating README documentation with command help output
"""

import logging
from typing import Annotated

import typer

from reggie_build import readme, workspace_create, workspace_sync

app = typer.Typer()
app.add_typer(workspace_create.app, name="create")
app.add_typer(workspace_sync.app, name="sync")
app.add_typer(readme.app, name="readme")


@app.callback()
def _callback(
    log_level: Annotated[
        str | None,
        typer.Option(
            help="Set the log level explicitly (e.g. DEBUG, INFO, WARNING, ERROR)."
        ),
    ] = None,
):
    log_level_no = (
        logging.getLevelNamesMapping().get(log_level.upper(), None)
        if log_level
        else None
    )
    if log_level_no is not None:
        logging.root.setLevel(log_level_no)


def main():
    app()


if __name__ == "__main__":
    main()
