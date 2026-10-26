"""The app's own updates: the latest GitHub Release, the download of its installer and starting it (spec: the
installer built by scripts/build_installer.ps1 upgrades the installed KAPITA in place and keeps the data folder)."""

import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

from financial_app.domain.app_update import INSTALLER_ARGS, LatestRelease, UpdateError, parse_latest_release

LATEST_URL = "https://api.github.com/repos/Gerruppa/Financial-APP/releases/latest"


def fetch(url: str) -> bytes:
    """The body at ``url``; network failures and HTTP errors raise OSError."""
    request = urllib.request.Request(url, headers={"User-Agent": "KAPITA", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
        return body


def launch(command: list[str]) -> None:
    """Start ``command`` apart from this process, which exits right after so the installer can replace its files."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen(command, creationflags=flags, close_fds=True)  # noqa: S603 - a file this app just downloaded


class UpdateSource:
    def __init__(
        self,
        fetch: Callable[[str], bytes] = fetch,
        launch: Callable[[list[str]], None] = launch,
        can_install: bool = False,
    ) -> None:
        self.fetch = fetch
        self.launch = launch
        # Only the installed (frozen) app can be replaced by the installer; a source checkout just points to the page
        self.can_install = can_install

    @classmethod
    def real(cls) -> UpdateSource:
        return cls(can_install=bool(getattr(sys, "frozen", False)))

    def latest(self) -> LatestRelease:
        try:
            body = self.fetch(LATEST_URL)
        except OSError:
            raise UpdateError("Brak połączenia z GitHubem; nie sprawdzono, czy jest nowa wersja.") from None
        return parse_latest_release(body.decode("utf-8", errors="replace"))

    def download(self, release: LatestRelease, folder: Path) -> Path:
        """The installer of ``release`` saved in ``folder``; a file of the wrong size is removed."""
        try:
            data = self.fetch(release.installer_url)
        except OSError:
            raise UpdateError("Nie udało się pobrać instalatora; spróbuj ponownie.") from None
        if len(data) != release.size:
            raise UpdateError("Pobrany instalator jest uszkodzony; spróbuj ponownie.")
        path = folder / release.installer_url.rsplit("/", 1)[-1]
        path.write_bytes(data)
        return path

    def install(self, installer: Path) -> None:
        self.launch([str(installer), *INSTALLER_ARGS])
