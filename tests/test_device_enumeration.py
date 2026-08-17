"""Regression tests for IMV physical-device enumeration."""

from __future__ import annotations

import unittest

from scanner.device import _deduplicate_physical_devices


class DeduplicatePhysicalDevicesTest(unittest.TestCase):
    """Verify stale SDK entries do not look like extra physical scanners."""

    def test_same_mac_is_one_device_and_latest_entry_wins(self) -> None:
        """Collapse formatting variants of one MAC and retain current metadata."""
        devices = [
            {
                "index": 0,
                "camera_type": "GigE",
                "serial_number": "SCANNER-1",
                "mac_address": "00:11:22:AA:BB:CC",
                "ip_address": "192.168.1.20",
            },
            {
                "index": 1,
                "camera_type": "GigE",
                "serial_number": "SCANNER-1",
                "mac_address": "001122aabbcc",
                "ip_address": "192.168.40.200",
            },
        ]

        result = _deduplicate_physical_devices(devices)

        self.assertEqual(1, len(result))
        self.assertEqual(1, result[0]["index"])
        self.assertEqual("192.168.40.200", result[0]["ip_address"])

    def test_different_macs_remain_two_devices(self) -> None:
        """Do not collapse two physical GigE scanners even if labels match."""
        devices = [
            {"index": 0, "serial_number": "SAME", "mac_address": "00:11:22:33:44:55"},
            {"index": 1, "serial_number": "SAME", "mac_address": "00:11:22:33:44:66"},
        ]

        result = _deduplicate_physical_devices(devices)

        self.assertEqual(2, len(result))

    def test_usb_device_falls_back_to_serial_number(self) -> None:
        """Collapse duplicate USB entries by serial number when MAC is absent."""
        devices = [
            {"index": 0, "serial_number": "USB-123", "mac_address": ""},
            {"index": 1, "serial_number": "usb123", "mac_address": ""},
        ]

        result = _deduplicate_physical_devices(devices)

        self.assertEqual(1, len(result))
        self.assertEqual(1, result[0]["index"])

    def test_missing_hardware_identity_is_not_collapsed(self) -> None:
        """Keep anonymous SDK entries because their physical identity is unknown."""
        devices = [
            {"index": 0, "serial_number": "", "mac_address": "", "camera_key": ""},
            {"index": 1, "serial_number": "", "mac_address": "", "camera_key": ""},
        ]

        result = _deduplicate_physical_devices(devices)

        self.assertEqual(2, len(result))


if __name__ == "__main__":
    unittest.main()
