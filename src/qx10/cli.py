"""Command-line entry point: `uv run qx <command>` (also installed as `qx10`)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import settings
from .api import ERR_FORBIDDEN, Camera, CameraError
from .config import CameraProfile, Config


def _visible_ssids(iface: str | None) -> list[str]:
    cmd = ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"] + (["ifname", iface] if iface else [])
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [line.replace("\\:", ":") for line in out.splitlines()]  # terse mode escapes ':' as '\:'


def _ssid_matches(profile: CameraProfile, ssid: str) -> bool:
    # Camera APs are named DIRECT-xxxx:<MODEL>, e.g. DIRECT-xxxx:DSC-QX100 or DIRECT-xxxx:ILCE-6300.
    # Without a configured SSID only the DSC-<profile name> form can be guessed.
    return ssid == profile.ssid if profile.ssid else ssid.endswith(f":DSC-{profile.name.upper()}")


def _joined_camera(cfg: Config) -> str | None:
    """Profile name of the camera the Wi-Fi adapter is currently joined to, if any."""
    if not cfg.iface:
        return None
    try:
        out = subprocess.run(
            ["nmcli", "-g", "GENERAL.CONNECTION", "dev", "show", cfg.iface],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out if out in cfg.cameras else None


def _unsupported_hint(cam: Camera, e: CameraError) -> str:
    """Explain an error caused by calling a method the camera doesn't offer (right now)."""
    try:
        available = cam.call("getAvailableApiList")[0]
    except Exception:
        return ""
    if e.method in available or e.method in ("getEvent", "getMethodTypes", "getVersions"):
        return ""
    return f"\n{e.method} isn't available on this camera (or in its current mode)"


def cmd_connect(cfg: Config, cam: Camera, args) -> None:
    if not cfg.cameras:
        sys.exit("no cameras in .env; add e.g. QX10_SSID and QX10_PASSWORD")
    visible = _visible_ssids(cfg.iface)
    name = args.camera or cfg.default_camera
    if not name:
        seen = [p.name for p in cfg.cameras.values() if any(_ssid_matches(p, s) for s in visible)]
        if len(seen) != 1:
            found = ", ".join(seen) if seen else "none"
            sys.exit(f"can't tell which camera to join (in range: {found}); use -c {{{','.join(cfg.cameras)}}}")
        name = seen[0]
    profile = cfg.cameras.get(name)
    if not profile or not profile.password:
        sys.exit(f"{name.upper()}_PASSWORD is not set in .env")
    ssid = profile.ssid or next((s for s in visible if _ssid_matches(profile, s)), None)
    if not ssid:
        sys.exit(f"{name} is not in range; is it on? (set {name.upper()}_SSID to skip the scan)")

    exists = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    if profile.name not in exists:
        add = ["sudo", "nmcli", "connection", "add", "type", "wifi", "con-name", profile.name,
               "ssid", ssid, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", profile.password,
               "ipv4.never-default", "yes", "ipv6.method", "disabled", "connection.autoconnect", "no"]
        if cfg.iface:
            add[6:6] = ["ifname", cfg.iface]
        subprocess.run(add, check=True)
    print(f"joining {ssid} ...")
    subprocess.run(["sudo", "nmcli", "connection", "up", profile.name], check=True)


def cmd_info(cfg: Config, cam: Camera, args) -> None:
    name, version = cam.call("getApplicationInfo")
    print(f"endpoint:  {cam.endpoint}")
    print(f"server:    {name} {version}")
    print(f"api:       {', '.join(cam.call('getVersions')[0])}")
    status = cam.event()
    print(f"status:    {status.get('cameraStatus', {}).get('cameraStatus')}")
    zoom = status.get("zoomInformation") or {}
    if zoom.get("zoomPosition", -1) >= 0:
        print(f"zoom:      {zoom['zoomPosition']}%")
    for storage in status.get("storageInformation", []):
        print(f"storage:   {storage['storageID']}: {storage['numberOfRecordableImages']} images left")


def cmd_settings(cfg: Config, cam: Camera, args) -> None:
    for name, (current, candidates) in settings.read_all(cam).items():
        print(f"{name:9} {current!s:28} [{', '.join(map(str, candidates))}]")


def cmd_set(cfg: Config, cam: Camera, args) -> None:
    try:
        settings.apply(cam, args.name, args.value)
    except CameraError as e:
        if e.code not in (1, ERR_FORBIDDEN):
            raise
        sys.exit(f"camera: {e}\n`{args.name}` isn't available now; check `qx settings` "
                 "(ISO/WB/EV need `set mode \"Program Auto\"`, fnumber needs Aperture, shutter needs Shutter)")
    # The camera reports the new value with a short delay.
    for _ in range(10):
        current, _ = settings.read_all(cam)[args.name]
        if str(current) == args.value:
            break
        time.sleep(0.3)
    print(f"{args.name} = {current}")


def _use_postview(cam: Camera, want: str) -> None:
    """Make actTakePicture return the `want` size where the camera lets us choose."""
    if "setPostviewImageSize" not in cam.call("getAvailableApiList")[0]:
        # e.g. the a7R III: it always returns a ~2M postview; the original stays on the card.
        if want == "Original":
            print("note: this camera only sends a reduced-size copy; the original stays on its card",
                  file=sys.stderr)
        return
    if cam.call("getPostviewImageSize")[0] != want:
        cam.call("setPostviewImageSize", want)


def cmd_shoot(cfg: Config, cam: Camera, args) -> None:
    outdir = args.output or cfg.outdir
    if not args.no_download:
        _use_postview(cam, "2M" if args.small else "Original")
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
        print("recording; stop with: qx movie stop")
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
        try:
            ok = cam.focus_at(x, y)
        except CameraError as e:
            if e.code != 1 or "setFocusMode" not in cam.call("getAvailableApiList")[0]:
                raise
            sys.exit(f"camera: {e}\ntouch AF needs an autofocus mode; try: qx set focus AF-S")
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

    _use_postview(cam, "Original")
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
    parser = argparse.ArgumentParser(prog="qx", description="Control a Sony camera (QX10, QX100, a6300, ...) over Wi-Fi")
    parser.add_argument("-c", "--camera", type=str.lower, help="camera profile from .env (e.g. qx10, qx100, a6300); "
                        "default: the one the Wi-Fi adapter is joined to")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("connect", help="join a camera's Wi-Fi (uses sudo nmcli and .env; picks the one in range)").set_defaults(
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
    cam = Camera(cfg.endpoint_for(args.camera or _joined_camera(cfg)))
    try:
        if args.command not in ("connect", "call"):
            cam.ensure_rec_mode()
        args.func(cfg, cam, args)
    except CameraError as e:
        sys.exit(f"camera: {e}{_unsupported_hint(cam, e)}")
    except OSError as e:
        if args.command == "connect":
            raise
        sys.exit(f"cannot reach the camera at {cfg.endpoint}: {e}\n"
                 f"is it on and joined? try: uv run qx connect")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
