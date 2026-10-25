"""Synthetic feedback dialogues: real extractor and durable World Model transitions."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.feedback import FeedbackService
from app.engines.world_model.registry import Registry
from tools.scratch import scratch

DIALOGUES=[
 ('partial',4,['pegamos 3, falta 1 idoso'],'PARTIAL',1),
 ('complete',4,['resgatamos 4'],'RESCUED',0),
 ('not-found',4,['nao achamos ninguem no endereco'],'NOT_FOUND',None),
 ('left',4,['ja sairam de carona'],'RESCUED',0),
 ('more',4,['precisa de mais um barco'],'proposed',None),
 ('sum-conflict',4,['pegamos 3, falta 3 idosos'],'proposed',None),
 ('too-many-remaining',4,['restam 5 pessoas'],'proposed',None),
 ('too-many-rescued',4,['retiramos 8'],'proposed',None),
 ('two-counts',4,['pegamos 1, pegamos 2'],'proposed',None),
 ('partial-then-done',4,['levamos 2, restam 2 pessoas','retiramos 2'],'RESCUED',0),
 ('partial-then-missing',4,['resgatamos 1','nao encontramos ninguem no local'],'NOT_FOUND',3),
 ('word-count',4,['pegamos tres, falta um idoso'],'PARTIAL',1),
 ('hazard',4,['correnteza forte'],'proposed',None),
 ('zero-remaining',4,['restam 0 pessoas'],'RESCUED',0),
 ('boats-and-partial',4,['retiramos 1; precisa de mais um barco'],'PARTIAL',3),
]


def seed(registry,mid,people=4):
    return registry.ingest({'message_id':mid,'text':'Quatro pessoas ilhadas, uma pessoa acamada.',
        'synthetic':True,'received_at':'2024-05-08T10:00:00-03:00','replay_time':'2024-05-08T12:00:00-03:00',
        'fields':{'people':{'value':people,'quote':'Quatro pessoas'},'disabled':{'value':1,'quote':'uma pessoa acamada'}},
        'result':{'decision':'SEND_CANDIDATE','priority':0,'questions':[]},'errors':[],'fleet':[],
        'operational_needs':{'needs':[{'tag':'stretcher_or_bedridden','quote':'acamada','message_index':0}]}})


def evaluate(live=False):
    from app.missions.client import MissionClient
    client=MissionClient(ROOT/'runtime/feedback_eval_trace.jsonl') if live else None
    results=[]
    with scratch() as folder:
        registry=Registry(Path(folder)/'events.jsonl');service=FeedbackService(registry,client)
        for name,people,replies,status,remaining in DIALOGUES:
            case=seed(registry,'feedback-'+name,people);checks=[]
            for i,text in enumerate(replies):
                case=service.submit(case['case_id'],{'actor':'synthetic-eval','text':text,'expected_version':case['version'],
                    'received_at':f'2024-05-08T{11+i:02}:00:00-03:00'})
                checks.append(case['agents']['field_feedback']['feedback_check'])
            conflict=name in ('sum-conflict','too-many-remaining','too-many-rescued','two-counts')
            ok=(case['status']==status and case['version']==len(replies)+1 and case.get('remaining_n')==remaining
                and (not conflict or case['result']['decision']=='REVIEW_REQUIRED')
                and Registry(registry.path).read(case['case_id'])['version']==case['version'])
            results.append({'id':name,'correct':ok,'status':case['status'],'version':case['version'],'remaining_n':case.get('remaining_n'),'checks':checks})
    return {'mode':'live' if live else 'offline','synthetic':True,'dialogues':len(results),'correct':sum(r['correct'] for r in results),
            'accuracy':sum(r['correct'] for r in results)/len(results),'results':results,
            'limits':'Author-written synthetic dialogues. Offline verifies keyword fallback and code transitions; live assesses the field_feedback role.'}


if __name__=='__main__':
    load_env();p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group()
    mode.add_argument('--offline',action='store_true');mode.add_argument('--live',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();result=evaluate(args.live);text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.write_text(text+'\n',encoding='utf-8')
    print(text);raise SystemExit(result['accuracy']!=1)
