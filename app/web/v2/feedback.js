'use strict';
window.DeskFeedback=(()=>{
 function dialog(title,{el,button}){const d=el('dialog');d.setAttribute('aria-label',title);d.append(el('h2',title),button('Fechar',()=>d.close()));d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();return d;}
 function form(c,{api,el,button,refresh,notice,day},mid){
  const root=el('section');root.append(el('h3','Retorno de campo'));
  for(const f of c.feedback||[])root.append(el('p',`${f.received_at} · ${f.source} · ${f.text}`),el('small',`${f.feedback_check}${f.fallback_reason?' · '+f.fallback_reason:''}`));
  if(['RESCUED','field_confirmed'].includes(c.status))return root;
  const form=el('form'),label=el('label','Relato da equipe ou cidadão'),input=el('textarea'),timeLabel=el('label','Recebido em (BRT)'),time=el('input'),sourceLabel=el('label','Fonte'),source=el('select');
  input.id='feedback-'+c.case_id;label.htmlFor=input.id;input.required=true;input.maxLength=12000;input.placeholder='Pegamos 3, falta 1 idoso';
  time.id='feedback-time-'+c.case_id;timeLabel.htmlFor=time.id;time.type='datetime-local';time.required=true;time.value=day+'T23:59';
  source.id='feedback-source-'+c.case_id;sourceLabel.htmlFor=source.id;for(const [value,text]of [['crew','Equipe'],['citizen','Cidadão']]){const o=el('option',text);o.value=value;source.append(o);}
  const submit=el('button','Registrar retorno');submit.type='submit';
  form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const body={text:input.value,received_at:time.value+':00-03:00',source:source.value,actor:'operador',expected_version:c.version,case_id:c.case_id};const updated=await api(mid?`/api/missions/${encodeURIComponent(mid)}/feedback`:`/api/cases/${encodeURIComponent(c.case_id)}/feedback`,body);notice(`Retorno registrado · versão ${updated.version} · ${updated.status} · ${updated.agents?.field_feedback?.feedback_check}`);await refresh();}catch(err){notice(err.message,true);}finally{submit.disabled=false;}};
  form.append(label,input,timeLabel,time,sourceLabel,source,submit);root.append(form);return root;
 }
 function errors(S,{el,button,select,mode}){
  const d=dialog('Estado do sistema',{el,button});for(const error of S.errors)d.append(el('p',error,'danger'));
  const cases=S.cases.filter(c=>c.errors?.length);if(!cases.length)d.append(el('p','Nenhum caso com erro registrado.'));
  if(S.cases.some(c=>c.mode==='sample_offline'))d.append(el('p','Offline: extração determinística, sem chamadas ao provedor.'));
  for(const c of cases)d.append(button(`${c.message_id} · ${c.errors.join('; ')}`,()=>{d.close();mode('dispatch');select(c.case_id);}),el('p',c.result?.decision_reason||'Falha registrada; revise Agentes para detalhes.'));
 }
 async function resources({api,el,button,notice,day}){
  const d=dialog('Recursos do turno',{el,button});const content=el('div');d.append(content);
  async function load(){
   const data=await api('/api/resources');content.replaceChildren();
   content.append(el('p','Capacidade de passageiros após equipe e equipamento. Deixe em branco sem fonte documental; valor ausente bloqueia missão.'));
   for(const u of data.resources||[]){const section=el('section');section.append(el('strong',`${u.id} · ${u.asset} · ${u.status}`),el('p',`Capacidade: ${u.capacity??'a confirmar'} · equipe: ${u.crew} · base: ${u.base}${u.synthetic?' · SINTÉTICO':''}`));content.append(section,editor(u,data.types));}
   content.append(el('h3','Registrar unidade'),editor(null,data.types));
  }
  function editor(unit,types){
   const f=el('form');const fields={};
   for(const [key,title,type]of [['id','Identificador','text'],['asset','Tipo','select'],['capacity','Capacidade (documentada)','number'],['capacity_source','Fonte da capacidade','text'],['crew','Equipe','text'],['base','Base','text'],['status','Estado','select'],['source','Fonte do registro','text'],['observed_date','Data do turno','date']]){
    const label=el('label',title),input=el(type==='select'?'select':'input');input.id=`resource-${unit?.id||'new'}-${key}`;label.htmlFor=input.id;
    if(type==='select'){for(const [v,t]of Object.entries(key==='asset'?types:{available:'Disponível',assigned:'Atribuído',maintenance:'Manutenção'})){const option=el('option',t);option.value=v;input.append(option);}}
    else input.type=type;
    if(type==='number')input.min='1';input.value=unit?.[key]??(key==='observed_date'?day:'');if(!['capacity','capacity_source'].includes(key))input.required=true;if(unit&&key==='id')input.readOnly=true;fields[key]=input;f.append(label,input);
   }
   const syntheticLabel=el('label','Dados sintéticos'),synthetic=el('input');synthetic.type='checkbox';synthetic.checked=unit?.synthetic===true;syntheticLabel.append(synthetic);f.append(syntheticLabel);
   const save=el('button',unit?'Atualizar recurso':'Registrar recurso');save.type='submit';f.append(save);
   f.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const value={...(unit||{})};for(const [k,input]of Object.entries(fields))value[k]=k==='capacity'?(input.value?Number(input.value):null):input.value;value.synthetic=synthetic.checked;await api('/api/resources',{actor:'operador',expected_version:unit?.version||0,unit:value});notice('Recurso registrado no World Model.');await load();}catch(error){notice(error.message,true);}finally{save.disabled=false;}};return f;
  }
  try{await load();}catch(error){content.append(el('p',error.message,'danger'));}
 }
 return {form,errors,resources};
})();
