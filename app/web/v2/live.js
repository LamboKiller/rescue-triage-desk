'use strict';
// Agentes ao vivo: mapa animado dos agentes. Dados: /api/flow (diário), SSE da execução (runEvent) e eventos do replay (feedReplay).
// Só desenha o que foi registrado; nada aqui decide. Movimento respeita prefers-reduced-motion e pausa com a aba oculta.
window.DeskLive=(()=>{
 const NS='http://www.w3.org/2000/svg';
 // id:[coluna (etapa, esquerda→direita), linha, rótulo, tipo]
 const N={citizen:[0,2,'Cidadão','human'],intake:[1,2,'Leitura','agent'],critic:[2,1,'Crítico','agent'],location:[2,3,'Localização','agent'],revision:[3,0,'Revisão','agent'],needs:[3,2,'Alocação','tool'],tools:[3,4,'Ferramentas','tool'],
  credibility:[4,0,'Credibilidade','agent'],hazard_critic:[4,1,'Perigo','agent'],duplicate_reviewer:[4,2,'Duplicatas','agent'],contradiction:[4,3,'Contradições','agent'],red_team:[4,4,'Red-team','agent'],
  arbiter:[5,1,'Árbitro','agent'],decide:[5,2,'Decisão','tool'],judge:[5,4,'Juiz','tool'],callback_planner:[6,1,'Callback','agent'],operator:[6,2,'◆ Aprovação humana','gate'],
  mission_planner:[7,1,'Planejador','agent'],supervisor:[7,3,'Supervisor','agent'],crew:[8,2,'Equipe','human']};
 const ALIAS={hydro:'tools',zetaris:'tools',place_memory:'tools',regression:'judge',location_agent:'location',credibility_reviewer:'credibility',field_feedback:'crew'};
 const SKEL=['citizen>intake','intake>critic','critic>revision','intake>location','location>tools','location>needs','needs>credibility','needs>hazard_critic','needs>duplicate_reviewer','credibility>decide','hazard_critic>decide',
  'duplicate_reviewer>decide','contradiction>decide','arbiter>decide','revision>location','decide>operator','decide>callback_planner','operator>mission_planner','mission_planner>crew','crew>operator',
  'supervisor>operator','operator>supervisor','red_team>judge','judge>operator'];
 const LOOPS={critic_revision:['Crítico → revisão','Crítico → revisão'],callback:['Retorno','Retorno: pergunta → resposta → nova decisão'],supervisor:['Supervisor','Supervisor: alerta → operador → re-checagem'],
  redteam:['Red-team','Red-team: ataque → juiz → humano → regressão'],mission:['Missão','Missão: proposta → aprovação → equipe'],contradiction:['Contradição','Contradição: fontes divergentes → pergunta'],location_tools:['Ferramentas','Localização: passos de ferramenta']};
 const STATE={ok:'ok',failed:'falhou',fallback:'regra determinística (sem modelo)',active:'em andamento',idle:'sem eventos',wait:'aguardando o operador'};
 const reduce=window.matchMedia?matchMedia('(prefers-reduced-motion: reduce)'):{matches:false};
 let ctx=null,filter='all',timer=null,cursor=null,loops={open:[],closed:[]},ticker=[],views=[],packets=[],raf=0,tick=0,expanded=false,run=null,seen=new Set(),polling=false;
 const nodes=Object.fromEntries(Object.keys(N).map(k=>[k,{id:k,state:'idle',calls:0,fails:0,since:0,dur:null,model:null,receipt:null,inE:null,outE:null}]));
 const edges=new Map();
 const hhmm=t=>String(t||'').slice(11,16);
 const norm=id=>id==null?null:id.startsWith('tool:')?'tools':ALIAS[id]||id;
 const svg=(tag,a,t)=>{const n=document.createElementNS(NS,tag);for(const k in a||{})n.setAttribute(k,a[k]);if(t!==undefined)n.textContent=t;return n;};
 const q=s=>s?`“${String(s).length>90?String(s).slice(0,89)+'…':s}”`:'—';
 const fs=s=>typeof s==='number'?(s<10?s.toFixed(1):Math.round(s))+' s':null;
 function edgeRec(k){let r=edges.get(k);if(!r){r={key:k,count:0,status:null,last:null};edges.set(k,r);}return r;}
 SKEL.forEach(edgeRec);
 function reset(){for(const n of Object.values(nodes))Object.assign(n,{state:'idle',calls:0,fails:0,since:0,dur:null,model:null,receipt:null,inE:null,outE:null,wait:false});
  for(const r of edges.values())Object.assign(r,{count:0,status:null,last:null});ticker=[];seen=new Set();cursor=null;packets=[];}
 // ---- ingest
 function apply(e,fresh){
  if(seen.has(e.id))return;seen.add(e.id);
  const s=norm(e.src),d=norm(e.dst);if(!N[s]||!N[d]||s===d)return;
  const r=edgeRec(s+'>'+d);r.count++;r.status=e.status;r.last=e;
  const D=nodes[d],S=nodes[s];D.calls++;D.inE=e;S.outE=e;
  D.state=e.status==='failed'?'failed':e.status==='fallback'?'fallback':'ok';if(e.status==='failed')D.fails++;
  if(e.model)D.model=e.model;if(e.receipt)D.receipt=e.receipt;if(typeof e.latency_s==='number')D.dur=e.latency_s;
  if(d==='operator')D.wait=!!e.human_gate;if(s==='operator')S.wait=false;
  if(fresh){ticker.unshift({e,s,d});ticker.length=Math.min(ticker.length,8);}
  views.forEach(v=>{v.edge(r);v.node(s);v.node(d);if(fresh){v.hit(r,d);}});
  if(fresh)launch(r.key,e.status);
 }
 function mergeLoops(r){const op=r.open_loops||[];loops.open=filter==='all'?op:op;const cl=new Map(loops.closed.map(l=>[l.id,l]));for(const l of r.loops||[])if(l.status!=='open')cl.set(l.id,l);loops.closed=[...cl.values()];}
 async function fetchFlow(first){
  const base=filter==='all'?'/api/flow?':`/api/flow?case_id=${encodeURIComponent(filter)}&`;
  const since=first?(filter==='all'?'j:0,r:999999999':''):cursor;
  const r=await ctx.api(base+(since?`since=${encodeURIComponent(since)}`:''));
  if(first)loops.closed=[];
  mergeLoops(r);cursor=r.cursor;
  const list=(r.edges||[]).filter(e=>e.src_kind!=='r');
  const fresh=!first;
  list.forEach(e=>apply(e,fresh&&list.length<40));
  if(first||list.length)views.forEach(v=>v.chips());
  views.forEach(v=>v.meta(r));
 }
 async function load(){reset();views.forEach(v=>v.all());try{await fetchFlow(true);}catch(e){views.forEach(v=>v.error(e.message));}}
 const wantPoll=()=>views.some(v=>v.root.isConnected&&(v.full||expanded))&&!document.hidden;
 function sched(){clearTimeout(timer);const tl=document.getElementById('timeline-panel');
  timer=setTimeout(async()=>{if(wantPoll()){try{await fetchFlow(false);}catch{}}sched();},run||(tl&&!tl.hidden)?1000:2500);}
 // ---- live (SSE of a running analysis) and replay events
 const ROLE={intake:'intake',critic:'critic',revision:'revision',location:'location',hazard_critic:'hazard_critic',duplicate_reviewer:'duplicate_reviewer',credibility:'credibility'};
 function say(a,b,text,status){const d=new Date();ticker.unshift({at:String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'),s:a,d:b,e:{payload:text,status:status||'ok'}});ticker.length=Math.min(ticker.length,8);views.forEach(v=>v.ticker());}
 function runEvent(ev){
  if(filter!=='all'&&ev.case_id&&ev.case_id!==filter)return;
  const st=ev.stage||'',role=ROLE[ev.role];
  if(role){const nm=N[role][2];say(role,role,st.endsWith('_started')?`${nm} iniciou`:st.endsWith('_done')?`${nm} concluiu${typeof ev.seconds==='number'?' · '+fs(ev.seconds):''}${ev.model?' · '+ev.model:''}`:`${nm} falhou`,st.endsWith('_error')?'failed':'ok');}
  else if(st==='received')say('citizen','intake','Mensagem recebida');else if(st==='decision')say('decide','operator','Decisão pronta · aguarda aprovação humana');
  if(st==='received'){run=Date.now();setExpanded(true);nodes.citizen.state='ok';pulseEdge('citizen>intake','ok');paint('citizen');}
  if(role){const n=nodes[role],base=st.replace(/_(started|done|error)$/,'');
   if(st.endsWith('_started')){n.state='active';n.since=performance.now();n.model=ev.model||n.model;}
   else if(st.endsWith('_done')){n.state=n.state==='fallback'?'fallback':'ok';n.dur=typeof ev.seconds==='number'?ev.seconds:(n.since?(performance.now()-n.since)/1000:n.dur);n.since=0;n.calls++;if(ev.model)n.model=ev.model;if(ev.receipt)n.receipt=ev.receipt;}
   else if(st.endsWith('_error')){n.state='failed';n.fails++;n.since=0;n.dur=typeof ev.seconds==='number'?ev.seconds:n.dur;}
   n.live={stage:base,case:ev.case_id};paint(role);
   const from={critic:'intake',revision:'critic',location:'intake'}[role];if(from&&st.endsWith('_started'))pulseEdge(from+'>'+role,'ok');}
  if(st==='checks_done'){pulseEdge('location>needs','ok');paint('needs');}
  if(st==='decision'){nodes.decide.state='ok';pulseEdge('needs>decide','ok');pulseEdge('decide>operator','ok');nodes.operator.wait=true;paint('decide');paint('operator');}
  if(st==='done'||st==='error'){run=null;for(const n of Object.values(nodes))if(n.state==='active'){n.state=st==='error'?'failed':'ok';n.since=0;}views.forEach(v=>v.all());fetchFlow(false).catch(()=>{});}
  startClock();
 }
 const RMAP={message_arrived:['citizen','intake'],citizen_reply:['citizen','callback_planner'],supervisor_alert:['supervisor','operator'],supervisor_recheck:['operator','supervisor'],mission_proposed:['operator','mission_planner'],
  mission_approved:['operator','crew'],crew_report:['crew','operator'],decision:['needs','decide'],decision_changed:['needs','decide'],operator_request_callback:['operator','callback_planner']};
 function feedReplay(list){
  for(const e of list||[]){
   if(filter!=='all'&&e.case_id&&e.case_id!==filter)continue;
   let pair=RMAP[e.kind];if(e.kind==='agent_stage'){const n=ROLE[e.role];if(n){nodes[n].state=e.status==='failed'?'failed':'ok';nodes[n].dur=typeof e.seconds==='number'?e.seconds:nodes[n].dur;nodes[n].calls++;paint(n);views.forEach(v=>v.hit(null,n));}continue;}
   if(!pair)continue;const key=pair.join('>');pulseEdge(key,'ok');if(e.kind==='supervisor_alert'||e.kind==='decision')nodes.operator.wait=true;pair.forEach(paint);
   ticker.unshift({e:{ts:e.replay_time,payload:e.text||e.why||e.decision||e.kind,label:e.kind,case_ids:e.case_id?[e.case_id]:[],status:'ok'},s:pair[0],d:pair[1]});ticker.length=Math.min(ticker.length,8);
  }
  views.forEach(v=>v.ticker());
 }
 function pulseEdge(key,status){const r=edgeRec(key);r.count++;r.status=status;views.forEach(v=>{v.edge(r);v.hit(r,key.split('>')[1]);});launch(key,status);}
 function paint(id){views.forEach(v=>v.node(id));}
 // ---- packets (one rAF loop, only while something travels)
 function launch(key,status){if(reduce.matches||document.hidden)return;if(packets.length>24)packets.shift().c.forEach(c=>c.remove());
  const cs=views.map(v=>v.packet(key,status)).filter(Boolean);if(cs.length){packets.push({t0:performance.now(),dur:650,c:cs,key});if(!raf)raf=requestAnimationFrame(frame);}}
 function frame(now){raf=0;packets=packets.filter(p=>{const k=Math.min(1,(now-p.t0)/p.dur);for(const c of p.c){const path=c.path;let pt;try{pt=path.getPointAtLength(path.getTotalLength()*k);}catch{c.remove();continue;}  /* UX2: edge path not laid out yet (empty) -> drop this packet instead of throwing every frame */
        c.setAttribute('cx',pt.x.toFixed(1));c.setAttribute('cy',pt.y.toFixed(1));}
   if(k>=1){p.c.forEach(c=>c.remove());return false;}return true;});if(packets.length)raf=requestAnimationFrame(frame);}
 // ---- active-stage timers (only while a stage is active)
 function startClock(){if(tick)return;tick=setInterval(()=>{let any=false;for(const n of Object.values(nodes))if(n.state==='active'){any=true;views.forEach(v=>v.timer(n));}if(!any){clearInterval(tick);tick=0;}},250);}
 // ---- view
const LEG=[['active','em andamento'],['ok','ok'],['fallback','regra determinística'],['failed','falhou'],['idle','sem eventos'],['wait','◆ aguarda operador']];
 const COLS=1+Math.max(...Object.values(N).map(n=>n[0]));
 function makeView(host,opt){
  const fz=opt.full?13:12,ph=opt.full?32:26,v={root:host,full:!!opt.full,n:{},e:{},pos:{}},{el}=ctx;
  const colw=Array.from({length:COLS},(_,c)=>Math.ceil(Math.max(...Object.values(N).filter(n=>n[0]===c).map(n=>n[2].length))*fz*.62+52));
  const s=svg('svg',{class:'live-svg',role:'group','aria-label':'Mapa ao vivo dos agentes'});
  const defs=svg('defs'),mk=svg('marker',{id:'la'+(v.full?'f':'d'),viewBox:'0 0 8 8',refX:'7',refY:'4',markerWidth:'6',markerHeight:'6',orient:'auto'});mk.append(svg('path',{d:'M0,0L8,4L0,8z',class:'live-arrow'}));defs.append(mk);s.append(defs);
  const eg=svg('g'),ng=svg('g'),pg=svg('g');s.append(eg,ng,pg);
  const tip=el('div',undefined,'live-tip');tip.hidden=true;const info=el('div',undefined,'live-info');info.hidden=true;
  for(const [id,[,,label,kind]] of Object.entries(N)){
   const g=svg('g',{class:'live-node k-'+kind+' s-idle',tabindex:0,role:'button','data-node':id});
   g.append(svg('rect',{class:'ring'}),svg('rect',{class:'body'}),svg('text',{class:'lbl'},label),svg('text',{class:'dur'},''));
   const show=()=>{showTip(v,tip,id,g);};g.onmouseenter=show;g.onfocus=show;g.onmouseleave=()=>{tip.hidden=true;};g.onblur=g.onmouseleave;
   g.onclick=()=>{showInfo(v,info,id);};g.onkeydown=ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();showInfo(v,info,id);}};
   ng.append(g);v.n[id]=g;}
  const path=(a,b)=>{const A=v.pos[a],B=v.pos[b];if(!A||!B)return '';const fw=N[b][0]>N[a][0],o=edges.has(b+'>'+a)?(fw?-4:4):0;
   if(N[b][0]===N[a][0]){const x=A.x+A.w/2,d=B.y>A.y?1:-1;return `M${x},${A.y+d*ph/2} L${x},${B.y-d*ph/2}`;}
   const x1=fw?A.x+A.w:A.x,x2=fw?B.x:B.x+B.w,m=(x1+x2)/2;return `M${x1},${A.y+o} C${m},${A.y+o} ${m},${B.y+o} ${x2},${B.y+o}`;};
  v.layout=()=>{const W=v.wrap.clientWidth,H=v.wrap.clientHeight;if(!W||!H)return;const pad=8,tot=colw.reduce((a,b)=>a+b,0),gap=Math.max(22,(W-2*pad-tot)/(COLS-1)),X=[];let x=pad;colw.forEach((w,i)=>{X[i]=x;x+=w+gap;});
   const width=Math.max(W,Math.ceil(x-gap+pad)),step=Math.min((H-2*pad-ph)/4,ph*2.4),y0=(H-4*step)/2;
   s.setAttribute('width',width);s.setAttribute('height',H);s.setAttribute('viewBox',`0 0 ${width} ${H}`);
   for(const id in N){const [c,r,,kind]=N[id],w=colw[c],y=y0+r*step,rx=kind==='tool'||kind==='gate'?4:ph/2;v.pos[id]={x:X[c],y,w};const g=v.n[id];g.setAttribute('transform',`translate(${(X[c]+w/2).toFixed(1)} ${y.toFixed(1)})`);
    const [ring,body,lbl,dur]=g.children;for(const [r_,m] of [[ring,3],[body,0]]){r_.setAttribute('x',-w/2-m);r_.setAttribute('y',-ph/2-m);r_.setAttribute('width',w+2*m);r_.setAttribute('height',ph+2*m);r_.setAttribute('rx',rx+m);}
    lbl.setAttribute('x',-w/2+9);lbl.setAttribute('y',fz*.36);dur.setAttribute('x',w/2-8);dur.setAttribute('y',fz*.36);}
   for(const k in v.e)v.e[k].setAttribute('d',path(...k.split('>')));};
  v.edgeEl=k=>{let p=v.e[k];if(!p){const [a,b]=k.split('>');if(!N[a]||!N[b])return null;p=svg('path',{d:path(a,b),class:'live-edge','marker-end':`url(#la${v.full?'f':'d'})`});eg.append(p);v.e[k]=p;}return p;};
  SKEL.forEach(k=>v.edgeEl(k));
  v.edge=r=>{const p=v.edgeEl(r.key);if(!p)return;p.setAttribute('class','live-edge'+(r.count?' used':'')+(r.status?' st-'+r.status:''));};
  v.hit=(r,nid)=>{const p=r&&v.e[r.key],g=v.n[nid];if(p){p.classList.add('hit');setTimeout(()=>p.classList.remove('hit'),1400);}if(g){g.classList.add('hit');setTimeout(()=>g.classList.remove('hit'),1400);}};
  v.node=id=>{const g=v.n[id],n=nodes[id];if(!g)return;const st=n.wait?'wait':n.state;g.setAttribute('class',`live-node k-${N[id][3]} s-${st}${g.classList.contains('hit')?' hit':''}${v.sel===id?' sel':''}`);
   g.querySelector('.dur').textContent=n.state==='active'?'':(fs(n.dur)||(n.calls?'×'+(n.calls>99?'99+':n.calls):''));g.setAttribute('aria-label',`${N[id][2]}: ${STATE[st]}${n.calls?`, ${n.calls} registros`:''}`);};
  v.timer=n=>{const g=v.n[Object.keys(nodes).find(k=>nodes[k]===n)];if(g&&n.since)g.querySelector('.dur').textContent=((performance.now()-n.since)/1000).toFixed(1)+' s';};
  v.packet=(key,status)=>{const p=v.e[key]||v.edgeEl(key);if(!p||!v.root.isConnected||!p.getTotalLength)return null;const c=svg('circle',{r:4.5,class:'live-packet st-'+(status||'ok')});c.path=p;pg.append(c);return c;};
  v.all=()=>{Object.keys(N).forEach(v.node);edges.forEach(r=>v.edge(r));};
  v.chips=()=>{};v.meta=()=>{};v.error=m=>{info.hidden=false;info.replaceChildren(el('p',m,'danger'));};v.ticker=()=>{};
  v.svgBox=el('div',undefined,'live-stage');v.wrap=el('div',undefined,'live-canvas');v.wrap.append(s);
  const leg=el('div',undefined,'live-legend');for(const [k,t] of LEG){const sp=el('span',undefined,'lg');sp.append(el('i',undefined,'sw s-'+k),t);leg.append(sp);}
  v.svgBox.append(v.wrap,leg,tip,info);v.svg=s;v.tip=tip;v.info=info;
  if(window.ResizeObserver)new ResizeObserver(()=>v.layout()).observe(v.wrap);
  v.all();v.layout();return v;
 }
 // ABL: contagem real por agente (/api/agents/contribution): disparou / mudou o resultado / avisou / puladas. Só leitura.
 let contrib=null;
 const CROLE={location:'location_agent',credibility:'credibility_reviewer',critic:'critic',revision:'revision',intake:'intake',hazard_critic:'hazard_critic',duplicate_reviewer:'duplicate_reviewer',arbiter:'arbiter'};
 function loadContribution(){fetch('/api/agents/contribution').then(r=>r.ok?r.json():null).then(d=>{if(d&&d.roles)contrib=d;}).catch(()=>{});}
 function contribText(id){const r=contrib&&contrib.roles[CROLE[id]];if(!r)return null;const sk=Object.entries(r.skipped||{}).map(([k,v])=>`${k} ×${v}`).join(', ');
  return `${r.fired} disparos · ${r.changed_outcome} mudaram o resultado · ${r.warned} avisos${sk?' · puladas: '+sk:''} (${contrib.messages} msgs)`;}
 function showTip(v,tip,id,g){const n=nodes[id],st=n.wait?'wait':n.state;tip.replaceChildren();
  const rows=[[N[id][2],STATE[st]],['Modelo',n.model||(n.state==='fallback'?'nenhum — regra determinística':'—')],['Latência',fs(n.dur)||'—'],['Comprovante',n.receipt||'—'],['Registros',`${n.calls}${n.fails?` · ${n.fails} falha(s)`:''}`]];
  const ct=contribText(id);if(ct)rows.push(['Contribuição',ct]);
  rows.forEach(([a,b],i)=>{const d=document.createElement('div');d.className=i?'tip-row':'tip-head';d.textContent=i?`${a}: ${b}`:`${a} · ${b}`;tip.append(d);});
  const b=g.getBoundingClientRect(),r=v.svgBox.getBoundingClientRect();tip.hidden=false;tip.style.left=Math.min(r.width-190,Math.max(4,b.left-r.left-60))+'px';tip.style.top=Math.max(2,b.top-r.top-tip.offsetHeight-6)+'px';}
 function showInfo(v,info,id){v.sel=id;Object.keys(N).forEach(v.node);const n=nodes[id],{el,button}=ctx;info.hidden=false;info.replaceChildren();
  const h=el('div',undefined,'info-head');h.append(el('strong',N[id][2]),button('×',()=>{v.sel=null;info.hidden=true;Object.keys(N).forEach(v.node);},'info-x'));h.lastChild.setAttribute('aria-label','Fechar');info.append(h);
  const line=(lab,e,pick)=>{const p=el('p');p.append(el('b',lab+' '),el('span',e?`${hhmm(e.ts)} ${q(e.payload)}`:'— nada registrado'));if(e&&pick){const cid=(e.case_ids||[])[0];if(cid&&ctx.openCase)p.append(button('abrir caso',()=>ctx.openCase(cid),'link'));}info.append(p);};
  line('Entrada',n.inE,true);line('Saída',n.outE,true);if(n.inE?.detail&&ctx.evidence)info.append(ctx.evidence('Registro completo',n.inE.detail));}
 // ---- dock + full
 function fmtTick(t){const a=N[t.s]?.[2]||t.s,b=N[t.d]?.[2]||t.d;return `${t.at||hhmm(t.e.ts)} ${a===b?a:a+' → '+b} · ${t.e.payload||t.e.label}`;}
 function chipsInto(box){const {el}=ctx;box.replaceChildren();
  for(const [k,[short,full]] of Object.entries(LOOPS)){const op=loops.open.filter(l=>l.kind===k),cl=loops.closed.filter(l=>l.kind===k);
   if(!op.length&&!cl.length&&k!=='critic_revision')continue;const c=el('span',`${short} ${op.length?op.length+' aberto'+(op.length>1?'s':'')+' · ':''}${cl.length} fechado${cl.length===1?'':'s'}`,'loop-chip'+(op.length?' open':''));c.title=full+(op.length?` — ${op.length} em aberto`:'');box.append(c);}
  const sc=ctx.selectedCase?.(),al=sc&&ctx.agentLine?ctx.agentLine(sc):null;if(al)box.append(el('span',al,'loop-chip agent-line'));}
 function mountDock(host){
  const {el,button}=ctx,v=makeView(host,{full:false});views.push(v);
  host.className='live-dock';host.setAttribute('aria-label','Agentes ao vivo');
  const bar=el('div',undefined,'live-bar'),dot=el('span',undefined,'live-dot'),title=el('strong','Agentes ao vivo'),strip=el('span',undefined,'live-strip'),chips=el('span',undefined,'live-chips');
  const sel=el('select',undefined,'live-filter');sel.setAttribute('aria-label','Filtrar por caso');sel.append(new Option('Todos os casos','all'),new Option('Caso selecionado','sel'));
  sel.onchange=()=>setFilter(sel.value==='sel'?(ctx.selected()||'all'):'all');
  const replay=button('↻ Repetir',()=>replayLast(),'live-btn'),big=button('Ampliar',()=>ctx.openFull(),'live-btn'),tog=button(expanded?'▾':'▴',()=>setExpanded(!expanded),'live-btn');tog.setAttribute('aria-label','Recolher ou expandir');tog.id='live-toggle';
  bar.append(dot,title,strip,chips,sel,replay,big,tog);
  const body=el('div',undefined,'live-body'),side=el('ol',undefined,'live-ticker');side.setAttribute('aria-label','Últimos eventos');body.append(v.svgBox,side);
  host.append(bar,body);
   v.chips=()=>{chipsInto(chips);};v.ticker=()=>{side.replaceChildren(...ticker.map(t=>{const li=el('li',fmtTick(t),'st-'+t.e.status);const cid=(t.e.case_ids||[])[0];if(cid&&ctx.openCase){li.tabIndex=0;li.onclick=()=>ctx.openCase(cid);li.onkeydown=ev=>{if(ev.key==='Enter')ctx.openCase(cid);};}return li;}));if(!ticker.length)side.append(el('li','Aguardando eventos.','muted'));};
  const oldNode=v.node;v.node=id=>{oldNode(id);paintStrip(strip);};
  v.meta=()=>{v.ticker();dot.className='live-dot on';};
  v.syncSel=()=>{if(filter!=='all'&&sel.value==='all')sel.value='sel';};
  v.tog=tog;v.ticker();setExpanded(false);return v;
 }
 function paintStrip(strip){if(!strip.isConnected)return;const bad=Object.values(nodes).filter(n=>n.state==='failed').length,fb=Object.values(nodes).filter(n=>n.state==='fallback').length,act=Object.values(nodes).filter(n=>n.state==='active').length;
  const t=act?`${act} em andamento`:bad?`${bad} com falha`:fb?`${fb} em regra determinística`:'';strip.textContent=t;strip.className='live-strip'+(act?' act':bad?' bad':fb?' fb':'');}
 function setExpanded(x){expanded=x;document.body.classList.toggle('live-open',x);const d=document.getElementById('live-dock');if(d)d.classList.toggle('open',x);const t=document.getElementById('live-toggle');if(t)t.textContent=x?'▾':'▴';
  try{window.DeskMap&&window.DeskMap.resize();}catch{}if(x){loadedOnce?fetchFlow(false).catch(()=>{}):lazyLoad();}}
 function setFilter(f){filter=f;load();}
 async function replayLast(){ // repete os últimos eventos do caso/sistema em câmera lenta para demonstração (nada novo é registrado)
  const keep=[...ticker].reverse();if(!keep.length)return;setExpanded(true);
  for(const t of keep){if(document.hidden)break;pulseEdge(t.s+'>'+t.d,t.e.status);await new Promise(r=>setTimeout(r,reduce.matches?0:450));}}
 function mountFull(root){
  const {el,button}=ctx;views=views.filter(x=>!x.full);root.replaceChildren();const v=makeView(root,{full:true});views.push(v);v.root=root;
  const head=el('div',undefined,'live-bar full'),chips=el('div',undefined,'live-chips');head.append(el('h1','Agentes ao vivo'),chips,button('↻ Repetir',()=>replayLast(),'live-btn'));
  const leg=el('p','Passe o mouse: modelo e latência. Clique: última entrada e saída.','muted legend-line');
  const side=el('ol',undefined,'live-ticker wide');
  v.chips=()=>chipsInto(chips);v.ticker=()=>{side.replaceChildren(...ticker.map(t=>el('li',fmtTick(t),'st-'+t.e.status)));if(!ticker.length)side.append(el('li','Aguardando eventos.','muted'));};v.meta=()=>v.ticker();
  const wrap=el('div',undefined,'live-full');wrap.append(v.svgBox,side);root.append(head,leg,wrap);const sys=el('div');sys.id='live-sys';root.append(sys);
  v.chips();v.ticker();window.DeskFlow&&window.DeskFlow.renderSystem(sys,true);loadedOnce?fetchFlow(false).catch(()=>{}):lazyLoad();return v;
 }
 function init(c){ctx=c;document.addEventListener('visibilitychange',()=>{if(!document.hidden&&loadedOnce){fetchFlow(false).catch(()=>{});}});sched();setTimeout(lazyLoad,9000);}
 let loadedOnce=false;
 function lazyLoad(){if(loadedOnce)return;loadedOnce=true;load();loadContribution();}  // UX2: the 600 KB journal is fetched on first use (dock opened / full view) or after 9 s idle, not on first paint
 function refreshChips(){for(const v of views)v.chips&&v.chips();}
 return {init,refreshChips,mountDock,mountFull,runEvent,feedReplay,setFilter,setExpanded,_state:()=>({nodes,edges,loops,filter})};
})();
