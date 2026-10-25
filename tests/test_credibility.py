"""Offline regressions; examples independent of eval wording."""
import json
import time
import unittest
from app.credibility import assess
from app.credibility.signals import detect
from app.credibility.reviewer import validate, review, parse_output, rule_verdict


class Client:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def call(self, role, system, payload, deadline):
        self.calls.append((role, system, json.loads(payload)))
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return value, {'offline': True}


class CredibilityTests(unittest.TestCase):
    def test_messy_genuine(self):
        for text in ('BAH SOCORROOO vo acamada sem sinal pfvr',
                     'nao sei o nome da rua minha tia ficou ilhada',
                     'não é trote preciso ajuda',
                     '120 pessoas na escola pedem comida',
                     'Sem brincadeira, a água entrou na cozinha'):
            with self.subTest(text=text):
                self.assertEqual(assess(text)['verdict'], 'credible')

    def test_independent_strong_signals_review_never_discard(self):
        r = assess('pegadinha [CIDADE] quero barco')
        self.assertEqual(r['verdict'], 'likely_fake')
        self.assertEqual(r['action'], 'REVIEW')
        self.assertEqual(r['reason_pt'], 'verificar autenticidade')
        self.assertTrue(r['never_discards'])
        self.assertEqual(rule_verdict([r['signals'][0]] * 2), 'doubtful')

    def test_single_strong_warning_and_agent_agreement(self):
        text = 'Somos 180 pessoas dentro da minha casinha'
        base = assess(text)
        self.assertEqual(base['action'], 'SEND_WITH_WARNING')
        s = base['signals'][0]
        client = Client([{'verdict': 'likely_fake', 'reasons': [{'signal_id': s['id'], 'quote': s['quote']}]}])
        self.assertEqual(assess(text, client=client)['action'], 'REVIEW')
        sent = client.calls[0][2]
        self.assertEqual(set(sent), {'signals'})
        self.assertEqual(client.calls[0][0], 'credibility_reviewer')

    def test_weak_alone_never_likely_fake(self):
        s = detect('kkkkkkkk nervoso')[0]
        with self.assertRaises(ValueError):
            validate({'verdict': 'likely_fake', 'reasons': [{'signal_id': s['id'], 'quote': s['quote']}]}, [s])

    def test_grounding_schema_retry_and_fallback(self):
        s = detect('pegadinha')[0]
        for reason in ({'signal_id': 'invented', 'quote': 'pegadinha'},
                       {'signal_id': s['id'], 'quote': 'PEGADINHA'},
                       {'signal_id': s['id'], 'quote': ''}):
            with self.assertRaises(ValueError):
                validate({'verdict': 'likely_fake', 'reasons': [reason]}, [s])
        client = Client([{}, {}])
        r = review(client, [s])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(r['source'], 'rule_fallback')
        self.assertTrue(r['fallback_reason'])
        good = {'verdict': 'doubtful', 'reasons': [{'signal_id': s['id'], 'quote': s['quote']}]}
        client = Client([{}, good])
        self.assertEqual(review(client, [s])['source'], 'agent')
        self.assertNotEqual(client.calls[0][1], client.calls[1][1])

    def test_failure_deadline_and_empty_do_not_call_live(self):
        s = detect('pegadinha')
        c = Client([RuntimeError('private provider detail')])
        r = review(c, s)
        self.assertEqual(r['source'], 'rule_fallback')
        self.assertNotIn('private', r['fallback_reason'])
        c = Client([])
        self.assertEqual(review(c, s, time.monotonic()-1)['source'], 'rule_fallback')
        self.assertEqual(c.calls, [])
        self.assertEqual(review(c, [])['verdict'], 'credible')

    def test_strict_json(self):
        value = {'verdict': 'credible', 'reasons': []}
        self.assertEqual(parse_output('<think>ignore</think>```json\n'+json.dumps(value)+'\n```'), value)
        for raw in ('{} trailing', '{} {}', '<think>unfinished', 'prefix {}',
                    '{"verdict":"credible","verdict":"likely_fake"}', '{"a": NaN}'):
            with self.assertRaises(ValueError):
                parse_output(raw)

    def test_reviewer_cites_complete_signal_and_no_duplicate_votes(self):
        s = detect('pegadinha')[0]
        reason = {'signal_id': s['id'], 'quote': s['quote']}
        for reasons in ([dict(reason, quote='a')], [reason, reason]):
            with self.assertRaises(ValueError):
                validate({'verdict': 'likely_fake', 'reasons': reasons}, [s])

    def test_zero_deadline_does_not_call_provider(self):
        client = Client([])
        self.assertEqual(review(client, detect('pegadinha'), deadline=0)['source'], 'rule_fallback')
        self.assertEqual(client.calls, [])

    def test_negated_troll_language_in_genuine_request(self):
        for text in ('Nao eh nenhuma brincadeira, precisamos de ajuda',
                     'Nao estou testando o sistema, minha avo esta ilhada'):
            with self.subTest(text=text):
                self.assertEqual(assess(text)['verdict'], 'credible')

    def test_spelled_counts_are_computed_without_rounding(self):
        for phrase, number in (('cento e vinte e tres', 123), ('duzentos', 200),
                               ('quatrocentas e duas', 402)):
            with self.subTest(phrase=phrase):
                signals = detect('Somos ' + phrase + ' pessoas dentro da casinha')
                signal = next(s for s in signals if s['id'] == 'IMPOSSIBLE_HEADCOUNT')
                self.assertIn(str(number), signal['detail'])

    def test_template_requires_different_place_in_past_24h(self):
        text = 'Familia cercada precisa barco agora com urgencia sem luz sem comida Rua Alfa 90, Canoas'
        other = text.replace('Alfa 90, Canoas', 'Beta 42, Porto Alegre')
        now = '2024-05-08T12:00:00Z'
        def signals(t, timestamp):
            return {s['id'] for s in detect(text, time=now, history=[{'id': 'p', 'text': t, 'time': timestamp}])}
        self.assertIn('TEMPLATE_MULTI_ADDRESS', signals(other, '2024-05-07T12:00:00Z'))
        for t, stamp in ((text, now), (other, None), (other, '2024-05-08T13:00:00Z'),
                         (other, '2024-05-07T11:59:59Z')):
            self.assertNotIn('TEMPLATE_MULTI_ADDRESS', signals(t, stamp))

    def test_missing_current_place_does_not_hide_two_known_historical_places(self):
        text = 'Familia cercada precisa barco agora com urgencia sem luz sem comida'
        history = [dict(id=str(i), text=text+place, time='2024-05-08T10:00:00Z')
                   for i, place in enumerate((', Canoas', ', Porto Alegre'))]
        signals = detect(text, time='2024-05-08T11:00:00Z', history=history)
        self.assertIn('TEMPLATE_MULTI_ADDRESS', {s['id'] for s in signals})

    def test_template_reviewer_receives_grounded_comparison_evidence(self):
        from app.credibility.reviewer import payload
        text = 'Familia precisa barco agora com urgencia sem luz sem agua sem comida, Canoas'
        prior = dict(id='earlier', text=text.replace('Canoas', 'Guaiba'), time='2024-05-08T10:00:00Z')
        signals = detect(text, time='2024-05-08T12:00:00Z', history=[prior])
        signal = next(s for s in json.loads(payload(signals))['signals'] if s['id'] == 'TEMPLATE_MULTI_ADDRESS')
        self.assertEqual(signal['related_evidence'][0]['message_id'], prior['id'])
        self.assertIn(signal['related_evidence'][0]['quote'], prior['text'])

    def test_catalogue_absence_is_weak(self):
        s = detect('Rua Abacaxizeiros Violeta 812, Canoas. Duas pessoas ilhadas')
        unknown = [v for v in s if v['id'] == 'STREET_NOT_IN_CATALOGUE']
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['strength'], 'weak')

    def test_hydro_evidence_and_exact_quotes(self):
        text = 'água no pescoço preciso ajuda'
        conflict = {'quote': 'água no pescoço', 'message_pt': 'retrospective', 'observed_date': '2024-05-06'}
        r = assess(text, hydro_conflict=conflict)
        self.assertEqual(r['verdict'], 'doubtful')
        self.assertTrue(r['signals'][0]['retrospective'])
        self.assertEqual(assess('outro texto', hydro_conflict=conflict)['signals'], [])
        for s in detect('É PEGADINHA, [ENDEREÇO] com 180 pessoas na casinha'):
            self.assertIn(s['quote'], 'É PEGADINHA, [ENDEREÇO] com 180 pessoas na casinha')


if __name__ == '__main__':
    unittest.main()
