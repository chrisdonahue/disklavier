"""
FastAPI server for Disklavier web interface.
Serves the MIDI recording browser and player.
"""

import datetime
import io
import zoneinfo
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from ..activity import parse_recording_filename, get_daily_activity_data
from ..paths import iter_midi_recordings
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
async def read_index():
    """Serve the main page"""
    index_path = static_path / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index page not found")

    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/recordings")
async def get_recordings():
    """Get all MIDI recordings with metadata"""
    recordings = []

    for recording_path in iter_midi_recordings():
        parsed = parse_recording_filename(recording_path)
        if parsed is None:
            continue

        timestamp, duration, note_count = parsed

        # Convert timestamp to US East Coast date string
        eastern_tz = zoneinfo.ZoneInfo("America/New_York")
        date_obj = datetime.datetime.fromtimestamp(timestamp, tz=eastern_tz)

        recording_data = {
            "filename": recording_path.name,
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

    for recording_path in iter_midi_recordings():
        parsed = parse_recording_filename(recording_path)
        if parsed is None:
            continue

        timestamp, duration, note_count = parsed
        eastern_tz = zoneinfo.ZoneInfo("America/New_York")
        date_obj = datetime.datetime.fromtimestamp(timestamp, tz=eastern_tz)
        date_str = date_obj.strftime("%Y-%m-%d")

        if date_str not in recordings_by_date:
            recordings_by_date[date_str] = []

        recording_data = {
            "filename": recording_path.name,
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


@app.get("/api/midi/{filename}")
async def serve_midi_file(filename: str):
    """Serve a MIDI file for playback with sustain pedal burned in"""

    # Find the file in the recordings
    for recording_path in iter_midi_recordings():
        if recording_path.name == filename:
            if not recording_path.exists():
                raise HTTPException(status_code=404, detail="MIDI file not found")

            # Process MIDI file to burn in sustain pedal effect
            processed_midi_bytes = burn_midi_sustain(str(recording_path))

            # Return with proper headers for MIDI players
            return Response(
                content=processed_midi_bytes,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f"inline; filename={filename}",
                    "Content-Length": str(len(processed_midi_bytes)),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-cache",
                },
            )

    raise HTTPException(status_code=404, detail="MIDI file not found")


@app.get("/api/download/{filename}")
async def download_midi_file(filename: str):
    """Download a MIDI file"""
    # Find the file in the recordings
    for recording_path in iter_midi_recordings():
        if recording_path.name == filename:
            if not recording_path.exists():
                raise HTTPException(status_code=404, detail="MIDI file not found")

            return FileResponse(
                path=str(recording_path),
                media_type="audio/midi",
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

    raise HTTPException(status_code=404, detail="MIDI file not found")


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
