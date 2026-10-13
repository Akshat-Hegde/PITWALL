# PyInstaller spec: one-folder build of the hub with the prebuilt TV dashboard.
# Build with packaging/build.ps1 (it runs `npm run build` first).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "hub" / "simtelemetry"
sys.path.insert(0, str(ROOT / "hub"))
from simtelemetry import brand  # noqa: E402  (the exe and folder names come from brand.py)

a = Analysis(
    [str(ROOT / "packaging" / "pitwall_entry.py")],
    pathex=[str(ROOT / "hub")],
    datas=[
        (str(ROOT / "dashboard" / "dist"), "dashboard"),
        (str(PKG / "api" / "*.html"), "simtelemetry/api"),
        (str(PKG / "tracks"), "simtelemetry/tracks"),
    ],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
                   "python_multipart", "multipart"],
    excludes=["pytest", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=brand.EXE_NAME, console=True,
          icon=str(ROOT / "packaging" / "pitwall.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name=brand.EXE_NAME)
