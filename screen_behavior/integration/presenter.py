"""
Brain -> animation contract.

`present(update)` turns one BrainUpdate into the JSON every front end reads
from GET /api/state:

- `animation` / `message`: one of the 7 detailed animations in UI/animation.js
- `pose`: hints for the sprites.js buddy (UI/app.js and the on-page buddy)
- `onpage_mode`: movement mode for browser_extension/buddy.js
- `behavior`, `mood`, `needs`, `user`, ... : the raw brain state

Front ends should only depend on this module's output, never on brain
internals, so either side can change without breaking the other.
"""
from __future__ import annotations

import time
from typing import Any

ANIMATIONS = {
    "lounging": "Lounging",
    "happy": "Happy",
    "sad": "Sad",
    "tired": "Tired",
    "angry": "Angry",
    "hungry": "Hungry",
    "encouragement": "You got this!",
}

# What buddy is doing, as a short caption.
BEHAVIOR_MESSAGES = {
    "idle": "Hanging out",
    "wave": "Waving at you!",
    "dance": "Dancing!",
    "stretch": "Stretching",
    "look_around": "Looking around",
    "sit_down": "Sitting down",
    "sleep": "Napping... zzz",
    "walk_around_corner": "Exploring",
    "ask_for_attention": "Wants some attention",
    "follow_mouse_with_eyes": "Watching your cursor",
    "send_kiss": "Sending you a kiss!",
    "play_dead": "Playing dead... yell to wake!",
    "study_with_user": "You got this!",
    "watch_screen": "Watching with you",
}

# How the on-page buddy (buddy.js) should move for each behavior.
ONPAGE_MODES = {
    "sleep": "sleep",
    "play_dead": "sleep",
    "walk_around_corner": "wander",
    "follow_mouse_with_eyes": "follow",
    "look_around": "follow",
    "dance": "cheer",
    "wave": "cheer",
    "send_kiss": "cheer",
    "ask_for_attention": "attention",
}


def _value(x: Any) -> Any:
    return getattr(x, "value", x)


def animation_for_update(update: Any) -> str:
    """Pick one of the 7 UI/animation.js states for a brain update."""
    behavior = _value(update.decision.behavior)
    mood = _value(update.pet.mood)

    if behavior in {"wave", "study_with_user"}:
        return "encouragement"
    if (
        behavior in {"sleep", "play_dead"}
        or mood == "tired"
        or update.pet.energy <= 15
    ):
        return "tired"
    if mood == "hungry" or update.pet.hunger >= 70:
        return "hungry"
    if mood in {"mad", "annoyed"}:
        return "angry"
    if mood == "lonely" or behavior == "ask_for_attention":
        return "sad"
    if mood in {"happy", "excited"} or behavior in {"dance", "send_kiss"}:
        return "happy"
    return "lounging"


def pose_for_update(update: Any) -> dict[str, str]:
    """Hints for sprites.js: eyes open/closed/happy and tail speed."""
    behavior = _value(update.decision.behavior)
    mood = _value(update.pet.mood)

    if behavior in {"sleep", "play_dead"}:
        return {"eyes": "closed", "tail": "still"}
    if behavior in {"dance", "wave", "send_kiss"} or mood in {"happy", "excited"}:
        return {"eyes": "happy", "tail": "fast"}
    if mood == "tired" or update.pet.energy <= 25:
        return {"eyes": "open", "tail": "slow"}
    return {"eyes": "open", "tail": "normal"}


def present(update: Any) -> dict[str, Any]:
    behavior = _value(update.decision.behavior)
    animation = animation_for_update(update)
    pet = update.pet
    screen = update.screen
    special = _value(getattr(pet, "special_mood", None))

    return {
        "brain": "running",
        "updated_at": time.time(),
        "animation": animation,
        "message": BEHAVIOR_MESSAGES.get(behavior, ANIMATIONS[animation]),
        "pose": pose_for_update(update),
        "onpage_mode": ONPAGE_MODES.get(behavior, "idle"),
        "behavior": behavior,
        "reason": update.decision.reason,
        "mood": _value(pet.mood),
        "special_mood": special,
        "needs": {
            "hunger": round(pet.hunger),
            "energy": round(pet.energy),
            "attention": round(pet.attention),
            "affection": round(pet.affection),
            "boredom": round(pet.boredom),
        },
        "user": {
            "state": _value(getattr(screen, "user_state", None)),
            "activity": _value(screen.activity),
            "confidence": round(screen.activity_confidence, 2),
            "host": (
                screen.browser.host
                if getattr(screen, "browser", None) and screen.browser.available
                else None
            ),
        },
        "distraction_budget": round(
            getattr(update.decision, "distraction_budget", 100.0)
        ),
    }


def offline_state(message: str = "Brain offline") -> dict[str, Any]:
    """What /api/state returns when no brain is running."""
    return {
        "brain": "offline",
        "updated_at": time.time(),
        "animation": "lounging",
        "message": message,
        "pose": {"eyes": "open", "tail": "normal"},
        "onpage_mode": "idle",
    }
