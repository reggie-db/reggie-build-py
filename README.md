# reggie-build

A comprehensive workspace management tool designed to handle complicated and common code generation tasks across
multi-project Python environments. Built to be adopted by any project requiring automated code generation, workspace
synchronization, and build orchestration.

## Why Use reggie-build?

Managing multi-project Python workspaces becomes increasingly complex as projects grow. Common challenges include:

- **Configuration Drift**: Build configs, dependencies, and tool settings diverge across related projects
- **Workspace Coordination**: Multiple projects with interdependencies require careful version and dependency management
- **Build Artifact Management**: Generated files, caches, and artifacts accumulate without systematic cleanup

`reggie-build` solves these problems by providing a battle-tested CLI that orchestrates:

- **Smart Synchronization**: Keep build configs, dependencies, and tool settings consistent across all workspace
  projects
- **Project Scaffolding**: Bootstrap new projects with standard layouts and automatic workspace integration
- **Version Coordination**: Manage version strings across multiple projects with git integration

## Use Cases

### Multi-Project Workspaces

Manage Python monorepos or multi-project repositories where several related packages share common build configurations,
dependencies, and tooling. Synchronize settings from a root project to all members automatically.

### Continuous Integration

Integrate workspace management into CI/CD pipelines with deterministic outputs and change detection.

## Installation

This package requires Python 3.12 or higher (< 3.14).

### For Use in Your Project (Recommended)

reggie-build is designed to be used as a development dependency. Add it to your `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "reggie-build-py @ git+https://github.com/reggie-db/reggie-build-py.git"
]
```

Then use it via `uv run` without polluting your production dependencies:

```bash
# Sync configurations
uv run reggie-build sync

# Create new projects
uv run reggie-build create new-service
```

Using `uv run` ensures reggie-build and its dependencies are isolated from your project's runtime dependencies while
remaining available for all developers and CI/CD environments.

### For reggie-build Development

```bash
# Clone and install in editable mode
git clone https://github.com/reggie-db/reggie-build-py.git
cd reggie-build-py
pip install -e .
```

## Commands

### Create

<!-- BEGIN:cmd reggie-build create --help -->
```shell
Usage: reggie-build create [OPTIONS] NAME COMMAND [ARGS]...                    
                                                                                
 Create a new member project in the workspace.                                  
                                                                                
 Sets up a pyproject.toml and a standard src/<package>/__init__.py layout.      
 Internal workspace dependencies are automatically synchronized after creation. 
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    name      TEXT  The name of the new project (used for directory and     │
│                      package name).                                          │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --path                         PATH  Optional parent directory within the    │
│                                      workspace root. Defaults to root.       │
│                                      [default: packages]                     │
│ --project-dependency  -pd      TEXT  List of existing workspace projects to  │
│                                      depend on.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd -->

```bash
# Create a new project
uv run reggie-build create my-project

# Create a project with dependencies on other workspace projects
uv run reggie-build create my-api \
  --project-dependency my-core \
  --project-dependency my-models

# Create in a specific path within the workspace
uv run reggie-build create my-project --path /path/to/parent
```

Created projects include:

- Standard Python src layout (`src/<package_name>/`)
- Configured `pyproject.toml` with optional dependencies
- `__init__.py` for package initialization
- Workspace integration support

### Sync

<!-- BEGIN:cmd reggie-build sync --help -->
```shell
Usage: reggie-build sync [OPTIONS] COMMAND [ARGS]...                           
                                                                                
 Synchronize project configurations across the workspace.                       
                                                                                
 This command performs several synchronization tasks to keep member projects    
 aligned with the root project settings and ensure consistent dependencies.     
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --name                -n                          TEXT  Specific member      │
│                                                         project names to     │
│                                                         sync.                │
│ --version                 --no-version                  Sync version from    │
│                                                         git history to all   │
│                                                         member projects.     │
│                                                         [default: version]   │
│ --build-system            --no-build-system             Sync  from root      │
│                                                         project to all       │
│                                                         member projects.     │
│                                                         [default:            │
│                                                         build-system]        │
│ --member-project-to…      --no-member-project…          Sync  from root      │
│                                                         project to all       │
│                                                         member projects.     │
│                                                         [default:            │
│                                                         member-project-tool] │
│ --member-project-de…      --no-member-project…          Sync internal member │
│                                                         dependencies to use  │
│                                                         file:// paths and uv │
│                                                         workspace sources.   │
│                                                         [default:            │
│                                                         member-project-depe… │
│ --member-paths            --no-member-paths             Sync member path     │
│                                                         patterns             │
│                                                         [default:            │
│                                                         member-paths]        │
│ --format-python           --no-format-python            Run ruff format and  │
│                                                         check on all         │
│                                                         projects.            │
│                                                         [default:            │
│                                                         format-python]       │
│ --format-pyproject        --no-format-pyproje…          Format               │
│                                                         pyproject.toml files │
│                                                         using taplo.         │
│                                                         [default:            │
│                                                         format-pyproject]    │
│                                                         and exit.            │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd -->

```bash
# Sync all configuration
uv run reggie-build sync

# Sync specific projects only
uv run reggie-build sync --name project1 --name project2

# Disable specific sync tasks
uv run reggie-build sync --no-version --no-format-python
```

### README

<!-- BEGIN:cmd reggie-build readme --help -->
```shell
Usage: reggie-build readme [OPTIONS] COMMAND [ARGS]...                         
                                                                                
 Update README command sentinel blocks.                                         
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --readme  -r                FILE     Path to README file to update.          │
│                                      [default: README.md]                    │
│ --write       --no-write             Write changes back to the README file.  │
│                                      [default: write]                        │
│ --jobs    -j                INTEGER  Maximum number of parallel commands.    │
│                                      [default: 13]                           │
│ --filter                    TEXT     Regex to select which BEGIN:cmd blocks  │
│                                      to update.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd -->

Automatically update README.md files by executing help commands embedded in sentinel blocks.

```bash
# Update all command blocks in README
uv run reggie-build readme update-cmd

# Specify a different README file
uv run reggie-build readme update-cmd --readme docs/CLI.md

# Only update specific commands (filter by regex)
uv run reggie-build readme update-cmd --filter "sync"

# Preview changes without writing
uv run reggie-build readme update-cmd --write false

# Control parallelism
uv run reggie-build readme update-cmd --jobs 4
```

> **Note**: This README's command documentation was automatically generated using `reggie-build readme`,
> which executes commands and embeds their help output into sentinel blocks.

#### How It Works

The `readme update-cmd` command looks for sentinel blocks in your README:

```markdown
<!-- BEGIN:cmd reggie-build sync --help -->
<!-- END:cmd -->
```

It executes the command between `BEGIN:cmd` and `--help`, captures the output, and replaces the content between the
BEGIN and END markers with a formatted code block containing the command's output.

**Features**:

- **Parallel Execution**: Runs multiple commands in parallel for faster updates
- **Smart Help Filtering**: Automatically removes `--help` option rows from help output to reduce noise
- **Empty Section Removal**: Removes empty Options sections when `--help` is the only option
- **Selective Updates**: Use `--filter` to update only specific commands
- **Safe by Default**: Preview mode available with `--write false`

This approach ensures your documentation stays in sync with actual command behavior, preventing documentation drift.

## Adopting reggie-build in Your Project

### Initial Setup

1. **Install reggie-build** in your project's dependencies
2. **Create a root pyproject.toml** if you don't have one
3. **Configure workspace members** to tell reggie-build which projects to manage
4. **Run your first sync** to align configurations

### Project Structure

The tool works with any workspace layout that has a root `pyproject.toml` and member projects:

```
your-workspace/
├── pyproject.toml              # Root configuration
├── core/                       # Your projects
│   ├── pyproject.toml
│   └── src/
│       └── core/
├── api/
│   ├── pyproject.toml
│   └── src/
│       └── api/
├── services/
│   ├── pyproject.toml
│   └── src/
│       └── services/
└── dev-local/                  # Auto-created for generated code
```

### Workspace Configuration

Add workspace configuration to your root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["core", "api", "services"]
# Or use globs for flexibility
members = ["*/"]
exclude = ["legacy", "archived"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# This section will be synced to all member projects
[tool.member-project]
# Shared configuration for all projects
```

### Common Workflows

**Keeping Projects in Sync**:

```bash
# Sync everything (run after changing root config)
uv run reggie-build sync

# Or sync specific aspects
uv run reggie-build sync --no-format-python
```

**Before Committing**:

```bash
# Sync and format
uv run reggie-build sync
```

## Module Reference

### config.py

Configuration and logging initialization for reggie-build. Sets up logging handlers and levels.

### pyproject.py

Utility for managing and manipulating pyproject.toml files using tomlkit and taplo.

### workspace.py

Interface for uv workspace metadata retrieval.

### workspace_create.py

Utilities for bootstrapping new workspace member projects.

### workspace_sync.py

Core synchronization logic for versions, build systems, and dependencies.

### readme.py

Automated README documentation updater using command output sentinels.

## Development

### Dependencies

Core dependencies:

- `uv`: Workspace and dependency management
- `ruff`: Python formatting and linting
- `taplo`: TOML formatting
- `typer`: CLI framework
- `tomlkit`: TOML manipulation
- `mergedeep`: Deep merging of configurations
- `dacite`: Dataclass conversion
- `sitecustomize-entrypoints`: Automatic logging initialization

### Environment Variables

- `LOG_LEVEL`: Control logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL)

## Extending reggie-build

The tool is designed to be extended for your specific needs:

### Adding New Commands

The modular architecture makes it easy to add new commands for your specific needs:

1. Create a new module in `src/reggie_build/`
2. Define a Typer app with your commands
3. Add it to `cli.py` to integrate with the CLI

## Real-World Examples

### Microservice Architecture

Use reggie-build to manage a microservice ecosystem where each service has its own project but shares common
infrastructure code, build configs, and deployment settings.

### Monorepo Management

Coordinate builds, tests, and deployments across dozens of related Python packages with consistent tooling and
dependencies.

## License

See [LICENSE](LICENSE) file for details.

## Contributing

Contributions that enhance workspace management capabilities are welcome. Maintain these principles:

- Preserve existing variable names and logic unless explicitly refactoring
- Add comprehensive documentation to all new or significantly modified code
- Follow Python standard ordering for globals, functions, and classes
- Use `_` prefix for private functions with limited scope
- Never use em dashes, en dashes, or unnecessary hyphens in prose
- Avoid emojis unless part of explicit instructions

## Support

For issues, questions, or feature requests related to using reggie-build in your project, please open an issue on
GitHub.
