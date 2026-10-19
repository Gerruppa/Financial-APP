"""Generate the next migration from the models: .venv/Scripts/python.exe scripts/new_migration.py "add term deposits"

The alembic CLI reads the user's real database, which lags behind main until the app has run, and then autogenerate
fails with "Target database is not up to date". This script upgrades a scratch database to head instead, so the new
revision holds only the model changes, and numbers it after the newest one (0036 -> 0037). ruff fixes and formats the
file (alembic.ini post_write_hooks).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "src" / "financial_app" / "persistence" / "migrations" / "versions"


def next_revision() -> str:
    numbers = [int(path.name[:4]) for path in VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py")]
    return f"{max(numbers, default=0) + 1:04d}"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    alembic = [sys.executable, "-m", "alembic"]
    with tempfile.TemporaryDirectory() as scratch:
        env = {**os.environ, "FINANCIAL_APP_DATA_DIR": scratch}
        subprocess.run([*alembic, "upgrade", "head"], env=env, check=True)
        revision = [*alembic, "revision", "--autogenerate", "--rev-id", next_revision(), "-m", sys.argv[1]]
        subprocess.run(revision, env=env, check=True)


if __name__ == "__main__":
    main()
