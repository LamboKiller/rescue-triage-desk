"""Location wiring evaluation. Offline uses a source-based scripted policy, not an LLM.

The policy receives messages and tool history only; truth is accessed by score().
--baseline measures the previous deterministic lookup/matcher without the loop.
--live uses the configured provider and is intended for Yussef to run explicitly.
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agents import baseline, location
from app.agents.spans import validate
from app.config import load_env
from app.data.source import LocalSource
from app.derive_count import _plain
from app.geo.incident import IncidentIndex, incident_text, key
from app.geo.landmarks import CATEGORIES, match
from app.geo.streets import lookup, normalize

REPLAY = '2024-05-06T14:00:00-03:00'
ABSTAIN = {'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}


class ScriptedPolicy:
    """General catalogue/regex fixture for the tool protocol; never reads labels."""
    def __init__(self, streets, landmarks, index):
        self.index = index
        self.names = {}
        self.roads = {}
        for row in landmarks:
            for name in [row['name']]+re.split(r'[|;]', row.get('alt_names', ''))+[
                    a['alias'] for a in row.get('curated_aliases', [])]:
                if key(name):
                    self.names.setdefault(key(name), []).append(row)
        for row in streets:
            self.roads.setdefault(key(normalize(row['display_name'])), []).append(row)

    @staticmethod
    def action(tool, quote, **args):
        return dict(tool=tool, args=args, why_quote=quote)

    def choose(self, payload):
        text = payload['message']
        scoped = incident_text(text)
        results = [r for r in payload['results'] if 'result_id' in r]
        if payload['objections']:
            return ABSTAIN
        if re.search(r'\b(?:ou|dois pedidos|nao sei qual municipio)\b', scoped):
            return ABSTAIN
        city_names = {key(c) for c in self.index.cities.values()}
        road_hits = [(a, b, rs) for a, b, rs in self.index.hits(scoped, self.roads)
                     if len(key(text[a:b])) >= 2 and key(text[a:b]) not in city_names]
        full_roads = self.index.hits(scoped, self.index.streets, self.index.max_words)
        cities = {display for city, display in self.index.cities.items()
                  for m in re.finditer(r'\b'+re.escape(city)+r'\b', scoped)
                  if not any(a <= m.start() and b >= m.end() for a, b, _ in full_roads)}
        city = next(iter(cities)) if len(cities) == 1 else None
        bairro_hits = self.index.hits(scoped, self.index.bairros)
        if not city and bairro_hits:
            cs = set().union(*(cs for _, _, cs in bairro_hits))
            city = next(iter(cs)) if len(cs) == 1 else None
        # Explicit designators also let the scripted fixture exercise fuzzy tools.
        road_quotes = []
        for m in re.finditer(r'\b(?:rua|avenida|av\.?|r\.)\s+[^,.;!\n]+', scoped):
            end = re.search(r'\s+(?:em|com|ou|no|na|agua|Canoas|Porto Alegre|São Leopoldo)\b|\s+\d', m[0], re.I)
            b = m.start()+(end.start() if end else len(m[0]))
            road_quotes.append(text[m.start():b].strip())
        if not road_quotes:
            road_quotes = [text[a:b] for a, b, _ in road_hits]
        corner = bool(re.search(r'\besquina|\bcruzamento', scoped)) and len(road_quotes) >= 2
        generic_market = bool(re.search(r'\b(?:supermercado|mercado)\b', scoped)) and bool(road_quotes)
        landmark_hits = self.index.hits(scoped, self.names)
        landmark_hits = [(a, b, rs) for a, b, rs in landmark_hits
                         if key(text[a:b]) not in city_names
                         and any(r['category'] not in ('place:suburb', 'place:neighbourhood') for r in rs)]
        if not results:
            if bairro_hits and not re.search(r'\b(?:estacao|hospital|igreja|capela|escola|colegio|mercado|supermercado|museu)\b', scoped) and not road_quotes:
                a, b, _ = max(bairro_hits, key=lambda h: h[1]-h[0])
                return self.action('search_bairro', text[a:b], name=text[a:b])
            if road_quotes and (not landmark_hits or corner or generic_market):
                return self.action('search_street', road_quotes[0], name=road_quotes[0], **({'city': city} if city else {}))
            if bairro_hits and not landmark_hits:
                a, b, _ = max(bairro_hits, key=lambda h: h[1]-h[0])
                return self.action('search_bairro', text[a:b], name=text[a:b])
            if landmark_hits:
                a, b, _ = max(landmark_hits, key=lambda h: h[1]-h[0])
                quote = text[a:b]
                hints = {category for word, categories in CATEGORIES.items() if word in _plain(quote).split() for category in categories}
                return self.action('search_landmark', quote, name=quote, **({'city': city} if city else {}),
                                   **({'category': next(iter(hints))} if len(hints) == 1 else {}))
            return ABSTAIN
        if corner and len(results) == 1:
            return self.action('search_street', road_quotes[1], name=road_quotes[1], **({'city': city} if city else {}))
        if corner and len(results) == 2:
            a, b = (r['candidates'] for r in results)
            if len(a) == len(b) == 1:
                return self.action('near', text.strip(), anchor_id=a[0]['candidate_id'], radius_m=300,
                                   category='intersection', other_anchor_id=b[0]['candidate_id'])
            return ABSTAIN
        if generic_market and len(results) == 1:
            anchors = results[0]['candidates']
            if len(anchors) == 1:
                return self.action('near', text.strip(), anchor_id=anchors[0]['candidate_id'], radius_m=300, category='market')
            return ABSTAIN
        last = results[-1]
        candidates = last['candidates']
        if city:
            candidates = [c for c in candidates if c['city'] == city]
        literal = [c for c in candidates if _plain(c['name']) in scoped]
        if literal:
            candidates = literal
        if len(candidates) != 1:
            return ABSTAIN
        c = candidates[0]
        return {'answer': {'candidate_id': c['candidate_id'], 'precision': c['precision'],
                           'evidence': [last['why_quote'], last['result_id']]}}

    def call(self, role, system, payload, deadline):
        started = time.monotonic()
        output = {'objections': []} if role == 'critic' else self.choose(json.loads(payload))
        return output, dict(role=role, model='scripted_tool_policy_NOT_LLM', receipt=None,
                            seconds=round(time.monotonic()-started, 4))


def baseline_result(rows, landmarks, fields, text):
    get = lambda k: fields.get(k, {}).get('value', '')
    street = lookup(rows, get('street'), get('municipality'), REPLAY)
    lm = match(landmarks, place_name=get('landmark'), landmark_quote=get('landmark'),
               municipality=get('municipality'), replay=REPLAY, message=text, streets=rows)
    if street['found']:
        candidate = dict(kind='street', name=street['display_name'], city=street['municipality'])
        precision = 'exact' if get('number') else 'street'
    elif lm['status'] == 'resolved':
        c = lm['matched']
        candidate = dict(candidate_id='osm:'+c['osm_type']+':'+c['osm_id'], kind='landmark', name=c['name'], city=c['municipality'])
        precision = 'approximate'
    else:
        candidate, precision = None, 'area'
    return dict(candidate=candidate, precision=precision, tool_steps=0, location_path='deterministic', fallback=False)


def score(outputs, cases):
    resolved = wrong_city = precision = identity = 0
    for out, case in zip(outputs, cases):
        truth = case['truth']
        c = out.get('candidate')
        resolved += bool(c)
        wrong_city += bool(c and truth.get('city') and normalize(c['city']) != normalize(truth['city']))
        precision += out['precision'] == truth['precision']
        if truth.get('unresolvable'):
            correct = c is None
        else:
            correct = bool(c and normalize(c['city']) == normalize(truth['city']))
            if correct and truth.get('candidate_id'):
                correct = c.get('candidate_id') == truth['candidate_id']
            elif correct and truth.get('streets'):
                correct = all(normalize(s) in normalize(c['name']) for s in truth['streets'])
            elif correct:
                correct = normalize(c['name']) == normalize(truth.get('street') or truth.get('bairro') or truth.get('landmark'))
        identity += correct
        out['identity_correct'] = bool(correct)
    n = len(outputs)
    return dict(n=n, resolved=resolved, resolved_percent=round(100*resolved/n, 2) if n else 0,
                wrong_city=wrong_city, identity_correct=identity, precision_correct=precision,
                precision_accuracy=round(precision/n, 4) if n else 0,
                mean_steps=round(statistics.mean(o['tool_steps'] for o in outputs), 4) if n else 0,
                mean_latency_seconds=round(statistics.mean(o['seconds'] for o in outputs), 4) if n else 0,
                fallbacks=sum(o.get('fallback', False) for o in outputs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true')
    mode.add_argument('--baseline', action='store_true')
    parser.add_argument('--set', type=Path, default=Path(__file__).with_name('location_set.jsonl'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = LocalSource()
    rows, landmarks, points = source.streets(), source.landmarks(), source.street_points()
    index = IncidentIndex(rows, landmarks)
    cases = [json.loads(line) for line in args.set.read_text(encoding='utf-8').splitlines() if line.strip()]
    if args.live:
        if not args.output:
            parser.error('--live requires --output for provider receipts and step traces')
        load_env()
        from app.llm.nightshift import Nightshift
        trace = args.output.with_suffix('.trace.jsonl')
        client = Nightshift(trace)
    else:
        trace = args.output.with_suffix('.trace.jsonl') if args.output else None
        client = ScriptedPolicy(rows, landmarks, index)
    outputs = []
    for case in cases:
        started = time.monotonic()
        fields, _ = validate(baseline.extract(case['text'], rows), case['text'])
        index.resolve(fields, case['text'])
        if args.baseline:
            out = baseline_result(rows, landmarks, fields, case['text'])
        else:
            if args.live:
                client.start_message(case['id'])
            street, _, _, out, _ = location.locate(rows, landmarks, fields, case['text'], REPLAY,
                client, time.monotonic()+480, index=index, points=points, trace=trace)
            if out['location_path'] == 'deterministic':
                out = {**out, 'candidate': dict(kind='street', name=street['display_name'], city=street['municipality'])}
        outputs.append({'id': case['id'], **out, 'seconds': round(time.monotonic()-started, 4)})
    report = dict(mode='live' if args.live else 'offline_deterministic_baseline' if args.baseline else 'offline_scripted_policy',
                  synthetic=True, critic='real_provider' if args.live else 'scripted_empty_objections_NOT_semantic_evaluation',
                  metrics=score(outputs, cases), cases=outputs)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'cases'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
