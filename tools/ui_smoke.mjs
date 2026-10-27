// CDP click-through for the UX2 flows. Usage: node tools/ui_smoke.mjs [baseUrl] [--shots outdir] [--port 9336] [--size 1920x1080] [--only name,name]
// Launches ONE headless Edge on --port with a throw-away profile, closes it at the end. Exit code 1 if any assertion fails.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf('--' + n); return i >= 0 ? args[i + 1] : d; };
const base = args.find(a => a.startsWith('http')) || 'http://127.0.0.1:8098';
const port = +opt('port', 9336), [W, H] = opt('size', '1920x1080').split('x').map(Number);
const shots = opt('shots', null), only = opt('only', '') ? opt('only', '').split(',') : null;
const EDGE = process.env.EDGE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
if (shots) mkdirSync(shots, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const edge = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'ux2-'))}`,
  `--window-size=${W},${H}`, '--no-first-run', '--disable-extensions', '--disable-sync', '--no-default-browser-check', '--disable-background-networking', '--disable-default-apps', '--disable-gpu-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', 'about:blank'], { stdio: 'ignore' });
let results = [], ws, id = 0; const logs = []; const pending = new Map();
async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find(t => t.type === 'page'); if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); break; }
    } catch { }
    await sleep(500);
  }
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = m => { const d = JSON.parse(m.data); if (d.method === 'Runtime.exceptionThrown') logs.push('EXC ' + (d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 300)); if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') logs.push('ERR ' + d.params.args.map(a => a.value || a.description).join(' ').slice(0, 300)); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
}
const cdp = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
async function ev(expr) {
  const r = await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval error');
  return r.result?.result?.value;
}
async function until(expr, ms = 15000, what = expr) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { const v = await ev(expr); if (v) return v; } catch { } await sleep(150); }
  throw new Error('timeout waiting for: ' + what.slice(0, 120));
}
const click = sel => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)throw new Error('no element ${sel.replace(/'/g, '')}');e.click();return true})()`);
async function shot(name) {
  if (!shots) return;
  const r = await cdp('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(shots, `${name}_${W}x${H}.png`), Buffer.from(r.result.data, 'base64'));
}
async function step(name, fn) {
  if (only && !only.includes(name)) return;
  const t0 = Date.now();
  try { await fn(); results.push({ name, ok: true, ms: Date.now() - t0 }); console.log(`PASS ${name} (${Date.now() - t0} ms)`); }
  catch (e) { results.push({ name, ok: false, err: e.message }); console.log(`FAIL ${name}: ${e.message}`); if (logs.length) console.log('  console:', logs.slice(-4).join(' | ')); try { console.log('  intake:', await ev('document.getElementById("intake-status")?.innerText')); console.log('  hint:', await ev('document.querySelector(".mx-hint")?.innerText')); console.log('  notice:', await ev('document.getElementById("notice")?.innerText')); console.log('  case-body:', (await ev('document.querySelector(".case-body")?.innerText.slice(0,300)')) || ''); } catch { } try { await shot('FAIL_' + name); } catch { } }
}
const NUM = 100 + Math.floor(Math.random() * 800), STREETS = ['Rua Gonçalves Dias', 'Rua Marcílio Dias', 'Av. Sertório', 'Rua Tiradentes', 'Rua Santana'], STREET = STREETS[NUM % STREETS.length];
const selectCase = id => ev(`window.DeskApp.select(${JSON.stringify(id)})`);
const tab = name => ev(`(()=>{window.DeskApp.setTab(${JSON.stringify(name)});return true})()`);

try {
  await connect();
  await cdp('Page.enable'); await cdp('Runtime.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  const nav = async () => { await cdp('Page.navigate', { url: base + '/v2' + (opt('t', '') ? '?t=' + opt('t', '') : '') }); await until('window.DeskApp&&document.querySelectorAll("#queue .queue-item").length>0', 90000, 'queue rendered'); };
  const t0 = Date.now(); await nav(); console.log('first usable paint (queue visible) ms:', Date.now() - t0);
  await sleep(2500);
  let caseId = opt('case', null);
  await step('nova_emergencia', async () => {
    await ev(`(()=>{window.DeskReplay.set('2024-05-08',1439);return true})()`); await until('document.querySelector("#date").value==="2024-05-08"&&window.DeskApp.S.cases.length>0', 20000, 'day 08/05'); await sleep(1500);
    await click('#new-request'); await until('document.querySelector("#new-dialog[open]")', 5000, 'dialog opened');
    await ev(`(()=>{const t=document.querySelector('#request-text');t.value='Estamos na ${STREET}, ${NUM}, Porto Alegre. Somos 4 pessoas, 2 crianças e 1 idoso, a água já passou de 1,5 m e está subindo. Precisamos de barco urgente.';t.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
    await click('#submit-request');
    await until('document.querySelector("#intake-status")?.innerText.match(/fila|analis|conclu/i)', 20000, 'queue state shown');
    await until('document.querySelector("#intake-status")?.innerText.match(/conclu/i)', 90000, 'finished');
    caseId = await ev(`(()=>{const l=window.DeskApp.S.cases.filter(c=>(c.text||'').includes(${JSON.stringify(STREET+', '+NUM)})).sort((a,b)=>Date.parse(b.received_at)-Date.parse(a.received_at));return l[0]&&l[0].case_id})()`);
    if (!caseId) throw new Error('new case not in queue data');
    await shot('ux2_new_emergency');
    await ev(`(()=>{document.querySelector('#close-dialog').click();return true})()`);
  });
  await step('importar_lote', async () => {
    await click('#new-request'); await until('document.querySelector("#new-dialog[open]")', 5000);
    await click('#batch-tab');
    await ev(`(()=>{const t=document.querySelector('#batch-text');t.value=['Casa alagada Rua A 10, 2 idosos precisam de barco','Pessoa acamada sem energia Av. B 200, agua no joelho','Gato preso no telhado Rua C 33'].join('\\n');t.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
    await until('document.querySelector("#batch-count")?.innerText.includes("3")', 3000, 'line count');
    await click('#submit-batch');
    await until('document.querySelector("#intake-status")?.innerText.match(/3 enviadas/)', 20000, 'batch accepted');
    await until('document.querySelector("#intake-status")?.innerText.match(/conclu/i)', 170000, 'batch analysed');
    await ev(`(()=>{document.querySelector('#close-dialog').click();return true})()`);
  });
  await step('meios_no_scroll', async () => {
    if (!caseId) {  // fixture / no new-emergency step: use the first dispatchable candidate at 12:00 (not stale)
      await ev(`(()=>{window.DeskReplay.set('2024-05-08',720);return true})()`);
      await until('document.querySelector("#date").value==="2024-05-08"&&window.DeskApp.S.cases.length>0', 20000); await sleep(1500);
      caseId = await ev(`(()=>{const c=window.DeskApp.S.cases.find(c=>c.result?.decision==='SEND_CANDIDATE'&&c.status==='proposed');return c&&c.case_id})()`);
      if (!caseId) throw new Error('no SEND_CANDIDATE case in the queue');
    }
    await selectCase(caseId); await tab('Meios');
    await until('document.querySelector(".mx-rec")', 60000, 'recommended card');
    await until('document.querySelector("#mx-route")&&!document.querySelector("#mx-route").disabled', 30000, 'route card ready');
    for (let i = 0; i < 4 && !(await ev('/km/.test(document.querySelector(".mx-card b").innerText)')); i++) {  // pick a unit that has a route
      await ev(`(()=>{const s=document.querySelector('#mx-swap');s.selectedIndex=${i + 1};s.dispatchEvent(new Event('change'));return true})()`);
      await until('document.querySelector("#mx-route")&&!document.querySelector("#mx-route").disabled&&document.querySelector(".mx-card b").innerText!=="…"', 30000, 'route card ready (swap)');
    }
    const m = await ev(`(()=>{const b=document.querySelector(".case-body");const checks=document.querySelectorAll(".mx-check input").length;
      const r=document.querySelector("#mx-dispatch").getBoundingClientRect();const last=document.querySelector(".mx-cards").getBoundingClientRect();
      return {checks,scroll:b.scrollHeight-b.clientHeight,btnVisible:r.bottom<innerHeight&&r.top>0,cardsBottom:last.bottom,vh:innerHeight,
        rawCodes:/\\bR0\\d\\d\\b|\\[(?:DEPTH|ROUTE|D_)/.test(b.innerText.split("Detalhes técnicos")[0])}})()`);
    console.log('  meios metrics', JSON.stringify(m));
    if (m.checks < 1 || m.checks > 5) throw new Error('checks=' + m.checks);
    if (!m.btnVisible) throw new Error('Despachar not visible');
    if (m.cardsBottom > m.vh) throw new Error('cards below fold');
    if (m.rawCodes) throw new Error('raw codes visible in main path');
    await shot('ux2_meios');
  });
  await step('checks_gate_dispatch', async () => {
    if (await ev('!document.querySelector("#mx-dispatch").disabled')) throw new Error('Despachar enabled with unticked checks');
    await ev(`(()=>{for(const i of document.querySelectorAll(".mx-check input")){if(!i.checked)i.click();}return true})()`);
    await until('!document.querySelector("#mx-dispatch").disabled', 5000, 'dispatch enabled after ticks');
    await ev(`(()=>{document.querySelector(".mx-check input").click();return true})()`);
    if (!(await ev('document.querySelector("#mx-dispatch").disabled'))) throw new Error('unticking did not disable Despachar');
    await ev(`(()=>{document.querySelector(".mx-check input").click();return true})()`);
  });
  await step('ver_rota', async () => {
    for (let i = 0; i < 4; i++) {  // find a unit type that has a route (amphibious/truck have none on the sample roads)
      await until('document.querySelector("#mx-route")&&!document.querySelector("#mx-route").disabled&&document.querySelector(".mx-card b").innerText!=="…"', 40000, 'route card');
      console.log('  route loop', i, await ev('document.querySelector("#mx-swap").selectedIndex+":"+document.querySelector(".mx-card b").innerText+":"+document.querySelector(".mx-head h3").innerText'));
      if (await ev('/km/.test(document.querySelector(".mx-card b").innerText)')) break;
      await ev(`(()=>{const s=document.querySelector('#mx-swap');s.selectedIndex=${i + 1};s.dispatchEvent(new Event('change'));return JSON.stringify([s.value,s.options.length,[...s.options].map(o=>o.value+'|'+o.text.slice(0,12)),[...window.DeskApp.S.units]])})()`).then(v => console.log('  swapped', v)); await sleep(500);
    }
    await click('#mx-route');
    await until('document.querySelector("#route-float")', 8000, 'floating summary');
    const t = await ev('document.querySelector("#route-float").innerText');
    if (!/km/.test(t) || !/min/.test(t) || !/profundidade/.test(t)) throw new Error('summary lacks km/min/profundidade: ' + t);
    const layers = await ev(`(()=>{const g=window.DeskMap.telemetrySurface().gl;return g?['rv-dim','route-land','route-water','rv-pts'].map(i=>!!g.getLayer(i)):null})()`);
    if (layers && !layers.every(Boolean)) throw new Error('map layers missing ' + layers);
    await sleep(1200); await shot('ux2_route');
    await click('#route-close');
    if (await ev('!!document.querySelector("#route-float")')) throw new Error('summary stays after Fechar rota');
    if (layers && await ev(`!!window.DeskMap.telemetrySurface().gl.getLayer('rv-dim')`)) throw new Error('dim layer stays');
  });
  await step('despachar_undo', async () => {
    const before = await ev(`window.DeskApp.S.cases.find(c=>c.case_id==${JSON.stringify(caseId)}).status`);
    await click('#mx-dispatch');
    await until('document.querySelector("#undo-toast")', 60000, 'undo toast');
    await until(`window.DeskApp.S.cases.find(c=>c.case_id==${JSON.stringify(caseId)}).status.startsWith("ASSIGNED:")`, 45000, 'case ASSIGNED in queue data');
    await shot('ux2_dispatched');
    await tab('Missões');
    await until('/missão atribuída/i.test(document.querySelector(".case-body")?.innerText||"")', 15000, 'mission visible in Missões');
    await click('#undo-dispatch');
    await until(`window.DeskApp.S.cases.find(c=>c.case_id==${JSON.stringify(caseId)}).status===${JSON.stringify(before)}`, 15000, 'status restored after undo');
  });
  await step('replay_picker', async () => {
    await until('document.querySelector("#replay-bar")', 5000, 'replay bar');
    const before = await ev('document.querySelector("#date").value');
    await click('#rp-preset-peak');
    await until('document.querySelector("#date").value==="2024-05-06"&&document.querySelector("#replay-clock").innerText.includes("06/05")', 8000, 'preset applied');
    await until('window.DeskApp.S.cases.length>0', 20000, 'cases reloaded');
    const clk = await ev('document.querySelector("#replay-clock").innerText'); console.log('  clock', clk, 'was', before);
    if (!/08:00/.test(clk)) throw new Error('hour not 08:00: ' + clk);
    await ev(`(()=>{const s=document.querySelector('#replay-hour');s.value='14';s.dispatchEvent(new Event('input',{bubbles:true}));s.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
    await until('document.querySelector("#replay-clock").innerText.includes("14:00")', 5000, 'hour slider');
    await click('#rp-play'); await sleep(2500);
    const adv = await ev('document.querySelector("#replay-clock").innerText'); await click('#rp-play');
    if (adv === clk) throw new Error('play did not advance');
    await shot('ux2_replay');
  });
  await step('dead_buttons', async () => {
    // 1) static: visible buttons that have no handler at all
    const dead = await ev(`(()=>{const out=[];for(const b of document.querySelectorAll('button')){if(b.disabled||b.hidden||!b.offsetParent)continue;if(!b.onclick&&!b.getAttribute('onclick')&&!b.form&&b.type!=='submit'&&!b.dataset.lang&&!b.dataset.mode&&!b.closest('summary,details,.maplibregl-ctrl'))out.push((b.id||'')+'|'+b.outerHTML.slice(0,90));}return out})()`);
    console.log('  buttons without handler:', JSON.stringify(dead));
    // 2) behavioural: click each top-bar / map-tool control and require a visible effect
    const snap = `(()=>JSON.stringify([document.body.className,document.querySelectorAll('dialog[open]').length,[...document.querySelectorAll('main')].map(m=>m.hidden?0:1).join(''),document.querySelector('#notice')?.innerText,document.querySelector('#more-menu')?.open,document.querySelector('#layers-menu')?.open,document.querySelector('#dimension')?.getAttribute('aria-pressed'),document.querySelector('#light')?.checked,document.querySelector('#dispatch')?.className,document.querySelector('#supervisor-panel,#timeline-panel')?.outerHTML.length,document.querySelector('.maplibregl-canvas')?.width,[...document.querySelectorAll('#supervisor-panel,#timeline-panel')].map(p=>p.hidden?0:1).join(''),document.querySelector('#date')?.value,document.querySelector('#replay-clock')?.innerText,document.querySelector('#rp-play')?.innerText,document.querySelector('#rp-s10')?.getAttribute('aria-pressed')]))()`;
    const targets = ['#supervisor-toggle', '#timeline-toggle', '#live-open', '#system-light', '#resources', '#dimension', '#light', '#toggle-queue', '#more-btn', '#layers-menu summary', '#new-request', '#rp-play', '#rp-s10', '#rp-prev', '#rp-next'];
    const report = [];
    for (const sel of targets) {
      const exists = await ev(`!!document.querySelector(${JSON.stringify(sel)})&&!document.querySelector(${JSON.stringify(sel)}).disabled`);
      if (!exists) { report.push(sel + ': absent/disabled'); continue; }
      const before = await ev(snap); await click(sel); await sleep(sel.includes('toggle') ? 3500 : 900); const after = await ev(snap);
      report.push(`${sel}: ${before !== after ? 'effect' : 'NO VISIBLE EFFECT'}`);
      await ev(`(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());if(window.DeskReplay?.isPlaying())document.querySelector('#rp-play').click();const b=document.querySelector('#back-dispatch');if(b&&!b.hidden)b.click();return true})()`);
      await sleep(250);
    }
    console.log('  click audit:' + String.fromCharCode(10) + '    ' + report.join(String.fromCharCode(10) + '    '));
    if (report.some(r => r.includes('NO VISIBLE EFFECT'))) throw new Error('dead controls: ' + report.filter(r => r.includes('NO VISIBLE')).join('; '));
  });
} catch (e) { console.log('HARNESS ERROR', e.message); results.push({ name: 'harness', ok: false, err: e.message }); }
finally {
  try { ws?.close(); } catch { }
  edge.kill();
  const bad = results.filter(r => !r.ok);
  console.log(`\n${results.length - bad.length}/${results.length} steps passed`);
  process.exit(bad.length ? 1 : 0);
}
