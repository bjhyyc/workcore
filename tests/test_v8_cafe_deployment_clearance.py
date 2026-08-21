from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLASS_A = (
    ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
)
for path in (ROOT, CLASS_A):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from skin_upper import build_upper_skin  # noqa: E402
from v8_cafe_deployment_clearance import (  # noqa: E402
    critical_cafe_deployment_report,
)
from v8_cafe_table_root_motion import (  # noqa: E402
    CAFE_ROTATION_CLEARANCE_LIFT_MM,
    cafe_root_motion_pose,
    cafe_transient_support_envelope,
)
from v8_table_lid_packaging import TABLE_ACCESS_SEQUENCE  # noqa: E402


class V8CafeDeploymentClearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parts = build_upper_skin("cafe")
        cls.by_name = {part.name: part for part in cls.parts}

    def test_same_height_path_is_rejected_but_ninety_mm_path_is_clear(self) -> None:
        moving = next(
            item
            for item in cafe_root_motion_pose(0.5, 0.0)
            if item.name == "A09_cafe_underleaf_motion_belly_right"
        ).shape
        obstacles = (
            self.by_name["A05_armrest_table_bay_shell_right"].shape,
            self.by_name["A05_armrest_touch_lid_right"].shape,
            self.by_name["A05_right_removable_drive_pod"].shape,
            self.by_name["A05_right_joystick"].shape,
        )
        old_common = sum(
            float(moving.intersect(obstacle).Volume()) for obstacle in obstacles
        )
        self.assertGreater(old_common, 1.0)

        raised = moving.translate(
            (0.0, 0.0, CAFE_ROTATION_CLEARANCE_LIFT_MM)
        )
        new_common = sum(
            float(raised.intersect(obstacle).Volume()) for obstacle in obstacles
        )
        self.assertLessEqual(new_common, 1.0e-5)

    def test_complete_sequence_uses_real_table_layers_and_unchanged_endpoint(
        self,
    ) -> None:
        report = critical_cafe_deployment_report(
            self.parts,
            motion_samples_per_leg=5,
            lid_sweep_samples=6,
        )
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["collision_count"], 0)
        self.assertEqual(report["clearance_lift_mm"], 90.0)
        self.assertTrue(report["final_endpoint_unchanged"])
        self.assertGreaterEqual(
            report["minimum_fixed_control_clearance_mm"],
            5.0,
        )
        self.assertEqual(report["table_access_sequence"], list(TABLE_ACCESS_SEQUENCE))
        self.assertIn(
            "raise_table_90_mm_above_fixed_control_sweep",
            TABLE_ACCESS_SEQUENCE,
        )
        self.assertIn(
            "lower_and_confirm_final_root_lock",
            TABLE_ACCESS_SEQUENCE,
        )
        self.assertEqual(
            len(report["released_table_rigid_layer_inventory"]),
            7,
        )
        self.assertTrue(
            all(
                evidence["status"] == "PASS"
                for evidence in report["final_brep_identity"].values()
            )
        )

    def test_guided_support_is_valid_and_uses_the_released_passage(self) -> None:
        support = cafe_transient_support_envelope(1.0, 1.0, 0.0)
        self.assertTrue(support.shape.isValid())
        self.assertGreater(float(support.shape.Volume()), 0.0)
        gland = self.by_name[
            "A05_right_table_root_tongue_compression_gland"
        ].shape
        shell = self.by_name["A05_armrest_table_bay_shell_right"].shape
        lid = self.by_name["A05_armrest_touch_lid_right"].shape
        self.assertLessEqual(float(support.shape.intersect(gland).Volume()), 1.0e-5)
        self.assertLessEqual(float(support.shape.intersect(shell).Volume()), 1.0e-5)
        self.assertLessEqual(float(support.shape.intersect(lid).Volume()), 1.0e-5)


if __name__ == "__main__":
    unittest.main()
