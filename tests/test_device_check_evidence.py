import hashlib
import json
import zipfile

import numpy as np
import pytest

from beqforge_device_check.evidence import (
    atomic_arrays,
    atomic_json,
    bundle,
    import_bundle,
    register,
)


def test_bundle_import_verifies_arrays_and_refuses_overwrite(tmp_path):
    source = tmp_path / "source"
    atomic_json(source / "manifest.json", {"case": "frozen"})
    atomic_arrays(
        source / "captures" / "partial.npz", samples=np.arange(32, dtype=np.float32)
    )
    register(source)
    bundle(source, tmp_path / "results.zip")
    imported = tmp_path / "imported"
    result = import_bundle(tmp_path / "results.zip", imported)
    assert result["replayable"] and result["offline_only"]
    with np.load(imported / "captures" / "partial.npz", allow_pickle=False) as data:
        np.testing.assert_array_equal(data["samples"], np.arange(32))
    with pytest.raises(ValueError, match="must not exist"):
        import_bundle(tmp_path / "results.zip", imported)


@pytest.mark.parametrize(
    "name",
    ["../secret.json", "/secret.json", "C:/secret.json", "captures/../../secret.npz"],
)
def test_import_rejects_path_traversal_without_exposing_destination(tmp_path, name):
    data = b"hostile"
    archive = tmp_path / "hostile.zip"
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr(
            "bundle.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "replayable": True,
                    "files": {name: hashlib.sha256(data).hexdigest()},
                }
            ),
        )
        file.writestr(name, data)
    destination = tmp_path / "imported"
    with pytest.raises(ValueError, match="unsafe"):
        import_bundle(archive, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle-import-*"))


def test_import_rejects_changed_hash_and_uncompressed_byte_bound(tmp_path):
    archive = tmp_path / "changed.zip"
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr(
            "bundle.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "replayable": True,
                    "files": {"manifest.json": "0" * 64},
                }
            ),
        )
        file.writestr("manifest.json", "{}")
    with pytest.raises(ValueError, match="byte bound"):
        import_bundle(archive, tmp_path / "bounded", maximum_bytes=1)
    with pytest.raises(ValueError, match="hash mismatch"):
        import_bundle(archive, tmp_path / "changed")
