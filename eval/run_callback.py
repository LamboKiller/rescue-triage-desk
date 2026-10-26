"""Callback agent eval: 12 synthetic cases with HIDDEN truth. Offline by default (regex baseline + scripted planner stand-in);
`--live` uses Nightshift for extraction and for the callback_planner (needs NIGHTSHIFT_* in the environment; human-run).

Loop per case: items (code) -> plan (agent + validator) -> SIMULATED reply from the hidden truth -> A3 merge -> items re-evaluated.
Metrics: resolved items %, questions per case (target <= 3), decision correct after reply, invented facts (must be 0).
"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry
from app.callback import planner, simulator
from app.callback.items import compute_items
from app.callback.service import CallbackService
from tools.scratch import scratch

SET = ROOT/'eval'/'callback_set.jsonl'


class ScriptedPlanner:
    """Offline stand-in for the model: phrases the template plan as JSON, optionally with a deliberate flaw the validator must catch."""
    def __init__(self):
        self.items, self.flaw = [], 'ok'

    def call(self, role, system, payload, deadline):
        chosen, _ = planner.select_items(self.items)
        qs, _ = planner.template_plan(self.items)
        out = [{'text': q['text_pt'], 'items': list(q['item_ids'])} for q in qs]
        if out and self.flaw == 'invent_number':
            out[0]['text'] += ' Vocês são 12 pessoas?'
        elif out and self.flaw == 'invent_place':
            out[0]['text'] += ' Fica na Rua Aurora?'
        elif out and self.flaw == 'unmapped':
            out[0]['items'].append('loc.zzz')
        elif out and self.flaw == 'omit_blocking':
            out[0]['items'] = out[0]['items'][:1]
        elif out and self.flaw == 'too_many':
            out = out+[{'text': out[0]['text']+' ('+str(n)+')', 'items': out[0]['items']} for n in (1, 2, 3)]
        return {'questions': out}, {'role': role, 'status': 'ok', 'scripted': True, 'chosen': len(chosen)}


def evaluate(live=False, path=SET):
    records = [json.loads(l) for l in Path(path).read_text(encoding='utf-8-sig').splitlines() if l.strip()]
    by_id = {r['message_id']: r for r in records}
    rows, flagged_rejects = [], 0
    totals = dict(resolvable=0, resolved=0, questions=0, decision_ok=0, decision_before_ok=0, items_before_ok=0, invented=0,
                  unmapped=0, model_ok=0, model_rejected=0, templates=0, simulated_labelled=0, replied=0, existing_questions=0)
    live_client = None
    if live:
        from app.llm.nightshift import Nightshift
        live_client = Nightshift(ROOT/'runtime'/'callback_trace.jsonl')
    for rec in records:
        with scratch() as folder:
            pipe = Pipeline(Registry(Path(folder)/'events.jsonl'), sample=not live, client=live_client)
            if live:
                client = live_client
            else:
                client = ScriptedPlanner()
            service = CallbackService(pipe.registry, pipe, client, records=by_id)
            row = {'case': rec['message_id'], 'expect': rec['expect']}
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    for i, prime in enumerate(rec.get('prime') or []):
                        pipe.run({'replay_time': prime['received_at'], 'messages': [dict(prime, message_id=rec['message_id']+'-prime%d' % i)]})
                    first = pipe.run({'replay_time': rec['message']['received_at'],
                                      'messages': [dict(rec['message'], message_id=rec['message_id'])]})['cases'][0]
                    if rec.get('stale_check_at'):
                        pipe.registry.detect_stale(rec['stale_check_at'])
                    case = pipe.registry.read(first['case_id'])
                    items = compute_items(case)
                    if not live:
                        client.items, client.flaw = items, rec.get('mock_planner', 'ok')
                    view = service.view(case['case_id'])
                    plan = view['plan']
                    questions = plan['questions']
                    row.update(decision_before=case['result']['decision'], items_before=[i['id'] for i in items],
                               analysis_before={k: case.get(k) for k in ('complete', 'errors', 'latency_budget')},
                               existing_questions=len(case['result'].get('questions') or []),
                               questions=[q['text_pt'] for q in questions], plan_source=plan['source'],
                               fallback_reason=plan['fallback_reason'], deferred=plan['deferred'])
                    totals['existing_questions'] += row['existing_questions']
                    totals['questions'] += len(questions)
                    totals['model_ok'] += plan['source'] == 'model'
                    totals['templates'] += plan['source'] == 'templates'
                    totals['model_rejected'] += bool(plan['fallback_reason']) and plan['agent']['status'] == 'fallback'
                    vocab = planner.vocabulary(items)
                    ids = {i['id'] for i in items if i['ask']}
                    totals['invented'] += sum(bool(planner.check_text(q['text_pt'], vocab)) for q in questions)
                    totals['unmapped'] += sum((not q['item_ids']) or any(i not in ids for i in q['item_ids']) for q in questions)
                    if rec['expect'].get('questions') == 0 and questions:
                        row['error'] = 'expected no questions'
                    if questions or rec['expect'].get('questions') != 0:
                        out = service.reply(case['case_id'], {'simulated': True})
                        totals['replied'] += 1
                        totals['simulated_labelled'] += out['simulated'] is True and out['reply_text'].startswith(simulator.PREFIX)
                        d = out['diff']
                        totals['resolvable'] += d['items']['resolvable_before']
                        totals['resolved'] += len(d['items']['resolved'])
                        row.update(reply=out['reply_text'], decision_after=d['decision']['after'], resolved=d['items']['resolved'],
                                   analysis_after=d['analysis'],
                                   remaining=d['items']['remaining'], new_items=d['items']['new'], fields_changed=[c['field'] for c in d['fields_changed']])
                        totals['decision_ok'] += d['decision']['after'] == rec['expect']['decision_after']
                    else:
                        row['decision_after'] = case['result']['decision']
                        totals['decision_ok'] += row['decision_after'] == rec['expect']['decision_after']
                    totals['decision_before_ok'] += row['decision_before'] == rec['expect']['decision_before']
                    totals['items_before_ok'] += sorted(row['items_before']) == sorted(rec['expect']['items_before'])
            except Exception as exc:
                row['error'] = type(exc).__name__+': '+str(exc)[:160]
            rows.append(row)
    n = len(records)
    summary = {'mode': 'live' if live else 'offline (regex baseline + scripted planner stand-in)', 'cases': n,
               'items_resolved_pct': round(100*totals['resolved']/totals['resolvable'], 1) if totals['resolvable'] else None,
               'items_resolvable': totals['resolvable'], 'items_resolved': totals['resolved'],
               'questions_per_case': round(totals['questions']/n, 2), 'existing_decide_questions_per_case': round(totals['existing_questions']/n, 2),
               'max_questions': max((len(r.get('questions', [])) for r in rows), default=0),
               'decision_correct_after': totals['decision_ok'], 'decision_correct_before': totals['decision_before_ok'],
               'items_before_as_expected': totals['items_before_ok'],
               'invented_facts_in_questions': totals['invented'], 'unmapped_questions': totals['unmapped'],
               'plans_from_model': totals['model_ok'], 'plans_rejected_to_templates': totals['model_rejected'],
               'plans_templates_only': totals['templates'] - totals['model_rejected'],
               'replies_simulated_and_labelled': f"{totals['simulated_labelled']}/{totals['replied']}",
               'errors': [r for r in rows if r.get('error')]}
    return {'summary': summary, 'cases': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='use Nightshift (human-run; needs NIGHTSHIFT_* env)')
    parser.add_argument('--out', type=Path, help='write full JSON here')
    args = parser.parse_args()
    if args.live:
        load_env()
    result = evaluate(args.live)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
    for r in result['cases']:
        print(r['case'], r.get('decision_before'), '->', r.get('decision_after'), '| items', r.get('items_before'), '-> resolved', r.get('resolved'),
              '| q', len(r.get('questions', [])), r.get('plan_source'), r.get('error', ''))
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    s = result['summary']
    raise SystemExit(bool(s['errors'] or s['invented_facts_in_questions'] or s['unmapped_questions']))
