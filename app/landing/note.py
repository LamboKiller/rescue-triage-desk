"""Server-rendered handoff: each operational clause retains its field meaning."""


def facts_of(plan, option):
    sh = option['shelters'][0] if option['shelters'] else None
    return {'caso': plan['case_id'], 'pessoas': plan['people'], 'desembarque': option['label'], 'distancia_km': round(option['distance']['m'] / 1000, 1),
            'distancia_tipo': option['distance']['label_pt'], 'abrigo': sh['label'] if sh else None, 'vagas': (sh['room_pt'] if sh else None),
            'medico': [m['quote'] for m in plan['medical']], 'avisos': option['warnings_pt'],
            'ambulancia': option['ambulance']['status'] if option['ambulance'] else None}


def template(f):
    t = 'Desembarcar em %s (%s km, %s). ' % (f['desembarque'], f['distancia_km'], f['distancia_tipo'])
    t += 'Pessoas: %s. ' % (f['pessoas'] if f['pessoas'] else 'contagem desconhecida')
    t += 'Destino sugerido: %s (%s). ' % (f['abrigo'], f['vagas']) if f['abrigo'] else 'Destino: nenhum abrigo elegível; falar com a coordenação. '
    if f['medico']:
        t += 'Necessidade médica citada: %s. ' % ', '.join('«%s»' % q for q in f['medico'])
        t += 'Ambulância: %s. ' % (f['ambulancia'] or 'acionamento não confirmado; requer aprovação humana')
    if f['avisos']: t += 'Avisos: %s. ' % '; '.join(f['avisos'])
    return t.strip()


def write(plan, option, client=None, deadline=None):
    # Free model prose cannot prove that a number still describes the same field.
    f = facts_of(plan, option)
    return {'note_pt': template(f), 'note_source': 'deterministic',
            'note_label_pt': 'Texto determinístico (sem IA); fatos e avisos atuais, sem autorização automática.', 'facts': f}
