"""
Utility functions for MIDI processing in the Disklavier web interface.
"""

import pretty_midi
import io
from typing import Union, List, Tuple


def burn_midi_sustain(original: Union[str, bytes]) -> bytes:
    """
    Take a MIDI file containing sustain pedal events and "burn in" the sustain
    by extending note durations appropriately, then remove sustain pedal CC events.

    Args:
        original: Either a file path (str) or pre-loaded MIDI bytes

    Returns:
        bytes: Processed MIDI file with sustain burned in and pedal events removed
    """
    # Load the MIDI file
    if isinstance(original, str):
        midi = pretty_midi.PrettyMIDI(original)
    else:
        midi = pretty_midi.PrettyMIDI(io.BytesIO(original))

    # Process each instrument
    for instrument in midi.instruments:
        if instrument.is_drum:
            continue

        # Extract sustain pedal events (CC64)
        sustain_events = []
        for cc in instrument.control_changes:
            if cc.number == 64:  # Sustain pedal
                sustain_events.append((cc.time, cc.value >= 64))  # True if pedal down

        # Sort sustain events by time
        sustain_events.sort(key=lambda x: x[0])

        # Process notes to extend based on sustain
        processed_notes = []

        for note in instrument.notes:
            # Find sustain state at note end
            note_end = note.end

            # Check if sustain pedal is down when the note would normally end
            sustain_down_at_end = False
            for i, (time, is_down) in enumerate(sustain_events):
                if time <= note_end:
                    sustain_down_at_end = is_down
                else:
                    break

            # If sustain is down at note end, find when it's released
            if sustain_down_at_end:
                release_time = None

                # Find the next pedal up event after note end
                for time, is_down in sustain_events:
                    if time > note_end and not is_down:
                        release_time = time
                        break

                # If no release found, use the end of the piece
                if release_time is None:
                    release_time = midi.get_end_time()

                # Check if another note with same pitch starts before release
                for other_note in instrument.notes:
                    if (
                        other_note.pitch == note.pitch
                        and other_note.start > note.start
                        and other_note.start < release_time
                    ):
                        release_time = other_note.start
                        break

                # Create extended note
                new_note = pretty_midi.Note(
                    velocity=note.velocity,
                    pitch=note.pitch,
                    start=note.start,
                    end=release_time,
                )
                processed_notes.append(new_note)
            else:
                # Keep original note
                processed_notes.append(note)

        # Replace notes with processed ones
        instrument.notes = processed_notes

        # Remove sustain pedal CC events
        instrument.control_changes = [
            cc for cc in instrument.control_changes if cc.number != 64
        ]

    # Write to bytes
    output_buffer = io.BytesIO()
    midi.write(output_buffer)
    output_buffer.seek(0)
    return output_buffer.read()
