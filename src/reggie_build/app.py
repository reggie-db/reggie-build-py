"""
Main entry point for the reggie-build CLI.

This module aggregates all subcommands from other modules and provides
a unified interface for workspace management. The CLI provides commands for:
- Cleaning build artifacts
- Creating new projects
- Synchronizing project configurations
- Generating FastAPI code from OpenAPI specifications
"""

import typer

from reggie_build import clean, create, openapi, sync, readme

app = typer.Typer()
app.add_typer(clean.app, name="clean")
app.add_typer(create.app, name="create")
app.add_typer(readme.app, name="readme")
app.add_typer(sync.app, name="sync")
app.add_typer(openapi.app, name="openapi")


def main():
    """
    Execute the Typer application.
    """
    app()


if __name__ == "__main__":
    main()
