"""Instant, deterministic pre-triage for the intake queue (no model, no I/O, <50 ms).

Purpose: order WAITING messages and show an honest provisional card. It never
decides, never dispatches and never hides a message. The agent pipeline result
replaces the provisional card. Unknown is not safe: an empty text still gets
a visible, low-confidence card.
"""
import hashlib
import re
import unicodedata

# (label shown to the operator, points, regex over accent-folded lower-case text)
LIFE_RISK = (
    ('Afogamento / pessoa na água', 40, r'afog|se afogando|boiando|arrastad|correnteza'),
    ('Parada/queda de respiração ou inconsciência', 40, r'sem respirar|parou de respirar|desmai|inconscient|convuls|infarto|avc\b|sangrando muito|hemorrag'),
    ('Oxigênio / aparelho de vida', 35, r'oxigenio|respirador|concentrador|cilindro|insulina|dialise|hemodialise|sonda|traqueo|bomba de'),
    ('Risco estrutural', 35, r'desab|desmoron|rachadura|parede (caindo|cedendo)|casa (caindo|cedendo)|teto (caindo|cedendo)'),
    ('Água subindo', 25, r'agua (esta |ta |foi )?(subindo|chegando|aumentando|na cintura|no peito|no pescoco)|nivel (da agua )?(subindo|aumentando)|subindo rapido|enchendo'),
    ('Telhado / laje / forro', 20, r'telhado|laje|forro|sotao|cima do (telhado|muro)|no alto'),
    ('Acamado / não anda', 20, r'acamad|cadeirante|cadeira de rodas|maca\b|nao (anda|consegue andar|consegue sair)|paralis|deficiente|acamada'),
    ('Bebê / gestante', 20, r'\bbebe|recem.?nascid|neonato|gestante|gravida|gravidez|trabalho de parto|amament'),
    ('Ferimento / urgência médica', 25, r'ferid|machucad|fratura|quebrou|febre alta|falta de ar|dor no peito|remedio|medicacao|diabet'),
    ('Eletricidade com água', 15, r'choque|eletrocut|fio (caido|solto)|energia ligada'),
)
VULNERABLE = (
    ('Criança(s)', 10, r'crianca|criancas|filh[oa]s?\b|menin[oa]s?\b|\bnenem'),
    ('Idoso(a)(s)', 10, r'idos[oa]s?\b|\bvov[oó]|\bavo\b|\bavos\b|velhinh|\b[78-9]\d anos'),
    ('Ilhado / sem saída', 8, r'ilhad|cercad|\bpreso|\bpresa|\bpresos|sem saida|sem como sair|isolad'),
    ('Pedido de socorro', 5, r'socorro|urgente|urgencia|pelo amor de deus|desesper|ajuda ja|por favor'),
)
LOWERING = (
    ('Informa que já foi resgatado', -30, r'ja (foram|fomos|foi) (resgatad|salv|retirad)|todos (resgatad|salvos|a salvo)|ja estamos a salvo|ja resgataram|nao precisa mais'),
    ('Oferta de ajuda / informe (não é pedido)', -15, r'ofereco (meu |um )?(barco|ajuda|carro)|sou voluntari|posso ajudar|distribuicao|doacao|doacoes|nao estou pedindo|ninguem pedindo|aviso do grupo'),
)
INJECTION = re.compile(r'ignor[ea] (todas |as )?(instru|ordens|regras)|ignore (all |previous|the above)|system prompt|desconsidere (as )?(regras|instru)|marque send|sem verificar', re.I)
STREET = re.compile(r'\b(rua|r\.|av\.?|avenida|travessa|tv\.|estrada|rodovia|alameda|beco|servidao|rod\.)\s+[a-z0-9]{2,}')
NUMBER = re.compile(r'\b(n[o]?\.?\s*\d{1,5}|numero\s+\d{1,5}|,\s*\d{1,5}\b|\bn\s*\d{1,5}\b)')
LANDMARK = re.compile(r'\b(ponte|escola|posto|mercado|igreja|hospital|ginasio|praca|esquina|quadra|terminal|rodoviaria|ubs|upa|ctg|condominio|cruzamento)\b')
BAIRRO = re.compile(r'\b(bairro|vila|jardim|loteamento|distrito|centro)\s+[a-z]{3,}')
PEOPLE = re.compile(r'\b(\d{1,3})\s+(pessoas|moradores|familias|adultos|criancas|idosos)\b')

_COMPILED = {}


def fold(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', text.casefold()).strip()


def text_hash(text):
    """Stable key for exact reposts: accent/case/punctuation/whitespace-insensitive."""
    return hashlib.sha256(re.sub(r'[^a-z0-9]+', ' ', fold(text)).strip().encode()).hexdigest()


def _rx(pattern):
    if pattern not in _COMPILED:
        _COMPILED[pattern] = re.compile(pattern)
    return _COMPILED[pattern]


def location_strength(folded):
    """0 none … 4 street + number + landmark/bairro. A hint for ordering only."""
    points = 0
    points += 2 if STREET.search(folded) else 0
    points += 1 if NUMBER.search(folded) else 0
    points += 1 if (LANDMARK.search(folded) or BAIRRO.search(folded)) else 0
    return min(4, points)


def pretriage(text):
    """-> provisional priority. Pure function of the text."""
    folded = fold(text)
    reasons, score = [], 0
    for table in (LIFE_RISK, VULNERABLE, LOWERING):
        for label, points, pattern in table:
            if _rx(pattern).search(folded):
                reasons.append({'reason_pt': label, 'points': points})
                score += points
    people = max([int(m.group(1)) for m in PEOPLE.finditer(folded)] or [0])
    if people:
        extra = min(15, people)
        reasons.append({'reason_pt': f'{people} pessoas citadas (limite 15)', 'points': extra})
        score += extra
    strength = location_strength(folded)
    if strength:
        reasons.append({'reason_pt': f'Localização citada: {("fraca", "fraca", "média", "boa", "forte")[strength]}', 'points': min(8, 2 * strength)})
        score += min(8, 2 * strength)
    injection = bool(INJECTION.search(str(text or '')))
    if injection:
        reasons.append({'reason_pt': 'Texto tenta dar ordens ao sistema; só revisão humana', 'points': -20})
        score -= 20
    if not folded:
        reasons.append({'reason_pt': 'Mensagem vazia; revisar', 'points': 0})
    score = max(0, min(100, score))
    level = 'P1' if score >= 40 else 'P2' if score >= 20 else 'P3'
    life = any(r['points'] >= 20 and r['reason_pt'] in {x[0] for x in LIFE_RISK} for r in reasons)
    return {
        'score': score, 'level': level, 'provisional': True, 'life_risk': life, 'injection': injection,
        'location_strength': strength, 'reasons': reasons, 'dispatch': False,
        'basis_pt': 'Pré-triagem por palavras-chave (sem agentes); não decide nem despacha.',
    }
