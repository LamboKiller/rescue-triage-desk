"""Attacker agent (role redteam_attacker): one realistic message + its declared category/outcomes, validated by code.

The declaration is written to the append-only store (with a hash) BEFORE the pipeline sees the message, so the
attacker cannot adapt its claim to the result.
"""
import hashlib
import json
import time
from app.redteam.policy import CATEGORIES, DECISIONS, norm
from app.redteam.scripted import pick_places, scripted_declaration

STYLE_EXCERPT = (
    'Real requests are short, hurried, often typed on a phone. Complete details are the exception: many omit the house '
    'number, the people count or the city. Relatives write on behalf of someone elsewhere; messages are forwarded and '
    'reposted in several groups; some are voice-note transcripts ("tá cortando", battery talk). Gaucho slang, typos, '
    'missing accents and a bit of Spanish/English are normal.')
SYSTEM = ('Você escreve UMA mensagem de teste realista de pedido de ajuda em enchente (RS) para testar um sistema. '
          'Estilo: ' + STYLE_EXCERPT + ' Use os 3 nomes de lugar fornecidos COPIADOS EXATAMENTE; não invente outros lugares. '
          'Não use dados pessoais reais. Declare a categoria pedida e as decisões aceitáveis ANTES do teste. '
          'Só JSON: {"category":"…","message":"…","places":["nome copiado"],"incident_city":"cidade do incidente ou null",'
          '"caller_city":"cidade de quem escreve se diferente ou null","expected_outcomes":["SEND_CANDIDATE|CALLBACK|REVIEW_REQUIRED|REPORTED_RESCUED"]}')
RETRY = ('Copie os nomes de lugar EXATAMENTE como fornecidos dentro de "message" e em "places"; categoria exatamente a pedida. '
         'Só JSON: {"category":"…","message":"…","places":["…"],"incident_city":null,"caller_city":null,"expected_outcomes":["…"]}')


def letters(hex_text):
    """Digit-free id: the pipeline redacts long digit runs inside message ids."""
    return hex_text.translate(str.maketrans('0123456789', 'ghijklmnop'))


def decl_hash(decl):
    core = {k: decl[k] for k in ('category', 'message', 'places', 'incident_city', 'caller_city', 'expected_outcomes')}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(output, category, given):
    """Strict validation of the attacker's JSON. Returns a declaration dict or raises ValueError."""
    if not isinstance(output, dict):
        raise ValueError('attacker output is not an object')
    if output.get('category') not in CATEGORIES or output['category'] != category:
        raise ValueError('category missing, unknown or not the requested one')
    msg = output.get('message')
    if not isinstance(msg, str) or not 15 <= len(msg) <= 800:
        raise ValueError('message missing or wrong length')
    places = output.get('places')
    allowed = {norm(g['name']) for g in given}
    if (not isinstance(places, list) or not places or not all(isinstance(p, str) and norm(p) in allowed for p in places)
            or not all(norm(p) in norm(msg) for p in places)):
        raise ValueError('declared places must be supplied names and appear in the message')
    outcomes = output.get('expected_outcomes')
    if not isinstance(outcomes, list) or not outcomes or not set(outcomes) <= set(DECISIONS):
        raise ValueError('expected_outcomes must be a non-empty subset of decisions')
    cities = {}
    for key in ('incident_city', 'caller_city'):
        v = output.get(key)
        if v is not None and (not isinstance(v, str) or norm(v) not in norm(msg)):
            raise ValueError(key + ' must be null or appear in the message')
        cities[key] = v
    if category == 'caller_elsewhere' and (not cities['caller_city'] or not cities['incident_city']
                                           or norm(cities['caller_city']) == norm(cities['incident_city'])):
        raise ValueError('caller_elsewhere needs distinct caller_city and incident_city')
    return {'category': category, 'message': msg.strip(), 'places': list(places), 'expected_outcomes': list(outcomes),
            **cities, 'source': 'model'}


class Attacker:
    """client=None -> scripted offline attacker. With a client: model attacker, one short retry, visible fallback."""

    def __init__(self, client=None):
        self.client = client

    def write(self, category, slots, given, variant=0):
        scripted = scripted_declaration(category, slots, variant)
        if self.client is None:
            return scripted
        payload = json.dumps({'category': category, 'category_description': CATEGORIES[category]['desc'],
                              'places': given}, ensure_ascii=False)
        error = 'unknown'
        try:
            if hasattr(self.client, 'start_message'):
                self.client.start_message('redteam:' + category)
            deadline = time.monotonic() + 150
            for attempt in range(2):
                raw, _meta = self.client.call('redteam_attacker', RETRY if attempt else SYSTEM, payload, deadline)
                try:
                    return validate(raw, category, given)
                except ValueError as exc:
                    error = str(exc)
        except Exception as exc:  # provider failure: visible fallback, never a silent success
            error = type(exc).__name__
        return {**scripted, 'source': 'scripted_fallback', 'fallback_reason': error}


def build(n, attacker, rng, order=None):
    """n declarations cycling through the categories (balanced). Pure; the caller stores them before running."""
    order = list(order or CATEGORIES)
    out = []
    for i in range(n):
        category = order[i % len(order)]
        slots, given = pick_places(category, rng)
        decl = attacker.write(category, slots, given, variant=i // len(order))
        decl['places_given'] = given
        decl['decl_hash'] = decl_hash(decl)
        decl['decl_id'] = 'rt-' + letters(decl['decl_hash'][:12])
        out.append(decl)
    return out
