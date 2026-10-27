'use strict';
window.DeskFleet=(()=>{
  const km=value=>value==null?'distância a confirmar':(value/1000).toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1})+' km estimados';
  const pretty=text=>String(text||'').replace(/(\d+(?:\.\d+)?) m(?=\s|[;.,)]|$)/g,(_,n)=>km(Number(n)));
  function sources(el,ids){const d=el('details');d.append(el('summary',`fontes (${ids.length})`),el('small',ids.join(', ')));return d;}
  const yes=value=>value===true?'Sim':value===false?'Não':'A confirmar';
  async function render(body,c,ctx){
    const {api,el,button,evidence,notice,refresh,day}=ctx;
    const card=el('section',undefined,'mission-card');card.setAttribute('aria-label','Qual meio enviar');
    card.append(el('h3','Qual meio enviar'),el('p','Consultando unidades, limites e disponibilidade…','muted'));body.prepend(card);
    try{
      const result=await api(`/api/cases/${encodeURIComponent(c.case_id)}/assets?date=${encodeURIComponent(day)}`);
      if(!card.isConnected)return;
      card.replaceChildren(el('h3','Qual meio enviar'),el('p',result.distance_basis_pt),
        el('p',pretty(result.explanation_pt)),el('small',result.explanation_check==='model_reviewed'?'Comparação Nemotron · citações validadas':`Modelo determinístico · ${result.fallback_reason||'sem chamada'}`));
      if(!result.top3.length)card.append(el('p','Sem unidade elegível. Confira os bloqueios antes de despachar.','danger'));
      for(const row of result.top3){
        const item=el('section');item.append(el('h4',`${row.rank}. ${row.label_pt} · ${row.id}`),
          el('p',`${row.synthetic?'[SIMULADO] · ':''}${row.capacity_people} passageiros · ${row.trips} viagem(ns) · base: ${km(row.distance_m)}`));
        const list=el('ul');
        for(const reason of row.reasons.filter(r=>!r.code.startsWith('R')||r.code!=='R000')){
          const li=el('li',`${pretty(reason.text_pt)} [${reason.code}]`);li.append(el('small',` · ${reason.fact_ids.join(', ')}`));list.append(li);
        }item.append(list);
        const checks=[];
        if(row.confirmation_checklist?.length)item.append(el('h4','Confirmar antes de despachar'));
        for(const check of row.confirmation_checklist||[]){
          const label=el('label',undefined,'ack'),tick=el('input');tick.type='checkbox';
          label.append(tick,document.createTextNode(` ${pretty(check.text_pt)} [${check.code}]`));
          const overrideLabel=el('label',`Justificativa para ressalva ${check.code}`),override=el('textarea');
          override.maxLength=500;override.rows=2;override.id=`fleet-check-${row.id}-${check.code}`;overrideLabel.htmlFor=override.id;
          item.append(label,sources(el,check.fact_ids),overrideLabel,override);checks.push({check,tick,override});
        }
        const reasonLabel=el('label','Motivo para escolher fora da primeira posição'),reasonInput=el('textarea');
        reasonInput.maxLength=500;reasonInput.rows=2;reasonInput.id=`fleet-override-${row.id}`;reasonLabel.htmlFor=reasonInput.id;
        if(row.rank>1)item.append(reasonLabel,reasonInput);
        const label=el('label',undefined,'ack'),ack=el('input');ack.type='checkbox';
        label.append(ack,document.createTextNode(' Revisei fatos, acesso, carga e cautelas. Aprovo esta unidade para a missão.'));
        const blockers=row.approval_blockers||[];
        blockers.forEach(text=>item.append(el('p',text,'danger')));
        const choose=button('Aprovar missão com esta unidade',async()=>{
          choose.disabled=true;
          try{
            await api('/api/missions',{proposal_id:row.proposal_id,expected_versions:row.expected_versions,
              actor:'operador',caution_acknowledged:ack.checked,override_reason:reasonInput.value,
              checklist_confirmations:Object.fromEntries(checks.map(({check,tick,override})=>[check.code,tick.checked?true:{override_reason:override.value.trim()}]))});
            notice('Missão aprovada pelo operador; unidade registrada.');await refresh();
          }catch(error){notice(error.message,true);choose.disabled=false;}
        },'primary');
        function update(){choose.disabled=!row.proposal_id||blockers.length>0||!ack.checked||row.rank>1&&!reasonInput.value.trim()||checks.some(({tick,override})=>!tick.checked&&!override.value.trim());}
        for(const {tick,override} of checks){tick.onchange=update;override.oninput=update;}
        ack.onchange=update;reasonInput.oninput=update;update();item.append(label,choose);card.append(item);
      }
      for(const request of result.requests||[])card.append(el('p',`${request.text_pt} [${request.reason_code}; ${request.fact_ids.join(', ')}] Disponibilidade não confirmada.`,'danger'));
      const blocked=el('details');blocked.append(el('summary',`Unidades bloqueadas (${result.ineligible.length})`));
      for(const row of result.ineligible)blocked.append(el('p',`${row.id} · ${row.label_pt}: ${row.blocking_reasons.map(r=>`${r.text_pt} [${r.code}; ${r.fact_ids.join(', ')}]`).join(' ')}`));
      card.append(blocked,evidence('Fatos citados e cálculo da classificação',result));
    }catch(error){if(card.isConnected)card.replaceChildren(el('h3','Qual meio enviar'),el('p',error.message,'danger'));}
  }
  async function resources(ctx){
    const {api,el,button,notice}=ctx,d=el('dialog');d.setAttribute('aria-label','Tipos e atributos da frota');
    const close=button('Fechar',()=>d.close());d.append(el('h2','Recursos · unidades e capacidades'),close);
    d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();
    try{
      const data=await api('/api/resources'),progress=await api('/api/units/status?replay_time='+encodeURIComponent((window.DeskReplay?window.DeskReplay.iso():ctx.day+'T23:59:59-03:00')));if(!d.isConnected)return;
      ctx={...ctx,refresh:async()=>{d.close();await resources(ctx);}};
      if(!data.typed_resources?.length)d.append(el('p','Nenhuma unidade com atributos tipados. Registre as capacidades documentadas.'));
      const attrs=[['Capacidade','capacity_people'],['Calado (m)','draft_m'],['Transposição (m)','max_wading_depth_m'],
        ['Maca','stretcher'],['Equipe médica','medical_crew'],['Noite','night_ok'],['Animais','pets_ok']];
      for(const u of data.typed_resources||[]){
        const section=el('section');section.append(el('h3',`${u.label_pt} · ${u.id} · ${u.status}`),
          el('p',`${u.source} · ${u.base||'Base a confirmar'} · último relato: ${u.last_report_at||'a confirmar'}`));
        const state=progress.units.find(r=>r.unit_id===u.id);
        if(state)section.append(status(el,state),reportForm(ctx,u.id));
        window.DeskTelemetry?.resources(section,u,ctx);
        const dl=el('dl');for(const [name,key] of attrs)dl.append(el('dt',name),el('dd',['stretcher','medical_crew','night_ok','pets_ok'].includes(key)?yes(u[key]):String(u[key]??'A confirmar')));
        if(u.type==='helicoptero')section.append(el('p','Somente solicitação; não integra unidades disponíveis.'));
        section.append(dl);d.append(section);
      }
      d.append(button('Registrar / editar inventário',()=>{d.close();window.DeskFeedback.resources(ctx);}));
    }catch(error){notice(error.message,true);d.append(el('p',error.message,'danger'));}
  }
  function status(el,s){
    const p=el('p',`Estado: ${s.label_pt} · ${s.source||'sem fonte'} ${s.status_at||''}`);p.setAttribute('role','status');
    if(s.last_report)p.append(el('small',` · último relato: ${s.last_report.text} (${s.last_report.at})`));
    if(s.expected)p.append(el('small',` · ${s.expected.label_pt} · ${s.expected.basis_pt}`));
    if(s.reroute_hint_pt)p.append(el('strong',s.reroute_hint_pt));return p;
  }
  function reportForm(ctx,uid,mid){
    const {el,button,api,notice}=ctx,box=el('details');box.append(el('summary',`Relatar estado · ${uid}`));
    const text=el('textarea');text.maxLength=12000;text.setAttribute('aria-label',`Relato da unidade ${uid}`);
    const at=el('input');at.value=ctx.day?ctx.day+'T12:00:00-03:00':new Date().toISOString();at.setAttribute('aria-label','Data e hora ISO do relato');
    const pick=el('select');pick.setAttribute('aria-label','Estado informado pelo operador');pick.append(new Option('Somente texto',''));
    for(const [k,v]of Object.entries({en_route:'A caminho',on_scene:'No local',returning:'Retornando',unloading:'Desembarcando',available:'Disponível',out_of_service:'Fora de serviço'}))pick.append(new Option(v,k));
    box.append(text,at,pick,button('Registrar relato',async()=>{
      try{await api(`/api/units/${encodeURIComponent(uid)}/report`,{text:text.value,received_at:at.value,status:pick.value||undefined,source:'operator',actor:'operador',mission_id:mid||undefined});notice('Relato registrado com fonte e horário.');await ctx.refresh?.();}
      catch(e){notice(e.message,true);}
    }));return box;
  }
  return {render,resources,status,reportForm};
})();
