from __future__ import annotations

from screen_behavior.awareness.models import (
    RawScreenSnapshot,
    ScreenBounds,
    WindowInfo,
)


class MacOSAwarenessBackend:
    """
    macOS-first awareness backend.

    Foreground app, cursor position, idle time, screen bounds, and best-effort
    foreground-window title/bounds are gathered locally.

    macOS may restrict some window metadata depending on privacy permissions.
    Missing title/geometry is treated as unavailable rather than fatal.
    """

    def __init__(self) -> None:
        try:
            from AppKit import NSWorkspace  # noqa: F401
            import Quartz  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "macOS support requires PyObjC. Install with:\n"
                "python3 -m pip install -r "
                "screen_behavior/requirements-macos.txt"
            ) from exc

    def snapshot(self) -> RawScreenSnapshot:
        x, y = self._cursor_position()
        foreground = self._foreground_app()
        self._try_attach_front_window_info(foreground)

        return RawScreenSnapshot(
            cursor_x=x,
            cursor_y=y,
            idle_seconds=self._idle_seconds(),
            foreground=foreground,
            screen_bounds=self._screen_bounds(),
        )

    def _cursor_position(self) -> tuple[int, int]:
        import Quartz

        event = Quartz.CGEventCreate(None)
        point = Quartz.CGEventGetLocation(event)
        return int(point.x), int(point.y)

    def _idle_seconds(self) -> float:
        import Quartz

        return float(
            Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateCombinedSessionState,
                Quartz.kCGAnyInputEventType,
            )
        )

    def _screen_bounds(self) -> ScreenBounds:
        import Quartz

        rect = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())

        return ScreenBounds(
            left=int(rect.origin.x),
            top=int(rect.origin.y),
            right=int(rect.origin.x + rect.size.width),
            bottom=int(rect.origin.y + rect.size.height),
        )

    def _foreground_app(self) -> WindowInfo:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()

        if app is None:
            return WindowInfo()

        app_name = app.localizedName() or ""
        bundle_id = app.bundleIdentifier() or ""

        try:
            pid = int(app.processIdentifier())
        except Exception:
            pid = None

        return WindowInfo(
            app_name=app_name,
            process_name=app_name,
            bundle_id=bundle_id,
            pid=pid,
        )

    def _try_attach_front_window_info(
        self,
        foreground: WindowInfo,
    ) -> None:
        try:
            import Quartz

            options = (
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements
            )

            windows = Quartz.CGWindowListCopyWindowInfo(
                options,
                Quartz.kCGNullWindowID,
            )

            for info in windows or []:
                owner_pid = info.get(Quartz.kCGWindowOwnerPID)

                if foreground.pid and owner_pid != foreground.pid:
                    continue

                name = info.get(Quartz.kCGWindowName) or ""

                if name:
                    foreground.title = str(name)

                bounds = info.get(Quartz.kCGWindowBounds) or {}

                try:
                    x = float(bounds.get("X", 0))
                    y = float(bounds.get("Y", 0))
                    width = float(bounds.get("Width", 0))
                    height = float(bounds.get("Height", 0))

                    if width > 0 and height > 0:
                        foreground.left = int(x)
                        foreground.top = int(y)
                        foreground.right = int(x + width)
                        foreground.bottom = int(y + height)
                except Exception:
                    pass

                # First matching on-screen window for the frontmost app.
                if foreground.title or foreground.has_geometry:
                    break

        except Exception:
            # Best-effort only. Privacy limitations must not crash awareness.
            return
