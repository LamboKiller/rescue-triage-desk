"""Prepare offline, premultiplied bilinear HAND imagery. Python stdlib only.

Run from the repository: python tools/prepare_water_tiles.py
Unknown native pixels remain transparent; colours never establish dry access.
"""
import json
import math
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.geo.depth import DATES, grid, lonlat_to_utm22s, utm22s_to_lonlat

# Existing fleet thresholds merged into four display bands, in metres.
BANDS = [(0, .3, '#b5dcf5'), (.3, 1.2, '#76b5df'),
         (1.2, 2.5, '#398ac1'), (2.5, None, '#155a94')]


def rgba(g, lon, lat):
    x, y = lonlat_to_utm22s(lon, lat)
    h = g.h
    cx = (x-h['origin_x'])/h['pixel_m']-.5
    cy = (h['origin_y']-y)/h['pixel_m']-.5
    c, r = math.floor(cx), math.floor(cy)
    # Do not fill unknown pixels with adjacent valid observations.
    nc, nr = math.floor(cx+.5), math.floor(cy+.5)
    def value(col, row):
        if not (0 <= col < h['width'] and 0 <= row < h['height']):
            return None
        cm = struct.unpack_from('<H', g.data, 2*(row*h['width']+col))[0]
        return None if cm == 65535 else cm/100
    if value(nc, nr) is None:
        return b'\0\0\0\0'
    weights, depth = 0., 0.
    for dc, dr, weight in [(0,0,(1-(cx-c))*(1-(cy-r))), (1,0,(cx-c)*(1-(cy-r))),
                           (0,1,(1-(cx-c))*(cy-r)), (1,1,(cx-c)*(cy-r))]:
        v = value(c+dc, r+dr)
        if v is not None:
            weights += weight
            depth += v*weight
    v = depth/weights
    color = next(color for lo, hi, color in BANDS if hi is None or v < hi or hi == 2.5 and v == hi)
    return bytes.fromhex(color[1:]) + bytes([round(255*weights)])


def png(width, height, rows):
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width,height,8,6,0,0,0))
            +chunk(b'IDAT', zlib.compress(b''.join(b'\0'+row for row in rows), 9))+chunk(b'IEND', b''))


def main():
    folder = ROOT/'data/map3d/water'
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for day in DATES:
        g = grid(day)
        h = g.h
        corners = [utm22s_to_lonlat(h['origin_x']+c*h['pixel_m'], h['origin_y']-r*h['pixel_m'])
                   for c, r in [(0,0),(h['width'],0),(h['width'],h['height']),(0,h['height'])]]
        west, east = min(p[0] for p in corners), max(p[0] for p in corners)
        south, north = min(p[1] for p in corners), max(p[1] for p in corners)
        merc = lambda lat: math.asinh(math.tan(math.radians(lat)))
        top, bottom = merc(north), merc(south)
        width = 768
        height = round(width*(top-bottom)/math.radians(east-west))
        rows = []
        for row in range(height):
            lat = math.degrees(math.atan(math.sinh(top+(bottom-top)*(row+.5)/height)))
            rows.append(b''.join(rgba(g, west+(east-west)*(col+.5)/width, lat) for col in range(width)))
        asset = folder/(day+'.png')
        asset.write_bytes(png(width,height,rows))
        assert asset.stat().st_size <= 3_000_000
        entries.append({'observation_date':day, 'published_at':h.get('published_at'),
                        'created_at':'2024-06-12', 'publication_note':'Publication date absent in source metadata; creation is not publication.',
                        'url':'/v2/map/water/'+asset.name, 'bytes':asset.stat().st_size,
                        'coordinates':[[west,north],[east,north],[east,south],[west,south]],
                        'source':h['attribution'], 'retrospective':True})
        print(day, width, height, asset.stat().st_size)
    manifest = {'bands':[{'min_m':lo,'max_m':hi,'color':color,'upper_inclusive':hi == 2.5,
                          'label':('> 2,5 m' if hi is None else '1,2–2,5 m (inclusive)' if hi == 2.5
                                   else f'{lo:g}–< {hi:g} m'.replace('.',','))} for lo,hi,color in BANDS],
                'missing':'Sem dado não significa seco; pixels transparentes.', 'images':entries}
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
