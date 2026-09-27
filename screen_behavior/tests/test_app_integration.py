"""
UI <-> brain <-> browser-extension integration.

Runs the real app server (UI/server.py) with the real companion hub
(UI/companion.py) on a free port, and talks to it over HTTP the same way the
extension's background.js does. UI/tests/test_companion.py covers the hub's
own routes (presence, interact, camera, chat).
"""
import json
import subprocess
import unittest
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from screen_behavior.awareness.activity_tracker import ActivityStabilityTracker
from screen_behavior.awareness.browser import BrowserActivityTracker
from screen_behavior.awareness.keyboard import KeyboardActivityTracker
from screen_behavior.awareness.models import ActivityType, Shortcut, WindowInfo
from screen_behavior.awareness.service import AwarenessService
from screen_behavior.integration.presenter import (
    ANIMATIONS,
    offline_state,
    present,
)
from screen_behavior.simulation import SimBackend, SimClock
from UI import server as app_server
from UI.companion import CompanionService

ROOT = Path(__file__).resolve().parents[2]


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class NoHook:
    def start(self):
        pass

    def stop(self):
        pass


def sim_service(clock, app="chrome", keyboard_available=True):
    backend = SimBackend(clock)
    backend.foreground = WindowInfo(
        title="Google Chrome" if app == "chrome" else "main.py - Visual Studio Code",
        process_name="chrome.exe" if app == "chrome" else "Code.exe",
    )
    keyboard = KeyboardActivityTracker(clock=clock)
    keyboard.set_monitoring_available(keyboard_available)
    service = AwarenessService(
        backend=backend,
        activity_tracker=ActivityStabilityTracker(clock=clock),
        keyboard_tracker=keyboard,
        keyboard_monitor=NoHook(),
        start_keyboard_monitor=False,
        start_mouse_monitor=False,
    )
    return service, backend


HEARTBEAT = {
    "host": "www.youtube.com",
    "title": "Lofi beats - YouTube",
    "activeMs": 5000,
    "clicks": 2,
    "keys": 0,
    "copies": 1,
    "pastes": 0,
    "maxScrollPct": 40,
    "left": False,
}


class BrowserActivityTrackerTests(unittest.TestCase):
    def test_empty_is_unavailable(self):
        self.assertFalse(BrowserActivityTracker(clock=FakeClock()).snapshot().available)

    def test_heartbeat_fields_and_rolling_window(self):
        clock = FakeClock()
        tracker = BrowserActivityTracker(clock=clock)

        tracker.record(HEARTBEAT)
        clock.advance(5)
        tracker.record({**HEARTBEAT, "keys": 7, "clicks": 1})
        snap = tracker.snapshot()

        self.assertTrue(snap.available)
        self.assertTrue(snap.focused)
        self.assertEqual(snap.host, "www.youtube.com")
        self.assertEqual(snap.clicks_last_minute, 3)
        self.assertEqual(snap.keys_last_minute, 7)
        self.assertEqual(snap.copies_last_minute, 2)
        self.assertEqual(snap.seconds_since_key, 0)
        self.assertEqual(snap.scroll_pct, 40)
        self.assertAlmostEqual(snap.active_seconds_on_host, 10.0)

        clock.advance(61)
        snap = tracker.snapshot()
        self.assertEqual(snap.clicks_last_minute, 0)
        self.assertFalse(snap.available)  # stale
        self.assertEqual(snap.total_copies, 2)

    def test_leaving_the_page_is_not_focused(self):
        tracker = BrowserActivityTracker(clock=FakeClock())
        tracker.record({**HEARTBEAT, "left": True})

        self.assertFalse(tracker.snapshot().focused)

    def test_bad_values_are_ignored(self):
        tracker = BrowserActivityTracker(clock=FakeClock())
        tracker.record({"host": "x.com", "clicks": "lots", "keys": -5, "title": None})
        snap = tracker.snapshot()

        self.assertEqual(snap.clicks_last_minute, 0)
        self.assertEqual(snap.keys_last_minute, 0)


class AwarenessBrowserTests(unittest.TestCase):
    def test_extension_page_sharpens_browser_classification(self):
        clock = SimClock()
        service, _ = sim_service(clock, app="chrome")
        self.assertEqual(service.snapshot().leading_activity, ActivityType.BROWSING)

        service.record_browser_activity(HEARTBEAT)
        context = service.snapshot()

        self.assertEqual(context.leading_activity, ActivityType.VIDEO)
        self.assertEqual(context.browser.host, "www.youtube.com")

    def test_extension_page_ignored_when_browser_not_in_front(self):
        clock = SimClock()
        service, _ = sim_service(clock, app="code")

        service.record_browser_activity(HEARTBEAT)

        self.assertEqual(service.snapshot().leading_activity, ActivityType.CODING)

    def test_browser_keys_stand_in_when_os_keyboard_unavailable(self):
        clock = SimClock()
        service, _ = sim_service(clock, keyboard_available=False)
        self.assertFalse(service.snapshot().keyboard.monitoring_available)

        service.record_browser_activity({**HEARTBEAT, "keys": 12, "pastes": 2})
        keyboard = service.snapshot().keyboard

        self.assertTrue(keyboard.monitoring_available)
        self.assertTrue(keyboard.typing_active)
        self.assertEqual(keyboard.shortcut_counts[Shortcut.PASTE], 2)

    def test_os_keyboard_wins_when_available(self):
        clock = SimClock()
        service, _ = sim_service(clock, keyboard_available=True)

        service.record_browser_activity({**HEARTBEAT, "keys": 12})

        self.assertFalse(service.snapshot().keyboard.typing_active)


def fake_update(behavior="idle", mood="neutral", energy=80, hunger=20):
    return SimpleNamespace(
        decision=SimpleNamespace(
            behavior=SimpleNamespace(value=behavior),
            reason="because",
            distraction_budget=73.4,
        ),
        pet=SimpleNamespace(
            mood=SimpleNamespace(value=mood),
            special_mood=None,
            energy=energy,
            hunger=hunger,
            attention=60,
            affection=55,
            boredom=10,
        ),
        screen=SimpleNamespace(
            activity=SimpleNamespace(value="coding"),
            activity_confidence=0.912,
            user_state=SimpleNamespace(value="focused"),
            browser=None,
        ),
    )


class PresenterTests(unittest.TestCase):
    def test_payload_contract(self):
        state = present(fake_update(behavior="study_with_user"))

        for key in ["brain", "animation", "message", "pose", "onpage_mode",
                    "behavior", "mood", "needs", "user", "distraction_budget"]:
            self.assertIn(key, state)
        self.assertIn(state["animation"], ANIMATIONS)
        self.assertEqual(state["user"]["state"], "focused")
        self.assertEqual(state["distraction_budget"], 73)
        json.dumps(state)  # must be JSON-serializable

    def test_every_behavior_maps_to_valid_outputs(self):
        from screen_behavior.pet.enums import Behavior
        for behavior in Behavior:
            state = present(fake_update(behavior=behavior.value))
            self.assertIn(state["animation"], ANIMATIONS, behavior)
            self.assertIn(
                state["onpage_mode"],
                {"idle", "sleep", "wander", "follow", "cheer", "attention"},
            )
            self.assertIn(state["pose"]["eyes"], {"open", "closed", "happy"})

    def test_sleep_closes_eyes_and_sleeps_onpage(self):
        state = present(fake_update(behavior="sleep"))

        self.assertEqual(state["pose"]["eyes"], "closed")
        self.assertEqual(state["onpage_mode"], "sleep")
        self.assertEqual(state["animation"], "tired")

    def test_offline_state_is_safe_for_all_front_ends(self):
        state = offline_state()

        self.assertEqual(state["brain"], "offline")
        self.assertIn(state["animation"], ANIMATIONS)
        self.assertEqual(state["onpage_mode"], "idle")


class AppServerTests(unittest.TestCase):
    """The HTTP calls the extension's background.js makes."""

    @classmethod
    def setUpClass(cls):
        cls.companion = CompanionService(native_awareness=False)
        cls.companion.tick()
        app_server.companion = cls.companion
        cls.server = app_server.make_server("127.0.0.1", 0)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.companion.close()
        app_server.companion = None

    def get(self, path):
        with urlopen(self.url + path, timeout=3) as res:
            return json.load(res)

    def post(self, path, body):
        req = Request(
            self.url + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3) as res:
            return json.load(res)

    def test_state_has_animation_and_brain_details(self):
        state = self.get("/api/state")

        self.assertIn(state["animation"], ANIMATIONS)
        self.assertIn("reason", state["pet"])
        self.assertEqual(state["feeding"], {"food": "fish"})

    def test_feeding_gives_fish(self):
        self.companion.brain.pet.hunger = 60
        result = self.post("/api/interact", {"action": "feed", "food": "wet"})

        self.assertTrue(result["accepted"])
        self.assertLess(self.companion.brain.pet.hunger, 60)

    def test_extension_heartbeat_reaches_the_brain(self):
        result = self.post("/api/browser-activity", {**HEARTBEAT, "keys": 9})
        self.assertTrue(result["ok"])

        context = self.companion.brain.awareness.snapshot()
        self.assertEqual(context.browser.host, "www.youtube.com")
        self.assertEqual(context.browser.keys_last_minute, 9)
        # Without native awareness, the heartbeat's tab is the foreground.
        self.assertIn("youtube", context.foreground.title.lower())
        self.assertEqual(context.leading_activity, ActivityType.VIDEO)

    def test_page_and_extension_assets_load(self):
        for path in ["/", "/app.js", "/animation.js", "/extension/characters.js"]:
            with self.subTest(path), urlopen(self.url + path, timeout=3) as res:
                self.assertNotIn(b"<<<<<<<", res.read())


class RepositoryHealthTests(unittest.TestCase):
    def test_no_committed_merge_conflict_markers(self):
        """A merge committed with conflict markers breaks the whole app."""
        out = subprocess.run(
            ["git", "grep", "-l", "-E", "^(<<<<<<<|>>>>>>>) ", "--", "."],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(out.stdout.strip(), "", "files with conflict markers")


if __name__ == "__main__":
    unittest.main()
