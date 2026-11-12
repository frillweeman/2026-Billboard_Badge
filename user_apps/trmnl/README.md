# TRMNL client (show pages from a TRMNL-compatible server)

Speaks the TRMNL device protocol, so any BYOS server ([LaraPaper](https://github.com/usetrmnl/larapaper), Terminus, ...) can cycle pages on the badge: bus times, calendar, whatever the server can render. The server renders everything; the badge only fetches a 1-bit PNG and shows it with the fast partial refresh driver (`lib/epd_partial.py`, black and white only, about 0.6 s per page).

Needs the `on_exit` hook in `apps/base_app.py` and `lib/app_switcher.py` (so the app can give the panel back when you open the app menu).

## Install

1. Copy `trmnl.py` to `/apps/` on the badge.
2. Create `data/wlan_credentials.json` ([`wlan_credentials.sample.json`](./wlan_credentials.sample.json)), the same file `http_poller` uses.
3. Create `data/trmnl.json` ([`trmnl.sample.json`](./trmnl.sample.json)); `server` is the base URL of your server.
4. Copy the changed `apps/base_app.py` and `lib/app_switcher.py` too, then reset.

## Server setup (LaraPaper)

- Set `APP_URL` to the address the badge can reach (it builds `image_url` from it).
- Enable auto-join so the badge registers itself on its first request, or add a device by hand with the badge's MAC (printed to the serial console as `ID`).
- Give the device custom dimensions **960 x 672**, 1-bit black and white, and put your pages in its playlist.
- Refresh interval comes from the server (`refresh_rate`); the badge never polls faster than `min_refresh`. For a live board set the device's refresh interval to about 20 s; the panel only refreshes when the picture changes.

## What it does each cycle

`GET /api/setup` (first run only) -> `GET /api/display` with `ID`, `Access-Token`, `Width`, `Height`, `Battery-Voltage`, `RSSI` -> if `filename` changed, `GET image_url` -> WiFi off -> draw and refresh -> sleep `refresh_rate`.

Every `clean_every` panel refreshes (not polls: an identical picture never touches the panel) it flashes the panel black then white (about 3 s) to remove ghosting. When the server's `refresh_rate` is under `keep_wifi_under` seconds it stays on WiFi between cycles instead of rejoining each time.

## Notes

- Set the device's image format on the server to **BMP3 1-bit** (TRMNL's native format). It is an uncompressed 1-bit bitmap, decoded by `decode_bmp` in `trmnl.py`, up to 960 x 672.
- PNG also works (non-interlaced palette or greyscale, via `lib/large_png.py`), but pick a 2-colour option. That decoder treats only grayscale sample 0 as black, so 8-bit/256-colour grayscale renders almost all white.
- Host test for the BMP decoder: `python3 user_apps/trmnl/tests/test_bmp.py [real.bmp ...]`.
- Leaving the app (menu buttons) stops it and returns the panel to the stock driver; the last page stays on screen.
- Not implemented: `/api/log`, firmware update fields, deep sleep.
