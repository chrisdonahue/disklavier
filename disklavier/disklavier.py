from typing import List, Callable, Optional
import argparse
from .midi import MidiInterface


class Disklavier(MidiInterface):
    """
    Disklavier-specific MIDI interface that handles device discovery and message filtering.

    This class extends MidiInterface to provide Disklavier-specific functionality:
    - Automatic USB MIDI device detection
    - Optional filtering to only musical messages (note on/off, control change)
    - Proper message parsing from different callback formats
    """

    def __init__(
        self,
        input_device_pattern: Optional[str] = "*USB Midi*",
        output_device_pattern: Optional[str] = "*USB Midi*",
        filter_system: bool = True,
    ):
        """
        Initialize Disklavier MIDI interface.

        Args:
            input_device_pattern: Pattern for input device (default: "*USB Midi*", None to disable)
            output_device_pattern: Pattern for output device (default: "*USB Midi*", None to disable)
            filter_system: If True, filter out system timing messages (default: True)
        """
        super().__init__(input_device_pattern, output_device_pattern)
        self._user_callback = None
        self.filter_system = filter_system

        # Override the parent callback with our filtering callback if input device exists
        if self.midi_in is not None:
            self.midi_in.set_callback(self._disklavier_callback)

    def _is_musical_message(self, midi_bytes: List[int]) -> bool:
        """Check if a MIDI message is musically relevant for Disklavier."""
        if not midi_bytes or len(midi_bytes) == 0:
            return False

        try:
            status = midi_bytes[0]
            if not isinstance(status, int):
                return False
        except (IndexError, TypeError):
            return False

        # Filter out system messages (timing, etc.)
        if status >= 0xF0:
            return False

        # Accept only note on/off and control change
        msg_type = status & 0xF0
        return msg_type in [
            0x80,  # Note Off
            0x90,  # Note On
            0xB0,  # Control Change
        ]

    def _parse_midi_message(self, raw_message, delta_time=None):
        """
        Parse MIDI message from callback into consistent format.

        Returns:
            tuple: (midi_bytes: List[int], delta_time: float)
        """
        actual_message = None
        actual_delta = 0.0

        if isinstance(raw_message, tuple) and len(raw_message) >= 2:
            # Message is a tuple (midi_bytes, delta_time)
            actual_message = raw_message[0]
            actual_delta = (
                raw_message[1] if isinstance(raw_message[1], (int, float)) else 0.0
            )
        elif isinstance(raw_message, list):
            # Message is just the MIDI bytes
            actual_message = raw_message
            actual_delta = delta_time if isinstance(delta_time, (int, float)) else 0.0
        else:
            return None, 0.0

        return actual_message, actual_delta

    def _disklavier_callback(self, raw_message, delta_time=None):
        """
        Internal callback that filters messages and calls user callback.
        """
        # Parse the message format
        midi_bytes, parsed_delta = self._parse_midi_message(raw_message, delta_time)

        if midi_bytes is None:
            return

        # Filter to only musical messages if enabled
        if self.filter_system and not self._is_musical_message(midi_bytes):
            return

        # Call user callback with clean format
        if self._user_callback:
            self._user_callback(midi_bytes, parsed_delta)

    def set_callback(self, callback_function: Callable[[List[int], float], None]):
        """
        Set callback for filtered MIDI messages.

        Args:
            callback_function: Function that takes (midi_bytes: List[int], delta_time: float)
                              Only receives note on/off and control change messages if filter_system=True.

        Raises:
            RuntimeError: If no input device is configured
        """
        if self.midi_in is None:
            raise RuntimeError("No MIDI input device configured. Cannot set callback.")
        self._user_callback = callback_function

    def send_note_on(self, note: int, velocity: int = 100, channel: int = 0):
        """
        Send a note on message.

        Raises:
            RuntimeError: If no output device is configured
        """
        if self.midi_out is None:
            raise RuntimeError("No MIDI output device configured. Cannot send note on.")
        self.send_message([0x90 | channel, note, velocity])

    def send_note_off(self, note: int, velocity: int = 0, channel: int = 0):
        """
        Send a note off message.

        Raises:
            RuntimeError: If no output device is configured
        """
        if self.midi_out is None:
            raise RuntimeError(
                "No MIDI output device configured. Cannot send note off."
            )
        self.send_message([0x80 | channel, note, velocity])

    def send_control_change(self, control: int, value: int, channel: int = 0):
        """
        Send a control change message.

        Raises:
            RuntimeError: If no output device is configured
        """
        if self.midi_out is None:
            raise RuntimeError(
                "No MIDI output device configured. Cannot send control change."
            )
        self.send_message([0xB0 | channel, control, value])

    def send_sustain_pedal(self, down: bool, channel: int = 0):
        """
        Send sustain pedal control change (CC 64).

        Raises:
            RuntimeError: If no output device is configured
        """
        value = 127 if down else 0
        self.send_control_change(64, value, channel)

    def send_soft_pedal(self, down: bool, channel: int = 0):
        """
        Send soft pedal control change (CC 67).

        Raises:
            RuntimeError: If no output device is configured
        """
        value = 127 if down else 0
        self.send_control_change(67, value, channel)

    def get_message_type_name(self, midi_bytes: List[int]) -> str:
        """Get a human-readable name for the MIDI message type."""
        if not midi_bytes or len(midi_bytes) == 0:
            return "Unknown"

        try:
            status = midi_bytes[0]
            if not isinstance(status, int):
                return "Invalid"
        except (IndexError, TypeError):
            return "Invalid"

        msg_type = status & 0xF0
        channel = status & 0x0F

        if msg_type == 0x90:
            if len(midi_bytes) >= 3:
                if midi_bytes[2] == 0:
                    return f"Note Off (ch{channel+1})"  # Note on with vel=0 acts as note off
                else:
                    return f"Note On (ch{channel+1})"
            return f"Note On (ch{channel+1})"
        elif msg_type == 0x80:
            return f"Note Off (ch{channel+1})"
        elif msg_type == 0xB0:
            if len(midi_bytes) >= 3:
                control_name = self._get_control_name(midi_bytes[1])
                return (
                    f"Control Change {midi_bytes[1]} ({control_name}) (ch{channel+1})"
                )
            return f"Control Change (ch{channel+1})"
        else:
            return f"MIDI 0x{status:02X}"

    def _get_control_name(self, control_number: int) -> str:
        """Get human-readable name for control change numbers."""
        control_names = {
            64: "Sustain Pedal",
            67: "Soft Pedal",
            66: "Sostenuto Pedal",
            7: "Volume",
            10: "Pan",
            1: "Modulation",
            11: "Expression",
        }
        return control_names.get(control_number, f"CC{control_number}")


def main():
    """Interactive Disklavier test interface."""
    parser = argparse.ArgumentParser(
        description="Disklavier Interactive Test Interface"
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include system timing messages (default is to filter them out)",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        default="*USB Midi*",
        help="Input device pattern (default: '*USB Midi*')",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="*USB Midi*",
        help="Output device pattern (default: '*USB Midi*')",
    )
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="Disable MIDI input (output only mode)",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Disable MIDI output (input only mode)",
    )

    args = parser.parse_args()

    print("🎹 Disklavier Interactive Test Interface")
    print("=" * 50)

    try:
        # Determine device patterns based on arguments
        input_pattern = None if args.no_input else args.input
        output_pattern = None if args.no_output else args.output

        # Initialize Disklavier with CLI arguments
        print("Initializing Disklavier...")
        print(f"Input pattern: {input_pattern if input_pattern else 'Disabled'}")
        print(f"Output pattern: {output_pattern if output_pattern else 'Disabled'}")
        print(f"Filter system messages: {not args.include_system}")

        disklavier = Disklavier(
            input_device_pattern=input_pattern,
            output_device_pattern=output_pattern,
            filter_system=not args.include_system,
        )

        input_status = "Connected" if disklavier.midi_in else "Disabled/Not found"
        output_status = "Connected" if disklavier.midi_out else "Disabled/Not found"
        print(f"✓ Input device: {input_status}")
        print(f"✓ Output device: {output_status}")

        # Set up callback to print MIDI messages if input is available
        if disklavier.midi_in:

            def midi_callback(message: List[int], delta_time: float):
                msg_type = disklavier.get_message_type_name(message)
                note_info = ""

                # Add note name for note messages
                if len(message) >= 3 and (message[0] & 0xF0) in [0x80, 0x90]:
                    note_name = get_note_name(message[1])
                    velocity = message[2]
                    note_info = f" | {note_name} vel={velocity}"
                elif len(message) >= 3 and (message[0] & 0xF0) == 0xB0:
                    value = message[2]
                    note_info = f" | value={value}"

                print(f"📥 {msg_type}: {message}{note_info} (Δt={delta_time:.3f}s)")

            disklavier.set_callback(midi_callback)

        print(f"\n🎵 MIDI Monitor Active")
        if disklavier.midi_in:
            if not args.include_system:
                print(
                    "🚫 System messages filtered out (use --include-system to see all)"
                )
            else:
                print("📡 All MIDI messages included (system timing messages visible)")
        else:
            print("📝 No input device - monitoring disabled")

        print("📝 Command Menu:")
        if disklavier.midi_out:
            print("  1 = Middle C Note On (vel=60)")
            print("  2 = Middle C Note Off")
            print("  3 = Sustain Pedal Down")
            print("  4 = Sustain Pedal Up")
            print("  5 = Soft Pedal Down")
            print("  6 = Soft Pedal Up")
        else:
            print("  No output device - sending disabled")
        print("  q = Quit")

        if disklavier.midi_in:
            print("\nListening for MIDI input and keyboard commands...")
        else:
            print("\nReady for keyboard commands...")

        # Main command loop
        while True:
            try:
                command = input("\nEnter command: ").strip().lower()

                if command == "q" or command == "quit":
                    break
                elif command == "1":
                    if disklavier.midi_out:
                        print("🎵 Sending Middle C Note On (vel=60)")
                        disklavier.send_note_on(60, 60)  # Middle C, velocity 60
                    else:
                        print("❌ No output device configured")
                elif command == "2":
                    if disklavier.midi_out:
                        print("🎵 Sending Middle C Note Off")
                        disklavier.send_note_off(60)  # Middle C
                    else:
                        print("❌ No output device configured")
                elif command == "3":
                    if disklavier.midi_out:
                        print("🎵 Sending Sustain Pedal Down")
                        disklavier.send_sustain_pedal(True)
                    else:
                        print("❌ No output device configured")
                elif command == "4":
                    if disklavier.midi_out:
                        print("🎵 Sending Sustain Pedal Up")
                        disklavier.send_sustain_pedal(False)
                    else:
                        print("❌ No output device configured")
                elif command == "5":
                    if disklavier.midi_out:
                        print("🎵 Sending Soft Pedal Down")
                        disklavier.send_soft_pedal(True)
                    else:
                        print("❌ No output device configured")
                elif command == "6":
                    if disklavier.midi_out:
                        print("🎵 Sending Soft Pedal Up")
                        disklavier.send_soft_pedal(False)
                    else:
                        print("❌ No output device configured")
                elif command == "":
                    continue  # Empty input, just continue
                else:
                    print(f"❌ Unknown command: {command}")

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    except Exception as e:
        print(f"❌ Failed to initialize Disklavier: {e}")
        return

    finally:
        print("\n🛑 Shutting down...")
        if "disklavier" in locals():
            disklavier.close()
        print("✓ Goodbye!")


def get_note_name(note_number: int) -> str:
    """Convert MIDI note number to note name."""
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = (note_number // 12) - 1
    note = note_names[note_number % 12]
    return f"{note}{octave}"


if __name__ == "__main__":
    main()
