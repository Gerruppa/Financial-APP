"""Click through KAPITA end to end in a real browser: .venv/Scripts/python.exe scripts/smoke_test.py --out <dir>

Starts `main.py --demo` (made-up data in a fresh TEMP database, never the user's) on a free port and drives it with
Playwright in the installed Chrome (else Edge), so no browser is downloaded: every tab in both Themes, the side menu,
the Dashboard's periods and switches, the header search, a Deposit and a Buy from the amount to spend through the "+"
dialog, editing and deleting it, the exports and the PDF report, every Ustawienia tab, the Strategy's planned
deposit, the View Scope switch and the discreet mode. Each check prints PASS or FAIL and the run goes on; a failed one
leaves a screenshot in <dir>. At the end it lists the browser's console errors and the server log's errors, and exits
with 1 when anything failed. The user_simulation tests cover the logic; this checks the real page, its JavaScript and
the downloads.
"""

import argparse
import re
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TABS = (
    ("/", "Dashboard"),
    ("/wyniki", "Wyniki"),
    ("/portfolio", "Portfolio"),
    ("/transakcje", "Transakcje"),
    ("/strategie", "Strategie inwestycyjne"),
    ("/obligacje", "Dochód stały"),
    ("/multi-asset", "Multi-asset"),
    ("/benchmarki", "Benchmarki"),
    ("/sprzedaz", "Podsumowanie sprzedaży"),
    ("/dochod-pasywny", "Dochód pasywny"),
    ("/ustawienia", "Ustawienia"),
    ("/pomoc", "Pomoc"),
)
SETTINGS_TABS = ("Konta", "Limity i reguły", "Klasy aktywów", "Instrumenty", "Import", "Wygląd i widoczność")
# Windows' asyncio reports a browser closing its connection this way; it is not the app's error
LOG_NOISE = re.compile(r"ConnectionResetError")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def start_demo(port: int, log: Path) -> subprocess.Popen[bytes]:
    with log.open("wb") as output:
        app = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py"), "--demo", "--port", str(port)],
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    for _ in range(120):
        if app.poll() is not None:
            sys.exit(f"The demo app stopped at start; see {log}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            return app
        except OSError:
            time.sleep(0.5)
    app.terminate()
    sys.exit(f"The demo app did not answer within a minute; see {log}")


def launch(playwright: Playwright) -> Browser:
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(channel=channel, headless=True)
        except Exception:  # noqa: BLE001 - try the next installed browser
            continue
    sys.exit("Neither Chrome nor Edge is installed for Playwright to drive")


class Run:
    """The checks of one run against the demo app at ``base``, their results and the page's console errors."""

    def __init__(self, page: Page, base: str, out: Path) -> None:
        self.page = page
        self.base = base
        self.out = out
        self.results: list[tuple[str, str]] = []  # (name, "" when it passed, else the error)
        self.console: list[str] = []
        page.on("console", lambda m: m.type == "error" and self.console.append(f"{page.url}: {m.text[:300]}"))
        page.on("pageerror", lambda e: self.console.append(f"{page.url}: {str(e)[:300]}"))

    def check(self, name: str, steps: Callable[[], None]) -> None:
        try:
            steps()
        except Exception as error:  # noqa: BLE001 - a smoke test reports every failure and goes on
            message = f"{type(error).__name__}: {str(error).splitlines()[0][:300]}"
            self.results.append((name, message))
            print(f"FAIL  {name}: {message}", flush=True)
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            try:
                self.page.screenshot(path=str(self.out / f"FAIL-{slug}.png"))
            except Exception:  # noqa: BLE001 - the screenshot only helps, the failure is already recorded
                pass
        else:
            self.results.append((name, ""))
            print(f"PASS  {name}", flush=True)

    # Helpers on the open page

    def open(self, route: str, settle_ms: int = 1200) -> None:
        self.page.goto(self.base + route)
        self.page.wait_for_timeout(settle_ms)

    def dialog(self):  # type: ignore[no-untyped-def]
        return self.page.locator(".q-dialog").last

    def choose(self, label: str, option: str) -> None:
        """Pick ``option`` in the open dialog's select labelled ``label``."""
        self.dialog().locator("label.q-field", has_text=label).first.click()
        self.page.get_by_role("option", name=option, exact=True).first.click()
        self.page.wait_for_timeout(500)

    def field(self, label: str):  # type: ignore[no-untyped-def]
        return self.dialog().get_by_label(label, exact=True)

    def download(self, route: str, button: str) -> Path:
        self.open(route, 3000)
        with self.page.expect_download(timeout=60000) as started:
            self.page.get_by_role("button", name=button).click()
        target = self.out / started.value.suggested_filename
        started.value.save_as(target)
        assert target.stat().st_size > 0, f"{target.name} is empty"
        return target


def checks(run: Run, theme: str) -> None:
    """Every tab, then (in Jasny) the flows."""
    page = run.page
    for route, title in TABS:

        def tab(route: str = route, title: str = title) -> None:
            page.goto(run.base + route)
            expect(page.get_by_text(title, exact=True).first).to_be_visible(timeout=15000)
            page.wait_for_timeout(1000)
            name = route.strip("/") or "dashboard"
            page.screenshot(path=str(run.out / f"{theme}-{name}.png"), full_page=True)

        run.check(f"{theme}: tab {route} opens", tab)
    if theme != "jasny":
        return

    def menu() -> None:
        run.open("/", 3000)
        for name, route in (("Portfolio", "/portfolio"), ("Transakcje", "/transakcje")):
            page.locator(".k-side").get_by_role("button", name=name, exact=True).click()
            expect(page).to_have_url(re.compile(f"{route}$"), timeout=10000)

    run.check("side menu goes to Portfolio and Transakcje", menu)

    def periods() -> None:
        run.open("/")
        for preset in ("1R", "YTD", "Od początku"):
            page.get_by_role("button", name=preset, exact=True).first.click()
            page.wait_for_timeout(600)
        page.get_by_role("button", name="Tabela").click()
        page.wait_for_timeout(600)
        page.get_by_role("button", name="Karty").click()

    run.check("Dashboard: periods and Karty/Tabela", periods)

    def after_tax() -> None:
        run.open("/")
        page.get_by_text("Po podatku", exact=True).click()
        expect(page.get_by_text("Szacowany podatek i opłaty").first).to_be_visible(timeout=20000)
        page.get_by_text("Po podatku", exact=True).click()

    run.check("Dashboard: 'Po podatku' shows the estimated tax", after_tax)

    def search() -> None:
        run.open("/portfolio")
        box = page.get_by_placeholder(re.compile("Szukaj"))
        box.fill("DEMO")
        expect(page.get_by_text("DEMO Akcje PL").last).to_be_visible(timeout=20000)
        box.fill("")

    run.check("header search finds an Instrument", search)

    def deposit() -> None:
        run.open("/transakcje")
        page.get_by_role("button", name="Dodaj transakcję").click()
        run.choose("Konto", "Konto maklerskie")
        run.choose("Typ", "Wpłata")
        run.field("Kwota (zł)").fill("500")
        run.dialog().get_by_role("button", name="Zapisz", exact=True).click()
        expect(page.get_by_text("+500,00 zł").first).to_be_visible(timeout=20000)

    run.check("'+': a Deposit of 500 zł", deposit)

    def buy() -> None:
        run.open("/transakcje")
        page.get_by_role("button", name="Dodaj transakcję").click()
        run.choose("Konto", "Konto maklerskie")
        run.choose("Typ", "Zakup")
        run.choose("Instrument", "DEMO Akcje PL")
        run.field("Kwota do wydania (zł)").fill("1000")
        run.field("Liczba").fill("10")
        expect(run.field("Cena (zł)")).to_have_value("100,00", timeout=20000)
        run.dialog().get_by_role("button", name="Zapisz", exact=True).click()
        expect(page.get_by_text("10 × 100,00 zł").first).to_be_visible(timeout=20000)

    run.check("'+': a Buy of 1000 zł for 10 units proposes the price 100,00", buy)

    def edit() -> None:
        page.get_by_text("10 × 100,00 zł").first.click()
        expect(page.get_by_text("Edytuj transakcję").first).to_be_visible(timeout=20000)
        run.field("Komentarz").fill("smoke test")
        run.dialog().get_by_role("button", name="Zapisz zmiany").click()
        expect(page.get_by_text("smoke test").first).to_be_visible(timeout=20000)

    run.check("editing the Buy's comment", edit)

    def delete() -> None:
        page.get_by_text("smoke test").first.click()
        run.dialog().get_by_role("button", name=re.compile("^Usuń")).click()
        page.wait_for_timeout(1000)
        confirm = run.dialog().get_by_role("button", name=re.compile("^Usuń"))
        if confirm.count():
            confirm.first.click()
        expect(page.get_by_text("smoke test")).to_have_count(0, timeout=20000)
        expect(page.get_by_text(re.compile("Cofnij")).first).to_be_visible(timeout=20000)

    run.check("deleting the Buy offers 'Cofnij'", delete)

    for route, button in (
        ("/transakcje", "Eksportuj CSV"),
        ("/transakcje", "Eksportuj XLSX"),
        ("/portfolio", "Eksportuj XLSX"),
    ):

        def export(route: str = route, button: str = button) -> None:
            run.download(route, button)

        run.check(f"{route} '{button}' downloads a file", export)

    def report() -> None:
        target = run.download("/wyniki", "Raport roczny PDF")
        assert target.read_bytes()[:5] == b"%PDF-", "not a PDF"

    run.check("Wyniki: 'Raport roczny PDF' downloads a PDF", report)

    def settings() -> None:
        run.open("/ustawienia")
        for tab in SETTINGS_TABS:
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(700)
        page.get_by_role("tab", name="Konta").click()
        page.get_by_role("button", name="Dodaj konto").click()
        expect(run.dialog()).to_be_visible()
        run.dialog().get_by_role("button", name="Anuluj").click()

    run.check("Ustawienia: every tab and the Account dialog", settings)

    def strategy() -> None:
        run.open("/strategie")
        page.get_by_label("Planuję wpłacić").fill("1000")
        expect(page.get_by_text(re.compile(r"^Kup na:")).first).to_be_visible(timeout=20000)
        page.get_by_role("button", name="Edytuj cele klas").click()
        expect(run.dialog()).to_be_visible()
        run.dialog().get_by_role("button", name="Anuluj").click()

    run.check("Strategie: a planned deposit names where to buy; the targets dialog", strategy)

    def income_year() -> None:
        run.open("/dochod-pasywny")
        # The year between the arrows, not the export's year select
        shown = page.get_by_role("button", name="Poprzedni rok").locator("xpath=following-sibling::*[1]")
        year = int(shown.inner_text())
        page.get_by_role("button", name="Poprzedni rok").click()
        shown = page.get_by_role("button", name="Poprzedni rok").locator("xpath=following-sibling::*[1]")
        expect(shown).to_have_text(str(year - 1), timeout=20000)

    run.check("Dochód pasywny: the previous year", income_year)

    def scope() -> None:
        run.open("/")
        page.get_by_text("Total", exact=True).first.click()
        page.get_by_text("IKE", exact=True).last.click()
        page.wait_for_timeout(1500)
        page.get_by_text("IKE", exact=True).first.click()
        page.get_by_text("Total", exact=True).last.click()

    run.check("View Scope: Total -> IKE -> Total", scope)

    def discreet() -> None:
        run.open("/portfolio")
        eye = "header button:has(i:text-matches('visibility'))"
        page.locator(eye).first.click()
        page.wait_for_timeout(800)
        page.locator(eye).first.click()

    run.check("discreet mode on and off", discreet)


def server_errors(log: str) -> list[str]:
    """The log's errors, each traceback as its final line (the exception), less Windows' connection-closed noise."""
    errors: list[str] = []
    in_traceback = False
    for line in log.splitlines():
        if line.startswith("Traceback"):
            in_traceback = True
        elif in_traceback and line and not line.startswith((" ", "\t", "~", "^")):
            in_traceback = False  # the exception line that ends the traceback
            if not LOG_NOISE.search(line):
                errors.append(line)
        elif not in_traceback and re.search(r"\bERROR\b", line) and not LOG_NOISE.search(line):
            errors.append(line)
    return errors


def switch_theme(run: Run, label: str, body_class: str) -> None:
    run.open("/ustawienia")
    run.page.get_by_role("tab", name="Wygląd i widoczność").click()
    run.page.wait_for_timeout(800)
    run.page.get_by_text(label, exact=True).first.click()
    run.page.wait_for_timeout(3000)
    assert body_class in (run.page.locator("body").get_attribute("class") or ""), f"the body is not {body_class}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="folder for the screenshots, downloads and log")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    log = out / "demo.log"
    app = start_demo(port, log)
    try:
        with sync_playwright() as playwright:
            browser = launch(playwright)
            context = browser.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True)
            run = Run(context.new_page(), f"http://127.0.0.1:{port}", out)
            checks(run, "jasny")
            run.check("switching to the Golden Theme", lambda: switch_theme(run, "Golden", "theme-golden"))
            checks(run, "golden")
            run.check("switching back to Jasny", lambda: switch_theme(run, "Jasny", "theme-jasny"))
            browser.close()
    finally:
        app.terminate()
        app.wait()
    failed = [(name, error) for name, error in run.results if error]
    print(f"\n{len(run.results) - len(failed)} passed, {len(failed)} failed")
    for name, error in failed:
        print(f"  FAILED {name}: {error}")
    print(f"Browser console errors: {len(run.console)}")
    for line in run.console[:40]:
        print(f"  {line}")
    errors = server_errors(log.read_text(encoding="utf-8", errors="replace"))
    print(f"Server log errors: {len(errors)}")
    for line in errors[:40]:
        print(f"  {line[:300]}")
    sys.exit(1 if failed or run.console or errors else 0)


if __name__ == "__main__":
    main()
