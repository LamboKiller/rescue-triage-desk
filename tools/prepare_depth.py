"""Decode the Copernicus EMSN194 WaterDepth GeoTIFFs (tiled, LZW, float32, UTM 22S) with the standard library only,
and write a compact depth grid (uint16 centimetres, 0xFFFF = no data) + JSON header. Also: lon/lat -> UTM 22S and lookup.

python tools/prepare_depth.py --src <folder with EMSN194_*_WaterDepth_v01.tif> --out data/depth
"""
import argparse
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

NODATA_CM = 0xFFFF


def lzw_decode(data):
    """TIFF LZW (MSB-first, early change)."""
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b'', b'']
    bitpos, nbits, prev = 0, 9, None
    total = len(data) * 8
    while bitpos + nbits <= total:
        byte = bitpos >> 3
        chunk = int.from_bytes(data[byte:byte + 4].ljust(4, b'\0'), 'big')
        code = (chunk >> (32 - (bitpos & 7) - nbits)) & ((1 << nbits) - 1)
        bitpos += nbits
        if code == 256:  # clear
            table = table[:258]
            nbits, prev = 9, None
            continue
        if code == 257:  # end of information
            break
        if prev is None:
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        prev = entry
        if len(table) + 1 >= (1 << nbits) and nbits < 12:
            nbits += 1
    return bytes(out)


def read_tiff(path):
    raw = Path(path).read_bytes()
    order = '<' if raw[:2] == b'II' else '>'
    if struct.unpack(order + 'H', raw[2:4])[0] != 42:
        raise ValueError('not a classic TIFF')
    ifd = struct.unpack(order + 'I', raw[4:8])[0]
    count = struct.unpack(order + 'H', raw[ifd:ifd + 2])[0]
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
    fmt = {1: 'B', 2: 'c', 3: 'H', 4: 'I', 5: 'II', 11: 'f', 12: 'd', 16: 'Q'}
    tags = {}
    for i in range(count):
        e = ifd + 2 + 12 * i
        tag, typ, n = struct.unpack(order + 'HHI', raw[e:e + 8])
        size = sizes[typ] * n
        off = e + 8 if size <= 4 else struct.unpack(order + 'I', raw[e + 8:e + 12])[0]
        if typ == 2:
            tags[tag] = raw[off:off + n].rstrip(b'\0').decode('latin-1')
        else:
            tags[tag] = list(struct.unpack(order + fmt[typ] * n, raw[off:off + size]))
    w, h = tags[256][0], tags[257][0]
    assert tags[259][0] == 5 and tags[258][0] == 32 and tags[339][0] == 3, 'expect LZW float32'
    assert tags.get(317, [1])[0] == 1, 'predictor not supported'
    tw, th = tags[322][0], tags[323][0]
    offsets, counts = tags[324], tags[325]
    across = math.ceil(w / tw)
    grid = [NODATA_CM] * (w * h)
    nodata = float(tags.get(42113, '-9999'))
    for t, (off, n) in enumerate(zip(offsets, counts)):
        tx, ty = (t % across) * tw, (t // across) * th
        if ty >= h:
            break
        vals = struct.unpack(order + 'f' * (tw * th), lzw_decode(raw[off:off + n])[:tw * th * 4].ljust(tw * th * 4, b'\0'))
        for r in range(th):
            y = ty + r
            if y >= h:
                break
            base = y * w
            for c in range(tw):
                x = tx + c
                if x >= w:
                    break
                v = vals[r * tw + c]
                if v != nodata and v == v and v >= 0:
                    grid[base + x] = min(65534, int(round(v * 100)))
    scale, tie = tags[33550], tags[33922]
    return {'width': w, 'height': h, 'pixel_m': scale[0], 'origin_x': tie[3], 'origin_y': tie[4]}, grid


def lonlat_to_utm22s(lon, lat):
    """WGS84 -> UTM zone 22S (EPSG:32722), standard Krüger series (cm-level)."""
    a, f = 6378137.0, 1 / 298.257223563
    k0, lon0 = 0.9996, math.radians(-51.0)
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    A = math.cos(phi) * (lam - lon0)
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * n * (A + (1 - t + c) * A ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * A ** 5 / 120) + 500000.0
    y = k0 * (m + n * math.tan(phi) * (A * A / 2 + (5 - t + 9 * c + 4 * c * c) * A ** 4 / 24
                                        + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * A ** 6 / 720)) + 10000000.0
    return x, y


class DepthGrid:
    def __init__(self, header, data):
        self.h, self.data = header, data

    @classmethod
    def load(cls, folder, date):
        folder = Path(folder)
        header = json.loads((folder / ('depth_' + date + '.json')).read_text(encoding='utf-8'))
        data = zlib.decompress((folder / ('depth_' + date + '.u16.zlib')).read_bytes())
        return cls(header, data)

    def depth_m(self, lon, lat):
        """Nearest native cell. None = outside raster or no data (unknown, never 'dry')."""
        x, y = lonlat_to_utm22s(lon, lat)
        col = int((x - self.h['origin_x']) / self.h['pixel_m'])
        row = int((self.h['origin_y'] - y) / self.h['pixel_m'])
        if not (0 <= col < self.h['width'] and 0 <= row < self.h['height']):
            return None
        i = 2 * (row * self.h['width'] + col)
        cm = int.from_bytes(self.data[i:i + 2], 'little')
        return None if cm == NODATA_CM else cm / 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=Path('data/depth'))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, date in (('P04FLDEL01', '2024-05-06'), ('P04FLDEL02', '2024-05-08')):
        tif = args.src / ('EMSN194_STD_AOI01_' + name + '_WaterDepth_v01.tif')
        header, grid = read_tiff(tif)
        (args.out / ('depth_' + date + '.u16.zlib')).write_bytes(zlib.compress(struct.pack('<' + 'H' * len(grid), *grid), 9))
        valid = [v for v in grid if v != NODATA_CM]
        header.update(date_observed=date, unit='m (stored as zlib-compressed little-endian uint16 cm, row-major from top-left, 65535 = no data)', crs='EPSG:32722',
                      source='Copernicus EMS EMSN194 ' + name + ' WaterDepth v01 (HAND method, 20 m)',
                      attribution='Copernicus Emergency Management Service (© 2024 European Union), EMSN194',
                      retrospective='product created 2024-06-12; not available during the event',
                      source_sha256=hashlib.sha256(tif.read_bytes()).hexdigest(),
                      valid_cells=len(valid), max_m=max(valid) / 100 if valid else None)
        (args.out / ('depth_' + date + '.json')).write_text(json.dumps(header, indent=2) + '\n', encoding='utf-8')
        print(date, header['width'], 'x', header['height'], 'valid cells', len(valid), 'max m', header['max_m'])


if __name__ == '__main__':
    main()
