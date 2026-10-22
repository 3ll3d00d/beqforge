"""The designer image's recipe, and its smoke check run against an in-process server.

The image itself is built and smoke-tested by `.github/workflows/build-designer-image.yml`;
these keep the recipe and the check honest without Docker.
"""

import importlib.util
import threading
from pathlib import Path

import pytest

from beqforge.pipeline import PipelineParams
from tools.designer_server import DesignServer, DesignSettings

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "packaging" / "designer" / "Dockerfile"


def _load_smoke():
    """packaging/designer/smoke.py by path: `packaging/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "beqforge_designer_smoke", ROOT / "packaging" / "designer" / "smoke.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()


def test_the_image_serves_the_designer_with_references_and_a_cache_by_default():
    recipe = DOCKERFILE.read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev --extra designer --no-editable" in recipe
    assert 'ENTRYPOINT ["beqforge", "serve-designer"]' in recipe
    for setting in (
        "BEQFORGE_HOST=0.0.0.0",
        "BEQFORGE_PORT=8420",
        "BEQFORGE_SHARED_ROOT=/work",
        "BEQFORGE_CACHE_DIR=/cache",
        "BEQFORGE_RECORD_DIR=/records",
        "BEQFORGE_LOG_FILE=false",
    ):
        assert setting in recipe
    assert 'VOLUME ["/cache", "/records"]' in recipe
    assert "USER beqforge" in recipe and "HEALTHCHECK" in recipe


def test_the_image_copies_every_package_the_wheel_includes():
    """`--no-editable` builds the wheel inside the image: a package left out fails the build."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    recipe = DOCKERFILE.read_text(encoding="utf-8")
    for package in config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]:
        assert f"COPY {package} {package}" in recipe


def test_the_smoke_digest_is_the_designers_own_arithmetic(tmp_path):
    from beqforge.reference import digest, read_column

    pcm = smoke.samples(seconds=1)
    smoke.write_wav(tmp_path / "mono.wav", pcm)
    column = read_column(tmp_path / "mono.wav", 0, smoke.FS, "mono_mix")
    assert (
        digest(column) == smoke.reference_request("mono.wav", pcm)["mono_mix"]["sha256"]
    )


@pytest.fixture
def server(tmp_path):
    """What the image runs: the designer with a shared root, here in-process."""
    httpd = DesignServer(
        ("127.0.0.1", 0),
        DesignSettings(
            PipelineParams(strategies=("flatten",), max_sections=1),
            shared_root=tmp_path.resolve(),
        ),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()


def test_the_smoke_check_passes_against_a_real_designer(server):
    base, work = server
    smoke.check(base, work)
    assert (work / "smoke" / "mono.wav").is_file()
