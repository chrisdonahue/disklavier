#!/usr/bin/env python3
"""
Disklavier master controller entry point.

Sets up the hardware once, then runs whichever mode is selected.  Modes are
numbered in the configuration file and switched from the keyboard itself.
"""

import argparse
import sys
import threading
from pathlib import Path

from .config import ConfigError, load_config
from .controller import Controller
from .disklavier import Disklavier
from .midi import MidiInterface
from .modes import MODES


def list_devices() -> None:
    """Print every MIDI device the system can see."""
    print("🎹 Available MIDI Input Devices:")
    for i, device in enumerate(MidiInterface.list_input_devices()):
        print(f"  {i}: {device}")

    print("\n🔊 Available MIDI Output Devices:")
    for i, device in enumerate(MidiInterface.list_output_devices()):
        print(f"  {i}: {device}")


def list_modes() -> None:
    """Print every mode implementation available for use in the config file."""
    print("🎛️  Available mode implementations:")
    for name in sorted(MODES):
        description = MODES[name].description or ""
        print(f"  {name}: {description}")


CONSOLE_HELP = """⌨️  Console commands:
  <number>  switch to that mode
  l         list configured modes
  q         quit
  ?         show this help"""


def start_console(controller: Controller) -> None:
    """
    Read mode-switch commands from stdin on a background thread.

    The same switch queue the keyboard gesture feeds, so console and piano
    cannot fight over the active mode.  Useful over ssh or in the service's
    tmux pane, where you are not sitting at the instrument.
    """

    def console():
        while True:
            try:
                line = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return  # stdin closed; the piano still drives the controller

            if not line:
                continue

            if line in ("q", "quit", "exit"):
                print("🛑 Quitting...")
                controller.shutdown()
                return

            if line in ("l", "list", "modes"):
                print("🎛️  Configured modes:")
                print(controller.describe_modes())
                print(f"   active: mode {controller.active_index}")
                continue

            if line in ("?", "h", "help"):
                print(CONSOLE_HELP)
                continue

            try:
                index = int(line)
            except ValueError:
                print(f"❌ Unknown command: {line!r}. Type '?' for help.")
                continue

            controller.request_mode(index)

    threading.Thread(target=console, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(
        description="Disklavier master controller - runs numbered modes of operation"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="Path to the configuration file (default: ~/.config/disklavier/config.json)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=int,
        default=None,
        help="Mode number to start in (default: the configured default mode)",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        default=None,
        help="Input device pattern, overriding the config file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output device pattern, overriding the config file",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include system timing messages (default is to filter them out)",
    )
    parser.add_argument(
        "--no-console",
        action="store_true",
        help="Do not read mode-switch commands from stdin",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available MIDI devices and exit",
    )
    parser.add_argument(
        "--list-modes",
        action="store_true",
        help="List available mode implementations and exit",
    )

    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    if args.list_modes:
        list_modes()
        return

    print("🎹 Disklavier Master Controller")
    print("=" * 50)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"⚙️  Config: {config['path']}")

    input_pattern = args.input or config["input_device_pattern"]
    output_pattern = args.output or config["output_device_pattern"]
    mode_switch = config["mode_switch"]

    controller = None
    try:
        print(f"   Input device pattern: {input_pattern}")
        print(f"   Output device pattern: {output_pattern}")

        disklavier = Disklavier(
            input_device_pattern=input_pattern,
            output_device_pattern=output_pattern,
            filter_system=not args.include_system,
        )

        if disklavier.midi_in is None:
            raise RuntimeError("No MIDI input device found. Cannot switch modes.")

        controller = Controller(
            disklavier,
            mode_specs=config["modes"],
            default_mode=0,
            idle_reset_seconds=float(config["idle_reset_seconds"]),
            select_note=int(mode_switch["select_note"]),
            count_note=int(mode_switch["count_note"]),
            gesture_timeout=float(mode_switch["gesture_timeout"]),
        )

        if not args.no_console and sys.stdin is not None and sys.stdin.isatty():
            print(CONSOLE_HELP)
            start_console(controller)

        controller.run(start_mode=args.mode)
    except Exception as e:
        print(f"❌ Failed to start Disklavier controller: {e}")
        if controller is not None:
            controller.close()
        sys.exit(1)

    print("✓ Shutdown complete")


if __name__ == "__main__":
    main()
