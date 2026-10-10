"""Named camera settings: read from getEvent, written with the matching set* method.

Values are passed as strings on the command line, e.g. `iso 800`,
`size 16:9/13M`, `wb Daylight`, `ev -3` (exposure steps are 1/3 EV).
Which settings exist depends on the model, firmware, and exposure mode:
ISO/WB/EV need Program Auto or higher; fnumber needs mode Aperture and
shutter needs mode Shutter (QX100 only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .api import Camera, CameraError


@dataclass(frozen=True)
class Setting:
    event_type: str
    current_key: str
    candidates_key: str | None
    setter: str
    is_int: bool = False


SETTINGS: dict[str, Setting] = {
    "mode": Setting("exposureMode", "currentExposureMode", "exposureModeCandidates", "setExposureMode"),
    "iso": Setting("isoSpeedRate", "currentIsoSpeedRate", "isoSpeedRateCandidates", "setIsoSpeedRate"),
    "ev": Setting("exposureCompensation", "currentExposureCompensation", None, "setExposureCompensation", True),
    "wb": Setting("whiteBalance", "currentWhiteBalanceMode", None, "setWhiteBalance"),
    "size": Setting("stillSize", "currentSize", None, "setStillSize"),
    "postview": Setting(
        "postviewImageSize", "currentPostviewImageSize", "postviewImageSizeCandidates", "setPostviewImageSize"
    ),
    "fnumber": Setting("fNumber", "currentFNumber", "fNumberCandidates", "setFNumber"),
    "shutter": Setting("shutterSpeed", "currentShutterSpeed", "shutterSpeedCandidates", "setShutterSpeed"),
    "focus": Setting("focusMode", "currentFocusMode", "focusModeCandidates", "setFocusMode"),
    "timer": Setting("selfTimer", "currentSelfTimer", "selfTimerCandidates", "setSelfTimer", True),
    "beep": Setting("beepMode", "currentBeepMode", "beepModeCandidates", "setBeepMode"),
    "shoot": Setting("shootMode", "currentShootMode", "shootModeCandidates", "setShootMode"),
    "function": Setting(
        "cameraFunction", "currentCameraFunction", "cameraFunctionCandidates", "setCameraFunction"
    ),
}


def read_all(cam: Camera) -> dict[str, tuple[Any, list[Any]]]:
    """Return {name: (current value, candidate values)} for every known setting."""
    status = cam.event()
    out = {}
    for name, s in SETTINGS.items():
        entry = status.get(s.event_type)
        if not isinstance(entry, dict):
            continue
        try:
            candidates = _candidates(cam, name, entry)
        except CameraError:  # e.g. getAvailableWhiteBalance in Intelligent Auto
            candidates = []
        out[name] = (_current(name, entry), candidates)
    return out


def _current(name: str, entry: dict) -> Any:
    if name == "size":
        return f"{entry['currentAspect']}/{entry['currentSize']}"
    return entry[SETTINGS[name].current_key]


def _candidates(cam: Camera, name: str, entry: dict) -> list[Any]:
    s = SETTINGS[name]
    if s.candidates_key:
        return entry.get(s.candidates_key, [])
    if name == "ev":
        return list(range(entry["minExposureCompensation"], entry["maxExposureCompensation"] + 1))
    if name == "wb":
        return [c["whiteBalanceMode"] for c in cam.call("getAvailableWhiteBalance")[1]]
    if name == "size":
        return [f"{c['aspect']}/{c['size']}" for c in cam.call("getAvailableStillSize")[1]]
    return []


def apply(cam: Camera, name: str, value: str) -> None:
    s = SETTINGS[name]
    if name == "wb":
        cam.call(s.setter, value, False, -1)
    elif name == "size":
        aspect, _, size = value.partition("/")
        cam.call(s.setter, aspect, size)
    else:
        cam.call(s.setter, int(value) if s.is_int else value)
