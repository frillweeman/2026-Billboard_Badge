"""TRMNL (BYOS) client: shows pages served by a TRMNL-compatible server.

Talks the TRMNL device protocol (GET /api/setup, GET /api/display, then the
image at image_url) so a self-hosted server such as LaraPaper can cycle pages
(bus times, calendar, ...) on the badge. Uses the fast partial refresh driver
(lib/epd_partial.py), so it is black and white only.

Config:
  data/wlan_credentials.json  [{"ssid": "...", "key": "..."}]  (same as http_poller)
  data/trmnl.json             see trmnl.sample.json
"""

import asyncio as aio
import gc
import os
import struct
import sys

import network
import requests
from ubinascii import hexlify

from apps.base_app import BaseApp
from lib.board import reg_in_v_sns
from lib.epd_partial import PartialEPD
from lib.json_configs import load, store
from lib.large_png import show_png

WLAN_CREDENTIALS_FILE = "data/wlan_credentials.json"
CONFIG_FILE = "data/trmnl.json"
FW_VERSION = "badge-trmnl-0.1"
WIDTH = 960
HEIGHT = 672
PLANE_BYTES = WIDTH * HEIGHT // 8

DEFAULTS = {
    "server": "",           # e.g. "http://192.168.1.10:4567" (no trailing slash)
    "api_key": "",          # filled in by /api/setup
    "clean_every": 20,      # black/white flash every N new pages, against ghosting
    "min_refresh": 30,      # never poll faster than this many seconds
    "retry": 30,            # wait this long after a failed cycle
}


def decode_bmp(data, buf):
    """Copy an uncompressed 1-bit BMP into buf (960 x 672, MONO_HLSB, 1 = black).

    This is TRMNL's native image format (what "BMP3 1-bit" servers send). Rows
    are byte-aligned in both formats, so each row is a slice copy, inverted
    when the file's palette makes bit 1 white. Images smaller than the panel
    are placed top-left (width must be a multiple of 8); buf should be cleared.
    """
    if data[:2] != b"BM":
        raise ValueError("not a BMP")
    offset, header = struct.unpack_from("<II", data, 10)
    width, height, _planes, bpp, compression = struct.unpack_from("<iiHHI", data, 18)
    if bpp != 1 or compression != 0 or header < 40:
        raise ValueError("need an uncompressed 1-bit BMP (BMP3 1-bit)")
    top_down = height < 0
    height = abs(height)
    if width % 8 or width > WIDTH or height > HEIGHT:
        raise ValueError("BMP is %dx%d, panel is %dx%d" % (width, height, WIDTH, HEIGHT))
    pal = 14 + header
    # Palette entries are B, G, R, 0. Bit 1 is black when entry 1 is the darker one.
    invert = sum(data[pal + 4:pal + 7]) >= sum(data[pal:pal + 3])
    stride = ((width + 31) // 32) * 4
    wb = width // 8
    mask = int.from_bytes(b"\xff" * wb, "big")
    row_bytes = WIDTH // 8
    for y in range(height):
        src = offset + (y if top_down else height - 1 - y) * stride
        row = bytes(data[src:src + wb])
        if invert:
            row = (int.from_bytes(row, "big") ^ mask).to_bytes(wb, "big")
        dst = y * row_bytes
        buf[dst:dst + wb] = row


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class TrmnlApp(BaseApp):
    def __init__(self, name: str | None = None) -> None:
        super().__init__("TRMNL")
        self.nic = network.WLAN(network.WLAN.IF_STA)
        self.panel = PartialEPD()
        self.task = None
        self.cfg = dict(DEFAULTS)
        self.last_filename = None
        self.pages = 0

    # ---- app lifecycle -----------------------------------------------------

    def run(self):
        # Called repeatedly by the app switcher; must return quickly.
        if self.launched and self.task is None:
            self.task = aio.create_task(self._main())

    def on_exit(self):
        """Leaving for the menu: stop and hand the panel back to the stock driver."""
        if self.task is not None:
            self.task.cancel()
            self.task = None

    # ---- config ------------------------------------------------------------

    def _load_config(self):
        cfg = dict(DEFAULTS)
        cfg.update(load(CONFIG_FILE))
        cfg["server"] = cfg["server"].rstrip("/")
        self.cfg = cfg
        if not cfg["server"]:
            raise ValueError("data/trmnl.json needs a \"server\" URL")

    def _save_api_key(self, key):
        self.cfg["api_key"] = key
        try:
            saved = load(CONFIG_FILE)
        except Exception:
            saved = {}
        saved["api_key"] = key
        store(saved, CONFIG_FILE)

    # ---- main task ---------------------------------------------------------

    async def _main(self):
        try:
            self._load_config()
            await self.panel.start()
            self.last_filename = None
            self.pages = 0
            while True:
                delay = self.cfg["retry"]
                try:
                    delay = await self._cycle()
                except Exception as ex:
                    print("trmnl: cycle failed:", ex)
                    sys.print_exception(ex)
                    self._wifi_off()
                gc.collect()
                await aio.sleep(delay)
        except Exception as ex:
            print("trmnl: stopped:", ex)
            sys.print_exception(ex)
        finally:
            self._wifi_off()
            try:
                await self.panel.stop()
            except Exception as ex:
                sys.print_exception(ex)

    async def _cycle(self):
        """One pass: ask the server, fetch the image if it changed, show it. Returns seconds to wait."""
        battery = self._battery_volts()   # before WiFi: the pin is on ADC2
        await self._connect()
        mac = hexlify(self.nic.config("mac"), ":").decode().upper()
        png = None
        refresh = self.cfg["retry"]
        try:
            if not self.cfg["api_key"]:
                self._setup(mac)
            info = self._display(mac, battery)
            refresh = max(_int(info.get("refresh_rate"), 60), self.cfg["min_refresh"])
            url = info.get("image_url")
            name = info.get("filename") or url
            if url and name != self.last_filename:
                png = self._download(url)
                self.last_filename = name
        finally:
            self._wifi_off()

        if png is not None:
            await self._show(png)
        return refresh

    # ---- WiFi --------------------------------------------------------------

    async def _connect(self):
        self.nic.active(True)
        if self.nic.isconnected():
            return
        for cred in load(WLAN_CREDENTIALS_FILE):
            print("trmnl: connecting to", cred["ssid"])
            try:
                self.nic.connect(cred["ssid"], cred["key"])
            except Exception as ex:
                sys.print_exception(ex)
                continue
            for _ in range(40):
                if self.nic.isconnected():
                    print("trmnl: connected, ip", self.nic.ipconfig("addr4"))
                    return
                await aio.sleep_ms(250)
        raise OSError("could not join any configured WiFi network")

    def _wifi_off(self):
        try:
            if self.nic.active():
                self.nic.disconnect()
                self.nic.active(False)
        except Exception:
            pass

    def _battery_volts(self):
        try:
            return reg_in_v_sns.read_uv() * 2 / 1000000   # 1/2 divider on the board
        except Exception:
            return 0.0

    # ---- TRMNL protocol ----------------------------------------------------

    def _get_json(self, path, headers):
        url = self.cfg["server"] + path
        print("trmnl: GET", url)
        r = requests.get(url, headers=headers)
        try:
            if r.status_code == 404:
                return None
            if not 200 <= r.status_code < 300:
                raise OSError("%s: HTTP %d" % (path, r.status_code))
            return r.json()
        finally:
            r.close()

    def _setup(self, mac):
        """GET /api/setup: the server hands out an api_key for this MAC."""
        data = self._get_json("/api/setup", {"ID": mac, "FW-Version": FW_VERSION, "Model": "badge"})
        key = data.get("api_key") if data else None
        if not key:
            # Servers with auto-join (LaraPaper) register the device on the first
            # /api/display call, so invent a token and let them keep it.
            key = hexlify(os.urandom(11)).decode()
            print("trmnl: setup gave no api_key, using a generated one")
        self._save_api_key(key)

    def _display(self, mac, battery):
        """GET /api/display: which image to show and when to come back."""
        headers = {
            "ID": mac,
            "Access-Token": self.cfg["api_key"],
            "Width": str(WIDTH),
            "Height": str(HEIGHT),
            "FW-Version": FW_VERSION,
            "Battery-Voltage": "%.2f" % battery,
            "RSSI": str(self.nic.status("rssi")),
            "Refresh-Rate": str(self.cfg["min_refresh"]),
        }
        info = self._get_json("/api/display", headers)
        if info is None:
            # Server doesn't know this key (new server or wiped DB): set up again next cycle.
            self._save_api_key("")
            raise OSError("server does not know this device (404)")
        print("trmnl: display ->", info)
        return info

    def _download(self, url):
        print("trmnl: GET", url)
        r = requests.get(url)
        try:
            if not 200 <= r.status_code < 300:
                raise OSError("image: HTTP %d" % r.status_code)
            return r.content
        finally:
            r.close()

    # ---- display -----------------------------------------------------------

    async def _show(self, png):
        panel = self.panel
        if self.pages and self.pages % self.cfg["clean_every"] == 0:
            print("trmnl: periodic clean")
            await panel.restart(wipe=True)
        panel.clear()
        if png[:2] == b"BM":
            decode_bmp(png, panel.buf)
        else:
            red = bytearray(PLANE_BYTES)   # show_png wants a red plane; 1-bit pages never use it
            show_png(None, panel.buf, red, data=png)
            del red
        del png
        gc.collect()
        ms = await panel.show()
        self.pages += 1
        print("trmnl: page %d shown in %d ms" % (self.pages, ms))
