'use strict';
window.DeskCoverage=(()=>{
  let payload=null,token=0;
  const make=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  function render(root=document.getElementById('situation')){
    if(!root)return;root.querySelector('[data-coverage]')?.remove();
    const box=make('section','');box.dataset.coverage='true';box.append(make('h2','Cobertura · estimativas'));
    if(!payload){box.append(make('p','Cobertura indisponível ou carregando; sem dado não significa cobertura.'));root.append(box);return;}
    box.append(make('p',payload.note_pt));
    box.append(make('p',`${payload.cells.filter(c=>c.gap).length} células com lacuna · limiar ${payload.threshold_minutes} min · vermelho: lacuna; amarelo: ETA desconhecido; verde: estimativa dentro do limiar.`));
    for(const cell of [...payload.cells].sort((a,b)=>Number(b.gap)-Number(a.gap)).slice(0,8)){
      const best=cell.best,eta=best?`~${Math.ceil(best.eta_seconds/60)} min · ${best.unit_id}`:'sem ETA comprovado';
      box.append(make('p',`${cell.label_pt}: ${cell.open_cases} pedidos · ${cell.people_known} pessoas + ${cell.people_unknown_cases} pedidos a confirmar · ${cell.p1_count} P1 · ${cell.life_safety_count} risco à vida · ${eta} (estimativa)`));
      if(best)box.append(make('small',best.basis_pt+(best.synthetic?' [SIMULADO]':'')));
      const suggestion=payload.suggestions.find(x=>x.cell_id===cell.id);
      if(suggestion)box.append(make('p',suggestion.text_pt));
      const details=make('details','');details.append(make('summary','Pedidos citados'),make('p',cell.case_ids.join(', ')));box.append(details);
    }
    if(!payload.cells.length)box.append(make('p','Nenhum pedido aberto com ponto nesta data.'));
    if(payload.unlocated_case_ids.length)box.append(make('p','Sem ponto; revisar localização: '+payload.unlocated_case_ids.join(', ')));
    root.append(box);
  }
  let recent=null;
  function refresh(){const day=document.getElementById('date').value;if(recent&&recent.day===day&&Date.now()-recent.t<2500)return recent.p;recent={day,t:Date.now(),p:refreshNow()};return recent.p;}  // UX2: init + first desk refresh asked twice
  async function refreshNow(){
    const mine=++token,day=document.getElementById('date').value;payload=null;window.DeskMap.showCoverage(null);
    try{const r=await fetch('/api/coverage?date='+encodeURIComponent(day));if(!r.ok)throw new Error('Cobertura indisponível');const data=await r.json();if(mine!==token)return;payload=data;window.DeskMap.showCoverage(data.geojson);}catch{if(mine!==token)return;}
    render();
  }
  refresh();return {refresh,render};
})();
