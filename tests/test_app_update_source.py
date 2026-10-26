"""The update source: asks GitHub for the latest Release, downloads the installer and starts it."""

from collections.abc import Callable
from pathlib import Path

import pytest

from financial_app.domain.app_update import INSTALLER_ARGS, LatestRelease, UpdateError
from financial_app.sources.app_update import UpdateSource

URL = "https://github.com/Gerruppa/Financial-APP/releases/download/v1.2.0/KAPITA-1.2.0-setup.exe"
LATEST = (
    '{"tag_name": "v1.2.0", "assets": [{"name": "KAPITA-1.2.0-setup.exe", "size": 5, '
    f'"browser_download_url": "{URL}"}}]}}'
)


def _source(fetch: Callable[[str], bytes], launched: list[list[str]] | None = None) -> UpdateSource:
    return UpdateSource(fetch=fetch, launch=(launched.append if launched is not None else lambda args: None))


def test_it_reads_the_latest_release() -> None:
    source = _source(lambda url: LATEST.encode())

    assert source.latest().version == "1.2.0"


def test_a_network_failure_is_an_update_error() -> None:
    def fetch(url: str) -> bytes:
        raise OSError("offline")

    with pytest.raises(UpdateError, match="połączenia"):
        _source(fetch).latest()


def test_it_downloads_the_installer_into_the_folder(tmp_path: Path) -> None:
    source = _source(lambda url: b"12345")

    path = source.download(LatestRelease("1.2.0", URL, 5), tmp_path)

    assert path == tmp_path / "KAPITA-1.2.0-setup.exe"
    assert path.read_bytes() == b"12345"


def test_a_download_of_the_wrong_size_is_refused_and_removed(tmp_path: Path) -> None:
    source = _source(lambda url: b"123")

    with pytest.raises(UpdateError, match="uszkodzony"):
        source.download(LatestRelease("1.2.0", URL, 5), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_it_starts_the_installer_silently(tmp_path: Path) -> None:
    launched: list[list[str]] = []
    source = _source(lambda url: b"", launched)

    source.install(tmp_path / "setup.exe")

    assert launched == [[str(tmp_path / "setup.exe"), *INSTALLER_ARGS]]
