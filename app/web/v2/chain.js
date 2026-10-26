'use strict';
window.DeskChain=(()=>{
  function card(p,ctx){
    const {el,button,api,notice,refresh}=ctx,box=el('section',undefined,'mission-card');
    box.append(el('h4',p.text_pt||`Parada extra: ${p.case_id} · +${p.added_minutes} min`),
      el('p',`Chegada estimada: ${p.arrival_minutes} min · atraso da missão: ${p.mission_delay_minutes} min`));
    for(const [id,minutes] of Object.entries(p.delays))box.append(el('p',`Atraso em ${id}: +${minutes} min`));
    const facts=el('details');facts.append(el('summary','Fontes e cálculos'));
    facts.append(el('pre',JSON.stringify({facts:p.facts,travel:p.travel_facts,sources:p.number_sources,free_units:p.free_unit_travel_facts},null,2)));box.append(facts);
    const checks=[];
    for(const check of p.confirmation_checklist||[]){
      const label=el('label'),tick=el('input');tick.type='checkbox';label.append(tick,document.createTextNode(check.text_pt));box.append(label);checks.push([check.code,tick]);
    }
    const ack=el('input');ack.type='checkbox';const label=el('label');
    label.append(ack,document.createTextNode(' Revisei as cautelas e confirmo explicitamente o desvio, inclusive saída de equipe em cena com pessoas a bordo.'));box.append(label);
    const approve=button('Aprovar alteração da missão',async()=>{
      approve.disabled=true;
      try{await api(`/api/reroutes/${p.id}/approve`,{actor:'operador',expected_versions:p.expected_versions,
        caution_acknowledged:ack.checked,confirm_on_scene_departure:ack.checked,
        checklist_confirmations:Object.fromEntries(checks.map(([code,tick])=>[code,tick.checked]))});
        notice('Alteração aprovada; evento versionado registrado.');await refresh();}
      catch(e){notice(e.message,true);update();}
    },'primary');
    function update(){approve.disabled=!ack.checked||checks.some(([,tick])=>!tick.checked);}
    ack.onchange=update;for(const [,tick] of checks)tick.onchange=update;update();
    box.append(approve,button('Recusar',async()=>{try{await api(`/api/reroutes/${p.id}/decline`,{});box.remove();notice('Proposta recusada.');}catch(e){notice(e.message,true);}}));
    return box;
  }
  async function mount(body,plan,ctx){
    const box=ctx.el('section');body.append(box);
    const label=ctx.el('label','Limite até uma parada da rota (km, estimado)'),radius=ctx.el('input');radius.type='number';radius.min='0.1';radius.max='20';radius.step='0.1';radius.value='1';label.append(radius);
    const results=ctx.el('div');box.append(ctx.el('h3','Encadear até duas paradas'),label,ctx.button('Recalcular',load),results);
    async function load(){try{
      const result=await ctx.api(`/api/missions/${plan.mission_id}/chain?radius_km=${encodeURIComponent(radius.value)}`);
      if(!box.isConnected)return;results.replaceChildren(ctx.el('p',result.radius_basis_pt));
      if(!result.proposals.length)results.append(ctx.el('p','Sem paradas extras elegíveis com capacidade disponível.'));
      for(const p of result.proposals)results.append(card(p,ctx));
      for(const x of result.excluded||[])if(x.unknown_count)results.append(ctx.el('p',`${x.case_id}: ${x.reason}`));
    }catch(e){ctx.notice(e.message,true);}}
    if(plan.last_update_id)box.append(ctx.button('Desfazer último desvio',async()=>{try{await ctx.api(`/api/reroutes/${plan.last_update_id}/undo`,{actor:'operador',expected_versions:plan.expected_versions});await ctx.refresh();}catch(e){ctx.notice(e.message,true);}}));
    await load();
  }
  async function alerts(body,ctx){try{
    const response=await ctx.api(`/api/reroutes?date=${encodeURIComponent(typeof ctx.day==='function'?ctx.day():ctx.day)}`);
    if(!body.isConnected)return;
    for(const p of response.alerts)body.append(card(p,ctx));
  }catch(e){ctx.notice(e.message,true);}}
  return {mount,alerts};
})();
