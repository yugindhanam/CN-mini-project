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
