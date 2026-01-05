# reggie-build

A comprehensive workspace management tool designed to handle complicated and common code generation tasks across multi-project Python environments. Built to be adopted by any project requiring automated code generation, workspace synchronization, and build orchestration.

## Why Use reggie-build?

Managing multi-project Python workspaces becomes increasingly complex as projects grow. Common challenges include:

- **Code Generation Complexity**: OpenAPI specs, protobuf definitions, and other schema-driven code need consistent regeneration workflows
- **Configuration Drift**: Build configs, dependencies, and tool settings diverge across related projects
- **Workspace Coordination**: Multiple projects with interdependencies require careful version and dependency management
- **Build Artifact Management**: Generated files, caches, and artifacts accumulate without systematic cleanup

`reggie-build` solves these problems by providing a battle-tested CLI that orchestrates:

- **Automated Code Generation**: Generate FastAPI code from OpenAPI specs with hash-based change detection and watch mode
- **Smart Synchronization**: Keep build configs, dependencies, and tool settings consistent across all workspace projects
- **Project Scaffolding**: Bootstrap new projects with standard layouts and automatic workspace integration
- **Artifact Management**: Clean build artifacts safely with protection for critical directories
- **Version Coordination**: Manage version strings across multiple projects with git integration

## Use Cases

### OpenAPI-Driven Development
Generate type-safe FastAPI code from OpenAPI specifications with custom templates. The tool handles downloading specs from URLs, detecting changes, and only updating when necessary. Perfect for microservice architectures where API contracts drive implementation.

### Multi-Project Workspaces
Manage Python monorepos or multi-project repositories where several related packages share common build configurations, dependencies, and tooling. Synchronize settings from a root project to all members automatically.

### Continuous Integration
Integrate code generation into CI/CD pipelines with deterministic outputs and change detection. Only regenerate when specs change, reducing unnecessary diff noise.

### Schema-Driven Workflows
While currently supporting OpenAPI, the architecture can be extended to handle other code generation tasks like protobuf compilation, GraphQL schema generation, or database model generation.

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
# Generate code
uv run reggie-build openapi generate spec.yaml

# Sync configurations
uv run reggie-build sync

# Clean artifacts
uv run reggie-build clean build-artifacts

# Create new projects
uv run reggie-build create member new-service
```

Using `uv run` ensures reggie-build and its dependencies are isolated from your project's runtime dependencies while remaining available for all developers and CI/CD environments.

### For reggie-build Development

```bash
# Clone and install in editable mode
git clone https://github.com/reggie-db/reggie-build-py.git
cd reggie-build-py
pip install -e .
```

## Commands

### Clean

<!-- BEGIN:cmd reggie-build clean build-artifacts --help -->
```bash
Usage: reggie-build clean build-artifacts [OPTIONS]                            
                                                                                
 Remove Python build artifacts from the workspace.                              
 This command recursively walks the workspace directory tree and removes: -     
 Virtual environment directories (.venv) - Python bytecode cache directories    
 (__pycache__) - Python egg-info directories                                    
 It protects the root .venv and scripts directory from deletion.
```
<!-- END:cmd reggie-build clean build-artifacts --help -->

```bash
# Clean all build artifacts
uv run reggie-build clean build-artifacts
```

This command removes:
- Virtual environments (`.venv` directories)
- Python bytecode caches (`__pycache__` directories)
- Egg info directories

The root `.venv` and scripts directory are protected from deletion.

### Create

<!-- BEGIN:cmd reggie-build create member --help -->
```bash
Usage: reggie-build create member [OPTIONS] NAME                               
                                                                                
 Create a new member project in the workspace.                                  
 This command creates a new Python project with: - A pyproject.toml             
 configuration file - Standard src layout (src/<package_name>/__init__.py) -    
 Optional dependencies on other workspace projects                              
 The project name is used for both the directory and package name (with hyphens 
 converted to underscores for the package).                                     
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    name      TEXT  Name of the project to create. Used as both the         │
│                      directory name and the project name.                    │
│                      [default: None]                                         │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --path                         DIRECTORY  Optional parent directory path     │
│                                           within the workspace root. If      │
│                                           omitted, the project is created in │
│                                           the workspace root.                │
│                                           [default: None]                    │
│ --project-dependency  -pd      TEXT       Optional list of existing          │
│                                           workspace project names to include │
│                                           as dependencies in the new         │
│                                           project's pyproject.toml.          │
│                                           [default: None]                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build create member --help -->

```bash
# Create a new project
uv run reggie-build create member my-project

# Create a project with dependencies on other workspace projects
uv run reggie-build create member my-api \
  --project-dependency my-core \
  --project-dependency my-models

# Create in a specific path within the workspace
uv run reggie-build create member my-project --path /path/to/parent
```

Created projects include:
- Standard Python src layout (`src/<package_name>/`)
- Configured `pyproject.toml` with optional dependencies
- `__init__.py` for package initialization
- Workspace integration support

### Sync

<!-- BEGIN:cmd reggie-build sync --help -->
```bash
Usage: reggie-build sync [OPTIONS] COMMAND [ARGS]...                           
                                                                                
 Synchronize all configuration across member projects.                          
 When run without a subcommand, executes all registered sync commands against   
 the selected projects. This includes build-system config, dependencies, tool   
 settings, formatting, and versioning.                                          
 Use --project to limit which projects are affected, or omit to sync all        
 workspace members.                                                             
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --project  -p      TEXT  Optional list of project names or identifiers to    │
│                          sync                                                │
│                          [default: None]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ build-system                  Synchronize build-system configuration from    │
│                               the root project to member projects.           │
│ member-project-dependencies   Synchronize member project dependencies to use │
│                               workspace file references.                     │
│ member-project-tool           Synchronize tool.member-project configuration  │
│                               from the root project to member projects.      │
│ ruff                          Run ruff formatter on git-tracked Python       │
│                               files.                                         │
│ version                       Synchronize project versions across selected   │
│                               projects.                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build sync --help -->

```bash
# Sync all configuration
uv run reggie-build sync

# Sync specific projects only
uv run reggie-build sync --project project1 --project project2

# Run individual sync commands
uv run reggie-build sync build-system
uv run reggie-build sync member-project-dependencies
uv run reggie-build sync member-project-tool
uv run reggie-build sync ruff
uv run reggie-build sync version
```

#### Sync Subcommands

**build-system**

<!-- BEGIN:cmd reggie-build sync build-system --help -->
```bash
2026-01-05 15:36:51 [INFO] sync - Syncing build-system
                                                                                
 Usage: reggie-build sync build-system [OPTIONS]                                
                                                                                
 Synchronize build-system configuration from the root project to member         
 projects.                                                                      
 Copies the [build-system] section from the root pyproject.toml to all selected 
 projects, ensuring consistent build tooling across the workspace.              
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --project  -p      TEXT  Optional list of project names or identifiers to    │
│                          sync                                                │
│                          [default: None]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build sync build-system --help -->

**member-project-dependencies**

<!-- BEGIN:cmd reggie-build sync member-project-dependencies --help -->
```bash
2026-01-05 15:36:51 [INFO] sync - Syncing member-project-dependencies
                                                                                
 Usage: reggie-build sync member-project-dependencies [OPTIONS]                 
                                                                                
 Synchronize member project dependencies to use workspace file references.      
 Converts member project dependencies to file:// references using               
 ${PROJECT_ROOT} placeholders and updates tool.uv.sources accordingly.          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --project  -p      TEXT  Optional list of project names or identifiers to    │
│                          sync                                                │
│                          [default: None]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build sync member-project-dependencies --help -->

**member-project-tool**

<!-- BEGIN:cmd reggie-build sync member-project-tool --help -->
```bash
2026-01-05 15:36:51 [INFO] sync - Syncing member-project-tool
                                                                                
 Usage: reggie-build sync member-project-tool [OPTIONS]                         
                                                                                
 Synchronize tool.member-project configuration from the root project to member  
 projects.                                                                      
 Copies the [tool.member-project] section from the root pyproject.toml to all   
 selected projects.                                                             
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --project  -p      TEXT  Optional list of project names or identifiers to    │
│                          sync                                                │
│                          [default: None]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build sync member-project-tool --help -->

**ruff**

<!-- BEGIN:cmd reggie-build sync ruff --help -->
```bash
2026-01-05 15:36:51 [INFO] sync - Syncing ruff
                                                                                
 Usage: reggie-build sync ruff [OPTIONS]                                        
                                                                                
 Run ruff formatter on git-tracked Python files.                                
 Formats all Python files tracked by git using the ruff formatter. If ruff is   
 not installed, either warns or fails depending on the require parameter.
```
<!-- END:cmd reggie-build sync ruff --help -->

**version**

<!-- BEGIN:cmd reggie-build sync version --help -->
```bash
2026-01-05 15:36:51 [INFO] sync - Syncing version
                                                                                
 Usage: reggie-build sync version [OPTIONS] [VERSION]                           
                                                                                
 Synchronize project versions across selected projects.                         
 Updates the version field in pyproject.toml for all selected projects. If no   
 version is specified, attempts to derive one from git commit hash or uses the  
 default version.                                                               
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   version      [VERSION]  Version string to apply (e.g. 1.2.3 or             │
│                           0.0.1+gabc123). If omitted, derived from git or    │
│                           defaults to 0.0.1.                                 │
│                           [default: None]                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --project  -p      TEXT  Optional list of project names or identifiers to    │
│                          sync                                                │
│                          [default: None]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build sync version --help -->

```bash
# Use git-derived version
uv run reggie-build sync version

# Specify explicit version
uv run reggie-build sync version 1.2.3
```

### OpenAPI

<!-- BEGIN:cmd reggie-build openapi generate --help -->
```bash
Usage: reggie-build openapi generate [OPTIONS] INPUT_SPEC [OUTPUT_DIR]         
                                                                                
 Generate FastAPI code from an OpenAPI specification and sync changes.          
 This command generates Python code from an OpenAPI spec, creating FastAPI      
 routes and Pydantic models. It uses hash-based change detection to only update 
 the output directory when files actually change.                               
 In watch mode, the command monitors the spec file and regenerates code         
 whenever changes are detected.                                                 
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    input_spec      TEXT          Path or URL to the OpenAPI specification  │
│                                    (YAML or JSON). May be a local file path  │
│                                    or an HTTP(S) URL.                        │
│                                    [default: None]                           │
│                                    [required]                                │
│      output_dir      [OUTPUT_DIR]  Destination directory for generated code. │
│                                    [default: None]                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --template-dir        PATH  Optional template directory for                  │
│                             fastapi-code-generator.                          │
│                             [default: None]                                  │
│ --watch                     Watch a local spec file for changes and          │
│                             regenerate on updates.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build openapi generate --help -->

```bash
# Generate from local file
uv run reggie-build openapi generate spec.yaml

# Generate from URL (great for CI/CD)
uv run reggie-build openapi generate https://example.com/api/openapi.json

# Specify output directory
uv run reggie-build openapi generate spec.yaml output-dir

# Use custom templates
uv run reggie-build openapi generate spec.yaml --template-dir ./templates

# Watch mode for development (regenerate on changes)
uv run reggie-build openapi generate spec.yaml --watch
```

#### Why This Generator?

Unlike basic code generators, reggie-build's OpenAPI generator is designed for real-world production use:

**Smart Change Detection**: Uses SHA-256 hashing to detect actual changes in generated code, ignoring timestamp comments. Only updates output when content actually changes, reducing git diff noise.

**Remote Spec Support**: Download specs from URLs with content-based directory naming. Perfect for consuming external APIs or working with spec servers in CI/CD pipelines.

**Custom Templates**: Ships with production-ready templates that generate abstract API contract classes, making it easy to implement APIs by extending generated base classes. Customize templates for your specific needs.

**Watch Mode**: During development, automatically regenerate code when specs change. Speeds up the edit-test cycle for API-driven development.

The generator produces:
- FastAPI routers with type-safe endpoints
- Pydantic models from schemas with full validation
- Abstract API contract base classes for clean implementation patterns
- Request/response logging and debugging support
- Proper separation between generated code and business logic

### README

<!-- BEGIN:cmd reggie-build readme update-cmd --help -->
```bash
Usage: reggie-build readme update-cmd [OPTIONS]                                
                                                                                
 Update README command sentinel blocks.                                         
 Only blocks whose command matches --filter are executed and updated.           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --readme  -r                FILE     Path to README file to update.          │
│                                      [default: README.md]                    │
│ --write       --no-write             Write changes back to the README file.  │
│                                      [default: write]                        │
│ --jobs    -j                INTEGER  Maximum number of parallel commands.    │
│                                      [default: 13]                           │
│ --filter                    TEXT     Regex to select which BEGIN:cmd blocks  │
│                                      to update.                              │
│                                      [default: None]                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build readme update-cmd --help -->

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

> **Note**: This README's command documentation was automatically generated using `reggie-build readme update-cmd`, which executes commands and embeds their help output into sentinel blocks.


#### How It Works

The `readme update-cmd` command looks for sentinel blocks in your README:

```markdown

<!-- BEGIN:cmd reggie-build sync --help -->
```bash
Usage: reggie-build sync [OPTIONS] COMMAND [ARGS]...                           
                                                                                
 Synchronize all configuration across member projects.                          
 When run without a subcommand, executes all registered sync commands against   
 the selected projects. This includes build-system config, dependencies, tool   
 settings, formatting, and versioning.                                          
 Use --project to limit which projects are affected, or omit to sync all        
 workspace members.                                                             
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --project  -p      TEXT  Optional list of project names or identifiers to    │
│                          sync                                                │
│                          [default: None]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ build-system                  Synchronize build-system configuration from    │
│                               the root project to member projects.           │
│ member-project-dependencies   Synchronize member project dependencies to use │
│                               workspace file references.                     │
│ member-project-tool           Synchronize tool.member-project configuration  │
│                               from the root project to member projects.      │
│ ruff                          Run ruff formatter on git-tracked Python       │
│                               files.                                         │
│ version                       Synchronize project versions across selected   │
│                               projects.                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```
<!-- END:cmd reggie-build sync --help -->

It executes the command between `BEGIN:cmd` and `--help`, captures the output, and replaces the content between the BEGIN and END markers with a formatted code block containing the command's output.

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

**Setting Up Code Generation**:
```bash
# Generate API code from your OpenAPI spec
uv run reggie-build openapi generate api/spec.yaml api/generated

# Add to your CI pipeline for automated updates
uv run reggie-build openapi generate https://api-server/openapi.json
```

**Keeping Projects in Sync**:
```bash
# Sync everything (run after changing root config)
uv run reggie-build sync

# Or sync specific aspects
uv run reggie-build sync build-system
uv run reggie-build sync member-project-dependencies
```

**Before Committing**:
```bash
# Format code
uv run reggie-build sync ruff

# Clean artifacts
uv run reggie-build clean build-artifacts
```

## Module Reference

### app.py

Main entry point that aggregates all subcommands and provides a unified CLI interface.

### clean.py

Utilities for removing build artifacts, with protection for important directories.

### create.py

Project bootstrapping with standard Python layouts and dependency management.

### openapi.py

FastAPI code generation from OpenAPI specs with synchronization and watch mode support. Uses the `fastapi-code-generator` library with custom templates for generating API contract classes.

### projects.py

Project discovery, loading, and manipulation. Provides the `Project` class for working with `pyproject.toml` files using benedict for dynamic attribute access.

Key functions:
- `root()`: Get the root workspace project
- `root_dir()`: Get the workspace root directory path
- `dir(input)`: Find project directory by path or name

Key class:
- `Project`: Wraps a pyproject.toml with methods for accessing metadata, checking workspace membership, and iterating member projects

### readme.py

Automated README documentation updater that executes commands and embeds their output in sentinel blocks. Keeps documentation synchronized with actual command behavior.

Key features:
- Parallel command execution for fast updates
- Smart filtering of help output (removes `--help` rows, empty sections)
- Selective updates via regex filtering
- Safe preview mode

### sync.py

Configuration synchronization across workspace projects. Commands can be run individually or all together via the main sync callback.

### utils.py

Common utilities including:
- Logging configuration with stdout/stderr separation
- File watching for continuous workflows
- Git integration for version strings and file tracking
- Executable discovery with caching

## Development

### Dependencies

Core dependencies:
- `typer`: CLI framework
- `tomlkit`: TOML manipulation
- `python-benedict`: Dictionary with dot notation
- `fastapi-code-generator`: OpenAPI to FastAPI conversion
- `packaging`: Version handling

### Environment Variables

- `LOG_LEVEL`: Control logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL)

### Templates

The OpenAPI generator includes custom Jinja2 templates in `src/reggie_build/openapi_template/`. The `main.jinja` template generates:
- `APIContract` abstract base class with operation methods
- `GeneratedRouter` class that binds routes to contract implementations
- `create_app()` helper for FastAPI application creation

## Extending reggie-build

The tool is designed to be extended for your specific code generation needs:

### Custom OpenAPI Templates

Create your own Jinja2 templates to customize generated code:

```bash
# Use your templates
uv run reggie-build openapi generate spec.yaml --template-dir ./my-templates
```

Study the included templates in `src/reggie_build/openapi_template/` as a starting point.

### Adding New Commands

The modular architecture makes it easy to add new commands for your specific needs:

1. Create a new module in `src/reggie_build/`
2. Define a Typer app with your commands
3. Add it to `app.py` to integrate with the CLI

### Custom Sync Operations

Add project-specific sync operations by creating new commands in the sync module. These automatically integrate with `reggie-build sync` to run all operations at once.

## Real-World Examples

### Microservice Architecture
Use reggie-build to manage a microservice ecosystem where each service has its own project but shares common infrastructure code, build configs, and API contracts.

### API Gateway Pattern
Generate client libraries and server stubs from a central OpenAPI specification. Keep multiple language implementations in sync with a single source of truth.

### Monorepo Management
Coordinate builds, tests, and deployments across dozens of related Python packages with consistent tooling and dependencies.

## License

See [LICENSE](LICENSE) file for details.

## Contributing

Contributions that enhance code generation capabilities, add new generators, or improve workspace management are welcome. Maintain these principles:
- Preserve existing variable names and logic unless explicitly refactoring
- Add comprehensive documentation to all new or significantly modified code
- Follow Python standard ordering for globals, functions, and classes
- Use `_` prefix for private functions with limited scope
- Never use em dashes, en dashes, or unnecessary hyphens in prose
- Avoid emojis unless part of explicit instructions

## Support

For issues, questions, or feature requests related to using reggie-build in your project, please open an issue on GitHub.

