"""
Network mode: bridge the piano to a network MIDI session.

This mode does not speak RTP-MIDI itself.  It publishes a pair of virtual ALSA
sequencer ports and relays between them and the Disklavier:

    Mac  ->  RTP-MIDI daemon  ->  "Disklavier Network" in   ->  piano
    piano ->  "Disklavier Network" out ->  RTP-MIDI daemon  ->  Mac

An AppleMIDI ("Network" in macOS Audio MIDI Setup) daemon does the protocol and
the Bonjour advertisement, and is connected to these ports with ``aconnect`` or
its own configuration.  That keeps the protocol implementation out of this
codebase and lets the daemon be swapped without touching any of it.

Why AppleMIDI rather than "UMP Network": UMP Network is MIDI 2.0 over the wire
and only exists on very recent macOS, with essentially no Linux implementations.
AppleMIDI/RTP-MIDI is the long-standing "Network" session, works with every
macOS version, and has several working Linux daemons.  This pipeline is
byte-oriented MIDI 1.0 throughout, so UMP would mean translating to 32-bit
packets for no benefit.

Note that the mode-switch keys are consumed by the controller and so are not
relayed: the top two keys of the piano do not reach the Mac.
"""

import os
import shlex
import signal
import subprocess
import threading
import time
from typing import Dict, List, Optional, Sequence, Union

import rtmidi

from ..base import Mode
from ... import alsa

DEFAULT_PORT_NAME = "Disklavier Network"


class VirtualMidiPort:
    """
    A virtual ALSA sequencer port pair that other MIDI software can connect to.

    Publishing our own ports rather than connecting to the daemon's means the
    mode starts cleanly whether or not the daemon is running yet, and the
    connection survives the daemon restarting.

    These are opened once per process and kept, never torn down between mode
    activations: ALSA keeps a virtual port's client alive for the lifetime of
    the process no matter what rtmidi is told, so re-opening on every activation
    would pile up duplicates of the same name.  Leaving them up is also what you
    want in practice -- the daemon's connection and the Mac's session survive
    switching to another mode and back.
    """

    def __init__(self, name: str = DEFAULT_PORT_NAME):
        self.name = name
        self.midi_in: Optional[rtmidi.MidiIn] = None
        self.midi_out: Optional[rtmidi.MidiOut] = None

    def open(self) -> None:
        self.midi_in = rtmidi.MidiIn()
        self.midi_in.open_virtual_port(self.name)
        # Relay whatever the Mac sends, including messages this codebase
        # otherwise filters, since the far end decides what is meaningful
        self.midi_in.ignore_types(sysex=False, timing=True, active_sense=True)

        self.midi_out = rtmidi.MidiOut()
        self.midi_out.open_virtual_port(self.name)

    def set_callback(self, callback) -> None:
        if self.midi_in is not None:
            self.midi_in.set_callback(callback)

    def send_message(self, message: List[int]) -> None:
        if self.midi_out is not None:
            self.midi_out.send_message(message)

    def cancel_callback(self) -> None:
        """Stop delivering incoming messages, leaving the ports published."""
        if self.midi_in is not None:
            try:
                self.midi_in.cancel_callback()
            except Exception:
                pass


# Virtual ports are process-wide and outlive any one activation of the mode
_PORTS: Dict[str, VirtualMidiPort] = {}
_PORTS_LOCK = threading.Lock()


def get_port(name: str) -> VirtualMidiPort:
    """Return the process's virtual port pair for ``name``, opening it once."""
    with _PORTS_LOCK:
        port = _PORTS.get(name)
        if port is None:
            port = VirtualMidiPort(name)
            port.open()
            _PORTS[name] = port
        return port


class NetworkMode(Mode):
    """
    Relay MIDI both ways between the piano and a network MIDI session.

    Requires an RTP-MIDI daemon running separately and connected to this mode's
    virtual ports; see the module docstring and the README.
    """

    name = "network"
    description = "Bridge the piano to a network MIDI session (RTP-MIDI)"

    def __init__(
        self,
        disklavier,
        port_name: str = DEFAULT_PORT_NAME,
        direct: bool = True,
        piano_port_pattern: str = "*USB Midi*",
        daemon_command: Optional[Union[str, Sequence[str]]] = None,
        daemon_port_pattern: str = "rtpmidi*",
        daemon_ready_timeout: float = 10.0,
        autoconnect: bool = True,
        to_piano: bool = True,
        from_piano: bool = True,
        verbose: bool = False,
    ):
        """
        Args:
            disklavier: Live Disklavier interface
            port_name: Name of the virtual ALSA ports to publish (relay mode)
            direct: Wire the piano's own ALSA port straight to the daemon.
                One network session, and MIDI never passes through Python, so
                this adds no latency.  Set False to relay through virtual ports
                instead, which lets the mode see and filter the traffic at the
                cost of two sessions on the Mac and a Python hop.
            piano_port_pattern: ALSA port of the piano, used by direct mode
            daemon_command: RTP-MIDI daemon to run for the life of this mode,
                as a string or argv list. None to manage the daemon yourself.
            daemon_port_pattern: Wildcard matching the ALSA port the daemon
                publishes, used to wire it to ours
            daemon_ready_timeout: Seconds to wait for that port to appear
            autoconnect: Wire the daemon's ALSA port to ours automatically
            to_piano: Play what arrives from the network on the piano
            from_piano: Send what is played on the piano out to the network
            verbose: Log every relayed message (noisy; for debugging)
        """
        super().__init__(disklavier)
        self.port_name = port_name
        self.direct = direct
        self.piano_port_pattern = piano_port_pattern
        self.to_piano = to_piano
        self.from_piano = from_piano
        self.verbose = verbose

        self.daemon_command = daemon_command
        self.daemon_port_pattern = daemon_port_pattern
        self.daemon_ready_timeout = daemon_ready_timeout
        self.autoconnect = autoconnect

        self.port: Optional[VirtualMidiPort] = None
        self._daemon: Optional[subprocess.Popen] = None
        self._connections: List[tuple] = []
        self._relaying = False
        self._from_network = 0
        self._to_network = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.direct:
            print("🌐 Direct mode: wiring the piano's ALSA port to the network")
            print("   MIDI does not pass through Python, so this adds no latency")
        else:
            try:
                self.port = get_port(self.port_name)
            except Exception as e:
                print(f"❌ Could not publish virtual MIDI ports: {e}")
                return

            self.port.set_callback(self._on_network_message)
            self._relaying = True

            print(f"🌐 Relay mode: virtual ALSA ports named '{self.port_name}'")
            print(f"   piano -> network: {'on' if self.from_piano else 'off'}")
            print(f"   network -> piano: {'on' if self.to_piano else 'off'}")
            if self.disklavier.midi_out is None and self.to_piano:
                print("⚠️  No MIDI output device: nothing from the network can play")

        if self.daemon_command:
            self._start_daemon()
        if self.autoconnect:
            self._wire_daemon()
        else:
            print("   Connect an RTP-MIDI daemon to these ports yourself.")

        print("   Open Audio MIDI Setup > Network on the Mac and connect.")

    def _start_daemon(self) -> None:
        """Run the RTP-MIDI daemon for as long as this mode is active."""
        command = self.daemon_command
        argv = shlex.split(command) if isinstance(command, str) else list(command)

        try:
            # Own process group, so a daemon that forks children can be stopped
            # as a unit rather than leaving orphans holding the UDP port
            self._daemon = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            print(f"❌ RTP-MIDI daemon not found: {argv[0]}")
            print("   Install it, or set daemon_command to null in the config")
            self._daemon = None
            return
        except Exception as e:
            print(f"❌ Could not start RTP-MIDI daemon: {e}")
            self._daemon = None
            return

        print(f"🚀 Started daemon: {' '.join(argv)} (pid {self._daemon.pid})")

    def _wire_daemon(self) -> None:
        """
        Connect the daemon's ALSA ports to ours, both directions.

        A subscription runs source -> destination, and the two halves of a
        virtual port pair share a name, so each end has to be looked up in the
        right direction: "-i" lists ports that can be read from, "-o" ports that
        can be written to.  Matching by name alone picks the wrong half and
        ALSA rejects the connection with "Operation not permitted".
        """
        # In direct mode the piano's own port is both ends; the hardware port
        # is bidirectional, so a single session carries both directions
        local = self.piano_port_pattern if self.direct else self.port_name
        ours_source = alsa.find_port(local, "-i")
        ours_dest = alsa.find_port(local, "-o")
        if ours_source is None or ours_dest is None:
            print(f"⚠️  Could not find local ALSA port matching '{local}'")
            return

        if self._await_daemon_port() is None:
            print(
                f"⚠️  No ALSA port matching '{self.daemon_port_pattern}' after "
                f"{self.daemon_ready_timeout:.0f}s -- is the daemon running?"
            )
            return

        theirs_source = alsa.find_port(self.daemon_port_pattern, "-i")
        theirs_dest = alsa.find_port(self.daemon_port_pattern, "-o")

        wired = []
        # network -> piano, then piano -> network
        for label, source, dest in (
            ("network -> piano", theirs_source, ours_dest),
            ("piano -> network", ours_source, theirs_dest),
        ):
            if source is None or dest is None:
                print(f"⚠️  Daemon has no port for {label}; skipping")
                continue
            if alsa.connect(source.address, dest.address):
                self._connections.append((source.address, dest.address))
                wired.append(f"{label} ({source.address}->{dest.address})")
            else:
                print(f"⚠️  aconnect {source.address} -> {dest.address} failed")

        if wired:
            print(f"🔌 Wired {', '.join(wired)}")

    def _await_daemon_port(self) -> Optional[alsa.AlsaPort]:
        """Poll for the daemon's ALSA port, which appears a moment after launch."""
        deadline = time.monotonic() + self.daemon_ready_timeout
        while True:
            found = alsa.find_port(self.daemon_port_pattern)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                return None
            if self._daemon is not None and self._daemon.poll() is not None:
                print(
                    f"❌ Daemon exited immediately (code {self._daemon.returncode})"
                )
                return None
            time.sleep(0.2)

    def _stop_daemon(self) -> None:
        """Stop the daemon we started, escalating if it ignores SIGTERM."""
        if self._daemon is None:
            return

        pid = self._daemon.pid
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            self._daemon = None
            return
        except Exception:
            self._daemon.terminate()

        try:
            self._daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"⚠️  Daemon {pid} ignored SIGTERM, killing it")
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                self._daemon.kill()
            try:
                self._daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"❌ Daemon {pid} would not die")

        print(f"🛑 Stopped daemon (pid {pid})")
        self._daemon = None

    def _on_network_message(self, event, _data=None) -> None:
        """Mac -> piano. Runs on the virtual port's callback thread."""
        message, _delta = event
        if not self._relaying or not self.to_piano:
            return
        if self.disklavier.midi_out is None:
            return

        try:
            self.disklavier.send_message(list(message))
        except Exception as e:
            print(f"❌ Could not play network message {list(message)}: {e}")
            return

        with self._lock:
            self._from_network += 1
        if self.verbose:
            print(f"🌐→🎹 {[f'{b:02X}' for b in message]}")

    def handle_midi(self, midi_bytes: List[int], delta_time: float) -> None:
        """piano -> Mac."""
        if not self._relaying or not self.from_piano or self.port is None:
            return

        try:
            self.port.send_message(list(midi_bytes))
        except Exception as e:
            print(f"❌ Could not relay {midi_bytes} to the network: {e}")
            return

        with self._lock:
            self._to_network += 1
        if self.verbose:
            print(f"🎹→🌐 {[f'{b:02X}' for b in midi_bytes]}")

    def stop(self) -> None:
        # Stop relaying but leave the ports published, so the daemon and the
        # Mac keep their session across a mode switch
        self._relaying = False
        if self.port is not None:
            self.port.cancel_callback()

        for source, dest in self._connections:
            alsa.disconnect(source, dest)
        self._connections = []

        self._stop_daemon()

        print(
            f"🌐 Network bridge idle "
            f"({self._to_network} sent, {self._from_network} received)"
        )
