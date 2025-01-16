#!/usr/bin/python3

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, Response, send_from_directory
import threading
import socket
import json
import time
import signal
from collections import deque
import os
import sys
import configparser
import subprocess
import queue

from udp_streamer import UDPStreamer  # External module for UDP streaming

# Configuration File
CONFIG_FILE = "plotter.cfg"

# Default Constants
DEFAULT_CONFIG = {
    "Network": {
        "JSON_STREAM_HOST": "192.168.1.20",
        "JSON_STREAM_PORT": "8103"
    },
    "Settings": {
        "RSSI_MIN": "-80",
        "RSSI_MAX": "-40",
        "SNR_MIN": "10",
        "SNR_MAX": "30",
        "DATA_REDUNDANCY_MIN": "0",
        "DATA_REDUNDANCY_MAX": "6",
        "MAX_SAMPLES": "300",
        "SOCKET_TIMEOUT": "5",
        "DERIVATIVE_WINDOW": "10",
        "DERIVATIVE_MIN": "-2",
        "DERIVATIVE_MAX": "2",
        "FEC_REC_MIN": "0",
        "FEC_REC_MAX": "30",
        "LOST_MIN": "0",
        "LOST_MAX": "10",
        "MBIT_MIN": "0",
        "MBIT_MAX": "100",
        "UDP_IP": "127.0.0.1",
        "UDP_PORT": "5005",
        "FILE_SERVE_DIR": "/tmp"
    },
    # NEW: a section for whitelists
    "Whitelists": {
        # Comma-separated list of file paths where uploads are allowed.
        # For example: "/usr/sbin/wfb-ng.sh, /etc/wifibroadcast, /etc/gs.key"
        "ALLOWED_UPLOAD_PATHS": "/usr/sbin/wfb-ng.sh,/etc/wifibroadcast,/etc/gs.key"
    }
}

# Load configuration with defaults
config = configparser.ConfigParser()
config.read_dict(DEFAULT_CONFIG)
if os.path.exists(CONFIG_FILE):
    config.read(CONFIG_FILE)
else:
    with open(CONFIG_FILE, "w") as configfile:
        config.write(configfile)

# Parse settings from config
settings = {
    "JSON_STREAM_HOST": config.get("Network", "JSON_STREAM_HOST"),
    "JSON_STREAM_PORT": int(config.get("Network", "JSON_STREAM_PORT")),
    "RSSI_MIN": int(config.get("Settings", "RSSI_MIN")),
    "RSSI_MAX": int(config.get("Settings", "RSSI_MAX")),
    "SNR_MIN": int(config.get("Settings", "SNR_MIN")),
    "SNR_MAX": int(config.get("Settings", "SNR_MAX")),
    "DATA_REDUNDANCY_MIN": int(config.get("Settings", "DATA_REDUNDANCY_MIN")),
    "DATA_REDUNDANCY_MAX": int(config.get("Settings", "DATA_REDUNDANCY_MAX")),
    "MAX_SAMPLES": int(config.get("Settings", "MAX_SAMPLES")),
    "SOCKET_TIMEOUT": int(config.get("Settings", "SOCKET_TIMEOUT")),
    "DERIVATIVE_WINDOW": int(config.get("Settings", "DERIVATIVE_WINDOW")),
    "DERIVATIVE_MIN": float(config.get("Settings", "DERIVATIVE_MIN")),
    "DERIVATIVE_MAX": float(config.get("Settings", "DERIVATIVE_MAX")),
    "FEC_REC_MIN": int(config.get("Settings", "FEC_REC_MIN")),
    "FEC_REC_MAX": int(config.get("Settings", "FEC_REC_MAX")),
    "LOST_MIN": int(config.get("Settings", "LOST_MIN")),
    "LOST_MAX": int(config.get("Settings", "LOST_MAX")),
    "MBIT_MIN": float(config.get("Settings", "MBIT_MIN")),
    "MBIT_MAX": float(config.get("Settings", "MBIT_MAX")),
    "UDP_IP": config.get("Settings", "UDP_IP"),
    "UDP_PORT": int(config.get("Settings", "UDP_PORT")),
    "FILE_SERVE_DIR": config.get("Settings", "FILE_SERVE_DIR"),
}

# NEW: parse the whitelisted paths for upload
whitelist_raw = config.get("Whitelists", "ALLOWED_UPLOAD_PATHS", fallback="")
ALLOWED_UPLOAD_PATHS = [p.strip() for p in whitelist_raw.split(',') if p.strip()]

# Ensure FILE_SERVE_DIR exists or create it
if not os.path.isdir(settings["FILE_SERVE_DIR"]):
    try:
        os.makedirs(settings["FILE_SERVE_DIR"], exist_ok=True)
    except Exception as e:
        print(f"Warning: failed to create directory {settings['FILE_SERVE_DIR']}: {e}")

# Shared Data for Visualizations
sample_indices = deque(range(settings["MAX_SAMPLES"]), maxlen=settings["MAX_SAMPLES"])
rssi_values = {}
snr_values = {}
redundancy_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
derivative_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
all_mbit_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
out_mbit_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
colors = {}
log_interval = None  # Updated from "settings" messages

# Raw Data
raw_rssi_values = {}
raw_snr_values = {}
raw_fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
raw_lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

# UDP Streamer
udp_streamer = UDPStreamer(settings["UDP_IP"], settings["UDP_PORT"])

# Flask App
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

shutdown_flag = threading.Event()
restart_flag = threading.Event()


@app.route('/viewer')
def viewer_page():
    return render_template('viewer.html')


@app.route('/save')
def save_data():
    filename = "/tmp/data.json"
    try:
        with open(filename, 'w') as f:
            json.dump({
                'rssi': {k: list(v) for k, v in rssi_values.items()},
                'snr': {k: list(v) for k, v in snr_values.items()},
                'redundancy': list(redundancy_values),
                'derivative': list(derivative_values),
                'fec_rec': list(fec_rec_values),
                'lost': list(lost_values),
                'all_mbit': list(all_mbit_values),
                'out_mbit': list(out_mbit_values),
                'sample_indices': list(sample_indices),
                'colors': colors,
                'settings': settings,
                'log_interval': log_interval,  # Include log_interval as metadata
            }, f, indent=4)
        return send_file(filename, as_attachment=True)
    except Exception as e:
        print(f"Error saving data to file: {e}")
        return "An error occurred while saving the file. Please try again later.", 500


#########################################################################
#  HOME / SETTINGS / DATA ROUTES (EXISTING)
#########################################################################
@app.route('/')
def index():
    return render_template('index.html', settings=settings)

@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    if request.method == 'POST':
        for key in settings:
            if key in request.form:
                if isinstance(settings[key], int):
                    settings[key] = int(request.form[key])
                elif isinstance(settings[key], float):
                    settings[key] = float(request.form[key])
                else:
                    settings[key] = request.form[key]

        # Save to configuration file
        for section in config.sections():
            for key in config[section]:
                if key.upper() in settings:
                    config[section][key] = str(settings[key.upper()])

        with open(CONFIG_FILE, "w") as configfile:
            config.write(configfile)

        global sample_indices
        global rssi_values, snr_values
        global redundancy_values, derivative_values, fec_rec_values, lost_values
        global all_mbit_values, out_mbit_values
        global raw_rssi_values, raw_snr_values, raw_fec_rec_values, raw_lost_values

        sample_indices = deque(range(settings["MAX_SAMPLES"]), maxlen=settings["MAX_SAMPLES"])
        rssi_values = {}
        snr_values = {}
        redundancy_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        derivative_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        all_mbit_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        out_mbit_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

        raw_rssi_values = {}
        raw_snr_values = {}
        raw_fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        raw_lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

        # Re-check file serve dir
        if not os.path.isdir(settings["FILE_SERVE_DIR"]):
            try:
                os.makedirs(settings["FILE_SERVE_DIR"], exist_ok=True)
            except Exception as e:
                print(f"Warning: failed to create directory {settings['FILE_SERVE_DIR']}: {e}")

        # Possibly re-parse ALLOWED_UPLOAD_PATHS if user changed it in the config
        global ALLOWED_UPLOAD_PATHS
        whitelist_raw_again = config.get("Whitelists", "ALLOWED_UPLOAD_PATHS", fallback="")
        ALLOWED_UPLOAD_PATHS = [p.strip() for p in whitelist_raw_again.split(',') if p.strip()]

        # Update UDP
        udp_streamer.update_settings(settings["UDP_IP"], settings["UDP_PORT"])

        restart_flag.set()
        return redirect(url_for('index'))

    return render_template('settings.html', settings=settings)

@app.route('/data')
def data():
    return jsonify({
        'rssi': {k: list(v) for k, v in rssi_values.items()},
        'snr': {k: list(v) for k, v in snr_values.items()},
        'redundancy': list(redundancy_values),
        'derivative': list(derivative_values),
        'fec_rec': list(fec_rec_values),
        'lost': list(lost_values),
        'all_mbit': list(all_mbit_values),
        'out_mbit': list(out_mbit_values),
        'sample_indices': list(sample_indices),
        'colors': colors,
        'settings': settings,
        'log_interval': log_interval,
    })

@app.route('/data/raw')
def data_raw():
    return jsonify({
        'raw_rssi': {antenna: list(values) for antenna, values in raw_rssi_values.items()},
        'raw_snr': {antenna: list(values) for antenna, values in raw_snr_values.items()},
        'raw_fec_rec': list(raw_fec_rec_values),
        'raw_lost': list(raw_lost_values),
        'sample_indices': list(sample_indices),
    })

@app.route('/udp-log')
def udp_log():
    return jsonify({"logs": udp_streamer.get_logs()})

@app.route('/udp-settings', methods=['GET', 'POST'])
def udp_settings():
    if request.method == 'POST':
        udp_ip = request.form.get('UDP_IP', settings['UDP_IP'])
        udp_port = request.form.get('UDP_PORT', settings['UDP_PORT'])

        settings['UDP_IP'] = udp_ip
        settings['UDP_PORT'] = int(udp_port)

        config.set("Settings", "UDP_IP", udp_ip)
        config.set("Settings", "UDP_PORT", str(udp_port))
        with open(CONFIG_FILE, "w") as configfile:
            config.write(configfile)

        udp_streamer.update_settings(udp_ip, int(udp_port))

        if 'start' in request.form:
            udp_streamer.start()
        elif 'stop' in request.form:
            udp_streamer.stop()

        return redirect(url_for('udp_settings'))

    return render_template('udp_settings.html', settings=settings, udp_running=udp_streamer.is_running())


#########################################################################
#  REMOTE COMMAND EXECUTION (UNCHANGED)
#########################################################################
command_lock = threading.Lock()
command_process = None
command_output_queue = queue.Queue()
command_running_info = {
    "cmd": None,
    "args": None,
    "running": False,
    "exit_code": None,
}

def read_process_output(proc, output_queue):
    try:
        for line in iter(proc.stdout.readline, b''):
            if not line:
                break
            output_queue.put(line)
    except Exception as e:
        output_queue.put(f"[ERROR reading output]: {e}\n".encode("utf-8"))
    finally:
        output_queue.put(b"__CMD_STREAM_END__")

def start_command(command, args=None):
    with command_lock:
        if command_running_info["running"]:
            return False, "Another command is currently running."

        import os
        cmd_basename = os.path.basename(command)
        if not cmd_basename.startswith("extcmd_"):
            return False, f"Not allowed. Command '{cmd_basename}' must begin with 'extcmd_'."

        if args is None:
            args = []

        while not command_output_queue.empty():
            command_output_queue.get_nowait()

        full_cmd = [command] + args

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=0
            )
        except Exception as e:
            return False, f"Failed to start command: {e}"

        command_running_info["cmd"] = command
        command_running_info["args"] = args
        command_running_info["running"] = True
        command_running_info["exit_code"] = None

        global command_process
        command_process = proc

        t = threading.Thread(target=read_process_output, args=(command_process, command_output_queue), daemon=True)
        t.start()

    return True, f"Command '{full_cmd}' started."

def stop_command(force=False):
    with command_lock:
        if not command_running_info["running"]:
            return False, "No command is running."
        if not command_process:
            return False, "Process reference is missing."

        try:
            if force:
                command_process.terminate()
                return True, "SIGTERM sent (force)."
            else:
                command_process.send_signal(signal.SIGINT)
                time.sleep(0.2)
                retcode = command_process.poll()
                if retcode is None:
                    command_process.terminate()
                    return True, "SIGINT sent, then SIGTERM fallback."
                else:
                    return True, "SIGINT sent successfully (process exited)."
        except Exception as e:
            return False, f"Error stopping command: {e}"

def send_input(data):
    with command_lock:
        if not command_running_info["running"]:
            return False, "No command is running to send input."
        try:
            if isinstance(data, str):
                data_bytes = data.encode("utf-8")
            else:
                data_bytes = data
            command_process.stdin.write(data_bytes)
            command_process.stdin.flush()
        except Exception as e:
            return False, f"Failed to send data to stdin: {e}"
    return True, "Data sent."

def check_command_status():
    with command_lock:
        if not command_running_info["running"] or not command_process:
            return
        retcode = command_process.poll()
        if retcode is not None:
            command_running_info["exit_code"] = retcode
            command_running_info["running"] = False

@app.route('/command/start', methods=['POST'])
def command_start():
    data = request.json or request.form
    cmd = data.get("command")
    args = data.get("args", [])

    if not cmd:
        return jsonify({"success": False, "message": "No command specified."}), 400

    ok, msg = start_command(cmd, args)
    return jsonify({"success": ok, "message": msg})

@app.route('/command/stop', methods=['POST'])
def command_stop():
    check_command_status()
    force_str = request.args.get("force", "0")
    force_val = (force_str == "1")

    ok, msg = stop_command(force=force_val)
    return jsonify({"success": ok, "message": msg})

@app.route('/command/input', methods=['POST'])
def command_input():
    check_command_status()
    data = request.json or request.form
    if data.get("ctrl_c", False):
        ok, msg = stop_command(force=False)
        return jsonify({"success": ok, "message": msg})
    else:
        text = data.get("input", "")
        ok, msg = send_input(text + "\n")
        return jsonify({"success": ok, "message": msg})

@app.route('/command/status', methods=['GET'])
def command_status():
    check_command_status()
    with command_lock:
        return jsonify(command_running_info)

@app.route('/command/stream', methods=['GET'])
def command_stream():
    check_command_status()

    def event_stream():
        process_finished_msg_sent = False
        while True:
            check_command_status()
            if not command_running_info["running"]:
                break
            try:
                line = command_output_queue.get(timeout=0.5)
                if line == b"__CMD_STREAM_END__":
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
            except queue.Empty:
                continue

        while not command_output_queue.empty():
            line = command_output_queue.get()
            if line == b"__CMD_STREAM_END__":
                continue
            yield f"data: {line.decode('utf-8', errors='replace')}\n\n"

        if not process_finished_msg_sent:
            yield "data: [Process finished]\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


#########################################################################
#  FILE SERVING + NEW FILE UPLOAD FUNCTION
#########################################################################

def safe_join_file(base_dir, filename):
    """
    Ensure final path is inside the base_dir (prevents directory traversal).
    """
    full_path = os.path.join(base_dir, filename)
    normalized_base = os.path.abspath(base_dir)
    normalized_full = os.path.abspath(full_path)
    if not normalized_full.startswith(normalized_base + os.sep) and normalized_full != normalized_base:
        raise ValueError("File path outside of allowed directory.")
    return normalized_full

@app.route('/files', methods=['GET'])
def list_files():
    directory = settings['FILE_SERVE_DIR']
    try:
        files_list = []
        for entry in os.scandir(directory):
            if entry.is_file():
                stat_info = entry.stat()
                files_list.append({
                    "name": entry.name,
                    "size": stat_info.st_size,
                    "modified": time.ctime(stat_info.st_mtime),
                })
        return jsonify({"directory": directory, "files": files_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/files/download/<path:filename>', methods=['GET'])
def download_file(filename):
    directory = settings['FILE_SERVE_DIR']
    try:
        full_path = safe_join_file(directory, filename)
        if not os.path.isfile(full_path):
            return jsonify({"error": "File not found"}), 404

        return send_from_directory(directory, filename, as_attachment=True)
    except ValueError:
        return jsonify({"error": "Invalid file path"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/files/delete/<path:filename>', methods=['POST'])
def delete_file(filename):
    directory = settings['FILE_SERVE_DIR']
    try:
        full_path = safe_join_file(directory, filename)
        if not os.path.isfile(full_path):
            return jsonify({"error": "File not found"}), 404
        os.remove(full_path)
        return jsonify({"success": True, "message": f"File '{filename}' deleted."})
    except ValueError:
        return jsonify({"error": "Invalid file path"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


#########################################################################
#  NEW UPLOAD ENDPOINT (WHITELISTED PATHS)
#########################################################################
@app.route('/files/upload', methods=['POST'])
def upload_file():
    """
    Expects:
      - form field "targetPath": the exact path from ALLOWED_UPLOAD_PATHS
      - form field "file": the uploaded file data
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file_to_upload = request.files['file']
    target_path = request.form.get("targetPath", "")

    if not target_path:
        return jsonify({"error": "No target path provided"}), 400

    # Check if the user-supplied target path is EXACTLY in the allowed list
    if target_path not in ALLOWED_UPLOAD_PATHS:
        return jsonify({"error": f"Target path '{target_path}' is not in upload whitelist"}), 403

    try:
        # Attempt to overwrite or create the file at targetPath
        # We do not do safe_join here because the user is specifying the full path EXACTLY,
        # and it must match one of the whitelisted items exactly. If you'd prefer partial
        # directories or something else, you can adapt further.

        with open(target_path, 'wb') as f:
            f.write(file_to_upload.read())

        return jsonify({"success": True, "message": f"File uploaded to '{target_path}' successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


#########################################################################
#  SERVE FILE-BROWSER HTML PAGE
#########################################################################
@app.route('/file-browser', methods=['GET'])
def file_browser_page():
    """
    Serves the file-browser HTML snippet.
    You can place that snippet in templates/file-browser.html.
    """
    return render_template('file-browser.html', settings=settings)


#########################################################################
#  BACKGROUND JSON STREAM READER
#########################################################################
def compute_derivative():
    window = settings["DERIVATIVE_WINDOW"]
    if len(redundancy_values) >= window:
        latest = redundancy_values[-1]
        previous = redundancy_values[-window]
        return (latest - previous) / window
    return 0

def normalize_value(value, min_val, max_val):
    if value <= min_val:
        return 0.0
    elif value >= max_val:
        return 1.0
    else:
        return (value - min_val) / (max_val - min_val)

def normalize_rssi(rssi):
    return normalize_value(rssi, settings["RSSI_MIN"], settings["RSSI_MAX"])

def normalize_snr(snr):
    return normalize_value(snr, settings["SNR_MIN"], settings["SNR_MAX"])

def parse_ant_field(ant_value):
    if ant_value is None:
        return "None"
    try:
        ip_part = (ant_value >> 32) & 0xFFFFFFFF
        wlan_idx = (ant_value >> 8) & 0xFFFFFF
        antenna_idx = ant_value & 0xFF
        ip_address = ".".join(str((ip_part >> (8 * i)) & 0xFF) for i in reversed(range(4)))
        return f"{ip_address}_{wlan_idx}_{antenna_idx}"
    except Exception:
        return str(ant_value)

def get_random_color():
    import random
    return f"hsl({random.randint(0, 360)}, 70%, 50%)"

def listen_to_stream():
    global rssi_values, snr_values
    global redundancy_values, derivative_values, fec_rec_values, lost_values
    global all_mbit_values, out_mbit_values, colors, log_interval
    global raw_rssi_values, raw_snr_values, raw_fec_rec_values, raw_lost_values

    while not shutdown_flag.is_set():
        if restart_flag.is_set():
            restart_flag.clear()
            print("Restarting connection to JSON stream with updated settings.")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(settings["SOCKET_TIMEOUT"])
                s.connect((settings["JSON_STREAM_HOST"], settings["JSON_STREAM_PORT"]))
                print(f"Connected to JSON stream at {settings['JSON_STREAM_HOST']}:{settings['JSON_STREAM_PORT']}")

                buffer = ""
                tracked_antennas = set()

                while not shutdown_flag.is_set() and not restart_flag.is_set():
                    try:
                        data = s.recv(4096).decode('utf-8')
                        if not data:
                            raise ConnectionError("Connection to JSON server lost.")

                        buffer += data
                        lines = buffer.split('\n')
                        buffer = lines[-1]

                        for line in lines[:-1]:
                            if not line.strip():
                                continue
                            try:
                                obj = json.loads(line)

                                if obj.get("type") == "settings" and "settings" in obj:
                                    log_interval = obj["settings"]["common"].get("log_interval", None)

                                if obj.get("type") == "rx" and obj.get("id") == "video rx":
                                    packets = obj.get("packets", {})
                                    rx_ant_stats = obj.get("rx_ant_stats", [])

                                    # Redundancy
                                    all_value = packets.get("all", [0])[0]
                                    out_value = packets.get("out", [1])[0]
                                    redundancy = all_value / out_value if out_value > 0 else 0
                                    redundancy_values.append(redundancy)

                                    # Derivative
                                    derivative = compute_derivative()
                                    derivative_values.append(derivative)

                                    # RAW + Normalized FEC_REC
                                    fec_rec = packets.get("fec_rec", [0])[0]
                                    raw_fec_rec_values.append(fec_rec)
                                    fec_rec_values.append(normalize_value(
                                        fec_rec, settings["FEC_REC_MIN"], settings["FEC_REC_MAX"]
                                    ))

                                    # RAW + Normalized LOST
                                    lost = packets.get("lost", [0])[0]
                                    raw_lost_values.append(lost)
                                    lost_values.append(normalize_value(
                                        lost, settings["LOST_MIN"], settings["LOST_MAX"]
                                    ))

                                    # Mbit/s
                                    all_bytes = packets.get("all_bytes", [0])[0]
                                    out_bytes = packets.get("out_bytes", [0])[0]
                                    if log_interval and log_interval > 0:
                                        all_mbit = (all_bytes * 8) / (1_000_000 * (log_interval / 1000))
                                        out_mbit = (out_bytes * 8) / (1_000_000 * (log_interval / 1000))
                                    else:
                                        all_mbit = 0
                                        out_mbit = 0
                                    all_mbit_values.append(all_mbit)
                                    out_mbit_values.append(out_mbit)

                                    current_antenna_set = set()
                                    for ant_stat in rx_ant_stats:
                                        ant_id = parse_ant_field(ant_stat.get("ant"))
                                        current_antenna_set.add(ant_id)
                                        tracked_antennas.add(ant_id)

                                        rssi_avg = ant_stat.get("rssi_avg", 0)
                                        snr_avg = ant_stat.get("snr_avg", 0)

                                        if ant_id not in rssi_values:
                                            rssi_values[ant_id] = deque([0.0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
                                            colors[ant_id] = get_random_color()
                                        if ant_id not in snr_values:
                                            snr_values[ant_id] = deque([0.0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

                                        if ant_id not in raw_rssi_values:
                                            raw_rssi_values[ant_id] = deque([0.0]*settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
                                        if ant_id not in raw_snr_values:
                                            raw_snr_values[ant_id] = deque([0.0]*settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

                                        # RAW
                                        raw_rssi_values[ant_id].append(rssi_avg)
                                        raw_snr_values[ant_id].append(snr_avg)

                                        # Normalized
                                        rssi_values[ant_id].append(normalize_rssi(rssi_avg))
                                        snr_values[ant_id].append(normalize_snr(snr_avg))

                                    # For antennas not reported
                                    for ant_id in tracked_antennas - current_antenna_set:
                                        rssi_values[ant_id].append(0.0)
                                        snr_values[ant_id].append(0.0)
                                        raw_rssi_values[ant_id].append(0.0)
                                        raw_snr_values[ant_id].append(0.0)

                                    # Update UDP
                                    udp_streamer.update_data({
                                        "redundancy": list(redundancy_values),
                                        "derivative": list(derivative_values),
                                        "fec_rec": list(fec_rec_values),
                                        "lost": list(lost_values),
                                        "all_mbit": list(all_mbit_values),
                                        "out_mbit": list(out_mbit_values),
                                    })

                            except json.JSONDecodeError:
                                continue

                    except (socket.timeout, ConnectionError, BrokenPipeError):
                        print("Connection error. Retrying...")
                        break

        except Exception as e:
            print(f"Error connecting to JSON server: {e}. Retrying in 3 seconds...")
            time.sleep(3)

def shutdown_signal_handler(signal_number, frame):
    print("Graceful shutdown initiated.")
    shutdown_flag.set()
    udp_streamer.stop()
    with command_lock:
        if command_process and command_running_info["running"]:
            try:
                command_process.send_signal(signal.SIGINT)
                time.sleep(0.1)
                if command_process.poll() is None:
                    command_process.terminate()
            except:
                pass
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, shutdown_signal_handler)
    signal.signal(signal.SIGTERM, shutdown_signal_handler)
    threading.Thread(target=listen_to_stream, daemon=True).start()
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        print("Server interrupted. Exiting...")
