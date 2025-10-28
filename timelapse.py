# ...existing code...
import os
import json
import time
import signal
import threading
import subprocess
from datetime import datetime
from queue import Queue, Empty

from flask import Flask, render_template, request, jsonify, Response, send_from_directory

app = Flask(__name__)

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(BASE_DIR, "timelapse_status.json")
# Production script path (Raspberry Pi)
TIMELAPSE_SCRIPT = "/usr/local/bin/timelapse.sh"
# For local development uncomment the following if you have a local script
# TIMELAPSE_SCRIPT = os.path.join(BASE_DIR, "timelapse.sh")

# Globals
process = None
process_lock = threading.Lock()
log_clients = []       # list of Queue objects for log SSE clients
status_clients = []    # list of Queue objects for status SSE clients
clients_lock = threading.Lock()
recent_logs = []       # in-memory recent log lines
MAX_RECENT_LOGS = 200

# Utilities
def safe_write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        # best-effort: try writing directly
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def read_status():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # default status
    return {"status": "idle", "captured": 0, "total": 0, "error": None, "recent_logs": []}

def write_status(data):
    # keep recent logs in file too
    data = dict(data)
    data.setdefault("recent_logs", recent_logs[-MAX_RECENT_LOGS:])
    safe_write_json(STATUS_FILE, data)
    # broadcast to status clients
    broadcast_status(data)

def broadcast_log(line):
    payload = {"log": line}
    with clients_lock:
        for q in list(log_clients):
            try:
                q.put_nowait(payload)
            except Exception:
                # if a client queue is stuck, ignore it (it will be removed on disconnect)
                pass

def broadcast_status(status_data):
    with clients_lock:
        for q in list(status_clients):
            try:
                q.put_nowait(status_data)
            except Exception:
                pass

def append_log(line):
    recent_logs.append(line)
    if len(recent_logs) > MAX_RECENT_LOGS:
        del recent_logs[:-MAX_RECENT_LOGS]
    # update status file small interval
    curr = read_status()
    curr["recent_logs"] = recent_logs[-MAX_RECENT_LOGS:]
    safe_write_json(STATUS_FILE, curr)

# Timelapse runner thread
def run_timelapse_process(interval, frames):
    global process
    start_ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_meta = {
        "start_time": start_ts,
        "status": "running",
        "captured": 0,
        "total": frames,
        "error": None,
        "recent_logs": recent_logs[-MAX_RECENT_LOGS:]
    }
    write_status(run_meta)

    try:
        with process_lock:
            # Launch subprocess; merge stderr into stdout so we capture both
            process = subprocess.Popen(
                [TIMELAPSE_SCRIPT, str(interval), str(frames)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                close_fds=True
            )

        # Read stdout/stderr live
        if process.stdout is not None:
            for raw_line in iter(process.stdout.readline, ""):
                line = raw_line.rstrip("\n")
                if line:
                    # Update in-memory/log file and broadcast
                    timestamped = f"{datetime.utcnow().isoformat()} - {line}"
                    append_log(timestamped)
                    broadcast_log(timestamped)

                    # detect simple progress info if the script emits something like "captured: X"
                    try:
                        if "captured" in line and ":" in line:
                            # naive parse e.g. "captured: 12"
                            parts = line.split(":")
                            key = parts[0].strip().lower()
                            val = int(parts[1].strip())
                            if key == "captured":
                                curr = read_status()
                                curr.update({"status": "running", "captured": val, "total": frames, "error": None})
                                write_status(curr)
                    except Exception:
                        pass

        # Wait for process to terminate
        ret = process.wait()
        end_status = "done" if ret == 0 else "error"
        curr = read_status()
        curr["status"] = end_status
        curr["captured"] = curr.get("captured", frames)
        curr["total"] = frames
        if ret != 0:
            curr["error"] = f"timelapse script exited with code {ret}"
        write_status(curr)

    except Exception as exc:
        curr = read_status()
        curr["status"] = "error"
        curr["error"] = str(exc)
        write_status(curr)
        broadcast_log(f"ERROR: {exc}")
    finally:
        with process_lock:
            process = None

# Flask endpoints
@app.route("/")
def index():
    return render_template("index.html", status=read_status())

@app.route("/start", methods=["POST"])
def start_timelapse():
    global process
    data = request.get_json() if request.is_json else request.form
    interval = data.get("interval", "5")
    frames = data.get("frames", "10")

    try:
        interval_i = int(interval)
        frames_i = int(frames)
        if interval_i < 1 or frames_i < 1:
            return jsonify({"success": False, "message": "Interval and frames must be >= 1"}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Invalid numeric values"}), 400

    if not os.path.exists(TIMELAPSE_SCRIPT) or not os.access(TIMELAPSE_SCRIPT, os.X_OK):
        return jsonify({"success": False, "message": f"Timelapse script not found or not executable: {TIMELAPSE_SCRIPT}"}), 500

    with process_lock:
        if process is not None and process.poll() is None:
            return jsonify({"success": False, "message": "Timelapse already running"}), 400

        # reset recent logs for this run
        recent_logs.clear()
        # start thread to run the process
        thread = threading.Thread(target=run_timelapse_process, args=(interval_i, frames_i), daemon=True)
        thread.start()

    return jsonify({"success": True, "message": "Timelapse started"})

@app.route("/stop", methods=["POST"])
def stop_timelapse():
    with process_lock:
        if process is None or process.poll() is not None:
            return jsonify({"success": False, "message": "No timelapse running"}), 400
        try:
            # try graceful interrupt first
            process.send_signal(signal.SIGINT)
            # update status immediately
            curr = read_status()
            curr["status"] = "idle"
            write_status(curr)
            return jsonify({"success": True, "message": "Stop signal sent"})
        except Exception as exc:
            return jsonify({"success": False, "message": f"Failed to stop: {exc}"}), 500

@app.route("/status")
def get_status():
    return jsonify(read_status())

# SSE log streaming
def sse_format_event(data):
    # data is a dict; encode as JSON string on client side or embed
    payload = json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n"

@app.route("/stream/logs")
def stream_logs():
    q = Queue()
    with clients_lock:
        log_clients.append(q)

    def generator():
        try:
            # send last N logs initially
            for line in recent_logs[-50:]:
                yield sse_format_event({"log": line})
            # then stream new lines
            while True:
                try:
                    item = q.get(timeout=15)
                    yield sse_format_event(item)
                except Empty:
                    # keepalive comment to prevent proxies/timeouts
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            # client disconnected
            pass
        finally:
            with clients_lock:
                try:
                    log_clients.remove(q)
                except ValueError:
                    pass

    return Response(generator(), mimetype="text/event-stream")

# SSE status streaming
@app.route("/stream/status")
def stream_status():
    q = Queue()
    with clients_lock:
        status_clients.append(q)

    def generator():
        try:
            # send immediate status snapshot
            yield sse_format_event(read_status())
            while True:
                try:
                    item = q.get(timeout=10)
                    yield sse_format_event(item)
                except Empty:
                    # periodically re-send current status to ensure clients stay in sync
                    yield sse_format_event(read_status())
                    time.sleep(0.5)
        except GeneratorExit:
            pass
        finally:
            with clients_lock:
                try:
                    status_clients.remove(q)
                except ValueError:
                    pass

    return Response(generator(), mimetype="text/event-stream")

# Thumbnails, frames, video endpoints rely on folder structure created by your script.
def find_latest_folder():
    # look for folders in BASE_DIR that start with "timelapse_" (script expected to create these)
    try:
        folders = [
            os.path.join(BASE_DIR, d)
            for d in os.listdir(BASE_DIR)
            if os.path.isdir(os.path.join(BASE_DIR, d)) and d.startswith("timelapse_")
        ]
        if not folders:
            return None
        return max(folders, key=os.path.getmtime)
    except Exception:
        return None

@app.route("/thumbnails")
def thumbnails():
    folder = find_latest_folder()
    if not folder:
        return jsonify({"images": []})
    frames_dir = os.path.join(folder, "video_frames")
    if not os.path.exists(frames_dir):
        return jsonify({"images": []})
    files = sorted([f for f in os.listdir(frames_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))])[-50:]
    urls = [f"/frames/{f}" for f in files]
    return jsonify({"images": urls})

@app.route("/frames/<path:filename>")
def frame_file(filename):
    folder = find_latest_folder()
    if not folder:
        return "Folder not found", 404
    frames_dir = os.path.join(folder, "video_frames")
    if not os.path.exists(frames_dir):
        return "Frame folder not found", 404
    return send_from_directory(frames_dir, filename)

@app.route("/video")
def video_info():
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

@app.route("/video_file/<path:filename>")
def video_file(filename):
    folder = find_latest_folder()
    if not folder:
        return "Folder not found", 404
    video_dir = os.path.join(folder, "video")
    if not os.path.exists(video_dir):
        return "Video folder not found", 404
    return send_from_directory(video_dir, filename, as_attachment=False)

@app.route("/download_video/<path:filename>")
def download_video(filename):
    folder = find_latest_folder()
    if not folder:
        return "Folder not found", 404
    video_dir = os.path.join(folder, "video")
    if not os.path.exists(video_dir):
        return "Video folder not found", 404
    return send_from_directory(video_dir, filename, as_attachment=True)

# Ensure status file exists on startup
if __name__ == "__main__":
    # write initial status if missing
    if not os.path.exists(STATUS_FILE):
        write_status(read_status())
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode, threaded=True)
# ...existing code...
