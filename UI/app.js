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
//   camera-confirmed return    happy                              voice: onReturn
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
  const cameraView = $("camera-view");
  const cameraVideo = $("camera-video");
  const cameraSkeleton = $("camera-skeleton");
  const cameraBadge = $("camera-badge");
  const cameraNote = $("camera-note");
  const cameraToggle = $("camera-toggle");
  const cameraPreviewToggle = $("camera-preview-toggle");
  const cameraTrackingStatus = $("camera-tracking-status");
  const bodyStatus = $("body-status");
  const showOnSites = $("show-on-sites");
  const voiceToggle = $("voice-on");
  const petCount = $("pet-count");
  const chatLog = $("chat-history");
  const chatForm = $("chat-form");
  const chatInput = $("user-input");
  const clearButton = $("clear-chat");
  const clearDialog = $("clear-dialog");
  const clearMemories = $("clear-memories");
  const clearMemoriesLabel = $("clear-memories-label");
  const memoryToggle = $("memory-toggle");
  const memoryPanel = $("memory-panel");
  const memoryNote = $("memory-note");
  const memoryList = $("memory-list");
  const forgetAllButton = $("forget-all");

  const LOCAL_KEY = "buddy-app";
  const OFFLINE_TEXT = "I can't reach the Buddy app. Make sure python3 UI/server.py is running.";
  const SLEEP_AFTER_MS = 90_000;
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
  // [{ role: "user" | "buddy", text, at, error?, thought?, learned? }]; thought is
  // Claude's summarized reasoning, learned the notes it saved while replying.
  let chat = [];
  let live = null; // the reply streaming in: { text, thought, learned }
  let notes = []; // what the buddy has learned about the user: [{ id, kind, text }]
  let aiOn = false; // the app server answers with Claude
  let pets = 0;
  let lastFed = Date.now();
  let ext = null; // { version } once the extension answers
  let extensionVoice = false;
  let extSeen = false; // the app server has had heartbeats from the extension
  let typing = false;
  let lastInput = Date.now();

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
    if (msg.type === "hello" && !ext) {
      extensionVoice = msg.voice === true;
      connect(msg.version);
    }
    else if (msg.type === "response" && pending.has(msg.id)) {
      pending.get(msg.id)(msg.data);
      pending.delete(msg.id);
    } else if (msg.type === "changed") applyState(msg.data);
  });

  async function connect(version) {
    ext = { version };
    renderExtStatus();
    const saved = await request("get");
    if (extensionVoice && saved.voiceOn === undefined) await request("setVoice", { on: voiceOn });
    applyState(saved);
  }

  function applyState(data = {}) {
    if ("buddy" in data) prefs = { character: null, visible: true, ...data.buddy };
    if ("pets" in data) pets = data.pets ?? 0;
    if ("chat" in data) chat = data.chat ?? [];
    if ("lastFed" in data && data.lastFed) lastFed = data.lastFed;
    if ("voiceOn" in data) {
      voiceOn = data.voiceOn !== false;
      voiceToggle.checked = voiceOn;
      if (!voiceOn) { voice.pause(); stage.setSpeech(null); }
    }
    if ("voicePlayback" in data) showRemoteLine(data.voicePlayback);
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
      if ((status.ai === "claude") !== aiOn) {
        aiOn = status.ai === "claude";
        renderMemory();
      }
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
  const CMD_LINE_GAP_MS = 1000; // per shortcut; copy never delays a following paste/undo
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
  const voiceOwner = "page-" + Math.random().toString(36).slice(2);

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
    playLine(emotion, ms, message, trigger, interrupt).catch(() => {});
  }

  function showRemoteLine(line) {
    if (!line || !voiceOn) { stage.setSpeech(null); return; }
    const remaining = line.seconds * 1000 - (Date.now() - line.startedAt);
    if (remaining <= 0 || line.character !== charKey()) return;
    lineId++;
    lineHeldUntil = performance.now() + remaining;
    stage.setSpeech(line.text ?? "");
    endLine();
  }

  async function playLine(emotion, ms, message, trigger, interrupt, event = null) {
    if (!voiceOn || !trigger) return;
    if (extensionVoice) {
      await request("voice", { trigger, interrupt, event });
      return; // the shared playback notification supplies its exact caption
    }
    const now = performance.now();
    const [gapKey, gap] = [trigger, trigger.startsWith("CMD") ? CMD_LINE_GAP_MS : SAME_LINE_GAP_MS];
    if (now - (lastSaid[gapKey] ?? -Infinity) < gap) return;
    if (!interrupt && !voice.paused && !voice.ended) return;
    const clip = pickClip(trigger);
    if (!clip) return;
    let claimed = false;
    if (event?.key) {
      const response = await fetch("/api/voice/claim", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: event.key, owner: voiceOwner }) });
      if (!response.ok || !(await response.json()).claimed) return;
      claimed = true;
    }
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
      if (claimed) fetch("/api/voice/claim", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: event.key, owner: voiceOwner, release: true }) }).catch(() => {});
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
      if (lastVoiceId !== null && line && (line.key ?? line.id) !== lastVoiceId) {
        stage.react(state.animation, line.seconds * 1000, state.message);
        playLine(state.animation, line.seconds * 1000, state.message, line.trigger,
                 line.trigger.startsWith("CMD"), line).catch(() => {});
      }
      lastVoiceId = line?.key ?? line?.id ?? lastVoiceId ?? 0;
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
  //
  // The app server's webcam when it has one: companion.py runs
  // BodyTracking/tracking.py and streams /api/camera.mjpg. Otherwise (on
  // Vercel, or without OpenCV/MediaPipe) this page's webcam through body.js:
  // the video stays here and only the signals go to POST /api/body.

  const BODY_WORDS = { at_desk: "At your desk", getting_up: "Getting up", away: "Away" };
  const PREVIEW_KEY = "buddy-camera-preview";
  // Unchanged signals are re-sent this often, well within the server's
  // BODY_STALE_SECONDS (5s), so it knows the camera is still live.
  const BODY_REPORT_MS = 2000;
  let previewVisible = true;
  try { previewVisible = localStorage.getItem(PREVIEW_KEY) !== "hidden"; } catch {}
  const pageCamera = globalThis.BuddyBody?.createCamera({
    video: cameraVideo, canvas: cameraSkeleton, onSnapshot: reportBody, onChange: () => renderCamera(companion),
  });
  let bodyReported = { key: "", at: 0 };
  let bodyReporting = false;

  // The server's camera, or this page's while it runs or when the server has none.
  function cameraInfo(state) {
    const server = state?.camera ?? { status: "unavailable", error: "" };
    const pageOn = pageCamera?.status === "on" || pageCamera?.status === "starting";
    if (pageOn || (pageCamera && state && server.status === "unavailable")) {
      return { status: pageCamera.status, error: pageCamera.error, inPage: true };
    }
    return { ...server, inPage: false };
  }

  // Each frame's signals from body.js. Events go at once; otherwise only
  // changes, plus the same signals every BODY_REPORT_MS.
  async function reportBody(signals) {
    const key = [signals.state, signals.present, signals.hand_raised, signals.leaning_in].join();
    const now = Date.now();
    if (!signals.event && (bodyReporting || (key === bodyReported.key && now - bodyReported.at < BODY_REPORT_MS))) return;
    bodyReported = { key, at: now };
    bodyReporting = true;
    try {
      const res = await fetch("/api/body", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(signals) });
      if (res.ok) renderCompanion(await res.json());
    } catch {
      // Offline for now; the next change or report tries again.
    } finally {
      bodyReporting = false;
    }
  }

  function reportBodyOff() {
    bodyReported = { key: "", at: 0 };
    fetch("/api/body", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ camera: "off" }) })
      .then((res) => res.ok && res.json()).then((state) => state && renderCompanion(state)).catch(() => {});
  }

  function renderCamera(state) {
    const camera = cameraInfo(state);
    const on = camera.status === "on" || camera.status === "starting";
    const showPreview = on && previewVisible && document.visibilityState === "visible";
    const showFeed = showPreview && !camera.inPage;
    if (showFeed && !cameraFeed.getAttribute("src")) cameraFeed.src = `/api/camera.mjpg?${Date.now()}`;
    if (!showFeed && cameraFeed.getAttribute("src")) cameraFeed.removeAttribute("src");
    cameraFeed.hidden = !showFeed;
    // Off-screen rather than hidden while the page camera runs (see colorScheme.css).
    cameraView.hidden = !(on && camera.inPage);
    cameraView.dataset.preview = showPreview ? "shown" : "hidden";
    cameraBadge.hidden = camera.status !== "on" || !showPreview;
    cameraPreviewToggle.hidden = !on;
    cameraPreviewToggle.textContent = previewVisible ? "Hide preview" : "Show preview";
    cameraPreviewToggle.setAttribute("aria-pressed", String(previewVisible));
    cameraTrackingStatus.textContent = camera.status === "on"
      ? `Camera tracking on${showPreview ? "" : " · preview hidden"}`
      : camera.status === "starting" ? "Camera tracking starting…" : "Camera tracking off";

    cameraToggle.hidden = !(state || camera.inPage) || camera.status === "unavailable" || camera.status === "unsupported";
    cameraToggle.textContent = on ? "Stop camera" : "Start camera";
    cameraToggle.disabled = camera.status === "starting";

    if (!state && !camera.inPage) {
      cameraNote.textContent = "Start the app with python3 UI/server.py to use the camera.";
    } else if (camera.status === "unavailable") {
      cameraNote.textContent = "Body tracking needs OpenCV and MediaPipe. Install them with pip install -r requirements.txt, then restart the app.";
    } else if (camera.status === "error" || camera.status === "unsupported") {
      cameraNote.textContent = camera.error;
    } else if (!on) {
      cameraNote.textContent = "Turn on the camera and your buddy notices when you sit down, take a break, lean in or wave.";
    } else if (camera.inPage) {
      cameraNote.textContent = "Your video stays in this browser; only whether you're at your desk is sent. Tracking slows down while this tab is in the background.";
    } else {
      cameraNote.textContent = "Tracking continues while the preview is hidden or this tab is closed. Keep the Python app running.";
    }

    const body = camera.inPage ? pageCamera.snapshot : state?.body;
    bodyStatus.hidden = !body;
    if (body) {
      const extras = [body.hand_raised && "hand raised", body.leaning_in && "leaning in"].filter(Boolean);
      bodyStatus.textContent = [BODY_WORDS[body.state] ?? body.state, ...extras].join(" · ");
    }
  }

  cameraToggle.addEventListener("click", async () => {
    const camera = cameraInfo(companion);
    if (camera.inPage) {
      if (camera.status === "on") {
        pageCamera.stop();
        reportBodyOff();
      } else {
        await pageCamera.start();
      }
      return;
    }
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
  cameraPreviewToggle.addEventListener("click", () => {
    previewVisible = !previewVisible;
    try { localStorage.setItem(PREVIEW_KEY, previewVisible ? "shown" : "hidden"); } catch {}
    renderCamera(companion); // does not call /api/camera or change physical presence
  });
  document.addEventListener("visibilitychange", () => renderCamera(companion));

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

  const shortcutAt = {};
  async function reportShortcut(name, message) {
    const at = performance.now();
    if (at - (shortcutAt[name] ?? -Infinity) < 100) return;
    shortcutAt[name] = at;
    stage.react("encouragement", 2000, message);
    if (extensionVoice) return; // content.js reports the real input immediately
    try {
      const response = await fetch("/api/shortcut", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shortcut: name }) });
      if (response.ok) {
        lastVoiceId ??= 0;
        renderCompanion((await response.json()).state);
      } else {
        react("encouragement", 2000, message, { copy: "CMDC", paste: "CMDV", undo: "CMDZ" }[name]);
      }
    } catch {
      react("encouragement", 2000, message, { copy: "CMDC", paste: "CMDV", undo: "CMDZ" }[name]);
    }
  }
  document.addEventListener("copy", (event) => {
    if (!document.hasFocus() || event.isTrusted === false) return;
    reportShortcut("copy", pick(lines().copy));
    interact("copy_paste");
  });
  document.addEventListener("paste", (event) => {
    if (!document.hasFocus() || event.isTrusted === false) return;
    reportShortcut("paste", pick(lines().paste));
    interact("copy_paste");
  });
  document.addEventListener("keydown", (e) => {
    if (document.hasFocus() && e.isTrusted !== false && (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && !e.repeat) {
      const name = { c: "copy", v: "paste", z: "undo" }[String(e.key).toLowerCase()];
      if (name) reportShortcut(name, pick(lines()[name]));
    }
  });

  let lastPresence = 0;
  function noteInput(event) {
    if (!document.hasFocus() || event?.isTrusted === false) return;
    const wasAsleep = Date.now() - lastInput > SLEEP_AFTER_MS;
    lastInput = Date.now();
    if (wasAsleep) updateResting();
    // Let the brain know you're active (at most every 5s). No tab info is
    // sent from this page, so it keeps whatever activity the extension saw.
    if (companion && lastInput - lastPresence > 5000) {
      lastPresence = lastInput;
      fetch("/api/presence", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ input: true }) }).catch(() => {});
    }
  }
  for (const type of ["pointermove", "keydown", "wheel", "touchmove", "pointerdown"]) {
    addEventListener(type, noteInput, { passive: true, capture: true });
  }

  // Camera-confirmed returns arrive through /api/state. Switching tabs alone
  // must not play a missed-you/onReturn reaction.

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
    if (extensionVoice) request("setVoice", { on: voiceOn }).catch(() => {});
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
    renderMemory();
  }

  // --- Chat ----------------------------------------------------------------

  // One chat bubble. A buddy reply can carry Claude's summarized reasoning,
  // folded away underneath, and the notes it saved while answering.
  function messageEl(m, extraClass = "") {
    const article = document.createElement("article");
    article.className = `message ${m.role === "user" ? "user-message" : "ai-message"} ${extraClass}`.trim();
    const p = document.createElement("p");
    const who = document.createElement("strong");
    who.textContent = m.role === "user" ? "You" : buddyName();
    const body = document.createElement("span");
    p.append(who, document.createElement("br"), body);

    const thought = document.createElement("details");
    thought.className = "thought";
    const summary = document.createElement("summary");
    const reasoning = document.createElement("p");
    thought.append(summary, reasoning);
    const learned = document.createElement("p");
    learned.className = "learned";
    article.append(p, thought, learned);

    const fill = (m, thinking = false) => {
      body.textContent = m.text || "…";
      thought.hidden = !m.thought;
      summary.textContent = thinking ? `${buddyName()} is thinking…` : `How ${buddyName()} thought about it`;
      reasoning.textContent = m.thought ?? "";
      learned.hidden = !m.learned?.length;
      learned.textContent = m.learned?.length ? `Remembered: ${m.learned.join(" · ")}` : "";
    };
    fill(m);
    return { article, thought, fill };
  }

  let liveBubble = null;

  function renderChat() {
    chatLog.replaceChildren();
    if (!chat.length && !live) {
      chatLog.append(messageEl({ role: "buddy", text: `Hi! I'm ${buddyName()}. What are we working on today?` }).article);
    }
    for (const m of chat) chatLog.append(messageEl(m, m.error ? "error-message" : "").article);
    liveBubble = null;
    if (live) {
      liveBubble = messageEl({ role: "buddy", text: "" }, "typing");
      live.thinkingShown = undefined;
      chatLog.append(liveBubble.article);
      updateLive();
    }
    clearButton.disabled = typing || !chat.length;
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // Show the streaming reply without rebuilding the whole log.
  function updateLive() {
    if (!liveBubble || !live) return;
    const thinking = !live.text;
    liveBubble.fill(live, thinking);
    liveBubble.article.classList.toggle("typing", thinking);
    // Watch it think, then fold the reasoning away once the answer starts.
    if (live.thinkingShown !== thinking) {
      liveBubble.thought.open = thinking;
      live.thinkingShown = thinking;
    }
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // POST /api/chat/stream sends one JSON event per line (see UI/server.py);
  // resolves with the final "done" event.
  async function streamReply(text, history) {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, character: charKey(), history }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    let done = null;
    for (;;) {
      const { value, done: ended } = await reader.read();
      if (value) buffered += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffered.indexOf("\n")) >= 0) {
        const line = buffered.slice(0, newline).trim();
        buffered = buffered.slice(newline + 1);
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "done") done = event;
        else if (event.type === "thinking") live.thought += event.text;
        else if (event.type === "text") live.text += event.text;
        else if (event.type === "memory") {
          if (event.action === "remembered") live.learned.push(event.note.text);
          loadMemory();
        }
        updateLive();
      }
      if (ended) break;
    }
    if (!done) throw new Error("The reply stopped early.");
    return done;
  }

  async function sendChat(text) {
    typing = true;
    // React to what was said while the reply is on its way.
    stage.react(B.emotionForText(text), 3000);

    const history = chat.slice();
    const asked = { role: "user", text, at: Date.now() };
    chat.push(asked);
    live = { text: "", thought: "", learned: [] };
    renderChat();
    let answer;
    try {
      const done = await streamReply(text, history);
      answer = { role: "buddy", text: done.reply, at: Date.now() };
      if (done.thought) answer.thought = done.thought;
      if (done.learned?.length) answer.learned = done.learned;
    } catch {
      answer = { role: "buddy", text: OFFLINE_TEXT, error: true, at: Date.now() };
    }
    live = null;
    typing = false;
    chat.push(answer);
    renderChat();
    if (ext) {
      // The extension's storage holds the shared history; its change events
      // re-render the log here and on every other tab.
      request("recordChat", { entries: [asked, answer] }).catch(() => {});
    } else {
      saveLocal();
    }
  }

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text || typing) return;
    chatInput.value = "";
    sendChat(text);
  });

  // --- Deleting the chat ---------------------------------------------------

  clearButton.addEventListener("click", () => {
    clearMemories.checked = false;
    clearMemoriesLabel.textContent = `Also forget what ${buddyName()} learned about you`;
    clearMemories.parentElement.hidden = !notes.length;
    clearDialog.returnValue = "";
    clearDialog.showModal();
  });

  clearDialog.addEventListener("close", () => {
    if (clearDialog.returnValue === "delete") deleteChat(clearMemories.checked);
  });

  async function deleteChat(alsoMemories) {
    chat = [];
    renderChat();
    if (ext) request("clearChat").catch(() => {}); // clears every tab
    else saveLocal();
    if (alsoMemories) await forgetAll();
    stage.react("encouragement", 1600, "Fresh start!");
  }

  // --- Memory: what the buddy learned about you ----------------------------

  let forgetArmedUntil = 0;

  function noteEl(note) {
    const li = document.createElement("li");
    li.className = "memory-item";
    const kind = document.createElement("span");
    kind.className = "memory-kind";
    kind.textContent = note.kind === "how_to_talk" ? "How to talk" : "About you";
    const text = document.createElement("span");
    text.className = "memory-text";
    text.textContent = note.text;
    const forget = document.createElement("button");
    forget.type = "button";
    forget.className = "forget-note";
    forget.textContent = "✕";
    forget.setAttribute("aria-label", `Forget: ${note.text}`);
    forget.addEventListener("click", () => forgetNote(note.id));
    li.append(kind, text, forget);
    return li;
  }

  function renderMemory() {
    memoryToggle.textContent = notes.length ? `Memory (${notes.length})` : "Memory";
    memoryList.replaceChildren(...notes.map(noteEl));
    forgetAllButton.hidden = !notes.length;
    if (Date.now() > forgetArmedUntil) forgetAllButton.textContent = "Forget everything";
    memoryNote.textContent = notes.length
      ? `What ${buddyName()} has learned about you from chatting. Remove anything you don't want remembered.`
      : aiOn
        ? `Nothing yet. ${buddyName()} picks up what you're into and how you like to talk as you chat.`
        : `${buddyName()} learns about you while chatting with Claude. Start the app with an Anthropic API key to turn it on.`;
  }

  async function memoryRequest(path, body) {
    try {
      const res = await fetch(path, body === undefined ? { cache: "no-store" } : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) notes = (await res.json()).notes ?? [];
    } catch {} // the app server is off; keep what's shown
    renderMemory();
  }

  const loadMemory = () => memoryRequest("/api/memory");
  const forgetNote = (id) => memoryRequest("/api/memory/forget", { id });
  const forgetAll = () => memoryRequest("/api/memory/clear", {});

  memoryToggle.addEventListener("click", () => {
    memoryPanel.hidden = !memoryPanel.hidden;
    memoryToggle.setAttribute("aria-expanded", String(!memoryPanel.hidden));
    if (!memoryPanel.hidden) loadMemory();
  });

  // Two clicks, so one slip doesn't wipe everything.
  forgetAllButton.addEventListener("click", () => {
    if (Date.now() > forgetArmedUntil) {
      forgetArmedUntil = Date.now() + 4000;
      forgetAllButton.textContent = "Sure? Click again";
      setTimeout(renderMemory, 4100);
      return;
    }
    forgetArmedUntil = 0;
    forgetAll();
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
  loadMemory();
  renderCompanion(null);

  // The bridge announces itself when it loads; ask too, in case it loaded first.
  send("hello");
  setTimeout(() => ext || renderExtStatus(), 1500);
})();
