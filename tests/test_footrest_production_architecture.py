from __future__ import annotations

import unittest

from cad.footrest_production_architecture import (
    REQUIRED_PHYSICAL_OCCURRENCE_IDS,
    production_footrest_pose,
    production_motion_contract_evidence,
)


class FootrestProductionArchitectureTests(unittest.TestCase):
    def test_exact_stowed_clearance_and_deployed_datums(self) -> None:
        stowed = production_footrest_pose(0.0)
        clear = production_footrest_pose(0.1)
        extended = production_footrest_pose(0.7)
        deployed = production_footrest_pose(1.0)

        self.assertEqual(stowed.platform_center_mm, (-360.0, 0.0, 147.0))
        self.assertAlmostEqual(clear.platform_center_mm[0], -360.0)
        self.assertAlmostEqual(clear.platform_center_mm[2], 129.0)
        self.assertAlmostEqual(extended.platform_center_mm[0], -587.49242521854)
        self.assertAlmostEqual(extended.platform_center_mm[2], 129.0)
        self.assertAlmostEqual(deployed.platform_center_mm[0], -605.0)
        self.assertAlmostEqual(deployed.platform_center_mm[2], 95.0)
        self.assertEqual(deployed.platform_pitch_deg, 0.0)

    def test_101_pose_law_is_connected_monotonic_and_explicitly_not_released(
        self,
    ) -> None:
        evidence = production_motion_contract_evidence(101)
        self.assertTrue(evidence["platform_x_monotonic_forward"])
        self.assertTrue(evidence["primary_cartridge_travel_monotonic"])
        self.assertLessEqual(evidence["maximum_link_length_error_mm"], 1.0e-9)
        self.assertAlmostEqual(evidence["minimum_platform_bottom_z_mm"], 90.0)
        self.assertAlmostEqual(evidence["tactile_bumper_clearance_mm"], 5.0)
        self.assertFalse(evidence["release_ready"])
        self.assertTrue(evidence["missing_evidence"])
        self.assertEqual(
            evidence["same_required_occurrence_inventory"],
            REQUIRED_PHYSICAL_OCCURRENCE_IDS,
        )

    def test_progress_is_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            production_footrest_pose(-0.001)
        with self.assertRaises(ValueError):
            production_footrest_pose(1.001)


if __name__ == "__main__":
    unittest.main()
