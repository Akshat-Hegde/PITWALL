# PyInstaller spec: one-folder build of the hub with the prebuilt TV dashboard.
# Build with packaging/build.ps1 (it runs `npm run build` first).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "hub" / "simtelemetry"
sys.path.insert(0, str(ROOT / "hub"))
from simtelemetry import __version__, brand  # noqa: E402  (the exe and folder names come from brand.py)
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,  # noqa: E402
                                                 StringTable, VarFileInfo, VarStruct, VSVersionInfo)

# Windows file details (Properties > Details): product and version only. No company or copyright: one program build
# serves every variant, and an unbranded cafe's Pitwall.exe must not name 9T7 Racing (Decision 8.8, 2026-11-03). The
# 9T7 installer's publisher still comes from the Vendor define in pitwall.iss.
_nums = tuple(int(n) for n in (__version__.split(".") + ["0", "0", "0"])[:4])
VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", f"{brand.PRODUCT_NAME} hub"),
            StringStruct("FileVersion", __version__),
            StringStruct("InternalName", brand.EXE_NAME),
            StringStruct("OriginalFilename", f"{brand.EXE_NAME}.exe"),
            StringStruct("ProductName", brand.PRODUCT_NAME),
            StringStruct("ProductVersion", __version__),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

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
    excludes=["pytest", "tkinter", "factory"],          # factory/: the seller's tools, never shipped to cafes
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=brand.EXE_NAME, console=True,
          icon=str(ROOT / "packaging" / "pitwall.ico"), version=VERSION_INFO)
coll = COLLECT(exe, a.binaries, a.datas, name=brand.EXE_NAME)
