from __future__ import annotations

from screen_behavior.awareness.models import (
    ActivityClassification,
    ActivityType,
    KeyboardActivity,
    RawScreenSnapshot,
)


class ActivityClassifier:
    """
    Shared evidence scorer used by Windows and macOS.

    Scores are *evidence strengths*, not statistical probabilities.
    We compute every candidate score first, then expose the strongest raw
    candidate. A separate stability tracker decides when the public activity
    should actually switch.
    """

    CODING_TOKENS = {
        "code.exe",
        "visual studio code",
        "com.microsoft.vscode",
        "pycharm64.exe",
        "pycharm",
        "com.jetbrains.pycharm",
        "devenv.exe",
        "visual studio",
        "idea64.exe",
        "intellij",
        "sublime_text.exe",
        "sublime text",
        "notepad++.exe",
        "xcode",
        "com.apple.dt.xcode",
    }

    BROWSER_TOKENS = {
        "chrome.exe",
        "google chrome",
        "com.google.chrome",
        "msedge.exe",
        "microsoft edge",
        "firefox.exe",
        "firefox",
        "org.mozilla.firefox",
        "brave.exe",
        "brave browser",
        "safari",
        "com.apple.safari",
        "opera.exe",
        "opera",
    }

    GAME_TOKENS = {
        "robloxplayerbeta.exe",
        "roblox",
        "valorant-win64-shipping.exe",
        "valorant",
        "minecraftlauncher.exe",
        "minecraft",
        "steam.exe",
        "steam",
    }

    STUDY_TITLE_WORDS = {
        "canvas",
        "blackboard",
        "moodle",
        "quizlet",
        "khan academy",
        "google docs",
        "google slides",
        "coursera",
        "edx",
        "homework",
        "assignment",
        "study",
    }

    VIDEO_TITLE_WORDS = {
        "youtube",
        "netflix",
        "twitch",
        "hulu",
        "disney+",
    }

    def classify(
        self,
        snapshot: RawScreenSnapshot,
        keyboard: KeyboardActivity | None = None,
    ) -> ActivityClassification:
        keyboard = keyboard or KeyboardActivity()
        scores = self.score_candidates(snapshot, keyboard)

        activity = max(
            scores,
            key=lambda candidate: scores[candidate],
        )
        confidence = scores[activity]

        return ActivityClassification(
            activity=activity,
            confidence=confidence,
            scores=scores,
            reason=self._reason_for(activity, snapshot, keyboard),
        )

    def score_candidates(
        self,
        snapshot: RawScreenSnapshot,
        keyboard: KeyboardActivity | None = None,
    ) -> dict[ActivityType, float]:
        keyboard = keyboard or KeyboardActivity()

        scores = {
            ActivityType.CODING: 0.02,
            ActivityType.BROWSING: 0.02,
            ActivityType.GAMING: 0.01,
            ActivityType.STUDYING: 0.02,
            ActivityType.VIDEO: 0.01,
            ActivityType.IDLE: 0.01,
            ActivityType.OTHER: 0.18,
        }

        # Idle is strong evidence, but only after the explicit system-idle
        # threshold. Below the threshold it increases gradually.
        if snapshot.idle_seconds >= 120:
            scores[ActivityType.IDLE] = 0.99
        elif snapshot.idle_seconds >= 60:
            scores[ActivityType.IDLE] = 0.55
        elif snapshot.idle_seconds >= 30:
            scores[ActivityType.IDLE] = 0.25

        fg = snapshot.foreground
        if not fg:
            scores[ActivityType.OTHER] = max(
                scores[ActivityType.OTHER],
                0.45,
            )
            return self._bounded(scores)

        searchable = " ".join(
            [
                fg.title,
                fg.app_name,
                fg.process_name,
                fg.bundle_id,
            ]
        ).lower()

        title = fg.title.lower()

        is_coding_app = self._contains_any(
            searchable,
            self.CODING_TOKENS,
        )
        is_game = self._contains_any(
            searchable,
            self.GAME_TOKENS,
        )
        is_browser = self._contains_any(
            searchable,
            self.BROWSER_TOKENS,
        )
        has_study_title = self._contains_any(
            title,
            self.STUDY_TITLE_WORDS,
        )
        has_video_title = self._contains_any(
            title,
            self.VIDEO_TITLE_WORDS,
        )

        if is_coding_app:
            scores[ActivityType.CODING] = 0.92
            scores[ActivityType.OTHER] = 0.10

            if keyboard.monitoring_available:
                if keyboard.typing_active:
                    scores[ActivityType.CODING] += 0.06
                elif (
                    keyboard.seconds_since_last_keypress is not None
                    and keyboard.seconds_since_last_keypress >= 60
                ):
                    # The app is still clearly a coding app, but active coding
                    # confidence drops if there has been no typing for a while.
                    scores[ActivityType.CODING] -= 0.10

        if is_game:
            scores[ActivityType.GAMING] = max(
                scores[ActivityType.GAMING],
                0.92,
            )
            scores[ActivityType.OTHER] = min(
                scores[ActivityType.OTHER],
                0.12,
            )

        if is_browser:
            scores[ActivityType.BROWSING] = max(
                scores[ActivityType.BROWSING],
                0.70,
            )
            scores[ActivityType.OTHER] = min(
                scores[ActivityType.OTHER],
                0.12,
            )

            if keyboard.monitoring_available and keyboard.typing_active:
                scores[ActivityType.BROWSING] += 0.05

            if has_study_title:
                scores[ActivityType.STUDYING] = 0.88
                # A study page is still technically browsing, so keep browsing
                # as a plausible secondary candidate.
                scores[ActivityType.BROWSING] = max(
                    scores[ActivityType.BROWSING],
                    0.45,
                )

                if keyboard.monitoring_available and keyboard.typing_active:
                    scores[ActivityType.STUDYING] += 0.08

            if has_video_title:
                scores[ActivityType.VIDEO] = 0.92
                scores[ActivityType.BROWSING] = max(
                    scores[ActivityType.BROWSING],
                    0.40,
                )

                if (
                    keyboard.monitoring_available
                    and keyboard.seconds_since_last_keypress is not None
                    and keyboard.seconds_since_last_keypress >= 10
                ):
                    scores[ActivityType.VIDEO] += 0.04

        # If nothing strong matched, keep OTHER meaningful.
        strongest_specific = max(
            scores[a]
            for a in (
                ActivityType.CODING,
                ActivityType.BROWSING,
                ActivityType.GAMING,
                ActivityType.STUDYING,
                ActivityType.VIDEO,
            )
        )
        if strongest_specific < 0.50:
            scores[ActivityType.OTHER] = max(
                scores[ActivityType.OTHER],
                0.40,
            )

        return self._bounded(scores)

    @staticmethod
    def _bounded(
        scores: dict[ActivityType, float],
    ) -> dict[ActivityType, float]:
        return {
            key: max(0.0, min(1.0, value))
            for key, value in scores.items()
        }

    def _reason_for(
        self,
        activity: ActivityType,
        snapshot: RawScreenSnapshot,
        keyboard: KeyboardActivity,
    ) -> str:
        reasons = {
            ActivityType.CODING: "coding-app evidence is strongest",
            ActivityType.BROWSING: "browser evidence is strongest",
            ActivityType.GAMING: "game-app evidence is strongest",
            ActivityType.STUDYING: "study-page evidence is strongest",
            ActivityType.VIDEO: "video-site evidence is strongest",
            ActivityType.IDLE: "system-idle evidence is strongest",
            ActivityType.OTHER: "no known activity has stronger evidence",
        }
        return reasons[activity]

    @staticmethod
    def _contains_any(text: str, tokens: set[str]) -> bool:
        return any(token in text for token in tokens)
