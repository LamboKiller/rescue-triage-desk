"""Thread-safe last-20-run event journal. One active pipeline run at a time."""
import copy
import json
import threading
import time
import uuid
from collections import OrderedDict
from app.pipeline import validate_request


class EventClient:
    def __init__(self, client, emit):
        self.client, self.emit = client, emit

    def __getattr__(self, key):
        return getattr(self.client, key)

    def call(self, role, system, payload, deadline):
        self.emit(role+'_started', role=role)
        started = time.monotonic()
        try:
            output, meta = self.client.call(role, system, payload, deadline)
            self.emit(role+'_done', role=role, **{k:meta.get(k) for k in ('model','receipt','seconds')})
            return output, meta
        except Exception:
            self.emit(role+'_error', role=role, seconds=round(time.monotonic()-started,4))
            raise


class RunStore:
    def __init__(self, limit=20):
        self.limit = limit
        self.runs = OrderedDict()
        self.condition = threading.Condition()

    def start(self, pipeline, request):
        replay, messages = validate_request(request)
        if not pipeline.run_lock.acquire(blocking=False):
            raise ValueError('Já existe uma execução ativa nesta mesa.')
        run_id = uuid.uuid4().hex
        with self.condition:
            self.runs[run_id] = {'run_id':run_id,'status':'running','events':[],'result':None}
            while len(self.runs)>self.limit:
                self.runs.popitem(last=False)
        def emit(stage, **fields):
            with self.condition:
                run = self.runs.get(run_id)
                if run and run['status']=='running':
                    run['events'].append({'stage':stage,'run_id':run_id,'case_id':None,'role':None,
                                          'model':None,'receipt':None,'seconds':0,**fields})
                    self.condition.notify_all()
        def work():
            try:
                result = pipeline._run(replay,messages,'full',event_sink=emit,run_id=run_id)
                status = 'complete'
            except Exception:
                result, status = {'error':'Falha na execução.'}, 'failed'
                emit('error')
            finally:
                with self.condition:
                    run = self.runs[run_id]
                    run['result'],run['status'] = result,status
                    run['events'].append({'stage':'done','run_id':run_id,'case_id':None,'role':None,'model':None,'receipt':None,'seconds':result.get('seconds',0)})
                    pipeline.run_lock.release()
                    self.condition.notify_all()
        try:
            threading.Thread(target=work,daemon=True).start()
        except Exception:
            pipeline.run_lock.release()
            raise
        return {'run_id':run_id,'status':'running'}

    def read(self, run_id):
        with self.condition:
            run = self.runs.get(run_id)
            return copy.deepcopy({k:v for k,v in run.items() if k!='events'}) if run else None

    def events(self, run_id):
        index=0
        while True:
            with self.condition:
                run=self.runs.get(run_id)
                if run is None: return
                batch=copy.deepcopy(run['events'][index:])
                index+=len(batch)
                done=run['status']!='running'
                if not batch and not done:
                    self.condition.wait(timeout=10)
            for event in batch:
                yield 'event: '+event['stage']+'\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n'
            if done: return
            if not batch: yield ': keep-alive\n\n'
