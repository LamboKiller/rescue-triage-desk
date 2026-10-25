"""Conservative Portuguese street lookup; no household geocoding."""
import re
import unicodedata
from datetime import datetime


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', str(text).lower())
                   if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    if words and words[0] in ('rua', 'r', 'av', 'avenida', 'tv', 'travessa', 'est', 'estrada'):
        words.pop(0)
    return ' '.join(w for w in words if w not in ('do', 'da', 'dos', 'das', 'de'))


def lookup(rows, street, municipality, replay_time):
    date = datetime.fromisoformat(replay_time.replace('Z', '+00:00')).date().isoformat()
    matches = [r for r in rows if normalize(r['municipality']) == normalize(municipality)
               and normalize(r['display_name']) == normalize(street)] if street and municipality else []
    dates = [d for d in ('2024-05-06', '2024-05-08') if d <= date]
    observed = dates[-1] if dates else None
    row = matches[0] if len(matches) == 1 else None
    overlap = row.get('any_in_water_' + observed) in ('1', 'true', True) if row and observed else None
    return {'found': row is not None, 'candidates': [r['display_name'] for r in matches[:10]],
            'municipality': row['municipality'] if row else None,
            'display_name': row['display_name'] if row else None,
            'observed_date': observed, 'retrospective_water_overlap': overlap,
            'in_water_by_date': None, 'publication_available': False,
            'warning': 'Mapa retrospectivo; publicação desconhecida; sem máscara de água permanente. '
                       'Ausência de sobreposição não significa segurança; cobertura de 08/05 é diferente.'}
