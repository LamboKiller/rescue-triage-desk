"""Deterministic OSM name matching. Model guesses never become coordinates."""
import re
import unicodedata

STOP = {'a', 'o', 'as', 'os', 'de', 'da', 'do', 'das', 'dos', 'em', 'no', 'na', 'estacao', 'hospital'}


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold()) if unicodedata.category(c) != 'Mn')
    return ' '.join(w for w in re.findall(r'[a-z0-9]+', text) if w not in STOP)


def match(rows, place_name='', landmark_quote='', municipality='', neighbourhood='', replay='2024-05-06'):
    queries = [normalize(q) for q in (place_name, landmark_quote) if normalize(q)]
    candidates = []
    for row in rows:
        if not municipality or normalize(row['municipality']) != normalize(municipality):
            continue
        score = 0
        for name in [row['name']] + re.split(r'[|;]', row.get('alt_names', '')):
            n = normalize(name)
            if not n:
                continue
            for q in queries:
                overlap = len(set(q.split()) & set(n.split())) / len(set(q.split()) | set(n.split()))
                if q == n:
                    score = max(score, 1.0)
                elif overlap >= .8:
                    score = max(score, .9 + overlap*.05)
                elif min(len(q), len(n)) >= 5 and (q in n or n in q):
                    score = max(score, .8)
        if score:
            preference = bool(neighbourhood and normalize(neighbourhood) == normalize(row.get('neighbourhood', '')))
            candidates.append({**row, 'score': round(score, 3), 'neighbourhood_preferred': preference})
    candidates.sort(key=lambda r: (-r['score'], -r['neighbourhood_preferred'], r['name'], r['osm_id']))
    # Multiple OSM features for one place remain ambiguous unless one name is clearly better.
    clear = bool(candidates) and (len(candidates) == 1 or candidates[0]['score']-candidates[1]['score'] >= .1
              or (candidates[0]['neighbourhood_preferred'] and not candidates[1]['neighbourhood_preferred']
                  and candidates[0]['score'] == candidates[1]['score']))
    dates = [d for d in ('2024-05-06', '2024-05-08') if d <= replay[:10]]
    observed = dates[-1] if dates else None
    return {'status': 'resolved' if clear else ('ambiguous' if candidates else 'unresolved'),
            'matched': candidates[0] if clear else None, 'candidates': candidates[:3], 'observed_date': observed,
            'retrospective_water_overlap': candidates[0].get('in_water_'+observed) in ('1', True) if clear and observed else None,
            'in_water_by_date': None, 'publication_available': False}
