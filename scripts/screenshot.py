"""Screenshot tabs of the demo app: .venv/Scripts/python.exe scripts/screenshot.py dashboard portfolio --out <dir>

Starts `main.py --demo` (made-up data in a fresh TEMP database, never the user's) on a free port, shoots each tab
with headless Chrome or Edge into <dir>/<tab>.png and stops the app. A tab is its route without the slash
(`transakcje`, `ustawienia`; `dashboard` is /), since Git Bash turns a leading slash into a Windows path. --width
and --height set the viewport (default 1400x900, the native window's size); --theme golden shoots the Golden Theme.
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from financial_app.domain.themes import Theme

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]
# NiceGUI renders in the browser, so the shot waits this long (virtual time) for the page to settle
RENDER_MS = 8000


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_up(url: str, app: subprocess.Popen[bytes], seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if app.poll() is not None:
            sys.exit(f"main.py --demo stopped with exit code {app.returncode}")
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.5)
    sys.exit(f"{url} did not answer within {seconds:.0f} s")


def choose_theme(theme: str, discreet: bool = False) -> None:
    """Remember ``theme`` (and the discreet mode) in the demo database, as the window would; each page then builds in
    it."""
    from financial_app.app import demo_dir
    from financial_app.persistence.db import open_engine
    from financial_app.persistence.paths import DATA_DIR_ENV, database_path
    from financial_app.persistence.settings import UI_DISCREET, UI_THEME, save_setting

    os.environ[DATA_DIR_ENV] = str(demo_dir())
    engine = open_engine(database_path())
    save_setting(engine, UI_THEME, theme)
    save_setting(engine, UI_DISCREET, "1" if discreet else "0")
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tabs", nargs="*", default=["dashboard"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--theme", choices=[theme.value for theme in Theme], default=Theme.LIGHT.value)
    parser.add_argument("--discreet", action="store_true", help="shoot with the discreet mode on (amounts blurred)")
    args = parser.parse_args()
    browser = next((path for path in BROWSERS if path.exists()), None)
    if browser is None:
        sys.exit("Neither Chrome nor Edge is installed at " + ", ".join(map(str, BROWSERS)))
    args.out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--demo", "--port", str(port)], cwd=ROOT)
    try:
        wait_until_up(f"http://127.0.0.1:{port}/", app)
        choose_theme(args.theme, args.discreet)
        for tab in args.tabs:
            name = tab.strip("/") or "dashboard"
            route = "/" if name == "dashboard" else f"/{name}"
            target = args.out / f"{name.replace('/', '_')}.png"
            shot = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={args.width},{args.height}",
                f"--virtual-time-budget={RENDER_MS}",
                f"--user-data-dir={args.out / '.browser-profile'}",
                f"--screenshot={target}",
                f"http://127.0.0.1:{port}{route}",
            ]
            subprocess.run(shot, check=True, capture_output=True)
            print(target)
    finally:
        app.terminate()
        app.wait()


if __name__ == "__main__":
    main()
