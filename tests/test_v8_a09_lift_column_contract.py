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

from build_class_a_skin import (  # noqa: E402
    _roundtrip_signature_failures,
    _shape_signature,
    _signature_delta,
)
from skin_upper import _armrest_shell, build_upper_skin  # noqa: E402


STATES = ("follow", "ride", "cafe", "focus")
CAFE_FINAL_ROOT_NAMES = {
    "A09_cafe_fixed_root_housing_right",
    "A09_cafe_fixed_yoke_bearing_carrier_right",
    "A09_cafe_rotary_hub_right",
    "A09_cafe_rotary_linear_rail_right",
    "A09_cafe_underleaf_motion_belly_right",
}
FOCUS_RETIRED_TOKENS = (
    "focus_armrest_to_table_root_bridge",
    "focus_root_fairing",
    "focus_underleaf_saddle",
    "focus_underleaf_motion_belly",
    "focus_table_root_crown",
    "focus_table_mount_shoe",
    "table_lift_boot",
    "table_lift_moving_stage",
)


class V8A09LayoutArchitectureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Upper-skin only: this deliberately avoids every full-state CAD build.
        cls.cafe = build_upper_skin("cafe")
        cls.focus = build_upper_skin("focus")

    def test_a05_bilateral_metal_cassettes_are_state_invariant(self) -> None:
        for side, side_sign in (("left", -1), ("right", 1)):
            name = f"A05_table_root_structural_cassette_{side}"
            assemblies = {
                state: {
                    part.name: part
                    for part in _armrest_shell(side_sign, state)
                }
                for state in STATES
            }
            occurrences = {
                state: assembly[name]
                for state, assembly in assemblies.items()
            }
            reference = occurrences["follow"]
            reference_signature = _shape_signature(reference.shape)
            reference_id = reference.metadata["physical_occurrence_id"]

            self.assertIn("stainless", reference.material.lower())
            self.assertTrue(reference.metadata["primary_table_load_path"])
            self.assertTrue(
                reference.metadata["state_invariant_physical_occurrence"]
            )
            self.assertFalse(reference.metadata["final_exterior_visible"])
            for state, occurrence in occurrences.items():
                before = reference_signature
                after = _shape_signature(occurrence.shape)
                delta = _signature_delta(before, after)
                with self.subTest(side=side, state=state):
                    self.assertEqual(
                        occurrence.metadata["physical_occurrence_id"],
                        reference_id,
                    )
                    self.assertTrue(occurrence.metadata["primary_table_load_path"])
                    self.assertFalse(
                        occurrence.metadata["final_exterior_visible"]
                    )
                    self.assertEqual(
                        _roundtrip_signature_failures(
                            before,
                            after,
                            delta,
                            exact_topology=True,
                        ),
                        [],
                    )
                    shell = assemblies[state][
                        f"A05_armrest_table_bay_shell_{side}"
                    ]
                    self.assertLessEqual(
                        shell.shape.intersect(occurrence.shape).Volume(),
                        1.0e-5,
                    )
                    self.assertGreaterEqual(
                        shell.shape.distance(occurrence.shape),
                        0.999,
                    )
                    self.assertEqual(
                        shell.metadata[
                            "table_root_cassette_internal_clearance_mm"
                        ],
                        1.0,
                    )
                    self.assertFalse(
                        shell.metadata[
                            "table_root_cassette_keepout_reaches_exterior"
                        ]
                    )

    def test_cafe_has_five_final_roots_one_internal_envelope_and_one_visible_neck(
        self,
    ) -> None:
        by_name = {part.name: part for part in self.cafe}
        actual_roots = {
            name
            for name in by_name
            if name.startswith("A09_cafe_")
            and name
            not in {
                "A09_cafe_internal_lift_packaging_envelope_right",
                "A09_cafe_lock_release_paddle_right",
                "A09_cafe_positive_lock_witness_right",
            }
        }
        self.assertEqual(actual_roots, CAFE_FINAL_ROOT_NAMES)

        envelope = by_name[
            "A09_cafe_internal_lift_packaging_envelope_right"
        ]
        envelope_box = envelope.shape.BoundingBox()
        self.assertTrue(envelope.metadata["layout_packaging_reservation"])
        self.assertTrue(envelope.metadata["supplier_mechanism_not_frozen"])
        self.assertFalse(envelope.metadata["final_exterior_visible"])
        self.assertGreaterEqual(envelope_box.ymin, 316.0)
        self.assertLessEqual(envelope_box.ymax, 361.5)

        neck_name = "A09_cafe_underleaf_motion_belly_right"
        for name in CAFE_FINAL_ROOT_NAMES:
            part = by_name[name]
            with self.subTest(name=name):
                self.assertEqual(
                    part.metadata["final_exterior_visible"],
                    name == neck_name,
                )
                self.assertTrue(part.metadata["layout_kinematic_envelope_only"])
        neck = by_name[neck_name]
        self.assertTrue(neck.metadata["root_neck_outside_armrest"])
        self.assertFalse(neck.metadata["hinge_bearing_and_lock_outside_armrest"])
        self.assertEqual(neck.metadata["internal_spreader_length_mm"], 220.0)

        names = tuple(by_name)
        self.assertFalse(any("telescopic_rail_cover" in name for name in names))
        self.assertFalse(any("linear_guide_shoe" in name for name in names))
        self.assertFalse(any("table_mount_shoe" in name for name in names))
        torque_key = by_name["A09_cafe_rotary_linear_rail_right"]
        torque_key_box = torque_key.shape.BoundingBox()
        self.assertLessEqual(max(torque_key_box.xlen, torque_key_box.ylen), 6.01)
        self.assertNotIn("nominal_length_mm", torque_key.metadata)
        self.assertNotIn("final_carriage_capture_mm", torque_key.metadata)

    def test_focus_has_two_internal_root_boxes_three_guides_and_visible_necks(
        self,
    ) -> None:
        by_name = {part.name: part for part in self.focus}
        self.assertFalse(
            any(token in name for token in FOCUS_RETIRED_TOKENS for name in by_name)
        )

        for side in ("left", "right"):
            root_box = by_name[f"A09_focus_internal_root_box_{side}"]
            stages = tuple(
                by_name[f"A09_focus_internal_nested_guide_stage_{index}_{side}"]
                for index in (1, 2, 3)
            )
            neck = by_name[f"A09_focus_table_hidden_root_tongue_{side}"]
            cassette = by_name[f"A05_table_root_structural_cassette_{side}"]
            lid_release = by_name[f"A05_armrest_top_lid_release_{side}"]

            with self.subTest(side=side):
                self.assertFalse(root_box.metadata["final_exterior_visible"])
                self.assertTrue(root_box.metadata["closed_bottom"])
                self.assertEqual(root_box.metadata["fixed_to"], cassette.name)
                self.assertTrue(cassette.metadata["primary_table_load_path"])
                self.assertEqual(
                    tuple(stage.metadata["stage_index"] for stage in stages),
                    (1, 2, 3),
                )
                self.assertTrue(
                    all(
                        stage.metadata["independent_physical_stage"]
                        and not stage.metadata["final_exterior_visible"]
                        and stage.metadata["mechanism_z_max_mm"] <= 674.0
                        for stage in stages
                    )
                )
                self.assertTrue(neck.metadata["final_exterior_visible"])
                self.assertTrue(neck.metadata["root_neck_outside_armrest"])
                self.assertFalse(
                    neck.metadata["hinge_bearing_and_lock_outside_armrest"]
                )
                self.assertEqual(neck.metadata["internal_spreader_length_mm"], 220.0)
                self.assertLessEqual(
                    lid_release.shape.intersect(neck.shape).Volume(),
                    1.0e-5,
                )
                self.assertGreaterEqual(
                    lid_release.shape.distance(neck.shape),
                    3.999,
                )
                self.assertEqual(
                    lid_release.metadata[
                        "focus_root_neck_minimum_clearance_mm"
                    ],
                    4.0,
                )
                self.assertEqual(
                    lid_release.metadata["touch_surface"],
                    "fixed_inboard_vertical_face",
                )

    def test_focus_table_limits_and_twelve_millimetre_centre_gap_are_frozen(
        self,
    ) -> None:
        by_name = {part.name: part for part in self.focus}
        left = by_name["A09_table_underbelly_shell_left"].shape.BoundingBox()
        right = by_name["A09_table_underbelly_shell_right"].shape.BoundingBox()
        left_inner = by_name[
            "A09_table_underbelly_shell_left_fold_half_inner"
        ].shape.BoundingBox()
        right_inner = by_name[
            "A09_table_underbelly_shell_right_fold_half_inner"
        ].shape.BoundingBox()
        self.assertAlmostEqual(left.ymin, -276.0, places=6)
        self.assertAlmostEqual(right.ymax, 276.0, places=6)
        self.assertAlmostEqual(right_inner.ymin - left_inner.ymax, 12.0, places=6)


if __name__ == "__main__":
    unittest.main()
