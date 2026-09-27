import unittest

from screen_behavior.awareness.mouse import (
    ContinuousMouseMonitor,
    MouseActivity,
    MouseMotionTracker,
)


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def make_tracker():
    clock = FakeClock()
    tracker = MouseMotionTracker(clock=clock)
    tracker.set_monitoring_available(True)
    return tracker, clock


class MouseMotionTrackerTests(unittest.TestCase):
    def test_unavailable_reports_unavailable(self):
        tracker = MouseMotionTracker(clock=FakeClock())

        self.assertFalse(tracker.snapshot().monitoring_available)

    def test_position_is_latest_sample(self):
        tracker, clock = make_tracker()

        tracker.record_position(10, 20)
        clock.advance(0.03)
        tracker.record_position(40, 60)

        snapshot = tracker.snapshot()
        self.assertEqual((snapshot.x, snapshot.y), (40, 60))

    def test_velocity_and_moving(self):
        tracker, clock = make_tracker()

        # 10 px right every 1/30 s = 300 px/s.
        for i in range(5):
            tracker.record_position(i * 10, 100)
            clock.advance(1 / 30)
        clock.value -= 1 / 30  # snapshot at time of last sample

        snapshot = tracker.snapshot()

        self.assertAlmostEqual(snapshot.velocity_x, 300.0, delta=1.0)
        self.assertAlmostEqual(snapshot.velocity_y, 0.0)
        self.assertTrue(snapshot.moving)

    def test_still_mouse_is_not_moving(self):
        tracker, clock = make_tracker()

        tracker.record_position(0, 0)
        clock.advance(0.03)
        tracker.record_position(50, 0)
        for _ in range(30):
            clock.advance(1 / 30)
            tracker.record_position(50, 0)

        snapshot = tracker.snapshot()

        self.assertFalse(snapshot.moving)
        self.assertEqual(snapshot.speed, 0.0)
        self.assertAlmostEqual(snapshot.seconds_since_move, 1.0, places=5)

    def test_never_moved(self):
        tracker, clock = make_tracker()

        tracker.record_position(5, 5)
        clock.advance(1)
        tracker.record_position(5, 5)

        self.assertIsNone(tracker.snapshot().seconds_since_move)

    def test_distance_last_5_seconds(self):
        tracker, clock = make_tracker()

        tracker.record_position(0, 0)
        clock.advance(1)
        tracker.record_position(30, 40)   # 50 px
        clock.advance(1)
        tracker.record_position(30, 140)  # 100 px

        self.assertAlmostEqual(
            tracker.snapshot().distance_last_5_seconds,
            150.0,
        )

        clock.advance(10)
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.distance_last_5_seconds, 0.0)
        # Position is kept even after history expires.
        self.assertEqual((snapshot.x, snapshot.y), (30, 140))


class LookDirectionTests(unittest.TestCase):
    def test_look_right(self):
        look = MouseActivity(x=200, y=100).look_from(100, 100)

        self.assertAlmostEqual(look.dx, 1.0)
        self.assertAlmostEqual(look.dy, 0.0)
        self.assertAlmostEqual(look.distance_px, 100.0)
        self.assertAlmostEqual(look.angle_degrees, 0.0)

    def test_look_up_left(self):
        look = MouseActivity(x=0, y=0).look_from(100, 100)

        self.assertAlmostEqual(look.angle_degrees, 225.0)
        self.assertLess(look.dx, 0)
        self.assertLess(look.dy, 0)

    def test_cursor_on_pet(self):
        look = MouseActivity(x=50, y=50).look_from(50, 50)

        self.assertEqual(look.distance_px, 0.0)


class ContinuousMouseMonitorTests(unittest.TestCase):
    def test_poll_feeds_tracker_and_listeners(self):
        positions = iter([(1, 1), (1, 1), (5, 9)])
        seen = []
        monitor = ContinuousMouseMonitor(lambda: next(positions))
        monitor.tracker.set_monitoring_available(True)
        monitor.add_listener(lambda x, y: seen.append((x, y)))

        monitor.poll_once()
        monitor.poll_once()
        monitor.poll_once()

        # Listener only fires on change.
        self.assertEqual(seen, [(1, 1), (5, 9)])
        self.assertEqual(
            (monitor.snapshot().x, monitor.snapshot().y),
            (5, 9),
        )

    def test_broken_listener_does_not_stop_tracking(self):
        monitor = ContinuousMouseMonitor(lambda: (3, 4))
        monitor.tracker.set_monitoring_available(True)
        monitor.add_listener(lambda x, y: 1 / 0)

        monitor.poll_once()

        self.assertEqual(monitor.snapshot().x, 3)

    def test_failed_reader_reports_unavailable(self):
        def broken():
            raise OSError("no display")

        monitor = ContinuousMouseMonitor(broken)
        monitor.start()

        self.assertFalse(monitor.snapshot().monitoring_available)

    def test_background_thread_starts_and_stops(self):
        monitor = ContinuousMouseMonitor(lambda: (7, 8), hz=200)
        monitor.start()
        try:
            snapshot = monitor.snapshot()
            self.assertTrue(snapshot.monitoring_available)
            self.assertEqual((snapshot.x, snapshot.y), (7, 8))
        finally:
            monitor.stop()


if __name__ == "__main__":
    unittest.main()
