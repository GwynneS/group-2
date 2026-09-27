// Runs only on the local Buddy app (http://127.0.0.1:8765, see manifest.json).
// Lets the app page read and change the buddy settings, send headpats and
// chat through the extension, so the app and the buddy on other websites
// share one state.
//
// Protocol (window.postMessage, same origin only):
//   app -> extension  { source: "buddy-app", type, id?, ... }
//     hello                    ask the extension to announce itself
//     get          (id)        -> response { buddy, pets, chat, lastFed }
//     setBuddy     (id, buddy) -> response {}
//     pet                      count a headpat
//     feed                     feed the buddy (resets hunger)
//     chat         (id, text)  -> response { reply }
//   extension -> app { source: "buddy-extension", type, ... }
//     hello    { version }
//     response { id, data }
//     changed  { data: { buddy?, pets?, chat?, lastFed? } }
//
// Browsing sessions recorded by content.js are deliberately not exposed here.

(() => {
  // The manifest matches every localhost port; only talk to the Buddy app's.
  if (location.port !== "8765") return;

  const api = globalThis.browser ?? globalThis.chrome;
  const SHARED_KEYS = ["buddy", "pets", "chat", "lastFed"];

  function post(msg) {
    window.postMessage({ source: "buddy-extension", ...msg }, location.origin);
  }

  function hello() {
    post({ type: "hello", version: api.runtime.getManifest().version });
  }

  function cleanBuddy(buddy) {
    return {
      character: ["girl", "boy"].includes(buddy?.character) ? buddy.character : null,
      visible: buddy?.visible !== false,
    };
  }

  async function handle(msg) {
    switch (msg.type) {
      case "hello":
        return hello();
      case "get":
        return post({ type: "response", id: msg.id, data: await api.storage.local.get(SHARED_KEYS) });
      case "setBuddy":
        await api.storage.local.set({ buddy: cleanBuddy(msg.buddy) });
        return post({ type: "response", id: msg.id, data: {} });
      case "pet":
        return api.runtime.sendMessage({ type: "pet" });
      case "feed":
        return api.storage.local.set({ lastFed: Date.now() });
      case "chat": {
        const text = String(msg.text ?? "").slice(0, 2000);
        const data = await api.runtime.sendMessage({ type: "chat", text });
        return post({ type: "response", id: msg.id, data });
      }
    }
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin) return;
    if (e.data?.source !== "buddy-app") return;
    handle(e.data).catch((err) => console.warn("Buddy bridge:", err));
  });

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    const data = {};
    for (const key of SHARED_KEYS) if (key in changes) data[key] = changes[key].newValue;
    if (Object.keys(data).length) post({ type: "changed", data });
  });

  // At document_start the page's own script hasn't run yet; it also sends
  // "hello" when it loads, which gets answered above.
  hello();
})();
