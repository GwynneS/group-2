// Actual extension relay/player scripts; simulated Chrome/Firefox APIs and
// Audio element. No browser is installed and no physical sound is produced.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict");
const [root, browser] = process.argv.slice(2);
let clock = 1000, creations = 0, failures = 0, open = false;
let current = null;
const plays = [], claims = new Map(), listeners = [], changes = [];
const stored = {buddy: {character: "girl", visible: false}, voiceOn: true};
class FakeDate extends Date { static now() { return clock; } }
class FakeAudio {
  constructor() { this.paused = true; this.ended = false; this.duration = 2; }
  pause() { this.paused = true; }
  removeAttribute() { this.src = ""; }
  async play() {
    if (failures) { failures--; throw new Error("simulated autoplay failure"); }
    this.paused = false;
    plays.push(this.src);
  }
}
const api = {
  runtime: {
    id: "test-extension", getURL: name => "chrome-extension://test/" + name,
    getContexts: async () => open ? [{}] : [],
    onMessage: {addListener(fn) { listeners.push(fn); }},
    sendMessage(message) {
      return new Promise(resolve => {
        let wait = false;
        for (const fn of listeners) if (fn(message, {id: api.runtime.id, tab: {id: 1}}, resolve) === true) wait = true;
        if (!wait) resolve();
      });
    },
  },
  storage: {
    local: {
      get: async () => ({...stored}),
      set: async values => {
        const diff = {};
        for (const [key, value] of Object.entries(values)) { diff[key] = {newValue: value}; stored[key] = value; }
        for (const fn of changes) fn(diff, "local");
      },
    },
    onChanged: {addListener: fn => changes.push(fn)},
  },
};
const load = (context, name) => vm.runInContext(fs.readFileSync(path.join(root, "browser_extension", name), "utf8"), context, {filename:name});
if (browser === "chromium") {
  api.offscreen = {createDocument: async options => {
    assert.deepEqual(Array.from(options.reasons), ["AUDIO_PLAYBACK"]);
    assert.equal(options.url, "voice-offscreen.html");
    creations++;
    open = true;
    const context = vm.createContext({chrome: api, Audio: FakeAudio, URL, setTimeout, clearTimeout});
    load(context, "voice-player.js");
    load(context, "voice-offscreen.js");
  }};
}
let nextEvent = 0;
function event(trigger) { return {key: "session:" + (++nextEvent), id: nextEvent, trigger, seconds: 2.5}; }
const index = Object.fromEntries(["CMDC", "CMDV", "CMDZ", "onReturn"].map(trigger => [trigger, {
  girl: [{url: "/voice/" + trigger + "F1.mp3", text: "Exact " + trigger + " caption"}],
}]));
const fetch = async (url, options = {}) => {
  const pathname = new URL(url).pathname, body = JSON.parse(options.body ?? "{}");
  let data;
  if (pathname === "/api/voices") data = index;
  else if (pathname === "/api/voice/claim") {
    if (body.release) { const owned = claims.get(body.key) === body.owner; if (owned) claims.delete(body.key); data = {claimed:owned}; }
    else { const free = !claims.has(body.key); if (free) claims.set(body.key, body.owner); data = {claimed:free}; }
  } else if (pathname === "/api/presence") data = {voice:current};
  else if (pathname === "/api/shortcut") {
    current = event({copy:"CMDC", paste:"CMDV", undo:"CMDZ"}[body.shortcut]);
    data = {accepted:true, state:{voice:current}};
  } else throw new Error("Unexpected HTTP path " + pathname);
  return {ok:true, status:200, json:async () => data};
};
const background = vm.createContext({console, chrome:api, fetch, AbortSignal, URL, Date:FakeDate, setTimeout, clearTimeout,
  ...(browser === "firefox" ? {Audio:FakeAudio} : {})});
for (const file of ["characters.js", "voice-player.js", "background.js"]) load(background, file);
async function settle() { for (let i=0; i<30; i++) await Promise.resolve(); }
async function main() {
  // The Buddy website is not loaded; the floating buddy preference is hidden.
  const inputEvents = {}, inputMessages = [], pendingInput = [];
  let focused = true;
  const doc = {title:"Test",visibilityState:"visible",hasFocus:()=>focused,
    documentElement:{scrollHeight:1000,clientHeight:1000,scrollTop:0},
    addEventListener:(type,fn)=>(inputEvents[type]??=[]).push(fn)};
  const content = vm.createContext({document:doc,window:{addEventListener(){}},HTMLIFrameElement:class {},
    location:{href:"https://example.com",hostname:"example.com"},performance:{now:()=>clock},Date:FakeDate,
    setInterval(){},setTimeout(){},chrome:{runtime:{sendMessage:message=>{
      inputMessages.push(message);
      const job=api.runtime.sendMessage(message);pendingInput.push(job);return job;
    }}}});
  load(content,"content.js");
  const fire=(type,event)=>{for(const fn of inputEvents[type]??[])fn(event);};
  for (const [key, shortcut] of [["c","copy"],["v","paste"],["z","undo"]]) {
    fire("keydown", {key,ctrlKey:true,isTrusted:true});
    if(shortcut!=="undo")fire(shortcut,{isTrusted:true,clipboardData:{getData:()=>"PRIVATE CLIPBOARD"}});
    await Promise.all(pendingInput.splice(0));
    clock += 100;
  }
  assert.equal(inputMessages.length,3,"keydown and its clipboard event are one immediate shortcut");
  assert.ok(inputMessages.every(message=>Object.keys(message).sort().join() === "shortcut,type"));
  fire("keydown",{key:"z",ctrlKey:true,isTrusted:true,repeat:true});
  fire("keydown",{key:"z",ctrlKey:true,isTrusted:false});
  focused=false;fire("keydown",{key:"z",ctrlKey:true,isTrusted:true});
  assert.equal(inputMessages.length,3,"repeat, synthetic and unfocused input are ignored");
  assert.equal(plays.length, 3, "different shortcuts must not share a long cooldown");
  assert.ok(plays[2].endsWith("CMDZF1.mp3"));
  assert.equal(stored.voicePlayback.text, "Exact CMDZ caption");
  clock += 1200;
  await Promise.all([api.runtime.sendMessage({type:"appState"}), api.runtime.sendMessage({type:"appState"})]);
  await settle();
  assert.equal(plays.length, 3, "multiple tabs must not replay one brain event");
  if (browser === "chromium") assert.equal(creations, 1, "reuse one offscreen player");
  await api.storage.local.set({voiceOn:false});
  await settle();
  await api.runtime.sendMessage({type:"shortcut", shortcut:"copy"});
  assert.equal(plays.length, 3, "mute applies without the website being open");
  assert.equal(stored.voicePlayback, null);
  await api.storage.local.set({voiceOn:true});
  failures = 1;
  const failed = event("CMDC");
  await api.runtime.sendMessage({type:"voice", trigger:"CMDC", event:failed, interrupt:true});
  assert.ok(!claims.has(failed.key), "failed playback must release its server claim");
  await api.runtime.sendMessage({type:"voice", trigger:"CMDC", event:failed, interrupt:true});
  assert.equal(plays.length, 4);
  clock += 1200;
  const elsewhere = event("CMDV");
  claims.set(elsewhere.key, "desktop-window");
  await api.runtime.sendMessage({type:"voice", trigger:"CMDV", event:elsewhere, interrupt:true});
  assert.equal(plays.length, 4, "a website/native window claim prevents duplicate audio");
  if (browser === "chromium") {
    // Chrome can close the document after a period without audio. Recreate it.
    open = false;
    listeners.splice(1);
    await api.runtime.sendMessage({type:"shortcut", shortcut:"undo"});
    assert.equal(creations, 2);
    assert.equal(plays.length, 5);
  }
  console.log(JSON.stringify({singlePlayer:true, immediateShortcuts:true, mute:true, claimRecovery:true, creations}));
}
main().catch(error => {console.error(error); process.exitCode=1;});
