#!/usr/bin/env python3
"""
Surveil mode: continuous MIDI recording.

Records MIDI input from a Disklavier with high timing precision.  Recording
starts automatically when MIDI input arrives and the file is saved once silence
is detected for a configurable duration.
"""

import argparse
import datetime
import mido
import signal
import sys
import threading
import time
from typing import Callable, List, Optional

from ..base import Mode
from ...paths import RECORDINGS_DIR


class MidiRecorder:
    """
    High-precision MIDI recorder with automatic silence detection and file saving.

    This class only consumes MIDI messages handed to it; opening the hardware is
    the caller's job.
    """

    def __init__(
        self,
        silence_timeout: float = 10.0,
        message_namer: Optional[Callable[[List[int]], str]] = None,
    ):
        """
        Initialize the MIDI recorder.

        Args:
            silence_timeout: Seconds of silence before saving recording
            message_namer: Optional callable turning MIDI bytes into a readable
                name, used only for console feedback
        """
        self.silence_timeout = silence_timeout
        self._message_namer = message_namer

        # Recording state
        self.is_recording = False
        self.midi_events = []
        self.recording_start_time = None
        self.last_message_time = None
        self.note_count = 0

        # Threading
        self._silence_timer = None
        self._lock = threading.Lock()

    def handle_midi(self, midi_bytes: List[int], delta_time: float):
        """
        High-precision MIDI callback that records events with timestamps.

        Args:
            midi_bytes: MIDI message bytes
            delta_time: Time since last message (from rtmidi)
        """
        current_time = time.time()

        with self._lock:
            # If not currently recording, start recording
            if not self.is_recording:
                self._start_recording(current_time)

            # Calculate precise timestamp relative to recording start
            if self.recording_start_time is not None:
                timestamp = current_time - self.recording_start_time
            else:
                timestamp = 0.0

            # Store the event with high precision timestamp
            self.midi_events.append(
                {
                    "message": list(midi_bytes),
                    "timestamp": timestamp,
                    "delta_time": delta_time,
                    "absolute_time": current_time,
                }
            )

            # Count notes for filename
            if len(midi_bytes) >= 3:
                msg_type = midi_bytes[0] & 0xF0
                if msg_type == 0x90 and midi_bytes[2] > 0:  # Note on with velocity > 0
                    self.note_count += 1

            # Update last message time
            self.last_message_time = current_time

            # Reset silence timer
            self._reset_silence_timer()

            # Print real-time feedback
            msg_type_name = self._describe(midi_bytes)
            print(
                f"📥 {msg_type_name}: {midi_bytes} (t={timestamp:.3f}s, notes={self.note_count})"
            )

    def _describe(self, midi_bytes: List[int]) -> str:
        """Human-readable name for a message, if a namer was supplied."""
        if self._message_namer is None:
            return "MIDI"
        return self._message_namer(midi_bytes)

    def _start_recording(self, start_time: float):
        """Start a new recording session."""
        self.is_recording = True
        self.recording_start_time = start_time
        self.midi_events = []
        self.note_count = 0
        self.last_message_time = start_time

        print(
            f"\n🔴 Recording started at {datetime.datetime.now().strftime('%H:%M:%S')}"
        )

    def _reset_silence_timer(self):
        """Reset the silence detection timer."""
        # Cancel existing timer
        if self._silence_timer is not None:
            self._silence_timer.cancel()

        # Start new timer
        self._silence_timer = threading.Timer(
            self.silence_timeout, self._on_silence_timeout
        )
        self._silence_timer.daemon = True
        self._silence_timer.start()

    def _on_silence_timeout(self):
        """Handle silence timeout - save recording and reset."""
        with self._lock:
            if self.is_recording and self.midi_events:
                self._save_recording()
            self._stop_recording()

    def flush(self):
        """Save any in-progress recording and reset to the idle state."""
        with self._lock:
            if self.is_recording and self.midi_events:
                print("💾 Saving in-progress recording...")
                self._save_recording()
            self._stop_recording()

    def _stop_recording(self):
        """Stop the current recording session."""
        self.is_recording = False
        self.recording_start_time = None
        self.last_message_time = None

        if self._silence_timer is not None:
            self._silence_timer.cancel()
            self._silence_timer = None

    def _save_recording(self):
        """Save the current recording as a MIDI file with high precision timing."""
        if not self.midi_events:
            print("⚠️  No MIDI events to save")
            return

        try:
            # Calculate duration
            if self.midi_events:
                duration_seconds = self.midi_events[-1]["timestamp"]
            else:
                duration_seconds = 0

            duration_formatted = str(int(duration_seconds)).zfill(4)

            # Create timestamp
            timestamp = datetime.datetime.now().strftime("%y%b%d-%I%M%p%S").upper()

            # Create filename with timestamp, duration, and note count
            filename = f"{timestamp}-d{duration_formatted}-n{str(self.note_count).zfill(6)}.mid"

            filepath = RECORDINGS_DIR / filename

            # Create MIDI file with high precision timing
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)

            # Set high resolution (ticks per beat) for timing precision
            mid.ticks_per_beat = 960  # High resolution for precise timing

            # Convert events to MIDI messages with precise timing
            last_timestamp = 0.0

            for event in self.midi_events:
                # Calculate delta time in ticks
                delta_seconds = event["timestamp"] - last_timestamp
                delta_ticks = int(
                    delta_seconds * mid.ticks_per_beat * 2
                )  # Assume 120 BPM default

                # Create MIDI message
                midi_bytes = event["message"]
                if len(midi_bytes) >= 3:
                    msg_type = midi_bytes[0] & 0xF0
                    channel = midi_bytes[0] & 0x0F

                    if msg_type == 0x90:  # Note on
                        msg = mido.Message(
                            "note_on",
                            channel=channel,
                            note=midi_bytes[1],
                            velocity=midi_bytes[2],
                            time=delta_ticks,
                        )
                    elif msg_type == 0x80:  # Note off
                        msg = mido.Message(
                            "note_off",
                            channel=channel,
                            note=midi_bytes[1],
                            velocity=midi_bytes[2],
                            time=delta_ticks,
                        )
                    elif msg_type == 0xB0:  # Control change
                        msg = mido.Message(
                            "control_change",
                            channel=channel,
                            control=midi_bytes[1],
                            value=midi_bytes[2],
                            time=delta_ticks,
                        )
                    else:
                        continue  # Skip unknown message types

                    track.append(msg)
                    last_timestamp = event["timestamp"]

            # Save the MIDI file
            mid.save(str(filepath))

            # Print save confirmation
            print(f"\n💾 Recording saved: {filename}")
            print(f"   📍 Path: {filepath}")
            print(f"   ⏱️  Duration: {duration_seconds:.1f}s")
            print(f"   🎵 Notes: {self.note_count}")
            print(f"   📊 Events: {len(self.midi_events)}")

        except Exception as e:
            print(f"❌ Error saving recording: {e}")


class SurveilMode(Mode):
    """
    Listen to the piano and record everything played.

    Recording begins on the first message and the take is written to disk once
    the piano has been silent for ``silence_timeout`` seconds.
    """

    name = "surveil"
    description = "Record everything played, saving a take after each silence"

    def __init__(self, disklavier, silence_timeout: float = 10.0):
        """
        Args:
            disklavier: Live Disklavier interface
            silence_timeout: Seconds of silence before saving a recording
        """
        super().__init__(disklavier)
        self.recorder = MidiRecorder(
            silence_timeout=silence_timeout,
            message_namer=disklavier.get_message_type_name,
        )

    def start(self) -> None:
        print(f"📁 Recordings will be saved to: {RECORDINGS_DIR}")
        print(f"⏱️  Silence timeout: {self.recorder.silence_timeout}s")
        print("🎧 Waiting for MIDI input...")

    def handle_midi(self, midi_bytes: List[int], delta_time: float) -> None:
        self.recorder.handle_midi(midi_bytes, delta_time)

    def stop(self) -> None:
        self.recorder.flush()


def main():
    """Standalone entry point: run surveil mode on its own, without mode switching."""
    parser = argparse.ArgumentParser(
        description="Disklavier Recording Daemon - Continuous MIDI recording with automatic file saving"
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        default="*USB Midi*",
        help="Input device pattern (default: '*USB Midi*')",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=10.0,
        help="Silence timeout in seconds before saving recording (default: 10.0)",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include system timing messages (default is to filter them out)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available MIDI input devices and exit",
    )

    args = parser.parse_args()

    # Imported here so --list-devices works even without a device attached
    from ...disklavier import Disklavier
    from ...midi import MidiInterface

    # List devices and exit if requested
    if args.list_devices:
        print("🎹 Available MIDI Input Devices:")
        devices = MidiInterface.list_input_devices()
        if devices:
            for i, device in enumerate(devices):
                print(f"  {i}: {device}")
        else:
            print("  No MIDI input devices found")
        return

    disklavier = None
    try:
        print("🎹 Initializing Disklavier recording daemon...")
        print(f"   Input device pattern: {args.input}")
        print(f"   Silence timeout: {args.timeout}s")
        print(f"   Filter system messages: {not args.include_system}")

        disklavier = Disklavier(
            input_device_pattern=args.input,
            output_device_pattern=None,  # Recording only, no output needed
            filter_system=not args.include_system,
        )

        if disklavier.midi_in is None:
            raise RuntimeError(
                "No MIDI input device found. Cannot start recording daemon."
            )

        print("✓ Disklavier initialized successfully")

        mode = SurveilMode(disklavier, silence_timeout=args.timeout)
        disklavier.set_callback(mode.handle_midi)

        print("\n🎯 MIDI Recording Daemon Active")
        mode.start()
        print("   Press Ctrl+C to stop")

        stop_event = threading.Event()

        def signal_handler(signum, frame):
            print(f"\n🛑 Received signal {signum}, shutting down...")
            stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            while not stop_event.is_set():
                time.sleep(0.1)  # Small sleep to prevent busy waiting
        except KeyboardInterrupt:
            pass

        print("🛑 Shutting down recording daemon...")
        mode.stop()
        print("✓ Shutdown complete")

    except Exception as e:
        print(f"❌ Failed to start recording daemon: {e}")
        sys.exit(1)
    finally:
        if disklavier is not None:
            disklavier.close()


if __name__ == "__main__":
    main()
