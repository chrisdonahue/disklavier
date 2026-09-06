"""
Configuration loading for the Disklavier master controller.

The config file is JSON and lives at ``~/.config/disklavier/config.json`` by
default (override the directory with ``DISKLAVIER_CONFIG_DIR``).  It maps mode
numbers -- the numbers you dial in on the keyboard -- to mode implementations
and their options.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import CONFIG_PATH

DEFAULT_CONFIG: Dict[str, Any] = {
    "input_device_pattern": "*USB Midi*",
    "output_device_pattern": "*USB Midi*",
    # Return to mode 0 after this many seconds without a key press (0 disables).
    "idle_reset_seconds": 3600.0,
    "mode_switch": {
        # Top C (C8) opens and closes the mode-switch gesture.
        "select_note": 108,
        # Top B (B7) is repeated to count out the mode number.
        "count_note": 107,
        # Abandon a half-finished gesture after this many seconds.
        "gesture_timeout": 5.0,
    },
    "modes": {
        "0": {"mode": "surveil", "options": {"silence_timeout": 10.0}},
        "1": {"mode": "test", "options": {"velocity": 60}},
    },
}


class ConfigError(Exception):
    """Raised when the configuration file is malformed."""


def write_default_config(path: Path = CONFIG_PATH) -> Path:
    """Write the default configuration to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return path


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration, creating the default file if it does not exist.

    Top-level keys missing from the file fall back to the defaults, so a config
    only needs to spell out what it changes.
    """
    path = Path(path) if path is not None else CONFIG_PATH

    if not path.exists():
        write_default_config(path)
        print(f"📝 Wrote default configuration to {path}")

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"Could not parse config file {path}: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object")

    config = dict(DEFAULT_CONFIG)
    config.update(raw)

    # Nested defaults for the switch gesture so a partial block still works.
    mode_switch = dict(DEFAULT_CONFIG["mode_switch"])
    mode_switch.update(config.get("mode_switch") or {})
    config["mode_switch"] = mode_switch

    config["modes"] = parse_modes(config.get("modes"), path)
    config["path"] = path
    return config


def parse_modes(modes: Any, path: Path = CONFIG_PATH) -> Dict[int, Dict[str, Any]]:
    """
    Normalize the ``modes`` block into ``{index: {"mode": name, "options": {...}}}``.

    JSON object keys are always strings, so mode numbers are converted here.
    """
    if not isinstance(modes, dict):
        raise ConfigError(f"'modes' in {path} must be a JSON object")

    parsed: Dict[int, Dict[str, Any]] = {}
    for key, spec in modes.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise ConfigError(f"Mode key {key!r} in {path} is not a number")
        if index < 0:
            raise ConfigError(f"Mode number {index} in {path} must be non-negative")

        if isinstance(spec, str):
            spec = {"mode": spec, "options": {}}
        if not isinstance(spec, dict) or "mode" not in spec:
            raise ConfigError(
                f"Mode {index} in {path} must be a mode name or an object with a 'mode' key"
            )

        options = spec.get("options") or {}
        if not isinstance(options, dict):
            raise ConfigError(f"'options' for mode {index} in {path} must be an object")

        parsed[index] = {"mode": str(spec["mode"]), "options": dict(options)}

    if not parsed:
        raise ConfigError(f"No modes configured in {path}")

    return parsed
