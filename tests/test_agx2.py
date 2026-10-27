"""Original AGX2 regressions: evidence, locality scope and safe queue decisions."""
import unittest

from app.dispatch_card import build_card
from app.derive_count import completed_rescue_quote, reconcile_people
from app.geo.incident import IncidentIndex
from test_l1 import street, place
import test_safe1


class AGX2(unittest.TestCase):
    def setUp(self):
        self.helper = test_safe1.Safe1()
        self.helper.roads = [street('Rua Boreal'), street('Rua Aurora'),
                             street('Rua Aurora', 'Porto Alegre')]
        self.helper.landmarks = [place('Jardim Lunar', category='place:suburb'),
                                 {**place('Escola Cometa', osm_id='19'), 'neighbourhood': 'Jardim Lunar'},
                                 place('Santa Maria', category='place:suburb', osm_id='29')]

    def case(self, text):
        return self.helper.case(text)

    def count_case(self, phrase, total):
        text = 'Água entrando na Rua Boreal 62 em Canoas. '+phrase
        case = self.case(text)
        field = case['fields']['people']
        self.assertEqual(field['value'], total)
        self.assertEqual(field['count_basis'], 'derived')
        self.assertIn(field['quote'], text)
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        return case

    def test_sender_and_two_parents(self):
        case = self.count_case('Eu, minha mãe e meu pai aguardamos aqui.', 3)
        self.assertIn('minha mãe e meu pai', case['fields']['people']['quote'])

    def test_sender_and_numbered_children(self):
        self.count_case('Eu e meus 2 filhos precisamos sair.', 3)

    def test_singular_relative(self):
        self.count_case('Estou com minha irmã no andar de cima.', 2)

    def test_parents_are_two_people(self):
        self.count_case('Eu e meus pais aguardamos o barco.', 3)

    def test_remote_reporter_is_excluded_from_count(self):
        case = self.case('Meu irmão e minha mãe estão ilhados na Rua Boreal 62 em Canoas; eu tô em Pelotas.')
        self.assertEqual(case['fields']['people']['value'], 2)

    def test_remote_reporter_with_two_parents(self):
        case = self.case('Meus pais estão presos na Rua Boreal 62 em Canoas. Estou em Cachoeirinha e não posso ir.')
        self.assertEqual(case['fields']['people']['value'], 2)

    def test_water_level_rising_supports_approximate_street(self):
        case = self.case('Eu e meu pai na Rua Boreal em Canoas, água nos joelhos e subindo.')
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertTrue(case['result']['location_approximate'])

    def test_water_rising_over_floor_supports_approximate_street(self):
        case = self.case('Eu e minha mãe na Rua Boreal em Canoas, água pelo piso e subindo rapidamente.')
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')

    def test_third_party_self_exit(self):
        self.assertEqual(self.case('Minha tia já saiu de bote e está com parentes.')['result']['decision'], 'REPORTED_RESCUED')

    def test_whole_group_taken_to_shelter(self):
        self.assertEqual(self.case('O vizinho levou todo mundo pro abrigo, agradecemos muito.')['result']['decision'], 'REPORTED_RESCUED')

    def test_family_total(self):
        self.count_case('Minha família de 5 está ilhada.', 5)

    def test_pronoun_total(self):
        self.count_case('Nós 4 precisamos de um bote.', 4)

    def test_card_explains_derived_count(self):
        case = self.count_case('Eu e minha esposa ficamos presos.', 2)
        card = build_card(case)
        self.assertIn('contagem derivada: 2', card['text_pt'])
        self.assertIn('minha esposa', card['text_pt'])
        self.assertTrue(any(f['path'] == 'fields.people.quote' for f in card['facts_used']))

    def test_plural_relatives_stay_unknown(self):
        case = self.case('Eu e meus filhos estamos ilhados na Rua Boreal 62 em Canoas.')
        self.assertNotIn('people', case['fields'])
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')

    def test_unquantified_family_is_not_a_complete_list(self):
        case = self.case('Eu, meu pai e minha família precisamos sair da Rua Boreal 62 em Canoas.')
        self.assertNotIn('people', case['fields'])
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')

    def test_explicit_total_owns_breakdown(self):
        fields = {}
        reconcile_people(fields, 'Somos 4 pessoas, eu e meus 3 filhos.')
        self.assertEqual(fields['people']['value'], 4)

    def test_rescued_without_adverb(self):
        self.assertEqual(self.case('A família foi retirada pela equipe de bote.')['result']['decision'], 'REPORTED_RESCUED')

    def test_team_already_picked_up(self):
        self.assertEqual(self.case('Os bombeiros já nos buscaram de barco.')['result']['decision'], 'REPORTED_RESCUED')

    def test_shelter_completion(self):
        self.assertEqual(self.case('Estamos no abrigo municipal agora, todos juntos.')['result']['decision'], 'REPORTED_RESCUED')

    def test_portuguese_no_is_a_place_preposition(self):
        self.assertEqual(self.case('Estávamos no mercado e já estamos no abrigo.')['result']['decision'], 'REPORTED_RESCUED')

    def test_prior_place_does_not_negate_group_completion(self):
        self.assertEqual(self.case('Falei no posto mas todos já foram resgatados.')['result']['decision'], 'REPORTED_RESCUED')

    def test_withdrawal_is_reported_unconfirmed(self):
        case = self.case('Pode tirar da lista, nosso pedido foi resolvido.')
        self.assertEqual(case['result']['decision'], 'REPORTED_RESCUED')
        self.assertTrue(case['result']['questions'])

    def test_no_rescue_yet(self):
        for phrase in ('Ainda não fomos resgatados.', 'Os bombeiros ainda não nos buscaram.',
                       'Não estamos no abrigo.', 'Não pode tirar da lista.'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(completed_rescue_quote(phrase))
                self.assertNotEqual(self.case(phrase)['result']['decision'], 'REPORTED_RESCUED')

    def test_conditional_rescue_is_not_completed(self):
        for phrase in ('Se formos resgatados, aviso.', 'Quando estivermos no abrigo, telefono.',
                       'Ainda não estamos resgatados.', 'Quando os bombeiros já nos buscaram?'):
            with self.subTest(phrase=phrase):
                self.assertNotEqual(self.case(phrase)['result']['decision'], 'REPORTED_RESCUED')

    def test_partial_rescue_keeps_remaining_people(self):
        case = self.case('Fomos resgatados, mas minha mãe ainda está presa na Rua Boreal 62 em Canoas.')
        self.assertNotEqual(case['result']['decision'], 'REPORTED_RESCUED')

    def test_rescued_adjective_status(self):
        self.assertEqual(self.case('Já resgatadas, obrigada pela ajuda!')['result']['decision'], 'REPORTED_RESCUED')

    def test_entire_group_rescued_status(self):
        self.assertEqual(self.case('Todas resgatadas pela equipe voluntária, agradecemos.')['result']['decision'], 'REPORTED_RESCUED')

    def test_request_deletion_without_repeating_noun(self):
        self.assertEqual(self.case('Podem apagar, a situação foi resolvida por aqui.')['result']['decision'], 'REPORTED_RESCUED')

    def test_still_on_roof_is_not_withdrawn(self):
        self.assertNotEqual(self.case('Pode tirar da lista? Ainda estamos no telhado sem saída.')['result']['decision'], 'REPORTED_RESCUED')

    def test_arrival_does_not_mean_rescue_complete(self):
        self.assertNotEqual(self.case('Os bombeiros chegaram à rua, esperamos ser resgatados.')['result']['decision'], 'REPORTED_RESCUED')

    def test_water_removed_is_not_people_rescued(self):
        self.assertNotEqual(self.case('A água foi retirada da garagem, minha mãe segue ilhada.')['result']['decision'], 'REPORTED_RESCUED')

    def test_bairro_named_like_another_city(self):
        case = self.case('Socorro na Rua Boreal 62, bairro Santa Maria em Canoas, 2 pessoas ilhadas.')
        self.assertEqual(case['fields']['municipality']['value'], 'Canoas')
        self.assertFalse(case['routing_flags']['out_of_area'])

    def test_gate_is_not_a_city(self):
        case = self.case('2 pessoas presas na Rua Boreal 62 em Canoas, no portão branco.')
        self.assertFalse(case['routing_flags']['out_of_area'])
        self.assertEqual(case['fields']['municipality']['value'], 'Canoas')

    def test_remote_metro_caller(self):
        case = self.case('Minha mãe está presa na Rua Boreal 62 em Canoas; tô em Cachoeirinha e não consigo chegar.')
        self.assertFalse(case['routing_flags']['out_of_area'])

    def test_emotional_remote_caller(self):
        case = self.case('Minha mãe está ilhada na Rua Boreal 62 em Canoas. Eu tô preocupada aqui em Passo Fundo.')
        self.assertFalse(case['routing_flags']['out_of_area'])

    def test_actual_metro_incident_stays_outside(self):
        self.assertEqual(self.case('Duas pessoas presas na Rua Boreal 62 em Cachoeirinha.')['route']['id'], 'out_of_area')

    def test_outside_city_after_address_comma(self):
        self.assertEqual(self.case('Pessoas ilhadas na Rua Aurora 62, Recife, PE.')['route']['id'], 'out_of_area')

    def test_outside_capital_after_address_comma(self):
        self.assertEqual(self.case('Minha mãe precisa de resgate na Rua Aurora 62, Florianópolis, SC.')['route']['id'], 'out_of_area')

    def test_poa_city_alias(self):
        case = self.case('Socorro, nós 4 na Rua Aurora 18 em POA, água subindo.')
        self.assertEqual(case['fields']['municipality']['value'], 'Porto Alegre')
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')

    def test_city_disambiguates_street(self):
        case = self.case('Duas pessoas na Rua Aurora 18 em Canoas, socorro.')
        self.assertNotIn('ambiguous_place', case['fields'])
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')

    def test_bairro_disambiguates_street(self):
        case = self.case('Socorro, duas pessoas na Rua Aurora 18 no Jardim Lunar.')
        self.assertEqual(case['fields']['municipality']['value'], 'Canoas')
        self.assertNotIn('ambiguous_place', case['fields'])

    def test_landmark_disambiguates_street(self):
        case = self.case('Socorro na Rua Aurora 18, perto da Escola Cometa, duas pessoas.')
        self.assertEqual(case['fields']['municipality']['value'], 'Canoas')
        self.assertNotIn('ambiguous_place', case['fields'])

    def test_two_cities_stay_ambiguous(self):
        self.assertEqual(self.case('Pessoas ilhadas na Rua Aurora, sem saber a cidade.')['route']['id'], 'ambiguous_place')

    def test_all_hints_intersect_before_ambiguity(self):
        rows = [street('Rua Aurora', c) for c in ('Canoas', 'Porto Alegre', 'Guaíba')]
        landmarks = [place('Jardim Lunar', c, category='place:suburb', osm_id=str(i))
                     for i, c in enumerate(('Canoas', 'Porto Alegre'))]
        landmarks += [place('Escola Cometa', c, osm_id=str(i+10))
                      for i, c in enumerate(('Canoas', 'Guaíba'))]
        fields = {}
        IncidentIndex(rows, landmarks).resolve(fields, 'Rua Aurora 18 no Jardim Lunar perto da Escola Cometa.')
        self.assertEqual(fields['municipality']['value'], 'Canoas')
        self.assertNotIn('ambiguous_place', fields)


if __name__ == '__main__':
    unittest.main()
