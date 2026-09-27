"""
Whole-brain checks over simulated hours. These catch problems that only
show up over time (oscillating sleep, stuck play-dead, nagging, flicker).
"""
import unittest

from screen_behavior.simulation import run_scenario


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workday = run_scenario("workday", seed=1)
        cls.alt_tab = run_scenario("alt_tab", seed=1)
        cls.neglect = run_scenario("neglect", seed=1)
        cls.gaming = run_scenario("gaming_evening", seed=1)

    def test_focused_user_is_not_distracted_much(self):
        self.assertLessEqual(self.workday.distracting_per_hour("focused"), 2)

    def test_pet_is_freer_when_user_is_away(self):
        self.assertGreater(
            self.neglect.distracting_per_hour("away"),
            self.workday.distracting_per_hour("focused"),
        )

    def test_brief_alt_tabs_do_not_flip_activity(self):
        self.assertEqual(self.alt_tab.activity_switches, 0)
        self.assertEqual(
            set(self.alt_tab.activity_seconds),
            {"coding"},
        )

    def test_workday_detects_focus_and_away(self):
        self.assertGreater(self.workday.state_seconds["focused"], 2 * 3600)
        self.assertGreater(self.workday.state_seconds["away"], 30 * 60)

    def test_no_immediate_repeats(self):
        for report in (self.workday, self.gaming, self.neglect):
            self.assertEqual(report.immediate_repeats, 0, report.scenario)

    def test_sleep_does_not_oscillate(self):
        for report in (self.workday, self.gaming, self.neglect):
            per_hour = report.behavior_starts["sleep"] / (report.seconds / 3600)
            self.assertLessEqual(per_hour, 4, report.scenario)

    def test_play_dead_never_gets_stuck(self):
        for report in (self.workday, self.gaming, self.neglect):
            self.assertLessEqual(
                report.longest_play_dead_seconds, 91, report.scenario,
            )

    def test_neglected_pet_gets_hungry_and_asks_for_attention(self):
        self.assertGreater(self.neglect.max_hunger, 60)
        self.assertGreater(self.neglect.attention_requests, 0)
        self.assertEqual(self.neglect.feeds, 0)

    def test_attentive_user_keeps_pet_fed(self):
        self.assertLess(self.workday.max_hunger, 80)

    def test_same_seed_is_reproducible(self):
        again = run_scenario("alt_tab", seed=1)
        self.assertEqual(again.behavior_starts, self.alt_tab.behavior_starts)

    def test_report_formats(self):
        text = self.workday.format()
        self.assertIn("distracting behaviors per hour", text)
        self.assertTrue(self.workday.timeline)


if __name__ == "__main__":
    unittest.main()
