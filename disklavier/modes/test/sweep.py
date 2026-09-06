"""
Test mode: play every note on the piano, in time with the tempo dial.

Entering the mode arms it; nothing sounds until the panel's play button is
pressed.  It then loops the chromatic scale indefinitely as sixteenth notes,
locked to the tempo the instrument reports over MIDI clock, until stop is
pressed.  Turning the tempo dial mid-sweep speeds it up or slows it down
immediately, which makes it a handy way to hear the action at different rates.

Both controls come from the metronome: in disk mode, or with the metronome off,
the instrument sends neither clock nor transport.  Play will not start the sweep
at all, and there is no tempo to follow -- see ``disklavier.tempo``.
"""

import threading
import time
from typing import List, Optional

from ..base import Mode
from ...notes import HIGHEST_NOTE, LOWEST_NOTE, get_note_name

# A sixteenth note is a quarter of a beat
STEPS_PER_BEAT = 4


class TestMode(Mode):
    """
    Play the chromatic scale on a loop, one note per sixteenth.

    The sweep runs on its own thread so the controller stays responsive to the
    mode-switch gesture while the piano is playing, and re-reads the tempo every
    note so dial changes take effect within a sixteenth.
    """

    name = "test"
    description = "Play every note on the piano, looping in time with the tempo dial"

    def __init__(
        self,
        disklavier,
        velocity: int = 60,
        low_note: int = LOWEST_NOTE,
        high_note: int = HIGHEST_NOTE,
        default_bpm: float = 120.0,
        gate: float = 0.9,
        min_bpm: float = 20.0,
        max_bpm: float = 400.0,
        clock_warning_delay: float = 1.5,
    ):
        """
        Args:
            disklavier: Live Disklavier interface
            velocity: Note-on velocity for every note
            low_note: Lowest MIDI note to play (default A0)
            high_note: Highest MIDI note to play (default C8)
            default_bpm: Tempo used when the instrument sends no clock
            gate: Fraction of each sixteenth the note is held down, so
                consecutive notes are articulated rather than run together
            min_bpm: Floor applied to the reported tempo, so a garbled reading
                cannot stall the sweep
            max_bpm: Ceiling applied to the reported tempo, so it cannot flood
                the instrument faster than the action can respond
            clock_warning_delay: Seconds to wait before warning that no clock is
                arriving, long enough for the tempo tracker to lock on
        """
        super().__init__(disklavier)
        self.velocity = velocity
        self.low_note = low_note
        self.high_note = high_note
        self.default_bpm = default_bpm
        self.gate = gate
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm

        self.clock_warning_delay = clock_warning_delay

        self._stop_event = threading.Event()
        self._thread = None
        self._clock_warning = None

    def current_bpm(self) -> float:
        """
        Tempo to play at right now, clamped to something the piano can follow.

        Falls back to ``default_bpm`` when the instrument reports no clock.
        """
        bpm = self.disklavier.tempo
        if bpm is None:
            bpm = self.default_bpm
        return max(self.min_bpm, min(self.max_bpm, bpm))

    def step_seconds(self, bpm: float) -> float:
        """Duration of one sixteenth note at the given tempo."""
        return 60.0 / (bpm * STEPS_PER_BEAT)

    def start(self) -> None:
        """Arm the mode. Nothing sounds until the panel's play button."""
        if self.disklavier.midi_out is None:
            print("❌ Test mode needs a MIDI output device, but none is configured")
            return

        print(
            f"⏸️  Armed: {get_note_name(self.low_note)} to "
            f"{get_note_name(self.high_note)} as sixteenths, velocity {self.velocity}"
        )
        print("   Press play on the control panel to start, stop to halt")

        # Transport and clock come from the same place, so no clock is a strong
        # hint that play will not be transmitted either. Check on a delay: the
        # tracker needs a few ticks to lock, so an immediate read says None even
        # when the metronome is running perfectly well.
        self._clock_warning = threading.Timer(
            self.clock_warning_delay, self._warn_if_no_clock
        )
        self._clock_warning.daemon = True
        self._clock_warning.start()

    def _warn_if_no_clock(self) -> None:
        """Warn only if the clock is still absent once the tracker has settled."""
        if self.disklavier.tempo is None:
            print(
                "⚠️  No MIDI clock -- the metronome looks off, or the instrument "
                "is in disk mode. Play will not reach us until that changes."
            )

    def on_transport_start(self) -> None:
        """Panel play pressed: begin sweeping."""
        if self.disklavier.midi_out is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return  # already running; play again is a no-op

        bpm = self.disklavier.tempo
        source = (
            f"{bpm:.1f} BPM from the tempo dial"
            if bpm is not None
            else f"{self.default_bpm:.1f} BPM (no MIDI clock -- metronome off?)"
        )
        print(f"🔊 Sweeping at {source}")
        print("   Turn the tempo dial to change speed while it plays")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sweep, daemon=True)
        self._thread.start()

    def on_transport_stop(self) -> None:
        """Panel stop pressed: halt and leave the piano quiet."""
        if self._thread is None or not self._thread.is_alive():
            return

        print("⏹️  Sweep halted")
        self._halt()

        # The sweep releases the note it was holding, but a stop press should
        # leave nothing sounding whatever state it was interrupted in
        if self.disklavier.midi_out is not None:
            self.disklavier.all_notes_off()

    def _sweep(self) -> None:
        """Walk the keyboard on a loop until stopped, one note per sixteenth."""
        note = self.low_note
        reported = None
        # Absolute schedule, so a slow send does not accumulate into drift
        next_note_at = time.monotonic()

        try:
            while not self._stop_event.is_set():
                bpm = self.current_bpm()
                step = self.step_seconds(bpm)

                # Only mention the tempo when it has actually moved
                if reported is None or abs(bpm - reported) >= 1.0:
                    print(f"🎼 {bpm:.1f} BPM  ({step * 1000:.0f} ms per sixteenth)")
                    reported = bpm

                self.disklavier.send_note_on(note, self.velocity)

                if self._wait_until(next_note_at + step * self.gate):
                    self.disklavier.send_note_off(note)
                    return
                self.disklavier.send_note_off(note)

                next_note_at += step
                if self._wait_until(next_note_at):
                    return

                note += 1
                if note > self.high_note:
                    note = self.low_note

                # A big tempo increase can leave the schedule in the past;
                # resync rather than sprinting to catch up
                now = time.monotonic()
                if next_note_at < now:
                    next_note_at = now
        except Exception as e:
            print(f"❌ Test mode sweep failed: {e}")

    def _wait_until(self, deadline: float) -> bool:
        """
        Sleep until ``deadline``, interruptibly.

        Returns True if the mode was stopped while waiting.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return self._stop_event.is_set()
        return self._stop_event.wait(remaining)

    def handle_midi(self, midi_bytes: List[int], delta_time: float) -> None:
        """Test mode ignores input; it only drives the piano."""

    def _halt(self) -> None:
        """Stop the sweep thread and wait for it to unwind."""
        self._stop_event.set()

        if self._thread is not None:
            # One sixteenth at the slowest tempo, plus slack for the send
            self._thread.join(timeout=self.step_seconds(self.min_bpm) + 1.0)
            self._thread = None

    def stop(self) -> None:
        if self._clock_warning is not None:
            self._clock_warning.cancel()
            self._clock_warning = None

        self._halt()

        # The controller releases every key after this returns, so a note the
        # sweep was holding when it was interrupted does not need chasing here
