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
    
    // iOS Safari audio fix: Initialize audio context on first user interaction
    setupiOSAudioFix();
    
    setupEventListeners();
    await loadRecordings();
    renderCalendar();
    
    // Check for shared recording link parameters
    const urlParams = new URLSearchParams(window.location.search);
    const shareDate = urlParams.get('date');
    const shareFile = urlParams.get('file');
    
    if (shareDate && shareFile) {
        // Handle shared recording link
        await handleSharedRecording(shareDate, shareFile);
    } else {
        // Automatically select the most recent date with recordings
        autoSelectMostRecentDate();
    }
    
    hideLoading();
});

// iOS Safari audio context fix
function setupiOSAudioFix() {
    let audioContextInitialized = false;
    
    // Function to initialize audio context on iOS
    const initializeAudioContext = async () => {
        if (audioContextInitialized) return;
        
        try {
            // Resume any suspended audio contexts (iOS Safari requirement)
            if (window.Tone && window.Tone.context && window.Tone.context.state === 'suspended') {
                await window.Tone.context.resume();
                console.log('🎵 Audio context resumed for iOS');
            }
            
            // Try to access the audio context through the MIDI player
            if (midiPlayer && midiPlayer.player && midiPlayer.player._audioContext) {
                const ctx = midiPlayer.player._audioContext;
                if (ctx.state === 'suspended') {
                    await ctx.resume();
                    console.log('🎵 MIDI player audio context resumed for iOS');
                }
            }
            
            audioContextInitialized = true;
            
            // Remove the event listeners once initialized
            document.removeEventListener('touchstart', initializeAudioContext);
            document.removeEventListener('touchend', initializeAudioContext);
            document.removeEventListener('click', initializeAudioContext);
            
        } catch (error) {
            console.error('Failed to initialize audio context:', error);
        }
    };
    
    // Add event listeners for user interactions (required for iOS)
    document.addEventListener('touchstart', initializeAudioContext);
    document.addEventListener('touchend', initializeAudioContext);
    document.addEventListener('click', initializeAudioContext);
}

// Setup event listeners
function setupEventListeners() {
    // Calendar controls
    prevMonthBtn.addEventListener('click', () => {
        // Don't allow going back before March 2025
        if (prevMonthBtn.disabled) {
            return; // Exit if button is disabled
        }
        
        currentDate.setMonth(currentDate.getMonth() - 1);
        renderCalendar();
    });

    nextMonthBtn.addEventListener('click', () => {
        // Don't allow going beyond the current month
        if (nextMonthBtn.disabled) {
            return; // Exit if button is disabled
        }
        
        currentDate.setMonth(currentDate.getMonth() + 1);
        renderCalendar();
    });

    todayBtn.addEventListener('click', () => {
        // Get current date in Eastern timezone (regardless of user's timezone)
        const todayEastern = getCurrentEasternDate();
        currentDate = new Date(todayEastern.getFullYear(), todayEastern.getMonth(), 1); // First of current month
        renderCalendar();
        selectDate(formatDate(todayEastern));
    });

    // Player controls
    playBtn.addEventListener('click', async () => {
        if (midiPlayer && currentRecording) {
            try {
                // Ensure audio context is ready before playing (especially important for iOS)
                await ensureAudioContextReady();
                midiPlayer.start();
                hidePlayPrompt(); // Hide any play prompt that might be showing
            } catch (error) {
                console.error('Failed to start playback:', error);
                alert('Unable to start audio playback. Please try again.');
            }
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

    // Enable/disable navigation buttons based on date limits
    const earliestDate = new Date(2025, 2, 1); // March 2025 (month is 0-indexed)
    const currentMonthDate = new Date(year, month, 1);
    
    // Get current month in Eastern timezone (always US East Coast, regardless of user's timezone)
    const nowEastern = getCurrentEasternDate();
    const currentRealMonth = new Date(nowEastern.getFullYear(), nowEastern.getMonth(), 1);
    
    // Disable previous month if at earliest allowed date (March 2025)
    prevMonthBtn.disabled = currentMonthDate <= earliestDate;
    
    // Disable next month if at current month
    nextMonthBtn.disabled = currentMonthDate >= currentRealMonth;

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

// Convert 24-hour time to 12-hour format with AM/PM
function formatTime12Hour(time24) {
    const [hours, minutes, seconds] = time24.split(':');
    const hour24 = parseInt(hours);
    const hour12 = hour24 === 0 ? 12 : hour24 > 12 ? hour24 - 12 : hour24;
    const ampm = hour24 >= 12 ? 'PM' : 'AM';
    return `${hour12}:${minutes}:${seconds} ${ampm}`;
}

// Create a recording item element
function createRecordingItem(recording) {
    const item = document.createElement('div');
    item.className = 'recording-item';
    
    const formattedTime = formatTime12Hour(recording.time);
    
    item.innerHTML = `
        <div class="recording-header">
            <div class="recording-meta">
                <span class="recording-time">🕒 ${formattedTime}</span>
                <span class="recording-duration">⏱️ ${recording.formatted_duration}</span>
                <span class="recording-notes">🎶 ${recording.note_count.toLocaleString()} notes</span>
            </div>
        </div>
        <div class="recording-actions">
            <button class="play-btn">▶️ Play</button>
            <button class="share-btn">🔗 Share</button>
            <button class="download-btn">📥 Download MIDI</button>
            <button class="download-mp3-btn">🎵 Download MP3</button>
        </div>
    `;

    // Add event listeners
    const playButton = item.querySelector('.play-btn');
    const downloadButton = item.querySelector('.download-btn');
    const shareButton = item.querySelector('.share-btn');
    const downloadMp3Button = item.querySelector('.download-mp3-btn');

    playButton.addEventListener('click', async (e) => {
        e.stopPropagation();
        // Ensure audio context is ready for iOS
        try {
            await ensureAudioContextReady();
        } catch (error) {
            console.warn('Audio context preparation failed:', error);
        }
        playRecording(recording);
    });

    downloadButton.addEventListener('click', (e) => {
        e.stopPropagation();
        downloadRecording(recording);
    });

    shareButton.addEventListener('click', (e) => {
        e.stopPropagation();
        shareRecording(recording);
    });

    downloadMp3Button.addEventListener('click', (e) => {
        e.stopPropagation();
        downloadMp3(recording);
    });

    // Make the whole item clickable to play
    item.addEventListener('click', async () => {
        // Ensure audio context is ready for iOS
        try {
            await ensureAudioContextReady();
        } catch (error) {
            console.warn('Audio context preparation failed:', error);
        }
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
        const formattedTime = formatTime12Hour(recording.time);
        recordingItems.forEach(item => {
            if (item.querySelector('.recording-time').textContent === `🕒 ${formattedTime}`) {
                item.classList.add('playing');
            }
        });

        // Update track info
        const formattedTimeForTitle = formatTime12Hour(recording.time);
        trackName.textContent = `Piano Recording - ${formattedTimeForTitle}`;
        trackDetails.textContent = `${recording.formatted_duration} • ${recording.note_count.toLocaleString()} notes`;

        // Load MIDI file into player
        const midiUrl = `/api/midi/${recording.filename}`;
        
        // Wait for the MIDI file to be fully loaded before starting
        const onMidiLoaded = async () => {
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
            
            // Don't auto-start on iOS Safari due to audio policy restrictions
            const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
            if (!isIOS) {
                // Auto-start playback on desktop/non-iOS devices
                try {
                    // Ensure audio context is ready before playing
                    await ensureAudioContextReady();
                    midiPlayer.start();
                } catch (error) {
                    console.log('Auto-play failed (likely due to browser policy):', error);
                    // Show a message to the user
                    showPlayPrompt();
                }
            } else {
                // On iOS, show a prompt to the user to manually start playback
                showPlayPrompt();
            }
            
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

// Share a recording by copying a direct link to clipboard
async function shareRecording(recording) {
    try {
        // Get the date for this recording from selectedDate
        const shareUrl = new URL(window.location.href);
        shareUrl.search = ''; // Clear existing parameters
        shareUrl.searchParams.set('date', selectedDate);
        shareUrl.searchParams.set('file', recording.filename);
        
        // Copy to clipboard
        await navigator.clipboard.writeText(shareUrl.toString());
        
        // Show success feedback
        showShareSuccess();
        
    } catch (error) {
        console.error('Failed to copy to clipboard:', error);
        // Fallback: show the URL in a prompt for manual copying
        const shareUrl = new URL(window.location.href);
        shareUrl.search = '';
        shareUrl.searchParams.set('date', selectedDate);
        shareUrl.searchParams.set('file', recording.filename);
        prompt('Copy this link to share:', shareUrl.toString());
    }
}


// Download MP3 version of a recording
async function downloadMp3(recording) {
    try {
        // Show loading state with custom message
        showLoading('Rendering MP3...');
        
        // Make request to convert MIDI to MP3
        const response = await fetch(`/api/convert-to-mp3/${recording.filename}`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error(`Failed to convert to MP3: ${response.statusText}`);
        }
        
        // Get the MP3 blob
        const blob = await response.blob();
        
        // Create download link
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = recording.filename.replace('.mid', '.mp3');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Clean up the blob URL
        URL.revokeObjectURL(url);
        
        hideLoading();
        
    } catch (error) {
        console.error('Failed to download MP3:', error);
        alert('Failed to convert to MP3. Please try again.');
        hideLoading();
    }
}



// Ensure audio context is ready for playback (iOS fix)
async function ensureAudioContextReady() {
    try {
        // Resume Tone.js audio context if suspended
        if (window.Tone && window.Tone.context && window.Tone.context.state === 'suspended') {
            await window.Tone.context.resume();
            console.log('🎵 Tone.js audio context resumed');
        }
        
        // Resume MIDI player audio context if suspended
        if (midiPlayer && midiPlayer.player && midiPlayer.player._audioContext) {
            const ctx = midiPlayer.player._audioContext;
            if (ctx.state === 'suspended') {
                await ctx.resume();
                console.log('🎵 MIDI player audio context resumed');
            }
        }
    } catch (error) {
        console.error('Failed to ensure audio context is ready:', error);
        throw error;
    }
}

// Show play prompt for iOS users
function showPlayPrompt() {
    // Check if prompt already exists
    let prompt = document.getElementById('iosPlayPrompt');
    if (!prompt) {
        prompt = document.createElement('div');
        prompt.id = 'iosPlayPrompt';
        prompt.innerHTML = `
            <div style="
                background: #007AFF; 
                color: white; 
                padding: 12px 20px; 
                border-radius: 8px; 
                margin: 10px 0; 
                text-align: center;
                font-size: 14px;
                box-shadow: 0 2px 10px rgba(0,122,255,0.3);
            ">
                🎵 Tap the Play button to start audio playback
            </div>
        `;
        
        // Insert after track info
        const trackInfo = document.getElementById('trackInfo');
        trackInfo.parentNode.insertBefore(prompt, trackInfo.nextSibling);
    }
    prompt.style.display = 'block';
}

// Hide play prompt
function hidePlayPrompt() {
    const prompt = document.getElementById('iosPlayPrompt');
    if (prompt) {
        prompt.style.display = 'none';
    }
}

// Show success message when share link is copied to clipboard
function showShareSuccess() {
    // Check if message already exists
    let message = document.getElementById('shareSuccessMessage');
    if (!message) {
        message = document.createElement('div');
        message.id = 'shareSuccessMessage';
        message.innerHTML = `
            <div style="
                background: #28a745; 
                color: white; 
                padding: 12px 20px; 
                border-radius: 8px; 
                margin: 10px 0; 
                text-align: center;
                font-size: 14px;
                box-shadow: 0 2px 10px rgba(40,167,69,0.3);
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 1000;
                animation: slideIn 0.3s ease-out;
            ">
                🔗 Share link copied to clipboard!
            </div>
        `;
        document.body.appendChild(message);
    }
    
    message.style.display = 'block';
    
    // Hide after 3 seconds
    setTimeout(() => {
        if (message) {
            message.style.display = 'none';
        }
    }, 3000);
}

// Update player controls based on playback state
function updatePlayerControls(isPlaying) {
    if (isPlaying) {
        playBtn.disabled = true;
        pauseBtn.disabled = false;
        stopBtn.disabled = false;
        hidePlayPrompt(); // Hide prompt when playing
    } else {
        playBtn.disabled = false;
        pauseBtn.disabled = true;
        stopBtn.disabled = false;
    }
}

// US East Coast timezone for all date/time operations
const EASTERN_TZ = 'America/New_York';

// Get current date/time in Eastern timezone, regardless of user's local timezone
function getCurrentEasternDate() {
    const now = new Date();
    
    // Use Intl.DateTimeFormat to get Eastern timezone components
    const easternFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: EASTERN_TZ,
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
        hour12: false
    });
    
    const parts = easternFormatter.formatToParts(now);
    const partsMap = {};
    parts.forEach(part => {
        partsMap[part.type] = parseInt(part.value);
    });
    
    // Create a new Date object with Eastern timezone values
    return new Date(
        partsMap.year,
        partsMap.month - 1, // JavaScript months are 0-indexed
        partsMap.day,
        partsMap.hour,
        partsMap.minute,
        partsMap.second
    );
}

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

// Show loading overlay with optional custom message
function showLoading(message = 'Loading recordings...') {
    const loadingText = loading.querySelector('p');
    if (loadingText) {
        loadingText.textContent = message;
    }
    loading.classList.remove('hidden');
}

// Hide loading overlay and reset message
function hideLoading() {
    const loadingText = loading.querySelector('p');
    if (loadingText) {
        loadingText.textContent = 'Loading recordings...';
    }
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

// Update social media metadata with detailed recording information
function updateSocialMetadataWithRecording(recording, shareDate) {
    const dateObj = parseEasternDate(shareDate);
    const formattedDate = dateObj.toLocaleDateString('en-US', { 
        weekday: 'long',
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
    });
    
    const formattedTime = formatTime12Hour(recording.time);
    const customTitle = `Piano Recording - ${formattedDate} at ${formattedTime}`;
    const customDescription = `Listen to this ${recording.formatted_duration} piano recording (${recording.note_count.toLocaleString()} notes) from Chris's Disklavier database. Recorded on ${formattedDate} at ${formattedTime}. Browse more recordings and play with interactive piano roll visualization.`;
    
    // Update Open Graph tags
    document.querySelector('meta[property="og:title"]').setAttribute('content', customTitle);
    document.querySelector('meta[property="og:description"]').setAttribute('content', customDescription);
    
    // Update Twitter tags
    document.querySelector('meta[name="twitter:title"]').setAttribute('content', customTitle);
    document.querySelector('meta[name="twitter:description"]').setAttribute('content', customDescription);
    
    // Update page title
    document.title = customTitle + ' - Chris\'s Piano DB';
}

// Handle shared recording link by navigating to date and auto-playing file
async function handleSharedRecording(shareDate, shareFile) {
    try {
        // Check if the date exists and has recordings
        const recordings = recordingsByDate[shareDate] || [];
        const targetRecording = recordings.find(r => r.filename === shareFile);
        
        if (!targetRecording) {
            console.warn(`Shared recording not found: ${shareFile} on ${shareDate}`);
            // Fall back to normal behavior
            autoSelectMostRecentDate();
            return;
        }
        
        // Update social metadata with detailed recording information
        updateSocialMetadataWithRecording(targetRecording, shareDate);
        
        // Navigate to the correct month containing this date
        const dateObj = parseEasternDate(shareDate);
        currentDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), 1);
        
        // Re-render calendar for the correct month and select the date
        renderCalendar();
        selectDate(shareDate);
        
        // Wait a moment for the UI to update, then auto-play the recording
        setTimeout(async () => {
            try {
                await ensureAudioContextReady();
                await playRecording(targetRecording);
                
                // Clean up URL parameters and reset title after successful load
                const cleanUrl = new URL(window.location.href);
                cleanUrl.search = '';
                window.history.replaceState({}, '', cleanUrl.toString());
                
                // Reset page title to normal
                document.title = "Chris's Piano DB";
                
            } catch (error) {
                console.error('Failed to auto-play shared recording:', error);
            }
        }, 500); // Small delay to ensure UI is ready
        
    } catch (error) {
        console.error('Error handling shared recording:', error);
        // Fall back to normal behavior
        autoSelectMostRecentDate();
    }
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