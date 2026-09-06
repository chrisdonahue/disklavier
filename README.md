# Disklavier Recording System

A Python package for interfacing with Yamaha Disklavier MIDI systems, featuring a high-precision recording daemon that automatically captures and saves MIDI performances.

## Features

- **High-precision MIDI recording** with microsecond timing accuracy
- **Automatic silence detection** - starts recording when MIDI input is received, stops after configurable silence period
- **Smart filtering** - focuses on musical events (notes, pedals) while filtering out system timing messages
- **Automatic file saving** with descriptive filenames including timestamp, duration, and note count
- **Real-time monitoring** with live feedback of incoming MIDI events
- **Practice statistics** - analyze practice sessions with detailed activity reports
- **Modes of operation** - numbered modes selected from the keyboard itself

## Installation

```bash
pip install -e .
```

## Modes of Operation

`disklavier` is the master controller. It opens the hardware once, then runs a
single *mode* at a time. Modes live in `disklavier/modes/` and are numbered by
the configuration file.

```bash
# Run the controller (starts in mode 0)
disklavier

# Start in a specific mode
disklavier -m 1

# See which mode implementations exist
disklavier --list-modes
```

Built-in modes:

| # | Mode | What it does |
|---|---------|--------------|
| 0 | `surveil` | Records everything played, saving a take after each silence |
| 1 | `test` | Plays every note on the piano at velocity 60 |

### Network MIDI (mode 2)

Mode 2 bridges the piano to a network MIDI session so a Mac can play it and
record from it. It publishes a pair of virtual ALSA sequencer ports named
`Disklavier Network`:

```
Mac  ->  RTP-MIDI daemon  ->  Disklavier Network  ->  piano
piano ->  Disklavier Network  ->  RTP-MIDI daemon  ->  Mac
```

The mode does not speak RTP-MIDI itself. A separate daemon handles the protocol
and the Bonjour advertisement, and is connected to these ports with `aconnect`.
That keeps protocol code out of this repo and lets the daemon be swapped freely.

Use the **"Network"** session in macOS Audio MIDI Setup, not "UMP Network".
"Network" is AppleMIDI/RTP-MIDI, works on every macOS version, and has several
Linux daemons. "UMP Network" is MIDI 2.0 over the wire, exists only on very
recent macOS, and has essentially no Linux support — and this pipeline is
byte-oriented MIDI 1.0 throughout, so it would gain nothing.

Daemon options, none of which are packaged for Raspberry Pi OS by default:

| Daemon | Cost | Notes |
|---|---|---|
| [McLaren Labs rtpmidi](https://mclarenlabs.com/) | $5 | Full journal recovery; runs headless as a service |
| [MMKServer](https://mclarenlabs.com/) | free | Same vendor, systemd service, web console |
| [rtpmidid](https://github.com/davidmoreno/rtpmidid) | free | Prebuilt .debs, but self-described alpha and **no journal** |

Journal recovery matters on WiFi: without it a dropped packet can leave a note
stuck on, since the note-off never arrives.

**Setup used here** — `rtpmidid` installed from its Debian package, with its
systemd unit disabled so mode 2 owns the daemon's lifecycle:

```bash
sudo apt install ./rtpmidid_24.12.2_arm64.deb
sudo systemctl disable --now rtpmidid
```

Its config lives at `~/.config/disklavier/rtpmidid.ini`. The `[alsa_announce]`
section is what creates a persistent ALSA port to wire to; `[rtpmidi_announce]`
alone only creates one once the Mac connects, leaving nothing to pre-wire. The
`[alsa_hw_auto_export]` section is deliberately omitted — rtpmidid's built-in
default exports every local ALSA port, which makes extra sessions appear in
Audio MIDI Setup beside the real one.

#### Direct vs relay

`direct` (the default) wires the piano's own ALSA port straight to the daemon.
The hardware port is bidirectional, so this produces **one** network session and
MIDI never passes through Python — no added latency. The session shows up in
Audio MIDI Setup named after the ALSA device (`USB Midi-USB Midi MIDI 1`); that
name comes from the hardware and cannot be changed from here.

Setting `direct: false` relays through the virtual ports instead, so the mode
can see and filter traffic. The cost is a Python hop on every message and **two**
sessions on the Mac, one per direction, since each ALSA port is announced
separately and each is one-way.

Either way the mode gates access: connections are made on entry and torn down on
exit, so the Mac can only reach the piano while mode 2 is active.

Mode 2 can run the daemon for you, starting it on entry and stopping it on
exit, so nothing lingers when you switch modes. Set `daemon_command` in the
config:

```json
"2": {"mode": "network", "options": {
  "daemon_command": "rtpmidid --name Disklavier",
  "daemon_port_pattern": "rtpmidi*"
}}
```

On entry the mode spawns that command in its own process group, waits for the
matching ALSA port to appear, and wires it to its own ports in both directions.
On exit it disconnects, SIGTERMs the process group, and escalates to SIGKILL if
the daemon ignores it. A missing binary is reported and the bridge still comes
up, so a bad `daemon_command` never wedges the mode.

Leave `daemon_command` unset to manage the daemon yourself, then wire it by hand:

```bash
aconnect -i                                   # sources (read from)
aconnect -o                                   # destinations (write to)
aconnect <daemon source> <our dest>           # network -> piano
aconnect <our source> <daemon dest>           # piano -> network
```

Note that the two halves of a virtual port pair share a name, so you must pick
each end from the right list — `-i` for the source, `-o` for the destination.
Matching by name alone picks the wrong half and ALSA rejects the connection with
"Operation not permitted".

The virtual ports stay published for the life of the process, including while
another mode is active — ALSA will not release a virtual port before the process
exits, and keeping them up means the Mac's session survives a mode switch.
Relaying only happens while mode 2 is active.

Note that the mode-switch keys are consumed by the controller, so **the top two
keys of the piano do not reach the Mac**.

### Switching Modes from the Console

When the controller is attached to a terminal it also takes commands on stdin,
which is how you switch modes over ssh or from the service's tmux pane:

| Command | Effect |
|---------|--------|
| `<number>` | Switch to that mode |
| `l` | List configured modes and show the active one |
| `q` | Quit |
| `?` | Show help |

Console commands and the keyboard gesture feed the same queue, so the two
cannot fight over the active mode. The console is skipped automatically when
stdin is not a terminal, and `--no-console` disables it outright.

### Switching Modes from the Keyboard

Play the top C (108), then the mode number as that many presses of the top B
(107), then the top C again. The switch happens when you release that final top
C:

| Sequence | Mode |
|----------|------|
| `108, 108` | 0 |
| `108, 107, 108` | 1 |
| `108, 107, 107, 108` | 2 |

These two keys are reserved for the controller and never reach the running
mode, so a mode never sees them as input. Pressing any other key abandons a
gesture in progress, as does pausing for more than `gesture_timeout` seconds
mid-gesture.

After an hour with no key pressed, the controller returns to mode 0 whatever
mode it was in.

### Configuration

The controller reads `~/.config/disklavier/config.json`, writing the defaults on
first run. Override the directory with `DISKLAVIER_CONFIG_DIR`, or pass a file
with `disklavier -c path/to/config.json`.

```json
{
  "input_device_pattern": "*USB Midi*",
  "output_device_pattern": "*USB Midi*",
  "idle_reset_seconds": 3600.0,
  "mode_switch": {
    "select_note": 108,
    "count_note": 107,
    "gesture_timeout": 5.0
  },
  "modes": {
    "0": {"mode": "surveil", "options": {"silence_timeout": 10.0}},
    "1": {"mode": "test", "options": {"velocity": 60}}
  }
}
```

Each entry under `modes` maps a mode number to a mode implementation and the
keyword arguments passed to its constructor. Mode 0 is the default and the one
returned to when the piano goes idle.

### Adding a Mode

Subclass `Mode` in a new subpackage under `disklavier/modes/`, register it in
`disklavier/modes/__init__.py`, and add a number for it in the config file:

```python
from disklavier.modes.base import Mode

class MyMode(Mode):
    name = "mine"
    description = "What it does"

    def start(self): ...                              # entering the mode
    def handle_midi(self, midi_bytes, delta_time): ...  # incoming MIDI
    def stop(self): ...                               # leaving; leave the piano quiet
```

The controller hands each mode the shared `Disklavier` connection, so a mode
never opens MIDI ports itself. Modes are constructed fresh on every activation.

## Recording Daemon Usage

`disklavier-record` runs surveil mode on its own, without mode switching.

### Basic Usage

Start the recording daemon with default settings:

```bash
disklavier-record
```

This will:
- Connect to the first available "*USB Midi*" device
- Wait for MIDI input to start recording
- Save recordings after 10 seconds of silence
- Filter out system timing messages (keeping only notes and pedals)

### Advanced Usage

```bash
# Custom silence timeout (5 seconds)
disklavier-record -t 5

# Include system timing messages
disklavier-record --include-system

# Use custom device pattern
disklavier-record -i "*Piano*"

# List available MIDI devices
disklavier-record --list-devices
```

### How It Works

1. **Waiting**: The daemon waits patiently for any MIDI input
2. **Recording**: When MIDI input is detected, recording starts automatically
3. **Real-time feedback**: Each MIDI event is displayed with timing and note information
4. **Automatic saving**: After the configured silence period (default 10s), the recording is saved
5. **Filename format**: `25JUN02-1144PM24-d0011-n000014.mid`
   - `25JUN02-1144PM24`: Timestamp (YYMmmDD-HHMMAMPMSS)
   - `d0011`: Duration in seconds (11 seconds)
   - `n000014`: Number of notes played (14 notes)

### Recording Storage

Recordings are automatically saved to:
- Default: `~/.cache/disklavier/recordings/`
- Custom: Set `DISKLAVIER_CACHE_DIR` environment variable

### Example Session

```
🎹 Initializing Disklavier recording daemon...
   Input device pattern: *USB Midi*
   Silence timeout: 10.0s
   Filter system messages: True
✓ Disklavier initialized successfully

🎯 MIDI Recording Daemon Active
📁 Recordings will be saved to: /home/user/.cache/disklavier/recordings
⏱️  Silence timeout: 10.0s
🎧 Waiting for MIDI input...
   Press Ctrl+C to stop

🔴 Recording started at 23:44:24
📥 Note On (ch1): [144, 60, 64] (t=0.000s, notes=1)
📥 Note Off (ch1): [128, 60, 64] (t=0.500s, notes=1)
📥 Control Change 64 (Sustain Pedal) (ch1): [176, 64, 127] (t=1.200s, notes=1)

💾 Recording saved: 25JUN02-1144PM24-d0011-n000001.mid
   📍 Path: /home/user/.cache/disklavier/recordings/25JUN02-1144PM24-d0011-n000001.mid
   ⏱️  Duration: 11.2s
   🎵 Notes: 1
   📊 Events: 3
```

## Practice Activity Analysis

Analyze your practice sessions with detailed statistics:

```bash
# Show all-time practice statistics
disklavier-activity --all

# Show today's practice only
disklavier-activity --today

# Show last 7 days (default)
disklavier-activity

# Show last 30 days
disklavier-activity --days 30
```

### Visual Activity Charts

Create GitHub-style activity visualizations (requires `matplotlib`):

```bash
# Install matplotlib for visualizations
pip install matplotlib

# Create activity chart (always shows last 365 days)
disklavier-activity --visualize

# Create chart with different metrics
disklavier-activity --visualize --metric sessions  # Show session count
disklavier-activity --visualize --metric notes     # Show note count
disklavier-activity --visualize --metric duration  # Show practice time (default)

# Save to custom file
disklavier-activity --visualize --output my_chart.png --metric notes
```

The visualization creates a GitHub-style activity grid showing:
- **365 days of practice activity** in a wide format
- **Weekly layout** starting with Sunday at top, Saturday at bottom
- **Day labels** for Mon, Wed, Fri only (clean layout)
- **Color intensity** representing activity level (lighter = less, darker = more)
- **Month labels** across the top
- **Legend** showing color scale from "Less" to "More"

### Example Activity Report

```
📊 All-Time Practice Activity
==========================
🎵 Sessions: 23
⏰ Total practice time: 2h 15m 32s
🎹 Total notes played: 5,847
📈 Average session: 5m 54s, 254 notes
🎯 Notes per minute: 43.2
```

### Programmatic Usage

```python
from disklavier.web.activity import activity_over_period, create_summary_image
import time

# Get practice stats for the last week
week_ago = time.time() - (7 * 24 * 60 * 60)
sessions, duration, notes = activity_over_period(week_ago, time.time())

print(f"Last week: {sessions} sessions, {duration:.1f} seconds, {notes} notes")

# Create a visualization (returns PNG bytes)
png_bytes = create_summary_image(metric="duration")
if png_bytes:
    with open("my_activity.png", "wb") as f:
        f.write(png_bytes)
```

## Service Management

The disklavier recording daemon can be set up as a systemd service to automatically start on boot and restart on failure. The service runs the daemon in a tmux session called `DISKLAVIER`.

### Service Commands

```bash
# Check service status
sudo systemctl status disklavier.service

# Stop the service
sudo systemctl stop disklavier.service

# Start the service
sudo systemctl start disklavier.service

# Restart the service
sudo systemctl restart disklavier.service

# View service logs
sudo journalctl -u disklavier.service -f

# Connect to the tmux session to see live output
tmux attach -t DISKLAVIER

# List running tmux sessions
tmux list-sessions
```

### Service Installation

The service is configured to:
- Start automatically on boot
- Restart on failure with a 10-second delay
- Run in a dedicated tmux session for easy monitoring
- Save recordings to the default cache directory

## Interactive Testing

For interactive testing and device exploration:

```bash
disklavier
```

## Technical Details

### Timing Precision

The system uses high-precision timing through:
- `time.time()` for absolute timestamps
- `mido` library with 960 ticks per beat resolution
- Thread-safe event recording with proper synchronization

### MIDI File Format

Recordings are saved as standard MIDI files (.mid) with:
- High resolution timing (960 ticks per beat)
- Proper delta time encoding
- Support for notes, control changes, and pedal events

### Supported MIDI Events

- **Note On/Off**: Piano key presses and releases
- **Control Changes**: Pedal events (sustain, soft, sostenuto)
- **System filtering**: Optional filtering of timing/system messages

### Activity Analysis

The activity analysis works by:
- Parsing filename timestamps, durations, and note counts
- Filtering recordings by time period
- Aggregating statistics across multiple sessions
- Providing both raw data and formatted reports

## Command Line Options

### Recording Daemon

```
disklavier-record [-h] [-i INPUT] [-t TIMEOUT] [--include-system] [--list-devices]

options:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        Input device pattern (default: '*USB Midi*')
  -t TIMEOUT, --timeout TIMEOUT
                        Silence timeout in seconds before saving recording (default: 10.0)
  --include-system      Include system timing messages (default is to filter them out)
  --list-devices        List available MIDI input devices and exit
```

### Activity Analysis

```
disklavier-activity [-h] [--days DAYS] [--today] [--all]

options:
  -h, --help            show this help message and exit
  --days DAYS, -d DAYS  Number of recent days to analyze (default: 7)
  --today               Show only today's activity
  --all                 Show all-time activity
```

## Dependencies

- `python-rtmidi`: Low-latency MIDI I/O
- `mido`: MIDI file reading/writing and message handling 