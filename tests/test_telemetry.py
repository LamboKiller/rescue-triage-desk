"""Offline GPS timelines; telemetry can propose arrival but cannot report status."""
import json
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app.telemetry import Telemetry
from app.telemetry_routes import handle, ApprovedRoutes
from support import Scratch


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1715200000
        self.mission = dict(mission_id='mission-a', unit_id='boat-a', status='en_route',
            approved_at=self.now-100, case_ids=['case-a'], stops=[{'case_id':'case-a','point':{'lat':-30,'lon':-50.99}}],
            polyline=[[-51,-30],[-50.99,-30]], water=True)
        self.s = Telemetry(Path(self.tmp.name)/'gps.jsonl', lambda:['boat-a'], lambda:[self.mission], clock=lambda:self.now)

    def bind(self):
        return self.s.bind('device-a', 'boat-a', 'dispatcher')

    def fix(self, delta=0, **kw):
        return self.s.ingest(dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-90+delta,speed=4,accuracy=8,**kw))

    def test_unknown_pending_and_explicit_binding(self):
        self.assertEqual(self.fix()['status'],'pending')
        self.assertFalse(self.s.view()['units'])
        self.bind(); self.fix(1)
        self.assertEqual(self.s.view()['units'][0]['unit_id'],'boat-a')

    def test_invalid_future_order_and_confidence(self):
        self.bind(); self.fix()
        self.assertEqual(self.fix()['status'],'ignored')
        for key,val in [('lat',91),('lon',float('nan')),('timestamp',self.now+1)]:
            data=dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-1); data[key]=val
            with self.assertRaises(ValueError): self.s.ingest(data)
        low=self.s.ingest(dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-1,accuracy=201))
        self.assertEqual(low['status'],'low_confidence')
        self.assertEqual(self.s.view()['units'][0]['fix']['timestamp'],self.now-90)

    def test_arrival_is_only_a_proposal_and_eta_converges(self):
        self.bind(); self.fix()
        first=self.s.view()['units'][0]['eta_seconds']
        for i in range(2):
            self.s.ingest(dict(id='device-a',lat=-30,lon=-50.9901,timestamp=self.now-50+i,speed=4))
        row=self.s.view()['units'][0]
        self.assertLess(row['eta_seconds'],first)
        self.assertEqual(row['arrival_proposal']['status'],'confirmation_required')
        self.assertEqual(row['status'],'en_route')
        self.assertFalse(any(e.get('kind')=='unit_status' for e in self.s.events()))

    def test_alerts_and_noise(self):
        self.bind()
        for i in range(3):
            self.s.ingest(dict(id='device-a',lat=-29.995,lon=-50.995,timestamp=self.now-80+i,speed=4))
        self.assertIn('gps_off_route',[x['kind'] for x in self.s.findings(self.now)])
        self.assertTrue(self.s.findings(self.now)[0]['evidence'])
        self.now+=700
        self.assertIn('gps_no_signal',[x['kind'] for x in self.s.findings(self.now)])

    def test_restart_retains_binding_order_and_bounded_history(self):
        self.bind(); self.fix()
        s=Telemetry(self.s.path,lambda:['boat-a'],lambda:[self.mission],clock=lambda:self.now)
        self.assertEqual(s.ingest(dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-90))['status'],'ignored')
        self.assertEqual(s.view()['units'][0]['source'],'gps')

    def test_simulation_requires_sample_and_is_separate(self):
        self.bind()
        with self.assertRaises(ValueError): self.fix(source='simulated')
        self.s.sample=True; self.fix(); self.fix(1,source='simulated')
        self.assertEqual({r['source'] for r in self.s.view()['units']},{'gps','simulated'})

    def request(self,path,method='GET',data=None,content='application/json',origin=None):
        raw=(json.dumps(data).encode() if content=='application/json' else data.encode()) if data is not None else b''
        result=[]
        h=SimpleNamespace(path=path,headers={'Content-Length':str(len(raw)),'Content-Type':content,'Host':'desk'},
            rfile=io.BytesIO(raw),connection=SimpleNamespace(settimeout=lambda _:None),send_json=lambda code,body:result.extend([code,body]))
        if origin: h.headers['Origin']=origin
        handle(h,self.s,method);return result

    def test_osmand_get_form_json_and_query_only_post(self):
        self.bind()
        q=f'/api/telemetry/osmand?id=device-a&lat=-30&lon=-51&timestamp={self.now-5}&speed=2'
        self.assertEqual(self.request(q)[0],200)
        self.assertEqual(self.request('/api/telemetry/osmand','POST',f'id=device-a&lat=-30&lon=-51&timestamp={self.now-4}','application/x-www-form-urlencoded')[0],200)
        self.assertEqual(self.request('/api/telemetry/osmand','POST',dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-3))[0],200)
        self.assertEqual(self.request(q.replace(str(self.now-5),str(self.now-2)),'POST')[0],200)

    def test_batch_independent_rejections_and_same_origin_binding(self):
        self.assertEqual(self.request('/api/telemetry/bindings','POST',dict(device='device-a',unit_id='boat-a',actor='operator'),origin='http://evil')[0],403)
        self.assertFalse(self.s.bindings)
        self.assertEqual(self.request('/api/telemetry/bindings','POST',dict(device='device-a',unit_id='boat-a',actor='operator'))[0],200)
        code,body=self.request('/api/telemetry/positions','POST',{'positions':[dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-1),dict(id='device-a',lat=99,lon=-51)]})
        self.assertEqual(code,200)
        self.assertEqual([r['status'] for r in body['results']],['accepted','rejected'])
        self.assertEqual(self.request('/api/telemetry/missions')[0],403)

    def test_thresholds_and_bounded_history(self):
        self.bind()
        for i in range(130):
            self.s.ingest(dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-200+i,speed=4))
        row=self.s.view()['units'][0]
        self.assertEqual(len(row['trail']),10)
        self.assertEqual(len(self.s.history[('boat-a','gps')]),120)
        self.assertNotIn('gps_no_signal',[a['kind'] for a in self.s.findings(self.now+529)])
        self.assertIn('gps_no_signal',[a['kind'] for a in self.s.findings(self.now+530)])

    def test_stopped_alert_survives_compact_history(self):
        self.bind();self.mission['approved_at']=self.now-2000
        for i in range(1000):
            self.s.ingest(dict(id='device-a',lat=-30,lon=-51,timestamp=self.now-1500+i*1.5,speed=0))
        # Only 120 fixes are retained, yet the first stationary fix remains cited.
        self.assertIn('gps_stopped',[a['kind'] for a in self.s.findings(self.now)])

    def test_pre_mission_fix_does_not_make_new_mission_silent(self):
        self.bind();self.fix();self.now+=1000;self.mission['approved_at']=self.now-10
        self.assertNotIn('gps_no_signal',[a['kind'] for a in self.s.findings(self.now)])

    def test_no_fix_alert_and_old_mission_fix_not_used(self):
        self.mission['approved_at']=self.now-700
        self.assertEqual(self.s.findings(self.now)[0]['kind'],'gps_no_signal')
        self.bind();self.fix()
        self.mission['approved_at']=self.now-10
        row=self.s.view()['units'][0]
        self.assertIsNone(row['eta_seconds'])
        self.assertIsNone(row['arrival_proposal'])

    def test_supervisor_acknowledgement_and_resolution(self):
        from app.engines.world_model.registry import Registry
        from app.supervisor.service import SupervisorService
        from datetime import datetime, timezone
        registry=Registry(Path(self.tmp.name)/'events.jsonl')
        sup=SupervisorService(registry);sup.telemetry=self.s
        self.bind();self.fix();self.now+=700
        iso=lambda:datetime.fromtimestamp(self.now,timezone.utc).isoformat()
        alert=sup.tick(iso())['alerts'][0]
        self.assertEqual(alert['kind'],'gps_no_signal')
        self.assertTrue(alert['evidence'][0]['fix_id'])
        sup.decide(alert['alert_id'],'accept','dispatcher',iso())
        self.s.ingest(dict(id='device-a',lat=-30,lon=-51,timestamp=self.now,speed=4))
        self.assertEqual(sup.tick(iso())['rechecks'][0]['outcome'],'resolved')
        self.assertFalse(any(e.get('kind')=='unit_status' for e in self.s.events()))

    def test_route_adapter_snapshots_real_legs_only_once(self):
        plan=dict(status='assigned',units=[dict(id='boat-a',base_location=dict(lat=-30,lon=-51))],date='2024-05-08',
            stops=[dict(case_id='case-a',point=dict(lat=-30,lon=-50.99))])
        status=SimpleNamespace(view=lambda:{'units':[dict(unit_id='boat-a',mission_id='m1',status='en_route')]},
            journal=lambda:[dict(kind='approve_mission',mission_id='m1',at='2024-05-08T00:00:00Z')])
        missions=SimpleNamespace(detail=lambda mid:plan,registry=SimpleNamespace(read=lambda cid:dict(case_id=cid,position=plan['stops'][0]['point'])))
        routes=ApprovedRoutes(status,missions,self.s)
        route=dict(reachable=True,land={'polyline':[[-51,-30],[-50.995,-30]]},water={'polyline':[[-50.995,-30],[-50.99,-30]],'fallback':False,'grid_verified':True})
        with patch('app.geo.routing.case_route',return_value=route) as routing:
            first=routes();second=routes()
        self.assertEqual(routing.call_count,1)
        self.assertEqual(first,second)
        self.assertEqual(first[0]['polyline'],[[-51,-30],[-50.995,-30],[-50.99,-30]])
        self.assertEqual([s['mode'] for s in first[0]['segments']],['land','water'])
        restored=ApprovedRoutes(status,missions,self.s)
        with patch('app.geo.routing.case_route',side_effect=AssertionError('must use snapshot')):
            self.assertEqual(restored(),first)

    def test_grid_shore_gap_preserves_real_segments(self):
        plan=dict(status='assigned',units=[dict(id='boat-a',base_location=dict(lat=-30,lon=-51))],date='2024-05-08',
            stops=[dict(case_id='case-a',point=dict(lat=-30,lon=-50.99))])
        status=SimpleNamespace(view=lambda:{'units':[dict(unit_id='boat-a',mission_id='grid-mission',status='en_route')]},
            journal=lambda:[dict(kind='approve_mission',mission_id='grid-mission',at='2024-05-08T00:00:00Z')])
        route=dict(reachable=True,land={'polyline':[[-51,-30],[-50.995,-30]]},
            water={'polyline':[[-50.9949,-30],[-50.9901,-30]],'fallback':False,'grid_verified':True,'start_gap_m':10,'review_pt':['Confirmar acesso à margem.']})
        with patch('app.geo.routing.case_route',return_value=route):
            mission=ApprovedRoutes(status,SimpleNamespace(detail=lambda mid:plan),self.s)()[0]
        self.assertEqual(len(mission['segments']),2)
        self.assertIn('Confirmar acesso à margem.',mission['review_pt'])

    def test_eval_timelines(self):
        from eval.run_telemetry import run_case
        cases=[json.loads(s) for s in Path('eval/telemetry_set.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(cases),12)
        for case in cases:
            with self.subTest(case=case['id']): self.assertTrue(run_case(case)['passed'])

    def test_f3_status_api_exposes_proposal_without_changing_status(self):
        from app.unit_status import UnitStatusService
        from app.unit_status_routes import handle as status_handle
        from app.engines.world_model.registry import Registry
        from datetime import datetime, timezone
        status=UnitStatusService(Registry(Path(self.tmp.name)/'status.jsonl'),lambda:[{'id':'boat-a'}])
        status.telemetry=self.s;self.bind()
        self.s.ingest(dict(id='device-a',lat=-30,lon=-50.9901,timestamp=self.now-2))
        self.s.ingest(dict(id='device-a',lat=-30,lon=-50.9901,timestamp=self.now-1))
        result=[]
        status_handle(SimpleNamespace(path='/api/units/status',send_json=lambda code,body:result.extend([code,body])),status,'GET')
        self.assertEqual(result[0],200)
        self.assertEqual(result[1]['units'][0]['status'],'unknown')
        self.assertEqual(result[1]['telemetry_proposals'][0]['status'],'confirmation_required')
        status.report('boat-a',dict(actor='dispatcher',source='operator',status='on_scene',received_at=datetime.fromtimestamp(self.now,timezone.utc).isoformat()))
        self.assertEqual(status.view()['units'][0]['status'],'on_scene')


if __name__=='__main__': unittest.main()
