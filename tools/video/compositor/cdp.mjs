import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
// Scratch root for throwaway browser profiles: RTD_SCRATCH, else the OS temp dir.
export const S=process.env.RTD_SCRATCH||path.join(os.tmpdir(),'rtd-video');
export const sleep=ms=>new Promise(r=>setTimeout(r,ms));
export async function connect(port){
 const targets=await(await fetch(`http://127.0.0.1:${port}/json`)).json();
 const target=targets.find(x=>x.type==='page');if(!target)throw Error('No page');
 const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
 let id=0;const pending=new Map();ws.onmessage=e=>{let m=JSON.parse(e.data);if(pending.has(m.id)){let p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)}};
 const send=(method,params={})=>new Promise((resolve,reject)=>{let n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))});
 const evaluate=async expression=>{let r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));return r.result.value};
 return {send,evaluate,close:()=>ws.close(),target};
}
export async function launch(port,url,headless=false){
 if(port<9341||port>9349)throw Error('Port outside video allocation');
 const profile=path.join(S,`vidprof/${headless?'render':'capture'}-${port}-${Date.now()}`);fs.mkdirSync(profile,{recursive:true});
 let args=[`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','--disable-features=msEdgeSidebarV2','--mute-audio','--force-device-scale-factor=1',`--window-position=${headless?0:1920},0`,'--window-size=1920,1080'];
 if(headless)args.push('--headless=new','--hide-scrollbars',url);else args.push(`--app=${url}`);
 let proc=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args,{stdio:'ignore',windowsHide:headless});
 for(let i=0;i<100;i++){try{let c=await connect(port);await c.send('Page.enable');await c.send('Runtime.enable');return {proc,cdp:c,profile}}catch{}await sleep(200)}
 throw Error('Edge did not start');
}
export async function close(browser){try{await browser.cdp.send('Browser.close')}catch{}browser.cdp.close();}
