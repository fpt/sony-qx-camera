"""Live preview window with keyboard/mouse control (OpenCV HighGUI)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
import numpy as np

from .api import Camera, CameraError

WINDOW = "QX10"
HELP = (
    "SPACE shoot  +/- zoom  r movie  f half-press",
    "click: focus here  right-click/c: clear focus  h help  q quit",
)


class Viewer:
    def __init__(self, cam: Camera, outdir: Path):
        self.cam = cam
        self.outdir = outdir
        self.frame: bytes | None = None
        self.status: dict = {}
        self.message = ""
        self.message_until = 0.0
        self.show_help = True
        self.busy = False
        self.af_held = False
        self._size: tuple[int, int] | None = None
        self.zoom_lock = threading.Lock()
        # Touch-AF point in percent and whether AF locked; the camera does not report it back.
        self.af_point: tuple[float, float] | None = None
        self.af_ok = False
        self.stop = threading.Event()

    # --- background workers -------------------------------------------------

    def _liveview_loop(self) -> None:
        while not self.stop.is_set():
            try:
                for jpeg in self.cam.liveview():
                    self.frame = jpeg
                    if self.stop.is_set():
                        break
            except Exception as e:
                self.notify(f"liveview: {e}; reconnecting")
                self.stop.wait(1.0)

    def _event_loop(self) -> None:
        try:
            self.status = self.cam.event()
        except Exception:
            pass
        while not self.stop.is_set():
            try:
                self.status = self.status | self.cam.event(long_poll=True)
            except Exception:
                self.stop.wait(1.0)

    def _run_async(self, label: str, fn) -> None:
        if self.busy:
            self.notify("busy")
            return

        def work():
            self.busy = True
            try:
                fn()
            except Exception as e:
                self.notify(f"{label} failed: {e}")
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()

    # --- actions ------------------------------------------------------------

    def notify(self, text: str, seconds: float = 4.0) -> None:
        print(text)
        self.message = text
        self.message_until = time.monotonic() + seconds

    def shoot(self) -> None:
        def work():
            self.notify("shooting...")
            for url in self.cam.take_picture():
                self.notify("downloading...", 30)
                path = self.cam.download(url, self.outdir)
                self.notify(f"saved {path}")

        self._run_async("shoot", work)

    def zoom(self, direction: str) -> None:
        # Each step blocks for a timed start/stop burst; key repeats queue up behind the lock.
        def work():
            with self.zoom_lock:
                try:
                    self.cam.zoom(direction)
                except CameraError as e:
                    self.notify(str(e))

        threading.Thread(target=work, daemon=True).start()

    def toggle_af(self) -> None:
        try:
            if self.af_held:
                self.cam.call("cancelHalfPressShutter")
                self.notify("AF released")
            else:
                self.cam.call("actHalfPressShutter")
                self.notify("AF locked")
            self.af_held = not self.af_held
        except CameraError as e:
            self.notify(str(e))

    def touch_af(self, x_pct: float, y_pct: float) -> None:
        def work():
            self.af_point, self.af_ok = (x_pct, y_pct), False
            self.notify(f"focusing at {x_pct:.0f}%,{y_pct:.0f}%...")
            self.af_ok = self.cam.focus_at(x_pct, y_pct)
            self.notify(f"focus at {x_pct:.0f}%,{y_pct:.0f}%: {'OK' if self.af_ok else 'failed'}")

        self._run_async("focus", work)

    def clear_af(self) -> None:
        try:
            self.cam.cancel_focus()
            self.af_point = None
            self.notify("focus point cleared")
        except CameraError as e:
            self.notify(str(e))

    def toggle_movie(self) -> None:
        def work():
            if self._camera_status() == "MovieRecording":
                self.cam.call("stopMovieRec")
                self.cam.set_shoot_mode("still")
                self.notify("movie saved to the camera's card")
            else:
                self.cam.set_shoot_mode("movie")
                self.cam.call("startMovieRec")
                self.notify("recording")

        self._run_async("movie", work)

    def _camera_status(self) -> str:
        return self.status.get("cameraStatus", {}).get("cameraStatus", "")

    # --- UI -----------------------------------------------------------------

    def _on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and self._size:
            w, h = self._size
            self.touch_af(min(max(100 * x / w, 0), 100), min(max(100 * y / h, 0), 100))
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.clear_af()

    def _overlay(self, img: np.ndarray) -> None:
        zoom = self.status.get("zoomInformation", {})
        lines = [f"{self._camera_status() or '...'}   zoom {zoom.get('zoomPosition', '?')}%"]
        if self.af_point:
            h, w = img.shape[:2]
            cx, cy = int(self.af_point[0] * w / 100), int(self.af_point[1] * h / 100)
            half = w // 20
            # yellow while focusing or failed, green once AF locked
            color = (0, 220, 0) if self.af_ok else (0, 220, 255)
            cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half), color, 2)
        if self._camera_status() == "MovieRecording":
            cv2.circle(img, (img.shape[1] - 20, 20), 8, (0, 0, 255), -1)
        if self.show_help:
            lines.extend(HELP)
        if time.monotonic() < self.message_until:
            lines.append(self.message)
        for i, text in enumerate(lines):
            org = (8, 20 + 20 * i)
            (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(img, (org[0] - 4, org[1] - th - 4), (org[0] + tw + 4, org[1] + base + 2), (0, 0, 0), -1)
            cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    def run(self) -> None:
        threading.Thread(target=self._liveview_loop, daemon=True).start()
        threading.Thread(target=self._event_loop, daemon=True).start()

        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW, self._on_mouse)
        shown = None
        try:
            while True:
                frame = self.frame
                if frame is not None and frame is not shown:
                    img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        if self._size is None:
                            cv2.resizeWindow(WINDOW, img.shape[1] * 2, img.shape[0] * 2)
                        self._size = (img.shape[1], img.shape[0])
                        self._overlay(img)
                        cv2.imshow(WINDOW, img)
                    shown = frame
                key = cv2.waitKey(15) & 0xFF
                if key in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                elif key in (ord(" "), ord("s")):
                    self.shoot()
                elif key in (ord("+"), ord("="), ord("i")):
                    self.zoom("in")
                elif key in (ord("-"), ord("o")):
                    self.zoom("out")
                elif key == ord("c"):
                    self.clear_af()
                elif key == ord("f"):
                    self.toggle_af()
                elif key == ord("r"):
                    self.toggle_movie()
                elif key == ord("h"):
                    self.show_help = not self.show_help
        finally:
            self.stop.set()
            cv2.destroyAllWindows()
            cleanup = ["stopLiveview"] + (["cancelHalfPressShutter"] if self.af_held else [])
            # leave the touch-AF point in place so `qx10 shoot` keeps using it
            for method in cleanup:
                try:
                    self.cam.call(method)
                except Exception:
                    pass
