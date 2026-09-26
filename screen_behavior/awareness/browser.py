from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, Callable


@dataclass(slots=True)
class BrowserActivity:
    """
    Aggregate browser activity reported by the Buddy browser extension.

    Counts only: the extension never sends which keys were pressed, what was
    copied, or full URLs. `host` and `title` identify the current page.
    """
    available: bool = False          # a heartbeat arrived recently
    focused: bool = False            # the reporting tab is in view
    host: str = ""
    title: str = ""
    scroll_pct: int = 0
    seconds_since_update: float | None = None
    seconds_since_key: float | None = None
    clicks_last_minute: int = 0
    keys_last_minute: int = 0
    copies_last_minute: int = 0
    pastes_last_minute: int = 0
    active_seconds_on_host: float = 0.0
    active_seconds_by_host: dict[str, float] = field(default_factory=dict)
    total_copies: int = 0
    total_pastes: int = 0


def _count(payload: dict, key: str) -> int:
    try:
        return max(0, int(payload.get(key, 0)))
    except (TypeError, ValueError):
        return 0


class BrowserActivityTracker:
    """
    Receives extension heartbeats (deltas since the previous heartbeat) and
    keeps a rolling one-minute window plus per-host active time.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        stale_after_seconds: float = 20.0,
        window_seconds: float = 60.0,
        max_hosts: int = 50,
    ) -> None:
        self._clock = clock
        self._stale_after = stale_after_seconds
        self._window = window_seconds
        self._max_hosts = max_hosts

        self._events: deque[tuple[float, int, int, int, int]] = deque()
        self._host = ""
        self._title = ""
        self._scroll = 0
        self._focused = False
        self._last_update: float | None = None
        self._last_key: float | None = None
        self._by_host: dict[str, float] = {}
        self._total_copies = 0
        self._total_pastes = 0
        self._lock = Lock()

    def record(self, payload: dict[str, Any]) -> None:
        now = self._clock()
        host = str(payload.get("host", ""))[:253]
        title = str(payload.get("title", ""))[:300]
        clicks = _count(payload, "clicks")
        keys = _count(payload, "keys")
        copies = _count(payload, "copies")
        pastes = _count(payload, "pastes")
        active_seconds = _count(payload, "activeMs") / 1000

        with self._lock:
            self._host = host
            self._title = title
            self._scroll = min(100, _count(payload, "maxScrollPct"))
            self._focused = not payload.get("left", False)
            self._last_update = now
            if keys:
                self._last_key = now

            self._events.append((now, clicks, keys, copies, pastes))
            self._total_copies += copies
            self._total_pastes += pastes

            if host:
                self._by_host[host] = self._by_host.get(host, 0.0) + active_seconds
                if len(self._by_host) > self._max_hosts:
                    smallest = min(self._by_host, key=self._by_host.get)
                    del self._by_host[smallest]

            self._prune(now)

    def snapshot(self) -> BrowserActivity:
        now = self._clock()
        with self._lock:
            self._prune(now)
            if self._last_update is None:
                return BrowserActivity()

            since = max(0.0, now - self._last_update)
            sums = [sum(e[i] for e in self._events) for i in range(1, 5)]

            return BrowserActivity(
                available=since <= self._stale_after,
                focused=self._focused and since <= self._stale_after,
                host=self._host,
                title=self._title,
                scroll_pct=self._scroll,
                seconds_since_update=since,
                seconds_since_key=(
                    None if self._last_key is None
                    else max(0.0, now - self._last_key)
                ),
                clicks_last_minute=sums[0],
                keys_last_minute=sums[1],
                copies_last_minute=sums[2],
                pastes_last_minute=sums[3],
                active_seconds_on_host=self._by_host.get(self._host, 0.0),
                active_seconds_by_host=dict(self._by_host),
                total_copies=self._total_copies,
                total_pastes=self._total_pastes,
            )

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
