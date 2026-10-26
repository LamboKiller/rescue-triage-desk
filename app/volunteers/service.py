"""Volunteer boat offers: pending asset -> human verification -> F1FLEET inventory. Event-sourced, nothing dispatchable before verify."""
import hashlib
import json
import re
import threading
from datetime import datetime, timezone, timedelta
from app.config import ROOT
from app.redact import redact
from app.volunteers import detect, extract as ex

PENDING, VERIFIED, REJECTED = 'pending_verification', 'available', 'rejected'
METHODS = {'ligacao': 'ligação confirmada', 'visto': 'barco visto pessoalmente', 'video': 'vídeo/foto recente conferida'}
LIMITS = {'barco_aluminio': 12, 'bote_inflavel': 15, 'jet_ski': 3, 'caminhao_alto': 40, 'anfibio': 30, 'helicoptero': 20,
          'ambulancia': 6, 'desconhecido': 60}
WARN = {'NO_CONTACT': 'Sem contato informado — não há como confirmar a oferta.',
        'NO_BASE': 'Base/local não informado.', 'NO_CAPACITY': 'Capacidade não informada.',
        'TYPE_UNKNOWN': 'Tipo de veículo não identificado; o operador deve definir o tipo.',
        'CAPACITY_IMPLAUSIBLE': 'Capacidade declarada acima do plausível para o tipo.',
        'MOTOR_IMPLAUSIBLE': 'Potência de motor declarada implausível.',
        'DUPLICATE_OFFER': 'Possível oferta duplicada (mesmo contato, ou mesma base e tipo em até 6 h).',
        'CONTACT_MANY_PLACES': 'O mesmo contato aparece em bases diferentes.',
        'TEMPLATE_TEXT': 'Texto com marcas de modelo/repasse em massa.', 'SYNTHETIC': '[SIMULADO] mensagem sintética.',
        'CAPACITY_DECLARED': 'Capacidade é a declarada pelo voluntário (não medida); confira se inclui a tripulação.'}
EVENT_KEYS = ('reason', 'method', 'note', 'into', 'unit_id')


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _when(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _norm(value):
    return re.sub(r'\W+', ' ', detect.fold(value or '')).strip()


def _actor(request):
    a = request.get('actor') if isinstance(request, dict) else None
    if not isinstance(a, str) or not a.strip() or len(a) > 120:
        raise ValueError('Identifique o operador.')
    return redact(a.strip())


class VolunteerService:
    def __init__(self, path=None, registry=None, client=None, now=None):
        self.path = path or ROOT / 'runtime' / 'volunteers.jsonl'
        self.registry, self.client, self.now = registry, client, now or _now
        self.lock = threading.RLock()

    # ---- event log ----
    def _events(self):
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding='utf-8-sig').splitlines() if l.strip()]

    def _append(self, kind, vid, actor, **payload):
        event = {'seq': len(self._events()) + 1, 'at': self.now(), 'kind': kind, 'id': vid, 'actor': actor, **payload}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as out:
            out.write(json.dumps(event, ensure_ascii=False) + '\n')
        return event

    def _records(self):
        recs = {}
        for e in self._events():
            r, k = recs.get(e['id']), e['kind']
            summary = {x: e[x] for x in ('seq', 'at', 'kind', 'actor')} | {x: e[x] for x in EVENT_KEYS if e.get(x)}
            if k == 'submitted':
                recs[e['id']] = {**e['record'], 'events': [summary]}
                continue
            if r is None:
                continue
            r['events'].append(summary)
            if k == 'verified':
                r.update(status=VERIFIED, unit_id=e['unit_id'], verification={'actor': e['actor'], 'method': e['method'], 'note': e.get('note'), 'at': e['at']})
            elif k == 'rejected':
                r.update(status=REJECTED, rejection={'actor': e['actor'], 'reason': e['reason'], 'at': e['at']})
            elif k == 'merged':
                r['merged_into'] = e['into']
            elif k == 'unmerged':
                r['merged_into'] = None
        return recs

    # ---- credibility ----
    def _warnings(self, rec, others):
        f, w = rec['fields'], []
        kind = f.get('asset_type', {}).get('value', 'desconhecido')
        if rec['contact']['present'] is None:
            w.append('NO_CONTACT')
        if 'base_place' not in f and 'base_detail' not in f:
            w.append('NO_BASE')
        if 'capacity' not in f:
            w.append('NO_CAPACITY')
        else:
            w.append('CAPACITY_DECLARED')
            if f['capacity']['value'] > LIMITS.get(kind, 60):
                w.append('CAPACITY_IMPLAUSIBLE')
        if kind == 'desconhecido':
            w.append('TYPE_UNKNOWN')
        hp = ((f.get('motor') or {}).get('value') or {}).get('hp')
        if hp and (hp > 600 or (kind == 'barco_aluminio' and hp > 250)):
            w.append('MOTOR_IMPLAUSIBLE')
        if self.proposals(rec, others):
            w.append('DUPLICATE_OFFER')
        h = rec['contact']['hash']
        if h:
            places = {_norm(o['fields'].get('base_place', {}).get('quote')) for o in others if o['contact']['hash'] == h and o['id'] != rec['id']}
            places.add(_norm(f.get('base_place', {}).get('quote')))
            if len({p for p in places if p}) >= 2:
                w.append('CONTACT_MANY_PLACES')
        try:  # reuse the credibility package: placeholder / mass-template markers
            from app.credibility.signals import detect as sig
            hist = [{'id': o['id'], 'text': o['text'], 'time': o['received_at']} for o in others if o['id'] != rec['id']]
            if any(s['id'] in ('PLACEHOLDER_TEMPLATE', 'TEMPLATE_MULTI_ADDRESS') for s in sig(rec['text'], time=rec['received_at'], history=hist)):
                w.append('TEMPLATE_TEXT')
        except Exception:
            pass
        if rec.get('synthetic'):
            w.append('SYNTHETIC')
        return [{'code': c, 'text_pt': WARN[c]} for c in w]

    def proposals(self, rec, others):
        """Merge proposals: same contact hash, or same base + known type within 6 h. Always a proposal, never automatic."""
        out, t = [], _when(rec['received_at'])
        kind = rec['fields'].get('asset_type', {}).get('value')
        base = _norm(rec['fields'].get('base_place', {}).get('quote'))
        for o in others:
            if o['id'] == rec['id'] or o['status'] == REJECTED or o.get('merged_into') == rec['id']:
                continue
            reason = None
            if rec['contact']['hash'] and rec['contact']['hash'] == o['contact']['hash']:
                reason = 'mesmo contato'
            else:
                u = _when(o['received_at'])
                okind = o['fields'].get('asset_type', {}).get('value')
                if (base and base == _norm(o['fields'].get('base_place', {}).get('quote')) and kind and kind != 'desconhecido'
                        and kind == okind and t and u and abs(t - u) <= timedelta(hours=6)):
                    reason = 'mesma base e tipo em até 6 h'
            if reason:
                out.append({'with': o['id'], 'reason_pt': reason})
        return out

    # ---- public API ----
    def submit(self, text, *, received_at=None, synthetic=False, source_ref=None, deadline=None, actor='sistema'):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('Mensagem inválida.')
        with self.lock:
            recs = self._records()
            ref = source_ref or hashlib.sha1(text.encode()).hexdigest()[:12]
            vid = 'vol-' + hashlib.sha1(ref.encode()).hexdigest()[:8]
            if vid in recs:
                return self.view(vid)
            verdict = detect.classify(text)
            if verdict['kind'] != 'offer':
                return {'accepted': False, 'kind': verdict['kind'], 'reason_pt': verdict['reason']}
            info = ex.extract(text, self.client, deadline)
            events = info.pop('events')
            record = {'id': vid, 'status': PENDING, 'source': 'voluntario', 'synthetic': bool(synthetic), 'source_ref': ref,
                      'received_at': received_at or self.now(), 'text': redact(text),
                      'classification': {k: verdict[k] for k in ('kind', 'reason')},
                      'extraction': {k: info[k] for k in ('method', 'rejected', 'error')}, 'fields': info['fields'],
                      'contact': info['contact'], 'merged_into': None}
            if info['error']:  # visible, never silent
                record['extraction']['label_pt'] = 'Extração determinística (modelo indisponível).'
            if not record['fields'].get('asset_type') and verdict['vehicle']:
                v = verdict['vehicle']
                record['fields']['asset_type'] = {'quote': v[1], 'value': v[0], 'source': 'regex'}
            record['extraction']['model_calls'] = [{k: e.get(k) for k in ('role', 'status', 'model', 'receipt')} for e in events]
            self._append('submitted', vid, redact(actor), record=record)
            return self.view(vid)

    def view(self, vid, recs=None):
        recs = recs or self._records()
        rec = recs.get(vid)
        if rec is None:
            raise KeyError(vid)
        others = list(recs.values())
        out = dict(rec)
        out['warnings'] = self._warnings(rec, others)
        out['merge_proposals'] = self.proposals(rec, others)
        out['dispatchable'] = rec['status'] == VERIFIED and not rec.get('merged_into')
        out['label_pt'] = '[SIMULADO] ' if rec.get('synthetic') else ''
        return out

    def list(self):
        recs = self._records()
        views = [self.view(i, recs) for i in recs]
        return {'volunteers': views, 'counts': {s: sum(1 for v in views if v['status'] == s) for s in (PENDING, VERIFIED, REJECTED)}}

    def sync_cases(self, cases):
        """Cases routed to 'Voluntários' by the pipeline become pending assets (idempotent by case id)."""
        for c in cases or []:
            if (c.get('route') or {}).get('id') == 'volunteer_offer' and c.get('text'):
                self.submit(c['text'], received_at=c.get('received_at'), synthetic=bool(c.get('synthetic') or c.get('sample')),
                            source_ref='case:' + str(c.get('case_id')))

    def _pending(self, vid):
        rec = self._records().get(vid)
        if rec is None:
            raise KeyError(vid)
        if rec['status'] != PENDING:
            from app.engines.world_model.registry import Conflict
            raise Conflict('Oferta já decidida: ' + rec['status'])
        return rec

    def verify(self, vid, request):
        with self.lock:
            actor = _actor(request)
            rec = self._pending(vid)
            if rec.get('merged_into'):
                raise ValueError('Oferta fundida; desfaça a fusão antes de verificar.')
            method = request.get('method')
            if method not in METHODS:
                raise ValueError('Informe como foi verificado: ' + ', '.join(METHODS))
            note = request.get('note')
            if note is not None and (not isinstance(note, str) or len(note) > 300):
                raise ValueError('Observação inválida.')
            f = rec['fields']
            kind = request.get('type') or f.get('asset_type', {}).get('value')
            from app.fleet.assets import RULE_TYPES
            if kind not in RULE_TYPES:
                raise ValueError('Defina o tipo do veículo (barco_aluminio, bote_inflavel, jet_ski, ...).')
            base = request.get('base') or f.get('base_detail', {}).get('quote') or f.get('base_place', {}).get('quote')
            if not isinstance(base, str) or not base.strip():
                raise ValueError('Informe a base do veículo.')
            cap = request.get('capacity_people', f.get('capacity', {}).get('value'))
            if self.registry is None:
                raise ValueError('Inventário indisponível.')
            at = self.now()
            unit = {'id': 'vol-' + vid[4:], 'type': kind, 'crew': 'Voluntário (contato redigido)', 'base': base.strip()[:200],
                    'source': 'voluntario', 'origin': 'voluntario', 'volunteer_id': vid, 'observed_date': at[:10],
                    'last_report_at': at if at.endswith('Z') or '+' in at[10:] else at + 'Z',
                    'status': 'available', 'capacity': cap, 'synthetic': bool(rec.get('synthetic')),
                    'night_ok': (f.get('night_ok') or {}).get('value'), 'pets_ok': (f.get('pets_ok') or {}).get('value'),
                    'verification': {'method': method, 'actor': actor}}
            if cap is not None:
                unit['capacity_source'] = 'declarada pelo voluntário; conferida por ' + actor + ' (' + METHODS[method] + ')'
            from app.resources import register
            register(self.registry, {'actor': actor, 'expected_version': 0, 'unit': unit})
            self._append('verified', vid, actor, method=method, note=redact(note) if note else None, unit_id=unit['id'])
            return self.view(vid)

    def reject(self, vid, request):
        with self.lock:
            actor = _actor(request)
            self._pending(vid)
            reason = request.get('reason')
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                raise ValueError('Informe o motivo da rejeição.')
            self._append('rejected', vid, actor, reason=redact(reason.strip()))
            return self.view(vid)

    def merge(self, vid, request):
        with self.lock:
            actor = _actor(request)
            rec = self._pending(vid)
            into = request.get('into')
            recs = self._records()
            if into not in recs or into == vid or recs[into]['status'] == REJECTED or recs[into].get('merged_into'):
                raise ValueError('Destino da fusão inválido.')
            if not any(p['with'] == into for p in self.proposals(rec, list(recs.values()))):
                raise ValueError('Não há proposta de fusão com este destino.')
            self._append('merged', vid, actor, into=into)
            return self.view(vid)

    def unmerge(self, vid, request):
        with self.lock:
            actor = _actor(request)
            rec = self._records().get(vid)
            if rec is None:
                raise KeyError(vid)
            if not rec.get('merged_into'):
                raise ValueError('Oferta não está fundida.')
            self._append('unmerged', vid, actor)
            return self.view(vid)
