"""Browser/camera boundary regressions. Camera and browser APIs are mocked;
the HTTP tests use the real local server and the real extension relay scripts.
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "UI"))
import companion as companion_module
import server
from companion import BrowserActivityBackend, CameraWorker, CompanionService
from screen_behavior.awareness.models import Shortcut, UserState
from screen_behavior.awareness.user_state import UserStateTracker
from screen_behavior.pet.distraction import DistractionBudget


def body(present=True, camera_moving=False, event=None):
    return SimpleNamespace(present=present, camera_moving=camera_moving,
                           state="at_desk" if present else "away", event=event,
                           away_seconds=0, hand_raised=False, leaning_in=False)


class BrowserCameraTests(unittest.TestCase):
    def setUp(self):
        self.service = CompanionService(native_awareness=False)
        self.service.tick()
        self.addCleanup(self.service.close)

    def make_idle(self):
        self.service.browser_backend._last_input = time.monotonic() - 400

    def test_metadata_polling_and_heartbeats_do_not_reset_inactivity(self):
        self.make_idle()
        self.service.report_browser("Docs", "docs.python.org")
        self.service.report_browser("", "")
        for data in ({}, {"inputAgeMs": None}, {"activeMs": 5000, "maxScrollPct": 99},
                     {"left": True}, {"title": "New tab", "host": "example.com"}):
            self.service.record_browser_activity(data)
            self.assertGreaterEqual(self.service.browser_backend.snapshot().idle_seconds, 400)
        self.service.tick()
        state = self.service.state()
        self.assertEqual(state["activity"]["user_state"], "away")
        self.assertIsNone(state["activity"]["user_present"])
        self.assertTrue(state["activity"]["away_inferred"])

    def test_repeated_input_age_and_older_tabs_preserve_last_actual_input(self):
        clock = SimpleNamespace(now=1000.0)
        backend = BrowserActivityBackend(clock=lambda: clock.now)
        self.service.browser_backend = backend
        self.service.brain.awareness.backend = backend
        clock.now = 1400
        self.service.record_browser_activity({"inputAgeMs": 400000})
        self.assertEqual(backend.snapshot().idle_seconds, 400)
        clock.now = 1410
        self.service.record_browser_activity({"inputAgeMs": 410000})
        self.assertEqual(backend.snapshot().idle_seconds, 410)
        self.service.record_browser_activity({"inputAgeMs": 2000})
        self.assertEqual(backend.snapshot().idle_seconds, 2)
        self.service.record_browser_activity({"inputAgeMs": 410000, "left": True})
        self.assertEqual(backend.snapshot().idle_seconds, 2)

    def test_invalid_input_ages_do_not_reset_inactivity(self):
        self.make_idle()
        for age in (None, -1, "recent", float("inf"), float("nan"), True):
            with self.subTest(age=age):
                self.service.record_browser_activity({"inputAgeMs": age})
                self.assertGreaterEqual(self.service.browser_backend.snapshot().idle_seconds, 400)

    def test_legacy_real_counts_still_work(self):
        for count in ("keys", "clicks", "copies", "pastes"):
            self.make_idle()
            self.service.record_browser_activity({count: 1})
            self.assertLess(self.service.browser_backend.snapshot().idle_seconds, 1)

    def test_camera_absence_and_corrected_idle_reach_budget_without_changing_rates(self):
        self.service.camera.status = "on"  # simulated snapshots; no webcam opened
        self.service._on_body(body(present=False))
        self.service.tick()
        screen = self.service._update.screen
        self.assertIs(screen.user_present, False)
        self.assertEqual(screen.user_state, UserState.AWAY)
        self.assertTrue(screen.user_is_idle)  # existing helper includes AWAY
        self.assertFalse(self.service.state()["activity"]["away_inferred"])
        budget = DistractionBudget()
        budget.value = 0
        budget.tick(screen, 10)
        self.assertEqual(budget.value, 20)  # unchanged 2/sec idle/away refill

    def test_present_person_can_be_idle_and_receive_existing_in_frame_voice(self):
        clock = SimpleNamespace(now=1000.0)
        tracker = UserStateTracker(clock=lambda: clock.now)
        tracker.update(self.service._update.screen)
        self.service.brain.awareness.user_state_tracker = tracker
        self.service.camera.status = "on"
        self.make_idle()
        self.service._on_body(body())
        self.service.tick()
        clock.now += 6  # normal state smoothing, no real sleep
        self.service._on_body(body())
        self.service.tick()
        screen = self.service._update.screen
        self.assertIs(screen.user_present, True)
        self.assertGreaterEqual(screen.idle_seconds, 400)
        self.assertEqual(screen.user_state, UserState.IDLE)
        self.assertEqual(self.service.state()["voice"]["trigger"], "onInactiveINframe")
        budget = DistractionBudget()
        budget.value = 0
        budget.tick(screen, 10)
        self.assertEqual(budget.value, 20)

    def test_camera_return_leaves_away_without_inventing_input(self):
        self.make_idle()
        self.service.camera.status = "on"
        self.service._on_body(body(present=False))
        self.service.tick()
        self.service._on_body(body(event="user_returned"))
        self.service.tick()
        self.assertIs(self.service._update.screen.user_present, True)
        self.assertEqual(self.service._update.screen.user_state, UserState.IDLE)
        self.assertGreaterEqual(self.service._update.screen.idle_seconds, 400)
        # The existing in-frame reaction may follow the camera return reaction.
        self.assertIn(self.service.state()["voice"]["trigger"], {"onReturn", "onInactiveINframe"})

    def test_off_failed_stale_and_moving_camera_clear_presence(self):
        for status in ("off", "error", "unavailable", "starting", "stale", "moving"):
            with self.subTest(status=status):
                self.service.camera.status = "on"
                self.service._on_body(body(present=False))
                self.service.tick()
                if status == "stale":
                    self.service._body_at -= companion_module.BODY_STALE_SECONDS + 1
                elif status == "moving":
                    self.service._on_body(body(present=False, camera_moving=True))
                else:
                    self.service.camera.status = status
                self.service.tick()
                state = self.service.state()
                self.assertIsNone(self.service._update.screen.user_present)
                self.assertNotEqual(self.service._update.screen.user_state, UserState.AWAY)
                self.assertIsNone(state["body"])

    def test_uncertain_camera_cannot_trigger_in_frame_voice(self):
        self.make_idle()
        for kind in ("off", "stale", "moving"):
            with self.subTest(kind=kind):
                self.service._reaction = None
                self.service.camera.status = "on"
                self.service._on_body(body(camera_moving=kind == "moving"))
                if kind == "stale":
                    self.service._body_at -= companion_module.BODY_STALE_SECONDS + 1
                elif kind == "off":
                    self.service.camera.status = "off"
                self.service.tick()
                self.assertIsNone(self.service.state()["voice"])

    def test_state_preserves_legacy_fields_and_renderer_contract(self):
        state = self.service.state()
        self.assertTrue({"animation", "message", "voice", "pet", "activity", "feeding", "camera", "body"} <= state.keys())
        self.assertEqual(state["brain"], "running")
        self.assertIn(state["onpage_mode"], {"idle", "sleep", "wander", "follow", "cheer", "attention"})
        self.assertEqual(state["behavior"], state["pet"]["behavior"])
        self.assertEqual(state["user"]["state"], state["activity"]["user_state"])
        self.assertIn("distraction_budget", state)

    def test_polling_does_not_make_an_old_decision_fresh(self):
        before = self.service.state()["updated_at"]
        self.service._update_at -= 12
        state = self.service.state()
        self.assertEqual(state["updated_at"], before)
        self.assertGreaterEqual(state["decision_age_ms"], 12000)
        self.service.tick()
        self.assertLess(self.service.state()["decision_age_ms"], 1000)

    def test_camera_processing_failure_is_reported_and_releases_device(self):
        cap = mock.Mock()
        cap.isOpened.return_value = True
        cap.read.return_value = (True, object())
        tracker = mock.Mock()
        tracker.process.side_effect = RuntimeError("simulated frame failure")
        fake_cv = SimpleNamespace(VideoCapture=mock.Mock(return_value=cap))
        fake_tracking = SimpleNamespace(BodyTracker=mock.Mock(return_value=tracker), draw_skeleton=mock.Mock())
        with mock.patch.dict(sys.modules, {"cv2": fake_cv, "BodyTracking.tracking": fake_tracking}):
            self.service.camera._run(0)
        self.assertEqual(self.service.camera.status, "error")
        self.assertIn("simulated frame failure", self.service.camera.error)
        tracker.close.assert_called_once()
        cap.release.assert_called_once()


class BrowserHTTPTests(unittest.TestCase):
    def setUp(self):
        self.service = CompanionService(native_awareness=False)
        self.service.tick()
        self.previous_companion = server.companion
        server.companion = self.service
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.service.close()
        server.companion = self.previous_companion

    def post(self, path, payload):
        req = Request(self.base + path, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=5) as response:
            return json.load(response)

    def test_presence_polling_is_metadata_only_until_explicit_input(self):
        self.service.browser_backend._last_input = time.monotonic() - 400
        for payload in ({}, {"title": "Notes", "host": "example.com"}):
            state = self.post("/api/presence", payload)
            self.assertGreaterEqual(self.service.browser_backend.snapshot().idle_seconds, 400)
            self.assertIn("onpage_mode", state)
        self.post("/api/presence", {"input": True})
        self.assertLess(self.service.browser_backend.snapshot().idle_seconds, 1)

    def test_camera_off_route_immediately_clears_confirmed_absence(self):
        self.service.camera.status = "on"
        self.service._on_body(body(present=False))
        self.service.tick()
        state = self.post("/api/camera", {"on": False})
        self.assertIsNone(state["activity"]["user_present"])
        self.assertIsNone(state["body"])
        self.assertEqual(state["camera"]["status"], "off")

    def test_shortcut_http_responds_immediately_and_voice_is_claimed_once(self):
        result = self.post("/api/shortcut", {"shortcut": "undo"})
        self.assertTrue(result["accepted"])
        event = result["state"]["voice"]
        self.assertEqual(event["trigger"], "CMDZ")
        payload = {"key": event["key"], "owner": "test-tab-one"}
        self.assertTrue(self.post("/api/voice/claim", payload)["claimed"])
        self.assertFalse(self.post("/api/voice/claim", {**payload, "owner": "test-tab-two"})["claimed"])
        self.assertTrue(self.post("/api/voice/claim", {**payload, "release": True})["claimed"])
        self.assertTrue(self.post("/api/voice/claim", {**payload, "owner": "test-tab-two"})["claimed"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_real_extension_relay_and_content_script_over_http(self):
        self.service.browser_backend._last_input = time.monotonic() - 400
        def run(mode):
            result = subprocess.run(
                [shutil.which("node"), str(ROOT / "UI/tests/browser_http.cjs"), str(ROOT), self.base, mode],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        quiet = run("quiet")
        self.assertTrue(quiet["rendererContract"])
        self.assertGreaterEqual(self.service.browser_backend.snapshot().idle_seconds, 400)
        active = run("input")
        self.assertEqual(active["keys"], 1)
        self.assertLess(self.service.browser_backend.snapshot().idle_seconds, 3)
        self.service.tick()
        self.assertTrue(self.service.extension_seen)
        self.assertTrue(self.service._update.screen.keyboard.typing_active)


class ShortcutVoiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CompanionService(native_awareness=False)
        self.service.tick()
        self.addCleanup(self.service.close)

    def test_copy_paste_undo_have_no_shared_delay_and_do_not_change_needs(self):
        before = self.service.state()["pet"]
        for name, trigger in (("copy", "CMDC"), ("paste", "CMDV"), ("undo", "CMDZ")):
            self.assertTrue(self.service.record_browser_shortcut(name))
            self.assertEqual(self.service.state()["voice"]["trigger"], trigger)
        self.assertEqual(self.service.state()["pet"], before)

    def test_same_shortcut_has_one_second_guard_without_queuing_old_audio(self):
        self.service.record_browser_shortcut("undo")
        first = self.service.state()["voice"]
        self.service.record_browser_shortcut("undo")
        self.assertEqual(self.service.state()["voice"]["key"], first["key"])
        self.service._shortcut_voice_at[Shortcut.UNDO] -= 1.1
        self.service.record_browser_shortcut("undo")
        self.assertNotEqual(self.service.state()["voice"]["key"], first["key"])

    def test_delayed_browser_counts_do_not_replay_immediate_shortcut(self):
        self.service.record_browser_shortcut("copy")
        key = self.service.state()["voice"]["key"]
        self.service.record_browser_activity({"keys": 2, "copies": 1, "inputAgeMs": 1200,
                                             "shortcutsImmediate": True})
        self.service.tick()
        self.assertEqual(self.service.state()["voice"]["key"], key)

    def test_native_monitor_and_browser_do_not_duplicate_the_same_shortcut(self):
        tracker = self.service.brain.awareness.keyboard_tracker
        tracker.set_monitoring_available(True)
        self.service.tick()
        self.service.record_browser_shortcut("paste")
        key = self.service.state()["voice"]["key"]
        tracker.record_shortcut(Shortcut.PASTE)
        self.service.tick()
        self.assertEqual(self.service.state()["voice"]["key"], key)

    def test_undo_counts_reach_browser_fallback_keyboard_context(self):
        self.service.record_browser_activity({"host": "example.com", "undos": 2, "keys": 2,
                                             "inputAgeMs": 0, "shortcutsImmediate": True})
        self.service.tick()
        self.assertEqual(self.service._update.screen.keyboard.shortcut_counts[Shortcut.UNDO], 2)

    def test_claim_is_atomic_and_failed_player_can_release_only_its_own_claim(self):
        self.service.record_browser_shortcut("copy")
        key = self.service.state()["voice"]["key"]
        results = []
        threads = [threading.Thread(target=lambda i=i: results.append(
            (i, self.service.claim_voice(key, str(i))))) for i in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        winners = [i for i, claimed in results if claimed]
        self.assertEqual(len(winners), 1)
        self.assertFalse(self.service.claim_voice(key, "not-the-owner", release=True))
        self.assertTrue(self.service.claim_voice(key, str(winners[0]), release=True))
        self.assertTrue(self.service.claim_voice(key, "replacement-player"))

    def test_expired_or_invalid_voice_requests_are_rejected(self):
        self.assertFalse(self.service.record_browser_shortcut("raw typed text"))
        self.service.record_browser_shortcut("undo")
        key = self.service.state()["voice"]["key"]
        self.service._reaction.until -= 4
        self.assertFalse(self.service.claim_voice(key, "a"))
        self.assertFalse(self.service.claim_voice("invented", "a"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class VoiceAndPreviewRuntimeTests(unittest.TestCase):
    def run_runtime(self, name, *args):
        result = subprocess.run([shutil.which("node"), str(ROOT / "UI/tests" / name), str(ROOT), *args],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_extension_audio_with_mocked_chromium_offscreen_lifecycle(self):
        self.assertTrue(self.run_runtime("voice_runtime.cjs", "chromium")["singlePlayer"])

    def test_extension_audio_with_mocked_firefox_background_document(self):
        self.assertTrue(self.run_runtime("voice_runtime.cjs", "firefox")["singlePlayer"])

    def test_website_preview_and_voice_controls_with_mocked_dom(self):
        result = self.run_runtime("website_runtime.cjs")
        self.assertTrue(result["previewIndependent"])
        self.assertTrue(result["pageCamera"])

    def test_website_body_tracking_follows_tracking_py(self):
        self.assertTrue(self.run_runtime("body_runtime.cjs")["rules"])

    def test_extension_talks_to_the_site_it_was_downloaded_from(self):
        local = self.run_runtime("config_runtime.cjs")
        self.assertEqual(local["url"], server.LOCAL_APP_URL)
        self.assertTrue(local["local"])
        self.assertEqual(local["owns"], ["http://127.0.0.1:8765/", "http://localhost:8765/"])

        with zipfile.ZipFile(io.BytesIO(server.build_extension_zip("https://buddy.example.app"))) as zf, \
                tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.js"
            config.write_bytes(zf.read("buddy-extension/config.js"))
            manifest = json.loads(zf.read("buddy-extension/manifest.json"))
            deployed = self.run_runtime("config_runtime.cjs", str(config))
        self.assertEqual(deployed["url"], "https://buddy.example.app")
        self.assertFalse(deployed["local"])
        self.assertEqual(deployed["owns"], ["https://buddy.example.app/"])
        self.assertEqual(manifest["host_permissions"], ["https://buddy.example.app/*"])
        bridge = next(s for s in manifest["content_scripts"] if "bridge.js" in s["js"])
        self.assertEqual(bridge["matches"], ["https://buddy.example.app/*"])


if __name__ == "__main__":
    unittest.main()
