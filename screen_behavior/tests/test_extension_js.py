"""
Runs the real browser-extension scripts in Node with a fake browser, to check
the heartbeat contract the Python brain depends on. Skipped without Node.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from screen_behavior.awareness.browser import BrowserActivityTracker

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")

HARNESS = r"""
const fs = require("fs");
const sent = [];
const listeners = {};
const intervals = [];
const on = (target) => (type, fn) => ((listeners[target + ":" + type] ??= []).push(fn));
const fire = (target, type, event = {}) => (listeners[target + ":" + type] ?? []).forEach((fn) => fn(event));

globalThis.chrome = { runtime: { sendMessage: (m) => sent.push(m) } };
globalThis.location = { href: "https://www.youtube.com/watch", hostname: "www.youtube.com" };
globalThis.document = {
  title: "Lofi beats - YouTube",
  visibilityState: "visible",
  hasFocus: () => true,
  activeElement: null,
  documentElement: { scrollHeight: 2000, clientHeight: 1000, scrollTop: 500 },
  addEventListener: on("document"),
};
globalThis.window = { addEventListener: on("window") };
globalThis.HTMLIFrameElement = class {};
globalThis.setInterval = (fn, ms) => intervals.push({ fn, ms });

eval(fs.readFileSync(process.argv.at(-1), "utf8"));

for (let i = 0; i < 3; i++) fire("document", "keydown");
fire("document", "click");
fire("document", "copy");
fire("document", "scroll");
intervals.find((t) => t.ms === 5000).fn();   // first heartbeat
fire("document", "paste");
intervals.find((t) => t.ms === 5000).fn();   // second heartbeat: deltas only
fire("window", "pagehide", { persisted: false }); // leaving the page

console.log(JSON.stringify(sent));
"""


@unittest.skipUnless(NODE, "node is not installed")
class ContentScriptHeartbeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(
            [NODE, "-e", HARNESS, "--", str(ROOT / "browser_extension/content.js")],
            capture_output=True, text=True, timeout=20, check=True,
        )
        cls.messages = json.loads(out.stdout)
        cls.beats = [m["data"] for m in cls.messages if m["type"] == "heartbeat"]

    def test_heartbeats_carry_counts_not_content(self):
        first = self.beats[0]
        self.assertEqual(first["host"], "www.youtube.com")
        self.assertEqual(first["keys"], 3)
        self.assertEqual(first["clicks"], 1)
        self.assertEqual(first["copies"], 1)
        self.assertEqual(first["maxScrollPct"], 50)
        self.assertFalse(first["left"])
        self.assertNotIn("url", first)

    def test_heartbeats_send_deltas(self):
        second = self.beats[1]
        self.assertEqual(second["keys"], 0)
        self.assertEqual(second["pastes"], 1)

    def test_leaving_sends_final_heartbeat_and_session(self):
        self.assertTrue(self.beats[-1]["left"])
        self.assertIn("session", [m["type"] for m in self.messages])

    def test_python_tracker_accepts_extension_heartbeats(self):
        tracker = BrowserActivityTracker()
        for beat in self.beats:
            tracker.record(beat)
        snap = tracker.snapshot()

        self.assertEqual(snap.keys_last_minute, 3)
        self.assertEqual(snap.copies_last_minute, 1)
        self.assertEqual(snap.pastes_last_minute, 1)
        self.assertFalse(snap.focused)  # last heartbeat said the user left


@unittest.skipUnless(NODE, "node is not installed")
class ExtensionSyntaxTests(unittest.TestCase):
    def test_all_scripts_parse(self):
        for path in [*ROOT.glob("browser_extension/*.js"), *ROOT.glob("UI/*.js")]:
            with self.subTest(path.name):
                subprocess.run([NODE, "--check", str(path)], check=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
