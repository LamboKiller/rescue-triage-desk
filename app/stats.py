"""Date-bounded analysis statistics with explicit unknown counts."""
import math
from collections import Counter
from app.duplicates import value
from app.fleet import document
from app.geo.hazards import replay_day, map_data


def flooded_area(features, strips=512):
    """Scanline union, including holes/overlapping products; spherical area estimate."""
    polygons=[]
    for f in features:
        g=f.get('geometry') or {}
        if g.get('type')=='Polygon': polygons.append(g['coordinates'])
        elif g.get('type')=='MultiPolygon': polygons.extend(g['coordinates'])
    if not polygons: return 0.0
    ys=[p[1] for polygon in polygons for ring in polygon for p in ring]
    low,high=min(ys),max(ys)
    step=(high-low)/strips
    area=0
    scanlines=[[] for _ in range(strips)]
    if step == 0: return 0.0
    for polygon in polygons:
        crossings={}
        for ring in polygon:
            for a,b in zip(ring,ring[1:]+ring[:1]):
                if a[1]==b[1]: continue
                start=max(0,math.ceil((min(a[1],b[1])-low)/step-.5))
                stop=min(strips,math.ceil((max(a[1],b[1])-low)/step-.5))
                for row in range(start,stop):
                    y=low+(row+.5)*step
                    crossings.setdefault(row,[]).append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
        for row,xs in crossings.items():
            xs.sort()
            scanlines[row].extend(zip(xs[::2],xs[1::2]))
    for row,intervals in enumerate(scanlines):
        y=low+(row+.5)*step
        end=-float('inf');width=0
        for a,b in sorted(intervals):
            width+=max(0,b-max(a,end));end=max(end,b)
        area+=math.radians(width)*math.cos(math.radians(y))*math.radians(step)*6371.0**2
    return round(area,3)


def build_stats(day, cases):
    replay_day(day)
    selected=[]
    for current in cases:
        facts=[f for f in current.get('facts',[]) if f.get('received_at','9999')[:10]<=day and f.get('replay_time','9999')[:10]<=day]
        if not facts and current.get('received_at','9999')[:10]<=day and current.get('replay_time','9999')[:10]<=day: facts=[current]
        if facts:
            latest=max(facts,key=lambda f:(f.get('received_at',''),f.get('replay_time','')))
            # Human status has no historical timestamp in the original event schema.
            selected.append({**latest,'case_id':current['case_id'],'status':current.get('status','proposed'),
                             **({k:current[k] for k in ('fields','result') if k in current} if current.get('merge_state') and all(m['received_at'][:10]<=day for m in current.get('messages',[])) else {})})
    opened=[c for c in selected if c['status'] not in ('field_confirmed','reported_rescued_unconfirmed') and not c['status'].startswith('MERGED_INTO:') and c['result'].get('decision')!='REPORTED_RESCUED']
    mapped=map_data(day,opened)
    byid={c['case_id']:c for c in mapped['cases']}
    def counts(fn): return dict(Counter(str(fn(c)) for c in opened))
    people={}
    for key in ('people','children','elderly','disabled','pets'):
        known=[value(c,key) for c in opened if type(value(c,key)) is int and not c['result'].get('conflicting_counts')]
        people[key]={'known_total':sum(known),'unknown_cases':len(opened)-len(known)}
    exclusive_asset=Counter();exclusive_group=Counter();no_options=0
    assets=document()['assets']
    for c in opened:
        options=(byid.get(c['case_id'],{}).get('fleet_summary') or c.get('fleet_summary') or {}).get('options',[])
        ids={o['asset'] for o in options if o.get('verdict')!='unsafe'}
        groups={assets[a]['group'] for a in ids if a in assets}
        if len(ids)==1: exclusive_asset.update(ids)
        if len(groups)==1: exclusive_group.update(groups)
        if not ids: no_options+=1
    layers=mapped['layers']
    pumps=Counter(f['properties'].get('status','unknown') for f in layers['pumps']['features'])
    metrics={'calls_per_role':Counter(),'wins_per_model':Counter(),'failures':0,'critic_objections':0,'revisions':0,
             'hazard_critic_blocks':0,'validator_rejections':0,'injections_detected':0}
    calls=[];seen=set()
    for current in cases:
        for fact in current.get('facts') or [current]:
            if fact.get('received_at','9999')[:10]>day or fact.get('replay_time','9999')[:10]>day: continue
            key=(fact.get('run_id') or current['case_id'],fact.get('message_id'),fact.get('received_at'),fact.get('replay_time'))
            if key in seen: continue
            seen.add(key)
            calls.extend(fact.get('calls',[]))
            agents=fact.get('agents',{})
            review=agents.get('critic') or {}
            metrics['critic_objections']+=len(review.get('objections',[])) if isinstance(review,dict) else 0
            metrics['revisions']+=isinstance(agents.get('revision'),dict)
            hazard=fact.get('hazard_review') or {}
            metrics['hazard_critic_blocks']+=sum(o.get('severity')=='block' for o in hazard.get('objections',[])) if isinstance(hazard,dict) else 0
            metrics['validator_rejections']+=len(fact.get('unsupported',[]))+fact.get('hazard_unsupported',0)+fact.get('duplicate_unsupported',0)
            metrics['injections_detected']+=bool(fact.get('routing_flags',{}).get('injection'))
    for call in calls:
        metrics['calls_per_role'][call.get('role','unknown')]+=1
        metrics['failures']+=call.get('status')!='ok'
        if call.get('status')=='ok' and call.get('model'): metrics['wins_per_model'][call['model']]+=1
    seconds=sorted(c['seconds'] for c in calls if isinstance(c.get('seconds'),(float,int)))
    for label,p in (('p50_seconds',.5),('p90_seconds',.9)):
        metrics[label]=seconds[max(0,math.ceil(len(seconds)*p)-1)] if seconds else None
    return {'date':day,'status_basis':'current human status; analyses bounded by requested date','open_cases':len(opened),
            'by_priority':counts(lambda c:c['result'].get('priority','unknown')),
            'by_decision':counts(lambda c:c['result'].get('decision','unknown')),
            'by_route':counts(lambda c:(c.get('route') or {}).get('id','unknown')),
            'people_waiting':people,'by_municipality':counts(lambda c:value(c,'municipality') or 'unknown'),
            'by_bairro':counts(lambda c:value(c,'neighbourhood') or value(c,'bairro') or ((c.get('landmark_check') or {}).get('matched') or {}).get('neighbourhood') or 'unknown'),
            'depth_bands':counts(lambda c:(byid.get(c['case_id'],{}).get('hazards') or {}).get('depth_band','unknown')),
            'asset_demand':{'only_asset':dict(exclusive_asset),'only_group':dict(exclusive_group),'no_options':no_options},
            'hazards':{'flooded_area_km2':flooded_area(layers['flood']['features']),
                       'area_method':'512-strip spherical scanline union estimate; holes subtracted; overlapping products counted once',
                       'pumps_out':pumps['Inoperante'],'pumps_unknown':pumps['unknown'],
                       'active_closures':sum(f['properties'].get('status') not in
                           ('reported_alternative_open','reopened_direction_only','reopened')
                           for f in layers['closures']['features'])},'agent_metrics':metrics}
