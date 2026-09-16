# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the `beqforge` CLI — one onefile executable covering every subcommand
(design, extract, replay, summarise, ledger, validate, serve-designer).

`beqforge/cli.py` dispatches to `tools/*.py` by `importlib.import_module(name)` with `name` a
runtime string (`beqforge/cli.py`'s `_SUBCOMMANDS`), which PyInstaller's static import scanner
cannot follow — every one of those modules has to be named as a hidden import explicitly or the
built executable silently fails at `beqforge <subcommand>` with "no module named tools.X". Read
directly off `_SUBCOMMANDS` rather than hand-duplicated here, so it can't drift out of sync with
what `cli.py` actually dispatches to.

Build: `uv run pyinstaller beqforge.spec` (needs `uv pip install pyinstaller` first — it is not
a project dependency, only a build-time tool). `.github/workflows/build-executable.yml` runs
this on Linux/macOS/Windows and smoke-tests the result with `tools/smoke_test_exe.py`.

`ffmpeg` remains an external, unbundled runtime dependency of `beqforge extract` on every
platform — same as an unpackaged `uv run` install, not something PyInstaller bundles.
"""

from beqforge.cli import _SUBCOMMANDS

a = Analysis(
    ["beqforge/cli.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=list(_SUBCOMMANDS.values()),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="beqforge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed executables trigger more antivirus false positives on Windows
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
