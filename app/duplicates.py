"""Deterministic possible-duplicate blocking; never authorizes a merge."""
import re
from app.decide import timestamp
from app.geo.streets import normalize
from app.geo.hazards import distance_m


def value(case, key):
    return case.get('fields', {}).get(key, {}).get('value')


def candidate(a, b):
    if abs((timestamp(a['received_at'])-timestamp(b['received_at'])).total_seconds()) > 43200:
        return None
    reasons = []
    la, lb = a.get('landmark_check') or {}, b.get('landmark_check') or {}
    ma, mb = la.get('matched') or {}, lb.get('matched') or {}
    if la.get('status') == lb.get('status') == 'resolved' and ma.get('osm_id') and ma.get('osm_id') == mb.get('osm_id'):
        reasons.append('same_resolved_osm_id')
    city_a, city_b = value(a, 'municipality'), value(b, 'municipality')
    same_city = bool(city_a and city_b and normalize(str(city_a)) == normalize(str(city_b)))
    street_a, street_b = value(a, 'street'), value(b, 'street')
    same_street = same_city and street_a and street_b and normalize(str(street_a)) == normalize(str(street_b))
    if same_street and value(a, 'number') is not None and str(value(a, 'number')) == str(value(b, 'number')):
        reasons.append('same_street_number')
    pa, pb = a.get('position') or {}, b.get('position') or {}
    profiles = ('people', 'children', 'elderly', 'disabled', 'pets')
    overlap = any(type(value(a,k)) is int and value(a,k)>0 and value(a,k)==value(b,k) for k in profiles)
    # Explicit different house numbers must not become a proximity suggestion.
    different_number = same_street and value(a,'number') is not None and value(b,'number') is not None and str(value(a,'number')) != str(value(b,'number'))
    if not different_number and overlap and same_city and pa.get('position_kind','').startswith('street') and pb.get('position_kind','').startswith('street'):
        if distance_m(pa['lat'],pa['lon'],pb['lat'],pb['lon']) <= 150:
            reasons.append('street_points_150m_profile_overlap')
    ta, tb = (set(re.findall(r'\w+', normalize(c.get('text','')))) for c in (a,b))
    overlap_score = len(ta & tb)/max(len(ta),len(tb)) if ta and tb else 0
    if overlap_score >= .8:
        reasons.append('normalized_text_overlap_0.8')
    return {'score':round(max(.8 if 'normalized_text_overlap_0.8' in reasons else 0, .95 if 'same_street_number' in reasons or 'same_resolved_osm_id' in reasons else .7),3),
            'token_overlap':round(overlap_score,3),'reasons':reasons} if reasons else None


def candidates(case, cases):
    out=[]
    for other in cases:
        if other['case_id']==case['case_id'] or other.get('status','').startswith('MERGED_INTO:'):
            continue
        match=candidate(case,other)
        if match:
            out.append({'case_id':other['case_id'], **match})
    return sorted(out,key=lambda x:(-x['score'],x['case_id']))


# --- P1S: automatic, reversible repost linking (identical text, same place, within 24 h). ---
REPOST_HOURS = 24
REPOST_OVERLAP = .9


def _tokens(text):
    return set(re.findall(r'\w+', normalize(text or '')))


def _numbers(text):
    return sorted(re.findall(r'\d+', text or ''))


def overlap(a, b):
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb)/max(len(ta), len(tb)) if ta and tb else 0.0


def same_place(a, b):
    """Require the same resolved landmark or catalogued street/address in the same city."""
    la, lb = a.get('landmark_check') or {}, b.get('landmark_check') or {}
    if any(l.get('status') == 'ambiguous' for l in (la, lb)):
        return False
    if any(c.get('field') in ('municipality', 'street', 'number', 'landmark', 'cross_street')
           for case in (a, b) for c in case.get('contradictions') or []):
        return False
    ma, mb = la.get('matched') or {}, lb.get('matched') or {}
    if la.get('status') == lb.get('status') == 'resolved' and ma.get('osm_id') and ma.get('osm_id') == mb.get('osm_id'):
        return True
    city_a, city_b = value(a, 'municipality'), value(b, 'municipality')
    if not city_a or not city_b or normalize(str(city_a)) != normalize(str(city_b)):
        return False
    if not all((c.get('checks') or {}).get('found') for c in (a, b)):
        return False
    street_a, street_b = value(a, 'street'), value(b, 'street')
    if street_a and street_b and normalize(str(street_a)) == normalize(str(street_b)):
        na, nb = value(a, 'number'), value(b, 'number')
        return (None if na is None else str(na)) == (None if nb is None else str(nb))
    return False


def _own_texts(case):
    rows = case.get('messages') or [{'text': case.get('text', ''), 'received_at': case['received_at']}]
    return [(m.get('text', ''), m.get('received_at', case['received_at'])) for m in rows]


def repost_match(new, old):
    """Return {overlap, hours, reason} when `new` is a repost of `old`, else None. Pure; never merges two incidents."""
    from app.derive_count import INJECTION
    if old.get('status', '').startswith(('MERGED_INTO:', 'ASSIGNED:')) or old.get('merge_state'):
        return None
    if (new.get('routing_flags') or {}).get('injection') or INJECTION.search(new.get('text', '')):
        return None  # injected text is never absorbed silently; it stays its own REVIEW case
    if not same_place(new, old):
        return None
    best = None
    for text, at in _own_texts(old):
        hours = abs((timestamp(new['received_at'])-timestamp(at)).total_seconds())/3600
        score = overlap(new.get('text', ''), text)
        if _numbers(new.get('text', '')) != _numbers(text):
            continue  # a changed count/number is new information, never a repost
        if hours <= REPOST_HOURS and score >= REPOST_OVERLAP and (best is None or score > best[0]):
            best = (score, hours)
    return {'overlap': round(best[0], 3), 'hours': round(best[1], 2),
            'reason': 'identical_text_same_place_within_24h'} if best else None


def find_repost(new, cases):
    """Earliest-received candidate with the highest overlap; None if the message is a new incident."""
    found = []
    for old in cases:
        if old['case_id'] == new.get('case_id'):
            continue
        match = repost_match(new, old)
        if match:
            found.append((-match['overlap'], old['received_at'], old['case_id'], old, match))
    if not found:
        return None
    found.sort(key=lambda row: row[:3])
    return found[0][3], found[0][4]
