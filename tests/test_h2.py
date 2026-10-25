import contextlib
import io
import json
import time
import unittest
from pathlib import Path
from support import Scratch
from unittest.mock import patch
from app.agents import hazard_critic as hazard
from app.llm.nightshift import Nightshift, first_json, read_stream


class HazardFixTests(unittest.TestCase):
    def test_stream_deadline_and_reasoning_only(self):
        stream=[b'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}',
                b'data: [DONE]']
        self.assertEqual(read_stream(stream),('',{}))
        with self.assertRaises(TimeoutError):
            read_stream(stream,time.monotonic()-1)

    def test_parser_wrappers_and_truncation(self):
        for text in ('```json\n{"ok":true}\n```', '<think>{"wrong":true}</think>\n{"ok":true}',
                     'reasoning </think> {"ok":true}'):
            self.assertEqual(first_json(text), {"ok": True})
        for text in ('', '<think>{"ok":true}', '{"objections":[{"fact_ids":[]} ]', '{"a":{}'):
            with self.assertRaises(ValueError): first_json(text)

    def case(self):
        return {'text':'SECRET UNNEEDED MESSAGE'*100, 'fields':{'people':{'value':3,'quote':'verbose'}},
                'result':{'decision':'SEND_CANDIDATE'}, 'proposed_asset':'car',
                'fleet_summary':{'unsafe_assets':['car'],'options':[]},
                'hazard_facts':[{'id':'depth','text_pt':'Profundidade 2.7 m.','source':'long'*100},
                                {'id':'fleet:car','text_pt':'Carro: unsafe. Agua 2.7 m.','source':'rules'},
                                {'id':'fleet:boat','text_pt':'irrelevant','source':'rules'}]}

    def test_compact_input_and_ids(self):
        case=self.case()
        class Client:
            def call(inner,role,system,payload,deadline):
                data=json.loads(payload)
                self.assertNotIn('message',data)
                self.assertNotIn('fleet_summary',data)
                self.assertLess(len(payload),500)
                self.assertNotIn('source',payload)
                self.assertNotIn('fleet:boat',payload)
                return {'block':['fleet:car'],'warn':[]}, {'role':role}
        review,n,_=hazard.run(Client(),case['text'],case,time.monotonic()+5)
        self.assertEqual(n,0)
        self.assertEqual(review['objections'][0]['fact_ids'],['fleet:car'])
        self.assertEqual(review['objections'][0]['text_pt'],case['hazard_facts'][1]['text_pt'])
        with self.assertRaises(ValueError):
            hazard.expand({'block':['invented'],'warn':[]},case['hazard_facts'])

    def test_visible_fallback_preserves_triage(self):
        case=self.case()
        class Fail:
            def call(self,*args): raise ValueError('bad')
        hazard.attach(case,Fail(),time.monotonic()+5)
        self.assertEqual(case['hazard_check'],'deterministic_only')
        self.assertEqual(case['hazard_review'],'indispon\u00edvel')
        self.assertEqual(case['result']['decision'],'SEND_CANDIDATE')

    def test_hazard_transport_short_retry_and_budget(self):
        class Response:
            status=200
            def __init__(self,content): self.content=content
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def __iter__(self):
                return iter([json.dumps({'choices':[{'message':{'content':self.content}}]}).encode()])
        scratch=Scratch(); self.addCleanup(scratch.cleanup)
        with patch.dict('os.environ',{'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
             patch('urllib.request.urlopen',side_effect=[Response(''),Response('{"block":[],"warn":[]}')]) as urlopen, \
             contextlib.redirect_stdout(io.StringIO()):
            client=Nightshift(scratch.path/'trace.jsonl'); client.start_message('test')
            payload=json.dumps({'facts':[{'id':'depth','text_pt':'2.7 m'},{'id':'fleet:car','text_pt':'unsafe'}], 'proposed_asset':'car'})
            _,meta=client.call('hazard_critic',hazard.SYSTEM,payload,time.monotonic()+30)
            bodies=[json.loads(c.args[0].data) for c in urlopen.call_args_list]
            self.assertEqual(len(bodies),2)
            self.assertNotIn('chat_template_kwargs',bodies[0])  # thinking must stay ON on Nightshift
            self.assertLess(len(json.dumps(bodies[1])),len(json.dumps(bodies[0])))
            self.assertEqual(meta['output_chars'],22)

    def test_diagnostic_summary_and_failure(self):
        from tools.diagnose_hazard import diagnose
        class Client:
            def start_message(self,mid): pass
            def message_calls(self): return []
            def call(self,*args):
                return {'block':[],'warn':[]}, {'status':'ok','model':'TEST','output_chars':22}
        for fail,expected in ((False,0),(True,1)):
            client=Client()
            if fail:
                client.call=lambda *args: (_ for _ in ()).throw(ValueError('test'))
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(diagnose(client),expected)
            lines=output.getvalue().splitlines()
            self.assertEqual(len(lines),4)
            self.assertTrue(lines[-1].startswith('NOT YET' if fail else 'PASSED'))
            self.assertEqual(set(json.loads(lines[0])),
                             {'status','winner_model','seconds','output_chars','parse'})


if __name__=='__main__': unittest.main()
