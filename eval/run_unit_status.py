"""Author-written synthetic unit timelines; entirely offline, no model or GPS calls."""
import argparse
import json
import sys
import uuid
import shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.engines.world_model.registry import Registry
from app.unit_status import UnitStatusService


def evaluate():
    results=[];unsourced=0
    for item in [json.loads(s) for s in (ROOT/'eval/unit_status_set.jsonl').read_text(encoding='utf-8').splitlines()]:
        folder=ROOT/'.tmp'/('unit-eval-'+uuid.uuid4().hex);folder.mkdir(parents=True)
        try:
            registry=Registry(folder/'events.jsonl')
            service=UnitStatusService(registry,lambda:[{'id':'boat-a'}])
            if item.get('mission'):
                c={'case_id':'synthetic-case','mission':{'units':[{'id':'boat-a'}],
                    'stops':[{'case_id':'synthetic-case'}],'eta_seconds':600}}
                with registry.locked(): registry._append(dict(kind='approve_mission',mission_id='mission-a',
                    at='2024-05-08T14:00:00-03:00',projections=[c]))
            errors=0;checks=[]
            for step in item['steps']:
                try:
                    service.report(step.get('uid','boat-a'),dict(actor='synthetic-crew',source=step.get('source','crew'),
                        text=step.get('text',''),received_at='2024-05-08T'+step['time']+':00-03:00',
                        **{k:step[k] for k in ('unit_id','mission_id','status') if k in step}))
                except (ValueError,KeyError): errors+=1
                if 'want' in step:
                    row=service.view('2024-05-08T'+step['time']+':00-03:00')['units'][0]
                    checks.append(row['status']==step['want'])
                    unsourced+=int(row['status']!='unknown' and not row['source_event'])
            now='2024-05-08T'+item['now']+':00-03:00'
            row=service.view(now)['units'][0];findings=service.findings(now)
            unsourced+=int(row['status']!='unknown' and not row['source_event'])
            ok=(all(checks) and row['status']==item['want'] and errors==item.get('errors',0)
                and [f['kind'] for f in findings]==item.get('alerts',[])
                and (not item.get('hint') or bool(row.get('reroute_hint_pt'))))
            results.append(dict(id=item['id'],correct=ok,status=row['status'],alerts=[f['kind'] for f in findings],rejections=errors))
        finally:
            target=folder.resolve()
            if ROOT.resolve() not in target.parents or '.tmp' not in target.parts: raise ValueError('Invalid scratch path')
            shutil.rmtree(target)
    return dict(mode='offline',synthetic=True,timelines=len(results),correct=sum(r['correct'] for r in results),
                unsourced_status_changes=unsourced,results=results,
                limits='Author-written timelines; offline validates code and the visible feedback fallback, not live model quality.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--offline',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();result=evaluate();text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.write_text(text+'\n',encoding='utf-8')
    print(text);raise SystemExit(result['correct']!=result['timelines'] or result['unsourced_status_changes']!=0)
