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
