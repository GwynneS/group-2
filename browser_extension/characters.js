// The two buddies and their emotion poses, shared by the on-page buddy,
// the popup, the background script and the Buddy app (UI/app.js).
//
// Art lives in art/<character>/<emotion>.png, cut from the sheets in
// art_source/ by art_source/slice_sheets.py.
//
// Each emotion has its own motion (ANIMATION_CSS below). A page shows a pose
// with this structure and toggles classes on it:
//
//   <div class="buddy-pose [pose-in]">                    pops when the pose changes
//     <img class="buddy-figure emo-<emotion> [react]">    loops while `react` is set

(() => {
  const EMOTIONS = ["happy", "sad", "angry", "tired", "hungry", "encouragement"];

  const CHARACTERS = {
    girl: { name: "Mochi", label: "Cat Girl" },
    boy: { name: "Kiko", label: "Cat Boy" },
  };

  const artPath = (character, emotion) => `art/${character}/${emotion}.png`;

  // Which pose to show in response to something the user typed.
  const TEXT_EMOTIONS = [
    ["tired", /\b(tired|sleepy|exhausted|sleep|nap|burn(ed|t)? ?out)\b/i],
    ["sad", /\b(sad|upset|lonely|cry|crying|bad day|depressed|miss)\b/i],
    ["angry", /\b(angry|mad|annoyed|frustrat\w*|hate|ugh+|argh+)\b/i],
    ["hungry", /\b(hungry|food|eat|eating|snack|lunch|dinner|breakfast|fish)\b/i],
    ["encouragement", /\b(done|finished|did it|passed|shipped|submitted|yay|win|won|help|stuck)\b/i],
  ];

  function emotionForText(text) {
    for (const [emotion, pattern] of TEXT_EMOTIONS) if (pattern.test(text)) return emotion;
    return "happy";
  }

  // Motion for each emotion. `react` loops the emotion's motion; without it,
  // the pose just holds (the page adds its own gentle float).
  const ANIMATION_CSS = `
    .buddy-pose { transform-origin: 50% 100%; }
    .buddy-pose.pose-in { animation: buddy-pop 260ms ease-out; }
    .buddy-figure { display: block; transform-origin: 50% 100%; user-select: none; -webkit-user-drag: none; }

    .buddy-figure.react.emo-happy { animation: buddy-bounce 700ms ease-in-out infinite; }
    .buddy-figure.react.emo-encouragement { animation: buddy-cheer 600ms ease-out, buddy-hop 800ms ease-in-out 600ms infinite; }
    .buddy-figure.react.emo-angry { animation: buddy-shake 260ms linear infinite; }
    .buddy-figure.react.emo-hungry { animation: buddy-wiggle 900ms ease-in-out infinite; }
    .buddy-figure.emo-sad { animation: buddy-droop 2400ms ease-in-out infinite; }
    .buddy-figure.emo-tired { animation: buddy-breathe 3200ms ease-in-out infinite; }
    .buddy-figure.emo-hungry { animation: buddy-wiggle 2400ms ease-in-out infinite; }

    @keyframes buddy-pop { 0% { transform: scale(0.86); } 70% { transform: scale(1.06); } 100% { transform: scale(1); } }
    @keyframes buddy-bounce {
      0%, 100% { transform: translateY(0) scale(1, 1); }
      30% { transform: translateY(-10px) scale(0.96, 1.04); }
      60% { transform: translateY(0) scale(1.04, 0.96); }
    }
    @keyframes buddy-cheer { 0% { transform: scale(0.8); } 60% { transform: translateY(-12px) scale(1.12); } 100% { transform: scale(1); } }
    @keyframes buddy-hop { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
    @keyframes buddy-shake {
      0%, 100% { transform: translateX(0) rotate(0); }
      25% { transform: translateX(-4px) rotate(-1.5deg); }
      75% { transform: translateX(4px) rotate(1.5deg); }
    }
    @keyframes buddy-wiggle { 0%, 100% { transform: rotate(0); } 25% { transform: rotate(-3deg); } 75% { transform: rotate(3deg); } }
    @keyframes buddy-droop { 0%, 100% { transform: translateY(0) rotate(0); } 50% { transform: translateY(3px) rotate(-2deg); } }
    @keyframes buddy-breathe { 0%, 100% { transform: scale(1, 1); } 50% { transform: scale(1.02, 0.96); } }

    @media (prefers-reduced-motion: reduce) {
      .buddy-pose, .buddy-figure { animation: none !important; }
    }
  `;

  globalThis.BuddyCharacters = { CHARACTERS, EMOTIONS, artPath, emotionForText, ANIMATION_CSS };
})();
