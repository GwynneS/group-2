# Screen Awareness + Tamagotchi Behavior — V0.5

This is the **Person 3 + Person 4** subsystem for the desktop-companion project.

It owns:

- Tamagotchi state: affection, attention, hunger, energy, boredom
- mood logic
- autonomous behavior selection
- behavior commitment/cooldowns/energy costs
- screen awareness
- active application/window
- cursor position
- idle time
- activity classification + confidence
- activity duration / previous activity
- active-window edge awareness
- aggregate keyboard activity
- keyboard inactivity clock

It does **not** own:

- rendering / desktop overlay
- animation files or frame timing
- voice/dialogue generation
- UI
- items / inventory / unlocks
- interaction content definitions
- event definitions

The subsystem returns **state, context, and behavior intent**. Other groups decide
how to render, animate, speak, or turn that data into content/events.

## Privacy rule for keyboard awareness

The keyboard monitor never stores or exposes which keys were pressed. A keypress
is immediately converted to a timestamp/counter and the key identity is discarded.

There is no key log, text reconstruction, clipboard monitoring, or password capture.

**One narrow exception: copy / paste / undo.** Ctrl or Cmd + C, V, Z are
recognized and reported only as `copy` / `paste` / `undo`. No other key or
combination is ever identified, and the clipboard contents are never read.

```python
kb = update.screen.keyboard
kb.last_shortcut                 # Shortcut.COPY / PASTE / UNDO, or None
kb.seconds_since_last_shortcut
kb.shortcut_counts               # {Shortcut.PASTE: 3, ...}; only goes up
```

To react to each new shortcut exactly once, compare `shortcut_counts` with the
previous update.

## Install

### Windows

```powershell
py -m pip install -r screen_behavior/requirements.txt
```

### macOS

```bash
python3 -m pip install -r screen_behavior/requirements.txt
python3 -m pip install -r screen_behavior/requirements-macos.txt
```

macOS may require the user to grant Accessibility/Input Monitoring permission for
global keyboard activity. The subsystem does not bypass macOS privacy controls.
If monitoring is unavailable, keyboard metrics report unavailable instead of
pretending the user is inactive.

## Demo

### Live awareness

Windows:

```powershell
py -m screen_behavior.demo_v04
```

macOS:

```bash
python3 -m screen_behavior.demo_v04
```

### Running the whole app (UI + brain + extension)

See the project README for the full picture. Short version:

```bash
python3 UI/server.py --open          # http://127.0.0.1:8765
python3 UI/server.py --camera --mic  # + webcam body tracking, + yell-to-wake
```

`UI/server.py` runs `UI/companion.py` (the UI team's hub), which owns one
`CompanionBrain` and ticks it every second. What this subsystem contributes
to that hub:

- `/api/state` reports the brain's behavior, the utility `reason`, needs,
  mood, activity and `user_state`. `animation_for_update()`
  (`integration/presenter.py`, re-exported by `animation_bridge.py`) maps a
  brain update to one of the 7 emotions.
- Feeding is `brain.feed()`: fish is the only food; the pet refuses when full.
- `POST /api/browser-activity` receives the extension's 5-second heartbeats
  (counts only: clicks, keys, copies, pastes, scroll, active time, plus tab
  title/host) and feeds them to `AwarenessService.record_browser_activity()`.
  The tab's title/host sharpens activity detection, and in-browser key counts
  stand in for typing when OS keyboard monitoring isn't permitted.
- `--mic` enables loudness detection (never recorded) so a yell wakes a pet
  that's playing dead.

### Driving the UI from your own script

`animation_bridge.py` serves the same app, but your script decides the state:

```python
from animation_bridge import AnimationBridge

bridge = AnimationBridge()
bridge.start()
bridge.set_animation("encouragement", "You got this!")   # manual
bridge.update_from_brain(brain.update())                  # or from a brain
```

`py -m screen_behavior.demo_v05 --ui` does this with the live brain.
Supported animation names are `lounging`, `happy`, `sad`, `tired`, `angry`,
`hungry`, and `encouragement`. Call `bridge.close()` when the script exits.

### Instant deterministic scenarios

Windows:

```powershell
py -m screen_behavior.demo_v04 --scenarios
```

macOS:

```bash
python3 -m screen_behavior.demo_v04 --scenarios
```

### Automated tests

No pytest required.

Windows:

```powershell
py -m screen_behavior.run_tests
```

macOS:

```bash
python3 -m screen_behavior.run_tests
```

## Public integration contract

Other groups should normally use only:

```python
from screen_behavior.integration.brain import CompanionBrain

brain = CompanionBrain()
update = brain.update()
```

`update` contains:

```text
BrainUpdate
├── screen
│   ├── activity
│   ├── activity_confidence
│   ├── activity_duration_seconds
│   ├── previous_activity
│   ├── activity_changed
│   ├── foreground
│   ├── screen_bounds
│   ├── cursor_x / cursor_y
│   ├── idle_seconds
│   ├── window_edge
│   └── keyboard
│
├── pet
│   ├── energy
│   ├── hunger
│   ├── attention
│   ├── affection
│   ├── boredom
│   ├── mood
│   └── special_mood
│
└── decision
    ├── behavior
    ├── reason
    ├── distracting
    ├── commitment_remaining_seconds
    └── cooldown_remaining_seconds
```

Person 1 can consume geometry/context.
Person 2 can consume `decision.behavior`.
Person 5 can consume moods/context for dialogue.
Person 6 can apply generic numeric interaction effects through the public hook,
without this subsystem defining the content of those interactions.


## V0.5 activity scoring


Screen awareness now computes an evidence score for every activity candidate:

```python
screen.activity_scores
```

Example:

```text
coding=0.98
studying=0.25
browsing=0.08
gaming=0.01
video=0.01
idle=0.01
other=0.10
```

The highest raw score is exposed as `screen.leading_activity`, but the public
`screen.activity` uses a short stability/hysteresis layer so tiny score changes
do not cause rapid `coding -> browsing -> coding` flicker.

Run:

```powershell
py -m screen_behavior.demo_v05
```

or:

```powershell
py -m screen_behavior.demo_v05 --scenarios
```


## V0.6 brain upgrades

### Evidence decay (smoother activity detection)
`awareness/evidence.py`. Activity scores are a time-weighted average over
roughly the last 30–60 seconds (20s time constant), so a 5-second Alt-Tab from
VS Code to Chrome stays "coding", while a minute in Chrome becomes "browsing".
Coming back from idle is immediate. `screen.activity_scores` is the decayed
evidence; `screen.leading_activity` is still the instant raw leader.

### Unified user state
`awareness/user_state.py` fuses activity, typing, mouse, idle time, and body
presence into one stable state:

| State | Meaning |
|---|---|
| `FOCUSED` | coding/studying with typing in the last ~90s |
| `ACTIVE` | engaged but not working (gaming, browsing with input) |
| `PASSIVE` | watching/reading with little input |
| `DISTRACTED` | 3+ app switches in 2 min, or just drifted from work to leisure |
| `IDLE` | no input for 60s+ |
| `AWAY` | no input for 5 min+, or body tracking says not present |

A new state must hold 5s before it's reported (AWAY/IDLE transitions are
immediate). Read `update.screen.user_state` / `user_state_seconds`.
Body tracking can call `brain.awareness.set_user_present(True/False/None)`.

### Utility behavior brain

`BehaviorEngine.decide()` runs a fixed pipeline; the first stage that
applies decides (`decision.source` says which):

1. `play_dead`: loud-voice wake, 90s timeout, or keep playing dead
2. `sleep`: stay asleep until energy reaches 75
3. `urgent`: energy ≤ 18 → sleep; attention ≤ 18 or hunger ≥ 80 → ask for
   attention. Urgent needs interrupt commitments.
4. `commitment`: keep the current behavior until its commitment ends
5. hard eligibility (excluded before scoring): min energy, cooldown,
   distraction budget, and "not tired enough to nap" (energy ≥ 45)
6. `utility`: every eligible behavior gets points (not a probability)
7. controlled variation: behaviors within 12 points of the leader (and at
   least 60% of its score) get lottery tickets in proportion to how close
   they are; one is drawn with the engine's seeded RNG. A clearly worse
   behavior can never win.

Utility = labeled components, so every decision is explainable:

```python
d = brain.update().decision
d.behavior_scores   # {Behavior.STUDY_WITH_USER: 83.0, Behavior.SIT_DOWN: 42.1, ...}
d.score_breakdown   # {"base": 8, "context": 39, "focus": 34.2, "variation": -1.3}
d.candidates        # the strong behaviors the pick was drawn from
d.reason            # "keeping the user company while they work (context +39, focus +34)"
```

Components: `base`, `context` (activity fit × classifier confidence),
`energy`/`tiredness`/`boredom`/`loneliness`/`affection`/`hunger`, `mood`,
`special_mood`, `focus` (how engaged the user is in work: typing, confidence,
session length, user state), `idle`, `mouse`, `hyper`, `distraction`
(focus penalty + low budget + recent distracting behaviors), `repetition`,
`recency`, `attention_request` (fades over 5 min after asking), `ignored`,
`whim` (rare behaviors), `variation` (±3), `preference`.

**Tuning:** every number is in `pet/utility_config.py`: one
`BehaviorProfile` per behavior plus global weights and urgent thresholds.
`BehaviorSpec` in `pet/config.py` still owns min energy, energy cost,
commitment, cooldown, and the distracting flag.

**Hyper:** `InteractionEffect(hyper_seconds=60)` makes buddy hyper (excited
mood, energetic behaviors score higher) until it counts down. Whoever owns
treats/events decides when; the brain only reacts.

**Future personalization:** `BehaviorEngine(preference=fn)` takes
`fn(behavior, scoring_context) -> points`, clamped to ±10, so a learned layer
can nudge choices without ever overriding urgent needs or hard rules.

**Brain simulator** (no UI, sensors, or animation):

```bash
python3 -m screen_behavior.demo_brain                    # all scenarios A-I
python3 -m screen_behavior.demo_brain --scenario coding --scores 5
python3 -m screen_behavior.demo_brain --list
```

Scenarios: long coding, going idle, video, high boredom, lonely, low
energy, hyper, high affection, and 60 repeated cycles. Each row shows time,
activity, energy/attention/hunger/boredom, mood, behavior, deciding stage,
top scores, and reason; each scenario ends with a pattern summary.

### Simulation harness
`simulation.py` runs the full pipeline on simulated time: hours in about a
second.

```bash
python3 -m screen_behavior.simulation --list
python3 -m screen_behavior.simulation --scenario workday
python3 -m screen_behavior.simulation --scenario neglect --hours 8
python3 -m screen_behavior.simulation --scenario workday --csv timeline.csv
python3 -m screen_behavior.simulation --scenario workday --ignore-buddy
```

Scenarios: `workday`, `alt_tab`, `gaming_evening`, `app_hopping`, `neglect`.
The report shows time per user state/activity/mood, distracting behaviors per
hour by user state, behavior counts, repeats, attention requests, feeds,
play-dead length, and need extremes. `tests/test_simulation.py` turns these
into regression checks.


## Distraction budget

Buddy has a `distraction_budget` (0–100). Distracting behaviors spend it:
dance 35, play dead 30, walk around corner 25, ask for attention 20,
send kiss 10, wave 8. Quiet behaviors (watch screen, study with user, sit,
look around, follow mouse, stretch, sleep, idle) are free.

The budget refills slowly while the user codes/studies (~30 min to full),
moderately otherwise, and fast when the user is idle. A behavior buddy can't
afford is skipped. Urgent needs (e.g. critically lonely) still go through.

`update.decision.distraction_budget` exposes the current value. Numbers live
in `DistractionConfig` in `pet/distraction.py`.


## Behavioral memory

Short-term state, not AI memory. `update.memory` contains:

- `last_behavior`, `last_5_behaviors`
- `time_since_attention_request`
- `recently_ignored`: buddy asked for attention and nobody interacted within
  30s. For the next 5 minutes buddy sulks (sits down) instead of nagging again.
- `recently_interacted_with`: fed or interacted with in the last 2 minutes.

Buddy avoids repeating its last behavior, or anything it did twice in its
last 5, when another option is available. `brain.feed()` and
`brain.apply_interaction()` count as interacting.


## Feeding system

Fish is buddy's only food. This subsystem owns what fish does; whoever owns
the feeding UI decides when the user feeds buddy and calls:

```python
result = brain.feed()
result.accepted  # False if buddy is full
result.reason
```

- Fish lowers hunger by 35, adds 10 energy, 6 affection, 5 attention.
- Buddy refuses fish when hunger is 10 or below.
- A hungry buddy gets tired faster (see `NeedsConfig`).

Numbers live in `FeedingConfig` in `pet/feeding.py`.

```bash
python3 -m screen_behavior.demo_feeding              # interactive
python3 -m screen_behavior.demo_feeding --scenarios  # scripted
```


## Continuous mouse tracking

A background thread reads the cursor ~30 times/second (macOS + Windows, no
extra permission needed). Only cursor position is used: no clicks, nothing
about what's under the cursor.

```python
m = brain.mouse()            # cheap; call every animation frame
m.x, m.y, m.speed, m.moving, m.seconds_since_move, m.distance_last_5_seconds

look = m.look_from(pet_eye_x, pet_eye_y)   # for follow-mouse-with-eyes
look.dx, look.dy, look.angle_degrees, look.distance_px

brain.add_mouse_listener(lambda x, y: ...)  # called on every cursor move
```

`update.screen.mouse` carries the same data on each `brain.update()`.

```bash
python3 -m screen_behavior.demo_mouse
```


## Voice / loudness detection (opt-in)

Works on macOS and Windows via `sounddevice` (bundles PortAudio; no extra
install). It is **off by default**:

```python
brain = CompanionBrain(enable_microphone=True)
update = brain.update()
update.microphone.user_talking          # voice above background noise
update.microphone.loud_voice_detected   # user yelled
```

When `loud_voice_detected` is true, a play-dead buddy wakes up (surprised,
waves). "Loud" is relative to the room's background noise, so normal talking
doesn't count; a fan or music slowly raises the bar.

Privacy: each ~50ms audio block becomes one loudness number and the samples
are discarded. No recording, no speech-to-text, nothing leaves the machine.

Permissions: macOS asks to allow Terminal/VS Code under Privacy & Security >
Microphone. Windows: Settings > Privacy > Microphone > allow desktop apps.

```bash
python3 -m screen_behavior.demo_voice   # live meter; yell to wake buddy
```
