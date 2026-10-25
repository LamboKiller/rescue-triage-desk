'use strict';
// Linha do tempo: replay clock + controls + event lanes. Every event comes from GET /api/replay/state (the desk's own log);
// this file decides nothing. Click a marker to open its case.
window.DeskTimeline=(()=>{
 let ctx=null,open=false,state=null,events=[],timer=null,selectedSeq=null,lastRefresh=0;
 const LANES=[['message','Mensagens'],['agent','Agentes'],['decision','Decisão'],['supervisor','Supervisor'],['mission','Missão'],['feedback','Retorno de campo']];
 const KIND={message_arrived:'Mensagem chegou',citizen_reply:'Resposta do cidadão (simulada)',agent_stage:'Etapa de agente',decision:'Decisão',decision_changed:'Decisão mudou',
  operator_request_callback:'Operador pediu retorno',operator_confirm_location:'Operador confirmou local',resource_registered:'Recurso registrado',
  supervisor_tick:'Tick do supervisor',supervisor_alert:'Alerta do supervisor',supervisor_recheck:'Re-checagem',alert_decided:'Operador decidiu alerta',alert_not_found:'Alerta não encontrado',
  mission_proposed:'Missão proposta',mission_approved:'Missão aprovada pelo operador',mission_blocked:'Missão bloqueada',mission_proposal_missing:'Sem proposta',
  crew_report:'Relato da equipe',requeue:'Pessoas restantes voltaram à fila',error:'Falha',finished:'Replay terminou'};
 const hhmm=t=>String(t||'').slice(11,16);
 function summary(e){
  const bits=[`${hhmm(e.replay_time)} · ${KIND[e.kind]||e.kind}`];
  if(e.scenario_input)bits.push('[entrada do cenário]');
  if(e.kind==='message_arrived'||e.kind==='citizen_reply'||e.kind==='crew_report')bits.push(`“${e.text}”`);
  if(e.kind==='agent_stage')bits.push(`${e.role||e.stage}${e.seconds?` (${e.seconds} s)`:''}`);
  if(e.kind==='decision')bits.push(`${e.decision}${e.decision_reason?` — ${e.decision_reason}`:''}`);
  if(e.kind==='decision_changed')bits.push(`${e.before} → ${e.after}`);
  if(e.kind==='supervisor_tick')bits.push(`${e.cases_seen} casos · ${e.findings} achados · ${e.alerts} alertas`);
  if(e.kind==='supervisor_alert')bits.push(e.why);
  if(e.kind==='supervisor_recheck')bits.push(e.delta);
  if(e.kind==='alert_decided')bits.push(e.summary||e.decision);
  if(e.kind==='mission_proposed')bits.push(`${e.asset||'—'} · ${e.stops.length} parada(s)`);
  if(e.kind==='mission_blocked'||e.kind==='mission_proposal_missing')bits.push(e.reason);
  if(e.kind==='mission_approved')bits.push(`${e.asset||'—'} · ${e.status}`);
  if(e.kind==='crew_report')bits.push(`→ ${e.status}${e.remaining_n!=null?` · restam ${e.remaining_n}`:''}${e.conflicts?.length?` · conflito: ${e.conflicts.join(' ')}`:''}`);
  if(e.kind==='requeue')bits.push(`${e.remaining_n} pessoa(s) · ${e.decision}`);
  if(e.kind==='error')bits.push(e.message);
  if(e.kind==='resource_registered')bits.push(`${e.unit_id} · ${e.asset} · capacidade ${e.capacity} (sintético)`);
  return bits.join(' · ');
 }
 async function poll(){
  try{
   const since=events.length?events[events.length-1].seq:0;
   const next=await ctx.api(`/api/replay/state?since=${since}`);
   if(next.event_count<events.length)events=[];
   state={...next,events:undefined};events=events.concat(next.events||[]);
   draw();
   const now=Date.now();
   if((next.events||[]).some(e=>e.lane!=='agent'&&e.kind!=='supervisor_tick')&&now-lastRefresh>2500){lastRefresh=now;ctx.refresh().catch(()=>{});}
  }catch(e){ctx.notice(e.message,true);}
  clearTimeout(timer);
  if(open)timer=setTimeout(poll,state?.status==='running'?1000:2500);
 }
 async function post(path,body){
  try{const r=await ctx.api(path,body||{});state={...r,events:undefined};if(r.clock?.day)await ctx.setDay(r.clock.day);}
  catch(e){ctx.notice(e.message,true);}
  await poll();
 }
 function marker(e){
  const {el}=ctx,b=el('button',undefined,`tl-mark tl-${e.lane}${e.scenario_input?' tl-input':''}${e.kind==='error'?' tl-error':''}`);
  b.type='button';b.style.left=`${Math.min(100,Math.max(0,e.t_min/(state.clock.end_min||1)*100))}%`;
  b.title=summary(e);b.setAttribute('aria-label',summary(e));b.dataset.seq=e.seq;b.dataset.kind=e.kind;
  if(e.seq===selectedSeq)b.classList.add('tl-selected');
  b.onclick=()=>{selectedSeq=e.seq;if(e.case_id)ctx.select(e.case_id);draw();};
  return b;
 }
 function draw(){
  const root=document.getElementById('timeline-panel');if(!root)return;
  const toggle=document.getElementById('timeline-toggle');
  root.hidden=!open;if(!open||!state)return;
  const {el,button}=ctx,end=state.clock.end_min||1,t=state.clock.t_min||0;
  root.replaceChildren();
  const top=el('div',undefined,'tl-row');
  const clock=el('strong',hhmm(state.clock.replay_time)+' BRT','tl-clock');clock.id='tl-clock';
  top.append(el('h2','Linha do tempo'),clock,el('span',`${state.clock.day} · ${state.status}`,'tl-status'));
  const run=state.status==='running',paused=state.status==='paused',active=run||paused;
  const start=button(state.status==='finished'||state.status==='stopped'?'Reiniciar':'Iniciar',()=>post('/api/replay/start',{speed:state.speed||10}),'primary');
  start.id='tl-start';start.disabled=active;
  const pause=button(paused?'Continuar':'Pausar',()=>post('/api/replay/pause',{paused:!paused}));pause.id='tl-pause';pause.disabled=!active;
  top.append(start,pause);
  for(const s of state.speeds||[1,10,60]){const b=button(`${s}×`,()=>post('/api/replay/speed',{speed:s}));b.id='tl-speed-'+s;b.setAttribute('aria-pressed',String(state.speed===s));if(state.speed===s)b.classList.add('primary');b.disabled=!active;top.append(b);}
  top.append(button('Fechar',()=>{open=false;draw();}));
  const bar=el('progress');bar.max=end;bar.value=t;bar.className='tl-progress';bar.setAttribute('aria-label','Progresso do replay');
  root.append(top,el('p',`${state.scenario?.name||''} — cenário sintético. Entradas do cenário (mensagens, ações de operador/equipe, respostas simuladas) vêm do arquivo; toda decisão vem do pipeline e dos agentes em tempo de execução.`,'muted'),bar);
  if(state.warning)root.append(el('p',state.warning,'tl-warning'));
  const lanes=el('div',undefined,'tl-lanes');
  for(const [lane,label] of LANES){
   const row=el('div',undefined,'tl-lane'),track=el('div',undefined,'tl-track');row.dataset.lane=lane;
   const list=events.filter(e=>e.lane===lane);
   for(const e of list)track.append(marker(e));
   const now=el('span',undefined,'tl-now');now.style.left=`${Math.min(100,t/end*100)}%`;track.append(now);
   row.append(el('span',label,'tl-label'),track);lanes.append(row);
  }
  root.append(lanes);
  const chosen=events.find(e=>e.seq===selectedSeq),log=el('ol',undefined,'tl-log');log.setAttribute('aria-label','Registro de eventos');
  if(chosen)root.append(el('p',summary(chosen),'tl-detail'));
  for(const e of events.filter(x=>x.kind!=='agent_stage').slice(-40).reverse()){
   const li=el('li'),b=button(summary(e),()=>{selectedSeq=e.seq;if(e.case_id)ctx.select(e.case_id);draw();},'tl-item');b.disabled=false;li.append(b);log.append(li);
  }
  root.append(log);
  if(toggle)toggle.textContent=active?`Linha do tempo · ${hhmm(state.clock.replay_time)}`:'Linha do tempo';
 }
 function init(c){
  ctx=c;const bar=document.querySelector('.status-bar'),anchor=document.getElementById('resources');
  if(!bar||document.getElementById('timeline-toggle'))return;
  const b=c.button('Linha do tempo',async()=>{open=!open;if(open)await poll();else draw();});b.id='timeline-toggle';
  bar.insertBefore(b,anchor);
 }
 return {init,poll,summary};
})();
