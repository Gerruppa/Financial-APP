"""The update notice under the version label: shown for a newer Release only, and the install starts the installer."""

from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.app_update import UpdateError
from financial_app.persistence.db import init_db
from financial_app.sources.app_update import UpdateSource
from financial_app.ui.shell import build_shell

URL = "https://github.com/Gerruppa/Financial-APP/releases/download/v9.0.0/KAPITA-9.0.0-setup.exe"


def _latest(version: str) -> bytes:
    name = f"KAPITA-{version}-setup.exe"
    return (
        f'{{"tag_name": "v{version}", "assets": [{{"name": "{name}", "size": 3, '
        f'"browser_download_url": "{URL.replace("9.0.0", version)}"}}]}}'
    ).encode()


def _source(version: str, launched: list[list[str]], can_install: bool = True) -> UpdateSource:
    def fetch(url: str) -> bytes:
        return _latest(version) if "api.github.com" in url else b"abc"

    return UpdateSource(fetch=fetch, launch=launched.append, can_install=can_install)


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("financial_app.ui.app_update.CHECK_DELAY", 0.0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


async def test_a_newer_release_shows_the_notice(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, updates=_source("9.0.0", []))) as user:
        await user.open("/")
        await user.should_see("Dostępna wersja 9.0.0")


async def test_the_same_or_an_older_release_shows_nothing(engine: Engine) -> None:
    from financial_app import __version__

    async with user_simulation(lambda: build_shell(engine, updates=_source(__version__, []))) as user:
        await user.open("/")
        await user.should_not_see("Dostępna wersja")


async def test_a_failed_check_stays_silent(engine: Engine) -> None:
    def fetch(url: str) -> bytes:
        raise OSError("offline")

    source = UpdateSource(fetch=fetch)
    with pytest.raises(UpdateError):
        source.latest()
    async with user_simulation(lambda: build_shell(engine, updates=source)) as user:
        await user.open("/")
        await user.should_not_see("Dostępna wersja")


async def test_installing_downloads_and_starts_the_installer(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr("financial_app.ui.app_update.app.shutdown", lambda: None)
    async with user_simulation(lambda: build_shell(engine, updates=_source("9.0.0", launched))) as user:
        await user.open("/")
        await user.should_see("Dostępna wersja 9.0.0")
        user.find(marker="update-available").click()
        user.find(marker="update-install").click()
        await user.should_see("Uruchamianie instalatora…")

    [[installer, *args]] = launched
    assert installer.endswith("KAPITA-9.0.0-setup.exe")
    assert "/SILENT" in args


async def test_a_source_checkout_only_points_to_the_release_page(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, updates=_source("9.0.0", [], can_install=False))) as user:
        await user.open("/")
        await user.should_see("Dostępna wersja 9.0.0")
        user.find(marker="update-available").click()
        await user.should_see(marker="update-page")
        await user.should_not_see(marker="update-install")
