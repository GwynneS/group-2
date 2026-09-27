// Buddy UI: buddy settings, reactions to the user, chat, live camera, the
// companion's needs, and extension download. The buddy itself is drawn by
// animation.js (BuddyStage); this file decides how it reacts:
//
//   click (headpat)             happy          + headpat counted   voice: happy
//   5+ clicks in 2s             angry                              voice: unhappy
//   Feed                        happy          resets hunger       voice: fed
//   chat message                by its words (see characters.js)
//   copy / paste / undo here    encouragement                      voice: CMDC / CMDV / CMDZ
//   idle 90s                    tired          (resting pose, until you're back)
//   back after 60s away         sad, then happy                    voice: onReturn
//
// Headpats, pokes, feeding and copy/paste are also sent to the companion
// brain (UI/server.py → screen_behavior), which updates the buddy's needs
// and mood; its state comes back through BuddyStage.onState. The brain has
// voice lines of its own (see UI/companion.py): keys in any app, typing, and
// the camera's getting up / gone / back / sitting idle.
//
// Voice lines are the clips in HackMp3s/ (Mochi's end in F, Kiko's in M),
// listed by /api/voices.
//
// When the browser extension is installed, its bridge script (bridge.js)
// answers on this page through window.postMessage, and the extension's
// storage becomes the source of truth for settings, headpats, feeding and
// chat, so everything stays in sync with the buddy on other websites.
// Without the extension, the page talks to the app server directly and
// remembers state in localStorage. That's always the case in the desktop
// window (pywebview), where extensions can't run; there the extension chip
// only shows whether the app server has heard from the extension.

(() => {
  const B = globalThis.BuddyCharacters;
  const stage = globalThis.BuddyStage;
  const $ = (id) => document.getElementById(id);

  const aiStatus = $("ai-status");
  const extStatus = $("ext-status");
  const downloadLink = $("download-extension");
  const installDialog = $("install-dialog");
  const poke = $("buddy-poke");
  const caption = $("animation-caption");
  const choices = [...document.querySelectorAll(".buddy-choice")];
  const feedButton = $("feed-buddy");
  const treatButton = $("treat-buddy");
  const needsBox = $("needs");
  const moodLine = $("mood-line");
  const cameraFeed = $("camera-feed");
  const cameraBadge = $("camera-badge");
  const cameraNote = $("camera-note");
  const cameraToggle = $("camera-toggle");
  const bodyStatus = $("body-status");
  const showOnSites = $("show-on-sites");
  const voiceToggle = $("voice-on");
  const petCount = $("pet-count");
  const chatLog = $("chat-history");
  const chatForm = $("chat-form");
  const chatInput = $("user-input");

  const LOCAL_KEY = "buddy-app";
  const OFFLINE_TEXT = "I can't reach the Buddy app. Make sure python3 UI/server.py is running.";
  const SLEEP_AFTER_MS = 90_000;
  const WELCOME_AFTER_MS = 60_000;
  const HUNGRY_AFTER_MS = 45 * 60_000;

  if (!B || !stage) {
    aiStatus.textContent = "App server offline";
    aiStatus.dataset.state = "warn";
    caption.textContent = "Start the app with python3 UI/server.py, then open http://127.0.0.1:8765";
    return;
  }

  const LINES = {
    girl: {
      pet: ["Nya~ ♥", "Hehe, that tickles!", "More headpats please!"],
      angry: ["Hey! Too many pokes!", "Nyaa! Stop that!"],
      fed: ["Yum! Thank you~ ♥", "Fishies! Best buddy ever!"],
      copy: ["Ooh, copied! Nice find~"],
      paste: ["Pasted! You're on a roll~"],
      undo: ["Oopsie, undone~", "Undo! No worries~"],
      missed: ["You left me all alone..."],
      welcome: ["Welcome back! I missed you~"],
      hungry: "Mochi is hungry... fish please?",
      tired: "Zzz...",
    },
    boy: {
      pet: ["Mrrp. Thanks.", "H-hey! ...okay, that's nice."],
      angry: ["Okay, okay, that's enough!", "Hey! Quit it!"],
      fed: ["Oh, fish! Thanks.", "Mrrp. That hit the spot."],
      copy: ["Copied. Smart move."],
      paste: ["Pasted! Keep it up."],
      undo: ["Undone. Happens to everyone."],
      missed: ["...You were gone a while."],
      welcome: ["There you are!"],
      hungry: "Kinda hungry over here...",
      tired: "Zzz...",
    },
  };
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

  // --- State ---------------------------------------------------------------

  let prefs = { character: null, visible: true };
  let chat = []; // [{ role: "user" | "buddy", text, at, error? }]
  let pets = 0;
  let lastFed = Date.now();
  let ext = null; // { version } once the extension answers
  let extSeen = false; // the app server has had heartbeats from the extension
  let typing = false;
  let lastInput = Date.now();
  let hiddenAt = 0;

  const charKey = () => prefs.character ?? "girl";
  const buddyName = () => B.CHARACTERS[charKey()].name;
  const lines = () => LINES[charKey()];

  function loadLocal() {
    try {
      const saved = JSON.parse(localStorage.getItem(LOCAL_KEY));
      if (saved) {
        prefs = { ...prefs, ...saved.prefs };
        chat = Array.isArray(saved.chat) ? saved.chat : [];
        pets = saved.pets ?? 0;
        lastFed = saved.lastFed ?? lastFed;
      }
    } catch {}
  }

  function saveLocal() {
    if (ext) return; // the extension stores everything once connected
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify({ prefs, chat: chat.slice(-50), pets, lastFed }));
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
    if ("lastFed" in data && data.lastFed) lastFed = data.lastFed;
    renderSettings();
    renderChat();
    updateResting();
  }

  function setPrefs(next) {
    const changed = next.character !== prefs.character;
    prefs = next;
    renderSettings();
    renderChat();
    if (changed) stage.react("encouragement", 1600, `Hi! I'm ${buddyName()}!`);
    if (ext) request("setBuddy", { buddy: next });
    else saveLocal();
  }

  // --- Status chips --------------------------------------------------------

  function renderExtStatus() {
    if (ext) {
      extStatus.textContent = `Extension: connected v${ext.version}`;
      extStatus.dataset.state = "good";
    } else if (extSeen) {
      extStatus.textContent = "Extension: connected";
      extStatus.dataset.state = "good";
    } else {
      extStatus.textContent = "Extension: not installed";
      extStatus.dataset.state = "warn";
    }
    // The setting lives in the extension's storage, which only bridge.js reaches.
    showOnSites.disabled = !ext;
    showOnSites.parentElement.title = ext ? ""
      : extSeen ? "Right-click your buddy on any website to hide it."
      : "Install the extension to see your buddy on other websites.";
  }

  async function checkServer() {
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      const status = await res.json();
      aiStatus.textContent = status.ai === "claude" ? "AI: Claude" : "AI: built-in replies";
      aiStatus.dataset.state = status.ai === "claude" ? "good" : "warn";
      if (!!status.extension_seen !== extSeen) {
        extSeen = !!status.extension_seen;
        renderExtStatus();
      }
    } catch {
      aiStatus.textContent = "AI: app server offline";
      aiStatus.dataset.state = "warn";
    }
  }

  downloadLink.addEventListener("click", () => installDialog.showModal());

  // --- Voice (HackMp3s) ------------------------------------------------------

  const VOICE_KEY = "buddy-voice";
  const SAME_LINE_GAP_MS = 4000; // the page and the brain may both notice one thing
  const CMD_LINE_GAP_MS = 15_000; // one copy/paste/undo line per 15s, as in UI/companion.py
  const voice = new Audio();
  // { trigger: { girl: [{ url, text }], boy: [...] } } from /api/voices; `text`
  // is the clip's exact words from HackMp3s/captions.json, or null.
  let voiceClips = {};
  let voiceOn = true;
  try { voiceOn = localStorage.getItem(VOICE_KEY) !== "off"; } catch {}
  const lastClip = {}; // trigger -> url, so a line doesn't repeat back to back
  const lastSaid = {}; // trigger -> performance.now()
  let lineId = 0; // the line playing (or starting) now
  let lineHeldUntil = 0; // its reaction's end: the caption stays the line's until then

  fetch("/api/voices", { cache: "no-store" })
    .then((res) => res.json())
    .then((data) => { voiceClips = data; })
    .catch(() => {});

  // While a line plays, and until the reaction that came with it ends, the
  // caption is the line's own words or nothing: no other text shows over it.
  function endLine(id = lineId) {
    if (id !== lineId) return; // a newer line took over
    const wait = lineHeldUntil - performance.now();
    if (wait > 0) setTimeout(() => endLine(id), wait);
    else stage.setSpeech(null);
  }
  voice.addEventListener("ended", () => endLine());
  voice.addEventListener("error", () => endLine());

  function pickClip(trigger) {
    const options = voiceClips[trigger]?.[charKey()] ?? [];
    const fresh = options.length > 1 ? options.filter((c) => c.url !== lastClip[trigger]) : options;
    const clip = fresh.length ? pick(fresh) : null;
    if (clip) lastClip[trigger] = clip.url;
    return clip;
  }

  // Show `emotion` (BuddyStage.react) and say a `trigger` line in the chosen
  // buddy's voice, keeping the pose until the line ends. Things the user just
  // did cut off whatever is playing; the brain's own lines (`interrupt`
  // false) wait for silence instead. `message` only shows when nothing is
  // being said.
  function react(emotion, ms, message, trigger, interrupt = true) {
    stage.react(emotion, ms, message);
    if (!voiceOn || !trigger) return;
    const now = performance.now();
    // CMDC, CMDV and CMDZ share one limit.
    const [gapKey, gap] = trigger.startsWith("CMD") ? ["CMD", CMD_LINE_GAP_MS] : [trigger, SAME_LINE_GAP_MS];
    if (now - (lastSaid[gapKey] ?? -Infinity) < gap) return;
    if (!interrupt && !voice.paused && !voice.ended) return;
    const clip = pickClip(trigger);
    if (!clip) return;
    lastSaid[gapKey] = now;
    const id = ++lineId;
    lineHeldUntil = now + ms;
    stage.setSpeech(clip.text ?? "");
    voice.onloadedmetadata = () => {
      const lineMs = voice.duration * 1000 + 250;
      if (id !== lineId || lineMs <= ms) return;
      lineHeldUntil = Math.max(lineHeldUntil, performance.now() + lineMs);
      if (stage.isReacting(emotion)) stage.react(emotion, lineMs, message);
    };
    voice.src = clip.url;
    voice.play().catch(() => {
      // Browsers block sound until the page has been clicked once. Nothing
      // is said then, so the written line can show.
      if (id !== lineId) return;
      lineHeldUntil = 0;
      endLine(id);
    });
  }

  // --- Companion brain ------------------------------------------------------

  let companion = null; // latest /api/state, or null when the brain isn't running

  // Tell the brain about an interaction. Returns its result, or null if the
  // app server isn't running the companion.
  async function interact(action, extra = {}) {
    try {
      const res = await fetch("/api/interact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...extra }),
      });
      return res.status === 404 ? null : await res.json();
    } catch {
      return null;
    }
  }

  const ACTIVITY_WORDS = {
    coding: "coding", browsing: "browsing", gaming: "gaming", studying: "studying",
    video: "watching videos", idle: "taking a break", other: "doing your thing",
  };

  let lastVoiceId = null; // the brain's last voice line; null until the first state

  function renderCompanion(state) {
    // animation_bridge.py's /api/state has only animation + message: no needs to show.
    if (state && !state.pet) state = null;
    companion = state;
    if (state) {
      const line = state.voice;
      // Lines said before this page opened stay unsaid.
      if (lastVoiceId !== null && line && line.id !== lastVoiceId) {
        react(state.animation, line.seconds * 1000, state.message, line.trigger, false);
      }
      lastVoiceId = line?.id ?? lastVoiceId ?? 0;
    }
    needsBox.hidden = !state;
    treatButton.hidden = !state;
    if (!state) {
      moodLine.textContent = "";
      renderCamera(null);
      return;
    }
    for (const row of needsBox.querySelectorAll(".need")) {
      const value = state.pet[row.dataset.need];
      row.querySelector(".bar span").style.width = `${value}%`;
      row.classList.toggle("high", value >= 70);
      row.classList.toggle("low", value <= 25);
      row.title = `${row.dataset.need}: ${value}/100`;
    }
    // Fish is the brain's only food now, so the treat button only appears if
    // a brain reports earned treats.
    const treats = state.feeding?.wet_food_available;
    treatButton.hidden = treats === undefined;
    if (treats !== undefined) {
      treatButton.textContent = `Treat ×${treats}`;
      treatButton.disabled = treats < 1;
    }
    moodLine.textContent = `Feeling ${state.pet.mood} · you're ${ACTIVITY_WORDS[state.activity.type] ?? state.activity.type}`;
    renderCamera(state);
  }

  // --- Camera (BodyTracking) -------------------------------------------------

  const BODY_WORDS = { at_desk: "At your desk", getting_up: "Getting up", away: "Away" };

  function renderCamera(state) {
    const camera = state?.camera ?? { status: "unavailable", error: "" };
    const on = camera.status === "on" || camera.status === "starting";
    if (on && !cameraFeed.getAttribute("src")) cameraFeed.src = `/api/camera.mjpg?${Date.now()}`;
    if (!on && cameraFeed.getAttribute("src")) cameraFeed.removeAttribute("src");
    cameraFeed.hidden = !on;
    cameraBadge.hidden = camera.status !== "on";

    cameraToggle.hidden = !state || camera.status === "unavailable";
    cameraToggle.textContent = on ? "Stop camera" : "Start camera";
    cameraToggle.disabled = camera.status === "starting";

    if (!state) {
      cameraNote.textContent = "Start the app with python3 UI/server.py to use the camera.";
    } else if (camera.status === "unavailable") {
      cameraNote.textContent = "Body tracking needs OpenCV and MediaPipe. Install them with pip install -r requirements.txt, then restart the app.";
    } else if (camera.status === "error") {
      cameraNote.textContent = camera.error;
    } else if (!on) {
      cameraNote.textContent = "Turn on the camera and your buddy notices when you sit down, take a break, lean in or wave.";
    }

    const body = state?.body;
    bodyStatus.hidden = !body;
    if (body) {
      const extras = [body.hand_raised && "hand raised", body.leaning_in && "leaning in"].filter(Boolean);
      bodyStatus.textContent = [BODY_WORDS[body.state] ?? body.state, ...extras].join(" · ");
    }
  }

  cameraToggle.addEventListener("click", async () => {
    const on = !(companion?.camera.status === "on");
    cameraToggle.disabled = true;
    try {
      const res = await fetch("/api/camera", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on }),
      });
      const data = await res.json();
      if (res.ok) renderCompanion(data);
      else cameraNote.textContent = data.error;
    } catch {
      cameraNote.textContent = "Couldn't reach the app server.";
    }
    cameraToggle.disabled = false;
  });

  stage.onState(renderCompanion);

  // --- Reactions -------------------------------------------------------------

  // Resting pose when nothing else is happening: asleep after a quiet spell,
  // hungry when it's been a while since the last meal, otherwise lounging.
  function updateResting() {
    const asleep = Date.now() - lastInput > SLEEP_AFTER_MS;
    const hungry = Date.now() - lastFed > HUNGRY_AFTER_MS;
    stage.setResting(asleep ? "tired" : hungry ? "hungry" : "lounging");
    stage.setDefaultCaption(
      asleep ? lines().tired
        : hungry ? lines().hungry
        : prefs.character ? `${buddyName()} · click for a headpat`
        : "Pick a buddy to get started"
    );
  }

  const clickTimes = [];
  function onPoke() {
    const now = performance.now();
    while (clickTimes.length && now - clickTimes[0] > 2000) clickTimes.shift();
    clickTimes.push(now);
    if (clickTimes.length >= 5) {
      clickTimes.length = 0;
      react("angry", 2500, pick(lines().angry), "unhappy");
      interact("poke");
      return;
    }
    if (stage.isReacting("angry")) return; // let the sulk finish
    react("happy", 1800, pick(lines().pet), "happy");
    interact("pet");
    if (ext) {
      send("pet");
    } else {
      pets++;
      saveLocal();
      renderSettings();
    }
  }

  async function feed(food = "dry") {
    const result = await interact("feed", { food });
    if (result && !result.accepted) {
      // The brain decides: full, or no treats earned yet.
      stage.react("sad", 2000, result.message.includes("full") ? "I'm full..." : "No treats yet. Keep working!");
      return;
    }
    lastFed = Date.now();
    react("happy", 2000, food === "wet" ? "A treat!! Best day ever!" : pick(lines().fed), "fed");
    if (ext) send("feed");
    else saveLocal();
    updateResting();
  }

  poke.addEventListener("click", onPoke);
  feedButton.addEventListener("click", () => feed("dry"));
  treatButton.addEventListener("click", () => feed("wet"));

  document.addEventListener("copy", () => {
    react("encouragement", 2000, pick(lines().copy), "CMDC");
    interact("copy_paste");
  });
  document.addEventListener("paste", () => {
    react("encouragement", 2000, pick(lines().paste), "CMDV");
    interact("copy_paste");
  });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.repeat && e.key.toLowerCase() === "z") {
      react("encouragement", 2000, pick(lines().undo), "CMDZ");
    }
  });

  let lastPresence = 0;
  function noteInput() {
    const wasAsleep = Date.now() - lastInput > SLEEP_AFTER_MS;
    lastInput = Date.now();
    if (wasAsleep) updateResting();
    // Let the brain know you're active (at most every 5s). No tab info is
    // sent from this page, so it keeps whatever activity the extension saw.
    if (companion && lastInput - lastPresence > 5000) {
      lastPresence = lastInput;
      fetch("/api/presence", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
    }
  }
  for (const type of ["pointermove", "keydown", "scroll", "pointerdown"]) {
    addEventListener(type, noteInput, { passive: true, capture: true });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      hiddenAt = Date.now();
    } else if (hiddenAt && Date.now() - hiddenAt > WELCOME_AFTER_MS) {
      stage.react("sad", 1800, pick(lines().missed));
      setTimeout(() => react("happy", 1600, pick(lines().welcome), "onReturn"), 1800);
    }
  });

  setInterval(updateResting, 5000);

  // --- Settings ------------------------------------------------------------

  function setChoicePose(btn, emotion, active) {
    const img = btn.querySelector("img");
    const src = `/extension/${B.artPath(btn.dataset.char, emotion)}`;
    if (img.getAttribute("src") !== src) {
      img.src = src;
      const pose = img.parentElement;
      pose.classList.remove("pose-in");
      void pose.offsetWidth;
      pose.classList.add("pose-in");
    }
    img.className = `buddy-figure emo-${emotion}${active ? " react" : ""}`;
  }

  for (const btn of choices) {
    btn.querySelector(".name").textContent = B.CHARACTERS[btn.dataset.char].name;
    btn.querySelector(".label").textContent = B.CHARACTERS[btn.dataset.char].label;
    btn.addEventListener("click", () => setPrefs({ ...prefs, character: btn.dataset.char, visible: true }));
    // Hovering a choice makes that buddy cheer.
    btn.addEventListener("mouseenter", () => setChoicePose(btn, "encouragement", true));
    btn.addEventListener("mouseleave", renderSettings);
  }

  showOnSites.addEventListener("change", () => setPrefs({ ...prefs, visible: showOnSites.checked }));

  voiceToggle.checked = voiceOn;
  voiceToggle.addEventListener("change", () => {
    voiceOn = voiceToggle.checked;
    if (!voiceOn) {
      voice.pause();
      lineHeldUntil = 0;
      endLine();
    }
    try { localStorage.setItem(VOICE_KEY, voiceOn ? "on" : "off"); } catch {}
  });

  function renderSettings() {
    for (const btn of choices) {
      const selected = btn.dataset.char === prefs.character;
      btn.setAttribute("aria-pressed", String(selected));
      setChoicePose(btn, "happy", false);
    }
    showOnSites.checked = !!prefs.visible;
    petCount.textContent = pets ? `Headpats given: ${pets}` : "";
    feedButton.textContent = `Feed ${buddyName()}`;
    stage.setCharacter(charKey());
    updateResting();
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
    // React to what was said while the reply is on its way.
    stage.react(B.emotionForText(text), 3000);

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
  setInterval(checkServer, 5000); // the desktop window is never reloaded
  renderCompanion(null);

  // The bridge announces itself when it loads; ask too, in case it loaded first.
  send("hello");
  setTimeout(() => ext || renderExtStatus(), 1500);
})();
