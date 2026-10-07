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
