"""
Master controller: owns the hardware, switches between modes.

The controller is the only thing that talks to the Disklavier directly.  It
watches for the mode-switch gesture on the top two keys, keeps those keys away
from whatever mode is running, and drops back to the default mode after a long
enough silence.
"""

import queue
import signal
from functools import partial
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .modes import Mode, get_mode_class
from .notes import get_note_name, is_note_off, is_note_on, note_number
from .tempo import START, STOP

# Sentinel pushed onto the switch queue to unblock run() on shutdown.
_SHUTDOWN = object()


class ModeSwitchDetector:
    """
    Recognizes the mode-switch gesture played on the top two keys.

    The gesture is the select note (top C, 108), then the mode number spelled
    out as that many presses of the count note (top B, 107), then the select
    note again.  The switch fires on the release of that final select note:

        108, 108           -> mode 0
        108, 107, 108      -> mode 1
        108, 107, 107, 108 -> mode 2

    Every message on the two gesture keys is consumed regardless of state, so a
    mode never sees them.  A press of any other key abandons a gesture in
    progress, as does letting the gesture go stale for ``gesture_timeout``.
    """

    def __init__(
        self,
        select_note: int = 108,
        count_note: int = 107,
        gesture_timeout: float = 5.0,
    ):
        """
        Args:
            select_note: Note that opens and closes the gesture (top C)
            count_note: Note repeated to count out the mode number (top B)
            gesture_timeout: Seconds of inactivity that abandon a partial gesture
        """
        self.select_note = select_note
        self.count_note = count_note
        self.gesture_timeout = gesture_timeout

        self._sequence: List[int] = []
        self._armed = False
        self._last_event = 0.0

    @property
    def gesture_notes(self) -> Tuple[int, int]:
        """The two notes reserved for the controller."""
        return (self.select_note, self.count_note)

    def observe(
        self, midi_bytes: List[int], now: Optional[float] = None
    ) -> Tuple[bool, Optional[int]]:
        """
        Feed one MIDI message to the detector.

        Returns:
            (consumed, selected_mode) where ``consumed`` is True if the message
            must not be passed on to the active mode, and ``selected_mode`` is
            the mode number if this message completed a gesture, else None.
        """
        now = time.time() if now is None else now

        note = note_number(midi_bytes)
        if note is None:
            # Not a note message (pedals, etc.) - leave the gesture alone
            return False, None

        if note not in (self.select_note, self.count_note):
            # Playing anything else means this was music, not a gesture
            if is_note_on(midi_bytes):
                self._reset()
            return False, None

        selected = None
        if is_note_on(midi_bytes):
            self._on_note_on(note, now)
        elif is_note_off(midi_bytes):
            selected = self._on_note_off(note, now)

        return True, selected

    def _on_note_on(self, note: int, now: float) -> None:
        if self._expired(now):
            self._reset()

        if self._armed:
            # A press before the release that would have fired: start over
            self._reset()

        if not self._sequence:
            # A gesture can only begin with the select note
            if note != self.select_note:
                return
            self._sequence = [note]
        elif note == self.count_note:
            self._sequence.append(note)
        else:
            # Second select note closes the gesture; it fires on release
            self._sequence.append(note)
            self._armed = True

        self._last_event = now

    def _on_note_off(self, note: int, now: float) -> Optional[int]:
        if self._expired(now):
            self._reset()
            return None

        self._last_event = now

        if self._armed and note == self.select_note:
            index = self._sequence.count(self.count_note)
            self._reset()
            return index

        return None

    def _expired(self, now: float) -> bool:
        """True if a gesture is in progress but has gone stale."""
        return bool(self._sequence) and (now - self._last_event) > self.gesture_timeout

    def _reset(self) -> None:
        self._sequence = []
        self._armed = False


class Controller:
    """
    Runs one mode at a time on a shared Disklavier connection.

    MIDI arrives on the rtmidi callback thread and is dispatched straight to the
    active mode.  Mode switches are queued and applied on the thread running
    ``run()``, so a slow ``stop()`` never stalls MIDI input.
    """

    def __init__(
        self,
        disklavier,
        mode_specs: Dict[int, Dict[str, Any]],
        default_mode: int = 0,
        idle_reset_seconds: float = 3600.0,
        select_note: int = 108,
        count_note: int = 107,
        gesture_timeout: float = 5.0,
    ):
        """
        Args:
            disklavier: Live Disklavier interface
            mode_specs: ``{index: {"mode": name, "options": {...}}}`` from the config
            default_mode: Mode entered at startup and returned to when idle
            idle_reset_seconds: Seconds without a key press before resetting to
                the default mode (0 disables)
            select_note: Note that opens and closes the mode-switch gesture
            count_note: Note repeated to count out the mode number
            gesture_timeout: Seconds of inactivity that abandon a partial gesture
        """
        self.disklavier = disklavier
        self.mode_specs = dict(mode_specs)
        self.default_mode = default_mode
        self.idle_reset_seconds = idle_reset_seconds

        if default_mode not in self.mode_specs:
            raise ValueError(
                f"Default mode {default_mode} is not configured "
                f"(configured modes: {sorted(self.mode_specs)})"
            )

        self.detector = ModeSwitchDetector(
            select_note=select_note,
            count_note=count_note,
            gesture_timeout=gesture_timeout,
        )

        self._active_index: Optional[int] = None
        self._active_mode: Optional[Mode] = None
        self._mode_lock = threading.Lock()

        self._switch_queue: "queue.Queue" = queue.Queue()
        self._stop_event = threading.Event()
        self._last_key_time = time.time()
        self._reported_tempo: Optional[float] = None

    # -- MIDI input ------------------------------------------------------

    def midi_callback(self, midi_bytes: List[int], delta_time: float) -> None:
        """Route one incoming message to the gesture detector or the active mode."""
        if is_note_on(midi_bytes):
            self._last_key_time = time.time()

        # Panel transport is a control surface, handled like the reserved notes:
        # consumed here, delivered to the mode as a hook, never as raw bytes
        if midi_bytes and midi_bytes[0] in (START, STOP):
            # Reaching for the panel is someone being present at the instrument
            self._last_key_time = time.time()
            self._switch_queue.put(partial(self._dispatch_transport, midi_bytes[0]))
            return

        try:
            consumed, selected = self.detector.observe(midi_bytes)
        except Exception as e:
            print(f"❌ Mode switch detection failed: {e}")
            consumed, selected = False, None

        if selected is not None:
            self.request_mode(selected)

        # The gesture keys are reserved for the controller and never reach a mode
        if consumed:
            return

        with self._mode_lock:
            mode = self._active_mode

        if mode is None:
            return

        try:
            mode.handle_midi(midi_bytes, delta_time)
        except Exception as e:
            print(f"❌ Mode '{mode.name}' failed handling {midi_bytes}: {e}")

    # -- Mode switching --------------------------------------------------

    def request_mode(self, index: int) -> None:
        """Queue a switch to the given mode number, applied by ``run()``."""
        self._switch_queue.put(index)

    def describe_modes(self) -> str:
        """Human-readable listing of the configured modes and their gestures."""
        lines = []
        for index in sorted(self.mode_specs):
            spec = self.mode_specs[index]
            lines.append(f"  {index}: {spec['mode']}  [{self.gesture_for(index)}]")
        return "\n".join(lines)

    def gesture_for(self, index: int) -> str:
        """The key sequence that selects a mode, as a readable string."""
        select = self.detector.select_note
        count = self.detector.count_note
        notes = [select] + [count] * index + [select]
        return ", ".join(f"{n} ({get_note_name(n)})" for n in notes)

    def all_notes_off(self) -> None:
        """
        Release every key on the piano.

        Called on every mode switch and at shutdown so a mode can never strand a
        note on the instrument, however it was interrupted.
        """
        if self.disklavier.midi_out is None:
            return
        try:
            self.disklavier.all_notes_off()
        except Exception as e:
            print(f"❌ Could not clear stuck notes: {e}")

    def _activate(self, index: int) -> None:
        """Stop the current mode and start the one at ``index``."""
        spec = self.mode_specs.get(index)
        if spec is None:
            print(
                f"⚠️  Mode {index} is not configured, staying in mode "
                f"{self._active_index}. Configured modes: {sorted(self.mode_specs)}"
            )
            return

        try:
            mode_class = get_mode_class(spec["mode"])
        except KeyError as e:
            print(f"❌ {e}")
            return

        # Detach the running mode before touching the new one so that no MIDI is
        # dispatched into a half-torn-down mode
        with self._mode_lock:
            previous = self._active_mode
            self._active_mode = None
            self._active_index = None

        if previous is not None:
            print(f"\n⏹️  Leaving mode: {previous.name}")
            try:
                previous.stop()
            except Exception as e:
                print(f"❌ Error stopping mode '{previous.name}': {e}")

        # Whatever the outgoing mode left sounding is not the next mode's problem
        self.all_notes_off()

        try:
            mode = mode_class(self.disklavier, **spec["options"])
        except Exception as e:
            print(f"❌ Could not create mode {index} ('{spec['mode']}'): {e}")
            return

        print(f"\n▶️  Mode {index}: {mode.name}")
        if mode.description:
            print(f"   {mode.description}")

        with self._mode_lock:
            self._active_mode = mode
            self._active_index = index

        try:
            mode.start()
        except Exception as e:
            print(f"❌ Error starting mode '{mode.name}': {e}")

    @property
    def active_index(self) -> Optional[int]:
        """Mode number currently running."""
        return self._active_index

    # -- Main loop -------------------------------------------------------

    def run(
        self, start_mode: Optional[int] = None, handle_signals: bool = True
    ) -> None:
        """
        Activate a mode and process switch requests until interrupted.

        Args:
            start_mode: Mode to start in (defaults to ``default_mode``)
            handle_signals: Install SIGINT/SIGTERM handlers for a clean shutdown.
                Only possible on the main thread, so this is skipped elsewhere.
        """
        if handle_signals and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

        self.disklavier.set_callback(self.midi_callback)

        print("\n🎛️  Configured modes:")
        print(self.describe_modes())
        print(
            f"\n🎹 Switch modes with {self.detector.select_note} "
            f"({get_note_name(self.detector.select_note)}), then the mode number as "
            f"repeats of {self.detector.count_note} "
            f"({get_note_name(self.detector.count_note)}), then "
            f"{self.detector.select_note} again."
        )
        if self.idle_reset_seconds > 0:
            print(
                f"⏳ Resets to mode {self.default_mode} after "
                f"{self.idle_reset_seconds:.0f}s without a key press."
            )
        print("   Press Ctrl+C to stop")

        if start_mode is not None and start_mode not in self.mode_specs:
            print(
                f"⚠️  Mode {start_mode} is not configured, "
                f"starting in mode {self.default_mode} instead"
            )
            start_mode = None

        self._last_key_time = time.time()
        self._activate(self.default_mode if start_mode is None else start_mode)

        try:
            while not self._stop_event.is_set():
                try:
                    request = self._switch_queue.get(timeout=0.5)
                except queue.Empty:
                    self._check_idle()
                    self._check_tempo()
                    continue

                if request is _SHUTDOWN:
                    break

                # Transport hooks ride the same queue as mode switches, so they
                # run here rather than stalling the MIDI callback thread
                if callable(request):
                    request()
                    continue

                self._activate(request)
                # A gesture is itself a key press, so the idle clock restarts
                self._last_key_time = time.time()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def _dispatch_transport(self, status: int) -> None:
        """Hand a panel play/stop press to the active mode."""
        with self._mode_lock:
            mode = self._active_mode

        label = "start" if status == START else "stop"
        print(f"🎛️  Transport {label}")

        if mode is None:
            return

        try:
            if status == START:
                mode.on_transport_start()
            else:
                mode.on_transport_stop()
        except Exception as e:
            print(f"❌ Mode '{mode.name}' failed handling transport {label}: {e}")

    def _check_tempo(self) -> None:
        """
        Log the tempo dial when it moves, and when the clock comes or goes.

        Modes read ``disklavier.tempo`` themselves; this only makes the dial
        visible in the log, which is otherwise silent about it.
        """
        tempo = self.disklavier.tempo
        previous = self._reported_tempo

        if tempo is None and previous is not None:
            print("🎼 MIDI clock lost -- tempo is now None (metronome off?)")
        elif tempo is not None and previous is None:
            print(f"🎼 MIDI clock found -- tempo {tempo:.1f} BPM")
        elif tempo is not None and previous is not None:
            if abs(tempo - previous) < 2.0:
                return  # dial has not really moved; leave the log alone
            print(f"🎼 Tempo {tempo:.1f} BPM")

        self._reported_tempo = tempo

    def _check_idle(self) -> None:
        """Return to the default mode after a long enough silence."""
        if self.idle_reset_seconds <= 0:
            return
        if self._active_index == self.default_mode:
            return
        if (time.time() - self._last_key_time) < self.idle_reset_seconds:
            return

        print(
            f"\n⏳ No key pressed for {self.idle_reset_seconds:.0f}s, "
            f"resetting to mode {self.default_mode}"
        )
        self._last_key_time = time.time()
        self._activate(self.default_mode)

    def shutdown(self) -> None:
        """Ask ``run()`` to stop. Safe to call from any thread."""
        self._stop_event.set()
        self._switch_queue.put(_SHUTDOWN)

    def _signal_handler(self, signum, frame) -> None:
        print(f"\n🛑 Received signal {signum}, shutting down...")
        self.shutdown()

    def close(self) -> None:
        """Stop the active mode and release the hardware."""
        self._stop_event.set()

        with self._mode_lock:
            mode = self._active_mode
            self._active_mode = None
            self._active_index = None

        if mode is not None:
            try:
                mode.stop()
            except Exception as e:
                print(f"❌ Error stopping mode '{mode.name}': {e}")

        self.all_notes_off()
        self.disklavier.close()
