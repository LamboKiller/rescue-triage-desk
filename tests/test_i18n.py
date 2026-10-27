"""PT|EN switch of the /v2 desk (I18N). The engine runs under node in a stub DOM: dictionary coverage, templates,
evidence never translated, safety labels exact, persistence. Skipped when node is not installed."""
import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.web import routes_v2

ROOT = Path(__file__).resolve().parents[1]
UI = routes_v2.UI
NODE = shutil.which('node.exe') or shutil.which('node')

HARNESS = r'''
const fs=require('fs'),vm=require('vm');
const UI=process.argv[2], input=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const noop=()=>{}; const el=()=>({append:noop,addEventListener:noop,setAttribute:noop,textContent:''});
const store={};
function make(search){
  const ctx={console,location:{search},localStorage:{getItem:k=>(k in store?store[k]:null),setItem:(k,v)=>{store[k]=String(v)}},URLSearchParams,
   MutationObserver:class{observe(){}disconnect(){}takeRecords(){return []}},NodeFilter:{SHOW_TEXT:4,SHOW_ELEMENT:1},
   document:{readyState:'complete',documentElement:{lang:''},head:el(),body:el(),createElement:el,addEventListener:noop,dispatchEvent:noop,querySelectorAll:()=>[],createTreeWalker:()=>({nextNode:()=>null}),title:''},
   CustomEvent:class{},alert:noop,confirm:noop};
  ctx.window=ctx; vm.createContext(ctx);
  for(const f of ['i18n_en.js','i18n.js']) vm.runInContext(fs.readFileSync(UI+'/'+f,'utf8'),ctx,{filename:f});
  return ctx;
}
const out={};
const c=make('?lang=en'); out.tr=input.phrases.map(p=>c.I18N.tr(p)); out.lang=c.I18N.lang;
const c0=make(''); out.defaultLang=c0.I18N.lang;
delete store['rtd.lang']; const c1=make(''); c1.I18N.set('en'); out.stored=store['rtd.lang']; out.afterSet=c1.I18N.lang;
const c2=make(''); out.reloaded=c2.I18N.lang;
const c3=make('?lang=pt'); out.urlWins=c3.I18N.lang;
c3.I18N.set('pt'); out.t_pt=c3.I18N.t('Recursos'); const c4=make('?lang=en'); out.t_en=c4.I18N.t('Recursos'); out.t_vars=c4.I18N.t('x {n} y',{n:3});
out.patterns=c.I18N_PATTERNS.length; out.dict=Object.keys(c.I18N_EN).length;
console.log(JSON.stringify(out));
'''


def run_node(phrases):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'h.js').write_text(HARNESS, encoding='utf-8')
        (Path(d) / 'in.json').write_text(json.dumps({'phrases': phrases}, ensure_ascii=False), encoding='utf-8')
        p = subprocess.run([NODE, str(Path(d) / 'h.js'), str(UI), str(Path(d) / 'in.json')], capture_output=True, text=True, encoding='utf-8', timeout=60)
    if p.returncode:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


class Static(HTMLParser):
    """Visible text nodes and translatable attributes of index.html (the static chrome)."""
    def __init__(self):
        super().__init__()
        self.strings, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip += 1
        for k, v in attrs:
            if k in ('title', 'aria-label', 'placeholder') and v:
                self.strings.append(v)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.strings.append(data.strip())


PT_HINT = re.compile(r'[áàâãçéêíóôõúü]|\b(de|do|da|para|com|sem|não|em|uma?|por|ou|ao)\b', re.I)


@unittest.skipUnless(NODE, 'Node local não encontrado')
class I18NTests(unittest.TestCase):
    def test_callback_and_supervisor_loop_strings(self):
        phrases = ['Copiar pergunta', 'Abrir no WhatsApp', 'Resposta recebida · em fila para retriagem',
                   'resposta recebida → retriado: CALLBACK → SEND_CANDIDATE',
                   'Encerrados: 4 · Escalados: 2', 'Responsável: operador de retorno · Prazo: 12:30',
                   'Encerra quando: Todos os pedidos citados receberam atendimento ou saíram do achado.', 'escalado']
        expected = ['Copy question', 'Open in WhatsApp', 'Reply received · queued for triage',
                    'reply received → triaged: CALLBACK → SEND_CANDIDATE', 'Closed: 4 · Escalated: 2',
                    'Owner: callback operator · Due: 12:30',
                    'Closes when: All cited requests were addressed or left the finding.', 'escalated']
        self.assertEqual(run_node(phrases)['tr'], expected)

    def test_every_static_chrome_string_has_an_english_equivalent(self):
        parser = Static()
        parser.feed((UI / 'index.html').read_text(encoding='utf-8'))
        strings = sorted({s for s in parser.strings if PT_HINT.search(s)} | {s for s in parser.strings if re.search(r'[A-Za-zÀ-ÿ]{4}', s)})
        r = run_node(strings)
        same = {'Replay', 'Supervisor', 'Evals', 'Red team'}   # identical in both languages
        missing = [s for s, e in zip(strings, r['tr']) if e is None and s not in same and PT_HINT.search(s)]
        self.assertEqual(missing, [], 'index.html strings without EN: %s' % missing)

    def test_every_fleet_reason_sentence_is_translated(self):
        reasons = json.loads((ROOT / 'data' / 'fleet' / 'reasons_pt.json').read_text(encoding='utf-8'))
        phrases = sorted(set(reasons.values()))
        r = run_node(phrases)
        bad = [p for p, e in zip(phrases, r['tr']) if e is None or e == p or re.search(r'[áàâãçéêíóôõúü]', e)]
        self.assertEqual(bad, [])

    def test_safety_labels_have_exact_english_equivalents(self):
        pairs = [('[SIMULADO]', '[SIMULATED]'), ('desconhecido ≠ seco', 'unknown ≠ dry'), ('Dados sintéticos', 'Synthetic data'),
                 ('Aprovação humana', 'Human approval'), ('Sem dado não significa seco', 'No data does not mean dry'),
                 ('Oferta ≠ meio disponível até um operador verificar.', 'Offer ≠ available asset until an operator verifies.'),
                 ('[SIMULADO] vol-64388b0f · Aguardando verificação', '[SIMULATED] vol-64388b0f · Awaiting verification'),
                 ('capacidade desconhecida não é vaga', 'unknown capacity is not a space')]
        r = run_node([p for p, _ in pairs])
        self.assertEqual(r['tr'], [e for _, e in pairs])

    def test_evidence_is_never_translated(self):
        cases = [
            'Água subindo: “agua subindo” (mensagem 1)',
            'bairro Niterói — “bairro Niterói” · regex',
            'Contagem derivada — confirmar: 4 (quem escreve + minha mae, 2 guris). Risco à vida e local aproximado identificado; confirmar o ponto exato em paralelo.',
            'Telhado e água subindo, sem embarcação elegível: solicitar avaliação aérea. [HELI_REQUEST; case:9cfc767, case:9cfc767:water_rising]',
        ]
        free = ['socorro 3 pessoas na Travessa Gambia agua ja entro na casa', 'Rua Voluntários da Pátria · Porto Alegre',
                'Tenho um barco de alumínio com motor 15, cabem 6 pessoas, estou em Canoas no bairro Niterói']
        t = run_node(cases + free)['tr']
        self.assertIn('“agua subindo”', t[0])
        self.assertTrue(t[0].startswith('Water rising'))
        self.assertIn('“bairro Niterói”', t[1])
        self.assertIn('minha mae, 2 guris', t[2])
        self.assertTrue(t[2].startswith('Derived count'))
        self.assertIn('[HELI_REQUEST; case:9cfc767, case:9cfc767:water_rising]', t[3])
        self.assertEqual(t[4:], [None, None, None], 'free text and place names must stay untouched (no translation, no error)')

    def test_templates_capture_numbers_and_places(self):
        rows = [
            ('Sem atualização há 38,8 h · ainda estão no local?', 'No update for 38.8 h · still at the location?'),
            ('4 pessoas · crianças — · idosos —', '4 people · children — · elderly —'),
            ('Fila médica (3)', 'Medical queue (3)'),
            ('3 abrigo(s) não oferecidos', '3 shelter(s) not offered'),
            ('Distância em linha reta 14.7 km (rota não verificada).', 'Straight-line distance 14.7 km (route not verified).'),
            ('Pergunta principal (1 de 2)', 'Main question (1 of 2)'),
            ('REVISAR: sem rota terrestre seca até Abrigo Canoas, -29.883/-51.176.', 'REVIEW: no dry land route to Shelter Canoas, -29.883/-51.176.'),
            ('322 propostas de red-team aguardam revisão humana (menu Mais → Red team).', '322 red-team proposals await human review (More menu → Red team).'),
            ('Calado padrão estimado: 0,4 m; confirmar na unidade.', 'Estimated standard draft: 0.4 m; confirm on the unit.'),
        ]
        self.assertEqual(run_node([a for a, _ in rows])['tr'], [b for _, b in rows])

    def test_unknown_strings_stay_portuguese_without_error(self):
        self.assertEqual(run_node(['Frase totalmente desconhecida do servidor que ninguém traduziu', ''])['tr'], [None, None])

    def test_default_pt_url_param_and_persistence(self):
        r = run_node(['Recursos'])
        self.assertEqual(r['lang'], 'en')
        self.assertEqual(r['defaultLang'], 'pt')
        self.assertEqual((r['stored'], r['afterSet']), ('en', 'en'))
        self.assertEqual(r['reloaded'], 'en')
        self.assertEqual(r['urlWins'], 'pt')
        self.assertEqual((r['t_pt'], r['t_en'], r['t_vars']), ('Recursos', 'Resources', 'x 3 y'))
        self.assertGreater(r['dict'], 400)
        self.assertGreater(r['patterns'], 50)

    def test_html_wiring_and_assets_served(self):
        html = (UI / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="lang-toggle"', html)
        self.assertLess(html.index('/v2/i18n_en.js'), html.index('/v2/i18n.js'))
        self.assertLess(html.index('/v2/i18n.js'), html.index('/v2/app.js'))
        self.assertIn('data-lang="pt"', html)
        self.assertIn('data-lang="en"', html)

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                u = urlsplit(self.path)
                if not routes_v2.handle_get(self, u.path, parse_qs(u.query)):
                    self.send_error(404)

            def log_message(self, *a):
                pass
        srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            for name in ('i18n.js', 'i18n_en.js'):
                c = http.client.HTTPConnection('127.0.0.1', srv.server_port, timeout=10)
                c.request('GET', '/v2/' + name)
                resp = c.getresponse()
                body = resp.read()
                c.close()
                self.assertEqual(resp.status, 200, name)
                self.assertIn('javascript', resp.getheader('Content-Type'))
                self.assertGreater(len(body), 1000)
        finally:
            srv.shutdown()
            srv.server_close()
            th.join()

    def test_engine_skips_evidence_containers_and_has_debug_helper(self):
        src = (UI / 'i18n.js').read_text(encoding='utf-8')
        for sel in ('.message', '.quote', 'pre', 'textarea', '[data-evidence]'):
            self.assertIn(sel, src)
        self.assertIn('i18n_debug', src)


if __name__ == '__main__':
    unittest.main()
