"""Portuguese radio card assembled exclusively from case values and screened rules."""

def build_card(case):
    facts, lines = [], []
    def use(path, default='não informado'):
        value = case
        try:
            for key in path.split('.'):
                value = value[int(key)] if isinstance(value,list) else value[key]
        except (KeyError, TypeError, IndexError):
            return default
        facts.append({'path':path,'value':value})
        return str(value) if value is not None else default
    place = ', '.join(use('fields.'+k+'.value') for k in ('landmark','street','number','municipality') if k in case.get('fields',{}))
    lines.append('Local: '+(place or 'não informado')+'. Posição: '+use('result.location_confidence')+'; '+use('position.position_kind')+'.')
    if case.get('result', {}).get('location_approximate'):
        use('result.location_approximate')
        lines.append('Local aproximado (bairro inteiro): confirmar ponto' if case.get('result', {}).get('location_precision') == 'area'
                     else 'Local aproximado: confirmar no local')
    if case.get('result', {}).get('people') is None and not case.get('fields', {}).get('people', {}).get('value'):
        lines.append('contagem desconhecida, confirmar')
    lines.append('Pessoas: '+use('fields.people.value')+'; '+ '; '.join(label+': '+use('fields.'+key+'.value') for key,label in [('children','crianças'),('elderly','idosos'),('disabled','deficiência / acamados'),('pets','pets')])+'.')
    if isinstance(case.get('incident_state'), dict) and 'error' not in case['incident_state']:
        lines.append('Estado do incidente: precisão do local '+use('incident_state.location_precision.value')+'; nível '
                     +use('incident_state.vertical_level.value')+'; pessoas inicial '+use('incident_state.people_initial.value')
                     +' / restantes '+use('incident_state.people_remaining.value')+'; relatos '+use('incident_state.report_count')
                     +'; remetente '+use('incident_state.sender_role.value')+'.')
    lines.append('Profundidade (estimativa): faixa '+use('hazards.depth_band')+'; data '+use('hazards.depth_observed_date')+'.')
    chosen = case.get('approved_asset') or case.get('proposed_asset')
    fleet = case.get('fleet',[])
    idx = next((i for i,r in enumerate(fleet) if r['asset']==chosen), None)
    if idx is None:
        idx = next((i for i,r in enumerate(fleet) if r['verdict']!='unsafe'),None)
    if idx is not None:
        prefix = 'fleet.'+str(idx)
        lines.append('Meio para revisão humana: '+use(prefix+'.label_pt')+'; '+use(prefix+'.verdict')+'. Cautelas: '+ ' '.join(use(prefix+'.reasons_pt.'+str(i)) for i in range(len(fleet[idx]['reasons_pt']))))
        rules = set(fleet[idx].get('rule_ids',[]))
        equipment=[]
        if rules & {'R060','R061'}:
            equipment.append('maca fixada e conjunto aprovado de extração')
        if 'R065' in rules:
            equipment.append('coletes / flutuação e proteção individual ajustados aos ocupantes')
            if case.get('fields',{}).get('children',{}).get('value',0)>0:
                use('fields.children.value')
                equipment.append('coletes infantis ajustados às crianças')
        # Rule R010 supports mission equipment and PPE; no unverified kit is invented.
        if 'R010' in rules:
            equipment.append('equipamento de missão e proteção individual')
        for i,rule in enumerate(fleet[idx].get('rule_ids',[])):
            if rule in {'R060','R061','R010','R065'}:
                use(prefix+'.rule_ids.'+str(i))
        lines.append('Levar / verificar: '+('; '.join(equipment) or 'confirmar equipamento com a equipe')+'.')
    else:
        lines.append('Meio: nenhum recurso elegível; revisão humana obrigatória. Levar: confirmar com a equipe.')
    if not case.get('location_confirmed'):
        lines.append('Confirmar na chegada: localização ainda sem confirmação humana.')
    questions = case.get('result',{}).get('questions',[])
    lines.append('Confirmar na chegada: '+(' '.join(use('result.questions.'+str(i)) for i in range(len(questions))) or 'local, condições atuais e conclusão do resgate com a equipe.'))
    lines.append('Caso '+use('case_id')+'; versão '+use('version')+'.')
    return {'text_pt':'\n'.join(lines),'lines':lines,'facts_used':facts}
