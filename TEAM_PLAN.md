# Screen Awareness + Tamagotchi Behavior Team

## Goal

Build the part of the desktop companion that answers:

1. What is happening on the user's computer?
2. What does the pet currently need?
3. Given both of those things, what should the pet do next?

The final renderer, character model, and voice system should not be required
for this module to work.

## Recommended 3-person split

### Person A — Screen Awareness
Own:
- `awareness/`
- foreground application/window
- cursor position
- idle time
- activity classification
- later: window geometry and opt-in local vision

Output only high-level `ScreenContext` data.

### Person B — Tamagotchi Needs
Own:
- `pet/models.py`
- `pet/needs.py`

Responsibilities:
- affection
- hunger
- attention
- energy
- boredom
- interaction effects
- rates and balancing

### Person C — Behavior / Integration
Own:
- `pet/behavior.py`
- `integration/`

Responsibilities:
- combine `PetState` + `ScreenContext`
- choose high-level behavior
- generate dialogue intents
- maintain tests
- keep interfaces stable for other teams

## Shared contract

Other teams should consume:

```python
BrainUpdate(
    pet=...,
    screen=...,
    decision=BehaviorDecision(
        behavior="study_with_user",
        emotion="focused",
        reason="user appears to be coding",
        dialogue_intent=None,
    )
)
```

The animation team maps `behavior` to an animation.
The voice team maps `dialogue_intent` + `emotion` to speech.

## Current awareness policy

V0.1 does not record keystrokes, passwords, or clipboard contents and does not
upload screenshots. Advanced screen vision should remain local and opt-in.
