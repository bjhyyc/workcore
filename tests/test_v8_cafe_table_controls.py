from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cadquery as cq


ROOT = Path(__file__).resolve().parents[1]
CAD_DIR = (
    ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
)
if str(CAD_DIR) not in sys.path:
    sys.path.insert(0, str(CAD_DIR))

from skin_upper import _table_parts  # noqa: E402
from v8_cafe_table_root_motion import (  # noqa: E402
    CAFE_INTERNAL_CAVITY_Y_MAX_MM,
    CAFE_INTERNAL_CAVITY_Y_MIN_MM,
    cafe_root_motion_poses,
    cafe_table_control_final_occurrences,
    cafe_table_control_pose,
)
from v8_table_lid_packaging import cafe_half_leaf_pair  # noqa: E402


CONTROL_NAMES = (
    "A09_cafe_lock_release_paddle_right",
    "A09_cafe_positive_lock_witness_right",
)


class V8CafeTableControlTests(unittest.TestCase):
    def test_final_skin_uses_the_same_two_control_breps_and_ids(self) -> None:
        production = {part.name: part for part in _table_parts("cafe")}
        references = cafe_table_control_final_occurrences()
        self.assertEqual(tuple(item.name for item in references), CONTROL_NAMES)
        self.assertEqual(
            len({item.physical_occurrence_id for item in references}),
            2,
        )
        for reference in references:
            actual = production[reference.name]
            self.assertEqual(
                actual.metadata["physical_occurrence_id"],
                reference.physical_occurrence_id,
            )
            self.assertLessEqual(reference.shape.distance(actual.shape), 1.0e-7)
            self.assertLessEqual(
                abs(reference.shape.Volume() - actual.shape.Volume()),
                1.0e-6,
            )
            self.assertAlmostEqual(
                reference.shape.intersect(actual.shape).Volume(),
                reference.shape.Volume(),
                places=5,
            )

    def test_controls_remain_fixed_inside_armrest_and_clear_root_motion(self) -> None:
        roots = cafe_root_motion_poses(21)
        reference_volumes = {
            item.physical_occurrence_id: item.shape.Volume()
            for item in cafe_table_control_pose(0.0, 0.0)
        }
        minimum_carriage_gap = float("inf")
        minimum_fixed_gap = float("inf")
        minimum_leaf_gap = float("inf")
        for frame, root_pose in enumerate(roots):
            if frame <= 20:
                rotation = frame / 20.0
                returned = 0.0
            else:
                rotation = 1.0
                returned = (frame - 20) / 20.0
            controls = cafe_table_control_pose(rotation, returned)
            leaves = cafe_half_leaf_pair(rotation, returned)
            by_name = {item.name: item for item in root_pose}
            carriage = by_name[
                "A09_cafe_underleaf_motion_belly_right"
            ].shape
            fixed = (
                by_name["A09_cafe_fixed_root_housing_right"].shape,
                by_name["A09_cafe_fixed_yoke_bearing_carrier_right"].shape,
            )
            self.assertEqual(tuple(item.name for item in controls), CONTROL_NAMES)
            for control in controls:
                self.assertAlmostEqual(
                    control.shape.Volume(),
                    reference_volumes[control.physical_occurrence_id],
                    places=5,
                )
                reference = {
                    item.name: item
                    for item in cafe_table_control_pose(0.0, 0.0)
                }[control.name]
                self.assertLessEqual(
                    control.shape.distance(reference.shape),
                    1.0e-7,
                )
                self.assertAlmostEqual(
                    control.shape.intersect(reference.shape).Volume(),
                    control.shape.Volume(),
                    places=5,
                )
                control_box = control.shape.BoundingBox()
                self.assertGreaterEqual(
                    control_box.ymin,
                    CAFE_INTERNAL_CAVITY_Y_MIN_MM,
                )
                self.assertLessEqual(
                    control_box.ymax,
                    CAFE_INTERNAL_CAVITY_Y_MAX_MM,
                )
                for root in root_pose:
                    distance = control.shape.distance(root.shape)
                    if distance <= 1.0e-6:
                        self.assertLessEqual(
                            control.shape.intersect(root.shape).Volume(),
                            1.0e-6,
                            msg=f"frame={frame} {control.name}->{root.name}",
                        )
                minimum_carriage_gap = min(
                    minimum_carriage_gap,
                    control.shape.distance(carriage),
                )
                minimum_fixed_gap = min(
                    minimum_fixed_gap,
                    *(control.shape.distance(item) for item in fixed),
                )
                minimum_leaf_gap = min(
                    minimum_leaf_gap,
                    *(control.shape.distance(item.shape) for item in leaves),
                )
        self.assertGreaterEqual(minimum_carriage_gap, 14.0)
        self.assertGreaterEqual(minimum_fixed_gap, 1.0)
        self.assertGreaterEqual(minimum_leaf_gap, 55.0)

    def test_control_step_roundtrip_preserves_solids_and_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for control in cafe_table_control_final_occurrences():
                path = Path(directory) / f"{control.name}.step"
                cq.exporters.export(control.shape, str(path))
                imported = cq.importers.importStep(str(path)).val()
                self.assertTrue(imported.isValid())
                self.assertEqual(len(imported.Solids()), 1)
                self.assertLessEqual(
                    abs(imported.Volume() - control.shape.Volume()),
                    0.05,
                )


if __name__ == "__main__":
    unittest.main()
