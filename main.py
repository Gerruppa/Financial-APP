"""Start the app: .venv/Scripts/python.exe main.py (also the script PyInstaller freezes into KAPITA.exe)"""

import multiprocessing

from financial_app.app import main

if __name__ == "__main__":
    # The frozen KAPITA.exe opens its native window in a spawned copy of itself, which must stop here
    multiprocessing.freeze_support()
    main()
