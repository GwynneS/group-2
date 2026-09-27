"""
Utility behavior brain: scoring, selection, memory, urgency, explainability.

Most checks run many seeds or compare scores, instead of depending on one
exact random draw.
"""
import random
import unittest

from screen_behavior.awareness.models import (
    ActivityType,
    KeyboardActivity,
    ScreenContext,
    UserState,
)
from screen_behavior.pet.behavior import BehaviorEngine, ExternalSignals
from screen_behavior.pet.config import BEHAVIOR_SPECS
from screen_behavior.pet.enums import BaseMood, Behavior, SpecialMood
from screen_behavior.pet.interactions import (
    InteractionEffect,
    apply_interaction_effect,
)
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem
from screen_behavior.pet.utility_config import BehaviorUtilityConfig


class Clock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


FOCUSED_CODING = ScreenContext(
    activity=ActivityType.CODING,
    activity_confidence=0.95,
    activity_duration_seconds=1200,
    keyboard=KeyboardActivity(monitoring_available=True, typing_active=True),
    user_state=UserState.FOCUSED,
)
IDLE = ScreenContext(
    activity=ActivityType.IDLE,
    idle_seconds=240,
    user_state=UserState.IDLE,
)
VIDEO = ScreenContext(
    activity=ActivityType.VIDEO,
    activity_confidence=0.9,
    user_state=UserState.PASSIVE,
)
GAMING = ScreenContext(
    activity=ActivityType.GAMING,
    activity_confidence=0.9,
    user_state=UserState.ACTIVE,
)

QUIET = {
    Behavior.STUDY_WITH_USER,
    Behavior.SIT_DOWN,
    Behavior.WATCH_SCREEN,
    Behavior.FOLLOW_MOUSE_WITH_EYES,
    Behavior.LOOK_AROUND,
    Behavior.STRETCH,
    Behavior.IDLE,
}
PLAYFUL = {
    Behavior.WAVE,
    Behavior.DANCE,
    Behavior.WALK_AROUND_CORNER,
    Behavior.SEND_KISS,
}


def engine(seed=0, clock=None, **kwargs):
    return BehaviorEngine(
        rng=random.Random(seed),
        clock=clock or Clock(),
        **kwargs,
    )


def scores(pet, screen, seed=0, eng=None):
    eng = eng or engine(seed)
    return {s.behavior: s for s in eng.score_all(pet, screen)}


def first_choices(pet_factory, screen, seeds=range(40)):
    return [engine(seed).decide(pet_factory(), screen) for seed in seeds]


class FocusTests(unittest.TestCase):
    def test_focused_work_strongly_favors_quiet_behaviors(self):
        decisions = first_choices(lambda: PetState(energy=90), FOCUSED_CODING)

        self.assertTrue(all(d.behavior in QUIET for d in decisions))
        leaders = {max(d.behavior_scores, key=d.behavior_scores.get) for d in decisions}
        self.assertEqual(leaders, {Behavior.STUDY_WITH_USER})

    def test_distracting_behaviors_penalized_during_focus(self):
        pet = PetState(energy=100, boredom=70)
        focused = scores(pet, FOCUSED_CODING)
        idle = scores(pet, IDLE)

        for behavior in [Behavior.DANCE, Behavior.WALK_AROUND_CORNER,
                         Behavior.ASK_FOR_ATTENTION]:
            with self.subTest(behavior.value):
                self.assertLess(
                    focused[behavior].breakdown.components.get("distraction", 0),
                    -20,
                )
                self.assertLess(focused[behavior].score, idle[behavior].score)
        self.assertGreater(
            focused[Behavior.STUDY_WITH_USER].score,
            3 * focused[Behavior.DANCE].score,
        )

    def test_attention_requests_suppressed_while_focused_unless_critical(self):
        lonely = PetState(attention=30)
        decisions = first_choices(lambda: PetState(attention=30), FOCUSED_CODING)
        self.assertNotIn(
            Behavior.ASK_FOR_ATTENTION, {d.behavior for d in decisions}
        )
        self.assertLess(
            scores(lonely, FOCUSED_CODING)[Behavior.ASK_FOR_ATTENTION].score,
            scores(lonely, IDLE)[Behavior.ASK_FOR_ATTENTION].score,
        )

        critical = engine().decide(PetState(attention=10), FOCUSED_CODING)
        self.assertEqual(critical.behavior, Behavior.ASK_FOR_ATTENTION)
        self.assertEqual(critical.source, "urgent")

    def test_idle_user_allows_social_and_playful_behavior(self):
        decisions = first_choices(
            lambda: PetState(energy=90, boredom=50), IDLE,
        )
        playful = [d for d in decisions if d.behavior in PLAYFUL]

        self.assertGreater(len(playful), len(decisions) // 3)

    def test_video_and_gaming_favor_watch_screen(self):
        for screen in (VIDEO, GAMING):
            with self.subTest(screen.activity.value):
                s = scores(PetState(), screen)
                self.assertEqual(max(s, key=lambda b: s[b].score), Behavior.WATCH_SCREEN)


class UrgencyAndCommitmentTests(unittest.TestCase):
    def test_low_energy_forces_sleep(self):
        decision = engine().decide(PetState(energy=10), FOCUSED_CODING)

        self.assertEqual(decision.behavior, Behavior.SLEEP)
        self.assertEqual(decision.source, "urgent")

    def test_severe_hunger_is_urgent(self):
        decision = engine().decide(PetState(hunger=90), IDLE)

        self.assertEqual(decision.behavior, Behavior.ASK_FOR_ATTENTION)
        self.assertEqual(decision.source, "urgent")

    def test_commitment_prevents_rerolling(self):
        clock = Clock()
        eng = engine(clock=clock)
        pet = PetState(energy=90)

        first = eng.decide(pet, FOCUSED_CODING)
        for _ in range(5):
            clock.advance(1)
            held = eng.decide(pet, FOCUSED_CODING)
            self.assertEqual(held.behavior, first.behavior)
            self.assertEqual(held.source, "commitment")

    def test_urgent_need_interrupts_commitment(self):
        clock = Clock()
        eng = engine(clock=clock)
        pet = PetState(energy=90)
        first = eng.decide(pet, FOCUSED_CODING)
        self.assertGreater(first.commitment_remaining_seconds, 5)

        clock.advance(1)
        pet.energy = 12
        interrupted = eng.decide(pet, FOCUSED_CODING)

        self.assertEqual(interrupted.behavior, Behavior.SLEEP)
        self.assertEqual(interrupted.source, "urgent")

    def test_not_tired_enough_to_nap(self):
        s = engine().decide(PetState(energy=80), IDLE)
        self.assertNotIn(Behavior.SLEEP, s.behavior_scores)

        tired = engine().decide(PetState(energy=30), IDLE)
        self.assertIn(Behavior.SLEEP, tired.behavior_scores)


class EligibilityTests(unittest.TestCase):
    def test_cooldowns_are_respected(self):
        clock = Clock()
        eng = engine(clock=clock)
        pet = PetState(energy=100)
        eng._start(pet, Behavior.DANCE, "test", clock(), force=True)

        clock.advance(BEHAVIOR_SPECS[Behavior.DANCE].commitment_seconds + 1)
        decision = eng.decide(pet, IDLE)

        self.assertNotIn(Behavior.DANCE, decision.behavior_scores)
        self.assertNotEqual(decision.behavior, Behavior.DANCE)

    def test_min_energy_excludes_before_scoring(self):
        decision = engine().decide(PetState(energy=40), IDLE)

        self.assertNotIn(Behavior.DANCE, decision.behavior_scores)  # needs 55

    def test_energy_cost_only_charged_when_behavior_starts(self):
        clock = Clock()
        eng = engine(clock=clock)
        pet = PetState(energy=100)
        eng._start(pet, Behavior.DANCE, "test", clock(), force=True)
        after_start = pet.energy

        for _ in range(3):
            clock.advance(1)
            eng.decide(pet, IDLE)

        self.assertEqual(after_start, 100 - BEHAVIOR_SPECS[Behavior.DANCE].energy_cost)
        self.assertEqual(pet.energy, after_start)


class MemoryTests(unittest.TestCase):
    def test_recent_repetition_reduces_utility(self):
        eng = engine()
        pet = PetState()
        before = scores(pet, FOCUSED_CODING, eng=eng)[Behavior.LOOK_AROUND]

        for t in range(3):
            eng.memory.record_behavior(Behavior.LOOK_AROUND, 900 + t)
        after = scores(pet, FOCUSED_CODING, eng=eng)[Behavior.LOOK_AROUND]

        self.assertLess(after.score, before.score)
        self.assertLess(after.breakdown.components["repetition"], -20)

    def test_attention_request_discouraged_after_commitment_ends(self):
        clock = Clock()
        eng = engine(clock=clock)
        pet = PetState(attention=35)
        base = scores(pet, IDLE, eng=eng)[Behavior.ASK_FOR_ATTENTION].score

        eng.memory.record_behavior(Behavior.ASK_FOR_ATTENTION, clock())
        clock.advance(60)  # well past its 8s commitment
        after = scores(pet, IDLE, eng=eng)[Behavior.ASK_FOR_ATTENTION]

        self.assertLess(after.score, base - 25)
        self.assertIn("attention_request", after.breakdown.components)

    def test_history_is_bounded(self):
        eng = engine(utility_config=BehaviorUtilityConfig(history_size=8))
        for t in range(200):
            eng.memory.record_behavior(Behavior.IDLE, t)

        self.assertEqual(len(eng.memory.history), 8)

    def test_repeated_cycles_have_variety(self):
        clock = Clock()
        eng = engine(seed=3, clock=clock)
        pet = PetState(energy=90)
        chosen = []
        for _ in range(40):
            clock.advance(35)
            pet.energy = 90
            chosen.append(eng.decide(pet, FOCUSED_CODING).behavior)

        self.assertGreaterEqual(len(set(chosen)), 3)
        longest = run = 1
        for a, b in zip(chosen, chosen[1:]):
            run = run + 1 if a == b else 1
            longest = max(longest, run)
        self.assertLessEqual(longest, 3)


class SelectionTests(unittest.TestCase):
    def test_seeded_rng_is_deterministic(self):
        def run(seed):
            clock = Clock()
            eng = engine(seed=seed, clock=clock)
            pet = PetState(energy=90, boredom=40)
            out = []
            for i in range(30):
                clock.advance(20)
                out.append(eng.decide(pet, IDLE if i % 3 else VIDEO).behavior)
            return out

        self.assertEqual(run(7), run(7))

    def test_low_scorers_never_beat_strong_behaviors(self):
        cfg = BehaviorUtilityConfig()
        for seed in range(60):
            d = engine(seed).decide(PetState(energy=90), FOCUSED_CODING)
            best = max(d.behavior_scores.values())
            floor = max(best - cfg.near_best_margin, best * cfg.min_fraction_of_best)
            self.assertGreaterEqual(d.behavior_scores[d.behavior], floor)

    def test_debug_data_is_consistent(self):
        d = engine().decide(PetState(), FOCUSED_CODING)

        self.assertEqual(d.source, "utility")
        self.assertTrue(all(isinstance(b, Behavior) for b in d.behavior_scores))
        self.assertIn(d.behavior, d.candidates)
        self.assertTrue(set(d.candidates) <= set(d.behavior_scores))
        self.assertAlmostEqual(
            sum(d.score_breakdown.values()),
            d.behavior_scores[d.behavior],
            delta=0.5,
        )
        self.assertIn("base", d.score_breakdown)

    def test_non_utility_decisions_have_empty_debug_data(self):
        d = engine().decide(PetState(energy=5), IDLE)

        self.assertEqual(d.source, "urgent")
        self.assertEqual(d.behavior_scores, {})

    def test_preference_bonus_is_bounded(self):
        cfg = BehaviorUtilityConfig()
        eng = engine(preference=lambda behavior, ctx: 1000.0)

        s = scores(PetState(), FOCUSED_CODING, eng=eng)[Behavior.DANCE]

        self.assertEqual(s.breakdown.components["preference"], cfg.max_preference_bonus)


class MoodAndHyperTests(unittest.TestCase):
    def test_affectionate_special_mood_favors_send_kiss(self):
        pet = PetState(energy=95, affection=90)
        normal = scores(pet, IDLE)[Behavior.SEND_KISS].score
        pet.special_mood = SpecialMood.AFFECTIONATE

        self.assertGreater(scores(pet, IDLE)[Behavior.SEND_KISS].score, normal + 20)

    def test_tired_mood_prefers_rest(self):
        pet = PetState(energy=30)
        pet.mood = BaseMood.TIRED
        s = scores(pet, IDLE)

        self.assertGreater(s[Behavior.SIT_DOWN].score, s[Behavior.DANCE].score)

    def test_hyper_boosts_energetic_behaviors_and_wears_off(self):
        pet = PetState(energy=90)
        calm = scores(pet, IDLE)[Behavior.DANCE].score

        apply_interaction_effect(pet, InteractionEffect(hyper_seconds=30))
        self.assertTrue(pet.is_hyper)
        self.assertGreater(scores(pet, IDLE)[Behavior.DANCE].score, calm + 20)

        NeedsSystem().tick(pet, 31)
        self.assertFalse(pet.is_hyper)

    def test_hyper_pet_is_excited(self):
        pet = PetState(hyper_seconds_remaining=10)
        NeedsSystem().update_mood(pet)

        self.assertEqual(pet.mood, BaseMood.EXCITED)


class PlayDeadTests(unittest.TestCase):
    def test_loud_signal_wakes_play_dead(self):
        clock = Clock()
        eng = engine(clock=clock)
        pet = PetState(energy=90)
        eng._start(pet, Behavior.PLAY_DEAD, "test", clock(), force=True)

        clock.advance(5)
        held = eng.decide(pet, IDLE)
        self.assertEqual(held.behavior, Behavior.PLAY_DEAD)

        clock.advance(1)
        woke = eng.decide(pet, IDLE, ExternalSignals(loud_voice_detected=True))
        self.assertEqual(woke.behavior, Behavior.WAVE)
        self.assertEqual(woke.mood, BaseMood.SURPRISED)
        self.assertFalse(pet.play_dead_active)


if __name__ == "__main__":
    unittest.main()
