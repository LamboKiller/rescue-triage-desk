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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.geo import roads
from app.geo.routing import Router, edge_reasons, default_router

SET_PATH = ROOT / 'eval/routing_set.jsonl'


def load_items(path=None):
    return [json.loads(l) for l in Path(path or SET_PATH).read_text(encoding='utf-8').splitlines() if l.strip()]


def run(item, edge_by_id):
    router = Router(allow_unknown=item['allow_unknown']) if 'allow_unknown' in item else default_router()
    if item['action'] == 'route':
        out = router.route(item['origin'], item['target'], item['vehicle'], item['date'])
        land = out
    else:
        out = router.plan(item['origin'], item['target'], item['vehicle'], item['date'])
        land = out.get('land') or out
    fails = []
    violations = []
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
        results.append({'id': item['id'], 'reachable': out['reachable'], 'failures': fails, 'safety_violations': violations})
    return {'cases': len(items), 'passed': ok, 'safety_violations': violations_total, 'results': results,
            'limits': 'Real OSM road graph for the 6 metro cities; only 2024-05-06/08 carry HAND depth '
                      'observations; later replay dates use the latest observation, never a future layer. '
                      'Unknown access stays warned/penalized; derived launches require dry-road/wet-road adjacency. '
                      'Straight-line water legs are estimates (no navigability/obstacle check).'}


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
