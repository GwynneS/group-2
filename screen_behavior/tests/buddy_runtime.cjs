// Execute the real buddy.js with a small DOM/browser mock. This is a runtime
// regression check, not a replacement for testing in an installed browser.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("node:assert/strict");
const rootDir = process.argv[2];
let clock = 1000;
let raf;
let shadow;
let state = {behavior: "study_with_user", onpage_mode: "idle", animation: "encouragement", message: "Studying with you"};
const intervals = [];
const events = {};
const documentEvents = {};
const requests = [];
const on = (map, type, callback) => (map[type] ??= []).push(callback);
class Element {
  constructor(name = "") {
    this.name = name;
    this.children = new Map();
    this.listeners = {};
    this.style = {};
    this.dataset = {};
    this.hidden = true;
    this.textContent = "";
    this.src = "";
    this.value = "";
    this.naturalWidth = 300;
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  querySelector(selector) {
    if (!this.children.has(selector)) this.children.set(selector, new Element(selector));
    return this.children.get(selector);
  }
  querySelectorAll(selector) {
    if (this.name === ".picker" && selector === "button") {
      return ["girl", "boy"].map(character => {
        const button = this.querySelector(character);
        button.dataset.char = character;
        return button;
      });
    }
    return [];
  }
  attachShadow() { shadow = new Element("shadow"); return shadow; }
  addEventListener(type, callback) { on(this.listeners, type, callback); }
  append() {}
  prepend() {}
  remove() {}
  replaceChildren() {}
  setAttribute() {}
  setPointerCapture() {}
  focus() {}
  contains() { return false; }
  getBoundingClientRect() { return {left: 500, top: 100, right: 700, bottom: 400}; }
}
class FakeDate extends Date { static now() { return clock; } }
const stored = {buddy: {character: "girl", visible: true}, lastFed: 1, chat: []};
const sandbox = {
  console,
  Date: FakeDate,
  performance: {now: () => clock},
  innerWidth: 1200,
  innerHeight: 800,
  location: {hostname: "example.com", port: ""},
  matchMedia: () => ({matches: true}),
  Image: class { constructor() { this.src = ""; } },
  setInterval: (callback, ms) => intervals.push({callback, ms}),
  setTimeout: () => 1,
  clearTimeout() {},
  requestAnimationFrame: callback => { raf = callback; },
  addEventListener: (type, callback) => on(events, type, callback),
  document: {
    documentElement: new Element("html"),
    visibilityState: "visible",
    hasFocus: () => true,
    title: "Test page",
    createElement: name => new Element(name),
    addEventListener: (type, callback) => on(documentEvents, type, callback),
  },
  chrome: {
    runtime: {
      getURL: relative => "chrome-extension://test/" + relative,
      sendMessage: async message => {
        requests.push(message);
        if (message.type === "appState") return {...state};
        if (message.type === "interact") return {accepted: true};
        throw new Error("Unexpected message type: " + message.type);
      },
    },
    storage: {
      local: {get: async () => ({...stored}), set: async () => {}},
      onChanged: {addListener() {}},
    },
  },
};
sandbox.window = sandbox;
sandbox.top = sandbox;
const context = vm.createContext(sandbox);
for (const file of ["characters.js", "buddy.js"]) {
  vm.runInContext(fs.readFileSync(path.join(rootDir, "browser_extension", file), "utf8"), context, {filename: file});
}
async function settle() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
async function poll() {
  await intervals.find(item => item.ms === 4000).callback();
  await settle();
}
function frame(ms = 16) { clock += ms; assert.equal(typeof raf, "function"); raf(clock); }
async function main() {
  await settle();
  const wrap = shadow.querySelector(".wrap");
  const figure = wrap.querySelector(".buddy-figure");
  const bubble = shadow.querySelector(".bubble");
  assert.equal(wrap.hidden, false);
  frame();
  const atRest = wrap.style.transform;
  for (let i = 0; i < 8; i++) { await poll(); frame(3000); }
  assert.equal(wrap.style.transform, atRest, "brain-controlled idle must not start random wandering");
  state = {...state, behavior: "sleep", onpage_mode: "sleep", animation: "tired"};
  await poll(); frame();
  assert.ok(figure.src.endsWith("/tired.png"));
  for (const callback of events.mousemove ?? []) callback({clientX: 100, clientY: 100});
  frame();
  assert.ok(figure.src.endsWith("/tired.png"), "mouse motion must not override the current brain decision");
  state = {...state, behavior: "ask_for_attention", onpage_mode: "attention", animation: "sad", message: "A little attention?"};
  await poll(); frame();
  assert.equal(bubble.textContent, state.message);
  state = {...state, behavior: "study_with_user", onpage_mode: "idle", animation: "encouragement"};
  await poll(); frame();
  const focusedPosition = wrap.style.transform;
  for (let i = 0; i < 5; i++) { await poll(); frame(3000); }
  assert.equal(wrap.style.transform, focusedPosition);
  // Tab switching alone must not invent a missed-you/return reaction.
  sandbox.document.visibilityState = "hidden";
  for (const callback of documentEvents.visibilitychange ?? []) callback();
  clock += 61000;
  sandbox.document.visibilityState = "visible";
  for (const callback of documentEvents.visibilitychange ?? []) callback();
  await settle(); frame();
  assert.ok(figure.src.endsWith("/encouragement.png"), "tab return must keep the brain pose");
  // Programmatic clipboard events must not be reported as real input.
  for (const callback of documentEvents.copy ?? []) callback({isTrusted: false});
  for (const callback of documentEvents.paste ?? []) callback({isTrusted: false});
  // A responding HTTP server cannot make an old brain decision fresh.
  state = {...state, behavior: "sleep", onpage_mode: "sleep", animation: "tired", decision_age_ms: 12000};
  await poll();
  for (const callback of events.mousemove ?? []) callback({clientX: 100, clientY: 100});
  frame();
  assert.ok(!figure.src.endsWith("/tired.png"), "stale brain output must release control");
  state = {...state, decision_age_ms: 0};
  await poll(); frame();
  assert.ok(figure.src.endsWith("/tired.png"), "a new brain decision must regain control");
  assert.ok(requests.length > 0);
  assert.ok(requests.every(message => message.type === "appState"));
  console.log(JSON.stringify({started: true, brainControlled: true, sleepRespected: true, attentionCaption: true}));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
