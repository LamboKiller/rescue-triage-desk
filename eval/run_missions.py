"""Offline mission arithmetic/safety and needs baseline; --live enables mission roles.

All scenarios/attestations/capacities are synthetic. Street reference points are
read from the real local dataset; no operational capacity is asserted by this eval.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.agents.needs import NeedsExtractor
from app.fleet import document, screen, rule_input, translations
from app.fleet.evaluator import evaluate as evaluate_fleet
from app.missions.planner import propose, check_plan, safety, tags
from app.missions.brief import explain

DAY='2024-05-08'


def prepare(item):
    with (ROOT/'data/hazards/street_points.csv').open(encoding='utf-8') as src:
        rows=list(csv.DictReader(src))
    cases=[]
    for row in item['cases']:
        p=next(r for r in rows if r['municipality']=='Canoas' and r['display_name']==row['street'])
        c={'case_id':row['id'],'message_id':item['id']+':'+row['id'],'version':1,'synthetic':True,
           'status':'proposed','location_confirmed':True,'text':row.get('text','Pessoas aguardando resgate.'),
           'received_at':DAY+'T10:00:00-03:00','replay_time':DAY+'T12:00:00-03:00',
           'position':{'lat':float(p['lat']),'lon':float(p['lon']),'position_kind':'street_reference',
                       'source':'data/hazards/street_points.csv#'+row['street']},
           'fields':{k:{'value':v} for k,v in {'people':row['people'],'street':row['street'],
                     'number':row.get('number'),'municipality':'Canoas'}.items()},
           'hazards':{'depth_band':row.get('band','d_0_6_to_1_2'),'depth_m':0.8,'depth_observed_date':DAY},
           'hazard_blocks':row.get('blocked',[]),'result':{'priority':10,'decision':'SEND_CANDIDATE'}}
        screen(c)
        cases.append(c)
    units=[{'id':item['id']+':unit:'+str(i),'asset':u['asset'],'capacity':u.get('capacity'),
            'capacity_basis':'rescue_passengers_after_crew_and_equipment','available':True,'observed_date':DAY,
            'source':'author-written synthetic eval inventory','synthetic':True,
            'attestations':{**{k:True for k in document()['verification_fields']},
                            'stretcher_capable':u.get('stretcher_capable',True)}} for i,u in enumerate(item['units'])]
    # Each test case arrives with a real rules evaluation for its supplied synthetic
    # resource configuration. Production never gets these blanket attestations.
    for c in cases:
        inputs=rule_input(c);inputs['assigned_assets']={u['asset']:u['attestations'] for u in units}
        raw=evaluate_fleet(document(),inputs)
        for r in c['fleet']:
            actual=raw['assets'][r['asset']]
            r.update(verdict=actual['status'],rule_ids=actual['matched_rules'],source_ids=actual['source_ids'],
                     reasons_pt=[translations()[rule] for rule in actual['matched_rules']])
    return cases,units


def evaluate(live=False,client=None):
    if live and client is None:
        from app.missions.client import MissionClient
        client=MissionClient(ROOT/'runtime/mission_eval_trace.jsonl')
    extractor=NeedsExtractor(client)
    scenarios=[json.loads(l) for l in (ROOT/'eval/mission_set.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    capacity_violations=blocked_assignments=order_tests=order_ok=correct=crashes=0;results=[]
    for item in scenarios:
        try:
            cases,units=prepare(item);plans=propose(cases,DAY,units,extractor=extractor,deadline=time.monotonic()+240)
            actual=sorted(sorted(s['case_id'] for s in p['stops']) for p in plans)
            expected=[sorted(sorted(g) for g in groups) for groups in [item['truth']['groups']]+item['truth'].get('alternative_groups',[])]
            group_ok=actual in expected;correct+=group_ok
            failures=[]
            for p in plans:
                p.update(explain(p,client,time.monotonic()+90))
                if p['capacity'] is not None and p['people'] is not None:
                    capacity_violations+=p['people']>p['capacity']*p['trips']
                    capacity_violations+=sum(t['people']>t['capacity'] for t in p['trip_loads'])
                blocked_assignments+=sum(p['asset'] in c.get('hazard_blocks',[]) or any(r['asset']==p['asset'] and r['verdict']=='unsafe' for r in c['fleet']) for c in cases if c['case_id'] in {s['case_id'] for s in p['stops']})
                ranks=[s['safety_rank'] for s in p['stops']];order_tests+=1;order_ok+=ranks==sorted(ranks)
                truth=item['truth'];ids=[s['case_id'] for s in p['stops']]
                if 'asset' in truth and p['asset']!=truth['asset']: failures.append('asset')
                if 'assets' in truth and any(p['asset']!=truth['assets'][i] for i in ids): failures.append('assets')
                for a,b in truth.get('before',[]):
                    if a in ids and b in ids and ids.index(a)>=ids.index(b): failures.append('stop_order')
                for key in ('people','trips','asset_count'):
                    if key in truth and p[key]!=truth[key]: failures.append(key)
                if truth.get('blocked') or any(i in truth.get('blocked_cases',[]) for i in ids):
                    if not p['blocking_reasons']: failures.append('missing_block')
                elif check_plan(p,cases,units): failures.append('unexpected_block')
            results.append({'id':item['id'],'grouping_correct':group_ok,'groups':actual,'failures':failures})
        except Exception as exc:
            crashes+=1;results.append({'id':item['id'],'error':type(exc).__name__})
    messages=[json.loads(l) for l in (ROOT/'eval/mission_set_needs.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    tp=fp=fn=exact=groups_ok=fallbacks=0
    for item in messages:
        out=extractor.extract({'case_id':item['id'],'text':item['text']},time.monotonic()+90)
        got={n['tag'] for n in out['needs']};truth=set(item['truth'])
        tp+=len(got&truth);fp+=len(got-truth);fn+=len(truth-got);exact+=got==truth
        groups_ok+=sorted(g['people'] for g in out['count_by_group'])==sorted(item.get('groups',[]))
        fallbacks+=out['needs_check']=='deterministic_only'
    return {'mode':'live' if live else 'offline','synthetic':True,'scenarios':len(scenarios),'crashes':crashes,
            'capacity_violations':capacity_violations,'blocked_asset_assignments':blocked_assignments,
            'life_safety_first':order_ok/order_tests if order_tests else None,'grouping_accuracy':correct/len(scenarios),
            'needs':{'messages':len(messages),'precision':tp/(tp+fp) if tp+fp else 1,'recall':tp/(tp+fn) if tp+fn else 1,
                     'exact_tag_accuracy':exact/len(messages),'group_counts_accuracy':groups_ok/len(messages),
                     'deterministic_fallbacks':fallbacks},'results':results,
            'limits':'Author-written synthetic inventory and truth; real street reference points, not surveyed house positions. Offline measures keyword fallback, not live model quality.'}


if __name__=='__main__':
    load_env();p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--offline',action='store_true');mode.add_argument('--live',action='store_true')
    p.add_argument('--output',type=Path);args=p.parse_args();result=evaluate(args.live)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.write_text(text+'\n',encoding='utf-8')
    print(text)
    raise SystemExit(bool(result['crashes'] or result['capacity_violations'] or result['blocked_asset_assignments'] or
                          result['life_safety_first']!=1 or any(r.get('failures') or not r.get('grouping_correct') for r in result['results'])))
