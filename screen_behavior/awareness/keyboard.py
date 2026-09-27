from __future__ import annotations

import platform
import threading
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from types import SimpleNamespace
from typing import Callable

from screen_behavior.awareness.models import KeyboardActivity, Shortcut


_LETTER_TO_SHORTCUT = {
    "c": Shortcut.COPY,
    "v": Shortcut.PASTE,
    "z": Shortcut.UNDO,
}

# Physical key codes, so detection works even when Ctrl turns 'c' into '\x03'.
_MAC_VK = {8: "c", 9: "v", 6: "z"}              # kVK_ANSI_C / V / Z
_WINDOWS_VK = {0x43: "c", 0x56: "v", 0x5A: "z"}  # VK_C / VK_V / VK_Z


def modifier_name(key) -> str | None:
    """'ctrl' / 'cmd' for modifier keys, else None."""
    name = getattr(key, "name", None) or ""
    if name.startswith("ctrl"):
        return "ctrl"
    if name.startswith("cmd"):
        return "cmd"
    return None


def shortcut_for_key(
    key,
    modifiers_held: set[str],
    is_mac: bool,
) -> Shortcut | None:
    """
    Map a keypress to copy/paste/undo, or None.

    Only C, V, Z while Ctrl or Cmd is held are recognized. Every other key
    returns None and its identity is discarded by the caller.
    """
    if not modifiers_held:
        return None

    vk_map = _MAC_VK if is_mac else _WINDOWS_VK
    vk = getattr(key, "vk", None)
    if vk in vk_map:
        return _LETTER_TO_SHORTCUT[vk_map[vk]]

    char = getattr(key, "char", None)
    if not char:
        return None
    char = char.lower()
    if char in _LETTER_TO_SHORTCUT:
        return _LETTER_TO_SHORTCUT[char]

    # Ctrl+letter often arrives as a control character (\x03 = Ctrl+C).
    code = ord(char[0])
    if 1 <= code <= 26:
        return _LETTER_TO_SHORTCUT.get(chr(code + 96))
    return None


class KeyboardActivityTracker:
    """
    Aggregate-only keyboard activity.

    `record_keypress()` receives no key identity. It records only a timestamp.
    This prevents the public model from ever containing typed characters,
    key names, words, passwords, or key sequences.

    The one exception is `record_shortcut()`, which receives only
    copy/paste/undo, never the underlying key.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        typing_active_window_seconds: float = 2.0,
        burst_gap_seconds: float = 3.0,
    ) -> None:
        self._clock = clock
        self._typing_active_window = typing_active_window_seconds
        self._burst_gap = burst_gap_seconds
        self._timestamps: deque[float] = deque()
        self._last_keypress: float | None = None
        self._burst_started_at: float | None = None
        self._monitoring_available = False
        self._last_shortcut: Shortcut | None = None
        self._last_shortcut_at: float | None = None
        self._shortcut_counts: dict[Shortcut, int] = {}
        self._lock = Lock()

    def set_monitoring_available(self, value: bool) -> None:
        with self._lock:
            self._monitoring_available = bool(value)

    def record_keypress(self) -> None:
        now = self._clock()
        with self._lock:
            if (
                self._last_keypress is None
                or now - self._last_keypress > self._burst_gap
            ):
                self._burst_started_at = now

            self._last_keypress = now
            self._timestamps.append(now)
            self._prune(now)

    def record_shortcut(self, shortcut: Shortcut) -> None:
        now = self._clock()
        with self._lock:
            self._last_shortcut = shortcut
            self._last_shortcut_at = now
            self._shortcut_counts[shortcut] = (
                self._shortcut_counts.get(shortcut, 0) + 1
            )

    def snapshot(self) -> KeyboardActivity:
        now = self._clock()

        with self._lock:
            self._prune(now)

            if not self._monitoring_available:
                return KeyboardActivity(monitoring_available=False)

            last_5 = sum(1 for t in self._timestamps if now - t <= 5.0)
            last_30 = sum(1 for t in self._timestamps if now - t <= 30.0)
            last_60 = len(self._timestamps)

            if self._last_keypress is None:
                seconds_since = None
                no_typing_duration = None
                typing_active = False
                burst_duration = 0.0
            else:
                seconds_since = max(0.0, now - self._last_keypress)
                no_typing_duration = seconds_since
                typing_active = seconds_since <= self._typing_active_window

                if (
                    typing_active
                    and self._burst_started_at is not None
                ):
                    burst_duration = max(0.0, now - self._burst_started_at)
                else:
                    burst_duration = 0.0

            return KeyboardActivity(
                monitoring_available=True,
                typing_active=typing_active,
                keypresses_last_5_seconds=last_5,
                keypresses_last_30_seconds=last_30,
                typing_rate_per_minute=float(last_60),
                current_typing_burst_seconds=burst_duration,
                seconds_since_last_keypress=seconds_since,
                current_no_typing_duration=no_typing_duration,
                last_shortcut=self._last_shortcut,
                seconds_since_last_shortcut=(
                    None if self._last_shortcut_at is None
                    else max(0.0, now - self._last_shortcut_at)
                ),
                shortcut_counts=dict(self._shortcut_counts),
            )

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


class MacKeyTap:
    """
    macOS key listener: a listen-only Quartz event tap on its own thread.

    Hands `on_key` only the physical key code and whether Cmd / Ctrl were
    held; characters are never read. Needs the Input Monitoring permission
    (System Settings > Privacy & Security > Input Monitoring) for the app
    that runs Python, usually the terminal.
    """

    def __init__(self, on_key: Callable[[int, bool, bool], None]) -> None:
        self._on_key = on_key
        self._tap = None
        self._run_loop = None

    def start(self) -> str:
        """Returns "on", "needs_permission" or "unavailable"."""
        try:
            import Quartz
        except ImportError:  # pyobjc-framework-Quartz (pywebview installs it)
            return "unavailable"

        if not Quartz.CGPreflightListenEventAccess():
            # Lists this app under Input Monitoring and asks once. macOS
            # applies the permission after the app restarts.
            Quartz.CGRequestListenEventAccess()
            return "needs_permission"

        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), name="mac-key-tap", daemon=True).start()
        ready.wait(timeout=2.0)
        return "on" if self._tap is not None else "unavailable"

    def stop(self) -> None:
        if self._run_loop is not None:
            import Quartz

            Quartz.CFRunLoopStop(self._run_loop)
            self._run_loop = None

    def _callback(self, proxy, event_type, event, refcon):
        import Quartz

        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
        elif not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
            flags = Quartz.CGEventGetFlags(event)
            try:
                self._on_key(
                    Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode),
                    bool(flags & Quartz.kCGEventFlagMaskCommand),
                    bool(flags & Quartz.kCGEventFlagMaskControl),
                )
            except Exception:
                pass  # never let a bug here stall the tap
        return event

    def _run(self, ready: threading.Event) -> None:
        import Quartz

        try:
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionListenOnly,
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
                self._callback,
                None,
            )
            if self._tap is not None:
                source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
                self._run_loop = Quartz.CFRunLoopGetCurrent()
                Quartz.CFRunLoopAddSource(self._run_loop, source, Quartz.kCFRunLoopCommonModes)
                Quartz.CGEventTapEnable(self._tap, True)
        except Exception:
            self._tap = None
        finally:
            ready.set()
        if self._tap is not None:
            Quartz.CFRunLoopRun()


class GlobalKeyboardMonitor:
    """
    System-wide key listener: a Quartz event tap on macOS (MacKeyTap),
    pynput everywhere else.

    Every keypress becomes `tracker.record_keypress()` with no key identity.
    Ctrl/Cmd + C, V, Z additionally becomes `tracker.record_shortcut()`.
    """

    def __init__(self, tracker: KeyboardActivityTracker | None = None) -> None:
        self.tracker = tracker or KeyboardActivityTracker()
        self._listener = None
        self._modifiers_held: set[str] = set()
        self._is_mac = platform.system() == "Darwin"
        # "on", "needs_permission" (macOS Input Monitoring), "unavailable",
        # or "off" before start().
        self.status = "off"

    def start(self) -> None:
        if self._is_mac:
            tap = MacKeyTap(self._on_mac_key)
            self.status = tap.start()
            if self.status == "on":
                self._listener = tap
            self.tracker.set_monitoring_available(self.status == "on")
            return

        try:
            from pynput import keyboard

            def on_press(key) -> None:
                self.tracker.record_keypress()

                modifier = modifier_name(key)
                if modifier is not None:
                    self._modifiers_held.add(modifier)
                    return

                shortcut = shortcut_for_key(
                    key,
                    self._modifiers_held,
                    self._is_mac,
                )
                if shortcut is not None:
                    self.tracker.record_shortcut(shortcut)
                # Key identity is discarded here.

            def on_release(key) -> None:
                modifier = modifier_name(key)
                if modifier is not None:
                    self._modifiers_held.discard(modifier)

            self._listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            )
            self._listener.daemon = True
            self._listener.start()
            self.tracker.set_monitoring_available(True)
            self.status = "on"
        except Exception:
            self._listener = None
            self.tracker.set_monitoring_available(False)
            self.status = "unavailable"

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            finally:
                self._listener = None

    def _on_mac_key(self, keycode: int, command: bool, control: bool) -> None:
        self.tracker.record_keypress()
        held = {name for name, down in (("cmd", command), ("ctrl", control)) if down}
        shortcut = shortcut_for_key(SimpleNamespace(vk=keycode, char=None), held, is_mac=True)
        if shortcut is not None:
            self.tracker.record_shortcut(shortcut)
        # The key code is discarded here.
