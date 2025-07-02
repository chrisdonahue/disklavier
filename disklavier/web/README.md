# Disklavier Web Interface

A beautiful web interface for browsing and playing your Disklavier MIDI recordings.

## Features

- 🎹 **Piano Player**: Play MIDI recordings with visual piano roll display
- 📅 **Calendar View**: Browse recordings by date with visual indicators
- 🦶 **Sustain Pedal Support**: Automatically processes sustain pedal (CC 64) data for realistic web playback
- 📥 **Download**: Download any MIDI file
- 🎵 **Rich Playback**: Uses [html-midi-player](https://github.com/cifkao/html-midi-player/) for high-quality MIDI playback
- 📱 **Responsive Design**: Works on desktop and mobile devices

## Installation

1. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Make sure you're in the disklavier project directory and that your MIDI recordings are accessible via the `paths.py` module.

## Running the Server

1. Start the web server (from the project root directory):
   ```bash
   # Basic usage with defaults (host: 0.0.0.0, port: 8000)
   python -m disklavier.web
   
   # Custom host and port
   python -m disklavier.web --host localhost --port 8080
   
   # Short options
   python -m disklavier.web -H 127.0.0.1 -p 9000
   
   # Enable auto-reload for development
   python -m disklavier.web --reload
   
   # See all options
   python -m disklavier.web --help
   ```

2. Open your browser and navigate to the displayed URL (default: http://localhost:8000)

The server will:
- Serve the web interface at the root URL
- Provide API endpoints for recordings data
- Serve MIDI files for playback and download

## Usage

### Calendar View
- Use the calendar to browse recordings by date
- Days with recordings are highlighted in blue with a red counter showing the number of recordings
- Click on any date to view recordings for that day

### Playing Recordings
- Click on any recording in the list to play it
- Use the player controls to play, pause, or stop playback
- The piano roll visualizer shows notes as they play
- Currently playing recordings are highlighted in green

### Downloading
- Click the download button on any recording to save it to your computer
- Or use the main download button while a recording is loaded
- **Note**: Downloaded files are the original MIDI recordings (sustain pedal processing is only applied for web playback)

### Sustain Pedal Processing
The web interface automatically processes sustain pedal data to ensure realistic playback in web browsers:

- **For Playback**: MIDI files are processed in real-time to "burn in" sustain pedal effects by extending note durations
- **For Downloads**: Original files are served unchanged, preserving all MIDI data
- **How it works**: When sustain pedal (CC 64) is pressed, note-off events are delayed until the pedal is released
- **Why it's needed**: Web MIDI players often don't properly interpret sustain pedal control changes

## API Endpoints

- `GET /`: Main web interface
- `GET /api/recordings`: Get all recordings with metadata
- `GET /api/recordings/by-date`: Get recordings organized by date
- `GET /api/midi/{filename}`: Serve MIDI file for playback
- `GET /api/download/{filename}`: Download MIDI file

## Troubleshooting

- If recordings don't appear, check that the `paths.py` module is correctly configured
- If MIDI files don't play, ensure your browser supports Web Audio API
- For best experience, use a modern browser (Chrome, Firefox, Safari, Edge)

🎹 Starting Disklavier MIDI Browser
📡 Server: http://localhost:8080
🔄 Auto-reload: disabled
Press Ctrl+C to stop the server 