import json
import unittest
from types import SimpleNamespace
from urllib.request import urlopen

from animation_bridge import AnimationBridge, animation_for_update


def make_update(behavior="idle", mood="neutral", energy=80, hunger=20):
    return SimpleNamespace(
        decision=SimpleNamespace(
            behavior=SimpleNamespace(value=behavior),
        ),
        pet=SimpleNamespace(
            mood=SimpleNamespace(value=mood),
            energy=energy,
            hunger=hunger,
        ),
    )


class AnimationBridgeTests(unittest.TestCase):
    def test_brain_update_maps_to_all_animation_states(self):
        examples = [
            (make_update(), "lounging"),
            (make_update(behavior="dance"), "happy"),
            (make_update(mood="lonely"), "sad"),
            (make_update(behavior="sleep"), "tired"),
            (make_update(mood="annoyed"), "angry"),
            (make_update(hunger=80), "hungry"),
            (make_update(behavior="wave"), "encouragement"),
        ]

        for update, expected in examples:
            with self.subTest(expected=expected):
                self.assertEqual(animation_for_update(update), expected)

    def test_manual_animation_state_can_include_message(self):
        bridge = AnimationBridge()

        bridge.set_animation("encouragement", "You can do this!")

        self.assertEqual(
            bridge.snapshot(),
            {
                "animation": "encouragement",
                "message": "You can do this!",
            },
        )

    def test_local_server_serves_ui_and_current_state(self):
        bridge = AnimationBridge(port=0)
        url = bridge.start(open_browser=False)
        try:
            with urlopen(url, timeout=2) as response:
                page = response.read().decode("utf-8")
            with urlopen(f"{url}api/state", timeout=2) as response:
                state = json.load(response)

            self.assertIn("animation.js", page)
            self.assertEqual(state["animation"], "lounging")
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()