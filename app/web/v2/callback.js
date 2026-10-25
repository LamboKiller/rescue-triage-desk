'use strict';
window.DeskCallback=(()=>{
 const last=new Map(),expanded=new Set();
 const NAMES={'area.out_of_area':'Fora da área?','loc.municipality':'Município','loc.place':'Rua / referência','loc.number':'Número / cruzamento','loc.approximate':'Local aproximado','dialogue.conflict':'Locais divergentes','people.count':'Nº de pessoas','people.conflict':'Contagens conflitantes','people.derived':'Total derivado','vuln.unknown':'Vulnerabilidade','stale.contact':'Ainda no local?','rescue.unconfirmed':'Resgate relatado','dup.suspected':'Possível duplicado','review.injection':'Instrução suspeita','review.not_rescue':'Sem pedido de resgate','review.incomplete':'Análise incompleta'};
 const name=id=>NAMES[id]||id;
 function evText(e){return e.quote||e.name||(e.path?`${e.path}: ${e.value??'ausente'}`:'')||(e.field?`${e.field}: ${e.previous??''} → ${e.reply??''}`:'')||(e.case_id?`caso ${e.case_id}`:'');}
 function badge(el,text,cls){return el('span',text,'cb-badge '+(cls||''));}
 function diffView(d,el,evidence){
  const root=el('section',undefined,'cb-diff');root.append(el('h3','Antes / depois'));
  if(d.simulated)root.append(badge(el,'SIMULADO','cb-sim'),el('small',' Resposta gerada a partir de um registro de verdade sintético; não é um cidadão real.'));
  const x=d.diff;root.append(el('p',`Decisão: ${x.decision.before} → ${x.decision.after}${x.decision.changed?' (mudou)':' (sem mudança)'} · versão ${x.version.before} → ${x.version.after}`),el('p',x.decision.reason_after||'','reason'),el('blockquote',d.reply_text,'cb-reply'));
  const ch=el('ul');for(const c of x.fields_changed)ch.append(el('li',`${c.field}: ${c.from??'—'} → ${c.to} (mensagem ${c.message_index})`));if(!ch.childNodes.length)ch.append(el('li','Nenhum campo alterado.'));root.append(el('strong','Campos alterados'),ch);
  const it=x.items;root.append(el('p',`Itens resolvidos: ${it.resolved.map(name).join(', ')||'nenhum'}`),el('p',`Ainda abertos: ${it.remaining.map(name).join(', ')||'nenhum'}`));if(it.new.length)root.append(el('p',`Novos itens: ${it.new.map(name).join(', ')}`,'danger'));
  root.append(evidence('Dados do diff',d));return root;
 }
 async function render(body,c,{api,el,button,evidence,refresh,notice,day}){
  const root=el('section');root.id='callback-tab';root.append(el('h3','Retorno · itens abertos e perguntas'),el('p','Carregando…','muted'));body.append(root);
  let view;try{view=await api(`/api/cases/${encodeURIComponent(c.case_id)}/callback${expanded.has(c.case_id)?'?expand=1':''}`);}catch(e){root.replaceChildren(el('h3','Retorno'),el('p',e.message,'danger'));return;}
  if(!root.isConnected)return;
  root.replaceChildren(el('h3','Retorno · itens abertos e perguntas'));
  root.append(el('p',`Decisão atual: ${view.decision}. Itens bloqueantes impedem o despacho; os demais refinam. Quem aprova é sempre o operador.`,'muted'));
  const list=el('ul',undefined,'cb-items');
  for(const i of view.items){const li=el('li',undefined,i.blocking?'cb-block':'cb-soft');li.append(el('span',i.blocking?'☐ ':'○ '),el('strong',name(i.id)),badge(el,i.blocking?'bloqueia':'refina'),el('p',i.why_pt));const ev=i.evidence.map(evText).filter(Boolean);if(ev.length)li.append(el('small','Evidência: '+ev.join(' · ')));list.append(li);}
  if(!view.items.length)list.append(el('li','Nenhum item aberto.'));root.append(list);
  const p0=view.plan,qs=el('section');const total=p0.total_questions??p0.questions.length;qs.append(el('h3',p0.expanded?`Perguntas (${p0.questions.length}, máx. 3)`:`Pergunta principal (1 de ${total})`));
  const p=view.plan;qs.append(el('small',p.source==='model'?'Redigidas pelo agente callback_planner e validadas por código.':p.source==='templates'?`Modelos de texto determinísticos${p.fallback_reason?' · motivo: '+p.fallback_reason:''}.`:'Nenhuma pergunta automática para este caso.'));
  const ol=el('ol');for(const q of p.questions){const li=el('li');li.append(el('span',q.text_pt),el('small',' → '+q.item_ids.map(name).join(', ')));ol.append(li);}qs.append(ol);
  if(p.addressed_to&&!['on_site','unknown','crew'].includes(p.addressed_to))qs.append(el('small',`Dirigida a: ${p.addressed_to==='third_party_elsewhere'?'terceiro fora do local (peça que repasse)':'quem repassou a mensagem'}.`));
  if(!p.expanded&&total>1)qs.append(button(`Mostrar todas (${total})`,()=>{expanded.add(c.case_id);root.remove();render(body,c,{api,el,button,evidence,refresh,notice,day});}));
  if(p.expanded&&total>1)qs.append(button('Só a principal',()=>{expanded.delete(c.case_id);root.remove();render(body,c,{api,el,button,evidence,refresh,notice,day});}));
  if(p.questions.length)qs.append(button('Copiar perguntas',()=>navigator.clipboard?.writeText(p.questions.map((q,n)=>`${n+1}. ${q.text_pt}`).join('\n'))));
  if(p.deferred?.length)qs.append(el('small',`Adiado (não bloqueia): ${p.deferred.map(name).join(', ')}`));
  qs.append(evidence('Agente e validação',p.agent));root.append(qs);
  const form=el('form'),label=el('label','Resposta do contato'),input=el('textarea'),time=el('input'),timeLabel=el('label','Recebida em (BRT, opcional)');
  input.id='callback-reply';label.htmlFor=input.id;input.maxLength=4000;time.id='callback-time';timeLabel.htmlFor=time.id;time.type='datetime-local';
  const send=el('button','Registrar resposta e reavaliar'),sim=el('button','Simular resposta');send.type='submit';sim.type='button';
  async function post(body){send.disabled=sim.disabled=true;try{const out=await api(`/api/cases/${encodeURIComponent(c.case_id)}/callback/reply`,body);last.set(out.case_id,out);notice(`Versão ${out.diff.version.after}: ${out.diff.decision.before} → ${out.diff.decision.after}${out.simulated?' · SIMULADO':''}`);await refresh();}catch(e){notice(e.message,true);}finally{send.disabled=sim.disabled=false;}}
  form.onsubmit=e=>{e.preventDefault();if(!input.value.trim())return;const b={text:input.value,expected_version:view.version};if(time.value)b.received_at=time.value+':00-03:00';post(b);};
  sim.onclick=()=>post({simulated:true,expected_version:view.version,scope:view.plan.expanded?'all':'primary'});
  form.append(label,input,timeLabel,time,send);
  if(view.simulator_available){sim.append(document.createTextNode(' '),badge(el,'SIMULADO','cb-sim'));form.append(sim);}else form.append(el('small','Simulador indisponível: este caso não tem registro de verdade sintético (somente demo/avaliação).','muted'));
  root.append(form);
  const d=last.get(c.case_id);if(d&&d.case&&d.case.version===view.version)root.append(diffView(d,el,evidence));
 }
 return {render};
})();
