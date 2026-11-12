# TRMNL client app

`firmware/badge/apps/trmnl.py` makes the badge a display for any server that speaks the
[TRMNL](https://trmnl.com) device protocol (a "BYOS" server such as
[LaraPaper](https://github.com/usetrmnl/larapaper) or Terminus). The server renders pages
(bus times, calendar, ...) into a 960 x 672 black-and-white image and decides what to show
next; the badge fetches the image and puts it on the panel with the fast partial refresh
driver (`lib/epd_partial.py`, about 0.7 s, black and white only).

Everything in this directory is documentation, samples and tests. The app itself lives in
`firmware/badge/apps/` so `firmware/scripts/update.py push` deploys it.

## How it works

One asyncio task per launch, repeating:

1. Join WiFi (`data/wlan_credentials.json`). The battery pin is on ADC2, so it is read
   before WiFi comes up.
2. `GET /api/setup` once, only if `data/trmnl.json` has no `api_key`.
3. `GET /api/display` with headers `ID` (the MAC), `Access-Token`, `Width`, `Height`,
   `Battery-Voltage`, `RSSI`, `FW-Version`. The reply carries `image_url`, `filename`,
   `refresh_rate` (seconds). Firmware-update fields are ignored.
4. If `filename` changed, `GET image_url` and decode it into the panel's framebuffer.
   A **1-bit BMP** (TRMNL's native format) is decoded by `decode_bmp`; a palette/greyscale
   PNG falls back to `lib/large_png.py`.
5. `panel.show()` diffs the frame against what is on the glass and only pulls the panel
   if something changed (about 0.7 s). An identical picture never touches the panel.
6. Sleep `refresh_rate` seconds (never less than `min_refresh`). WiFi stays up between
   cycles when `refresh_rate < keep_wifi_under`, otherwise it is switched off.

Every `clean_every` real panel refreshes (about one a minute, because the server's countdowns all change on the minute) it flashes black then white (about 3 s) to remove
ghosting. If ghosting still builds up between cleans, lower `clean_every`. Leaving the app (a menu button) stops the task and hands the panel back to the
stock driver through the `BaseApp.on_exit` hook; the last picture stays on screen.

## Install

```sh
cd firmware
python3 scripts/update.py ls      # what differs from the badge (read-only)
python3 scripts/update.py push    # make the badge match firmware/badge/ (see warning)
```

`push` deletes everything on the badge that is not in `firmware/badge/` except `/data` and
`__pycache__`. Then create the two config files, which are never in git:

```sh
cp trmnl/trmnl.sample.json /tmp/trmnl.json            # edit "server" and "api_key"
mpremote cp /tmp/trmnl.json :data/trmnl.json
# trmnl/wlan_credentials.sample.json shows the format; 2.4 GHz networks only
mpremote cp /tmp/wlan.json :data/wlan_credentials.json
mpremote reset
```

Write the WiFi JSON in a file with an editor rather than `printf` on the command line; a
shell quoting slip (a missing `"`) gives `ValueError: syntax error in JSON` on the badge.

## Config (`/data/trmnl.json`)

| key | default | meaning |
| --- | --- | --- |
| `server` | (required) | base URL, no trailing slash, e.g. `http://192.168.0.17:4567` |
| `api_key` | `""` | the device's access token; if empty the app calls `/api/setup` |
| `min_refresh` | 10 | never poll faster than this many seconds |
| `retry` | 30 | seconds to wait after a failed cycle |
| `keep_wifi_under` | 90 | stay on WiFi between cycles when the server's refresh is under this |
| `clean_every` | 15 | black/white flash every N panel refreshes (not polls) |

## Server setup (LaraPaper)

- Set `APP_URL` to an address the badge can reach; `image_url` is built from it.
- Create the device with the badge's MAC (printed by `mpremote exec` or visible in
  LaraPaper's request log), custom dimensions **960 x 672**, image format **BMP3 1-bit**.
- LaraPaper only answers `/api/setup` for a device that has never refreshed (or while
  "Permit Auto-Join" is on). Easiest is to set the device's `api_key` yourself and put the
  same value in `data/trmnl.json`; the badge then skips setup.
- Set the device's refresh interval to the cadence you want (20 s works well).
- A recipe is only re-rendered when its data is stale, and the UI's minimum stale time is
  1 minute. For a live board set the recipe's `data_stale_minutes` to `0` in the database
  (LaraPaper treats 0 as always stale); re-saving the recipe in the UI may reset it.
- The framework wraps recipes in an 800 x 480 `.screen` unless the device has a matching
  Device Model; the bus-board template pins `.screen` to 960 x 672 itself.

## Troubleshooting

Watch the console with `tools/serial_log.py` (passive; it never resets the badge).

| log line | meaning |
| --- | --- |
| `ValueError: syntax error in JSON` | `data/wlan_credentials.json` or `data/trmnl.json` is malformed |
| `could not join any configured WiFi network` | wrong credentials, 5 GHz only, out of range |
| `server does not know this device (404)` | wrong MAC or `api_key`; check the device in LaraPaper |
| `need an uncompressed 1-bit BMP` | set the device image format to BMP3 1-bit |
| `picture unchanged, panel left alone` | normal: nothing to redraw |
| `MemoryError` | heap fragmentation; reset the badge and relaunch |

`mpremote exec` interrupts `main.py` (a KeyboardInterrupt stops the main loop). Reset the
badge afterwards. Files written without `with open(...)` may not be flushed when you read
them back in the same `exec`.

## Tests

```sh
python3 trmnl/tests/test_bmp.py [real.bmp ...]
```

Host-side test (CPython) of `decode_bmp`: both palette orders, bottom-up and top-down rows,
a smaller image, and bad input. The function is lifted out of `trmnl.py` with `ast`, since
the module imports MicroPython-only packages. The simulator (`firmware/sim`) has no WiFi,
so everything network-related has to be tested on the badge.

Not implemented: `/api/log`, firmware-update fields, deep sleep.
