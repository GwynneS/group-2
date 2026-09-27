# This project is based on the idea of a Fem Boy AI Buddy

# This AI will praise you and support you on your productive tasks

# Particular response on command V
# Particular response on command C
# You cant pet the cat girl or femboy and it boosts the "happiness" bar


## Running the Buddy app

```bash
pip install -r requirements.txt   # optional extras; see below
python3 UI/server.py              # add --camera to start body tracking right away
```

This opens the Buddy app in its own desktop window. Closing the window quits
the app. The same page is served at http://127.0.0.1:8765, which is where the
browser extension connects. Use `--open` to open the app in your browser
instead, or `--no-window` to only run the server. From the app you can:

- pick Mochi (cat girl) or Kiko (cat boy), pet, poke and feed them
- watch their needs (hunger, energy, attention, affection, boredom) and mood live
- turn on the camera so they notice you sitting down, getting up, leaning in or waving
- chat with them (they know how they're feeling)
- download the browser extension (**Download extension**, then follow the install steps)

With the extension installed, your buddy floats on every website you visit
and shows the same moods. Right-click it to chat, feed, switch character or
hide it. When the app is open in that same browser (`--open`), it also shares
one set of settings and one chat history with the extension. The desktop
window keeps its own, because extensions can't run inside it.

Every extra is optional. The app runs with plain Python and tells you what's
missing:

| Extra | Install | Without it |
|---|---|---|
| Desktop window | `pip install pywebview` (included in `requirements.txt`; Linux also needs GTK or Qt) | The app prints its URL; open it in your browser |
| AI chat (Claude) | `pip install -r UI/requirements.txt`, then `export ANTHROPIC_API_KEY=...` | Short built-in replies |
| Screen awareness (which app you're in, typing) | `pip install -r screen_behavior/requirements.txt` (+ `requirements-macos.txt` on macOS) | The brain uses the browser tab the extension reports |
| Body tracking (webcam) | `pip install mediapipe` (included in `requirements.txt`) | Camera panel explains how to enable it |

### How everything connects

```
 browser_extension/ ──(tab title+host, headpats, feeding, chat)──┐
   buddy on every site  ◄──────(emotion, caption, mood)──────────┤
                                                                 │
 UI/ website ──(headpats, feeding, camera on/off, chat)─────────►│ UI/server.py
   Your Buddy, needs, camera feed, chat  ◄──(/api/state)─────────┤  + UI/companion.py
                                                                 │
                          screen_behavior/ brain ◄───────────────┤  needs, mood, behavior, feeding
                          BodyTracking/ webcam   ◄───────────────┤  presence, getting up, hand, leaning in
                          animation_bridge.py    ◄───────────────┘  brain state -> emotion
```

| Piece | Folder | Role |
|---|---|---|
| App server | `UI/server.py` | Desktop window, website, extension download, chat, and the API below |
| Companion hub | `UI/companion.py` | Runs the brain every second, the optional camera, and turns interactions into need changes |
| Brain | `screen_behavior/` | Pet needs, mood, behavior and feeding rules |
| Body tracking | `BodyTracking/tracking.py` | Webcam presence and gestures; feeds reactions and the live video panel |
| Emotion mapping | `animation_bridge.py` | Brain update → one of the six emotions (or "lounging") |
| Website | `UI/index.html`, `UI/app.js`, `UI/animation.js` | Buddy, needs, camera, chat, download |
| Bridge | `browser_extension/bridge.js` | Runs only on the website; syncs settings, headpats, feeding and chat with the extension |
| On-page buddy | `browser_extension/buddy.js` | The floating buddy and its chat panel on every other website |
| Background | `browser_extension/background.js` | Stores data and relays chat, tab activity and interactions to the app server |

API (127.0.0.1 only): `GET /api/state`, `POST /api/presence`, `POST /api/interact`,
`POST /api/camera`, `GET /api/camera.mjpg`, `POST /api/chat`, `GET /api/status`.
The focused tab's title and host are sent only to this local server, only
while it's running, so the brain can tell coding from videos.

### The extension in every browser

`browser_extension/` runs as-is in Chromium browsers (Chrome, Edge, Brave,
Opera, Vivaldi, Arc), Firefox and Safari. Its manifest lists both background
styles: Chromium runs `background.js` as a service worker, Firefox runs
`background.scripts`.

To try it, load the folder unpacked (**Download extension** in the app gives
you the same folder):

| Browser | Load it | Needs |
|---|---|---|
| Chrome, Edge, Brave, Opera, Vivaldi, Arc | `chrome://extensions` (`edge://extensions`, ...) → **Developer mode** → **Load unpacked** → pick the folder | Chrome 121+ |
| Firefox | `about:debugging` → **This Firefox** → **Load Temporary Add-on** → pick `manifest.json` | Firefox 140+ (Android 142+) |
| Safari | Run `python3 build_extension.py safari`, then Safari → Settings → Advanced → **Show features for web developers**, and Settings → Developer → **Add Temporary Extension…** → pick `dist/safari/extension` | Safari 18+ to load it this way; the built app runs on 16.4+ |

If the buddy doesn't appear on websites (Firefox and Safari can install it
without site access), click the toolbar icon, then **Allow on all websites**,
and reload your tabs.

To publish, build one package per store:

```bash
python3 build_extension.py
```

| Output | Upload to |
|---|---|
| `dist/buddy-chromium-<version>.zip` | Chrome Web Store, Microsoft Edge Add-ons, Opera add-ons. Brave, Vivaldi and Arc install from the Chrome Web Store. |
| `dist/buddy-firefox-<version>.zip` | addons.mozilla.org (desktop and Android), which signs it |
| `dist/safari/` | With Xcode installed, the script also runs `safari-web-extension-converter` to make an Xcode app project; ship that through the Mac or iOS App Store. Set `SAFARI_BUNDLE_ID` in `build_extension.py` first. |

Each package keeps only the manifest keys its browser reads, and the script
refuses to build if the manifest is broken or a file has merge-conflict
markers. Raise `version` in `browser_extension/manifest.json` before each
store upload. The icons in `browser_extension/icons/` come from
`python3 art_source/slice_sheets.py --icons`.

Tests:

```bash
python3 -m unittest discover -s UI/tests      # website + companion hub
python3 -m screen_behavior.run_tests          # brain + animation bridge
```

### Character art and reactions

The two buddies come from the sheets in `art_source/` (cat girl and cat boy,
six emotions each). `python3 art_source/slice_sheets.py` (needs Pillow) cuts
them into `browser_extension/art/<girl|boy>/<emotion>.png`, which both the
extension and the app use.

| User does | Emotion shown |
|---|---|
| Click (headpat) | Happy, with a bounce and hearts |
| Click 5+ times in 2s, or shake while dragging | Angry, with a shake |
| Copy or paste | Encouragement, with a pop and hop |
| Chat message | Depends on the words: "tired", "hungry", "ugh", "done!"… |
| Idle for 90s | Tired, breathing slowly until you're back |
| Come back after a minute away | Sad, then happy |
| Not fed for 45 min | Hungry, until you feed them (right-click → Feed, or Feed in the app) |

With the app server running, the brain's state (`/api/state`) sets the
resting pose instead (hungry when its hunger is high, tired when its energy
is low, sad when it's lonely), on the website and on every other site, and
these reactions play on top. Webcam events add more: waving back when you
raise a hand, "Welcome back!" when you return to your desk, and a nudge to
stretch when you get up. `animation_bridge.py` still works on its own for
`python3 -m screen_behavior.demo_v05 --ui`.
