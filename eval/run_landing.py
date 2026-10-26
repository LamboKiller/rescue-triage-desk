"""Offline landing/disembark eval (12 author-written synthetic scenarios; no model, no network).

Checks the plan (landing order, shelter, ambulance card, congestion warning, review notes) plus the hard rules: never a flooded landing
point, never a shelter reported full, ambulance only for quoted medical need, unknown capacity never shown as room, nothing auto-dispatched,
reports after the replay clock invisible.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.landing.service import LandingService
from app.shelters.state import Catalogue, Shelters, Store

SRC = {'source_kind': 'roads_launch_points', 'source_label': 'sintético (avaliação)', 'capacity_basis': 'estimate'}


class Reg:
    def __init__(self, case): self.case = case
    def read(self, cid): return self.case if cid == self.case['case_id'] else None


class Shel:
    def __init__(self, shelters): self.shelters = shelters


def build(item):
    c = item['case']
    case = {'case_id': item['id'], 'message_id': item['id'], 'version': 1, 'text': c['text'], 'received_at': '2024-05-08T08:00:00-03:00',
            'status': 'proposed', 'fields': {'people': {'value': c.get('people')}}, 'result': {'decision': 'SEND', 'priority': 1}}
    if c.get('lat') is not None: case['position'] = {'lat': c['lat'], 'lon': c['lon']}
    S = Shelters(Catalogue.from_places([{k: v for k, v in s.items() if k != 'access'} for s in item['shelters']]), Store())
    for e in item.get('shelter_events', []): S.record(e)
    access = {(round(p['lat'], 5), round(p['lon'], 5)): p['access'] for p in item['landings'] + item['shelters']}
    fn = lambda lat, lon, day: {'state': access[(round(lat, 5), round(lon, 5))], 'source': 'synthetic', 'reason_pt': 'camada sintética'}
    pts = [{'landing_id': p['id'], 'label': p['id'], 'lat': p['lat'], 'lon': p['lon'], 'municipality': 'Canoas (sintético)', 'capacity_per_hour': p.get('cap', 40), **SRC}
           for p in item['landings']]
    svc = LandingService(Reg(case), Shel(S), None, None, fn, None, pts)
    for e in item.get('landing_events', []): svc.store.add(e)
    return svc, S


def evaluate(path=None):
    items = [json.loads(l) for l in Path(path or ROOT / 'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    ok = violations = 0;results = []
    for item in items:
        svc, S = build(item);v = svc.view(item['id'], item['now']);t = item['truth'];fails = [];viol = []
        opts = v['options'];ids = [o['landing_id'] for o in opts]
        top = opts[0] if opts else None
        if (ids[:1] or [None])[0] != t.get('top_landing'): fails.append('top_landing:%s' % ids[:1])
        if 'top_shelter' in t:
            got = [s['shelter_id'] for s in top['shelters']][:1] if top else []
            if got != ([t['top_shelter']] if t['top_shelter'] else []): fails.append('top_shelter:%s' % got)
        if bool(top and top['ambulance']) != t.get('ambulance', False): fails.append('ambulance')
        if t.get('ambulance') and top and top['ambulance'] and t['quote'] not in top['ambulance']['text_pt']: fails.append('ambulance_quote')
        if set(o['landing_id'] for o in opts if o['congested']) != set(t.get('congested', [])): fails.append('congested')
        for needle in t.get('warn', []):
            if not any(needle in w for o in opts for w in o['warnings_pt']): fails.append('warn:' + needle)
        if bool(v['review_pt']) != t.get('review', False): fails.append('review')
        for needle in t.get('review_has', []):
            if not any(needle in r for r in v['review_pt']): fails.append('review_text:' + needle)
        if t.get('unknown_not_room'):
            rows = [s for o in opts for s in o['shelters']]
            if not rows or any(s['capacity']['known'] or 'desconhecida' not in s['room_pt'] for s in rows): fails.append('unknown_labelled')
        full = {s['shelter_id'] for s in S.state(item['now']) if s['full']}
        for o in opts:
            if o['access']['state'] == 'flooded': viol.append('flooded_landing:' + o['landing_id'])
            if o['ambulance'] and not v['medical']: viol.append('ambulance_without_medical')
            viol += ['full_shelter:' + s['shelter_id'] for s in o['shelters'] if s['shelter_id'] in full]
        if v['auto_dispatched'] or not v['human_choice_required']: viol.append('auto_dispatch')
        viol += ['never_landing:' + i for i in set(t.get('never_landing', [])) & set(ids)]
        ok += not fails and not viol;violations += len(viol)
        results.append({'id': item['id'], 'landings': ids, 'failures': fails, 'safety_violations': viol})
    return {'cases': len(items), 'passed': ok, 'safety_violations': violations, 'synthetic': True, 'results': results,
            'limits': 'Author-written synthetic points/shelters; straight-line distance; measures the deterministic planner and its hard rules, not real-world coverage.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--output', type=Path);a = p.parse_args()
    r = evaluate();text = json.dumps(r, ensure_ascii=False, indent=2)
    if a.output: a.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    sys.exit(0 if r['passed'] == r['cases'] and not r['safety_violations'] else 1)
