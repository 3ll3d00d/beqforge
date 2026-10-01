# -*- mode: python ; coding: utf-8 -*-
"""Native F2 preview; BEQFORGE_DEVICE_BUILD_MODE=onedir for initial diagnosis."""
import ctypes.util
import json
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from beqforge.record import BUILD_REVISION_FILE, revision
from beqforge_device_check.cli import provenance
from beqforge_device_check.evidence import atomic_json, file_hash
from tools.prepare_device_check_helper import host_target

root = Path(SPECPATH)
helper = Path(os.environ.get("BEQFORGE_DEVICE_HELPER_DIR", root / "build/device-helper"))
manifest = json.loads((helper / "helper.json").read_text())
name = "minidsp.exe" if os.name == "nt" else "minidsp"
if manifest["target"] != host_target() or file_hash(helper / name) != manifest["binary_sha256"]:
    raise ValueError("helper target/hash mismatch; prepare it on this build host")
if os.name == "posix" and host_target().startswith("linux") and not ctypes.util.find_library("portaudio"):
    raise ValueError("Linux preview requires a discoverable PortAudio library")
work = Path(workpath)
work.mkdir(parents=True, exist_ok=True)
stamp = work / BUILD_REVISION_FILE
stamp.write_text(revision())
atomic_json(work / "build.json", {"target": host_target(), "preview": True, **provenance()})
# PyInstaller retains the basename, so use a distinct directory for the second stamp.
device_stamp = work / "device-stamp" / "BUILD_REVISION"
device_stamp.parent.mkdir(exist_ok=True)
device_stamp.write_text(provenance()["implementation"])
datas = [(str(stamp), "beqforge"), (str(device_stamp), "beqforge_device_check")]
datas += [(str(helper / "helper.json"), "helpers"), (str(helper / "minidsp-LICENSE.txt"), "helpers"),
          (str(root / "packaging/device-check/NOTICE.txt"), "."), (str(work / "build.json"), "."),
          (str(root / "docs/device-check.md"), "docs")]
if (helper / "native-notices").is_dir():
    datas += [(str(p), "helpers/native-notices") for p in (helper / "native-notices").iterdir()]
for package in ("pyfar", "sofar"):
    datas += collect_data_files(package)
for distribution in ("numpy", "scipy", "matplotlib", "pyfar", "sounddevice", "websocket-client"):
    datas += copy_metadata(distribution, recursive=True)
a = Analysis([str(root / "beqforge_device_check/cli.py")], pathex=[str(root)],
             binaries=[(str(helper / name), "helpers")], datas=datas,
             hiddenimports=["_cffi_backend", "sounddevice", "websocket", "pyfar"],
             excludes=["pytest", "tests", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
mode = os.environ.get("BEQFORGE_DEVICE_BUILD_MODE", "onefile")
if mode not in ("onefile", "onedir"):
    raise ValueError("build mode must be onefile or onedir")
if mode == "onedir":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="beqforge-device-check",
              console=True, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="beqforge-device-check", upx=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="beqforge-device-check",
              console=True, upx=False)
