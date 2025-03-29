document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const portSelect = document.getElementById('port-select');
    const connectBtn = document.getElementById('connect-btn');
    const channelSelect = document.getElementById('channel');
    const velocitySlider = document.getElementById('velocity');
    const velocityValue = document.getElementById('velocity-value');
    const noteInput = document.getElementById('note');
    const noteOnBtn = document.getElementById('note-on-btn');
    const noteOffBtn = document.getElementById('note-off-btn');
    const statusDiv = document.getElementById('status');
    const pianoDiv = document.getElementById('piano');
    
    // Current state
    let currentPort = null;
    
    // Initialize channel select
    for (let i = 0; i < 16; i++) {
        const option = document.createElement('option');
        option.value = i;
        option.textContent = `Channel ${i+1}`;
        channelSelect.appendChild(option);
    }
    
    // Initialize piano
    const octaveStart = 4; // Start at middle C (C4)
    const numOctaves = 2;
    const noteNames = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    const whiteKeys = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
    
    // Create piano keys
    for (let octave = octaveStart; octave < octaveStart + numOctaves; octave++) {
        let whiteKeyIndex = 0;
        
        // Create white keys first
        for (let n = 0; n < whiteKeys.length; n++) {
            const noteName = whiteKeys[n];
            const noteNumber = noteNames.indexOf(noteName) + (octave * 12);
            
            const key = document.createElement('div');
            key.className = 'white-key';
            key.dataset.note = noteNumber;
            key.dataset.name = `${noteName}${octave}`;
            
            key.addEventListener('mousedown', () => sendNoteOn(noteNumber));
            key.addEventListener('mouseup', () => sendNoteOff(noteNumber));
            key.addEventListener('mouseleave', () => sendNoteOff(noteNumber));
            
            pianoDiv.appendChild(key);
            whiteKeyIndex++;
        }
    }
    
    // Add black keys on top
    const whiteKeys2 = document.querySelectorAll('.white-key');
    for (let i = 0; i < whiteKeys2.length; i++) {
        const noteName = whiteKeys2[i].dataset.name[0];
        const octave = whiteKeys2[i].dataset.name[1];
        
        // Add black key after C, D, F, G, A
        if (noteName === 'C' || noteName === 'D' || noteName === 'F' || noteName === 'G' || noteName === 'A') {
            const blackKeyNote = parseInt(whiteKeys2[i].dataset.note) + 1;
            const blackKey = document.createElement('div');
            blackKey.className = 'black-key';
            blackKey.dataset.note = blackKeyNote;
            blackKey.style.left = `${whiteKeys2[i].offsetLeft + 40}px`;
            
            blackKey.addEventListener('mousedown', () => sendNoteOn(blackKeyNote));
            blackKey.addEventListener('mouseup', () => sendNoteOff(blackKeyNote));
            blackKey.addEventListener('mouseleave', () => sendNoteOff(blackKeyNote));
            
            pianoDiv.appendChild(blackKey);
        }
    }
    
    // Update velocity display
    velocitySlider.addEventListener('input', function() {
        velocityValue.textContent = this.value;
    });
    
    // Fetch available MIDI ports
    fetch('/api/midi-ports')
        .then(response => response.json())
        .then(data => {
            data.forEach(port => {
                const option = document.createElement('option');
                option.value = port.id;
                option.textContent = port.name;
                portSelect.appendChild(option);
            });
            
            if (data.length > 0) {
                addStatus(`Found ${data.length} MIDI ports. Select one and click Connect.`);
            } else {
                addStatus('No MIDI ports found. A virtual port has been created.');
            }
        })
        .catch(error => {
            addStatus(`Error fetching MIDI ports: ${error}`);
        });
    
    // Connect to selected MIDI port
    connectBtn.addEventListener('click', function() {
        const portId = parseInt(portSelect.value);
        
        fetch('/api/connect', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ port_id: portId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                currentPort = portId;
                addStatus(data.message);
            } else {
                addStatus(`Error: ${data.message}`);
            }
        })
        .catch(error => {
            addStatus(`Connection error: ${error}`);
        });
    });
    
    // Send Note On
    function sendNoteOn(note) {
        const velocity = parseInt(velocitySlider.value);
        const channel = parseInt(channelSelect.value);
        
        // Update UI
        const pianoKey = document.querySelector(`.white-key[data-note="${note}"]`) || 
                        document.querySelector(`.black-key[data-note="${note}"]`);
        if (pianoKey) {
            if (pianoKey.classList.contains('black-key')) {
                pianoKey.classList.add('black-pressed');
            } else {
                pianoKey.classList.add('pressed');
            }
        }
        
        fetch('/api/note-on', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ note, velocity, channel })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                addStatus(data.message);
            } else {
                addStatus(`Error: ${data.message}`);
            }
        })
        .catch(error => {
            addStatus(`Note ON error: ${error}`);
        });
    }
    
    // Send Note Off
    function sendNoteOff(note) {
        const velocity = 0;
        const channel = parseInt(channelSelect.value);
        
        // Update UI
        const pianoKey = document.querySelector(`.white-key[data-note="${note}"]`) || 
                        document.querySelector(`.black-key[data-note="${note}"]`);
        if (pianoKey) {
            pianoKey.classList.remove('pressed');
            pianoKey.classList.remove('black-pressed');
        }
        
        fetch('/api/note-off', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ note, velocity, channel })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // addStatus(data.message); // Commented out to reduce log spam
            } else {
                addStatus(`Error: ${data.message}`);
            }
        })
        .catch(error => {
            addStatus(`Note OFF error: ${error}`);
        });
    }
    
    // Manual note buttons
    noteOnBtn.addEventListener('click', function() {
        const note = parseInt(noteInput.value);
        sendNoteOn(note);
    });
    
    noteOffBtn.addEventListener('click', function() {
        const note = parseInt(noteInput.value);
        sendNoteOff(note);
    });
    
    // Add status message
    function addStatus(message) {
        const p = document.createElement('p');
        p.textContent = message;
        statusDiv.appendChild(p);
        statusDiv.scrollTop = statusDiv.scrollHeight;
        
        // Limit status messages
        while (statusDiv.children.length > 100) {
            statusDiv.removeChild(statusDiv.firstChild);
        }
    }
    
    // Add keyboard support
    const keyMap = {
        'a': 60, // Middle C
        'w': 61, // C#
        's': 62, // D
        'e': 63, // D#
        'd': 64, // E
        'f': 65, // F
        't': 66, // F#
        'g': 67, // G
        'y': 68, // G#
        'h': 69, // A
        'u': 70, // A#
        'j': 71, // B
        'k': 72  // C5
    };
    
    const pressedKeys = new Set();
    
    window.addEventListener('keydown', function(e) {
        const note = keyMap[e.key.toLowerCase()];
        if (note && !pressedKeys.has(e.key)) {
            pressedKeys.add(e.key);
            sendNoteOn(note);
        }
    });
    
    window.addEventListener('keyup', function(e) {
        const note = keyMap[e.key.toLowerCase()];
        if (note) {
            pressedKeys.delete(e.key);
            sendNoteOff(note);
        }
    });
});