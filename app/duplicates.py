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
