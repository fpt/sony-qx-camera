# CLAUDE.md

Linux CLI/GUI for a Sony DSC-QX10 over its Wi-Fi Camera Remote API. Python, managed with **uv**
(`uv run qx10 ...`, `uv add <pkg>`; don't use pip). OpenCV HighGUI is the preview window
(the system Python has no tkinter).

## Layout

- `src/qx10/api.py`: `Camera` JSON-RPC client, liveview stream parser, zoom/AF/shoot-mode helpers
- `src/qx10/settings.py`: table mapping friendly names (`iso`, `wb`, ...) to getEvent fields and setters
- `src/qx10/viewer.py`: preview window with threads for liveview, getEvent long-poll, and actions
- `src/qx10/cli.py`: argparse subcommands
- `src/qx10/config.py`: reads `QX_*` from the environment or `.env`

## Secrets

`.env` holds the camera's Wi-Fi password and is gitignored. Never commit it, and never copy its
values into tracked files. `.env.example` is the template.

## Hardware facts (verified on this unit: firmware v3.00, server "Smart Remote Control" 2.1.1)

- USB is mass storage only. The camera turns Wi-Fi off while on USB data, so power it from a charger.
- Wi-Fi is 2.4 GHz only. The working adapter is an MT7601U (`wlxa047d745940e`). The Archer T1U
  (`mt76x0u`) is 5 GHz-only and can't see the camera.
- Camera AP `DIRECT-M3Q0:DSC-QX10`, channel 1, camera at `10.0.0.1`, PC gets `10.0.1.1/16`.
- NetworkManager changes need `sudo` here (polkit denies them without a password), so the
  agent can't run `qx10 connect` itself; ask the user to.
- `actZoom ... "1shot"` returns success but doesn't move. Use timed `start`/`stop` bursts
  (0.2 s does nothing, 0.3 s is ~12%, 0.4 s ~19%). The first burst from fully wide reports 0%.
  `start` alone runs to the end stop and returns immediately.
- `startMovieRec` right after `setShootMode movie` fails with error 5. Wait until getEvent shows
  the new shoot mode and `cameraStatus` `IDLE` (`Camera.set_shoot_mode`).
- `setTouchAFPosition x y` (floats, percent) returns `[0, {"AFResult": bool, ...}]`. The point
  persists until `cancelTouchAFPosition`. getEvent's `touchAFPosition` only reports `currentSet`
  (coordinates come back empty), so the viewer tracks the point itself.
- `getStorageInformation` returns 403. Read storage from getEvent instead.
- `getAvailable*` methods take no params. Passing `["1.0"]` gives error 3.
- Liveview: 640x480 JPEG at ~21 fps. Packets are an 8-byte common header and a 128-byte payload
  header (start code `24 35 68 79`, 3-byte size, 1-byte padding). Only type 0x01 frames are
  sent; there's no focus-frame info.
- Setting postview to `Original` makes `actTakePicture` return the full 4896x3672 JPEG (~5 MB,
  ~7 s round trip). `shoot` and `view` switch to it automatically.

## Testing

There are no unit tests. Check against the real camera: `uv run qx10 info`, `settings`, `af 50 50`,
`shoot`. Shots land on the card **and** in `photos/` (gitignored). To exercise the viewer without
opening a window, drive `Viewer` methods directly and render `_overlay()` to a PNG.
Put camera settings you changed for a test back afterwards (e.g. beep, zoom, AF point, shoot mode).
