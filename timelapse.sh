#!/bin/bash

# Timelapse script for Raspberry Pi
# Arguments: $1 = interval (seconds), $2 = number of frames

INTERVAL=${1:-5}
FRAMES=${2:-10}

# Use BASE_DIR environment variable or default to script directory
if [ -z "$BASE_DIR" ]; then
    # Use /mnt/share on Raspberry Pi if it exists, otherwise use script directory
    if [ -d "/mnt/share" ] && [ -w "/mnt/share" ]; then
        BASE_DIR="/mnt/share"
    else
        BASE_DIR="$(dirname "$(realpath "$0")")"
    fi
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="$BASE_DIR/timelapse_$TIMESTAMP"
VIDEO_FRAMES_DIR="$OUTPUT_DIR/video_frames"
VIDEO_DIR="$OUTPUT_DIR/video"
LOG_FILE="$OUTPUT_DIR/timelapse.log"
STATUS_FILE="$BASE_DIR/timelapse_status.json"

# Create directories
mkdir -p "$VIDEO_FRAMES_DIR"
mkdir -p "$VIDEO_DIR"

# Initialize log
echo "[$(date)] Starting timelapse: $FRAMES frames at $INTERVAL second intervals" > "$LOG_FILE"

# Initialize status
cat > "$STATUS_FILE" <<EOF
{
    "status": "running",
    "captured": 0,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": null
}
EOF

# Cleanup function
cleanup() {
    echo "[$(date)] Received interrupt signal, cleaning up..." >> "$LOG_FILE"
    
    # Check if we have any frames captured
    if [ $CAPTURED -gt 0 ]; then
        echo "[$(date)] Creating video from $CAPTURED captured frames..." >> "$LOG_FILE"
        
        # Update status to rendering
        cat > "$STATUS_FILE" <<EOF
{
    "status": "rendering",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": null
}
EOF
        
        # Create video using ffmpeg
        VIDEO_FILE="$VIDEO_DIR/timelapse_$TIMESTAMP.mp4"
        if command -v ffmpeg &> /dev/null; then
            echo "[$(date)] Creating video with ffmpeg" >> "$LOG_FILE"
            ffmpeg -framerate 30 -pattern_type glob -i "$VIDEO_FRAMES_DIR/*.jpg" \
                -c:v libx264 -pix_fmt yuv420p -preset medium -crf 23 \
                "$VIDEO_FILE" >> "$LOG_FILE" 2>&1
            
            if [ $? -eq 0 ]; then
                echo "[$(date)] Video created successfully: $VIDEO_FILE" >> "$LOG_FILE"
                cat > "$STATUS_FILE" <<EOF
{
    "status": "stopped",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "video": "$VIDEO_FILE",
    "error": null
}
EOF
            else
                echo "[$(date)] Error creating video" >> "$LOG_FILE"
                cat > "$STATUS_FILE" <<EOF
{
    "status": "stopped",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": "Failed to create video"
}
EOF
            fi
        else
            echo "[$(date)] Warning: ffmpeg not found, skipping video creation" >> "$LOG_FILE"
            cat > "$STATUS_FILE" <<EOF
{
    "status": "stopped",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": "ffmpeg not available"
}
EOF
        fi
    else
        # No frames captured, just set stopped status
        cat > "$STATUS_FILE" <<EOF
{
    "status": "stopped",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": null
}
EOF
    fi
    
    exit 0
}

trap cleanup SIGINT SIGTERM

# Capture frames
CAPTURED=0
while [ $CAPTURED -lt $FRAMES ]; do
    CAPTURED=$((CAPTURED + 1))
    FRAME_FILE="$VIDEO_FRAMES_DIR/frame_$(printf "%04d" $CAPTURED).jpg"
    
    echo "[$(date)] Capturing frame $CAPTURED/$FRAMES" >> "$LOG_FILE"
    
    # Check if raspistill is available (Raspberry Pi), otherwise use a placeholder
    if command -v raspistill &> /dev/null; then
        raspistill -o "$FRAME_FILE" -w 1920 -h 1080 -q 85 -t 1000 2>> "$LOG_FILE"
    else
        # For testing without a Pi camera, create a placeholder image
        echo "[$(date)] Warning: raspistill not found, creating placeholder image" >> "$LOG_FILE"
        convert -size 1920x1080 -pointsize 72 -gravity center \
            label:"Frame $CAPTURED\n$(date +%H:%M:%S)" "$FRAME_FILE" 2>> "$LOG_FILE" || \
        touch "$FRAME_FILE"
    fi
    
    if [ ! -f "$FRAME_FILE" ]; then
        echo "[$(date)] Error: Failed to capture frame $CAPTURED" >> "$LOG_FILE"
        cat > "$STATUS_FILE" <<EOF
{
    "status": "error",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": "Failed to capture frame $CAPTURED"
}
EOF
        exit 1
    fi
    
    # Update status
    cat > "$STATUS_FILE" <<EOF
{
    "status": "running",
    "captured": $CAPTURED,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": null
}
EOF
    
    # Wait for interval (unless this is the last frame)
    if [ $CAPTURED -lt $FRAMES ]; then
        sleep $INTERVAL
    fi
done

echo "[$(date)] All frames captured, starting video rendering" >> "$LOG_FILE"

# Update status to rendering
cat > "$STATUS_FILE" <<EOF
{
    "status": "rendering",
    "captured": $FRAMES,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": null
}
EOF

# Create video using ffmpeg
VIDEO_FILE="$VIDEO_DIR/timelapse_$TIMESTAMP.mp4"
if command -v ffmpeg &> /dev/null; then
    echo "[$(date)] Creating video with ffmpeg" >> "$LOG_FILE"
    ffmpeg -framerate 30 -pattern_type glob -i "$VIDEO_FRAMES_DIR/*.jpg" \
        -c:v libx264 -pix_fmt yuv420p -preset medium -crf 23 \
        "$VIDEO_FILE" >> "$LOG_FILE" 2>&1
    
    if [ $? -eq 0 ]; then
        echo "[$(date)] Video created successfully: $VIDEO_FILE" >> "$LOG_FILE"
        cat > "$STATUS_FILE" <<EOF
{
    "status": "done",
    "captured": $FRAMES,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "video": "$VIDEO_FILE",
    "error": null
}
EOF
    else
        echo "[$(date)] Error creating video" >> "$LOG_FILE"
        cat > "$STATUS_FILE" <<EOF
{
    "status": "error",
    "captured": $FRAMES,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": "Failed to create video"
}
EOF
        exit 1
    fi
else
    echo "[$(date)] Warning: ffmpeg not found, skipping video creation" >> "$LOG_FILE"
    cat > "$STATUS_FILE" <<EOF
{
    "status": "done",
    "captured": $FRAMES,
    "total": $FRAMES,
    "folder": "$OUTPUT_DIR",
    "error": "ffmpeg not available"
}
EOF
fi

echo "[$(date)] Timelapse complete!" >> "$LOG_FILE"
exit 0
