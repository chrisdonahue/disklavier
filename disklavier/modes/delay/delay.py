"""
Delay mode: echo every note played, in time with the tempo dial.

Each note struck on the piano is repeated by the solenoids a fixed number of
times, spaced by a musical interval derived from the instrument's MIDI clock,
with the velocity fading on each repeat.  The default is three echoes at 125%,
100% and 75% of the velocity you played, one beat apart.  The boost is
deliberate: the solenoids strike more softly than fingers do, so an echo sent at
the velocity you played reads as noticeably quieter than the note you struck.

After the last echo, each key gets a phantom release -- a bare note-off sent one
delay interval later.  Nothing depends on the player having lifted the key, so a
note held down while its echoes fire still ends up released rather than stuck.

The delay interval is read from the tempo at the moment the note is struck, so
a note's echoes stay evenly spaced even if the dial is turned while they are
still sounding.  Turning the dial changes the spacing of notes played after it.
With no MIDI clock (metronome off, or disk mode) the tempo reads None and
``default_bpm`` is used instead -- see ``disklavier.tempo``.
"""

import threading
import time
from typing import List, Optional, Sequence, Tuple

from ..base import Mode
from ...notes import get_note_name, is_note_on, note_number
from ...scheduler import MessageScheduler


class DelayMode(Mode):
    """
    Repeat each played note, fading out, spaced by the tempo.

    Echo note-ons are scheduled when the key is struck.  Their note-offs are
    scheduled when the key is released, each holding for as long as the original
    was held, so the echoes phrase the way the playing did.
    """

    name = "delay"
    description = "Echo every note in time with the tempo dial, fading out"

    def __init__(
        self,
        disklavier,
        repeats: int = 3,
        decay_factors: Optional[Sequence[float]] = None,
        first_factor: float = 1.25,
        last_factor: float = 0.75,
        delay_beats: float = 1.0,
        default_bpm: float = 120.0,
        min_bpm: float = 20.0,
        max_bpm: float = 400.0,
        min_velocity: int = 1,
        channel: int = 0,
        phantom_release: bool = True,
        phantom_offset: float = 1.0,
        suppress_feedback: bool = True,
        feedback_window: float = 0.2,
        tempo_report_delay: float = 1.5,
        verbose: bool = True,
    ):
        """
        Args:
            disklavier: Live Disklavier interface
            repeats: How many echoes each note gets. Ignored if
                ``decay_factors`` is given, which then sets the count.
            decay_factors: Explicit velocity multiplier per echo, e.g.
                ``[1.0, 0.75, 0.5]``. When None they are spaced evenly from
                ``first_factor`` to ``last_factor`` across ``repeats``.
            first_factor: Velocity multiplier for the first echo. Above 1.0
                by default to offset the solenoids striking more softly than
                fingers at the same velocity.
            last_factor: Velocity multiplier for the final echo
            delay_beats: Spacing between echoes in quarter notes -- 1.0 is one
                beat, 0.5 an eighth, 2.0 a half note
            default_bpm: Tempo used when the instrument sends no clock
            min_bpm: Floor on the tempo, capping how long a delay can get
            max_bpm: Ceiling on the tempo, capping how fast echoes can stack
            min_velocity: Velocity floor, so a faded echo still sounds rather
                than becoming a silent note-on
            channel: MIDI channel to send echoes on
            phantom_release: After the last echo, send a bare note-off to each
                echoed key. This is scheduled when the key is struck, so it
                fires whether or not the player ever lifted the key -- which is
                what stops a held note's echoes from sticking down.
            phantom_offset: How many delay intervals after the final echo the
                phantom release lands
            suppress_feedback: Ignore an incoming note that exactly matches an
                echo just sent, in case the instrument reports its own solenoids
                back on MIDI in. Without this, echoes would echo themselves and
                grow exponentially.
            feedback_window: Seconds an echo stays eligible for that match.
                Wide enough to cover solenoid actuation and the sensor
                reporting back, which is mechanical and not instant; too narrow
                and a real echo arrives after the entry has expired.
            tempo_report_delay: Seconds to wait before reporting the echo
                spacing at startup, long enough for the tempo tracker to lock
            verbose: Print one line per struck note showing its echo plan
        """
        super().__init__(disklavier)

        self.decay_factors = (
            [float(f) for f in decay_factors]
            if decay_factors is not None
            else self.linear_factors(repeats, first_factor, last_factor)
        )
        self.repeats = len(self.decay_factors)

        self.delay_beats = delay_beats
        self.default_bpm = default_bpm
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.min_velocity = min_velocity
        self.channel = channel
        self.phantom_release = phantom_release
        self.phantom_offset = phantom_offset
        self.suppress_feedback = suppress_feedback
        self.feedback_window = feedback_window
        self.tempo_report_delay = tempo_report_delay
        self.verbose = verbose

        self.scheduler = MessageScheduler(self._send)

        # note -> (time struck, delay in seconds captured at that moment)
        self._struck = {}
        self._recent_echoes: List[Tuple[float, int, int]] = []
        self._tempo_report: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    @staticmethod
    def linear_factors(repeats: int, first: float, last: float) -> List[float]:
        """
        Velocity multipliers spaced evenly from ``first`` down to ``last``.

        Three repeats from 1.25 to 0.75 gives the default [1.25, 1.0, 0.75].
        """
        if repeats <= 0:
            return []
        if repeats == 1:
            return [first]
        step = (last - first) / (repeats - 1)
        return [first + step * i for i in range(repeats)]

    def current_delay(self) -> float:
        """Seconds between echoes right now, from the tempo dial."""
        bpm = self.disklavier.tempo
        if bpm is None:
            bpm = self.default_bpm
        bpm = max(self.min_bpm, min(self.max_bpm, bpm))
        return (60.0 / bpm) * self.delay_beats

    def echo_velocity(self, velocity: int, factor: float) -> int:
        """Velocity for one echo, clamped to a value the piano will sound."""
        return max(self.min_velocity, min(127, int(round(velocity * factor))))

    def start(self) -> None:
        if self.disklavier.midi_out is None:
            print("❌ Delay mode needs a MIDI output device, but none is configured")
            return

        percentages = ", ".join(f"{f * 100:.0f}%" for f in self.decay_factors)
        print(f"🔁 Echoing each note {self.repeats}x at {percentages} of its velocity")
        if self.phantom_release:
            print(
                f"   Phantom release {self.phantom_offset:g} interval after the "
                f"last echo, so nothing sticks"
            )
        print("   Turn the tempo dial to change the delay")

        self.scheduler.start()

        # Report the actual interval on a delay: the tempo tracker needs a few
        # clock ticks to lock, so reading it now says None even when the
        # metronome is running, and would print the wrong delay
        self._tempo_report = threading.Timer(
            self.tempo_report_delay, self._report_delay
        )
        self._tempo_report.daemon = True
        self._tempo_report.start()

    def _report_delay(self) -> None:
        """Print the echo spacing once the tempo reading has settled."""
        bpm = self.disklavier.tempo
        source = (
            f"{bpm:.1f} BPM from the tempo dial"
            if bpm is not None
            else f"{self.default_bpm:.1f} BPM (no MIDI clock -- metronome off?)"
        )
        print(
            f"   {self.delay_beats:g} beat apart = "
            f"{self.current_delay():.3f}s at {source}"
        )

    def handle_midi(self, midi_bytes: List[int], delta_time: float) -> None:
        if self.repeats == 0 or self.disklavier.midi_out is None:
            return

        note = note_number(midi_bytes)
        if note is None:
            return  # not a note message; pedals and the rest pass by untouched

        if is_note_on(midi_bytes):
            self._note_struck(note, midi_bytes[2])
        else:
            self._note_released(note)

    def _note_struck(self, note: int, velocity: int) -> None:
        """Schedule this note's echoes."""
        if self.suppress_feedback and self._claim_own_echo(note, velocity):
            return

        now = time.monotonic()
        delay = self.current_delay()

        with self._lock:
            self._struck[note] = (now, delay)

        velocities = []
        for index, factor in enumerate(self.decay_factors, start=1):
            echo_velocity = self.echo_velocity(velocity, factor)
            velocities.append(echo_velocity)
            self.scheduler.schedule(
                now + index * delay,
                [0x90 | self.channel, note, echo_velocity],
            )

        # Scheduled here, not on release, so it still fires for a key that is
        # never lifted -- the case that leaves echoes stuck down
        if self.phantom_release:
            self.scheduler.schedule(
                now + (self.repeats + self.phantom_offset) * delay,
                [0x80 | self.channel, note, 0],
            )

        if self.verbose:
            plan = ", ".join(str(v) for v in velocities)
            print(
                f"🔁 {get_note_name(note)} vel={velocity} -> "
                f"{plan} every {delay:.3f}s"
            )

    def _note_released(self, note: int) -> None:
        """
        Schedule the echoes' note-offs, each held as long as the original was.

        Every one of these lands in the future: echo k turns off at
        struck + k*delay + duration, which is at least ``duration`` past now.
        """
        with self._lock:
            struck = self._struck.pop(note, None)

        if struck is None:
            return  # released a note we never saw struck, e.g. held across a switch

        struck_at, delay = struck
        duration = time.monotonic() - struck_at

        for index in range(1, self.repeats + 1):
            self.scheduler.schedule(
                struck_at + index * delay + duration,
                [0x80 | self.channel, note, 0],
            )

    def _send(self, message: List[int]) -> None:
        """Send one echo, remembering it so it cannot echo itself."""
        try:
            self.disklavier.send_message(message)
        except Exception as e:
            print(f"❌ Could not send echo {message}: {e}")
            return

        if self.suppress_feedback and is_note_on(message):
            with self._lock:
                self._recent_echoes.append(
                    (time.monotonic() + self.feedback_window, message[1], message[2])
                )

    def _claim_own_echo(self, note: int, velocity: int) -> bool:
        """
        True if this note-on looks like an echo we just sent, coming back.

        Matching on note, exact velocity and a tight time window: a player is
        very unlikely to reproduce an echo's exact velocity at its exact moment.
        """
        now = time.monotonic()
        with self._lock:
            self._recent_echoes = [e for e in self._recent_echoes if e[0] > now]
            for entry in self._recent_echoes:
                if entry[1] == note and entry[2] == velocity:
                    self._recent_echoes.remove(entry)
                    return True
        return False

    def stop(self) -> None:
        if self._tempo_report is not None:
            self._tempo_report.cancel()
            self._tempo_report = None

        self.scheduler.stop()
        with self._lock:
            self._struck.clear()
            self._recent_echoes.clear()
        # The controller releases every key after this returns, so echoes that
        # were still sounding do not need chasing here
