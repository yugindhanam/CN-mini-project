"""Real TCP integration tests plus a withdrawn Tk GUI lifecycle test."""

import socket
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer import ClockAnalyzer
from client import NetworkClient
from server import TimeServer, receive_json
from synchronization import BERKELEY, CRISTIAN, SynchronizationManager
from visualization import create_figure


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.server = TimeServer(port=0)
        self.server.start()
        self.clients = []
        for index, offset in enumerate((-5, 8, 3), start=1):
            client = NetworkClient(f"Client {index}", self.server.clock, offset, 0)
            client.request_delay = 0.05
            client.response_delay = 0.05
            client.start()
            self.clients.append(client)
        self.manager = SynchronizationManager(self.server)

    def tearDown(self):
        for client in self.clients:
            client.stop()
        self.server.stop()

    def test_cristian_asymmetric_network_has_predicted_residual(self):
        self.clients[0].request_delay = 0.05
        self.clients[0].response_delay = 0.25
        report = self.manager.synchronize(self.clients, CRISTIAN)
        self.assertEqual(len(report.results), 3)
        first = report.results[0]
        self.assertGreaterEqual(first.rtt, 0.30)
        self.assertAlmostEqual(first.after_offset, -0.10, delta=0.035)
        self.assertAlmostEqual(first.correction, 4.90, delta=0.035)
        self.assertAlmostEqual(first.target_error, 0.10, delta=0.035)
        for row in report.results[1:]:
            self.assertLess(row.reference_error, 0.035)
        self.assertEqual(len(create_figure(report).axes), 2)

    def test_berkeley_includes_and_corrects_master(self):
        report = self.manager.synchronize(self.clients, BERKELEY)
        # (-5 + 8 + 3 + 0) / 4 = 1.5, not the external reference time.
        self.assertAlmostEqual(report.average_offset, 1.5, delta=0.035)
        self.assertAlmostEqual(self.server.master_offset, 1.5, delta=0.035)
        for row in report.results:
            self.assertLess(row.target_error, 0.035)
            self.assertAlmostEqual(row.after_offset, 1.5, delta=0.05)
            self.assertAlmostEqual(row.reference_error, 1.5, delta=0.05)
        # A second round uses the already adjusted master, not a fresh zero.
        second = self.manager.synchronize(self.clients, BERKELEY)
        self.assertAlmostEqual(second.average_offset, 0.0, delta=0.05)
        # Cristian must still use the unchanged trusted reference.
        third = self.manager.synchronize(self.clients, CRISTIAN)
        self.assertTrue(all(row.reference_error < 0.035 for row in third.results))

    def test_berkeley_asymmetry_and_partial_failure(self):
        self.clients[0].request_delay = 0.05
        self.clients[0].response_delay = 0.25
        self.clients[2].stop()
        report = self.manager.synchronize(self.clients, BERKELEY)
        self.assertEqual(len(report.results), 2)
        self.assertIn("Client 3", report.failures)
        # Estimated offsets are -5.1 and +8; the master contributes 0.
        self.assertAlmostEqual(report.average_offset, 2.9 / 3, delta=0.035)
        self.assertAlmostEqual(report.results[0].target_error, 0.10, delta=0.035)
        self.assertEqual(self.clients[2].clock_offset, 3)

    def test_real_drift_and_statistics(self):
        client = self.clients[0]
        client.drift_ppm = 100
        self.assertAlmostEqual(client.current_offset(client.created_at + 1000), -4.9)
        stats = ClockAnalyzer.analyze(self.clients, client.created_at)
        self.assertAlmostEqual(stats["average_offset"], 2.0)
        self.assertEqual(stats["maximum_drift"], 8)
        self.assertEqual(stats["minimum_drift"], 3)

    def test_stopped_server_invalid_input_and_port_conflict(self):
        with self.assertRaises(ValueError):
            self.manager.synchronize([], CRISTIAN)
        duplicate = TimeServer(port=self.server.port)
        with self.assertRaises(OSError):
            duplicate.start()
        self.server.stop()
        with self.assertRaises(ConnectionError):
            self.manager.synchronize(self.clients, CRISTIAN)
        with self.assertRaises(OSError):
            self.clients[0].request_time(self.server)
        self.server.start()
        self.assertTrue(self.server.running)
        with self.assertRaises(ValueError):
            create_figure(None)

    def test_fragmented_json_and_bad_messages_do_not_kill_server(self):
        with socket.create_connection((self.server.host, self.server.port)) as connection:
            connection.settimeout(2)
            connection.sendall(b'{"type": "TIME_')
            time.sleep(0.01)
            connection.sendall(b'REQUEST"}\n')
            self.assertIn("timestamp", receive_json(connection))
        with socket.create_connection((self.server.host, self.server.port)) as connection:
            connection.settimeout(2)
            connection.sendall(b'[]\n')
            self.assertIn("error", receive_json(connection))
        self.assertIn("timestamp", self.clients[0].request_time(self.server))


class GUITests(unittest.TestCase):
    def test_demo_reset_graph_errors_and_close_during_request(self):
        import tkinter as tk
        from main import TimeSyncApp

        root = tk.Tk()
        root.withdraw()
        app = TimeSyncApp(root, port=0)

        def pump_until(condition, timeout=12):
            deadline = time.monotonic() + timeout
            while not condition() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertTrue(condition(), "GUI operation did not finish in time")

        try:
            pump_until(lambda: app.server.running)
            with patch("main.messagebox.showinfo") as info:
                app.synchronize()
                app.open_graph()
                self.assertEqual(info.call_count, 2)
            with patch("main.messagebox.showerror") as error:
                app.client_count.set("7")
                app.generate_clients()
                error.assert_called_once()
            app.client_count.set("3")
            app.generate_clients()
            pump_until(lambda: not app.busy and len(app.table.get_children()) == 3)
            app.analyze_drift()
            self.assertIn("mean", app.statistics.get())
            for client in app.clients:
                client.request_delay = client.response_delay = 0.05
            app.synchronize()
            pump_until(lambda: not app.busy)
            self.assertEqual(len(app.report.results), 3)
            self.assertIn("SUCCESS", app.result_text.get())
            app.table.selection_set("Client 1")
            app._show_details()
            self.assertIn("Server timestamp", app.details.get())
            app.open_graph()
            self.assertTrue(app.graph_windows[-1].winfo_exists())
            app.graph_windows[-1].withdraw()
            app.reset()
            pump_until(lambda: not app.busy)
            self.assertEqual(app.table.get_children(), ())
            self.assertIsNone(app.report)
            self.assertEqual(app.graph_windows, [])
            app.client_count.set("5")
            app.generate_clients()
            pump_until(lambda: not app.busy)
            self.assertEqual(len(app.clients), 5)
            app.algorithm.set(BERKELEY)
            app._algorithm_changed()
            for client in app.clients:
                client.request_delay = client.response_delay = 0.05
            app.synchronize()
            pump_until(lambda: not app.busy)
            self.assertEqual(len(app.report.results), 5)
            self.assertIn("Berkeley mean", app.result_text.get())
            app.new_delays()
            self.assertIsNone(app.report)
            self.assertTrue(all(0.05 <= c.request_delay <= 0.5 for c in app.clients))
            port = app.server.port
            app.synchronize()
            app.close()
            pump_until(lambda: app.shutting_down and not app.server.running)
            # Wait for root destruction, after every listener is closed.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    if not root.winfo_exists():
                        break
                    root.update()
                    time.sleep(0.01)
                except tk.TclError:
                    break
            replacement = TimeServer(port=port)
            replacement.start()
            replacement.stop()
            self.assertTrue(all(not client.service.running for client in app.clients))
        finally:
            for client in app.clients:
                client.stop()
            app.server.stop()
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
