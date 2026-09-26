"""Tests for the companion hub (UI/companion.py) and the app server routes.

    python3 -m unittest discover -s UI/tests
"""

import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(UI_DIR))

import companion as companion_module  # noqa: E402
import server  # noqa: E402
from companion import CompanionService  # noqa: E402

ANIMATIONS = {"lounging", "happy", "sad", "tired", "angry", "hungry", "encouragement"}


def body(event=None, present=True, hand_raised=False, leaning_in=False, camera_moving=False):
    return SimpleNamespace(
        event=event, present=present, state="at_desk" if present else "away",
        hand_raised=hand_raised, leaning_in=leaning_in, camera_moving=camera_moving,
    )


class CompanionServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CompanionService(native_awareness=False)
        self.service.tick()

    def tearDown(self):
        self.service.close()

    def test_state_follows_animation_bridge_format(self):
        state = self.service.state()
        self.assertIn(state["animation"], ANIMATIONS)
        self.assertIsInstance(state["message"], str)
        for need in ("hunger", "energy", "attention", "affection", "boredom"):
            self.assertIn(need, state["pet"])
        self.assertEqual(state["activity"]["source"], "browser")

    def test_headpat_raises_affection_and_attention(self):
        before = self.service.state()["pet"]
        result = self.service.interact("pet")
        after = self.service.state()["pet"]
        self.assertTrue(result["accepted"])
        self.assertGreater(after["affection"], before["affection"])
        self.assertGreater(after["attention"], before["attention"])

    def test_poke_lowers_affection(self):
        before = self.service.state()["pet"]["affection"]
        self.service.interact("poke")
        self.assertLess(self.service.state()["pet"]["affection"], before)

    def test_feeding_until_full_is_refused(self):
        first = self.service.interact("feed")
        self.assertTrue(first["accepted"])
        self.assertEqual(self.service.state()["animation"], "happy")
        second = self.service.interact("feed")
        self.assertFalse(second["accepted"])
        self.assertIn("full", second["message"])
        self.assertEqual(self.service.state()["animation"], "sad")

    def test_fish_is_the_only_food(self):
        # The brain only has fish; an old "wet" treat request just feeds fish.
        self.service.brain.pet.hunger = 60
        result = self.service.interact("feed", "wet")
        self.assertTrue(result["accepted"])
        self.assertEqual(self.service.state()["feeding"], {"food": "fish"})

    def test_unknown_interaction_is_rejected(self):
        self.assertFalse(self.service.interact("hug")["accepted"])

    def test_body_events_trigger_reactions(self):
        self.service._on_body(body(event="user_returned"))
        state = self.service.state()
        self.assertEqual(state["animation"], "happy")
        self.assertEqual(state["message"], "Welcome back!")

        self.service._on_body(body(event="user_left", present=False))
        self.assertEqual(self.service.state()["animation"], "sad")

    def test_raised_hand_waves_back_once_per_cooldown(self):
        self.service._on_body(body(hand_raised=True))
        self.assertEqual(self.service.state()["message"], "Hi! *waves back*")
        self.service._reaction = None
        self.service._on_body(body(hand_raised=False))
        self.service._on_body(body(hand_raised=True))
        self.assertIsNone(self.service._reaction)  # still cooling down

    def test_camera_movement_is_ignored(self):
        self.service._on_body(body(hand_raised=True, camera_moving=True))
        self.assertIsNone(self.service._reaction)

    def test_browser_tab_becomes_foreground_window(self):
        self.service.report_browser("Lofi beats", "www.youtube.com")
        raw = self.service.browser_backend.snapshot()
        self.assertIn("youtube", raw.foreground.title)
        self.assertLess(raw.idle_seconds, 1)

    def test_empty_presence_only_marks_activity(self):
        self.service.report_browser("Docs", "docs.python.org")
        self.service.report_browser("", "")
        self.assertIn("docs.python.org", self.service.browser_backend.snapshot().foreground.title)


class ServerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = CompanionService(native_awareness=False)
        cls.service.tick()
        server.companion = cls.service
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.service.close()
        server.companion = None

    def post(self, path, payload):
        req = Request(self.base + path, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=5) as res:
                return res.status, json.load(res)
        except HTTPError as err:
            with err:
                return err.code, json.load(err)

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as res:
            return res.status, res.read()

    def test_state_route(self):
        status, raw = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertIn(json.loads(raw)["animation"], ANIMATIONS)

    def test_status_reports_brain_and_camera(self):
        _, raw = self.get("/api/status")
        data = json.loads(raw)
        self.assertEqual(data["brain"], "browser")
        self.assertIn(data["camera"], {"off", "unavailable"})

    def test_interact_route(self):
        status, data = self.post("/api/interact", {"action": "pet"})
        self.assertEqual(status, 200)
        self.assertTrue(data["accepted"])
        self.assertIn("state", data)
        status, _ = self.post("/api/interact", {"action": "hug"})
        self.assertEqual(status, 400)

    def test_presence_route_returns_state(self):
        status, data = self.post("/api/presence", {"title": "Calculus notes", "host": "en.wikipedia.org"})
        self.assertEqual(status, 200)
        self.assertIn("pet", data)

    def test_chat_counts_as_attention(self):
        before = self.service.state()["pet"]["attention"]
        status, data = self.post("/api/chat", {"message": "hello!", "character": "boy"})
        self.assertEqual(status, 200)
        self.assertTrue(data["reply"])
        self.assertGreaterEqual(self.service.state()["pet"]["attention"], min(before + 1, 100))

    @unittest.skipIf(companion_module.CameraWorker.available(), "OpenCV/MediaPipe installed")
    def test_camera_without_packages_explains_what_to_install(self):
        status, data = self.post("/api/camera", {"on": True})
        self.assertEqual(status, 409)
        self.assertIn("pip install", data["error"])

    def test_art_and_scripts_are_served(self):
        for path in ("/", "/app.js", "/animation.js", "/extension/characters.js", "/extension/art/boy/happy.png"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 200)


if __name__ == "__main__":
    unittest.main()
