import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from tests.support import Scratch
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry, Conflict

TIME = '2024-05-06T14:00:00-03:00'

class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Registry(Path(self.tmp.name)/'events.jsonl')
        self.pipeline = Pipeline(self.registry, sample=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.case = self.pipeline.run({'replay_time':TIME,'messages':[{'message_id':'callback','text':'Precisamos de resgate, 3 pessoas em Porto Alegre, número 40.','received_at':TIME}]})['cases'][0]

    def reply(self, text):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.pipeline.reply(self.case['case_id'], {'text':text,'received_at':TIME})

    def test_merge_and_version(self):
        case = self.reply('Estamos na Rua dos Andradas em Porto Alegre.')
        self.assertEqual(case['version'], 2)
        self.assertEqual(case['parent_version'], 1)
        self.assertEqual(case['fields']['people']['value'], 3)
        self.assertEqual(case['fields']['people']['message_index'], 0)
        self.assertEqual(case['fields']['street']['message_index'], 1)
        self.assertEqual(len(case['messages']), 2)
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertIn('street', case['change_summary_pt'])
        self.assertEqual(len(case['facts']), 2)

    def test_conflict_keeps_previous_count(self):
        case = self.reply('Agora somos 5 pessoas.')
        self.assertTrue(case['result']['conflicting_counts'])
        self.assertEqual(case['fields']['people']['value'], 3)
        self.assertTrue(case['contradictions'])

    def test_explicit_correction(self):
        case = self.reply('Corrigindo: 5 pessoas.')
        self.assertEqual(case['fields']['people']['value'], 5)
        self.assertFalse(case['result']['conflicting_counts'])

    def test_failure_retains_previous_analysis(self):
        with patch('app.agents.baseline.extract', side_effect=RuntimeError('broken')):
            case = self.reply('Rua dos Andradas em Porto Alegre')
        self.assertEqual(case['fields'], self.case['fields'])
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(case['parent_version'], 1)
        self.assertEqual(len(case['messages']), 2)

    def test_empty_reply_is_recorded_for_review(self):
        case = self.reply('')
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(len(case['messages']), 2)

    def test_card_numbers_have_case_provenance(self):
        from app.dispatch_card import build_card
        case = self.reply('Já fomos resgatados.')
        card = build_card(case)
        self.assertEqual(card['text_pt'], '\n'.join(card['lines']))
        self.assertTrue(card['facts_used'])
        for fact in card['facts_used']:
            value = case
            for key in fact['path'].split('.'):
                value = value[int(key)] if isinstance(value,list) else value[key]
            self.assertEqual(value, fact['value'])
        import re
        numbers = re.findall(r'\d+', card['text_pt'])
        evidence = ' '.join(str(f['value']) for f in card['facts_used'])
        for number in numbers:
            self.assertIn(number, evidence)


class CallbackExtendedTests(unittest.TestCase):
    setUp = CallbackTests.setUp
    reply = CallbackTests.reply

    def test_live_reply_intake_only_and_failure_recovery(self):
        from unittest.mock import Mock
        self.pipeline.sample=False
        client=Mock()
        client.call.return_value=({'objections':[], 'brief_pt':''},{'role':'critic','model':'fake','receipt':'test'})
        self.pipeline.client=client
        text='Rua das Flores'
        with patch('app.agents.intake.run',return_value=({'fields':{'street':{'value':text,'quote':text}}},{'role':'intake','model':'fake','receipt':'test'})) as intake:
            case=self.reply(text)
        self.assertEqual(intake.call_args.args[1], text)
        self.assertEqual(case['result']['decision'],'SEND_CANDIDATE')
        critic_calls=[c for c in client.call.call_args_list if c.args[0]=='critic']
        self.assertEqual(len(critic_calls),1)
        self.assertIn(self.case['text'],critic_calls[0].args[2])
        self.assertTrue(any(c.args[0]=='hazard_critic' for c in client.call.call_args_list))
        self.case=case
        client.call.side_effect=TimeoutError('failed critic')
        with patch('app.agents.intake.run',return_value=({'fields':{}},{'role':'intake','model':'fake','receipt':'test'})):
            failed=self.reply('hello')
        self.assertEqual(failed['fields'],case['fields'])
        self.assertEqual(failed['result']['decision'],'REVIEW_REQUIRED')
        self.assertEqual(failed['version'],3)
        self.assertEqual(len(failed['messages']),3)

    def test_stale_reply_cannot_overwrite_action(self):
        from copy import deepcopy
        self.registry.action(self.case['case_id'],'request_callback',1,'test',human=True)
        with self.assertRaises(Conflict):
            self.registry.append_reply(self.case['case_id'],1,deepcopy(self.case))
        self.assertEqual(self.registry.read(self.case['case_id'])['version'],2)

    def test_bedridden_reply_reruns_fleet_and_card_kit_has_rule(self):
        from app.dispatch_card import build_card
        case=self.reply('1 acamado')
        self.assertEqual(case['fields']['disabled']['value'],1)
        self.assertNotEqual(case['fleet'],self.case['fleet'])
        screened=next(r for r in case['fleet'] if 'R061' in r['rule_ids'] or 'R060' in r['rule_ids'])
        case['proposed_asset']=screened['asset']
        card=build_card(case)
        self.assertIn('maca',card['text_pt'])
        self.assertTrue(any(f['value'] in ('R060','R061') for f in card['facts_used'] if isinstance(f['value'],str)))

class DialogueContractTests(unittest.TestCase):
    def test_live_critic_sees_both_messages_in_critic_role(self):
        from app.dialogue import merge
        from unittest.mock import Mock
        client=Mock()
        client.call.return_value=({'objections':[]},{'role':'critic','model':'fake','receipt':'test'})
        old={'text':'3 pessoas','message_id':'x','received_at':TIME,'fields':{'people':{'value':3,'quote':'3 pessoas'}}}
        reply={'text':'1 acamado','message_id':'y','received_at':TIME}
        merged,history,conflicts,changes,review,calls=merge(old,{'disabled':{'value':1,'quote':'1 acamado'}},reply,client,100,False)
        args=client.call.call_args.args
        self.assertEqual(args[0],'critic')
        self.assertIn('3 pessoas',args[2]);self.assertIn('1 acamado',args[2])
        self.assertEqual(merged['disabled']['message_index'],1)
        self.assertEqual(merged['people']['message_index'],0)

    def test_invalid_critic_evidence_fails_closed(self):
        from app.dialogue import merge
        from unittest.mock import Mock
        client=Mock();client.call.return_value=({'objections':[{'field':'people','quote':'invented'}]}, {})
        old={'text':'3 pessoas','message_id':'x','received_at':TIME,'fields':{}}
        with self.assertRaises(ValueError):
            merge(old,{},dict(old,text='hello'),client,100,False)

class CallbackHTTPTests(unittest.TestCase):
    setUp = CallbackTests.setUp
    # Reuse the initial case fixture without inheriting its test methods below.
    def test_reply_and_card_http_contract(self):
        import http.client
        import threading
        import json
        from run import create_server
        server=create_server('127.0.0.1',0,pipeline=self.pipeline)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=120)
            cid=self.case['case_id']
            conn.request('POST',f'/api/cases/{cid}/reply',json.dumps({'text':'Rua das Flores','received_at':TIME}),{'Content-Type':'application/json'})
            response=conn.getresponse();case=json.loads(response.read());self.assertEqual(response.status,200)
            self.assertEqual(case['version'],2)
            conn.request('GET',f'/api/cases/{cid}/card');response=conn.getresponse();card=json.loads(response.read())
            self.assertEqual(response.status,200);self.assertIn('text_pt',card)
            conn.request('GET','/api/cases/unknown/card');response=conn.getresponse();response.read();self.assertEqual(response.status,404)
            conn.request('POST',f'/api/cases/{cid}/reply',json.dumps({'text':'hello','received_at':'bad'}),{'Content-Type':'application/json'})
            response=conn.getresponse();response.read();self.assertEqual(response.status,400)
            conn.close()
        finally:
            server.shutdown();server.server_close();thread.join()

class CardEvidenceTests(unittest.TestCase):
    def test_all_numeric_tokens_come_from_exact_case_paths(self):
        import copy
        import re
        from app.dispatch_card import build_card
        case={'case_id':'case-927','version':7,'fields':{
            'people':{'value':12},'children':{'value':2},'number':{'value':'431'},
            'street':{'value':'Rua Exemplo'},'municipality':{'value':'Canoas'}},
            'result':{'location_confidence':'confirmar','questions':['Confirmar total: 12 pessoas.']},
            'position':{'position_kind':'street_centroid'},
            'hazards':{'depth_band':'d_0_6_to_1_2','depth_observed_date':'2024-05-08'},
            'fleet':[{'asset':'test','label_pt':'Recurso','verdict':'caution','reasons_pt':['Confirmar as 12 pessoas.'],
                      'rule_ids':['R065'],'source_ids':['PFD']}]}
        before=copy.deepcopy(case);card=build_card(case)
        self.assertEqual(case,before)
        numeric_evidence=set()
        for fact in card['facts_used']:
            value=case
            for key in fact['path'].split('.'):
                value=value[int(key)] if isinstance(value,list) else value[key]
            self.assertEqual(value,fact['value'])
            numeric_evidence.update(re.findall(r'\d+',str(value)))
        self.assertLessEqual(set(re.findall(r'\d+',card['text_pt'])),numeric_evidence)
        self.assertIn('coletes infantis',card['text_pt'])
        self.assertIn('estimativa',card['text_pt'])

if __name__ == '__main__':
    unittest.main()
