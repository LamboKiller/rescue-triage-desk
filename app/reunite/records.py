"""Extract minimal, redacted search/found records. Only what a message states; no identity inference."""
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from app.redact import redact

BRT = timezone(timedelta(hours=-3))
PARTICLES = {'da', 'de', 'do', 'das', 'dos', 'e'}
# Capitalised words that are never person names (places, titles, salutations).
NOT_NAME = {'rua', 'avenida', 'av', 'travessa', 'bairro', 'vila', 'estrada', 'ilha', 'praca', 'porto', 'alegre', 'canoas', 'sao', 'leopoldo',
            'abrigo', 'ginasio', 'escola', 'igreja', 'hospital', 'centro', 'rio', 'grande', 'sul', 'brasil', 'ola', 'bom', 'boa', 'por', 'favor',
            'obrigado', 'obrigada', 'senhor', 'senhora', 'dona', 'seu', 'meu', 'minha', 'moro', 'eu', 'ele', 'ela', 'ontem', 'hoje',
            'whatsapp', 'telefone', 'contato', 'cep', 'bloco', 'apto', 'casa', 'sarandi', 'navegantes', 'humaita', 'cais', 'guaiba',
            'sinos', 'taquari', 'jacui', 'caixas', 'pelotas', 'eldorado', 'cachoeirinha', 'gravatai', 'novo', 'hamburgo', 'defesa', 'civil',
            'bombeiros', 'barco', 'lancha', 'voluntarios', 'equipe', 'resgate', 'nome', 'idoso', 'idosa', 'crianca', 'menino', 'menina'}
CUE = re.compile(r'(?:chamad[oa]s?|nome|procuro|procurando|noticias? d[eoa]|achar|pai|mae|vo|vovo|avo|irmao|irma|filh[oa]|marido|esposa|mulher|tio|tia|primo|prima|'
                 r'sobrinh[oa]|neto|neta|senhor|senhora|dona|seu|idos[oa]|menin[oa]|crianca|resgatad[oa]s?|abrigad[oa]s?|deu entrada|chegou|acolhid[oa]s?|entregue?s?)\b[^.\n;]{0,45}$')
NAME = re.compile(r"\b([A-ZÀ-Ú][a-zà-ú']{1,20}(?:\s+(?:d[aeo]s?|e)\s+|\s+)?(?:[A-ZÀ-Ú][a-zà-ú']{1,20}(?:\s+(?:d[aeo]s?)\s+|\s+)?){0,3})")
AGE = re.compile(r'\b(\d{1,3})\s*(?:anos|a\.)(?![a-zà-ú])|\b(?:idade|tem)\s*:?\s*(\d{1,3})\b', re.I)
WELFARE = re.compile(r'\b(?:procuro|procurando|procuramos|desaparecid[oa]|sumiu|sem noticias?|perdi (?:o )?contato|ultima vez|ultimo lugar|nao (?:responde|atende)|'
                     r'ninguem (?:sabe|tem noticia)|alguem (?:viu|sabe|tem noticia)|noticias? d[eoa]|nao sei onde)\b')
FOUND = re.compile(r'\b(?:resgatamos|retiramos|pegamos|levamos|resgatad[oa]s?|abrigad[oa]s?|acolhid[oa]s?|deu entrada|chegou|chegaram|entregue?s?|check-?in|esta no abrigo|estao no abrigo|retirad[oa]s?)\b')
PLACE = re.compile(r'\b(?i:rua|av\.?|avenida|travessa|bairro|vila|estrada|localidade|ilha|comunidade|praca|loteamento)\s+((?:(?:d[aeo]s?\s+)?[A-ZÀ-Ú][a-zà-ú]{2,20}\s?){1,3})')
PLACE_STOP = {'rua', 'avenida', 'bairro', 'vila', 'alegre', 'grande', 'sul', 'centro', 'abrigo'}
LEAD = {'resgatado', 'resgatada', 'resgatados', 'abrigado', 'abrigada', 'abrigados', 'acolhido', 'acolhida', 'chegou', 'entregue', 'retirado', 'retirada'}
UNIT = re.compile(r'\b(?:cep\s*:?\s*)?\d{5}-?\d{3}\b|\b(?:apto?\.?|apartamento|bloco|bl\.?|sala|fundos|casa dos fundos)\s*\w{0,6}\b|\b\d{7,}\b', re.I)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).lower()) if unicodedata.category(c) != 'Mn')


def ts(value):
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=BRT)


def scrub(text, limit=220):
    """Redact phones/e-mails/CPF, then drop address complements (CEP, apartment, bloco); street + number stay."""
    out = UNIT.sub('[REDIGIDO]', redact(str(text or '')))
    return re.sub(r'\s+', ' ', out).strip()[:limit]


def metres(a, b, c, d):
    p = math.radians
    h = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def names(text):
    """Names only when a cue word (relation, 'chamado', 'resgatado'...) precedes them in the same clause; as written."""
    found, plain = [], str(text)
    for m in NAME.finditer(plain):
        raw = m.group(1).strip()
        lead = fold(raw.split()[0]) in LEAD  # 'Abrigado Paulo Mendes' at a sentence start: the verb is the cue, not a name
        if lead:
            raw = raw.split(None, 1)[1] if len(raw.split()) > 1 else ''
            if not raw:
                continue
        tokens = [t for t in raw.split() if fold(t) not in PARTICLES]
        if any(fold(t) in NOT_NAME for t in tokens):
            continue
        before = fold(plain[:m.start()])
        if not lead and not CUE.search(before[-60:]):
            continue
        # a capitalised run right after a place word is a street/bairro, not a person
        if not lead and re.search(r'(?:rua|avenida|av|travessa|bairro|vila|estrada|ilha|praca|em|no|na)\s*$', before[-14:]):
            continue
        if raw not in found:
            found.append(raw)
    return found[:6]


def ages(text):
    out = []
    for m in AGE.finditer(str(text)):
        n = int(m.group(1) or m.group(2))
        if 0 <= n <= 110 and n not in out:
            out.append(n)
    return out[:6]


def place_tokens(text):
    toks = set()
    for m in PLACE.finditer(str(text)):
        toks.update(t for t in fold(m.group(1)).split() if len(t) > 2 and t not in PLACE_STOP and t not in PARTICLES and not t.isdigit())
    return sorted(toks)


def _coords(case):
    agents = case.get('agents') if isinstance(case.get('agents'), dict) else {}
    loc = agents.get('location') if isinstance(agents.get('location'), dict) else {}
    for src in (case.get('location') if isinstance(case.get('location'), dict) else {}, loc, case):
        lat, lon = src.get('lat'), src.get('lon')
        if type(lat) in (int, float) and type(lon) in (int, float) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return float(lat), float(lon)
    return None, None


def _record(side, source, ref, at, text, lat=None, lon=None, municipality='', case_id=None, count=None):
    text = str(text or '')
    rid = hashlib.sha256(f'{side}|{source}|{ref}|{text}'.encode()).hexdigest()[:12]
    return {'id': rid, 'side': side, 'source': source, 'ref': str(ref), 'case_id': case_id, 'at': at, 'names': names(text), 'ages': ages(text),
            'place_tokens': place_tokens(text), 'municipality': fold(municipality or ''), 'lat': lat, 'lon': lon, 'count': count, 'quote': scrub(text)}


def missing_from_case(case):
    """Family search message (welfare / missing person). Needs a stated name or age; coordinates only if the case location is confirmed."""
    text = case.get('text')
    if not isinstance(text, str) or not WELFARE.search(fold(text)):
        return None
    lat, lon = _coords(case) if case.get('location_confirmed') else (None, None)
    agents = case.get('agents') if isinstance(case.get('agents'), dict) else {}
    muni = case.get('municipality') or (agents.get('location') or {}).get('municipality') or ''
    rec = _record('missing', 'review', case.get('case_id') or case.get('message_id'), case.get('received_at'), text, lat, lon, muni, case.get('case_id'))
    return rec if rec['names'] or rec['ages'] else None


def found_from_feedback(case):
    """Crew feedback that states who/how many were taken out; one record per feedback event."""
    out = []
    for i, ev in enumerate(case.get('feedback') or []):
        if not isinstance(ev, dict):
            continue
        outcomes = [o for o in ev.get('outcomes') or [] if isinstance(o, dict) and o.get('kind') == 'rescued_n']
        text = ' . '.join(p for p in [str(ev.get('text') or '')] + [str(o.get('quote') or '') for o in outcomes] if p)
        if not text or not (outcomes or FOUND.search(fold(text))):
            continue
        lat, lon = _coords(case) if case.get('location_confirmed') else (None, None)
        count = next((o.get('value') for o in outcomes if type(o.get('value')) is int), None)
        rec = _record('found', 'crew_feedback', f"{case.get('case_id')}#{i}", ev.get('received_at') or case.get('received_at'), text,
                      lat, lon, '', case.get('case_id'), count)
        # the rescued case's own text names the street the crew went to; keep street tokens only, never its person data
        rec['place_tokens'] = sorted(set(rec['place_tokens']) | set(place_tokens(case.get('text'))))
        if rec['names'] or rec['ages']:
            out.append(rec)
    return out


def found_from_shelter(event, place=None):
    """Shelter delivery/check-in event with free text naming who arrived."""
    text = event.get('quote')
    if not isinstance(text, str) or event.get('kind') == 'register' or not FOUND.search(fold(text)) and event.get('kind') != 'delivered':
        return None
    place = place or {}
    rec = _record('found', 'shelter', f"{event.get('shelter_id')}#{event.get('id') or event.get('seq')}", event.get('at'), text, place.get('lat'), place.get('lon'),
                  place.get('municipality') or '', event.get('case_id'), event.get('value') if event.get('kind') == 'delivered' else None)
    return rec if rec['names'] or rec['ages'] else None
