"""Single entry point called by Pipeline._run once every message has its decision (outside any message budget)."""
import copy
from app.config import ROOT
from app.contradictions import service as svc

_SHELTERS = {}


def shelters():
    """Shelter state from the desk's own report journal (read-only); None when unavailable (then no shelter detector)."""
    try:
        from app.shelters.state import Catalogue, Shelters, Store
        if 'catalogue' not in _SHELTERS:  # the pre-existing list is static; reports (Store) are re-read every run
            _SHELTERS['catalogue'] = Catalogue()
        return Shelters(catalogue=_SHELTERS['catalogue'], store=Store(ROOT / 'runtime/shelter_events.jsonl'))
    except Exception:
        return None


def after_decision(pipeline, results, previous=None, client=None):
    """Deterministic detectors on every finished case; model phrasing is scheduled on a background thread after ingest.
    Advisory: a failure leaves the case exactly as decided and marks `contradiction_check.error`."""
    if not any(case.get('complete') for case in results):
        return []  # No advisory work for deadline failures; do not cold-load a catalogue.
    existing = pipeline.registry.analysis_context(False)[0] if hasattr(pipeline.registry, 'analysis_context') else pipeline.registry.read()
    shelter = shelters()
    jobs = []
    for case in results:
        if not case.get('complete'):
            continue
        key = previous['case_id'] if previous is not None else svc.case_key(case['message_id'])
        try:
            peers = [c for c in existing if c.get('case_id') != key] + \
                    [{**c, 'case_id': svc.case_key(c['message_id'])} for c in results if c is not case and c.get('complete')]
            view = case
            if previous is not None:  # a reply keeps the crew reports and dialogue of the case it extends
                view = {**case, 'feedback': case.get('feedback') or previous.get('feedback'),
                        'messages': case.get('messages') or previous.get('messages')}
            items = svc.attach(view, key=key, peers=peers, shelters=shelter, now=case.get('replay_time') or case.get('received_at'))
            for field in ('cross_source', 'open_items', 'contradiction_check'):
                case[field] = copy.deepcopy(view[field])
            if items and isinstance(case.get('result'), dict):
                case['result']['questions'] = view['result']['questions']
            jobs.append((key, items, case.get('replay_time') or case.get('received_at')))
        except Exception as exc:
            case['contradiction_check'] = {'items': 0, 'error': type(exc).__name__, 'model_in_triage_path': False}
    svc.ContradictionService(pipeline.registry).schedule(jobs, client)
    return jobs
