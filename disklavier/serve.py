from flask import Flask, render_template, request, jsonify
import rtmidi
from threading import Lock

from . import LIB_DIR

# Create the Flask app with static folder configuration
app = Flask(
    __name__,
    static_url_path="/static",
    static_folder=LIB_DIR / "static",
    template_folder=LIB_DIR / "templates",
)

midi_lock = Lock()  # To prevent concurrent MIDI access issues

# Find available MIDI output ports
available_midi_outputs = []
midi_out = None


def initialize_midi():
    """Initialize MIDI connection and discover available ports"""
    global midi_out, available_midi_outputs

    midi_out = rtmidi.MidiOut()
    available_ports = midi_out.get_ports()

    print("Available MIDI ports:")
    for idx, port in enumerate(available_ports):
        print(f"  {idx}: {port}")
        available_midi_outputs.append({"id": idx, "name": port})

    # If no ports available, create a virtual one
    if not available_ports:
        print("No MIDI ports found. Creating a virtual port.")
        midi_out.open_virtual_port("Flask MIDI Server")
        available_midi_outputs.append({"id": 0, "name": "Flask MIDI Server (Virtual)"})
    else:
        # Connect to the first available port by default
        midi_out.open_port(0)
        print(f"Connected to: {available_ports[0]}")


# Initialize MIDI when the app starts
initialize_midi()


@app.route("/")
def index():
    """Render the main web interface"""
    return render_template("index.html", midi_outputs=available_midi_outputs)


@app.route("/api/midi-ports", methods=["GET"])
def get_midi_ports():
    """Return a list of available MIDI ports"""
    return jsonify(available_midi_outputs)


@app.route("/api/connect", methods=["POST"])
def connect_to_port():
    """Connect to the specified MIDI port"""
    global midi_out

    data = request.get_json()
    port_idx = data.get("port_id")

    with midi_lock:
        # Close current port if open
        if midi_out.is_port_open():
            midi_out.close_port()

        try:
            midi_out.open_port(port_idx)
            port_name = midi_out.get_port_name(port_idx)
            return jsonify({"success": True, "message": f"Connected to {port_name}"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/note-on", methods=["POST"])
def note_on():
    """Send a MIDI note-on message"""
    data = request.get_json()
    note = data.get("note", 60)  # Middle C by default
    velocity = data.get("velocity", 64)  # Medium velocity by default
    channel = data.get("channel", 0)  # MIDI channel 1 by default (zero-indexed)

    with midi_lock:
        if midi_out and midi_out.is_port_open():
            # Construct a note-on message
            midi_out.send_message([0x90 + channel, note, velocity])
            return jsonify(
                {
                    "success": True,
                    "message": f"Note ON: {note}, velocity: {velocity}, channel: {channel}",
                }
            )
        else:
            return jsonify({"success": False, "message": "No MIDI port open"}), 400


@app.route("/api/note-off", methods=["POST"])
def note_off():
    """Send a MIDI note-off message"""
    data = request.get_json()
    note = data.get("note", 60)
    velocity = data.get("velocity", 0)  # Usually 0 for note-off
    channel = data.get("channel", 0)

    with midi_lock:
        if midi_out and midi_out.is_port_open():
            # Construct a note-off message
            midi_out.send_message([0x80 + channel, note, velocity])
            return jsonify(
                {
                    "success": True,
                    "message": f"Note OFF: {note}, velocity: {velocity}, channel: {channel}",
                }
            )
        else:
            return jsonify({"success": False, "message": "No MIDI port open"}), 400


if __name__ == "__main__":
    # Get the host IP for network access
    import socket

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print(f"Starting server on http://{local_ip}:5000")
    print("You can access this from other devices on your network using this URL")

    # Run the Flask app
    app.run(host="0.0.0.0", port=5000, debug=True)
