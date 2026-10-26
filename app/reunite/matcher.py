"""Deterministic candidate matcher. Produces evidence-bearing candidates only; it has no confirm path."""
import hashlib
from app.reunite.records import fold, metres, ts, PARTICLES

NEAR_M, FAR_M = 3000, 40000
WINDOW_DAYS = 21


def _tokens(name):
    return [t for t in fold(name).replace("'", '').split() if t not in PARTICLES and len(t) > 1]


def _name_evidence(a, b):
    """Strongest name agreement as written: full (>=2 shared tokens) or first-name only; no fuzzy identity guessing."""
    best = None
    for x in a['names']:
        for y in b['names']:
            tx, ty = _tokens(x), _tokens(y)
            shared = [t for t in tx if t in ty]
            if len(shared) >= 2:
                return 'full', f'{x} / {y}'
            if shared and tx[0] == ty[0]:
                best = best or ('first', f'{x} / {y}')
    return best or (None, None)


def _age_evidence(a, b):
    pairs = [(x, y) for x in a['ages'] for y in b['ages']]
    if not pairs:
        return None, None
    d = min(abs(x - y) for x, y in pairs)
    return ('match' if d <= 2 else 'conflict' if d > 5 else 'weak'), f'{a["ages"]} / {b["ages"]}'


def _place_evidence(a, b):
    if None not in (a['lat'], a['lon'], b['lat'], b['lon']):
        d = metres(a['lat'], a['lon'], b['lat'], b['lon'])
        if d <= NEAR_M:
            return 'near', f'{d / 1000:.1f} km'
        if d > FAR_M:
            return 'far', f'{d / 1000:.0f} km'
        return 'region', f'{d / 1000:.1f} km'
    shared = sorted(set(a['place_tokens']) & set(b['place_tokens']))
    if shared:
        return 'name', ' '.join(shared)
    if a['municipality'] and a['municipality'] == b['municipality']:
        return 'municipality', a['municipality']
    return None, None


def pair_id(missing, found):
    return hashlib.sha256(f"{missing['id']}|{found['id']}".encode()).hexdigest()[:14]


def score(missing, found):
    """Return a candidate dict or None. Requires a full name, or first name + (age match and place evidence)."""
    ev, total = [], 0
    kind, detail = _name_evidence(missing, found)
    if kind == 'full':
        total += 5; ev.append({'kind': 'name', 'strength': 'full', 'detail': detail, 'label_pt': 'Nome igual ao escrito nas duas mensagens'})
    elif kind == 'first':
        total += 1; ev.append({'kind': 'name', 'strength': 'first', 'detail': detail, 'label_pt': 'Só o primeiro nome coincide (fraco)'})
    akind, adetail = _age_evidence(missing, found)
    if akind == 'conflict':
        return None
    if akind == 'match':
        total += 2; ev.append({'kind': 'age', 'strength': 'match', 'detail': adetail, 'label_pt': 'Idades compatíveis (±2 anos) como escritas'})
    elif akind == 'weak':
        total += 1; ev.append({'kind': 'age', 'strength': 'weak', 'detail': adetail, 'label_pt': 'Idades próximas (até 5 anos)'})
    pkind, pdetail = _place_evidence(missing, found)
    if pkind == 'far':
        return None
    place_pts = {'near': 3, 'name': 2, 'region': 1, 'municipality': 1}.get(pkind, 0)
    if place_pts:
        total += place_pts; ev.append({'kind': 'place', 'strength': pkind, 'detail': pdetail, 'label_pt': 'Local do relato próximo ao local do resgate/abrigo'})
    try:
        gap = (ts(found['at']) - ts(missing['at'])).total_seconds() / 86400
    except (TypeError, ValueError):
        return None
    if 0 <= gap <= WINDOW_DAYS:
        total += 1; ev.append({'kind': 'time', 'strength': 'after', 'detail': f'{gap:.1f} d', 'label_pt': 'Resgate/entrada registrado depois do pedido de notícias'})
    elif gap < 0:
        ev.append({'kind': 'time', 'strength': 'before', 'detail': f'{-gap:.1f} d', 'label_pt': 'Resgate registrado antes do pedido (possível, não é prova)'})
    elif gap > WINDOW_DAYS:
        return None
    if kind != 'full' and not (kind == 'first' and akind == 'match' and place_pts >= 2):
        return None
    conf = 'alta' if total >= 8 else 'média' if total >= 6 else 'baixa'
    return {'id': pair_id(missing, found), 'missing': missing, 'found': found, 'score': total, 'confidence': conf, 'evidence': ev,
            'status': 'candidate', 'requires_human': True,
            'notice_pt': 'Candidato por coincidência de dados escritos; não confirma identidade. Só uma pessoa confirma.'}


def match(missing, found, asof=None):
    """Ranked candidates; found/missing observed after `asof` are ignored (no hindsight)."""
    limit = ts(asof) if asof else None
    live = lambda r: limit is None or ts(r['at']) <= limit
    out = []
    for m in filter(live, missing):
        for f in filter(live, found):
            c = score(m, f)
            if c:
                out.append(c)
    out.sort(key=lambda c: (-c['score'], c['id']))
    return out
