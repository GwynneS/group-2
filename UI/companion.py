"""The companion hub behind the Buddy website and browser extension.

Connects the project's pieces into one live state:

    screen_behavior/      the pet's brain: needs, mood, behavior, feeding
    BodyTracking/         optional webcam body tracking (presence, getting up,
                          raised hand, leaning in), plus the live video feed
    UI/body.js            the same tracking in the website, when this computer
                          has no camera to use (e.g. on Vercel)
    animation_bridge.py   brain update -> emotion shown on screen

and turns what the user does (headpats, pokes, feeding, chatting, browsing)
into interactions the brain responds to.

Screen awareness uses screen_behavior's native backend when its packages are
installed (psutil, pynput, pyobjc on macOS). Otherwise it classifies the
browser tab the extension reports, using the same activity classifier.
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from animation_bridge import ANIMATION_LABELS, animation_for_update  # noqa: E402
from screen_behavior.awareness.models import ActivityType, RawScreenSnapshot, Shortcut, WindowInfo  # noqa: E402
from screen_behavior.awareness.service import AwarenessService  # noqa: E402
from screen_behavior.integration.brain import CompanionBrain  # noqa: E402
from screen_behavior.integration.presenter import present  # noqa: E402
from screen_behavior.pet.interactions import InteractionEffect  # noqa: E402

BRAIN_TICK_SECONDS = 1.0
BODY_STALE_SECONDS = 5.0

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

# Reactions to webcam body-tracking events:
# (emotion, caption, seconds, effect, voice clips from HackMp3s/ or None).
BODY_REACTIONS = {
    "user_arrived": ("happy", "There you are! Let's get started.", 4, InteractionEffect(attention_delta=10), None),
    "user_returned": ("happy", "Welcome back!", 4, InteractionEffect(attention_delta=15, affection_delta=3), "onReturn"),
    "user_left": ("sad", "Come back soon...", 5, None, None),
    "user_getting_up": ("encouragement", "Stretch break? Good idea!", 4, None, "onGetup"),
    "user_sat_back_down": ("happy", "Back to it!", 3, None, None),
}
HAND_RAISE_COOLDOWN = 10.0
LEAN_IN_COOLDOWN = 90.0

# Voice lines for things the brain notices on its own (the website plays them;
# see UI/app.js). Each one also shows its emotion and caption.
GONE_AFTER_SECONDS = 20.0         # out of the camera's view this long -> notInFrame
INACTIVE_IN_FRAME_SECONDS = 60.0  # at the desk with no keyboard/mouse input -> onInactiveINframe
TYPING_LINE_EVERY = (45.0, 60.0)  # seconds of typing per whenTyping line, picked at random each time
TYPING_PAUSE_SECONDS = 8.0        # a longer pause starts the count over
SHORTCUT_VOICE_COOLDOWN = 1.0     # per shortcut; a different shortcut can respond immediately
SHORTCUT_REACTIONS = {
    Shortcut.COPY: ("encouragement", "Copied! Nice find~", "CMDC"),
    Shortcut.PASTE: ("encouragement", "Pasted! You're on a roll~", "CMDV"),
    Shortcut.UNDO: ("encouragement", "Undo! No worries~", "CMDZ"),
}


class BrowserActivityBackend:
    """Screen awareness from the browser tab the user is on.

    Stands in for screen_behavior's native backend when its packages aren't
    installed. The extension and website report the focused tab's title and
    host; that becomes the "foreground window" the activity classifier reads.
    """

    def __init__(self, clock=None) -> None:
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic
        self._title = ""
        self._last_input = self._clock()

    def report(self, title: str, host: str) -> None:
        with self._lock:
            self._title = f"{title} - {host}".strip(" -")[:300]

    def note_input(self, age_seconds: float = 0.0) -> None:
        # Reporting old input again must not make it look new.
        with self._lock:
            self._last_input = max(self._last_input, self._clock() - age_seconds)

    def snapshot(self) -> RawScreenSnapshot:
        with self._lock:
            title = self._title
            idle = max(0.0, self._clock() - self._last_input)
        return RawScreenSnapshot(
            idle_seconds=idle,
            foreground=WindowInfo(title=title, app_name="Google Chrome") if title else None,
        )


@dataclass
class Reaction:
    animation: str
    message: str
    until: float
    voice: str | None = None  # a trigger in HackMp3s/, e.g. "onReturn"
    id: int = 0


@dataclass
class BrowserBody:
    """A body-tracking result from the website's webcam (UI/body.js runs
    BodyTracking/tracking.py's rules in the browser): the fields of
    tracking.BodySnapshot the companion reads."""

    state: str  # "at_desk" | "getting_up" | "away"
    present: bool
    event: str | None
    away_seconds: float
    hand_raised: bool
    leaning_in: bool
    camera_moving: bool = False  # body.js can't tell (see its header)


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
        except Exception as exc:
            self.status, self.error = "error", f"Body tracking stopped: {exc}"
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
        self._update_at: float | None = None
        self._updated_at: float | None = None
        self._reaction: Reaction | None = None
        self._reaction_id = 0
        self._voice_session = uuid.uuid4().hex
        self._voice_claim = None
        self._body = None
        self._body_at: float | None = None
        self._body_source = "native"  # or "browser": record_browser_body
        self._last_hand_raise = 0.0
        self._last_lean_in = 0.0
        self._hand_was_raised = False
        self._was_leaning = False
        self._gone_announced = False
        self._inactive_announced = False
        self._shortcut_counts: dict | None = None  # from the previous tick
        self._last_shortcut_voice = float("-inf")
        self._shortcut_voice_at: dict = {}
        self._browser_shortcut_at: dict = {}
        self._browser_immediate_until = 0.0
        self._typing_since: float | None = None
        self._typing_due = 0.0  # seconds of typing until the next whenTyping line

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
            now = time.monotonic()
            body = self._fresh_body(now)
            self.brain.awareness.set_user_present(
                bool(body.present) if body is not None else None
            )
            self._update = self.brain.update()
            self._update_at, self._updated_at = time.monotonic(), time.time()
            self._voice_for_screen(self._update.screen, now)

    def _fresh_body(self, now: float):
        """Only a live, stable camera can provide physical-presence evidence:
        this computer's while it runs, or the website's while it keeps reporting."""
        if (
            (self.camera.status == "on" or self._body_source == "browser")
            and self._body is not None
            and self._body_at is not None
            and 0 <= now - self._body_at <= BODY_STALE_SECONDS
            and not self._body.camera_moving
        ):
            return self._body
        return None

    @property
    def keyboard_status(self) -> str:
        """Key tracking in every app: "on", "needs_permission" (macOS Input
        Monitoring), "unavailable", or "off" (browser extension only)."""
        if self.awareness_source != "native":
            return "off"
        return getattr(getattr(self.brain.awareness, "keyboard_monitor", None), "status", "off")

    # --- inputs --------------------------------------------------------------

    def report_browser(self, title: str, host: str) -> None:
        """Page metadata only; an open page is not proof of user input."""
        if title or host:
            self.browser_backend.report(title, host)

    def note_browser_input(self, age_seconds: float = 0.0) -> None:
        """Actual input, kept separate from page metadata and camera presence."""
        if math.isfinite(age_seconds) and age_seconds >= 0:
            self.browser_backend.note_input(age_seconds)

    def record_browser_activity(self, payload: dict) -> None:
        """Extension heartbeat: tab title/host plus counts (clicks, keys,
        copies, pastes, scroll, active time). Never key identities or text."""
        self.extension_seen = True
        if payload.get("shortcutsImmediate") is True:
            self._browser_immediate_until = time.monotonic() + 10.0
        if not payload.get("left"):
            self.report_browser(str(payload.get("title", ""))[:200], str(payload.get("host", ""))[:100])
        if "inputAgeMs" in payload:
            age = payload["inputAgeMs"]
            if isinstance(age, (int, float)) and not isinstance(age, bool):
                self.note_browser_input(age / 1000.0)
        else:
            # Older extensions can still report real key/click counts.
            # activeMs, focus and maximum scroll position are not input.
            for key in ("clicks", "keys", "copies", "pastes"):
                value = payload.get(key, 0)
                if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                    self.note_browser_input()
                    break
        record = getattr(self.brain.awareness, "record_browser_activity", None)
        if callable(record):
            with self._lock:
                record(payload)

    def record_browser_shortcut(self, name: str) -> bool:
        """Immediate semantic event only: never text, key history or clipboard data."""
        try:
            shortcut = Shortcut(name)
        except ValueError:
            return False
        if shortcut not in SHORTCUT_REACTIONS:
            return False
        with self._lock:
            now = time.monotonic()
            self.note_browser_input()
            self._browser_immediate_until = now + 10.0
            self._browser_shortcut_at[shortcut] = now
            self._say_shortcut(shortcut, now)
        return True

    def _say_shortcut(self, shortcut, now: float) -> None:
        if now - self._shortcut_voice_at.get(shortcut, float("-inf")) < SHORTCUT_VOICE_COOLDOWN:
            return
        self._shortcut_voice_at[shortcut] = now
        self._last_shortcut_voice = now
        animation, message, voice = SHORTCUT_REACTIONS[shortcut]
        self._react(animation, message, 2.5, voice)

    def claim_voice(self, key: str, owner: str, release: bool = False) -> bool:
        """One player per live reaction across website tabs and the extension."""
        with self._lock:
            if release:
                if self._voice_claim == (key, owner):
                    self._voice_claim = None
                    return True
                return False
            reaction = self._reaction
            if (not owner or not reaction or not reaction.voice
                    or time.monotonic() >= reaction.until
                    or key != f"{self._voice_session}:{reaction.id}"
                    or (self._voice_claim and self._voice_claim[0] == key)):
                return False
            self._voice_claim = (key, owner)
            return True

    def interact(self, action: str, food: str = "fish") -> dict:
        """Apply a user interaction. Returns {accepted, message}.

        Fish is the only food; `food` is accepted for compatibility and ignored.
        """
        with self._lock:
            if action == "feed":
                self.browser_backend.note_input()
                result = self.brain.feed()
                if result.accepted:
                    self._react("happy", "Yum, fish! Thank you~", 3)
                    message = "fed"
                else:
                    self._react("sad", "I'm full...", 3)
                    message = result.reason
                self._update = self.brain.update()
                self._update_at, self._updated_at = time.monotonic(), time.time()
                return {"accepted": result.accepted, "message": message}

            effect = INTERACTIONS.get(action)
            if effect is None:
                return {"accepted": False, "message": f"Unknown interaction {action!r}."}
            self.brain.apply_interaction(effect)
            self.browser_backend.note_input()
            self._update = self.brain.update()
            self._update_at, self._updated_at = time.monotonic(), time.time()
            return {"accepted": True, "message": action}

    def record_browser_body(self, payload: dict) -> bool:
        """A body-tracking result from the website's webcam (UI/body.js), or
        {"camera": "off"} when the page stops it. Only these signals arrive,
        never video. Ignored (returns False) while this computer's own camera runs."""
        if self.camera.status in ("on", "starting"):
            return False
        if payload.get("camera") == "off":
            with self._lock:
                if self._body_source == "browser":
                    self._body = self._body_at = None
            self.tick()
            return True
        present = payload.get("present") is True
        state = payload.get("state")
        if not present:
            state = "away"
        elif state not in ("at_desk", "getting_up"):
            state = "at_desk"
        event = payload.get("event")
        away = payload.get("away_seconds")
        if isinstance(away, bool) or not isinstance(away, (int, float)) or not math.isfinite(away):
            away = 0.0
        self._on_body(BrowserBody(
            state=state,
            present=present,
            event=event if event in BODY_REACTIONS else None,
            away_seconds=min(max(float(away), 0.0), 24 * 3600.0),
            hand_raised=payload.get("hand_raised") is True,
            leaning_in=payload.get("leaning_in") is True,
        ), source="browser")
        return True

    def _on_body(self, snap, source: str = "native") -> None:
        """Called for every processed frame: from the camera thread, or with
        source="browser" from record_browser_body."""
        now = time.monotonic()
        with self._lock:
            self._body = snap
            self._body_at = now
            self._body_source = source
            if snap.camera_moving:
                self.brain.awareness.set_user_present(None)
                return
            self.brain.awareness.set_user_present(bool(snap.present))
            reaction = BODY_REACTIONS.get(snap.event or "")
            if reaction:
                animation, message, seconds, effect, voice = reaction
                self._react(animation, message, seconds, voice)
                if effect:
                    self.brain.apply_interaction(effect)
            # "user_left" comes after a few seconds; completely gone is later.
            if snap.present:
                self._gone_announced = False
            elif snap.away_seconds >= GONE_AFTER_SECONDS and not self._gone_announced:
                self._gone_announced = True
                self._react("sad", "Where did you go...?", 5, "notInFrame")
            if snap.hand_raised and not self._hand_was_raised and now - self._last_hand_raise > HAND_RAISE_COOLDOWN:
                self._last_hand_raise = now
                self._react("encouragement", "Hi! *waves back*", 3)
                self.brain.apply_interaction(InteractionEffect(attention_delta=5, affection_delta=1))
            if snap.leaning_in and not self._was_leaning and now - self._last_lean_in > LEAN_IN_COOLDOWN:
                self._last_lean_in = now
                self._react("encouragement", "Deep focus! You've got this.", 3)
            self._hand_was_raised = snap.hand_raised
            self._was_leaning = snap.leaning_in

    def _voice_for_screen(self, screen, now: float) -> None:
        """Reactions, with voice lines, to copy/paste/undo and typing in any
        app, and to sitting at the desk without touching anything."""
        keyboard = screen.keyboard
        if keyboard is not None:
            counts = dict(keyboard.shortcut_counts)
            if self._shortcut_counts is not None:
                new = [s for s, n in counts.items()
                       if s in SHORTCUT_REACTIONS and n > self._shortcut_counts.get(s, 0)]
                native_keys = self.brain.awareness.keyboard_tracker.snapshot().monitoring_available
                if not native_keys and now < self._browser_immediate_until:
                    new = []  # these browser counts already had immediate events
                new = [s for s in new if now - self._browser_shortcut_at.get(s, float("-inf")) > 2.0]
                if new:
                    shortcut = keyboard.last_shortcut if keyboard.last_shortcut in new else new[0]
                    self._say_shortcut(shortcut, now)
            self._shortcut_counts = counts

            since_key = keyboard.seconds_since_last_keypress
            if since_key is not None and since_key <= TYPING_PAUSE_SECONDS:
                if self._typing_since is None or now - self._typing_since >= self._typing_due:
                    if self._typing_since is not None:
                        self._react("encouragement", "Look at you go!", 4, "whenTyping")
                    self._typing_since = now
                    self._typing_due = random.uniform(*TYPING_LINE_EVERY)
            else:
                self._typing_since = None

        # Inactivity and presence are separate in both native and browser modes.
        # A stale or uncertain camera must not trigger an in-frame voice line.
        body = self._fresh_body(now)
        inactive = (
            body is not None and body.present and body.state == "at_desk"
            and screen.idle_seconds >= INACTIVE_IN_FRAME_SECONDS
            and screen.activity != ActivityType.VIDEO  # watching is fine
        )
        if not inactive:
            self._inactive_announced = False
        elif not self._inactive_announced:
            self._inactive_announced = True
            self._react("tired", "Still with me...?", 5, "onInactiveINframe")

    def _react(self, animation: str, message: str, seconds: float, voice: str | None = None) -> None:
        self._reaction_id += 1
        self._reaction = Reaction(animation, message, time.monotonic() + seconds, voice, self._reaction_id)

    # --- output --------------------------------------------------------------

    def state(self) -> dict:
        """Everything the website and extension show. `animation` and `message`
        follow animation_bridge.py's /api/state format."""
        with self._lock:
            update = self._update
            reaction = self._reaction
            body = self._fresh_body(time.monotonic())
            decision_age_ms = max(0.0, time.monotonic() - self._update_at) * 1000
            updated_at = self._updated_at

        pet = update.pet
        decision = update.decision
        animation = animation_for_update(update)
        behavior = decision.behavior.value
        message = BEHAVIOR_MESSAGES.get(behavior, ANIMATION_LABELS[animation])
        if animation == "hungry":
            message = "I'm hungry... feed me?"
        elif animation == "tired" and behavior not in ("sleep", "play_dead"):
            message = "So sleepy..."
        voice = None
        now = time.monotonic()
        if reaction and now < reaction.until:
            animation, message = reaction.animation, reaction.message
            if reaction.voice:
                # seconds: how long this reaction (and its caption) still shows.
                voice = {"id": reaction.id, "trigger": reaction.voice, "seconds": round(reaction.until - now, 2),
                         "key": f"{self._voice_session}:{reaction.id}"}

        return {
            **present(update),
            "updated_at": updated_at,
            "decision_age_ms": round(decision_age_ms),
            "animation": animation,
            "message": message,
            # A line to say with this reaction; the page plays each id once.
            "voice": voice,
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
                "user_present": update.screen.user_present,
                "idle_seconds": round(update.screen.idle_seconds, 1),
                "away_inferred": (
                    update.screen.user_state is not None
                    and update.screen.user_state.value == "away"
                    and update.screen.user_present is None
                ),
            },
            "feeding": {"food": "fish"},
            "camera": {"status": self.camera.status, "error": self.camera.error},
            "body": {
                "state": body.state,
                "present": body.present,
                "hand_raised": body.hand_raised,
                "leaning_in": body.leaning_in,
            } if body else None,  # _fresh_body: only from a live camera
        }
