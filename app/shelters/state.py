"""Shelter state: pre-existing OSM/UFRGS shelter list + event-time reports (capacity, deliveries, attributes).

Labels (never blur them): the CSV/geojson list is PRE-EXISTING (retrospective, publication time unknown); capacity during
the event only comes from timestamped reports (operator/crew) or, when no report exists, from the dated snapshot. Unknown stays unknown.
"""
import csv
import hashlib
import json
import math
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.config import ROOT

SNAPSHOT_CSV = ROOT / 'data' / 'hazards' / 'shelters.csv'
KINDS = ('vacancies', 'full', 'capacity', 'delivered', 'attr', 'access', 'alias', 'register')
ATTRS = ('health_support', 'animals_ok', 'accessible')
SOURCES = ('operator', 'crew', 'citizen')
LOCAL = timezone(timedelta(hours=-3))
LABEL_PRE = 'Lista pré-existente (OSM/UFRGS D1; retrospectiva, hora de publicação desconhecida)'
LABEL_REPORT = 'Relato durante o evento'


def naive(ts):
    """ISO timestamp -> naive local (UTC-3) datetime so snapshots and tz-aware replay clocks compare."""
    if not isinstance(ts, str) or len(ts) < 10: raise ValueError('Informe data/hora ISO.')
    d = datetime.fromisoformat(ts.strip().replace('Z', '+00:00'))
    if d.tzinfo: d = d.astimezone(LOCAL).replace(tzinfo=None)
    return d


def clock(now_or_day):
    """A replay clock: a date means the END of that day (everything observed that day is eligible, nothing later)."""
    return naive(now_or_day + 'T23:59:59') if isinstance(now_or_day, str) and len(now_or_day) == 10 else naive(now_or_day)


def metres(a_lat, a_lon, b_lat, b_lon):
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2
    return 12742000 * math.asin(min(1, math.sqrt(h)))


def fold(text):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text).lower()) if not unicodedata.combining(c)).strip()


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return int(n) if math.isfinite(n) and n >= 0 and n == int(n) else None


class Catalogue:
    """Physical shelters keyed by coordinate (the list has no names); every row is one dated snapshot of that place."""
    def __init__(self, path=None):
        self.places = {}
        with Path(path or SNAPSHOT_CSV).open(encoding='utf-8-sig', newline='') as src:
            for row in csv.DictReader(src):
                try:
                    lat, lon, at = float(row['lat']), float(row['lon']), naive(row['snapshot_local'])
                except (KeyError, ValueError):
                    continue
                key = 'S%s,%s' % (row['lat'].strip(), row['lon'].strip())
                place = self.places.setdefault(key, {'id': key, 'lat': lat, 'lon': lon, 'municipality': '', 'snapshots': []})
                place['municipality'] = place['municipality'] or (row.get('municipality') or '').strip()
                place['snapshots'].append({'at': at, 'vacancies': _num(row.get('vacancies')), 'capacity': _num(row.get('capacity')),
                                           'sheltered': _num(row.get('sheltered_people')), 'source': row.get('source', '')})
        for place in self.places.values(): place['snapshots'].sort(key=lambda s: s['at'])


    @classmethod
    def from_places(cls, rows):
        """In-memory catalogue (tests/eval): rows = [{id, lat, lon, municipality, snapshots:[{at, vacancies, capacity, sheltered}]}]."""
        self = cls.__new__(cls)
        self.places = {r['id']: {'id': r['id'], 'lat': r['lat'], 'lon': r['lon'], 'municipality': r.get('municipality', ''),
                                  'snapshots': sorted(({'at': naive(x['at']), 'vacancies': x.get('vacancies'), 'capacity': x.get('capacity'),
                                                        'sheltered': x.get('sheltered'), 'source': 'synthetic'} for x in r.get('snapshots', [])), key=lambda x: x['at'])}
                       for r in rows}
        return self


class Store:
    """Append-only JSONL of shelter reports. Each event: id, seq, kind, shelter_id, at, source, actor, value, quote."""
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.events = []
        if self.path and self.path.is_file():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    try: self.events.append(json.loads(line))
                    except ValueError: continue

    def add(self, event):
        with self.lock:
            event = {**event, 'seq': len(self.events)}
            event['id'] = hashlib.sha256(json.dumps({k: v for k, v in event.items() if k != 'id'}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            self.events.append(event)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open('a', encoding='utf-8') as out: out.write(json.dumps(event, ensure_ascii=False) + '\n')
            return event


def validate_event(raw, known):
    """Strict gate: only reports that name an existing (or being registered) shelter, a valid kind, value and time."""
    if not isinstance(raw, dict): raise ValueError('Relato inválido.')
    kind = raw.get('kind')
    if kind not in KINDS: raise ValueError('Tipo de relato inválido.')
    source = raw.get('source', 'operator')
    if source not in SOURCES: raise ValueError('Fonte deve ser operator, crew ou citizen.')
    actor = raw.get('actor')
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 120: raise ValueError('Identifique quem relatou.')
    at = raw.get('at')
    naive(at)
    event = {'kind': kind, 'at': at, 'source': source, 'actor': actor.strip()}
    for k in ('quote', 'case_id', 'mission_id'):
        if isinstance(raw.get(k), str) and raw[k].strip(): event[k] = raw[k].strip()[:500]
    if kind == 'register':
        name, lat, lon = raw.get('name'), raw.get('lat'), raw.get('lon')
        if not isinstance(name, str) or not name.strip() or len(name) > 120: raise ValueError('Informe o nome do abrigo.')
        if type(lat) not in (int, float) or type(lon) not in (int, float) or not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError('Coordenadas inválidas.')
        event.update(name=name.strip(), lat=float(lat), lon=float(lon), municipality=str(raw.get('municipality') or '')[:80],
                     shelter_id='X' + hashlib.sha256(fold(name).encode()).hexdigest()[:10])
        return event
    sid = raw.get('shelter_id')
    if sid not in known: raise ValueError('Abrigo desconhecido; escolha da lista ou cadastre.')
    event['shelter_id'] = sid
    if kind == 'full': event['value'] = 0
    elif kind in ('vacancies', 'capacity', 'delivered'):
        n = raw.get('value')
        if type(n) is not int or not 0 <= n <= 100000 or (kind == 'delivered' and n < 1): raise ValueError('Valor deve ser inteiro válido.')
        event['value'] = n
    elif kind == 'attr':
        if raw.get('attr') not in ATTRS or type(raw.get('value')) is not bool: raise ValueError('Atributo inválido.')
        event.update(attr=raw['attr'], value=raw['value'])
    elif kind == 'access':
        if raw.get('value') not in ('dry', 'flooded'): raise ValueError('Acesso deve ser dry ou flooded.')
        event['value'] = raw['value']
    elif kind == 'alias':
        name = raw.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 120: raise ValueError('Informe o nome.')
        event['name'] = name.strip()
    return event


class Shelters:
    def __init__(self, catalogue=None, store=None):
        self.catalogue = catalogue or Catalogue()
        self.store = store or Store()

    def known(self):
        ids = set(self.catalogue.places)
        ids.update(e['shelter_id'] for e in self.store.events if e['kind'] == 'register')
        return ids

    def record(self, raw):
        event = validate_event(raw, self.known())
        if event['kind'] == 'register' and event['shelter_id'] in self.known(): raise ValueError('Abrigo já cadastrado.')
        return self.store.add(event)

    def aliases(self, now=None):
        """folded alias/name/id -> shelter_id (later aliases win; ambiguous names are not guessed)."""
        out = {}
        limit = clock(now) if now else datetime.max
        for e in self.store.events:
            if naive(e['at']) > limit: continue
            if e['kind'] == 'register': out[fold(e['name'])] = e['shelter_id']
            elif e['kind'] == 'alias': out[fold(e['name'])] = e['shelter_id']
        for sid in self.catalogue.places: out[fold(sid)] = sid
        return out

    def places(self, now):
        limit = clock(now);out = {}
        for sid, p in self.catalogue.places.items():
            snaps = [s for s in p['snapshots'] if s['at'] <= limit]
            if snaps: out[sid] = {'id': sid, 'lat': p['lat'], 'lon': p['lon'], 'municipality': p['municipality'], 'snapshot': snaps[-1], 'origin': 'pre_existing_list'}
        for e in self.store.events:
            if e['kind'] == 'register' and naive(e['at']) <= limit:
                out[e['shelter_id']] = {'id': e['shelter_id'], 'lat': e['lat'], 'lon': e['lon'], 'municipality': e.get('municipality', ''), 'snapshot': None,
                                        'origin': 'operator_registered', 'name': e['name']}
        return out

    def state(self, now):
        """List of shelter states at replay clock `now` (date or timestamp). Events after the clock are invisible."""
        limit = clock(now)
        events = [e for e in self.store.events if naive(e['at']) <= limit]
        out = []
        for sid, p in self.places(now).items():
            mine = [e for e in events if e.get('shelter_id') == sid and e['kind'] != 'register']
            mine.sort(key=lambda e: (naive(e['at']), e['seq']))
            name = next((e['name'] for e in reversed(mine) if e['kind'] == 'alias'), p.get('name'))
            snap = p['snapshot']
            # Latest reading of remaining places: report beats an older snapshot; a newer snapshot beats an older report.
            reading = None
            if snap:
                vac = snap['vacancies']
                if vac is None and snap['capacity'] is not None and snap['sheltered'] is not None: vac = max(0, snap['capacity'] - snap['sheltered'])
                if vac is not None: reading = {'at': snap['at'], 'seq': -1, 'remaining': vac, 'source': 'snapshot', 'label': LABEL_PRE}
            for e in mine:
                if e['kind'] in ('vacancies', 'full'):
                    reading = {'at': naive(e['at']), 'seq': e['seq'], 'remaining': e['value'], 'source': e['source'], 'label': LABEL_REPORT,
                               'actor': e['actor'], 'quote': e.get('quote')}
            delivered_all = sum(e['value'] for e in mine if e['kind'] == 'delivered')
            capacity = next((e['value'] for e in reversed(mine) if e['kind'] == 'capacity'), snap['capacity'] if snap else None)
            remaining = None;basis = 'unknown';note = 'Capacidade desconhecida; confirmar com o abrigo.'
            if reading:
                after = sum(e['value'] for e in mine if e['kind'] == 'delivered' and (naive(e['at']), e['seq']) > (reading['at'], reading['seq']))
                remaining = max(0, reading['remaining'] - after)
                basis = reading['source'] + '_minus_deliveries' if after else reading['source']
                note = '%s %s vagas em %s%s' % ('Relatado:' if reading['source'] != 'snapshot' else 'Retrato pré-existente:', reading['remaining'],
                                                 reading['at'].isoformat(timespec='minutes'), (' − %s entregues depois' % after) if after else '')
                if reading['remaining'] - after < 0: note += ' (excedido em %s; confirmar)' % (after - reading['remaining'])
            maxrem = max(0, capacity - delivered_all) if remaining is None and capacity is not None else None
            if maxrem is not None: note = 'Capacidade total %s informada, ocupação prévia desconhecida (no máximo %s vagas); confirmar.' % (capacity, maxrem)
            attrs = {}
            for a in ATTRS:
                ev = next((e for e in reversed(mine) if e['kind'] == 'attr' and e['attr'] == a), None)
                attrs[a] = {'value': ev['value'], 'source': ev['source'], 'at': ev['at']} if ev else {'value': None, 'source': None, 'at': None}
            access = next((e for e in reversed(mine) if e['kind'] == 'access'), None)
            stamps = [naive(e['at']) for e in mine] + ([snap['at']] if snap else [])
            last = max(stamps, default=None)
            out.append({'shelter_id': sid, 'label': name or 'Abrigo %s, %.3f/%.3f' % (p['municipality'] or 'município n/i', p['lat'], p['lon']),
                        'name': name, 'lat': p['lat'], 'lon': p['lon'], 'municipality': p['municipality'], 'origin': p['origin'],
                        'origin_label': LABEL_PRE if p['origin'] == 'pre_existing_list' else 'Cadastrado por operador',
                        'capacity_total': capacity, 'remaining': remaining, 'remaining_max': maxrem, 'capacity_known': remaining is not None,
                        'capacity_basis': basis, 'capacity_note_pt': note,
                        'full': remaining == 0 and remaining is not None, 'delivered_total': delivered_all,
                        'attributes': attrs, 'reported_access': {'value': access['value'], 'source': access['source'], 'at': access['at']} if access else None,
                        'last_report_at': last.isoformat(timespec='minutes') if last else None,
                        'last_report_age_h': round((limit - last).total_seconds() / 3600, 1) if last else None,
                        'last_event_report_at': next((e['at'] for e in reversed(mine) if e['kind'] != 'alias'), None)})
        return out
