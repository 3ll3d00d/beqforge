"""The three workflows share primitives, never import each other's implementations."""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {"beqforge", "beqforge_device_check", "beqoptimiser"}


@pytest.mark.parametrize("package", sorted(WORKFLOWS | {"beq_common"}))
def test_workflow_import_boundaries(package):
    forbidden = WORKFLOWS - {package}
    for path in (ROOT / package).glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            assert not any(name.split(".")[0] in forbidden for name in imported), path


@pytest.mark.parametrize(
    "package,module",
    [
        ("beqforge", "beqforge.pipeline"),
        ("beqforge_device_check", "beqforge_device_check.cli"),
        ("beqoptimiser", "beqoptimiser.cli"),
    ],
)
def test_workflow_imports_with_siblings_unavailable(package, module):
    # Includes lazy imports in provenance, beyond the static dependency check above.
    code = """
import importlib, importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in FORBIDDEN:
            raise AssertionError('cross-workflow import: ' + fullname)
sys.meta_path.insert(0, Block())
m = importlib.import_module(MODULE)
if hasattr(m, 'provenance'):
    m.provenance()
""".replace("FORBIDDEN", repr(WORKFLOWS - {package})).replace("MODULE", repr(module))
    subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True
    )


def test_one_distribution_with_profiles_and_commands():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = config["project"]
    assert project["name"] == "beqforge"
    assert set(project["scripts"]) == {
        "beqforge",
        "beqforge-device-check",
        "beqoptimiser",
    }
    extras = project["optional-dependencies"]
    assert set(extras) == {"designer", "device-check", "optimiser", "all"}
    assert not any("matplotlib" in d or "sounddevice" in d for d in extras["optimiser"])
    assert not any("ruff" in d or "stubs" in d for d in project["dependencies"])
    assert not list(ROOT.glob("packages/**/pyproject.toml"))
