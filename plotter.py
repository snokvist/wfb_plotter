#!/usr/bin/python3

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
import threading
import socket
import json
import time
import signal
from collections import deque
import os
import sys
import configparser
from udp_streamer import UDPStreamer  # Import the external UDP streaming module

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
        "UDP_PORT": "5005"
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

# Current Settings
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
}

# Shared Data for Visualizations
sample_indices = deque(range(settings["MAX_SAMPLES"]), maxlen=settings["MAX_SAMPLES"])
rssi_values = {}  # normalized RSSI by antenna
snr_values = {}   # normalized SNR by antenna
redundancy_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
derivative_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
all_mbit_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
out_mbit_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
colors = {}
log_interval = None  # Extracted from the "settings" JSON

# NEW: Raw Data Setup
# We'll store raw RSSI and SNR per antenna, and raw FEC_REC and LOST globally.
raw_rssi_values = {}  # raw RSSI by antenna
raw_snr_values = {}   # raw SNR by antenna
raw_fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
raw_lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

# UDP Streamer Instance
udp_streamer = UDPStreamer(settings["UDP_IP"], settings["UDP_PORT"])

# Flask App
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

# Graceful Shutdown and Restart Flags
shutdown_flag = threading.Event()
restart_flag = threading.Event()


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

        # Reset our data structures because MAX_SAMPLES or other settings may have changed
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

        # NEW: Reset raw data as well
        raw_rssi_values = {}
        raw_snr_values = {}
        raw_fec_rec_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
        raw_lost_values = deque([0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

        # Update UDP Streamer settings
        udp_streamer.update_settings(settings["UDP_IP"], settings["UDP_PORT"])

        restart_flag.set()
        return redirect(url_for('index'))

    return render_template('settings.html', settings=settings)


@app.route('/data')
def data():
    """
    Existing data endpoint - unchanged format
    """
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
        'log_interval': log_interval,  # Include log_interval as metadata
    })


# NEW: Raw Data Endpoint
@app.route('/data/raw')
def data_raw():
    """
    Expose only raw (unnormalized) RSSI, SNR, FEC_REC, and LOST values.
    """
    return jsonify({
        'raw_rssi': {antenna: list(values) for antenna, values in raw_rssi_values.items()},
        'raw_snr': {antenna: list(values) for antenna, values in raw_snr_values.items()},
        'raw_fec_rec': list(raw_fec_rec_values),
        'raw_lost': list(raw_lost_values),
        'sample_indices': list(sample_indices),
    })


@app.route('/udp-log')
def udp_log():
    """
    Endpoint to retrieve the UDP streamer logs.
    """
    return jsonify({"logs": udp_streamer.get_logs()})


@app.route('/udp-settings', methods=['GET', 'POST'])
def udp_settings():
    """
    Endpoint to configure and control the UDP streamer.
    """
    if request.method == 'POST':
        udp_ip = request.form.get('UDP_IP', settings['UDP_IP'])
        udp_port = request.form.get('UDP_PORT', settings['UDP_PORT'])

        # Update the settings
        settings['UDP_IP'] = udp_ip
        settings['UDP_PORT'] = int(udp_port)

        # Save updated settings to the configuration file
        config.set("Settings", "UDP_IP", udp_ip)
        config.set("Settings", "UDP_PORT", str(udp_port))
        with open(CONFIG_FILE, "w") as configfile:
            config.write(configfile)

        # Update the UDP streamer
        udp_streamer.update_settings(udp_ip, int(udp_port))

        # Handle start/stop commands
        if 'start' in request.form:
            udp_streamer.start()
        elif 'stop' in request.form:
            udp_streamer.stop()

        return redirect(url_for('udp_settings'))

    return render_template('udp_settings.html', settings=settings, udp_running=udp_streamer.is_running())


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
    # NEW: Also reference raw data globals
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

                                    # Redundancy calculation
                                    all_value = packets.get("all", [0])[0]
                                    out_value = packets.get("out", [1])[0]
                                    redundancy = all_value / out_value if out_value > 0 else 0
                                    redundancy_values.append(redundancy)

                                    # Compute and append derivative
                                    derivative = compute_derivative()
                                    derivative_values.append(derivative)

                                    # RAW + Normalized FEC_REC
                                    fec_rec = packets.get("fec_rec", [0])[0]
                                    raw_fec_rec_values.append(fec_rec)  # NEW: store raw value
                                    fec_rec_values.append(normalize_value(
                                        fec_rec,
                                        settings["FEC_REC_MIN"],
                                        settings["FEC_REC_MAX"]
                                    ))

                                    # RAW + Normalized LOST
                                    lost = packets.get("lost", [0])[0]
                                    raw_lost_values.append(lost)  # NEW: store raw value
                                    lost_values.append(normalize_value(
                                        lost,
                                        settings["LOST_MIN"],
                                        settings["LOST_MAX"]
                                    ))

                                    # Calculate Mbit/s for all_bytes and out_bytes with log_interval
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

                                        # Initialize antenna keys if not present
                                        if ant_id not in rssi_values:
                                            rssi_values[ant_id] = deque([0.0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
                                            colors[ant_id] = get_random_color()
                                        if ant_id not in snr_values:
                                            snr_values[ant_id] = deque([0.0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

                                        # NEW: Initialize raw antenna keys if needed
                                        if ant_id not in raw_rssi_values:
                                            raw_rssi_values[ant_id] = deque([0.0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])
                                        if ant_id not in raw_snr_values:
                                            raw_snr_values[ant_id] = deque([0.0] * settings["MAX_SAMPLES"], maxlen=settings["MAX_SAMPLES"])

                                        # Append RAW values
                                        raw_rssi_values[ant_id].append(rssi_avg)
                                        raw_snr_values[ant_id].append(snr_avg)

                                        # Append Normalized values
                                        rssi_values[ant_id].append(normalize_rssi(rssi_avg))
                                        snr_values[ant_id].append(normalize_snr(snr_avg))

                                    # For antennas that didn't appear this round, push a zero
                                    for ant_id in tracked_antennas - current_antenna_set:
                                        rssi_values[ant_id].append(0.0)
                                        snr_values[ant_id].append(0.0)
                                        # NEW: If we want to store "missing" raw, might append 0.0 as well:
                                        raw_rssi_values[ant_id].append(0.0)
                                        raw_snr_values[ant_id].append(0.0)

                                    # Pass latest data to UDPStreamer
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
    udp_streamer.stop()  # Ensure UDP streaming stops
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, shutdown_signal_handler)
    signal.signal(signal.SIGTERM, shutdown_signal_handler)
    threading.Thread(target=listen_to_stream, daemon=True).start()
    try:
        app.run(host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("Server interrupted. Exiting...")
