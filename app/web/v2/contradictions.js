'use strict';
// Divergências entre fontes (N2 A3): a mensagem contra camada de alagamento, interdições, abrigos, relatos da equipe e duplicatas.
// Tudo vem de GET /api/contradictions?case_id=…; este arquivo não decide nada. A sugestão "resgatado" só vale após confirmação humana.
window.DeskContradictions=(()=>{
 const STRENGTH={weak:'fraca (camada retrospectiva ou imprecisa)',medium:'média',strong:'forte'};
 const SOURCE={message:'Mensagem',flood_layer:'Camada de alagamento',road_closure:'Interdição',shelter_state:'Abrigo',crew_report:'Equipe de campo',duplicate_case:'Caso parecido'};
 const STATE={open:'aberta',acknowledged:'reconhecida',dismissed:'dispensada',confirmed:'sugestão confirmada'};
 function card(it,c,ctx){
  const {el,button,api,notice,refresh}=ctx,root=el('article');root.className='contradiction contradiction-'+it.strength;
  root.append(el('strong',`${STRENGTH[it.strength]||it.strength} · ${STATE[it.state]||it.state}`),el('p',it.question_pt));
  root.append(el('small',it.phrased_by==='model'?'Pergunta redigida pelo modelo (validada: sem fatos novos).':'Pergunta por regra.'+(it.phrasing?.fallback_reason?` Modelo indisponível: ${it.phrasing.fallback_reason}.`:'')));
  const list=el('ul');for(const s of it.sources){const li=el('li');li.append(el('b',`${SOURCE[s.source]||s.source} (${s.ref}): `),document.createTextNode(`“${s.quote}”`));list.append(li);}
  root.append(list,el('small',it.basis_pt||''));
  if(it.state==='open'){
   const bar=el('div');bar.className='actions';
   const act=(label,decision)=>button(label,async()=>{try{await api('/api/contradictions/decision',{case_id:c.case_id,item_id:it.id,decision,actor:'operador',expected_version:c.version});notice('Decisão registrada.');await refresh();}catch(e){notice(e.message||'Falha ao registrar.',true);}});
   if(it.suggestion)bar.append(act('Confirmar: marcar como resgatado (humano)','confirm'));
   bar.append(act('Reconhecer','acknowledge'),act('Dispensar','dismiss'));root.append(bar);
  }
  return root;
 }
 function render(c,ctx){
  const {el}=ctx,root=el('section');root.setAttribute('aria-label','Divergências entre fontes');
  if(!(c.cross_source||[]).length)return root;
  root.append(el('h3','Divergências entre fontes'));
  const body=el('div');root.append(body);
  ctx.api(`/api/contradictions?case_id=${encodeURIComponent(c.case_id)}`).then(v=>{
   for(const it of v.items||[])body.append(card(it,{...c,version:v.version},ctx));
  }).catch(()=>body.append(el('p','Divergências indisponíveis agora; conferir o diário.','danger')));
  return root;
 }
 return {render};
})();
