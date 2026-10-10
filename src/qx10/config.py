"""Settings from environment variables, with a project-level .env as fallback.

Each camera is a profile named by a prefix, e.g. QX10_SSID / QX10_PASSWORD
and QX100_SSID / QX100_PASSWORD. Shared settings use the QX_ prefix.
"""

from __future__ import annotations

import os
import re
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
class CameraProfile:
    name: str  # lower-case profile name, also the NetworkManager connection name
    ssid: str | None
    password: str | None


@dataclass
class Config:
    cameras: dict[str, CameraProfile]
    default_camera: str | None
    iface: str | None
    endpoint: str
    outdir: Path

    @classmethod
    def load(cls) -> Config:
        dotenv = find_dotenv()
        values = (load_dotenv(dotenv) if dotenv else {}) | {
            k: v for k, v in os.environ.items() if k.startswith("QX") and v
        }

        cameras = {}
        for key in values:
            m = re.fullmatch(r"(QX\d+)_(SSID|PASSWORD)", key)
            if m:
                prefix = m.group(1)
                cameras[prefix.lower()] = CameraProfile(
                    name=prefix.lower(),
                    ssid=values.get(f"{prefix}_SSID"),
                    password=values.get(f"{prefix}_PASSWORD"),
                )

        return cls(
            cameras=dict(sorted(cameras.items())),
            default_camera=(values.get("QX_CAMERA") or "").lower() or None,
            iface=values.get("QX_IFACE"),
            endpoint=values.get("QX_ENDPOINT", DEFAULT_ENDPOINT),
            outdir=Path(values.get("QX_OUTDIR", "photos")).expanduser(),
        )
