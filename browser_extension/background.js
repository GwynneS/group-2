// Receives session records from content.js and headpats from buddy.js and
// saves them to extension storage. Writes are queued so records from several
// tabs closing at once don't overwrite each other. Also keeps the toolbar
// icon in sync with the chosen buddy.
//
// Storage layout (browser.storage.local):
//   sessions: [record, ...]          newest last, capped at MAX_SESSIONS
//   totals:   { [host]: { activeMs, visits, clicks, keys, copies, pastes, lastVisit } }
//   pets:     number of times the buddy has been petted
//   buddy:    { character: "girl" | "boy" | null, visible: boolean }  (written by popup/buddy)
//   buddyPos: { fx, fy }  last position as a fraction of the viewport

// Chrome runs this as a service worker (needs importScripts); Firefox loads
// sprites.js first via the manifest's background.scripts.
if (typeof importScripts === "function" && !globalThis.BuddySprites) {
  importScripts("sprites.js");
}

const api = globalThis.browser ?? globalThis.chrome;
const MAX_SESSIONS = 1000;

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

api.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.type === "session" && msg.record) {
    saveRecord({ ...msg.record, tabId: sender.tab?.id });
  } else if (msg?.type === "pet") {
    countPet();
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
