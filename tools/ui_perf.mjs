// Load + interaction timings over CDP. Usage: node tools/ui_perf.mjs [baseUrl] [--port 9336] [--warm]
// Prints: time to first usable paint (queue visible), slowest resources, case switch and tab switch latency, 600-card queue render time.
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const args = process.argv.slice(2), base = args.find(a => a.startsWith('http')) || 'http://127.0.0.1:8098';
const pi = args.indexOf('--port'), port = pi >= 0 ? +args[pi + 1] : 9336;
const EDGE = process.env.EDGE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const already = await fetch(`http://127.0.0.1:${port}/json/version`).then(() => true, () => false);
const edge = already ? { kill() {} } : spawn(EDGE, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'ux2p-'))}`, '--window-size=1920,1080', '--no-first-run', '--disable-extensions', '--disable-sync', '--no-default-browser-check', '--disable-background-networking', '--disable-default-apps', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', 'about:blank'], { stdio: 'ignore' });
let ws, id = 0; const pending = new Map();
for (let i = 0; i < 60 && !ws; i++) { try { const l = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); const p = l.find(t => t.type === 'page'); if (p) { ws = new WebSocket(p.webSocketDebuggerUrl); break; } } catch { } await sleep(400); }
await new Promise(r => ws.onopen = r);
ws.onmessage = m => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const cdp = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async e => (await cdp('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true })).result?.result?.value;
const until = async (e, ms = 60000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(e)) return Date.now() - t; await sleep(50); } throw new Error('timeout ' + e); };
try {
  console.error('connected'); await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Performance.enable'); console.error('enabled');
  const out = {};
  for (const round of ['cold', 'warm']) {
    const t0 = Date.now();
    await cdp('Page.navigate', { url: base + '/v2?t=2024-05-08T12:00' });
    await until('window.DeskApp&&document.querySelectorAll("#queue .queue-item").length>0');
    out[round + '_first_usable_paint_ms'] = Date.now() - t0;
    await sleep(3000);
    if (round === 'cold') {
      out.top_resources = await ev(`performance.getEntriesByType('resource').map(r=>[r.name.replace(location.origin,''),Math.round(r.duration),r.transferSize,r.encodedBodySize]).sort((a,b)=>b[1]-a[1]).slice(0,6)`);
      out.js_css_encoded_kb = await ev(`Math.round(performance.getEntriesByType('resource').filter(r=>/\\.(js|css)/.test(r.name)).reduce((a,r)=>a+r.encodedBodySize,0)/1024)`);
      out.requests = await ev(`performance.getEntriesByType('resource').length`);
    }
  }
  const m = await cdp('Performance.getMetrics'); out.metrics = Object.fromEntries(m.result.metrics.filter(x => ['ScriptDuration', 'LayoutDuration', 'RecalcStyleDuration', 'JSHeapUsedSize'].includes(x.name)).map(x => [x.name, +x.value.toFixed(3)]));
  // case switch latency (to the first paint of the new header) and tab switch latency
  out.case_switch_ms = await ev(`(async()=>{const ids=window.DeskApp.S.cases.slice(0,6).map(c=>c.case_id),t=[];for(const i of ids){const a=performance.now();window.DeskApp.select(i);await new Promise(r=>requestAnimationFrame(()=>r()));t.push(performance.now()-a);}return t.map(x=>Math.round(x))})()`);
  out.tab_switch_ms = await ev(`(async()=>{const t=[];for(const n of ['Retorno','Registro','Resumo','Retorno']){const a=performance.now();window.DeskApp.setTab(n);await new Promise(r=>requestAnimationFrame(()=>r()));t.push(performance.now()-a);}return t.map(x=>Math.round(x))})()`);
  out.queue_600_render_ms = await ev(`(()=>{const S=window.DeskApp.S,base=S.cases.slice(),big=[];for(let i=0;i<600;i++){const c=structuredClone(base[i%base.length]);c.case_id='perf'+i;big.push(c);}S.cases=big;const a=performance.now();window.DeskApp.drawQueue?window.DeskApp.drawQueue():0;const b=performance.now()-a;S.cases=base;return {ms:Math.round(b),items:document.querySelectorAll('#queue .queue-item').length}})()`);
  console.log(JSON.stringify(out, null, 1));
} finally { ws.close(); edge.kill(); process.exit(0); }
