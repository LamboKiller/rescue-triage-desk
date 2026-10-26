"""Unit movement must be sourced, replayable and separate from predictions."""
import sys
import unittest
import threading
import http.client
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engines.world_model.registry import Registry
from app import unit_status as U
from support import Scratch


class UnitStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Registry(Path(self.tmp.name)/'events.jsonl')
        self.service = U.UnitStatusService(self.registry, lambda: [{'id':'boat-a'}])

    def report(self, text, minute=10, **extra):
        return self.service.report('boat-a', dict(text=text, actor='crew-a', source='crew',
            received_at=f'2024-05-08T14:{minute:02}:00-03:00', **extra))

    def approve(self, eta=600):
        from eval.run_feedback import seed
        c=seed(self.registry,'unit-timeline')
        plan={'units':[{'id':'boat-a'}], 'stops':[{'case_id':c['case_id']}], 'eta_seconds':eta}
        c.update(mission_id='mission-a', mission=plan, status='ASSIGNED:mission-a')
        with self.registry.locked():
            self.registry._append(dict(kind='approve_mission',at='2024-05-08T14:00:00-03:00',mission_id='mission-a',projections=[c]))
        return c

    def test_reports_and_late_reordering(self):
        self.report('Já chegamos ao endereço.', 20)
        self.report('Saímos da base.', 10)
        row = self.service.view('2024-05-08T14:30:00-03:00')['units'][0]
        self.assertEqual(row['status'], 'on_scene')
        self.assertEqual(row['status_at'], '2024-05-08T14:20:00-03:00')
        self.assertEqual(self.service.view('2024-05-08T14:15:00-03:00')['units'][0]['status'], 'en_route')

    def test_no_source_means_unknown(self):
        self.assertEqual(self.service.view('2024-05-08T14:00:00-03:00')['units'][0]['status'], 'unknown')
        self.report('Como está o tempo?')
        self.assertEqual(self.service.view('2024-05-08T14:30:00-03:00')['units'][0]['status'], 'unknown')

    def test_wrong_unit_and_injection_rejected(self):
        with self.assertRaises(ValueError): self.report('Saímos', unit_id='boat-b')
        with self.assertRaises(KeyError): self.service.report('missing', {})
        self.assertFalse(self.registry.read())

    def test_negated_movement_and_model_evidence(self):
        self.report('Não chegamos; talvez voltando.')
        self.assertEqual(self.service.view('2024-05-08T14:30:00-03:00')['units'][0]['status'], 'unknown')
        from app.feedback import validate
        with self.assertRaises(ValueError): validate({'outcomes':[{'kind':'unit_arrived','quote':'motor quebrou'}]}, 'motor quebrou')

    def test_engine_failure_hint_and_no_timer_transition(self):
        self.report('O motor quebrou no canal.')
        row = self.service.view('2024-05-09T14:00:00-03:00')['units'][0]
        self.assertEqual(row['status'], 'out_of_service')
        self.assertIn('Replanejar', row['reroute_hint_pt'])
        self.assertTrue(row['source_event'])

    def test_estimate_alert_acknowledgement_and_resolution(self):
        self.approve()
        row=self.service.view('2024-05-08T14:31:00-03:00')['units'][0]
        self.assertEqual(row['status'],'assigned')
        self.assertEqual(row['expected']['at'],'2024-05-08T14:10:00-03:00')
        self.assertFalse(self.service.findings('2024-05-08T14:30:00-03:00'))
        self.assertEqual(self.service.findings('2024-05-08T14:31:00-03:00')[0]['kind'],'unit_silent')
        from app.supervisor.service import SupervisorService
        sup=SupervisorService(self.registry);sup.unit_status=self.service
        alert=next(a for a in sup.tick('2024-05-08T14:31:00-03:00')['alerts'] if a['kind']=='unit_silent')
        result=sup.decide(alert['alert_id'],'accept','dispatcher','2024-05-08T14:32:00-03:00')
        self.assertEqual(result['status'],'accepted')
        self.assertTrue(sup.tick('2024-05-08T14:33:00-03:00')['rechecks'])
        self.report('Chegamos à residência.',34,mission_id='mission-a')
        self.assertEqual(sup.tick('2024-05-08T14:35:00-03:00')['rechecks'][0]['outcome'],'resolved')

    def test_idle_threshold_not_refreshed_by_pickup(self):
        self.approve()
        self.report('Chegamos ao local.',10)
        self.report('Pegamos 3 pessoas.',40)
        self.assertEqual(self.service.findings('2024-05-08T14:51:00-03:00')[0]['kind'],'unit_idle')

    def test_mission_membership_and_landing_events(self):
        self.approve()
        with self.assertRaises(ValueError): self.report('Saímos.',10,mission_id='wrong-mission')
        self.service.landing_events=lambda:[dict(kind='arrival',unit_id='boat-a',mission_id='mission-a',
            at='2024-05-08T14:40:00-03:00',source='crew',landing_id='pier-a')]
        row=self.service.view('2024-05-08T14:41:00-03:00')['units'][0]
        self.assertEqual(row['status'],'unloading')
        self.assertTrue(row['source_event'].startswith('landing:'))

    def test_breakdown_removes_inventory_and_does_not_clear_on_movement(self):
        self.report('Motor quebrou.')
        self.report('Estamos voltando.',20)
        units=U.overlay_inventory(self.registry,[dict(id='boat-a',status='available',available=True)])
        self.assertFalse(units[0]['available'])
        self.assertEqual(units[0]['status'],'out_of_service')
        self.service.report('boat-a',dict(actor='op',received_at='2024-05-08T14:30:00-03:00',status='available'))
        self.assertEqual(self.service.view('2024-05-08T14:31:00-03:00')['units'][0]['status'],'available')

    def test_reported_failure_overrides_available_button(self):
        self.service.report('boat-a',dict(text='Motor quebrou no retorno.',source='operator',status='available',
            actor='op',received_at='2024-05-08T14:00:00-03:00'))
        row=self.service.view('2024-05-08T14:01:00-03:00')['units'][0]
        self.assertEqual(row['status'],'out_of_service')

    def test_existing_field_feedback_drives_single_unit(self):
        c=self.approve()
        from app.feedback import FeedbackService
        FeedbackService(self.registry).submit(c['case_id'],dict(text='Saímos da base.',actor='crew',
            received_at='2024-05-08T14:05:00-03:00',expected_version=c['version']))
        self.assertEqual(self.service.view('2024-05-08T14:06:00-03:00')['units'][0]['status'],'en_route')

    def test_partial_pickup_keeps_unit_busy_until_an_availability_report(self):
        c=self.approve()
        from app.feedback import FeedbackService
        c=FeedbackService(self.registry).submit(c['case_id'],dict(text='Pegamos 2, falta 2.',actor='crew',
            received_at='2024-05-08T14:05:00-03:00',expected_version=c['version']))
        self.assertFalse(U.overlay_inventory(self.registry,[dict(id='boat-a',status='available',available=True)])[0]['available'])
        self.report('Desembarcamos no ponto da base. Unidade disponível.',10)
        self.assertTrue(U.overlay_inventory(self.registry,[dict(id='boat-a',status='available',available=True)])[0]['available'])

    def test_api_report_replay_and_origin(self):
        from app.web.server import create_server
        server=create_server('127.0.0.1',0,sample=True,registry_path=self.tmp.path/'api.jsonl',inventory=[{'id':'boat-a'}])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
        try:
            body=json.dumps(dict(text='Saímos da sede.',actor='op',received_at='2024-05-08T14:00:00-03:00'))
            conn.request('POST','/api/units/boat-a/report',body,{'Content-Type':'application/json'})
            response=conn.getresponse();self.assertEqual(response.status,200);response.read()
            conn.request('GET','/api/units/status?replay_time=2024-05-08T14:01:00-03:00')
            response=conn.getresponse();data=json.loads(response.read())
            self.assertEqual((response.status,data['units'][0]['status']),(200,'en_route'))
            conn.request('POST','/api/units/boat-a/report',body,{'Content-Type':'application/json','Origin':'https://elsewhere.invalid'})
            response=conn.getresponse();self.assertEqual(response.status,403);response.read()
        finally:
            conn.close();server.shutdown();server.server_close();thread.join()


if __name__ == '__main__': unittest.main()
