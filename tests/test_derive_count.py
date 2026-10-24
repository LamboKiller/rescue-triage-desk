"""Derived people count (Yussef 24/10): sender + listed people, code only, flagged for confirmation."""
import unittest
from app.derive_count import derive_people


class DerivedCount(unittest.TestCase):
    def test_counts_sender_plus_listed(self):
        cases = {
            'socorro estamos dentro da rodoviaria de porto alegre e esta alagando tudo, estou com meus dois bebes': 3,
            'socorrou estou aqui com meu filho na rodoviaria e a agua ta subindo': 2,
            'to sozinha com minha mãe e meu pai na escola': 3,
            'eu e minha vó estamos no segundo andar': 2,
        }
        for text, total in cases.items():
            with self.subTest(text=text):
                d = derive_people(text)
                self.assertEqual(d['value'], total)
                self.assertTrue(d['derived'])
                self.assertIn(d['quote'], text)

    def test_skips_when_unsafe(self):
        for text in (
            'estamos no aeroporto salgado filho, somos 3 com um bebê',   # total written
            'tamo em 3 dentro de casa (tem 1 criança junto)',             # total written
            'eu e meus filhos estamos no telhado',                        # plural without a number
            'Repassando msg de uma guria: tamo com meu filho no HCPA',     # relayed: sender not in the group
            'tem um idoso preso na rua dos andradas',                     # no first person, no relation list
        ):
            with self.subTest(text=text):
                self.assertIsNone(derive_people(text))


if __name__ == '__main__':
    unittest.main()
