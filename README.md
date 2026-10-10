# qx10

Control a Sony **DSC-QX10** (the 2013 lens-style camera) from Linux: live
preview, shutter, zoom, touch AF, movie recording, settings, and automatic
download of full-resolution photos.

## How it works

The QX10 has two interfaces:

| Interface | What it does |
|---|---|
| USB (`054c:0751`) | Plain mass storage only (microSD card + a 1 MB `PMHOME` partition). No PTP/MTP, so gphoto2 can't control it. Also charges. |
| Wi-Fi (2.4 GHz only) | Sony **Camera Remote API**: JSON-RPC over HTTP at `http://10.0.0.1:10000/sony/camera`, plus an MJPEG-like liveview stream. This is what this tool uses. |

The camera turns Wi-Fi off while it's in USB mass-storage mode. Power it
from a plain USB charger (or the battery) instead.

Your PC needs a Wi-Fi adapter that supports **2.4 GHz**. A 5 GHz-only
adapter such as the TP-Link Archer T1U can't see the camera. An MT7601U
dongle works with Linux's built-in driver.

## Setup

```sh
cp .env.example .env     # then fill in SSID/password from the label inside the battery cover
uv sync
```

`.env`:

```sh
QX_SSID="DIRECT-XXXX:DSC-QX10"
QX_PASSWORD="XXXXXXXX"
QX_IFACE=wlx...          # optional: which Wi-Fi adapter to use (see `nmcli dev`)
```

Connect (creates a NetworkManager profile `qx10` on first run; needs sudo):

```sh
uv run qx10 connect
```

The profile has `ipv4.never-default yes`, so your normal internet keeps
going over Ethernet or your other Wi-Fi, and `autoconnect no`, so it only
joins the camera when asked.

## Usage

```sh
uv run qx10 view                    # live preview window (see keys below)
uv run qx10 shoot                   # take a photo, download the full 18 MP JPEG to ./photos
uv run qx10 shoot -n 5 --interval 2 # burst of 5, 2 s apart
uv run qx10 shoot --af 30 40        # focus at 30% from left, 40% from top, then shoot
uv run qx10 af 50 50                # set the AF point (stays until cancelled)
uv run qx10 af cancel               # back to automatic AF area
uv run qx10 zoom in -n 3            # step zoom (~12% per step)
uv run qx10 zoom tele|wide          # zoom all the way
uv run qx10 movie start|stop        # record video (saved on the card only)
uv run qx10 settings                # current values and choices
uv run qx10 set iso 800             # mode, iso, ev, wb, size, postview, timer, beep, shoot, function
uv run qx10 info                    # server version, status, zoom, free space
uv run qx10 call getEvent false     # any raw API method; params parsed as JSON
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

`ev` is in 1/3 EV steps (`-6`…`6` = −2…+2 EV). `size` takes
`aspect/size`, e.g. `16:9/13M`. `wb` takes the full name, e.g.
`"Fluorescent: Day White (+1)"`. Run `qx10 settings` for the exact choices.

## Limitations

- Movies stay on the microSD card. To copy them, use USB mass storage, or the
  camera's "Contents Transfer" mode (`set function "Contents Transfer"`), which
  this tool doesn't implement yet.
- No manual shutter or aperture control. The QX10 only offers Intelligent
  Auto, Superior Auto, and Program Auto.
- Only one client at a time. Close the phone app first.
