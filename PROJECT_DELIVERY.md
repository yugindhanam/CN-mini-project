# Complete project delivery

The sections below follow the requested 20-part order. Source listings are complete copies of the delivered files. Run the files in this folder; there is no need to retype the listings.

## 1. Final project architecture

```text
                         Tkinter GUI (main thread)
                        controls / table / event log
                                     |
                         background experiment worker
                                     |
        +----------------------------+----------------------------+
        |                                                         |
  Cristian: clients request                         Berkeley: master polls
  trusted reference time                            client logical times
        |                                                         |
  Client 1 / 2 / 3 -- TCP --> Time server    Time master -- TCP --> Client listeners
        |                                                         |
  timestamp + RTT/2                                 average relative offsets
        |                                                         |
  correct client logical clocks                     correct clients AND master
        +----------------------------+----------------------------+
                                     |
                    analyzer: error against known simulation truth
                                     |
                         table + Matplotlib comparison
```

All participants run on one computer, but requests pass through actual TCP
sockets. Berkeley clients listen on OS-assigned local ports. The master's
`poll_client()` method initiates their requests. The GUI orchestrates the
simulation; it never blocks while waiting for network messages.

The trusted **reference clock** is anchored to wall time at startup and advanced
using a monotonic timer. The **Berkeley logical master** starts at reference time
but can move when the group is averaged. Both are visible in the server panel.
Cristian always uses the unchanged reference, including after a Berkeley run.

## 2. Folder structure

```text
Network-Time-Synchronization/
├── main.py                 # Tkinter UI, actions, worker queue and shutdown
├── server.py               # Reference clock, TCP service, framing and polling
├── client.py               # Logical clocks, drift, delays and client listeners
├── synchronization.py      # Cristian/Berkeley formulas and result records
├── analyzer.py             # Clock differences, absolute errors and statistics
├── visualization.py        # Matplotlib figure and Tk graph window
├── requirements.txt        # Only the third-party dependency: Matplotlib
├── README.md               # Setup, architecture, math, usage and limitations
├── PROJECT_DELIVERY.md     # Requested 20-part guide with complete source code
├── .gitignore              # Ignore local environments and bytecode
├── tests/
│   └── test_project.py     # Real-socket and withdrawn-GUI integration tests
└── screenshots/
    └── .gitkeep            # Preserve the screenshot directory in Git
```

## 3. Explanation of how the application works

1. The GUI starts the reference server in a background listener thread.
2. Generate Clients creates logical clocks and TCP listeners for Berkeley polls.
3. Each clock advances with its initial offset and its own ppm rate error.
4. Analyze Drift samples all clocks at the same reference instant.
5. Synchronize runs the selected algorithm in a worker thread.
6. Real request/response exchanges include simulated directional waits.
7. The algorithm calculates an adjustment without consulting ground-truth error.
8. The analyzer compares the corrected time to its target and the reference.
9. Show Graph opens a frozen snapshot of that run. The main clocks keep ticking.

Select a client row to see its drift rate, TCP port, before time, sampled timestamp,
estimated one-way delay and absolute reference error.

## 4. Complete code for server.py

```python
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
```

## 5. Complete code for client.py

```python
"""Simulated computers with an initial offset and a small clock rate error."""

import random

from server import JSONService, timed_request


class NetworkClient:
    def __init__(self, client_id, clock, clock_offset=None, drift_ppm=None):
        self.client_id = client_id
        self.clock = clock
        self.clock_offset = (random.uniform(-10, 10) if clock_offset is None
                             else float(clock_offset))
        self.drift_ppm = (random.uniform(-250, 250) if drift_ppm is None
                          else float(drift_ppm))
        self.created_at = clock.now()
        self.correction = 0.0
        self.synchronized_time = None
        self.synchronization_error = None
        self.rtt = None
        self.status = "Not synchronized"
        self.randomize_delay()
        self.service = JSONService(self._respond)

    def current_offset(self, reference=None):
        if reference is None:
            reference = self.clock.now()
        # ppm = microseconds gained/lost per second; offset is a time difference.
        return (self.clock_offset
                + (reference - self.created_at) * self.drift_ppm / 1_000_000)

    def local_time(self, reference=None):
        if reference is None:
            reference = self.clock.now()
        return reference + self.current_offset(reference)

    @property
    def network_delay(self):
        return self.request_delay + self.response_delay

    def randomize_delay(self):
        self.request_delay = random.uniform(0.05, 0.5)
        self.response_delay = random.uniform(0.05, 0.5)

    def _respond(self, message):
        if message.get("type") != "CLOCK_REQUEST":
            raise ValueError("Expected CLOCK_REQUEST.")
        return {"client_id": self.client_id, "timestamp": self.local_time()}

    def start(self):
        self.service.start()

    def stop(self):
        self.service.stop()

    def request_time(self, server):
        return timed_request(
            server.host, server.port, {"type": "TIME_REQUEST"},
            self.request_delay, self.response_delay, self.clock,
        )

    def apply_correction(self, correction):
        # Change only this simulated clock. Never set the computer's OS time.
        self.clock_offset += correction
        self.correction = correction

    def clear_result(self):
        self.rtt = None
        self.correction = 0.0
        self.synchronized_time = None
        self.synchronization_error = None
        self.status = "Not synchronized"
```

## 6. Complete code for synchronization.py

```python
"""Educational Cristian and Berkeley algorithms, independent of the GUI."""

import threading
from dataclasses import dataclass, field


CRISTIAN = "Cristian's Algorithm"
BERKELEY = "Berkeley Algorithm"


@dataclass
class ClientResult:
    client_id: str
    before_offset: float
    after_offset: float
    correction: float
    rtt: float
    original_time: float
    sampled_time: float
    synchronized_time: float
    reference_time: float
    target_error: float
    reference_error: float
    request_delay: float
    response_delay: float


@dataclass
class SyncReport:
    algorithm: str
    total_clients: int
    results: list = field(default_factory=list)
    failures: dict = field(default_factory=dict)
    average_offset: float = 0.0
    master_offset: float = 0.0
    master_correction: float = 0.0


class SynchronizationManager:
    def __init__(self, server, log=None):
        self.server = server
        self.log = log or (lambda message: None)
        self.cancel = threading.Event()

    def synchronize(self, clients, algorithm):
        if not clients:
            raise ValueError("Generate clients before synchronizing.")
        if not self.server.running:
            raise ConnectionError("The time server is stopped. Start it first.")
        self.cancel.clear()
        if algorithm not in (CRISTIAN, BERKELEY):
            raise ValueError("Choose a supported synchronization algorithm.")
        for client in clients:
            client.clear_result()
        if algorithm == CRISTIAN:
            return self._cristian(clients)
        return self._berkeley(clients)

    def _failure(self, report, client, error):
        client.status = "Failed"
        report.failures[client.client_id] = str(error)
        self.log(f"{client.client_id}: {error}")

    def _record(self, report, client, sample, before, correction, reference, target):
        after = client.local_time(reference)
        client.rtt = sample["rtt"]
        client.synchronized_time = after
        client.synchronization_error = abs(after - target)
        client.status = "Synchronized"
        report.results.append(ClientResult(
            client.client_id, before - reference, after - reference, correction,
            sample["rtt"], before, sample["timestamp"], after, reference,
            abs(after - target), abs(after - reference),
            client.request_delay, client.response_delay,
        ))
        self.log(f"{client.client_id}: RTT {sample['rtt'] * 1000:.1f} ms; "
                 f"correction {correction:+.4f} s; "
                 f"target error {client.synchronization_error:.4f} s.")

    def _cristian(self, clients):
        report = SyncReport(CRISTIAN, len(clients),
                            master_offset=self.server.master_offset)
        for client in clients:
            if self.cancel.is_set():
                break
            try:
                self.log(f"{client.client_id} sent TIME_REQUEST over TCP.")
                sample = client.request_time(self.server)
                reference = sample["received_at"]
                before = client.local_time(reference)
                # RTT = T1 - T0 (monotonic); estimated one-way delay = RTT / 2.
                estimated = sample["timestamp"] + sample["rtt"] / 2
                correction = estimated - before
                client.apply_correction(correction)
                # Truth is used ONLY to measure error, never to set the clock.
                self._record(report, client, sample, before, correction,
                             reference, reference)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self._failure(report, client, error)
        return report

    def _berkeley(self, clients):
        report = SyncReport(BERKELEY, len(clients))
        polls = []
        old_master_offset = self.server.master_offset
        for client in clients:
            if self.cancel.is_set():
                break
            try:
                self.log(f"Master sent CLOCK_REQUEST to {client.client_id} over TCP.")
                sample = self.server.poll_client(client)
                # Bring the sampled client time to estimated poll-receipt time.
                estimate = sample["timestamp"] + sample["rtt"] / 2
                offset = estimate - self.server.master_time(sample["received_at"])
                polls.append((client, sample, offset))
            except (OSError, ValueError, KeyError, TypeError) as error:
                self._failure(report, client, error)
        if not polls or self.cancel.is_set():
            report.master_offset = old_master_offset
            return report
        # Include the master's relative offset 0; exclude unreachable clients.
        average = sum(offset for _, _, offset in polls) / (len(polls) + 1)
        report.average_offset = average
        report.master_correction = average
        self.server.master_offset += average
        report.master_offset = self.server.master_offset
        self.log(f"Berkeley mean = {average:+.4f} s across {len(polls) + 1} clocks "
                 "(including the master). Applying relative corrections.")
        # Educational simplification: apply all corrections locally at one epoch.
        # Polling is TCP; correction distribution has no extra simulated delay.
        reference = self.server.clock.now()
        target = self.server.master_time(reference)
        for client, sample, offset in polls:
            before = client.local_time(reference)
            correction = average - offset
            client.apply_correction(correction)
            self._record(report, client, sample, before, correction, reference, target)
        return report
```

## 7. Complete code for analyzer.py

```python
"""Small pure functions for clock differences and synchronization statistics."""

from statistics import mean


class ClockAnalyzer:
    @staticmethod
    def clock_difference(client_time, server_time):
        return client_time - server_time

    @staticmethod
    def absolute_error(client_time, reference_time):
        return abs(client_time - reference_time)

    @staticmethod
    def analyze(clients, reference):
        offsets = [client.local_time(reference) - reference for client in clients]
        if not offsets:
            raise ValueError("Generate clients before analyzing drift.")
        return {"average_offset": mean(offsets), "minimum_offset": min(offsets),
                "maximum_offset": max(offsets),
                "maximum_drift": max(abs(offset) for offset in offsets),
                "minimum_drift": min(abs(offset) for offset in offsets)}

    @staticmethod
    def summarize(report):
        if not report.results:
            return {"average_error": None, "maximum_error": None,
                    "average_reference_error": None}
        errors = [row.target_error for row in report.results]
        return {"average_error": mean(errors), "maximum_error": max(errors),
                "average_reference_error": mean(
                    row.reference_error for row in report.results)}
```

## 8. Complete code for visualization.py

```python
"""Matplotlib figures embedded in a separate Tk window."""

import tkinter as tk
from tkinter import ttk

from synchronization import BERKELEY


def create_figure(report):
    from matplotlib.figure import Figure

    if not report or not report.results:
        raise ValueError("Synchronize at least one client before showing a graph.")
    figure = Figure(figsize=(10, 6), dpi=100, constrained_layout=True)
    offsets, delays = figure.subplots(2, 1)
    rows = report.results
    positions = list(range(len(rows)))
    offsets.bar([x - 0.18 for x in positions],
                [row.before_offset for row in rows], 0.36,
                color="#64748b", label="Before: signed offset from reference")
    offsets.bar([x + 0.18 for x in positions],
                [row.after_offset for row in rows], 0.36,
                color="#0284c7", label="After: signed offset from reference")
    offsets.axhline(0, color="#334155", linewidth=0.8)
    if report.algorithm == BERKELEY:
        offsets.axhline(report.master_offset, color="#d97706", linestyle="--",
                        label=f"Group/master target {report.master_offset:+.3f} s")
    offsets.set_title(f"Clock offset before vs after — {report.algorithm}")
    offsets.set_ylabel("Signed offset (seconds)")
    offsets.set_xticks(positions, [row.client_id for row in rows])
    offsets.legend(fontsize=8)
    offsets.grid(axis="y", alpha=0.2)
    delays.bar([x - 0.24 for x in positions],
               [row.request_delay * 1000 for row in rows], 0.24,
               label="Simulated request", color="#64748b")
    delays.bar(positions, [row.response_delay * 1000 for row in rows], 0.24,
               label="Simulated response", color="#38bdf8")
    delays.bar([x + 0.24 for x in positions], [row.rtt * 1000 for row in rows],
               0.24, label="Measured RTT", color="#0284c7")
    delays.set_ylabel("Delay (milliseconds)")
    delays.set_xticks(positions, [row.client_id for row in rows])
    delays.legend(fontsize=8)
    delays.grid(axis="y", alpha=0.2)
    return figure


def show_graph(parent, report):
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

    figure = create_figure(report)
    window = tk.Toplevel(parent)
    window.title("Synchronization results — frozen measurement snapshot")
    window.geometry("1000x720")
    canvas = FigureCanvasTkAgg(figure, master=window)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)
    NavigationToolbar2Tk(canvas, window).update()
    ttk.Label(window, text=(
        "Bars use the same reference and signed units. Berkeley aims at the group "
        "line, which need not be zero.\nOnly successful clients are plotted. "
        "Use the toolbar to save a screenshot."
    ), padding=8).pack()
    return window
```

## 9. Complete code for main.py

```python
"""Run with Python 3.11+: python main.py [--port 5000]."""

import argparse
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from analyzer import ClockAnalyzer
from client import NetworkClient
from server import TimeServer
from synchronization import BERKELEY, CRISTIAN, SynchronizationManager
from visualization import show_graph


def format_time(timestamp):
    if timestamp is None:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]


class TimeSyncApp:
    def __init__(self, root, port=5000):
        self.root = root
        self.server = TimeServer(port=port)
        self.clients = []
        self.report = None
        self.graph_windows = []
        self.events = queue.Queue()
        self.manager = SynchronizationManager(self.server, self.log)
        self.busy = False
        self.closing = False
        self.shutting_down = False
        self.controls = []
        self.algorithm = tk.StringVar(value=CRISTIAN)
        self.client_count = tk.StringVar(value="3")
        self.server_text = tk.StringVar()
        self.explanation = tk.StringVar()
        self.statistics = tk.StringVar(value="Generate 3–5 clients, then analyze their clocks.")
        self.result_text = tk.StringVar(value="Synchronization status: NOT SYNCHRONIZED")
        self.details = tk.StringVar(value="Select a client to inspect its clock and measurements.")
        self._build_ui()
        self._algorithm_changed()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self._poll_events)
        self.root.after(100, self._tick)
        self.root.after(150, self.start_server)

    def _build_ui(self):
        self.root.title("Network Time Synchronization & Clock Drift Analyzer")
        self.root.geometry("1180x820")
        self.root.minsize(1000, 700)
        self.root.configure(background="#eef2f6")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f6")
        style.configure("TLabel", background="#eef2f6", font=("Segoe UI", 10))
        style.configure("TLabelframe", background="#eef2f6")
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=(10, 6), font=("Segoe UI", 9))
        style.configure("Treeview", rowheight=32, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        # Windows display scaling can make the results taller than the window.
        # Keep every section accessible instead of clipping the event log.
        self.page_canvas = tk.Canvas(
            self.root, background="#eef2f6", highlightthickness=0,
        )
        page_scroll = ttk.Scrollbar(
            self.root, orient="vertical", command=self.page_canvas.yview,
        )
        page_scroll.pack(side="right", fill="y")
        self.page_canvas.pack(side="left", fill="both", expand=True)
        self.page_canvas.configure(yscrollcommand=page_scroll.set)
        body = ttk.Frame(self.page_canvas, padding=16)
        content = self.page_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: self.page_canvas.configure(
            scrollregion=self.page_canvas.bbox("all")))
        self.page_canvas.bind("<Configure>", lambda event: self.page_canvas.itemconfigure(
            content, width=event.width))
        self.root.bind("<MouseWheel>", self._scroll_page)
        ttk.Label(body, text="NETWORK TIME SYNCHRONIZATION",
                  font=("Segoe UI", 20, "bold"), foreground="#0f172a").pack(anchor="w")
        ttk.Label(body, text="& CLOCK DRIFT ANALYZER  |  TCP networking laboratory",
                  foreground="#475569").pack(anchor="w", pady=(0, 12))

        server_box = ttk.LabelFrame(body, text="1  Time server", padding=10)
        server_box.pack(fill="x")
        ttk.Label(server_box, textvariable=self.server_text).pack(side="left", expand=True, anchor="w")
        self._button(server_box, "Start Server", self.start_server).pack(side="left", padx=3)
        self._button(server_box, "Stop Server", self.stop_server).pack(side="left", padx=3)

        control_box = ttk.LabelFrame(body, text="2  Experiment controls", padding=10)
        control_box.pack(fill="x", pady=10)
        options = ttk.Frame(control_box)
        options.pack(fill="x")
        ttk.Label(options, text="Clients:").pack(side="left")
        count = ttk.Combobox(options, textvariable=self.client_count,
                             values=(3, 4, 5), width=4, state="readonly")
        count.pack(side="left", padx=(6, 18))
        self.controls.append((count, "readonly"))
        ttk.Label(options, text="Algorithm:").pack(side="left")
        algorithms = ttk.Combobox(options, textvariable=self.algorithm,
                                  values=(CRISTIAN, BERKELEY), width=24, state="readonly")
        algorithms.pack(side="left", padx=6)
        algorithms.bind("<<ComboboxSelected>>", self._algorithm_changed)
        self.controls.append((algorithms, "readonly"))
        self.progress = ttk.Progressbar(options, mode="indeterminate", length=160)
        self.progress.pack(side="right", padx=5)
        actions = ttk.Frame(control_box)
        actions.pack(fill="x", pady=(10, 6))
        for label, command in (
            ("Generate Clients", self.generate_clients),
            ("Analyze Drift", self.analyze_drift),
            ("Synchronize", self.synchronize),
            ("Simulate New Delay", self.new_delays),
            ("Reset", self.reset), ("Show Graph", self.open_graph),
        ):
            self._button(actions, label, command).pack(side="left", padx=(0, 6))
        ttk.Label(control_box, textvariable=self.explanation, wraplength=1050,
                  foreground="#075985").pack(anchor="w")

        table_box = ttk.LabelFrame(body, text="3  Live client clocks", padding=8)
        table_box.pack(fill="x")
        columns = ("client", "current", "offset", "delay", "rtt", "correction", "synced", "error", "status")
        self.table = ttk.Treeview(table_box, columns=columns, show="headings", height=5)
        headings = ("Client", "Current time", "Offset (s)", "Req / Resp (ms)",
                    "RTT (ms)", "Correction (s)", "Synced time", "Target error (s)", "Status")
        widths = (78, 108, 85, 110, 80, 95, 108, 105, 125)
        for column, heading, width in zip(columns, headings, widths):
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=width, anchor="center")
        self.table.pack(fill="x")
        scrollbar = ttk.Scrollbar(table_box, orient="horizontal", command=self.table.xview)
        scrollbar.pack(fill="x")
        self.table.configure(xscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self._show_details)
        ttk.Label(table_box, text="Current time/offset are live. RTT, correction, synced time and error are last-run snapshots.",
                  foreground="#475569").pack(anchor="w", pady=(5, 0))

        result_box = ttk.LabelFrame(body, text="4  Analysis and results", padding=10)
        result_box.pack(fill="x", pady=10)
        ttk.Label(result_box, textvariable=self.statistics, wraplength=1060).pack(anchor="w")
        ttk.Separator(result_box).pack(fill="x", pady=7)
        ttk.Label(result_box, textvariable=self.result_text, wraplength=1060,
                  foreground="#075985").pack(anchor="w")
        ttk.Label(result_box, textvariable=self.details, wraplength=1060,
                  font=("Consolas", 9)).pack(anchor="w", pady=(8, 0))

        log_box = ttk.LabelFrame(body, text="5  Event log", padding=8)
        log_box.pack(fill="both", expand=True)
        self.log_view = tk.Text(log_box, height=5, state="disabled", wrap="word",
                                font=("Consolas", 9), background="#0f172a",
                                foreground="#cbd5e1", relief="flat")
        self.log_view.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_box, command=self.log_view.yview)
        scroll.pack(side="right", fill="y")
        self.log_view.configure(yscrollcommand=scroll.set)

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append((button, "normal"))
        return button

    def _scroll_page(self, event):
        if event.widget not in (self.log_view, self.table):
            self.page_canvas.yview_scroll(-int(event.delta / 120), "units")

    def _algorithm_changed(self, event=None):
        if self.algorithm.get() == CRISTIAN:
            text = "Cristian: trusted reference time + RTT/2. Target error is relative to the reference clock."
        else:
            text = "Berkeley: master polls clients, averages offsets including itself, then adjusts the group. Target error is relative to the adjusted master."
        self.explanation.set(text)

    def log(self, message):
        # Workers only enqueue data; all Tk operations run on the main thread.
        self.events.put(("log", message))

    def _set_busy(self, busy):
        self.busy = busy
        for widget, normal_state in self.controls:
            widget.configure(state="disabled" if busy or self.closing else normal_state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _run_work(self, work, completed):
        if self.busy:
            return
        self._set_busy(True)

        def run():
            try:
                result = work()
                self.events.put(("done", completed, result, None))
            except Exception as error:
                self.events.put(("done", completed, None, error))

        threading.Thread(target=run, name="Experiment worker", daemon=False).start()

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self.log_view.configure(state="normal")
                    self.log_view.insert("end", f"[{format_time(self.server.clock.now())}] {event[1]}\n")
                    if int(self.log_view.index("end-1c").split(".")[0]) > 160:
                        self.log_view.delete("1.0", "2.0")
                    self.log_view.see("end")
                    self.log_view.configure(state="disabled")
                elif event[0] == "done":
                    _, completed, result, error = event
                    self._set_busy(False)
                    if error is not None:
                        self.log(str(error))
                        if not self.closing:
                            messagebox.showerror("Operation failed", str(error), parent=self.root)
                    else:
                        completed(result)
                elif event[0] == "closed":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        if self.closing and not self.busy and not self.shutting_down:
            self._shutdown()
        self.root.after(50, self._poll_events)

    def _tick(self):
        if self.closing:
            return
        reference = self.server.clock.now()
        status = "RUNNING" if self.server.running else "STOPPED"
        self.server_text.set(
            f"{status}  |  {self.server.host}:{self.server.port}  |  Reference: {format_time(reference)}\n"
            f"Berkeley logical master: {format_time(self.server.master_time(reference))}  "
            f"(offset {self.server.master_offset:+.3f} s)"
        )
        for client in self.clients:
            values = (
                client.client_id, format_time(client.local_time(reference)),
                f"{client.current_offset(reference):+.3f}",
                f"{client.request_delay * 1000:.0f} / {client.response_delay * 1000:.0f}",
                "—" if client.rtt is None else f"{client.rtt * 1000:.1f}",
                "—" if client.synchronized_time is None else f"{client.correction:+.4f}",
                format_time(client.synchronized_time),
                "—" if client.synchronization_error is None else f"{client.synchronization_error:.4f}",
                client.status,
            )
            if self.table.exists(client.client_id):
                self.table.item(client.client_id, values=values)
            else:
                self.table.insert("", "end", iid=client.client_id, values=values)
        self.root.after(100, self._tick)

    def start_server(self):
        if self.closing or self.busy or self.server.running:
            return
        try:
            self.server.start()
            self.log(f"Time server started on {self.server.host}:{self.server.port}.")
        except OSError as error:
            messagebox.showerror("Cannot start server",
                                 f"Port {self.server.port} may already be in use.\n"
                                 f"Try: python main.py --port 5001\n\n{error}", parent=self.root)

    def stop_server(self):
        if not self.server.running:
            return
        self._run_work(self.server.stop, lambda _: self.log("Time server stopped."))

    def _require_clients(self):
        if self.clients:
            return True
        messagebox.showinfo("No clients", "Generate clients first.", parent=self.root)
        return False

    def _clear_snapshot(self):
        self.report = None
        self.statistics.set("No drift analysis yet.")
        self.result_text.set("Synchronization status: NOT SYNCHRONIZED")
        self.details.set("Select a client to inspect its clock and measurements.")
        for window in self.graph_windows:
            if window.winfo_exists():
                window.destroy()
        self.graph_windows.clear()
        for client in self.clients:
            client.clear_result()

    def generate_clients(self):
        try:
            count = int(self.client_count.get())
            if not 3 <= count <= 5:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid count", "Choose 3, 4 or 5 clients.", parent=self.root)
            return

        def generate():
            new_clients = []
            try:
                for number in range(1, count + 1):
                    client = NetworkClient(f"Client {number}", self.server.clock)
                    new_clients.append(client)
                    client.start()
            except Exception:
                for client in new_clients:
                    client.stop()
                raise
            for client in self.clients:
                client.stop()
            return new_clients

        def completed(clients):
            self.clients = clients
            self.server.master_offset = 0.0
            self.table.delete(*self.table.get_children())
            self._clear_snapshot()
            self.log(f"Generated {len(clients)} clients with offsets ±10 s, drift ±250 ppm, "
                     "and independent 50–500 ms delays in each direction.")

        self._run_work(generate, completed)

    def analyze_drift(self):
        if not self._require_clients():
            return
        stats = ClockAnalyzer.analyze(self.clients, self.server.clock.now())
        self.statistics.set(
            f"Offset snapshot: mean {stats['average_offset']:+.4f} s  |  "
            f"signed min/max {stats['minimum_offset']:+.4f} / {stats['maximum_offset']:+.4f} s\n"
            f"Absolute drift min/max: {stats['minimum_drift']:.4f} / {stats['maximum_drift']:.4f} s"
        )
        self.log("Drift analysis completed against a common reference instant.")

    def new_delays(self):
        if not self._require_clients():
            return
        self._clear_snapshot()
        for client in self.clients:
            client.randomize_delay()
        self.log("New request/response delays generated. Clock values preserved; measurement results cleared.")

    def synchronize(self):
        if not self._require_clients():
            return
        if not self.server.running:
            messagebox.showerror("Server unavailable", "Start the time server first.", parent=self.root)
            return
        self._clear_snapshot()
        self.analyze_drift()
        algorithm = self.algorithm.get()
        self.result_text.set(f"Synchronization status: RUNNING  |  {algorithm}")
        self._run_work(lambda: self.manager.synchronize(self.clients, algorithm), self._sync_finished)

    def _sync_finished(self, report):
        self.report = report
        count = len(report.results)
        status = "SUCCESS" if count == report.total_clients else "PARTIAL" if count else "FAILED"
        summary = ClockAnalyzer.summarize(report)
        text = f"Synchronization status: {status}  |  {report.algorithm}  |  Clients: {count}/{report.total_clients}"
        if count:
            text += (f"\nTarget error: average {summary['average_error']:.4f} s, "
                     f"maximum {summary['maximum_error']:.4f} s  |  "
                     f"Average reference error: {summary['average_reference_error']:.4f} s")
        if report.algorithm == BERKELEY:
            text += (f"\nBerkeley mean/master correction: {report.average_offset:+.4f} s  |  "
                     f"Group offset from reference: {report.master_offset:+.4f} s")
        self.result_text.set(text)
        self.log(f"{report.algorithm}: {status}; synchronized {count}/{report.total_clients} clients.")
        self._show_details()
        if report.failures and not self.closing:
            messagebox.showwarning("Some clients could not synchronize",
                                   "\n".join(f"{name}: {error}" for name, error in report.failures.items()),
                                   parent=self.root)

    def _show_details(self, event=None):
        selected = self.table.selection()
        if not selected:
            return
        client = next((item for item in self.clients if item.client_id == selected[0]), None)
        if client is None:
            return
        text = (f"{client.client_id}: clock rate {client.drift_ppm:+.1f} ppm; "
                f"Berkeley TCP listener {client.service.host}:{client.service.port}.")
        row = next((row for row in self.report.results if row.client_id == client.client_id), None) if self.report else None
        if row:
            source = "Server timestamp" if self.report.algorithm == CRISTIAN else "Polled client timestamp"
            text += (f"\nBefore: {format_time(row.original_time)} ({row.before_offset:+.4f} s); "
                     f"{source}: {format_time(row.sampled_time)}; RTT/2: {row.rtt * 500:.2f} ms."
                     f"\nReference at measurement: {format_time(row.reference_time)}; "
                     f"absolute reference error: {row.reference_error:.4f} s.")
        self.details.set(text)

    def open_graph(self):
        if not self.report or not self.report.results:
            messagebox.showinfo("No results", "Synchronize clients before showing a graph.", parent=self.root)
            return
        try:
            self.graph_windows.append(show_graph(self.root, self.report))
        except ImportError:
            messagebox.showerror("Matplotlib is missing", "Run: python -m pip install -r requirements.txt", parent=self.root)

    def reset(self):
        def clear():
            for client in self.clients:
                client.stop()

        def completed(_):
            self.clients = []
            self.server.master_offset = 0.0
            self.table.delete(*self.table.get_children())
            self._clear_snapshot()
            self.log("Reset complete: client listeners, statistics and graph data cleared.")

        self._run_work(clear, completed)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.manager.cancel.set()
        self._set_busy(self.busy)
        self.result_text.set("Closing: waiting for the current request and releasing TCP ports…")

    def _shutdown(self):
        self.shutting_down = True

        def stop_all():
            try:
                for client in self.clients:
                    client.stop()
                self.server.stop()
            finally:
                self.events.put(("closed",))

        threading.Thread(target=stop_all, name="Shutdown worker", daemon=False).start()


def main():
    parser = argparse.ArgumentParser(description="Network Time Synchronization & Clock Drift Analyzer")
    parser.add_argument("--port", type=int, default=5000, help="Local time-server port (default: 5000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    root = tk.Tk()
    TimeSyncApp(root, args.port)
    root.mainloop()


if __name__ == "__main__":
    main()
```

## 10. requirements.txt

```text
matplotlib>=3.8,<4
```

## 11. README.md

````markdown
# Network Time Synchronization and Clock Drift Analyzer

A Python Computer Networks mini project for a third-year B.Tech IT demonstration.
It runs a real localhost TCP time server, simulates 3–5 independent logical clocks,
and compares Cristian's reference-clock synchronization with Berkeley's group-clock
synchronization in a Tkinter interface.

## Project overview

Computers can disagree about the time even when each clock appears to work. An
initial **offset** is the difference between two clocks at one instant. **Clock
drift** is the accumulation of error because a clock runs slightly fast or slow.
Network latency makes the timestamp received from another computer already old.

This application demonstrates all three effects. It changes simulated clocks only;
it does not change Windows time or need administrator privileges.

## Problem statement

How can computers agree on time when their clocks differ and timestamp messages
take an unknown amount of time to travel? How does a trusted time source differ
from a group that agrees on its own average time?

## Objectives

- Implement real TCP request-response communication using Python sockets.
- Observe initial offsets, continuing clock drift and directional network delays.
- Apply and compare Cristian's and Berkeley's algorithms.
- Measure corrections, residual error and group/reference accuracy.
- Explain the results using a live table, event log and before/after graph.

## Features

- Automatically started reference server at `127.0.0.1:5000`, configurable by CLI.
- Three to five clients with random offsets from −10 to +10 seconds.
- Independent drift rates from −250 to +250 parts per million (ppm).
- Independent request and response delays, each from 50 to 500 ms.
- Measured RTT that includes real waits and local socket overhead.
- Live clocks updated every 100 ms using Tkinter `after()`.
- Background workers keep the interface responsive during network operations.
- Cristian reference synchronization and Berkeley polling/averaging.
- Mean offset, signed minimum/maximum offset and absolute minimum/maximum drift.
- Target error and external reference error displayed separately.
- Matplotlib before/after bars and request/response/RTT comparison.
- Per-client measurement details, bounded event log, reset and clean shutdown.
- Understandable messages for missing clients, stopped server and port conflicts.

## System architecture

```text
                         Tkinter GUI (main thread)
                        controls / table / event log
                                     |
                         background experiment worker
                                     |
        +----------------------------+----------------------------+
        |                                                         |
  Cristian: clients request                         Berkeley: master polls
  trusted reference time                            client logical times
        |                                                         |
  Client 1 / 2 / 3 -- TCP --> Time server    Time master -- TCP --> Client listeners
        |                                                         |
  timestamp + RTT/2                                 average relative offsets
        |                                                         |
  correct client logical clocks                     correct clients AND master
        +----------------------------+----------------------------+
                                     |
                    analyzer: error against known simulation truth
                                     |
                         table + Matplotlib comparison
```

All participants run on one computer, but requests pass through actual TCP
sockets. Berkeley clients listen on OS-assigned local ports. The master's
`poll_client()` method initiates their requests. The GUI orchestrates the
simulation; it never blocks while waiting for network messages.

The trusted **reference clock** is anchored to wall time at startup and advanced
using a monotonic timer. The **Berkeley logical master** starts at reference time
but can move when the group is averaged. Both are visible in the server panel.
Cristian always uses the unchanged reference, including after a Berkeley run.

## Technologies used

| Technology | Purpose |
| --- | --- |
| Python 3.11+ | Application and algorithms |
| Tkinter / ttk | Desktop GUI |
| `socket` / `socketserver` | TCP communication and threaded listeners |
| `threading` / `queue` | Workers and safe delivery of GUI updates |
| `time` / `datetime` | Monotonic measurements and displayed clock times |
| `random` | Offsets, rate errors and delays |
| JSON | Structured, newline-delimited messages |
| Matplotlib | Embedded plots and image export |
| `unittest` | Network and GUI integration tests |

## Project structure

```text
Network-Time-Synchronization/
├── main.py                 # Tkinter UI, actions, worker queue and shutdown
├── server.py               # Reference clock, TCP service, framing and polling
├── client.py               # Logical clocks, drift, delays and client listeners
├── synchronization.py      # Cristian/Berkeley formulas and result records
├── analyzer.py             # Clock differences, absolute errors and statistics
├── visualization.py        # Matplotlib figure and Tk graph window
├── requirements.txt        # Only the third-party dependency: Matplotlib
├── README.md               # Setup, architecture, math, usage and limitations
├── PROJECT_DELIVERY.md     # Requested 20-part guide with complete source code
├── .gitignore              # Ignore local environments and bytecode
├── tests/
│   └── test_project.py     # Real-socket and withdrawn-GUI integration tests
└── screenshots/
    └── .gitkeep            # Preserve the screenshot directory in Git
```

## How the application works

1. The GUI starts the reference server in a background listener thread.
2. Generate Clients creates logical clocks and TCP listeners for Berkeley polls.
3. Each clock advances with its initial offset and its own ppm rate error.
4. Analyze Drift samples all clocks at the same reference instant.
5. Synchronize runs the selected algorithm in a worker thread.
6. Real request/response exchanges include simulated directional waits.
7. The algorithm calculates an adjustment without consulting ground-truth error.
8. The analyzer compares the corrected time to its target and the reference.
9. Show Graph opens a frozen snapshot of that run. The main clocks keep ticking.

Select a client row to see its drift rate, TCP port, before time, sampled timestamp,
estimated one-way delay and absolute reference error.

## Algorithms and formulas

Let `R(t)` be the simulation's trusted reference time and `C_i(t)` a client clock.
All times and corrections below use seconds unless stated otherwise.

### Clock model

```text
Client time = Reference time + Current offset
Current offset = Base offset + Elapsed seconds × Drift ppm / 1,000,000
Observed offset = Client time − Reference time
```

An offset of `−5 s` means the clock is five seconds behind. A drift of `+100 ppm`
means the clock gains `0.0001 s` every second, or `0.1 s` in 1,000 seconds.
Applying a correction changes the base offset; it does not fix the rate error.
The Analyze Drift panel uses “absolute drift” to mean accumulated absolute clock
difference, while the row details identify the actual rate in ppm.

### Cristian's Algorithm

Cristian assumes a trusted reference time server.

1. A client connects to the reference server and records monotonic send time `T0`.
2. It waits for its simulated request journey, then sends `TIME_REQUEST`.
3. The server samples reference timestamp `Ts` before the response journey.
4. After the response delay and socket delivery, the client records `T1`.
5. It estimates the current reference time and applies the correction:

```text
RTT = T1 − T0
Estimated one-way delay = RTT / 2
Estimated reference time at receipt = Ts + RTT / 2
Correction = Estimated reference time − Client time at receipt
Corrected client time = Client time + Correction
Reference error = |Corrected client time − Reference time at receipt|
```

`T0` and `T1` use a monotonic timer, so clock corrections cannot distort the RTT.
TCP connection establishment is deliberately excluded from the measurement.
The client's local time and the reference used to evaluate its correction are
sampled at the same receipt epoch. Time continues to advance after that snapshot.

For request delay `d_request` and response delay `d_response`, ignoring overhead:

```text
Signed residual offset ≈ (d_request − d_response) / 2
```

Equal delays are well compensated even if large. **Asymmetry**, processing and
scheduling overhead cause error. The application never adds a fake error value or
forces the error to zero. Small natural residuals may round to zero in the table.

### Berkeley Algorithm

Berkeley aims at agreement among participating clocks. It does not assume that the
master has the correct external time.

1. The master connects to each client listener and sends `CLOCK_REQUEST`.
2. The client replies with its logical timestamp, sampled before the return delay.
3. The master estimates each client's time at poll receipt using `timestamp + RTT/2`.
4. It subtracts the master's logical time at that same epoch to estimate offset `o_i`.
5. It averages the available client offsets **including the master's offset 0**.
6. It adjusts the master by the mean and every responding client by `mean − o_i`.

```text
Estimated client time = Polled client timestamp + RTT / 2
Client offset o_i = Estimated client time − Master time at poll receipt
Average offset A = (0 + o_1 + o_2 + ... + o_n) / (n + 1)
Client correction_i = A − o_i
Master correction = A
Group target = Previous master time + A
Group error_i = |Corrected client time − Adjusted master time|
Reference error_i = |Corrected client time − Trusted reference time|
```

For ideal measurements and offsets `−5, +8, +3 s`, the average including the master
is `1.5 s`. The master moves forward by `1.5 s`; the clients receive corrections
`+6.5, −6.5, −1.5 s`. They agree at a group time `1.5 s` ahead of the external
reference. Their group errors can be small while their reference errors remain large.

This implementation uses **measured** offsets, so asymmetric delays affect Berkeley
as well. Polls are sequential; the small drift between polls is not extrapolated
away. Corrections are then applied locally at a common reference epoch. Additional
correction-message transport delay is intentionally not simulated. Only successful
polls enter the average; unreachable clients are excluded and reported as failures.

### Statistics and graph interpretation

```text
Average offset = sum(signed offsets) / number of clients
Minimum/maximum signed offset = min/max(offsets)
Minimum/maximum absolute drift = min/max(|offsets|)
Average synchronization error = sum(target errors) / successful clients
Maximum synchronization error = max(target errors)
Milliseconds = Seconds × 1,000
```

The table's **Target error** is reference error for Cristian and group/master error
for Berkeley. Results also show average external reference error. Failed clients
do not enter success-only error statistics; the success count makes this explicit.

The graph uses **signed reference offsets for both bars**, avoiding a misleading
comparison of signed offsets and absolute errors. Berkeley adds a horizontal
group-target line. The lower plot compares both simulated directions and measured
RTT. Graphs and measurement columns are snapshots, while Current time and Offset
remain live. Switching the algorithm selector does not relabel a previous report.

## Installation

Install Python 3.11 or later with Tcl/Tk support. The standard Windows installer
normally includes it. Open the project folder in VS Code and select its Python
interpreter. No Flask, Django, database or cloud account is required.

After uploading the project to your own repository, substitute its URL:

```powershell
git clone <repository-url>
cd Network-Time-Synchronization
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Using the interpreter path directly avoids PowerShell activation-policy issues.
If using an already activated environment, these are equivalent:

```powershell
pip install -r requirements.txt
python main.py
```

Only Matplotlib is installed through pip. Tkinter, sockets, JSON and threading
are Python standard-library modules, not requirements entries.

## How to run

For this delivered workspace:

```powershell
cd C:\Users\Home\Desktop\CN\Network-Time-Synchronization
python -m pip install -r requirements.txt
python main.py
```

If port 5000 is occupied, stop the other demo or use another port:

```powershell
python main.py --port 5001
```

The GUI owns its server; do not also start `server.py` on the same port. Running
`python server.py` separately is useful only for an independent socket demonstration.
Close the GUI with the normal window close button. It waits for any current request
and releases every listener, including client ports.

## Professor demonstration workflow

1. Launch the application and identify the running reference server and local port.
2. Generate three clients. Point out their different offsets and request/response delays.
3. Select a client to explain its ppm rate error and TCP listener.
4. Click Analyze Drift. Explain signed offset versus absolute accumulated error.
5. Select Cristian's Algorithm, then Synchronize. Watch the log while clocks continue.
6. Explain the measured RTT, half-RTT estimate, corrections and residual errors.
7. Select a row for the sampled server timestamp and original client time.
8. Open Show Graph and compare before/after offsets and directional delays.
9. Close the graph, Reset, and Generate Clients again.
10. Select Berkeley Algorithm and Synchronize.
11. Show the mean offset and the master's adjustment, then the group-target graph line.
12. Compare small group error with potentially larger external reference error.
13. Click Simulate New Delay and rerun to demonstrate uncertainty from asymmetry.
14. Close the application and rerun it to show that the server port is released.

Reset clears clients, listeners, results, statistics, graph windows and the logical
master offset. It leaves the reference server available. Generate Clients also starts
a fresh group. Simulate New Delay preserves current clock values but clears previous
measurements so the displayed delays and result snapshots cannot be confused.

## Example output

The following is an **illustrative calculation**, ignoring OS overhead and ppm drift;
the GUI uses random inputs and measures real elapsed time.

| Client | Before offset | Request / response | RTT | Cristian correction | After offset | Absolute error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Client 1 | −5.000 s | 50 / 250 ms | 300 ms | +4.900 s | −0.100 s | 0.100 s |
| Client 2 | +8.000 s | 120 / 80 ms | 200 ms | −7.980 s | +0.020 s | 0.020 s |
| Client 3 | +3.000 s | 60 / 100 ms | 160 ms | −3.020 s | −0.020 s | 0.020 s |

Average reference error is approximately `0.0467 s`; maximum is `0.1000 s`.

For the same initial offsets in a **fresh Berkeley run with symmetric delays**:

```text
Participating clocks: 3 clients + 1 master
Average offset: (-5 + 8 + 3 + 0) / 4 = +1.500 s
Master correction: +1.500 s
Client corrections: +6.500 s, -6.500 s, -1.500 s
Group offset from external reference: +1.500 s
Group error: near zero, subject to measured network and scheduling effects
External reference error: approximately 1.500 s
```

## Testing

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

Seven tests cover actual socket framing, asymmetric Cristian residuals, Berkeley's
master adjustment, repeat synchronization, reference/group distinction, partial
failures, drift math, port conflicts and server recovery. The GUI lifecycle test
creates a withdrawn Tk root and exercises generation, analysis, both algorithms,
graph creation, invalid input, reset, regeneration and closing during a request.
It verifies that the server port can be bound again after shutdown.

The GUI test requires a desktop/Tk environment; a graph window may briefly appear.
For a server without a display, run only the network tests:

```powershell
python -m unittest discover -s tests -p test_project.py -k NetworkTests -v
```

The delivered project was tested on Windows with Python 3.14.5, Tk 8.6 and
Matplotlib 3.11.0. It targets Python 3.11+, but every supported interpreter version
has not been tested. Timing assertions allow a small scheduling tolerance; a heavily
loaded machine may need a rerun after the load is reduced.

## Error handling and troubleshooting

| Situation | Expected action or behavior |
| --- | --- |
| Port already in use | A message explains how to choose `--port 5001` |
| Server stopped | Start Server before synchronizing |
| No clients | Generate Clients first; an informational dialog explains this |
| Invalid count | Only 3, 4 and 5 are accepted |
| No successful results | Show Graph asks you to synchronize first |
| Connection failure | Report failed/partial status with per-client details |
| Matplotlib missing | Install `requirements.txt`; normal startup still works |
| Tkinter missing | Modify/reinstall Python with Tcl/Tk support |
| Clocks diverge after synchronization | Expected: corrections do not remove oscillator rate error |
| Large Berkeley reference error | Expected: group agreement does not ensure external accuracy |

## Computer Networks concepts used

Client-server architecture; TCP sockets and ports; request-response communication;
TCP byte-stream framing; directional latency and RTT; time servers; distributed
logical clocks; offset versus drift; reference synchronization; group consensus on
time; asymmetric-delay uncertainty; multithreaded network services.

Messages use one JSON object plus a newline per connection. The receiver loops
until it sees the delimiter because TCP does not preserve application message
boundaries. Size limits and socket timeouts prevent malformed or incomplete input
from waiting indefinitely. Listeners bind only to localhost for this demo.

## Screenshots

Save your own screenshots in `screenshots/`:

- `before-sync.png`: three clients and drift analysis.
- `cristian-results.png`: reference corrections and errors.
- `berkeley-results.png`: adjusted master, mean offset and target errors.
- `comparison.png`: before/after graph saved with the Matplotlib toolbar.

These filenames are suggestions, not claims that GUI screenshots are bundled.
The directory contains `.gitkeep` so it is preserved in Git.

## Limitations

- This is a simulator with actual localhost sockets, not a full NTP implementation.
- All clocks share one host's timing source; physical oscillators are modeled with ppm.
- The reference is a stable local baseline, not independently verified UTC.
- Delays are deliberate waits, not measurements of a real remote network path.
- Processing overhead is included in RTT; equal-path-delay assumptions are approximate.
- Berkeley polls sequentially, uses no outlier rejection and applies corrections locally.
- Clocks are stepped, not gradually slewed; drift continues after synchronization.
- No clock election, authenticated time, packet-loss model or persistent history.
- Mean offsets near zero can make Berkeley's output look close to Cristian by chance.

## Future enhancements

Real NTP time sources and protocol; multiple physical computers; IPv4/IPv6
configuration; periodic synchronization; jitter analysis; packet-loss simulation;
outlier rejection; correction delivery over TCP; synchronization history; CSV export;
optional database logs; a separate web dashboard.

## Academic relevance

This project links socket programming with distributed-systems time uncertainty.
Students can inspect every formula, modify offset/drift/delay ranges, compare
reference accuracy with group agreement, and demonstrate the impact of network
asymmetry without external services or specialized hardware.

Suggested explanation: “Different computers have different local clocks. Network
latency makes clock synchronization difficult. Cristian's Algorithm estimates
reference time using RTT, while Berkeley's Algorithm synchronizes a group of clocks
using an average correction.”
````

## 12. Commands to create and run the project in VS Code

The project folder and complete files have already been created in your workspace.
Open a PowerShell terminal and run:

```powershell
cd C:\Users\Home\Desktop\CN\Network-Time-Synchronization
code .
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Choose `.venv\Scripts\python.exe` with VS Code's **Python: Select Interpreter**.
If the `code` command is unavailable, use VS Code → File → Open Folder.
You do not need to activate the environment when using its interpreter directly.

For a normal activated environment:

```powershell
pip install -r requirements.txt
python main.py
```

For a port conflict:

```powershell
python main.py --port 5001
```

To recreate the project elsewhere, create a folder named
`Network-Time-Synchronization`, save sections 4–11 with their stated filenames,
and create `screenshots/`. The delivered folder also includes integration tests:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

## 13. Expected GUI workflow

1. Launch the application and identify the running reference server and local port.
2. Generate three clients. Point out their different offsets and request/response delays.
3. Select a client to explain its ppm rate error and TCP listener.
4. Click Analyze Drift. Explain signed offset versus absolute accumulated error.
5. Select Cristian's Algorithm, then Synchronize. Watch the log while clocks continue.
6. Explain the measured RTT, half-RTT estimate, corrections and residual errors.
7. Select a row for the sampled server timestamp and original client time.
8. Open Show Graph and compare before/after offsets and directional delays.
9. Close the graph, Reset, and Generate Clients again.
10. Select Berkeley Algorithm and Synchronize.
11. Show the mean offset and the master's adjustment, then the group-target graph line.
12. Compare small group error with potentially larger external reference error.
13. Click Simulate New Delay and rerun to demonstrate uncertainty from asymmetry.
14. Close the application and rerun it to show that the server port is released.

Reset clears clients, listeners, results, statistics, graph windows and the logical
master offset. It leaves the reference server available. Generate Clients also starts
a fresh group. Simulate New Delay preserves current clock values but clears previous
measurements so the displayed delays and result snapshots cannot be confused.

## 14. Example output

The following is an **illustrative calculation**, ignoring OS overhead and ppm drift;
the GUI uses random inputs and measures real elapsed time.

| Client | Before offset | Request / response | RTT | Cristian correction | After offset | Absolute error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Client 1 | −5.000 s | 50 / 250 ms | 300 ms | +4.900 s | −0.100 s | 0.100 s |
| Client 2 | +8.000 s | 120 / 80 ms | 200 ms | −7.980 s | +0.020 s | 0.020 s |
| Client 3 | +3.000 s | 60 / 100 ms | 160 ms | −3.020 s | −0.020 s | 0.020 s |

Average reference error is approximately `0.0467 s`; maximum is `0.1000 s`.

For the same initial offsets in a **fresh Berkeley run with symmetric delays**:

```text
Participating clocks: 3 clients + 1 master
Average offset: (-5 + 8 + 3 + 0) / 4 = +1.500 s
Master correction: +1.500 s
Client corrections: +6.500 s, -6.500 s, -1.500 s
Group offset from external reference: +1.500 s
Group error: near zero, subject to measured network and scheduling effects
External reference error: approximately 1.500 s
```

## 15. Explanation of Cristian's Algorithm

Cristian assumes a trusted reference time server.

1. A client connects to the reference server and records monotonic send time `T0`.
2. It waits for its simulated request journey, then sends `TIME_REQUEST`.
3. The server samples reference timestamp `Ts` before the response journey.
4. After the response delay and socket delivery, the client records `T1`.
5. It estimates the current reference time and applies the correction:

```text
RTT = T1 − T0
Estimated one-way delay = RTT / 2
Estimated reference time at receipt = Ts + RTT / 2
Correction = Estimated reference time − Client time at receipt
Corrected client time = Client time + Correction
Reference error = |Corrected client time − Reference time at receipt|
```

`T0` and `T1` use a monotonic timer, so clock corrections cannot distort the RTT.
TCP connection establishment is deliberately excluded from the measurement.
The client's local time and the reference used to evaluate its correction are
sampled at the same receipt epoch. Time continues to advance after that snapshot.

For request delay `d_request` and response delay `d_response`, ignoring overhead:

```text
Signed residual offset ≈ (d_request − d_response) / 2
```

Equal delays are well compensated even if large. **Asymmetry**, processing and
scheduling overhead cause error. The application never adds a fake error value or
forces the error to zero. Small natural residuals may round to zero in the table.

## 16. Explanation of Berkeley Algorithm

Berkeley aims at agreement among participating clocks. It does not assume that the
master has the correct external time.

1. The master connects to each client listener and sends `CLOCK_REQUEST`.
2. The client replies with its logical timestamp, sampled before the return delay.
3. The master estimates each client's time at poll receipt using `timestamp + RTT/2`.
4. It subtracts the master's logical time at that same epoch to estimate offset `o_i`.
5. It averages the available client offsets **including the master's offset 0**.
6. It adjusts the master by the mean and every responding client by `mean − o_i`.

```text
Estimated client time = Polled client timestamp + RTT / 2
Client offset o_i = Estimated client time − Master time at poll receipt
Average offset A = (0 + o_1 + o_2 + ... + o_n) / (n + 1)
Client correction_i = A − o_i
Master correction = A
Group target = Previous master time + A
Group error_i = |Corrected client time − Adjusted master time|
Reference error_i = |Corrected client time − Trusted reference time|
```

For ideal measurements and offsets `−5, +8, +3 s`, the average including the master
is `1.5 s`. The master moves forward by `1.5 s`; the clients receive corrections
`+6.5, −6.5, −1.5 s`. They agree at a group time `1.5 s` ahead of the external
reference. Their group errors can be small while their reference errors remain large.

This implementation uses **measured** offsets, so asymmetric delays affect Berkeley
as well. Polls are sequential; the small drift between polls is not extrapolated
away. Corrections are then applied locally at a common reference epoch. Additional
correction-message transport delay is intentionally not simulated. Only successful
polls enter the average; unreachable clients are excluded and reported as failures.

## 17. Explanation of important formulas

| Formula | Meaning |
| --- | --- |
| `C(t) = R(t) + b + (t - t_start) × ppm / 1,000,000` | Client logical time from reference, base offset and rate error |
| `Offset = C(t) - R(t)` | Signed difference at the same instant; negative is behind |
| `RTT = T1 - T0` | Measured monotonic request/response duration in seconds |
| `Estimated one-way delay = RTT / 2` | Assumes approximately symmetric paths |
| `Estimated reference = Ts + RTT / 2` | Cristian's reference time at response receipt |
| `Correction = Estimated reference - Client time` | Amount added to the logical clock |
| `Error = abs(Corrected time - Target time)` | Absolute target error at a shared measurement epoch |
| `A = (0 + sum(client offsets relative to master)) / (responding clients + 1)` | Berkeley mean includes the master |
| `Client adjustment = A - estimated client offset` | Brings each responding clock toward group time |
| `Master adjustment = A` | The master also participates in Berkeley synchronization |
| `Average error = sum(errors) / successful clients` | Mean absolute error among successful clients |
| `Delay in ms = Delay in s × 1000` | Display unit conversion |

Clock **offset** is measured in seconds; clock **drift rate** is measured in ppm.
The clock still drifts after a one-time correction. The graphs keep both before and
after bars in signed reference-offset units; absolute errors are displayed separately.

Ground truth is available because this is a simulator. It evaluates error but is
never used by an algorithm to erase error. Network asymmetry naturally causes
residuals. For Cristian, the ideal signed residual is `(request - response) / 2`.
Berkeley can achieve close agreement without external accuracy.

## 18. Demo explanation for professor

**Opening (30 seconds):**

“My project is Network Time Synchronization and Clock Drift Analyzer. It shows
why distributed computers can disagree about time and how two algorithms reduce
that disagreement. The application uses real TCP sockets, not only simulated tables.”

**Clocks and network (one minute):**

“This is the reference server on localhost. I generate three clients with independent
offsets and small rate errors. Offset tells us how far a clock is ahead or behind;
drift describes how that difference changes. Each direction has its own network delay.
The live clocks keep updating while requests run in a background thread.”

**Cristian demonstration (one minute):**

“The client records a monotonic send time and asks the server for a timestamp. At
receipt, it computes RTT and adds half of RTT to the timestamp. The difference from
its own time is the correction. The remaining error exists because the request and
response journeys may not take equal time. The graph shows the measured reduction.”

**Berkeley demonstration (one minute):**

“Now I reset and generate another group. The master polls each client over TCP,
estimates its relative offset, and calculates an average including itself. It adjusts
the clients and its own logical clock toward the group time. Notice the group line
can remain away from the external reference even when group errors are small.”

**Engineering and limitations (30 seconds):**

“TCP messages use newline-delimited JSON because TCP is a stream. Tkinter updates
run only on the main thread. A queue carries worker results. Reset and shutdown
close listeners. This educational Berkeley version polls over TCP but applies
corrections locally; it is not a complete NTP protocol or a real multi-machine deployment.”

Use the example table only to explain the math. Do not promise exact random outputs
during a live demo. If the Berkeley average happens to be near zero, regenerate the
group to make the reference-versus-group distinction easier to see.

## 19. Possible viva questions with short answers

| Question | Short answer |
| --- | --- |
| What is clock offset? | The signed difference between two clocks at the same instant. |
| How is drift different? | Drift is the accumulation of clock error due to a differing clock rate. |
| What does 100 ppm mean? | The clock gains or loses 100 microseconds per second. |
| Why synchronize clocks? | To improve coordination and interpretation of timestamps across computers. |
| What is RTT? | The measured duration of a request and its response. |
| Why does Cristian use RTT/2? | It estimates response transit time assuming approximately symmetric paths. |
| Does a larger RTT always cause larger error? | No. Symmetry matters; equal long paths can be compensated well. |
| What causes residual error here? | Directional asymmetry, processing/scheduling overhead and ongoing drift. |
| How does Berkeley differ from Cristian? | Berkeley averages a group; Cristian follows a trusted reference. |
| Why include the master in the mean? | It is one of the participating clocks and must also be corrected. |
| Does Berkeley guarantee UTC accuracy? | No. Clocks can agree while all differ from external time. |
| What happens when a client is unreachable? | It is reported as failed and excluded from the responding group average. |
| Is networking real in this project? | Yes. Time requests and Berkeley polls use localhost TCP sockets. |
| Why TCP? | It provides a simple reliable, ordered byte stream for the educational exchange. |
| Does NTP normally use TCP? | No. This project demonstrates algorithms over TCP; it is not an NTP implementation. |
| Why add a newline to JSON? | TCP does not preserve message boundaries, so a delimiter marks completion. |
| Why use a monotonic timer? | Measuring RTT must not be affected by wall-clock changes or clock corrections. |
| Why does the interface stay responsive? | Networking runs in workers; Tk's main loop only handles UI updates. |
| Can worker threads update Tkinter widgets? | They should not; this application delivers updates through a queue. |
| Are OS clocks modified? | No, only logical simulated clock offsets are adjusted. |
| How is error known? | The simulator has a reference clock used for evaluation, separate from correction formulas. |
| Why do clocks drift again afterward? | A one-time offset correction does not remove clock rate error. |
| What is simplified in Berkeley? | Sequential polling, no outlier rejection, and local correction distribution. |
| Why show group error and reference error? | Agreement within a group and correctness against external time are different properties. |
| What would you add next? | Real remote clocks, periodic synchronization, outlier rejection and NTP integration. |

## 20. GitHub commands to upload the project

Create an **empty** GitHub repository named `Network-Time-Synchronization` in your
account. Do not initialize the remote with another README. Then run the following
from the delivered project directory, substituting your real account name:

```powershell
cd C:\Users\Home\Desktop\CN\Network-Time-Synchronization
git init
git add .
git commit -m "Build network time synchronization and clock drift analyzer"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/Network-Time-Synchronization.git
git push -u origin main
```

Git may ask you to authenticate or configure your author name/email before the first
commit. `.gitignore` excludes `.venv` and Python bytecode. If a remote already exists,
inspect it using `git remote -v` and use the correct existing URL instead of adding
another `origin`. These are instructions; no repository was published automatically.

After upload, another student can run:

```powershell
git clone https://github.com/YOUR-USERNAME/Network-Time-Synchronization.git
cd Network-Time-Synchronization
pip install -r requirements.txt
python main.py
```
