"""Offline author-written allocation scenarios. No provider, network or .env reads."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.fleet import document
from app.fleet.evaluator import evaluate as evaluate_rules
from app.fleet.allocation import allocate, inputs_for


def evaluate():
    items=[json.loads(line) for line in (ROOT/'eval/allocation_set.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    correct=unsafe=eligible_top1=abstentions=0;results=[]
    for item in items:
        c=item['case'];truth=item['truth'];day='2024-05-08'
        try:
            out=allocate(c,item['units'],day);top=out['top3'];failures=[]
            eligible_top1+=bool(top and top[0]['eligible'])
            abstentions+=not top
            if (top[0]['id'] if top else None)!=truth['top1']: failures.append('top1')
            if truth.get('open_checklist') and (not top or not top[0].get('confirmation_checklist')): failures.append('open_checklist')
            if 'trips' in truth and (not top or top[0]['trips']!=truth['trips']): failures.append('trips')
            if 'request' in truth and bool(out['requests'])!=truth['request']: failures.append('request')
            for row in top:
                u=next(u for u in item['units'] if u['id']==row['id'])
                inputs=inputs_for(c,day);inputs['assigned_assets']={u['asset']:{**u['attestations'],
                    'available':u['status']=='available','stretcher_capable':u['stretcher'],'night_capable':u['night_ok']}}
                verdict=evaluate_rules(document(),inputs)['assets'][u['asset']]['status']
                bad=verdict=='unsafe' or row['type']=='helicoptero' or row['type'] in truth.get('forbidden_types',[]) or bool(row['blocking_reasons'])
                unsafe+=int(bad)
                if bad: failures.append('unsafe_proposal')
                people=c.get('fields',{}).get('people',{}).get('value')
                if people and row['capacity_people'] and row['trips'] and people>row['capacity_people']*row['trips']: failures.append('capacity')
                if not set(row['fact_ids'])<={f['id'] for f in out['facts']}: failures.append('citation')
            correct+=not failures;results.append({'id':item['id'],'pass':not failures,'failures':failures,'top1':top[0]['id'] if top else None})
        except Exception as exc: results.append({'id':item['id'],'pass':False,'error':type(exc).__name__})
    return {'mode':'offline','synthetic':True,'scenarios':len(items),'correct':correct,
        'top1_eligible':eligible_top1,'safe_abstentions':abstentions,
        'unsafe_proposals':unsafe,'results':results,
        'limits':'Author-written synthetic cases and capability manifests; no operational validation or live model quality claim.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=evaluate();text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.write_text(text+'\n',encoding='utf-8')
    print(text);raise SystemExit(result['correct']!=result['scenarios'] or result['unsafe_proposals']!=0)
