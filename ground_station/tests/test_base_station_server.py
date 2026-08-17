import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread

from ground_station.base_station_server import create_server


class BaseStationServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["BASE_INGEST_TOKEN"] = "device-token"
        os.environ["BASE_OPERATOR_TOKEN"] = "operator-token"
        self.server = create_server("127.0.0.1", 0, Path(self.temp.name))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()
        os.environ.pop("BASE_INGEST_TOKEN", None)
        os.environ.pop("BASE_OPERATOR_TOKEN", None)

    def request(self, path, payload=None, token=None):
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.base + path, data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.load(response)

    def test_coordinate_to_prepared_mission_flow(self):
        status, ingested = self.request("/api/base/ingest", {
            "device_id": "GROUND-01",
            "latitude": 30.1,
            "longitude": 114.2,
            "battery_percent": 88,
            "targets": [{"latitude": 30.1001, "longitude": 114.2002, "confidence": 0.91}],
        }, "device-token")
        self.assertEqual(status, 200)
        target_id = ingested["target_ids"][0]

        _, confirmed = self.request(f"/api/base/targets/{target_id}/confirm", {}, "operator-token")
        self.assertEqual(confirmed["target"]["status"], "confirmed")

        _, prepared = self.request("/api/base/missions/prepare", {
            "target_id": target_id,
            "aircraft_id": "RESCUE-01",
        }, "operator-token")
        self.assertEqual(prepared["mission"]["status"], "prepared")
        self.assertFalse(prepared["mission"]["dispatch_enabled"])

        _, dispatched = self.request("/api/base/missions/dispatch", {
            "mission_id": prepared["mission"]["mission_id"],
        }, "operator-token")
        self.assertEqual(dispatched["mission"]["status"], "queued")
        self.assertTrue(dispatched["mission"]["dispatch_enabled"])

        _, snapshot = self.request("/api/base/status")
        self.assertEqual(snapshot["connected_devices"], 1)
        self.assertEqual(snapshot["mission"]["target_id"], target_id)
        self.assertEqual(snapshot["mission"]["status"], "queued")

    def test_unified_platform_static_pages_and_video_config(self):
        with urllib.request.urlopen(self.base + "/", timeout=2) as response:
            command_page = response.read().decode("utf-8")
        self.assertIn("综合指挥", command_page)
        self.assertIn("/drone/", command_page)

        with urllib.request.urlopen(self.base + "/drone/", timeout=2) as response:
            drone_page = response.read().decode("utf-8")
        self.assertIn("无人机作业", drone_page)
        self.assertIn("/drone/assets/dashboard.js", drone_page)

        _, config = self.request("/api/platform/config")
        self.assertIn("station_video", config)
        self.assertIn("drone_video", config)

    def test_ingest_rejects_missing_token(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/base/ingest", {"device_id": "GROUND-01"})
        self.assertEqual(context.exception.code, 401)

    def test_unconfirmed_target_cannot_create_mission(self):
        _, ingested = self.request("/api/base/ingest", {
            "device_id": "GROUND-01",
            "targets": [{"latitude": 30.1, "longitude": 114.2, "confidence": 0.8}],
        }, "device-token")
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/base/missions/prepare", {
                "target_id": ingested["target_ids"][0],
                "aircraft_id": "RESCUE-01",
            }, "operator-token")
        self.assertEqual(context.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
