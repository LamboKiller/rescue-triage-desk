"""Textual safety guards for remaining people; independent of model compliance."""
import re
from app.derive_count import _plain, completed_rescue_quote, written_total

LIFE_SAFETY = re.compile(r'socorro|resgat|ilhado|ilhada|pres[oa]s?\b|telhado|agua (?:ja |esta |ta )?(?:sub|entrou|tomou|no pescoco)|agua (?:na|no|nos|nas|pelo|pela|ate)\b[^.;!\n]{0,30}\be subindo\b|correnteza|sem insulina|oxigenio|nao (?:anda|consegue andar)|precisa.{0,20}(?:sair|tirar)|techo|help|ayuda|agua sube')
ANIMALS = re.compile(r'\b(?:animais|bichos?|cachorros?|gatos?|cuscos?|pets?|caes|cavalos?|vacas?|bois|porcos?|ovelhas?|galinhas?)\b')
PEOPLE_OUT = re.compile(r'\b(?:ele|ela|eles|elas|todos|as pessoas(?: da casa)?|a familia|o pessoal)\s+(?:mesm[oa]s?\s+)?ja\s+(?:saiu|sairam|foi embora|foram embora)\b')
NO_PEOPLE = re.compile(r'\b(?:(?:nao (?:ha|tem)|sem) (?:pessoas|gente)(?=\s*(?:[.;,!]|$|na casa|no local|em risco|aqui|so |apenas ))|(?:so|somente|apenas) (?:os |as )?(?:animais|bichos|cachorros|gatos|cuscos)|(?:ninguem|nenhuma pessoa).{0,20}(?:em risco|na casa|no local))\b')
PARTIAL = re.compile(r'\b(?:(?:mas|porem)\s+(?:ficou|ficaram|restou|restaram)\s+(?:(?:meus?|minhas?)\s+(?:filh[oa]s?|mae|pai|irm[ao]s?|avos?|net[oa]s?)|(?:o|a)\s+(?:seu|dona|senhor|senhora)\s+\w+|(?:\d+|uma?|duas?|dois|tres)\s+(?:pessoas?|criancas?|idos[oa]s?))\b|restam?\s+(?:\d+|uma?|duas?|dois|tres|quatro|cinco|seis)\s+(?:pessoas?|adultos?|idos[oa]s?|criancas?)|'
                     r'(?:pessoas?|adultos?|idos[oa]s?|criancas?).{0,35}(?:ficaram|ficou).{0,15}(?:para tras|pra tras)|'
                     r'(?:ficamos|fiquei|ficou|ficaram) (?:para tras|pra tras)|nao coube|'
                     r'(?:ele|ela|eles|elas|gente).{0,15}continua[m]? (?:ilhad|pres)|'
                     r'ainda (?:ha|tem|ficaram|restam).{0,25}(?:pessoas|gente|adultos|idosos))')
RESCUED = re.compile(r'\b(?:ja (?:fomos resgatados|resgatad[oa]s?|tiraram todo mundo|foram (?:resgatad[oa]s?|tirados))|'
                     r'(?:bombeiros|voluntarios).{0,20}levaram todas as|conseguiram tirar (?:todo mundo|o pessoal)|'
                     r'(?:a gente|as pessoas) (?:ja )?foi resgatad|as pessoas (?:ja )?foram resgatadas)')
INFO = re.compile(r'\b(?:doa[cç][aã]o|doacoes|doar|doando|entregar|comprar|mantimentos|suprimentos|recebendo|recebem|informam|informacao|horario)\b')
PHYSICAL_DANGER = re.compile(r'\b(?:ilhad[oa]s?|pres[oa]s?|telhado|correnteza|'
    r'agua\s+(?:(?:ja|esta|ta|nao para de)\s+)?(?:subindo|subir|entrou|tomou|(?:na|no|ate a|ate o)\s+(?:cintura|peito|pescoco)))\b')
VULNERABLE_OR_UPSTAIRS = re.compile(r'\b(?:gravid[ao]s?|idos[oa]s?|(?:segundo|2[º°o]?)\s+andar|andar superior)\b')
ROAD_INFORMATION = re.compile(r'\b(?:transitavel|interditad[ao]s?|liberaram a (?:rua|estrada)|'
    r'(?:como|se)\s+(?:esta|ta)\s+(?:a\s+)?(?:rua|estrada)|(?:da|posso|consegui?mos)\s+(?:pra|para)\s+(?:voltar|passar)\b)')
DONATION_DRIVE = re.compile(r'\bcoleta\s+(?:de|para)\b|\bquem puder (?:levar|doar|entregar)\b')

# ACC1: the writer says it is not a request, only a warning / preventive note / advice question.
STATEMENT_ONLY = re.compile(r'\bnao\s+(?:e|eh|seria)\s+(?:um\s+|uma\s+)?(?:pedido|chamado|caso|solicitacao)\b|'
    r'\b(?:so|apenas|somente)\s+(?:avisando|informando|pra avisar|para avisar|um aviso|prevenindo|por precaucao|para prevenir|pra prevenir)\b|'
    r'\bpor precaucao\b|\bmensagem\b[^.;!?\n]{0,40}\bantes d[aeo]\s+(?:cheia|enchente|chuva|alagamento)\b|\bainda nao (?:alagou|choveu|encheu)\b|'
    r'\b(?:quero|queria|gostaria de)\s+saber\s+se\s+(?:devo|preciso|vale|e melhor|posso|da pra)\b|\b(?:devo|devemos)\s+(?:sair|evacuar|ir embora)\b|'
    r'\bainda\s+da\s+(?:pra|para)\s+(?:ficar|esperar)\b|\be seguro\s+(?:ficar|sair)\b')

# ACC1: thanks / alert questions with no need, place or danger in them are not requests.
THANKS = re.compile(r'\b(?:obrigad[oa]s?|agradeco|agradecemos|deus abencoe|parabens|gratidao)\b|\balguem\s+(?:recebeu|viu|sabe|tem)\s+(?:\w+\s+){0,2}(?:aviso|alerta|previsao|boletim|noticia|informacao)\b')
QUESTION_INFO = re.compile(r'\bquem\s+tem\b[^.!?]{0,40}\b(?:gerador|combustivel|comida|cobertor(?:es)?|colchao|colchoes|roupas?|remedios?|doacoes)\b[^.!]*\?|\b(?:quais|qual|onde|quando|alguem sabe)\b[^.!]{0,70}\b(?:abrigos?|ponte|luz|energia|posto|doacoes|ponto de coleta|liberad[ao])\b[^.!]*\?|\bquando volta\b[^.!]*\?|\bponte\b[^.!?]{0,40}\b(?:liberad|aberta|fechada|transitavel)[^.!]*\?')
NEED_OR_PLACE = re.compile(r'\b(?:precis\w*|socorro|resgat\w*|urgente|agua|alag\w*|ilhad\w+|pres[oa]s?|telhado|rua|avenida|travessa|estrada|n[ao]s? ajud\w*|venham|mandem)\b')


PAST_RESCUE = re.compile(r'\b(?:fomos|fui|foi|foram|todos|todas)\s+(?:ja\s+)?(?:tod[oa]s?\s+)?resgatad[oa]s?\b')
NEGATED = re.compile(r'\b(?:nao|nunca|quando|se|ate|sem)\s+(?:\w+\s+){0,2}$')


def past_rescue(text):
    """Completed rescue stated in the past tense, not negated or conditional."""
    return any(not NEGATED.search(text[max(0, m.start()-30):m.start()]) for m in PAST_RESCUE.finditer(text))


def state(text):
    from app.textnorm import slang
    text = slang(_plain(text))
    partial = bool(PARTIAL.search(text))
    rescued = bool(completed_rescue_quote(text))
    human_present = bool(re.search(r'\b(?:\d+|uma?|duas?|dois|tres|quatro|cinco|seis)\s+(?:pessoas?|adultos?|idos[oa]s?|criancas?|bebes?)\b|'
                                  r'\b(?:pessoas?|personas?|people|adult[oa]s?|idos[oa]s?|criancas?|bebes?|familias?|senhor[ae]s?|'
                                  r'meu pai|minha mae|minha vo|meu vo|meu irmao|minha irma|pai|mae|avos?|vo|irmao|irma|filh[oa]s?|marido|esposa|tio|tia|vizinh[oa]s?|moradores|gravid[ao]s?|eu|nos|estou|estamos|a gente precisa)\b', text))
    human_present = human_present or bool(written_total(text))
    people_out = bool(PEOPLE_OUT.search(text) and ANIMALS.search(text) and not partial and
                      not re.search(r'\b(?:ainda|continua|segue)\b', text))
    animal_only = bool(people_out or NO_PEOPLE.search(text) or (ANIMALS.search(text) and not partial and
                       (not human_present or rescued and re.search(r'ficaram|restaram|apenas|somente|so os|so as', text))))
    # Supply/information conversations can mention rescues in passing. An
    # explicit human danger/request keeps the incident in the live queue.
    human_danger = bool(re.search(r'(?:pessoas?|gente|idos[oa]s?|criancas?|familia|meu pai|minha mae).{0,60}(?:ilhad|pres[oa]s?\b|telhado|precis.{0,15}resgat)|'
                                 r'(?:socorro|preciso de resgate|precisamos de resgate)', text)) or bool(
                                     human_present and PHYSICAL_DANGER.search(text))
    welfare = re.search(r'\balguem\s+(?:sabe\s+se|mora|vive)\b|\b(?:minha|meu)\s+\w+\s+nao\s+(?:responde|atende)\b|'
                        r'\b(?:procuro|procurando)\s+(?:meu|minha|o|a)\b|perdi (?:o )?contato|ultima vez visto|ninguem tem noticia|'
                        r'\b(?:achar\s+)?noticias\s+(?:de|do|da)\b|\bninguem sabe del[ae]\b', text)
    people_signal = bool(re.search(r'\b(?:\d+|uma?|duas?|dois|tres|quatro|cinco|seis)\s+(?:pessoas?|adultos?|idos[oa]s?|criancas?|bebes?)\b|'
                                   r'\b(?:pessoas|gente|familias?|idos[oa]s?|criancas?|bebes?|adultos?|moradores|cadeirantes?)\b', text))
    informational = bool((INFO.search(text) or STATEMENT_ONLY.search(text) or (THANKS.search(text) and not NEED_OR_PLACE.search(text)) or QUESTION_INFO.search(text) or welfare or ROAD_INFORMATION.search(text) or DONATION_DRIVE.search(text))
                         and not human_danger and not partial and not rescued)
    return {'people_signal': people_signal, 'partial': partial, 'rescued': rescued and not partial,
            'not_a_rescue': animal_only or informational,
            'life_safety': partial or bool(LIFE_SAFETY.search(text) or PHYSICAL_DANGER.search(text) or
                                          human_present and VULNERABLE_OR_UPSTAIRS.search(text))}


def guard_fields(fields, text):
    status = state(text)
    if status['partial'] or status['not_a_rescue']:
        fields.pop('already_rescued', None)
    elif status['rescued']:
        fields['already_rescued'] = {'value': True, 'quote': completed_rescue_quote(text), 'source': 'rule:rescue_state'}
    else:
        fields.pop('already_rescued', None)
    return status
