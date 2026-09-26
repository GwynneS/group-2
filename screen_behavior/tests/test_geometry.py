import unittest

from screen_behavior.awareness.geometry import (
    calculate_window_edge_awareness,
)
from screen_behavior.awareness.models import (
    RawScreenSnapshot,
    WindowInfo,
)


class GeometryTests(unittest.TestCase):
    def test_cursor_near_left_edge(self):
        result = calculate_window_edge_awareness(
            RawScreenSnapshot(
                cursor_x=105,
                cursor_y=250,
                foreground=WindowInfo(
                    left=100,
                    top=100,
                    right=800,
                    bottom=600,
                ),
            ),
            near_threshold_px=20,
        )

        self.assertTrue(result.available)
        self.assertTrue(result.cursor_near_window_edge)
        self.assertEqual(result.nearest_edge, "left")
        self.assertEqual(
            result.distance_to_nearest_edge_px,
            5.0,
        )


if __name__ == "__main__":
    unittest.main()
