"""Static checks of the app's container permissions (plan 6, phase 5)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

APP_DIR = Path(__file__).resolve().parents[2]
CONFIG = APP_DIR / "config.yaml"
APPARMOR = APP_DIR / "apparmor.txt"

pytestmark = pytest.mark.skipif(not CONFIG.exists(), reason="app folder not available")


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    return dict(yaml.safe_load(CONFIG.read_text(encoding="utf-8")))


def test_no_extra_privileges(config: dict[str, Any]) -> None:
    for key in (
        "privileged",
        "full_access",
        "devices",
        "usb",
        "uart",
        "gpio",
        "kernel_modules",
        "docker_api",
        "host_pid",
        "host_ipc",
        "host_dbus",
        "homeassistant_api",
        "auth_api",
        "map",
        "ports",
        "webui",
    ):
        assert key not in config, key
    # Supervisor API only for discovery, with the default (least) role.
    assert config.get("hassio_role", "default") == "default"
    assert config.get("apparmor", True) is True


def test_admin_only_through_ingress(config: dict[str, Any]) -> None:
    assert config["ingress"] is True
    assert config.get("panel_admin", True) is True
    assert config["ingress_port"] == 8737


def test_apparmor_profile() -> None:
    profile = APPARMOR.read_text(encoding="utf-8")
    assert re.search(r"^profile sobo flags=", profile, re.MULTILINE)
    assert "/usr/local/bin/python3* cx -> sobo_python" in profile
    child = profile[profile.index("profile sobo_python") :]
    # The backend profile has no capabilities, no blanket file access and may write
    # only to /data and /tmp.
    assert "capability" not in child
    assert not re.search(r"^\s*file,", child, re.MULTILINE)
    writable = re.findall(r"^\s*(/\S+)\s+\w*w\w*,", child, re.MULTILINE)
    allowed = ("/data/", "/tmp/", "/dev/null", "/dev/tty")  # noqa: S108 – profile paths
    assert writable and all(path.startswith(allowed) for path in writable), writable
    assert profile.count("{") == profile.count("}")
