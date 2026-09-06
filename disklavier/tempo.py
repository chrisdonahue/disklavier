"""
Tempo tracking from the MIDI clock stream.

The Disklavier transmits MIDI clock (0xF8) at 24 pulses per quarter note while
its metronome is enabled, which makes the panel's tempo dial usable as a
continuous control knob: turn it and the derived BPM follows in real time.

The clock is only present in metronome mode.  In disk mode, or with the
metronome switched off, nothing is transmitted and the tempo reads as None.

Transport messages
------------------
The panel's play and stop buttons arrive as single-byte transport messages:

    0xFA  Start  -- play pressed
    0xFC  Stop   -- stop pressed

``Disklavier._is_musical_message`` lets these two through the system-message
filter, and ``Controller.midi_callback`` consumes them the way it consumes the
reserved notes: a mode receives them as ``on_transport_start()`` and
``on_transport_stop()``, never as raw bytes.

Two things to know when building on them:

* They come from the metronome, same as the clock.  With the metronome off, or
  in disk mode, pressing play emits nothing at all -- so a mode gated on
  transport will simply never start, and should say so rather than look hung.
* They report state transitions, not presses.  Pressing stop when already
  stopped sends nothing, so presses cannot be counted.

"""

import statistics
import time
from collections import deque
from typing import Deque, Optional

# MIDI clock resolution: pulses per quarter note, fixed by the MIDI spec
PPQN = 24

CLOCK = 0xF8
START = 0xFA  # panel play button; see "Transport messages" above
STOP = 0xFC  # panel stop button; see "Transport messages" above


class TempoTracker:
    """
    Derives BPM from the spacing of MIDI clock ticks.

    ``tick()`` is called on the MIDI callback thread while ``bpm`` is read from
    whatever thread a mode runs on.  Both are safe: a deque's append and its
    snapshot are atomic under the GIL.
    """

    def __init__(
        self,
        window: int = 24,
        timeout: float = 1.0,
        min_intervals: int = 4,
    ):
        """
        Args:
            window: Clock intervals to average over -- one quarter note at the
                default of 24, so the reading follows the dial closely.
            timeout: Seconds without a tick after which the tempo reads as None.
                Generous: even 20 BPM still ticks every 125 ms.
            min_intervals: Intervals required before reporting anything, so a
                couple of stray ticks cannot produce a wild reading.
        """
        self.window = window
        self.timeout = timeout
        self.min_intervals = min_intervals
        self._ticks: Deque[float] = deque(maxlen=window + 1)

    def tick(self, now: Optional[float] = None) -> None:
        """Record one clock pulse. Call for every 0xF8 received."""
        now = time.monotonic() if now is None else now

        # A gap this large means the clock stopped and has since resumed; the
        # old timestamps describe a different run and would skew the median
        if self._ticks and (now - self._ticks[-1]) > self.timeout:
            self._ticks.clear()

        self._ticks.append(now)

    @property
    def bpm(self) -> Optional[float]:
        """
        Current tempo in BPM, or None when the instrument is not sending clock.

        None means one of: the metronome is off, the instrument is in disk mode,
        it is disconnected, or too few ticks have arrived to measure yet.
        """
        ticks = list(self._ticks)
        if len(ticks) < self.min_intervals + 1:
            return None

        if (time.monotonic() - ticks[-1]) > self.timeout:
            return None

        intervals = [b - a for a, b in zip(ticks, ticks[1:])]
        # Median, not mean: it shrugs off the odd late tick from USB jitter
        median = statistics.median(intervals)
        if median <= 0:
            return None

        return 60.0 / (median * PPQN)

    def reset(self) -> None:
        """Forget all timing history."""
        self._ticks.clear()

    def __repr__(self) -> str:
        bpm = self.bpm
        shown = "None" if bpm is None else f"{bpm:.1f}"
        return f"<TempoTracker bpm={shown} ticks={len(self._ticks)}>"
