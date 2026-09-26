// The on-page buddy: a pixel cat girl or cat boy that drifts around the
// browser window, follows the cursor now and then, reacts to copy/paste,
// can be petted (click) or moved (drag), and falls asleep when you're idle.
//
// Preference lives in storage.local under `buddy`:
//   { character: "girl" | "boy" | null, visible: boolean }
// Changing it anywhere (popup, right-click menu, first-run picker) updates
// every open tab live.

(() => {
  if (window.top !== window || !document.documentElement) return;

  const api = globalThis.browser ?? globalThis.chrome;
  const S = globalThis.BuddySprites;

  const SCALE = S.SCALE;
  const BW = S.W * SCALE;
  const BH = S.H * SCALE;
  const EDGE = 8;
  const TOP_ROOM = 60; // keep space above for the speech bubble
  const SLEEP_AFTER_MS = 90_000;
  const WELCOME_AFTER_MS = 60_000;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const LINES = {
    girl: {
      greet: ["Hi hi! I'm Mochi~", "Mochi's here! Let's do our best!"],
      pet: ["Nya~ ♥", "Hehe, that tickles!", "Purrr...", "More headpats please!"],
      copy: ["Ooh, copied! Nice find~", "Got it saved, nya!"],
      paste: ["Pasted! You're on a roll~", "Paste-tastic!"],
      welcome: ["Welcome back! I missed you~", "Yay, you're back!"],
      wake: ["Mm? Oh! I'm awake, I'm awake!", "*yawn* ...morning~"],
      idle: ["You're doing great!", "Remember to drink water~", "Focus mode: activated!", "Nya~"],
    },
    boy: {
      greet: ["Hey! I'm Kiko. Let's get stuff done.", "Kiko reporting for duty!"],
      pet: ["H-hey! ...okay, that's nice.", "Mrrp. Thanks.", "Purr... don't tell anyone."],
      copy: ["Copied. Smart move.", "Nice grab!"],
      paste: ["Pasted! Keep it up.", "And... pasted. Nice."],
      welcome: ["Welcome back! Ready to go?", "There you are!"],
      wake: ["Huh? I wasn't sleeping.", "*stretch* ...okay, I'm up."],
      idle: ["You've got this.", "Stretch break soon?", "Solid work so far.", "Mrrp."],
    },
  };

  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

  let prefs = { character: null, visible: true };

  // --- DOM (inside a shadow root so page CSS can't touch it) ---------------

  const host = document.createElement("div");
  host.style.cssText =
    "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      [hidden] { display: none !important; }
      * { box-sizing: border-box; font-family: "Press Start 2P", "VT323", ui-monospace, "Courier New", monospace; }
      .wrap { position: fixed; left: 0; top: 0; width: ${BW}px; height: ${BH}px; pointer-events: none; will-change: transform; }
      canvas {
        width: ${BW}px; height: ${BH}px; image-rendering: pixelated;
        pointer-events: auto; cursor: grab; touch-action: none;
        filter: drop-shadow(3px 3px 0 rgba(43, 25, 64, 0.25));
      }
      canvas.dragging { cursor: grabbing; }
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
        position: absolute; color: #f06a9b; font-size: 14px; pointer-events: none;
        text-shadow: 1px 1px 0 #2b1940; animation: rise 900ms steps(6, end) forwards;
      }
      @keyframes rise { to { transform: translateY(-40px); opacity: 0; } }

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

      .picker { right: 16px; bottom: 16px; padding: 14px; width: 260px; }
      .picker h2 { margin: 0 0 10px; font-size: 10px; line-height: 1.6; text-transform: uppercase; }
      .picker .choices { display: flex; gap: 10px; }
      .picker button {
        flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px;
        padding: 8px 4px; background: #eee0ff; border: 2px solid #392452;
      }
      .picker button:hover, .picker button:focus-visible { background: #d8b8f2; }
      .picker canvas {
        width: ${BW}px; height: ${BH}px; cursor: pointer; filter: none; pointer-events: none;
        /* center the body; the canvas has extra room on the right for the tail */
        transform: translateX(${((S.W - S.BODY_W) / 2) * SCALE}px);
      }
      .picker p { margin: 10px 0 0; font-size: 8px; line-height: 1.6; color: #715d88; }
    </style>
    <div class="wrap" hidden>
      <div class="bubble" hidden></div>
      <canvas width="${BW}" height="${BH}" aria-label="Buddy"></canvas>
    </div>
    <div class="menu" hidden></div>
    <div class="picker" hidden>
      <h2>Pick your buddy!</h2>
      <div class="choices">
        <button data-char="girl"><canvas width="${BW}" height="${BH}"></canvas>${S.CHARACTERS.girl.label}</button>
        <button data-char="boy"><canvas width="${BW}" height="${BH}"></canvas>${S.CHARACTERS.boy.label}</button>
      </div>
      <p>You can switch any time: right-click your buddy or use the toolbar icon.</p>
    </div>
  `;

  const wrap = root.querySelector(".wrap");
  const canvas = wrap.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const bubble = root.querySelector(".bubble");
  const menu = root.querySelector(".menu");
  const picker = root.querySelector(".picker");

  for (const btn of picker.querySelectorAll("button")) {
    S.draw(btn.querySelector("canvas").getContext("2d"), btn.dataset.char, {}, SCALE);
    btn.addEventListener("click", () => savePrefs({ character: btn.dataset.char, visible: true }));
  }

  // --- State ---------------------------------------------------------------

  const st = {
    x: innerWidth - BW - 40,
    y: innerHeight - BH - 40,
    tx: 0,
    ty: 0,
    mode: "idle", // idle | wander | follow | sleep
    modeUntil: 0,
    facingLeft: false,
    nextBlink: 0,
    blinkUntil: 0,
    happyUntil: 0,
    lastInput: Date.now(),
    hiddenAt: 0,
    mouse: null,
  };
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

  function update(now, dt) {
    if (drag) return false;

    if (st.mode !== "sleep" && Date.now() - st.lastInput > SLEEP_AFTER_MS) {
      setMode("sleep");
      say("Zzz...", 0);
    }

    let moving = false;
    switch (st.mode) {
      case "idle":
        if (now > st.modeUntil) pickNextMove();
        break;
      case "wander":
        moving = !moveToward(st.tx, st.ty, 60, dt);
        if (!moving || now > st.modeUntil) {
          setMode("idle", rand(2500, 7000));
          if (Math.random() < 0.15) say(pick(lines().idle));
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
    }
    clampToViewport();
    return moving;
  }

  function render(now, moving) {
    if (!prefs.character) return;
    const sleeping = st.mode === "sleep";
    const happy = now < st.happyUntil;

    if (now > st.nextBlink) {
      st.blinkUntil = now + 150;
      st.nextBlink = now + rand(2500, 6000);
    }
    const eyes = sleeping || now < st.blinkUntil ? "closed" : happy ? "happy" : "open";
    const tail = sleeping ? 0 : Math.floor(now / (happy ? 150 : 450)) % 2;
    const step = moving ? 1 + (Math.floor(now / 180) % 2) : 0;

    S.draw(ctx, prefs.character, { eyes, tail, step }, SCALE, st.facingLeft);

    // Gentle hover bob; slower and smaller while asleep.
    const bob = reduceMotion ? 0 : Math.sin(now / (sleeping ? 900 : 380)) * (sleeping ? 1.5 : 3);
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
  }

  function stop() {
    running = false;
  }

  // --- Interaction: pet (click), move (drag), menu (right-click) -----------

  let drag = null;

  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    canvas.setPointerCapture(e.pointerId);
    drag = { sx: e.clientX, sy: e.clientY, ox: st.x, oy: st.y, moved: false };
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx;
    const dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true;
    canvas.classList.add("dragging");
    st.x = drag.ox + dx;
    st.y = drag.oy + dy;
    clampToViewport();
    render(performance.now(), false);
  });

  canvas.addEventListener("pointerup", () => {
    if (!drag) return;
    const wasDrag = drag.moved;
    drag = null;
    canvas.classList.remove("dragging");
    wake();
    if (wasDrag) {
      setMode("idle", 8000);
      savePosition();
    } else {
      pet();
    }
  });

  canvas.addEventListener("pointercancel", () => {
    drag = null;
    canvas.classList.remove("dragging");
  });

  function pet() {
    const now = performance.now();
    st.happyUntil = now + 1500;
    setMode("idle", 3000);
    say(pick(lines().pet), 2200);
    for (let i = 0; i < 3; i++) {
      const heart = document.createElement("span");
      heart.className = "heart";
      heart.textContent = "♥";
      heart.style.left = `${rand(10, BW - 20)}px`;
      heart.style.top = `${rand(0, 30)}px`;
      heart.style.animationDelay = `${i * 120}ms`;
      wrap.append(heart);
      setTimeout(() => heart.remove(), 900 + i * 120);
    }
    try {
      api.runtime.sendMessage({ type: "pet", character: prefs.character });
    } catch {}
  }

  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    const other = prefs.character === "girl" ? "boy" : "girl";
    const o = S.CHARACTERS[other];
    menu.innerHTML = "";
    const items = [
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
    menu.style.top = `${clamp(e.clientY, 8, innerHeight - 90)}px`;
  });

  addEventListener("pointerdown", (e) => {
    // The shadow root is closed, so from out here the path stops at `host`.
    if (!menu.hidden && !e.composedPath().includes(host)) menu.hidden = true;
  }, true);

  // --- Reactions to the user ----------------------------------------------

  function wake() {
    st.lastInput = Date.now();
    if (st.mode === "sleep") {
      setMode("idle", 1500);
      say(pick(lines().wake), 2500);
    }
  }

  addEventListener("mousemove", (e) => {
    st.mouse = { x: e.clientX, y: e.clientY };
    wake();
  }, { passive: true });
  addEventListener("keydown", wake, { passive: true, capture: true });
  addEventListener("scroll", wake, { passive: true });

  document.addEventListener("copy", () => {
    if (!prefs.character) return;
    st.happyUntil = performance.now() + 1200;
    say(pick(lines().copy), 2200);
  }, true);

  document.addEventListener("paste", () => {
    if (!prefs.character) return;
    st.happyUntil = performance.now() + 1200;
    say(pick(lines().paste), 2200);
  }, true);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      st.hiddenAt = Date.now();
      stop();
      savePosition();
    } else if (shouldShow()) {
      if (st.hiddenAt && Date.now() - st.hiddenAt > WELCOME_AFTER_MS) {
        say(pick(lines().welcome));
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
      return;
    }
    if (previous?.character !== prefs.character) say(pick(lines().greet));
    if (document.visibilityState === "visible") start();
  }

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes.buddy) return;
    const previous = prefs;
    prefs = { character: null, visible: true, ...changes.buddy.newValue };
    apply(previous);
  });

  api.storage.local.get(["buddy", "buddyPos"]).then(({ buddy, buddyPos }) => {
    prefs = { character: null, visible: true, ...buddy };
    if (buddyPos) {
      st.x = buddyPos.fx * innerWidth;
      st.y = buddyPos.fy * innerHeight;
    }
    clampToViewport();
    setMode("idle", rand(1500, 4000));
    document.documentElement.append(host);
    // Only greet on first choice, not on every page load.
    apply(prefs);
  });
})();
