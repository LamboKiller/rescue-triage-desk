'use strict';
// Abrigos: lista (pré-existente) + relatos durante o evento; fila médica (ordem, nunca decisão); recomendação de destino na missão.
window.DeskShelters=(()=>{
  const $=id=>document.getElementById(id);
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=text;if(cls)n.className=cls;return n;};
  const day=()=>($('date')||{}).value||'2024-05-08';
  async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let d;try{d=await r.json();}catch{throw new Error('Resposta inválida ('+r.status+')');}if(!r.ok)throw new Error(d.error||('Erro '+r.status));return d;}
  const kindLabels={full:'Lotado',vacancies:'Vagas restantes',capacity:'Capacidade total',delivered:'Pessoas entregues',animals_yes:'Aceita animais',animals_no:'Não aceita animais',health_yes:'Tem apoio de saúde',health_no:'Sem apoio de saúde',access_dry:'Acesso seco',access_flooded:'Acesso alagado',alias:'Nome / apelido'};
  const fmtAge=h=>h==null?'sem relato':h<1?'< 1 h':h<48?Math.round(h)+' h':Math.round(h/24)+' d';
  const tri=v=>v===true?'sim':v===false?'não':'desconhecido';

  // ---------- Fila médica: ordena e filtra a fila existente sem alterar decisões ----------
  let medicalOnly=false,applying=false;
  const caseMap=()=>{try{return new Map((S.cases||[]).map(c=>[c.case_id,c]));}catch{return new Map();}};
  const band=m=>`${m.time_to_harm_hours[0]}–${m.time_to_harm_hours[1]} h`;
  function remaining(m){return m.time_to_harm_hours[0]-m.waited_hours;}
  function applyQueue(){
    const q=$('queue');if(!q||applying)return;applying=true;
    try{
      const cases=caseMap();
      const rows=[...q.querySelectorAll('[data-case]')];
      for(const r of rows){
        const m=cases.get(r.dataset.case)?.medical;
        let b=r.querySelector('.medical-flag');
        if(m&&!b){b=el('span','','life-flags medical-flag');r.append(b);}
        if(b){b.textContent=m?`Médica · ${m.needs.map(n=>n.label_pt).join(', ')} · dano em ~${band(m)} (estimativa operacional)`:'';}
        r.hidden=medicalOnly&&!m;
      }
      if(medicalOnly){
        const sortedRows=rows.filter(r=>!r.hidden).sort((a,b)=>{const ma=cases.get(a.dataset.case).medical,mb=cases.get(b.dataset.case).medical;return remaining(ma)-remaining(mb)||ma.time_to_harm_hours[1]-mb.time_to_harm_hours[1];});
        const empty=q.querySelector('.empty');
        if(sortedRows.some((r,i)=>q.children[i]!==r))for(const r of sortedRows)q.append(r);
        if(!sortedRows.length&&!q.querySelector('.medical-empty')){const p=el('p','Nenhum incidente aberto com necessidade médica citada.','empty medical-empty');q.append(p);}
        if(sortedRows.length)q.querySelector('.medical-empty')?.remove();
        if(empty&&sortedRows.length)empty.hidden=true;
      }else q.querySelector('.medical-empty')?.remove();
      const t=$('medical-toggle');if(t){const n=rows.filter(r=>cases.get(r.dataset.case)?.medical).length;t.textContent=`Fila médica (${n})`;t.setAttribute('aria-pressed',String(medicalOnly));}
    }finally{applying=false;}
  }
  function mountQueue(){
    const q=$('queue');if(!q||$('medical-toggle'))return;
    const b=el('button','Fila médica','medical-toggle');b.id='medical-toggle';b.type='button';b.setAttribute('aria-pressed','false');
    b.title='Só incidentes com necessidade médica citada na mensagem, por menor janela até dano (estimativa operacional). Não altera decisões.';
    b.onclick=()=>{medicalOnly=!medicalOnly;if(!medicalOnly)for(const r of q.querySelectorAll('[data-case]'))r.hidden=false;applyQueue();};
    q.parentElement.insertBefore(b,q);
    new MutationObserver(()=>{if(!applying)applyQueue();}).observe(q,{childList:true});
    applyQueue();
  }

  // ---------- Vista Abrigos ----------
  let root=null,state=null,query='',onlyReported=true,busy=false;
  function field(label,node){const l=el('label');l.append(document.createTextNode(label+' '),node);return l;}
  function reportForm(s,done){
    const d=el('details','','shelter-report'),sum=el('summary','Relatar');d.append(sum);
    const f=el('form');const kind=el('select');for(const [k,v] of Object.entries(kindLabels))kind.append(new Option(v,k));
    const value=el('input');value.type='number';value.min='0';value.max='100000';value.placeholder='número';
    const name=el('input');name.type='text';name.placeholder='nome / apelido';name.maxLength=120;name.hidden=true;
    const actor=el('input');actor.value='operador';actor.maxLength=120;actor.required=true;
    const at=el('input');at.type='datetime-local';at.value=day()+'T'+new Date().toTimeString().slice(0,5);at.required=true;
    const src=el('select');for(const [k,v] of [['operator','operador'],['crew','equipe em campo'],['citizen','cidadão']])src.append(new Option(v,k));
    const sync=()=>{const k=kind.value;value.hidden=!['vacancies','capacity','delivered'].includes(k);value.required=!value.hidden;name.hidden=k!=='alias';name.required=!name.hidden;};kind.onchange=sync;sync();
    const submit=el('button','Registrar');submit.type='submit';
    f.append(field('O que',kind),value,name,field('Quem',actor),field('Fonte',src),field('Quando',at),submit);
    f.onsubmit=async e=>{e.preventDefault();submit.disabled=true;
      const k=kind.value,body={shelter_id:s.shelter_id,actor:actor.value,source:src.value,at:at.value+':00-03:00'};
      if(k==='full'||k==='vacancies'||k==='capacity'||k==='delivered'){body.kind=k;if(k!=='full')body.value=parseInt(value.value,10);}
      else if(k.startsWith('animals_')||k.startsWith('health_')){body.kind='attr';body.attr=k.startsWith('animals_')?'animals_ok':'health_support';body.value=k.endsWith('_yes');}
      else if(k.startsWith('access_')){body.kind='access';body.value=k.slice(7);}
      else{body.kind='alias';body.name=name.value;}
      try{await api('/api/shelters/reports',body);notice('Relato registrado.');await done();}catch(err){notice(err.message,true);submit.disabled=false;}};
    d.append(f);return d;
  }
  function notice(text,bad){const n=$('notice');if(!n)return;n.hidden=false;n.textContent=text;n.className=bad?'bad':'';clearTimeout(notice.t);notice.t=setTimeout(()=>{n.hidden=true;},5000);}
  function row(s){
    const tr=el('tr');
    const cap=s.capacity_known?`${s.remaining} vagas`:(s.remaining_max!=null?`≤ ${s.remaining_max} (total ${s.capacity_total}, ocupação desconhecida)`:'capacidade desconhecida');
    const a=s.attributes,reported=s.reported_access?`${s.reported_access.value==='dry'?'seco':'alagado'} (${s.reported_access.source})`:'—';
    const c1=el('td');c1.append(el('strong',s.label),el('br'),el('small',s.origin_label));
    const c2=el('td',cap+(s.full?' · LOTADO':''),s.full?'danger':s.capacity_known?'':'muted');c2.append(el('br'),el('small',s.capacity_note_pt));
    for(const n of [c1,c2,el('td',fmtAge(s.last_report_age_h)),el('td',`saúde: ${tri(a.health_support.value)} · animais: ${tri(a.animals_ok.value)}`),el('td',reported),el('td',String(s.delivered_total))])tr.append(n);
    const act=el('td');act.append(reportForm(s,()=>draw(true)));tr.append(act);return tr;
  }
  async function draw(force){
    root=$('shelters');if(!root||busy)return;busy=true;
    try{
      if(!state||force)state=await api('/api/shelters?date='+encodeURIComponent(day()));
      const sum=state.summary;
      root.replaceChildren(el('h1','Abrigos · capacidade e necessidades'),
        el('p',state.labels_pt.list+' '+state.labels_pt.capacity,'muted'),
        el('p',`${sum.total} abrigos · vagas conhecidas em ${sum.capacity_known} · lotados ${sum.full} · desconhecidas ${sum.capacity_unknown} · pessoas entregues (relatos) ${sum.delivered_total}`));
      const tools=el('div','','shelter-tools');
      const search=el('input');search.type='search';search.placeholder='Buscar abrigo ou município';search.value=query;search.oninput=()=>{query=search.value;fill();};
      const only=el('input');only.type='checkbox';only.checked=onlyReported;only.onchange=()=>{onlyReported=only.checked;fill();};
      const lab=el('label');lab.append(only,document.createTextNode(' Só com vagas conhecidas ou relato'));tools.append(search,lab);
      const text=el('form','','shelter-text'),area=el('input');area.placeholder='Relato em texto: "abrigo Nome lotado" · "entregues 5 no abrigo Nome" · "Nome: 40 vagas"';area.maxLength=2000;area.required=true;area.style.minWidth='24em';
      const who=el('input');who.value='operador';who.maxLength=120;who.required=true;const go=el('button','Interpretar e registrar');go.type='submit';text.append(area,who,go);
      text.onsubmit=async e=>{e.preventDefault();go.disabled=true;try{const r=await api('/api/shelters/reports',{text:area.value,actor:who.value,source:'operator',at:day()+'T'+new Date().toTimeString().slice(0,5)+':00-03:00'});
        if(r.unresolved)notice(r.unresolved,true);else{notice(`${r.recorded.length} relato(s) registrado(s).`);area.value='';await draw(true);}}catch(err){notice(err.message,true);}go.disabled=false;};
      const table=el('table'),head=el('thead'),hr=el('tr');for(const h of ['Abrigo','Vagas','Último relato','Necessidades atendidas','Acesso (relato)','Entregues','Relatar'])hr.append(el('th',h));head.append(hr);
      const body=el('tbody'),count=el('p','','muted');table.append(head,body);
      function fill(){
        const q=query.toLocaleLowerCase();
        let list=state.shelters.filter(s=>(!onlyReported||s.capacity_known||s.last_event_report_at)&&(!q||(s.label+' '+s.municipality).toLocaleLowerCase().includes(q)));
        list.sort((a,b)=>(!!b.last_event_report_at-!!a.last_event_report_at)||((b.capacity_known)-(a.capacity_known))||a.label.localeCompare(b.label));
        count.textContent=`${list.length} abrigo(s)`+(list.length>150?' · mostrando 150 (refine a busca)':'');
        body.replaceChildren(...list.slice(0,150).map(row));
      }
      root.append(tools,text,count,table);fill();
    }catch(err){root.replaceChildren(el('h1','Abrigos'),el('p',err.message,'danger'));}
    finally{busy=false;}
  }
  function show(){
    for(const id of ['dispatch','agents','situation','data','flow']){const n=$(id);if(n)n.hidden=true;}
    root.hidden=false;const back=$('back-dispatch');if(back)back.hidden=false;
    document.querySelectorAll('nav [data-mode]').forEach(b=>b.removeAttribute('aria-current'));$('shelters-nav')?.setAttribute('aria-current','page');
    state=null;draw(true);
  }
  function mountView(){
    if($('shelters'))return;
    root=el('main','','other-mode');root.id='shelters';root.hidden=true;root.setAttribute('aria-label','Abrigos');
    ($('data')||document.body).after(root);
    const nav=document.querySelector('.map-tools nav');
    if(nav){const b=el('button','Abrigos');b.id='shelters-nav';b.type='button';b.onclick=show;nav.append(b);}
    // Any other view becoming visible closes this one (app.js owns their hidden flags).
    const watch=new MutationObserver(()=>{if(!root.hidden&&['dispatch','agents','situation','data','flow'].some(id=>$(id)&&!$(id).hidden)){root.hidden=true;$('shelters-nav')?.removeAttribute('aria-current');}});
    for(const id of ['dispatch','agents','situation','data','flow']){const n=$(id);if(n)watch.observe(n,{attributes:true,attributeFilter:['hidden']});}
    $('date')?.addEventListener('change',()=>{state=null;if(!root.hidden)draw(true);});
  }

  // ---------- Cartão da missão: destino recomendado (humano escolhe) ----------
  async function mount(section,{plan}){
    const box=el('section','','shelter-reco');section.append(box);
    box.append(el('h4','Abrigo de destino · recomendação (o operador escolhe)'),el('p','Carregando abrigos…','muted'));
    try{
      const ids=(plan.stops||[]).map(s=>s.case_id);if(!ids.length){box.lastChild.textContent='Sem paradas.';return;}
      const r=await api(`/api/shelters/recommend?date=${encodeURIComponent(plan.date||day())}&case_ids=${encodeURIComponent(ids.join(','))}`+(Number.isInteger(plan.people)?`&people=${plan.people}`:''));
      box.lastChild.remove();
      box.append(el('small',r.ranking_pt+' Distância = linha reta a partir de '+r.group.reference_basis+'.','muted'));
      if(r.message_pt)box.append(el('p',r.message_pt,'danger'));
      for(const s of r.recommendations){
        const card=el('div','','shelter-option');
        card.append(el('strong',`${s.rank}. ${s.label}`),el('span',` · ${(s.distance_m/1000).toFixed(1)} km · acesso: ${({dry:'seco',flooded:'ALAGADO',unknown:'desconhecido',conflict:'em conflito'})[s.access.state]} · vagas: ${s.capacity.known?s.capacity.remaining:'desconhecidas'}`));
        for(const t of s.reasons_pt)card.append(el('p',t));
        for(const t of s.confirm_pt)card.append(el('p','Confirmar: '+t,'muted'));
        for(const t of s.warnings_pt)card.append(el('p',t,'danger'));
        card.append(el('small',s.origin_label,'muted'));box.append(card);
      }
      if(r.excluded_total){const d=el('details');d.append(el('summary',`${r.excluded_total} abrigo(s) não oferecidos`),...r.excluded.map(x=>el('p',`${x.label}: ${x.reason_pt}`)));box.append(d);}
    }catch(err){box.replaceChildren(el('h4','Abrigo de destino'),el('p',err.message,'danger'));}
  }

  function init(){mountView();mountQueue();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  return {mount,draw,applyQueue,medicalOnly:()=>medicalOnly};
})();
