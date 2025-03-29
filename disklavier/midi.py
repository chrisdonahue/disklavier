"""
Extended MIDI functionality for the disklavier library
Adds input handling capability to the existing MIDI functionality
"""

import mido
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MidiInterface:
    def __init__(self, input_name=None, output_name=None):
        """
        Initialize MIDI interface with optional input and output port names.

        Args:
            input_name: Name of the MIDI input port (None for default)
            output_name: Name of the MIDI output port (None for default)
        """
        self.input_port = None
        self.output_port = None

        # List available ports
        input_ports = mido.get_input_names()
        output_ports = mido.get_output_names()

        logger.info(f"Available MIDI input ports: {input_ports}")
        logger.info(f"Available MIDI output ports: {output_ports}")

        # Initialize input port
        if input_name is not None:
            if input_name in input_ports:
                self.input_port = mido.open_input(input_name)
                logger.info(f"Opened MIDI input port: {input_name}")
            else:
                logger.warning(
                    f"Requested input port '{input_name}' not found. Using default."
                )
                input_name = None

        if input_name is None and input_ports:
            self.input_port = mido.open_input(input_ports[0])
            logger.info(f"Opened default MIDI input port: {input_ports[0]}")

        # Initialize output port
        if output_name is not None:
            if output_name in output_ports:
                self.output_port = mido.open_output(output_name)
                logger.info(f"Opened MIDI output port: {output_name}")
            else:
                logger.warning(
                    f"Requested output port '{output_name}' not found. Using default."
                )
                output_name = None

        if output_name is None and output_ports:
            self.output_port = mido.open_output(output_ports[0])
            logger.info(f"Opened default MIDI output port: {output_ports[0]}")

    def send_message(self, msg):
        """
        Send a MIDI message to the output port.

        Args:
            msg: A mido.Message object
        """
        if self.output_port:
            self.output_port.send(msg)
            logger.debug(f"Sent MIDI message: {msg}")
        else:
            logger.error("No MIDI output port available")

    def receive_message(self, timeout=0):
        """
        Receive a MIDI message from the input port.

        Args:
            timeout: How long to wait for a message in seconds (0 = non-blocking)

        Returns:
            A mido.Message object or None if no message was received
        """
        if not self.input_port:
            logger.error("No MIDI input port available")
            return None

        if timeout == 0:
            # Non-blocking receive
            msg = self.input_port.receive(block=False)
        else:
            # For blocking with timeout, we need to implement our own timeout
            # since mido.Input.receive() doesn't support timeout parameter
            start_time = time.time()
            msg = None
            while time.time() - start_time < timeout:
                msg = self.input_port.receive(block=False)
                if msg:
                    break
                time.sleep(0.001)  # Small sleep to prevent CPU hogging

        if msg:
            logger.info(f"Received MIDI message: {msg}")
        return msg

    def receive_all_pending(self):
        """
        Receive all pending MIDI messages from the input port.

        Returns:
            List of mido.Message objects
        """
        messages = []
        while True:
            msg = self.receive_message(timeout=0)
            if msg is None:
                break
            messages.append(msg)
        return messages

    def callback_receive(self, callback_function):
        """
        Set a callback function for incoming MIDI messages.

        Args:
            callback_function: Function to call when a message is received
        """
        if not self.input_port:
            logger.error("No MIDI input port available")
            return

        # Set the callback
        self.input_port.callback = callback_function
        logger.info("MIDI input callback set")

    def close(self):
        """Close all MIDI ports"""
        if self.input_port:
            self.input_port.close()
            logger.info("Closed MIDI input port")

        if self.output_port:
            self.output_port.close()
            logger.info("Closed MIDI output port")


# Example usage for printing all incoming MIDI messages
if __name__ == "__main__":
    from . import DISKLAVIER_MIDI_IN_NAME, DISKLAVIER_MIDI_OUT_NAME

    def print_message(msg):
        print(f"Received: {msg}")

    midi = MidiInterface(
        input_name=DISKLAVIER_MIDI_IN_NAME,
        output_name=DISKLAVIER_MIDI_OUT_NAME,
    )

    try:
        print("Listening for MIDI messages. Press Ctrl+C to exit.")
        midi.callback_receive(print_message)

        # Keep the script running to receive messages
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        midi.close()
