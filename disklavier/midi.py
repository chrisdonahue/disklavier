import rtmidi
import fnmatch
from typing import Optional, List
import argparse
import time
import threading
import sys


class MidiDeviceError(Exception):
    """Exception raised when MIDI device cannot be found or is not exclusive."""

    pass


class MidiInterface:
    """
    MIDI Interface class for handling real-time MIDI I/O.

    This class provides a high-level interface for MIDI input and output
    using python-rtmidi for low-latency real-time performance.
    """

    def __init__(
        self,
        input_device_pattern: Optional[str] = None,
        output_device_pattern: Optional[str] = None,
    ):
        """
        Initialize MIDI interface with optional device patterns.

        Args:
            input_device_pattern: Wildcard pattern to match input device name
            output_device_pattern: Wildcard pattern to match output device name

        Raises:
            MidiDeviceError: If devices cannot be exclusively found
        """
        self.midi_in = None
        self.midi_out = None
        self.input_port = None
        self.output_port = None

        # Initialize MIDI input if pattern provided
        if input_device_pattern:
            self.midi_in = rtmidi.MidiIn()
            self.input_port = self._find_exclusive_port(
                self.midi_in, input_device_pattern, "input"
            )
            self.midi_in.open_port(self.input_port)

        # Initialize MIDI output if pattern provided
        if output_device_pattern:
            self.midi_out = rtmidi.MidiOut()
            self.output_port = self._find_exclusive_port(
                self.midi_out, output_device_pattern, "output"
            )
            self.midi_out.open_port(self.output_port)

    def _find_exclusive_port(self, midi_interface, pattern: str, port_type: str) -> int:
        """
        Find a single port that exclusively matches the given pattern.

        Args:
            midi_interface: RtMidi input or output interface
            pattern: Wildcard pattern to match against port names
            port_type: "input" or "output" for error messages

        Returns:
            Port index of the exclusively matched device

        Raises:
            MidiDeviceError: If no ports or multiple ports match the pattern
        """
        available_ports = midi_interface.get_ports()

        if not available_ports:
            raise MidiDeviceError(f"No MIDI {port_type} devices available")

        # Find matching ports
        matching_ports = []
        for i, port_name in enumerate(available_ports):
            if fnmatch.fnmatch(port_name.lower(), pattern.lower()):
                matching_ports.append((i, port_name))

        if len(matching_ports) == 0:
            raise MidiDeviceError(
                f"No MIDI {port_type} device found matching pattern '{pattern}'. "
                f"Available devices: {available_ports}"
            )
        elif len(matching_ports) > 1:
            matching_names = [name for _, name in matching_ports]
            raise MidiDeviceError(
                f"Multiple MIDI {port_type} devices match pattern '{pattern}': {matching_names}. "
                f"Pattern must match exactly one device."
            )

        port_index, port_name = matching_ports[0]
        print(f"Connected to MIDI {port_type} device: {port_name}")
        return port_index

    def send_message(self, message: List[int]) -> None:
        """
        Send a MIDI message to the output device.

        Args:
            message: List of MIDI bytes to send

        Raises:
            RuntimeError: If no output device is configured
        """
        if not self.midi_out:
            raise RuntimeError("No MIDI output device configured")

        self.midi_out.send_message(message)

    def set_callback(self, callback_function) -> None:
        """
        Set a callback function for incoming MIDI messages.

        Args:
            callback_function: Function to call when MIDI input is received.
                             Should accept (message, delta_time) parameters.

        Raises:
            RuntimeError: If no input device is configured
        """
        if not self.midi_in:
            raise RuntimeError("No MIDI input device configured")

        self.midi_in.set_callback(callback_function)

    def get_message(self):
        """
        Poll for incoming MIDI messages (non-blocking).

        Returns:
            Tuple of (message, delta_time) or None if no message available

        Raises:
            RuntimeError: If no input device is configured
        """
        if not self.midi_in:
            raise RuntimeError("No MIDI input device configured")

        return self.midi_in.get_message()

    def close(self):
        """Close MIDI connections and clean up resources."""
        if self.midi_in:
            # Cancel before closing. Closing a port while a callback is in
            # flight deadlocks in rtmidi, and with MIDI clock streaming at
            # ~50 messages a second one almost always is.
            try:
                self.midi_in.cancel_callback()
            except Exception:
                pass
            self.midi_in.close_port()
            del self.midi_in
            self.midi_in = None

        if self.midi_out:
            self.midi_out.close_port()
            del self.midi_out
            self.midi_out = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()

    @staticmethod
    def list_input_devices() -> List[str]:
        """
        List all available MIDI input devices.

        Returns:
            List of available MIDI input device names
        """
        midi_in = rtmidi.MidiIn()
        ports = midi_in.get_ports()
        del midi_in
        return ports

    @staticmethod
    def list_output_devices() -> List[str]:
        """
        List all available MIDI output devices.

        Returns:
            List of available MIDI output device names
        """
        midi_out = rtmidi.MidiOut()
        ports = midi_out.get_ports()
        del midi_out
        return ports


def main():
    """Main function for command line usage."""
    parser = argparse.ArgumentParser(description="MIDI Interface Testing Tool")
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        help='Input device wildcard pattern (e.g., "*piano*")',
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help='Output device wildcard pattern (e.g., "*synth*")',
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all available MIDI devices and exit",
    )
    parser.add_argument(
        "--test-notes", action="store_true", help="Send test notes to output device"
    )

    args = parser.parse_args()

    # If no arguments provided, run interactive mode
    if len(sys.argv) == 1:
        return interactive_mode()

    # List devices and exit if requested
    if args.list_devices:
        print("Available MIDI Input Devices:")
        for i, device in enumerate(MidiInterface.list_input_devices()):
            print(f"  {i}: {device}")

        print("\nAvailable MIDI Output Devices:")
        for i, device in enumerate(MidiInterface.list_output_devices()):
            print(f"  {i}: {device}")
        return

    # Create MIDI interface
    try:
        print("Initializing MIDI interface...")
        midi = MidiInterface(
            input_device_pattern=args.input, output_device_pattern=args.output
        )
    except MidiDeviceError as e:
        print(f"Error: {e}")
        return
    except Exception as e:
        print(f"Unexpected error: {e}")
        return

    # Set up input callback if input device is configured
    if midi.midi_in:

        def midi_callback(message, delta_time):
            print(f"MIDI In: {message} (Δt: {delta_time:.3f}s)")

        midi.set_callback(midi_callback)
        print("MIDI input callback set up. Listening for messages...")

    # Send test notes if requested and output device is available
    if args.test_notes and midi.midi_out:
        print("Sending test notes...")
        test_notes = [60, 64, 67, 72]  # C, E, G, C (C major chord)

        for note in test_notes:
            # Note on
            midi.send_message([0x90, note, 100])  # Channel 1, velocity 100
            print(f"Note on: {note}")
            time.sleep(0.5)

            # Note off
            midi.send_message([0x80, note, 0])
            print(f"Note off: {note}")
            time.sleep(0.2)

    # Keep running to listen for MIDI input
    if midi.midi_in:
        print("\nListening for MIDI input. Press Ctrl+C to exit...")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nExiting...")
    elif not args.test_notes:
        print("No input device configured and no test requested. Nothing to do.")

    # Clean up
    midi.close()
    print("MIDI interface closed.")


def interactive_mode():
    """Interactive mode for device selection."""
    print("MIDI Interface - Interactive Mode")
    print("=" * 40)

    # Get available devices
    input_devices = MidiInterface.list_input_devices()
    output_devices = MidiInterface.list_output_devices()

    # Display input devices
    print("\nAvailable MIDI Input Devices:")
    if not input_devices:
        print("  No input devices available")
    else:
        for i, device in enumerate(input_devices):
            print(f"  {i}: {device}")

    # Display output devices
    print("\nAvailable MIDI Output Devices:")
    if not output_devices:
        print("  No output devices available")
    else:
        for i, device in enumerate(output_devices):
            print(f"  {i}: {device}")

    # Get user input for input device
    input_pattern = None
    if input_devices:
        print("\nSelect MIDI Input Device:")
        print("  Enter device number, wildcard pattern, or press Enter to skip")
        choice = input("Input device: ").strip()

        if choice:
            if choice.isdigit() and 0 <= int(choice) < len(input_devices):
                # User selected by number - create exact match pattern
                selected_device = input_devices[int(choice)]
                input_pattern = selected_device
                print(f"Selected input: {selected_device}")
            else:
                # User entered a pattern
                input_pattern = choice
                print(f"Using input pattern: {choice}")

    # Get user input for output device
    output_pattern = None
    if output_devices:
        print("\nSelect MIDI Output Device:")
        print("  Enter device number, wildcard pattern, or press Enter to skip")
        choice = input("Output device: ").strip()

        if choice:
            if choice.isdigit() and 0 <= int(choice) < len(output_devices):
                # User selected by number - create exact match pattern
                selected_device = output_devices[int(choice)]
                output_pattern = selected_device
                print(f"Selected output: {selected_device}")
            else:
                # User entered a pattern
                output_pattern = choice
                print(f"Using output pattern: {choice}")

    # Ask about test notes
    test_notes = False
    if output_pattern:
        choice = input("\nSend test notes? (y/n): ").strip().lower()
        test_notes = choice in ["y", "yes"]

    # Create MIDI interface
    try:
        print("\nInitializing MIDI interface...")
        midi = MidiInterface(
            input_device_pattern=input_pattern, output_device_pattern=output_pattern
        )
    except MidiDeviceError as e:
        print(f"Error: {e}")
        return
    except Exception as e:
        print(f"Unexpected error: {e}")
        return

    # Set up input callback if input device is configured
    if midi.midi_in:

        def midi_callback(message, delta_time):
            print(f"MIDI In: {message} (Δt: {delta_time:.3f}s)")

        midi.set_callback(midi_callback)
        print("MIDI input callback set up. Listening for messages...")

    # Send test notes if requested
    if test_notes and midi.midi_out:
        print("Sending test notes...")
        test_notes_list = [60, 64, 67, 72]  # C, E, G, C (C major chord)

        for note in test_notes_list:
            # Note on
            midi.send_message([0x90, note, 100])  # Channel 1, velocity 100
            print(f"Note on: {note}")
            time.sleep(0.5)

            # Note off
            midi.send_message([0x80, note, 0])
            print(f"Note off: {note}")
            time.sleep(0.2)

    # Keep running to listen for MIDI input
    if midi.midi_in:
        print("\nListening for MIDI input. Press Ctrl+C to exit...")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nExiting...")
    elif not test_notes:
        print("No input device configured and no test requested. Nothing to do.")

    # Clean up
    midi.close()
    print("MIDI interface closed.")


if __name__ == "__main__":
    main()
