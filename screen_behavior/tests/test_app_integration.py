"""
UI <-> brain <-> browser-extension integration.

Runs the real app server (UI/server.py) on a free port with a real brain
fed by simulated sensors, and talks to it over HTTP the same way UI/app.js,
UI/animation.js and the extension's background.js do.
"""
import json
import random
import unittest
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from screen_behavior.awareness.activity_tracker import ActivityStabilityTracker
from screen_behavior.awareness.browser import BrowserActivityTracker
from screen_behavior.awareness.keyboard import KeyboardActivityTracker
from screen_behavior.awareness.models import ActivityType, Shortcut, WindowInfo
from screen_behavior.awareness.service import AwarenessService
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.integration.presenter import (
    ANIMATIONS,
    offline_state,
    present,
)
from screen_behavior.integration.runtime import BuddyRuntime
from screen_behavior.pet.behavior import BehaviorEngine
from screen_behavior.simulation import SimBackend, SimClock
from UI.server import make_server


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


def make_runtime(clock):
    service, backend = sim_service(clock)
    brain = CompanionBrain(
        awareness=service,
        behavior=BehaviorEngine(rng=random.Random(3), clock=clock),
        clock=clock,
    )
    return BuddyRuntime(lambda: brain), backend


class AppServerTests(unittest.TestCase):
    """The same HTTP calls UI/app.js, animation.js and background.js make."""

    def setUp(self):
        self.clock = SimClock()
        self.runtime, self.backend = make_runtime(self.clock)
        self.runtime.tick()
        self.server = make_server("127.0.0.1", 0, runtime=self.runtime)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

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

    def test_state_route_serves_presented_brain_state(self):
        state = self.get("/api/state")

        self.assertEqual(state["brain"], "running")
        self.assertIn(state["animation"], ANIMATIONS)
        self.assertIn("hunger", state["needs"])

    def test_status_reports_brain(self):
        self.assertEqual(self.get("/api/status")["brain"], "running")

    def test_page_loads_both_animation_scripts(self):
        with urlopen(self.url + "/", timeout=3) as res:
            page = res.read().decode()

        self.assertNotIn("<<<<<<<", page)
        self.assertIn("app.js", page)
        self.assertIn("animation.js", page)
        self.assertIn('id="buddy-sprite"', page)
        self.assertIn('id="buddy-canvas"', page)
        self.assertIn('id="feed-button"', page)

    def test_feed_reaches_the_brain(self):
        self.runtime.brain.pet.hunger = 60

        first = self.post("/api/feed", {})
        self.runtime.brain.pet.hunger = 5
        second = self.post("/api/feed", {})

        self.assertTrue(first["accepted"])
        self.assertFalse(second["accepted"])

    def test_headpat_reaches_the_brain(self):
        before = self.runtime.brain.pet.attention

        self.post("/api/interact", {"type": "pet"})

        self.assertGreater(self.runtime.brain.pet.attention, before)
        self.assertTrue(
            self.runtime.brain.behavior.memory_snapshot().recently_interacted_with
        )

    def test_unknown_interaction_is_rejected(self):
        with self.assertRaises(HTTPError) as ctx:
            self.post("/api/interact", {"type": "tickle"})
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

    def test_extension_heartbeat_changes_what_the_brain_sees(self):
        self.post("/api/browser-activity", HEARTBEAT)
        self.clock.value += 1
        state = self.runtime.tick()

        self.assertEqual(state["user"]["host"], "www.youtube.com")
        self.assertEqual(
            self.runtime.brain.awareness.snapshot().leading_activity,
            ActivityType.VIDEO,
        )


class NoBrainServerTests(unittest.TestCase):
    def test_ui_still_works_without_brain(self):
        server = make_server("127.0.0.1", 0)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urlopen(url + "/api/state", timeout=3) as res:
                self.assertEqual(json.load(res)["brain"], "offline")
            req = Request(url + "/api/feed", data=b"{}", method="POST")
            with self.assertRaises(HTTPError) as ctx:
                urlopen(req, timeout=3)
            self.assertEqual(ctx.exception.code, 503)
            ctx.exception.close()
        finally:
            server.shutdown()
            server.server_close()


class RuntimeTests(unittest.TestCase):
    def test_background_loop_updates_state_and_stops(self):
        clock = SimClock()
        runtime, _ = make_runtime(clock)
        runtime._interval = 0.01
        seen = []
        runtime.add_listener(seen.append)

        runtime.start()
        try:
            import time
            deadline = time.time() + 2
            while len(seen) < 3 and time.time() < deadline:
                time.sleep(0.01)
        finally:
            runtime.stop()

        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual(runtime.state()["brain"], "running")


if __name__ == "__main__":
    unittest.main()
