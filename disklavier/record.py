#!/usr/bin/env python3
"""
record.py - A daemon script for recording MIDI data from a Disklavier or other MIDI instrument.

This script continuously listens for MIDI input and records it to files.
When there is no MIDI activity for 10 seconds, it saves the recorded data
to a file named with the timestamp, number of notes, and duration.
"""

import datetime
import logging
import pathlib
import time
from threading import Timer

import mido

from . import RECORDINGS_DIR
from .midi import MidiInterface

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("midi_recorder.log")],
)
logger = logging.getLogger(__name__)


class MidiRecorder:
    def __init__(
        self,
        input_name=None,
        output_name=None,
        silence_timeout=10.0,
        output_dir: pathlib.Path = RECORDINGS_DIR,
    ):
        """
        Initialize the MIDI recorder.

        Args:
            input_name: Name of the MIDI input port (None for default)
            output_name: Name of the MIDI output port (None for default)
            silence_timeout: Time in seconds of silence before saving a recording
        """
        self.midi = MidiInterface(input_name, output_name)
        self.silence_timeout = silence_timeout
        self.recording = False
        self.current_messages = []
        self.silence_timer = None
        self.start_time = None
        self.last_activity_time = None
        self.note_count = 0
        self.output_dir = output_dir

        # Create recordings directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using recordings directory: {self.output_dir}")

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages and add them to the current recording."""
        logger.info(f"Received MIDI message: {msg}")

        # Store the current time with the message
        # Add custom attribute to track when we received this message
        received_time = time.time()

        # Start recording if this is the first message
        if not self.recording:
            self.start_recording()

        # Reset the silence timer
        self.reset_silence_timer()

        # We need to create a copy of the message with our custom attribute
        msg_copy = msg.copy()

        # Add the message to our recording
        self.current_messages.append((received_time, msg_copy))

        # Count note events
        if msg.type == "note_on" and msg.velocity > 0:
            self.note_count += 1

    def start_recording(self):
        """Start a new recording session."""
        logger.info("Starting new recording")
        self.recording = True
        self.start_time = time.time()
        self.last_activity_time = self.start_time
        self.current_messages = []
        self.note_count = 0

    def reset_silence_timer(self):
        """Reset the silence timer that triggers saving the recording."""
        self.last_activity_time = time.time()

        # Cancel the existing timer if there is one
        if self.silence_timer is not None:
            self.silence_timer.cancel()

        # Set a new timer
        self.silence_timer = Timer(self.silence_timeout, self.save_recording)
        self.silence_timer.daemon = True
        self.silence_timer.start()

    def save_recording(self):
        """Save the current recording to a file if it contains data."""
        if not self.recording or not self.current_messages:
            logger.info("No data to save")
            return

        # Calculate recording duration
        duration = self.last_activity_time - self.start_time
        duration_formatted = str(round(duration)).zfill(4)

        # Create timestamp
        timestamp = datetime.datetime.now().strftime("%y%b%d-%I%M%p%S").upper()

        # Create filename with timestamp, note count, and duration
        filename = (
            f"{timestamp}-d{duration_formatted}-n{str(self.note_count).zfill(6)}.mid"
        )
        filepath = self.output_dir / filename

        # Create a MIDI file with a single track
        mid = mido.MidiFile(type=1, ticks_per_beat=480)
        track = mido.MidiTrack()
        mid.tracks.append(track)

        # Add tempo and time signature messages
        track.append(
            mido.MetaMessage("track_name", name="Disklavier Recording", time=0)
        )
        track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))  # 120 BPM
        track.append(
            mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
        )

        # Filter and sort messages by timestamp
        filtered_messages = [
            (t, m)
            for t, m in self.current_messages
            if m.type
            in [
                "note_on",
                "note_off",
                "control_change",
                "program_change",
                "pitchwheel",
            ]
        ]
        filtered_messages.sort(key=lambda msg: msg[0])

        # Convert real timestamps to MIDI ticks
        previous_time = self.start_time
        for t, msg in filtered_messages:
            # Calculate time delta in seconds
            delta_sec = t - previous_time
            # Convert to MIDI ticks (at 120 BPM, 480 ticks per beat)
            delta_ticks = int(delta_sec * 120 * 480 / 60)

            # Create a new message with the correct delta time
            new_msg = msg.copy(time=delta_ticks)
            track.append(new_msg)

            # Update previous time
            previous_time = t

        # Add end of track message
        track.append(mido.MetaMessage("end_of_track", time=0))

        # Save the file
        mid.save(filepath)
        logger.info(f"Saved recording: {filepath}")
        logger.info(
            f"Recording stats: {self.note_count} notes, {duration_formatted} seconds"
        )

        # Reset for the next recording
        self.recording = False
        self.current_messages = []
        self.note_count = 0

    def start_listening(self):
        """Start listening for MIDI input continuously."""
        logger.info("Starting MIDI recorder daemon")
        logger.info(f"Silence timeout set to {self.silence_timeout} seconds")

        try:
            while True:
                # Poll for MIDI messages
                msg = self.midi.receive_message(timeout=0.1)
                if msg:
                    self._handle_midi_message(msg)

                # Short sleep to prevent CPU hogging
                time.sleep(0.01)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, stopping...")
        finally:
            # Save any ongoing recording
            if self.recording and self.current_messages:
                logger.info("Saving final recording before exit")
                if self.silence_timer:
                    self.silence_timer.cancel()
                self.save_recording()

            # Close MIDI ports
            self.midi.close()
            logger.info("MIDI recorder daemon stopped")


def main():
    """Main entry point for the MIDI recorder daemon."""
    from . import DISKLAVIER_MIDI_IN_NAME, DISKLAVIER_MIDI_OUT_NAME

    # Parameters can be added here for command-line arguments
    recorder = MidiRecorder(
        input_name=DISKLAVIER_MIDI_IN_NAME,
        output_name=DISKLAVIER_MIDI_OUT_NAME,
        silence_timeout=10.0,
    )
    recorder.start_listening()


if __name__ == "__main__":
    main()
