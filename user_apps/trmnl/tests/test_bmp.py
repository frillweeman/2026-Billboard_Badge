"""Host test (CPython) for decode_bmp in ../trmnl.py.

    python3 user_apps/trmnl/tests/test_bmp.py [path/to/real.bmp ...]

trmnl.py imports MicroPython-only modules, so the function is lifted out of the
source with ast instead of importing the module.
"""
import ast
import struct
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "trmnl.py"
tree = ast.parse(SRC.read_text())
wanted = [n for n in tree.body
          if (isinstance(n, ast.FunctionDef) and n.name == "decode_bmp")
          or (isinstance(n, ast.Assign) and n.targets[0].id in ("WIDTH", "HEIGHT"))]
ns = {"struct": struct}
exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SRC), "exec"), ns)
decode_bmp, W, H = ns["decode_bmp"], ns["WIDTH"], ns["HEIGHT"]
ROW = W // 8


def make_bmp(width, height, pixel, black_first=True, top_down=False):
    """pixel(x, y) -> True for black. Uncompressed 1-bit BMP like a BMP3 writer makes."""
    stride = ((width + 31) // 32) * 4
    rows = []
    for y in range(height):
        bits = bytearray(stride)
        for x in range(width):
            black = pixel(x, y)
            bit = (0 if black else 1) if black_first else (1 if black else 0)
            if bit:
                bits[x // 8] |= 0x80 >> (x % 8)
        rows.append(bytes(bits))
    if not top_down:
        rows.reverse()
    pal = bytes((0, 0, 0, 0, 255, 255, 255, 0)) if black_first else bytes((255, 255, 255, 0, 0, 0, 0, 0))
    off = 14 + 40 + 8
    head = b"BM" + struct.pack("<IHHI", off + stride * height, 0, 0, off)
    info = struct.pack("<IiiHHIIiiII", 40, width, -height if top_down else height, 1, 1, 0, stride * height, 0, 0, 2, 2)
    return head + info + pal + b"".join(rows)


def pix(buf, x, y):
    return bool(buf[y * ROW + x // 8] & (0x80 >> (x % 8)))


class DecodeBmp(unittest.TestCase):
    def check(self, bmp, width, height, pixel):
        buf = bytearray(ROW * H)
        decode_bmp(bmp, buf)
        for y in range(H):
            for x in range(W):
                want = pixel(x, y) if (x < width and y < height) else False
                self.assertEqual(pix(buf, x, y), want, (x, y))

    def test_variants(self):
        f = lambda x, y: (x * 7 + y * 3) % 5 < 2 or (x < 9 and y < 4)
        for black_first in (True, False):
            for top_down in (False, True):
                with self.subTest(black_first=black_first, top_down=top_down):
                    self.check(make_bmp(W, H, f, black_first, top_down), W, H, f)

    def test_smaller_image_top_left(self):
        f = lambda x, y: (x + y) % 3 == 0
        self.check(make_bmp(800, 480, f), 800, 480, f)

    def test_rejects(self):
        buf = bytearray(ROW * H)
        with self.assertRaises(ValueError):
            decode_bmp(b"\x89PNG....", buf)
        bad = bytearray(make_bmp(16, 2, lambda x, y: False))
        struct.pack_into("<H", bad, 28, 8)   # 8 bpp
        with self.assertRaises(ValueError):
            decode_bmp(bytes(bad), buf)


class RealFiles(unittest.TestCase):
    def test_real(self):
        for path in sys.argv[1:]:
            with self.subTest(path=path):
                data = Path(path).read_bytes()
                buf = bytearray(ROW * H)
                decode_bmp(data, buf)
                ink = sum(bin(b).count("1") for b in buf)
                print(f"{path}: {ink} black pixels of {W * H}")
                self.assertGreater(ink, 0)
                self.assertLess(ink, W * H // 2)   # a logo on white, not an inverted page


if __name__ == "__main__":
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    sys.argv[1:] = files
    unittest.main(argv=[sys.argv[0]], verbosity=1)
