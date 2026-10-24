"""Audit evidence as stored; never repair historical records or fabricate receipts."""
import argparse
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from tools.scratch import scratch
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry


def check_case(case):
    violations = []
    text = case.get('text', '')
    for section in ('fields', 'initial_fields'):
        for key, field in case.get(section, {}).items():
            if not isinstance(field, dict) or 'value' not in field:
                violations.append(section+':invalid_field'); continue
            quote = field.get('quote')
            derived = field.get('derived') is True and bool(field.get('source'))
            if not derived and not (isinstance(quote,str) and quote.strip() and quote in text):
                violations.append(section+':missing_evidence')
            if field.get('derived') and not field.get('source'):
                violations.append(section+':missing_derivation_source')
    for fact in case.get('hazard_facts', []) + (case.get('hazards') or {}).get('facts', []):
        if not isinstance(fact,dict) or not fact.get('id') or not fact.get('source'):
            violations.append('hazard:missing_id_or_source')
    for call in case.get('calls', []):
        if not isinstance(call,dict) or not call.get('role') or 'model' not in call or 'receipt' not in call:
            violations.append('call:missing_metadata'); continue
        # Failed attempts may have explicit nulls: no receipt was issued.
        if case.get('mode') != 'sample_offline' and call.get('status') != 'failed' and not (call['model'] and call['receipt']):
            violations.append('call:missing_model_or_receipt')
    if not case.get('result',{}).get('decision_reason'):
        violations.append('decision:missing_reason')
    route = case.get('route')
    if not isinstance(route,dict) or not all(route.get(k) for k in ('id','label_pt','reason_pt','steps')):
        violations.append('decision:missing_route')
    return violations


def saved_cases(paths):
    for path in paths:
        for number,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
            try:
                event=json.loads(line)
                if event.get('kind') in ('ingest','analysis'):
                    yield event['case']
                elif 'fields' in event and 'result' in event:
                    yield event
            except (ValueError,KeyError,TypeError) as exc:
                raise ValueError(str(path)+':'+str(number)+': invalid saved case') from exc


def summarize(cases):
    counts=Counter(); total=bad=0
    for case in cases:
        total += 1; violations=check_case(case); bad += bool(violations); counts.update(violations)
    return {'cases':total,'cases_with_violations':bad,'violations':sum(counts.values()),'by_kind':dict(sorted(counts.items()))}


def audit(include_saved=True):
    with scratch() as folder:
        pipeline=Pipeline(Registry(Path(folder)/'events.jsonl'),sample=True)
        sample=[]
        for path in sorted((ROOT/'examples').glob('input_*.json')):
            with contextlib.redirect_stdout(io.StringIO()):
                sample.extend(pipeline.run(json.loads(path.read_text(encoding='utf-8')))['cases'])
        result={'offline_sample':summarize(sample)}
    if include_saved:
        paths=sorted((ROOT/'runtime').glob('eval_*.jsonl'))
        result['saved_evaluations']=dict(summarize(saved_cases(paths)), files=len(paths))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sample-only',action='store_true');args=parser.parse_args()
    result=audit(not args.sample_only)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(any(group['violations'] for group in result.values()))
