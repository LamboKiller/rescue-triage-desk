"""Deterministic credibility signals. Code finds and quotes evidence; nothing here discards a message.

Strong signals (can support "likely_fake"): template spam across addresses, copy-paste placeholders,
impossible head-counts, explicit hoax/test markers. Weak signals only make a message "doubtful": street unknown to
every catalogue city, life-safety claim at a retrospective-dry point, laughter-only/scam wording.
A genuine message that is merely messy (typos, no punctuation, caps, missing street) triggers nothing.
"""
import csv
import difflib
import re
from datetime import datetime, timezone
from functools import lru_cache
from app.config import ROOT
from app.geo.hydro import fold1, key
from app.geo.streets import normalize as street_norm

STRONG, WEAK = 'strong', 'weak'
FAMILY = {'TEMPLATE_MULTI_ADDRESS': 'history', 'PLACEHOLDER_TEMPLATE': 'template', 'IMPOSSIBLE_HEADCOUNT': 'plausibility',
          'TROLL_MARKER': 'markers', 'STREET_NOT_IN_CATALOGUE': 'catalogue', 'HYDRO_DRY_LIFE_SAFETY': 'geo',
          'TROLL_SOFT': 'markers', 'SCAM_MARKER': 'markers'}
LABEL = {'TEMPLATE_MULTI_ADDRESS': 'mesmo texto em 24 h citando endereços/cidades diferentes',
         'PLACEHOLDER_TEMPLATE': 'modelo copiado com campo não preenchido',
         'IMPOSSIBLE_HEADCOUNT': 'número de pessoas impossível para uma casa',
         'TROLL_MARKER': 'marcador explícito de trote/teste',
         'STREET_NOT_IN_CATALOGUE': 'rua não existe em nenhuma cidade do catálogo, mensagem específica',
         'HYDRO_DRY_LIFE_SAFETY': 'risco de vida em ponto fora da área alagada observada (camada retrospectiva)',
         'TROLL_SOFT': 'risos/marcadores de brincadeira', 'SCAM_MARKER': 'pedido de dinheiro/link em pedido de resgate'}
STRENGTH = {k: (WEAK if k in ('STREET_NOT_IN_CATALOGUE', 'HYDRO_DRY_LIFE_SAFETY', 'TROLL_SOFT', 'SCAM_MARKER') else STRONG) for k in FAMILY}

STREET = re.compile(r"\b(?P<type>rua|r|avenida|av|travessa|tv|estrada|alameda|beco|rodovia|largo)\.?\s+"
                    r"(?P<name>[^\W\d_][\w'’-]*(?:\s+[^\W\d_][\w'’-]*){0,5})(?:[\s,]*(?:n[ºo°.]*\s*|numero\s*)?(?P<num>\d{1,5})\b)?", re.I)
STOP_WORDS = {'em', 'no', 'na', 'nos', 'nas', 'onde', 'preciso', 'precisamos', 'urgente', 'socorro', 'estamos', 'estou', 'pessoas', 'perto',
              'proximo', 'aqui', 'agua', 'casa', 'ajuda', 'por', 'favor', 'ha', 'ta', 'esta', 'tem', 'com', 'sem', 'que', 'e', 'mas', 'ilhados',
              'ilhadas', 'presos', 'bairro', 'cidade', 'apto', 'apartamento', 'fundos', 'frente', 'preciso', 'precisa', 'resgate', 'barco', 'bote'}
PLACEHOLDER = re.compile(
    r"(\[\s*(?:rua|endereco|endere\u00e7o|nome|cidade|bairro|local|numero|n\u00famero|x+|insira|inserir|preencher)[^\]]*\]|"
    r"<\s*(?:rua|endereco|endere\u00e7o|nome|cidade|bairro|local|numero)[^>]*>|\{\{?[^}]{1,30}\}\}?|"
    r"\b(?:nome|endereco|cidade|bairro|rua)\s+(?:aqui|da\s+rua|do\s+bairro|da\s+cidade|completo)\b|"
    r"\b(?:inserir|colocar|preencher|escreva)\s+(?:o\s+|a\s+)?(?:endereco|nome|cidade|bairro)\b|"
    r"\bfulano\s+de\s+tal\b|\bxxx+\b|\brua\s+x\b|\b(?:copie|cole)\s+(?:e\s+cole\s+)?(?:esta|essa|a)\s+mensagem\b|\blorem\s+ipsum\b)", re.I)
DWELLING = re.compile(r"\b(casa|casinha|apartamento|apto|ap|sobrado|kitnet|quarto|barraco|residencia|telhado)\b")
COLLECTIVE = re.compile(r"\b(predio|condominio|bairro|vila|comunidade|abrigo|escola|ginasio|igreja|ilha|quadra|hospital|asilo|lar|creche|empresa|"
                        r"fabrica|cooperativa|clube|centro|rua|ruas|regiao|cidade|favela|loteamento|ocupacao|presidio|penitenciaria|shopping)\b")
WORDNUM = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5,
           'seis': 6, 'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12,
           'treze': 13, 'catorze': 14, 'quatorze': 14, 'quinze': 15, 'dezesseis': 16,
           'dezessete': 17, 'dezoito': 18, 'dezenove': 19, 'vinte': 20, 'trinta': 30,
           'quarenta': 40, 'cinquenta': 50, 'sessenta': 60, 'setenta': 70, 'oitenta': 80,
           'noventa': 90, 'cem': 100, 'cento': 100, 'mil': 1000}
for _word, _value in (('duzent', 200), ('trezent', 300), ('quatrocent', 400), ('quinhent', 500),
                      ('seiscent', 600), ('setecent', 700), ('oitocent', 800), ('novecent', 900)):
    WORDNUM[_word + 'os'] = WORDNUM[_word + 'as'] = _value
_NUMBER_WORD = '(?:' + '|'.join(WORDNUM) + ')'
COUNT = re.compile(r'\b(\d{2,9}|' + _NUMBER_WORD + r'(?:\s+e\s+' + _NUMBER_WORD + r'){0,3})'
                   r'\s+(?:pessoas|adultos|criancas|idosos|moradores|familiares|gente)\b')
TROLL = re.compile(r"\b(trote|pegadinha|zoeira|so\s+testando|teste\s+teste|testando\s+(?:o\s+)?(?:sistema|bot|aplicativo)|brincadeira|e\s+mentira|mensagem\s+falsa)\b")
NEGATED = re.compile(r"\b(nao|nem|sem|nunca)\s+(?:(?:e|eh|era|foi|estou|estamos|estamos so|estou so)\s+)?"
                     r"(?:(?:nenhum|nenhuma|um|uma|so)\s+)?$")
SOFT = re.compile(r"\b(?:k{5,}|(?:rs){4,}|(?:ha){4,}|(?:kk\s*){3,})\b")
SCAM = re.compile(r"(chave\s+pix|mand(?:e|ar)\s+(?:um\s+)?pix|faca\s+um\s+pix|transfira|deposite|r\$\s*\d+[^.]{0,30}(?:para|pra)\s+(?:eu\s+)?(?:conseguir|liberar)|clique\s+no\s+link|link\s+na\s+bio|https?://)", re.I)


@lru_cache(maxsize=1)
def municipalities():
    with (ROOT / 'data/rs_municipios.csv').open(encoding='utf-8-sig', newline='') as f:
        names = [r['name'] for r in csv.DictReader(f)]
    return sorted(((key(n), n) for n in names), key=lambda t: -len(t[0]))


@lru_cache(maxsize=1)
def catalogue():
    """(street keys, covered city keys, keys by first letter) from data/streets_flood.csv."""
    keys, cities = set(), set()
    with (ROOT / 'data/streets_flood.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            keys.add(street_norm(r['display_name']))
            cities.add(key(r['municipality']))
    by_first = {}
    for k in keys:
        by_first.setdefault(k[:1], []).append(k)
    return keys, cities, by_first


def city_mentions(text):
    t = ' ' + key(text) + ' '
    return [n for k, n in municipalities() if ' ' + k + ' ' in t]


def addresses(text):
    """[(street words, number or None, quote)] from explicit 'Rua X 123'-style spans."""
    found = []
    for m in STREET.finditer(text or ''):
        words = []
        for w in m.group('name').split():
            if fold1(w) in STOP_WORDS:
                break
            words.append(w)
        if not words:
            continue
        num = m.group('num') if len(words) == len(m.group('name').split()) else None
        found.append((' '.join(words), num, m.group(0)))
    return found


def street_known(name_words):
    """Lenient catalogue test: longest word-prefix exact, else fuzzy >= .86 on the full phrase."""
    keys, _, by_first = catalogue()
    words = name_words.split()
    for n in range(len(words), 0, -1):
        k = street_norm('rua ' + ' '.join(words[:n]))
        if k in keys and (n > 1 or len(words[0]) >= 4):
            return True
    k = street_norm('rua ' + name_words)
    pool = [c for c in by_first.get(k[:1], []) if abs(len(c) - len(k)) <= 4]
    return bool(difflib.get_close_matches(k, pool, n=1, cutoff=0.86))


def place_of(text):
    addrs = addresses(text)
    cities = city_mentions(text)
    a = addrs[0] if addrs else None
    return {'street': street_norm('rua ' + a[0]) if a else '', 'number': a[1] if a else '', 'city': key(cities[0]) if cities else ''}


def _differ(p, q):
    for f in ('street', 'number', 'city'):
        if p[f] and q[f] and p[f] != q[f]:
            return True
    return False


def masked_tokens(text):
    t = fold1(text)
    for m in STREET.finditer(text or ''):
        t = t[:m.start()] + ' ' * (m.end() - m.start()) + t[m.end():]
    k = ' ' + re.sub(r'[^a-z0-9]+', ' ', t) + ' '
    for ck, _ in municipalities():
        k = k.replace(' ' + ck + ' ', ' ')
    return {w for w in re.sub(r'\d+', ' ', k).split() if len(w) > 1}


def _when(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sig(sid, quote, detail, **extra):
    return {'id': sid, 'strength': STRENGTH[sid], 'family': FAMILY[sid], 'label_pt': LABEL[sid], 'quote': (quote or '')[:200],
            'detail': detail, **extra}


def detect(text, *, time=None, history=(), hydro_conflict=None):
    """Return the list of signal dicts for one message. `history` = [{'id','text','time'}] of earlier messages."""
    text = text or ''
    f = fold1(text)
    signals = []
    # 1. same/near-same text claiming >= 2 different addresses/cities within 24 h
    mine = masked_tokens(text)
    now = _when(time)
    if len(mine) >= 8:
        group = [place_of(text)]
        ids = []
        evidence = []
        for h in history:
            then = _when(h.get('time'))
            if not now or not then or not 0 <= (now - then).total_seconds() <= 86400:
                continue
            theirs = masked_tokens(h.get('text', ''))
            if len(theirs) >= 8 and len(mine & theirs) / len(mine | theirs) >= 0.8:
                group.append(place_of(h.get('text', '')))
                ids.append(h.get('id'))
                if len(evidence) < 10:
                    evidence.append({'message_id': h.get('id'), 'quote': h.get('text', '')[:200],
                                     'time': h.get('time'), 'place': group[-1]})
        clusters = []
        for p in group:
            if not (p['street'] or p['city']):
                continue
            if not any(not _differ(p, c) for c in clusters):
                clusters.append(p)
        if ids and len(clusters) >= 2 and sum(1 for p in group if p['street'] or p['city']) >= 2:
            signals.append(_sig('TEMPLATE_MULTI_ADDRESS', text[:160], '%d textos quase iguais em 24 h, %d locais diferentes' % (len(group), len(clusters)),
                                other_message_ids=ids[:10], distinct_places=len(clusters), related_evidence=evidence))
    # 2. placeholders
    m = PLACEHOLDER.search(f)
    if m and not re.search(r'\b(?:nao sei|desconheco|sem saber)\b', f[max(0, m.start()-25):m.start()]):
        signals.append(_sig('PLACEHOLDER_TEMPLATE', text[m.start():m.end()], 'campo de modelo não preenchido'))
    # 3. impossible head-count: >= 100 people in a single dwelling
    for sentence in re.split(r'[.!?\n]+', f):
        mc = COUNT.search(sentence)
        if not mc:
            continue
        window = sentence[max(0, mc.start() - 45):mc.end() + 45]
        if not DWELLING.search(window) or COLLECTIVE.search(window):
            continue
        raw = mc.group(1)
        n = int(raw) if raw.isdigit() else sum(WORDNUM[w] for w in raw.split() if w != 'e')
        if n >= 100:
            start = f.find(sentence)
            signals.append(_sig('IMPOSSIBLE_HEADCOUNT', text[start + mc.start():start + mc.end()], '%d pessoas em uma residência' % n))
            break
    # 4. explicit hoax/test markers (negation-protected: "não é trote")
    for mt in TROLL.finditer(f):
        if not NEGATED.search(f[max(0, mt.start() - 40):mt.start()]):
            signals.append(_sig('TROLL_MARKER', text[mt.start():mt.end()], 'declara trote/teste'))
            break
    ms = SOFT.search(f)
    if ms and not any(s['id'] == 'TROLL_MARKER' for s in signals):
        signals.append(_sig('TROLL_SOFT', text[ms.start():ms.end()], 'risada repetida'))
    mx = SCAM.search(text)
    if mx:
        signals.append(_sig('SCAM_MARKER', mx.group(0), 'dinheiro/link'))
    # 5. street unknown to every catalogue city while the message is otherwise specific (street + number + covered city)
    _, covered, _ = catalogue()
    cities = [c for c in city_mentions(text) if key(c) in covered]
    for name, num, quote in addresses(text):
        if num and cities and not street_known(name):
            signals.append(_sig('STREET_NOT_IN_CATALOGUE', quote, '"%s" não encontrada em nenhuma cidade do catálogo' % name))
            break
    # 6. life-safety claim at a point confidently dry (from app.geo.hydro.hydro_conflict; retrospective => weak)
    if hydro_conflict and hydro_conflict.get('quote') and hydro_conflict['quote'] in text:
        signals.append(_sig('HYDRO_DRY_LIFE_SAFETY', hydro_conflict.get('quote'), hydro_conflict.get('message_pt', ''),
                            observed_date=hydro_conflict.get('observed_date'), retrospective=True))
    return signals
