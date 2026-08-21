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

from skin_lower import _footrest_skin, _side_shells, build_lower_skin  # noqa: E402
from skin_upper import build_upper_skin  # noqa: E402
from v8_functional_fixes import apply_v8_functional_fixes  # noqa: E402
from v8_footrest_drawer_brep import (  # noqa: E402
    FIXED_OCCURRENCE_NAMES,
    a08_footrest_drawer_host_corridor,
    a08_footrest_drawer_occurrences,
    a08_footrest_support_host_corridor,
    evaluate_a08_final_body_interfaces,
    evaluate_a08_footrest_drawer_brep,
    evaluate_a08_fixed_host_clearance,
    evaluate_a08_rear_labyrinth_sightlines,
    evaluate_a08_retained_running_gear_clearance,
)


class V8A08CapturedDrawerBRepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # This is the actual one-percent production-motion audit.  Keeping one
        # shared result prevents individual assertions from rerunning 101 exact
        # B-Rep sweeps.
        cls.evidence = evaluate_a08_footrest_drawer_brep(101)
        release = next(
            part.shape
            for part in _footrest_skin("follow")
            if part.name == "A08_manual_release_paddle_shell"
        )
        hosts = {}
        for side_name, side in (("left", -1), ("right", 1)):
            shell = next(
                part.shape
                for part in _side_shells("follow")
                if part.name == f"A02_main_side_shell_{side_name}"
            )
            hosts[side_name] = shell.cut(
                a08_footrest_support_host_corridor(side, 1.0)
            ).clean()
        cls.final_body_evidence = evaluate_a08_final_body_interfaces(
            release,
            hosts,
            2,
        )
        cls.running_gear_evidence = evaluate_a08_retained_running_gear_clearance(
            {
                side: importers.importStep(
                    str(ROOT / "build" / "parts" / f"tyre_front_{side}.step")
                ).val()
                for side in ("left", "right")
            },
            {
                side: importers.importStep(
                    str(
                        ROOT
                        / "build"
                        / "parts"
                        / f"suspension_rocker_{side}.step"
                    )
                ).val()
                for side in ("left", "right")
            },
            101,
        )

    def test_four_primary_states_use_one_inventory_and_correct_endpoints(self) -> None:
        requested = {
            "follow": 0.0,
            "ride": 1.0,
            "cafe": 0.0,
            "focus": 0.0,
        }
        reference_names = tuple(
            sorted(a08_footrest_drawer_occurrences(0.0, "follow"))
        )
        reference_volumes = {
            name: round(shape.Volume(), 6)
            for name, shape in a08_footrest_drawer_occurrences(
                0.0, "follow"
            ).items()
        }
        for state, progress in requested.items():
            with self.subTest(state=state):
                occurrences = a08_footrest_drawer_occurrences(progress, state)
                self.assertEqual(tuple(sorted(occurrences)), reference_names)
                self.assertEqual(len(occurrences), 48)
                for name, shape in occurrences.items():
                    self.assertTrue(shape.isValid())
                    self.assertEqual(len(shape.Solids()), 1)
                    self.assertAlmostEqual(
                        shape.Volume(), reference_volumes[name], places=5
                    )
                platform_x = occurrences["A08_footrest_top_skin"].Center().x
                self.assertAlmostEqual(
                    platform_x, -605.0 if state == "ride" else -360.0, places=6
                )

    def test_101_pose_exact_collision_lock_and_hazard_contract(self) -> None:
        evidence = self.evidence
        self.assertEqual(evidence["samples"], 101)
        self.assertTrue(evidence["same_occurrence_inventory_all_poses"])
        self.assertTrue(evidence["same_occurrence_inventory_all_four_states"])
        self.assertTrue(evidence["all_occurrences_single_valid_solids"])
        self.assertTrue(
            evidence["rigid_occurrence_volume_topology_signature_constant"]
        )
        self.assertLessEqual(
            evidence["maximum_unintended_moving_vs_moving_common_mm3"], 1.0e-6
        )
        self.assertLessEqual(
            evidence["maximum_moving_vs_fixed_common_mm3"], 1.0e-6
        )
        self.assertGreaterEqual(evidence["minimum_root_to_moving_distance_mm"], 5.0)
        self.assertAlmostEqual(
            evidence["minimum_rear_labyrinth_baffle_to_moving_distance_mm"],
            5.0,
            places=6,
        )
        self.assertEqual(
            evidence["closest_rear_labyrinth_baffle_moving_occurrence"],
            "A08_footrest_perimeter_skin",
        )
        self.assertTrue(evidence["lock_pins_retracted_during_motion"])
        self.assertTrue(evidence["stowed_lock_pins_geometrically_engaged"])
        self.assertTrue(evidence["deployed_lock_pins_geometrically_engaged"])
        self.assertTrue(evidence["physical_foot_zone_sensors_present"])
        self.assertFalse(evidence["human_swept_volume_clearance_pass"])
        self.assertTrue(evidence["two_channel_fail_closed_interlock_required"])
        self.assertTrue(evidence["brep_contract_pass"])

    def test_101_pose_final_release_and_a02_host_interfaces(self) -> None:
        evidence = self.final_body_evidence
        self.assertTrue(evidence["pass"], evidence)
        self.assertLessEqual(
            evidence["maximum_undertray_to_body_release_common_mm3"],
            1.0e-6,
        )
        self.assertGreaterEqual(
            evidence["minimum_undertray_to_body_release_gap_mm"],
            2.0 - 1.0e-6,
        )
        self.assertLessEqual(
            evidence["maximum_support_to_a02_host_common_mm3"],
            1.0e-6,
        )
        self.assertGreaterEqual(
            evidence["minimum_support_to_a02_host_gap_mm"],
            1.0 - 1.0e-6,
        )

    def test_xz_motion_complete_a08_inventory_clears_retained_running_gear(self) -> None:
        evidence = self.running_gear_evidence
        self.assertTrue(evidence["pass"], evidence)
        self.assertEqual(evidence["samples"], 2)
        self.assertEqual(evidence["occurrence_count_per_pose"], 48)
        self.assertEqual(
            tuple(evidence["rocker_angles_deg"]),
            (-10.0, -5.0, 0.0, 5.0, 10.0),
        )
        self.assertEqual(evidence["maximum_front_tyre_common_mm3"], 0.0)
        self.assertGreaterEqual(
            evidence["minimum_front_tyre_clearance_mm"],
            12.0 - 1.0e-6,
        )
        self.assertEqual(evidence["maximum_rocker_sweep_common_mm3"], 0.0)
        self.assertGreaterEqual(
            evidence["minimum_rocker_sweep_clearance_mm"],
            3.0 - 1.0e-6,
        )
        self.assertTrue(
            evidence["lateral_bounds_invariant_across_sampled_endpoints"]
        )
        self.assertFalse(evidence["collision_allowlist_permitted"])

    def test_final_platform_solids_are_exact_or_conservatively_contained(self) -> None:
        for state, progress in (("follow", 0.0), ("ride", 1.0)):
            final = {part.name: part.shape for part in _footrest_skin(state)}
            motion = a08_footrest_drawer_occurrences(progress, state)
            for name in (
                "A08_footrest_top_skin",
                "A08_footrest_inset_tread",
            ):
                common = final[name].intersect(motion[name]).Volume()
                symmetric_difference = (
                    final[name].Volume() + motion[name].Volume() - 2.0 * common
                )
                self.assertAlmostEqual(symmetric_difference, 0.0, places=3)
            perimeter_name = "A08_footrest_perimeter_skin"
            self.assertLessEqual(
                final[perimeter_name].cut(motion[perimeter_name]).Volume(),
                1.0e-6,
            )
            self.assertAlmostEqual(
                motion[perimeter_name].cut(final[perimeter_name]).Volume(),
                41_040.0,
                places=3,
            )

    def test_functional_fix_pipeline_preserves_canonical_platform_brep(self) -> None:
        """The final build pass must not introduce a second drain pattern."""

        for state, progress in (
            ("follow", 0.0),
            ("ride", 1.0),
            ("cafe", 0.0),
            ("focus", 0.0),
        ):
            with self.subTest(state=state):
                raw_parts = build_lower_skin(state) + build_upper_skin(state)
                raw = {part.name: part.shape for part in raw_parts}
                fixed = {
                    part.name: part.shape
                    for part in apply_v8_functional_fixes(state, raw_parts)
                }
                motion = a08_footrest_drawer_occurrences(progress, state)
                for name in (
                    "A08_footrest_top_skin",
                    "A08_footrest_inset_tread",
                ):
                    raw_fixed_common = raw[name].intersect(fixed[name]).Volume()
                    raw_fixed_symmetric_difference = (
                        raw[name].Volume()
                        + fixed[name].Volume()
                        - 2.0 * raw_fixed_common
                    )
                    fixed_motion_common = fixed[name].intersect(motion[name]).Volume()
                    fixed_motion_symmetric_difference = (
                        fixed[name].Volume()
                        + motion[name].Volume()
                        - 2.0 * fixed_motion_common
                    )
                    self.assertAlmostEqual(
                        raw_fixed_symmetric_difference, 0.0, places=3
                    )
                    self.assertAlmostEqual(
                        fixed_motion_symmetric_difference, 0.0, places=3
                    )

    def test_permanent_a01_drawer_throat_preserves_motion_breps(self) -> None:
        raw_nose = next(
            part.shape
            for part in build_lower_skin("follow")
            if part.name == "A01_front_nose_shell"
        )
        corridor = a08_footrest_drawer_host_corridor(3.0)
        relieved_nose = raw_nose.cut(corridor)
        self.assertTrue(relieved_nose.isValid())
        self.assertEqual(len(relieved_nose.Solids()), 1)
        evidence = evaluate_a08_fixed_host_clearance(relieved_nose, 21)
        self.assertTrue(evidence["pass"], evidence)
        self.assertEqual(
            evidence["maximum_moving_vs_fixed_host_common_mm3"],
            0.0,
        )

    def test_representative_rigid_occurrences_survive_step_roundtrip(self) -> None:
        occurrences = a08_footrest_drawer_occurrences(0.5, "cafe")
        names = (
            "A08_footrest_platform_undertray_monocoque",
            "A08_footrest_fixed_guide_housing_left",
            "A08_footrest_captured_inner_rail_left",
            "A08_footrest_drop_link_left_front",
            "A08_footrest_stowed_lock_pin_left",
            "A08_footrest_rear_labyrinth_baffle",
        )
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in names:
                source = occurrences[name]
                path = folder / f"{name}.step"
                exporters.export(source, str(path), exportType="STEP")
                loaded = importers.importStep(str(path)).val()
                self.assertTrue(loaded.isValid())
                self.assertEqual(len(loaded.Solids()), 1)
                self.assertAlmostEqual(
                    loaded.Volume(), source.Volume(), delta=source.Volume() * 1.0e-6
                )

    def test_fixed_inventory_contains_root_guides_locks_and_interlock_channels(self) -> None:
        for required in (
            "A08_footrest_root_monocoque",
            "A08_footrest_rear_labyrinth_baffle",
            "A08_footrest_fixed_guide_housing_left",
            "A08_footrest_fixed_guide_housing_right",
            "A08_foot_zone_interlock_channel_a",
            "A08_foot_zone_interlock_channel_b",
            "A08_footrest_manual_release_actuator",
        ):
            self.assertIn(required, FIXED_OCCURRENCE_NAMES)

        fixed = a08_footrest_drawer_occurrences(0.0, "follow")
        for name, expected_y in (
            ("A08_foot_zone_interlock_channel_a", -200.0),
            ("A08_foot_zone_interlock_channel_b", 200.0),
        ):
            center = fixed[name].Center()
            self.assertAlmostEqual(center.x, -450.0, places=6)
            self.assertAlmostEqual(center.y, expected_y, places=6)
            self.assertAlmostEqual(center.z, 250.0, places=6)

    def test_rear_labyrinth_is_fixed_mounted_and_blocks_ride_sightlines(self) -> None:
        evidence = evaluate_a08_rear_labyrinth_sightlines()
        self.assertEqual(evidence["ray_count"], 36)
        self.assertEqual(evidence["ray_y_values_mm"], tuple(range(-240, 241, 60)))
        self.assertEqual(evidence["ray_z_values_mm"], (110.0, 120.0, 135.0, 145.0))
        self.assertTrue(evidence["all_target_ride_front_sightlines_blocked"])
        self.assertGreaterEqual(evidence["minimum_baffle_intercept_x_mm"], 5.999)
        self.assertEqual(evidence["standing_oblique_ray_count"], 10)
        self.assertTrue(evidence["all_standing_oblique_sightlines_blocked"])
        self.assertEqual(evidence["normal_floor_human_common_mm3"], 0.0)
        self.assertGreaterEqual(
            evidence["minimum_normal_floor_human_distance_mm"],
            200.0,
        )
        self.assertTrue(
            evidence["both_guide_mount_feet_face_contact_without_common"]
        )
        self.assertTrue(evidence["same_fixed_baffle_brep_all_four_states"])


if __name__ == "__main__":
    unittest.main()
