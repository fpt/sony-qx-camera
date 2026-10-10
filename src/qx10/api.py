"""Client for the Sony Camera Remote API as served by the DSC-QX10.

The camera exposes JSON-RPC over HTTP on its own Wi-Fi access point.
Every call is a POST of {"method", "params", "id", "version"} to the
camera service endpoint; replies carry either "result" or "error".
"""

from __future__ import annotations

import itertools
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://10.0.0.1:10000/sony/camera"

# Error codes from the Camera Remote API reference.
ERR_ILLEGAL_ARGUMENT = 3
ERR_FORBIDDEN = 403  # method not available in the current camera state
ERR_SHOOTING_FAILED = 40400  # e.g. AF could not lock
ERR_NOT_READY = 40401
ERR_CAPTURE_NOT_FINISHED = 40403  # follow up with awaitTakePicture

LIVEVIEW_PAYLOAD_START = b"\x24\x35\x68\x79"
LIVEVIEW_TYPE_JPEG = 0x01


class CameraError(RuntimeError):
    def __init__(self, method: str, code: int, message: str = ""):
        super().__init__(f"{method}: error {code} {message}".rstrip())
        self.method = method
        self.code = code


class Camera:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 10.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self._ids = itertools.count(1)

    def call(self, method: str, *params: Any, version: str = "1.0", timeout: float | None = None) -> Any:
        body = json.dumps(
            {"method": method, "params": list(params), "id": next(self._ids), "version": version}
        ).encode()
        req = urllib.request.Request(self.endpoint, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                reply = json.load(resp)
        except urllib.error.HTTPError as e:
            # Older firmware (QX100, server 2.0.0) sends the JSON error with HTTP status 403.
            try:
                reply = json.load(e)
            except ValueError:
                raise e from None
        if "error" in reply:
            raise CameraError(method, *reply["error"])
        # getMethodTypes answers with "results" instead of "result".
        return reply.get("result", reply.get("results"))

    def ensure_rec_mode(self, timeout: float = 15.0) -> None:
        """Enter shooting mode on bodies that need it (Alpha, RX); a no-op on the QX series.

        Until startRecMode, such bodies expose only ~10 methods; afterwards the
        full list appears over a few seconds.
        """
        apis = self.call("getAvailableApiList")[0]
        if "startRecMode" not in apis or "actTakePicture" in apis:
            return
        self.call("startRecMode", timeout=20)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "actTakePicture" in self.call("getAvailableApiList")[0]:
                time.sleep(1.0)  # settings in getEvent fill in a moment later
                return
            time.sleep(0.5)
        raise CameraError("startRecMode", ERR_NOT_READY, "camera did not enter shooting mode")

    def event(self, long_poll: bool = False) -> dict[str, Any]:
        """Return getEvent's status entries keyed by their "type".

        The raw reply is a positional array whose slots hold a dict, a list
        of dicts, or null. With long_poll=True the camera blocks until
        something changes (or its own timeout elapses).
        """
        result = self.call("getEvent", long_poll, timeout=70 if long_poll else None)
        status: dict[str, Any] = {}
        for item in result:
            if isinstance(item, dict) and "type" in item:
                status[item["type"]] = item
            elif isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict) and "type" in sub:
                        status.setdefault(sub["type"], []).append(sub)
        return status

    def take_picture(self) -> list[str]:
        """Shoot a still and return the postview image URL(s)."""
        try:
            return self.call("actTakePicture", timeout=30)[0]
        except CameraError as e:
            if e.code == ERR_CAPTURE_NOT_FINISHED:
                return self.call("awaitTakePicture", timeout=30)[0]
            if e.code == ERR_SHOOTING_FAILED and "actHalfPressShutter" in self.call("getAvailableApiList")[0]:
                # The a7R III fails actTakePicture unless AF has already locked.
                return self._take_picture_after_focus()
            raise

    def _take_picture_after_focus(self, timeout: float = 5.0) -> list[str]:
        self.call("actHalfPressShutter", timeout=15)
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self.focus_status() not in ("Focused", "Failed"):
                time.sleep(0.2)
            return self.call("actTakePicture", timeout=30)[0]
        finally:
            self.call("cancelHalfPressShutter")

    def focus_status(self) -> str | None:
        """"Focused", "Failed", "Focusing", "Not Focusing", or None if not reported.

        focusStatus is only in getEvent version 1.1 and later.
        """
        try:
            result = self.call("getEvent", False, version="1.1")
        except CameraError:
            return None
        for item in result:
            if isinstance(item, dict) and item.get("type") == "focusStatus":
                return item["focusStatus"]
        return None

    def zoom(self, direction: str, seconds: float = 0.3) -> None:
        """Zoom "in" or "out" for a short burst.

        The QX10 accepts actZoom "1shot" but does not move, so a step is a
        timed start/stop: 0.3 s is ~12%, 0.4 s ~19%, 0.2 s nothing. The first
        burst from fully wide reports no movement; later ones step evenly.
        """
        self.call("actZoom", direction, "start")
        time.sleep(seconds)
        self.call("actZoom", direction, "stop")

    def set_shoot_mode(self, mode: str, timeout: float = 10.0) -> None:
        """Switch "still"/"movie" and wait until the camera has settled.

        Calling startMovieRec right after setShootMode fails with error 5.
        """
        self.call("setShootMode", mode)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.event()
            if st["shootMode"]["currentShootMode"] == mode and st["cameraStatus"]["cameraStatus"] == "IDLE":
                return
            time.sleep(0.3)
        raise CameraError("setShootMode", ERR_NOT_READY, f"camera did not settle in {mode} mode")

    def focus_at(self, x_pct: float, y_pct: float) -> bool:
        """Touch AF: focus on a point given in percent of the frame (0,0 = top-left).

        The point stays in effect for following shots until cancel_focus().
        Returns whether autofocus succeeded.
        """
        result = self.call("setTouchAFPosition", float(x_pct), float(y_pct), timeout=15)
        return bool(result[1].get("AFResult")) if len(result) > 1 else False

    def cancel_focus(self) -> None:
        self.call("cancelTouchAFPosition")

    def zoom_position(self) -> int:
        return self.event()["zoomInformation"]["zoomPosition"]

    def zoom_to_end(self, direction: str) -> int:
        """Zoom fully in or out; "start" runs to the end stop without a stop call."""
        self.call("actZoom", direction, "start")
        last = None
        while (pos := self.zoom_position()) != last:
            last = pos
            time.sleep(0.5)
        return pos

    def download(self, url: str, outdir: Path) -> Path:
        outdir.mkdir(parents=True, exist_ok=True)
        name = Path(urllib.parse.urlparse(url).path).name or "image.jpg"
        dest = outdir / name
        n = 1
        while dest.exists():
            dest = outdir / f"{Path(name).stem}_{n}{Path(name).suffix}"
            n += 1
        tmp = dest.with_name(dest.name + ".part")
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
        tmp.rename(dest)
        return dest

    def liveview(self) -> Iterator[bytes]:
        """Start liveview and yield JPEG frames until the caller stops iterating."""
        url = self.call("startLiveview")[0]
        try:
            yield from read_liveview(url)
        finally:
            try:
                self.call("stopLiveview")
            except Exception:
                pass


def read_liveview(url: str) -> Iterator[bytes]:
    """Parse the liveview stream into JPEG frames.

    Each packet is an 8-byte common header (0xFF, payload type, sequence,
    timestamp), a 128-byte payload header (start code, 3-byte data size,
    1-byte padding size, ...), then the data and padding.
    """
    with urllib.request.urlopen(url, timeout=10) as resp:

        def read_exact(n: int) -> bytes:
            buf = bytearray()
            while len(buf) < n:
                chunk = resp.read(n - len(buf))
                if not chunk:
                    raise EOFError("liveview stream closed")
                buf += chunk
            return bytes(buf)

        while True:
            common = read_exact(8)
            if common[0] != 0xFF:
                raise ValueError(f"bad liveview packet start byte {common[0]:#x}")
            payload_header = read_exact(128)
            if payload_header[:4] != LIVEVIEW_PAYLOAD_START:
                raise ValueError("bad liveview payload start code")
            size = int.from_bytes(payload_header[4:7], "big")
            padding = payload_header[7]
            data = read_exact(size)
            read_exact(padding)
            if common[1] == LIVEVIEW_TYPE_JPEG:
                yield data
