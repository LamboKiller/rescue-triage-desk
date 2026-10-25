"""Offline synthetic hydro checks over the real local catalogue; no model calls.

Precision means correct expected precision class, not surveyed coordinate accuracy.
Bairro containment uses the labelled place-node proxy because polygons are absent.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.geo import hydro as h


def evaluate(cases):
    results = []
    wrong_city = bounds_ok = areas = precision_ok = precision_cases = 0
    for c in cases:
        task = c['task']; truth = c['truth']; city = c.get('municipality')
        candidates = []
        if task == 'classify':
            value = h.classify_point(c['lat'], c['lon'], c['day'])
            ok = value['state'] == truth['state'] and value['observed_date'] == truth['observed_date']
        elif task == 'rank':
            value = h.rank_candidates(c['candidates'], c['text'], c['day'], city)
            candidates = value['ranked']
            ok = [v['id'] for v in candidates] == truth['ids']
            # Ranker retains alternatives; only the top candidate is the choice.
            candidates = candidates[:1]
        elif task == 'area':
            value = h.area_point(c['bairro'], city, c['day'])
            ok = value.get('flooded') == truth['flooded'] and bool(value['point']) == truth['point']
            precision_cases += 1
            precision_ok += value['precision'] == truth['precision']
            if value.get('flooded'):
                areas += 1
                p = value['point']; w, s, e, n = value['bbox']
                nodes = h.find_bairro(c['bairro'], city)
                all_nodes = [v for v in h._places() if v['mun'] == h.key(city)]
                near = min(all_nodes, key=lambda v: h._metres(p['lat'], p['lon'], v['lat'], v['lon']))
                inside = (w <= p['lon'] <= e and s <= p['lat'] <= n and near in nodes
                          and h._metres(p['lat'], p['lon'], near['lat'], near['lon']) <= h.BAIRRO_RADIUS_M)
                bounds_ok += inside
                ok = ok and inside and h.classify_point(p['lat'], p['lon'], c['day'])['state'] == 'wet'
        else:
            value = h.resolve_descriptors(c['text'], city, c['day'], c.get('bairro'))
            candidates = [v for item in value for v in item['candidates']]
            ok = bool(candidates) == truth['found']
            if truth.get('name_contains'):
                ok = ok and any(h.key(truth['name_contains']) in h.key(v['name']) for v in candidates)
            if truth.get('precision'):
                precision_cases += 1
                good = bool(candidates) and all(v['precision'] == truth['precision'] for v in candidates)
                precision_ok += good
                ok = ok and good
            ok = ok and all(item.get('quote', '') in c['text'] for item in value)
        mismatches = sum(h.key(v.get('municipality', '')) != h.key(city) for v in candidates) if city else 0
        wrong_city += mismatches
        results.append({'id': c['id'], 'pass': bool(ok and not mismatches), 'task': task})
    return dict(cases=len(cases), passed=sum(v['pass'] for v in results), wrong_city=wrong_city,
                precision_correct=precision_ok, precision_cases=precision_cases,
                flooded_centroids_in_proxy_bounds=bounds_ok, flooded_centroids=areas,
                boundary='estimated OSM place-node proxy; not official bairro polygons', results=results)


def main():
    cases = [json.loads(line) for line in (ROOT/'eval/hydro_set.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    r = evaluate(cases)
    print(json.dumps(r, ensure_ascii=True, indent=2))
    return 0 if r['passed'] == r['cases'] and not r['wrong_city'] else 1


if __name__ == '__main__':
    sys.exit(main())
