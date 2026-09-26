"""
Webcam body tracking with MediaPipe Pose.

Run from the repo root:
    python BodyTracking/tracking.py

Press Q (or Esc) in the camera window to quit.
"""

from __future__ import annotations

import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
MODEL_PATH = Path(__file__).parent / "models" / "pose_landmarker_lite.task"


class LM:
    """Indices into MediaPipe's 33 pose landmarks."""

    NOSE = 0
    LEFT_EAR = 7
    RIGHT_EAR = 8
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_WRIST = 15
    RIGHT_WRIST = 16


# Skeleton lines to draw, as (start, end) landmark index pairs.
CONNECTIONS = [
    # face
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    # torso
    (11, 12), (11, 23), (12, 24), (23, 24),
    # arms and hands
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    # legs and feet
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
]

# Landmarks below this visibility are treated as not seen.
MIN_VISIBILITY = 0.5


# Presence: ignore short tracking dropouts so the pet doesn't overreact.
AWAY_AFTER_SECONDS = 3.0     # not at the desk this long -> user has left
RETURN_AFTER_SECONDS = 0.7   # back at the desk this long -> user is back
# Seen but much smaller than normal = walking around the room, not at the desk.
FAR_AWAY_RATIO = 0.5

# Getting up: user is still in view but standing / backing away from the desk.
GETTING_UP_AFTER_SECONDS = 0.8   # signs of getting up this long -> "user_getting_up"
SAT_BACK_AFTER_SECONDS = 1.0     # normal again this long -> "user_sat_back_down"
# Shoulders this much higher than seated (fraction of frame) counts as standing.
# Only shoulders are used: leaning in can move the head a lot, but shoulders at most ~0.13,
# while standing raised them 0.23-0.70 in testing.
STAND_RISE = 0.20
SIT_RISE = 0.10                  # back within this of seated height = sat back down

# Camera movement: if the top corners of the picture (usually wall behind the user) shift
# together, the camera moved, not the user. Pause and re-learn the seated position.
CAMERA_SHIFT_PX = 2.0            # corner shift (in a 160px-wide copy of the frame) = camera moved
CAMERA_COMPARE_SECONDS = 0.3     # compare against the frame from this long ago
CAMERA_SETTLE_SECONDS = 1.0      # still for this long after moving -> recalibrate

# Leaning in: compare against the user's normal distance, measured after they sit down.
CALIBRATION_SECONDS = 2.0
CALIBRATION_MAX_WOBBLE = 0.10  # nose/shoulders must stay within this range to lock in
LEAN_IN_RATIO = 1.3          # 30% closer than normal counts as leaning in


@dataclass
class BodySnapshot:
    """High-level body signals the pet can react to."""

    # "at_desk" | "getting_up" | "away"
    state: str = "away"
    # Debounced: True for at_desk and getting_up, flips after AWAY_AFTER_SECONDS.
    present: bool = False
    # Set for exactly one frame when something changes, else None:
    #   "user_arrived"        first time someone sits down
    #   "user_getting_up"     standing up / backing away, but still in view
    #   "user_sat_back_down"  was getting up, settled back at the desk
    #   "user_left"           gone (out of view or far away) for AWAY_AFTER_SECONDS
    #   "user_returned"       back after leaving
    event: Optional[str] = None
    # How long the user has been gone (0 while present).
    away_seconds: float = 0.0
    # How long the user has been getting up (0 unless state == "getting_up").
    getting_up_seconds: float = 0.0
    # On "user_returned", how long they were gone.
    last_away_seconds: float = 0.0

    left_hand_raised: bool = False
    right_hand_raised: bool = False
    # Shoulder width as a fraction of frame width. Bigger = closer to camera.
    closeness: float = 0.0
    # Ear-to-ear width; stays in frame when the user is very close.
    face_size: float = 0.0
    leaning_in: bool = False
    # True while the camera is being moved/adjusted; ignore body signals meanwhile.
    camera_moving: bool = False

    # Internal raw measurements (0 = not visible), used for calibration.
    _shoulder_y: float = 0.0
    _nose_y: float = 0.0

    @property
    def hand_raised(self) -> bool:
        return self.left_hand_raised or self.right_hand_raised


class PresenceTracker:
    """Turns noisy per-frame detections into stable present / away state."""

    def __init__(self) -> None:
        self.present = False
        self._seen_since: Optional[float] = None
        self._unseen_since: Optional[float] = None
        self._away_since: Optional[float] = None
        self._ever_present = False

    def update(self, seen: bool, now: float, snap: BodySnapshot) -> None:
        if seen:
            self._unseen_since = None
            if self._seen_since is None:
                self._seen_since = now
            if not self.present and now - self._seen_since >= RETURN_AFTER_SECONDS:
                self.present = True
                if self._ever_present:
                    snap.event = "user_returned"
                    snap.last_away_seconds = now - self._away_since
                else:
                    snap.event = "user_arrived"
                    self._ever_present = True
                self._away_since = None
        else:
            self._seen_since = None
            if self._unseen_since is None:
                self._unseen_since = now
            if self.present and now - self._unseen_since >= AWAY_AFTER_SECONDS:
                self.present = False
                snap.event = "user_left"
                self._away_since = self._unseen_since

        snap.present = self.present
        if not self.present and self._away_since is not None:
            snap.away_seconds = now - self._away_since


class GettingUpDetector:
    """Debounces per-frame "looks like they're getting up" into getting_up state."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.getting_up = False
        self._since: Optional[float] = None   # when getting_up signal started
        self._settled_since: Optional[float] = None
        self._getting_up_at: Optional[float] = None

    def update(self, signal: Optional[bool], now: float, snap: BodySnapshot) -> None:
        if signal is None:
            pass  # can't tell this frame; keep current state and timers
        elif signal:
            self._settled_since = None
            if self._since is None:
                self._since = now
            if not self.getting_up and snap.event is None and now - self._since >= GETTING_UP_AFTER_SECONDS:
                self.getting_up = True
                self._getting_up_at = self._since
                snap.event = "user_getting_up"
        else:
            self._since = None
            if self._settled_since is None:
                self._settled_since = now
            if self.getting_up and snap.event is None and now - self._settled_since >= SAT_BACK_AFTER_SECONDS:
                self.getting_up = False
                self._getting_up_at = None
                snap.event = "user_sat_back_down"

        if self.getting_up:
            snap.getting_up_seconds = now - self._getting_up_at


class SeatedBaseline:
    """Learns how the user normally sits from the first steady CALIBRATION_SECONDS stretch."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.ready = False
        self.closeness = self.face_size = self.shoulder_y = self.nose_y = 0.0
        self._samples: deque = deque()  # (time, closeness, face_size, shoulder_y, nose_y)

    def update(self, snap: "BodySnapshot", now: float) -> None:
        if self.ready:
            return
        # Only learn from a normal upright pose: facing the camera, nose well above shoulders.
        if not snap._nose_y or not snap._shoulder_y or snap.face_size < 0.05:
            return
        if snap._shoulder_y - snap._nose_y < 0.15:
            return
        self._samples.append((now, snap.closeness, snap.face_size, snap._shoulder_y, snap._nose_y))
        while now - self._samples[0][0] > CALIBRATION_SECONDS:
            self._samples.popleft()
        if now - self._samples[0][0] < CALIBRATION_SECONDS * 0.9 or len(self._samples) < 10:
            return

        def column(i: int) -> list:
            return sorted(x[i] for x in self._samples if x[i] > 0)

        def spread(i: int) -> float:
            # 10th-90th percentile range, so a few glitchy frames don't count.
            vals = column(i)
            return vals[len(vals) * 9 // 10] - vals[len(vals) // 10]

        if spread(3) > CALIBRATION_MAX_WOBBLE or spread(4) > CALIBRATION_MAX_WOBBLE:
            return  # not steady yet; keep sliding the window

        def median(i: int) -> float:
            vals = column(i)
            return vals[len(vals) // 2] if vals else 0.0

        self.closeness, self.face_size, self.shoulder_y, self.nose_y = (median(i) for i in (1, 2, 3, 4))
        self.ready = True


class CameraMotionDetector:
    """Detects the camera itself moving by watching the top-left and top-right corners."""

    SIZE = (160, 120)
    CORNER_W, CORNER_H = 48, 40

    def __init__(self) -> None:
        self._window = cv2.createHanningWindow((self.CORNER_W, self.CORNER_H), cv2.CV_32F)
        self._ref = None
        self._ref_time = 0.0
        self._moving_until = 0.0
        self.last_shift = 0.0

    def _corners(self, frame_bgr):
        small = cv2.resize(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY), self.SIZE).astype("float32")
        return small[: self.CORNER_H, : self.CORNER_W], small[: self.CORNER_H, -self.CORNER_W :]

    def _shift(self, a, b):
        # phaseCorrelate modifies its inputs in place (OpenCV 4.11), so hand it copies.
        return cv2.phaseCorrelate(a.copy(), b.copy(), self._window)

    def _body_in_corners(self, lms) -> bool:
        """True if any visible body part is in (or near) either top corner."""
        if lms is None:
            return False
        margin = 0.05
        max_x = self.CORNER_W / self.SIZE[0] + margin
        max_y = self.CORNER_H / self.SIZE[1] + margin
        for p in lms:
            if p.visibility >= 0.3 and p.y < max_y and (p.x < max_x or p.x > 1 - max_x):
                return True
        return False

    def update(self, frame_bgr, now: float, lms=None) -> bool:
        """Returns True while the camera is moving or hasn't settled yet."""
        if self._body_in_corners(lms):
            # The user (standing up, raising a hand...) is in the corners, so movement there
            # tells us nothing about the camera. Start fresh once the corners are clear.
            self._ref = None
            return now < self._moving_until
        corners = self._corners(frame_bgr)
        if self._ref is None:
            self._ref, self._ref_time = corners, now
            return False

        (lx, ly), _ = self._shift(self._ref[0], corners[0])
        (rx, ry), _ = self._shift(self._ref[1], corners[1])
        left, right = (lx * lx + ly * ly) ** 0.5, (rx * rx + ry * ry) ** 0.5
        self.last_shift = min(left, right)
        # Both corners moved, in the same direction -> the whole picture moved.
        if min(left, right) >= CAMERA_SHIFT_PX and lx * rx + ly * ry > 0:
            self._moving_until = now + CAMERA_SETTLE_SECONDS

        if now - self._ref_time >= CAMERA_COMPARE_SECONDS:
            self._ref, self._ref_time = corners, now
        return now < self._moving_until


def ensure_model() -> Path:
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading pose model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


class BodyTracker:
    def __init__(self) -> None:
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model())),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._start = time.monotonic()
        self._presence = PresenceTracker()
        self._seated = SeatedBaseline()
        self._getting_up = GettingUpDetector()
        self._camera = CameraMotionDetector()
        self._camera_was_moving = False
        self.landmarks = None

    def process(self, frame_bgr) -> BodySnapshot:
        """Pass the raw (unmirrored) camera frame so left/right stay correct."""
        now = time.monotonic()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        result = self._landmarker.detect_for_video(image, int((now - self._start) * 1000))
        self.landmarks = result.pose_landmarks[0] if result.pose_landmarks else None

        snap = self._read_pose(self.landmarks)
        self._presence.update(self._at_desk(snap), now, snap)

        if snap.event in ("user_arrived", "user_returned"):
            self._seated.reset()  # they may sit differently this time

        snap.camera_moving = self._camera.update(frame_bgr, now, self.landmarks)
        if snap.camera_moving:
            self._camera_was_moving = True
        elif self._camera_was_moving:
            # Camera settled in a new position: re-learn how they sit, quietly.
            self._camera_was_moving = False
            self._seated.reset()
            self._getting_up.reset()

        if not snap.present:
            self._getting_up.reset()
            snap.state = "away"
            return snap

        if snap.camera_moving:
            pass  # everything looks shifted; don't judge or learn until it settles
        elif not self._seated.ready:
            self._seated.update(snap, now)  # still learning how they normally sit
        else:
            self._getting_up.update(self._looks_like_getting_up(snap), now, snap)

        snap.state = "getting_up" if self._getting_up.getting_up else "at_desk"
        if self._seated.ready and snap.state == "at_desk":
            snap.leaning_in = snap.face_size > self._seated.face_size * LEAN_IN_RATIO
        return snap

    def _looks_like_getting_up(self, snap: BodySnapshot) -> Optional[bool]:
        """True = standing up, False = seated normally, None = can't tell (keep current state).

        Only a clear rise of the shoulders counts. Head position and width-based checks
        (shoulders/face looking narrower) misfire on leans and head tilts.
        """
        if not self._body_seen(self.landmarks):
            return None  # out of view: PresenceTracker decides if they've left
        if not snap._shoulder_y:
            return None  # shoulders not visible
        # How much higher than when seated (y grows downward, so positive = higher).
        rise = self._seated.shoulder_y - snap._shoulder_y
        if rise >= STAND_RISE:
            return True
        if rise <= SIT_RISE:
            return False
        return None  # in between: keep current state so it doesn't flicker

    def _at_desk(self, snap: BodySnapshot) -> bool:
        if not self._body_seen(self.landmarks):
            return False
        normal = self._seated.closeness if self._seated.ready else 0.0
        # closeness is 0 when a shoulder is out of frame (e.g. very close), so only
        # a small but nonzero width means "far away".
        if normal and 0 < snap.closeness < normal * FAR_AWAY_RATIO:
            return False
        return True

    def close(self) -> None:
        self._landmarker.close()

    @staticmethod
    def _body_seen(lms) -> bool:
        if lms is None:
            return False
        return any(lms[i].visibility >= MIN_VISIBILITY for i in (LM.NOSE, LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER))

    @staticmethod
    def _read_pose(lms) -> BodySnapshot:
        snap = BodySnapshot()
        if lms is None:
            return snap

        def seen(i: int) -> bool:
            return lms[i].visibility >= MIN_VISIBILITY

        # y grows downward, so "above" means a smaller y.
        if seen(LM.LEFT_WRIST) and seen(LM.LEFT_SHOULDER):
            snap.left_hand_raised = lms[LM.LEFT_WRIST].y < lms[LM.LEFT_SHOULDER].y
        if seen(LM.RIGHT_WRIST) and seen(LM.RIGHT_SHOULDER):
            snap.right_hand_raised = lms[LM.RIGHT_WRIST].y < lms[LM.RIGHT_SHOULDER].y

        if seen(LM.LEFT_SHOULDER) and seen(LM.RIGHT_SHOULDER):
            snap.closeness = abs(lms[LM.LEFT_SHOULDER].x - lms[LM.RIGHT_SHOULDER].x)
        if seen(LM.LEFT_EAR) and seen(LM.RIGHT_EAR):
            snap.face_size = abs(lms[LM.LEFT_EAR].x - lms[LM.RIGHT_EAR].x)

        shoulders_y = [lms[i].y for i in (LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER) if seen(i)]
        if shoulders_y:
            snap._shoulder_y = sum(shoulders_y) / len(shoulders_y)
        if seen(LM.NOSE) and lms[LM.NOSE].y > 0:
            snap._nose_y = lms[LM.NOSE].y

        return snap


def draw_skeleton(frame, lms, mirrored: bool = True) -> None:
    if lms is None:
        return
    h, w = frame.shape[:2]
    points = [(int((1 - p.x if mirrored else p.x) * w), int(p.y * h)) for p in lms]
    visible = [p.visibility >= MIN_VISIBILITY for p in lms]

    for start, end in CONNECTIONS:
        if visible[start] and visible[end]:
            cv2.line(frame, points[start], points[end], (255, 255, 255), 2)
    for pt, vis in zip(points, visible):
        if vis:
            cv2.circle(frame, pt, 4, (0, 200, 255), -1)


def draw_status(frame, snap: BodySnapshot, fps: float) -> None:
    lines = [
        f"FPS: {fps:4.1f}",
        f"state: {snap.state}"
        + (f"  (away {snap.away_seconds:.0f}s)" if snap.state == "away" and snap.away_seconds else "")
        + (f"  ({snap.getting_up_seconds:.1f}s)" if snap.state == "getting_up" else ""),
        f"hand raised: L={snap.left_hand_raised} R={snap.right_hand_raised}",
        f"closeness: {snap.closeness:.2f}  face: {snap.face_size:.2f}" + ("  (leaning in!)" if snap.leaning_in else ""),
    ]
    if snap.camera_moving:
        lines.append("camera moving - will recalibrate")
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (10, 25 + i * 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)


def main(camera_index: int = 0) -> None:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise SystemExit(
            "Could not open the webcam. On macOS, allow camera access for your terminal / VS Code "
            "in System Settings > Privacy & Security > Camera, then restart it."
        )

    tracker = BodyTracker()
    last = time.monotonic()
    fps = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Lost camera frame, stopping.")
                break

            snap = tracker.process(frame)
            now = time.monotonic()

            if snap.event == "user_returned":
                print(f"[event] user_returned after {snap.last_away_seconds:.1f}s away")
            elif snap.event:
                print(f"[event] {snap.event}")

            fps = 0.9 * fps + 0.1 * (1.0 / max(now - last, 1e-6))
            last = now

            display = cv2.flip(frame, 1)  # mirror only what the user sees
            draw_skeleton(display, tracker.landmarks, mirrored=True)
            draw_status(display, snap, fps)
            cv2.imshow("CatBoy body tracking (Q to quit)", display)

            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        tracker.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
