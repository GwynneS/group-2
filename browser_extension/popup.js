// Toolbar popup: choose cat girl or cat boy, and show/hide the buddy.
// The chosen buddy bounces happily; hovering a choice makes it cheer.

const api = globalThis.browser ?? globalThis.chrome;
const B = globalThis.BuddyCharacters;
const buttons = [...document.querySelectorAll(".choice")];
const visible = document.getElementById("visible");
const pets = document.getElementById("pets");

document.head.append(Object.assign(document.createElement("style"), { textContent: B.ANIMATION_CSS }));

let prefs = { character: null, visible: true };

function setPose(btn, emotion, active) {
  const img = btn.querySelector("img");
  const src = api.runtime.getURL(B.artPath(btn.dataset.char, emotion));
  if (img.src !== src) {
    img.src = src;
    const pose = img.parentElement;
    pose.classList.remove("pose-in");
    void pose.offsetWidth;
    pose.classList.add("pose-in");
  }
  img.className = `buddy-figure emo-${emotion}${active ? " react" : ""}`;
}

for (const btn of buttons) {
  const ch = B.CHARACTERS[btn.dataset.char];
  btn.querySelector(".name").textContent = ch.name;
  btn.querySelector("small").textContent = ch.label;
  btn.addEventListener("click", () => save({ ...prefs, character: btn.dataset.char, visible: true }));
  btn.addEventListener("mouseenter", () => setPose(btn, "encouragement", true));
  btn.addEventListener("mouseleave", render);
}
visible.addEventListener("change", () => save({ ...prefs, visible: visible.checked }));

function save(next) {
  prefs = next;
  api.storage.local.set({ buddy: next });
  render();
}

function render() {
  for (const btn of buttons) {
    const selected = btn.dataset.char === prefs.character;
    btn.setAttribute("aria-pressed", String(selected));
    setPose(btn, "happy", selected);
  }
  visible.checked = prefs.visible;
}

// Is the Buddy app (UI/server.py) running, and how is the buddy feeling?
const appStatus = document.getElementById("app-status");
api.runtime.sendMessage({ type: "appState" }).then((state) => {
  if (!state) {
    appStatus.textContent = "Buddy app isn't running. Start it with python3 UI/server.py for moods, needs and chat.";
    return;
  }
  const name = B.CHARACTERS[prefs.character ?? "girl"].name;
  appStatus.textContent = `${name} feels ${state.pet.mood}: ${state.message}`;
});

api.storage.local.get(["buddy", "pets"]).then(({ buddy, pets: count = 0 }) => {
  prefs = { character: null, visible: true, ...buddy };
  if (count) pets.textContent = `Headpats given: ${count}`;
  render();
});
