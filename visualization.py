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
