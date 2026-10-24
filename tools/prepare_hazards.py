"""Prepare compact, reproducible hazard data from a read-only backup; stdlib only."""
import argparse
import collections
import csv
import hashlib
import json
import math
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.geo.streets import normalize
from tools.prepare_data import Index

BBOX = (-51.75, -30.35, -50.85, -29.55)
TOLERANCE_M = 15


def dp(points, tolerance=TOLERANCE_M):
    if len(points) <= 2:
        return points
    a, b = points[0], points[-1]
    dx, dy = (b[0]-a[0])*96300, (b[1]-a[1])*111320
    size = dx*dx+dy*dy
    best, at = 0, 0
    for i, p in enumerate(points[1:-1], 1):
        x, y = (p[0]-a[0])*96300, (p[1]-a[1])*111320
        t = max(0, min(1, (x*dx+y*dy)/size)) if size else 0
        dist = (x-t*dx)**2+(y-t*dy)**2
        if dist > best:
            best, at = dist, i
    return dp(points[:at+1], tolerance)[:-1]+dp(points[at:], tolerance) if best > tolerance**2 else [a,b]


def clip_ring(ring):
    points = [list(p[:2]) for p in ring[:-1]]
    for axis, bound, sign in ((0,BBOX[0],1),(0,BBOX[2],-1),(1,BBOX[1],1),(1,BBOX[3],-1)):
        if not points:
            return []
        output, a = [], points[-1]
        for b in points:
            ai, bi = sign*(a[axis]-bound)>=0, sign*(b[axis]-bound)>=0
            if ai != bi:
                t = (bound-a[axis])/(b[axis]-a[axis])
                p = [a[j]+t*(b[j]-a[j]) for j in (0,1)]
                p[axis] = bound
                output.append(p)
            if bi:
                output.append(b)
            a = b
        points = output
    if len(points)<3:
        return []
    points.append(points[0])
    # Split a closed ring at its farthest vertex before Douglas-Peucker.
    at = max(range(1,len(points)-1), key=lambda i: sum((points[i][j]-points[0][j])**2 for j in (0,1)))
    simplified = dp(points[:at+1])[:-1]+dp(points[at:])
    result = [[round(x,6),round(y,6)] for x,y in simplified]
    if len(set(map(tuple,result)))<3:
        result = [[round(x,6),round(y,6)] for x,y in points]
    return result if len(set(map(tuple,result)))>=3 else []


def compact_geometry(g):
    typ, coords = g['type'], g['coordinates']
    if typ in ('Polygon','MultiPolygon'):
        polygons = [coords] if typ=='Polygon' else coords
        result = []
        for polygon in polygons:
            outer = clip_ring(polygon[0])
            if outer:
                result.append([outer]+[r for ring in polygon[1:] if (r:=clip_ring(ring))])
        return {'type':'MultiPolygon','coordinates':result} if result else None
    if typ=='Point':
        return {'type':typ,'coordinates':[round(v,6) for v in coords[:2]]}
    lines = [coords] if typ=='LineString' else coords
    return {'type':typ,'coordinates': [[round(v,6) for v in p[:2]] for p in dp(lines[0])] if typ=='LineString' else
            [[[round(v,6) for v in p[:2]] for p in dp(line)] for line in lines]}


def prepare(backup, dest=None):
    dest = Path(dest or ROOT/'data/hazards')
    dest.mkdir(parents=True,exist_ok=True)
    sources, outputs = {}, {}
    def read(name):
        path=backup/name
        raw=path.read_bytes()
        sources[name]={'source_file':name,'sha256':hashlib.sha256(raw).hexdigest(),
                       'licence_pointer':'data/ATTRIBUTION.md#hazard-layers-v2-a'}
        if name.endswith('.csv'):
            import io
            rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        else:
            rows=json.loads(raw)['features']
        sources[name]['count']=len(rows)
        return rows
    def write_json(name,fs):
        payload=json.dumps({'type':'FeatureCollection','features':fs},ensure_ascii=False,separators=(',',':'))
        (dest/name).write_text(payload,encoding='utf-8')
        outputs[name]={'count':len(fs),'bytes':(dest/name).stat().st_size}
    def write_csv(name,rows,columns=None):
        with (dest/name).open('w',encoding='utf-8',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=columns or list(rows[0]));writer.writeheader();writer.writerows(rows)
        outputs[name]={'count':len(rows),'bytes':(dest/name).stat().st_size}
    def feature(g,p,id):
        return {'type':'Feature','id':str(id),'geometry':g,'properties':p}
    floods=collections.defaultdict(list)
    for name in ('flood_observed.geojson','copernicus_flood_delineation.geojson'):
        for i,f in enumerate(read('D1/clean/'+name)):
            p=f['properties'];g=compact_geometry(f['geometry'])
            if g:
                day=p['observation_date'];floods[day].append(feature(g,{'observation_date':day,'source':name,
                    'source_layer':p.get('source_layer',p.get('source_file','')),'publication_available':False},name+':'+str(i)))
    for day,fs in sorted(floods.items()):
        write_json('flood_'+day+'.geojson',fs)
    closures=read('D3/clean/road_closures.csv')
    geometries=read('D3/clean/transport_geometry_candidates.geojson')
    matched=collections.defaultdict(list)
    for f in geometries:
        for rid in f['properties'].get('transport_record_ids','').split('|'):
            matched[rid].append(f)
    cfs=[]
    for row in closures:
        lines=[]
        for f in matched[row['record_id']]:
            g=compact_geometry(f['geometry'])
            lines.extend([g['coordinates']] if g['type']=='LineString' else g['coordinates'])
        cfs.append(feature({'type':'MultiLineString','coordinates':lines} if lines else None,
                           {**row,'closure_extent_verified':False,'routing_safe':False},row['record_id']))
    write_json('closures.geojson',cfs)
    write_csv('closures.csv',[{**r,'geometry':json.dumps(f['geometry'],separators=(',',':'))} for r,f in zip(closures,cfs)])
    pumps=[];pump_rows=[]
    for f in read('D1/clean/pump_stations.geojson'):
        p=f['properties'];g=compact_geometry(f['geometry'])
        q={'source_fid':str(p['source_fid']),'name':p.get('Nome Completo',''),'municipality':p.get('NM_MUN',''),
           'source':'D1/clean/pump_stations.geojson'}
        pumps.append(feature(g,q,q['source_fid']));pump_rows.append({**q,'lon':g['coordinates'][0],'lat':g['coordinates'][1]})
    write_json('pumps.geojson',pumps);write_csv('pumps.csv',pump_rows)
    write_csv('pump_status_daily.csv',read('D1/clean/pump_status_daily.csv'))
    for layer,name in (('events','D3/clean/infrastructure_events.geojson'),('shelters','D1/clean/shelters_timeseries.geojson'),('levees','D1/clean/levees.geojson')):
        fs=[];rows=[]
        for i,f in enumerate(read(name)):
            g=compact_geometry(f['geometry']);p={**f['properties'],'source':f['properties'].get('source') or name}
            if layer=='shelters':
                p={k:p.get(k) for k in ('snapshot_local','snapshot_row_id','municipality','facility_type','sheltered_people','capacity','vacancies','source')}
            rid=p.get('record_id',str(i));fs.append(feature(g,p,rid))
            if g['type']=='Point':
                rows.append({**p,'id':rid,'lon':g['coordinates'][0],'lat':g['coordinates'][1]})
        write_json(layer+'.geojson',fs)
        if rows:
            cols=sorted({k for r in rows for k in r});write_csv(layer+'.csv',rows,cols)
    cities=Index()
    for f in read('D1/clean/census_tracts_2022.geojson'):
        cities.add(f['geometry'],f['properties']['municipality'])
    groups={}
    for f in read('D1/clean/osm_roads.geojson'):
        p,g=f['properties'],f['geometry']
        if not p.get('name') or not p.get('highway') or g['type'] not in ('LineString','MultiLineString'):
            continue
        lines=[g['coordinates']] if g['type']=='LineString' else g['coordinates']
        for line in lines:
            length=sum(math.hypot((a[0]-b[0])*96300,(a[1]-b[1])*111320) for a,b in zip(line,line[1:]))
            touched=collections.defaultdict(list)
            for point in line:
                if BBOX[0]<=point[0]<=BBOX[2] and BBOX[1]<=point[1]<=BBOX[3]:
                    for city in cities.values(point): touched[city].append(point[:2])
            for city,points in touched.items():
                key=(normalize(p['name']),normalize(city))
                group=groups.setdefault(key,{'display_name':p['name'],'municipality':city,'points':[],'length_m':0})
                group['points'].extend(points);group['length_m']+=length
    rows=[]
    for (name,city),group in sorted(groups.items()):
        points=sorted(group['points']);point=points[len(points)//2];xs,ys=zip(*points)
        rows.append({'normalized_name':name,'display_name':group['display_name'],'municipality':group['municipality'],
                     'normalized_municipality':city,'lat':round(point[1],6),'lon':round(point[0],6),
                     'bbox':json.dumps([round(v,6) for v in (min(xs),min(ys),max(xs),max(ys))],separators=(',',':')),'length_m':round(group['length_m'],1)})
    write_csv('street_points.csv',rows)
    manifest={'bbox':BBOX,'simplification':{'algorithm':'Douglas-Peucker; closed rings split; rectangular clipping',
                'tolerance_m':TOLERANCE_M,'coordinate_decimals':6,'metric':'local equirectangular at 30 S'},
              'sources':sources,'outputs':outputs,'notes':['Flood publication unknown: retrospective observations only.',
                'Street position is a median source vertex; length includes full touched OSM ways.',
                'Closure geometries are unverified corridor candidates; routing_safe is false.']}
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    total=sum(p.stat().st_size for p in dest.iterdir() if p.is_file())
    print('Prepared',len(outputs),'layers/tables;',total,'bytes')
    if total>15_000_000: raise ValueError('Hazard data exceeds 15 MB budget')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,default=Path(os.environ.get('RTD_BACKUP_DIR','data-backup')))
    args=parser.parse_args();prepare(args.backup)


