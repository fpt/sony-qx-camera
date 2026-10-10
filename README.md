# qx10

Control Sony **QX-series** lens-style cameras (DSC-QX10, DSC-QX100) from
Linux: live preview, shutter, zoom, touch AF, movie recording, settings
(including aperture and shutter priority on the QX100), and automatic
download of full-resolution photos.

The command is `qx` (also installed as `qx10`).

## How it works

Each camera has two interfaces:

| Interface | What it does |
|---|---|
| USB (QX10 `054c:0751`) | Plain mass storage only (microSD card + a 1 MB `PMHOME` partition). No PTP/MTP, so gphoto2 can't control it. Also charges. |
| Wi-Fi (2.4 GHz only) | Sony **Camera Remote API**: JSON-RPC over HTTP at `http://10.0.0.1:10000/sony/camera`, plus an MJPEG-like liveview stream. This is what this tool uses. |

A camera turns Wi-Fi off while it's in USB mass-storage mode. Power it
from a plain USB charger (or the battery) instead.

Your PC needs a Wi-Fi adapter that supports **2.4 GHz**. A 5 GHz-only
adapter such as the TP-Link Archer T1U can't see the camera. An MT7601U
dongle works with Linux's built-in driver.

## Setup

```sh
cp .env.example .env     # then fill in from the label inside each battery cover
uv sync
```

`.env` has one block per camera. The prefix becomes the profile name used with `-c`:

```sh
QX10_SSID="DIRECT-XXXX:DSC-QX10"
QX10_PASSWORD="XXXXXXXX"
QX100_SSID="DIRECT-XXXX:DSC-QX100"   # optional; found by scanning if omitted
QX100_PASSWORD="XXXXXXXX"
QX_IFACE=wlx...                      # optional: which Wi-Fi adapter to use (see `nmcli dev`)
```

Connect (needs sudo; creates a NetworkManager profile named after the camera on first run):

```sh
uv run qx connect           # joins whichever configured camera is in range
uv run qx -c qx100 connect  # or pick one explicitly
```

Only one camera can be joined at a time per Wi-Fi adapter. Both cameras use
the same address, so all other commands work with whichever is joined.

The profile has `ipv4.never-default yes`, so your normal internet keeps
going over Ethernet or your other Wi-Fi, and `autoconnect no`, so it only
joins the camera when asked.

## Usage

```sh
uv run qx view                    # live preview window (see keys below)
uv run qx shoot                   # take a photo, download the full-resolution JPEG to ./photos
uv run qx shoot -n 5 --interval 2 # burst of 5, 2 s apart
uv run qx shoot --af 30 40        # focus at 30% from left, 40% from top, then shoot
uv run qx af 50 50                # set the AF point (stays until cancelled)
uv run qx af cancel               # back to automatic AF area
uv run qx zoom in -n 3            # step zoom (~12% per step)
uv run qx zoom tele|wide          # zoom all the way
uv run qx movie start|stop        # record video (saved on the card only)
uv run qx settings                # current values and choices
uv run qx set iso 800             # mode, iso, ev, wb, size, fnumber, shutter, focus, postview, timer, beep, shoot, function
uv run qx info                    # server version, status, zoom, free space
uv run qx call getEvent false     # any raw API method; params parsed as JSON
```

### Preview window keys

| Input | Action |
|---|---|
| `Space` / `s` | Shoot and download |
| `+` / `-` (or `i` / `o`) | Zoom in / out |
| Left-click | Touch AF at that point: box is yellow while focusing or if AF failed, green once locked |
| Right-click / `c` | Clear the AF point |
| `f` | Toggle half-press (AF/AE lock) |
| `r` | Start/stop movie recording |
| `h` | Toggle help overlay |
| `q` / `Esc` | Quit |

### Settings values

What you can set depends on the camera and its exposure `mode`:

| Setting | QX10 | QX100 |
|---|---|---|
| `mode` | Intelligent Auto, Superior Auto, Program Auto | adds `Aperture` and `Shutter` |
| `iso`, `wb`, `ev` | Program Auto only | Program Auto, Aperture, Shutter |
| `fnumber` | – | `Aperture` mode, f/1.8–11 |
| `shutter` | – | `Shutter` mode, 30"–1/2000 |
| `focus` | – | `AF-S`, `MF` (no remote focus drive) |

Example: `qx set mode Aperture && qx set fnumber 2.8`.

`ev` is in 1/3 EV steps (QX10 `-6`…`6`, QX100 `-9`…`9`). `size` takes
`aspect/size`, e.g. `16:9/13M`. `wb` takes the full name, e.g.
`"Fluorescent: Day White (+1)"`. Run `qx settings` for the exact choices.

## Limitations

- Movies stay on the microSD card. To copy them, use USB mass storage, or the
  camera's "Contents Transfer" mode (`set function "Contents Transfer"`), which
  this tool doesn't implement yet.
- The QX10 has no aperture or shutter control (Intelligent Auto, Superior
  Auto, and Program Auto only).
- The QX100 needs firmware v3.00. On v1.00 most settings return error 403.
  Sony's updater runs on Windows or Mac only.
- Only one client at a time. Close the phone app first.
