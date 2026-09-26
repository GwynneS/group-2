// Buddy UI: animated buddy, buddy settings, chat, and extension download.
//
// When the browser extension is installed, its bridge script (bridge.js)
// answers on this page through window.postMessage, and the extension's
// storage becomes the source of truth for settings, headpats and chat, so
// everything stays in sync with the buddy on other websites. Without the
// extension, the page talks to the app server directly and remembers state
// in localStorage.

(() => {
  const S = globalThis.BuddySprites;
  const $ = (id) => document.getElementById(id);

  const aiStatus = $("ai-status");
  const extStatus = $("ext-status");
  const downloadLink = $("download-extension");
  const installDialog = $("install-dialog");
  const stage = $("buddy-canvas");
  const caption = $("buddy-caption");
  const choices = [...document.querySelectorAll(".buddy-choice")];
  const showOnSites = $("show-on-sites");
  const petCount = $("pet-count");
  const chatLog = $("chat-history");
  const chatForm = $("chat-form");
  const chatInput = $("user-input");

  const STAGE_SCALE = 3;
  const LOCAL_KEY = "buddy-app";
  const OFFLINE_TEXT = "I can't reach the Buddy app. Make sure python3 UI/server.py is running.";

  if (!S) {
    aiStatus.textContent = "App server offline";
    aiStatus.dataset.state = "warn";
    caption.textContent = "Start the app with python3 UI/server.py, then open http://127.0.0.1:8765";
    return;
  }

  // --- State ---------------------------------------------------------------

  let prefs = { character: null, visible: true };
  let chat = []; // [{ role: "user" | "buddy", text, at, error? }]
  let pets = 0;
  let ext = null; // { version } once the extension answers
  let typing = false;
  let happyUntil = 0;

  const charKey = () => prefs.character ?? "girl";
  const buddyName = () => S.CHARACTERS[charKey()].name;

  function loadLocal() {
    try {
      const saved = JSON.parse(localStorage.getItem(LOCAL_KEY));
      if (saved) {
        prefs = { ...prefs, ...saved.prefs };
        chat = Array.isArray(saved.chat) ? saved.chat : [];
        pets = saved.pets ?? 0;
      }
    } catch {}
  }

  function saveLocal() {
    if (ext) return; // the extension stores everything once connected
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify({ prefs, chat: chat.slice(-50), pets }));
    } catch {}
  }

  // --- Extension bridge ----------------------------------------------------

  const pending = new Map();
  let nextId = 1;

  function send(type, payload = {}) {
    window.postMessage({ source: "buddy-app", type, ...payload }, location.origin);
  }

  function request(type, payload = {}) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, resolve);
      send(type, { ...payload, id });
      setTimeout(() => pending.delete(id) && reject(new Error("The extension didn't answer.")), 60_000);
    });
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin) return;
    const msg = e.data;
    if (msg?.source !== "buddy-extension") return;
    if (msg.type === "hello" && !ext) connect(msg.version);
    else if (msg.type === "response" && pending.has(msg.id)) {
      pending.get(msg.id)(msg.data);
      pending.delete(msg.id);
    } else if (msg.type === "changed") applyState(msg.data);
  });

  async function connect(version) {
    ext = { version };
    renderExtStatus();
    applyState(await request("get"));
  }

  function applyState(data = {}) {
    if ("buddy" in data) prefs = { character: null, visible: true, ...data.buddy };
    if ("pets" in data) pets = data.pets ?? 0;
    if ("chat" in data) chat = data.chat ?? [];
    renderSettings();
    renderChat();
  }

  function setPrefs(next) {
    prefs = next;
    renderSettings();
    renderChat();
    if (ext) request("setBuddy", { buddy: next });
    else saveLocal();
  }

  // --- Status chips --------------------------------------------------------

  function renderExtStatus() {
    if (ext) {
      extStatus.textContent = `Extension: connected v${ext.version}`;
      extStatus.dataset.state = "good";
    } else {
      extStatus.textContent = "Extension: not installed";
      extStatus.dataset.state = "warn";
    }
    showOnSites.disabled = !ext;
    showOnSites.parentElement.title = ext ? "" : "Install the extension to see your buddy on other websites.";
  }

  async function checkServer() {
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      const status = await res.json();
      aiStatus.textContent = status.ai === "claude" ? "AI: Claude" : "AI: built-in replies";
      aiStatus.dataset.state = status.ai === "claude" ? "good" : "warn";
    } catch {
      aiStatus.textContent = "AI: app server offline";
      aiStatus.dataset.state = "warn";
    }
  }

  downloadLink.addEventListener("click", () => installDialog.showModal());

  // --- Buddy stage and settings -------------------------------------------

  const centerShift = (scale) => `translateX(${((S.W - S.BODY_W) / 2) * scale}px)`;

  stage.width = S.W * STAGE_SCALE;
  stage.height = S.H * STAGE_SCALE;
  const stageCtx = stage.getContext("2d");
  stage.tabIndex = 0;

  for (const btn of choices) {
    const canvas = btn.querySelector("canvas");
    canvas.width = S.W;
    canvas.height = S.H;
    canvas.style.transform = centerShift(2);
    S.draw(canvas.getContext("2d"), btn.dataset.char, {}, 1);
    btn.querySelector(".name").textContent = S.CHARACTERS[btn.dataset.char].name;
    btn.addEventListener("click", () => setPrefs({ ...prefs, character: btn.dataset.char, visible: true }));
  }

  showOnSites.addEventListener("change", () => setPrefs({ ...prefs, visible: showOnSites.checked }));

  function pet() {
    happyUntil = performance.now() + 1500;
    if (ext) {
      send("pet");
    } else {
      pets++;
      saveLocal();
      renderSettings();
    }
  }
  stage.addEventListener("click", pet);
  stage.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pet();
    }
  });

  function renderSettings() {
    for (const btn of choices) {
      btn.setAttribute("aria-pressed", String(btn.dataset.char === prefs.character));
    }
    showOnSites.checked = !!prefs.visible;
    petCount.textContent = pets ? `Headpats given: ${pets}` : "";
    caption.textContent = prefs.character
      ? `${buddyName()} · click for a headpat`
      : "Pick a buddy to get started";
  }

  let nextBlink = 0;
  let blinkUntil = 0;
  function animate(now) {
    if (now > nextBlink) {
      blinkUntil = now + 150;
      nextBlink = now + 2500 + Math.random() * 3500;
    }
    const happy = now < happyUntil;
    S.draw(
      stageCtx,
      charKey(),
      {
        eyes: now < blinkUntil ? "closed" : happy ? "happy" : "open",
        tail: Math.floor(now / (happy ? 150 : 450)) % 2,
      },
      STAGE_SCALE
    );
    const bob = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : Math.round(Math.sin(now / 380) * 3);
    stage.style.transform = `${centerShift(STAGE_SCALE)} translateY(${bob}px)`;
    requestAnimationFrame(animate);
  }

  // --- Chat ----------------------------------------------------------------

  function messageEl(role, text, extraClass = "") {
    const article = document.createElement("article");
    article.className = `message ${role === "user" ? "user-message" : "ai-message"} ${extraClass}`.trim();
    const p = document.createElement("p");
    const who = document.createElement("strong");
    who.textContent = role === "user" ? "You" : buddyName();
    p.append(who, document.createElement("br"), text);
    article.append(p);
    return article;
  }

  function renderChat() {
    chatLog.replaceChildren();
    if (!chat.length) {
      chatLog.append(messageEl("buddy", `Hi! I'm ${buddyName()}. What are we working on today?`));
    }
    for (const m of chat) {
      chatLog.append(messageEl(m.role, m.text, m.error ? "error-message" : ""));
    }
    if (typing) chatLog.append(messageEl("buddy", "…", "typing"));
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  async function sendChat(text) {
    typing = true;
    if (ext) {
      // The extension records both sides of the conversation; its storage
      // change events re-render the log here and on every other tab.
      renderChat();
      try {
        await request("chat", { text });
      } catch {
        chat.push({ role: "buddy", text: OFFLINE_TEXT, error: true, at: Date.now() });
      }
      typing = false;
      renderChat();
      return;
    }

    const history = chat.slice();
    chat.push({ role: "user", text, at: Date.now() });
    renderChat();
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, character: charKey(), history }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      chat.push({ role: "buddy", text: data.reply, at: Date.now() });
    } catch {
      chat.push({ role: "buddy", text: OFFLINE_TEXT, error: true, at: Date.now() });
    }
    typing = false;
    saveLocal();
    renderChat();
  }

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text || typing) return;
    chatInput.value = "";
    sendChat(text);
  });

  // --- Start ---------------------------------------------------------------

  loadLocal();
  renderSettings();
  renderChat();
  renderExtStatus();
  extStatus.textContent = "Extension: checking…";
  extStatus.dataset.state = "unknown";
  checkServer();
  requestAnimationFrame(animate);

  // The bridge announces itself when it loads; ask too, in case it loaded first.
  send("hello");
  setTimeout(() => ext || renderExtStatus(), 1500);
})();
