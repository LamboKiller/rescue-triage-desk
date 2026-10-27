"""Author-written offline GPS timelines, independent expectations; no model/network."""
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from app.telemetry import Telemetry
from support import Scratch

BASE=1715200000


def run_case(case):
    tmp=Scratch()
    try:
        now=BASE+case.get('now',100)
        mission=dict(mission_id='mission-eval',unit_id='eval-boat',status='en_route',approved_at=BASE,
            case_ids=['eval-stop'],stops=[{'case_id':'eval-stop','point':{'lat':-30,'lon':-50.99}}],
            polyline=[[-51,-30],[-50.99,-30]])
        original=copy.deepcopy(mission)
        def create(): return Telemetry(Path(tmp.name)/'telemetry.jsonl',lambda:['eval-boat'] if case['bind'] else [],lambda:[mission] if case['bind'] else [],clock=lambda:now,sample=case.get('sample',False))
        service=create()
        if case['bind']: service.bind('handset','eval-boat','eval-operator')
        outcomes=[]; etas=[]
        for i,fix in enumerate(case['fixes']):
            if i and case.get('restart'): service=create()
            payload=dict(id='handset',lat=-30,lon=-51,accuracy=8,speed=4)
            payload.update({k:v for k,v in fix.items() if k!='t'}); payload['timestamp']=BASE+fix['t']
            try: outcomes.append(service.ingest(payload)['status'])
            except (ValueError,TypeError): outcomes.append('rejected')
            rows=service.view()['units']
            if rows and rows[0].get('eta_seconds') is not None: etas.append(rows[0]['eta_seconds'])
        view=service.view(); rows=view['units']; expected=case['expect']; failures=[]
        alerts=sorted({a['kind'] for r in rows for a in r['alerts']})
        if alerts!=sorted(expected['alerts']): failures.append('alerts')
        if len(rows)!=expected['units']: failures.append('unit_count')
        if any(bool(r.get('arrival_proposal')) for r in rows)!=expected['proposal']: failures.append('arrival_proposal')
        if 'outcomes' in expected and outcomes!=expected['outcomes']: failures.append('ingest_outcomes')
        if 'pending' in expected and len(view['pending'])!=expected['pending']: failures.append('pending')
        if 'last_t' in expected and rows[0]['fix']['timestamp']!=BASE+expected['last_t']: failures.append('last_fix')
        if 'sources' in expected and sorted(r['source'] for r in rows)!=expected['sources']: failures.append('sources')
        if expected.get('eta_decreases') and not (len(etas)>=2 and all(b<a for a,b in zip(etas,etas[1:]))): failures.append('eta')
        for r in rows:
            for a in r['alerts']:
                if a['mission_ids']!=[mission['mission_id']] or not a['evidence']: failures.append('uncited_alert')
        unsafe=int(mission!=original or any(e['kind']=='unit_status' for e in service.events()) or any(r['status']!='en_route' for r in rows))
        return dict(id=case['id'],passed=not failures and not unsafe,failures=failures,status_changes_without_confirmation=unsafe)
    finally: tmp.cleanup()


def main():
    cases=[json.loads(line) for line in Path(__file__).with_name('telemetry_set.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    rows=[run_case(c) for c in cases]
    result=dict(passed=sum(r['passed'] for r in rows),total=len(rows),status_changes_without_confirmation=sum(r['status_changes_without_confirmation'] for r in rows),cases=rows)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['passed']==len(rows) and not result['status_changes_without_confirmation'] else 1


if __name__=='__main__': sys.exit(main())
