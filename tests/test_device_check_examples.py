"""The documented example benches must stay valid as the tool changes."""

import json
from pathlib import Path

import pytest

from beqforge_device_check.cli import validate_config
from beqforge_device_check.engines import MINIDSP_VERSION, usb_loopback_route
from beqforge_device_check.profiles import PROFILES, DeviceProfile

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "device-check-examples"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_example_bench_validates_against_its_current_profile(path):
    config = json.loads(path.read_text())
    profile = validate_config(config)
    # A profile copied into an example must not drift from the shipped one.
    assert profile == PROFILES[profile.id]
    assert DeviceProfile.from_dict(config["profile"]) == PROFILES[profile.id]


def test_usb_loopback_example_is_the_generated_route_and_pinned_helper():
    config = json.loads((EXAMPLES / "minidsp-2x4hd-usb-loopback.json").read_text())
    assert config["engine"]["version"] == MINIDSP_VERSION
    assert config["engine"]["route_commands"] == usb_loopback_route(
        PROFILES["minidsp-2x4hd"]
    )
    assert config["engine"]["route_commands"][0] == ["source", "usb"]
