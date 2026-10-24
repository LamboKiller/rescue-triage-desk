"""Hazard critic evaluation. Offline proves wiring only; live is run separately by the operator."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.geo.hazards import assess
from app.fleet import screen
from app.agents import hazard_critic
from app.llm.nightshift import Nightshift


def prepare(item):
    case=dict(item)
    case['hazards']=assess(item['lat'],item['lon'],item['date'],'landmark')
    case['landmark_check']={'matched':{'category':'synthetic:real_place'}}
    case['result']={'decision':'SEND_CANDIDATE'}
    return screen(case)


class FakeClient:
    def call(self,role,system,payload,deadline):
        data=json.loads(payload); proposed=data['proposed_asset']
        fact=next(f for f in data['facts'] if f['id']=='fleet:'+proposed)
        unsafe=proposed in data['fleet_summary']['unsafe_assets']
        return {'objections':[{'fact_ids':[fact['id']], 'text_pt':'Recurso inseguro conforme as regras citadas.',
                              'severity':'block'}] if unsafe else [],
                'brief_pt':'Requer revisão humana e verificações locais.'}, {'role':role,'offline':True}


class RecordingClient:
    def __init__(self,client): self.client=client; self.raw=None; self.facts=[]
    def call(self,role,system,payload,deadline):
        data=json.loads(payload); self.facts=data['facts']
        self.raw,meta=self.client.call(role,system,payload,deadline)
        return self.raw,meta


def evaluate(items, truth, offline=False, client=None):
    started=time.monotonic(); rows=[]; tp=fp=positives=negatives=0
    citation_total=citation_valid=unsupported=units=unavailable=0
    provider=client or (FakeClient() if offline else Nightshift(ROOT/'runtime/hazard_eval_trace.jsonl'))
    for item in items:
        case=prepare(item); recorder=RecordingClient(provider); before=time.monotonic()
        hazard_critic.attach(case,recorder,time.monotonic()+120)
        review=case['hazard_review']; expected=truth[item['message_id']]['should_block']
        predicted=isinstance(review,dict) and any(o['severity']=='block' for o in review['objections'])
        positives+=expected; negatives+=not expected; tp+=expected and predicted; fp+=(not expected) and predicted
        unavailable+=review=='indisponível'; unsupported+=case['hazard_unsupported']
        raw=recorder.raw if isinstance(recorder.raw,dict) else {}
        obs=raw.get('objections',[]); obs=obs if isinstance(obs,list) else []
        units+=len(obs)+bool(raw.get('brief_pt'))
        ids={f['id'] for f in recorder.facts}
        for obj in obs:
            citation_total+=1
            cited=obj.get('fact_ids') if isinstance(obj,dict) else None
            citation_valid+=bool(isinstance(cited,list) and cited and all(isinstance(i,str) and i in ids for i in cited))
        rows.append({'message_id':item['message_id'],'expected_block':expected,'blocked':predicted,
                     'unavailable':review=='indisponível','unsupported':case['hazard_unsupported'],
                     'seconds':round(time.monotonic()-before,4)})
    return {'mode':'offline_wiring_only' if offline else 'live','cases':len(rows),
            'block_recall':tp/positives if positives else None,'false_block_rate':fp/negatives if negatives else None,
            'citation_validity':citation_valid/citation_total if citation_total else None,
            'unsupported_rate':unsupported/units if units else 0,'unsupported':unsupported,'unavailable':unavailable,
            'seconds':round(time.monotonic()-started,4),'results':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if not args.offline: load_env()
    items=[json.loads(line) for line in (ROOT/'eval/hazard_set.jsonl').read_text(encoding='utf-8').splitlines()]
    truth=json.loads((ROOT/'eval/hazard_truth.json').read_text(encoding='utf-8'))['cases']
    result=evaluate(items,truth,args.offline)
    (ROOT/'eval/hazard_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))

if __name__=='__main__': main()
