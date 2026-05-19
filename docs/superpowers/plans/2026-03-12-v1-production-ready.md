# v1.0 Production Ready Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mcp-pcb-emcopilot production-ready with proper error handling, CI/CD, type safety, comprehensive tests, sample designs, contributor docs, and PyPI publishing.

**Architecture:** 4 parallel workstreams on non-overlapping files: (A) Error handling + validation in parsers/analyzers, (B) CI/CD + CONTRIBUTING + PyPI config, (C) Type hints + mypy across all modules, (D) Sample PCB designs + comprehensive test suite for all 93 tools.

**Tech Stack:** Python 3.10+, pytest, mypy, ruff, GitHub Actions, hatchling (PyPI)

**Issues:** #16, #17, #18, #19, #20, #21, #22

---

## Chunk 1: CI/CD, Contributing, PyPI Config (Issues #19, #20, #22)

These are independent infrastructure files that don't touch source code.

### Task 1: GitHub Actions CI/CD Pipeline (#19)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: |
          pip install -e ".[all]"
          pip install pytest pytest-cov ruff mypy cairosvg python-docx
      - name: Lint with ruff
        run: ruff check src/ tests/
      - name: Type check with mypy
        run: mypy src/mcp_pcb_emcopilot/ --ignore-missing-imports
      - name: Run tests
        run: pytest tests/ -v --tb=short --co -q | tail -5 && pytest tests/ -v --tb=short
      - name: Check coverage
        run: pytest tests/ --cov=mcp_pcb_emcopilot --cov-report=term-missing --cov-fail-under=70
```

- [ ] **Step 2: Create release workflow**

```yaml
# .github/workflows/release.yml
name: Release to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install build tools
        run: pip install build
      - name: Build package
        run: python -m build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 3: Verify CI config is valid YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`

- [ ] **Step 4: Commit**

```bash
git add .github/
git commit -m "feat: add CI/CD pipeline with GitHub Actions (#19)"
```

### Task 2: CONTRIBUTING.md and Templates (#20)

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: Create CONTRIBUTING.md**

Cover: dev setup, coding standards (ruff, mypy), testing (pytest, TDD), PR process, architecture overview.

- [ ] **Step 2: Create bug report template**

YAML-based GitHub issue form with fields: description, steps to reproduce, expected behavior, PCB format, Python version.

- [ ] **Step 3: Create feature request template**

YAML-based with fields: description, use case, proposed solution, alternatives considered.

- [ ] **Step 4: Create PR template**

Markdown checklist: description, tests added, docs updated, lint passes, type check passes.

- [ ] **Step 5: Commit**

```bash
git add CONTRIBUTING.md .github/
git commit -m "docs: add CONTRIBUTING.md and issue/PR templates (#20)"
```

### Task 3: PyPI Publishing Config (#22)

**Files:**
- Modify: `pyproject.toml`
- Create: `src/mcp_pcb_emcopilot/py.typed`

- [ ] **Step 1: Update pyproject.toml**

Add ruff config, mypy config, pytest config, update classifiers, add project URLs, add dev dependencies group.

```toml
[project.urls]
Homepage = "https://github.com/RFingAdam/mcp-pcb-emcopilot"
Documentation = "https://github.com/RFingAdam/mcp-pcb-emcopilot#readme"
Repository = "https://github.com/RFingAdam/mcp-pcb-emcopilot"
Issues = "https://github.com/RFingAdam/mcp-pcb-emcopilot/issues"

[project.optional-dependencies]
# ... existing ...
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.4.0",
    "mypy>=1.10",
    "cairosvg>=2.7",
    "python-docx>=1.1",
]

[tool.ruff]
target-version = "py310"
line-length = 120
[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

- [ ] **Step 2: Create py.typed marker**

```
# src/mcp_pcb_emcopilot/py.typed
# PEP 561 marker — this package supports type checking
```

- [ ] **Step 3: Verify build**

Run: `python3 -m build --no-isolation 2>&1 | tail -5`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/mcp_pcb_emcopilot/py.typed
git commit -m "build: configure PyPI publishing, ruff, mypy, pytest (#22)"
```

---

## Chunk 2: Error Handling & Validation (#18)

Systematic input validation and structured error responses across all parsers and server tool dispatch.

### Task 4: Add Structured Error Types

**Files:**
- Create: `src/mcp_pcb_emcopilot/errors.py`
- Test: `tests/test_errors.py`

- [ ] **Step 1: Write tests for error types**

```python
# tests/test_errors.py
from mcp_pcb_emcopilot.errors import (
    PCBError, ParseError, ValidationError, AnalysisError,
    error_response, validate_positive, validate_range, validate_session
)

def test_parse_error_to_dict():
    e = ParseError("MALFORMED_FILE", "Bad header", {"file": "test.pcb"})
    d = e.to_dict()
    assert d["code"] == "MALFORMED_FILE"
    assert d["error_type"] == "parse_error"

def test_error_response_format():
    result = error_response("INVALID_INPUT", "Width must be positive", {"width": -1})
    assert result["success"] is False
    assert result["error"]["code"] == "INVALID_INPUT"

def test_validate_positive():
    assert validate_positive(1.0, "width") == 1.0
    try:
        validate_positive(-1.0, "width")
        assert False, "Should raise"
    except ValidationError as e:
        assert "width" in str(e)

def test_validate_range():
    assert validate_range(4.3, 1.0, 20.0, "Er") == 4.3
    try:
        validate_range(0.5, 1.0, 20.0, "Er")
        assert False
    except ValidationError:
        pass

def test_validate_session(sessions_fixture):
    # Test with invalid session ID
    try:
        validate_session("nonexistent", sessions_fixture)
        assert False
    except ValidationError as e:
        assert "session" in str(e).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_errors.py -v`
Expected: ImportError

- [ ] **Step 3: Implement error module**

```python
# src/mcp_pcb_emcopilot/errors.py
"""Structured error types for PCB EMCopilot."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class PCBError(Exception):
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.__class__.__name__.lower().replace("error", "_error").strip("_"),
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }

class ParseError(PCBError): pass
class ValidationError(PCBError): pass
class AnalysisError(PCBError): pass
class SessionError(PCBError): pass

def error_response(code: str, message: str, context: dict | None = None) -> dict:
    return {
        "success": False,
        "error": {"code": code, "message": message, "context": context or {}},
    }

def validate_positive(value: float, name: str) -> float:
    if value <= 0:
        raise ValidationError("INVALID_VALUE", f"{name} must be positive, got {value}", {name: value})
    return value

def validate_range(value: float, min_val: float, max_val: float, name: str) -> float:
    if not (min_val <= value <= max_val):
        raise ValidationError(
            "OUT_OF_RANGE",
            f"{name} must be between {min_val} and {max_val}, got {value}",
            {name: value, "min": min_val, "max": max_val},
        )
    return value

def validate_session(session_id: str, manager) -> Any:
    design = manager.get(session_id)
    if design is None:
        raise ValidationError(
            "INVALID_SESSION",
            f"No active session with ID '{session_id}'. Use pcb_parse_layout first.",
            {"session_id": session_id},
        )
    return design
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_errors.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/errors.py tests/test_errors.py
git commit -m "feat: add structured error types and validation helpers (#18)"
```

### Task 5: Add Input Validation to Server Tool Dispatch

**Files:**
- Modify: `src/mcp_pcb_emcopilot/server.py`
- Test: `tests/test_tool_validation.py`

- [ ] **Step 1: Write tests for tool parameter validation**

Test that each calculator tool rejects invalid inputs (negative trace width, zero dielectric height, NaN values, extreme values) and returns structured error responses.

- [ ] **Step 2: Add validation wrapper to server.py handle_call**

Add try/except around each tool dispatch that catches ValidationError/PCBError and returns structured JSON error. Add parameter validation at entry point for all calculator tools.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_tool_validation.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/mcp_pcb_emcopilot/server.py tests/test_tool_validation.py
git commit -m "feat: add input validation to all calculator tools (#18)"
```

### Task 6: Add Parser Error Handling

**Files:**
- Modify: `src/mcp_pcb_emcopilot/parsers/__init__.py`
- Modify: `src/mcp_pcb_emcopilot/parsers/altium_parser.py`
- Modify: `src/mcp_pcb_emcopilot/parsers/odb_parser.py`
- Test: `tests/test_parser_errors.py`

- [ ] **Step 1: Write tests for parser error paths**

Test: nonexistent file, empty file, corrupt binary, wrong format, file too large (>500MB check), permission denied.

- [ ] **Step 2: Add file validation to parse_pcb_file()**

Add file existence check, size limit (500MB), magic byte validation before format-specific parsing. Wrap each parser in try/except returning ParseError with context.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_parser_errors.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/mcp_pcb_emcopilot/parsers/ tests/test_parser_errors.py
git commit -m "feat: add robust error handling to all parsers (#18)"
```

---

## Chunk 3: Type Hints & Docstrings (#21)

### Task 7: Add Type Hints to All Parsers

**Files:**
- Modify: All files in `src/mcp_pcb_emcopilot/parsers/`

- [ ] **Step 1: Add type hints to parsers/__init__.py**

All functions get full type annotations including return types.

- [ ] **Step 2: Add type hints to kicad_pcb_parser.py, odb_parser.py, altium_parser.py**

Focus on public API functions. Internal helpers get basic annotations.

- [ ] **Step 3: Add type hints to remaining parsers**

gerber_parser.py, ipc2581_parser.py, step_parser.py, pdf_schematic_parser.py

- [ ] **Step 4: Run mypy**

Run: `mypy src/mcp_pcb_emcopilot/parsers/ --ignore-missing-imports`
Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/parsers/
git commit -m "feat: add type hints to all parser modules (#21)"
```

### Task 8: Add Type Hints to All Analyzers

**Files:**
- Modify: All files in `src/mcp_pcb_emcopilot/analyzers/`

- [ ] **Step 1-4: Add type hints to each analyzer subdomain**

emc/, rf_si/, high_speed/, power_integrity/, thermal/, dfm/, antenna/, validation/

- [ ] **Step 5: Run mypy**

Run: `mypy src/mcp_pcb_emcopilot/analyzers/ --ignore-missing-imports`

- [ ] **Step 6: Commit**

```bash
git add src/mcp_pcb_emcopilot/analyzers/
git commit -m "feat: add type hints to all analyzer modules (#21)"
```

### Task 9: Add Type Hints to Server, Session, Models

**Files:**
- Modify: `src/mcp_pcb_emcopilot/server.py`
- Modify: `src/mcp_pcb_emcopilot/session.py`

- [ ] **Step 1: Add type hints to server.py functions**
- [ ] **Step 2: Add type hints to session.py**
- [ ] **Step 3: Run full mypy check**

Run: `mypy src/mcp_pcb_emcopilot/ --ignore-missing-imports`

- [ ] **Step 4: Commit**

```bash
git add src/mcp_pcb_emcopilot/
git commit -m "feat: add type hints to server and session modules (#21)"
```

---

## Chunk 4: Sample Designs & Comprehensive Tests (#17, #16)

### Task 10: Create Synthetic Sample PCB Designs (#17)

**Files:**
- Create: `tests/fixtures/README.md`
- Create: `tests/fixtures/simple_2layer.kicad_pcb`
- Create: `tests/fixtures/mixed_signal_4layer.kicad_pcb`
- Create: `tests/fixtures/generate_fixtures.py` (generates ODB++, Gerber, IPC-2581 test data)
- Create: `tests/conftest.py` (shared fixtures)

- [ ] **Step 1: Create tests/fixtures/ directory and README**
- [ ] **Step 2: Create minimal KiCad test designs programmatically**

Write a generator script that produces syntactically valid .kicad_pcb files with known component counts, net lists, and trace geometries. 2-layer simple board and 4-layer mixed-signal.

- [ ] **Step 3: Create ODB++ test archive**

Generate a minimal valid ODB++ directory structure (matrix, steps/pcb/layers/*, misc/info) as a .tgz file with known data.

- [ ] **Step 4: Create Gerber test files**

Generate minimal RS-274X files with known apertures and draws.

- [ ] **Step 5: Create IPC-2581 test XML**

Generate minimal valid IPC-2581 XML with known components and nets.

- [ ] **Step 6: Create shared conftest.py with fixtures**

```python
# tests/conftest.py
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def simple_2layer_kicad():
    return str(FIXTURES_DIR / "simple_2layer.kicad_pcb")

@pytest.fixture
def mixed_signal_4layer_kicad():
    return str(FIXTURES_DIR / "mixed_signal_4layer.kicad_pcb")

@pytest.fixture
def sample_odb_archive():
    return str(FIXTURES_DIR / "sample_4layer.tgz")

@pytest.fixture
def sample_gerber():
    return str(FIXTURES_DIR / "sample_top_copper.gbr")

@pytest.fixture
def sample_ipc2581():
    return str(FIXTURES_DIR / "sample_design.xml")
```

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/ tests/conftest.py
git commit -m "feat: add synthetic sample PCB designs for testing (#17)"
```

### Task 11: Parser Tests (#16 - parsers)

**Files:**
- Create: `tests/test_kicad_parser.py`
- Create: `tests/test_odb_parser.py`
- Create: `tests/test_gerber_parser.py`
- Create: `tests/test_ipc2581_parser.py`
- Create: `tests/test_altium_parser.py`
- Create: `tests/test_format_detection.py`

- [ ] **Step 1: Write format detection tests**

Test detect_format() with every supported extension, content-based XML detection, unknown formats.

- [ ] **Step 2: Write KiCad parser tests**

Test: parse simple board, verify component count, net names, trace widths, layer stackup. Test error cases.

- [ ] **Step 3: Write ODB++ parser tests**

Test: parse sample archive, verify extraction of matrix, stackup, components, nets, drill table.

- [ ] **Step 4: Write Gerber parser tests**

Test: parse sample gerber, verify aperture parsing, draw/flash commands, board outline extraction.

- [ ] **Step 5: Write IPC-2581 parser tests**

Test: parse sample XML, verify component and net extraction.

- [ ] **Step 6: Write Altium parser tests**

Test: mock OLE file structure, verify component/net extraction, handle missing olefile gracefully.

- [ ] **Step 7: Commit**

```bash
git add tests/test_*_parser.py tests/test_format_detection.py
git commit -m "feat: add comprehensive parser tests (#16)"
```

### Task 12: Analyzer Tests (#16 - analyzers)

**Files:**
- Create: `tests/test_impedance_calcs.py`
- Create: `tests/test_emc_analyzers.py`
- Create: `tests/test_si_analyzers.py`
- Create: `tests/test_pi_analyzers.py`
- Create: `tests/test_highspeed_analyzers.py`
- Create: `tests/test_dfm_analyzers.py`
- Create: `tests/test_thermal_analyzers.py`
- Create: `tests/test_antenna_analyzers.py`

- [ ] **Step 1-8: Write tests for each analyzer domain**

Each test file covers all tools in that domain with:
- Known-good reference calculations (manually verified)
- Edge cases (zero values, extreme values, boundary conditions)
- At least 3 test cases per tool

- [ ] **Step 9: Run full test suite and verify coverage**

Run: `pytest tests/ -v --cov=mcp_pcb_emcopilot --cov-report=term-missing`
Target: >= 70% coverage

- [ ] **Step 10: Commit**

```bash
git add tests/
git commit -m "feat: add comprehensive analyzer tests for all 93 tools (#16)"
```

---

## Chunk 5: Allegro Parser & Altium Hardening (#25 + Altium improvements)

### Task 13: Allegro/OrCAD Parser (#25)

**Files:**
- Create: `src/mcp_pcb_emcopilot/parsers/allegro_parser.py`
- Modify: `src/mcp_pcb_emcopilot/parsers/__init__.py` (add allegro to detect_format and parse_pcb_file)
- Create: `tests/test_allegro_parser.py`
- Create: `tests/fixtures/sample_allegro_extract.txt` (Allegro ASCII export format)

- [ ] **Step 1: Write Allegro parser tests**

Test parsing of Allegro ASCII export format (.brd extract), component extraction, net extraction, trace/via data.

- [ ] **Step 2: Implement Allegro parser**

Parse Allegro ASCII export format (from "File > Export > ASCII..."). Support:
- Component placement (COMPONENT section)
- Net connectivity (NET section)
- Via definitions
- Constraint rules
- Board outline

- [ ] **Step 3: Register in parsers/__init__.py**

Add "allegro" to detect_format() for .brd extension, add parse case in parse_pcb_file().

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_allegro_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/parsers/allegro_parser.py src/mcp_pcb_emcopilot/parsers/__init__.py tests/test_allegro_parser.py tests/fixtures/sample_allegro_extract.txt
git commit -m "feat: add Allegro/OrCAD parser support (#25)"
```

### Task 14: Harden Altium Parser

**Files:**
- Modify: `src/mcp_pcb_emcopilot/parsers/altium_parser.py`
- Create: `tests/test_altium_parser_advanced.py`

- [ ] **Step 1: Write tests for missing Altium features**

Test: design rules extraction, differential pair detection, zone/pour data, multi-layer stackup.

- [ ] **Step 2: Add design rules extraction to Altium parser**

Parse Rules section from OLE stream for trace width, clearance, and impedance rules.

- [ ] **Step 3: Add zone/copper pour extraction**

Parse Fill and Region records.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_altium_parser*.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/parsers/altium_parser.py tests/test_altium_parser_advanced.py
git commit -m "feat: harden Altium parser with design rules and zone extraction"
```

---

## Chunk 6: Final Integration & Issue Closure

### Task 15: Run Full Test Suite & Fix Issues

- [ ] **Step 1: Run complete test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`

- [ ] **Step 2: Run ruff linting**

Run: `ruff check src/ tests/ --fix`

- [ ] **Step 3: Run mypy**

Run: `mypy src/mcp_pcb_emcopilot/ --ignore-missing-imports`

- [ ] **Step 4: Fix any failures**

- [ ] **Step 5: Final commit and push**

```bash
git add -A
git commit -m "fix: resolve linting and type errors across all modules"
git push origin main
```

### Task 16: Close GitHub Issues

- [ ] **Step 1: Close each completed issue**

```bash
gh issue close 16 -c "Comprehensive test coverage added for all 93 tools"
gh issue close 17 -c "Sample PCB designs added for KiCad, ODB++, Gerber, IPC-2581"
gh issue close 18 -c "Structured error handling and input validation added"
gh issue close 19 -c "CI/CD pipeline with GitHub Actions added"
gh issue close 20 -c "CONTRIBUTING.md and issue/PR templates added"
gh issue close 21 -c "Type hints and docstrings added to all public APIs"
gh issue close 22 -c "PyPI publishing configured with trusted publishing"
gh issue close 25 -c "Allegro/OrCAD parser support added"
```
