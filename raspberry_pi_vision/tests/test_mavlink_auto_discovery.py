import sys
import types
import unittest
from unittest.mock import patch

if sys.platform == "win32":
    sys.modules.setdefault("termios", types.ModuleType("termios"))
    sys.modules.setdefault("tty", types.ModuleType("tty"))

from mavlink_telemetry import empty_state, preflight_checks, reset_vehicle_state, resolve_serial_path


class MavlinkAutoDiscoveryTests(unittest.TestCase):
    def test_explicit_connection_is_preserved(self):
        self.assertEqual(resolve_serial_path("/dev/custom-fc", []), "/dev/custom-fc")

    def test_auto_selects_the_only_connected_controller(self):
        candidate = "/dev/serial/by-id/usb-ArduPilot_fmuv3_test-if00"
        self.assertEqual(resolve_serial_path("auto", [candidate]), candidate)

    def test_auto_rejects_ambiguous_multiple_controllers(self):
        with self.assertRaises(RuntimeError):
            resolve_serial_path("auto", ["/dev/ttyACM0", "/dev/ttyACM1"])

    def test_auto_reports_no_controller(self):
        with self.assertRaises(FileNotFoundError):
            resolve_serial_path("auto", [])

    def test_vehicle_switch_clears_stale_telemetry(self):
        state = empty_state()
        state.update({"connected": True, "battery_percent": 92, "armed": True})
        reset_vehicle_state(state, "/dev/ttyACM1")
        self.assertFalse(state["connected"])
        self.assertIsNone(state["battery_percent"])
        self.assertIsNone(state["armed"])
        self.assertEqual(state["device"], "/dev/ttyACM1")

    @patch.dict("os.environ", {"GPS_BARO_DEVICE_IDS": "GPS-FC-02"}, clear=False)
    def test_gps_baro_profile_uses_gps_and_barometer(self):
        state = empty_state()
        reset_vehicle_state(state, "/dev/serial/by-id/usb-ArduPilot_GPS-FC-02-if00")
        state.update({
            "connected": True,
            "battery_percent": 95,
            "gps_fix_type": 3,
            "satellites": 8,
            "system_status": 3,
            "ekf_flags": 16,
        })
        state["sensor_health"].update({"gps": True, "barometer": True})
        self.assertEqual(state["vehicle_profile"], "gps_baro")
        self.assertTrue(all(preflight_checks(state).values()))

    @patch.dict("os.environ", {"GPS_BARO_DEVICE_IDS": "GPS-FC-02"}, clear=False)
    def test_gps_baro_profile_blocks_weak_gps(self):
        state = empty_state()
        reset_vehicle_state(state, "/dev/serial/by-id/usb-ArduPilot_GPS-FC-02-if00")
        state.update({"connected": True, "battery_percent": 95, "gps_fix_type": 3, "satellites": 5, "system_status": 3, "ekf_flags": 16})
        state["sensor_health"].update({"gps": True, "barometer": True})
        self.assertFalse(preflight_checks(state)["navigation"])

    @patch.dict("os.environ", {"GPS_BARO_DEVICE_IDS": "GPS-FC-02"}, clear=False)
    def test_gps_baro_profile_blocks_uninitialized_ekf(self):
        state = empty_state()
        reset_vehicle_state(state, "/dev/serial/by-id/usb-ArduPilot_GPS-FC-02-if00")
        state.update({"connected": True, "battery_percent": 95, "gps_fix_type": 3, "satellites": 8, "system_status": 5, "ekf_flags": 1024})
        state["sensor_health"].update({"gps": True, "barometer": True})
        checks = preflight_checks(state)
        self.assertFalse(checks["flight_controller"])
        self.assertFalse(checks["navigation"])


if __name__ == "__main__":
    unittest.main()
