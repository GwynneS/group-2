// Buddy stage: shows the chosen buddy's current emotion in the "Your Buddy"
// panel, using the character art from browser_extension/art.
//
// Two things decide what's shown:
//
//   1. The Python companion. /api/state (from UI/server.py's companion hub,
//      or from animation_bridge.py) reports the brain's animation (lounging,
//      happy, sad, tired, angry, hungry, encouragement) and a message. That is
//      the resting pose. The full state also goes to BuddyStage.onState
//      listeners (app.js shows needs, mood, camera). If there's no /api/state,
//      polling stops and app.js sets the resting pose itself.
//
//   2. The user. app.js calls BuddyStage.react() for headpats, pokes, chat,
//      feeding and so on, which plays that emotion's animation for a moment
//      on top of the resting pose.

(() => {
  const B = globalThis.BuddyCharacters;
  const figure = document.querySelector("#buddy-figure");
  const pose = figure?.parentElement;
  const poke = document.querySelector("#buddy-poke");
  const caption = document.querySelector("#animation-caption");
  if (!B || !figure) return;

  document.head.append(Object.assign(document.createElement("style"), { textContent: B.ANIMATION_CSS }));

  const ART_SCALE = 0.5; // art is drawn at 2x for sharp screens

  const validStates = new Set(["lounging", ...B.EMOTIONS]);
  const labels = {
    lounging: "Lounging",
    happy: "Happy",
    sad: "Sad",
    tired: "Tired",
    angry: "Angry",
    hungry: "Hungry",
    encouragement: "You got this!",
  };

  let character = "girl";
  let python = null; // { animation, message } from the Python companion
  let resting = "lounging"; // set by app.js when there's no Python companion
  let defaultCaption = "";
  let reaction = null; // { emotion, message, until }
  let reactionTimer = 0;
  const stateListeners = [];

  figure.addEventListener("load", () => {
    figure.style.width = `${figure.naturalWidth * ART_SCALE}px`;
  });

  function render() {
    const reacting = reaction && performance.now() < reaction.until;
    const state = reacting ? reaction.emotion : python?.animation ?? resting;
    // "lounging" has no pose of its own: it's the calm, happy resting pose.
    const emotion = state === "lounging" ? "happy" : state;
    const src = `/extension/${B.artPath(character, emotion)}`;

    if (figure.getAttribute("src") !== src) {
      figure.src = src;
      pose.classList.remove("pose-in");
      void pose.offsetWidth;
      pose.classList.add("pose-in");
    }
    figure.className = `buddy-figure emo-${emotion}${reacting ? " react" : ""}`;
    poke.classList.toggle("floating", state === "lounging");

    caption.textContent = reacting && reaction.message
      ? reaction.message
      : python?.message ?? defaultCaption;
    poke.setAttribute(
      "aria-label",
      `${B.CHARACTERS[character].name}, ${labels[state].toLowerCase()}. Click to give a headpat.`
    );
  }

  let polling = true;
  async function readPythonState() {
    if (!polling) return;
    try {
      const response = await fetch("/api/state", { cache: "no-store" });
      if (response.status === 404) {
        polling = false; // served by UI/server.py: no Python companion here
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      if (validStates.has(data.animation)) {
        python = { animation: data.animation, message: data.message || labels[data.animation] };
        render();
        for (const fn of stateListeners) fn(data);
      }
    } catch {
      if (python) {
        python = null;
        render();
        for (const fn of stateListeners) fn(null);
      }
    }
  }

  globalThis.BuddyStage = {
    setCharacter(next) {
      character = next;
      for (const emotion of B.EMOTIONS) new Image().src = `/extension/${B.artPath(next, emotion)}`;
      render();
    },
    // Play `emotion` for `ms`, optionally with a caption, then settle back.
    react(emotion, ms, message) {
      reaction = { emotion, message, until: performance.now() + ms };
      clearTimeout(reactionTimer);
      reactionTimer = setTimeout(render, ms);
      render();
    },
    isReacting(emotion) {
      return !!reaction && reaction.emotion === emotion && performance.now() < reaction.until;
    },
    setResting(state) {
      if (!validStates.has(state) || state === resting) return;
      resting = state;
      render();
    },
    // Called with the companion's full state on every poll (null if it stops answering).
    onState(fn) {
      stateListeners.push(fn);
    },
    setDefaultCaption(text) {
      defaultCaption = text;
      render();
    },
  };

  render();
  readPythonState();
  setInterval(readPythonState, 300);
})();
