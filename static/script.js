// Global state
let statusEventSource = null;
let logsEventSource = null;
let currentVideoUrl = null;
let galleryRefreshInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    loadTheme();
    initializeSSE();
    updateEstimatedDuration();
    startGalleryRefresh();
    
    // Add input listeners for duration calculation
    document.getElementById('interval').addEventListener('input', updateEstimatedDuration);
    document.getElementById('frames').addEventListener('input', updateEstimatedDuration);
});

// Theme Management
function loadTheme() {
    const theme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-bs-theme', theme);
    updateThemeIcon(theme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-bs-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const icon = document.querySelector('#theme-toggle i');
    if (theme === 'dark') {
        icon.className = 'bi bi-sun';
    } else {
        icon.className = 'bi bi-moon-stars';
    }
}

// Server-Sent Events (SSE) for real-time updates
function initializeSSE() {
    // Status updates
    statusEventSource = new EventSource('/stream/status');
    statusEventSource.onmessage = function(event) {
        const status = JSON.parse(event.data);
        updateStatus(status);
        updateConnectionStatus(true);
    };
    statusEventSource.onerror = function() {
        updateConnectionStatus(false);
        // Attempt to reconnect
        setTimeout(initializeSSE, 5000);
    };

    // Log updates
    logsEventSource = new EventSource('/stream/logs');
    logsEventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        appendLog(data.log);
    };
}

function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connection-status');
    if (connected) {
        statusEl.innerHTML = '<i class="bi bi-circle-fill text-success"></i> Connected';
    } else {
        statusEl.innerHTML = '<i class="bi bi-circle-fill text-danger"></i> Disconnected';
    }
}

// Update dashboard status
function updateStatus(status) {
    const statusBadge = document.getElementById('status-badge');
    const capturedCount = document.getElementById('captured-count');
    const totalCount = document.getElementById('total-count');
    const progressBar = document.getElementById('progress-bar');
    
    // Update status badge
    statusBadge.textContent = status.status;
    statusBadge.className = 'badge ' + getStatusClass(status.status);
    
    // Update counts
    capturedCount.textContent = status.captured || 0;
    totalCount.textContent = status.total || 0;
    
    // Update progress bar
    const percentage = status.total > 0 ? Math.round((status.captured / status.total) * 100) : 0;
    progressBar.style.width = percentage + '%';
    progressBar.textContent = percentage + '%';
    progressBar.className = 'progress-bar ' + getProgressBarClass(status.status);
    
    // Update button states
    updateButtonStates(status.status);
    
    // Handle errors
    if (status.error) {
        showAlert('Error: ' + status.error, 'danger');
    }
    
    // Check for video availability
    if (status.status === 'done' || status.status === 'error') {
        checkForVideo();
    }
}

function getStatusClass(status) {
    const classes = {
        'idle': 'bg-secondary',
        'running': 'bg-primary',
        'rendering': 'bg-warning',
        'done': 'bg-success',
        'stopped': 'bg-secondary',
        'error': 'bg-danger'
    };
    return classes[status] || 'bg-secondary';
}

function getProgressBarClass(status) {
    const classes = {
        'running': 'bg-primary',
        'rendering': 'bg-warning',
        'done': 'bg-success',
        'error': 'bg-danger'
    };
    return classes[status] || '';
}

function updateButtonStates(status) {
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const intervalInput = document.getElementById('interval');
    const framesInput = document.getElementById('frames');
    
    if (status === 'running' || status === 'rendering') {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        intervalInput.disabled = true;
        framesInput.disabled = true;
    } else {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        intervalInput.disabled = false;
        framesInput.disabled = false;
    }
}

// Timelapse control
async function startTimelapse(event) {
    event.preventDefault();
    
    const interval = document.getElementById('interval').value;
    const frames = document.getElementById('frames').value;
    
    try {
        const response = await fetch('/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ interval, frames })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('Timelapse started successfully!', 'success');
            clearLogs();
        } else {
            showAlert(data.message, 'danger');
        }
    } catch (error) {
        showAlert('Failed to start timelapse: ' + error.message, 'danger');
    }
}

async function stopTimelapse() {
    try {
        const response = await fetch('/stop', {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('Timelapse stopped', 'warning');
        } else {
            showAlert(data.message, 'danger');
        }
    } catch (error) {
        showAlert('Failed to stop timelapse: ' + error.message, 'danger');
    }
}

// Log management
function appendLog(logLine) {
    const logsEl = document.getElementById('logs');
    logsEl.textContent += logLine + '\n';
    // Auto-scroll to bottom
    logsEl.scrollTop = logsEl.scrollHeight;
}

function clearLogs() {
    document.getElementById('logs').textContent = '';
}

// Gallery management
function startGalleryRefresh() {
    refreshGallery();
    galleryRefreshInterval = setInterval(refreshGallery, 3000); // Refresh every 3 seconds
}

async function refreshGallery() {
    try {
        const response = await fetch('/thumbnails');
        const data = await response.json();
        
        const imagesDiv = document.getElementById('images');
        const noImagesMsg = document.getElementById('no-images-msg');
        const imageCount = document.getElementById('image-count');
        
        if (data.images && data.images.length > 0) {
            imagesDiv.innerHTML = '';
            noImagesMsg.style.display = 'none';
            imageCount.textContent = data.images.length;
            
            data.images.forEach(url => {
                const col = document.createElement('div');
                col.className = 'col-6 col-sm-4 col-md-3 col-lg-2 mb-3';
                
                const img = document.createElement('img');
                img.src = url;
                img.className = 'img-thumbnail gallery-image';
                img.alt = 'Captured frame';
                img.loading = 'lazy';
                img.onclick = () => showImageModal(url);
                
                col.appendChild(img);
                imagesDiv.appendChild(col);
            });
            
            imagesDiv.className = 'image-gallery row';
        } else {
            imagesDiv.innerHTML = '';
            noImagesMsg.style.display = 'block';
            imageCount.textContent = '0';
        }
    } catch (error) {
        console.error('Failed to refresh gallery:', error);
    }
}

function showImageModal(imageUrl) {
    // Create a simple modal to show full-size image
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.innerHTML = `
        <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Image Preview</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body text-center">
                    <img src="${imageUrl}" class="img-fluid" alt="Frame preview">
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
    modal.addEventListener('hidden.bs.modal', () => modal.remove());
}

// Video management
async function checkForVideo() {
    try {
        const response = await fetch('/video');
        const data = await response.json();
        
        const noVideoMsg = document.getElementById('no-video-msg');
        const videoReady = document.getElementById('video-ready');
        const videoPlayer = document.getElementById('videoPlayer');
        
        if (data.video) {
            noVideoMsg.style.display = 'none';
            videoReady.style.display = 'block';
            videoPlayer.src = data.video;
            currentVideoUrl = data.video;
        } else {
            noVideoMsg.style.display = 'block';
            videoReady.style.display = 'none';
        }
    } catch (error) {
        console.error('Failed to check for video:', error);
    }
}

function downloadVideo() {
    if (currentVideoUrl) {
        // Extract filename from URL
        const filename = currentVideoUrl.split('/').pop();
        window.location.href = '/download_video/' + filename;
    }
}

// Utility functions
function updateEstimatedDuration() {
    const interval = parseInt(document.getElementById('interval').value) || 0;
    const frames = parseInt(document.getElementById('frames').value) || 0;
    const totalSeconds = interval * frames;
    
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    
    let duration = '';
    if (hours > 0) duration += hours + 'h ';
    if (minutes > 0) duration += minutes + 'm ';
    duration += seconds + 's';
    
    document.getElementById('estimated-duration').textContent = duration;
}

function showAlert(message, type) {
    const alertContainer = document.getElementById('alert-container');
    const alertId = 'alert-' + Date.now();
    
    const alert = document.createElement('div');
    alert.id = alertId;
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    alertContainer.appendChild(alert);
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        const alertEl = document.getElementById(alertId);
        if (alertEl) {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alertEl);
            bsAlert.close();
        }
    }, 5000);
}

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (statusEventSource) statusEventSource.close();
    if (logsEventSource) logsEventSource.close();
    if (galleryRefreshInterval) clearInterval(galleryRefreshInterval);
});

