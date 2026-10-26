'use strict';
window.DeskMissions=(()=>{
  let generation=0;
  const names={stretcher_or_bedridden:'Maca / pessoa acamada',wheelchair:'Cadeira de rodas',infant:'Bebê',pregnant:'Gestante',medical_urgent:'Urgência médica',structural_risk:'Risco estrutural',water_rising:'Água subindo',animals:'Animais'};
  async function render(body,c,{api,el,button,evidence,refresh,notice,day}){
    const token=++generation;
    body.replaceChildren(el('p','Carregando missões e verificando versões…','muted'));
    try{
      const assigned=c.status?.startsWith('ASSIGNED:'),mid=assigned?c.status.slice(9):null;
      const response=await api(mid?`/api/missions/${encodeURIComponent(mid)}`:`/api/missions/proposals?date=${encodeURIComponent(day)}`);
      if(token!==generation||!body.isConnected)return;
      body.replaceChildren(el('h3',assigned?'Missão atribuída':'Proposta de missão'),el('p','Ordem sugerida — não é rota navegável. Confirmar acesso e transferência com a equipe.','mission-route-note'));
      const plans=assigned?[response]:(response.proposals||[]).filter(p=>p.stops.some(s=>s.case_id===c.case_id));
      if(assigned&&response.date>day){window.DeskMap.showMission(null);body.append(el('p','A missão atual pertence a uma data posterior ao replay. Selecione a data da missão para revisar ou cancelar.'));return;}
      if(!plans.length){window.DeskMap.showMission(null);body.append(el('p','Nenhuma proposta para este caso nesta data. Somente candidatos SEND disponíveis podem integrar uma missão.'));return;}
      for(const p of plans){
        window.DeskMap.showMission(p);
        const section=el('section',undefined,'mission-card');
        section.append(el('h4',`${p.stops.length} parada(s) · ${p.asset||'meio a confirmar'}`),el('p',p.crew_brief_pt),el('small',`Brief: ${p.brief_check} · ${p.synthetic?'inventário / dados sintéticos':'dados do operador'}`));
        const summary=el('dl');for(const [title,value]of [['Pessoas',p.people],['Capacidade por ciclo',p.capacity],['Unidades',p.asset_count],['Ciclos de viagem',p.trips],['Distância entre paradas (m)',p.distance_m]]){summary.append(el('dt',title),el('dd',value==null?'A confirmar':String(value)));}section.append(summary);
        const list=el('ol');for(const stop of p.stops){const item=el('li');item.append(el('strong',`Parada ${stop.order} · ${stop.case_id}`),el('p',`${stop.people??'Contagem a confirmar'} pessoas · necessidades: ${stop.requirements.needs_check}`));for(const need of stop.requirements.needs||[])item.append(el('p',`${names[need.tag]||need.tag}: “${need.quote}” (mensagem ${need.message_index+1})`));for(const group of stop.requirements.count_by_group||[])item.append(el('p',`${group.group_quote}: ${group.people} pessoas · “${group.quote}”`));item.append(evidence('Profundidade, regras e requisitos',stop));if(assigned){item.append(el('p',stop.done?'Parada conclu\u00edda':'Retorno de campo pendente'));if(!stop.done){const member=await api(`/api/cases/${encodeURIComponent(stop.case_id)}`);if(token!==generation||!body.isConnected)return;item.append(window.DeskFeedback.form(member,{api,el,button,refresh,notice,day},p.mission_id));}}list.append(item);}section.append(list);
        section.append(el('h4','Por que este grupo'));for(const reason of p.why_group_pt||[])section.append(el('p',reason));window.DeskShelters?.mount(section,{plan:p,day});
        const blockers=p.blocking_reasons||[];for(const reason of blockers)section.append(el('p',reason,'danger'));
        section.append(evidence('Cargas por viagem e entradas dos cálculos',{trip_loads:p.trip_loads,units:p.units,distance_inputs:p.distance_inputs,distance_basis:p.distance_basis}));
        const ack=el('label',undefined,'ack'),check=el('input');check.type='checkbox';ack.append(check,document.createTextNode(' Revisei requisitos, capacidades, versões e todas as cautelas dos meios.'));
        const act=button(assigned?'Cancelar missão':'Aprovar missão',async()=>{
          act.disabled=true;
          try{
            const expected=assigned?p.expected_versions:Object.fromEntries(p.stops.map(s=>[s.case_id,s.expected_version]));
            await api(assigned?`/api/missions/${encodeURIComponent(p.mission_id)}/cancel`:'/api/missions',assigned?{actor:'operador',expected_versions:expected}:{proposal_id:p.proposal_id,actor:'operador',expected_versions:expected,caution_acknowledged:check.checked});
            notice(assigned?'Missão cancelada; estados anteriores restaurados.':'Missão aprovada por operador humano.');
            await refresh();
          }catch(error){notice(error.message,true);act.disabled=blockers.length>0||!assigned&&!check.checked;}
        },assigned?'':'primary');
        act.disabled=blockers.length>0||!assigned;check.onchange=()=>{act.disabled=blockers.length>0||!check.checked;};
        if(!assigned)section.append(ack);section.append(act);body.append(section);if(assigned)await window.DeskChain?.mount(section,p,{api,el,button,evidence,refresh,notice,day});
      }
    }catch(error){if(token!==generation||!body.isConnected)return;window.DeskMap.showMission(null);body.replaceChildren(el('p',error.message,'danger'));}
  }
  function clear(){generation++;window.DeskMap.showMission(null);}
  return {render,clear};
})();
