"""
Modes of operation for the Disklavier.

Each mode lives in its own subpackage and is registered here under the name
used by the ``modes`` block of the configuration file.
"""

from typing import Dict, Type

from .base import Mode
from .delay import DelayMode
from .looper import LooperMode
from .network import NetworkMode
from .surveil import SurveilMode
from .test import TestMode

MODES: Dict[str, Type[Mode]] = {
    SurveilMode.name: SurveilMode,
    NetworkMode.name: NetworkMode,
    TestMode.name: TestMode,
    DelayMode.name: DelayMode,
    LooperMode.name: LooperMode,
}

__all__ = [
    "Mode",
    "MODES",
    "DelayMode",
    "LooperMode",
    "NetworkMode",
    "SurveilMode",
    "TestMode",
    "get_mode_class",
]


def get_mode_class(name: str) -> Type[Mode]:
    """Look up a mode class by its registered name."""
    try:
        return MODES[name]
    except KeyError:
        known = ", ".join(sorted(MODES))
        raise KeyError(f"Unknown mode '{name}'. Available modes: {known}") from None
