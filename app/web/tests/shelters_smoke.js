'use strict';
// Offline regression: deliver mutation records after the handler returns, like browsers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const observers = [];
let callbacks = 0;
class MutationObserver {
  constructor(callback) { this.callback = callback; this.targets = new Map(); this.records = []; observers.push(this); }
  observe(target, options) { this.targets.set(target, options); }
}
function mutation(target, type, attributeName) {
  for (const observer of observers) {
    const options = observer.targets.get(target);
    if (options && (type === 'childList' ? options.childList : options.attributes && options.attributeFilter.includes(attributeName))) {
      observer.records.push({target, type, attributeName});
    }
  }
}
function flush() {
  const start = callbacks;
  while (observers.some(o => o.records.length)) {
    assert.ok(callbacks - start < 10, 'observer callbacks must settle within 10 deliveries');
    for (const observer of observers) {
      if (!observer.records.length) continue;
      const records = observer.records.splice(0);
      callbacks++;
      observer.callback(records);
    }
  }
  return callbacks - start;
}
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this._hidden = false; this._text = ''; }
  set hidden(value) { this._hidden = value; mutation(this, 'attributes', 'hidden'); }
  get hidden() { return this._hidden; }
  set textContent(value) { this._text = value; this.children = []; mutation(this, 'childList'); }
  get textContent() { return this._text; }
  append(...nodes) {
    for (const node of nodes) {
      if (node.parentElement) node.remove();
      node.parentElement = this; this.children.push(node); mutation(this, 'childList');
    }
  }
  remove() {
    const parent = this.parentElement;
    if (parent) { parent.children.splice(parent.children.indexOf(this), 1); this.parentElement = null; mutation(parent, 'childList'); }
  }
  insertBefore(node, before) { node.parentElement = this; this.children.splice(this.children.indexOf(before), 0, node); mutation(this, 'childList'); }
  after(node) { this.parentElement.append(node); }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this.append(...nodes); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener() {}
  querySelectorAll(selector) {
    const match = n => selector === '[data-case]' ? !!n.dataset.case : (n.className || '').split(' ').includes(selector.slice(1));
    return this.children.flatMap(n => [...(match(n) ? [n] : []), ...n.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const body = new Element('body');
const ids = ['dispatch', 'agents', 'situation', 'data', 'flow', 'back-dispatch', 'date', 'queue'];
for (const id of ids) { const node = new Element('div'); node.id = id; body.append(node); }
const nav = new Element('nav'); body.append(nav);
function find(id, node = body) { return node.id === id ? node : node.children.map(n => find(id, n)).find(Boolean); }
const document = {
  body, readyState: 'complete', getElementById: id => find(id), createElement: tag => new Element(tag),
  querySelector: selector => selector === '.map-tools nav' ? nav : null,
  querySelectorAll: () => nav.children.filter(n => n.dataset.mode),
};
const medical = hours => ({time_to_harm_hours: [hours, hours + 2], waited_hours: 0, needs: [{label_pt: 'apoio'}]});
const S = {cases: [{case_id: 'ordinary'}, {case_id: 'slow', medical: medical(8)}, {case_id: 'fast', medical: medical(1)}]};
const queue = find('queue');
function row(id) { const node = new Element('article'); node.dataset.case = id; return node; }
queue.append(...S.cases.map(c => row(c.case_id)));
const window = {DeskMap: {resize() {}}, DeskFlow: {stop() {}, renderSystem() {}}};
const context = {window, document, S, MutationObserver,
  // Keep the shelter request pending: navigation is independent of its response.
  fetch: () => new Promise(() => {}), drawAgents() {}, drawSituation() {}, drawData() {}};
vm.createContext(context);
const ui = path.join(__dirname, '../v2');
vm.runInContext(fs.readFileSync(path.join(ui, 'shelters.js'), 'utf8'), context);
// Exercise the actual app navigation function and back-button handler.
const app = fs.readFileSync(path.join(ui, 'app.js'), 'utf8');
vm.runInContext("const $=id=>document.getElementById(id);\n" + app.match(/^function mode\(name\).*$/m)[0] +
  "\n$('back-dispatch').onclick=()=>mode('dispatch');", context);
flush();
const toggle = find('medical-toggle');
for (let cycle = 0; cycle < 2; cycle++) {
  toggle.onclick();
  assert.ok(flush() <= 2);
  assert.equal(window.DeskShelters.medicalOnly(), true);
  assert.deepEqual(queue.children.filter(n => n.dataset.case && !n.hidden).map(n => n.dataset.case), ['fast', 'slow']);
  assert.equal(toggle.attributes['aria-pressed'], 'true');
  toggle.onclick();
  assert.ok(flush() <= 2);
  assert.equal(window.DeskShelters.medicalOnly(), false);
  assert.ok(queue.children.filter(n => n.dataset.case).every(n => !n.hidden));
}
// External queue redraws must still trigger filtering and sorting.
toggle.onclick(); flush();
queue.replaceChildren(row('ordinary'), row('slow'), row('fast'));
assert.ok(flush() <= 2);
assert.deepEqual(queue.children.filter(n => !n.hidden).map(n => n.dataset.case), ['fast', 'slow']);
queue.replaceChildren(row('ordinary'));
assert.ok(flush() <= 2);
assert.ok(queue.querySelector('.medical-empty'));
toggle.onclick(); flush();
assert.equal(queue.querySelector('.medical-empty'), null);
queue.replaceChildren(row('ordinary'), row('slow'), row('fast')); flush();
toggle.onclick(); flush();
assert.equal(window.DeskShelters.medicalOnly(), true);
for (const destination of ['dispatch', 'agents', 'situation', 'data', 'flow']) {
  find('shelters-nav').onclick(); flush();
  assert.equal(find('shelters').hidden, false);
  if (destination === 'dispatch') find('back-dispatch').onclick();
  else vm.runInContext(`mode('${destination}')`, context);
  assert.ok(flush() <= 1);
  assert.equal(find('shelters').hidden, true);
  assert.equal(find(destination).hidden, false);
  assert.equal(find('shelters-nav').attributes['aria-current'], undefined);
}
console.log(`Shelters smoke passed: ${callbacks} observer callbacks; medical toggles, redraws, empty queue, back and all navigation destinations.`);
