'use strict';
// Fluxo dos agentes: swimlane per case + system view. Everything drawn comes from GET /api/flow (a read-only projection of the
// desk's own records); this file decides nothing and highlights only edges that arrived in the latest poll.
window.DeskFlow=(()=>{
 const NS='http://www.w3.org/2000/svg';
 const ORDER=['citizen','intake','critic','revision','location','tool:','needs','hazard_critic','credibility','duplicate_reviewer','hydro','zetaris','decide','callback_planner','operator','crew','mission_planner','supervisor','place_memory','red_team','judge','regression','nightshift'];
 const STATUS={ok:'ok',failed:'falhou',fallback:'regra determinística'};
 const KIND={message:'mensagem',reply:'resposta',call:'chamada',handoff:'repasse',tool_call:'ferramenta',decision:'decisão',callback_ask:'pergunta de retorno',human_action:'ação humana',
  alert:'alerta',recheck:'re-checagem',mission_proposal:'proposta de missão',field_report:'relato de campo',memory_proposal:'memória proposta',attack:'ataque',verdict:'veredito',proposal:'proposta de regressão',data:'dado'};
 const LOOP={critic_revision:'Crítico → revisão',location_tools:'Localização: passos de ferramenta',callback:'Retorno: pergunta → resposta → nova decisão',supervisor:'Supervisor: alerta → operador → re-checagem',
  mission:'Missão: proposta → aprovação → equipe → caso',redteam:'Red-team: ataque → juiz → humano → regressão',memory:'Memória: proposta → aprovação humana'};
 let ctx=null,sys={edges:[],nodes:[],stats:{},open_loops:[],loops:[],cursor:null,clock:null},cases=new Map(),timer=null,detail=null;
 const rank=id=>{const i=ORDER.findIndex(k=>k.endsWith(':')?id.startsWith(k):k===id);return i<0?ORDER.length:i;};
 const hhmm=t=>String(t||'').slice(11,16);
 const svg=(tag,attrs,text)=>{const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
 const fmtS=s=>typeof s==='number'?(s<10?s.toFixed(2):s.toFixed(1))+' s':'—';
 const age=m=>m==null?'—':m>=120?`${Math.round(m/60)} h`:`${Math.round(m)} min`;
 // ---- pure layout (also exercised by the node smoke test)
 function layout(nodes,edges,opt={}){
  const left=opt.left||176,col=opt.col||44,row=opt.row||34,top=opt.top||12;
  const used=new Set();for(const e of edges){used.add(e.src);used.add(e.dst);}
  const lanes=nodes.filter(n=>used.has(n.id)).sort((a,b)=>rank(a.id)-rank(b.id)||a.id.localeCompare(b.id));
  const y=new Map(lanes.map((n,i)=>[n.id,top+row/2+i*row]));
  const ordered=[...edges].sort((a,b)=>(a.src_kind===b.src_kind?a.seq-b.seq:(a.t||0)-(b.t||0))||a.id.localeCompare(b.id,undefined,{numeric:true}));
  const marks=ordered.map((e,i)=>({edge:e,x:left+(i+.5)*col,y1:y.get(e.src),y2:y.get(e.dst)}));
  return {lanes,marks,width:left+ordered.length*col+30,height:top+lanes.length*row+26,left,row,top};
 }
 const edgeClass=e=>`flow-edge st-${e.status}${e.human_gate?' gate':''}${e.fresh?' flow-fresh':''}`;
 function drawSwimlane(parent,graph){
  const L=layout(graph.nodes,graph.edges),box=ctx.el('div',undefined,'flow-scroll');
  if(!L.lanes.length){parent.append(ctx.el('p','Nenhum evento registrado para este caso.','muted'));return;}
  const s=svg('svg',{width:L.width,height:L.height,role:'group','aria-label':'Fluxo de agentes no tempo',class:'flow-svg'});
  const defs=svg('defs');for(const [id,cls] of [['arr','arrow-ok'],['arr-f','arrow-failed'],['arr-b','arrow-fallback']]){const m=svg('marker',{id:'flow-'+id,viewBox:'0 0 8 8',refX:'7',refY:'4',markerWidth:'7',markerHeight:'7',orient:'auto'});m.append(svg('path',{d:'M0,0 L8,4 L0,8 z',class:cls}));defs.append(m);}s.append(defs);
  L.lanes.forEach((n,i)=>{const y=L.top+i*L.row;s.append(svg('rect',{x:0,y,width:L.width,height:L.row,class:'flow-lane'+(i%2?' alt':'')+' k-'+n.kind}));
   s.append(svg('line',{x1:L.left-8,x2:L.width-8,y1:y+L.row/2,y2:y+L.row/2,class:'flow-axis'}));
   const t=svg('text',{x:8,y:y+L.row/2+4,class:'flow-lane-label k-'+n.kind,tabindex:0,role:'button','aria-label':'Agente '+n.label},(n.kind==='human'?'◆ ':'')+n.label);
   t.onclick=()=>showNode(n,graph);t.onkeydown=e=>{if(e.key==='Enter')showNode(n,graph);};s.append(t);});
  let last='';
  for(const m of L.marks){const e=m.edge;
   const g=svg('g',{class:edgeClass(e),tabindex:0,role:'button','aria-label':`${e.label}: ${e.payload}. Estado: ${STATUS[e.status]||e.status}`,'data-edge':e.id});
   const mk=e.status==='failed'?'flow-arr-f':e.status==='fallback'?'flow-arr-b':'flow-arr';
   if(m.y1===m.y2)g.append(svg('circle',{cx:m.x,cy:m.y1,r:6,class:'flow-dot'}));
   else{g.append(svg('line',{x1:m.x,x2:m.x,y1:m.y1,y2:m.y2+(m.y2>m.y1?-7:7),class:'flow-line','marker-end':`url(#${mk})`}));g.append(svg('line',{x1:m.x,x2:m.x,y1:m.y1,y2:m.y2,class:'flow-hit'}));}
   g.append(svg('circle',{cx:m.x,cy:m.y1,r:3,class:'flow-src'}));
   if(e.human_gate)g.append(svg('rect',{x:m.x-6,y:m.y2-6,width:12,height:12,class:'flow-gate',transform:`rotate(45 ${m.x} ${m.y2})`}));
   if(e.status==='failed')g.append(svg('text',{x:m.x+7,y:m.y2-6,class:'flow-flag'},'✕'));else if(e.status==='fallback')g.append(svg('text',{x:m.x+7,y:m.y2-6,class:'flow-flag'},'≈'));
   g.onclick=()=>showEdge(e);g.onkeydown=ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();showEdge(e);}};
   g.append(svg('title',{},`${hhmm(e.ts)} · ${e.label} — ${e.payload}`));s.append(g);
   const lbl=hhmm(e.ts);if(lbl&&lbl!==last){s.append(svg('text',{x:m.x-12,y:L.height-8,class:'flow-time'},lbl));last=lbl;}}
  box.append(s);parent.append(box);
 }
 function row(k,v){const r=ctx.el('div',undefined,'flow-kv');r.append(ctx.el('b',k),ctx.el('span',v==null||v===''?'—':String(v)));return r;}
 function showEdge(e){if(!detail)return;detail.replaceChildren(ctx.el('h4',`${e.label} · ${e.src} → ${e.dst}`),row('Resumo (campos repassados)',e.payload),row('Estado',STATUS[e.status]||e.status),
   row('Tipo',KIND[e.kind]||e.kind),row('Hora (relógio do replay)',e.ts),row('Latência',fmtS(e.latency_s)),row('Modelo',e.model||(e.status==='fallback'?'nenhum — regra determinística':'—')),
   row('Comprovante (receipt)',e.receipt||'—'),row('Versão do caso',e.version),row('Porta humana',e.human_gate?'sim — nada segue sem decisão do operador':'não'),
   row('Dados simulados',e.simulated?'sim [SIMULADO]':'não'),ctx.evidence('Conteúdo registrado',e.detail||{}));}
 function showNode(n,graph){if(!detail)return;const ins=graph.edges.filter(e=>e.dst===n.id),outs=graph.edges.filter(e=>e.src===n.id);
  detail.replaceChildren(ctx.el('h4',`${n.label} (${n.kind})`),row('Eventos registrados',n.event_count));
  for(const [title,list] of [['Entradas',ins],['Saídas',outs]]){const d=ctx.el('div');d.append(ctx.el('strong',`${title} (${list.length})`));const ul=ctx.el('ul',undefined,'flow-io');
   for(const e of list.slice(-12)){const li=ctx.el('li');li.append(ctx.button(`${hhmm(e.ts)} ${e.src}→${e.dst}: ${e.payload}`,()=>showEdge(e),'flow-link'));ul.append(li);}
   if(!list.length)ul.append(ctx.el('li','nenhuma','muted'));d.append(ul);detail.append(d);}}
 function loopList(parent,loops,open){
  const ul=ctx.el('ul',undefined,'flow-loops');
  for(const l of loops){const li=ctx.el('li',undefined,'flow-loop '+l.status);
   li.append(ctx.el('strong',LOOP[l.kind]||l.kind),ctx.el('span',` · ${l.status==='open'?'ABERTO':'fechado'} · ${l.iterations} iteração(ões)`,'flow-loop-state'));
   li.append(ctx.el('p',`${l.outcome||'—'}${l.status==='open'?` · aberto há ${age(l.age_min)}`:l.duration_s!=null?` · levou ${age(l.duration_s/60)}`:''}`));
   const cid=(l.case_ids||[])[0];if(cid&&ctx.openCase)li.append(ctx.button('Abrir caso',()=>ctx.openCase(cid)));
   li.append(ctx.evidence('Detalhes do laço',l.detail||{}));ul.append(li);}
  if(!loops.length)ul.append(ctx.el('li',open?'Nenhum laço aberto.':'Nenhum laço detectado nos registros.','muted'));parent.append(ul);}
 function legend(parent){const d=ctx.el('details');d.append(ctx.el('summary','Legenda'));
  d.append(ctx.el('p','Seta contínua = repasse ok · tracejada vermelha ✕ = falhou · tracejada âmbar ≈ = regra determinística no lugar do modelo · losango ◆ = porta humana (nada segue sem o operador). Só há destaque pulsante para eventos que chegaram na última atualização.','muted'));parent.append(d);}
 // ---- data
 function mergeEdges(list,incoming,fresh){const seen=new Set(list.map(e=>e.id));let n=0;for(const e of incoming){if(seen.has(e.id))continue;e.fresh=fresh;list.push(e);n++;}return n;}
 function mergeNodes(list,incoming){for(const n of incoming){const i=list.findIndex(x=>x.id===n.id);if(i<0)list.push(n);else list[i]=n;}}
 async function fetchSystem(first){
  const r=await ctx.api('/api/flow'+(sys.cursor&&!first?`?since=${encodeURIComponent(sys.cursor)}`:''));
  if(first){sys.edges=[];sys.nodes=[];}
  for(const e of sys.edges)e.fresh=false;
  const n=mergeEdges(sys.edges,r.edges||[],!first);mergeNodes(sys.nodes,r.nodes||[]);
  Object.assign(sys,{stats:r.stats,open_loops:r.open_loops,loops:r.loops,cursor:r.cursor,clock:r.clock});return n;
 }
 async function fetchCase(id,first){
  let st=cases.get(id);if(!st||first){st={edges:[],nodes:[],loops:[],cursor:null};cases.set(id,st);}
  const r=await ctx.api(`/api/flow?case_id=${encodeURIComponent(id)}`+(st.cursor&&!first?`&since=${encodeURIComponent(st.cursor)}`:''));
  for(const e of st.edges)e.fresh=false;
  const n=mergeEdges(st.edges,r.edges||[],st.cursor!=null&&!first);mergeNodes(st.nodes,r.nodes||[]);Object.assign(st,{loops:r.loops||[],cursor:r.cursor,clock:r.clock});return n;
 }
 const pollMs=()=>{const tl=document.getElementById('timeline-panel');return tl&&!tl.hidden?1000:2500;};
 // ---- views
 function renderCase(body,c){
  const wrap=ctx.el('section',undefined,'flow-case'),lane=ctx.el('div'),loops=ctx.el('div');wrap.id='flow-case-view';
  detail=ctx.el('div',undefined,'flow-detail');detail.setAttribute('aria-live','polite');detail.append(ctx.el('p','Selecione uma seta ou um agente.','muted'));
  wrap.append(ctx.el('h3','Fluxo dos agentes neste caso'),ctx.el('p','Cada seta é um repasse registrado (hora do replay, ordem do diário). Clique numa seta para ver conteúdo e comprovante; clique num agente para ver o que entrou e saiu.','muted'),lane,detail,ctx.el('h3','Laços neste caso'),loops);
  legend(wrap);body.append(wrap);const id=c.case_id;
  const draw=()=>{const st=cases.get(id);lane.replaceChildren();loops.replaceChildren();if(!st)return;drawSwimlane(lane,st);loopList(loops,st.loops,false);};
  lane.append(ctx.el('p','Carregando…','muted'));
  fetchCase(id,true).then(draw).catch(e=>lane.replaceChildren(ctx.el('p',e.message,'danger')));
  clearInterval(timer);
  timer=setInterval(async()=>{if(!wrap.isConnected){clearInterval(timer);return;}try{if(await fetchCase(id,false))draw();}catch{}},pollMs());
 }
 function renderSystem(root){
  root.replaceChildren(ctx.el('h1','Fluxo · agentes e laços em execução'),ctx.el('p','Contagens vêm das chamadas e eventos já registrados. "Últimos 15 min" usa o relógio do replay (o diário não grava hora de parede).','muted'));
  const body=ctx.el('div');root.append(body);let sig='';
  const draw=()=>{body.replaceChildren();
   const t=ctx.el('table',undefined,'flow-stats'),h=ctx.el('tr');['Agente / ferramenta','Chamadas','Falhas','Regra no lugar do modelo','Latência média','Últimos 15 min','Última'].forEach(x=>h.append(ctx.el('th',x)));const th=ctx.el('thead');th.append(h);t.append(th);
   const tb=ctx.el('tbody'),names=Object.fromEntries(sys.nodes.map(n=>[n.id,n.label]));
   for(const [id,s] of Object.entries(sys.stats||{}).sort((a,b)=>rank(a[0])-rank(b[0]))){const tr=ctx.el('tr');if(s.failures)tr.className='bad';
    [names[id]||id,s.calls,s.failures,s.fallbacks,fmtS(s.mean_latency_s),s.recent_calls,hhmm(s.last_ts)||'—'].forEach(v=>tr.append(ctx.el('td',String(v))));tb.append(tr);}
   t.append(tb);body.append(t,ctx.el('h2',`Laços abertos (${(sys.open_loops||[]).length}) · mais antigo primeiro`));loopList(body,sys.open_loops||[],true);
   body.append(ctx.el('h2','Últimos repasses'));const ul=ctx.el('ul',undefined,'flow-recent');
   for(const e of sys.edges.slice(-25).reverse()){const li=ctx.el('li',undefined,edgeClass(e).replace('flow-edge','flow-item')),cid=(e.case_ids||[])[0];
    li.append(ctx.el('span',`${hhmm(e.ts)} ${e.src} → ${e.dst} · ${e.label}: ${e.payload}`));if(cid&&ctx.openCase)li.append(ctx.button('Abrir caso',()=>ctx.openCase(cid)));ul.append(li);}
   body.append(ul);legend(body);};
  const signature=()=>JSON.stringify([sys.cursor,sys.stats,(sys.open_loops||[]).map(l=>[l.id,l.status,l.iterations,l.outcome])]);
  fetchSystem(true).then(()=>{sig=signature();draw();}).catch(e=>body.replaceChildren(ctx.el('p',e.message,'danger')));
  clearInterval(timer);
  timer=setInterval(async()=>{if(root.hidden||!root.isConnected){clearInterval(timer);return;}try{await fetchSystem(false);const s=signature();if(s!==sig){sig=s;draw();}}catch{}},pollMs());
 }
 const stop=()=>clearInterval(timer);
 const api={init:c=>{ctx=c;},renderCase,renderSystem,stop,layout,_state:()=>({sys,cases})};
 if(typeof module!=='undefined')module.exports=api;
 return api;
})();
