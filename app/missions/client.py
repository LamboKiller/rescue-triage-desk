"""Nightshift transport for mission roles: shared slots/parser, one short retry."""
import json
import socket
import time
import urllib.error
import urllib.request
from app.config import setting
from app.llm.nightshift import Nightshift, first_json, read_stream, TRACE_LOCK
from app.redact import redact_json


class MissionClient(Nightshift):
    def _call(self,role,system,payload,deadline):
        key=setting('NIGHTSHIFT_API_KEY')
        if not key: raise RuntimeError('Nightshift key missing')
        body={'model':setting('NIGHTSHIFT_MODEL','nvidia/nemotron-3.5-lightning-30b-a3b'),
              'max_tokens':max(6000,int(setting('NIGHTSHIFT_MAX_TOKENS','6000'))),'stream':True,
              'messages':[{'role':'system','content':system},{'role':'user','content':redact_json(payload)}]}
        for attempt in range(2):
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('Global mission deadline')
            started=time.monotonic()
            event={'role':role,'attempt':attempt+1,'requested_model':body['model'],
                   'model':None,'receipt':None,'route_kind':None,'status':'failed'}
            try:
                req=urllib.request.Request(setting('NIGHTSHIFT_BASE_URL','http://127.0.0.1:8088/v1').rstrip('/')+'/chat/completions',
                    data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key,
                    'meterless-app':'rescue-triage-desk','meterless-scope':'user'})
                with urllib.request.urlopen(req,timeout=min(float(setting('NIGHTSHIFT_CALL_TIMEOUT','75')),remaining)) as response:
                    raw,meta=read_stream(response,deadline)
                output=first_json(raw)
                if time.monotonic()>=deadline: raise TimeoutError('Global mission deadline')
                event.update(status='ok',model=meta.get('routed_model'),receipt=meta.get('receipt_id'),
                             route_kind=(meta.get('winning_route') or {}).get('kind'))
                return output,event
            except (ValueError,urllib.error.URLError,TimeoutError,socket.timeout) as exc:
                event['error']=type(exc).__name__
                if attempt or isinstance(exc,urllib.error.HTTPError) and exc.code!=502:
                    raise RuntimeError('Mission provider unavailable') from None
                body['messages'][0]['content']=system+' Copie somente trechos exatos; responda JSON válido.'
            finally:
                event['seconds']=round(time.monotonic()-started,3)
                self.local.events=getattr(self.local,'events',[])+[event]
                with TRACE_LOCK:
                    self.trace_path.parent.mkdir(parents=True,exist_ok=True)
                    with self.trace_path.open('a',encoding='utf-8') as out:
                        out.write(json.dumps(event,ensure_ascii=False)+'\n')
