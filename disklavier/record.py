#!/usr/bin/env python3
"""
Disklavier Recording Daemon

This daemon continuously records MIDI input from a Disklavier with high timing precision.
It automatically starts recording when MIDI input is received and saves files when
silence is detected for a configurable duration.
"""

import argparse
import datetime
import mido
import signal
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from .disklavier import Disklavier
from .paths import RECORDINGS_DIR


class MidiRecorder:
    """
    High-precision MIDI recorder with automatic silence detection and file saving.
    """

    def __init__(
        self,
        input_device_pattern: str = "*USB Midi*",
        silence_timeout: float = 10.0,
        filter_system: bool = True,
    ):
        """
        Initialize the MIDI recorder.

        Args:
            input_device_pattern: Pattern for MIDI input device
            silence_timeout: Seconds of silence before saving recording
            filter_system: Whether to filter out system timing messages
        """
        self.silence_timeout = silence_timeout
        self.filter_system = filter_system

        # Recording state
        self.is_recording = False
        self.midi_events = []
        self.recording_start_time = None
        self.last_message_time = None
        self.note_count = 0

        # Threading
        self._stop_event = threading.Event()
        self._silence_timer = None
        self._lock = threading.Lock()

        # Initialize Disklavier
        print(f"🎹 Initializing Disklavier recording daemon...")
        print(f"   Input device pattern: {input_device_pattern}")
        print(f"   Silence timeout: {silence_timeout}s")
        print(f"   Filter system messages: {filter_system}")

        self.disklavier = Disklavier(
            input_device_pattern=input_device_pattern,
            output_device_pattern=None,  # Recording only, no output needed
            filter_system=filter_system,
        )

        if self.disklavier.midi_in is None:
            raise RuntimeError(
                "No MIDI input device found. Cannot start recording daemon."
            )

        print("✓ Disklavier initialized successfully")

        # Set up MIDI callback
        self.disklavier.set_callback(self._midi_callback)

    def _midi_callback(self, midi_bytes: List[int], delta_time: float):
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
                    "message": midi_bytes.copy(),
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
            msg_type_name = self.disklavier.get_message_type_name(midi_bytes)
            print(
                f"📥 {msg_type_name}: {midi_bytes} (t={timestamp:.3f}s, notes={self.note_count})"
            )

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
        self._silence_timer.start()

    def _on_silence_timeout(self):
        """Handle silence timeout - save recording and reset."""
        with self._lock:
            if self.is_recording and self.midi_events:
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

    def run(self):
        """Run the recording daemon."""
        print(f"\n🎯 MIDI Recording Daemon Active")
        print(f"📁 Recordings will be saved to: {RECORDINGS_DIR}")
        print(f"⏱️  Silence timeout: {self.silence_timeout}s")
        print(f"🎧 Waiting for MIDI input...")
        print("   Press Ctrl+C to stop")

        try:
            # Set up signal handlers for graceful shutdown
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

            # Main daemon loop
            while not self._stop_event.is_set():
                time.sleep(0.1)  # Small sleep to prevent busy waiting

        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\n🛑 Received signal {signum}, shutting down...")
        self._stop_event.set()

    def _shutdown(self):
        """Clean shutdown of the recording daemon."""
        print("🛑 Shutting down recording daemon...")

        # Save any ongoing recording
        with self._lock:
            if self.is_recording and self.midi_events:
                print("💾 Saving final recording...")
                self._save_recording()
            self._stop_recording()

        # Clean up
        if self.disklavier:
            self.disklavier.close()

        print("✓ Shutdown complete")


def main():
    """Main entry point for the recording daemon."""
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

    # List devices and exit if requested
    if args.list_devices:
        print("🎹 Available MIDI Input Devices:")
        from .midi import MidiInterface

        devices = MidiInterface.list_input_devices()
        if devices:
            for i, device in enumerate(devices):
                print(f"  {i}: {device}")
        else:
            print("  No MIDI input devices found")
        return

    try:
        # Create and run the recorder
        recorder = MidiRecorder(
            input_device_pattern=args.input,
            silence_timeout=args.timeout,
            filter_system=not args.include_system,
        )

        recorder.run()

    except Exception as e:
        print(f"❌ Failed to start recording daemon: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
