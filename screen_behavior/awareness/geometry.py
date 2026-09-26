from __future__ import annotations

from screen_behavior.awareness.models import (
    RawScreenSnapshot,
    WindowEdgeAwareness,
)


def calculate_window_edge_awareness(
    snapshot: RawScreenSnapshot,
    near_threshold_px: int = 28,
) -> WindowEdgeAwareness:
    fg = snapshot.foreground

    if fg is None or not fg.has_geometry:
        return WindowEdgeAwareness(available=False)

    x = snapshot.cursor_x
    y = snapshot.cursor_y

    inside = fg.left <= x <= fg.right and fg.top <= y <= fg.bottom

    distances = {
        "left": abs(x - fg.left),
        "right": abs(fg.right - x),
        "top": abs(y - fg.top),
        "bottom": abs(fg.bottom - y),
    }

    nearest_edge = min(distances, key=distances.get)
    nearest_distance = float(distances[nearest_edge])

    return WindowEdgeAwareness(
        available=True,
        cursor_inside_foreground_window=inside,
        cursor_near_window_edge=nearest_distance <= near_threshold_px,
        nearest_edge=nearest_edge,
        distance_to_nearest_edge_px=nearest_distance,
    )
