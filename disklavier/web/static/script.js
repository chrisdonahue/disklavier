// Global state
let recordingsByDate = {};
let currentDate = new Date();
let selectedDate = null;
let currentRecording = null;
let midiPlayer = null;

// DOM elements
const loading = document.getElementById('loading');
const calendarGrid = document.getElementById('calendarGrid');
const currentMonthSpan = document.getElementById('currentMonth');
const recordingsList = document.getElementById('recordingsList');
const selectedDateTitle = document.getElementById('selectedDateTitle');
const trackName = document.getElementById('trackName');
const trackDetails = document.getElementById('trackDetails');
const pianoSection = document.getElementById('pianoSection');

// Player controls
const playBtn = document.getElementById('playBtn');
const pauseBtn = document.getElementById('pauseBtn');
const stopBtn = document.getElementById('stopBtn');
const downloadBtn = document.getElementById('downloadBtn');

// Calendar controls
const prevMonthBtn = document.getElementById('prevMonth');
const nextMonthBtn = document.getElementById('nextMonth');
const todayBtn = document.getElementById('todayBtn');

// Initialize the application
document.addEventListener('DOMContentLoaded', async () => {
    midiPlayer = document.getElementById('midiPlayer');
    
    // Configure the MIDI visualizer for piano range (A0 to C8, MIDI 21-108)
    const midiVisualizer = document.getElementById('midiVisualizer');
    if (midiVisualizer) {
        midiVisualizer.config = {
            noteHeight: 4,
            pixelsPerTimeStep: 60,
            minPitch: 21,  // A0
            maxPitch: 108, // C8
            showOnlyOctaveLabels: true,
            colorMap: {
                0: '#ff6b6b',  // Channel 0 - red
                1: '#4ecdc4',  // Channel 1 - teal
                2: '#45b7d1',  // Channel 2 - blue
                3: '#96ceb4',  // Channel 3 - green
                4: '#feca57',  // Channel 4 - yellow
                5: '#ff9ff3',  // Channel 5 - pink
                6: '#54a0ff',  // Channel 6 - light blue
                7: '#5f27cd',  // Channel 7 - purple
                8: '#00d2d3',  // Channel 8 - cyan
                9: '#ff6348'   // Channel 9 - orange (drums)
            }
        };
    }
    
    // Configure MIDI player for better sustain pedal handling
    if (midiPlayer) {
        // Enable sustain pedal processing - this should handle CC 64 messages
        midiPlayer.addEventListener('start', () => {
            console.log('🎹 MIDI playback started - sustain pedal should be active');
        });
        
        // Log MIDI events for debugging pedal data
        midiPlayer.addEventListener('note', (e) => {
            // This will help us see if pedal data is in the MIDI file
            console.log('🎵 MIDI event:', e.detail);
        });
    }
    
    setupEventListeners();
    await loadRecordings();
    renderCalendar();
    
    // Automatically select the most recent date with recordings
    autoSelectMostRecentDate();
    
    hideLoading();
});

// Setup event listeners
function setupEventListeners() {
    // Calendar controls
    prevMonthBtn.addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() - 1);
        renderCalendar();
    });

    nextMonthBtn.addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() + 1);
        renderCalendar();
    });

    todayBtn.addEventListener('click', () => {
        // Get current date in Eastern timezone
        const now = new Date();
        const todayEastern = new Date(now.toLocaleString("en-US", {timeZone: EASTERN_TZ}));
        currentDate = new Date(todayEastern.getFullYear(), todayEastern.getMonth(), 1); // First of current month
        renderCalendar();
        selectDate(formatDate(todayEastern));
    });

    // Player controls
    playBtn.addEventListener('click', () => {
        if (midiPlayer && currentRecording) {
            midiPlayer.start();
        }
    });

    pauseBtn.addEventListener('click', () => {
        if (midiPlayer) {
            midiPlayer.pause();
        }
    });

    stopBtn.addEventListener('click', () => {
        if (midiPlayer) {
            midiPlayer.stop();
        }
    });

    downloadBtn.addEventListener('click', () => {
        if (currentRecording) {
            downloadRecording(currentRecording);
        }
    });

    // MIDI player events
    if (midiPlayer) {
        midiPlayer.addEventListener('start', () => {
            updatePlayerControls(true);
        });

        midiPlayer.addEventListener('stop', () => {
            updatePlayerControls(false);
        });

        midiPlayer.addEventListener('pause', () => {
            updatePlayerControls(false);
        });
    }
}

// Load recordings data from API
async function loadRecordings() {
    try {
        showLoading();
        const response = await fetch('/api/recordings/by-date');
        recordingsByDate = await response.json();
        console.log('Loaded recordings:', recordingsByDate);
    } catch (error) {
        console.error('Error loading recordings:', error);
        alert('Failed to load recordings. Please refresh the page.');
    }
}

// Render the calendar
function renderCalendar() {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    
    // Update month display
    currentMonthSpan.textContent = currentDate.toLocaleDateString('en-US', { 
        timeZone: EASTERN_TZ,
        month: 'long', 
        year: 'numeric' 
    });

    // Clear calendar grid
    calendarGrid.innerHTML = '';

    // Add day headers
    const dayHeaders = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    dayHeaders.forEach(day => {
        const header = document.createElement('div');
        header.textContent = day;
        header.style.textAlign = 'center';
        header.style.fontWeight = 'bold';
        header.style.color = '#666';
        header.style.padding = '10px';
        header.style.background = '#f8f9fa';
        calendarGrid.appendChild(header);
    });

    // Get first day of month and number of days
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDayOfWeek = firstDay.getDay();

    // Add empty cells for days before the first day of the month
    for (let i = 0; i < startingDayOfWeek; i++) {
        const emptyCell = document.createElement('div');
        emptyCell.className = 'calendar-day empty';
        calendarGrid.appendChild(emptyCell);
    }

    // Add days of the month
    for (let day = 1; day <= daysInMonth; day++) {
        const dayCell = document.createElement('button');
        dayCell.className = 'calendar-day';
        
        const date = new Date(year, month, day);
        const dateStr = formatDate(date);
        
        // Check if this date has recordings
        const recordings = recordingsByDate[dateStr] || [];
        const hasRecordings = recordings.length > 0;
        
        if (hasRecordings) {
            dayCell.classList.add('has-recordings');
        }

        // Create day number
        const dayNumber = document.createElement('div');
        dayNumber.className = 'day-number';
        dayNumber.textContent = day;
        dayCell.appendChild(dayNumber);

        // Add recording count if there are recordings
        if (hasRecordings) {
            const recordingCount = document.createElement('div');
            recordingCount.className = 'recording-count';
            recordingCount.textContent = recordings.length;
            dayCell.appendChild(recordingCount);
        }

        // Add click handler
        dayCell.addEventListener('click', () => selectDate(dateStr));

        // Highlight selected date
        if (selectedDate === dateStr) {
            dayCell.classList.add('selected');
        }

        calendarGrid.appendChild(dayCell);
    }
}

// Select a date and show its recordings
function selectDate(dateStr) {
    selectedDate = dateStr;
    renderCalendar(); // Re-render to update selection
    showRecordingsForDate(dateStr);
}

// Show recordings for a specific date
function showRecordingsForDate(dateStr) {
    const recordings = recordingsByDate[dateStr] || [];
    const date = parseEasternDate(dateStr);
    
    selectedDateTitle.textContent = `Recordings for ${date.toLocaleDateString('en-US', { 
        timeZone: EASTERN_TZ,
        weekday: 'long',
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
    })} (Eastern Time)`;

    recordingsList.innerHTML = '';

    if (recordings.length === 0) {
        const noRecordings = document.createElement('div');
        noRecordings.textContent = 'No recordings found for this date.';
        noRecordings.style.textAlign = 'center';
        noRecordings.style.color = '#666';
        noRecordings.style.fontStyle = 'italic';
        recordingsList.appendChild(noRecordings);
        return;
    }

    recordings.forEach(recording => {
        const recordingItem = createRecordingItem(recording);
        recordingsList.appendChild(recordingItem);
    });
}

// Create a recording item element
function createRecordingItem(recording) {
    const item = document.createElement('div');
    item.className = 'recording-item';
    
    item.innerHTML = `
        <div class="recording-header">
            <span class="recording-name">${recording.filename}</span>
            <span class="recording-time">${recording.time}</span>
        </div>
        <div class="recording-details">
            <span>Duration: ${recording.formatted_duration}</span>
            <span>Notes: ${recording.note_count.toLocaleString()}</span>
        </div>
        <div class="recording-actions">
            <button class="play-btn">▶️ Play</button>
            <button class="download-btn">📥 Download</button>
        </div>
    `;

    // Add event listeners
    const playButton = item.querySelector('.play-btn');
    const downloadButton = item.querySelector('.download-btn');

    playButton.addEventListener('click', (e) => {
        e.stopPropagation();
        playRecording(recording);
    });

    downloadButton.addEventListener('click', (e) => {
        e.stopPropagation();
        downloadRecording(recording);
    });

    // Make the whole item clickable to play
    item.addEventListener('click', () => {
        playRecording(recording);
    });

    return item;
}

// Play a recording
async function playRecording(recording) {
    try {
        showLoading();
        
        // Clear previous recording highlights
        document.querySelectorAll('.recording-item.playing').forEach(item => {
            item.classList.remove('playing');
        });

        // Highlight current recording
        const recordingItems = document.querySelectorAll('.recording-item');
        recordingItems.forEach(item => {
            if (item.querySelector('.recording-name').textContent === recording.filename) {
                item.classList.add('playing');
            }
        });

        // Update track info
        trackName.textContent = recording.filename;
        trackDetails.textContent = `${recording.formatted_duration} • ${recording.note_count.toLocaleString()} notes • ${recording.time}`;

        // Load MIDI file into player
        const midiUrl = `/api/midi/${recording.filename}`;
        
        // Wait for the MIDI file to be fully loaded before starting
        const onMidiLoaded = () => {
            currentRecording = recording;
            
            // Show the piano player section
            pianoSection.style.display = 'block';
            
            playBtn.disabled = false;
            downloadBtn.disabled = false;
            hideLoading();
            
            // Scroll to the piano player
            pianoSection.scrollIntoView({ 
                behavior: 'smooth', 
                block: 'start' 
            });
            
            // Auto-start playback now that it's loaded
            midiPlayer.start();
            
            // Remove the event listener
            midiPlayer.removeEventListener('load', onMidiLoaded);
        };
        
        // Listen for the load event
        midiPlayer.addEventListener('load', onMidiLoaded);
        
        // Set the source (this will trigger loading)
        midiPlayer.src = midiUrl;
        
    } catch (error) {
        console.error('Error playing recording:', error);
        alert('Failed to play recording.');
        hideLoading();
    }
}

// Download a recording
function downloadRecording(recording) {
    const downloadUrl = `/api/download/${recording.filename}`;
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = recording.filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}



// Update player controls based on playback state
function updatePlayerControls(isPlaying) {
    if (isPlaying) {
        playBtn.disabled = true;
        pauseBtn.disabled = false;
        stopBtn.disabled = false;
    } else {
        playBtn.disabled = false;
        pauseBtn.disabled = true;
        stopBtn.disabled = false;
    }
}

// US East Coast timezone for all date/time operations
const EASTERN_TZ = 'America/New_York';

// Format date as YYYY-MM-DD using US East Coast timezone
function formatDate(date) {
    const formatter = new Intl.DateTimeFormat('en-CA', { 
        timeZone: EASTERN_TZ,
        year: 'numeric',
        month: '2-digit', 
        day: '2-digit'
    });
    return formatter.format(date); // Returns YYYY-MM-DD format
}

// Parse date string as US East Coast date
function parseEasternDate(dateStr) {
    const [year, month, day] = dateStr.split('-').map(Number);
    // Create date at noon Eastern time to avoid DST edge cases
    return new Date(year, month - 1, day, 12, 0, 0);
}

// Show loading overlay
function showLoading() {
    loading.classList.remove('hidden');
}

// Hide loading overlay
function hideLoading() {
    loading.classList.add('hidden');
}

// Utility function to get month name
function getMonthName(monthIndex) {
    const months = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];
    return months[monthIndex];
}

// Automatically select the most recent date with recordings
function autoSelectMostRecentDate() {
    const datesWithRecordings = Object.keys(recordingsByDate);
    
    if (datesWithRecordings.length === 0) {
        return; // No recordings found
    }
    
    // Sort dates and get the most recent one
    const mostRecentDate = datesWithRecordings.sort().pop();
    
    // Navigate to the month containing this date
    const dateObj = parseEasternDate(mostRecentDate);
    currentDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), 1);
    
    // Re-render calendar for the correct month and select the date
    renderCalendar();
    selectDate(mostRecentDate);
}

// Error handling for MIDI player
window.addEventListener('error', (event) => {
    console.error('JavaScript error:', event.error);
    hideLoading();
});

// Handle unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    hideLoading();
}); 