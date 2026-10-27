"""Offline routing eval on the real OSM road graph for the 6 metro cities (no model, no network).

Origin->target pairs, hand-picked by inspecting the real committed graph (data/roads), covering:
dry routes that exist, a water depth above a vehicle's wading limit that blocks it while a boat
still reaches the case via a launch estimate, unknown depth warned/penalized or strictly blocked,
dry estimates outside the observed extent, an active closure (record T001) that forces a detour without
ever crossing the closed arcs, one-way streets that force a longer detour in one direction, and
points clearly outside the routable network, and May 6 dry-frontier launch recovery. Targets: all correct, 0
routes through any blocked edge (every edge of every returned route is independently re-checked
with edge_reasons, not just trusted from the search).
"""
import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.geo import roads, depth
from app.geo.routing import Router, edge_reasons, default_router

SET_PATH = ROOT / 'eval/routing_set.jsonl'


def water_scenario(item):
    """Author-written synthetic channel/island maps, never used by production."""
    from app.geo.water_routing import WaterRouter
    spec=item['water_grid'];day=max(d for d in spec['layers'] if d<=item['date'])
    rows=spec['layers'][day];legend=spec.get('legend',{'~':2.,'#':0.,'s':.45,'?':None})
    h=dict(width=len(rows[0]),height=len(rows),pixel_m=20.,origin_x=500000.,origin_y=6680000.,date_observed=day)
    values=[65535 if legend[c] is None else round(legend[c]*100) for row in rows for c in row]
    g=depth.DepthGrid(h,struct.pack('<'+'H'*len(values),*values))
    mask=bytearray(len(values))
    for col,row in spec.get('buildings',[]): mask[row*h['width']+col]=1
    def point(cell):
        lon,lat=depth.utm22s_to_lonlat(h['origin_x']+(cell[0]+.5)*20,h['origin_y']-(cell[1]+.5)*20)
        return dict(lon=lon,lat=lat)
    a,b=point(item['origin_cell']),point(item['target_cell'])
    r=WaterRouter(g,mask).route(a,b,draft_m=item['vehicle'].get('draft_m'),
        speed=item['vehicle'].get('boat_speed_kph',12),allow_unknown=item.get('allow_unknown',True))
    return dict(r,water=r,reachable=not r['fallback'] and r['km'] is not None),g,mask


def crossed_cells(polyline,g):
    """Independent segment/grid intersection via sorted boundary crossing times.

    Does not call the router's A*, state map, supercover or smoothing helpers.
    Includes both sides of exact boundary/corner contacts.
    """
    h=g.h;w=h['width'];seen=set()
    for p,q in zip(polyline,polyline[1:]):
        ax,ay=depth.lonlat_to_utm22s(*p);bx,by=depth.lonlat_to_utm22s(*q)
        ax=(ax-h['origin_x'])/h['pixel_m'];bx=(bx-h['origin_x'])/h['pixel_m']
        ay=(h['origin_y']-ay)/h['pixel_m'];by=(h['origin_y']-by)/h['pixel_m']
        ts={0.,1.}
        for a,b in ((ax,bx),(ay,by)):
            if a==b: continue
            for boundary in range(math.ceil(min(a,b)),math.floor(max(a,b))+1):
                t=(boundary-a)/(b-a)
                if 0<=t<=1: ts.add(t)
        times=sorted(ts)
        for t in times+[(lo+hi)/2 for lo,hi in zip(times,times[1:])]:
            x=ax+(bx-ax)*t;y=ay+(by-ay)*t
            for col in {math.floor(x-1e-8),math.floor(x+1e-8)}:
                for row in {math.floor(y-1e-8),math.floor(y+1e-8)}:
                    seen.add((col,row))
    return seen


def water_violations(water,day,g=None,buildings=None):
    if not water: return []
    bad=[]
    if water.get('fallback'):
        if water.get('basis')!='straight_line_water' or not water.get('review_pt') or not water.get('reason_codes') or 'linha reta' not in water.get('label_pt',''):
            bad.append('unlabelled_water_fallback')
        return bad
    if water.get('basis')=='water_search_incomplete':
        if water.get('water_km') is not None or water.get('polyline'): bad.append('incomplete_claims_route')
        return bad
    observed=max((d for d in depth.DATES if d<=day),default=None)
    if water.get('observation_date')!=observed: bad.append('water_future_or_wrong_observation')
    if g is None:
        if observed is None: return bad+['water_without_observation']
        g=depth.grid(observed)
        from app.geo.water_routing import default_water_router
        buildings=default_water_router(observed).buildings
    cells=crossed_cells(water['polyline'],g);unknown=0;known=[]
    for col,row in cells:
        if not (0<=col<g.h['width'] and 0<=row<g.h['height']): bad.append('water_outside_grid');continue
        idx=row*g.h['width']+col
        if buildings is not None and buildings[idx]: bad.append('water_building_collision')
        cm=struct.unpack_from('<H',g.data,idx*2)[0]
        if cm==65535: unknown+=1
        else:
            known.append(cm/100)
            if cm==0: bad.append('water_dry_cell')
            if cm/100+1e-8<water['draft_m']+water['clearance_m']: bad.append('water_shallower_than_draft_margin')
    if unknown and ('UNKNOWN_WATER' not in water.get('reason_codes',[]) or not any('trecho sem dado' in n for n in water.get('review_pt',[])) or water.get('grid_verified')):
        bad.append('unflagged_unknown_water')
    # Router extrema include conservative corner-side cells before lon/lat
    # rounding. They may widen, never narrow, the independently crossed envelope.
    if known and (water['min_depth_m']>min(known) or water['max_depth_m']<max(known)): bad.append('water_depth_envelope_unsafe')
    if not cells or len(water['polyline'])>128: bad.append('water_polyline_missing_or_uncapped')
    return sorted(set(bad))


def load_items(path=None):
    return [json.loads(l) for l in Path(path or SET_PATH).read_text(encoding='utf-8').splitlines() if l.strip()]


def run(item, edge_by_id):
    if item['action']=='water':
        out,g,mask=water_scenario(item);t=item['truth'];fails=[]
        if out['reachable']!=t['reachable']: fails.append('reachable:'+str(out['reachable']))
        for key in ('basis','observation_date'):
            if key in t and out.get(key)!=t[key]: fails.append(key+':'+str(out.get(key)))
        if out.get('water_km') is not None and out['water_km']<t.get('min_water_km',0): fails.append('water_path_too_short')
        if 'max_end_gap_m' in t and out.get('end_gap_m',math.inf)>t['max_end_gap_m']: fails.append('water_end_gap')
        for text in t.get('review_has',[]):
            if not any(text in note for note in out['review_pt']): fails.append('review_text:'+text)
        return fails,water_violations(out['water'],item['date'],g,mask),out
    router = Router(allow_unknown=item['allow_unknown']) if 'allow_unknown' in item else default_router()
    if item['action'] == 'route':
        out = router.route(item['origin'], item['target'], item['vehicle'], item['date'])
        land = out
    else:
        out = router.plan(item['origin'], item['target'], item['vehicle'], item['date'])
        land = out.get('land') or out
    fails = []
    violations = water_violations(out.get('water'),item['date'])
    for alternative in out.get('alternatives', []):
        violations.extend('alternative:'+v for v in water_violations(alternative.get('water'),item['date']))
    t = item['truth']
    reachable = bool(out['reachable'])
    if reachable != t['reachable']:
        fails.append('reachable:%s' % reachable)
    if 'edge_ids' in t and land.get('edge_ids') != t['edge_ids']:
        fails.append('edge_ids:%s' % land.get('edge_ids'))
    if 'land_km' in t and land.get('land_km') != t['land_km']:
        fails.append('land_km:%s' % land.get('land_km'))
    if 'water_km' in t and round(out.get('water_km') or -1, 4) != t['water_km']:
        fails.append('water_km:%s' % out.get('water_km'))
    if 'launch_node' in t and (out.get('launch_point') or {}).get('node_id') != t['launch_node']:
        fails.append('launch_node:%s' % (out.get('launch_point') or {}).get('node_id'))
    if 'launch_derived' in t and bool((out.get('launch_point') or {}).get('derived')) != t['launch_derived']:
        fails.append('launch_derived')
    if 'min_alternatives' in t and len(out.get('alternatives', [])) < t['min_alternatives']:
        fails.append('alternatives:%s' % len(out.get('alternatives', [])))
    if 'dry_estimate_min' in t and len(land.get('dry_estimate_edge_ids', [])) < t['dry_estimate_min']:
        fails.append('dry_estimate_edges:%s' % len(land.get('dry_estimate_edge_ids', [])))
    if 'unknown_min' in t and len(land.get('unknown_edge_ids', [])) < t['unknown_min']:
        fails.append('unknown_edges:%s' % len(land.get('unknown_edge_ids', [])))
    if 'min_edges' in t and len(land.get('edge_ids', [])) < t['min_edges']:
        fails.append('min_edges:%s' % len(land.get('edge_ids', [])))
    codes_seen = {b['code'] for b in (land.get('blocked_edges') or [])}
    for code in t.get('blocked_code_present', []):
        if code not in codes_seen:
            fails.append('missing_code:' + code)
    if 'closure_id' in t:
        cited = any(t['closure_id'] in b.get('closure_ids', []) for b in (land.get('blocked_edges') or []))
        if not cited:
            fails.append('closure_id_not_cited:' + t['closure_id'])
    for needle in t.get('review_has', []):
        if not any(needle in r for r in out.get('review_pt', [])):
            fails.append('review_text:' + needle)
    # Hard safety invariant: a route must never cross an edge that is itself blocked for
    # this vehicle/date. Re-derive each edge's reasons independently of the search/cache.
    land_vehicle=(item['vehicle'].get('carrier') or {'requires_dry_roads':True}) if out.get('water') else item['vehicle']
    launch=out.get('launch_point') or {}
    if launch.get('derived'):
        nid=launch['node_id'];wet=edge_by_id.get(launch['edge_id'])
        if not wet or nid not in (wet['u'],wet['v']):
            violations.append('launch_missing_wet_adjacency')
        else:
            why,state=edge_reasons(wet,land_vehicle,item['date'],router.allow_unknown,router.extent)
            if state!='wet' or not why or any(w['code'] not in ('WADING_LIMIT','WET_DEPTH_UNKNOWN') for w in why):
                violations.append('launch_without_eligible_wet_boundary')
        adjacent=[e for e in edge_by_id.values() if nid in (e['u'],e['v'])]
        if not any(not why and state in ('dry','dry_estimate') for e in adjacent
                   for why,state in [edge_reasons(e,land_vehicle,item['date'],router.allow_unknown,router.extent)]):
            violations.append('launch_without_dry_access')
        if launch['observation_date']>item['date']:
            violations.append('launch_future_observation')
    for eid in land.get('edge_ids', []):
        edge = edge_by_id.get(eid)
        if edge is None:
            violations.append('edge_missing:' + eid)
            continue
        reasons, state = edge_reasons(edge, land_vehicle, item['date'], router.allow_unknown, router.extent)
        # unknown / dry_estimate edges may be used only if the route flags them (never silently dry)
        if state == 'unknown' and eid not in land.get('unknown_edge_ids', []): violations.append('unflagged_unknown_edge:' + eid)
        if state == 'dry_estimate' and eid not in land.get('dry_estimate_edge_ids', []): violations.append('unflagged_dry_estimate_edge:' + eid)
        if reasons:
            violations.append('blocked_edge_in_route:' + eid + ':' + ','.join(r['code'] for r in reasons))
    for forbidden in t.get('never_edges', []):
        if forbidden in land.get('edge_ids', []):
            violations.append('forbidden_edge_used:' + forbidden)
    return fails, violations, out


def evaluate(path=None):
    items = load_items(path)
    network = roads.load()
    edge_by_id = {e['id']: e for e in network.edges}
    ok = 0
    violations_total = 0
    results = []
    for item in items:
        fails, violations, out = run(item, edge_by_id)
        ok += not fails and not violations
        violations_total += len(violations)
        row={'id': item['id'], 'reachable': out['reachable'], 'failures': fails, 'safety_violations': violations}
        if out.get('water'):
            water=out['water']
            row['water']={k:water.get(k) for k in ('basis','water_km','water_eta_min','min_depth_m','max_depth_m',
                'unknown_samples','start_gap_m','end_gap_m','reason_codes')}
            if out.get('launch_point'):
                a,b=out['launch_point'],item['target']
                row['water']['straight_km']=round(roads._distance(a['lon'],a['lat'],b['lon'],b['lat'])/1000,4)
        results.append(row)
    return {'cases': len(items), 'passed': ok, 'safety_violations': violations_total, 'results': results,
            'limits': 'Real OSM road graph for the 6 metro cities; only 2024-05-06/08 carry HAND depth '
                      'observations; later replay dates use the latest observation, never a future layer. '
                      'Unknown access stays warned/penalized; derived launches require dry-road/wet-road adjacency. '
                      'Water uses exact HAND cells plus conservative building footprints; unknown last resort is warned. '
                      'Straight line only on explained no-path fallback; retrospective model is not navigability certification.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    r = evaluate()
    text = json.dumps(r, ensure_ascii=False, indent=2)
    if a.output:
        a.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    sys.exit(0 if r['passed'] == r['cases'] and not r['safety_violations'] else 1)
