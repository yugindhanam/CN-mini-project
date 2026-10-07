"""Reference clock and small, newline-delimited JSON TCP services."""

import json
import math
import socket
import socketserver
import threading
import time
from datetime import datetime


class ReferenceClock:
    """Wall time at startup, advanced by a monotonic clock (no OS clock edits)."""

    def __init__(self):
        self.epoch = time.time()
        self.started = time.perf_counter()

    def now(self):
        return self.epoch + time.perf_counter() - self.started


def receive_json(connection):
    """TCP is a byte stream: read through the newline, not just one recv()."""
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(1024)
        if not chunk:
            raise ConnectionError("Connection closed before a complete response.")
        data.extend(chunk)
        if len(data) > 4096:
            raise ValueError("Message exceeds the 4096-byte limit.")
    message = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("Expected a JSON object.")
    return message


def send_json(connection, message):
    connection.sendall((json.dumps(message) + "\n").encode("utf-8"))


class _TCPServer(socketserver.ThreadingTCPServer):
    # Do not permit a second demo to silently share the same Windows port.
    allow_reuse_address = False
    daemon_threads = False
    block_on_close = True


class _RequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(2.0)
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            message = receive_json(self.request)
            delay = float(message.get("response_delay", 0.0))
            if not 0.0 <= delay <= 0.5:
                raise ValueError("Response delay must be between 0 and 0.5 s.")
            # Sample BEFORE the simulated return journey, as a real sender does.
            response = self.server.responder(message)
            if not self.server.stopping.wait(delay):
                send_json(self.request, response)
        except (OSError, ValueError, TypeError, KeyError) as error:
            try:
                send_json(self.request, {"error": str(error)})
            except OSError:
                pass


class JSONService:
    """Reusable background TCP listener; also used by Berkeley client clocks."""

    def __init__(self, responder, host="127.0.0.1", port=0):
        self.responder = responder
        self.host = host
        self.port = port
        self.listener = None
        self.thread = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.running:
            return
        listener = _TCPServer((self.host, self.port), _RequestHandler)
        listener.responder = self.responder
        listener.stopping = threading.Event()
        self.listener = listener
        self.port = listener.server_address[1]
        self.thread = threading.Thread(
            target=listener.serve_forever, kwargs={"poll_interval": 0.05},
            name=f"TCP listener {self.port}", daemon=True,
        )
        self.thread.start()

    def stop(self):
        if self.listener is not None:
            self.listener.stopping.set()
            self.listener.shutdown()
            self.listener.server_close()  # Joins in-flight request handlers.
            self.thread.join(timeout=2.0)
            self.listener = None
            self.thread = None


def timed_request(host, port, message, request_delay, response_delay, clock):
    """Measure the request/response interval, excluding TCP connection setup."""
    with socket.create_connection((host, port), timeout=3.0) as connection:
        connection.settimeout(3.0)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        start = time.perf_counter()
        time.sleep(request_delay)  # Actual elapsed time, not a decorative number.
        send_json(connection, {**message, "response_delay": response_delay})
        response = receive_json(connection)
        end = time.perf_counter()
        received_at = clock.now()
    if "error" in response:
        raise ValueError(response["error"])
    timestamp = float(response["timestamp"])
    if not math.isfinite(timestamp):
        raise ValueError("Received an invalid timestamp.")
    return {
        "timestamp": timestamp, "rtt": end - start,
        "received_at": received_at, "t0": start, "t1": end,
    }


class TimeServer:
    def __init__(self, host="127.0.0.1", port=5000, clock=None):
        self.clock = clock or ReferenceClock()
        self.master_offset = 0.0
        self.service = JSONService(self._respond, host, port)

    @property
    def host(self):
        return self.service.host

    @property
    def port(self):
        return self.service.port

    @property
    def running(self):
        return self.service.running

    def _respond(self, message):
        if message.get("type") != "TIME_REQUEST":
            raise ValueError("Expected TIME_REQUEST.")
        timestamp = self.clock.now()
        return {"timestamp": timestamp,
                "server_time": datetime.fromtimestamp(timestamp).isoformat()}

    def start(self):
        self.service.start()

    def stop(self):
        self.service.stop()

    def master_time(self, reference=None):
        if reference is None:
            reference = self.clock.now()
        return reference + self.master_offset

    def poll_client(self, client):
        """Berkeley master initiates a real TCP request to a client listener."""
        if not self.running:
            raise ConnectionError("Start the time server before synchronizing.")
        return timed_request(
            self.host, client.service.port, {"type": "CLOCK_REQUEST"},
            client.request_delay, client.response_delay, self.clock,
        )


if __name__ == "__main__":
    server = TimeServer()
    try:
        server.start()
        print(f"Time server listening on {server.host}:{server.port}. Ctrl+C stops it.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
