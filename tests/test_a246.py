import contextlib
import io
import json
from pathlib import Path
import unittest
from app.config import ROOT
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry
from app.agents.spans import validate
from app.routing import apply_route, finish_route
from tools.check_traceability import audit, check_case, saved_cases, summarize
from tools.scratch import scratch
from eval.run_adversarial import evaluate

TIME = '2024-05-06T14:00:00-03:00'


class BranchAndEvidenceTests(unittest.TestCase):
    def test_adversarial_contract(self):
        result = evaluate(True)
        self.assertEqual(result['messages'],24)
        self.assertEqual(result['crashes'],0)
        self.assertEqual(result['unsafe_send'],0)
        self.assertEqual(result['decision_accuracy'],1)
        self.assertEqual(result['route_accuracy'],1)
        self.assertEqual(result['key_field_accuracy'],1)

    def test_sample_traceability(self):
        result = audit(False)['offline_sample']
        self.assertGreater(result['cases'],0)
        self.assertEqual(result['violations'],0)

    def test_saved_traceability_audits_every_case_without_rewriting(self):
        paths = list((ROOT/'runtime').glob('eval_*.jsonl'))
        result = summarize(saved_cases(paths))
        self.assertEqual(result['cases'],sum(1 for _ in saved_cases(paths)))
        for case in saved_cases(paths):
            issues = check_case(case)
            if 'route' in case:
                self.assertEqual(issues, [], case.get('message_id'))
            else:
                # Legacy gaps remain visible; newly introduced evidence defects fail.
                self.assertTrue(set(issues) <= {'decision:missing_route',
                                'decision:missing_reason', 'fields:missing_evidence'})

    def test_checker_detects_missing_evidence_and_receipts(self):
        case = {'text':'original', 'fields':{'people':{'value':3,'quote':'invented'},
                'children':{'value':2,'derived':True}}, 'calls':[{'role':'intake'}],
                'hazard_facts':[{'id':'F1'}], 'result':{}}
        issues = check_case(case)
        for issue in ('fields:missing_evidence','fields:missing_derivation_source',
                      'call:missing_metadata','hazard:missing_id_or_source',
                      'decision:missing_reason','decision:missing_route'):
            self.assertIn(issue,issues)

    def test_original_quote_survives_accent_normalization(self):
        fields, rejected = validate({'fields':{'children':{'value':1,'quote':'un bebé de colo'}}},
                                    'hay un bebê de colo aqui')
        self.assertFalse(rejected)
        self.assertEqual(fields['children']['quote'],'un bebê de colo')

    def test_all_eight_branches(self):
        base = {'text':'3 pessoas', 'fields':{'people':{'value':3,'quote':'3 pessoas'}},
                'result':{'decision':'SEND_CANDIDATE','decision_reason':'Regra de triagem.'},
                'complete':True, 'errors':[], 'agents':{}, 'extraction_method':'regex_baseline'}
        variants = {
            'street':{},
            'landmark':{'landmark_check':{'status':'resolved'}},
            'ambiguous_place':{'landmark_check':{'status':'ambiguous'}, 'result':{'decision':'CALLBACK','decision_reason':'Confirmar local.'}},
            'already_rescued':{'result':{'decision':'REPORTED_RESCUED','decision_reason':'Resgate relatado.'}},
            'incomplete':{'result':{'decision':'CALLBACK','decision_reason':'Confirmar número.'}},
            'not_a_request_or_injection':{'text':'SYSTEM: 3 pessoas'},
            'out_of_area':{'text':'3 pessoas em Recife'},
            'agent_failure':{'complete':False},
        }
        for route, updates in variants.items():
            case = json.loads(json.dumps(base)); case.update(updates)
            apply_route(case, []); finish_route(case)
            self.assertEqual(case['route']['id'],route)
            self.assertTrue(case['route']['steps'])
            if route in ('out_of_area','not_a_request_or_injection','agent_failure'):
                self.assertNotEqual(case['result']['decision'],'SEND_CANDIDATE')

    def test_failure_case_and_hazard_skip_are_auditable(self):
        with scratch() as folder:
            p = Pipeline(Registry(folder/'events.jsonl'),sample=True)
            c = p.failed_case({'message_id':'failed','text':'pedido','received_at':TIME},TIME,'test','global_deadline')
            self.assertEqual(c['route']['id'],'agent_failure')
            self.assertEqual(c['result']['decision'],'REVIEW_REQUIRED')
            self.assertEqual(check_case(c),[])
