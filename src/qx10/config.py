"""Settings from environment variables, with a project-level .env as fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .api import DEFAULT_ENDPOINT


def find_dotenv(start: Path | None = None) -> Path | None:
    for d in [start or Path.cwd(), *(start or Path.cwd()).parents]:
        if (d / ".env").is_file():
            return d / ".env"
    return None


def load_dotenv(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class Config:
    ssid: str | None
    password: str | None
    iface: str | None
    connection: str
    endpoint: str
    outdir: Path

    @classmethod
    def load(cls) -> Config:
        dotenv = find_dotenv()
        file_values = load_dotenv(dotenv) if dotenv else {}

        def get(key: str, default: str | None = None) -> str | None:
            return os.environ.get(key) or file_values.get(key) or default

        return cls(
            ssid=get("QX_SSID"),
            password=get("QX_PASSWORD"),
            iface=get("QX_IFACE"),
            connection=get("QX_CONNECTION", "qx10"),
            endpoint=get("QX_ENDPOINT", DEFAULT_ENDPOINT),
            outdir=Path(get("QX_OUTDIR", "photos")).expanduser(),
        )
