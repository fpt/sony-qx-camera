# CLAUDE.md

Linux CLI/GUI for Sony QX-series cameras (DSC-QX10, DSC-QX100) over the Wi-Fi Camera Remote API.
Python, managed with **uv** (`uv run qx ...`, `uv add <pkg>`; don't use pip). The package is still
named `qx10`, and the `qx10` script is an alias of `qx`. OpenCV HighGUI is the preview window
(the system Python has no tkinter).

## Layout

- `src/qx10/api.py`: `Camera` JSON-RPC client, liveview stream parser, zoom/AF/shoot-mode helpers
- `src/qx10/settings.py`: table mapping friendly names (`iso`, `wb`, ...) to getEvent fields and setters
- `src/qx10/viewer.py`: preview window with threads for liveview, getEvent long-poll, and actions
- `src/qx10/cli.py`: argparse subcommands
- `src/qx10/config.py`: reads the environment or `.env`. Per-camera profiles are `<MODEL>_SSID` /
  `<MODEL>_PASSWORD` (e.g. `QX10_`, `QX100_`); shared settings use `QX_` (`QX_IFACE`, `QX_CAMERA`, ...).

## Secrets

`.env` holds the cameras' Wi-Fi passwords and is gitignored. Never commit it, and never copy its
values into tracked files. `.env.example` is the template.

## Hardware facts

Both units run firmware v3.00 (read from the EXIF `Software` tag of a shot) with server "Smart Remote
Control" 2.1.1 and API 1.0/1.1. Both answer at `10.0.0.1`, and the PC gets `10.0.1.1/16`.

| | QX10 | QX100 |
|---|---|---|
| AP | `DIRECT-M3Q0:DSC-QX10`, channel 1 | `DIRECT-imQ0:DSC-QX100`, channel 1 |
| NM profile | `qx10` | `qx100` |
| Exposure modes | iAuto, Superior Auto, Program Auto | adds Aperture (f/1.8–11), Shutter (30"–1/2000) |
| ISO | AUTO, 100–3200 | AUTO, 160–12800 |
| EV range | -6..6 (1/3 steps) | -9..9 |
| Focus mode API | none | AF-S / MF; MF has no remote focus-drive call |
| Still sizes | 4:3 18M/5M, 16:9 13M/2M | 3:2 20M/5M, 16:9 17M/4.2M, 4:3 18M/5M, 1:1 13M/3.7M |
| Zoom bursts | first burst from wide reports 0%; then 0.3 s ≈ 12% | 0.3 s ≈ 12%, including the first |
| Liveview | ~21 fps | ~5 fps (seen at night indoors; possibly light-dependent) |

- ISO/WB/EV and their getters only appear in `getAvailableApiList` in Program Auto, Aperture, or
  Shutter mode. In Intelligent Auto, `getAvailable*` for them returns error 1.
- `getMethodTypes` takes a version param (`"1.0"`) on the QX100, and it lists methods the firmware
  doesn't actually serve. Trust `getAvailableApiList` plus a real call.
- The QX100 was on v1.00 when first connected. There, most getters and setters returned **HTTP 403**
  with a JSON error body, even when listed as available. `Camera.call` parses that body. The fix
  was Sony's v3.00 updater, which runs on Windows/Mac only.
- USB is mass storage only. The camera turns Wi-Fi off while on USB data, so power it from a charger.
- Wi-Fi is 2.4 GHz only. The working adapter is an MT7601U (`wlxa047d745940e`). The Archer T1U
  (`mt76x0u`) is 5 GHz-only and can't see the camera.
- `nmcli -t` escapes `:` in SSIDs as `\:`, so unescape it before matching `DIRECT-…:DSC-…`.
- NetworkManager changes need `sudo` here (polkit denies them without a password), so the
  agent can't run `qx connect` itself; ask the user to (`uv run qx -c qx100 connect`).
- `actZoom ... "1shot"` returns success but doesn't move. Use timed `start`/`stop` bursts
  (0.2 s does nothing, 0.3 s is ~12%, 0.4 s ~19%). `start` alone runs to the end stop and
  returns immediately.
- `startMovieRec` right after `setShootMode movie` fails with error 5. Wait until getEvent shows
  the new shoot mode and `cameraStatus` `IDLE` (`Camera.set_shoot_mode`).
- `setTouchAFPosition x y` (floats, percent) returns `[0, {"AFResult": bool, ...}]`. The point
  persists until `cancelTouchAFPosition`. getEvent's `touchAFPosition` only reports `currentSet`
  (coordinates come back empty), so the viewer tracks the point itself.
- `getStorageInformation` returns 403. Read storage from getEvent instead.
- `getAvailable*` methods take no params. Passing `["1.0"]` gives error 3.
- Settings changes show up in getEvent a moment later, so `qx set` polls before printing.
- Liveview: 640x480 JPEG (frame rate per model in the table above). Packets are an 8-byte common header and a 128-byte payload
  header (start code `24 35 68 79`, 3-byte size, 1-byte padding). Only type 0x01 frames are
  sent; there's no focus-frame info.
- Setting postview to `Original` makes `actTakePicture` return the full-size JPEG (QX10 4896x3672,
  ~5 MB, ~7 s round trip). `shoot` and `view` switch to it automatically.

## Testing

There are no unit tests. Check against the real camera(s): `uv run qx info`, `settings`, `af 50 50`,
`shoot`. Shots land on the card **and** in `photos/` (gitignored). To exercise the viewer without
opening a window, drive `Viewer` methods directly and render `_overlay()` to a PNG.
Put camera settings you changed for a test back afterwards (e.g. beep, zoom, AF point, shoot mode,
exposure mode). Both cameras were left in Intelligent Auto, AF-S, still mode, zoomed fully out.
