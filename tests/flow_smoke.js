'use strict';
// Fake-DOM smoke for app/web/v2/flow.js: renders the per-case swimlane and the system view from a recorded /api/flow payload.
const fs = require('fs'), assert = require('assert');
class Node {
  constructor(tag, ns) { this.tag = tag; this.ns = ns; this.children = []; this.attrs = {}; this.hidden = false; this.className = ''; this.textContent = ''; this.isConnected = true; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  append(...xs) { for (const x of xs) this.children.push(typeof x === 'string' ? Object.assign(new Node('#text'), { textContent: x }) : x); }
  replaceChildren(...xs) { this.children = []; this.append(...xs); }
  walk(f) { f(this); for (const c of this.children) c.walk(f); }
}
global.document = {
  createElement: t => new Node(t), createElementNS: (ns, t) => new Node(t, ns), getElementById: () => null,
};
global.window = {};
const graph = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const calls = [];
const Flow = require('../app/web/v2/flow.js');
const el = (tag, text, cls) => { const n = new Node(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
Flow.init({
  api: async path => { calls.push(path); return graph; }, el,
  button: (text, fn, cls) => { const b = el('button', text, cls); b.onclick = fn; return b; },
  evidence: (title, data) => el('details', title + JSON.stringify(data)), openCase: () => {},
});
(async () => {
  const body = el('div'); Flow.renderCase(body, { case_id: 'js1' });
  await new Promise(r => setTimeout(r, 20));
  let edges = 0, failed = 0, gates = 0, lanes = 0;
  body.walk(n => {
    if (n.attrs['data-edge']) { edges++; if (/st-failed/.test(n.attrs.class)) failed++; }
    if (n.tag === 'rect' && /flow-gate/.test(n.attrs.class || '')) gates++;
    if (n.tag === 'text' && /flow-lane-label/.test(n.attrs.class || '')) lanes++;
  });
  assert.strictEqual(edges, graph.edges.length, 'one SVG mark per recorded edge');
  assert.ok(failed >= 1, 'failed edge must be drawn distinctly');
  assert.ok(gates >= 1, 'human gate must be drawn');
  assert.ok(lanes >= 3);
  assert.ok(calls[0].includes('case_id=js1'));
  const L = Flow.layout(graph.nodes, graph.edges);
  assert.ok(L.marks.every((m, i) => i === 0 || m.x > L.marks[i - 1].x), 'columns follow event order');
  const root = el('main'); Flow.renderSystem(root);
  await new Promise(r => setTimeout(r, 20));
  let rows = 0; root.walk(n => { if (n.tag === 'tr') rows++; });
  assert.ok(rows >= 2, 'stats table rendered');
  Flow.stop();
  console.log('FLOW_SMOKE_OK edges=' + edges + ' failed=' + failed + ' gates=' + gates);
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
