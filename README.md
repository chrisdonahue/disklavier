# Disklavier Recording System

A Python package for interfacing with Yamaha Disklavier MIDI systems, featuring a high-precision recording daemon that automatically captures and saves MIDI performances.

## Features

- **High-precision MIDI recording** with microsecond timing accuracy
- **Automatic silence detection** - starts recording when MIDI input is received, stops after configurable silence period
- **Smart filtering** - focuses on musical events (notes, pedals) while filtering out system timing messages
- **Automatic file saving** with descriptive filenames including timestamp, duration, and note count
- **Real-time monitoring** with live feedback of incoming MIDI events

## Installation

```bash
pip install -e .
```

## Recording Daemon Usage

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

## Command Line Options

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

## Dependencies

- `python-rtmidi`: Low-latency MIDI I/O
- `mido`: MIDI file reading/writing and message handling 