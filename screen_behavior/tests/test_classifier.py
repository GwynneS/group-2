import unittest

from screen_behavior.awareness.classifier import ActivityClassifier
from screen_behavior.awareness.models import (
    ActivityType,
    KeyboardActivity,
    RawScreenSnapshot,
    WindowInfo,
)


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = ActivityClassifier()

    def test_windows_vscode_is_coding(self):
        result = self.classifier.classify(
            RawScreenSnapshot(
                foreground=WindowInfo(
                    title="project - Visual Studio Code",
                    process_name="Code.exe",
                )
            )
        )
        self.assertEqual(result.activity, ActivityType.CODING)

    def test_macos_vscode_is_coding(self):
        result = self.classifier.classify(
            RawScreenSnapshot(
                foreground=WindowInfo(
                    app_name="Visual Studio Code",
                    bundle_id="com.microsoft.VSCode",
                )
            )
        )
        self.assertEqual(result.activity, ActivityType.CODING)

    def test_typing_increases_coding_confidence(self):
        raw = RawScreenSnapshot(
            foreground=WindowInfo(
                process_name="Code.exe",
            )
        )

        no_typing = self.classifier.classify(
            raw,
            KeyboardActivity(
                monitoring_available=True,
                typing_active=False,
            ),
        )
        typing = self.classifier.classify(
            raw,
            KeyboardActivity(
                monitoring_available=True,
                typing_active=True,
            ),
        )

        self.assertGreater(
            typing.scores[ActivityType.CODING],
            no_typing.scores[ActivityType.CODING],
        )

    def test_highest_candidate_is_exposed_as_leader(self):
        result = self.classifier.classify(
            RawScreenSnapshot(
                foreground=WindowInfo(
                    title="Assignment 4 - Canvas",
                    process_name="chrome.exe",
                )
            ),
            KeyboardActivity(
                monitoring_available=True,
                typing_active=True,
            ),
        )

        self.assertEqual(result.activity, ActivityType.STUDYING)
        self.assertEqual(
            result.confidence,
            max(result.scores.values()),
        )

    def test_scores_include_all_activity_types(self):
        result = self.classifier.classify(
            RawScreenSnapshot(
                foreground=WindowInfo(process_name="Code.exe")
            )
        )

        self.assertEqual(
            set(result.scores),
            set(ActivityType),
        )

    def test_all_scores_are_bounded(self):
        result = self.classifier.classify(
            RawScreenSnapshot(
                foreground=WindowInfo(
                    title="YouTube - Google Chrome",
                    process_name="chrome.exe",
                )
            )
        )

        for score in result.scores.values():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()
