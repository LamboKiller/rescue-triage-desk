"""Textual safety guards for remaining people; independent of model compliance."""
import re
from app.derive_count import _plain

LIFE_SAFETY = re.compile(r'socorro|resgat|ilhado|ilhada|pres[oa]s?\b|telhado|agua (?:ja |esta |ta )?(?:sub|entrou|tomou|no pescoco)|correnteza|sem insulina|oxigenio|nao (?:anda|consegue andar)|precisa.{0,20}(?:sair|tirar)|techo|help|ayuda|agua sube')
ANIMALS = re.compile(r'\b(?:animais|bichos?|cachorros?|gatos?|cuscos?|pets?|caes)\b')
NO_PEOPLE = re.compile(r'\b(?:(?:nao (?:ha|tem)|sem) (?:pessoas|gente)(?=\s*(?:[.;,!]|$|na casa|no local|em risco|aqui|so |apenas ))|(?:so|somente|apenas) (?:os |as )?(?:animais|bichos|cachorros|gatos|cuscos)|(?:ninguem|nenhuma pessoa).{0,20}(?:em risco|na casa|no local))\b')
PARTIAL = re.compile(r'\b(?:restam?\s+(?:\d+|uma?|duas?|dois|tres|quatro|cinco|seis)\s+(?:pessoas?|adultos?|idos[oa]s?|criancas?)|'
                     r'(?:pessoas?|adultos?|idos[oa]s?|criancas?).{0,35}(?:ficaram|ficou).{0,15}(?:para tras|pra tras)|'
                     r'(?:ficamos|fiquei|ficou|ficaram) (?:para tras|pra tras)|nao coube|'
                     r'(?:ele|ela|eles|elas|gente).{0,15}continua[m]? (?:ilhad|pres)|'
                     r'ainda (?:ha|tem|ficaram|restam).{0,25}(?:pessoas|gente|adultos|idosos))')
RESCUED = re.compile(r'\b(?:ja (?:fomos resgatados|resgatad[oa]s?|tiraram todo mundo|foram (?:resgatad[oa]s?|tirados))|'
                     r'(?:bombeiros|voluntarios).{0,20}levaram todas as|conseguiram tirar (?:todo mundo|o pessoal)|'
                     r'(?:a gente|as pessoas) (?:ja )?foi resgatad|as pessoas (?:ja )?foram resgatadas)')
INFO = re.compile(r'\b(?:doa[cç][aã]o|doacoes|doar|doando|entregar|comprar|mantimentos|suprimentos|recebendo|recebem|informam|informacao|horario)\b')


def state(text):
    text = _plain(text)
    partial = bool(PARTIAL.search(text))
    rescued = bool(RESCUED.search(text))
    human_present = bool(re.search(r'\b(?:\d+|uma?|duas?|dois|tres|quatro|cinco|seis)\s+(?:pessoas?|adultos?|idos[oa]s?|criancas?|bebes?)\b|'
                                  r'\b(?:pessoas?|personas?|people|adult[oa]s?|idos[oa]s?|criancas?|bebes?|familias?|senhor[ae]s?|'
                                  r'meu pai|minha mae|minha vo|meu vo|meu irmao|minha irma|eu|nos|estou com|estamos|a gente precisa)\b', text))
    animal_only = bool(NO_PEOPLE.search(text) or (ANIMALS.search(text) and not partial and
                       (not human_present or rescued and re.search(r'ficaram|restaram|apenas|somente|so os|so as', text))))
    # Supply/information conversations can mention rescues in passing. An
    # explicit human danger/request keeps the incident in the live queue.
    human_danger = bool(re.search(r'(?:pessoas?|gente|idos[oa]s?|criancas?|familia|meu pai|minha mae).{0,60}(?:ilh|pres|telhado|precis.{0,15}resgat)|'
                                 r'(?:socorro|preciso de resgate|precisamos de resgate)', text))
    informational = bool(INFO.search(text) and not human_danger and not partial and not rescued)
    return {'partial': partial, 'rescued': rescued and not partial,
            'not_a_rescue': animal_only or informational,
            'life_safety': bool(LIFE_SAFETY.search(text))}


def guard_fields(fields, text):
    status = state(text)
    if status['partial'] or status['not_a_rescue']:
        fields.pop('already_rescued', None)
    elif status['rescued']:
        fields['already_rescued'] = {'value': True, 'quote': text, 'source': 'rule:rescue_state'}
    return status
