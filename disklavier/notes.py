"""
Note-level MIDI helpers shared by the top level and every mode.

Keeping these here (rather than on the Disklavier interface) lets modes reason
about raw MIDI bytes without needing a live hardware connection.
"""

from typing import List, Optional

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Range of a standard 88-key piano: A0 through C8.
LOWEST_NOTE = 21
HIGHEST_NOTE = 108


def get_note_name(note_number: int) -> str:
    """Convert MIDI note number to note name."""
    octave = (note_number // 12) - 1
    note = NOTE_NAMES[note_number % 12]
    return f"{note}{octave}"


def _status(midi_bytes: List[int]) -> Optional[int]:
    """Return the status byte of a well-formed channel message, else None."""
    if not midi_bytes or len(midi_bytes) < 3:
        return None
    status = midi_bytes[0]
    if not isinstance(status, int):
        return None
    return status


def note_number(midi_bytes: List[int]) -> Optional[int]:
    """
    Return the note number if this is a note on/off message, else None.
    """
    status = _status(midi_bytes)
    if status is None:
        return None
    if status & 0xF0 not in (0x80, 0x90):
        return None
    return midi_bytes[1]


def is_note_on(midi_bytes: List[int]) -> bool:
    """True for a genuine key press (note on with non-zero velocity)."""
    status = _status(midi_bytes)
    if status is None:
        return False
    return (status & 0xF0) == 0x90 and midi_bytes[2] > 0


def is_note_off(midi_bytes: List[int]) -> bool:
    """True for a key release, including note on with velocity 0."""
    status = _status(midi_bytes)
    if status is None:
        return False
    msg_type = status & 0xF0
    if msg_type == 0x80:
        return True
    return msg_type == 0x90 and midi_bytes[2] == 0
