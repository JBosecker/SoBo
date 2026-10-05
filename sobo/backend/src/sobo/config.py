"""App-Optionen aus `/data/options.json` (vom Supervisor) plus Umgebungsvariablen
für die Entwicklung."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

INGRESS_IP = "172.30.32.2"


class AppOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    log_level: str = "info"
    fake_sonos: bool = False
    data_dir: Path = Path("/data")
    # Admin-UI über Ingress (muss von der Supervisor-Bridge erreichbar sein)
    host: str = "0.0.0.0"  # noqa: S104 – Ingress kommt über das hassio-Netz
    port: int = 8737
    # Interne API für die Integration: nur lokal, HA Core läuft ebenfalls im Host-Netz
    internal_host: str = "127.0.0.1"
    internal_port: int = 8738
    trusted_ingress: frozenset[str] = Field(default_factory=lambda: frozenset({INGRESS_IP}))
    poll_interval: float = 1.5
    fake_speed: float = 1.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sobo.db"

    @property
    def secret_path(self) -> Path:
        return self.data_dir / "secret"

    @classmethod
    def load(cls, options_file: Path | None = None) -> AppOptions:
        values: dict[str, object] = {}
        path = options_file or Path(os.environ.get("SOBO_OPTIONS", "/data/options.json"))
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for key in ("log_level", "fake_sonos"):
                if key in raw:
                    values[key] = raw[key]
        env = os.environ
        if "SOBO_DATA_DIR" in env:
            values["data_dir"] = Path(env["SOBO_DATA_DIR"])
        if "SOBO_FAKE_SONOS" in env:
            values["fake_sonos"] = env["SOBO_FAKE_SONOS"].lower() in ("1", "true", "yes")
        if "SOBO_FAKE_SPEED" in env:
            values["fake_speed"] = float(env["SOBO_FAKE_SPEED"])
        if "SOBO_TRUSTED_INGRESS" in env:
            values["trusted_ingress"] = frozenset(
                ip.strip() for ip in env["SOBO_TRUSTED_INGRESS"].split(",") if ip.strip()
            )
        for key, name in (("port", "SOBO_PORT"), ("internal_port", "SOBO_INTERNAL_PORT")):
            if name in env:
                values[key] = int(env[name])
        if "SOBO_INTERNAL_HOST" in env:
            values["internal_host"] = env["SOBO_INTERNAL_HOST"]
        return cls.model_validate(values)
