"""ADR-0001: the domain core must not depend on the UI or the database."""

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
FORBIDDEN = ("nicegui", "sqlalchemy", "alembic", "webview")

# Imports every module of financial_app.domain in a fresh interpreter, then lists forbidden top-level packages loaded
PROBE = f"""
import importlib, pkgutil, sys
import financial_app.domain as domain
for module in pkgutil.walk_packages(domain.__path__, "financial_app.domain."):
    importlib.import_module(module.name)
print(sorted({{name.split(".")[0] for name in sys.modules}} & set({FORBIDDEN!r})))
"""


def test_domain_package_imports_neither_ui_nor_database() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    assert result.stdout.strip() == "[]"
