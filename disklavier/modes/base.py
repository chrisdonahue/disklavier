"""Base class every Disklavier mode implements."""

from typing import List


class Mode:
    """
    A mode of operation for the Disklavier.

    The master controller owns the hardware connection and hands it to the mode,
    so a mode never opens MIDI ports itself.  The controller calls ``start()``
    when the mode is activated, feeds it MIDI via ``handle_midi()``, and calls
    ``stop()`` before switching away.  Modes are constructed fresh on every
    activation, so ``__init__`` should not assume any prior state.

    Note that the mode-switch keys (top C and top B) never reach
    ``handle_midi()``; they are consumed by the controller.

    ``self.disklavier.tempo`` gives the tempo in BPM from the instrument's MIDI
    clock, which the panel's tempo dial drives -- a free continuous control
    knob.  It reads None when the instrument sends no clock (metronome off, or
    disk mode), so always handle that case; see ``disklavier.tempo`` for detail.
    """

    name = "mode"
    description = ""

    def __init__(self, disklavier):
        """
        Args:
            disklavier: Live Disklavier interface, shared with the controller.
        """
        self.disklavier = disklavier

    def start(self) -> None:
        """Called when this mode becomes active."""

    def handle_midi(self, midi_bytes: List[int], delta_time: float) -> None:
        """
        Called for each incoming MIDI message while this mode is active.

        Runs on the rtmidi callback thread, so it should return promptly.
        """

    def on_transport_start(self) -> None:
        """
        Called when the panel's play button is pressed (MIDI Start).

        Only ever fires in metronome mode -- see ``disklavier.tempo``.  Runs on
        the controller's run thread, so it may block briefly.
        """

    def on_transport_stop(self) -> None:
        """
        Called when the panel's stop button is pressed (MIDI Stop).

        Reports a state transition, not a press: pressing stop when already
        stopped sends nothing, so this will not fire twice in a row.
        """

    def stop(self) -> None:
        """
        Called when this mode is deactivated.

        Should stop any threads the mode started.  The controller releases every
        key immediately afterwards, so a mode does not need to chase down notes
        it left sounding.
        """
