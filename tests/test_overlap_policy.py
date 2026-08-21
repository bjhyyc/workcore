from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from build import controlled_overlap_reason  # noqa: E402


class ControlledOverlapPolicyTests(unittest.TestCase):
    def test_hmi_cannot_use_the_opposite_armrest_as_a_controlled_host(self) -> None:
        self.assertIsNone(
            controlled_overlap_reason("hmi_status_display_left", "armrest_lid_right", "seat")
        )
        self.assertEqual(
            controlled_overlap_reason("hmi_status_display_left", "armrest_lid_left", "seat"),
            "armrest_hmi_mounted_interface",
        )

    def test_drawer_rule_rejects_cross_side_and_cross_tier_pairs(self) -> None:
        self.assertIsNone(
            controlled_overlap_reason("drawer_tray_left_upper", "cots_latch_right_upper", "stowed")
        )
        self.assertIsNone(
            controlled_overlap_reason("drawer_tray_left_upper", "cots_latch_left_lower", "stowed")
        )
        self.assertEqual(
            controlled_overlap_reason("drawer_tray_left_upper", "cots_latch_left_upper", "stowed"),
            "drawer_fastened_interface",
        )

    def test_desk_rule_rejects_opposite_side_lid_or_shell(self) -> None:
        self.assertIsNone(
            controlled_overlap_reason("desk_panel_left", "armrest_lid_right", "desk")
        )
        self.assertIsNone(
            controlled_overlap_reason("desk_bundle_stowed_left", "armrest_shell_right", "seat")
        )
        self.assertEqual(
            controlled_overlap_reason("desk_panel_left", "armrest_lid_left", "desk"),
            "desk_fastened_or_latched_interface",
        )

    def test_closed_transfer_hardware_uses_only_explicit_base_shell_pairs(self) -> None:
        self.assertEqual(
            controlled_overlap_reason(
                "armrest_base_shell_right", "armrest_transfer_link_right", "seat"
            ),
            "transfer_closed_mount_inside_base_shell",
        )
        self.assertIsNone(
            controlled_overlap_reason(
                "armrest_base_shell_left", "armrest_transfer_link_right", "seat"
            )
        )


if __name__ == "__main__":
    unittest.main()
