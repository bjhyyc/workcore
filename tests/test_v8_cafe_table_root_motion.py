from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from cadquery import exporters, importers


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

from build_class_a_skin import (  # noqa: E402
    _roundtrip_signature_failures,
    _shape_signature,
    _signature_delta,
)
from skin_upper import _table_root_structural_cassette  # noqa: E402
from v8_cafe_table_root_motion import (  # noqa: E402
    CAFE_FINAL_RAIL_CAPTURE_MM,
    CAFE_INTERNAL_CAVITY_Y_MAX_MM,
    CAFE_INTERNAL_CAVITY_Y_MIN_MM,
    CAFE_RETURN_TRAVEL_MM,
    cafe_root_final_occurrences,
    cafe_root_motion_pose,
    cafe_root_motion_poses,
)
from v8_table_lid_packaging import cafe_half_leaf_pair  # noqa: E402


BOOLEAN_TOLERANCE_MM3 = 1.0e-5
FINAL_NAMES = (
    "A09_cafe_fixed_root_housing_right",
    "A09_cafe_fixed_yoke_bearing_carrier_right",
    "A09_cafe_rotary_hub_right",
    "A09_cafe_rotary_linear_rail_right",
    "A09_cafe_underleaf_motion_belly_right",
)
FINAL_ROLES = (
    "fixed_drainable_yoke_housing",
    "fixed_aluminium_yoke_outer_race_and_lift_collar",
    "catalog_bearing_inner_race_and_rail_pedestal",
    "internal_rotary_torque_key",
    "table_attached_closed_root_neck_and_internal_spreader",
)


def _by_name(progress_rotation: float, progress_return: float):
    return {
        item.name: item
        for item in cafe_root_motion_pose(progress_rotation, progress_return)
    }


class V8CafeTableRootMotionTests(unittest.TestCase):
    def test_inventory_is_exactly_five_conserved_final_root_occurrences(self) -> None:
        poses = cafe_root_motion_poses(9)
        reference = poses[0]
        reference_ids = tuple(item.physical_occurrence_id for item in reference)
        reference_volumes = {
            item.physical_occurrence_id: float(item.shape.Volume())
            for item in reference
        }

        self.assertEqual(tuple(item.name for item in reference), FINAL_NAMES)
        self.assertEqual(tuple(item.role for item in reference), FINAL_ROLES)
        self.assertEqual(len(set(reference_ids)), 5)
        self.assertFalse(
            any(
                forbidden in item.name
                for item in reference
                for forbidden in (
                    "telescopic_rail_cover",
                    "linear_guide_shoe",
                    "table_mount_shoe",
                )
            )
        )
        for frame, pose in enumerate(poses):
            with self.subTest(frame=frame):
                self.assertEqual(tuple(item.name for item in pose), FINAL_NAMES)
                self.assertEqual(
                    tuple(item.physical_occurrence_id for item in pose),
                    reference_ids,
                )
                for item in pose:
                    self.assertTrue(item.shape.isValid())
                    self.assertEqual(len(item.shape.Solids()), 1)
                    self.assertAlmostEqual(
                        float(item.shape.Volume()),
                        reference_volumes[item.physical_occurrence_id],
                        places=5,
                    )

    def test_rotate_then_return_interlock_and_motion_ownership(self) -> None:
        with self.assertRaisesRegex(ValueError, "interlocked"):
            cafe_root_motion_pose(0.95, 0.01)

        start = _by_name(0.0, 0.0)
        rotated = _by_name(1.0, 0.0)
        final = _by_name(1.0, 1.0)
        neck_name = "A09_cafe_underleaf_motion_belly_right"
        key_name = "A09_cafe_rotary_linear_rail_right"

        for name in FINAL_NAMES[:2]:
            self.assertAlmostEqual(
                start[name].shape.Center().x,
                final[name].shape.Center().x,
                places=6,
            )
            self.assertAlmostEqual(
                start[name].shape.Center().y,
                final[name].shape.Center().y,
                places=6,
            )
        self.assertNotAlmostEqual(
            start[key_name].shape.Center().x,
            rotated[key_name].shape.Center().x,
            places=3,
        )
        self.assertAlmostEqual(
            final[key_name].shape.Center().x,
            rotated[key_name].shape.Center().x,
            places=6,
        )
        self.assertAlmostEqual(
            final[neck_name].shape.Center().x
            - rotated[neck_name].shape.Center().x,
            CAFE_RETURN_TRAVEL_MM,
            places=6,
        )

    def test_bearing_key_hardware_remains_inside_right_armrest_cavity(self) -> None:
        for frame, pose in enumerate(cafe_root_motion_poses(9)):
            for item in pose[:4]:
                box = item.shape.BoundingBox()
                with self.subTest(frame=frame, name=item.name):
                    self.assertGreaterEqual(
                        box.ymin,
                        CAFE_INTERNAL_CAVITY_Y_MIN_MM,
                    )
                    self.assertLessEqual(
                        box.ymax,
                        CAFE_INTERNAL_CAVITY_Y_MAX_MM,
                    )

    def test_table_attached_neck_never_collides_with_fixed_root_housing(self) -> None:
        # Detailed supplier bearings/guides are intentionally not frozen at this
        # layout stage.  The hard packaging claim is narrower: the one moving
        # exterior neck must not cut through the fixed drainable housing.
        for frame, pose in enumerate(cafe_root_motion_poses(9)):
            by_name = {item.name: item.shape for item in pose}
            housing = by_name["A09_cafe_fixed_root_housing_right"]
            neck = by_name["A09_cafe_underleaf_motion_belly_right"]
            with self.subTest(frame=frame):
                self.assertLessEqual(
                    float(housing.intersect(neck).Volume()),
                    BOOLEAN_TOLERANCE_MM3,
                )

    def test_final_load_path_contacts_the_a05_cassette_and_closed_root_neck(
        self,
    ) -> None:
        final = {item.name: item.shape for item in cafe_root_final_occurrences()}
        chain = (
            _table_root_structural_cassette(1),
            *(final[name] for name in FINAL_NAMES),
        )
        for index, (first, second) in enumerate(zip(chain, chain[1:])):
            with self.subTest(interface=index):
                self.assertLessEqual(
                    float(first.intersect(second).Volume()),
                    BOOLEAN_TOLERANCE_MM3,
                )
                self.assertLessEqual(float(first.distance(second)), 0.05)

        torque_key = final["A09_cafe_rotary_linear_rail_right"]
        key_box = torque_key.BoundingBox()
        self.assertLessEqual(max(key_box.xlen, key_box.ylen, key_box.zlen), 6.01)
        self.assertEqual(CAFE_FINAL_RAIL_CAPTURE_MM, 0.0)

    def test_final_cafe_table_keeps_original_positive_276_millimetre_limit(
        self,
    ) -> None:
        inner, outer = cafe_half_leaf_pair(1.0, 1.0)
        self.assertAlmostEqual(inner.shape.BoundingBox().ymax, 276.0, places=6)
        self.assertAlmostEqual(outer.shape.BoundingBox().ymax, 276.0, places=6)

    def test_five_final_root_breps_survive_step_roundtrip(self) -> None:
        final = _by_name(1.0, 1.0)
        with tempfile.TemporaryDirectory() as temp_dir:
            for name in FINAL_NAMES:
                before = final[name].shape
                target = Path(temp_dir) / f"{name}.step"
                exporters.export(before, str(target))
                after = importers.importStep(str(target)).val()
                before_signature = _shape_signature(before)
                after_signature = _shape_signature(after)
                failures = _roundtrip_signature_failures(
                    before_signature,
                    after_signature,
                    _signature_delta(before_signature, after_signature),
                )
                with self.subTest(name=name):
                    self.assertTrue(after.isValid())
                    self.assertEqual(len(after.Solids()), 1)
                    self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
