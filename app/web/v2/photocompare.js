'use strict';
// Photo compare overlay (video tooling): real geotagged flood photos as framed cards with a leader line anchored to the exact coordinates.
// Lazy-loaded by map.js when the URL has ?tour=photos (or Alt+Shift+P). Console API:
//   DeskPhotoTour.start({interval:3200})      fade the cards in one by one (works in 2D canvas fallback and in 3D MapLibre)
//   DeskPhotoTour.clear()                     remove cards
//   DeskPhotoTour.cameraPath({duration:6000}) 2D overview -> tilt to 3D over the flooded 4o Distrito / Centro (buildings on), returns a Promise
//   DeskPhotoTour.run()                       cameraPath() then start()
// Photos: Wikimedia Commons, CC BY 4.0 (data/photos/ATTRIBUTION.md). Taken 2024-05-21 (after the 6-8 May peak): shown as post-event illustration only.
// All 4 sit inside the observed 2024-05-06 flood polygon AND inside 3D zone 'centro_rodoviaria' (~1.0-2.0 km from the Rodoviária).
window.DeskPhotoTour=(()=>{
  const PHOTOS=[
    {id:'148627044',lon:-51.228236,lat:-30.027133,slot:'tl',note:'Rua do 4º Distrito, oeste da Rodoviária'},
    {id:'148626724',lon:-51.229992,lat:-30.029628,slot:'bl',note:'Água parada entre prédios, perto do Guaíba'},
    {id:'148626709',lon:-51.225278,lat:-30.041,slot:'br',note:'Centro, ao sul da Rodoviária'},
    {id:'148626704',lon:-51.221792,lat:-30.043592,slot:'tr',note:'Av. perto do Mercado/Centro'}];
  const AUTHOR='CarolSiBa',LICENSE='CC BY 4.0',ORIGIN=[-51.2275,-30.0345];
  let root=null,svg=null,items=[],hooked=null,raf=0;
  const $=id=>document.getElementById(id),mk=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!==undefined)n.textContent=x;return n;};
  const gl=()=>window.DeskMap?.telemetrySurface?.().gl||null;
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  function project(p){
    const g=gl(),stage=document.querySelector('.map-stage');
    if(g){const v=g.project(p);return [v.x,v.y];}
    const s=window.DeskMap.telemetrySurface(),r=stage.getBoundingClientRect(),scale=Math.min(r.width/.036,r.height/.028),c=s.center;
    return [r.width/2+(p[0]-c[0])*scale*Math.cos(c[1]*Math.PI/180),r.height/2-(p[1]-c[1])*scale];
  }
  function mount(){
    if(root)return;const stage=document.querySelector('.map-stage');if(!stage)throw new Error('map-stage ausente');
    root=mk('div');root.id='photo-tour';root.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:6;overflow:hidden';
    svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','100%');svg.setAttribute('height','100%');svg.style.cssText='position:absolute;inset:0';
    root.append(svg);stage.append(root);
    const style=mk('style');style.textContent='#photo-tour .pt-card{position:absolute;width:236px;background:#0f1a21;border:2px solid #f4d67d;border-radius:6px;box-shadow:0 8px 28px #000a;opacity:0;transform:translateY(8px) scale(.97);transition:opacity .8s ease,transform .8s ease;color:#e6edf3;font:12px/1.35 system-ui}#photo-tour .pt-card.on{opacity:1;transform:none}#photo-tour img{display:block;width:100%;height:150px;object-fit:cover;border-radius:4px 4px 0 0}#photo-tour .pt-cap{padding:6px 8px}#photo-tour .pt-cap b{display:block;color:#f4d67d}#photo-tour .pt-cap small{color:#a9b9c5;display:block}#photo-tour .pt-dot{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:3px solid #f4d67d;background:#e5484d88;opacity:0;transition:opacity .6s}#photo-tour .pt-dot.on{opacity:1;animation:ptpulse 1.8s infinite}@keyframes ptpulse{0%{box-shadow:0 0 0 0 #f4d67daa}100%{box-shadow:0 0 0 18px #f4d67d00}}#photo-tour line{stroke:#f4d67d;stroke-width:2;stroke-dasharray:6 4;opacity:0;transition:opacity .8s}#photo-tour line.on{opacity:1}';
    root.append(style);
  }
  function place(it){
    const stage=document.querySelector('.map-stage').getBoundingClientRect(),w=236,h=210,m=18,s=it.photo.slot;
    const x=s.endsWith('l')?m:stage.width-w-m,y=s.startsWith('t')?m+8:stage.height-h-m-30;
    it.card.style.left=x+'px';it.card.style.top=y+'px';
    const a=project([it.photo.lon,it.photo.lat]);it.dot.style.left=a[0]+'px';it.dot.style.top=a[1]+'px';
    const cx=x+w/2,cy=y+(s.startsWith('t')?h:0);it.line.setAttribute('x1',cx);it.line.setAttribute('y1',cy);it.line.setAttribute('x2',a[0]);it.line.setAttribute('y2',a[1]);
  }
  function loop(){raf=0;items.forEach(place);if(items.length&&!raf)raf=requestAnimationFrame(loop);}
  function hook(){const g=gl();if(g&&g!==hooked){hooked=g;}}
  async function start(opts={}){
    mount();clear();hook();const interval=opts.interval||3200,list=(opts.photos||PHOTOS);
    for(const photo of list){
      const card=mk('div','pt-card'),img=mk('img'),cap=mk('div','pt-cap'),dot=mk('div','pt-dot');
      img.src=`/v2/photos/thumbs/${photo.id}.jpg`;img.alt=photo.note;
      cap.append(mk('b',null,photo.note),mk('small',null,`Foto de 21/05/2024 · pós-pico · ilustração, não prova da data do pedido`),mk('small',null,`© ${AUTHOR} · ${LICENSE} · Wikimedia Commons`));
      card.append(img,cap);const line=document.createElementNS('http://www.w3.org/2000/svg','line');
      root.append(card,dot);svg.append(line);const it={photo,card,dot,line};items.push(it);place(it);
      if(!raf)raf=requestAnimationFrame(loop);
      await sleep(60);card.classList.add('on');dot.classList.add('on');line.classList.add('on');
      await sleep(interval);
    }
    return items.length;
  }
  function clear(){items=[];cancelAnimationFrame(raf);raf=0;if(root){[...root.querySelectorAll('.pt-card,.pt-dot')].forEach(n=>n.remove());svg.replaceChildren();}}
  // 2D overview -> tilt to 3D. Returns when the camera stopped.
  async function cameraPath(o={}){
    const g=gl();if(!g)return 'sem MapLibre (fica no 2D)';
    const d=o.duration||6000,btn=$('dimension');
    g.jumpTo({center:o.from?.slice(0,2)||[-51.215,-30.02],zoom:o.from?.[2]||12.2,pitch:0,bearing:0});await sleep(900);
    if(btn&&btn.getAttribute('aria-pressed')!=='true')btn.click();   // turns buildings + 3D on (map.js)
    const terrain=document.querySelector('#layer-options input[type=checkbox]:last-of-type');
    g.flyTo({center:o.to?.slice(0,2)||ORIGIN,zoom:o.to?.[2]||14.8,pitch:o.to?.[3]??58,bearing:o.to?.[4]??-22,duration:d,essential:true});
    await new Promise(r=>g.once('moveend',r));await sleep(600);return 'ok';
  }
  async function run(){await cameraPath();return start();}
  // hidden key: Alt+Shift+P runs the whole sequence
  addEventListener('keydown',e=>{if(e.altKey&&e.shiftKey&&e.code==='KeyP')run();});
  if(/[?&]tour=photos/.test(location.search))setTimeout(()=>{try{run();}catch(e){console.error(e);}},(window.DeskMap?1500:4000));
  return {start,clear,cameraPath,run,photos:PHOTOS};
})();
