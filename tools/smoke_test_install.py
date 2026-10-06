"""Build-independent wheel/profile check in a fresh environment; stdlib only."""

import argparse
import json
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

PROFILES = ("base", "designer", "optimiser", "device-check", "all")
COMMANDS = {
    "base": [("beqforge", "--help")],
    "designer": [("beqforge", "design", "--help")],
    "optimiser": [("beqoptimiser", "--help")],
    "device-check": [("beqforge-device-check", "--help")],
    "all": [
        ("beqforge", "design", "--help"),
        ("beqoptimiser", "--help"),
        ("beqforge-device-check", "--help"),
    ],
}


def run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def check(wheel: Path, profile: str, lockfile: Path, offline: bool = False) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for package in (
            "beq_common",
            "beqforge",
            "beqforge_device_check",
            "beqoptimiser",
        ):
            if not any(name.startswith(package + "/") for name in names):
                raise ValueError(f"wheel omits {package}")
    with tempfile.TemporaryDirectory(prefix=f"beqforge-{profile}-") as directory:
        root = Path(directory)
        env = root / "env"
        run(["uv", "venv", "--python", sys.executable, str(env)], root)
        bin_dir = env / ("Scripts" if sys.platform == "win32" else "bin")
        python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
        constraints = root / "constraints.txt"
        lock = tomllib.loads(lockfile.read_text())
        constraints.write_text(
            "".join(
                f"{p['name']}=={p['version']}\n"
                for p in lock["package"]
                if "registry" in p["source"]
            )
        )
        requirement = str(wheel) + (f"[{profile}]" if profile != "base" else "")
        command = [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--constraint",
            str(constraints),
        ]
        if offline:
            command.append("--offline")
        run([*command, requirement], root)
        for name, *args in COMMANDS[profile]:
            executable = bin_dir / (name + (".exe" if sys.platform == "win32" else ""))
            run([str(executable), *args], root)
        code = """
import importlib.metadata, importlib.util, json
names = ['numpy','scipy','matplotlib','pyfar','sounddevice','websocket','ruff']
print(json.dumps({n: importlib.util.find_spec(n) is not None for n in names}))
"""
        installed = json.loads(run([str(python), "-c", code], root))
        if installed["ruff"]:
            raise ValueError("development tooling leaked into runtime profile")
        if profile in ("base", "optimiser") and any(
            installed[n] for n in ("matplotlib", "pyfar", "sounddevice", "websocket")
        ):
            raise ValueError(
                "plotting or measurement dependencies leaked into numerical profile"
            )
        if profile == "base" and installed["scipy"]:
            raise ValueError("SciPy leaked into base profile")
        if profile in ("optimiser", "all"):
            run(
                [
                    str(python),
                    "-c",
                    """
from beqoptimiser import Section, optimise
for rate,q in [(48000,2),(96000,.7)]:
    result=optimise([Section('PeakingEQ',10,q,12).sos(rate)],rate=rate)
    assert result.replacement and result.candidate_error_db < .5
""",
                ],
                root,
            )
        return installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--lockfile", type=Path, default=Path("uv.lock"))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    wheels = list(args.wheel_dir.glob("beqforge-*.whl"))
    if len(wheels) != 1:
        parser.error("wheel directory must contain exactly one beqforge wheel")
    result = check(
        wheels[0].resolve(), args.profile, args.lockfile.resolve(), args.offline
    )
    print(json.dumps({"profile": args.profile, "passed": True, "dependencies": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
