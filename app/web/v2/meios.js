'use strict';
// Meios = one decision screen: [Recomendado · ETA · capacidade · motivo] [Despachar] [Trocar] + <=5 real checks +
// Rota / Desembarque cards. Raw codes live in the "Detalhes técnicos" drawer. Everything shown is computed by code.
window.DeskMeios=(()=>{
  const GROUPS=[
    {key:'local',text:'Local e pessoas conferidos com quem pediu (endereço, quantas pessoas, crianças, idosos, animais)',re:/^(R016|R019B|R094|REPORT_DATE|CAPACITY_UNKNOWN)$/},
    {key:'agua',text:'Água e profundidade no trajeto verificadas (correnteza, detritos, risco elétrico)',re:/^(R001|R017|R021|R040|R045|D_|DEPTH_|DRAFT_)/},
    {key:'rota',text:'Rota estimada, embarque e acesso conferidos',re:/^ROUTE_/},
    {key:'equipe',text:'Equipe e equipamento prontos (dia/noite, comunicação, combustível, proteção)',re:/./},
    {key:'ok',text:'Li as cautelas deste meio e aprovo o despacho',re:/^$/}
  ];
  const ticks=new Map(),cache=new Map(),routes=new Map();let gen=0;
  const fmt=(n,d=1)=>Number.isFinite(n)?n.toLocaleString('pt-BR',{maximumFractionDigits:d}):'—';
  const km=m=>Number.isFinite(m)?fmt(m/1000)+' km':'distância a confirmar';
  const VERDICT={suitable:'adequado',caution:'com cautelas',unsafe:'inadequado'};
  function checksFor(row,c){
    const out=GROUPS.map(g=>({key:g.key,text_pt:g.text,codes:[],texts:[]}));
    for(const x of row.confirmation_checklist||[]){const i=GROUPS.findIndex(g=>g.key!=='ok'&&g.re.test(x.code));const slot=out[i<0?3:i];slot.codes.push(x.code);slot.texts.push(x.text_pt);}
    const need=out.filter(g=>g.codes.length||g.key==='ok'||g.key==='local'&&!c.location_confirmed);
    if(!c.location_confirmed){const l=need.find(g=>g.key==='local');l.text_pt='Localização confirmada com quem pediu (endereço e ponto no mapa)';}
    return need;
  }
  const plain=t=>t.startsWith('Revisão humana necessária')?'Há pendências abertas ou dados em conflito: resolva no Resumo ou no Retorno.':t.replace(/ (do|no) caso [0-9a-f]{24}/,'');
  function blockers(c){
    const r=c.result||{};
    if(String(c.status).startsWith('ASSIGNED:'))return 'Já está em missão.';
    if(r.decision==='REVIEW_REQUIRED')return 'Caso em revisão humana: resolva a pendência na aba Resumo.';
    if(r.decision==='CALLBACK')return 'Falta informação: peça retorno antes de despachar.';
    if(r.decision!=='SEND_CANDIDATE')return 'Este caso ainda não é candidato a envio.';
    if(!['proposed','PARTIAL'].includes(c.status))return 'Estado atual do caso não permite novo despacho.';
    return '';
  }
  function getAssets(api,c,day){
    const key=`${c.case_id}:${c.version}:${day}`;
    if(!cache.has(key)){const p=api(`/api/cases/${encodeURIComponent(c.case_id)}/assets?date=${encodeURIComponent(day)}`);cache.set(key,p);p.catch(()=>cache.delete(key));if(cache.size>40)cache.delete(cache.keys().next().value);}
    return cache.get(key);
  }
  function getRoute(api,c,unit,day){
    const key=`${c.case_id}:${unit}:${day}`;
    if(!routes.has(key)){const p=api(`/api/cases/${encodeURIComponent(c.case_id)}/route?unit=${encodeURIComponent(unit)}&date=${encodeURIComponent(day)}`);routes.set(key,p);p.catch(()=>routes.delete(key));if(routes.size>40)routes.delete(routes.keys().next().value);}
    return routes.get(key);
  }
  async function render(body,c,ctx){
    const {api,el,button,evidence,notice,refresh,day}=ctx,app=window.DeskApp,my=++gen;
    const root=el('section',undefined,'mx');body.append(root);
    root.append(el('p','Calculando o meio recomendado…','muted'));
    let data;try{data=await getAssets(api,c,day);}catch(e){root.replaceChildren(el('p',`Não foi possível avaliar os meios: ${e.message}`,'danger'),button('Tentar de novo',()=>{cache.clear();app.redraw();}));return;}
    if(my!==gen||!root.isConnected)return;
    const rows=data.top3||[],block=blockers(c);
    if(!rows.length){
      root.replaceChildren(el('h3','Nenhum meio disponível agora'),el('p',block||'Nenhuma unidade elegível. Veja os motivos nos detalhes.','danger'));
      root.append(details(el,evidence,data,c,null,null));return;
    }
    const pref=app.S.units.get(c.case_id),idx=Math.max(0,rows.findIndex(r=>r.id===pref)),row=rows[idx];
    const sel=`${c.case_id}:${c.version}:${row.id}`,groups=checksFor(row,c),state=ticks.get(sel)||new Set();ticks.set(sel,state);
    const people=c.fields?.people?.value;
    const rec=el('div',undefined,'mx-rec'),head=el('div',undefined,'mx-head');
    head.append(el('small',idx===0?'RECOMENDADO':`ESCOLHIDO (recomendado: ${rows[0].label_pt})`,'mx-tag'),el('h3',`${row.synthetic?'[SIMULADO] ':''}${row.label_pt}`),el('span',VERDICT[row.verdict]||'',`mx-v v-${row.verdict}`));
    const nums=el('div',undefined,'mx-nums'),etaB=el('b',row.eta_seconds?`${fmt(row.eta_seconds/60,0)} min`:'…');
    const n1=el('div');n1.append(etaB,el('small','chegada estimada'));
    const n2=el('div');n2.append(el('b',String(row.capacity_people)),el('small','pessoas por viagem'));
    const n3=el('div');n3.append(el('b',String(row.trips)),el('small',row.trips===1?'viagem':'viagens'));
    nums.append(n1,n2,n3);
    const why=el('p',`${row.capacity_people} lugares${Number.isFinite(people)?` para ${people} pessoa(s)`:''} · base a ${km(row.distance_m)} em linha reta${row.verdict==='caution'?' · exige as checagens abaixo':''}`,'mx-why');
    const act=el('div',undefined,'mx-act'),go=button('Despachar',()=>dispatch(),'primary');go.id='mx-dispatch';
    const swap=el('select');swap.id='mx-swap';swap.setAttribute('aria-label','Trocar meio');
    rows.forEach((r,i)=>{const o=el('option',`${i===0?'★ ':''}${r.label_pt} · ${r.capacity_people} lugares · ${km(r.distance_m)}`);o.value=r.id;if(i===idx)o.selected=true;swap.append(o);});
    swap.onchange=()=>{app.S.units.set(c.case_id,swap.value);app.redraw();};
    const swapLabel=el('label','Trocar ▾ ');swapLabel.className='mx-swap';swapLabel.append(swap);
    const hint=el('small',undefined,'mx-hint');
    act.append(go,swapLabel);rec.append(head,nums,why,act,hint);
    const fs=el('fieldset',undefined,'mx-checks');fs.append(el('legend','Antes de despachar'));
    for(const g of groups){
      const lab=el('label',undefined,'mx-check'),inp=el('input');inp.type='checkbox';inp.checked=state.has(g.key);inp.dataset.check=g.key;
      inp.onchange=()=>{inp.checked?state.add(g.key):state.delete(g.key);sync();};
      lab.append(inp,el('span',g.text_pt));fs.append(lab);
    }
    let busy=false;
    function sync(){
      const missing=groups.filter(g=>!state.has(g.key)).length;
      let msg=block;if(!msg&&missing)msg=`Faltam ${missing} checagen${missing>1?'s':''}`;
      const bl=[...new Set((row.approval_blockers||[]).filter(t=>!t.startsWith('Confirmar localização')).map(plain))];
      if(!msg&&bl.length)msg=bl.join(' ');
      go.disabled=!!msg||busy;hint.textContent=msg||'Tudo conferido: pronto para despachar.';hint.className='mx-hint '+(msg?'':'ready');
      go.title=msg||'Cria a missão com este meio';
    }
    async function dispatch(){
      busy=true;sync();go.textContent='Despachando…';
      try{
        const d=await api('/api/ux/dispatch',{case_id:c.case_id,unit_id:row.id,date:day,actor:'operador',expected_version:c.version,
          caution_acknowledged:true,override_reason:idx>0?'Escolhido pelo operador (Trocar).':undefined,
          checks:groups.map(g=>({key:g.key,text_pt:g.text_pt,codes:g.codes,done:state.has(g.key)}))});
        ticks.delete(sel);
        undoToast(d,ctx,row);startMover(d,routeFor(row),ctx);
        notice(`Despachado: ${row.label_pt} a caminho. Missão criada; dá para desfazer por ${Math.round(d.undo_left_s||10)} s.`);
        await refresh();
      }catch(e){notice(e.message,true);busy=false;go.textContent='Despachar';sync();}
    }
    const routeFor=r=>getRoute(api,c,r.id,day);
    const cards=el('div',undefined,'mx-cards');
    const rc=el('section',undefined,'mx-card'),rkey=el('b','…'),rsub=el('small','calculando rota');
    const rbtn=button('Ver rota',()=>showRoute(),'');rbtn.id='mx-route';rbtn.disabled=true;
    rc.append(el('h4','Rota'),rkey,rsub,rbtn);
    const lc=el('section',undefined,'mx-card'),lkey=el('b','…'),lsub=el('small','buscando ponto de desembarque');
    const lbtn=button('Ver opções',()=>landingDialog(),'');lbtn.id='mx-landing';lbtn.disabled=true;lc.append(el('h4','Desembarque'),lkey,lsub,lbtn);
    cards.append(rc,lc);
    root.replaceChildren(rec,fs,cards,details(el,evidence,data,c,row,groups));sync();
    let plan=null;
    function showRoute(){
      if(!plan?.reachable){const why=(plan?.review_pt||[]).filter(t=>/sem rota|sem caminho|desconectad/i.test(t))[0]||'Sem rota comprovada para esta unidade.';rsub.textContent=why.replace(/^REVISAR:\s*/,'');rsub.className='danger';notice('Sem rota para este meio: '+rsub.textContent+' Tente outro meio em “Trocar”.',true);return;}
      window.DeskRouteView.show(plan,{unitLabel:row.label_pt,destLabel:app.place(c),dest:app.pos(c)});
    }
    routeFor(row).then(r=>{
      if(my!==gen||!root.isConnected)return;plan=r;
      if(r.reachable){const l=r.land||r,w=r.water,total=(l.land_km||0)+(w?.km||0),min=Number.isFinite(r.eta_seconds)?r.eta_seconds/60:(l.land_eta_min||0)+(w?.eta_min||0);
        rkey.textContent=`${fmt(total)} km · ${fmt(min,0)} min`;rsub.textContent=w?`terra ${fmt(l.land_km)} km + água ${fmt(w.km)} km (estimativa)`:'só por terra (estimativa)';rbtn.disabled=false;
        if(!row.eta_seconds)etaB.textContent=`${fmt(min,0)} min`;}
      else{rkey.textContent='sem rota';rsub.textContent='sem caminho terrestre comprovado';rbtn.disabled=false;if(!row.eta_seconds)etaB.textContent='—';}
    }).catch(e=>{if(my===gen){rkey.textContent='indisponível';rsub.textContent=e.message;etaB.textContent='—';}});
    api(`/api/cases/${encodeURIComponent(c.case_id)}/landing?now=${encodeURIComponent(day+'T12:00:00-03:00')}`).then(v=>{
      if(my!==gen||!root.isConnected)return;const o=v?.options?.[0];
      if(o){lkey.textContent=`${o.label} · ${fmt(o.distance.m/1000)} km`;lsub.textContent=o.shelters?.length?`${o.shelters.length} abrigo(s) elegível(is)`:'sem abrigo elegível ainda';}
      else{lkey.textContent='sem opção';lsub.textContent=(v?.review_pt||[])[0]||'nenhum ponto elegível';}
      lbtn.disabled=false;
    }).catch(e=>{lkey.textContent='indisponível';lsub.textContent=e.message;});
    function landingDialog(){
      const d=el('dialog',undefined,'mx-dialog'),b=el('div'),bar=el('div',undefined,'row spread');
      bar.append(el('strong','Desembarque'),button('Fechar',()=>{d.close();}));d.append(bar,b);
      document.body.append(d);d.onclose=()=>d.remove();d.showModal();window.DeskLanding?.render(b,c,{api,el,button,notice,day});
    }
    api(`/api/ux/dispatches?case_id=${encodeURIComponent(c.case_id)}`).then(r=>{
      const last=(r.dispatches||[]).find(x=>x.state==='dispatched');if(!last||my!==gen||!root.isConnected)return;
      const s=el('section',undefined,'mx-saved');s.append(el('strong',`Despachado: ${last.label_pt} · missão ${last.mission_id.slice(0,6)}`),el('small',`Checagens registradas (${last.checks.length}): ${last.checks.map(x=>x.text_pt.split(' (')[0]).join(' · ')}`));
      root.prepend(s);}).catch(()=>{});
  }
  function details(el,evidence,data,c,row,groups){
    const d=el('details',undefined,'mx-det');d.append(el('summary','Detalhes técnicos (códigos, fontes, bloqueios)'));
    let built=false;d.ontoggle=()=>{if(!d.open||built)return;built=true;
      if(row){const ul=el('ul');for(const r of row.reasons||[])ul.append(el('li',`${r.text_pt} [${r.code}]`));d.append(el('h4','Motivos do meio'),ul);}
      if(groups){const ul=el('ul');for(const g of groups)ul.append(el('li',`${g.text_pt}: ${g.codes.join(', ')||'—'}`));d.append(el('h4','Checagens → códigos'),ul);}
      if(data.ineligible?.length){const ul=el('ul');for(const r of data.ineligible)ul.append(el('li',`${r.label_pt} (${r.id}): ${(r.blocking_reasons||[]).map(x=>x.text_pt).join(' ')}`));d.append(el('h4',`Unidades bloqueadas (${data.ineligible.length})`),ul);}
      d.append(el('p',data.distance_basis_pt||'','muted'),evidence('Fatos e cálculo (JSON)',data));
      const cr=c.hazard_review;if(cr?.brief_pt)d.append(el('h4','Parecer do crítico de risco'),el('p',cr.brief_pt));};
    return d;
  }
  let iv=null;
  function undoToast(d,ctx,row){
    document.getElementById('undo-toast')?.remove();clearInterval(iv);
    const {el,button,api,notice,refresh}=ctx,t=el('div',undefined,'undo-toast');t.id='undo-toast';t.setAttribute('role','status');
    const msg=el('span',`${row.label_pt} despachado · missão criada`),left=el('b'),u=button('Desfazer',async()=>{
      u.disabled=true;try{await api('/api/ux/undo',{dispatch_id:d.dispatch_id,actor:'operador'});stopMover();clearInterval(iv);t.remove();notice('Despacho desfeito: missão cancelada e caso restaurado.');await refresh();}catch(e){notice(e.message,true);u.disabled=false;}});
    u.id='undo-dispatch';t.append(msg,left,u);document.body.append(t);
    const end=Date.now()+(d.undo_left_s||10)*1000;
    const tick=()=>{const s=Math.max(0,Math.ceil((end-Date.now())/1000));left.textContent=` ${s} s `;if(s<=0){clearInterval(iv);t.remove();}};
    iv=setInterval(tick,250);tick();
  }
  // [SIMULADO] mover (sample mode only): posts simulated GPS fixes along the route
  let mover=null;
  function startMover(d,routeP,ctx){
    stopMover();
    if(!window.DeskApp.S.mode_info?.offline)return;
    routeP.then(async r=>{
      const pts=[...((r.land||r).polyline||[]),...(r.water?.polyline||[])];if(pts.length<2)return;
      const dev='sim-'+d.unit_id;try{await ctx.api('/api/telemetry/bindings',{device:dev,unit_id:d.unit_id,actor:'operador'});}catch{}
      let i=0;const step=Math.max(1,Math.floor(pts.length/40));
      const tick=async()=>{const p=pts[Math.min(i,pts.length-1)];
        try{await ctx.api('/api/telemetry/positions',{positions:[{id:dev,lat:p[1],lon:p[0],source:'simulated',timestamp:Date.now()/1000-1,speed:10,bearing:0,accuracy:5}]});}catch{}
        i+=step;if(i>=pts.length+step)stopMover();};
      mover=setInterval(tick,2500);tick();
    }).catch(()=>{});
  }
  function stopMover(){if(mover){clearInterval(mover);mover=null;}}
  function prefetch(c,api){if(!c||c.result?.decision!=='SEND_CANDIDATE'||blockers(c))return;const day=document.getElementById('date').value;getAssets(api,c,day).catch(()=>{});}
  return {render,prefetch,stopMover,reset:()=>{cache.clear();routes.clear();}};
})();
