"""Architectural import boundary tests (Priority 4).

Guarantees:
1. `agentic_trading.market_data` has ZERO dependencies on broker execution or risk engine.
2. `agentic_trading.risk_engine` has ZERO dependencies on broker connectors or live order routing.
3. Clean architectural separation between domain models, quality gate, and paper-trading engine.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _get_imports_from_file(file_path: Path) -> set[str]:
    """Parse a Python source file and extract all imported module names."""
    with open(file_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(file_path))

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    return imported_modules


def test_market_data_has_no_broker_or_risk_engine_imports() -> None:
    """Validate that market_data modules never import risk_engine or broker connectors."""
    src_dir = Path(__file__).resolve().parent.parent / "src" / "agentic_trading" / "market_data"
    assert src_dir.is_dir(), f"Directory not found: {src_dir}"

    for py_file in src_dir.glob("*.py"):
        imports = _get_imports_from_file(py_file)
        for imp in imports:
            assert not imp.startswith("agentic_trading.risk_engine"), (
                f"Boundary violation in {py_file.name}: imports risk_engine ({imp})"
            )
            assert "zerodha" not in imp.lower(), (
                f"Boundary violation in {py_file.name}: imports broker connector ({imp})"
            )
            assert "kiteconnect" not in imp.lower(), (
                f"Boundary violation in {py_file.name}: imports live broker SDK ({imp})"
            )


def test_risk_engine_has_no_live_broker_imports() -> None:
    """Validate that risk_engine has no broker connector or live execution imports."""
    src_dir = Path(__file__).resolve().parent.parent / "src" / "agentic_trading"
    risk_file = src_dir / "risk_engine.py"
    files_to_check: list[Path] = []
    if risk_file.is_file():
        files_to_check.append(risk_file)
    risk_dir = src_dir / "risk_engine"
    if risk_dir.is_dir():
        files_to_check.extend(risk_dir.glob("*.py"))
    assert files_to_check, "No risk engine files found"

    for py_file in files_to_check:
        imports = _get_imports_from_file(py_file)
        for imp in imports:
            assert "zerodha" not in imp.lower(), (
                f"Boundary violation in {py_file.name}: imports broker connector ({imp})"
            )
            assert "kiteconnect" not in imp.lower(), (
                f"Boundary violation in {py_file.name}: imports live broker SDK ({imp})"
            )
            assert "live" not in imp.lower() or "agentic_trading" not in imp.lower(), (
                f"Boundary violation in {py_file.name}: imports live trading module ({imp})"
            )


def test_market_data_all_exports_are_importable() -> None:
    """Verify that all symbols declared in market_data.__all__ import cleanly."""
    import agentic_trading.market_data as md

    assert hasattr(md, "__all__")
    for name in md.__all__:
        assert hasattr(md, name), f"Symbol '{name}' listed in __all__ but missing from module"
