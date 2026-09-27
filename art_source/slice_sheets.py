"""Cut the character sheets into one transparent PNG per emotion.

Each sheet is a 3 x 2 grid of poses on a black background, with a purple
label under each pose:

    happy   sad     angry
    tired   hungry  encouragement

Output: browser_extension/art/<girl|boy>/<emotion>.png, scaled so both
characters stand the same height (measured on the standing "angry" pose),
and browser_extension/icons/icon-<size>.png, the extension's store and
toolbar icons.

    pip install pillow
    python3 art_source/slice_sheets.py            # art + icons
    python3 art_source/slice_sheets.py --icons    # icons only, from the existing art
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "browser_extension" / "art"
ICONS = ROOT.parent / "browser_extension" / "icons"
ICON_SIZES = (16, 32, 48, 128)
ICON_POSE = ("girl", "happy")  # background.js swaps in the chosen buddy at runtime

SHEETS = {"girl": ROOT / "cat_girl_sheet.png", "boy": ROOT / "cat_boy_sheet.png"}
GRID = [["happy", "sad", "angry"], ["tired", "hungry", "encouragement"]]

BG_EDGE = 14        # flood-fill from the border through pixels this dark
BG_ENCLOSED = 5     # enclosed pockets this dark (gaps under arms, tails) are background too
MIN_POCKET = 40     # ...if at least this many pixels
TARGET_HEIGHT = 260 # px height of the standing pose after scaling
PAD = 4
MIN_SPECK = 80      # opaque specks smaller than this are dropped...
THIN_LINE = 4       # ...and so are hairline slivers of neighbouring labels, this thin or thinner,
EDGE_SCRAP = 1000   # ...and bits of a neighbouring pose cut off at the cell's side edge


def is_label_pixel(p: tuple[int, int, int]) -> bool:
    r, g, b = p
    return b > 150 and 70 < r < 170 and g < 100


def remove_background(cell: Image.Image) -> Image.Image:
    rgb = cell.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    dark = [[max(px[x, y]) for x in range(w)] for y in range(h)]
    clear = [[False] * w for _ in range(h)]

    def fill(seeds, limit, min_size=0):
        for sx, sy in seeds:
            if clear[sy][sx] or dark[sy][sx] > limit:
                continue
            region, queue = [], deque([(sx, sy)])
            seen = {(sx, sy)}
            while queue:
                x, y = queue.popleft()
                region.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen \
                            and not clear[ny][nx] and dark[ny][nx] <= limit:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(region) >= min_size:
                for x, y in region:
                    clear[y][x] = True

    border = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] \
        + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    fill(border, BG_EDGE)
    fill([(x, y) for y in range(h) for x in range(w)], BG_ENCLOSED, MIN_POCKET)

    out = cell.convert("RGBA")
    opx = out.load()
    for y in range(h):
        for x in range(w):
            if clear[y][x]:
                opx[x, y] = (0, 0, 0, 0)
    return out


def cut_labels(cell: Image.Image) -> Image.Image:
    """Drop the purple name label at the bottom of the cell, and any sliver of
    the label above that spills over the top edge of a second-row cell."""
    rgb = cell.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    ratio = [sum(is_label_pixel(px[x, y]) for x in range(w)) / w for y in range(h)]

    # Top: skip rows touched by the label above, then the black gap after them.
    top = 0
    while top < h // 4 and ratio[top] > 0.02:
        top += 1

    # Bottom: find the label's solid bar, then climb past its text rows until
    # reaching the black gap between the label and the figure.
    bottom = h
    y = h - 1
    while y > h // 2 and ratio[y] <= 0.35:
        y -= 1
    if y > h // 2:
        while y > 0 and ratio[y] > 0.02:
            y -= 1
        bottom = max(y - 1, top + 1)
    return cell.crop((0, top, w, bottom))


def drop_specks(img: Image.Image) -> Image.Image:
    """Clear tiny blobs and hairline slivers left over from cell edges."""
    w, h = img.size
    px = img.load()
    seen = [[False] * w for _ in range(h)]
    for sy in range(h):
        for sx in range(w):
            if seen[sy][sx] or px[sx, sy][3] == 0:
                continue
            region, queue = [], deque([(sx, sy)])
            seen[sy][sx] = True
            while queue:
                x, y = queue.popleft()
                region.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and px[nx, ny][3]:
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            xs = [x for x, _ in region]
            ys = [y for _, y in region]
            thin = min(max(xs) - min(xs), max(ys) - min(ys)) < THIN_LINE
            edge_scrap = (min(xs) == 0 or max(xs) == w - 1) and len(region) < EDGE_SCRAP
            if len(region) < MIN_SPECK or thin or edge_scrap:
                for x, y in region:
                    px[x, y] = (0, 0, 0, 0)
    return img


def slice_sheet(path: Path) -> dict[str, Image.Image]:
    sheet = Image.open(path)
    w, h = sheet.size
    poses = {}
    for row, names in enumerate(GRID):
        for col, name in enumerate(names):
            box = (col * w // 3, row * h // 2, (col + 1) * w // 3, (row + 1) * h // 2)
            cell = drop_specks(remove_background(cut_labels(sheet.crop(box))))
            poses[name] = cell.crop(cell.getbbox())
    return poses


def make_icons() -> None:
    """Crop the default buddy to her head, the same crop background.js uses
    for the live toolbar icon, so it stays readable at 16px."""
    char, emotion = ICON_POSE
    art = Image.open(OUT / char / f"{emotion}.png").convert("RGBA")
    side = min(art.width, round(art.height * 0.62))
    left = (art.width - side) // 2
    head = art.crop((left, 0, left + side, side))
    ICONS.mkdir(parents=True, exist_ok=True)
    for size in ICON_SIZES:
        dest = ICONS / f"icon-{size}.png"
        head.resize((size, size), Image.LANCZOS).save(dest, optimize=True)
        print(f"{dest.relative_to(ROOT.parent)}  {size}x{size}")


def main() -> None:
    if "--icons" in sys.argv:
        make_icons()
        return
    for char, path in SHEETS.items():
        poses = slice_sheet(path)
        scale = TARGET_HEIGHT / poses["angry"].height
        (OUT / char).mkdir(parents=True, exist_ok=True)
        for name, img in poses.items():
            size = (round(img.width * scale), round(img.height * scale))
            small = img.resize(size, Image.LANCZOS)
            framed = Image.new("RGBA", (size[0] + PAD * 2, size[1] + PAD * 2))
            framed.paste(small, (PAD, PAD))
            dest = OUT / char / f"{name}.png"
            framed.save(dest, optimize=True)
            print(f"{dest.relative_to(ROOT.parent)}  {framed.size[0]}x{framed.size[1]}")
    make_icons()


if __name__ == "__main__":
    main()
