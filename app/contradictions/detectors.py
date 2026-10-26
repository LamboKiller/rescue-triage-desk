"""Deterministic cross-source contradiction detectors (N2 A3).

Each detector compares ONE claim in the citizen message with ONE other source that is already in the case or the desk's
state (flood/depth layer, road closures, shelter state, crew reports, duplicate cases). Output items carry both sources with
ids + exact quotes and a strength:

  weak    retrospective or low-confidence layer (e.g. HAND depth, created after the event): opens an item, no question push
  medium  a dated/typed record of another source disagrees with the message: open item + callback question
  strong  a fresh, specific, human-made record disagrees (shelter report <= 6 h, crew report on the same address)

Nothing here changes a decision. Unknown is never treated as contradiction (no layer value -> no item).
"""
import hashlib
import re
import unicodedata
from datetime import timedelta
from app.decide import timestamp

STRENGTHS = ('weak', 'medium', 'strong')
FRESH_SHELTER_HOURS = 6
MIN_ALIAS = 4
BODY_DEPTH = (  # folded phrase -> metres (lower bound of the claimed level)
    ('tornozelo', .15), ('canela', .3), ('joelho', .5), ('coxa', .8), ('cintura', 1.0), ('barriga', 1.0), ('peito', 1.3),
    ('pescoco', 1.5), ('ate o teto', 2.5), ('cobr\\w+ (?:a|o|toda|todo) (?:casa|telhado)', 2.5), ('telhado', 2.5))
NEGATION = re.compile(r'\b(?:nao|nunca|sem|jamais|ninguem)\b[^,.;!?\n]{0,40}$')


def fold(text):
    s = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return s


def folded_map(text):
    """(folded string, offsets) so a match in the folded text maps back to the exact original substring."""
    chars, offsets = [], []
    for i, ch in enumerate(text):
        for f in fold(ch):
            chars.append(f)
            offsets.append(i)
    return ''.join(chars), offsets


def exact(text, plain, offsets, start, end):
    return text[offsets[start]:offsets[end - 1] + 1]


def negated(plain, start):
    clause = re.split(r'[,.;!?\n]', plain[:start])[-1]
    return bool(NEGATION.search(clause[-60:]))


def item_id(case_key, kind, *refs):
    return 'ct-' + hashlib.sha1('|'.join([str(case_key), kind, *map(str, refs)]).encode()).hexdigest()[:10]


def source(role, src, ref, quote, **extra):
    return {'role': role, 'source': src, 'ref': ref, 'quote': quote, **extra}


def citizen_texts(case):
    out = []
    for m in case.get('messages') or []:
        if isinstance(m, dict) and m.get('text') and m.get('message_id') and m.get('role', 'citizen') != 'operator':
            out.append((m['message_id'], m['text'], m.get('received_at')))
    if not out and case.get('text'):
        out.append((case.get('message_id'), case['text'], case.get('received_at')))
    return out


# ------------------------------------------------------------------ 1. water level vs flood/depth layer (retrospective)
def claimed_depth(text):
    """(metres, exact quote) of the highest explicit water level claim, else None. Negated/hedged claims are ignored."""
    plain, off = folded_map(text)
    found = []
    for m in re.finditer(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:m\b|metros?\b|mts?\b)(?:\s+de\s+agua)?', plain):
        around = plain[max(0, m.start() - 30):m.end() + 30]
        if re.search(r'agua|nivel|alag|enchente', around) and not negated(plain, m.start()):
            value = float(m[1].replace(',', '.'))
            if 0 < value <= 15:
                found.append((value, exact(text, plain, off, m.start(), m.end())))
    for phrase, metres in BODY_DEPTH:
        for m in re.finditer(r'agua\b[^,.;!?\n]{0,25}\b' + phrase + r'\b', plain):
            if not negated(plain, m.start()) and not re.search(r'\b(?:nao|nunca|jamais|sem)\b', m[0]):
                found.append((metres, exact(text, plain, off, m.start(), m.end())))
    return max(found, default=None)


def water_vs_layer(case, key):
    hz = case.get('hazards') or {}
    depth = hz.get('depth_m')
    if not isinstance(depth, (int, float)) or hz.get('depth_observed_date') is None:
        return []
    out = []
    for mid, text, _ in citizen_texts(case):
        claim = claimed_depth(text)
        if not claim or claim[0] < depth + 1.0:  # HAND is +-1 m: anything inside the tolerance is not a contradiction
            continue
        layer_quote = ('profundidade estimada %s m (%s), observada em %s' % (depth, hz.get('depth_band'), hz['depth_observed_date']))
        out.append({'kind': 'water_level_vs_flood_layer', 'strength': 'weak', 'retrospective': True,
                    'sources': [source('A', 'message', mid, claim[1], claimed_m=claim[0]),
                                source('B', 'flood_layer', 'hazards.depth:' + hz['depth_observed_date'], layer_quote, depth_m=depth,
                                       confidence=hz.get('depth_confidence'))],
                    'basis_pt': 'Camada HAND retrospectiva (±1 m, criada após o evento): pode subestimar; nunca prova nível seco.',
                    'template_pt': 'A mensagem fala em "%s", mas a camada retrospectiva indica %s m. Confirmar com quem pediu ajuda o nível da água?' % (claim[1], depth),
                    'refs': [mid, hz['depth_observed_date']]})
        break
    hc = case.get('hydro_conflict')
    if isinstance(hc, dict) and hc.get('quote'):
        out.append({'kind': 'life_safety_vs_dry_point', 'strength': 'weak', 'retrospective': True,
                    'sources': [source('A', 'message', case.get('message_id'), hc['quote']),
                                source('B', 'flood_layer', 'hydro:' + str(hc.get('observed_date')), hc.get('message_pt', '')[:160], confidence=hc.get('confidence'))],
                    'basis_pt': 'Camada retrospectiva: pode ser cobertura e não recessão. Só duvidoso, nunca descarte.',
                    'template_pt': 'O relato de risco ("%s") fica fora da área alagada observada. Confirmar o endereço exato por retorno?' % hc['quote'],
                    'refs': [case.get('message_id'), hc.get('observed_date')]})
    return out


# ------------------------------------------------------------------ 2. route-access claim vs active road closure
PASSABLE = re.compile(r'\b(?:da pra (?:chegar|passar|entrar)|(?:rua|estrada|via|acesso|ponte|br[ -]?\d{2,3}) (?:esta )?(?:livre|liberad[ao]|aberta|transitavel)|passa (?:carro|caminhao|onibus|van)|(?:carro|caminhao|onibus) (?:passa|chega|consegue passar))')
ROAD = re.compile(r'\b(?:br|rs|rsc)[ -]?(\d{2,3})\b')


def road_access(case, key):
    hz = case.get('hazards') or {}
    closures = [c for c in hz.get('closures_nearby') or [] if c.get('status') == 'closed' and isinstance(c.get('distance_m'), (int, float))
                and c['distance_m'] <= 1000]
    if not closures:
        return []
    for mid, text, _ in citizen_texts(case):
        plain, off = folded_map(text)
        for m in PASSABLE.finditer(plain):
            if negated(plain, m.start()):
                continue
            said = {r[1] for r in ROAD.finditer(plain)}
            named = [c for c in closures if said and said & set(ROAD.findall(fold(c.get('road', ''))))]
            c = (named or closures)[0]
            strength = 'medium' if named else 'weak'
            quote = exact(text, plain, off, m.start(), m.end())
            record = '%s %s, %s, fechada desde %s (a %s m)' % (c['road'], c.get('segment', ''), c['status'], c['from_date'][:10], c['distance_m'])
            return [{'kind': 'route_access_vs_closure', 'strength': strength, 'retrospective': False,
                     'sources': [source('A', 'message', mid, quote),
                                 source('B', 'road_closure', c.get('record_id') or c.get('id'), record, source_id=c.get('source_id'),
                                        geometry_status=c.get('geometry_status'))],
                     'basis_pt': 'Interdição por corredor candidato (geometria não verificada); %s.' % ('a via citada coincide com o registro' if named else 'a via citada não aparece no registro, apenas próxima'),
                     'template_pt': 'O relato diz que dá para chegar ("%s"), mas há interdição registrada (%s). Confirmar o acesso com quem pediu ajuda?' % (quote, c['road']),
                     'refs': [mid, c.get('record_id') or c.get('id')]}]
    return []


# ------------------------------------------------------------------ 3. shelter claim vs shelter state
FULL = re.compile(r'\b(?:lotad[oa]s?|lotou|cheio|cheia|sem vagas?|nao tem vagas?|nao ha vagas?|superlotad[oa])\b')
NOT_BE = re.compile(r'\bnao (?:esta|ta|estava)\s*$')
OPEN = re.compile(r'\b(?:tem vagas?|ha vagas?|com vagas?|aceitando|recebendo|vagas disponiveis)\b')


def shelter_claims(case, key, shelters, now):
    if shelters is None:
        return []
    try:
        aliases = shelters.aliases(now)
        folded_texts = [fold(t) for _, t, _ in citizen_texts(case)]
        if not any(len(a) >= MIN_ALIAS and a in ft for a in aliases for ft in folded_texts):
            return []  # no shelter named: skip the (costly) state computation
        states = {s['shelter_id']: s for s in shelters.state(now)}
    except Exception:
        return []
    out = []
    for mid, text, _ in citizen_texts(case):
        plain, off = folded_map(text)
        for alias, sid in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
            if len(alias) < MIN_ALIAS or sid not in states:
                continue
            a = re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', plain)
            if not a:
                continue
            window = plain[max(0, a.start() - 50):a.end() + 60]
            offset = max(0, a.start() - 50)
            claim = None
            for rx, kind in ((FULL, 'full'), (OPEN, 'open')):
                m = rx.search(window)
                if m and (not negated(plain, offset + m.start()) if kind == 'open' else
                          not NOT_BE.search(plain[:offset + m.start()][-16:])):
                    claim = (kind, offset + m.start(), offset + m.end())
                    break
            if not claim:
                continue
            st = states[sid]
            if claim[0] == 'full' and not (isinstance(st['remaining'], int) and st['remaining'] > 0):
                continue
            if claim[0] == 'open' and not st['full']:
                continue
            fresh = st.get('last_event_report_at') is not None and st.get('last_report_age_h') is not None and st['last_report_age_h'] <= FRESH_SHELTER_HOURS
            quote = exact(text, plain, off, min(a.start(), claim[1]), max(a.end(), claim[2]))
            out.append({'kind': 'shelter_state_vs_message', 'strength': 'strong' if fresh else 'medium', 'retrospective': not fresh,
                        'sources': [source('A', 'message', mid, quote),
                                    source('B', 'shelter_state', sid, st['capacity_note_pt'], full=st['full'], remaining=st['remaining'],
                                           basis=st['capacity_basis'], last_report_at=st['last_report_at'])],
                        'basis_pt': 'Relato de abrigo %s' % ('recente (até %d h)' % FRESH_SHELTER_HOURS if fresh else 'antigo ou retrato pré-existente; pode ter mudado'),
                        'template_pt': 'O relato diz "%s", mas o estado do abrigo indica o contrário (%s). Confirmar a vaga antes de orientar o deslocamento?' % (quote, st['capacity_note_pt']),
                        'refs': [mid, sid]})
            break
    return out


# ------------------------------------------------------------------ 4. crew reports (own case) and 5. duplicates
def rescued_by_crew(case):
    """Crew/operator feedback rows that say the people are out or not there: [(row, kind, quote)]."""
    out = []
    for fb in case.get('feedback') or []:
        if fb.get('source', 'crew') != 'crew':
            continue
        for o in fb.get('outcomes') or []:
            if o.get('kind') in ('left_by_other_means', 'not_found') or (o.get('kind') == 'remaining_n' and o.get('value') == 0):
                out.append((fb, o['kind'], o['quote']))
    return out


STILL_THERE = re.compile(r'\b(?:ainda (?:estamos|estou|esta|estao|tem|temos|precisamos)|continuamos|seguimos|ninguem (?:veio|chegou|apareceu)|nao veio ninguem|nao chegou ninguem)\b')


def crew_vs_message(case, key):
    out = []
    for fb, kind, quote in rescued_by_crew(case):
        for mid, text, received in citizen_texts(case):
            try:
                later = received and timestamp(received) > timestamp(fb['received_at'])
            except Exception:
                later = False
            if not later:
                continue
            plain, off = folded_map(text)
            m = STILL_THERE.search(plain)
            if not m or negated(plain, m.start()):
                continue
            q = exact(text, plain, off, m.start(), m.end())
            out.append({'kind': 'crew_report_vs_message', 'strength': 'medium', 'retrospective': False,
                        'sources': [source('A', 'message', mid, q), source('B', 'crew_report', fb['received_at'], quote, outcome=kind, actor=fb.get('actor'))],
                        'basis_pt': 'O relato da equipe é anterior à mensagem; a mensagem posterior pode ser a situação atual.',
                        'template_pt': 'A equipe relatou "%s", mas depois chegou "%s". Ligar de volta para confirmar se há pessoas no local?' % (quote, q),
                        'refs': [mid, fb['received_at']]})
            break
    return out


def peer_checks(case, key, peers):
    """Duplicate cases: crew already rescued there (strong when the address is identical) or counts that disagree."""
    from app.duplicates import candidate
    out = []
    own_people = ((case.get('fields') or {}).get('people') or {}).get('value')
    own_text = case.get('text', '')
    for peer in peers or []:
        if peer.get('case_id') == key or str(peer.get('status', '')).startswith('MERGED_INTO:'):
            continue
        try:
            match = candidate({**case, 'case_id': key}, peer)
        except Exception:
            continue
        if not match:
            continue
        po, pn = (peer.get('fields') or {}).get('number', {}).get('value'), (case.get('fields') or {}).get('number', {}).get('value')
        if po is not None and pn is not None and str(po) != str(pn):
            continue  # explicit different house numbers: not the same address
        same_address = any(r in match['reasons'] for r in ('same_resolved_osm_id', 'same_street_number'))
        crew = rescued_by_crew(peer)
        peer_status = peer.get('outcome_status') or peer.get('status')
        if crew and peer_status in ('RESCUED', 'NOT_FOUND', 'field_confirmed', 'reported_rescued_unconfirmed', 'PARTIAL') and crew[-1][1] != 'not_found':
            fb, kind, quote = crew[-1]
            if str(case.get('status', '')) in ('RESCUED', 'field_confirmed'):
                continue
            strength = 'strong' if same_address else 'medium'
            out.append({'kind': 'crew_already_rescued', 'strength': strength, 'retrospective': False,
                        'suggestion': {'action': 'report_rescued', 'status': 'RESCUED', 'requires_human': True} if strength == 'strong' else None,
                        'sources': [source('A', 'message', case.get('message_id'), own_text[:140]),
                                    source('B', 'crew_report', peer['case_id'] + '@' + str(fb.get('received_at')), quote, outcome=kind,
                                           reasons=match['reasons'], actor=fb.get('actor'))],
                        'basis_pt': 'Mesmo endereço em outro caso já retirado pela equipe' if same_address else 'Local parecido (%s) com caso já retirado pela equipe; pode ser outra casa' % ', '.join(match['reasons']),
                        'template_pt': 'A equipe já relatou "%s" em um caso do mesmo endereço. Marcar este pedido como resgatado (confirmação humana) ou ligar de volta?' % quote,
                        'refs': [case.get('message_id'), peer['case_id']]})
            continue
        peer_people = ((peer.get('fields') or {}).get('people') or {}).get('value')
        if type(own_people) is int and type(peer_people) is int and own_people != peer_people and match['score'] >= .8:
            pq = ((peer.get('fields') or {}).get('people') or {}).get('quote') or str(peer_people)
            oq = ((case.get('fields') or {}).get('people') or {}).get('quote') or str(own_people)
            out.append({'kind': 'duplicate_count_mismatch', 'strength': 'medium' if same_address else 'weak', 'retrospective': False,
                        'sources': [source('A', 'message', case.get('message_id'), oq), source('B', 'duplicate_case', peer['case_id'], pq, reasons=match['reasons'])],
                        'basis_pt': 'Possível duplicata com contagens diferentes; a contagem maior não é descartada.',
                        'template_pt': 'Dois pedidos parecidos trazem contagens diferentes ("%s" e "%s"). Confirmar quantas pessoas há no endereço?' % (oq, pq),
                        'refs': [case.get('message_id'), peer['case_id']]})
    return out


def detect(case, *, case_key, peers=(), shelters=None, now=None):
    """All contradiction items for one case; deterministic, no I/O besides the shelter state passed in."""
    items = []
    for fn, args in ((water_vs_layer, ()), (road_access, ()), (crew_vs_message, ())):
        items += fn(case, case_key, *args)
    items += shelter_claims(case, case_key, shelters, now or case.get('replay_time') or case.get('received_at'))
    items += peer_checks(case, case_key, peers)
    out, seen = [], set()
    for it in items:
        it['id'] = item_id(case_key, it['kind'], *it.pop('refs', []))
        if it['id'] in seen:
            continue
        seen.add(it['id'])
        it.setdefault('suggestion', None)
        it['question_pt'] = it.pop('template_pt')
        it['phrased_by'] = 'template'
        it['state'] = 'open'
        out.append(it)
    out.sort(key=lambda i: (-STRENGTHS.index(i['strength']), i['id']))
    return out
