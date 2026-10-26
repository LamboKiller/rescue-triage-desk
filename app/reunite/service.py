"""Reunification registry: loads sources on demand, ranks candidates, records human decisions + notes in its own journal."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from app.reunite import matcher, records
from app.reunite.records import scrub


class Reunite:
    def __init__(self, registry=None, shelters=None, path=None):
        self.registry, self.shelters, self.path = registry, shelters, Path(path) if path else None
        self.lock = threading.Lock()
        self.events = []
        if self.path and self.path.is_file():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                try:
                    self.events.append(json.loads(line))
                except ValueError:
                    pass

    def _write(self, event):
        self.events.append(event)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8', newline='\n') as out:
                out.write(json.dumps(event, ensure_ascii=False) + '\n')

    def sources(self, cases=None, shelter_events=None, places=None):
        cases = cases if cases is not None else (self.registry.read() if self.registry else [])
        missing, found = [], []
        for case in cases:
            rec = records.missing_from_case(case)
            if rec:
                missing.append(rec)
            found.extend(records.found_from_feedback(case))
        if shelter_events is None and self.shelters:
            shelter_events = self.shelters.shelters.store.events
            places = places if places is not None else self.shelters.shelters.places(datetime.now().isoformat(timespec='seconds'))
        for ev in shelter_events or []:
            rec = records.found_from_shelter(ev, (places or {}).get(ev.get('shelter_id')))
            if rec:
                found.append(rec)
        return missing, found

    def _decided(self):
        out = {}
        for e in self.events:
            if e.get('kind') == 'decision':
                out[e['pair_id']] = e
        return out

    def view(self, asof=None, **sources):
        """Candidates still open + human decisions. Runs the matcher here only (never on the triage path)."""
        missing, found = self.sources(**sources)
        if asof:
            limit = records.ts(asof)
            missing = [r for r in missing if records.ts(r['at']) <= limit]
            found = [r for r in found if records.ts(r['at']) <= limit]
        ranked = matcher.match(missing, found, asof)
        decided = self._decided()
        return {'asof': asof, 'counts': {'missing': len(missing), 'found': len(found)},
                'candidates': [c for c in ranked if c['id'] not in decided],
                'decisions': [{k: e[k] for k in ('pair_id', 'action', 'actor', 'at', 'summary')} for e in decided.values()],
                'privacy_pt': 'Só o que as mensagens afirmam; telefones, e-mails e complementos de endereço são ocultados; nenhuma identidade é inferida.'}

    def decide(self, pair_id, action, actor, *, human=False, asof=None, **sources):
        if human is not True:
            raise PermissionError('Somente uma pessoa confirma ou rejeita.')
        if action not in ('confirm', 'reject'):
            raise ValueError('Ação inválida.')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError('Identifique quem decidiu.')
        with self.lock:
            if pair_id in self._decided():
                raise ValueError('Par já decidido.')
            cand = next((c for c in self.view(asof, **sources)['candidates'] if c['id'] == pair_id), None)
            if cand is None:
                raise KeyError(pair_id)
            at = datetime.now(timezone.utc).isoformat(timespec='seconds')
            m, f = cand['missing'], cand['found']
            summary = {'missing': {k: m[k] for k in ('id', 'case_id', 'names', 'ages', 'quote')}, 'found': {k: f[k] for k in ('id', 'case_id', 'source', 'names', 'ages', 'quote')},
                       'evidence': [e['label_pt'] + ': ' + e['detail'] for e in cand['evidence']]}
            event = {'kind': 'decision', 'pair_id': pair_id, 'action': action, 'actor': scrub(actor.strip(), 120), 'at': at, 'summary': summary}
            self._write(event)
            if action == 'confirm':
                for side, other in (('missing', 'found'), ('found', 'missing')):
                    cid = cand[side].get('case_id')
                    if cid:
                        self._write({'kind': 'note', 'case_id': cid, 'pair_id': pair_id, 'actor': event['actor'], 'at': at,
                                     'note_pt': f"Reencontro confirmado por {event['actor']}: relato do outro lado — “{cand[other]['quote']}”"})
            return event

    def notes(self, case_id):
        return [e for e in self.events if e.get('kind') == 'note' and e.get('case_id') == case_id]
