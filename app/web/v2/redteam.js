'use strict';
window.DeskRedTeam=(()=>{
 let ctx=null,data=null,replay=null,open=false,busy=false,panel=null;
 const pct=r=>r===null||r===undefined?'—':Math.round(r*100)+'%';
 async function load(){try{data=await ctx.api('/api/redteam');}catch(e){ctx.notice(e.message,true);return;}draw();}
 async function post(path,body,ok){
  if(busy)return;busy=true;draw();
  try{const r=await ctx.api(path,body);data=r;if(r.replay)replay=r.replay;if(ok)ctx.notice(ok(r));}catch(e){ctx.notice(e.message,true);}
  busy=false;draw();
 }
 const run=()=>post('/api/redteam/run',{n:Math.max(1,Math.min(48,Number(document.getElementById('rt-n').value)||24))},r=>`Red team: ${r.last_run.summary.passed}/${r.last_run.summary.total} passaram · ${r.last_run.summary.unsafe_send} envios inseguros.`);
 const rerun=()=>post('/api/redteam/rerun',{},r=>`Regressões reexecutadas: ${r.replay.filter(x=>x.fixed).length} corrigidas, ${r.replay.filter(x=>x.regressed).length} regrediram.`);
 const decide=(p,decision)=>post(`/api/redteam/proposals/${encodeURIComponent(p.proposal_id)}`,{decision,actor:'operador'},()=>decision==='approve'?'Caso aprovado e anexado ao conjunto de regressão.':'Caso rejeitado.');
 function proposalCard(p){
  const {el,button}=ctx,card=el('article',undefined,'rt-case');
  const head=el('div',undefined,'rt-row');head.append(el('strong',p.category),el('span',`${p.decision||'—'}${p.unsafe_send?' · envio inseguro':''}`,'rt-badge '+(p.unsafe_send?'rt-bad':'rt-warn')));
  card.append(head,el('p',p.message,'rt-msg'));
  for(const r of p.reasons||[])card.append(el('small',r));
  if(p.status==='pending'){const row=el('div',undefined,'rt-row');const ok=button('Aprovar como regressão',()=>decide(p,'approve'),'primary');ok.id='rt-approve-'+p.proposal_id;row.append(ok,button('Rejeitar',()=>decide(p,'reject')));card.append(row);}
  else card.append(el('small',p.status==='approved'?'Aprovado — vale como regressão aberta até passar.':'Rejeitado.','muted'));
  return card;
 }
 function draw(){
  const {el,button}=ctx;panel.hidden=!open;
  const pending=(data?.proposals||[]).filter(p=>p.status==='pending').length;
  const t=document.getElementById('redteam-toggle');if(t)t.textContent=pending?`Red team (${pending})`:'Red team';
  if(!open||!data)return;
  panel.replaceChildren();
  const top=el('div',undefined,'rt-row');top.append(el('h2','Red team · auto-jogo'),button('Fechar',()=>{open=false;draw();}));
  const n=el('input');n.type='number';n.id='rt-n';n.min='1';n.max='48';n.value='24';n.setAttribute('aria-label','Mensagens por rodada');
  const controls=el('div',undefined,'rt-row');const go=button(busy?'Executando…':'Rodar rodada',run,'primary');go.id='rt-run';go.disabled=busy;
  const again=button('Reexecutar regressões',rerun);again.id='rt-rerun';again.disabled=busy;controls.append(n,go,again);
  panel.append(top,el('p',`Modo ${data.mode==='live'?'ao vivo (modelo escreve os ataques)':'offline (ataques roteirizados)'}. Um atacante declara categoria e desfechos aceitáveis antes da execução; o código (não um modelo) julga. Falhas viram propostas; só um humano as aprova.`,'muted'),controls);
  const s=data.last_run?.summary;
  if(!s)panel.append(el('p','Nenhuma rodada ainda.','muted'));
  else{
   panel.append(el('p',`Última rodada: ${s.passed}/${s.total} (${pct(s.rate)}) · envios inseguros: ${s.unsafe_send}`,'rt-sum'));
   const tbl=el('table',undefined,'rt-table');tbl.append(Object.assign(el('caption','Taxa de aprovação por categoria')));
   for(const c of data.categories){const v=s.categories[c.id]||{runs:0,passed:0,rate:null};const tr=el('tr',undefined,v.runs&&v.passed<v.runs?'rt-fail':'');tr.title=c.desc;tr.append(el('td',c.id),el('td',`${v.passed}/${v.runs}`),el('td',pct(v.rate)));tbl.append(tr);}
   panel.append(tbl);
  }
  if(replay){const d=el('details');d.open=true;d.append(el('summary',`Regressões reexecutadas (${replay.length})`));
   for(const r of replay)d.append(el('p',`${r.id} · ${r.category}: ${r.fixed?'CORRIGIDO':r.regressed?'REGREDIU':r.passed?'passa':'ainda falha'}${r.reasons.length?' — '+r.reasons[0]:''}`,'rt-recheck rt-'+(r.fixed||r.passed?'ok':'bad')));
   panel.append(d);}
  const list=el('div',undefined,'rt-cases');
  const props=(data.proposals||[]).filter(p=>p.status==='pending');
  list.append(el('h3',`Novas p/ revisar: ${props.length} · ${data.regression.length} casos de regressão (${data.regression.filter(r=>r.known_open).length} abertos)`));
  if(!props.length)list.append(el('p','Nenhuma falha pendente.','muted'));
  for(const p of props)list.append(proposalCard(p));
  panel.append(list);
 }
 function init(c){
  ctx=c;const bar=document.querySelector('.status-bar'),anchor=document.getElementById('resources');
  if(!bar||document.getElementById('redteam-toggle'))return;
  panel=document.createElement('section');panel.id='redteam-panel';panel.className='redteam-panel';panel.setAttribute('aria-label','Red team');panel.hidden=true;document.body.append(panel);
  const b=c.button('Red team',async()=>{open=!open;if(open)await load();else draw();});b.id='redteam-toggle';
  bar.insertBefore(b,anchor);load();
 }
 return {init,load};
})();
