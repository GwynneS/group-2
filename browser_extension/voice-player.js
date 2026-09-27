// A single audio element in an extension page. Chromium loads this in its
// offscreen document; Firefox can use its existing background page.
(() => {
  let audio;
  let generation = 0;
  globalThis.BuddyAudio = {
    async play({ url, interrupt = false }) {
      const parsed = new URL(url);
      if (parsed.origin !== "http://127.0.0.1:8765" || !/^\/voice\/[A-Za-z0-9]+\.mp3$/.test(parsed.pathname)) {
        throw new Error("Invalid Buddy voice clip");
      }
      audio ??= new Audio();
      if (!interrupt && !audio.paused && !audio.ended) return { played: false, reason: "busy" };
      const own = ++generation;
      audio.pause();
      audio.src = parsed.href;
      let timeout;
      try {
        await Promise.race([audio.play(), new Promise((_, reject) => {
          timeout = setTimeout(() => reject(new Error("Buddy audio startup timed out")), 3000);
        })]);
      } catch (error) {
        if (own === generation) { audio.pause(); audio.removeAttribute("src"); }
        throw error;
      } finally { clearTimeout(timeout); }
      return { played: own === generation, duration: Number.isFinite(audio.duration) ? audio.duration : null };
    },
    stop() {
      generation++;
      audio?.pause();
      if (audio) audio.removeAttribute("src");
      return { stopped: true };
    },
  };
})();
