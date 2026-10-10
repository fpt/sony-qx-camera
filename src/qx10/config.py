"""Settings from environment variables, with a project-level .env as fallback.

Each camera is a profile named by a prefix, e.g. QX10_SSID / QX10_PASSWORD,
QX100_*, A6300_*, with an optional <PREFIX>_ENDPOINT for bodies that don't
answer at the QX default address. Shared settings use the QX_ prefix.
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
    endpoint: str | None = None


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
        file_values = load_dotenv(dotenv) if dotenv else {}
        # The environment overrides .env, but only for keys this tool owns, so that
        # unrelated variables like DB_PASSWORD don't turn into camera profiles.
        values = file_values | {
            k: v for k, v in os.environ.items() if v and (k.startswith("QX") or k in file_values)
        }

        cameras = {}
        for key in values:
            m = re.fullmatch(r"([A-Z][A-Z0-9]*)_(SSID|PASSWORD)", key)
            if m and m.group(1) != "QX":
                prefix = m.group(1)
                cameras[prefix.lower()] = CameraProfile(
                    name=prefix.lower(),
                    ssid=values.get(f"{prefix}_SSID"),
                    password=values.get(f"{prefix}_PASSWORD"),
                    endpoint=values.get(f"{prefix}_ENDPOINT"),
                )

        return cls(
            cameras=dict(sorted(cameras.items())),
            default_camera=(values.get("QX_CAMERA") or "").lower() or None,
            iface=values.get("QX_IFACE"),
            endpoint=values.get("QX_ENDPOINT", DEFAULT_ENDPOINT),
            outdir=Path(values.get("QX_OUTDIR", "photos")).expanduser(),
        )

    def endpoint_for(self, camera: str | None) -> str:
        """Endpoint of the named profile, falling back to QX_ENDPOINT / the QX default."""
        profile = self.cameras.get(camera or "")
        return (profile and profile.endpoint) or self.endpoint
