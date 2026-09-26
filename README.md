# This project is based on the idea of a Fem Boy AI Buddy

# This AI will praise you and support you on your productive tasks

# Particular response on command V
# Particular response on command C
# You cant pet the cat girl or femboy and it boosts the "happiness" bar


## Running the Buddy app

```bash
pip install -r requirements.txt   # optional extras; see below
python3 UI/server.py --open       # add --camera to start body tracking right away
```

This opens http://127.0.0.1:8765, the Buddy website. From there you can:

- pick Mochi (cat girl) or Kiko (cat boy), pet, poke and feed them
- watch their needs (hunger, energy, attention, affection, boredom) and mood live
- turn on the camera so they notice you sitting down, getting up, leaning in or waving
- chat with them (they know how they're feeling)
- download the browser extension (**Download extension**, then follow the install steps)

With the extension installed, your buddy floats on every website you visit,
shows the same moods, and shares one set of settings and one chat history
with the website. Right-click it to chat, feed, switch character or hide it.

Every extra is optional. The app runs with plain Python and tells you what's
missing:

| Extra | Install | Without it |
|---|---|---|
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
| App server | `UI/server.py` | Website, extension download, chat, and the API below |
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
