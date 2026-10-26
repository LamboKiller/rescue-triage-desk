"""Declared data-source kinds (one table for UI, API and README) + the Evals view.

Nothing here computes a result: the Evals view only re-reads files that eval runs wrote and never fills a missing number.
"""
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STALE_HOURS = 24

KINDS = {
    'pre_event': {'label_pt': 'pré-evento', 'label_en': 'pre-event',
                  'meaning': 'Existed before the May 2024 flood (streets, landmarks, census areas).'},
    'live_equivalent': {'label_pt': 'tempo real', 'label_en': 'live-equivalent',
                        'meaning': 'Real-time kind of source with its own timestamp; usable for replay date D only if observed/published <= D.'},
    'retrospective': {'label_pt': 'retrospectivo', 'label_en': 'retrospective stand-in',
                      'meaning': 'Produced or published after the event; stays usable but low confidence, never proof of a dry or safe route.'},
    'simulated': {'label_pt': 'simulado', 'label_en': 'simulated',
                  'meaning': 'Synthetic input or [SIMULADO] reply; fictional by construction.'},
}

# id -> (map layer key or None, label_pt, kind, source, observed/published rule)
LAYERS = {
    'coverage': ('coverage', 'Cobertura estimada', 'retrospective', 'Open cases + sourced fleet reports + local routing/HAND; synthetic units flagged', 'Derived at replay date; retrospective depth and unproven routes remain estimates'),
    'streets': (None, 'Ruas', 'pre_event', 'OpenStreetMap (snapshot taken 2024-06-15)', 'Features pre-date the event; the extract is later'),
    'landmarks': (None, 'Pontos de referência', 'pre_event', 'OSM Overpass + hand-curated aliases', 'Features pre-date the event; the extract is later'),
    'shelters_osm': (None, 'Abrigos (OSM)', 'pre_event', 'OpenStreetMap', 'Facility existence only; occupancy comes from snapshots'),
    'ibge': (None, 'Setores / municípios', 'pre_event', 'IBGE Censo 2022', 'Census 2022'),
    'terrain': (None, 'Terreno', 'pre_event', 'Skadi / SRTM', 'Year 2000'),
    'flood': ('flood', 'Inundação observada', 'retrospective', 'Possantti et al. (UFRGS) / EMSN194', 'Observed 6 and 8 May; published later'),
    'depth': ('depth', 'Profundidade (HAND)', 'retrospective', 'Copernicus EMS EMSN194 + HAND', 'Observed 6/8 May; grids created 2024-06-12'),
    'pumps': ('pumps', 'Bombas', 'retrospective', 'UFRGS crisis layers', 'Daily status table'),
    'levees': ('levees', 'Diques', 'retrospective', 'UFRGS crisis layers', 'Static'),
    'shelters': ('shelters', 'Abrigos (ocupação)', 'retrospective', 'UFRGS shelter snapshots', 'Snapshots from 8 May'),
    'buildings': ('buildings', 'Prédios', 'retrospective', 'OSM + Microsoft + Google Open Buildings', 'Releases 2023-2026'),
    'photos': (None, 'Fotos de enchente', 'retrospective', 'Wikimedia Commons', 'Post-event illustration only'),
    'closures': ('closures', 'Bloqueios', 'live_equivalent', 'DNIT / DMAE / prefeitura bulletins', 'Per-record published_at; corridor is an unverified candidate'),
    'events': ('events', 'Infraestrutura', 'live_equivalent', 'DMAE / prefeitura bulletins', 'Per-record observed_at and published_at'),
    'messages': (None, 'Mensagens recebidas', 'live_equivalent', 'Citizen channel (as received)', 'received_at'),
    'crew_reports': (None, 'Relatos de equipe', 'live_equivalent', 'Crew report with timestamp', 'Row time t'),
    'operator_reports': (None, 'Relatos do operador', 'live_equivalent', 'Operator action with timestamp', 'Row time t'),
    'citizen_replies': (None, 'Respostas simuladas', 'simulated', '[SIMULADO] callback simulator', 'Scripted; refuses cases without truth record'),
    'synthetic_messages': (None, 'Mensagens sintéticas', 'simulated', 'Generator / hand-written / red team', 'Fictional; flagged synthetic'),
    'cases': ('cases', 'Pedidos', 'simulated', 'Synthetic messages analysed by this system', 'Derived; each case carries its message kind'),
    'ring': ('ring', 'Raio de 1 km', 'live_equivalent', 'Computed from the case position', 'Computed, not an observation'),
}

EVAL_COMMANDS = {
    'suite': 'python -m unittest discover -s tests',
    'redteam': 'python eval/run_redteam.py --n 42',
    'adversarial': 'python eval/run_adversarial.py --offline',
    'credibility': 'python eval/run_credibility.py --json',
    'hydro': 'python eval/run_hydro.py',
    'callback': 'python eval/run_callback.py',
    'dialogues': 'python eval/run_dialogues.py --offline',
    'realdev': 'python tools/gate.py  (check realdev; needs the planning folder)',
    'gate': 'python tools/gate.py --fast',
    'results': 'python eval/run_eval.py --offline',
    'results_live': 'python eval/run_eval.py   (live model calls)',
}
# check -> (value key, label). A missing key shows as missing, never as a number.
HEADLINE = {
    'redteam': ('rate', 'taxa de aprovação'), 'adversarial': ('decision_accuracy', 'acerto de decisão'),
    'credibility': ('acceptable', 'casos aceitáveis'), 'hydro': ('passed', 'casos aprovados'),
    'callback': ('items_resolved_pct', 'itens resolvidos %'), 'dialogues': ('final_decision_accuracy', 'acerto final'),
    'realdev': ('correct', 'corretos'),
}


def layer_kind(layer):
    """Kind for a map layer key or a LAYERS id; None when undeclared (UI then shows 'sem rótulo', never a guess)."""
    row = LAYERS.get(layer) or next((v for v in LAYERS.values() if v[0] == layer), None)
    return row[2] if row else None


def message_kind(case):
    """Synthetic or [SIMULADO] text is simulated; anything else is a live-equivalent message."""
    text = str((case or {}).get('text') or (case or {}).get('message') or '')
    return 'simulated' if (case or {}).get('synthetic') or (case or {}).get('simulated') or text.lstrip().startswith('[SIMULADO]') else 'live_equivalent'


def table():
    return {'kinds': KINDS, 'layers': [{'id': k, 'map_layer': v[0], 'label_pt': v[1], 'kind': v[2], 'source': v[3], 'rule': v[4]}
                                       for k, v in LAYERS.items()]}


def _day(value):
    return str(value)[:10] if value and re.match(r'\d{4}-\d{2}-\d{2}', str(value)) else None


def usable_at(layer, record_time, replay_time):
    """No-hindsight gate. Pre-event layers are always usable; every other kind needs a known time <= replay time
    (retrospective ones stay usable only when their observation date qualifies, and remain labelled)."""
    kind = layer_kind(layer)
    if kind == 'pre_event':
        return True
    if kind is None:
        return False
    observed, replay = _day(record_time), _day(replay_time)
    return bool(observed and replay and observed <= replay)


def readme_table():
    rows = ['| Layer | Kind | Source | Time rule |', '|---|---|---|---|']
    rows += [f"| {v[1]} (`{k}`) | {KINDS[v[2]]['label_en']} | {v[3]} | {v[4]} |" for k, v in LAYERS.items()]
    return '\n'.join(rows)


def _head():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=5, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _scalar(value, key):
    value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, (int, float, str, bool)) else None


def _age(date, now):
    try:
        then = dt.datetime.fromisoformat(date)
        if then.tzinfo is None:
            then = then.replace(tzinfo=dt.timezone.utc)
        return (now - then).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _stale(date, commit, head, now):
    reasons = []
    hours = _age(date, now)
    if hours is None:
        reasons.append('data desconhecida')
    elif hours > STALE_HOURS:
        reasons.append(f'rodada com {hours:.0f} h (> {STALE_HOURS} h)')
    if commit and head and commit != head:
        reasons.append('commit diferente do atual')
    elif commit is None and head:
        reasons.append('commit não registrado')
    return reasons


def evals_view(root=None, now=None, head=None):
    """Rows from eval/gate_last.json and eval/results*.json exactly as stored; missing values stay None."""
    root = Path(root or ROOT)
    now = now or dt.datetime.now(dt.timezone.utc)
    head = head if head is not None else _head()
    rows = []
    gate = None
    try:
        gate = json.loads((root / 'eval/gate_last.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        gate = None
    if isinstance(gate, dict):
        for name, check in (gate.get('checks') or {}).items():
            value = check.get('value') if isinstance(check, dict) else None
            key, label = HEADLINE.get(name, (None, 'contagem' if name == 'suite' else 'valor'))
            metric = value if name == 'suite' and isinstance(value, (int, float)) else _scalar(value, key) if key else None
            total = _scalar(value, 'total') or _scalar(value, 'cases') or _scalar(value, 'messages') or _scalar(value, 'dialogues')
            mode = _scalar(value, 'mode')
            stale = _stale(gate.get('date'), gate.get('commit'), head, now)
            rows.append({'id': name, 'source': 'eval/gate_last.json', 'metric': label, 'value': metric, 'of': total,
                         'mode': 'offline', 'mode_detail': mode,
                         'passed': check.get('pass') if isinstance(check, dict) else None, 'date': gate.get('date'),
                         'commit': gate.get('commit'), 'fast': gate.get('fast'), 'stale': bool(stale), 'stale_reasons': stale,
                         'command': EVAL_COMMANDS.get(name)})
    for stem, key in (('results', 'results'), ('results_live', 'results_live')):
        path = root / 'eval' / (stem + '.json')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            date = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat()
        except (OSError, ValueError):
            continue
        for set_name, arms in (data.get('sets') or {}).items():
            for arm, stats in (arms or {}).items():
                acc = _scalar(stats, 'decision_accuracy')
                stale = _stale(date, None, head, now)
                rows.append({'id': f'{stem}:{set_name}:{arm}', 'source': f'eval/{stem}.json', 'metric': 'acerto de decisão', 'value': acc,
                             'of': _scalar(stats, 'n'), 'mode': data.get('mode'), 'passed': None, 'date': date, 'commit': None,
                             'date_note': 'data = última modificação do arquivo', 'fast': None, 'stale': bool(stale), 'stale_reasons': stale,
                             'command': EVAL_COMMANDS[key]})
    return {'head': head, 'now': now.isoformat(), 'stale_hours': STALE_HOURS, 'gate_pass': gate.get('pass') if isinstance(gate, dict) else None,
            'rows': rows, 'note': 'Valores lidos de arquivos de rodadas; nada é recalculado aqui.'}
