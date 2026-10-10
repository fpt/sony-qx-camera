# CLAUDE.md

Linux CLI/GUI for Sony cameras over the Wi-Fi Camera Remote API: QX-series (DSC-QX10, DSC-QX100) and
Alpha a6300 (ILCE-6300) and Alpha 7R III (ILCE-7RM3).
Python, managed with **uv** (`uv run qx ...`, `uv add <pkg>`; don't use pip). The package is still
named `qx10`, and the `qx10` script is an alias of `qx`. OpenCV HighGUI is the preview window
(the system Python has no tkinter).

## Layout

- `src/qx10/api.py`: `Camera` JSON-RPC client, liveview stream parser, zoom/AF/shoot-mode helpers
- `src/qx10/settings.py`: table mapping friendly names (`iso`, `wb`, ...) to getEvent fields and setters
- `src/qx10/viewer.py`: preview window with threads for liveview, getEvent long-poll, and actions
- `src/qx10/cli.py`: argparse subcommands
- `src/qx10/config.py`: reads the environment or `.env`. Per-camera profiles are `<MODEL>_SSID` /
  `<MODEL>_PASSWORD`, optional `<MODEL>_ENDPOINT` (e.g. `QX10_`, `QX100_`, `A6300_`); shared settings use
  `QX_` (`QX_IFACE`, `QX_CAMERA`, ...). Without `-c`, the CLI uses the endpoint of the profile whose
  NetworkManager connection is active on `QX_IFACE`.

## Secrets

`.env` holds the cameras' Wi-Fi passwords and is gitignored. Never commit it, and never copy its
values into tracked files. `.env.example` is the template.

## Hardware facts

Observed on a QX10 and a QX100, both on firmware v3.00 (read from the EXIF `Software` tag of a shot),
with server "Smart Remote Control" 2.1.1 and API 1.0/1.1. Both answer at `10.0.0.1`, and the PC
gets an address in `10.0.0.0/16`.

| | QX10 | QX100 |
|---|---|---|
| AP | `DIRECT-xxxx:DSC-QX10`, 2.4 GHz | `DIRECT-xxxx:DSC-QX100`, 2.4 GHz |
| NM profile | `qx10` | `qx100` |
| Exposure modes | iAuto, Superior Auto, Program Auto | adds Aperture (f/1.8–11), Shutter (30"–1/2000) |
| ISO | AUTO, 100–3200 | AUTO, 160–12800 |
| EV range | -6..6 (1/3 steps) | -9..9 |
| Focus mode API | none | AF-S / MF; MF has no remote focus-drive call |
| Still sizes | 4:3 18M/5M, 16:9 13M/2M | 3:2 20M/5M, 16:9 17M/4.2M, 4:3 18M/5M, 1:1 13M/3.7M |
| Zoom bursts | first burst from wide reports 0%; then 0.3 s ≈ 12% | 0.3 s ≈ 12%, including the first |
| Liveview | ~21 fps | ~5 fps (seen at night indoors; possibly light-dependent) |

### a6300 (ILCE-6300, firmware v2.01, "Smart Remote Control SR/4.31" 2.1.4, API 1.0–1.4)

- The AP is `DIRECT-xxxx:ILCE-6300`; the PC gets `192.168.122.x/24`. Found by SSDP
  (`ST: urn:schemas-sony-com:service:ScalarWebAPI:1`, sent out the Wi-Fi interface): the device
  description lists `camera`, `avContent`, `guide`, and `accessControl` at `http://192.168.122.1:8080/sony`.
- Only ~10 methods until `startRecMode`. After it, the list grows over ~2 s (28, then 67 methods).
  `Camera.ensure_rec_mode()` handles this, and the CLI calls it for every command except `connect`/`call`.
- Exposure mode/F/shutter/ISO/EV follow the mode dial; in iAuto their candidate lists are empty.
- Focus modes: AF-S, AF-C, DMF, MF. `setTouchAFPosition` only appears in an AF mode (error 1 in MF).
- Zoom is Clear Image Zoom (`getZoomSetting`) with a non-power-zoom lens; the burst zoom code works.
- Postview `Original` gives the full 6000x4000 JPEG (~6 MB, ~14 s). Liveview is ~21 fps.

### a7R III (ILCE-7RM3, firmware v3.10, built-in "Smart Remote Control" 2.1.7, API 1.0–1.8)

- Started from the camera's Menu → Network → Ctrl w/ Smartphone. AP `DIRECT-xxxx:ILCE-7RM3` on
  channel 11; the PC got `192.168.0.x/16`. SSDP device description: `camera`, `system`, `guide`, and
  `accessControl` at `http://192.168.122.1:10000/sony`, plus a `DigitalImaging` (PTP/IP) service.
- No `startRecMode` needed: all 57 methods are there at once.
- Missing: `actZoom`, `setTouchAFPosition`, `setFocusMode`, `setPostviewImageSize`/`getPostviewImageSize`
  (error 40401), and storage or battery info in getEvent at any version. Unavailable methods return
  error 1, and the CLI adds a hint (`_unsupported_hint`).
- `actTakePicture` returns **40400** (shooting failed) unless AF has already locked.
  `Camera.take_picture` then half-presses, waits for `focusStatus` (getEvent ≥1.1) to be
  Focused/Failed, and shoots.
- The postview is 1616x1080 only. `shoot` warns that the original stays on the card.
- Liveview is ~28 fps. ISO goes AUTO, 50–102400, and EV -15..15. Shoot modes: still, movie, "slow and quick".

### QX notes (the API behaviour below also applies to the a6300 unless noted above)

- ISO/WB/EV and their getters only appear in `getAvailableApiList` in Program Auto, Aperture, or
  Shutter mode. In Intelligent Auto, `getAvailable*` for them returns error 1.
- `getMethodTypes` takes a version param (`"1.0"`) on the QX100, and on v1.00 it listed methods the firmware
  didn't actually serve. Trust `getAvailableApiList` plus a real call.
- On QX100 firmware v1.00, most getters and setters return **HTTP 403**
  with a JSON error body, even when listed as available. `Camera.call` parses that body. The fix
  is Sony's v3.00 updater, which runs on Windows/Mac only.
- USB is mass storage only. The camera turns Wi-Fi off while on USB data, so power it from a charger.
- Wi-Fi is 2.4 GHz only. An MT7601U USB adapter (in-kernel `mt7601u`) works. The Archer T1U
  (`mt76x0u`) is 5 GHz-only and can't see the camera. Set `QX_IFACE` to pick the adapter.
- `nmcli -t` escapes `:` in SSIDs as `\:`, so unescape it before matching `DIRECT-…:DSC-…`.
- NetworkManager changes usually need `sudo` (polkit denies them from a non-interactive shell),
  so the agent can't run `qx connect` itself; ask the user to (`uv run qx -c qx100 connect`).
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
- Liveview: 640x480 JPEG on the QX models (frame rate per model in the table above). Packets are an 8-byte common header and a 128-byte payload
  header (start code `24 35 68 79`, 3-byte size, 1-byte padding). Only type 0x01 frames are
  sent; there's no focus-frame info.
- Setting postview to `Original` makes `actTakePicture` return the full-size JPEG (QX10 4896x3672,
  ~5 MB, ~7 s round trip). `shoot` and `view` switch to it automatically.

## Testing

There are no unit tests. Check against the real camera(s): `uv run qx info`, `settings`, `af 50 50`,
`shoot`. Shots land on the card **and** in `photos/` (gitignored). To exercise the viewer without
opening a window, drive `Viewer` methods directly and render `_overlay()` to a PNG.
Put camera settings you changed for a test back afterwards (e.g. beep, zoom, AF point, shoot mode,
exposure mode).
