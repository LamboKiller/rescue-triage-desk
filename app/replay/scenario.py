"""Scenario files: INPUTS only. A scenario row is a citizen message or an explicitly labelled operator/crew/simulator input.

Nothing a pipeline or agent must decide (decision, priority, route, outcome, mission, status ...) may appear in a row:
the whitelist below rejects every other key, so a decision cannot be smuggled in.
"""
import json
import re
from pathlib import Path
from app.config import ROOT

DEFAULT = ROOT/'eval'/'demo_scenario.jsonl'
OPS = ('confirm_location', 'request_callback', 'approve_mission', 'decide_alert')
KEYS = {
    'scenario': {'type', 'name', 'replay_day', 'start', 'end_min', 'tick_every_min', 'synthetic', 'note'},
    'message': {'type', 't', 'id', 'text', 'synthetic', 'channel'},
    'resource': {'type', 't', 'unit', 'scenario_input'},
    'operator': {'type', 't', 'op', 'ref', 'alert_kind', 'choice', 'acknowledge_caution', 'scenario_input', 'note'},
    'crew_report': {'type', 't', 'ref', 'text', 'scenario_input', 'note'},
    'citizen_reply': {'type', 't', 'ref', 'citizen_replies', 'unknown_reply', 'simulated', 'scenario_input', 'note'},
}
REQUIRED = {'message': {'t', 'id', 'text', 'synthetic'}, 'resource': {'t', 'unit'}, 'operator': {'t', 'op'},
            'crew_report': {'t', 'ref', 'text'}, 'citizen_reply': {'t', 'ref', 'citizen_replies', 'simulated'}}


class ScenarioError(ValueError):
    pass


def validate(rows):
    """Return {'meta': dict, 'items': [row ...]} or raise ScenarioError. Items keep file order."""
    if not rows or rows[0].get('type') != 'scenario':
        raise ScenarioError('A primeira linha deve ser o cabeçalho do cenário (type=scenario).')
    meta = rows[0]
    extra = set(meta) - KEYS['scenario']
    if extra:
        raise ScenarioError('Chaves não permitidas no cabeçalho: '+', '.join(sorted(extra)))
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(meta.get('replay_day'))) or not re.fullmatch(r'\d{2}:\d{2}', str(meta.get('start'))):
        raise ScenarioError('replay_day (AAAA-MM-DD) e start (HH:MM) são obrigatórios.')
    end, every = meta.get('end_min'), meta.get('tick_every_min', 30)
    if type(end) is not int or end <= 0 or type(every) is not int or every <= 0:
        raise ScenarioError('end_min e tick_every_min devem ser inteiros positivos.')
    items, message_ids = [], set()
    for number, row in enumerate(rows[1:], 2):
        kind = row.get('type')
        if kind not in REQUIRED:
            raise ScenarioError(f'Linha {number}: tipo desconhecido {kind!r}.')
        extra = set(row) - KEYS[kind]
        if extra:
            raise ScenarioError(f'Linha {number}: chaves não permitidas ({", ".join(sorted(extra))}); o cenário só traz entradas, nunca decisões.')
        missing = REQUIRED[kind] - set(row)
        if missing:
            raise ScenarioError(f'Linha {number}: faltam {", ".join(sorted(missing))}.')
        if type(row['t']) not in (int, float) or not 0 <= row['t'] <= end:
            raise ScenarioError(f'Linha {number}: t fora de 0..end_min.')
        if kind == 'message':
            if row['synthetic'] is not True or not isinstance(row['text'], str) or not row['text'].strip():
                raise ScenarioError(f'Linha {number}: mensagem deve ser sintética e ter texto.')
            if row['id'] in message_ids:
                raise ScenarioError(f'Linha {number}: id de mensagem repetido.')
            message_ids.add(row['id'])
        else:
            if row.get('scenario_input') is not True:
                raise ScenarioError(f'Linha {number}: entradas de operador/equipe/simulador exigem scenario_input=true.')
        if kind == 'operator':
            if row['op'] not in OPS:
                raise ScenarioError(f'Linha {number}: operação desconhecida {row["op"]!r}.')
            if row['op'] == 'decide_alert':
                if not row.get('alert_kind') or row.get('choice') not in ('accept', 'dismiss'):
                    raise ScenarioError(f'Linha {number}: decide_alert exige alert_kind e choice accept/dismiss.')
            elif not row.get('ref'):
                raise ScenarioError(f'Linha {number}: {row["op"]} exige ref (id de mensagem).')
        if kind == 'citizen_reply':
            if row['simulated'] is not True or not isinstance(row['citizen_replies'], dict) or not row['citizen_replies']:
                raise ScenarioError(f'Linha {number}: resposta de cidadão deve ser simulated=true com citizen_replies.')
        items.append(row)
    for number, row in enumerate(items, 1):
        ref = row.get('ref')
        if ref is not None and ref not in message_ids:
            raise ScenarioError(f'ref {ref!r} não é uma mensagem do cenário.')
    return {'meta': meta, 'items': items, 'message_ids': sorted(message_ids)}


def load(path=DEFAULT):
    path = Path(path)
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    return validate(rows)
