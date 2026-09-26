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

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "session" && msg.record) {
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
    appRequest("/api/presence", page).then(sendResponse);
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
});
