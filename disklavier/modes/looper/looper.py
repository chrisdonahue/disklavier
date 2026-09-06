"""
Looper mode: play a phrase twice and it loops.

Unlike delay mode there is no fixed timer.  Every note-on is remembered, and
whenever the most recent notes turn out to be the same run of pitches played
twice in a row, that phrase starts looping.  Timing and velocity are averaged
across the two passes, so the loop sits between the two takes rather than
inheriting the quirks of either.

Only pitches decide whether two passes match; timing does not have to line up,
which is what lets a loosely played repeat still be recognised.

Several phrases can loop at once.  When more arrive than ``max_patterns``
allows, the phrase that has been looping longest is evicted -- stopped and
released -- to make room.
"""

import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..base import Mode
from ...notes import get_note_name, is_note_on, note_number
from ...scheduler import MessageScheduler


class NoteRecord:
    """One note-on heard from the player, with its duration once released."""

    __slots__ = ("pitch", "velocity", "onset", "duration")

    def __init__(self, pitch: int, velocity: int, onset: float):
        self.pitch = pitch
        self.velocity = velocity
        self.onset = onset
        self.duration: Optional[float] = None


class LoopPattern:
    """
    A phrase to repeat, averaged across the two passes that defined it.

    ``intervals[i]`` is the wait between starting note i and note i+1, and the
    final entry wraps from the last note back to the first of the next cycle.
    """

    def __init__(
        self,
        pitches: Sequence[int],
        velocities: Sequence[int],
        intervals: Sequence[float],
        durations: Sequence[float],
    ):
        self.pitches = tuple(pitches)
        self.velocities = list(velocities)
        self.intervals = list(intervals)
        self.durations = list(durations)

    def __len__(self) -> int:
        return len(self.pitches)

    @property
    def cycle_seconds(self) -> float:
        """How long one time around the loop takes."""
        return sum(self.intervals)

    def describe(self) -> str:
        names = " ".join(get_note_name(p) for p in self.pitches)
        return f"{len(self)} notes [{names}] cycle {self.cycle_seconds:.2f}s"


class PatternDetector:
    """
    Watches the note-on stream for a run of pitches played twice in a row.

    Prefers the longest match.  Over-matching is harmless -- picking C D C D
    over C D loops the identical music, just on a longer cycle -- whereas
    under-matching would loop a fragment the player never intended.
    """

    def __init__(self, min_length: int = 2, max_length: int = 64, gate: float = 0.9):
        """
        Args:
            min_length: Shortest phrase that may loop, in notes
            max_length: Longest phrase that may loop, in notes
            gate: Fraction of a note's interval to hold it for when its real
                duration is unknown, which happens for a note still held down
                at the moment the phrase is recognised
        """
        self.min_length = max(2, min_length)
        self.max_length = max_length
        self.gate = gate

        self._history: List[NoteRecord] = []
        self._open: Dict[int, NoteRecord] = {}

    def note_on(self, pitch: int, velocity: int, when: float) -> None:
        record = NoteRecord(pitch, velocity, when)
        self._history.append(record)
        self._open[pitch] = record

        # Only ever need two passes of the longest allowed phrase
        limit = 2 * self.max_length
        if len(self._history) > limit:
            del self._history[:-limit]

    def note_off(self, pitch: int, when: float) -> None:
        record = self._open.pop(pitch, None)
        if record is not None:
            record.duration = when - record.onset

    def reset(self) -> None:
        self._history.clear()
        self._open.clear()

    def detect(self) -> Optional[LoopPattern]:
        """Return the phrase that was just played twice, if there is one."""
        history = self._history
        longest = min(self.max_length, len(history) // 2)

        for length in range(longest, self.min_length - 1, -1):
            first = history[-2 * length : -length]
            second = history[-length:]
            if [r.pitch for r in first] == [r.pitch for r in second]:
                return self._build(first, second)
        return None

    def _build(
        self, first: List[NoteRecord], second: List[NoteRecord]
    ) -> LoopPattern:
        """Average the two passes into one pattern."""
        length = len(first)
        pitches = [r.pitch for r in first]
        velocities = [
            int(round((a.velocity + b.velocity) / 2)) for a, b in zip(first, second)
        ]

        intervals: List[float] = []
        for i in range(length - 1):
            intervals.append(
                (
                    (first[i + 1].onset - first[i].onset)
                    + (second[i + 1].onset - second[i].onset)
                )
                / 2
            )
        # Wrap: end of the first pass to the start of the second. Only one
        # sample of it exists, so it is used as measured rather than averaged.
        intervals.append(second[0].onset - first[length - 1].onset)

        durations = []
        for i in range(length):
            measured = [r.duration for r in (first[i], second[i]) if r.duration]
            if measured:
                durations.append(sum(measured) / len(measured))
            else:
                durations.append(max(0.05, intervals[i] * self.gate))

        return LoopPattern(pitches, velocities, intervals, durations)


class LoopPlayer:
    """
    Plays one pattern round and round on its own thread until stopped.

    Note-offs go to a shared scheduler rather than being slept through, so that
    a chord -- whose notes are separated by almost no interval -- still sustains
    properly instead of being cut to nothing.
    """

    def __init__(
        self,
        pattern: LoopPattern,
        send,
        scheduler: MessageScheduler,
        velocity_factor: float = 1.25,
        min_velocity: int = 1,
        channel: int = 0,
    ):
        self.pattern = pattern
        self.velocity_factor = velocity_factor
        self.min_velocity = min_velocity
        self.channel = channel

        self._send = send
        self._scheduler = scheduler
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.started_at = time.monotonic()

    def velocity_for(self, index: int) -> int:
        raw = self.pattern.velocities[index] * self.velocity_factor
        return max(self.min_velocity, min(127, int(round(raw))))

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        pattern = self.pattern
        # Absolute schedule so a slow send does not accumulate into drift
        next_at = time.monotonic()

        try:
            while not self._stop_event.is_set():
                for index in range(len(pattern)):
                    if self._stop_event.is_set():
                        return

                    pitch = pattern.pitches[index]
                    self._send([0x90 | self.channel, pitch, self.velocity_for(index)])
                    self._scheduler.schedule(
                        next_at + pattern.durations[index],
                        [0x80 | self.channel, pitch, 0],
                    )

                    next_at += pattern.intervals[index]
                    now = time.monotonic()
                    if next_at < now:
                        next_at = now  # fell behind; resync rather than sprint
                    if self._stop_event.wait(next_at - now):
                        return
        except Exception as e:
            print(f"❌ Loop failed: {e}")

    def stop(self) -> None:
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        # Release only this loop's keys: other loops may still be playing
        for pitch in set(self.pattern.pitches):
            self._send([0x80 | self.channel, pitch, 0])


class LooperMode(Mode):
    """Loop any phrase the player repeats, averaging the two passes."""

    name = "looper"
    description = "Play a phrase twice and it loops, averaged across both passes"

    def __init__(
        self,
        disklavier,
        max_patterns: int = 1,
        velocity_factor: float = 1.25,
        min_length: int = 2,
        max_length: int = 64,
        gate: float = 0.9,
        min_velocity: int = 1,
        channel: int = 0,
        suppress_feedback: bool = True,
        feedback_window: float = 0.2,
        verbose: bool = True,
    ):
        """
        Args:
            disklavier: Live Disklavier interface
            max_patterns: How many phrases may loop at once. When a new one
                arrives with this many already going, the longest-running is
                evicted.
            velocity_factor: Multiplier on the averaged velocity. Above 1.0 by
                default because the solenoids strike more softly than fingers
                at the same velocity.
            min_length: Shortest phrase that may loop, in notes
            max_length: Longest phrase that may loop, in notes
            gate: Fraction of its interval a note is held for when its real
                duration is unknown
            min_velocity: Velocity floor, so a quiet note still sounds
            channel: MIDI channel to play loops on
            suppress_feedback: Ignore an incoming note that matches one this
                mode just played, in case the instrument reports its own
                solenoids back on MIDI in. Without it a loop would feed its own
                notes into the detector and match against itself.
            feedback_window: Seconds a played note stays eligible for that match
            verbose: Announce each phrase as it starts looping
        """
        super().__init__(disklavier)
        self.max_patterns = max(1, max_patterns)
        self.velocity_factor = velocity_factor
        self.min_velocity = min_velocity
        self.channel = channel
        self.suppress_feedback = suppress_feedback
        self.feedback_window = feedback_window
        self.verbose = verbose

        self.detector = PatternDetector(min_length, max_length, gate)
        self.scheduler = MessageScheduler(self._send)

        self._loops: List[LoopPlayer] = []
        self._recent_played: List[Tuple[float, int, int]] = []
        self._lock = threading.Lock()

    @property
    def active_loops(self) -> int:
        with self._lock:
            return len(self._loops)

    def start(self) -> None:
        if self.disklavier.midi_out is None:
            print("❌ Looper mode needs a MIDI output device, but none is configured")
            return

        print(
            f"🔂 Play any phrase twice and it loops "
            f"({self.detector.min_length}-{self.detector.max_length} notes)"
        )
        print(
            f"   Up to {self.max_patterns} at once, at "
            f"{self.velocity_factor * 100:.0f}% of the velocity you played"
        )
        self.scheduler.start()

    def handle_midi(self, midi_bytes: List[int], delta_time: float) -> None:
        if self.disklavier.midi_out is None:
            return

        pitch = note_number(midi_bytes)
        if pitch is None:
            return  # pedals and the rest are not part of a phrase

        now = time.monotonic()

        if is_note_on(midi_bytes):
            if self.suppress_feedback and self._claim_own_note(pitch, midi_bytes[2]):
                return
            self.detector.note_on(pitch, midi_bytes[2], now)
            pattern = self.detector.detect()
            if pattern is not None:
                self._begin_loop(pattern)
        else:
            self.detector.note_off(pitch, now)

    def _begin_loop(self, pattern: LoopPattern) -> None:
        """Start looping a freshly recognised phrase, evicting if needed."""
        evicted: List[LoopPlayer] = []

        with self._lock:
            # Replaying a phrase that is already looping refreshes it rather
            # than stacking a second copy on top of itself
            for loop in list(self._loops):
                if loop.pattern.pitches == pattern.pitches:
                    self._loops.remove(loop)
                    evicted.append(loop)

            while len(self._loops) >= self.max_patterns:
                evicted.append(self._loops.pop(0))

        for loop in evicted:
            loop.stop()

        player = LoopPlayer(
            pattern,
            self._send,
            self.scheduler,
            velocity_factor=self.velocity_factor,
            min_velocity=self.min_velocity,
            channel=self.channel,
        )

        with self._lock:
            self._loops.append(player)

        player.start()

        # Start the next phrase from a clean slate, so the notes that triggered
        # this loop cannot immediately trigger it again
        self.detector.reset()

        if self.verbose:
            note = " (evicted oldest)" if evicted else ""
            print(f"🔂 Looping {pattern.describe()}{note}")

    def _send(self, message: List[int]) -> None:
        try:
            self.disklavier.send_message(message)
        except Exception as e:
            print(f"❌ Could not play loop note {message}: {e}")
            return

        if self.suppress_feedback and is_note_on(message):
            with self._lock:
                self._recent_played.append(
                    (time.monotonic() + self.feedback_window, message[1], message[2])
                )

    def _claim_own_note(self, pitch: int, velocity: int) -> bool:
        """True if this note-on looks like one of our own, coming back."""
        now = time.monotonic()
        with self._lock:
            self._recent_played = [e for e in self._recent_played if e[0] > now]
            for entry in self._recent_played:
                if entry[1] == pitch and entry[2] == velocity:
                    self._recent_played.remove(entry)
                    return True
        return False

    def stop(self) -> None:
        with self._lock:
            loops = list(self._loops)
            self._loops.clear()

        for loop in loops:
            loop.stop()

        self.scheduler.stop()
        self.detector.reset()
        with self._lock:
            self._recent_played.clear()
        # The controller releases every key after this returns
