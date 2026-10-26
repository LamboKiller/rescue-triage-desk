"""Offline OSM road routing. All speeds/ETAs are estimates, never dispatch authority.

Road polylines are lon/lat; input points are {lat, lon} or exact OSM node ids.
Edge water state per date (see ``edge_reasons``): wet / dry (measured 0) /
dry_estimate (outside the observed Copernicus flood extent, retrospective) /
unknown (no layer covers it). Unknown is never silently dry: it is allowed only
with a heavy cost penalty and a mandatory "trecho sem dado" warning.
"""
from collections import OrderedDict, defaultdict
from datetime import date as iso_date
from functools import lru_cache
import heapq
import math
from app.geo import roads, depth

# POLICY for edges with no data (no flood/depth layer covers them on the date):
#   'penalize' = passable for land vehicles, cost x UNKNOWN_PENALTY, flagged on the
#                route (unknown_edge_ids + "trecho sem dado" warning) - never silently dry;
#   'block'    = impassable (old strict behaviour, Router(allow_unknown=False)).
# Edges INSIDE the observed flood extent whose depth is unknown are always blocked
# (code WET_DEPTH_UNKNOWN); a wet edge is passable only with a measured depth <= wading limit.
# Edges outside the observed extent with no positive HAND depth are 'dry_estimate':
# passable, flagged, retrospective, low confidence.
UNKNOWN_POLICY = 'penalize'
UNKNOWN_PENALTY = 20
DRY_ESTIMATE_LABEL = 'seco estimado: fora da mancha observada (Copernicus), retrospectivo'
UNKNOWN_LABEL = 'trecho sem dado: sem camada de inundação/profundidade; não presumido seco'

# Conservative author estimates (km/h), not observed traffic or emergency SOP.
SPEED_KPH = {'motorway':60, 'motorway_link':30, 'trunk':50, 'trunk_link':25,
    'primary':40, 'primary_link':25, 'secondary':35, 'secondary_link':20,
    'tertiary':30, 'tertiary_link':20, 'residential':20, 'unclassified':20,
    'living_street':10, 'service':10, 'track':8, 'road':10}
BOATS = {'barco_aluminio','bote_inflavel','jet_ski','aluminium_outboard','irb','pwc_sled'}
WATER_LABEL = 'trecho na água em linha reta — estimativa'
LAND_LABEL = 'rota OSM; velocidade por classe viária — estimativa'
REVIEW = 'REVISAR: HAND/OSM retrospectivos, confiança baixa; confirmar acesso, transporte e estacionamento no local.'


def day_value(day):
    if not isinstance(day,str) or iso_date.fromisoformat(day).isoformat()!=day:
        raise ValueError('Data deve ser YYYY-MM-DD.')
    return day


def _metres(a,b):
    return roads._distance(a['lon'],a['lat'],b['lon'],b['lat'])


def _profile(vehicle):
    if not isinstance(vehicle,dict):
        vehicle=vars(vehicle)
    limit=vehicle.get('max_wading_depth_m')
    if limit is None: limit=0
    if type(limit) not in (int,float) or not math.isfinite(limit) or limit<0:
        raise ValueError('Limite de transposição inválido.')
    dry=vehicle.get('requires_dry_roads',vehicle.get('type') in ('ambulancia','road_ambulance'))
    return (0 if dry else float(limit)),bool(dry)


class _RowMask:
    """Scanline-rasterised polygon mask: per ~11 m latitude row, sorted x intervals.

    The exact point-in-polygon test is ~8 ms per query on the big metro polygons, too slow
    for 150k edges; rows are sampled at their centre, x is exact (error <= ~6 m N-S).
    """
    STEP = 0.0001

    def __init__(self, features):
        from collections import defaultdict
        import math as m
        rows = defaultdict(list); self.lat0 = -90.0; step = self.STEP
        for f in features:
            g = f['geometry']
            for poly in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
                cross = defaultdict(list)
                for ring in poly:
                    for a, b in zip(ring, ring[1:] + ring[:1]):
                        if a[1] == b[1]: continue
                        (ax, ay), (bx, by) = a[:2], b[:2]
                        lo, hi = min(ay, by), max(ay, by)
                        for r in range(m.ceil((lo - self.lat0) / step - .5), m.ceil((hi - self.lat0) / step - .5)):
                            yc = self.lat0 + (r + .5) * step
                            cross[r].append(ax + (yc - ay) * (bx - ax) / (by - ay))
                for r, xs in cross.items():
                    xs.sort()
                    rows[r].extend(zip(xs[0::2], xs[1::2]))
        self.rows = {}
        for r, iv in rows.items():
            iv.sort(); merged = [list(iv[0])]
            for x0, x1 in iv[1:]:
                if x0 <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], x1)
                else: merged.append([x0, x1])
            self.rows[r] = ([a for a, _ in merged], [b for _, b in merged])

    def contains(self, lat, lon):
        import bisect
        hit = self.rows.get(math.floor((lat - self.lat0) / self.STEP))
        if not hit: return False
        i = bisect.bisect_right(hit[0], lon) - 1
        return i >= 0 and lon <= hit[1][i]


class ObservedExtent:
    """Observed Copernicus flood extent per date (data/hazards/flood_<date>.geojson).

    No hindsight: the layer for day D is the latest one with date <= D. Coverage (the
    area the product actually looked at) is the HAND grid footprint of the same date;
    outside it nothing is known, so edges there are 'unknown', not 'dry'.
    """
    def __init__(self, flood_dir=None, depth_dir=None):
        from pathlib import Path
        from app.config import ROOT
        self.flood_dir = Path(flood_dir or ROOT / 'data/hazards')
        self.depth_dir = Path(depth_dir or ROOT / 'data/depth')
        self.layers = {}
        self.cache = {}

    def dates(self):
        if getattr(self, '_dates', None) is None: self._dates = self._scan()
        return self._dates

    def _scan(self):
        return sorted(p.stem.removeprefix('flood_') for p in self.flood_dir.glob('flood_*.geojson'))

    def layer(self, day):
        import json
        observed = max((d for d in self.dates() if d <= day), default=None)
        if observed is None: return None
        if observed not in self.layers:
            feats = json.loads((self.flood_dir / ('flood_' + observed + '.geojson')).read_text(encoding='utf-8'))['features']
            try: h = json.loads((self.depth_dir / ('depth_' + observed + '.json')).read_text(encoding='utf-8'))
            except OSError: h = None
            aoi = (h['origin_x'], h['origin_y'] - h['height'] * h['pixel_m'],
                   h['origin_x'] + h['width'] * h['pixel_m'], h['origin_y']) if h else None
            self.layers[observed] = (observed, _RowMask(feats), aoi)
        return self.layers[observed]

    @staticmethod
    def samples(edge):
        pts = edge['polyline']
        out = []
        for a, b in zip(pts, pts[1:]):
            out.append(a); out.append([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])
        out.append(pts[-1])
        if len(out) > 16: out = [out[round(i * (len(out) - 1) / 15)] for i in range(16)]
        return out

    def classify(self, edge, day):
        """-> ('inside' | 'outside' | 'uncovered', layer date) for this edge on this day."""
        layer = self.layer(day)
        if layer is None: return 'uncovered', None
        observed, index, aoi = layer
        key = (observed, edge['id'])
        if key not in self.cache:
            pts = self.samples(edge)
            if any(index.contains(lat, lon) for lon, lat in pts): r = 'inside'
            elif aoi is None: r = 'uncovered'
            else:
                r = 'outside'
                for lon, lat in (pts[0], pts[-1]):  # edges are short vs the ~28x69 km footprint
                    x, y = depth.lonlat_to_utm22s(lon, lat)
                    if not (aoi[0] <= x <= aoi[2] and aoi[1] <= y <= aoi[3]): r = 'uncovered'; break
            self.cache[key] = r
        return self.cache[key], observed


@lru_cache(maxsize=1)
def default_extent(): return ObservedExtent()


def edge_reasons(edge, vehicle, day, allow_unknown=None, extent=None):
    """Recheck a returned edge independently of the search cache -> (reasons, state).

    state: 'wet' (depth>0 or inside the observed extent), 'dry' (measured 0 m),
    'dry_estimate' (outside the observed extent, no positive depth), 'unknown'.
    """
    if allow_unknown is None: allow_unknown = UNKNOWN_POLICY == 'penalize'
    limit,dry=_profile(vehicle); reasons=[]
    def add(code,**extra): reasons.append(dict(edge_id=edge['id'],code=code,**extra))
    if edge.get('routing_eligible',True) is not True: add('TOPOLOGY_INELIGIBLE')
    if edge.get('highway') not in SPEED_KPH or any(edge.get(k) in ('no','private') for k in ('access','vehicle','motor_vehicle')):
        add('ACCESS_RESTRICTED')
    closures=[]
    for c in edge.get('closure_matches',[]):
        start=c.get('from_date') or day
        end=c.get('to_date') or '9999-12-31'
        published=(c.get('source_published_at') or start)[:10]
        if start<=day<=end and published<=day and c.get('status') not in ('open','reopened','reported_alternative_open'):
            closures.append(c.get('record_id','unknown'))
    if closures or day in edge.get('closed_dates',[]): add('CLOSURE',closure_ids=closures,extent_verified=False)
    layers=edge.get('depth',{})
    observed=max((d for d,v in layers.items() if d<=day and (v.get('observation_date') or d)<=day),default=None)
    layer=layers[observed] if observed else {}
    value=layer.get('max_depth_m')
    unknown=value is None or layer.get('unknown_fraction',0)>0
    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0): unknown=True;value=None
    if value is not None and value>limit: add('WADING_LIMIT',max_depth_m=value,limit_m=limit,observation_date=observed)
    where,ext_date=extent.classify(edge,day) if extent is not None else ('uncovered',None)
    if not unknown: state='dry' if value==0 else 'wet'
    elif where=='inside':
        state='wet'
        add('WET_DEPTH_UNKNOWN',observation_date=ext_date,note_pt='dentro da mancha observada, profundidade desconhecida')
    elif where=='outside' and not value:
        state='dry_estimate'
    else:
        state='unknown'
        if not allow_unknown: add('DEPTH_UNKNOWN',observation_date=observed)
    return reasons,state


class Router:
    def __init__(self,network=None,allow_unknown=None,snap_m=75,extent='auto'):
        self.extent=default_extent() if extent=='auto' and network is None else (None if extent=='auto' else extent)
        self.network=network if network is not None else roads.load()
        self.allow_unknown=(UNKNOWN_POLICY=='penalize') if allow_unknown is None else bool(allow_unknown);self.snap_m=snap_m
        self.adjacency=defaultdict(list);self.incident=defaultdict(list);self.buckets=defaultdict(list);self.cities=defaultdict(list)
        self.states=OrderedDict();self.searches={};self.frontiers=OrderedDict()
        for nid,n in self.network.nodes.items():
            self.buckets[(math.floor(n['lon']/.002),math.floor(n['lat']/.002))].append(nid)
        for e in self.network.edges:
            # Only real shared node ids connect components; no geometric stitching.
            if e['u'] not in self.network.nodes or e['v'] not in self.network.nodes: continue
            self.cities[e['municipality']].append(e)
            self.incident[e['u']].append(e);self.incident[e['v']].append(e)
            one=str(e.get('oneway') or '').lower()
            if one!='-1': self.adjacency[e['u']].append((e['v'],e,False))
            if one not in ('yes','true','1') and not (e.get('junction')=='roundabout' and not one):
                self.adjacency[e['v']].append((e['u'],e,True))

    def _snap(self,value):
        if isinstance(value,str):
            n=self.network.nodes.get(value)
            return (value,0) if n and n.get('routing_eligible',True) else (None,None)
        if not isinstance(value,dict): raise ValueError('Ponto deve conter lat/lon ou ser id de nó OSM.')
        lat,lon=roads._point(value.get('lat'),value.get('lon'))
        x,y=math.floor(lon/.002),math.floor(lat/.002)
        candidates=[]
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for nid in self.buckets.get((x+dx,y+dy),[]):
                    n=self.network.nodes[nid]
                    if n.get('routing_eligible',True):
                        d=roads._distance(lon,lat,n['lon'],n['lat'])
                        if d<=self.snap_m: candidates.append((d,nid))
        if not candidates: return None,None
        d,nid=min(candidates)
        return nid,round(d,2)

    def _state(self,edge,vehicle,day):
        profile=_profile(vehicle);key=(day,*profile,edge['municipality'])
        if key not in self.states:
            self.states[key]={}
            if len(self.states)>24: self.states.popitem(last=False)
        self.states.move_to_end(key)
        rows=self.states[key]
        if edge['id'] not in rows:
            rows[edge['id']]=edge_reasons(edge,vehicle,day,self.allow_unknown,self.extent)
        return rows[edge['id']]

    def _search(self,start,targets,vehicle,day,key=None):
        """Dijkstra from start. targets=None explores the whole reachable component (cacheable, reused by
        every target); a `key` caches the result per (start, vehicle profile, day) for per-request reuse."""
        ck=(key,start,day,*_profile(vehicle)) if key else None
        if ck and ck in self.searches: return self.searches[ck]
        out=self._dijkstra(start,targets,vehicle,day)
        if ck:
            if len(self.searches)>=12: self.searches.pop(next(iter(self.searches)))
            self.searches[ck]=out
        return out

    def _dijkstra(self,start,targets,vehicle,day):
        best={start:0};prev={};heap=[(0,start)];remaining=set(targets) if targets is not None else {None};blocked={}
        while heap and remaining:
            cost,u=heapq.heappop(heap)
            if cost!=best.get(u): continue
            remaining.discard(u)
            for v,e,reverse in self.adjacency.get(u,[]):
                why,state=self._state(e,vehicle,day)
                if why:
                    for item in why: blocked[(item['edge_id'],item['code'])]=item
                    continue
                seconds=e['length_m']/(SPEED_KPH[e['highway']]/3.6)
                if state=='unknown': seconds*=UNKNOWN_PENALTY
                alt=cost+seconds
                if alt<best.get(v,float('inf')):
                    best[v]=alt;prev[v]=(u,e,reverse,state);heapq.heappush(heap,(alt,v))
        return best,prev,list(blocked.values())

    def _result(self,start,target,vehicle,day,search,snaps=(0,0)):
        best,prev,blocked=search
        out={'reachable':target in best,'date':day,'decision':'REVIEW_REQUIRED',
             'edge_ids':[],'node_ids':[],'polyline':[],'land_km':None,'land_eta_min':None,
             'blocked_edges':[],'blocked_edges_total':len(blocked),'unknown_edge_ids':[],'dry_estimate_edge_ids':[],
             'basis_pt':LAND_LABEL,'retrospective':True,'confidence':'low',
             'origin_snap_m':snaps[0],'target_snap_m':snaps[1],
             'review_pt':[REVIEW],'human_approval_required':True}
        if target not in best:
            out['blocked_edges']=blocked[:50]
            out['review_pt'].append('REVISAR: sem rota terrestre; interdições/profundidade desconhecida ou acima do limite, sentido único ou topologia desconectada.')
            return out
        steps=[];cursor=target
        while cursor!=start:
            u,e,reverse,state=prev[cursor];steps.append((cursor,e,reverse,state));cursor=u
        steps.reverse();out['node_ids']=[start];metres=0
        for v,e,reverse,state in steps:
            out['edge_ids'].append(e['id']);out['node_ids'].append(v);metres+=e['length_m']
            coords=list(reversed(e['polyline'])) if reverse else e['polyline']
            out['polyline'].extend(coords if not out['polyline'] else coords[1:])
            if state=='unknown': out['unknown_edge_ids'].append(e['id'])
            elif state=='dry_estimate': out['dry_estimate_edge_ids'].append(e['id'])
        if not out['polyline']:
            n=self.network.nodes[start];out['polyline']=[[n['lon'],n['lat']]]
        route_nodes=set(out['node_ids'])
        edge_lookup={e['id']:e for nid in route_nodes for e in self.incident[nid]}
        # Include incoming blocked edges too, without scanning the entire city.
        out['blocked_edges']=[b for b in blocked if b['edge_id'] in edge_lookup][:50]
        out.update(land_km=round(metres/1000,4),land_eta_min=round(best[target]/60,3),
                   decision='REVIEW_REQUIRED' if out['unknown_edge_ids'] else 'HUMAN_PICK_REQUIRED')
        if any(x for x in snaps): out['review_pt'].append('Confirmar ligação entre posição e nó OSM; deslocamento fora da malha não modelado.')
        if out['unknown_edge_ids']: out['review_pt'].append('REVISAR: %d trecho(s) sem dado (%s); permitido pela política com custo penalizado %dx, nunca presumido seco.'%(len(out['unknown_edge_ids']),UNKNOWN_LABEL,UNKNOWN_PENALTY))
        if out['dry_estimate_edge_ids']: out['review_pt'].append('%d trecho(s) %s.'%(len(out['dry_estimate_edge_ids']),DRY_ESTIMATE_LABEL))
        return out

    def route(self,origin,target,vehicle,date):
        day_value(date);_profile(vehicle)
        start,ds=self._snap(origin);end,dt=self._snap(target)
        if start is None or end is None:
            return {'reachable':False,'decision':'REVIEW_REQUIRED','date':date,'edge_ids':[],'node_ids':[],
                    'polyline':[],'land_km':None,'land_eta_min':None,'blocked_edges':[],
                    'unknown_edge_ids':[],'review_pt':['REVISAR: posição fora da malha OSM elegível (limite de associação: %s m); sem ligação comprovada.'%self.snap_m],
                    'human_approval_required':True,'basis_pt':LAND_LABEL}
        return self._result(start,end,vehicle,date,self._search(start,None,vehicle,date,key='all'),(ds,dt))

    def _frontier_launches(self,carrier,day):
        """Unverified launch estimates at dry-road / wet-road shared OSM nodes.

        Stored launches used HAND-only shallow endpoints (<0.3 m), which need not
        have dry access under the observed-extent policy. Recompute the boundary
        with that same policy; never drive along the wet edge to reach the water.
        Unknown, closed and restricted streets cannot establish dry-side access.
        """
        key=(day,*_profile(carrier))
        if key in self.frontiers: return self.frontiers[key]
        dry_nodes=set();wet_edges=[]
        for e in self.network.edges:
            if e['u'] not in self.network.nodes or e['v'] not in self.network.nodes: continue
            why,state=self._state(e,carrier,day)
            if not why and state in ('dry','dry_estimate'):
                dry_nodes.update((e['u'],e['v']))
            elif state=='wet' and why and all(w['code'] in ('WADING_LIMIT','WET_DEPTH_UNKNOWN') for w in why):
                observed=max(w['observation_date'] for w in why if w.get('observation_date'))
                wet_edges.append((e,observed))
        points={}
        for e,observed in wet_edges:
            for nid in (e['u'],e['v']):
                n=self.network.nodes.get(nid)
                if nid not in dry_nodes or not n or not n.get('routing_eligible',True): continue
                points.setdefault(nid,dict(node_id=nid,dry_side_node_id=nid,lat=n['lat'],lon=n['lon'],
                    edge_id=e['id'],municipality=e['municipality'],routing_eligible=True,
                    nearest_street_name=e.get('name') or e.get('ref') or '(sem nome)',
                    observation_date=observed,kind='retrospective',confidence='low',derived=True,
                    parking_status='unverified',label='lançamento estimado na transição seco/água; confirmar no local'))
        if len(self.frontiers)>=12: self.frontiers.popitem(last=False)
        self.frontiers[key]=list(points.values())
        return self.frontiers[key]

    def plan(self,origin,target,vehicle,date):
        day_value(date)
        if vehicle.get('type',vehicle.get('asset')) not in BOATS:
            land=self.route(origin,target,vehicle,date)
            return dict(land,land=land,water=None,water_km=0,launch_point=None,alternatives=[])
        # Boat trailer/carrier is not documented in boat inventory; a dry-only
        # carrier is an explicit estimate, requiring operator confirmation.
        carrier=vehicle.get('carrier') or {'requires_dry_roads':True,'max_wading_depth_m':0}
        start,ds=self._snap(origin)
        if start is None:
            land=self.route(origin,target,carrier,date)
            return dict(land,land=land,water=None,water_km=None,launch_point=None,alternatives=[])
        launches=[]
        for p in self.network.launch_points(date):
            nid=p.get('dry_side_node_id');n=self.network.nodes.get(nid)
            if n and n.get('routing_eligible',True) and p.get('routing_eligible',True) and (p.get('observation_date') or date)<=date:
                launches.append(dict(p,node_id=nid,lat=n['lat'],lon=n['lon']))
        search=self._search(start,{p['node_id'] for p in launches},carrier,date,key='launch')
        # Preserve reachable stored estimates; otherwise derive candidates
        # from this date's policy, rather than borrowing launches from a future day.
        if not any(p['node_id'] in search[0] for p in launches):
            launches=self._frontier_launches(carrier,date)
            search=self._search(start,None,carrier,date,key='all')
        speed=vehicle.get('boat_speed_kph',12) # author estimate when not documented
        if type(speed) not in (int,float) or not math.isfinite(speed) or speed<=0: raise ValueError('Velocidade inválida.')
        options=[]
        for p in launches:
            nid=p['node_id']
            if nid not in search[0]: continue
            water_m=_metres(p,target)
            total=search[0][nid]+water_m/(speed/3.6)
            options.append((total,nid,p,water_m))
        options.sort(key=lambda x:(x[0],x[1]))
        choices=[]
        for seconds,nid,p,water_m in options[:2]:
            land=self._result(start,nid,carrier,date,search,(ds,0))
            water=water_leg(p,target,date,speed)
            choices.append({'launch_point':p,'land':land,'water':water,
                'land_km':land['land_km'],'land_eta_min':land['land_eta_min'],'water_km':water['km'],
                'eta_seconds':round(seconds,2),'reachable':True})
        if not choices:
            land=self._result(start,'__no_launch__',carrier,date,search,(ds,0))
            land['review_pt'].append('REVISAR: nenhum ponto de lançamento alcançável pelo lado seco.')
            return dict(land,land=land,water=None,water_km=None,launch_point=None,alternatives=[])
        pick=choices[0]
        launch_notes=[pick['launch_point']['label']] if pick['launch_point'].get('derived') else []
        return dict(pick,alternatives=choices,blocked_edges=pick['land']['blocked_edges'],
            decision='REVIEW_REQUIRED',human_approval_required=True,retrospective=True,confidence='low',
            carrier_estimated='carrier' not in vehicle,
            review_pt=[REVIEW,'Confirmar veículo que transporta a embarcação e velocidade aquática (estimativa %s km/h).'%speed,
                'Linha na água não verifica navegação, correnteza, obstáculos nem calado mínimo.']+launch_notes)


@lru_cache(maxsize=1)
def default_router(): return Router()


def route(origin,target,vehicle,date): return default_router().route(origin,target,vehicle,date)


@lru_cache(maxsize=256)
def _water_cached(alat,alon,blat,blon,day,speed):
    a={'lat':alat,'lon':alon};b={'lat':blat,'lon':blon};length=_metres(a,b)
    steps=max(1,math.ceil(length/25));known=[];unknown=0
    for i in range(steps+1):
        t=i/steps
        try:
            v=depth.lookup(alon+(blon-alon)*t,alat+(blat-alat)*t,day)['depth_m']
        except (OSError,ValueError,KeyError): v=None
        if v is None: unknown+=1
        else: known.append(v)
    return {'polyline':[[alon,alat],[blon,blat]],'km':round(length/1000,4),
            'eta_min':round(length/(speed*1000/60),3),'speed_kph':speed,'speed_estimated':True,
            'max_depth_m':max(known,default=None),'unknown_samples':unknown,'samples':steps+1,
            'sampling_m':25,'label_pt':WATER_LABEL,'basis':'straight_line_water',
            'retrospective':True,'confidence':'low','navigability_verified':False}


def water_leg(a,b,day,speed=12):
    import copy
    day_value(day)
    roads._point(a['lat'],a['lon']);roads._point(b['lat'],b['lon'])
    if type(speed) not in (int,float) or not math.isfinite(speed) or speed<=0: raise ValueError('Velocidade inválida.')
    return copy.deepcopy(_water_cached(a['lat'],a['lon'],b['lat'],b['lon'],day,speed))


_PLAN_CACHE={}
_WARM={'thread':None}


def router_ready():
    return default_router.cache_info().currsize>0


def warm_async():
    """Build the 150k-edge graph/adjacency in a daemon thread so request handlers never wait for it."""
    import threading
    if _WARM['thread'] is None:
        def work():
            try:
                default_router()
                ex=default_extent()
                for d in ex.dates(): ex.layer(d)
            except Exception: _WARM['thread']=None
        _WARM['thread']=threading.Thread(target=work,daemon=True);_WARM['thread'].start()


class FleetDistance:
    """Two-point adapter with per-unit extension for the allocator call site."""
    BUDGET_S = 0.8  # routing work allowed per adapter instance (= per request); the rest falls back, labelled
    def __init__(self,day,router=None): self.day=day;self.router=router;self.spent=0.0
    def _unproven(self,why):
        return {'reachable':False,'distance_m':None,'eta_seconds':None,'basis_pt':'rota não comprovada',
                'review_pt':['REVISAR: rota não comprovada ('+why+'); usando linha reta como estimativa.'],'route':{}}
    def for_unit(self,base,target,unit):
        import time
        if self.router is None and not router_ready():
            warm_async(); return self._unproven('malha viária carregando em segundo plano')
        key=(self.day,round(base['lat'],6),round(base['lon'],6),round(target['lat'],6),round(target['lon'],6),
             unit.get('type'),unit.get('asset'),unit.get('max_wading_depth_m'),unit.get('requires_dry_roads'),id(self.router))
        r=_PLAN_CACHE.get(key)
        if r is None:
            if self.spent>=self.BUDGET_S: return self._unproven('orçamento de tempo de roteamento da requisição esgotado')
            t=time.monotonic()
            try: r=(self.router or default_router()).plan(base,target,unit,self.day)
            finally: self.spent+=time.monotonic()-t
            if len(_PLAN_CACHE)>512: _PLAN_CACHE.clear()
            _PLAN_CACHE[key]=r
        ok=r['reachable']
        return {'reachable':ok,'distance_m':round((r['land_km']+(r.get('water_km') or 0))*1000,2) if ok else None,
                'eta_seconds':r.get('eta_seconds',r['land_eta_min']*60 if ok else None),
                'basis_pt':LAND_LABEL+' + '+WATER_LABEL if r.get('water') else LAND_LABEL,
                'review_pt':r.get('review_pt',[]),'route':r}
    def __call__(self,base,target):
        return self.for_unit(base,target,{'requires_dry_roads':True})


def landing_distance(day):
    def distance(a,b):
        water=water_leg(a,b,day)
        return dict(water,m=round(water['km']*1000),basis='straight_line_water')
    return distance


def landing_transfers(options,day,router=None):
    """Add land access to each proposed shelter; never fabricate a fallback road."""
    r=router or default_router()
    for option in options:
        for shelter in option.get('shelters',[]):
            land=r.route(option,shelter,{'type':'ambulancia','requires_dry_roads':True},day)
            shelter['land_route']=land
            if not land['reachable']:
                option['warnings_pt'].append('REVISAR: sem rota terrestre seca até '+shelter['label']+'.')
        if option.get('ambulance'):
            top=next(iter(option.get('shelters',[])),{})
            option['ambulance']['land_route']=top.get('land_route')
            if not top.get('land_route',{}).get('reachable'):
                option['ambulance']['status']='REVISAR: sem rota terrestre seca; nada foi acionado'


def case_route(case,unit,day,router=None):
    from app.missions.planner import point
    p=point(case);base=unit.get('base_location')
    if not p or not base:
        return {'case_id':case['case_id'],'unit_id':unit['id'],'date':day,'reachable':False,
                'decision':'REVIEW_REQUIRED','review_pt':['REVISAR: caso sem ponto confirmado ou unidade sem base.'],
                'human_approval_required':True,'alternatives':[]}
    result=(router or default_router()).plan(base,p,unit,day)
    return dict(result,case_id=case['case_id'],unit_id=unit['id'],date=day)
