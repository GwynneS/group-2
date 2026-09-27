// Receives session records from content.js, and headpats and chat messages
// from buddy.js / bridge.js, and saves them to extension storage. Writes are
// queued so records from several tabs closing at once don't overwrite each
// other. Also keeps the toolbar icon in sync with the chosen buddy.
//
// Talks to the local Buddy app (UI/server.py) when it's running:
//   heartbeat  -> /api/browser-activity  counts only (clicks, keys, copies,
//                                 pastes, scroll, active time) every 5s
//   chat       -> /api/chat       replies in character
//   appState   -> /api/presence   reports the focused tab's title and host so
//                                 the companion brain knows what you're doing,
//                                 and returns its state (emotion, needs, mood)
//   interact   -> /api/interact   headpats, pokes, feeding, copy/paste
//   shortcut   -> /api/shortcut   immediate copy/paste/undo, without typed text
//   voice / voiceSupport         shared audio player and its capability check
//
// Storage layout (browser.storage.local):
//   sessions: [record, ...]          newest last, capped at MAX_SESSIONS
//   totals:   { [host]: { activeMs, visits, clicks, keys, copies, pastes, lastVisit } }
//   pets:     number of times the buddy has been petted
//   buddy:    { character: "girl" | "boy" | null, visible: boolean }  (written by popup/buddy)
//   buddyPos: { fx, fy }  last position as a fraction of the viewport
//   lastFed:  timestamp of the last feeding; the buddy gets hungry 45 min later
//   chat:     [{ role: "user" | "buddy", text, at, error? }]  newest last, capped at MAX_CHAT

// Chrome runs this as a service worker (needs importScripts); Firefox loads
// characters.js first via the manifest's background.scripts.
if (typeof importScripts === "function" && !globalThis.BuddyCharacters) {
  importScripts("characters.js");
}
if (typeof importScripts === "function" && !globalThis.BuddyAudio) {
  importScripts("voice-player.js");
}

const api = globalThis.browser ?? globalThis.chrome;
const MAX_SESSIONS = 1000;
const MAX_CHAT = 50;
// The local Buddy app; keep in sync with PORT in UI/server.py and manifest.json.
const APP_URL = "http://127.0.0.1:8765";

let writeQueue = Promise.resolve();

// --- Activity heartbeats -----------------------------------------------------

// content.js sends a count-only heartbeat every 5s while a page is in view;
// forward it to the companion brain. Fire-and-forget: the app may be off.
function toBrain(path, body) {
  return fetch(`${APP_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => {});
}

function enqueue(fn) {
  writeQueue = writeQueue.then(fn).catch((err) => console.error("Storage write failed", err));
  return writeQueue;
}

function saveRecord(record) {
  return enqueue(async () => {
    const { sessions = [], totals = {} } = await api.storage.local.get(["sessions", "totals"]);

    sessions.push(record);
    if (sessions.length > MAX_SESSIONS) sessions.splice(0, sessions.length - MAX_SESSIONS);

    const t = (totals[record.host] ??= {
      activeMs: 0, visits: 0, clicks: 0, keys: 0, copies: 0, pastes: 0, lastVisit: 0,
    });
    t.activeMs += record.activeMs;
    t.visits += 1;
    t.clicks += record.clicks;
    t.keys += record.keys;
    t.copies += record.copies;
    t.pastes += record.pastes;
    t.lastVisit = record.endedAt;

    await api.storage.local.set({ sessions, totals });
  });
}

function countPet() {
  return enqueue(async () => {
    const { pets = 0 } = await api.storage.local.get("pets");
    await api.storage.local.set({ pets: pets + 1 });
  });
}

function appendChat(entry) {
  return enqueue(async () => {
    const { chat = [] } = await api.storage.local.get("chat");
    chat.push({ ...entry, at: Date.now() });
    if (chat.length > MAX_CHAT) chat.splice(0, chat.length - MAX_CHAT);
    await api.storage.local.set({ chat });
  });
}

// Send a chat message to the Buddy app and record both sides of it.
async function chat(text) {
  text = String(text ?? "").trim().slice(0, 2000);
  if (!text) return { error: "Message is empty." };

  const { chat: history = [], buddy } = await api.storage.local.get(["chat", "buddy"]);
  await appendChat({ role: "user", text });

  try {
    const res = await fetch(`${APP_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, character: buddy?.character ?? "girl", history }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
    await appendChat({ role: "buddy", text: data.reply });
    return { reply: data.reply, source: data.source };
  } catch (err) {
    const reply = "I can't reach the Buddy app. Start it with python3 UI/server.py and try again.";
    await appendChat({ role: "buddy", text: reply, error: true });
    return { reply, error: String(err) };
  }
}

async function appRequest(path, body) {
  try {
    const res = await fetch(`${APP_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
      signal: AbortSignal.timeout(3000),
    });
    return res.ok || res.status === 400 ? await res.json() : null;
  } catch {
    return null; // app isn't running
  }
}

// One playback owner for every tab. The server claim also prevents a second
// website/desktop window from speaking the same brain event.
let creatingAudio = null;
let voiceQueue = Promise.resolve();
let clipIndex = null;
const lastClip = {};
const lastVoice = {};
const voiceOwner = "extension-" + Math.random().toString(36).slice(2);

async function audioMessage(message, create = true) {
  if (!api.offscreen?.createDocument) {
    if (typeof Audio !== "function") throw new Error("Background voice is unavailable in this browser");
    return message.type === "stop" ? BuddyAudio.stop() : BuddyAudio.play(message);
  }
  const contexts = await api.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"], documentUrls: [api.runtime.getURL("voice-offscreen.html")],
  });
  if (!contexts.length) {
    if (!create) return { stopped: true };
    if (!creatingAudio) {
      creatingAudio = api.offscreen.createDocument({
        url: "voice-offscreen.html", reasons: ["AUDIO_PLAYBACK"],
        justification: "Play the user's enabled Buddy voice clips without opening a video window.",
      }).finally(() => { creatingAudio = null; });
    }
    await creatingAudio;
  }
  if (message.type === "play" && (await api.storage.local.get("voiceOn")).voiceOn === false) {
    return { played: false, reason: "muted" };
  }
  return api.runtime.sendMessage({ target: "buddy-audio", ...message });
}

async function playVoice({ trigger, interrupt = false, event = null }) {
  const { voiceOn = true, buddy } = await api.storage.local.get(["voiceOn", "buddy"]);
  if (!voiceOn || !buddy?.character) return { played: false, reason: "muted" };
  const at = Date.now();
  const gap = String(trigger).startsWith("CMD") ? 1000 : 4000;
  if (at - (lastVoice[trigger] ?? -Infinity) < gap) return { played: false, reason: "repeat" };
  if (!clipIndex) {
    const response = await fetch(`${APP_URL}/api/voices`, { signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("Voice clips unavailable");
    clipIndex = await response.json();
  }
  const options = clipIndex[trigger]?.[buddy.character] ?? [];
  const fresh = options.length > 1 ? options.filter(clip => clip.url !== lastClip[trigger]) : options;
  if (!fresh.length) return { played: false, reason: "no_clip" };
  const clip = fresh[Math.floor(Math.random() * fresh.length)];
  let claimed = false;
  if (event?.key) {
    claimed = (await appRequest("/api/voice/claim", { key: event.key, owner: voiceOwner }))?.claimed === true;
    if (!claimed) return { played: false, reason: "already_claimed" };
  }
  try {
    // Mute may have changed while the clip index/document was loading.
    if ((await api.storage.local.get("voiceOn")).voiceOn === false) return { played: false, reason: "muted" };
    const result = await audioMessage({ type: "play", url: APP_URL + clip.url, interrupt });
    if (!result?.played) throw new Error(result?.error ?? result?.reason ?? "Voice did not start");
    lastVoice[trigger] = Date.now();
    lastClip[trigger] = clip.url;
    claimed = false; // keep the successful server claim
    await api.storage.local.set({ voicePlayback: {
      text: clip.text, trigger, character: buddy.character, startedAt: Date.now(),
      seconds: result.duration ?? event?.seconds ?? 4,
    } });
    return { ...result, text: clip.text, trigger };
  } finally {
    if (claimed) await appRequest("/api/voice/claim", { key: event.key, owner: voiceOwner, release: true });
  }
}

function queueVoice(message) {
  const job = voiceQueue.then(() => playVoice(message));
  voiceQueue = job.catch(() => {});
  return job.catch(error => ({ played: false, error: String(error) }));
}

async function withBrainVoice(state) {
  if (state?.voice?.seconds > 0) {
    await queueVoice({ trigger: state.voice.trigger, event: state.voice,
                       interrupt: state.voice.trigger.startsWith("CMD") });
  }
  return state;
}

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.target === "buddy-audio") return; // handled only by the offscreen page
  if (msg?.type === "voiceSupport") {
    sendResponse({ supported: !!api.offscreen?.createDocument || typeof Audio === "function" });
  } else if (msg?.type === "session" && msg.record) {
    saveRecord({ ...msg.record, tabId: sender.tab?.id });
  } else if (msg?.type === "heartbeat" && msg.data) {
    toBrain("/api/browser-activity", msg.data);
  } else if (msg?.type === "pet") {
    // Only counts the headpat; buddy.js / app.js tell the brain via "interact".
    countPet();
  } else if (msg?.type === "chat") {
    chat(msg.text).then(sendResponse);
    return true; // keep the channel open for the async reply
  } else if (msg?.type === "appState") {
    const page = msg.page ? { title: String(msg.page.title ?? ""), host: String(msg.page.host ?? "") } : {};
    appRequest("/api/presence", page).then(state => {
      sendResponse(state); // movement/state delivery never waits for audio loading
      withBrainVoice(state).catch(() => {});
    });
    return true;
  } else if (msg?.type === "shortcut") {
    appRequest("/api/shortcut", { shortcut: msg.shortcut }).then(async result => {
      if (result?.accepted) await withBrainVoice(result.state);
      sendResponse(result);
    });
    return true;
  } else if (msg?.type === "voice") {
    queueVoice({ trigger: String(msg.trigger ?? ""), interrupt: msg.interrupt === true,
                 event: msg.event }).then(sendResponse);
    return true;
  } else if (msg?.type === "interact") {
    appRequest("/api/interact", { action: msg.action, food: msg.food }).then(sendResponse);
    return true;
  }
});

// --- Toolbar icon ----------------------------------------------------------

// The toolbar icon shows the chosen buddy's happy pose, cropped to the head
// so it stays readable at 16px.
async function updateIcon(character) {
  if (typeof OffscreenCanvas !== "function" || typeof createImageBitmap !== "function") return;
  try {
    const url = api.runtime.getURL(BuddyCharacters.artPath(character ?? "girl", "happy"));
    const art = await createImageBitmap(await (await fetch(url)).blob());
    const side = Math.min(art.width, art.height * 0.62);
    const sx = (art.width - side) / 2;
    const imageData = {};
    for (const size of [16, 32]) {
      const ctx = new OffscreenCanvas(size, size).getContext("2d");
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(art, sx, 0, side, side, 0, 0, size, size);
      imageData[size] = ctx.getImageData(0, 0, size, size);
    }
    await (api.action ?? api.browserAction).setIcon({ imageData });
  } catch (err) {
    console.warn("Couldn't update the toolbar icon", err);
  }
}

api.storage.local.get("buddy").then(({ buddy }) => updateIcon(buddy?.character));
api.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.buddy) updateIcon(changes.buddy.newValue?.character);
  if (area === "local" && changes.voiceOn?.newValue === false) {
    audioMessage({ type: "stop" }, false).catch(() => {});
    api.storage.local.set({ voicePlayback: null });
  }
});
