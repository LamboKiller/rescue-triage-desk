"""GET /api/flow?case_id=...&since=j:N,r:M  (read-only; called from the mission-enabled server handler)."""
from app.config import ROOT
from .build import build_flow


def handle(handler, registry, query):
    ids = query.get('case_id', [])
    since = query.get('since', [''])[0]
    if len(ids) > 1 or len(since) > 40 or any(len(v) > 1 for v in query.values()):
        handler.send_json(400, {'error': 'Parâmetros inválidos.'})
        return True
    try:
        payload = build_flow(registry.path, case_id=ids[0] if ids else None, since=since or None,
                             callback_log=ROOT/'runtime/callback_log.jsonl', redteam_dir=ROOT/'runtime/redteam',
                             redteam_eval_dir=ROOT/'eval/redteam')
    except Exception:
        handler.send_json(500, {'error': 'Falha ao montar o fluxo; conferir o diário local.'})
        return True
    handler.send_json(200, payload)
    return True
