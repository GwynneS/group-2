// The on-page buddy: a cat girl or cat boy that drifts around the browser
// window and changes pose and motion in response to what you do:
//
//   click (pet)                  happy          bounce + hearts
//   5+ clicks in 2s / shaking    angry          shake
//   copy or paste                encouragement  pop, then hop
//   chat message                 by its words (see characters.js)
//   idle 90s                     tired          slow breathing, until you're back
//   back after 60s away          sad, then happy
//   not fed for 45 min           hungry         wiggle, until fed (right-click → Feed)
//
// Drag to move it; right-click to chat, feed, switch character or hide it.
// The chat is shared with the Buddy app (UI/server.py) and every other tab.
//
// When the Buddy app is running, its companion brain (screen_behavior) sets
// the resting pose and caption: hungry, tired, lonely... based on its needs.
// Every few seconds, the focused tab's title and host go to the app
// (127.0.0.1 only) so the brain knows whether you're coding, studying,
// watching videos and so on. Headpats, pokes, feeding and copy/paste are
// sent to the brain too.
//
// Preference lives in storage.local under `buddy`:
//   { character: "girl" | "boy" | null, visible: boolean }
// and the last feeding time under `lastFed`. Changing either anywhere
// (popup, app, right-click menu, first-run picker) updates every tab live.

(() => {
  if (window.top !== window || !document.documentElement) return;
  // The Buddy app page shows its own buddy; don't add a second one there.
  if (/^(127\.0\.0\.1|localhost)$/.test(location.hostname) && location.port === "8765") return;

  const api = globalThis.browser ?? globalThis.chrome;
  const B = globalThis.BuddyCharacters;

  const BW = 150; // box the buddy lives in; poses sit bottom-centre inside it
  const BH = 140;
  const ART_SCALE = 0.5; // art is drawn at 2x for sharp screens
  const EDGE = 8;
  const TOP_ROOM = 60; // keep space above for the speech bubble
  const SLEEP_AFTER_MS = 90_000;
  const WELCOME_AFTER_MS = 60_000;
  const HUNGRY_AFTER_MS = 45 * 60_000;
  const APP_POLL_MS = 4000;
<<<<<<< HEAD
  const BRAIN_POLL_MS = 3000;
  const BRAIN_STALE_MS = 10_000;
=======
>>>>>>> 9b0637757641b51cd0079019b108ecf6b47ec0ad
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const LINES = {
    girl: {
      greet: ["Hi hi! I'm Mochi~", "Mochi's here! Let's do our best!"],
      pet: ["Nya~ ♥", "Hehe, that tickles!", "Purrr...", "More headpats please!"],
      angry: ["Hey! Too many pokes!", "Nyaa! Stop that!", "Put me down gently!"],
      copy: ["Ooh, copied! Nice find~", "Got it saved, nya!"],
      paste: ["Pasted! You're on a roll~", "Paste-tastic!"],
      missed: ["You left me all alone...", "Where did you go?"],
      welcome: ["Welcome back! I missed you~", "Yay, you're back!"],
      wake: ["Mm? Oh! I'm awake, I'm awake!", "*yawn* ...morning~"],
      hungry: ["Mochi is hungry... fish please?", "My tummy's rumbling~"],
      fed: ["Yum! Thank you~ ♥", "Fishies! Best buddy ever!"],
      idle: ["You're doing great!", "Remember to drink water~", "Focus mode: activated!", "Nya~"],
    },
    boy: {
      greet: ["Hey! I'm Kiko. Let's get stuff done.", "Kiko reporting for duty!"],
      pet: ["H-hey! ...okay, that's nice.", "Mrrp. Thanks.", "Purr... don't tell anyone."],
      angry: ["Okay, okay, that's enough!", "Hey! Quit it!", "Easy! I'm not a stress ball."],
      copy: ["Copied. Smart move.", "Nice grab!"],
      paste: ["Pasted! Keep it up.", "And... pasted. Nice."],
      missed: ["...You were gone a while.", "Oh. You're back."],
      welcome: ["Welcome back! Ready to go?", "There you are!"],
      wake: ["Huh? I wasn't sleeping.", "*stretch* ...okay, I'm up."],
      hungry: ["Any chance of a snack?", "Kinda hungry over here..."],
      fed: ["Oh, fish! Thanks.", "Mrrp. That hit the spot."],
      idle: ["You've got this.", "Stretch break soon?", "Solid work so far.", "Mrrp."],
    },
  };

  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const artUrl = (character, emotion) => api.runtime.getURL(B.artPath(character, emotion));

  let prefs = { character: null, visible: true };
  let lastFed = Date.now();
  let app = null; // companion state from the Buddy app, or null if it isn't running

  // --- DOM (inside a shadow root so page CSS can't touch it) ---------------

  const host = document.createElement("div");
  host.style.cssText =
    "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
  const root = host.attachShadow({ mode: "closed" });
  // Styles go in through textContent and the markup stays a plain string, so
  // nothing dynamic is ever parsed as HTML (Firefox add-on review checks this).
  const style = document.createElement("style");
  style.textContent = `
      :host { all: initial; }
      [hidden] { display: none !important; }
      * { box-sizing: border-box; font-family: "Press Start 2P", "VT323", ui-monospace, "Courier New", monospace; }
      ${B.ANIMATION_CSS}
      .wrap { position: fixed; left: 0; top: 0; width: ${BW}px; height: ${BH}px; pointer-events: none; will-change: transform; }
      .flip { position: absolute; inset: 0; }
      .flip.left { transform: scaleX(-1); }
      .buddy-pose {
        position: absolute; left: 50%; bottom: 0; translate: -50% 0;
        filter: drop-shadow(3px 3px 0 rgba(43, 25, 64, 0.25));
      }
      .buddy-figure { pointer-events: auto; cursor: grab; touch-action: none; }
      .buddy-figure.dragging { cursor: grabbing; }
      .bubble {
        position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
        width: max-content; max-width: 190px; padding: 6px 8px;
        background: #fff8df; color: #2b1940; border: 2px solid #392452;
        box-shadow: 3px 3px 0 rgba(43, 25, 64, 0.3);
        font-size: 9px; line-height: 1.6; text-align: center;
      }
      .bubble::after {
        content: ""; position: absolute; top: 100%; left: calc(50% - 4px);
        border: 4px solid transparent; border-top-color: #392452;
      }
      .heart {
        position: absolute; color: #9b5de5; font-size: 16px; pointer-events: none;
        text-shadow: 1px 1px 0 #2b1940; animation: rise 900ms steps(6, end) forwards;
      }
      @keyframes rise { to { transform: translateY(-44px); opacity: 0; } }

      .menu, .picker {
        position: fixed; pointer-events: auto; background: #fff8df; color: #2b1940;
        border: 3px solid #392452; box-shadow: 4px 4px 0 rgba(43, 25, 64, 0.3);
      }
      .menu { display: flex; flex-direction: column; min-width: 170px; }
      .menu button, .picker button {
        all: unset; cursor: pointer; font-size: 9px; line-height: 1.6; color: #2b1940;
      }
      .menu button { padding: 8px 10px; }
      .menu button + button { border-top: 2px solid #eee0ff; }
      .menu button:hover, .menu button:focus-visible { background: #eee0ff; }

      .picker { right: 16px; bottom: 16px; padding: 14px; width: 280px; }
      .picker h2 { margin: 0 0 10px; font-size: 10px; line-height: 1.6; text-transform: uppercase; }
      .picker .choices { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
      .picker button {
        display: flex; flex-direction: column; align-items: center; gap: 6px;
        padding: 8px 4px; background: #eee0ff; border: 2px solid #392452; text-align: center;
      }
      .picker button:hover, .picker button:focus-visible { background: #d8b8f2; }
      .picker img { height: 110px; width: auto; pointer-events: none; }
      .picker p { margin: 10px 0 0; font-size: 8px; line-height: 1.6; color: #715d88; }

      .chat {
        position: fixed; right: 16px; bottom: 16px; width: 280px; height: 340px;
        max-width: calc(100vw - 32px); max-height: calc(100vh - 32px);
        display: flex; flex-direction: column; pointer-events: auto;
        background: #fff8df; color: #2b1940;
        border: 3px solid #392452; box-shadow: 4px 4px 0 rgba(43, 25, 64, 0.3);
      }
      .chat header {
        display: flex; align-items: center; justify-content: space-between; gap: 8px;
        padding: 6px 8px; background: #43245e; color: #fff8df; font-size: 9px; line-height: 1.6;
      }
      .chat header button { all: unset; cursor: pointer; padding: 0 4px; font-size: 10px; color: #fff8df; }
      .chat header button:focus-visible { outline: 2px dashed #c6ed78; }
      .chat .log {
        flex: 1; min-height: 0; overflow-y: auto; padding: 8px;
        display: flex; flex-direction: column; gap: 8px; background: #eee0ff;
      }
      .chat .msg {
        max-width: 88%; padding: 6px 8px; background: #ffffff; border: 2px solid #392452;
        font-size: 8px; line-height: 1.7; overflow-wrap: anywhere;
      }
      .chat .msg.user { align-self: flex-end; background: #fff8df; }
      .chat .msg.error { border-style: dashed; }
      .chat .msg.typing { color: #715d88; }
      .chat .msg b { display: block; color: #7046a0; }
      .chat form { display: flex; gap: 6px; padding: 8px; border-top: 2px solid #392452; }
      .chat input {
        all: unset; flex: 1; min-width: 0; padding: 6px 8px; background: #ffffff;
        border: 2px solid #392452; font-size: 8px; line-height: 1.6; color: #2b1940;
      }
      .chat form button {
        all: unset; cursor: pointer; padding: 6px 8px; background: #7046a0; color: #ffffff;
        border: 2px solid #392452; font-size: 8px; line-height: 1.6;
      }
      .chat input:focus-visible, .chat form button:focus-visible { outline: 2px dashed #7046a0; outline-offset: 1px; }
  `;
  root.innerHTML = `
    <div class="wrap" hidden>
      <div class="flip"><div class="buddy-pose"><img class="buddy-figure" alt="Buddy" draggable="false"></div></div>
      <div class="bubble" hidden></div>
    </div>
    <div class="menu" hidden></div>
    <div class="picker" hidden>
      <h2>Pick your buddy!</h2>
      <div class="choices">
        <button data-char="girl"><img alt=""></button>
        <button data-char="boy"><img alt=""></button>
      </div>
      <p>You can switch any time: right-click your buddy or use the toolbar icon.</p>
    </div>
    <section class="chat" hidden aria-label="Chat with your buddy">
      <header><span class="chat-title"></span><button type="button" class="close" aria-label="Close chat">✕</button></header>
      <div class="log" role="log" aria-live="polite"></div>
      <form>
        <input type="text" maxlength="2000" placeholder="Say something…" aria-label="Message" autocomplete="off">
        <button type="submit">Send</button>
      </form>
    </section>
  `;
  root.prepend(style);

  const wrap = root.querySelector(".wrap");
  const flip = wrap.querySelector(".flip");
  const pose = wrap.querySelector(".buddy-pose");
  const figure = wrap.querySelector(".buddy-figure");
  const bubble = root.querySelector(".bubble");
  const menu = root.querySelector(".menu");
  const picker = root.querySelector(".picker");
  const chatPanel = root.querySelector(".chat");
  const chatLog = chatPanel.querySelector(".log");
  const chatInput = chatPanel.querySelector("input");

  for (const btn of picker.querySelectorAll("button")) {
    const ch = B.CHARACTERS[btn.dataset.char];
    btn.querySelector("img").src = artUrl(btn.dataset.char, "happy");
    btn.append(`${ch.name} · ${ch.label}`);
    btn.addEventListener("click", () => savePrefs({ character: btn.dataset.char, visible: true }));
  }

  // Poses are shown at half their pixel size so they stay sharp.
  figure.addEventListener("load", () => {
    figure.style.width = `${figure.naturalWidth * ART_SCALE}px`;
  });

  // --- State ---------------------------------------------------------------

  const st = {
    x: innerWidth - BW - 40,
    y: innerHeight - BH - 40,
    tx: 0,
    ty: 0,
    mode: "idle", // idle | wander | follow | sleep | chat
    modeUntil: 0,
    facingLeft: false,
    lastInput: Date.now(),
    hiddenAt: 0,
    mouse: null,
  };
  const reaction = { emotion: null, until: 0 };
  let bubbleTimer = 0;
  let running = false;

  function lines() {
    return LINES[prefs.character] ?? LINES.girl;
  }

  function say(text, ms = 3000) {
    clearTimeout(bubbleTimer);
    bubble.textContent = text;
    bubble.hidden = false;
    if (ms) bubbleTimer = setTimeout(() => (bubble.hidden = true), ms);
  }

  function setMode(mode, ms = 0) {
    st.mode = mode;
    st.modeUntil = performance.now() + ms;
  }

  // Show `emotion` with its motion for `ms`, then fall back to the resting pose.
  function react(emotion, ms, line) {
    reaction.emotion = emotion;
    reaction.until = performance.now() + ms;
    if (line) say(line, ms + 600);
  }

  // With the app running, its brain decides hunger; otherwise a local timer does.
  const isHungry = () => (app ? app.animation === "hungry" : Date.now() - lastFed > HUNGRY_AFTER_MS);

  function currentPose(now) {
    if (reaction.emotion && now < reaction.until) return { emotion: reaction.emotion, active: true };
    if (st.mode === "sleep") return { emotion: "tired", active: false };
    if (app && app.animation !== "lounging") return { emotion: app.animation, active: false };
    if (isHungry()) return { emotion: "hungry", active: false };
    return { emotion: "happy", active: false };
  }

  // --- Buddy app (companion brain) -----------------------------------------

  function tellApp(action, extra = {}) {
    try {
      return api.runtime.sendMessage({ type: "interact", action, ...extra });
    } catch {
      return Promise.resolve(null); // extension reloaded; this page's script is orphaned
    }
  }

  async function pollApp() {
    if (!running || document.visibilityState !== "visible") return;
    const page = document.hasFocus() ? { title: document.title, host: location.hostname } : null;
    let next = null;
    try {
      next = await api.runtime.sendMessage({ type: "appState", page });
    } catch {}
    // Say what the brain is up to when it changes (hungry, lonely, sleepy...).
    if (next && next.animation !== app?.animation && next.animation !== "lounging" && now() > reaction.until) {
      say(next.message, 3500);
    }
    app = next;
  }
  const now = () => performance.now();
  setInterval(pollApp, APP_POLL_MS);

  let shownSrc = "";
  let shownClass = "";
  function showPose(emotion, active) {
    const src = artUrl(prefs.character, emotion);
    if (src !== shownSrc) {
      shownSrc = src;
      figure.src = src;
      // Restart the little "pop" whenever the pose changes.
      pose.classList.remove("pose-in");
      void pose.offsetWidth;
      pose.classList.add("pose-in");
    }
    const cls = `buddy-figure emo-${emotion}${active ? " react" : ""}${drag?.moved ? " dragging" : ""}`;
    if (cls !== shownClass) figure.className = shownClass = cls;
  }

  function preload(character) {
    for (const emotion of B.EMOTIONS) new Image().src = artUrl(character, emotion);
  }

  function clampToViewport() {
    st.x = clamp(st.x, EDGE, innerWidth - BW - EDGE);
    st.y = clamp(st.y, TOP_ROOM, innerHeight - BH - EDGE);
  }

  function pickNextMove() {
    if (st.mouse && Math.random() < 0.3) {
      setMode("follow", rand(3000, 5000));
      return;
    }
    st.tx = rand(EDGE, innerWidth - BW - EDGE);
    st.ty = rand(TOP_ROOM, innerHeight - BH - EDGE);
    setMode("wander", 15000);
  }

  // Move toward (tx, ty); returns true on arrival.
  function moveToward(tx, ty, speed, dt) {
    const dx = tx - st.x;
    const dy = ty - st.y;
    const dist = Math.hypot(dx, dy);
    if (dist < 2) return true;
    const step = Math.min(dist, speed * dt);
    st.x += (dx / dist) * step;
    st.y += (dy / dist) * step;
    if (Math.abs(dx) > 1) st.facingLeft = dx < 0;
    return false;
  }

<<<<<<< HEAD
  // --- Companion brain -----------------------------------------------------

  function brainFresh() {
    return st.brain && Date.now() - st.brainAt < BRAIN_STALE_MS;
  }

  // Act on the brain's decision when it changes; in between, the buddy's own
  // movement code animates it.
  function applyBrain(data) {
    st.brain = data;
    st.brainAt = data ? Date.now() : 0;
    const mode = data?.onpage_mode ?? null;
    if (!mode || mode === st.brainMode) return;
    st.brainMode = mode;
    if (st.mode === "chat" || drag || !prefs.character) return;

    switch (mode) {
      case "sleep":
        setMode("sleep");
        say("Zzz...", 0);
        break;
      case "wander":
        st.tx = rand(EDGE, innerWidth - BW - EDGE);
        st.ty = rand(TOP_ROOM, innerHeight - BH - EDGE);
        setMode("wander", 15000);
        break;
      case "follow":
        if (st.mouse) setMode("follow", rand(4000, 6000));
        break;
      case "cheer":
        setMode("idle", 3000);
        react("happy", 2500, data.message);
        break;
      case "attention":
        if (st.mouse) setMode("follow", 6000);
        say(pick(lines().attention), 3500);
        break;
      default:
        if (st.mode === "sleep") {
          setMode("idle", 1500);
          say(pick(lines().wake), 2500);
        }
    }
  }

  function pollBrain() {
    if (!running) return;
    try {
      api.runtime.sendMessage({ type: "brainState" }).then(applyBrain, () => applyBrain(null));
    } catch {
      applyBrain(null); // extension reloaded; this page's script is orphaned
    }
  }
  setInterval(pollBrain, BRAIN_POLL_MS);

=======
>>>>>>> 9b0637757641b51cd0079019b108ecf6b47ec0ad
  function update(now, dt) {
    if (drag) return false;

    if (st.mode !== "sleep" && st.mode !== "chat" && Date.now() - st.lastInput > SLEEP_AFTER_MS) {
      setMode("sleep");
      say("Zzz...", 0);
    }

    // Busy reacting: stay put until the reaction is over.
    if (now < reaction.until && st.mode !== "chat") return false;

    let moving = false;
    switch (st.mode) {
      case "idle":
        if (now > st.modeUntil) pickNextMove();
        break;
      case "wander":
        moving = !moveToward(st.tx, st.ty, 60, dt);
        if (!moving || now > st.modeUntil) {
          setMode("idle", rand(2500, 7000));
          if (isHungry() && Math.random() < 0.4) say(pick(lines().hungry));
          else if (Math.random() < 0.15) say(pick(lines().idle));
        }
        break;
      case "follow": {
        if (!st.mouse || now > st.modeUntil) {
          setMode("idle", rand(2000, 4000));
          break;
        }
        // Stop a little to the side of the cursor instead of covering it.
        const side = st.mouse.x > st.x + BW / 2 ? -BW - 24 : 24;
        const tx = clamp(st.mouse.x + side, EDGE, innerWidth - BW - EDGE);
        const ty = clamp(st.mouse.y - BH / 2, TOP_ROOM, innerHeight - BH - EDGE);
        moving = !moveToward(tx, ty, 120, dt);
        break;
      }
      case "chat": {
        // Sit just to the left of the chat panel.
        const r = chatPanel.getBoundingClientRect();
        moving = !moveToward(r.left - BW - 4, r.bottom - BH, 160, dt);
        if (!moving) st.facingLeft = false;
        break;
      }
    }
    clampToViewport();
    return moving;
  }

  function render(now, moving) {
    if (!prefs.character) return;
    const { emotion, active } = currentPose(now);
    showPose(emotion, active);
    flip.classList.toggle("left", st.facingLeft);

    // Float gently; hop while travelling; sink low while asleep.
    let bob = 0;
    if (!reduceMotion) {
      if (moving) bob = -Math.abs(Math.sin(now / 140)) * 6;
      else if (st.mode === "sleep") bob = Math.sin(now / 900) * 1.5;
      else if (!active) bob = Math.sin(now / 380) * 3;
    }
    wrap.style.transform = `translate(${Math.round(st.x)}px, ${Math.round(st.y + bob)}px)`;
  }

  let last = 0;
  function frame(now) {
    if (!running) return;
    const dt = Math.min((now - (last || now)) / 1000, 0.05);
    last = now;
    render(now, update(now, dt));
    requestAnimationFrame(frame);
  }

  function start() {
    if (running) return;
    running = true;
    last = 0;
    requestAnimationFrame(frame);
    pollApp();
<<<<<<< HEAD
    pollBrain();
=======
>>>>>>> 9b0637757641b51cd0079019b108ecf6b47ec0ad
  }

  function stop() {
    running = false;
  }

  // --- Interaction: pet (click), move (drag), menu (right-click) -----------

  let drag = null;
  const clickTimes = [];

  figure.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    figure.setPointerCapture(e.pointerId);
    drag = { sx: e.clientX, sy: e.clientY, ox: st.x, oy: st.y, moved: false, dir: 0, flips: [] };
  });

  figure.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx;
    const dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true;
    st.x = drag.ox + dx;
    st.y = drag.oy + dy;
    clampToViewport();

    // Shaking: several fast left-right direction changes within a second.
    if (Math.abs(e.movementX) > 8) {
      const dir = Math.sign(e.movementX);
      if (drag.dir && dir !== drag.dir) {
        const now = performance.now();
        drag.flips = drag.flips.filter((t) => now - t < 1000).concat(now);
        if (drag.flips.length >= 4 && reaction.emotion !== "angry") {
          react("angry", 2500, pick(lines().angry));
        }
      }
      drag.dir = dir;
    }
    render(performance.now(), false);
  });

  figure.addEventListener("pointerup", () => {
    if (!drag) return;
    const wasDrag = drag.moved;
    drag = null;
    wake();
    if (wasDrag) {
      if (chatPanel.hidden) setMode("idle", 8000);
      savePosition();
    } else {
      poke();
    }
  });

  figure.addEventListener("pointercancel", () => {
    drag = null;
  });

  function hearts() {
    for (let i = 0; i < 3; i++) {
      const heart = document.createElement("span");
      heart.className = "heart";
      heart.textContent = "♥";
      heart.style.left = `${rand(20, BW - 30)}px`;
      heart.style.top = `${rand(0, 40)}px`;
      heart.style.animationDelay = `${i * 120}ms`;
      wrap.append(heart);
      setTimeout(() => heart.remove(), 900 + i * 120);
    }
  }

  // A click is a headpat, unless it's one of many in quick succession.
  function poke() {
    const now = performance.now();
    while (clickTimes.length && now - clickTimes[0] > 2000) clickTimes.shift();
    clickTimes.push(now);
    if (clickTimes.length >= 5) {
      clickTimes.length = 0;
      react("angry", 2500, pick(lines().angry));
      tellApp("poke");
      return;
    }
    react("happy", 1800, pick(lines().pet));
    hearts();
    tellApp("pet");
    try {
      api.runtime.sendMessage({ type: "pet", character: prefs.character });
    } catch {}
  }

  async function feed() {
    const result = await tellApp("feed");
    if (result && !result.accepted) {
      react("sad", 2000, result.message?.includes("full") ? "I'm full..." : pick(lines().hungry));
      return;
    }
    api.storage.local.set({ lastFed: Date.now() });
    lastFed = Date.now();
    react("happy", 2000, pick(lines().fed));
    hearts();
  }

  figure.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    const other = prefs.character === "girl" ? "boy" : "girl";
    const o = B.CHARACTERS[other];
    const me = B.CHARACTERS[prefs.character];
    menu.innerHTML = "";
    const items = [
      [`Chat with ${me.name}`, openChat],
      [`Feed ${me.name}`, feed],
      [`Switch to ${o.name} (${o.label})`, () => savePrefs({ ...prefs, character: other })],
      ["Hide buddy", () => savePrefs({ ...prefs, visible: false })],
    ];
    for (const [label, fn] of items) {
      const b = document.createElement("button");
      b.textContent = label;
      b.addEventListener("click", () => {
        menu.hidden = true;
        fn();
      });
      menu.append(b);
    }
    menu.hidden = false;
    menu.style.left = `${clamp(e.clientX, 8, innerWidth - 190)}px`;
    menu.style.top = `${clamp(e.clientY, 8, innerHeight - 160)}px`;
  });

  addEventListener("pointerdown", (e) => {
    // The shadow root is closed, so from out here the path stops at `host`.
    if (!menu.hidden && !e.composedPath().includes(host)) menu.hidden = true;
  }, true);

  // --- Chat ----------------------------------------------------------------

  let chatHistory = [];
  let chatWaiting = false;

  function openChat() {
    chatPanel.querySelector(".chat-title").textContent = `Chat with ${B.CHARACTERS[prefs.character].name}`;
    chatPanel.hidden = false;
    setMode("chat");
    wake();
    renderChat();
    api.storage.local.get("chat").then(({ chat = [] }) => {
      chatHistory = chat;
      renderChat();
    });
    chatInput.focus();
  }

  function closeChat() {
    chatPanel.hidden = true;
    setMode("idle", rand(1500, 3000));
  }

  function renderChat() {
    const name = B.CHARACTERS[prefs.character ?? "girl"].name;
    const rows = chatHistory.length
      ? chatHistory
      : [{ role: "buddy", text: `Hi! I'm ${name}. What are we working on?` }];
    chatLog.replaceChildren();
    const add = (role, text, cls = "") => {
      const div = document.createElement("div");
      div.className = `msg ${role === "user" ? "user" : ""} ${cls}`.trim();
      const who = document.createElement("b");
      who.textContent = role === "user" ? "You" : name;
      div.append(who, text);
      chatLog.append(div);
    };
    for (const m of rows) add(m.role, m.text, m.error ? "error" : "");
    if (chatWaiting) add("buddy", "…", "typing");
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  chatPanel.querySelector(".close").addEventListener("click", closeChat);

  chatPanel.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text || chatWaiting) return;
    chatInput.value = "";
    chatWaiting = true;
    renderChat();
    // React to what was said while the reply is on its way.
    react(B.emotionForText(text), 3000);
    try {
      // The background script records both sides; the storage listener
      // below re-renders the log here and in every other tab.
      await api.runtime.sendMessage({ type: "chat", text });
    } catch {
      // Extension was reloaded; this page's script is orphaned.
    }
    chatWaiting = false;
    renderChat();
  });

  // Keep typing in the chat from triggering the website's own shortcuts.
  for (const type of ["keydown", "keyup", "keypress"]) {
    chatPanel.addEventListener(type, (e) => {
      e.stopPropagation();
      if (type === "keydown" && e.key === "Escape") closeChat();
    });
  }

  // --- Reactions to the user ----------------------------------------------

  function wake() {
    st.lastInput = Date.now();
    if (st.mode === "sleep") {
      setMode("idle", 1500);
      react("happy", 1500, pick(lines().wake));
    }
  }

  addEventListener("mousemove", (e) => {
    st.mouse = { x: e.clientX, y: e.clientY };
    wake();
  }, { passive: true });
  addEventListener("keydown", wake, { passive: true, capture: true });
  addEventListener("scroll", wake, { passive: true });

  document.addEventListener("copy", () => {
    if (!shouldShow()) return;
    react("encouragement", 2000, pick(lines().copy));
    tellApp("copy_paste");
  }, true);

  document.addEventListener("paste", () => {
    if (!shouldShow()) return;
    react("encouragement", 2000, pick(lines().paste));
    tellApp("copy_paste");
  }, true);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      st.hiddenAt = Date.now();
      stop();
      savePosition();
    } else if (shouldShow()) {
      if (st.hiddenAt && Date.now() - st.hiddenAt > WELCOME_AFTER_MS) {
        // A little sulk about being left alone, then happy to see you.
        react("sad", 1800, pick(lines().missed));
        setTimeout(() => react("happy", 1600, pick(lines().welcome)), 1800);
      }
      start();
    }
  });

  addEventListener("resize", clampToViewport);
  addEventListener("pagehide", savePosition);

  // --- Preferences & persistence -------------------------------------------

  function shouldShow() {
    return prefs.visible && !!prefs.character;
  }

  function savePrefs(next) {
    api.storage.local.set({ buddy: next });
  }

  function savePosition() {
    if (!shouldShow()) return;
    api.storage.local.set({
      buddyPos: { fx: st.x / innerWidth, fy: st.y / innerHeight },
    });
  }

  function apply(previous) {
    wrap.hidden = !shouldShow();
    picker.hidden = !prefs.visible || !!prefs.character;
    if (!shouldShow()) {
      stop();
      bubble.hidden = true;
      chatPanel.hidden = true;
      return;
    }
    preload(prefs.character);
    if (!chatPanel.hidden) {
      chatPanel.querySelector(".chat-title").textContent = `Chat with ${B.CHARACTERS[prefs.character].name}`;
      renderChat();
    }
    if (previous?.character !== prefs.character) react("encouragement", 1800, pick(lines().greet));
    if (document.visibilityState === "visible") start();
  }

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.chat) {
      chatHistory = changes.chat.newValue ?? [];
      if (!chatPanel.hidden) renderChat();
    }
    if (changes.lastFed) lastFed = changes.lastFed.newValue ?? Date.now();
    if (!changes.buddy) return;
    const previous = prefs;
    prefs = { character: null, visible: true, ...changes.buddy.newValue };
    apply(previous);
  });

  api.storage.local.get(["buddy", "buddyPos", "lastFed"]).then((data) => {
    prefs = { character: null, visible: true, ...data.buddy };
    if (data.lastFed) lastFed = data.lastFed;
    else api.storage.local.set({ lastFed });
    if (data.buddyPos) {
      st.x = data.buddyPos.fx * innerWidth;
      st.y = data.buddyPos.fy * innerHeight;
    }
    clampToViewport();
    setMode("idle", rand(1500, 4000));
    document.documentElement.append(host);
    // Only greet on first choice, not on every page load.
    apply(prefs);
  });
})();
