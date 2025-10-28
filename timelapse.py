from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import subprocess, os, json, signal, time, threading
from datetime import datetime

app = Flask(__name__)

# Configuration - Use local paths for development/testing
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(BASE_DIR, "timelapse_status.json")
TIMELAPSE_SCRIPT = os.path.join(BASE_DIR, "timelapse.sh")

# For production on Raspberry Pi, uncomment these:
# STATUS_FILE = "/mnt/share/timelapse_status.json"
# TIMELAPSE_SCRIPT = "/usr/local/bin/timelapse.sh"

process = None  # track the running timelapse
log_position = {}  # track log file positions for streaming

def read_status():
    """Read the current status from the JSON file"""
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE) as f:
                return json.load(f)
    except Exception as e:
        app.logger.error(f"Error reading status: {e}")
    return {"status": "idle", "captured": 0, "total": 0, "error": None}

def find_latest_folder():
    """Find the most recent timelapse folder"""
    base = os.path.dirname(STATUS_FILE)
    try:
        folders = [os.path.join(base, d) for d in os.listdir(base) 
                   if os.path.isdir(os.path.join(base, d)) and d.startswith("timelapse_")]
        if not folders:
            return None
        return max(folders, key=os.path.getmtime)
    except Exception as e:
        app.logger.error(f"Error finding folder: {e}")
        return None

@app.route("/")
def index():
    return render_template("index.html", status=read_status())

@app.route("/start", methods=["POST"])
def start_timelapse():
    """Start a new timelapse capture"""
    global process
    try:
        data = request.get_json() if request.is_json else request.form
        interval = data.get("interval", "5")
        frames = data.get("frames", "10")
        
        # Validate inputs
        try:
            interval_int = int(interval)
            frames_int = int(frames)
            if interval_int < 1 or frames_int < 1:
                return jsonify({"success": False, "message": "Interval and frames must be positive"}), 400
        except ValueError:
            return jsonify({"success": False, "message": "Invalid interval or frames value"}), 400
        
        if process and process.poll() is None:
            return jsonify({"success": False, "message": "Timelapse already running"}), 400
        
        if not os.path.exists(TIMELAPSE_SCRIPT):
            return jsonify({"success": False, "message": "Timelapse script not found"}), 500

        process = subprocess.Popen([TIMELAPSE_SCRIPT, str(interval_int), str(frames_int)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        app.logger.info(f"Started timelapse: {frames_int} frames at {interval_int}s interval")
        return jsonify({"success": True, "message": "Timelapse started"})
    except Exception as e:
        app.logger.error(f"Error starting timelapse: {e}")
        return jsonify({"success": False, "message": "Failed to start timelapse"}), 500

@app.route("/stop", methods=["POST"])
def stop_timelapse():
    """Stop the running timelapse"""
    global process
    try:
        if process and process.poll() is None:
            process.send_signal(signal.SIGINT)
            app.logger.info("Stopped timelapse")
            return jsonify({"success": True, "message": "Timelapse stopped"})
        return jsonify({"success": False, "message": "No timelapse running"}), 400
    except Exception as e:
        app.logger.error(f"Error stopping timelapse: {e}")
        return jsonify({"success": False, "message": "Failed to stop timelapse"}), 500

@app.route("/status")
def status():
    return jsonify(read_status())

@app.route("/logs")
def logs():
    """Get the latest log entries"""
    try:
        folder = find_latest_folder()
        if not folder:
            return jsonify({"logs": []})
        log_file = os.path.join(folder, "timelapse.log")
        if not os.path.exists(log_file):
            return jsonify({"logs": []})
        with open(log_file) as f:
            lines = f.readlines()
        return jsonify({"logs": lines[-50:]})  # last 50 lines
    except Exception as e:
        app.logger.error(f"Error reading logs: {e}")
        return jsonify({"logs": [], "error": "Failed to read logs"})

def stream_logs():
    """Generator function for streaming logs via SSE"""
    client_id = id(threading.current_thread())
    log_position[client_id] = 0
    
    try:
        while True:
            folder = find_latest_folder()
            if folder:
                log_file = os.path.join(folder, "timelapse.log")
                if os.path.exists(log_file):
                    with open(log_file) as f:
                        f.seek(log_position.get(client_id, 0))
                        new_lines = f.readlines()
                        log_position[client_id] = f.tell()
                        
                        if new_lines:
                            for line in new_lines:
                                yield f"data: {json.dumps({'log': line.strip()})}\n\n"
            
            time.sleep(1)
    except GeneratorExit:
        log_position.pop(client_id, None)

@app.route("/stream/logs")
def stream_logs_endpoint():
    """SSE endpoint for streaming logs"""
    return Response(stream_logs(), mimetype="text/event-stream")

def stream_status():
    """Generator function for streaming status updates via SSE"""
    while True:
        status = read_status()
        yield f"data: {json.dumps(status)}\n\n"
        time.sleep(1)

@app.route("/stream/status")
def stream_status_endpoint():
    """SSE endpoint for streaming status updates"""
    return Response(stream_status(), mimetype="text/event-stream")

@app.route("/thumbnails")
def thumbnails():
    """Get list of captured thumbnail images"""
    try:
        folder = find_latest_folder()
        if not folder:
            return jsonify({"images": []})
        video_frames = os.path.join(folder, "video_frames")
        if not os.path.exists(video_frames):
            return jsonify({"images": []})
        files = sorted(os.listdir(video_frames))[-50:]  # last 50 images
        urls = [f"/frames/{file}" for file in files if file.endswith(('.jpg', '.jpeg', '.png'))]
        return jsonify({"images": urls})
    except Exception as e:
        app.logger.error(f"Error getting thumbnails: {e}")
        return jsonify({"images": [], "error": "Failed to get thumbnails"})

@app.route("/frames/<filename>")
def frame_file(filename):
    """Serve individual frame image files"""
    try:
        folder = find_latest_folder()
        if not folder:
            return "Folder not found", 404
        frames_path = os.path.join(folder, "video_frames")
        return send_from_directory(frames_path, filename)
    except Exception as e:
        app.logger.error(f"Error serving frame: {e}")
        return "Frame not found", 404

@app.route("/video")
def video():
    """Get information about the rendered video"""
    try:
        folder = find_latest_folder()
        if not folder:
            return jsonify({"video": None})
        video_dir = os.path.join(folder, "video")
        if not os.path.exists(video_dir):
            return jsonify({"video": None})
        videos = sorted(os.listdir(video_dir))
        if not videos:
            return jsonify({"video": None})
        return jsonify({"video": f"/video_file/{videos[-1]}"})
    except Exception as e:
        app.logger.error(f"Error getting video: {e}")
        return jsonify({"video": None, "error": "Failed to get video"})

@app.route("/video_file/<filename>")
def video_file(filename):
    """Download/stream the video file"""
    try:
        folder = find_latest_folder()
        if not folder:
            return "Folder not found", 404
        video_path = os.path.join(folder, "video")
        return send_from_directory(video_path, filename, as_attachment=False)
    except Exception as e:
        app.logger.error(f"Error serving video: {e}")
        return "Video not found", 404

@app.route("/download_video/<filename>")
def download_video(filename):
    """Force download of the video file"""
    try:
        folder = find_latest_folder()
        if not folder:
            return "Folder not found", 404
        video_path = os.path.join(folder, "video")
        return send_from_directory(video_path, filename, as_attachment=True)
    except Exception as e:
        app.logger.error(f"Error downloading video: {e}")
        return "Video not found", 404

if __name__ == "__main__":
    import os
    # Use debug mode only in development, controlled by environment variable
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)


