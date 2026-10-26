"""Free-text shelter reports -> structured events (deterministic, quote-backed). Used for operator/crew text such as
'abrigo Ginasio X lotado', '40 vagas', 'entregues 5 no abrigo X'. Anything unresolved is returned, never guessed."""
import re
from app.shelters.state import fold

_NUM = r'(\d{1,5})'


def resolve(text_folded, aliases):
    """Longest known alias contained in the text (word-bounded). Returns (shelter_id, alias) or (None, None)."""
    best = None
    for alias, sid in aliases.items():
        if len(alias) >= 3 and re.search(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', text_folded):
            if not best or len(alias) > len(best[1]): best = (sid, alias)
    return best if best else (None, None)


def parse(text, aliases, shelter_id=None):
    """Return {'events':[partial events], 'shelter_id':..., 'unresolved_pt':...}. Events lack actor/at/source (caller adds)."""
    plain = fold(text)
    sid, alias = (shelter_id, None) if shelter_id else resolve(plain, aliases)
    ev = []
    def add(**k): ev.append(k)
    delivered = re.search(r'entreg\w*\s+' + _NUM + r'\b|\b' + _NUM + r'\s+(?:pessoas?\s+)?(?:entreg\w*|deixad\w*|desembarcad\w*)', plain)
    if delivered:
        add(kind='delivered', value=int(delivered[1] or delivered[2]), quote=text[:200])
    if re.search(r'\b(?:lotad[oa]|cheio|sem vagas|superlotad[oa]|nao ha vagas|nao tem vagas|esgotad[oa])\b', plain) and not re.search(r'\bnao (?:esta )?(?:lotad|cheio)', plain):
        add(kind='full', quote=text[:200])
    else:
        vac = re.search(_NUM + r'\s+vagas?\b|\bvagas?\s*[:=]\s*' + _NUM + r'|restam\s+' + _NUM, plain)
        if vac and not delivered: add(kind='vacancies', value=int(next(g for g in vac.groups() if g)), quote=text[:200])
    cap = re.search(r'capacidade(?: total| maxima)?(?: de| para| e|:)?\s*' + _NUM, plain)
    if cap: add(kind='capacity', value=int(cap[1]), quote=text[:200])
    if re.search(r'\b(?:aceita|recebe|tem espaco para) (?:animais|pets?|cachorros?|gatos?)\b', plain): add(kind='attr', attr='animals_ok', value=True, quote=text[:200])
    if re.search(r'\bnao (?:aceita|recebe) (?:animais|pets?|cachorros?|gatos?)\b|\bsem (?:espaco para )?animais\b', plain): add(kind='attr', attr='animals_ok', value=False, quote=text[:200])
    if re.search(r'\b(?:tem|com|ha) (?:posto medico|enfermaria|ambulatorio|medico|equipe de saude|atendimento medico|enfermeir\w+)\b', plain): add(kind='attr', attr='health_support', value=True, quote=text[:200])
    if re.search(r'\b(?:sem|nao tem) (?:posto medico|enfermaria|ambulatorio|medico|equipe de saude|atendimento medico)\b', plain): add(kind='attr', attr='health_support', value=False, quote=text[:200])
    if re.search(r'\bacesso (?:esta |ficou )?(?:alagad\w+|bloquead\w+|cortad\w+|submerso)\b|\brua alagada\b', plain): add(kind='access', value='flooded', quote=text[:200])
    elif re.search(r'\bacesso (?:esta |segue |ficou )?(?:seco|livre|desimpedido)\b', plain): add(kind='access', value='dry', quote=text[:200])
    out = {'events': ev, 'shelter_id': sid, 'alias': alias}
    if ev and not sid: out['unresolved_pt'] = 'Relato com dados de abrigo, mas o abrigo não foi identificado; escolha na lista de abrigos.'
    return out
