import json
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from dashboard_server import VISION_EMPTY, create_server, read_snapshot


class DashboardSnapshotTests(unittest.TestCase):
    def test_missing_vision_file_is_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            value = read_snapshot(Path(directory) / "missing.json", VISION_EMPTY, 3.0)
        self.assertFalse(value["connected"])
        self.assertEqual(value["boxes"], [])

    def test_stale_vision_is_safely_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vision.json"
            path.write_text(json.dumps({
                "connected": True,
                "updated": time.time() - 20,
                "people": 1,
                "confirmed": True,
                "boxes": [{"x1": 1}],
            }), encoding="utf-8")
            value = read_snapshot(path, VISION_EMPTY, 3.0)
        self.assertFalse(value["connected"])
        self.assertEqual(value["people"], 0)
        self.assertEqual(value["boxes"], [])


class DashboardHTTPTests(unittest.TestCase):
    def test_dashboard_and_all_sources_work_without_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / "web"
            web.mkdir()
            (web / "index.html").write_text("dashboard-ready", encoding="utf-8")
            server = create_server("127.0.0.1", 0, root / "output", web)
            server.public_access = True
            server.upstreams = {"vision": "", "flight_controller": "", "ground_terminal": ""}
            from threading import Thread
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/", timeout=1) as response:
                    self.assertEqual(response.read(), b"dashboard-ready")
                for endpoint in ("/status.json", "/telemetry.json", "/ground.json", "/api/sources"):
                    with urllib.request.urlopen(base + endpoint, timeout=1) as response:
                        value = json.load(response)
                        self.assertEqual(response.status, 200)
                        self.assertIsInstance(value, dict)
                with urllib.request.urlopen(base + "/api/sources", timeout=1) as response:
                    sources = json.load(response)
                self.assertTrue(sources["platform"]["connected"])
                self.assertFalse(sources["air_unit"]["connected"])
                self.assertFalse(sources["vision"]["connected"])
                self.assertFalse(sources["flight"]["connected"])
                self.assertFalse(sources["video"]["connected"])
                self.assertFalse(sources["ground"]["connected"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
