"""Load test for Lap API using locust.

Run:
    pip install locust
    locust -f scripts/load_test.py --host http://localhost:5000

Target concurrency: 50 users for baseline, 200 for stress.
"""
from __future__ import annotations

import os
import random
import tempfile

from locust import HttpUser, between, task


class TelemetryUser(HttpUser):
    """Simulates a typical Lap user: health check, session list, upload."""

    wait_time = between(1, 5)

    @task(10)
    def health_check(self):
        self.client.get("/healthz", name="/healthz")

    @task(5)
    def session_list(self):
        self.client.get(
            "/api/v1/sessions",
            name="/api/v1/sessions",
            headers=self._auth_headers(),
        )

    @task(2)
    def session_detail(self):
        self.client.get(
            "/api/v1/sessions/1",
            name="/api/v1/sessions/:id",
            headers=self._auth_headers(),
        )

    @task(1)
    def upload_small_csv(self):
        """Upload a minimal synthetic CSV (tests ingest path without large data)."""
        csv_content = self._synthetic_csv(rows=100)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(csv_content.encode())
            f.flush()
            with open(f.name, "rb") as upload:
                self.client.post(
                    "/api/v1/sessions/upload",
                    files={"file": ("test_session.csv", upload, "text/csv")},
                    name="/api/v1/sessions/upload",
                    headers=self._auth_headers(),
                )
            os.unlink(f.name)

    def _auth_headers(self) -> dict:
        token = os.environ.get("LOAD_TEST_TOKEN", "")
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    @staticmethod
    def _synthetic_csv(rows: int = 100) -> str:
        header = '"Lap #","Time (s)","Speed (m/s)","Latitude (deg)","Longitude (deg)"'
        lines = [header]
        for i in range(rows):
            t = i * 0.1
            speed = 15.0 + random.uniform(-2, 2)
            lat = 45.0 + i * 0.0001
            lon = 7.0 + i * 0.0001
            lines.append(f'1,{t:.2f},{speed:.2f},{lat:.6f},{lon:.6f}')
        return "\n".join(lines)
