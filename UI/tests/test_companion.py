"""Tests for the companion hub (UI/companion.py) and the app server routes.

    python3 -m unittest discover -s UI/tests
"""

import io
import json
import sys
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(UI_DIR))

import companion as companion_module  # noqa: E402
import server  # noqa: E402
from companion import CompanionService  # noqa: E402
from screen_behavior.awareness.models import Shortcut  # noqa: E402

# Every voice trigger UI/app.js and UI/companion.py play.
VOICE_TRIGGERS = {
    "happy", "unhappy", "fed", "CMDC", "CMDV", "CMDZ", "whenTyping",
    "onGetup", "notInFrame", "onReturn", "onInactiveINframe",
}

ANIMATIONS = {"lounging", "happy", "sad", "tired", "angry", "hungry", "encouragement"}


def body(event=None, present=True, hand_raised=False, leaning_in=False, camera_moving=False, away_seconds=0.0):
    return SimpleNamespace(
        event=event, present=present, state="at_desk" if present else "away",
        hand_raised=hand_raised, leaning_in=leaning_in, camera_moving=camera_moving,
        away_seconds=away_seconds,
    )


def screen(since_key=None, idle=0.0, activity="coding"):
    """What _voice_for_screen reads from a brain update's ScreenContext."""
    keyboard = SimpleNamespace(shortcut_counts={}, last_shortcut=None, seconds_since_last_keypress=since_key)
    return SimpleNamespace(keyboard=keyboard, idle_seconds=idle, activity=activity)


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

    def voice(self):
        line = self.service.state()["voice"]
        return line and (line["id"], line["trigger"])

    def test_camera_events_say_their_lines(self):
        for event, trigger in (("user_returned", "onReturn"), ("user_getting_up", "onGetup")):
            with self.subTest(event=event):
                self.service._on_body(body(event=event))
                self.assertEqual(self.voice()[1], trigger)

    def test_gone_for_20_seconds_says_not_in_frame_once(self):
        self.service._on_body(body(present=False, away_seconds=5))
        self.assertIsNone(self.voice())
        self.service._on_body(body(present=False, away_seconds=21))
        first = self.voice()
        self.assertEqual(first[1], "notInFrame")
        self.service._on_body(body(present=False, away_seconds=30))
        self.assertEqual(self.voice(), first)  # not said again while still gone

    def website_body(self, **fields):
        return self.service.record_browser_body({"state": "at_desk", "present": True, **fields})

    def test_website_camera_reacts_like_this_computers_camera(self):
        self.assertTrue(self.website_body(state="getting_up", event="user_getting_up"))
        self.assertEqual(self.voice()[1], "onGetup")
        self.assertEqual(self.service.state()["body"]["state"], "getting_up")
        self.website_body(present=False, away_seconds=21)
        self.assertEqual(self.voice()[1], "notInFrame")

    def test_website_camera_presence_goes_stale_and_off(self):
        self.website_body()
        self.service.tick()
        self.assertIs(self.service._update.screen.user_present, True)
        self.service._body_at -= companion_module.BODY_STALE_SECONDS + 1
        self.assertIsNone(self.service.state()["body"])  # the page stopped reporting

        self.website_body()
        self.assertTrue(self.service.record_browser_body({"camera": "off"}))
        self.assertIsNone(self.service.state()["body"])
        self.assertIsNone(self.service._update.screen.user_present)

    def test_website_camera_input_is_checked(self):
        self.website_body(state="dancing", present="yes", event="user_exploded",
                          away_seconds=float("inf"), hand_raised=1, leaning_in="true")
        got = self.service._body
        self.assertEqual((got.state, got.present, got.event, got.away_seconds, got.hand_raised, got.leaning_in),
                         ("away", False, None, 0.0, False, False))
        self.website_body(state="away")
        self.assertEqual(self.service._body.state, "at_desk")  # present wins

    def test_website_camera_is_ignored_while_this_computers_camera_runs(self):
        self.service.camera.status = "on"
        self.assertFalse(self.website_body(event="user_returned"))
        self.assertIsNone(self.service._reaction)
        self.assertFalse(self.service.record_browser_body({"camera": "off"}))

    def test_copy_paste_undo_in_any_app_say_their_lines(self):
        keys = self.service.brain.awareness.keyboard_tracker
        keys.set_monitoring_available(True)
        self.service.tick()
        keys.record_shortcut(Shortcut.PASTE)
        self.service.tick()
        self.assertEqual(self.voice()[1], "CMDV")
        keys.record_shortcut(Shortcut.UNDO)
        self.service.tick()
        state = self.service.state()
        self.assertEqual(state["message"], "Undo! No worries~")
        self.assertEqual(state["voice"]["trigger"], "CMDZ")  # different shortcuts respond immediately

    def test_typing_says_a_line_every_45_to_60_seconds(self):
        self.service._voice_for_screen(screen(since_key=1), now=1000)
        self.service._voice_for_screen(screen(since_key=5), now=1044)  # short pauses are fine
        self.assertIsNone(self.voice())
        self.service._voice_for_screen(screen(since_key=1), now=1060)
        first = self.voice()
        self.assertEqual(first[1], "whenTyping")
        self.service._voice_for_screen(screen(since_key=1), now=1104)  # 44s more typing
        self.assertEqual(self.voice(), first)
        self.service._voice_for_screen(screen(since_key=1), now=1120)
        self.assertNotEqual(self.voice(), first)
        self.assertEqual(self.voice()[1], "whenTyping")

    def test_a_long_pause_starts_the_typing_count_over(self):
        self.service._voice_for_screen(screen(since_key=1), now=1000)
        self.service._voice_for_screen(screen(since_key=30), now=1040)  # stopped typing
        self.service._voice_for_screen(screen(since_key=1), now=1050)
        self.service._voice_for_screen(screen(since_key=1), now=1070)
        self.assertIsNone(self.voice())  # only 20s since typing resumed

    def test_sitting_idle_in_frame_says_a_line_once(self):
        self.service.camera.status = "on"
        self.service._body = body(present=True)
        self.service._body_at = 1000  # a fresh simulated camera frame
        self.service._voice_for_screen(screen(idle=90), now=1000)
        first = self.voice()
        self.assertEqual(first[1], "onInactiveINframe")
        self.service._voice_for_screen(screen(idle=95), now=1005)
        self.assertEqual(self.voice(), first)
        self.service._voice_for_screen(screen(idle=90, activity="video"), now=1100)  # watching: fine
        self.assertEqual(self.voice(), first)

    def test_extension_is_seen_after_its_first_heartbeat(self):
        self.assertFalse(self.service.extension_seen)
        self.service.record_browser_activity({"title": "Notes", "host": "docs.python.org"})
        self.assertTrue(self.service.extension_seen)


class DesktopWindowTests(unittest.TestCase):
    def test_without_pywebview_nothing_opens(self):
        with mock.patch.dict(sys.modules, {"webview": None}):  # makes `import webview` fail
            self.assertFalse(server.run_window("http://127.0.0.1:8765"))

    def test_window_allows_downloads_and_keeps_local_storage(self):
        fake = SimpleNamespace(
            settings={"ALLOW_DOWNLOADS": False},
            create_window=mock.Mock(),
            start=mock.Mock(),
            errors=SimpleNamespace(WebViewException=RuntimeError),
        )
        with mock.patch.dict(sys.modules, {"webview": fake}):
            self.assertTrue(server.run_window("http://127.0.0.1:8765"))
        self.assertTrue(fake.settings["ALLOW_DOWNLOADS"])
        self.assertEqual(fake.create_window.call_args.args[1], "http://127.0.0.1:8765")
        self.assertIs(fake.start.call_args.kwargs["private_mode"], False)


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

    def test_status_reports_extension_after_a_heartbeat(self):
        status, _ = self.post("/api/browser-activity", {"title": "Notes", "host": "docs.python.org"})
        self.assertEqual(status, 200)
        _, raw = self.get("/api/status")
        self.assertTrue(json.loads(raw)["extension_seen"])

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

    def download_extension(self, **headers):
        with urlopen(Request(self.base + "/download/buddy-extension.zip", headers=headers), timeout=5) as res:
            with zipfile.ZipFile(io.BytesIO(res.read())) as zf:
                return zf.read("buddy-extension/config.js").decode(), json.loads(zf.read("buddy-extension/manifest.json"))

    def test_extension_download_talks_to_the_site_it_came_from(self):
        # Vercel sends the site's name in Host and says it's https.
        config, manifest = self.download_extension(Host="group-2.vercel.app", **{"X-Forwarded-Proto": "https"})
        self.assertIn('url: "https://group-2.vercel.app"', config)
        self.assertEqual(manifest["host_permissions"], ["https://group-2.vercel.app/*"])

        config, manifest = self.download_extension(Host="127.0.0.1:8765")
        self.assertEqual(config, (server.EXT_DIR / "config.js").read_text())
        self.assertEqual(manifest, json.loads((server.EXT_DIR / "manifest.json").read_text()))

        config, _ = self.download_extension(Host='evil"; alert(1); "')
        self.assertIn(f'url: "{server.LOCAL_APP_URL}"', config)

    def test_body_route_takes_the_websites_camera(self):
        status, data = self.post("/api/body", {"state": "at_desk", "present": True, "leaning_in": True})
        self.assertEqual(status, 200)
        self.assertIs(data["body"]["leaning_in"], True)
        status, data = self.post("/api/body", {"camera": "off"})
        self.assertEqual(status, 200)
        self.assertIsNone(data["body"])

    def test_every_voice_trigger_has_lines_for_both_buddies(self):
        _, raw = self.get("/api/voices")
        clips = json.loads(raw)
        for trigger in VOICE_TRIGGERS:
            with self.subTest(trigger=trigger):
                self.assertTrue(clips[trigger]["girl"], "no Mochi (F) clips")
                self.assertTrue(clips[trigger]["boy"], "no Kiko (M) clips")
                for clip in clips[trigger]["girl"] + clips[trigger]["boy"]:
                    self.assertIn("text", clip)  # its exact words, or None

    def test_voice_file_names(self):
        match = server.VOICE_FILE.fullmatch
        self.assertEqual(match("onInactiveINframeF1.mp3").group("trigger", "voice"), ("onInactiveINframe", "F"))
        self.assertEqual(match("CMDCM2.mp3").group("trigger", "voice"), ("CMDC", "M"))
        self.assertIsNone(match("notInFrame3.mp3"))  # whose voice?
        self.assertIsNone(match("onGetupM3 2.mp3"))  # a Finder copy

    def test_voice_clips_answer_byte_ranges(self):
        req = Request(self.base + "/voice/happyF1.mp3", headers={"Range": "bytes=0-1"})
        with urlopen(req, timeout=5) as res:
            self.assertEqual(res.status, 206)
            self.assertEqual(res.headers["Content-Type"], "audio/mpeg")
            self.assertTrue(res.headers["Content-Range"].startswith("bytes 0-1/"))
            self.assertEqual(len(res.read()), 2)

    def test_art_and_scripts_are_served(self):
        for path in ("/", "/app.js", "/animation.js", "/extension/characters.js", "/extension/art/boy/happy.png"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 200)


if __name__ == "__main__":
    unittest.main()
