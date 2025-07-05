"""
FastAPI server for Disklavier web interface.
Serves the MIDI recording browser and player.
"""

import datetime
import zoneinfo
import io
import html
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import pretty_midi
import soundfile as sf
import numpy as np

from ..activity import parse_recording_filename
from ..paths import REPO_DIR, iter_midi_tags, get_midi_recording
from .utils import burn_midi_sustain


app = FastAPI(
    title="Disklavier MIDI Browser", description="Browse and play MIDI recordings"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", response_class=HTMLResponse)
async def read_index(date: str = None, file: str = None):
    """Serve the main page with dynamic metadata for shared recordings"""
    index_path = static_path / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index page not found")

    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # If this is a shared recording link, customize the metadata
    if date and file:
        try:
            # Find the recording metadata using tag
            tag = file.replace(".mid", "") if file.endswith(".mid") else file
            recording_path = get_midi_recording(tag)
            parsed = parse_recording_filename(recording_path)
            if parsed is not None:
                timestamp, duration, note_count = parsed

                # Format date and time
                eastern_tz = zoneinfo.ZoneInfo("America/New_York")
                date_obj = datetime.datetime.fromtimestamp(timestamp, tz=eastern_tz)
                formatted_date = date_obj.strftime("%A, %B %d, %Y")
                formatted_time = date_obj.strftime("%I:%M:%S %p").lstrip("0")
                formatted_duration = format_duration(duration)

                # Create custom metadata with HTML escaping
                custom_title = f"Piano Recording - {formatted_date} at {formatted_time}"
                custom_description = f"Listen to this {formatted_duration} piano recording ({note_count:,} notes) from Chris's Disklavier database. Recorded on {formatted_date} at {formatted_time}. Browse more recordings and play with interactive piano roll visualization."

                # HTML escape the content to prevent XSS
                escaped_title = html.escape(custom_title, quote=True)
                escaped_description = html.escape(custom_description, quote=True)

                # Replace metadata in HTML
                html_content = html_content.replace(
                    '<meta property="og:title" content="Chris\'s Piano Database">',
                    f'<meta property="og:title" content="{escaped_title}">',
                )
                html_content = html_content.replace(
                    '<meta property="og:description" content="Candid piano recordings from a Yamaha Disklavier. Mostly classical, some pop and improv. Browse by date and listen with interactive piano roll visualization.">',
                    f'<meta property="og:description" content="{escaped_description}">',
                )
                html_content = html_content.replace(
                    '<meta name="twitter:title" content="Chris\'s Piano Database">',
                    f'<meta name="twitter:title" content="{escaped_title}">',
                )
                html_content = html_content.replace(
                    '<meta name="twitter:description" content="Candid piano recordings from a Yamaha Disklavier. Mostly classical, some pop and improv. Browse by date and listen with interactive piano roll visualization.">',
                    f'<meta name="twitter:description" content="{escaped_description}">',
                )
                html_content = html_content.replace(
                    "<title>Chris's Piano DB</title>",
                    f"<title>{html.escape(custom_title)} - Chris's Piano DB</title>",
                )

        except Exception as e:
            # If anything goes wrong, just serve the default page
            print(f"Error customizing metadata for shared recording: {e}")
            pass

    return HTMLResponse(content=html_content)


@app.get("/api/recordings")
async def get_recordings():
    """Get all MIDI recordings with metadata"""
    recordings = []

    for tag in iter_midi_tags():
        recording_path = get_midi_recording(tag)
        parsed = parse_recording_filename(recording_path)
        if parsed is None:
            continue

        timestamp, duration, note_count = parsed

        # Filter out MIDI files with only one note
        if note_count <= 1:
            continue

        # Convert timestamp to US East Coast date string
        eastern_tz = zoneinfo.ZoneInfo("America/New_York")
        date_obj = datetime.datetime.fromtimestamp(timestamp, tz=eastern_tz)

        recording_data = {
            "tag": tag,
            "filename": recording_path.name,  # Keep for backward compatibility
            "filepath": str(recording_path),
            "timestamp": timestamp,
            "date": date_obj.strftime("%Y-%m-%d"),
            "time": date_obj.strftime("%H:%M:%S"),
            "duration": duration,
            "note_count": note_count,
            "formatted_duration": format_duration(duration),
        }
        recordings.append(recording_data)

    # Sort by timestamp (newest first)
    recordings.sort(key=lambda x: x["timestamp"], reverse=True)

    return {"recordings": recordings}


@app.get("/api/recordings/by-date")
async def get_recordings_by_date():
    """Get recordings organized by date for calendar view"""
    recordings_by_date = {}

    for tag in iter_midi_tags():
        recording_path = get_midi_recording(tag)
        parsed = parse_recording_filename(recording_path)
        if parsed is None:
            continue

        timestamp, duration, note_count = parsed

        # Filter out MIDI files with only one note
        if note_count <= 1:
            continue

        eastern_tz = zoneinfo.ZoneInfo("America/New_York")
        date_obj = datetime.datetime.fromtimestamp(timestamp, tz=eastern_tz)
        date_str = date_obj.strftime("%Y-%m-%d")

        if date_str not in recordings_by_date:
            recordings_by_date[date_str] = []

        recording_data = {
            "tag": tag,
            "filename": recording_path.name,  # Keep for backward compatibility
            "filepath": str(recording_path),
            "timestamp": timestamp,
            "time": date_obj.strftime("%H:%M:%S"),
            "duration": duration,
            "note_count": note_count,
            "formatted_duration": format_duration(duration),
        }
        recordings_by_date[date_str].append(recording_data)

    # Sort recordings within each date by timestamp (newest first)
    for date in recordings_by_date:
        recordings_by_date[date].sort(key=lambda x: x["timestamp"], reverse=True)

    return recordings_by_date


@app.get("/api/player_midi/{tag}")
async def prepare_and_download_player_midi(tag: str):
    """Serve a MIDI file for playback with sustain pedal burned in"""

    # Remove .mid extension if present to get the actual tag
    if tag.endswith(".mid"):
        actual_tag = tag[:-4]
    else:
        actual_tag = tag

    try:
        recording_path = get_midi_recording(actual_tag)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="MIDI file not found")

    # Process MIDI file to burn in sustain pedal effect
    processed_midi_bytes = burn_midi_sustain(str(recording_path))

    # Return with proper headers for MIDI players
    return Response(
        content=processed_midi_bytes,
        media_type="audio/midi",
        headers={
            "Content-Disposition": f"inline; filename={tag if tag.endswith('.mid') else tag + '.mid'}",
            "Content-Length": str(len(processed_midi_bytes)),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@app.get("/api/preview_mp3/{tag}")
async def prepare_and_download_preview_mp3(tag: str):
    """Convert a MIDI file to MP3 using FluidSynth and return for download"""

    # Remove .mp3 extension if present to get the actual tag
    if tag.endswith(".mp3"):
        actual_tag = tag[:-4]
    else:
        actual_tag = tag

    try:
        recording_path = get_midi_recording(actual_tag)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="MIDI file not found")

    # Load MIDI file using pretty_midi
    midi_data = pretty_midi.PrettyMIDI(str(recording_path))

    # Path to SoundFont file
    sf2_path = str(REPO_DIR / "SalC5Light2.sf2")

    if not Path(sf2_path).exists():
        raise HTTPException(
            status_code=500, detail=f"SoundFont file not found: {sf2_path}"
        )

    # Synthesize audio using FluidSynth
    # Sample rate of 44.1kHz is standard for MP3
    sample_rate = 44100
    audio = midi_data.fluidsynth(fs=sample_rate, sf2_path=sf2_path).astype(np.float32)

    # Write audio directly to MP3 format using soundfile
    mp3_buffer = io.BytesIO()
    sf.write(mp3_buffer, audio, sample_rate, format="MP3")
    mp3_buffer.seek(0)
    mp3_data = mp3_buffer.getvalue()

    return StreamingResponse(
        io.BytesIO(mp3_data),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f"attachment; filename={tag if tag.endswith('.mp3') else tag + '.mp3'}",
            "Content-Length": str(len(mp3_data)),
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@app.get("/api/raw_midi/{tag}")
async def download_raw_midi(tag: str):
    """Download a raw MIDI file"""

    # Remove .mid extension if present to get the tag
    if tag.endswith(".mid"):
        actual_tag = tag[:-4]
    else:
        actual_tag = tag

    try:
        recording_path = get_midi_recording(actual_tag)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="MIDI file not found")

    return FileResponse(
        path=str(recording_path),
        media_type="audio/midi",
        filename=tag,
        headers={
            "Content-Disposition": f"attachment; filename={tag}",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


def format_duration(seconds: float) -> str:
    """Format duration in seconds to a human-readable string"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if secs > 0:
            return f"{hours}h {minutes}m {secs}s"
        else:
            return f"{hours}h {minutes}m"


def main():
    """Main function with argument parsing"""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Disklavier MIDI Browser - Web interface for browsing and playing MIDI recordings"
    )
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default="0.0.0.0",
        help="Host to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )

    args = parser.parse_args()

    print(f"🎹 Starting Disklavier MIDI Browser")
    print(f"📡 Server: http://{args.host}:{args.port}")
    print(f"🔄 Auto-reload: {'enabled' if args.reload else 'disabled'}")
    print("Press Ctrl+C to stop the server")

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
