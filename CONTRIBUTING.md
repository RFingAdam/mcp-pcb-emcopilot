# Contributing to MCP PCB EMCopilot

Thank you for your interest in contributing to MCP PCB EMCopilot! This guide will help you get started.

## Development Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/RFingAdam/mcp-pcb-emcopilot.git
   cd mcp-pcb-emcopilot
   ```

2. **Install in development mode with all dependencies:**

   ```bash
   uv pip install -e ".[all,dev]"
   ```

   Or with standard pip:

   ```bash
   pip install -e ".[all,dev]"
   ```

3. **Verify the installation:**

   ```bash
   pytest tests/ -v
   ```

## Running Tests

Run the full test suite:

```bash
pytest tests/ -v
```

Run tests with coverage:

```bash
pytest tests/ --cov=mcp_pcb_emcopilot --cov-report=term-missing
```

Run a specific test file:

```bash
pytest tests/test_kicad_parser.py -v
```

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

- **Line length:** 120 characters
- **Target Python version:** 3.10+
- **Lint rules:** E, F, W, I (isort), UP (pyupgrade), B (bugbear)

Run the linter:

```bash
ruff check src/ tests/
```

Auto-fix issues:

```bash
ruff check --fix src/ tests/
```

## Type Checking

We use [mypy](https://mypy-lang.org/) for static type analysis:

```bash
mypy src/mcp_pcb_emcopilot/ --ignore-missing-imports
```

Type annotations are encouraged for all public APIs. The package includes a `py.typed` marker for PEP 561 compliance.

## Architecture Overview

The project follows a clean pipeline architecture:

```
Parsers --> PCBDesignData --> Analyzers --> Server Tools
```

- **Parsers** (`src/mcp_pcb_emcopilot/parsers/`): Read PCB design files (KiCad, ODB++, Gerber, Altium, IPC-2581, Allegro) and produce a unified `PCBDesignData` model.
- **Models** (`src/mcp_pcb_emcopilot/models/`): Pydantic data models representing PCB designs, stackups, components, nets, traces, etc.
- **Analyzers** (`src/mcp_pcb_emcopilot/analyzers/`): Domain-specific analysis engines (EMC, signal integrity, power delivery, thermal, etc.) that operate on `PCBDesignData`.
- **Server** (`src/mcp_pcb_emcopilot/server.py`): MCP server that registers tools and routes requests to the appropriate analyzers.
- **Session** (`src/mcp_pcb_emcopilot/session.py`): Manages parsed design sessions so users can load a design once and run multiple analyses.

## Adding a New Analyzer

1. Create a new file in `src/mcp_pcb_emcopilot/analyzers/` (e.g., `my_analyzer.py`).
2. Implement your analysis function(s) that accept `PCBDesignData` and return structured results.
3. Register the tool(s) in `src/mcp_pcb_emcopilot/server.py` using the MCP tool decorator pattern.
4. Add tests in `tests/` (e.g., `test_my_analyzer.py`) with appropriate test fixtures.

Example pattern:

```python
# src/mcp_pcb_emcopilot/analyzers/my_analyzer.py
from mcp_pcb_emcopilot.models import PCBDesignData

def analyze_something(design: PCBDesignData, **params) -> dict:
    """Analyze some aspect of the PCB design."""
    results = {}
    # ... analysis logic ...
    return results
```

## Adding a New Parser

1. Create a new parser file in `src/mcp_pcb_emcopilot/parsers/` (e.g., `my_format_parser.py`).
2. Implement parsing logic that converts the file format into `PCBDesignData`.
3. Register the parser in `src/mcp_pcb_emcopilot/parsers/__init__.py`.
4. Add test fixtures (sample files) in `tests/fixtures/` and corresponding tests.

## Pull Request Process

1. **Fork and branch:** Create a feature branch from `main` (e.g., `feature/add-xyz-analyzer`).
2. **Make changes:** Implement your feature or fix.
3. **Test:** Ensure all tests pass and add new tests for new functionality.
4. **Lint:** Run `ruff check src/ tests/` and fix any issues.
5. **Type check:** Run `mypy src/mcp_pcb_emcopilot/ --ignore-missing-imports`.
6. **Submit PR:** Open a pull request against `main` with a clear description.

### PR Checklist

Before submitting, verify:

- [ ] Tests added or updated for the change
- [ ] `ruff check` passes with no errors
- [ ] `mypy` passes (or not applicable)
- [ ] Documentation updated if adding new tools or changing behavior
- [ ] No customer-specific or proprietary data included in commits
- [ ] Commit messages are clear and descriptive

## Reporting Issues

Please use the GitHub issue templates:

- **Bug reports:** Include steps to reproduce, expected behavior, PCB format used, and Python version.
- **Feature requests:** Describe the use case and proposed solution.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
