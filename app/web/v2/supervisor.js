'use strict';
window.DeskSupervisor=(()=>{
 let ctx=null,data=null,open=false;
 const KIND={cluster_growth:'Aglomeração',stale_send:'SEND/ASSIGNED parado',idle_resources:'Recurso ocioso',rising_depth:'Água subindo',callback_aging:'Retorno envelhecendo',mission_feedback:'Missão sem retorno'};
 const CHECK={model_reviewed:'Modelo (validado)',deterministic_only:'supervisor_check: deterministic_only',no_findings:'Nada a alertar'};
 const hhmm=t=>String(t).slice(11,16);
 function badge(text,cls){const b=ctx.el('span',text,'sup-badge '+cls);return b;}
 async function load(){
  const day=ctx.day();
  try{data=await ctx.api(`/api/supervisor/ticks?date=${encodeURIComponent(day)}`);}catch(e){ctx.notice(e.message,true);return;}
  draw();
 }
 async function run(until){
  const day=ctx.day(),time=document.getElementById('sup-time').value||'12:00',now=`${day}T${time}:00-03:00`;
  const body={replay_time:now};if(until)body.until=`${day}T${until}:00-03:00`;
  try{await ctx.api('/api/supervisor/tick',body);ctx.notice(until?'Supervisor: série de ticks executada.':'Supervisor: tick executado.');}catch(e){ctx.notice(e.message,true);}
  await load();
 }
 async function decide(alert,decision){
  try{const r=await ctx.api(`/api/supervisor/alerts/${encodeURIComponent(alert.alert_id)}`,{decision,actor:'operador',replay_time:alert.created_at});
   ctx.notice(decision==='accept'?`Aceito: ${r.decision?.execution?.summary_pt||'ação registrada'}. Rode o próximo tick para re-checar.`:'Alerta dispensado.');
   if(decision==='accept')await ctx.refresh();}
  catch(e){ctx.notice(e.message,true);}
  await load();
 }
 function alertCard(a){
  const {el,button}=ctx,card=el('article',undefined,'sup-alert');
  const head=el('div',undefined,'sup-row');
  head.append(el('strong',`${hhmm(a.created_at)} · ${KIND[a.kind]||a.kind}`),badge({open:'Aberto',accepted:'Aceito',dismissed:'Dispensado'}[a.status],'sup-'+a.status));
  if(a.outcome)head.append(badge(a.outcome==='resolved'?'Resolvido':'Ainda aberto','sup-'+a.outcome));
  card.append(head,el('p',a.why_pt),el('small',`Ação proposta (humana decide): ${a.action_label_pt}`));
  const d=el('details');d.append(el('summary','Fatos citados'));
  for(const f of a.facts)d.append(el('p',`${f.id}: ${f.text_pt}`));
  if(a.numbers)d.append(el('p',Object.entries(a.numbers).map(([k,v])=>`${k}=${v}`).join(' · ')));
  card.append(d);
  if(a.status==='open'){const row=el('div',undefined,'sup-row');const ok=button('Aceitar e executar',()=>decide(a,'accept'),'primary'),no=button('Dispensar',()=>decide(a,'dismiss'));ok.id='sup-accept-'+a.alert_id;row.append(ok,no);card.append(row);}
  const ex=a.decision?.execution;if(ex)card.append(el('p',`Executado: ${ex.summary_pt}`,'sup-exec'));
  for(const r of a.rechecks||[])card.append(el('p',`Re-checagem ${hhmm(r.replay_time)}: ${r.outcome==='resolved'?'resolvido':'ainda aberto'} — ${r.delta_pt}`,'sup-recheck sup-'+r.outcome));
  return card;
 }
 function draw(){
  const root=document.getElementById('supervisor-panel'),{el,button}=ctx;root.hidden=!open;
  const toggle=document.getElementById('supervisor-toggle');if(toggle){const n=data?.counts?.open||0;toggle.textContent=n?`Supervisor (${n})`:'Supervisor';}
  if(!open||!data)return;
  root.replaceChildren();
  const top=el('div',undefined,'sup-row');top.append(el('h2','Supervisor · '+data.date),button('Fechar',()=>{open=false;draw();}));
  const time=el('input');time.type='time';time.id='sup-time';time.value='12:00';time.setAttribute('aria-label','Horário do replay');
  const controls=el('div',undefined,'sup-row');controls.append(time,button('Rodar agora',()=>run(null),'primary'),button(`Rodar até 23:30 (a cada ${data.interval_min} min)`,()=>run('23:30')));
  root.append(top,el('p',`Vigia a mesa a cada ${data.interval_min} min de replay. Propõe ações; nada é executado sem decisão humana. Contagens: ${data.counts.open} abertos · ${data.counts.accepted} aceitos · ${data.counts.dismissed} dispensados · ${data.counts.resolved} resolvidos · ${data.counts.still_open} ainda abertos.`,'muted'),controls);
  const tl=el('ol',undefined,'sup-timeline');tl.setAttribute('aria-label','Linha do tempo de ticks');
  if(!data.ticks.length)tl.append(el('li','Nenhum tick neste dia.'));
  for(const t of data.ticks){const li=el('li');li.append(el('strong',hhmm(t.replay_time)),el('span',` · ${t.findings.length} achados · ${t.alerts.length} alertas · ${t.rechecks.length} re-checagens `),badge(CHECK[t.supervisor_check]||t.supervisor_check,t.supervisor_check==='deterministic_only'?'sup-warn':'sup-ok'));if(t.fallback_reason)li.append(el('small',` (${t.fallback_reason})`));tl.append(li);}
  root.append(tl);
  const list=el('div',undefined,'sup-alerts');if(!data.alerts.length)list.append(el('p','Sem alertas neste dia.','muted'));
  for(const a of data.alerts)list.append(alertCard(a));
  root.append(list);window.DeskChain?.alerts(list,ctx);
 }
 function init(c){
  ctx=c;const bar=document.querySelector('.status-bar'),anchor=document.getElementById('resources');
  if(!bar||document.getElementById('supervisor-toggle'))return;
  const b=c.button('Supervisor',async()=>{open=!open;if(open)await load();else draw();});b.id='supervisor-toggle';
  bar.insertBefore(b,anchor);
  const date=document.getElementById('date');if(date)date.addEventListener('change',()=>{if(open)load();});
  load();
 }
 return {init,load};
})();
