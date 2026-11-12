# Supercon badge, home-display fork

Fork of Hack-a-Day's 2026 Billboard Badge firmware (ESP32-S3, MicroPython, 9.7" Pervasive
E2969JS0B1 e-paper, 960 x 672, black/white/red). **Purpose of this fork:** show pages from a
TRMNL-protocol server (bus times, calendar, ...) on the badge. The only app is TRMNL.
Read `trmnl/README.md` for what the app does and how to set it up.

## Remotes and branches

- `origin` = `frillweeman/2026-Billboard_Badge` (the fork), branch `main`.
- `upstream` = `Hack-a-Day/2026-Billboard_Badge`. Nothing here goes upstream unless asked.
- Commit messages end with the usual `Co-Authored-By` trailer.

## Layout

- `firmware/badge/` is the badge's filesystem; `update.py push` makes the badge match it.
  - `apps/trmnl.py` the app; `apps/base_app.py` (has the `on_exit` hook);
    `apps/template.py` a developer example the switcher skips.
  - `lib/app_switcher.py` discovers `/apps/*.py` and runs one app at a time;
    `lib/epd.py` stock display driver; `lib/epd_partial.py` fast partial refresh;
    `lib/large_png.py` PNG decoder; `lib/led_bar.py`, `lib/button.py`.
  - `data/` fonts, `rendered_luts.py` (waveforms), two splash images. Runtime config files
    (`wlan_credentials.json`, `trmnl.json`) are created on the badge and **never** in git.
- `trmnl/` docs, samples, host test, `tools/serial_log.py`.
- `firmware/sim/` desktop simulator (needs a Linux SDL build of lv_micropython; no WiFi).
- `libraries/billboard_epd`, `hardware/`, `documentation/` are upstream, untouched.

## Rules for the display driver (learned the hard way)

- `PartialEPD` (`lib/epd_partial.py`) is B1-panel only, black and white only. `start()` takes
  `display.lock` and the SPI bus; `stop()` releases them and **must** run, or every other
  display user hangs. The TRMNL app does this from its task's `finally`, triggered by
  `on_exit` (the switcher calls it when the user leaves for the menu).
- `panel.fb` is 960 x 672 MONO_HLSB with 1 = black. `show()` diffs against what is on the
  glass and returns the ms it took, or 0 if nothing changed (the panel is not touched).
  After `SESSION_PULLS` (60) pulls it reopens the session itself.
- Ghosting: `restart(wipe=True)` flashes black/white (~3 s); the app does it every
  `clean_every` real refreshes. Don't call `gc.collect()` between frames in a fast loop.
- `large_png.show_png` writes both a black and a red plane; pass a throwaway red buffer for
  1-bit images. It treats only grayscale sample 0 as black. The app prefers BMP
  (`decode_bmp` in `trmnl.py`).
- `app.run()` must return quickly: the switcher polls the menu buttons between calls. Long
  work goes in `aio.create_task`.
- The battery pin (GPIO14) is on ADC2, unreliable while WiFi is on.

## Deploying to the badge

- Ask before writing to the badge or flashing. Never run `esptool` erase/write unprompted.
- `cd firmware && python3 scripts/update.py ls` is a read-only diff; `push` copies
  `firmware/badge/` and **deletes anything on the badge that isn't in it** (except `/data`
  and `__pycache__`). `mpremote cp` for single files. The port is `/dev/cu.usbmodem101`
  and only one program can hold it.
- `mpremote exec` (and `update.py ls`) interrupt `main.py`; the badge sits at the REPL
  afterwards, so `mpremote reset`. Files written without `with open(...)` may not be flushed
  when read back in the same call.
- Watch the console with `trmnl/tools/serial_log.py` (passive, reconnects). `mpremote repl`
  needs a terminal and is awkward from scripts. Stop the logger before using mpremote.
- Create JSON config files in an editor, not with `printf` on the command line: a missing
  quote in `wlan_credentials.json` once gave `ValueError: syntax error in JSON`.
- After a launch you need a button press: press the menu button that moves backwards
  (selection wraps), then User A.

## This installation

- Badge MAC `90:DA:72:4F:18:DC`. Its access token is in the badge's `/data/trmnl.json` and in
  LaraPaper's database (device id 1); it is not stored in this repo.
- LaraPaper (TRMNL server): `plex@192.168.0.17`, `~/larapaper`, `http://192.168.0.17:4567`.
  Device: 960 x 672, BMP3 1-bit, refresh interval 20 s, recipe "Bus Board" (plugin id 1)
  with `data_stale_minutes = 0` set in the database. `/api/setup` only works for a device
  that has never refreshed, so the badge uses the stored token and skips setup.
- bustimes (`~/bustimes`, `:3000`) is the data source; see that repo's `CLAUDE.md`.
- To inspect or change LaraPaper: `sudo docker compose exec -T app php artisan tinker --execute="..."`
  from `~/larapaper`.

## Testing

- `python3 trmnl/tests/test_bmp.py [real.bmp ...]` tests the BMP decoder on the host.
- There is no MicroPython on the dev machine and the simulator has no WiFi, so network and
  panel behaviour are checked on the badge via the serial log.
- To reproduce what the badge fetches: call `/api/display` with `ID` and `Access-Token`
  headers, download `image_url`, and decode it with `decode_bmp`.
