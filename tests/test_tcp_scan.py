"""Regression tests for Huaray scanner angle conversion."""

from __future__ import annotations

import unittest

from scanner.tcp_scan import huaray_theta_to_degrees


class HuarayThetaConversionTests(unittest.TestCase):
    """Verify clockwise camera readings become counter-clockwise robot offsets."""

    def test_cardinal_angles_follow_robot_direction(self) -> None:
        """Convert the four cardinal camera readings using the robot convention."""
        expected_by_theta = {
            0: 0.0,
            900: -90.0,
            1800: 180.0,
            2700: 90.0,
        }

        for theta, expected in expected_by_theta.items():
            with self.subTest(theta=theta):
                self.assertEqual(expected, huaray_theta_to_degrees(theta))

    def test_small_offsets_reverse_camera_direction(self) -> None:
        """Match the documented 10-degree clockwise and counter-clockwise cases."""
        expected_by_theta = {
            100: -10.0,
            3500: 10.0,
            1: -0.1,
            3599: 0.1,
        }

        for theta, expected in expected_by_theta.items():
            with self.subTest(theta=theta):
                self.assertAlmostEqual(expected, huaray_theta_to_degrees(theta))

    def test_full_turns_are_normalized_before_direction_conversion(self) -> None:
        """Treat equivalent readings outside one turn as the same camera angle."""
        self.assertEqual(-10.0, huaray_theta_to_degrees(3700))
        self.assertEqual(10.0, huaray_theta_to_degrees(-100))


if __name__ == "__main__":
    unittest.main()
