"""Write a PNG of random pixels close to a given size, for the image scenarios of the device matrix.

    python3 tools/bench/make_test_png.py 5000000 image-5mb.png

Random pixels do not compress, so the file stays near the requested size after the apps re-encode it (PNG and
JPEG are sent as is; other formats become PNG, 04-clipboard CLIP-03). Standard library only.
"""

import os
import struct
import sys
import zlib


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    target, path = int(sys.argv[1]), sys.argv[2]
    side = max(1, int((target / 3) ** 0.5))  # RGB, 3 bytes per pixel
    rows = b"".join(b"\x00" + os.urandom(side * 3) for _ in range(side))  # filter byte 0 on every row
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))
    with open(path, "wb") as out:
        out.write(png)
    print(f"{path}: {side}x{side} pixels, {len(png)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
