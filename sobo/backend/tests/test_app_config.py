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
    # Exact path: `file,` in the outer profile grants `ix` everywhere, and only an exact
    # rule may override it ("conflicting x modifiers" otherwise).
    transition = re.search(r"^\s*(\S+) cx -> sobo_python,", profile, re.MULTILINE)
    assert transition and "*" not in transition.group(1)
    dockerfile = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")
    python = re.search(r"base-python:(\d+\.\d+)-", dockerfile)
    assert python and transition.group(1) == f"/usr/local/bin/python{python.group(1)}"
    child = profile[profile.index("profile sobo_python") :]
    # The backend profile has no capabilities, no blanket file access and may write
    # only to /data and /tmp.
    assert "capability" not in child
    assert not re.search(r"^\s*file,", child, re.MULTILINE)
    writable = re.findall(r"^\s*(/\S+)\s+\w*w\w*,", child, re.MULTILINE)
    allowed = ("/data/", "/tmp/", "/dev/null", "/dev/tty")  # noqa: S108 – profile paths
    assert writable and all(path.startswith(allowed) for path in writable), writable
    assert profile.count("{") == profile.count("}")


ROOT = APP_DIR.parent


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_versions_agree(config: dict[str, Any]) -> None:
    """The release workflow checks the same: tag = app = integration = backend."""
    import json
    import tomllib

    version = config["version"]
    manifest = json.loads((ROOT / "custom_components/sobo/manifest.json").read_text())
    pyproject = tomllib.loads((APP_DIR / "backend/pyproject.toml").read_text())
    assert manifest["version"] == version
    assert pyproject["project"]["version"] == version
    changelog = (APP_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(version)}( |$)", changelog, re.MULTILINE)


def test_prebuilt_multi_arch_image(config: dict[str, Any]) -> None:
    # Lowercase owner (GHCR), generic name: the multi-arch manifest picks the platform.
    assert config["image"] == "ghcr.io/jbosecker/sobo"
    assert set(config["arch"]) == {"amd64", "aarch64"}


def test_brand_images() -> None:
    assert _png_size(APP_DIR / "icon.png") == (128, 128)
    assert _png_size(APP_DIR / "logo.png") == (250, 100)
    brand = ROOT / "custom_components/sobo/brand"
    assert _png_size(brand / "icon.png") == (256, 256)
    assert _png_size(brand / "icon@2x.png") == (512, 512)
    for name in ("logo", "dark_logo"):
        width, height = _png_size(brand / f"{name}.png")
        assert height == 128 and width >= height
        assert _png_size(brand / f"{name}@2x.png")[1] == 256
