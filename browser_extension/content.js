// Runs on every website. Tracks activity while the page is in view and sends
// a session record to the background script whenever the user leaves the site:
// switching tabs, minimizing / leaving the browser window, navigating away,
// or closing the tab.
//
// While the page is in view it also sends a small heartbeat every few
// seconds (counts since the last heartbeat + host/title/scroll). The
// background script forwards heartbeats to the companion brain in the Buddy
// app so it knows what you're doing in the browser right now.
//
// Only aggregate counts and known shortcut names are sent — never typed text
// or clipboard contents. Shortcut events bypass the regular heartbeat delay.

(() => {
  const api = globalThis.browser ?? globalThis.chrome;

  const HEARTBEAT_MS = 5000;

  let session = newSession();
  let activeSince = isInView() ? Date.now() : null;
  let sent = zeroCounts();
  let lastInputAt = null;

  function newSession() {
    return {
      url: location.href,
      host: location.hostname,
      title: document.title,
      startedAt: Date.now(),
      activeMs: 0,
      clicks: 0,
      keys: 0,
      copies: 0,
      pastes: 0,
      undos: 0,
      maxScrollPct: 0,
    };
  }

  function zeroCounts() {
    return { activeMs: 0, clicks: 0, keys: 0, copies: 0, pastes: 0, undos: 0 };
  }

  function currentActiveMs() {
    return session.activeMs + (activeSince !== null ? Date.now() - activeSince : 0);
  }

  // Counts since the previous heartbeat. `left` tells the brain the user
  // just switched away from this page.
  function heartbeat(left = false) {
    const now = { ...session, activeMs: currentActiveMs() };
    const delta = {};
    for (const key of Object.keys(sent)) delta[key] = Math.max(0, now[key] - sent[key]);
    sent = { activeMs: now.activeMs, clicks: now.clicks, keys: now.keys, copies: now.copies, pastes: now.pastes, undos: now.undos };
    try {
      api.runtime.sendMessage({
        type: "heartbeat",
        data: {
          host: location.hostname,
          title: document.title,
          maxScrollPct: session.maxScrollPct,
          left,
          inputAgeMs: lastInputAt === null ? null : Math.max(0, performance.now() - lastInputAt),
          shortcutsImmediate: true,
          ...delta,
        },
      });
    } catch {
      // Extension was reloaded or disabled; the page's old script is orphaned.
    }
  }

  setInterval(() => {
    if (isInView()) heartbeat();
  }, HEARTBEAT_MS);

  function isInView() {
    return document.visibilityState === "visible" && document.hasFocus();
  }

  function pauseTimer() {
    if (activeSince !== null) {
      session.activeMs += Date.now() - activeSince;
      activeSince = null;
    }
  }

  function resumeTimer() {
    if (activeSince === null) activeSince = Date.now();
  }

  // Save the current session and start a fresh one. `reason` says why the
  // user left: "hidden", "blur", "navigate" or "close".
  function flush(reason) {
    pauseTimer();
    heartbeat(true);
    sent = zeroCounts();
    const hadActivity =
      session.activeMs > 0 || session.clicks || session.keys || session.copies || session.pastes;
    if (hadActivity) {
      const record = { ...session, title: document.title, endedAt: Date.now(), reason };
      try {
        api.runtime.sendMessage({ type: "session", record });
      } catch {
        // Extension was reloaded or disabled; the page's old script is orphaned.
      }
    }
    session = newSession();
  }

  // --- Leaving the site -----------------------------------------------------

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush("hidden");
    else if (isInView()) resumeTimer();
  });

  // Switching to another app keeps the tab "visible", so watch focus too.
  window.addEventListener("blur", () => {
    // Clicking into an iframe also blurs the window; that's not leaving.
    setTimeout(() => {
      if (!document.hasFocus() && !(document.activeElement instanceof HTMLIFrameElement)) {
        flush("blur");
      }
    }, 0);
  });
  window.addEventListener("focus", resumeTimer);

  // Navigating away or closing the tab. `persisted` means the page went into
  // the back/forward cache rather than being destroyed.
  window.addEventListener("pagehide", (e) => flush(e.persisted ? "navigate" : "close"));
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) {
      session = newSession();
      if (isInView()) resumeTimer();
    }
  });

  // Single-page apps change the URL without a pagehide; treat a new path as a
  // new session so records stay per page.
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      const stillHere = activeSince !== null;
      flush("navigate");
      lastUrl = location.href;
      if (stillHere) resumeTimer();
    }
  }, 1000);

  // --- Activity counters ----------------------------------------------------

  function noteInput(event) {
    if (!isInView() || event?.isTrusted === false) return false;
    lastInputAt = performance.now();
    return true;
  }

  const quickAt = {};
  function shortcut(name, event) {
    if (!noteInput(event) || event.repeat) return;
    const at = performance.now();
    if (at - (quickAt[name] ?? -Infinity) < 100) return; // keydown + clipboard event
    quickAt[name] = at;
    if (name === "undo") session.undos++;
    try {
      Promise.resolve(api.runtime.sendMessage({ type: "shortcut", shortcut: name })).catch(() => {});
    } catch {}
  }
  document.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.repeat) return;
    const name = { c: "copy", v: "paste", z: "undo" }[String(event.key).toLowerCase()];
    if (name) shortcut(name, event);
  }, true);
  document.addEventListener("copy", event => shortcut("copy", event), true);
  document.addEventListener("paste", event => shortcut("paste", event), true);

  // Read-only voice delivery also works when the floating buddy is hidden.
  // Only the focused page polls; no keyboard/mouse activity is invented.
  let voicePollPending = false;
  setInterval(async () => {
    if (!isInView() || voicePollPending) return;
    voicePollPending = true;
    try { await api.runtime.sendMessage({ type: "appState" }); }
    catch {} finally { voicePollPending = false; }
  }, 1000);

  for (const [type, counter] of Object.entries({ click: "clicks", keydown: "keys", copy: "copies", paste: "pastes" })) {
    document.addEventListener(type, (event) => {
      if (noteInput(event)) session[counter]++;
    }, true);
  }
  // Store only the time of movement, not mouse positions or typed text.
  document.addEventListener("pointermove", noteInput, { passive: true, capture: true });
  document.addEventListener("pointerdown", noteInput, { passive: true, capture: true });
  document.addEventListener("wheel", noteInput, { passive: true, capture: true });
  document.addEventListener("touchmove", noteInput, { passive: true, capture: true });
  document.addEventListener(
    "scroll",
    () => {
      const el = document.documentElement;
      const scrollable = el.scrollHeight - el.clientHeight;
      if (scrollable <= 0) return;
      const pct = Math.round((el.scrollTop / scrollable) * 100);
      if (pct > session.maxScrollPct) session.maxScrollPct = pct;
    },
    { passive: true, capture: true }
  );
})();
