// Receives session records from content.js, and headpats and chat messages
// from buddy.js / bridge.js, and saves them to extension storage. Writes are
// queued so records from several tabs closing at once don't overwrite each
// other. Chat replies come from the local Buddy app (UI/server.py). Also keeps
// the toolbar icon in sync with the chosen buddy.
//
// Storage layout (browser.storage.local):
//   sessions: [record, ...]          newest last, capped at MAX_SESSIONS
//   totals:   { [host]: { activeMs, visits, clicks, keys, copies, pastes, lastVisit } }
//   pets:     number of times the buddy has been petted
//   buddy:    { character: "girl" | "boy" | null, visible: boolean }  (written by popup/buddy)
//   buddyPos: { fx, fy }  last position as a fraction of the viewport
//   chat:     [{ role: "user" | "buddy", text, at, error? }]  newest last, capped at MAX_CHAT

// Chrome runs this as a service worker (needs importScripts); Firefox loads
// sprites.js first via the manifest's background.scripts.
if (typeof importScripts === "function" && !globalThis.BuddySprites) {
  importScripts("sprites.js");
}

const api = globalThis.browser ?? globalThis.chrome;
const MAX_SESSIONS = 1000;
const MAX_CHAT = 50;
// The local Buddy app; keep in sync with PORT in UI/server.py and manifest.json.
const APP_URL = "http://127.0.0.1:8765";

let writeQueue = Promise.resolve();

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

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "session" && msg.record) {
    saveRecord({ ...msg.record, tabId: sender.tab?.id });
  } else if (msg?.type === "pet") {
    countPet();
  } else if (msg?.type === "chat") {
    chat(msg.text).then(sendResponse);
    return true; // keep the channel open for the async reply
  }
});

// --- Toolbar icon ----------------------------------------------------------

function updateIcon(character) {
  if (typeof OffscreenCanvas !== "function" || !globalThis.BuddySprites) return;
  const S = globalThis.BuddySprites;
  const imageData = {};
  for (const size of [16, 32]) {
    const canvas = new OffscreenCanvas(size, size);
    const ctx = canvas.getContext("2d");
    // Crop to the head so it stays readable at 16px.
    const full = new OffscreenCanvas(S.W, S.H);
    S.draw(full.getContext("2d"), character ?? "girl", { eyes: "happy" }, 1);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(full, 0, 0, 26, 26, 0, 0, size, size);
    imageData[size] = ctx.getImageData(0, 0, size, size);
  }
  (api.action ?? api.browserAction).setIcon({ imageData });
}

api.storage.local.get("buddy").then(({ buddy }) => updateIcon(buddy?.character));
api.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.buddy) updateIcon(changes.buddy.newValue?.character);
});
