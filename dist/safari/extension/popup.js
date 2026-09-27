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

// Firefox and Safari may install the extension without access to websites,
// which keeps the buddy off every page and the Buddy app out of reach.
// Chrome grants it on install, so this stays hidden there.
const SITE_ACCESS = { origins: ["<all_urls>"] };
const access = document.getElementById("access");
const grant = document.getElementById("grant");
api.permissions?.contains(SITE_ACCESS).then((granted) => (access.hidden = granted), () => {});
grant.addEventListener("click", () => {
  // Must run straight from the click, or the browser refuses to ask.
  api.permissions.request(SITE_ACCESS).then((granted) => {
    if (!granted) return;
    document.getElementById("access-text").textContent = "Done! Reload your open tabs to see your buddy there.";
    grant.hidden = true;
  }, (err) => console.warn("Couldn't request site access", err));
});

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
