from flask import Flask, render_template, request, jsonify, send_from_directory
import subprocess, os, json, signal

app = Flask(__name__)

STATUS_FILE = "/mnt/share/timelapse_status.json"
TIMELAPSE_SCRIPT = "/usr/local/bin/timelapse.sh"

process = None  # track the running timelapse

def read_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {"status": "idle", "captured": 0, "total": 0}

def find_latest_folder():
    base = "/mnt/share"
    folders = [os.path.join(base, d) for d in os.listdir(base) if d.startswith("timelapse_")]
    if not folders: return None
    return max(folders, key=os.path.getmtime)

@app.route("/")
def index():
    return render_template("index.html", status=read_status())

@app.route("/start", methods=["POST"])
def start_timelapse():
    global process
    interval = request.form.get("interval", "5")
    frames = request.form.get("frames", "10")
    if process and process.poll() is None:
        return jsonify({"message": "Timelapse already running"}), 400

    process = subprocess.Popen([TIMELAPSE_SCRIPT, interval, frames])
    return jsonify({"message": "Timelapse started"})

@app.route("/stop", methods=["POST"])
def stop_timelapse():
    global process
    if process and process.poll() is None:
        process.send_signal(signal.SIGINT)
        return jsonify({"message": "Timelapse stopped"})
    return jsonify({"message": "No timelapse running"}), 400

@app.route("/status")
def status():
    return jsonify(read_status())

@app.route("/logs")
def logs():
    folder = find_latest_folder()
    if not folder:
        return jsonify({"logs": "No timelapse folder found"})
    log_file = os.path.join(folder, "timelapse.log")
    if not os.path.exists(log_file):
        return jsonify({"logs": "No log file found"})
    with open(log_file) as f:
        lines = f.readlines()
    return jsonify({"logs": lines[-50:]})  # last 50 lines

@app.route("/thumbnails")
def thumbnails():
    folder = find_latest_folder()
    if not folder:
        return jsonify({"images": []})
    video_frames = os.path.join(folder, "video_frames")
    if not os.path.exists(video_frames):
        return jsonify({"images": []})
    files = sorted(os.listdir(video_frames))[-20:]  # last 20 images
    urls = [f"/frames/{file}" for file in files]
    return jsonify({"images": urls})

@app.route("/frames/<filename>")
def frame_file(filename):
    folder = find_latest_folder()
    return send_from_directory(os.path.join(folder, "video_frames"), filename)

@app.route("/video")
def video():
    folder = find_latest_folder()
    video_dir = os.path.join(folder, "video")
    if not os.path.exists(video_dir):
        return jsonify({"video": None})
    videos = sorted(os.listdir(video_dir))
    if not videos:
        return jsonify({"video": None})
    return jsonify({"video": f"/video_file/{videos[-1]}"})

@app.route("/video_file/<filename>")
def video_file(filename):
    folder = find_latest_folder()
    return send_from_directory(os.path.join(folder, "video"), filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

