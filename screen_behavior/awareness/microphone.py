from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable


SILENCE_DB = -100.0


@dataclass(slots=True)
class MicrophoneActivity:
    monitoring_available: bool = False
    level_db: float = SILENCE_DB
    noise_floor_db: float = SILENCE_DB
    user_talking: bool = False
    loud_voice_detected: bool = False
    seconds_since_voice: float | None = None


def rms_db(samples: array) -> float:
    """Loudness of one block of int16 samples, in dBFS (0 = max, -100 = silent)."""
    if not samples:
        return SILENCE_DB
    mean_square = sum(s * s for s in samples) / len(samples)
    if mean_square <= 0:
        return SILENCE_DB
    return max(SILENCE_DB, 10 * math.log10(mean_square / (32768.0 ** 2)))


class VoiceLevelTracker:
    """
    Aggregate-only microphone activity.

    `record_level()` receives a single loudness number per audio block. Audio
    samples are never stored, recorded, transcribed, or sent anywhere, so the
    public model cannot contain speech content.

    "Loud" is relative to the room's background noise, so buddy wakes from
    play-dead when the user yells, not when they talk normally.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        talk_margin_db: float = 10.0,
        loud_margin_db: float = 25.0,
        loud_min_db: float = -30.0,
        loud_max_db: float = -10.0,
        loud_min_seconds: float = 0.2,
        loud_hold_seconds: float = 1.5,
        talk_hold_seconds: float = 0.6,
    ) -> None:
        self._clock = clock
        self._talk_margin = talk_margin_db
        self._loud_margin = loud_margin_db
        self._loud_min_db = loud_min_db
        # In a noisy room / hot mic, floor + margin can exceed what a mic can
        # physically record, so cap the threshold.
        self._loud_max_db = loud_max_db
        self._loud_min_seconds = loud_min_seconds
        # Hold the loud flag briefly so a short yell between two brain
        # updates is not missed.
        self._loud_hold = loud_hold_seconds
        self._talk_hold = talk_hold_seconds

        self._monitoring_available = False
        self._level_db = SILENCE_DB
        self._noise_floor_db: float | None = None
        self._last_voice: float | None = None
        self._loud_started: float | None = None
        self._last_loud: float | None = None
        self._last_level_at: float | None = None
        self._lock = Lock()

    def set_monitoring_available(self, value: bool) -> None:
        with self._lock:
            self._monitoring_available = bool(value)

    def record_level(self, level_db: float) -> None:
        now = self._clock()
        with self._lock:
            self._level_db = level_db

            if self._noise_floor_db is None:
                self._noise_floor_db = level_db

            floor = self._noise_floor_db

            if level_db >= floor + self._talk_margin:
                self._last_voice = now

            loud_threshold = max(
                self._loud_min_db,
                min(floor + self._loud_margin, self._loud_max_db),
            )
            loud = level_db >= loud_threshold
            if loud:
                if self._loud_started is None:
                    self._loud_started = now
                if now - self._loud_started >= self._loud_min_seconds:
                    self._last_loud = now
            else:
                self._loud_started = None

            # Track background noise: drop quickly when the room gets
            # quieter, rise slowly (~10s) so a sustained fan/music raises
            # the bar but a sentence or a yell doesn't.
            if level_db < floor:
                self._noise_floor_db = floor + 0.2 * (level_db - floor)
            elif not loud:
                self._noise_floor_db = floor + 0.005 * (level_db - floor)

            self._last_level_at = now

    def snapshot(self) -> MicrophoneActivity:
        now = self._clock()

        with self._lock:
            if not self._monitoring_available:
                return MicrophoneActivity(monitoring_available=False)

            seconds_since_voice = (
                None if self._last_voice is None
                else max(0.0, now - self._last_voice)
            )

            return MicrophoneActivity(
                monitoring_available=True,
                level_db=self._level_db,
                noise_floor_db=(
                    SILENCE_DB if self._noise_floor_db is None
                    else self._noise_floor_db
                ),
                user_talking=(
                    seconds_since_voice is not None
                    and seconds_since_voice <= self._talk_hold
                ),
                loud_voice_detected=(
                    self._last_loud is not None
                    and now - self._last_loud <= self._loud_hold
                ),
                seconds_since_voice=seconds_since_voice,
            )


class MicrophoneMonitor:
    """
    Opt-in microphone listener using sounddevice.

    The audio callback converts each block to one loudness number and
    discards the samples immediately.
    """

    def __init__(
        self,
        tracker: VoiceLevelTracker | None = None,
        sample_rate: int = 16000,
        block_seconds: float = 0.05,
    ) -> None:
        self.tracker = tracker or VoiceLevelTracker()
        self._sample_rate = sample_rate
        self._block_size = int(sample_rate * block_seconds)
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice

            def on_audio(data, _frames, _time, _status) -> None:
                samples = array("h")
                samples.frombytes(bytes(data))
                # Only the loudness number leaves this callback.
                self.tracker.record_level(rms_db(samples))

            self._stream = sounddevice.RawInputStream(
                samplerate=self._sample_rate,
                blocksize=self._block_size,
                channels=1,
                dtype="int16",
                callback=on_audio,
            )
            self._stream.start()
            self.tracker.set_monitoring_available(True)
        except Exception:
            self._stream = None
            self.tracker.set_monitoring_available(False)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        self.tracker.set_monitoring_available(False)

    def snapshot(self) -> MicrophoneActivity:
        return self.tracker.snapshot()
