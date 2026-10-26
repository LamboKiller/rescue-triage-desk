"""Deterministic pre-check: is this message a volunteer OFFER of a vehicle, a rescue request, or neither?

Rescue always wins: a message that asks for help (or reports people in danger) is never an offer, even if it
mentions a boat. Text is matched on an accent-folded copy of identical length so spans map to the original text.
"""
import re
import unicodedata
from app.derive_count import INJECTION

TYPE_PATTERNS = (  # first match wins; value = app.fleet.assets type enum
    ('bote_inflavel', r'\b(?:bote|barco|lancha)\s+inflavel\b|\binflavel\b|\bzodiac\b'),
    ('jet_ski', r'\bjet\s*-?\s*skis?\b|\bmoto\s+aquatica\b'),
    ('barco_aluminio', r'\b(?:barco|bote|lancha|barca|embarcacao)\s+(?:de\s+)?aluminio\b|\baluminio\b'),
    ('anfibio', r'\banfibi\w+'),
    ('helicoptero', r'\bhelicopter\w*'),
    ('ambulancia', r'\bambulancia\b'),
    ('caminhao_alto', r'\bcaminhao\b'),
)
GENERIC_VEHICLE = r'\b(?:barco|barcos|bote|lancha|barca|barquinho|canoa|caiaque|catamara|veleiro|embarcacao|balsa|traineira|' \
                  r'caminhonete|trator|jipe|4x4|gaiola|vehiculo|veiculo)\b'
VEHICLE = re.compile(GENERIC_VEHICLE+'|'+'|'.join(p for _, p in TYPE_PATTERNS))
OFFER_CUE = re.compile(r'\b(?:tenho|temos|possuo|possuimos|disponibilizo|disponibilizamos|ofereco|oferecemos|empresto|emprestamos|'
                       r'cedo|cedemos|coloco|colocamos|posso|podemos|dou|doo)\b|a disposicao|\bquem precisar\b|\bse precisarem\b|'
                       r'\bse (?:alguem )?precisar\b|\bdisponivel\b|\bdisponiveis\b')
HELP_CUE = re.compile(r'\bposso ajudar\b|\bpodemos ajudar\b|\bquero ajudar\b|\bvoluntari[oa]\b')
# First-person need / danger. Intentionally excludes "resgatar pessoas" (an offer) but includes "me resgatem".
RESCUE_CUE = re.compile(r'\b(?:preciso|precisamos|necessito|necessitamos|socorro|urgente)\b|\bnos\s+(?:resgat|ajud|tir|busqu)\w*|'
                        r'\bme\s+(?:resgat|ajud|tir|busqu)\w*|\b(?:estou|estamos|ficamos|estao|esta)\s+(?:preso|presa|presos|presas|ilhad\w+|'
                        r'cercad\w+|sem comida|sem agua|no telhado|na laje|ilhados)\b|\bagua\s+(?:entrou|esta subindo|subindo)\b|'
                        r'\b(?:afundou|virou|naufrag\w+|perdi (?:o|meu) barco|barco (?:quebrou|furou))\b|\bpede?m? (?:resgate|socorro)\b|'
                        r'\bresgate\s+(?:urgente|imediato)\b|\bno\s+telhado\b|'
                        r'\bagua\s+(?:ja\s+)?(?:na|ate\s+(?:a|o)|no|tava|estava|entrando|entrou)\b|\bentrando\s+na\s+casa\b|'
                        r'\bsem\s+(?:sinal|gasolina|combustivel|luz|bateria|comida|remedio)\b|\bbateria\s+\d+|\bdesesper\w+|'
                        r'\bpelo\s+amor\s+de\s+deus\b|\bnao\s+voltou\b|\bsem\s+resposta\b|\bnao\s+(?:consigo|consegui)\s+(?:falar|contato)|'
                        r'\b(?:alguem|quem)\s+(?:com|que\s+(?:tenha|tiver|possa)|tiver|tenha)\s+(?:\w+\s+){0,2}(?:barco|bote|lancha|jet|embarcacao)|'
                        r'\bmand\w+\s+(?:alguem|ajuda|um barco|barco)\b|\b(?:venham|venha)\b|'
                        r'\bprecis\w+\s+(?:de\s+)?(?:um\s+|uma\s+)?(?:barco|bote|lancha|ajuda|resgate)\b|'
                        r'\b(?:perdemos|perdi)\b|\bsozinh[oa]s?\b')
# Purpose clauses of an offer ("posso buscar pessoas ilhadas") must not read as a rescue request.
PURPOSE = re.compile(r'\b(?:buscar|resgatar|salvar|socorrer|tirar|ajudar|levar|atender|auxiliar|transportar|prestar socorro a?)\s+'
                     r'(?:as\s+|os\s+|a\s+)?(?:\w+\s+){0,2}(?:pessoas|gente|familias|moradores|ilhad\w+|presos|vitimas|quem)\b[^.;!?\n]*')
THIRD_PARTY = re.compile(r'\b(?:gente|pessoas|familia|idosos?|criancas?|bebes?|vizinhos?|mae|pai|filhos?)\b(?:\s+\w+){0,4}\s+'
                         r'(?:ilhad\w+|pres[oa]s?|no telhado|na laje|sem comida|isolad\w+)\b')
OWNERSHIP_DETAIL = re.compile(r'\b(?:lugares|vagas|cabe|cabem|capacidade|motor|hp|disponivel|disposicao|aluminio|inflavel)\b')
OWNERSHIP = re.compile(r'\b(?:meu|minha|nosso|nossa)\s+(?:\w+\s+){0,2}(?:' + GENERIC_VEHICLE[2:-2] + r'|jet\s*-?\s*ski|inflavel)\b')
NEGATED_OFFER = re.compile(r'\b(?:nao|nunca)\s+(?:tenho|temos|posso|podemos)\b|\bquem\s+tem\b|\balguem\s+(?:tem|possui)\b|\bprocuro\b')


def fold(text):
    """Lower-case, accent-free copy with the SAME length as `text` (falls back to plain lower)."""
    out = ''.join((unicodedata.normalize('NFD', c.lower()) or c)[0] for c in text)
    return out if len(out) == len(text) else text.lower()


def vehicle(text, folded=None):
    """-> (type enum or 'desconhecido', exact quote) for the first vehicle mention, or None."""
    f = folded or fold(text)
    for kind, pattern in TYPE_PATTERNS:
        m = re.search(pattern, f)
        if m:
            return kind, text[m.start():m.end()]
    m = re.search(GENERIC_VEHICLE, f)
    return ('desconhecido', text[m.start():m.end()]) if m else None


def classify(text):
    """-> {'kind': 'offer'|'rescue'|'info'|'other', ...}. Pure, offline, no hindsight."""
    text = text if isinstance(text, str) else ''
    f = fold(text)
    v = vehicle(text, f)
    needs = PURPOSE.sub(' ', f)
    rescue = RESCUE_CUE.search(needs) or THIRD_PARTY.search(needs)
    base = {'vehicle': v, 'injection': bool(INJECTION.search(text))}
    if base['injection']:
        return {**base, 'kind': 'other', 'reason': 'instrução suspeita no texto'}
    if rescue:
        return {**base, 'kind': 'rescue', 'reason': 'pedido de socorro ou pessoas em risco no texto'}
    if v and (OFFER_CUE.search(f) or OWNERSHIP.search(f) and OWNERSHIP_DETAIL.search(f)) and not NEGATED_OFFER.search(f):
        return {**base, 'kind': 'offer', 'reason': 'veículo oferecido na primeira pessoa'}
    if HELP_CUE.search(f):
        return {**base, 'kind': 'info', 'reason': 'oferta de ajuda sem veículo'}
    return {**base, 'kind': 'other', 'reason': 'sem oferta de veículo'}


def is_offer(text):
    """Single guard used by the routing hook."""
    return classify(text)['kind'] == 'offer'
