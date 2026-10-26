"""Lazy offline ODbL road graph access; no routing or passability claims.

Coordinates in stored polylines/nodes are [lon, lat]. Public lookup arguments
are (lat, lon). Depth and launch estimates retain retrospective provenance.
"""
import datetime as dt
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path

from app.config import ROOT

DEFAULT_PATH = ROOT / 'data/roads/graph.json.gz'


def _point(lat, lon):
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Invalid latitude/longitude')
    return lat, lon


def _distance(lon1, lat1, lon2, lat2):
    a, b, c, d = map(math.radians, (lon1, lat1, lon2, lat2))
    return 12742000 * math.asin(min(1, math.sqrt(math.sin((d-b)/2)**2 +
        math.cos(b)*math.cos(d)*math.sin((c-a)/2)**2)))


def _edge_distance(lat, lon, polyline):
    scale = math.cos(math.radians(lat))*111195
    best = float('inf')
    for a,b in zip(polyline,polyline[1:]):
        ax,ay = (a[0]-lon)*scale,(a[1]-lat)*111195
        bx,by = (b[0]-lon)*scale,(b[1]-lat)*111195
        dx,dy = bx-ax,by-ay
        t = max(0,min(1,-(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx or dy else 0
        best = min(best,math.hypot(ax+t*dx,ay+t*dy))
    return best


class RoadNetwork:
    def __init__(self, document):
        if document.get('schema_version') != 1 or document.get('coordinate_order') != 'lon,lat':
            raise ValueError('Unsupported road graph format')
        self.document = document
        self.nodes = {}
        self.edges = []
        for graph in document['graphs']:
            for node, point in graph['nodes'].items():
                self.nodes.setdefault(node, {'id':node,'lon':point[0],'lat':point[1],
                    'municipality':graph['municipality'],
                    'routing_eligible':graph.get('routing_eligible',True),
                    'synthetic_node_id':graph.get('synthetic_node_ids',False)})
            self.edges.extend(graph['edges'])

    def nearest_node(self, lat, lon):
        lat,lon = _point(lat,lon)
        if not self.nodes:
            return None
        node = min(self.nodes.values(), key=lambda n:(_distance(lon,lat,n['lon'],n['lat']),n['id']))
        return dict(node, distance_m=round(_distance(lon,lat,node['lon'],node['lat']),2))

    def edges_near(self, lat, lon, radius_m=100):
        lat,lon = _point(lat,lon)
        if not math.isfinite(radius_m) or radius_m < 0:
            raise ValueError('Invalid radius')
        hits = []
        for edge in self.edges:
            dist = _edge_distance(lat,lon,edge['polyline'])
            if dist <= radius_m:
                hits.append(dict(edge,distance_m=round(dist,2)))
        return sorted(hits,key=lambda e:(e['distance_m'],e['municipality'],e['id']))

    def launch_points(self, date):
        if not isinstance(date,str) or dt.date.fromisoformat(date).isoformat() != date:
            raise ValueError('Date must be YYYY-MM-DD')
        available = self.document.get('launch_points',{})
        observed = max((d for d in available if d <= date),default=None)
        # Select one observation, never union stale estimates into a later layer.
        return [dict(p) for p in available[observed]] if observed else []


@lru_cache(maxsize=4)
def load(path=None):
    """Load only on first use. Missing data raises, never fabricates an empty graph."""
    path = Path(path) if path is not None else DEFAULT_PATH
    raw = path.read_bytes()
    return RoadNetwork(json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw))


def nearest_node(lat, lon):
    return load().nearest_node(lat,lon)


def edges_near(lat, lon, radius_m=100):
    return load().edges_near(lat,lon,radius_m)


def launch_points(date):
    return load().launch_points(date)
