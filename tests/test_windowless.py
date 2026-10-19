"""The shortcut and KAPITA.exe start the app without a console: sys.stdout and sys.stderr are None, or os.devnull."""

import os
import sys
from pathlib import Path

import pytest

from financial_app.app import attach_log_when_windowless


def test_without_a_console_output_goes_to_a_log_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log_file = tmp_path / "logs" / "app.log"

    attach_log_when_windowless(log_file)
    assert sys.stdout is not None and sys.stderr is not None
    assert not sys.stdout.isatty()
    print("hello")
    sys.stderr.write("oops\n")
    sys.stdout.flush()
    sys.stderr.flush()

    assert log_file.read_text(encoding="utf-8").splitlines() == ["hello", "oops"]


def test_with_a_console_output_is_left_alone(tmp_path: Path) -> None:
    stdout, stderr = sys.stdout, sys.stderr

    attach_log_when_windowless(tmp_path / "app.log")

    assert (sys.stdout, sys.stderr) == (stdout, stderr)
    assert not (tmp_path / "app.log").exists()


def test_streams_pywebview_sent_to_devnull_go_to_the_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Importing pywebview (as NiceGUI does) swaps the missing streams for os.devnull before main() runs
    with open(os.devnull, "w") as stdout, open(os.devnull, "w") as stderr:
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        log_file = tmp_path / "app.log"

        attach_log_when_windowless(log_file)
        print("hello")
        sys.stdout.flush()

    assert log_file.read_text(encoding="utf-8").splitlines() == ["hello"]
