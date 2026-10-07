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
