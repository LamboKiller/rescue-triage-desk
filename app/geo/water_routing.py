"""Bounded offline boat A* on exact HAND cells, never nearest-depth interpolation.

Unknown cells are considered only after connectivity proves no all-known route.
The 20 m model and conservative building raster are retrospective estimates, not
navigability certification. Search exhaustion is distinct from resource limits.
"""
from array import array
from bisect import bisect_right
from collections import OrderedDict
from functools import lru_cache
import gzip
import heapq
import json
import math
import re
import sys
import threading
import time

from app.config import ROOT
from app.geo import depth, roads
from app.geo.hazards import replay_day

LABEL = 'rota na água — estimativa (HAND retrospectivo)'
FALLBACK_LABEL = 'trecho na água em linha reta — estimativa (HAND retrospectivo)'
CLEARANCE_M = .1  # Author estimate, not an operational clearance standard.
UNKNOWN_PENALTY = 40
SNAP_M = 150
MAX_POINTS = 128
_LOCK = threading.RLock()


def _number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(name+' inválido.')
    return float(value)


def supercover(a, b):
    """All cells touched between cell centres, including both sides of corners."""
    x, y = a; bx, by = b
    dx, dy = bx-x, by-y; nx, ny = abs(dx), abs(dy)
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    ix = iy = 0
    yield x, y
    while ix < nx or iy < ny:
        cross = (1+2*ix)*ny - (1+2*iy)*nx
        if cross == 0:
            yield x+sx, y
            yield x, y+sy
            x += sx; y += sy; ix += 1; iy += 1
        elif cross < 0:
            x += sx; ix += 1
        else:
            y += sy; iy += 1
        yield x, y


@lru_cache(maxsize=1)
def building_mask(width, height, pixel, origin_x, origin_y):
    """Rasterise footprint row strips conservatively (any overlap blocks a cell).

    One compressed tile is decoded at a time. Concavities/holes may be overblocked;
    roofs never become navigable simply because a cell centre misses a small wall.
    Footprints have no historical observation date: explicitly retrospective.
    """
    mask = bytearray(width*height); seen = set(); count = 0
    paths = sorted((ROOT/'data/map3d/buildings').glob('*.geojson.gz'))
    for path in paths:
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            tile = json.load(stream)
        for f in tile.get('features', []):
            fid = f.get('id')
            if fid is not None and fid in seen: continue
            if fid is not None: seen.add(fid)
            g = f.get('geometry') or {}
            polygons = [g['coordinates']] if g.get('type') == 'Polygon' else g.get('coordinates', []) if g.get('type') == 'MultiPolygon' else []
            for poly in polygons:
                if not poly: continue
                ring = []
                for lon, lat, *_ in poly[0]:
                    x, y = depth.lonlat_to_utm22s(lon, lat)
                    ring.append(((x-origin_x)/pixel, (origin_y-y)/pixel))
                if len(ring) < 3: continue
                low = max(0, math.floor(min(y for x,y in ring)))
                high = min(height-1, math.floor(max(y for x,y in ring)))
                for row in range(low, high+1):
                    xs = []
                    for (ax,ay),(bx,by) in zip(ring, ring[1:]+ring[:1]):
                        lo, hi = max(min(ay,by),row), min(max(ay,by),row+1)
                        if lo > hi: continue
                        if ay == by: xs.extend((ax,bx))
                        else: xs.extend((ax+(lo-ay)*(bx-ax)/(by-ay), ax+(hi-ay)*(bx-ax)/(by-ay)))
                    if xs:
                        left=max(0,math.floor(min(xs))); right=min(width-1,math.floor(max(xs)))
                        if left <= right: mask[row*width+left:row*width+right+1] = b'\1'*(right-left+1)
                count += 1
        del tile
    return mask, {'files':len(paths), 'footprints':count, 'retrospective':True,
                  'basis':'conservative footprint row strips; partial geographic coverage'}


class Components:
    """Connected row runs, not Python objects for millions of cells.

    Four-way components exactly match eight-way search with no corner cutting.
    Regex scans the byte mask in C. Only runs/union labels are retained.
    """
    def __init__(self, states, width, height, unknown=False):
        self.rows = []; parents = [0]; previous = []
        table = bytes([0,1,1 if unknown else 0]+[0]*253)
        def root(i):
            while parents[i] != i:
                parents[i] = parents[parents[i]]; i = parents[i]
            return i
        for row in range(height):
            line = states[row*width:(row+1)*width].translate(table)
            runs = []; j = 0
            for match in re.finditer(b'\1+', line):
                lo, hi = match.start(), match.end()-1
                label = len(parents); parents.append(label)
                while j < len(previous) and previous[j][1] < lo: j += 1
                k = j
                while k < len(previous) and previous[k][0] <= hi:
                    a, b = root(label), root(previous[k][2]); parents[a] = b; k += 1
                runs.append((lo,hi,label))
            self.rows.append(runs); previous = runs
        for row, runs in enumerate(self.rows):
            self.rows[row] = ([lo for lo,hi,label in runs], [hi for lo,hi,label in runs],
                              [root(label) for lo,hi,label in runs])

    def at(self, col, row):
        starts, ends, labels = self.rows[row]
        i = bisect_right(starts,col)-1
        return labels[i] if i >= 0 and col <= ends[i] else None


class WaterRouter:
    def __init__(self, grid, buildings=None, building_info=None):
        self.grid = grid; self.h = grid.h; self.w = self.h['width']; self.height = self.h['height']
        self.p = self.h['pixel_m']; self.buildings = buildings if buildings is not None else bytearray(self.w*self.height)
        self.building_info = building_info or {'basis':'injected mask', 'retrospective':True}
        if len(self.buildings) != self.w*self.height: raise ValueError('Invalid building mask')
        self.cm = array('H'); self.cm.frombytes(grid.data)
        if sys.byteorder != 'little': self.cm.byteswap()
        self.profiles = OrderedDict()

    def _profile(self, minimum):
        threshold = math.ceil(minimum*100-1e-9)
        if threshold not in self.profiles:
            states = bytearray(0 if self.buildings[i] else 2 if cm == 65535 else 1 if cm > 0 and cm >= threshold else 0
                               for i,cm in enumerate(self.cm))
            if len(self.profiles) >= 2: self.profiles.popitem(last=False)
            self.profiles[threshold] = (states, Components(states,self.w,self.height),
                                       Components(states,self.w,self.height,True))
        self.profiles.move_to_end(threshold)
        return threshold, self.profiles[threshold]

    def _xy(self, p):
        x, y = depth.lonlat_to_utm22s(p['lon'],p['lat'])
        return (x-self.h['origin_x'])/self.p-.5, (self.h['origin_y']-y)/self.p-.5

    def _candidates(self, xy, states, unknown=False):
        x,y=xy; c,r=math.floor(x+.5),math.floor(y+.5)
        state=states[r*self.w+c] if 0 <= c < self.w and 0 <= r < self.height else 0
        if state == 1 or (state == 2 and unknown): return [(0.,c,r)]
        n=math.ceil(SNAP_M/self.p); found=[]
        for row in range(max(0,r-n),min(self.height,r+n+1)):
            for col in range(max(0,c-n),min(self.w,c+n+1)):
                if states[row*self.w+col] != 1: continue
                dist=math.hypot(col-x,row-y)*self.p
                if dist <= SNAP_M: found.append((dist,col,row))
        return sorted(found)

    def _search(self, start, goal, states, unknown, deadline):
        w=self.w; height=self.height; gx,gy=goal; target=gy*w+gx
        sid=start[1]*w+start[0]; distances=[{sid:0.},{target:0.}]; previous=[{},{}]; costs={}
        def allowed(idx): return states[idx] == 1 or (unknown and states[idx] == 2)
        def penalty(idx):
            if idx not in costs:
                if states[idx] == 2: costs[idx]=UNKNOWN_PENALTY
                else:
                    r,c=divmod(idx,w)
                    edge=sum(not (0<=c+dx<w and 0<=r+dy<height) or states[(r+dy)*w+c+dx] != 1
                             for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))
                    # Prefer clearance from shallow shorelines even while both cells pass.
                    costs[idx]=1+edge*.5
            return costs[idx]
        def octile(c,r,point):
            dx,dy=abs(c-point[0]),abs(r-point[1])
            return max(dx,dy)+(math.sqrt(2)-1)*min(dx,dy)
        def potential(c,r): return (octile(c,r,goal)-octile(c,r,start))/2
        # Balanced, consistent potentials: two A* frontiers share a valid lower
        # bound. Costs are symmetric (distance * mean endpoint penalty).
        queues=[[(potential(*start),0.,sid)],[(-potential(*goal),0.,target)]]
        expanded=0;best=math.inf;meeting=None
        def result(limited):
            if meeting is None: return None,limited
            left=[meeting]
            while left[-1]!=sid: left.append(previous[0][left[-1]])
            path=list(reversed(left));idx=meeting
            while idx!=target:
                idx=previous[1][idx];path.append(idx)
            return path,limited
        if sid==target: return [sid],False
        while queues[0] and queues[1]:
            if expanded % 128 == 0 and (time.perf_counter() >= deadline or sum(map(len,distances))>60000):
                return result(True)
            for side in (0,1):
                while queues[side] and queues[side][0][1]!=distances[side].get(queues[side][0][2]):
                    heapq.heappop(queues[side])
            if not queues[0] or not queues[1]: break
            if queues[0][0][0]+queues[1][0][0]>=best: return result(False)
            side=0 if queues[0][0][0]<=queues[1][0][0] else 1
            _,dist,idx=heapq.heappop(queues[side])
            expanded += 1; r,c=divmod(idx,w); base=penalty(idx)
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)):
                nc,nr=c+dx,r+dy
                if not (0<=nc<w and 0<=nr<height): continue
                nxt=nr*w+nc
                if not allowed(nxt): continue
                if dx and dy and (not allowed(r*w+nc) or not allowed(nr*w+c)): continue
                nd=dist+(math.sqrt(2) if dx and dy else 1)*(base+penalty(nxt))/2
                if nd < distances[side].get(nxt,math.inf):
                    distances[side][nxt]=nd; previous[side][nxt]=idx
                    heapq.heappush(queues[side],(nd+(1 if side==0 else -1)*potential(nc,nr),nd,nxt))
                    joined=nd+distances[1-side].get(nxt,math.inf)
                    if joined<best: best=joined;meeting=nxt
        return result(False)

    def _smooth(self, path, states, unknown, deadline):
        cells=[(i%self.w,i//self.w) for i in path]
        def visible(a,b):
            return all(states[y*self.w+x] == 1 or (unknown and states[y*self.w+x] == 2) for x,y in supercover(a,b))
        out=[cells[0]]; anchor=0
        while anchor < len(cells)-1:
            if time.perf_counter() >= deadline: return None
            # Try long shortcuts first; halve on collision, then extend locally.
            step=len(cells)-1-anchor
            while step>1 and not visible(cells[anchor],cells[anchor+step]): step//=2
            end=anchor+step
            while end+1<len(cells) and visible(cells[anchor],cells[end+1]):
                end+=1
                if time.perf_counter() >= deadline: return None
            out.append(cells[end]);anchor=end
            if len(out)>MAX_POINTS: return None
        return out

    def route(self, a, b, draft_m=None, clearance_m=CLEARANCE_M, speed=12,
              speed_estimated=True, allow_unknown=True, max_seconds=.24):
        draft_estimated=draft_m is None
        draft=_number(.4 if draft_estimated else draft_m,'Calado')
        clearance=_number(clearance_m,'Margem'); speed=_number(speed,'Velocidade',True)
        base=dict(draft_m=draft,draft_estimated=draft_estimated,clearance_m=clearance,
                  clearance_estimated=True,minimum_depth_m=round(draft+clearance,6),speed_kph=speed,
                  speed_estimated=speed_estimated,observation_date=self.h.get('date_observed'),
                  buildings=self.building_info,retrospective=True,confidence='low',navigability_verified=False)
        threshold,(states,strict,soft)=self._profile(draft+clearance)
        # Profile/grid construction is cold work; query budget starts after preparation.
        deadline=time.perf_counter()+max_seconds
        xy_a,xy_b=self._xy(a),self._xy(b)
        chosen=None
        for unknown in (False,True) if allow_unknown else (False,):
            starts=self._candidates(xy_a,states,unknown); goals=self._candidates(xy_b,states,unknown)
            if not starts or not goals: continue
            comps=strict
            if unknown:
                if soft is None:
                    soft=Components(states,self.w,self.height,True)
                    self.profiles[threshold]=(states,strict,soft)
                comps=soft
                # Connectivity construction is also one-time cold work.
                deadline=time.perf_counter()+max_seconds
            by_component={}
            for dist,c,r in reversed(starts):
                by_component[comps.at(c,r)]=(dist,c,r)
            for end_dist,gc,gr in goals:
                start=by_component.get(comps.at(gc,gr))
                if start:
                    chosen=(start,(end_dist,gc,gr),unknown);break
            if chosen: break
        if not chosen:
            code='NO_WET_ENDPOINT' if not self._candidates(xy_a,states,True) or not self._candidates(xy_b,states,True) else 'NO_WATER_PATH'
            return fallback(a,b,base,code,'Sem caminho na grade para este calado/margem e os extremos (até 150 m).')
        start,goal,unknown=chosen
        # Reserve time for visibility shortcuts and export if a valid meeting
        # path exists before the optimality proof finishes.
        path,limited=self._search(start[1:],goal[1:],states,unknown,deadline-min(.03,max_seconds/5))
        cells=self._smooth(path,states,unknown,deadline) if path else None
        if (limited and not path) or (path and cells is None):
            return dict(base,basis='water_search_incomplete',fallback=False,grid_verified=False,
                        polyline=[],km=None,water_km=None,eta_min=None,water_eta_min=None,
                        min_depth_m=None,max_depth_m=None,unknown_samples=0,samples=0,
                        label_pt=LABEL,reason_codes=['SEARCH_LIMIT'],
                        review_pt=['REVISAR: busca aquática inconclusiva no limite de tempo/pontos; não é prova de ausência de caminho.'])
        if not path: return fallback(a,b,base,'NO_WATER_PATH','Sem caminho na grade para este calado/margem.')
        # Recheck the *smoothed* polyline, including side cells at diagonal corners.
        touched={y*self.w+x for p,q in zip(cells,cells[1:]) for x,y in supercover(p,q)}
        if len(cells)==1: touched.add(cells[0][1]*self.w+cells[0][0]);cells=cells*2
        known=[self.cm[i]/100 for i in touched if self.cm[i]!=65535]
        missing=sum(self.cm[i]==65535 for i in touched)
        length=sum(math.dist(p,q)*self.p for p,q in zip(cells,cells[1:]))
        polyline=[list(depth.utm22s_to_lonlat(self.h['origin_x']+(c+.5)*self.p,
                                            self.h['origin_y']-(r+.5)*self.p,precision=9)) for c,r in cells]
        start_gap=math.hypot(cells[0][0]-xy_a[0],cells[0][1]-xy_a[1])*self.p
        end_gap=math.hypot(cells[-1][0]-xy_b[0],cells[-1][1]-xy_b[1])*self.p
        codes=[];notes=['Confirmar correnteza, obstáculos, calado com carga e margem no local.']
        if draft_estimated: notes.append('Calado padrão estimado: 0,4 m; confirmar na unidade.')
        if speed_estimated: notes.append('Velocidade padrão estimada: %s km/h; confirmar na unidade.'%speed)
        notes.append('Margem estimada: %s m; HAND retrospectivo ±1 m, baixa confiança.'%clearance)
        if start[0]>0: codes.append('START_SHORE_ACCESS');notes.append('Acesso ao primeiro ponto molhado: %s m — confirmar lançamento/desembarque.'%round(start_gap,1))
        if goal[0]>0: codes.append('LAST_METRES_SHALLOW');notes.append('último trecho a pé/raso — confirmar (%s m).'%round(end_gap,1))
        if missing: codes.append('UNKNOWN_WATER');notes.append('trecho sem dado: usado somente após excluir caminho totalmente conhecido; não presumido navegável.')
        if limited: codes.append('SEARCH_LIMIT_VALID_PATH');notes.append('Caminho aquático verificado na grade; limite da busca atingido antes de provar custo mínimo.')
        km=round(length/1000,4);eta=round(length/(speed*1000/60),3)
        return dict(base,basis='depth_grid_water',fallback=False,grid_verified=not missing,tracking_eligible=not missing,
                    polyline=polyline,km=km,water_km=km,eta_min=eta,water_eta_min=eta,
                    min_depth_m=min(known,default=None),max_depth_m=max(known,default=None),
                    samples=len(touched),unknown_samples=missing,sampling_m=self.p,
                    start_gap_m=round(start_gap,1),end_gap_m=round(end_gap,1),
                    label_pt=LABEL,reason_codes=codes,review_pt=notes)


def fallback(a,b,base,code,reason):
    length=roads._distance(a['lon'],a['lat'],b['lon'],b['lat'])
    eta=round(length/(base['speed_kph']*1000/60),3);km=round(length/1000,4)
    return dict(base,polyline=[[a['lon'],a['lat']],[b['lon'],b['lat']]],basis='straight_line_water',
                km=km,water_km=km,eta_min=eta,water_eta_min=eta,fallback=True,grid_verified=False,tracking_eligible=False,
                max_depth_m=None,min_depth_m=None,unknown_samples=0,samples=0,label_pt=FALLBACK_LABEL,
                reason_codes=[code],review_pt=['REVISAR: linha reta sem rota aquática comprovada. '+reason,
                    'Calado %s m%s; margem estimada %s m; velocidade %s km/h%s.' %
                    (base['draft_m'],' (padrão estimado)' if base['draft_estimated'] else '',base['clearance_m'],
                     base['speed_kph'],' (padrão estimado)' if base['speed_estimated'] else '')])


@lru_cache(maxsize=2)
def _cached_water_router(observed):
    g=depth.grid(observed);h=g.h
    mask,info=building_mask(h['width'],h['height'],h['pixel_m'],h['origin_x'],h['origin_y'])
    return WaterRouter(g,mask,info)


_PREPARED=set()


def default_water_router(observed):
    # Avoid duplicate 95k-footprint decodes/profile builds on concurrent requests.
    with _LOCK:
        router=_cached_water_router(observed)
        _PREPARED.add(observed)
        return router


def water_ready(day):
    """True when a water search for `day` needs no heavy preparation (grid/buildings decode, ~10 s cold)."""
    observed=max((d for d in depth.DATES if d<=day),default=None)
    return observed is None or observed in _PREPARED


def warm_water(day):
    """Prepare the water grid in one daemon worker; callers get an explicit pending state meanwhile."""
    observed=max((d for d in depth.DATES if d<=day),default=None)
    if observed is None or observed in _PREPARED or observed in _WARMING: return
    _WARMING.add(observed)
    def work():
        try: default_water_router(observed)
        except Exception: pass
        finally: _WARMING.discard(observed)
    threading.Thread(target=work,daemon=True).start()


_WARMING=set()


def water_route(a,b,day,speed=12,draft_m=None,clearance_m=CLEARANCE_M,speed_estimated=True,allow_unknown=True):
    replay_day(day)
    for point in (a,b): roads._point(point['lat'],point['lon'])
    observed=max((d for d in depth.DATES if d<=day),default=None)
    if observed is None:
        draft=_number(.4 if draft_m is None else draft_m,'Calado');clearance=_number(clearance_m,'Margem')
        speed=_number(speed,'Velocidade',True)
        return fallback(a,b,dict(draft_m=draft,draft_estimated=draft_m is None,clearance_m=clearance,
            clearance_estimated=True,minimum_depth_m=draft+clearance,speed_kph=speed,speed_estimated=speed_estimated,
            observation_date=None,retrospective=True,confidence='low',navigability_verified=False),
            'NO_OBSERVATION','Sem observação de profundidade até a data de replay; nenhuma camada futura utilizada.')
    with _LOCK:
        return default_water_router(observed).route(a,b,draft_m,clearance_m,speed,speed_estimated,allow_unknown)
