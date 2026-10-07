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
