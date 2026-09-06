"""
ALSA sequencer helpers.

Thin wrappers over ``aconnect``, used to find the ports a MIDI daemon publishes
and wire them to ours.  Shelling out rather than binding libasound keeps this
dependency-free, and these calls happen only on mode switches, never per
message.
"""

import fnmatch
import re
import subprocess
from typing import List, NamedTuple, Optional

# "client 24: 'USB Midi' [type=kernel,card=2]"
_CLIENT_RE = re.compile(r"^client (\d+): '([^']*)'")
# "    0 'USB Midi MIDI 1 '"
_PORT_RE = re.compile(r"^\s+(\d+) '([^']*)'")


class AlsaPort(NamedTuple):
    """One ALSA sequencer port."""

    client_id: int
    client_name: str
    port_id: int
    port_name: str

    @property
    def address(self) -> str:
        """The ``client:port`` form that aconnect takes."""
        return f"{self.client_id}:{self.port_id}"


def list_ports(list_arg: str = "-l") -> List[AlsaPort]:
    """
    Every ALSA sequencer port on the system.

    Args:
        list_arg: "-i" for inputs (readable), "-o" for outputs (writable),
            "-l" for all.
    """
    try:
        out = subprocess.run(
            ["aconnect", list_arg], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    ports: List[AlsaPort] = []
    client_id, client_name = None, ""
    for line in out.splitlines():
        client = _CLIENT_RE.match(line)
        if client:
            client_id, client_name = int(client.group(1)), client.group(2).strip()
            continue
        port = _PORT_RE.match(line)
        if port and client_id is not None:
            ports.append(
                AlsaPort(client_id, client_name, int(port.group(1)), port.group(2).strip())
            )
    return ports


def find_port(pattern: str, list_arg: str = "-l") -> Optional[AlsaPort]:
    """
    First port whose client or port name matches a wildcard pattern.

    Matching is case-insensitive and checks both names, so "rtpmidid*" finds the
    daemon whether it names the client or the port.
    """
    lowered = pattern.lower()
    for port in list_ports(list_arg):
        if fnmatch.fnmatch(port.client_name.lower(), lowered) or fnmatch.fnmatch(
            port.port_name.lower(), lowered
        ):
            return port
    return None


def connect(source: str, dest: str) -> bool:
    """Subscribe ``dest`` to ``source``. True if connected or already were."""
    return _aconnect([source, dest])


def disconnect(source: str, dest: str) -> bool:
    """Undo a connection. True if removed or already absent."""
    return _aconnect(["-d", source, dest])


def _aconnect(args: List[str]) -> bool:
    try:
        result = subprocess.run(
            ["aconnect"] + args, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode == 0:
        return True
    # aconnect fails when a subscription already exists or is already gone,
    # which is the state we wanted either way
    noise = (result.stderr or "").lower()
    return "exists" in noise or "no such" in noise
