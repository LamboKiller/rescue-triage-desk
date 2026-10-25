"""Local, event-sourced aliases. Only human approval grants read authority."""
import hashlib
import json
import re
from datetime import datetime, timezone

from app.decide import timestamp
from app.derive_count import _plain
from app.geo.incident import incident_text, COVERED
from app.engines.world_model.registry import Conflict
from app.redact import redact


def now():
    return datetime.now(timezone.utc).isoformat()


def catalogue():
    from app.data.source import LocalSource
    return LocalSource().landmarks()


def place_id(row):
    return str(row['osm_type'])+':'+str(row['osm_id'])


class PlaceMemory:
    def __init__(self, registry, rows=None):
        self.registry = registry
        self.rows = catalogue() if rows is None else rows

    def _entries(self, at=None):
        cutoff = timestamp(at) if at else None
        entries = {}
        if self.registry.path.exists():
            for line in self.registry.path.read_text(encoding='utf-8').splitlines():
                event = json.loads(line)
                if event['kind'] != 'place_memory':
                    continue
                if cutoff and timestamp(event['at']) > cutoff:
                    continue
                if event['action'] == 'propose':
                    entries[event['entry']['id']] = {**event['entry'], 'status': 'pending', 'proposed_at': event['at']}
                elif event['id'] in entries:
                    entry = entries[event['id']]
                    status = {'approve': 'approved', 'reject': 'rejected', 'revoke': 'revoked'}[event['action']]
                    entry.update(status=status, **{status+'_at': event['at']}, actor=event['actor'])
                    if event['action'] == 'approve':
                        entry.update(approved_at=event['at'], approved_by=event['actor'])
        return list(entries.values())

    def entries(self, at=None):
        with self.registry.locked():
            return self._entries(at)

    def _propose(self, case, phrase, target):
        if not case.get('location_confirmed'):
            raise ValueError('Confirme a localização antes de propor memória.')
        if not isinstance(phrase, str) or not 4 <= len(phrase.strip()) <= 180:
            raise ValueError('Informe uma referência curta copiada da mensagem.')
        phrase = phrase.strip()
        if phrase not in case['text'] or _plain(phrase) not in incident_text(case['text']):
            raise ValueError('Referência deve ser uma citação exata do incidente.')
        row = next((r for r in self.rows if place_id(r) == target), None)
        if not row or _plain(row['municipality']) not in COVERED:
            raise ValueError('Local ausente do catálogo coberto.')
        # Exact names and curated aliases already have higher authority.
        names = [n for r in self.rows for n in [r['name'], *r.get('alt_names', '').split('|'),
                  *[a['alias'] for a in r.get('curated_aliases', [])]]]
        if _plain(phrase) in {_plain(n) for n in names if n}:
            return None
        key = '|'.join((_plain(phrase), target, _plain(row['municipality'])))
        eid = hashlib.sha256(key.encode()).hexdigest()[:24]
        if any(e['id'] == eid for e in self._entries()):
            return None
        entry = dict(id=eid, phrase=phrase, place_id=target, city=row['municipality'],
                     place_name=row['name'], evidence_case_id=case['case_id'], quote=phrase,
                     source='learned', evidence_version=case['version'])
        self.registry._append(dict(schema_version=1, kind='place_memory', action='propose', at=now(), entry=entry))
        return entry

    def propose(self, case, phrase, target):
        with self.registry.locked():
            current = self.registry._read()[0].get(case['case_id'])
            if not current or current['version'] != case['version']:
                raise Conflict('Caso alterado; revise a confirmação.')
            if not case.get('location_confirmed'):
                raise ValueError('Confirme a localização antes de propor memória.')
            return self._propose(current, phrase, target)

    def confirmed(self, case):
        """Called with the World Model lock held, immediately after confirmation."""
        target = (case.get('landmark_check') or {}).get('matched') or (
            case.get('agents', {}).get('location', {}).get('candidate'))
        if not target or not target.get('osm_type') or not target.get('osm_id'):
            return
        if not any(place_id(r) == place_id(target) for r in self.rows):
            return
        field = case.get('fields', {}).get('landmark', {})
        phrases = [field.get('quote', '')]
        # Conservative noun phrases after a location cue; never infer the target.
        pattern = r'\b(?:no|na|perto d[oa]|ao lado d[oa])\s+((?:(?:o|a)\s+)?(?:mercadinho|mercado|escola|colégio|prédio|galpão|venda|igreja|(?-i:[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}))\b[^,;.!?\n]{2,100})'
        phrases += [m[1].strip() for m in re.finditer(pattern, case['text'], re.I)]
        for phrase in dict.fromkeys(phrases):
            if phrase and 4 <= len(phrase) <= 180 and phrase in case['text'] and _plain(phrase) in incident_text(case['text']):
                self._propose(case, phrase, place_id(target))

    def decide(self, eid, action, actor, *, human=False):
        if not human:
            raise PermissionError('Ação exclusiva de operador humano.')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError('Identifique o operador.')
        if action not in ('approve', 'reject', 'revoke'):
            raise ValueError('Ação desconhecida.')
        with self.registry.locked():
            entry = next((e for e in self._entries() if e['id'] == eid), None)
            if entry is None:
                raise KeyError(eid)
            if entry['status'] != ('approved' if action == 'revoke' else 'pending'):
                raise Conflict('Memória alterada; recarregue e revise.')
            self.registry._append(dict(schema_version=1, kind='place_memory', id=eid,
                action=action, actor=redact(actor.strip()), at=now()))
            return next(e for e in self._entries() if e['id'] == eid)

    def aliases(self, replay):
        return [dict(alias=e['phrase'], municipality=e['city'], **e)
                for e in self.entries(replay) if e['status'] == 'approved']

    def enrich(self, rows, replay, cities):
        if len(cities) != 1:
            return rows
        city = _plain(next(iter(cities)))
        aliases = self.aliases(replay)
        return [{**r, 'learned_aliases': [a for a in aliases
                 if a['place_id'] == place_id(r) and _plain(a['city']) == city == _plain(r['municipality'])]}
                for r in rows]
