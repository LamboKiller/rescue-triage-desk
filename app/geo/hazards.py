"""Date-bounded retrospective hazard context. No routing or priority decisions."""
import csv
import hashlib
import json
import math
import threading
from collections import defaultdict
from datetime import date
from pathlib import Path
from app.config import ROOT
from app.geo.streets import normalize

STREET_POSITION = 'street_centroid — house number not geocoded'
DISTANCE_LABEL = 'straight-line, not a route'


def replay_day(value):
    if not isinstance(value,str) or len(value)!=10:
        raise ValueError('date must be YYYY-MM-DD')
    try:
        if date.fromisoformat(value).isoformat()!=value: raise ValueError()
    except ValueError:
        raise ValueError('date must be YYYY-MM-DD') from None
    return value


def distance_m(lat,lon,other_lat,other_lon):
    a,b,c,d=map(math.radians,(lat,lon,other_lat,other_lon))
    h=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))


def ring_contains(x,y,ring):
    inside=False
    a=ring[-1]
    for b in ring:
        ax,ay=a[:2];bx,by=b[:2]
        # Boundary is part of the observed extent.
        cross=(x-ax)*(by-ay)-(y-ay)*(bx-ax)
        if abs(cross)<1e-12 and min(ax,bx)<=x<=max(ax,bx) and min(ay,by)<=y<=max(ay,by):
            return True
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax: inside=not inside
        a=b
    return inside


class PolygonIndex:
    """0.01-degree bbox grid, with exact ray casting inside candidate rings."""
    def __init__(self,features):
        self.grid=defaultdict(list)
        for f in features:
            g=f['geometry'];polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
            for polygon in polys:
                xs,ys=zip(*polygon[0]);bbox=(min(xs),min(ys),max(xs),max(ys))
                for x in range(math.floor(bbox[0]*100),math.floor(bbox[2]*100)+1):
                    for y in range(math.floor(bbox[1]*100),math.floor(bbox[3]*100)+1):
                        self.grid[x,y].append((bbox,polygon))
    def contains(self,lat,lon):
        for (a,b,c,d),polygon in self.grid.get((math.floor(lon*100),math.floor(lat*100)),()):
            if a<=lon<=c and b<=lat<=d and ring_contains(lon,lat,polygon[0]) and not any(ring_contains(lon,lat,r) for r in polygon[1:]):
                return True
        return False


def geometry_distance(lat,lon,g):
    if not g: return float('inf')
    if g['type']=='Point': return distance_m(lat,lon,g['coordinates'][1],g['coordinates'][0])
    lines=[g['coordinates']] if g['type']=='LineString' else g['coordinates']
    scale=111320*math.cos(math.radians(lat));best=float('inf')
    for line in lines:
        for a,b in zip(line,line[1:]):
            ax,ay=(a[0]-lon)*scale,(a[1]-lat)*111320
            bx,by=(b[0]-lon)*scale,(b[1]-lat)*111320
            dx,dy=bx-ax,by-ay;size=dx*dx+dy*dy
            t=max(0,min(1,-(ax*dx+ay*dy)/size)) if size else 0
            best=min(best,math.hypot(ax+t*dx,ay+t*dy))
    return best


def active_closure(p,day):
    return bool(p.get('source_published_at')) and p['source_published_at'][:10]<=day and p['from_date'][:10]<=day and (not p.get('to_date') or day<=p['to_date'][:10])


class HazardData:
    def __init__(self,root=None):
        self.root=Path(root or ROOT/'data/hazards')
        self.layers={}
        for name in ('closures','pumps','events','shelters','levees'):
            self.layers[name]=json.loads((self.root/(name+'.geojson')).read_text(encoding='utf-8'))['features']
        self.flood={p.stem.removeprefix('flood_'):json.loads(p.read_text(encoding='utf-8'))['features'] for p in sorted(self.root.glob('flood_*.geojson'))}
        self.indices={day:PolygonIndex(fs) for day,fs in self.flood.items()}
        with (self.root/'pump_status_daily.csv').open(encoding='utf-8-sig',newline='') as f:
            self.pump_status={(r['source_fid'],r['date']):r['status'] for r in csv.DictReader(f)}
        with (self.root/'street_points.csv').open(encoding='utf-8-sig',newline='') as f:
            self.streets={(r['normalized_name'],r['normalized_municipality']):r for r in csv.DictReader(f)}

    def street_point(self,street,municipality):
        return self.streets.get((normalize(street),normalize(municipality)))

    def dated_layers(self,day):
        replay_day(day)
        observed=max((d for d in self.flood if d<=day),default=None)
        shelters=self.layers['shelters']
        snapshot=max((f['properties']['snapshot_local'] for f in shelters if f['properties']['snapshot_local'][:10]<=day),default=None)
        pumps=[]
        for f in self.layers['pumps']:
            raw=self.pump_status.get((str(f['properties']['source_fid']),day))
            status='unknown' if not raw or raw=='APURAR' else raw
            pumps.append({**f,'properties':{**f['properties'],'status':status,'status_date':day,'source_status':raw,
                                          'status_source':'D1/clean/pump_status_daily.csv'}})
        layers={'flood':self.flood.get(observed,[]),'closures':[f for f in self.layers['closures'] if active_closure(f['properties'],day)],
                'pumps':pumps,'events':[f for f in self.layers['events'] if f['properties'].get('published_at') and
                    f['properties']['published_at'][:10]<=day and f['properties'].get('observed_at','')[:10]<=day],
                'shelters':[f for f in shelters if f['properties']['snapshot_local']==snapshot], 'levees':self.layers['levees']}
        return observed,layers

    def assess(self,lat,lon,replay_date,position_kind):
        day=replay_day(replay_date)
        lat,lon=float(lat),float(lon)
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
            raise ValueError('invalid coordinates')
        if position_kind not in ('landmark',STREET_POSITION): raise ValueError('invalid position_kind')
        observed,layers=self.dated_layers(day)
        from app.geo.depth import lookup
        flood_by_date={d:self.indices[d].contains(lat,lon) for d in sorted(self.indices) if d<=day}
        wet=any(flood_by_date.values()) if flood_by_date else None
        result={'flood_by_date':flood_by_date,'in_flood_any':wet,**lookup(lon,lat,day),
                'closures_nearby':[],'pumps_nearby':[],'events_nearby':[],'nearest_shelters':[],
                'position_kind':position_kind,'facts':[]}
        def fact(key,text,source):
            token=hashlib.sha256((key+'|'+day+'|'+str(lat)+'|'+str(lon)).encode()).hexdigest()[:20]
            result['facts'].append({'id':'hazard:'+token,'text_pt':text,'source':source})
        fact('position', 'Posição de referência: '+position_kind+'.', 'data/hazards/street_points.csv' if position_kind==STREET_POSITION else 'data/landmarks.csv')
        if not flood_by_date:
            fact('flood:none','Sem observação de inundação até esta data.','data/hazards/manifest.json')
        for observation,inside in flood_by_date.items():
            fact('flood:'+observation,('Ponto dentro' if inside else 'Ponto fora')+' da extensão observada em '+observation+
                 '; resultado falso posterior pode refletir cobertura, não recessão; publicação desconhecida.',
                 'data/hazards/flood_'+observation+'.geojson')
        depth_text=('Profundidade desconhecida; nenhum valor válido até 60 m.' if result['depth_m'] is None else
                    'Profundidade estimada '+str(result['depth_m'])+' m; célula a '+str(result['depth_distance_m'])+' m; observada em '+result['depth_observed_date']+'.')
        fact('depth',depth_text+' '+result['depth_confidence']+'. '+result['depth_confidence_reason'],result['depth_source'])
        for name,limit,key in (('closures',1000,'closures_nearby'),('pumps',3000,'pumps_nearby'),('events',3000,'events_nearby')):
            nearby=[]
            for f in layers[name]:
                dist=geometry_distance(lat,lon,f['geometry'])
                if dist<=limit:
                    p=f['properties'];r={**p,'id':f['id'],'distance_m':round(dist,1)}
                    nearby.append(r)
            nearby.sort(key=lambda r:(r['distance_m'],r['id']))
            result[key]=nearby
            if not nearby: fact(name+':none','Nenhum registro de '+name+' no raio de '+str(limit)+' m nesta data; cobertura limitada.','data/hazards/'+name+'.geojson')
            for r in nearby:
                text=('Interdição '+r['road']+' ('+r['status']+'), corredor candidato não verificado' if name=='closures' else
                      'Bomba '+r['name']+' ('+r['status']+') em '+day if name=='pumps' else
                      'Evento '+r.get('asset','')+' ('+r['status']+'), observado em '+r.get('observed_at',''))
                fact(name+':'+r['id'],text+'; distância '+str(r['distance_m'])+' m.',r.get('status_source',r['source']))
        available=[]
        for f in layers['shelters']:
            p=f['properties']
            try: vacancies=float(p.get('vacancies'))
            except (TypeError,ValueError): continue
            if vacancies>0:
                available.append({**p,'id':f['id'],'distance_km':round(geometry_distance(lat,lon,f['geometry'])/1000,3),'distance_label':DISTANCE_LABEL})
        available.sort(key=lambda r:(r['distance_km'],r['id']))
        result['nearest_shelters']=available[:3]
        for r in available[:3]:
            fact('shelter:'+r['id'],'Abrigo em '+r.get('municipality','')+': '+str(r['vacancies'])+' vagas no registro '+r['snapshot_local']+'; '+str(r['distance_km'])+' km ('+DISTANCE_LABEL+').',r['source'])
        if not available: fact('shelter:none','Nenhum abrigo com vagas conhecidas no último retrato disponível até esta data.','data/hazards/shelters.geojson')
        return result


_data=None
_lock=threading.Lock()

def get_data():
    global _data
    with _lock:
        if _data is None: _data=HazardData()
    return _data


def assess(lat,lon,replay_date,position_kind):
    return get_data().assess(lat,lon,replay_date,position_kind)


def case_position(case):
    landmark=(case.get('landmark_check') or {}).get('matched')
    if landmark and landmark.get('lat') not in (None,'') and landmark.get('lon') not in (None,''):
        return {'lat':float(landmark['lat']),'lon':float(landmark['lon']),'position_kind':'landmark'}
    def value(key): return case.get('fields',{}).get(key,{}).get('value','')
    point=get_data().street_point(value('street'),value('municipality')) if (case.get('checks') or {}).get('found') else None
    if point: return {'lat':float(point['lat']),'lon':float(point['lon']),'position_kind':STREET_POSITION}
    return None


def attach(case):
    position=case_position(case)
    case['position']=position
    case['hazards']=assess(position['lat'],position['lon'],case['replay_time'][:10],position['position_kind']) if position else None
    case['hazards_reason']=None if position else 'No resolved landmark coordinates or unambiguous street point.'
    return case


def map_data(day,cases=()):
    replay_day(day)
    _,layers=get_data().dated_layers(day)
    result={'date':day,'layers':{k:{'type':'FeatureCollection','features':v} for k,v in layers.items()},'cases':[]}
    for current in cases:
        # Registry projections may contain analyses from later replay dates.
        candidates=[f for f in current.get('facts',[]) if isinstance(f,dict) and f.get('replay_time','9999')[:10]<=day and f.get('received_at','9999')[:10]<=day]
        if not candidates and current.get('replay_time','9999')[:10]<=day and current.get('received_at','9999')[:10]<=day: candidates=[current]
        if not candidates: continue
        case=max(candidates,key=lambda f:(f.get('received_at',''),f.get('replay_time','')))
        position=case_position(case);hazards=assess(position['lat'],position['lon'],day,position['position_kind']) if position else None
        from app.fleet import screen
        screened=screen({**case,'hazards':hazards})
        summary={k:hazards[k] for k in ('flood_by_date','in_flood_any','depth_m','depth_status','depth_band','depth_distance_m','depth_observed_date','depth_by_date','depth_confidence','depth_confidence_reason','depth_source','depth_retrospective')} if hazards else None
        if summary is not None:
            summary.update({key:len(hazards[key]) for key in ('closures_nearby','pumps_nearby','events_nearby','nearest_shelters')})
        result['cases'].append({'case_id':current['case_id'],'decision':case['result']['decision'],'priority':case['result'].get('priority'),
             'lat':position['lat'] if position else None,'lon':position['lon'] if position else None,
             'position_kind':position['position_kind'] if position else None,'hazards':summary,
             'fleet':screened['fleet'],'fleet_summary':screened['fleet_summary'],
             'fleet_replay_date':day,'hazard_review_replay_time':case.get('replay_time'),
             'hazard_review':case.get('hazard_review'),
             'hazard_critic':case.get('hazard_critic',case.get('hazard_review','indisponível')),
             'hazard_unsupported':case.get('hazard_unsupported',0)})
    return result
