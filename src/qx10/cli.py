"""Command-line entry point: `uv run qx10 <command>`."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import settings
from .api import Camera, CameraError
from .config import Config


def cmd_connect(cfg: Config, cam: Camera, args) -> None:
    exists = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    if cfg.connection not in exists:
        if not (cfg.ssid and cfg.password):
            sys.exit("QX_SSID and QX_PASSWORD must be set in .env to create the connection profile")
        add = ["sudo", "nmcli", "connection", "add", "type", "wifi", "con-name", cfg.connection,
               "ssid", cfg.ssid, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", cfg.password,
               "ipv4.never-default", "yes", "ipv6.method", "disabled", "connection.autoconnect", "no"]
        if cfg.iface:
            add[6:6] = ["ifname", cfg.iface]
        subprocess.run(add, check=True)
    subprocess.run(["sudo", "nmcli", "connection", "up", cfg.connection], check=True)


def cmd_info(cfg: Config, cam: Camera, args) -> None:
    name, version = cam.call("getApplicationInfo")
    print(f"endpoint:  {cam.endpoint}")
    print(f"server:    {name} {version}")
    print(f"api:       {', '.join(cam.call('getVersions')[0])}")
    status = cam.event()
    print(f"status:    {status.get('cameraStatus', {}).get('cameraStatus')}")
    zoom = status.get("zoomInformation", {})
    print(f"zoom:      {zoom.get('zoomPosition')}%")
    for storage in status.get("storageInformation", []):
        print(f"storage:   {storage['storageID']}: {storage['numberOfRecordableImages']} images left")


def cmd_settings(cfg: Config, cam: Camera, args) -> None:
    for name, (current, candidates) in settings.read_all(cam).items():
        print(f"{name:9} {current!s:28} [{', '.join(map(str, candidates))}]")


def cmd_set(cfg: Config, cam: Camera, args) -> None:
    settings.apply(cam, args.name, args.value)
    current, _ = settings.read_all(cam)[args.name]
    print(f"{args.name} = {current}")


def cmd_shoot(cfg: Config, cam: Camera, args) -> None:
    outdir = args.output or cfg.outdir
    if not args.no_download:
        want = "2M" if args.small else "Original"
        if cam.call("getPostviewImageSize")[0] != want:
            cam.call("setPostviewImageSize", want)
    if args.af:
        x, y = (_percent(v) for v in args.af)
        print(f"focus at {x:g}%,{y:g}%: {'OK' if cam.focus_at(x, y) else 'failed'}")
    for i in range(args.count):
        if i:
            time.sleep(args.interval)
        urls = cam.take_picture()
        if args.no_download:
            print(f"shot {i + 1}")
            continue
        for url in urls:
            print(cam.download(url, outdir))


def cmd_zoom(cfg: Config, cam: Camera, args) -> None:
    if args.direction in ("wide", "tele"):
        pos = cam.zoom_to_end("in" if args.direction == "tele" else "out")
    else:
        for _ in range(args.steps):
            cam.zoom(args.direction)
        time.sleep(0.5)  # zoomPosition lags the motor slightly
        pos = cam.zoom_position()
    print(f"zoom {pos}%")


def cmd_movie(cfg: Config, cam: Camera, args) -> None:
    if args.action == "start":
        cam.set_shoot_mode("movie")
        cam.call("startMovieRec")
        print("recording; stop with: qx10 movie stop")
    else:
        cam.call("stopMovieRec")
        cam.set_shoot_mode("still")
        print("stopped; the movie is on the camera's microSD card")


def cmd_af(cfg: Config, cam: Camera, args) -> None:
    if args.x == "cancel":
        cam.cancel_focus()
        print("focus point cleared (camera picks the AF area itself)")
    elif args.x == "status":
        entry = cam.event()["touchAFPosition"]
        print("focus point set" if entry["currentSet"] else "no focus point (camera picks the AF area)")
    else:
        x, y = _percent(args.x), _percent(args.y)
        ok = cam.focus_at(x, y)
        print(f"focus at {x:g}%,{y:g}%: {'OK' if ok else 'failed'}")
        if not ok:
            sys.exit(1)


def _percent(value: str | None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        sys.exit("usage: qx10 af X Y   (percent of the frame, 0-100), or: qx10 af cancel|status")
    if not 0 <= v <= 100:
        sys.exit("af coordinates are percentages, 0-100")
    return v


def cmd_view(cfg: Config, cam: Camera, args) -> None:
    from .viewer import Viewer

    if cam.call("getPostviewImageSize")[0] != "Original":
        cam.call("setPostviewImageSize", "Original")
    Viewer(cam, args.output or cfg.outdir).run()


def cmd_call(cfg: Config, cam: Camera, args) -> None:
    params = []
    for p in args.params:
        try:
            params.append(json.loads(p))
        except json.JSONDecodeError:
            params.append(p)
    print(json.dumps(cam.call(args.method, *params, version=args.version), indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="qx10", description="Control a Sony DSC-QX10 over Wi-Fi")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("connect", help="join the camera's Wi-Fi (uses sudo nmcli and .env)").set_defaults(
        func=cmd_connect
    )
    sub.add_parser("info", help="show server version, status, zoom, storage").set_defaults(func=cmd_info)
    sub.add_parser("settings", help="list settings with current value and choices").set_defaults(
        func=cmd_settings
    )

    p = sub.add_parser("set", help="change a setting, e.g. `set iso 800`")
    p.add_argument("name", choices=settings.SETTINGS)
    p.add_argument("value")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("shoot", help="take photo(s) and download them")
    p.add_argument("-n", "--count", type=int, default=1)
    p.add_argument("--interval", type=float, default=0, help="seconds between shots")
    p.add_argument("-o", "--output", type=Path, help="download directory (default: QX_OUTDIR or ./photos)")
    p.add_argument("--small", action="store_true", help="download the 2M postview instead of the original")
    p.add_argument("--no-download", action="store_true", help="leave the photo on the card only")
    p.add_argument("--af", nargs=2, metavar=("X", "Y"), help="focus on this point (percent) before shooting")
    p.set_defaults(func=cmd_shoot)

    p = sub.add_parser("zoom", help="zoom in/out by steps, or all the way to wide/tele")
    p.add_argument("direction", choices=["in", "out", "wide", "tele"])
    p.add_argument("-n", "--steps", type=int, default=1)
    p.set_defaults(func=cmd_zoom)

    p = sub.add_parser("movie", help="start/stop movie recording (saved on the card)")
    p.add_argument("action", choices=["start", "stop"])
    p.set_defaults(func=cmd_movie)

    p = sub.add_parser("af", help="touch AF: `af X Y` (percent of frame), `af cancel`, `af status`")
    p.add_argument("x", help="X percent from the left, or cancel/status")
    p.add_argument("y", nargs="?", help="Y percent from the top")
    p.set_defaults(func=cmd_af)

    p = sub.add_parser("view", help="live preview window with controls")
    p.add_argument("-o", "--output", type=Path)
    p.set_defaults(func=cmd_view)

    p = sub.add_parser("call", help="raw API call; params are parsed as JSON when possible")
    p.add_argument("method")
    p.add_argument("params", nargs="*")
    p.add_argument("--version", default="1.0")
    p.set_defaults(func=cmd_call)

    args = parser.parse_args()
    cfg = Config.load()
    cam = Camera(cfg.endpoint)
    try:
        args.func(cfg, cam, args)
    except CameraError as e:
        sys.exit(f"camera: {e}")
    except OSError as e:
        if args.command == "connect":
            raise
        sys.exit(f"cannot reach the camera at {cfg.endpoint}: {e}\n"
                 f"is it on and joined? try: uv run qx10 connect")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
