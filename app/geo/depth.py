"""Lookup and bounded 100 m aggregation of retrospective EMSN194 HAND grids."""
import json
import math
import struct
import zlib
from functools import lru_cache
from pathlib import Path
from app.config import ROOT

ATTRIBUTION = "Copernicus Emergency Management Service (© 2024 European Union), EMSN194"
CONFIDENCE = "baixa — estimativa HAND ±1 m, retrospectiva"
REASON = "HAND a 20 m; produto criado em 12/06/2024, posterior ao evento; pode subestimar profundidade; sem dado não significa seco."
DATES = ('2024-05-06', '2024-05-08')

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



def band(depth):
    if depth is None: return 'unknown'
    from app.fleet import document
    for b in document()['depth_bands']:
        lo, hi = b['min_inclusive_m'], b['max_exclusive_m']
        if lo is None: continue
        if (depth > lo if b.get('lower_exclusive') else depth >= lo) and (hi is None or (depth <= hi if b.get('upper_inclusive') else depth < hi)):
            return b['id']
    return 'unknown'


class DepthGrid:
    def __init__(self, header, data):
        self.h, self.data = header, data
        if len(data) != header['width'] * header['height'] * 2:
            raise ValueError('Invalid depth grid length')

    @classmethod
    def load(cls, folder, day):
        folder = Path(folder)
        return cls(json.loads((folder / ('depth_'+day+'.json')).read_text(encoding='utf-8')),
                   zlib.decompress((folder / ('depth_'+day+'.u16.zlib')).read_bytes()))

    def nearest(self, lon, lat, radius=60):
        x, y = lonlat_to_utm22s(lon, lat)
        h = self.h; p = h['pixel_m']; w = h['width']; height = h['height']
        col, row = math.floor((x-h['origin_x'])/p), math.floor((h['origin_y']-y)/p)
        n = math.ceil(radius/p); best = None
        for r in range(max(0,row-n), min(height,row+n+1)):
            for c in range(max(0,col-n), min(w,col+n+1)):
                dist = math.hypot(h['origin_x']+(c+.5)*p-x, h['origin_y']-(r+.5)*p-y)
                if dist > radius: continue
                cm = struct.unpack_from('<H', self.data, 2*(r*w+c))[0]
                if cm == 65535: continue
                item = (dist, r, c, cm/100)
                if best is None or item < best: best = item
        return {'depth_m':best[3], 'distance_m':round(best[0],1)} if best else {'depth_m':None, 'distance_m':None}


@lru_cache(maxsize=2)
def grid(day):
    return DepthGrid.load(ROOT/'data/depth', day)


def lookup(lon, lat, day):
    from app.geo.hazards import replay_day
    replay_day(day)
    by_date = {d:grid(d).nearest(lon,lat) for d in DATES if d<=day}
    observed = max(by_date, default=None)
    selected = by_date[observed] if observed else {'depth_m':None, 'distance_m':None}
    depth = selected['depth_m']
    return {'depth_m':depth, 'depth_status':'estimada' if depth is not None else 'desconhecida',
            'depth_band':band(depth), 'depth_distance_m':selected['distance_m'], 'depth_observed_date':observed,
            'depth_by_date':by_date, 'depth_confidence':CONFIDENCE, 'depth_confidence_reason':REASON,
            'depth_source':ATTRIBUTION, 'depth_retrospective':True}


def utm22s_to_lonlat(x,y,precision=6):
    # WGS84 inverse transverse Mercator, standard series.
    a=6378137.; e2=0.0066943799901413165; ep2=e2/(1-e2); k=.9996
    m=(y-10000000)/k; mu=m/(a*(1-e2/4-3*e2**2/64-5*e2**3/256))
    e1=(1-math.sqrt(1-e2))/(1+math.sqrt(1-e2))
    phi=mu+(3*e1/2-27*e1**3/32)*math.sin(2*mu)+(21*e1**2/16-55*e1**4/32)*math.sin(4*mu)+151*e1**3/96*math.sin(6*mu)+1097*e1**4/512*math.sin(8*mu)
    t=math.tan(phi)**2; c=ep2*math.cos(phi)**2
    n=a/math.sqrt(1-e2*math.sin(phi)**2); r=a*(1-e2)/(1-e2*math.sin(phi)**2)**1.5; d=(x-500000)/(n*k)
    lat=phi-n*math.tan(phi)/r*(d*d/2-(5+3*t+10*c-4*c*c-9*ep2)*d**4/24+(61+90*t+298*c+45*t*t-252*ep2-3*c*c)*d**6/720)
    lon=math.radians(-51)+(d-(1+2*t+c)*d**3/6+(5-2*c+28*t-3*c*c+8*ep2+24*t*t)*d**5/120)/math.cos(phi)
    return round(math.degrees(lon),precision),round(math.degrees(lat),precision)


@lru_cache(maxsize=2)
def aggregated(day):
    g=grid(day); h=g.h; w=h['width']; maxima={}
    for i,(cm,) in enumerate(struct.iter_unpack('<H',g.data)):
        if cm==65535: continue
        r,c=divmod(i,w); key=(c//5,r//5)
        maxima[key]=max(maxima.get(key,0),cm)
    cells=[]
    for (c,r),cm in sorted(maxima.items()):
        lon,lat=utm22s_to_lonlat(h['origin_x']+(c+.5)*100,h['origin_y']-(r+.5)*100)
        cells.append((lon,lat,band(cm/100),cm/100))
    return cells


def depth_data(day, bbox):
    from app.geo.hazards import replay_day
    replay_day(day)
    try: bounds=[float(v) for v in bbox.split(',')]
    except (AttributeError, ValueError): raise ValueError('bbox must be west,south,east,north') from None
    if len(bounds)!=4 or not all(math.isfinite(v) for v in bounds): raise ValueError('Invalid bbox')
    west,south,east,north=bounds
    if not (-180<=west<east<=180 and -90<=south<north<=90): raise ValueError('Invalid bbox')
    observed=max((d for d in DATES if d<=day),default=None)
    cells=[list(c) for c in aggregated(observed) if west<=c[0]<=east and south<=c[1]<=north] if observed else []
    if len(cells)>50000: raise ValueError('Too many cells; narrow bbox')
    return {'date':day,'observation_date':observed,'cell_m':100,'crs':'EPSG:4326',
            'columns':['lon','lat','band','max_depth_m'],'cells':cells,'missing':'desconhecida',
            'retrospective':True,'confidence':CONFIDENCE,'source':ATTRIBUTION}
