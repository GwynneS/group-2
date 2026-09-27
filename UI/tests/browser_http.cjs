// Real content.js -> real background.js -> real Python HTTP handler.
// DOM and Chrome APIs are simulated; this does not install an extension.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const [root, base, mode] = process.argv.slice(2);
const pending = [];
const messages = [];
const stored = {};
let handler;
const api = {
  runtime: {
    onMessage: {addListener(fn) { handler = fn; }},
    getURL: file => "chrome-extension://test/" + file,
    sendMessage(message) {
      messages.push(message);
      return new Promise(resolve => {
        const wait = handler(message, {tab: {id: 1}}, resolve);
        if (wait !== true) resolve();
      });
    },
  },
  storage: {
    local: {get: async () => ({...stored}), set: async data => Object.assign(stored, data)},
    onChanged: {addListener() {}},
  },
};
function load(context, file) {
  vm.runInContext(fs.readFileSync(path.join(root, "browser_extension", file), "utf8"), context, {filename: file});
}
const background = vm.createContext({
  console, chrome: api, AbortSignal, URL,
  fetch(url, options) {
    const request = fetch(base + new URL(url).pathname, options);
    pending.push(request);
    return request;
  },
});
load(background, "config.js");
load(background, "characters.js");
load(background, "background.js");

let clock = 1000;
const events = {};
const intervals = [];
const on = target => (type, fn) => (events[target + ":" + type] ??= []).push(fn);
const fire = (target, type, event = {}) => (events[target + ":" + type] ?? []).forEach(fn => fn(event));
const document = {
  title: "HTTP regression", visibilityState: "visible", hasFocus: () => true, activeElement: null,
  documentElement: {scrollHeight: 2000, clientHeight: 1000, scrollTop: 0},
  addEventListener: on("document"),
};
const content = vm.createContext({
  console, chrome: api, document,
  performance: {now: () => clock},
  location: {href: "https://example.com/", hostname: "example.com"},
  window: {addEventListener: on("window")}, HTMLIFrameElement: class {},
  setInterval: (fn, ms) => intervals.push({fn, ms}), setTimeout,
});
load(content, "content.js");
const beat = () => intervals.find(item => item.ms === 5000).fn();
async function main() {
  assert.equal(typeof handler, "function");
  if (mode === "input") {
    fire("document", "keydown", {isTrusted: true, key: "secret-text"});
    fire("document", "copy", {isTrusted: true, clipboardData: {getData: () => "secret-clipboard"}});
  } else {
    fire("document", "keydown", {isTrusted: false});
  }
  beat();
  clock += 5000;
  beat();
  await Promise.all(pending);
  const data = await api.runtime.sendMessage({type: "appState", page: {title: document.title, host: "example.com"}});
  assert.ok(data && data.brain === "running");
  for (const key of ["onpage_mode", "behavior", "pet", "activity", "voice", "distraction_budget", "decision_age_ms"]) {
    assert.ok(key in data, "Missing API field: " + key);
  }
  const beats = messages.filter(message => message.type === "heartbeat").map(message => message.data);
  assert.equal(beats[0].inputAgeMs, mode === "input" ? 0 : null);
  assert.equal(beats[1].inputAgeMs, mode === "input" ? 5000 : null);
  assert.equal(beats[1].keys, 0);
  const encoded = JSON.stringify(messages);
  assert.ok(!encoded.includes("secret-text") && !encoded.includes("secret-clipboard"));
  if (mode === "input") {
    const result = await api.runtime.sendMessage({type: "interact", action: "pet"});
    assert.equal(result.accepted, true);
    assert.ok(result.state.pet);
  }
  console.log(JSON.stringify({rendererContract: true, keys: beats[0].keys, inputAges: beats.map(b => b.inputAgeMs)}));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
