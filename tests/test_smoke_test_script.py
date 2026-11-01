"""The smoke test's reading of the demo app's log (scripts/smoke_test.py): a real traceback counts, Windows' report of
a browser closing its connection does not."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("playwright")


def _script() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "smoke_test.py"
    spec = importlib.util.spec_from_file_location("smoke_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLOSED_CONNECTION = """Exception in callback _ProactorBasePipeTransport._call_connection_lost()
handle: <Handle _ProactorBasePipeTransport._call_connection_lost()>
Traceback (most recent call last):
  File "C:\\Python314\\Lib\\asyncio\\events.py", line 94, in _run
    self._context.run(self._callback, *self._args)
    ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host
"""
APP_ERROR = """Traceback (most recent call last):
  File "src/financial_app/ui/dashboard.py", line 10, in build
    total = 1 / 0
ZeroDivisionError: division by zero
"""


def test_a_closed_connection_is_noise_but_an_app_traceback_and_an_error_line_count() -> None:
    errors = _script().server_errors(CLOSED_CONNECTION + "NiceGUI ready to go\n" + APP_ERROR + "ERROR: bad price\n")

    assert errors == ["ZeroDivisionError: division by zero", "ERROR: bad price"]


def test_a_clean_log_has_no_errors() -> None:
    assert _script().server_errors(CLOSED_CONNECTION + "NiceGUI ready to go on http://127.0.0.1:8080\n") == []
