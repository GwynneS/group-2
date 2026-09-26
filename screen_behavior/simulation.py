"""
Brain simulation harness.

Runs the full pipeline (fake OS sensors -> classifier -> evidence decay ->
user state -> needs -> utility behavior) on simulated time, so hours of
companion behavior can be checked in seconds instead of waiting around for
buddy to get hungry or lonely.

    python3 -m screen_behavior.simulation --scenario workday
    python3 -m screen_behavior.simulation --scenario neglect --hours 6
    python3 -m screen_behavior.simulation --list
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from dataclasses import dataclass, field

from screen_behavior.awareness.activity_tracker import ActivityStabilityTracker
from screen_behavior.awareness.keyboard import KeyboardActivityTracker
from screen_behavior.awareness.models import (
    RawScreenSnapshot,
    ScreenBounds,
    WindowInfo,
)
from screen_behavior.awareness.mouse import (
    ContinuousMouseMonitor,
    MouseMotionTracker,
)
from screen_behavior.awareness.service import AwarenessService
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.behavior import BehaviorEngine
from screen_behavior.pet.config import BEHAVIOR_SPECS
from screen_behavior.pet.enums import Behavior
from screen_behavior.pet.interactions import InteractionEffect


# --- Scenario definition ----------------------------------------------------

APPS: dict[str, WindowInfo | None] = {
    "code": WindowInfo(title="main.py - Visual Studio Code", process_name="Code.exe"),
    "chrome": WindowInfo(title="Reddit - Google Chrome", process_name="chrome.exe"),
    "youtube": WindowInfo(title="YouTube - Google Chrome", process_name="chrome.exe"),
    "docs": WindowInfo(title="Homework - Google Docs - Google Chrome", process_name="chrome.exe"),
    "game": WindowInfo(title="Minecraft", process_name="MinecraftLauncher.exe"),
    "away": None,
}


@dataclass(frozen=True, slots=True)
class Segment:
    minutes: float
    app: str
    typing: bool = False
    mouse: bool = False
    present: bool | None = None  # body tracking; None = camera off

    @property
    def user_input(self) -> bool:
        return self.typing or self.mouse


def _work_block(minutes: float) -> list[Segment]:
    """Coding with realistic short pauses to read/think."""
    out: list[Segment] = []
    remaining = minutes
    while remaining > 0:
        typing = min(8.0, remaining)
        out.append(Segment(typing, "code", typing=True, mouse=True))
        remaining -= typing
        if remaining > 0:
            think = min(1.0, remaining)
            out.append(Segment(think, "code", mouse=True))
            remaining -= think
    return out


SCENARIOS: dict[str, tuple[str, list[Segment]]] = {
    "workday": (
        "~4.5h: coding blocks, a YouTube break, some Reddit drift, lunch away, "
        "studying in Docs",
        [
            *_work_block(50),
            Segment(10, "youtube"),
            *_work_block(45),
            Segment(15, "chrome", mouse=True),
            Segment(30, "away", present=False),
            *_work_block(60),
            Segment(30, "docs", typing=True, mouse=True),
            Segment(20, "away"),
        ],
    ),
    "alt_tab": (
        "30 min coding with a 5-second Alt-Tab to Chrome every 3 minutes",
        [
            seg
            for _ in range(10)
            for seg in (
                Segment(3 - 5 / 60, "code", typing=True, mouse=True),
                Segment(5 / 60, "chrome", mouse=True),
            )
        ],
    ),
    "gaming_evening": (
        "~3h: gaming, YouTube, browsing, then idle",
        [
            Segment(90, "game", typing=True, mouse=True),
            Segment(45, "youtube"),
            Segment(30, "chrome", mouse=True),
            Segment(15, "away"),
        ],
    ),
    "app_hopping": (
        "20 min of switching apps every minute (distracted user)",
        [
            Segment(1, app, typing=True, mouse=True)
            for app in ["code", "chrome", "youtube", "code", "docs"] * 4
        ],
    ),
    "neglect": (
        "user leaves for hours; nobody feeds or answers buddy",
        [Segment(240, "away", present=False)],
    ),
}


# --- Simulated sensors ------------------------------------------------------

class SimClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class SimBackend:
    def __init__(self, clock: SimClock) -> None:
        self._clock = clock
        self.foreground: WindowInfo | None = None
        self.cursor = (500, 500)
        self.last_input = 0.0

    def input(self) -> None:
        self.last_input = self._clock()

    def snapshot(self) -> RawScreenSnapshot:
        return RawScreenSnapshot(
            cursor_x=self.cursor[0],
            cursor_y=self.cursor[1],
            idle_seconds=max(0.0, self._clock() - self.last_input),
            foreground=self.foreground,
            screen_bounds=ScreenBounds(0, 0, 1920, 1080),
        )

    def _cursor_position(self) -> tuple[int, int]:
        return self.cursor


class _NoKeyboardHook:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


# --- Report -----------------------------------------------------------------

@dataclass(slots=True)
class SimulationReport:
    scenario: str
    seconds: float = 0.0
    state_seconds: Counter = field(default_factory=Counter)
    activity_seconds: Counter = field(default_factory=Counter)
    mood_seconds: Counter = field(default_factory=Counter)
    behavior_starts: Counter = field(default_factory=Counter)
    distracting_starts_by_state: Counter = field(default_factory=Counter)
    immediate_repeats: int = 0
    activity_switches: int = 0
    attention_requests: int = 0
    sulks: int = 0
    interactions: int = 0
    feeds: int = 0
    play_dead_episodes: int = 0
    longest_play_dead_seconds: float = 0.0
    min_energy: float = 100.0
    max_hunger: float = 0.0
    min_attention: float = 100.0
    final: dict = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)

    def distracting_per_hour(self, state: str) -> float:
        hours = self.state_seconds.get(state, 0) / 3600
        if hours == 0:
            return 0.0
        return self.distracting_starts_by_state.get(state, 0) / hours

    def format(self) -> str:
        def minutes(counter: Counter) -> str:
            return ", ".join(
                f"{k}={v / 60:.0f}m"
                for k, v in counter.most_common()
            )

        lines = [
            f"=== Simulation: {self.scenario} ({self.seconds / 3600:.1f}h) ===",
            f"user states:   {minutes(self.state_seconds)}",
            f"activities:    {minutes(self.activity_seconds)}  "
            f"(switches={self.activity_switches})",
            f"moods:         {minutes(self.mood_seconds)}",
            "",
            "distracting behaviors per hour, by user state:",
        ]
        for state in self.state_seconds:
            lines.append(
                f"  {state:11} {self.distracting_per_hour(state):5.1f}/h"
            )
        lines += [
            "",
            "behavior starts: " + ", ".join(
                f"{k}={v}" for k, v in self.behavior_starts.most_common()
            ),
            f"immediate repeats: {self.immediate_repeats}",
            f"attention requests: {self.attention_requests}  "
            f"sulks (ignored): {self.sulks}  "
            f"user interactions: {self.interactions}  feeds: {self.feeds}",
            f"play dead: {self.play_dead_episodes} episodes, longest "
            f"{self.longest_play_dead_seconds:.0f}s",
            f"extremes: min energy {self.min_energy:.0f}, max hunger "
            f"{self.max_hunger:.0f}, min attention {self.min_attention:.0f}",
            "final: " + ", ".join(f"{k}={v}" for k, v in self.final.items()),
        ]
        return "\n".join(lines)


# --- Simulator --------------------------------------------------------------

class BrainSimulator:
    def __init__(
        self,
        seed: int = 0,
        step_seconds: float = 1.0,
        attentive_user: bool = True,
        respond_after_seconds: float = 10.0,
        feed_when_hunger_above: float = 70.0,
    ) -> None:
        self.step = step_seconds
        self.attentive = attentive_user
        self.respond_after = respond_after_seconds
        self.feed_threshold = feed_when_hunger_above
        self.rng = random.Random(seed)

        self.clock = SimClock()
        self.backend = SimBackend(self.clock)
        keyboard = KeyboardActivityTracker(clock=self.clock)
        keyboard.set_monitoring_available(True)
        self.keyboard = keyboard
        self.mouse = ContinuousMouseMonitor(
            self.backend._cursor_position,
            tracker=MouseMotionTracker(clock=self.clock),
        )
        self.mouse.tracker.set_monitoring_available(True)

        self.awareness = AwarenessService(
            backend=self.backend,
            activity_tracker=ActivityStabilityTracker(clock=self.clock),
            keyboard_tracker=keyboard,
            keyboard_monitor=_NoKeyboardHook(),
            start_keyboard_monitor=False,
            mouse_monitor=self.mouse,
            start_mouse_monitor=False,
        )
        self.brain = CompanionBrain(
            awareness=self.awareness,
            behavior=BehaviorEngine(
                rng=random.Random(seed),
                clock=self.clock,
            ),
            clock=self.clock,
        )

    def run(
        self,
        segments: list[Segment],
        name: str = "custom",
        hours: float | None = None,
    ) -> SimulationReport:
        report = SimulationReport(scenario=name)
        total = sum(s.minutes for s in segments) * 60
        target = hours * 3600 if hours else total

        last_started: Behavior | None = None
        current: Behavior | None = None
        ask_started_at: float | None = None
        play_dead_since: float | None = None
        elapsed = 0.0

        while elapsed < target:
            for segment in segments:
                seg_end = elapsed + segment.minutes * 60
                self.backend.foreground = APPS[segment.app]
                self.awareness.set_user_present(segment.present)

                while elapsed < seg_end and elapsed < target:
                    self._drive_sensors(segment)
                    update = self.brain.update()
                    now = self.clock()

                    behavior = update.decision.behavior
                    state = (update.screen.user_state or "none").__str__()

                    if behavior != current:
                        report.behavior_starts[behavior.value] += 1
                        if BEHAVIOR_SPECS[behavior].distracting:
                            report.distracting_starts_by_state[state] += 1
                        if behavior == last_started:
                            report.immediate_repeats += 1
                        if behavior == Behavior.ASK_FOR_ATTENTION:
                            report.attention_requests += 1
                            ask_started_at = now
                        if "ignored" in update.decision.reason:
                            report.sulks += 1
                        if behavior == Behavior.PLAY_DEAD:
                            report.play_dead_episodes += 1
                            play_dead_since = now
                        if current == Behavior.PLAY_DEAD and play_dead_since is not None:
                            report.longest_play_dead_seconds = max(
                                report.longest_play_dead_seconds,
                                now - play_dead_since,
                            )
                        last_started = behavior
                        current = behavior

                    if self._simulated_user(
                        report, segment, now, ask_started_at,
                    ):
                        ask_started_at = None  # answered once

                    self._record(report, update, state)
                    self.clock.value += self.step
                    elapsed += self.step

                if elapsed >= target:
                    break

        report.final = {
            "hunger": round(self.brain.pet.hunger),
            "energy": round(self.brain.pet.energy),
            "attention": round(self.brain.pet.attention),
            "affection": round(self.brain.pet.affection),
            "mood": self.brain.pet.mood.value,
            "budget": round(self.brain.behavior.budget.value),
        }
        return report

    def _drive_sensors(self, segment: Segment) -> None:
        if segment.user_input:
            self.backend.input()
        if segment.typing:
            for _ in range(3):
                self.keyboard.record_keypress()
        if segment.mouse:
            x, y = self.backend.cursor
            self.backend.cursor = (
                max(0, min(1919, x + self.rng.randint(-40, 40))),
                max(0, min(1079, y + self.rng.randint(-40, 40))),
            )
        self.mouse.poll_once()

    def _simulated_user(
        self,
        report: SimulationReport,
        segment: Segment,
        now: float,
        ask_started_at: float | None,
    ) -> bool:
        """Returns True if the user answered an attention request."""
        # Only a present, attentive user answers buddy or feeds it.
        if not self.attentive or segment.app == "away":
            return False

        if self.brain.pet.hunger >= self.feed_threshold:
            if self.brain.feed().accepted:
                report.feeds += 1

        if (
            ask_started_at is not None
            and now - ask_started_at >= self.respond_after
        ):
            self.brain.apply_interaction(
                InteractionEffect(attention_delta=30, affection_delta=5)
            )
            report.interactions += 1
            return True
        return False

    def _record(self, report: SimulationReport, update, state: str) -> None:
        pet = update.pet
        report.seconds += self.step
        report.state_seconds[state] += self.step
        report.activity_seconds[update.screen.activity.value] += self.step
        report.mood_seconds[pet.mood.value] += self.step
        if update.screen.activity_changed:
            report.activity_switches += 1
        report.min_energy = min(report.min_energy, pet.energy)
        report.max_hunger = max(report.max_hunger, pet.hunger)
        report.min_attention = min(report.min_attention, pet.attention)

        if int(report.seconds) % 60 == 0:
            report.timeline.append({
                "minute": int(report.seconds // 60),
                "activity": update.screen.activity.value,
                "user_state": state,
                "behavior": update.decision.behavior.value,
                "mood": pet.mood.value,
                "hunger": round(pet.hunger, 1),
                "energy": round(pet.energy, 1),
                "attention": round(pet.attention, 1),
                "budget": round(update.decision.distraction_budget, 1),
            })


def run_scenario(
    name: str,
    seed: int = 0,
    hours: float | None = None,
    attentive_user: bool | None = None,
) -> SimulationReport:
    if attentive_user is None:
        attentive_user = name != "neglect"
    _, segments = SCENARIOS[name]
    simulator = BrainSimulator(seed=seed, attentive_user=attentive_user)
    return simulator.run(segments, name=name, hours=hours)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scenario", default="workday", choices=SCENARIOS)
    parser.add_argument("--hours", type=float, help="repeat scenario to fill")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--ignore-buddy",
        action="store_true",
        help="simulated user never answers or feeds buddy",
    )
    parser.add_argument("--csv", help="write per-minute timeline to this file")
    parser.add_argument("--list", action="store_true", help="list scenarios")
    args = parser.parse_args()

    if args.list:
        for name, (description, _) in SCENARIOS.items():
            print(f"  {name:15} {description}")
        return

    report = run_scenario(
        args.scenario,
        seed=args.seed,
        hours=args.hours,
        attentive_user=False if args.ignore_buddy else None,
    )
    print(report.format())

    if args.csv:
        with open(args.csv, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(report.timeline[0]))
            writer.writeheader()
            writer.writerows(report.timeline)
        print(f"\ntimeline written to {args.csv}")


if __name__ == "__main__":
    main()
