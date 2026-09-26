// Anime-style pixel sprites for the buddy, drawn as text grids so the
// extension needs no image files. Shared by the content script, popup and
// background script.
//
// Each character's body is drawn as its LEFT half (13 columns) and mirrored,
// giving a symmetric 26-column body. The tail and asymmetric details (hair
// bow, ahoge) are added on top. The canvas is 32 x 44 so the tail has room
// on the right.
//
// Palette keys:
//   .  transparent        o  outline            h/H/l  hair / shade / shine
//   e  inner ear          s/S  skin / shade     k  lashes & eye line
//   I/i/j  iris dark / mid / light              w  eye highlight
//   b  blush              m  mouth              c/C  top / shade
//   a  collar / strings   r  ribbon             p/P  skirt or shorts / shade
//   f  shoes

(() => {
  const W = 32;
  const H = 44;
  const SCALE = 2; // default on-screen pixel size

  const common = {
    o: "#2b1940", k: "#2b1940", w: "#ffffff",
    s: "#ffe6d5", S: "#f3c3ad", e: "#ffb3cf",
    b: "#f9a3b8", m: "#b0476a", f: "#2b1940",
  };

  const CHARACTERS = {
    girl: {
      name: "Mochi",
      label: "Cat Girl",
      palette: {
        ...common,
        h: "#f7a8cf", H: "#d9749f", l: "#ffe0ef",
        I: "#4b2a7a", i: "#8a5cc7", j: "#c9a6f0",
        c: "#f7f2ff", C: "#d6c6ef", a: "#4a3a8c", r: "#e0457b",
        p: "#4a3a8c", P: "#352a6b",
      },
      half: [
        "..o..........",
        "..oo.........",
        "..oeo........",
        "..oeeo...oooo",
        "..oeeehooohhh",
        ".oheeehhhhhhh",
        ".ohhhhhhhhhll",
        "ohhhhhhhhllhh",
        "ohhhhhhllhhhh",
        "ohhhhllhhhhhh",
        "ohhhhhhhhhhhh",
        "ohhhHhhhhHhhh",
        "ohhHhHhhHhHhh",
        "ohhHSHhHSSHhH",
        "ohHSSSHSSSSHS",
        "ohhssssssssss",
        "ohhskkkkkksss",
        "ohhkkwwIIksss",
        "ohhskwIIIksss",
        "ohhskiiiiksss",
        "ohhskjjwiksss",
        "ohhsskkkkssss",
        "ohhsbbbssssss",
        "ohhssssssssms",
        "ohhhssssssssm",
        "ohhhhosssssss",
        "ohhhhhoosssss",
        "ohhhhhhhoooss",
        "ohhhhoaaaaaar",
        "ohhhocaaaarrr",
        "ohhhoccaaaacr",
        "ohhhocccccccc",
        ".ohhocccccccc",
        "..ohocccccccc",
        "..opppPppPppP",
        ".opppPppPppPp",
        ".opPppPppPppP",
        ".oooooooooooo",
        ".......osso..",
        ".......osso..",
        ".......osso..",
        ".......osso..",
        "......offfo..",
        "......ooooo..",
      ],
      legTop: 38,
      eyes: { row: 16, col: 3 },
      // Hair bow over the right ear.
      extras: [
        { x: 18, y: 4, rows: ["oo...oo", "oroooro", "orrorro", "oroooro", "oo...oo"] },
      ],
    },
    boy: {
      name: "Kiko",
      label: "Cat Boy",
      palette: {
        ...common,
        h: "#5b4a9e", H: "#3d2f75", l: "#8f7fd0",
        I: "#1f6b4a", i: "#3faa74", j: "#9be0b5",
        c: "#c6ed78", C: "#9cc756", a: "#fff8df",
        p: "#43245e", P: "#43245e",
      },
      half: [
        "..o..........",
        "..oo.........",
        "..oeo........",
        "..oeeo...oooo",
        "..oeeehooohhh",
        ".oheeehhhhhhh",
        ".ohhhhhhhhhll",
        "ohhhhhhhhllhh",
        "ohhhhhhllhhhh",
        "ohhhhllhhhhhh",
        "ohhhhhhhhhhhh",
        "ohhHhhhHhhhHh",
        "ohHhhhHhhhHhh",
        "ohHShHSHhHSHh",
        "ohSSSHSSSHSSS",
        "ohsssssssssss",
        "ohssskkkkksss",
        "ohsskkwIIksss",
        "ohssskwIiksss",
        "ohssskiiiksss",
        "ohssskjjjksss",
        "ohsssskkkssss",
        "ohssbbsssssss",
        "ohsssssssssms",
        ".ohsssssssssm",
        "..ohsssssssss",
        "...oossssssss",
        "......oooosss",
        "..occcccccCss",
        ".occcccccCCCC",
        ".occcccccccac",
        ".occoccccccac",
        ".occocccccccc",
        ".occocccccccc",
        ".ossoCCCCCCCC",
        "..ooopppppppp",
        "....oppppppo.",
        "....opppppo..",
        ".......osso..",
        ".......osso..",
        ".......osso..",
        ".......osso..",
        "......offfo..",
        "......ooooo..",
      ],
      legTop: 38,
      eyes: { row: 16, col: 3 },
      // Ahoge: the single stray lock of hair sticking up.
      extras: [{ x: 13, y: 0, rows: ["..oo", ".oho", "oho.", "oo.."] }],
    },
  };

  // Tail frames (two for wagging), drawn behind the body at (TAIL_X, TAIL_Y).
  const TAILS = [
    [
      "......ooo.",
      ".....ohllo",
      ".....ohhho",
      "......ohho",
      ".....ohho.",
      "....ohho..",
      "...ohho...",
      "..ohho....",
      ".ohho.....",
      "ohho......",
      "oho.......",
      "oo........",
    ],
    [
      "...ooo....",
      "..ollho...",
      "..ohhho...",
      "...ohho...",
      "....ohho..",
      "....ohho..",
      "...ohho...",
      "..ohho....",
      ".ohho.....",
      "ohho......",
      "oho.......",
      "oo........",
    ],
  ];
  const TAIL_X = 22;
  const TAIL_Y = 24;

  // Eye variants, 7 wide x 6 tall, written into the left half (mirrored).
  const EYES = {
    open: null, // as drawn
    closed: ["sssssss", "sssssss", "sssssss", "kssssss", "skkkkks", "sssssss"],
    happy: ["sssssss", "ssskkss", "sskssks", "skssssk", "sssssss", "sssssss"],
  };

  function mirror(half) {
    return half.map((row) => row + [...row].reverse().join(""));
  }

  function stamp(grid, x, y, rows) {
    rows.forEach((row, dy) => {
      [...row].forEach((px, dx) => {
        if (px !== ".") grid[y + dy][x + dx] = px;
      });
    });
  }

  // Build a W x H grid of palette keys for a pose.
  // pose: { eyes: "open"|"closed"|"happy", tail: 0|1, step: 0|1|2 }
  //   step 0 = standing, 1 = left leg lifted, 2 = right leg lifted
  function buildGrid(charKey, pose = {}) {
    const ch = CHARACTERS[charKey];
    const half = ch.half.map((r) => [...r]);
    const bodyW = half[0].length * 2;

    const eyeRows = EYES[pose.eyes ?? "open"];
    if (eyeRows) {
      eyeRows.forEach((row, dy) => {
        [...row].forEach((px, dx) => (half[ch.eyes.row + dy][ch.eyes.col + dx] = px));
      });
    }

    const grid = Array.from({ length: H }, () => Array(W).fill("."));
    stamp(grid, TAIL_X, TAIL_Y, TAILS[pose.tail ?? 0]);
    stamp(grid, 0, 0, mirror(half.map((r) => r.join(""))));

    // Walking: lift one leg by a pixel.
    const step = pose.step ?? 0;
    if (step) {
      const [x0, x1] = step === 1 ? [0, bodyW / 2] : [bodyW / 2, bodyW];
      for (let y = ch.legTop; y < H - 1; y++) {
        for (let x = x0; x < x1; x++) grid[y][x] = grid[y + 1][x];
      }
    }

    for (const { x, y, rows } of ch.extras) stamp(grid, x, y, rows);

    return grid;
  }

  // Draw a pose onto a 2D canvas context at the given pixel scale.
  // flip mirrors the whole sprite so the buddy can face left.
  function draw(ctx, charKey, pose = {}, scale = SCALE, flip = false) {
    const pal = CHARACTERS[charKey].palette;
    const grid = buildGrid(charKey, pose);
    ctx.clearRect(0, 0, W * scale, H * scale);
    grid.forEach((row, y) => {
      row.forEach((px, x) => {
        if (px === ".") return;
        ctx.fillStyle = pal[px];
        const dx = flip ? W - 1 - x : x;
        ctx.fillRect(dx * scale, y * scale, scale, scale);
      });
    });
  }

  // Width of the body without the tail, for centering the character.
  const BODY_W = CHARACTERS.girl.half[0].length * 2;

  globalThis.BuddySprites = { W, H, SCALE, BODY_W, CHARACTERS, buildGrid, draw };
})();
