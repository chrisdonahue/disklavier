#!/usr/bin/env python3
"""
play.py - A simple script to play back the most recent MIDI recording.

This script finds the most recent MIDI file in the recordings directory
and plays it through the default MIDI output device.
"""

import os
import time
import logging
import glob
import mido


from . import RECORDINGS_DIR, DISKLAVIER_MIDI_IN_NAME, DISKLAVIER_MIDI_OUT_NAME
from .midi import MidiInterface

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def find_most_recent_midi():
    """Find the most recent MIDI file in the recordings directory."""
    recordings_dir = str(RECORDINGS_DIR)
    if not os.path.exists(recordings_dir):
        logger.error(f"Recordings directory '{recordings_dir}' not found.")
        return None

    # Get all MIDI files in the directory
    midi_files = glob.glob(os.path.join(recordings_dir, "*.mid"))
    if not midi_files:
        logger.error("No MIDI files found in recordings directory.")
        return None

    # Sort by modification time (most recent last)
    midi_files.sort(key=os.path.getmtime)
    most_recent = midi_files[-1]

    logger.info(f"Found most recent MIDI file: {most_recent}")
    return most_recent


def play_midi_file(file_path):
    """Play the specified MIDI file through the default MIDI output."""
    if not os.path.exists(file_path):
        logger.error(f"MIDI file '{file_path}' not found.")
        return False

    try:
        # Parse the filename to extract information
        filename = os.path.basename(file_path)
        logger.info(f"Playing MIDI file: {filename}")

        # Initialize MIDI interface for output
        midi = MidiInterface(
            input_name=DISKLAVIER_MIDI_IN_NAME,
            output_name=DISKLAVIER_MIDI_OUT_NAME,
        )
        if not midi.output_port:
            logger.error("No MIDI output port available.")
            return False

        # Load the MIDI file
        midi_file = mido.MidiFile(file_path)
        logger.info(
            f"MIDI file loaded: {len(midi_file.tracks)} tracks, {midi_file.length:.2f} seconds"
        )

        # Play the file, sending messages to the output port
        logger.info("Playback started")
        start_time = time.time()

        # Calculate total notes for progress tracking
        total_notes = sum(
            1
            for track in midi_file.tracks
            for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        )
        notes_played = 0

        for msg in midi_file.play():
            # For note_on events, track progress
            if msg.type == "note_on" and msg.velocity > 0:
                notes_played += 1
                progress = (notes_played / total_notes) * 100 if total_notes > 0 else 0
                logger.info(
                    f"Playing note: {msg.note}, velocity: {msg.velocity} - Progress: {progress:.1f}%"
                )

            # Send the message to the MIDI output
            midi.send_message(msg)

        elapsed_time = time.time() - start_time
        logger.info(f"Playback completed in {elapsed_time:.2f} seconds")

        # Close MIDI port
        midi.close()
        return True

    except Exception as e:
        logger.error(f"Error playing MIDI file: {e}")
        return False


def main():
    """Main function to find and play the most recent MIDI recording."""
    # Find the most recent MIDI file
    midi_file = find_most_recent_midi()
    if not midi_file:
        logger.error("No MIDI file to play.")
        return

    # Play the MIDI file
    success = play_midi_file(midi_file)
    if success:
        logger.info("Playback completed successfully.")
    else:
        logger.error("Playback failed.")


if __name__ == "__main__":
    main()
