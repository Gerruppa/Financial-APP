# PyInstaller recipe for KAPITA.exe; scripts/build_installer.ps1 runs it, then packaging/kapita.iss.
# A folder build (not one file): it starts faster and Inno Setup installs the folder as it is.
from pathlib import Path

import nicegui

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "src" / "financial_app"

datas = [
    # NiceGUI serves its JavaScript and CSS from its package folder
    (str(Path(nicegui.__file__).parent), "nicegui"),
    # Alembic reads the migrations as files, not through imports
    (str(PACKAGE / "persistence" / "migrations"), "financial_app/persistence/migrations"),
    # The icons and the PDF report's DejaVu Sans fonts (assets/fonts), which the Polish letters need
    (str(PACKAGE / "ui" / "assets"), "financial_app/ui/assets"),
]
datas += [(str(path), "financial_app/ui") for path in (PACKAGE / "ui").glob("*.md")]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    # reportlab reads its settings module by name, and imports PIL (pillow) at start-up, so PIL stays in
    hiddenimports=["reportlab.rl_settings"],
    excludes=["pytest", "mypy", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KAPITA",
    console=False,
    icon=str(PACKAGE / "ui" / "assets" / "kapita.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="KAPITA")
