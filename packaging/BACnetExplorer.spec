# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec - builds two single-file Windows programs:
#   dist\BasilBACnetExplorer.exe   (GUI, no console window, green logo)
#   dist\BasilBACnetSimulator.exe  (test device simulator, console)
# Run from the project folder:  python -m PyInstaller --noconfirm --clean packaging\BACnetExplorer.spec
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from graphics import BUILTIN  # noqa: E402

ICON = os.path.join(ROOT, "assets", "logo.ico")
VERSION = os.path.join(ROOT, "packaging", "version_info.txt")
APP_NAME = os.environ.get("BACNET_EXE_NAME", "BasilBACnetExplorer")

hidden = ["netconfig", "auth", "xlsx_export", "graphics", "graphics.base", "graphics.panel"] + \
         [f"graphics.{m}" for m in BUILTIN]
excludes = ["numpy", "pandas", "matplotlib", "PIL", "scipy", "IPython", "pytest", "test",
            "unittest", "pydoc_data", "lib2to3"]

app = Analysis(
    [os.path.join(ROOT, "bacnet_explorer.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "assets"), "assets"),
           (os.path.join(ROOT, "graphics", "README.md"), "graphics")],
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
app_pyz = PYZ(app.pure)
EXE(
    app_pyz, app.scripts, app.binaries, app.datas, [],
    name=APP_NAME,
    icon=ICON,
    version=VERSION,
    console=False,          # GUI program: no black console window
    upx=False,              # UPX-packed exes trigger more antivirus false positives
    debug=False,
    strip=False,
    runtime_tmpdir=None,
)

sim = Analysis(
    [os.path.join(ROOT, "bacnet_simulator.py")],
    pathex=[ROOT],
    excludes=excludes + ["tkinter", "_tkinter"],
)
sim_pyz = PYZ(sim.pure)
EXE(
    sim_pyz, sim.scripts, sim.binaries, sim.datas, [],
    name=APP_NAME.replace("Explorer", "Simulator"),
    icon=ICON,
    version=VERSION,
    console=True,
    upx=False,
)
