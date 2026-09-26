"""The companion hub behind the Buddy website and browser extension.

Connects the project's pieces into one live state:

    screen_behavior/      the pet's brain: needs, mood, behavior, feeding
    BodyTracking/         optional webcam body tracking (presence, getting up,
                          raised hand, leaning in), plus the live video feed
    animation_bridge.py   brain update -> emotion shown on screen

and turns what the user does (headpats, pokes, feeding, chatting, browsing)
into interactions the brain responds to.

Screen awareness uses screen_behavior's native backend when its packages are
installed (psutil, pynput, pyobjc on macOS). Otherwise it classifies the
browser tab the extension reports, using the same activity classifier.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from animation_bridge import ANIMATION_LABELS, animation_for_update  # noqa: E402
from screen_behavior.awareness.models import RawScreenSnapshot, WindowInfo  # noqa: E402
from screen_behavior.awareness.service import AwarenessService  # noqa: E402
from screen_behavior.integration.brain import CompanionBrain  # noqa: E402
from screen_behavior.pet.interactions import InteractionEffect  # noqa: E402

BRAIN_TICK_SECONDS = 1.0

# What each user interaction does to the pet's needs.
INTERACTIONS = {
    "pet": InteractionEffect(affection_delta=4, attention_delta=6, boredom_delta=-3),
    "poke": InteractionEffect(affection_delta=-3, attention_delta=4),  # too many pokes at once
    "chat": InteractionEffect(affection_delta=1, attention_delta=8, boredom_delta=-6),
    "copy_paste": InteractionEffect(attention_delta=2, boredom_delta=-2),
}

# Friendly captions for the brain's behaviors.
BEHAVIOR_MESSAGES = {
    "idle": "Hanging out",
    "wave": "Hi there!",
    "dance": "Dancing!",
    "stretch": "Stretching~",
    "look_around": "Looking around",
    "sit_down": "Sitting with you",
    "sleep": "Napping... Zzz",
    "walk_around_corner": "Going for a little walk",
    "ask_for_attention": "Pay attention to me!",
    "follow_mouse_with_eyes": "Watching your cursor",
    "send_kiss": "Mwah!",
    "play_dead": "*plays dead*",
    "study_with_user": "Studying with you",
    "watch_screen": "Watching your screen",
}

# Reactions to webcam body-tracking events: (emotion, caption, seconds, effect).
BODY_REACTIONS = {
    "user_arrived": ("happy", "There you are! Let's get started.", 4, InteractionEffect(attention_delta=10)),
    "user_returned": ("happy", "Welcome back!", 4, InteractionEffect(attention_delta=15, affection_delta=3)),
    "user_left": ("sad", "Come back soon...", 5, None),
    "user_getting_up": ("encouragement", "Stretch break? Good idea!", 4, None),
    "user_sat_back_down": ("happy", "Back to it!", 3, None),
}
HAND_RAISE_COOLDOWN = 10.0
LEAN_IN_COOLDOWN = 90.0


class BrowserActivityBackend:
    """Screen awareness from the browser tab the user is on.

    Stands in for screen_behavior's native backend when its packages aren't
    installed. The extension and website report the focused tab's title and
    host; that becomes the "foreground window" the activity classifier reads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._title = ""
        self._last_input = time.monotonic()

    def report(self, title: str, host: str) -> None:
        with self._lock:
            self._title = f"{title} - {host}".strip(" -")[:300]
            self._last_input = time.monotonic()

    def note_input(self) -> None:
        with self._lock:
            self._last_input = time.monotonic()

    def snapshot(self) -> RawScreenSnapshot:
        with self._lock:
            title = self._title
            idle = time.monotonic() - self._last_input
        return RawScreenSnapshot(
            idle_seconds=idle,
            foreground=WindowInfo(title=title, app_name="Google Chrome") if title else None,
        )


@dataclass
class Reaction:
    animation: str
    message: str
    until: float


def module_available(*names: str) -> bool:
    return all(importlib.util.find_spec(n) is not None for n in names)


class CameraWorker:
    """Runs BodyTracking's BodyTracker on the webcam in a background thread and
    keeps the latest annotated frame as JPEG for the website's video feed."""

    def __init__(self, on_snapshot) -> None:
        self._on_snapshot = on_snapshot
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frame_cond = threading.Condition()
        self._frame: bytes | None = None
        self._frame_id = 0
        self.status = "off" if self.available() else "unavailable"
        self.error = ""

    @staticmethod
    def available() -> bool:
        return module_available("cv2", "mediapipe")

    def start(self, camera_index: int = 0) -> None:
        if not self.available() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self.status, self.error = "starting", ""
        self._thread = threading.Thread(target=self._run, args=(camera_index,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        if self.status != "unavailable":
            self.status = "off"
        with self._frame_cond:
            self._frame = None
            self._frame_cond.notify_all()

    def wait_frame(self, after_id: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        with self._frame_cond:
            self._frame_cond.wait_for(lambda: self._frame_id != after_id or self._stop.is_set(), timeout)
            return self._frame_id, self._frame

    def _run(self, camera_index: int) -> None:
        import cv2

        from BodyTracking.tracking import BodyTracker, draw_skeleton

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            self.status = "error"
            self.error = (
                "Couldn't open the webcam. On macOS, allow camera access for your terminal "
                "in System Settings > Privacy & Security > Camera, then restart the app."
            )
            return
        try:
            tracker = BodyTracker()  # downloads the pose model on first use
        except Exception as exc:  # model download or MediaPipe start-up failed
            cap.release()
            self.status, self.error = "error", f"Body tracking couldn't start: {exc}"
            return

        self.status = "on"
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    self.status, self.error = "error", "Lost the camera feed."
                    break
                snap = tracker.process(frame)
                self._on_snapshot(snap)

                display = cv2.flip(frame, 1)  # mirror only what the user sees
                draw_skeleton(display, tracker.landmarks, mirrored=True)
                h, w = display.shape[:2]
                display = cv2.resize(display, (480, int(h * 480 / w)))
                ok, jpg = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    with self._frame_cond:
                        self._frame = jpg.tobytes()
                        self._frame_id += 1
                        self._frame_cond.notify_all()
        finally:
            tracker.close()
            cap.release()


class CompanionService:
    """Owns the brain, the optional camera, and the state everyone reads."""

    def __init__(self, native_awareness: bool = True, enable_microphone: bool = False) -> None:
        self._lock = threading.RLock()
        self.browser_backend = BrowserActivityBackend()
        self.awareness_source = "browser"
        awareness = None
        if native_awareness:
            try:
                awareness = AwarenessService()
                self.awareness_source = "native"
            except Exception as exc:  # packages missing or unsupported OS
                print(f"[companion] Native screen awareness unavailable ({exc.__class__.__name__}); "
                      "using the browser tab the extension reports.")
        if awareness is None:
            awareness = AwarenessService(backend=self.browser_backend, start_keyboard_monitor=False)

        # enable_microphone: loudness only, never recorded; a yell wakes play-dead.
        self.brain = CompanionBrain(awareness=awareness, enable_microphone=enable_microphone)
        self.camera = CameraWorker(self._on_body)
        # True once the browser extension has sent a heartbeat. The desktop
        # window can't talk to the extension, so this is how it knows.
        self.extension_seen = False
        self._update = None
        self._reaction: Reaction | None = None
        self._body = None
        self._last_hand_raise = 0.0
        self._last_lean_in = 0.0
        self._hand_was_raised = False
        self._was_leaning = False

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.tick()
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self.camera.stop()
        self.brain.close()

    def _loop(self) -> None:
        while not self._stop.wait(BRAIN_TICK_SECONDS):
            try:
                self.tick()
            except Exception as exc:  # keep the hub alive; log and carry on
                print(f"[companion] brain update failed: {exc!r}")

    def tick(self) -> None:
        with self._lock:
            self._update = self.brain.update()

    # --- inputs --------------------------------------------------------------

    def report_browser(self, title: str, host: str) -> None:
        """The user is active on a tab (title/host), or just active (both empty)."""
        if title or host:
            self.browser_backend.report(title, host)
        else:
            self.browser_backend.note_input()

    def record_browser_activity(self, payload: dict) -> None:
        """Extension heartbeat: tab title/host plus counts (clicks, keys,
        copies, pastes, scroll, active time). Never key identities or text."""
        self.extension_seen = True
        if not payload.get("left"):
            self.report_browser(str(payload.get("title", ""))[:200], str(payload.get("host", ""))[:100])
        record = getattr(self.brain.awareness, "record_browser_activity", None)
        if callable(record):
            with self._lock:
                record(payload)

    def interact(self, action: str, food: str = "fish") -> dict:
        """Apply a user interaction. Returns {accepted, message}.

        Fish is the only food; `food` is accepted for compatibility and ignored.
        """
        with self._lock:
            if action == "feed":
                result = self.brain.feed()
                if result.accepted:
                    self._react("happy", "Yum, fish! Thank you~", 3)
                    message = "fed"
                else:
                    self._react("sad", "I'm full...", 3)
                    message = result.reason
                self._update = self.brain.update()
                return {"accepted": result.accepted, "message": message}

            effect = INTERACTIONS.get(action)
            if effect is None:
                return {"accepted": False, "message": f"Unknown interaction {action!r}."}
            self.brain.apply_interaction(effect)
            self.browser_backend.note_input()
            self._update = self.brain.update()
            return {"accepted": True, "message": action}

    def _on_body(self, snap) -> None:
        """Called from the camera thread for every processed frame."""
        now = time.monotonic()
        with self._lock:
            self._body = snap
            if snap.present:
                self.browser_backend.note_input()
            reaction = BODY_REACTIONS.get(snap.event or "")
            if reaction:
                animation, message, seconds, effect = reaction
                self._react(animation, message, seconds)
                if effect:
                    self.brain.apply_interaction(effect)
            if snap.camera_moving:
                return
            if snap.hand_raised and not self._hand_was_raised and now - self._last_hand_raise > HAND_RAISE_COOLDOWN:
                self._last_hand_raise = now
                self._react("encouragement", "Hi! *waves back*", 3)
                self.brain.apply_interaction(InteractionEffect(attention_delta=5, affection_delta=1))
            if snap.leaning_in and not self._was_leaning and now - self._last_lean_in > LEAN_IN_COOLDOWN:
                self._last_lean_in = now
                self._react("encouragement", "Deep focus! You've got this.", 3)
            self._hand_was_raised = snap.hand_raised
            self._was_leaning = snap.leaning_in

    def _react(self, animation: str, message: str, seconds: float) -> None:
        self._reaction = Reaction(animation, message, time.monotonic() + seconds)

    # --- output --------------------------------------------------------------

    def state(self) -> dict:
        """Everything the website and extension show. `animation` and `message`
        follow animation_bridge.py's /api/state format."""
        with self._lock:
            update = self._update
            reaction = self._reaction
            body = self._body

        pet = update.pet
        decision = update.decision
        animation = animation_for_update(update)
        behavior = decision.behavior.value
        message = BEHAVIOR_MESSAGES.get(behavior, ANIMATION_LABELS[animation])
        if animation == "hungry":
            message = "I'm hungry... feed me?"
        elif animation == "tired" and behavior not in ("sleep", "play_dead"):
            message = "So sleepy..."
        if reaction and time.monotonic() < reaction.until:
            animation, message = reaction.animation, reaction.message

        camera_on = self.camera.status == "on"
        return {
            "animation": animation,
            "message": message,
            "pet": {
                "hunger": round(pet.hunger),
                "energy": round(pet.energy),
                "attention": round(pet.attention),
                "affection": round(pet.affection),
                "boredom": round(pet.boredom),
                "mood": pet.mood.value,
                "behavior": behavior,
                "reason": decision.reason,
            },
            "activity": {
                "type": update.screen.activity.value,
                "confidence": round(update.screen.activity_confidence, 2),
                "source": self.awareness_source,
                "user_state": getattr(update.screen.user_state, "value", None),
            },
            "feeding": {"food": "fish"},
            "camera": {"status": self.camera.status, "error": self.camera.error},
            "body": {
                "state": body.state,
                "present": body.present,
                "hand_raised": body.hand_raised,
                "leaning_in": body.leaning_in,
            } if (body and camera_on) else None,
        }
