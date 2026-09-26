// Toolbar popup: choose cat girl or cat boy, and show/hide the buddy.

const api = globalThis.browser ?? globalThis.chrome;
const S = globalThis.BuddySprites;
const buttons = [...document.querySelectorAll(".choice")];
const visible = document.getElementById("visible");
const pets = document.getElementById("pets");

let prefs = { character: null, visible: true };

for (const btn of buttons) {
  const ch = S.CHARACTERS[btn.dataset.char];
  const canvas = btn.querySelector("canvas");
  canvas.width = S.W * S.SCALE;
  canvas.height = S.H * S.SCALE;
  // The canvas has room for the tail on the right; shift so the body is centered.
  canvas.style.transform = `translateX(${((S.W - S.BODY_W) / 2) * S.SCALE}px)`;
  btn.querySelector(".name").textContent = ch.name;
  btn.querySelector("small").textContent = ch.label;
  btn.addEventListener("click", () => save({ ...prefs, character: btn.dataset.char, visible: true }));
}
visible.addEventListener("change", () => save({ ...prefs, visible: visible.checked }));

function save(next) {
  prefs = next;
  api.storage.local.set({ buddy: next });
  render();
}

let tick = 0;
function render() {
  for (const btn of buttons) {
    const selected = btn.dataset.char === prefs.character;
    btn.setAttribute("aria-pressed", String(selected));
    S.draw(btn.querySelector("canvas").getContext("2d"), btn.dataset.char, {
      eyes: selected ? "happy" : "open",
      tail: selected ? tick % 2 : 0,
    });
  }
  visible.checked = prefs.visible;
}

setInterval(() => {
  tick++;
  render();
}, 300);

api.storage.local.get(["buddy", "pets"]).then(({ buddy, pets: count = 0 }) => {
  prefs = { character: null, visible: true, ...buddy };
  if (count) pets.textContent = `Headpats given: ${count}`;
  render();
});
