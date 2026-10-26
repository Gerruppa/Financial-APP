"""The app's own update check: the latest GitHub Release read into the version and its installer."""

import json

import pytest

from financial_app.domain.app_update import UpdateError, newer_release, parse_latest_release

BASE = "https://github.com/Gerruppa/Financial-APP/releases/download/v1.2.0/"


def _release(**changes: object) -> str:
    data: dict[str, object] = {
        "tag_name": "v1.2.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "notes.txt", "browser_download_url": BASE + "notes.txt", "size": 10},
            {"name": "KAPITA-1.2.0-setup.exe", "browser_download_url": BASE + "KAPITA-1.2.0-setup.exe", "size": 4321},
        ],
    }
    data.update(changes)
    return json.dumps(data)


def test_the_release_gives_its_version_and_installer() -> None:
    release = parse_latest_release(_release())

    assert release.version == "1.2.0"
    assert release.installer_url == BASE + "KAPITA-1.2.0-setup.exe"
    assert release.size == 4321


def test_a_release_without_the_installer_is_an_error() -> None:
    with pytest.raises(UpdateError, match="instalator"):
        parse_latest_release(_release(assets=[]))


def test_an_installer_from_another_address_is_refused() -> None:
    assets = [{"name": "KAPITA-1.2.0-setup.exe", "browser_download_url": "https://evil.example/x.exe", "size": 1}]

    with pytest.raises(UpdateError):
        parse_latest_release(_release(assets=assets))


def test_a_tag_that_is_not_a_version_is_an_error() -> None:
    with pytest.raises(UpdateError):
        parse_latest_release(_release(tag_name="latest"))


def test_text_that_is_not_json_is_an_error() -> None:
    with pytest.raises(UpdateError):
        parse_latest_release("<html>")


def test_only_a_newer_release_is_offered() -> None:
    release = parse_latest_release(_release())

    assert newer_release(release, "1.1.1") is release
    assert newer_release(release, "1.2.0") is None
    assert newer_release(release, "1.3.0") is None
