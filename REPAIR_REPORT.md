# Showerhacks browser integration repair — 0.5.3

Source of truth: the supplied **group-2 (3).zip**. This patch compares against
the files in that archive, not against its repository's older HEAD. It keeps
the Python brain, local HTTP server, companion hub, browser extension and
BodyTracking architecture.

## What was reproduced before changes

| Check on the supplied version | Observed failure | Corrected result |
|---|---|---|
| JavaScript parsing | `buddy.js` contained unresolved merge markers and failed Node's syntax check | Parses; the conflict is resolved around the existing `appState` handler |
| Empty/automatic browser heartbeat after 400 seconds idle | Idle time became 0 | Idle time remains approximately 400 seconds |
| Simulated camera absence | Brain presence remained unknown | Confirmed absence reaches AWAY and the existing distraction-budget logic |
| Simulated present camera frame after 400 seconds without input | Idle time became 0 | Idle time stays approximately 400 seconds; a present person can be IDLE |
| State consumed by the floating buddy | Missing `brain`, `onpage_mode`, `distraction_budget` | Existing presenter fields are added alongside all legacy companion fields |

Baseline UI suite: 31 tests passed. Baseline brain suite: 183 tests ran, with
one failure, one error and one skip. The two failing checks detected merge
markers and invalid JavaScript. Reproduction records and test logs are in
**REPAIR_REVIEW** in the corrected ZIP.

## State and presence consumers audited

`ActivityType.IDLE`, `UserState.IDLE`, and the pet's `Behavior.IDLE` are
different concepts. No enum values or existing helper meanings were changed.

| Consumer | Role and compatibility decision |
|---|---|
| `screen_behavior/awareness/models.py` | Defines activity/user-state enums and `ScreenContext`. `user_is_idle` still includes both IDLE and AWAY; its legacy activity fallback and `user_is_working` meaning are preserved. |
| `screen_behavior/awareness/user_state.py` | Fuses idle time and presence; keeps the existing thresholds and state smoothing. Known presence now prevents the five-minute inactivity fallback from declaring AWAY. Confirmed absence still declares AWAY immediately after the tracker reports it. |
| `screen_behavior/awareness/classifier.py`, `evidence.py` | Classify/smooth activity-level IDLE evidence. Unchanged. |
| `screen_behavior/awareness/service.py` | Accepts `set_user_present`, exposes it in snapshots, feeds the state tracker and supplies browser keyboard fallback. Only additive undo-count support was needed here. |
| `screen_behavior/pet/distraction.py` | Consumes `user_is_idle` and `user_is_working` for budget regeneration. Unchanged. |
| `screen_behavior/pet/utility.py` | Uses `user_is_idle`, idle duration, FOCUSED and PASSIVE to score behavior context. Unchanged. |
| `screen_behavior/pet/behavior.py`, `config.py`, `utility_config.py`, `models.py`, `enums.py` | Consume scoring context or define/default pet `Behavior.IDLE`. No new physical-presence policy or behavior rebalance was added. |
| `screen_behavior/integration/presenter.py`, `animation_bridge.py` | Serialize the brain's user state and rendering intent. The companion now includes the existing presenter contract. These files themselves are unchanged. |
| `screen_behavior/simulation.py`, `demo_brain.py` | Supply presence or construct sample IDLE/AWAY contexts. Unchanged. |
| `BodyTracking/tracking.py` | Produces debounced presence, camera-motion and body events. The tracker and its thresholds are unchanged; its snapshots are connected at the companion boundary. |
| `UI/companion.py` | Connects fresh, stable camera evidence to the brain; keeps it separate from input inactivity; generates existing body/typing/shortcut reactions and exposes state. |
| `UI/server.py`, `UI/app.js` | Relay state and interactions; show body/camera state. Preview visibility is now independent of tracking. The website no longer interprets tab hiding as physical absence. |
| `browser_extension/content.js`, `background.js`, `buddy.js`, `popup.js`, `bridge.js` | Report input/metadata, relay state, and consume rendering decisions or settings. The floating buddy uses `onpage_mode`; it does not invent a separate IDLE/AWAY classification. |
| Existing regression suites | User-state/service/classifier tests, budget/utility/behavior tests, simulation/integration tests and the UI tests were retained and run. New tests cover the repaired boundaries. |

No additional AWAY-only branch was needed in the budget or utility rules:
their existing deliberate treatment of both resting states is preserved.
The explicit physical-presence distinction is made at classification.

## Changes and intentional behavior differences

- Resolved the competing `buddy.js` implementations. Removed the unhandled
  `brainState` polling route and used the existing `appState` message.
- Preserved the artwork and added the existing presenter output to companion
  state. Fresh brain decisions control movement; unrelated random wandering
  and local sleep timers no longer override them. Fallback remains when brain
  data is unavailable or more than ten seconds old. State polling does not
  refresh a stopped brain's decision timestamp.
- Separated title/host metadata from genuine input. Heartbeats carry input
  age, so repeated reports and reports from older tabs cannot replace a newer
  input timestamp. Legacy positive key/click/copy/paste counts still work.
  Programmatic events, open pages, elapsed page time and scroll position do
  not count as fresh user input.
- Connected camera snapshots to `set_user_present`. Off, failed, starting,
  moving, or older-than-five-second snapshots provide unknown presence.
  Camera presence never resets keyboard/mouse inactivity. Camera processing
  failures report an error and release the device.
- Kept the existing no-camera policy: IDLE after roughly 60 seconds plus
  smoothing, inferred AWAY after 300 seconds. `activity.away_inferred`
  distinguishes the latter from camera-confirmed absence. Camera presence
  keeps a still person IDLE, even after five minutes.
- Removed tab-visibility-based missed-you/return reactions. Real camera
  return events and existing voice clips remain.
- Added immediate semantic copy/paste/undo messages and an additive shortcut
  endpoint. Browser Ctrl+Z now reaches both voice reactions and aggregate
  awareness counts. No typed text or clipboard contents are sent.
- As approved, changed shortcut speech from one shared 15-second cooldown to
  a **one-second guard per shortcut**. Different shortcuts can respond
  immediately. Held keys and duplicate keydown/clipboard signals are filtered;
  browser aggregate reports and a native monitor do not replay the same
  immediate event. Shortcuts may interrupt a current voice line. Suppressed
  repeats are discarded, not queued.
- Added one extension audio player, a shared Voice switch, exact-clip caption
  notifications, and an atomic server claim for live voice events. This
  prevents duplicate playback by tabs or a separate website/desktop window.
  Failed playback releases its claim. Brain movement updates do not wait for
  audio loading.
- Added Hide/Show preview independently of Start/Stop camera. Hiding removes
  the live image stream from the page and remembers the preference; Python
  tracking continues. A visible status still identifies active tracking.

**Budget and interruption policy:** budget costs, regeneration rates, utility
weights, hunger, energy, feeding and unrelated behavior rules are unchanged.
Both IDLE and AWAY still use the existing idle budget rate (2 units/second).
Corrected sensor facts now reach those rules. The intended interruption
changes are removal of incorrect floating-buddy fallback overrides and the
explicitly approved faster shortcut speech described above.

The original voice recordings/captions, needs/feeding rules, artwork, native
desktop-window feature, camera gestures and built-in/Claude chat paths are
preserved. All **76 image/audio/caption asset files** match the input archive
byte for byte. Signal analysis found about 0.22–0.60 seconds of leading silence
in the ten shortcut recordings; no audio files were edited.

## Compatibility and API details

Legacy state fields remain: `animation`, `message`, `voice`, `pet`, `activity`,
`feeding`, `camera`, and `body`. Existing public calls still accept their old
arguments. New constructor options and aggregate fields are optional.

Additions include the presenter fields, decision age, input age, undo counts,
presence/inferred-away diagnostics, and a unique `voice.key` in each existing
voice object. `updated_at` now describes the actual brain update rather than
the time a client happened to poll.

New routes:

- `POST /api/shortcut` with `{ "shortcut": "copy" | "paste" | "undo" }`.
- `POST /api/voice/claim` with the voice key, a player owner token, and optional
  `release: true` after playback fails.
- Existing `POST /api/presence` marks input only with explicit `input: true`;
  ordinary state polls and page metadata remain read-only with respect to
  inactivity. External callers that formerly used `{}` as an activity signal
  must send the explicit input flag for a genuine user event.

All extension messages were checked against handlers. Runtime messages are
`session`, `heartbeat`, `pet`, `chat`, `appState`, `interact`, `shortcut`,
`voice`, and `voiceSupport`. Audio-only `play`/`stop` messages are handled in
the offscreen document. Website bridge messages retain `hello`, `get`,
`setBuddy`, `pet`, `feed`, and `chat`, with additive `setVoice` and `voice`.

Chrome/Edge audio uses the documented `offscreen` permission and a bundled
audio page; Firefox uses its background page and the Firefox build removes
the Chrome-only permission. Unsupported browsers keep website audio as the
fallback; Safari extension-only background voice is not supported here.
The implementation follows [Chrome's offscreen API documentation](https://developer.chrome.com/docs/extensions/reference/api/offscreen)
and [Mozilla's background-script documentation](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Background_scripts).

Extension automatic speech checks run from a focused permitted webpage,
even when the floating character is hidden. Protected/suspended pages, no
permitted page, or minimizing the browser can delay browser reports and voice
events. Python camera tracking does not depend on an open preview or webpage.
Browser-only awareness cannot see input in unrelated desktop apps.

## Validation actually completed

Environment: Linux, Python 3.12.14, Node 24.19.0.

| Validation | Result and scope |
|---|---|
| `python3 -m unittest discover -s UI/tests` | 57 passed: legacy website/voice/desktop tests, real local HTTP routes, presence/inactivity, immediate shortcuts, voice claims and mocked camera failures. |
| `python3 -m screen_behavior.run_tests` | 188 ran: 187 passed, one macOS real-keyboard test skipped. Existing needs, feeding, budget, behavior and integration suites passed. |
| JavaScript syntax | Node parsed every extension and UI `.js` file. |
| Extension runtime | Actual content, background, buddy, bridge, offscreen and audio-player scripts ran in Node with mocked DOM/browser/Audio APIs. Covers immediate C/V/Z, duplicate prevention, mute, failed playback recovery, offscreen recreation, camera-preview controls and brain output. No physical audio was produced. |
| HTTP integration | Actual content/background JavaScript relayed to an actual Python HTTP server on a test port. Separately launched the real server on port 8765 and checked state, interactions, voice index, assets and the downloadable extension contents. |
| Camera | Simulated presence/absence/return/off/error/movement/staleness and processing exceptions. No physical webcam or pose inference was run. |
| Windows launcher | Python launch command and occupied-port guard tested with mocks; batch file supplied with Windows line endings. Not executed on Windows. |
| Extension builds | Chromium and Firefox packages built successfully. This is packaging validation, not browser installation. |
| Patch and archive | Patch checked/applied against a clean copy of the supplied source; resulting files compared. ZIP CRCs, modified entries and unchanged original entries verified. |

Total: **244 passed, one skipped**. A page loading or HTTP 200 is not treated
as proof of an installed extension working.

Still required on your computer: install/reload the extension, confirm site
access and sound, check real shortcut latency, start the physical webcam,
test hidden-preview absence/return behavior, and try the Windows launcher.
Optional dependency installation, native OS permissions, actual pywebview
rendering, real audio and Claude credentials were not validated here.

One existing test expectation was updated deliberately: paste immediately
followed by undo now expects the undo voice, as approved. The existing
in-frame voice fixture gained a fresh simulated camera timestamp. Other
existing valid assertions remain.

## Changed files

Modified source/packaging:

- `UI/app.js` — preview controls, immediate standalone shortcuts, shared voice ownership/captions and trusted input.
- `UI/companion.py` — input/presence separation, rendering contract, immediate voice events and claims.
- `UI/index.html` — preview toggle and camera-tracking status.
- `UI/server.py` — explicit input handling, camera-state refresh and additive voice routes.
- `browser_extension/background.js` — immediate shortcut relay and shared audio coordination.
- `browser_extension/bridge.js` — voice capability/settings/playback messages.
- `browser_extension/buddy.js` — resolved merge, fresh brain control and voice captions.
- `browser_extension/content.js` — input age, immediate shortcut events and read-only voice polling.
- `browser_extension/manifest.json` — version 0.5.3, audio permission and background-player reference.
- `browser_extension/popup.html`, `popup.js` — shared Voice switch.
- `build_extension.py` — omit Chrome-only permission from Firefox/Safari build manifests.
- `screen_behavior/awareness/browser.py`, `service.py` — additive browser undo aggregate.
- `screen_behavior/awareness/user_state.py` — known camera presence prevents inferred AWAY.

Modified tests:

- `UI/tests/test_companion.py`.
- `screen_behavior/tests/test_extension_js.py`.
- `screen_behavior/tests/test_user_state.py`.

Added files:

- `browser_extension/voice-player.js`, `voice-offscreen.js`, `voice-offscreen.html`.
- `UI/tests/test_browser_integration.py`, `browser_http.cjs`, `voice_runtime.cjs`, `website_runtime.cjs`.
- `screen_behavior/tests/buddy_runtime.cjs`.
- `START_BUDDY.bat`, `start_buddy.py`, `START_HERE.md`, `REPAIR_REPORT.md`.

The ZIP also includes generated build packages and `REPAIR_REVIEW` evidence
plus a copy of the patch. Those generated artifacts are not source changes
in the minimal review patch.

## Integrating without overwriting teammate work

For a beginner run, extract the complete corrected ZIP into a **new folder**
and follow **START_HERE.md**. The fixes are already applied in that ZIP.

For your team's newer branch, commit or back up current work and create a
repair branch. Put the separately supplied patch outside the repository, then
from your project root use its actual path:

```text
git switch -c fix/browser-integration
git apply --check ../showerhacks-browser-v0.5.3.patch
git apply ../showerhacks-browser-v0.5.3.patch
python -m unittest discover -s UI/tests
python -m screen_behavior.run_tests
python build_extension.py chromium firefox
```

If the check reports conflicts, have the owners of those files merge the
specific sections. Do not replace the whole newer project with this ZIP or
force the patch through. The tested clean application is against the exact
attached source; a perfect merge into newer teammate changes is not promised.
Review the UI/voice changes with those teams, reload the extension, and refresh
existing tabs after integration.
