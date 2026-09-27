// Execute the real website (and optional real extension bridge) with a small
// DOM/Audio mock. This verifies control wiring, not visual layout or hardware.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict");
const root = process.argv[2];
async function settle() { for (let i=0;i<60;i++) await Promise.resolve(); }
function page(withExtension = false, initial = {}, backgroundVoice = true) {
  let clock = 100000, voiceId = 0, speech = null;
  const requests = [], audio = [], messages = [], events = {}, docEvents = {}, elements = new Map();
  const storage = {"buddy-app":JSON.stringify({prefs:{character:"girl",visible:true}}), ...initial};
  const on = (map, type, fn) => (map[type] ??= []).push(fn);
  class Element {
    constructor() { this.attributes = {}; this.listeners = {}; this.style = {}; this.dataset = {}; this.hidden = false; this.checked = true; this.textContent=""; this.children=new Map(); this.classList={add(){},remove(){},toggle(){}}; }
    get parentElement() { return this.parent ??= new Element(); }
    get src() { return this.attributes.src ?? ""; }
    set src(v) { this.attributes.src=v; }
    getAttribute(key) { return this.attributes[key] ?? null; }
    setAttribute(key,value) { this.attributes[key]=value; }
    removeAttribute(key) { delete this.attributes[key]; }
    addEventListener(type, fn) { on(this.listeners,type,fn); }
    querySelector(key) { if (!this.children.has(key)) this.children.set(key,new Element()); return this.children.get(key); }
    querySelectorAll() { return []; }
    append() {} replaceChildren() {} showModal() {} focus() {}
  }
  const el = id => { if (!elements.has(id)) elements.set(id,new Element()); return elements.get(id); };
  let onState;
  const stage = {onState(fn){onState=fn;},setSpeech(text){speech=text;},setCharacter(){},react(){},isReacting:()=>true,setResting(){},setDefaultCaption(){}};
  const state = () => ({animation:"encouragement",message:"Copied!",pet:{mood:"happy",hunger:25,energy:90,attention:80,affection:75,boredom:10},
    activity:{type:"coding"},feeding:{food:"fish"},camera:{status:"on",error:""},body:{state:"at_desk",present:true},voice:null});
  const clips = Object.fromEntries(["CMDC","CMDV","CMDZ"].map(trigger=>[trigger,{girl:[{url:`/voice/${trigger}F1.mp3`,text:`Exact ${trigger}`}]}]));
  const document = {visibilityState:"visible",hasFocus:()=>true,getElementById:el,querySelectorAll:()=>[],
    createElement:()=>new Element(),addEventListener:(type,fn)=>on(docEvents,type,fn)};
  class FakeDate extends Date {static now(){return clock;}}
  const sandbox = {console, document, Date:FakeDate, performance:{now:()=>clock},
    location:{origin:"http://127.0.0.1:8765",port:"8765"}, BuddyStage:stage,
    localStorage:{getItem:key=>storage[key]??null,setItem:(key,value)=>storage[key]=value},
    addEventListener:(type,fn)=>on(events,type,fn),setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,
    Audio:class {constructor(){this.paused=true;this.ended=false;} addEventListener(){} pause(){this.paused=true;} async play(){this.paused=false;audio.push(this.src);}},
    fetch:async (url,options={})=>{
      const body=JSON.parse(options.body??"{}"); requests.push({url,body});
      let data;
      if(url==="/api/status") data={ai:"offline",extension_seen:withExtension};
      else if(url==="/api/voices") data=clips;
      else if(url==="/api/shortcut") data={accepted:true,state:{...state(),voice:{id:++voiceId,key:"test:"+voiceId,trigger:{copy:"CMDC",paste:"CMDV",undo:"CMDZ"}[body.shortcut],seconds:2.5}}};
      else if(url==="/api/voice/claim") data={claimed:true};
      else if(url==="/api/interact") data={accepted:true};
      else if(url==="/api/presence") data=state();
      else throw new Error("Unexpected request "+url);
      return {ok:true,json:async()=>data};
    },
  };
  sandbox.window=sandbox;
  let pageWindow;
  sandbox.postMessage=(data,origin)=>Promise.resolve().then(()=>{
    for(const fn of events.message??[]) fn({data,origin,source:pageWindow});
  });
  const context=vm.createContext(sandbox);
  pageWindow=vm.runInContext("window",context);
  const load=(file)=>vm.runInContext(fs.readFileSync(path.join(root,file),"utf8"),context,{filename:file});
  load("browser_extension/characters.js");
  if(withExtension){
    const shared={buddy:{character:"girl",visible:true},voiceOn:true};
    const changed=[];
    sandbox.chrome={runtime:{getManifest:()=>({version:"0.5.3"}),sendMessage:async m=>{messages.push(m);return m.type === "voiceSupport" ? {supported:backgroundVoice} : {played:true};}},
      storage:{local:{get:async()=>({...shared}),set:async data=>{
        Object.assign(shared,data);const diff=Object.fromEntries(Object.entries(data).map(([k,v])=>[k,{newValue:v}]));
        for(const fn of changed)fn(diff,"local");
      }},onChanged:{addListener:fn=>changed.push(fn)}}};
    load("browser_extension/bridge.js");
  }
  load("UI/app.js");
  return {el,storage,requests,audio,messages,state,document,onState:s=>onState(s),
    advance:ms=>clock+=ms, click:async id=>{for(const fn of el(id).listeners.click??[])await fn({isTrusted:true});await settle();},
    change:async id=>{for(const fn of el(id).listeners.change??[])await fn({isTrusted:true});await settle();},
    fire:async (type,e={})=>{for(const fn of docEvents[type]??[])await fn(e);await settle();},
    speech:()=>speech};
}
async function main(){
  const p=page();await settle();p.onState(p.state());
  assert.ok(p.el("camera-feed").src.startsWith("/api/camera.mjpg"));
  await p.click("camera-preview-toggle");
  assert.equal(p.el("camera-feed").hidden,true);
  assert.equal(p.el("camera-feed").getAttribute("src"),null);
  assert.equal(p.storage["buddy-camera-preview"],"hidden");
  assert.ok(p.el("camera-tracking-status").textContent.includes("tracking on"));
  assert.ok(!p.requests.some(r=>r.url==="/api/camera"),"hiding preview must not stop tracking");
  await p.click("camera-preview-toggle");
  assert.equal(p.el("camera-feed").hidden,false);
  p.document.visibilityState="hidden";await p.fire("visibilitychange");
  assert.equal(p.el("camera-feed").getAttribute("src"),null);
  p.document.visibilityState="visible";await p.fire("visibilitychange");
  assert.equal(p.el("camera-feed").hidden,false);
  const remembered=page(false,{"buddy-camera-preview":"hidden"});await settle();remembered.onState(remembered.state());
  assert.equal(remembered.el("camera-feed").hidden,true);
  for(const key of ["c","v","z"]){
    await p.fire("keydown",{key,ctrlKey:true,isTrusted:true});p.advance(150);
  }
  assert.equal(p.audio.length,3,"website shortcut voices must not share a 15-second gap");
  const sent=p.requests.filter(r=>r.url==="/api/shortcut");
  assert.deepEqual(sent.map(r=>r.body.shortcut),["copy","paste","undo"]);
  await p.fire("keydown",{key:"z",ctrlKey:true,repeat:true,isTrusted:true});
  await p.fire("keydown",{key:"z",ctrlKey:true,isTrusted:false});
  assert.equal(p.requests.filter(r=>r.url==="/api/shortcut").length,3);
  const ext=page(true);await settle();ext.onState(ext.state());
  ext.onState({...ext.state(),voice:{id:1,key:"native:1",trigger:"CMDZ",seconds:2.5}});await settle();
  assert.equal(ext.audio.length,0,"connected website delegates audio to the extension");
  assert.equal(ext.messages.filter(m=>m.type==="voice").length,1);
  ext.el("voice-on").checked=false;await ext.change("voice-on");
  assert.equal(ext.el("voice-on").checked,false);
  const fallback=page(true,{},false);await settle();fallback.onState(fallback.state());
  fallback.onState({...fallback.state(),voice:{id:1,key:"fallback:1",trigger:"CMDZ",seconds:2.5}});await settle();
  assert.equal(fallback.audio.length,1,"unsupported background audio keeps website playback available");
  console.log(JSON.stringify({previewIndependent:true,remembered:true,immediateShortcuts:true,bridgeDelegation:true}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
