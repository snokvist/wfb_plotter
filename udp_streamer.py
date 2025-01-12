import threading
import socket
import time
import queue
from collections import deque


class UDPStreamer:
    """
    A class for managing UDP streaming of transformed data.

    Attributes:
        ip (str): The IP address for UDP streaming.
        port (int): The port number for UDP streaming.
        verbose (bool): Whether to enable debug logging.
    """
    def __init__(self, ip: str, port: int, verbose: bool = False):
        self.ip = ip
        self.port = port
        self.verbose = verbose
        self.running = False
        self.lock = threading.Lock()
        self.data_queue = queue.Queue(maxsize=1)
        self.thread = None
        self.logs = deque(maxlen=100)  # Keep the last 100 log messages

    def update_settings(self, ip: str, port: int):
        """
        Update the IP and port for UDP streaming.

        Args:
            ip (str): The new IP address.
            port (int): The new port number.
        """
        with self.lock:
            self.ip = ip
            self.port = port
        self._log(f"UDPStreamer settings updated: IP={self.ip}, Port={self.port}")

    def start(self):
        """
        Start the UDP streaming thread.
        """
        with self.lock:
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._stream_data, daemon=True)
                self.thread.start()
        self._log("UDP streaming started.")

    def stop(self):
        """
        Stop the UDP streaming thread.
        """
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join()
            self.thread = None
        self._log("UDP streaming stopped.")

    def is_running(self):
        """
        Check if the UDP streaming is active.

        Returns:
            bool: True if running, False otherwise.
        """
        with self.lock:
            return self.running

    def update_data(self, data: dict):
        """
        Update the data to be sent via UDP.

        Args:
            data (dict): The latest data to send.
        """
        try:
            self.data_queue.put_nowait(data)
        except queue.Full:
            pass  # Drop the data if the queue is full to prevent blocking

    def get_logs(self):
        """
        Retrieve the collected logs.

        Returns:
            list: A list of log messages.
        """
        return list(self.logs)

    def _stream_data(self):
        """
        Internal method to stream data via UDP.
        """
        while self.is_running():
            try:
                # Get the latest data, with a timeout to check running state
                try:
                    data = self.data_queue.get(timeout=1)
                except queue.Empty:
                    continue

                # Process and format the data
                processed_data = self._process_data(data)

                # Send the data via UDP
                self._send_udp(processed_data)

                # Optionally, sleep to control the data transmission rate
                time.sleep(0.1)
            except Exception as e:
                self._log(f"Error in UDPStreamer: {e}")

    def _process_data(self, data: dict) -> str:
        """
        Process the data before sending it via UDP.

        Args:
            data (dict): The raw data.

        Returns:
            str: The processed data as a formatted text string.
        """
        # Example: Extract mbit/s data
        all_mbit = data.get("all_mbit", [])
        out_mbit = data.get("out_mbit", [])

        # Use the latest values if available
        if all_mbit and out_mbit:
            return f"all_bytes={all_mbit[-1]:.2f}Mbit/s, out_bytes={out_mbit[-1]:.2f}Mbit/s"
        else:
            return "No data available"

    def _send_udp(self, data: str):
        """
        Send the processed data via UDP.

        Args:
            data (str): The data to send.
        """
        with self.lock:
            ip = self.ip
            port = self.port

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(data.encode('utf-8'), (ip, port))
            self._log(f"Sent UDP data to {ip}:{port}: {data}")  # Log every data packet sent
            if self.verbose:
                print(f"Sent UDP data to {ip}:{port}: {data}")

    def _log(self, message: str):
        """
        Log a message to the in-memory log deque.

        Args:
            message (str): The message to log.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.logs.append(formatted_message)
        if self.verbose:
            print(formatted_message)
