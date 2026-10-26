'use strict';
// Desembarque: barco -> ponto de desembarque -> abrigo com vaga -> ambulância (casos médicos). Só propõe; o humano escolhe; tudo vira evento.
window.DeskLanding=(()=>{
  const sim=o=>o.simulated||o.synthetic||(o.shelters||[]).some(s=>s.synthetic||s.simulated)?' [SIMULADO]':'';
  const hhmm=d=>d+'T'+new Date().toTimeString().slice(0,5)+':00-03:00';
  async function render(body,c,x){
    const {api,el,button,notice,day}=x,box=el('section',undefined,'landing');body.append(box);
    box.append(el('h3','Desembarque'),el('p','Carregando…','muted'));
    let v;try{v=await api(`/api/cases/${encodeURIComponent(c.case_id)}/landing?now=${encodeURIComponent(hhmm(day))}`);}catch(e){box.replaceChildren(el('h3','Desembarque'),el('p','Indisponível: '+e.message,'danger'));return;}
    const again=()=>{box.remove();render(body,c,x);};
    box.replaceChildren(el('h3','Desembarque'),el('p',`${v.labels_pt.distance} · ${v.labels_pt.capacity}. Nada é acionado sozinho: o operador escolhe.`,'muted'));
    for(const r of v.review_pt)box.append(el('p',r,'danger'));
    if(v.choice)box.append(el('p',`Escolha registrada: ${v.choice.landing_id}${v.choice.shelter_id?' → '+v.choice.shelter_id:''}${v.choice.override?' (diferente da sugestão: '+v.choice.override_reason+')':''} · ${v.choice.actor}`,'reason'));
    for(const o of v.options){
      const card=el('div',undefined,'landing-opt'),km=(o.distance.m/1000).toFixed(1);
      card.append(el('strong',`${o.rank}. ${o.label}${sim(o)}`),el('p',`${km} km (${o.distance.label_pt}) · ${o.source_label} · acesso: ${({dry:'seco',unknown:'desconhecido',wet:'alagado',conflict:'conflitante'})[o.access.state]||o.access.state}`),
        el('p',`Capacidade: ${o.capacity_per_hour.value}/h (${o.capacity_per_hour.label_pt}) · fila: ${o.queue.has_reports?o.queue.people_waiting+' pessoa(s)':'desconhecida'}`));
      for(const w of o.warnings_pt)card.append(el('p',(o.congested&&w.startsWith('CONGESTIONADO')?'■ ':'◆ ')+w,o.congested?'danger':'muted'));
      const ul=el('ul');
      for(const s of o.shelters){const li=el('li',`${s.label} — ${s.room_pt}`);li.append(' ',button('Escolher',async()=>{const alt=o.rank!==1||s!==o.shelters[0];let why;if(alt){why=prompt('Diferente da sugestão. Motivo:');if(!why)return;}try{await api(`/api/cases/${encodeURIComponent(c.case_id)}/landing/choice`,{landing_id:o.landing_id,shelter_id:s.shelter_id,actor:'operador',at:hhmm(day),override_reason:why});notice('Escolha registrada (reversível).');again();}catch(e){notice(e.message,true);}}));ul.append(li);}
      card.append(ul);
      if(!o.shelters.length)card.append(el('p',o.shelters_message_pt||'Nenhum abrigo elegível.','danger'));
      if(o.ambulance){const a=el('div',undefined,'landing-amb');a.append(el('strong','Ambulância — '+o.ambulance.status),el('p',o.ambulance.text_pt));card.append(a);}
      const row=el('div',undefined,'row');
      const rep=(label,kind,ask)=>row.append(button(label,async()=>{const b={actor:'operador',source:'operator',at:hhmm(day)};if(ask){const n=parseInt(prompt(ask),10);if(!n)return;b.people=n;}try{await api(`/api/landing/${encodeURIComponent(o.landing_id)}/${kind}`,b);again();}catch(e){notice(e.message,true);}}));
      rep('Barco chegou','arrival','Pessoas a bordo (número):');rep('Desembarcaram','unloaded','Pessoas desembarcadas:');rep('Ponto saturado','full');
      card.append(row);box.append(card);
    }
    if(v.handoff){box.append(el('h4','Nota para a equipe de desembarque'),el('p',v.handoff.note_pt),el('small',v.handoff.note_label_pt+(v.handoff.for_choice?'':' · prévia, ainda sem escolha'),'muted'));}
    if(v.choice)box.append(button('Desfazer escolha',async()=>{try{await api(`/api/cases/${encodeURIComponent(c.case_id)}/landing/choice`,{revoke:true,actor:'operador',at:hhmm(day)});again();}catch(e){notice(e.message,true);}}));
  }
  return {render};
})();
