'use strict';
// "Ver rota": draws land (solid) + water (dashed) + base/launch/destination on the map, fits bounds, dims the other
// layers and shows a floating summary with "Fechar rota". Only draws what the route API returned.
window.DeskRouteView=(()=>{
  const WORLD={type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]]]}}]};
  const own=['rv-dim','rv-casing-land','rv-casing-water','route-land','route-water','route-launch','rv-ring','rv-pts','rv-label'];
  let box=null,open=false,opts=null;
  const gl=()=>window.DeskMap?.telemetrySurface?.().gl||null;
  const fc=f=>({type:'FeatureCollection',features:f});
  const line=(c,kind)=>({type:'Feature',properties:{kind},geometry:{type:'LineString',coordinates:c}});
  const pt=(c,kind,label)=>({type:'Feature',properties:{kind,label},geometry:{type:'Point',coordinates:c}});
  function points(plan,o){
    const land=plan.land||plan,out=[];
    const base=land.polyline?.[0];if(base)out.push(pt(base,'base',o.unitLabel||'Base'));
    if(plan.launch_point)out.push(pt([plan.launch_point.lon,plan.launch_point.lat],'launch','Lançamento'));
    if(o.dest)out.push(pt(o.dest,'dest',o.destLabel||'Caso'));
    return out;
  }
  function ensure(g,plan,o){
    const src={'rv-dim':WORLD,'rv-land':fc(plan.land?.polyline?.length>1||plan.polyline?.length>1?[line((plan.land||plan).polyline,'land')]:[]),
      'rv-water':fc(plan.water?.polyline?.length>1?[line(plan.water.polyline,'water')]:[]),'rv-pts':fc(points(plan,o))};
    for(const [id,data] of Object.entries(src)){if(g.getSource(id))g.getSource(id).setData(data);else g.addSource(id,{type:'geojson',data});}
    const add=(layer)=>{if(g.getLayer(layer.id))g.removeLayer(layer.id);g.addLayer(layer);};
    add({id:'rv-dim',type:'fill',source:'rv-dim',paint:{'fill-color':'#06090d','fill-opacity':.5}});
    add({id:'rv-casing-land',type:'line',source:'rv-land',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#06090d','line-width':9,'line-opacity':.9}});
    add({id:'rv-casing-water',type:'line',source:'rv-water',layout:{'line-cap':'round'},paint:{'line-color':'#06090d','line-width':9,'line-opacity':.9}});
    // keep the existing route layers (same data as the Rota tab) above the dim
    for(const id of ['route-land','route-water','route-launch'])if(g.getLayer(id))g.moveLayer(id);
    if(g.getLayer('route-land'))g.setPaintProperty('route-land','line-width',5);
    if(g.getLayer('route-water'))g.setPaintProperty('route-water','line-width',5);
    add({id:'rv-ring',type:'circle',source:'rv-pts',paint:{'circle-radius':['match',['get','kind'],'dest',17,'base',14,10],'circle-color':'rgba(0,0,0,0)','circle-stroke-width':3,
      'circle-stroke-color':['match',['get','kind'],'dest','#ff6b6b','base','#51d6ae','#fff1a8']}});
    add({id:'rv-pts',type:'circle',source:'rv-pts',paint:{'circle-radius':6,'circle-color':['match',['get','kind'],'dest','#ff6b6b','base','#51d6ae','#fff1a8'],'circle-stroke-width':2,'circle-stroke-color':'#0f1419'}});
    add({id:'rv-label',type:'symbol',source:'rv-pts',layout:{'text-field':['get','label'],'text-font':['Noto Sans Regular'],'text-size':13,'text-offset':[0,1.7],'text-anchor':'top','text-allow-overlap':true},
      paint:{'text-color':'#ffffff','text-halo-color':'#0f1419','text-halo-width':2}});
  }
  function bounds(plan,o){
    const pts=[...((plan.land||plan).polyline||[]),...(plan.water?.polyline||[])];
    if(plan.launch_point)pts.push([plan.launch_point.lon,plan.launch_point.lat]);
    if(o.dest)pts.push(o.dest);
    if(!pts.length)return null;
    let [w,s,e,n]=[180,90,-180,-90];for(const [x,y] of pts){w=Math.min(w,x);e=Math.max(e,x);s=Math.min(s,y);n=Math.max(n,y);}
    return [[w,s],[e,n]];
  }
  const fmt=(n,d=1)=>Number.isFinite(n)?n.toLocaleString('pt-BR',{maximumFractionDigits:d}):'—';
  function summary(plan,o){
    const land=plan.land||plan,w=plan.water;
    const km=(Number(land.land_km)||0)+(Number(w?.km)||0),min=Number.isFinite(plan.eta_seconds)?plan.eta_seconds/60:(Number(land.land_eta_min)||0)+(Number(w?.eta_min)||0);
    const warns=[...(plan.review_pt||[]),...(land.review_pt||[]),...(w?.review_pt||[])].map(t=>String(t).replace(/^REVISAR:\s*/,'')).filter((t,i,a)=>a.indexOf(t)===i);
    return {km,min,depth:w?.max_depth_m,warns,hasWater:!!w};
  }
  function card(plan,o){
    close_card();
    const s=summary(plan,o),b=document.createElement('aside');b.id='route-float';b.setAttribute('role','status');
    const h=document.createElement('strong');h.textContent=`${o.unitLabel||'Unidade'} → ${o.destLabel||'caso'}`;
    const nums=document.createElement('div');nums.className='rf-nums';
    for(const [v,l] of [[fmt(s.km)+' km','distância'],[fmt(s.min,0)+' min','tempo estimado'],[s.hasWater?(s.depth==null?'desconhecida':fmt(s.depth)+' m'):'sem água','maior profundidade']]){
      const d=document.createElement('div'),a=document.createElement('b'),c=document.createElement('small');a.textContent=v;c.textContent=l;d.append(a,c);nums.append(d);}
    const leg=document.createElement('small');leg.className='rf-leg';leg.textContent='── terra   ╌╌ água   ● base   ◉ lançamento   ◎ caso';
    b.append(h,nums,leg);
    if(s.warns.length){const ul=document.createElement('ul');ul.className='rf-warn';for(const t of s.warns.slice(0,3)){const li=document.createElement('li');li.textContent=t;ul.append(li);}if(s.warns.length>3){const li=document.createElement('li');li.textContent=`+${s.warns.length-3} avisos (veja Detalhes)`;ul.append(li);}b.append(ul);}
    const x=document.createElement('button');x.type='button';x.id='route-close';x.className='primary';x.textContent='Fechar rota';x.onclick=()=>hide();b.append(x);
    (document.querySelector('.map-stage')||document.body).append(b);box=b;
  }
  function close_card(){box?.remove();box=null;}
  function show(plan,o={}){
    if(!plan?.reachable)return false;
    opts=o;window.DeskMap.showRoute(plan);
    const g=gl();
    if(g){try{ensure(g,plan,o);const bb=bounds(plan,o);if(bb)g.fitBounds(bb,{padding:{top:90,bottom:150,left:60,right:60},maxZoom:15.5,duration:window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:700});}catch(e){console.warn('route view',e);}}
    card(plan,o);open=true;document.body.classList.add('route-open');return true;
  }
  function hide(){
    if(!open&&!box)return;open=false;document.body.classList.remove('route-open');close_card();
    const g=gl();if(g){for(const id of ['rv-label','rv-pts','rv-ring','rv-casing-water','rv-casing-land','rv-dim'])if(g.getLayer(id))g.removeLayer(id);
      for(const id of ['rv-dim','rv-land','rv-water','rv-pts'])if(g.getSource(id))g.removeSource(id);
      if(g.getLayer('route-land'))g.setPaintProperty('route-land','line-width',4);if(g.getLayer('route-water'))g.setPaintProperty('route-water','line-width',4);}
    window.DeskMap?.showRoute(null);
  }
  return {show,hide,isOpen:()=>open,layers:own};
})();
