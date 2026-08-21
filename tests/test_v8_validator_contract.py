from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

import cadquery as cq

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

from validate_class_a import (  # noqa: E402
    Bounds,
    Checks,
    OpeningRecord,
    PartRecord,
    A06_A07_COMMON_FOLD_HINGE_MM,
    A06_A07_FOLLOW_FOLD_DEG,
    SOURCE_MANIFEST_BASELINE,
    SOURCE_STEP_BASELINE,
    _part_from_object,
    _validate_a07_brep_contract,
    _validate_envelopes,
    _validate_feature_geometry,
    _validate_final_appearance_coverage,
    _validate_openings,
)
from skin_common import SkinPart  # noqa: E402
from source_disposition import (  # noqa: E402
    A07_MECHANISM_ENCLOSURES_BY_STATE,
    CONTROLLED_GLBS,
    _internal_policy,
)
from v8_release_gates import (  # noqa: E402
    _Box,
    _GateBook,
    _envelope_lock_evidence,
    SOURCE_STEPS,
    _gate_a07_single_moving_spine,
    _gate_retract_then_fold,
)
from build_class_a_skin import (  # noqa: E402
    CONTROLLED_SOURCE,
    EXPECTED_DFR5_MANIFEST_SHA256,
    RIGID_PAIR_COLLISION_ALLOWLIST,
    STATES as BUILD_STATES,
    _rigid_collision_report,
)
from v8_final_appearance_closure import (  # noqa: E402
    _production_a07_low_masters,
)


def _check(book: Checks, check_id: str) -> dict[str, object]:
    return next(item for item in book.items if item["id"] == check_id)


class V8ValidatorContractTests(unittest.TestCase):
    def test_backrest_feature_uses_conserved_a06_item_not_hinge_name_union(self) -> None:
        parts = [
            PartRecord(
                name="A06_backrest_weather_shell",
                module="A06",
                states=frozenset({"ride"}),
                bounds=Bounds(134.0, 369.0, -303.0, 303.0, 407.0, 1003.0),
            ),
            PartRecord(
                name="A06_backrest_contact_panel",
                module="A06",
                states=frozenset({"ride"}),
                bounds=Bounds(140.0, 360.0, -258.0, 258.0, 430.0, 990.0),
            ),
            # These are real hinge/root parts but are not the physical backrest
            # envelope.  The legacy role-word union widened the item to 735 mm.
            PartRecord(
                name="A04_backrest_root_shoulder_left",
                module="A04",
                states=frozenset({"ride"}),
                bounds=Bounds(280.0, 360.0, -367.5, -305.0, 420.0, 520.0),
            ),
            PartRecord(
                name="A04_backrest_root_shoulder_right",
                module="A04",
                states=frozenset({"ride"}),
                bounds=Bounds(280.0, 360.0, 305.0, 367.5, 420.0, 520.0),
            ),
        ]
        checks = Checks()
        _validate_feature_geometry(parts, checks)
        result = _check(checks, "features.ride.backrest_physical_item")
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["part_count"], 2)
        self.assertAlmostEqual(result["combined_bounds"]["ylen"], 606.0)

    def test_stowed_a08_supports_are_conserved_not_deleted_from_bom(self) -> None:
        common = {
            "a08_motion_progress": 0.0,
            "same_physical_occurrence_all_states": True,
            "collision_allowlist_permitted": False,
        }
        parts = [
            PartRecord(
                name="A08_footrest_root_monocoque",
                module="A08",
                states=frozenset({"follow"}),
                bounds=Bounds(-528.0, -465.0, -263.0, 263.0, 58.0, 160.0),
                metadata={
                    **common,
                    "body_side_fixed": True,
                    "pose_invariant": True,
                },
            ),
            PartRecord(
                name="A08_footrest_support_monocoque_left",
                module="A08",
                states=frozenset({"follow"}),
                bounds=Bounds(-337.0, -179.0, -280.0, -268.0, 85.0, 135.0),
                metadata={**common, "body_side_fixed": False},
            ),
            PartRecord(
                name="A08_footrest_support_monocoque_right",
                module="A08",
                states=frozenset({"follow"}),
                bounds=Bounds(-337.0, -179.0, 268.0, 280.0, 85.0, 135.0),
                metadata={**common, "body_side_fixed": False},
            ),
            PartRecord(
                name="A08_manual_release_paddle_shell",
                module="A08",
                states=frozenset({"follow"}),
                bounds=Bounds(220.0, 250.0, -20.0, 20.0, 400.0, 420.0),
                metadata={
                    "physical_occurrence_id": "E6-A08-MANUAL-RELEASE-PADDLE-SHELL",
                    "body_side_fixed": True,
                    "pose_invariant": True,
                },
            ),
        ]
        checks = Checks()
        _validate_final_appearance_coverage(parts, checks)
        root = _check(
            checks,
            "coverage.follow.A08.fixed_root_occurrence_conserved",
        )
        supports = _check(
            checks,
            "coverage.follow.A08.moving_support_occurrences_conserved_at_endpoint",
        )
        self.assertTrue(root["pass"], root)
        self.assertTrue(supports["pass"], supports)
        self.assertEqual(supports["expected_progress"], 0.0)

    def test_emergency_stop_position_uses_dedicated_occurrence(self) -> None:
        openings = [
            OpeningRecord(
                name="A05_armrest_table_bay_shell_left",
                states=frozenset({"ride"}),
                bounds=Bounds(-100.0, -32.5, -360.0, -317.5, 520.0, 575.0),
                metadata={"note": "clear of emergency_stop service route"},
            ),
            OpeningRecord(
                name="A05_left_mechanical_emergency_stop",
                states=frozenset({"ride"}),
                bounds=Bounds(-309.0, -279.0, -306.0, -296.0, 575.0, 605.0),
                metadata={
                    "physical_occurrence_id": "WC-HMI-MECHANICAL-E-STOP-LEFT"
                },
            ),
        ]
        checks = Checks()
        _validate_openings(openings, checks)
        result = _check(checks, "openings.ride.emergency_stop_position")
        self.assertTrue(result["pass"], result)
        self.assertEqual(
            result["dedicated_occurrence"],
            "A05_left_mechanical_emergency_stop",
        )

    def test_release_box_ignores_presentation_triangulation_cache(self) -> None:
        shape = cq.Workplane("XY").circle(20.0).extrude(100.0).val()
        exact_before = _Box.from_shape(shape)

        # This is the same display-only tessellation path used by the GLB
        # renderer.  CadQuery's default box expands by the mesh deflection,
        # while release evidence must remain tied to analytic geometry.
        shape.tessellate(0.45, 0.08)
        cached_box = shape.BoundingBox()
        exact_after = _Box.from_shape(shape)

        exact_delta = max(
            abs(a - b)
            for a, b in zip(
                (
                    exact_before.xmin,
                    exact_before.xmax,
                    exact_before.ymin,
                    exact_before.ymax,
                    exact_before.zmin,
                    exact_before.zmax,
                ),
                (
                    exact_after.xmin,
                    exact_after.xmax,
                    exact_after.ymin,
                    exact_after.ymax,
                    exact_after.zmin,
                    exact_after.zmax,
                ),
            )
        )
        cached_delta = max(
            abs(cached_box.xmin - exact_before.xmin),
            abs(cached_box.xmax - exact_before.xmax),
            abs(cached_box.ymin - exact_before.ymin),
            abs(cached_box.ymax - exact_before.ymax),
            abs(cached_box.zmin - exact_before.zmin),
            abs(cached_box.zmax - exact_before.zmax),
        )
        self.assertLessEqual(exact_delta, 1.0e-9)
        self.assertGreater(cached_delta, 1.0e-3)

    def test_all_controlled_source_consumers_point_to_hash_bound_dfr5(self) -> None:
        self.assertEqual(CONTROLLED_SOURCE.name, "controlled_source_e6_dfr5")
        self.assertEqual(
            {state.configuration for state in BUILD_STATES},
            {"follow", "ride", "cafe", "focus"},
        )
        for state in ("follow", "ride", "cafe", "focus"):
            release_path = str(SOURCE_STEPS[state]["path"])
            validator_path = str(SOURCE_STEP_BASELINE[state]["path"])
            ledger_path = str(CONTROLLED_GLBS[state])
            with self.subTest(state=state):
                self.assertIn("controlled_source_e6_dfr5", release_path)
                self.assertIn(f"workcore_e6_dfr5_{state}.step", release_path)
                self.assertEqual(validator_path, release_path)
                self.assertIn("controlled_source_e6_dfr5", ledger_path)
                self.assertIn(f"workcore_e6_dfr5_{state}.glb", ledger_path)
                path = ROOT / release_path
                self.assertEqual(path.stat().st_size, SOURCE_STEPS[state]["bytes"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    SOURCE_STEPS[state]["sha256"],
                )

        manifest_path = ROOT / str(SOURCE_MANIFEST_BASELINE["path"])
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            EXPECTED_DFR5_MANIFEST_SHA256,
        )
        self.assertEqual(
            SOURCE_MANIFEST_BASELINE["sha256"],
            EXPECTED_DFR5_MANIFEST_SHA256,
        )

    def test_follow_two_sided_class_a_returns_fit_per_boundary_lock(self) -> None:
        parts = [
            PartRecord(
                name="A03_continuous_wheel_belt_shell_left",
                module="A03",
                states=frozenset({"follow"}),
                bounds=Bounds(-523.95, 323.95, -372.45, -250.0, 73.01, 300.0),
            ),
            PartRecord(
                name="A04_fixed_backrest_root_shoulder_left",
                module="A04",
                states=frozenset({"follow"}),
                bounds=Bounds(280.0, 352.0, -302.879, -111.256, 469.5, 511.0),
            ),
        ]
        checks = Checks()
        _validate_envelopes(ROOT, parts, checks, None)
        result = _check(checks, "envelope.follow.x_within_lock")
        self.assertTrue(result["pass"], result)
        self.assertAlmostEqual(float(result["actual_mm"]), 875.95, places=2)
        self.assertAlmostEqual(float(result["maximum_mm"]), 885.0, places=3)
        self.assertEqual(
            result["boundary_pass"],
            {"xmin": True, "xmax": True},
        )
        self.assertAlmostEqual(
            float(result["boundary_margin_mm"]["xmin"]),
            6.05,
            places=3,
        )
        self.assertAlmostEqual(
            float(result["boundary_margin_mm"]["xmax"]),
            3.0,
            places=3,
        )

    def test_release_envelope_rejects_one_sided_shift_even_below_total_cap(self) -> None:
        source = _Box(-505.0, 330.0, -361.0, 374.0, 0.0, 695.422781471)
        one_sided_shift = _Box(
            -531.0,
            330.0,
            -361.0,
            374.0,
            0.0,
            695.422781471,
        )
        evidence = _envelope_lock_evidence(
            "follow",
            source,
            one_sided_shift,
            (835.0, 735.0, 689.5),
        )
        self.assertLess(one_sided_shift.lengths[0], evidence["maximum_mm"]["length_x"])
        self.assertFalse(evidence["boundary_pass"]["xmin"])
        self.assertFalse(evidence["axis_pass"]["x"])
        self.assertFalse(evidence["pass"])

    def test_follow_soft_preload_allowlist_is_pair_and_state_specific(self) -> None:
        pair = (
            "A04_seat_cushion_contact_island",
            "A06_backrest_weather_shell",
        )
        self.assertEqual(set(RIGID_PAIR_COLLISION_ALLOWLIST), {"follow"})
        self.assertEqual(
            set(RIGID_PAIR_COLLISION_ALLOWLIST["follow"]),
            {pair},
        )
        shared_shape = cq.Workplane("XY").box(20.0, 20.0, 20.0).val()
        shifted_shape = shared_shape.translate((5.0, 0.0, 0.0))

        def records(state: str) -> list[dict[str, object]]:
            return [
                {"name": pair[0], "state": state, "shape": shared_shape},
                {"name": pair[1], "state": state, "shape": shifted_shape},
            ]

        follow = _rigid_collision_report(records("follow"), "follow")
        self.assertEqual(follow["status"], "PASS")
        self.assertEqual(follow["hard_collision_count"], 0)
        self.assertEqual(len(follow["unused_allowlist"]), 0)
        self.assertEqual(
            follow["pairs"][0]["classification"],
            "allowlisted_interference",
        )

        ride = _rigid_collision_report(records("ride"), "ride")
        self.assertEqual(ride["status"], "FAIL")
        self.assertEqual(ride["hard_collision_count"], 1)
        self.assertEqual(
            ride["hard_collisions"][0]["classification"],
            "hard_interference",
        )

    def test_a07_state_hardpoints_keep_low_beam_and_fixed_outer(self) -> None:
        state_bounds = {
            "follow": {
                "A07_mast_fixed_outer_sleeve": Bounds(-354.0, -44.0, -75.0, 75.0, 574.0, 682.0),
                "A07_mast_moving_inner_sleeve": Bounds(-353.0, 225.987, -63.0, 63.0, 584.0, 693.0),
                "A07_sensor_beam_shell": Bounds(-416.0, -348.0, -160.8, 208.1, 571.0, 653.0),
            },
            "ride": {
                "A07_mast_fixed_outer_sleeve": Bounds(275.0, 345.0, -68.0, 68.0, 708.0, 1008.0),
                "A07_mast_moving_inner_sleeve": Bounds(283.0, 337.0, -60.0, 60.0, 468.0, 1008.0),
                "A07_sensor_beam_shell": Bounds(256.7, 350.1, -160.8, 208.1, 1008.0, 1072.0),
            },
            "cafe": {
                "A07_mast_fixed_outer_sleeve": Bounds(275.0, 345.0, -68.0, 68.0, 708.0, 1008.0),
                "A07_mast_moving_inner_sleeve": Bounds(283.0, 337.0, -60.0, 60.0, 468.0, 1008.0),
                "A07_sensor_beam_shell": Bounds(256.7, 350.1, -160.8, 208.1, 1008.0, 1072.0),
            },
            "focus": {
                "A07_mast_fixed_outer_sleeve": Bounds(275.0, 345.0, -68.0, 68.0, 708.0, 1008.0),
                "A07_mast_moving_inner_sleeve": Bounds(283.0, 337.0, -60.0, 60.0, 888.0, 1428.0),
                "A07_sensor_beam_shell": Bounds(256.7, 350.1, -160.8, 208.1, 1428.0, 1492.0),
            },
        }
        parts = [
            PartRecord(
                name,
                "A07",
                frozenset({state}),
                bounds,
                metadata=(
                    {"controlled_axis_x_mm": 310.0}
                    if name == "A07_sensor_beam_shell"
                    else {}
                ),
            )
            for state, members in state_bounds.items()
            for name, bounds in members.items()
        ]
        checks = Checks()
        _validate_feature_geometry(parts, checks)
        for state in ("follow", "ride", "cafe", "focus"):
            with self.subTest(state=state):
                result = _check(checks, f"features.{state}.mast_state_position")
                self.assertTrue(result["pass"], result)
        self.assertTrue(
            _check(checks, "features.a07.ride_cafe_low_beam_same_pose_bounds")["pass"]
        )
        self.assertTrue(
            _check(checks, "features.a07.ride_cafe_focus_fixed_outer_same_pose_bounds")["pass"]
        )
        self.assertTrue(
            _check(checks, "features.a07.focus_moving_inner_and_beam_bounds_plus_420_only")["pass"]
        )

    def test_hidden_service_core_and_rebased_focus_are_rejected(self) -> None:
        hidden = Bounds(182.0, 292.0, -164.683, 164.683, 90.0, 427.0)
        rebased = Bounds(326.0, 406.0, -160.0, 160.0, 1428.0, 1492.0)
        parts = [
            PartRecord(
                name="A07_sensor_beam_shell",
                module="A07",
                states=frozenset({state}),
                bounds=rebased if state == "focus" else hidden,
            )
            for state in ("follow", "ride", "cafe", "focus")
        ]
        checks = Checks()
        _validate_feature_geometry(parts, checks)
        self.assertFalse(_check(checks, "features.follow.mast_state_position")["pass"])
        self.assertFalse(_check(checks, "features.ride.mast_state_position")["pass"])
        self.assertFalse(_check(checks, "features.cafe.mast_state_position")["pass"])
        self.assertFalse(_check(checks, "features.focus.mast_state_position")["pass"])

    def test_drive_controls_are_exterior_only_in_ride(self) -> None:
        bounds = Bounds(-305.0, -195.0, 307.0, 359.0, 681.0, 727.0)
        ride_controls = [
            PartRecord(
                name=name,
                module="A05",
                states=frozenset({"ride"}),
                bounds=bounds,
            )
            for name in (
                "A05_right_removable_drive_pod",
                "A05_right_joystick",
                "A05_right_authorisation_key",
            )
        ]
        checks = Checks()
        _validate_final_appearance_coverage(ride_controls, checks)
        ride = _check(checks, "coverage.ride.A05.right_drive_control")
        focus = _check(
            checks,
            "coverage.focus.A05.no_exposed_right_drive_control",
        )
        self.assertTrue(ride["pass"], ride)
        self.assertTrue(focus["pass"], focus)

    def test_focus_privacy_shutter_uses_controlled_source_pose(self) -> None:
        sensor_window = OpeningRecord(
            name="A07_sensor_beam_smoked_window",
            states=frozenset({"focus"}),
            bounds=Bounds(265.0, 270.0, -140.0, 140.0, 1440.0, 1480.0),
            metadata={"minimum_normal_clearance_to_physical_shutter_mm": 1.5},
        )
        shutter = OpeningRecord(
            name="A07_physical_privacy_shutter",
            states=frozenset({"focus"}),
            bounds=Bounds(262.5, 266.5, 65.0, 191.0, 1443.0, 1477.0),
            metadata={
                "physical_occurrence_id": "WC-MAST-PHYSICAL-PRIVACY-SHUTTER"
            },
        )
        checks = Checks()
        _validate_openings([sensor_window, shutter], checks)
        result = _check(checks, "openings.focus.privacy_shutter_on_sensor_beam")
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["actual_center_mm"], [264.5, 128.0, 1460.0])

    def test_a07_brep_contract_checks_real_transforms(self) -> None:
        def solid(size: tuple[float, float, float], center: tuple[float, float, float]) -> cq.Shape:
            return cq.Workplane("XY").box(*size).translate(center).val()

        def record(state: str, name: str, module: str, shape: cq.Shape) -> PartRecord:
            box = shape.BoundingBox()
            return PartRecord(
                name=name,
                module=module,
                states=frozenset({state}),
                bounds=Bounds(box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax),
                shape=shape,
                metadata=(
                    {"controlled_axis_x_mm": 310.0}
                    if name == "A07_sensor_beam_shell"
                    else {}
                ),
            )

        ride_shapes = {
            "A06_backrest_weather_shell": solid((40.0, 500.0, 400.0), (200.0, 0.0, 800.0)),
            "A07_mast_fixed_outer_sleeve": solid((70.0, 136.0, 300.0), (310.0, 0.0, 858.0)),
            "A07_mast_moving_inner_sleeve": solid((54.0, 120.0, 540.0), (310.0, 0.0, 738.0)),
            "A07_sensor_beam_shell": solid((94.0, 370.0, 64.0), (310.0, 0.0, 1040.0)),
        }
        hx, hy, hz = A06_A07_COMMON_FOLD_HINGE_MM
        parts: list[PartRecord] = []
        for state in ("ride", "cafe"):
            for name, shape in ride_shapes.items():
                parts.append(record(state, name, "A06" if name.startswith("A06_") else "A07", shape))
        for name, shape in ride_shapes.items():
            focus_shape = (
                shape
                if name in {"A06_backrest_weather_shell", "A07_mast_fixed_outer_sleeve"}
                else shape.translate((0.0, 0.0, 420.0))
            )
            parts.append(record("focus", name, "A06" if name.startswith("A06_") else "A07", focus_shape))
            follow_shape = shape.rotate(
                (hx, hy, hz),
                (hx, hy + 1.0, hz),
                A06_A07_FOLLOW_FOLD_DEG,
            )
            parts.append(record("follow", name, "A06" if name.startswith("A06_") else "A07", follow_shape))

        checks = Checks()
        _validate_a07_brep_contract(parts, checks, cq)
        for check_id in (
            "a07.brep.ride_cafe_complete_low_pose_identity",
            "a07.brep.focus_fixed_outer_pose_invariant",
            "a07.brep.focus_moving_members_plus_420_only",
            "a07.brep.follow_a06_a07_common_hinge_transform",
            "a07.brep.ride.low_beam_exterior_readable",
            "a07.brep.cafe.low_beam_exterior_readable",
        ):
            with self.subTest(check_id=check_id):
                self.assertTrue(_check(checks, check_id)["pass"], _check(checks, check_id))

        wrong_parts = []
        for part in parts:
            if "focus" not in part.states:
                wrong_parts.append(part)
                continue
            moved = part.shape.translate((56.0, 0.0, 0.0))
            wrong_parts.append(record("focus", part.name, part.module, moved))
        wrong_checks = Checks()
        _validate_a07_brep_contract(wrong_parts, wrong_checks, cq)
        self.assertFalse(
            _check(wrong_checks, "a07.brep.focus_fixed_outer_pose_invariant")["pass"]
        )
        self.assertFalse(
            _check(wrong_checks, "a07.brep.focus_moving_members_plus_420_only")["pass"]
        )

    def test_follow_uses_open_a06_u_channel_not_a_top_cap(self) -> None:
        def solid(
            size: tuple[float, float, float],
            center: tuple[float, float, float],
        ) -> cq.Shape:
            return cq.Workplane("XY").box(*size).translate(center).val()

        # One fused A06 solid surrounds the A07 package laterally on both sides
        # and longitudinally.  Its top is intentionally open for the same beam
        # and moving sleeve to travel +420 mm in Focus.
        rear = solid((12.0, 370.0, 553.0), (258.0, 0.0, 726.5))
        side_left = solid((110.0, 10.0, 553.0), (313.0, -175.0, 726.5))
        side_right = solid((110.0, 10.0, 553.0), (313.0, 175.0, 726.5))
        front = solid((12.0, 370.0, 553.0), (368.0, 0.0, 726.5))
        open_a06 = rear.fuse(side_left).fuse(side_right).fuse(front).clean()
        self.assertTrue(open_a06.isValid())
        self.assertEqual(len(open_a06.Solids()), 1)

        low_a07 = {
            "A07_mast_fixed_outer_sleeve": solid(
                (70.0, 136.0, 300.0), (310.0, 0.0, 858.0)
            ),
            "A07_mast_moving_inner_sleeve": solid(
                (54.0, 120.0, 540.0), (310.0, 0.0, 738.0)
            ),
            "A07_sensor_beam_shell": solid(
                (94.0, 370.0, 64.0), (310.0, 0.0, 1040.0)
            ),
        }
        hx, hy, hz = A06_A07_COMMON_FOLD_HINGE_MM

        def record(
            state: str,
            name: str,
            module: str,
            shape: cq.Shape,
        ) -> PartRecord:
            box = shape.BoundingBox()
            return PartRecord(
                name=name,
                module=module,
                states=frozenset({state}),
                bounds=Bounds(
                    box.xmin,
                    box.xmax,
                    box.ymin,
                    box.ymax,
                    box.zmin,
                    box.zmax,
                ),
                shape=shape,
                metadata=(
                    {"controlled_axis_x_mm": 310.0}
                    if name == "A07_sensor_beam_shell"
                    else {}
                ),
            )

        def state_parts(a06: cq.Shape) -> list[PartRecord]:
            low = {"A06_backrest_weather_shell": a06, **low_a07}
            result: list[PartRecord] = []
            for state in ("ride", "cafe"):
                for name, shape in low.items():
                    result.append(
                        record(
                            state,
                            name,
                            "A06" if name.startswith("A06_") else "A07",
                            shape,
                        )
                    )
            for name, shape in low.items():
                focus_shape = (
                    shape
                    if name
                    in {
                        "A06_backrest_weather_shell",
                        "A07_mast_fixed_outer_sleeve",
                    }
                    else shape.translate((0.0, 0.0, 420.0))
                )
                follow_shape = shape.rotate(
                    (hx, hy, hz),
                    (hx, hy + 1.0, hz),
                    A06_A07_FOLLOW_FOLD_DEG,
                )
                module = "A06" if name.startswith("A06_") else "A07"
                result.append(record("focus", name, module, focus_shape))
                result.append(record("follow", name, module, follow_shape))
            return result

        checks = Checks()
        _validate_a07_brep_contract(state_parts(open_a06), checks, cq)
        coverage = _check(
            checks,
            "a07.brep.follow_a06_only_weather_coverage_and_clearance",
        )
        self.assertTrue(coverage["pass"], coverage)
        self.assertTrue(coverage["lateral_u_channel_surround_pass"])
        self.assertTrue(coverage["focus_open_egress_sweep_pass"])

        def as_skin_states(
            records: list[PartRecord],
        ) -> dict[str, list[SkinPart]]:
            states: dict[str, list[SkinPart]] = {
                state: [] for state in ("follow", "ride", "cafe", "focus")
            }
            for part in records:
                state = next(iter(part.states))
                metadata = {}
                if part.name == "A06_backrest_weather_shell":
                    metadata = {
                        "physical_occurrence_id": "E6-A06-BACKREST-WEATHER-SHELL",
                        "physical_part_conserved": True,
                        "master_has_mast_cutout": True,
                        "same_backrest_not_extra_cover": True,
                    }
                elif part.name == "A07_sensor_beam_shell":
                    metadata = {"controlled_axis_x_mm": 310.0}
                states[state].append(
                    SkinPart(
                        name=part.name,
                        shape=part.shape,
                        color=(0.5, 0.5, 0.5, 1.0),
                        material="test",
                        module=part.module,
                        configuration=state,
                        metadata=metadata,
                    )
                )
            return states

        release_book = _GateBook()
        _gate_retract_then_fold(
            as_skin_states(state_parts(open_a06)),
            release_book,
        )
        release_by_id = {item["id"]: item for item in release_book.checks}
        release_coverage = release_by_id[
            "a06_a07.follow.same_trapezoid_is_only_weather_cover"
        ]
        self.assertTrue(release_coverage["pass"], release_coverage)
        self.assertTrue(release_coverage["lateral_u_channel_surround_pass"])
        self.assertTrue(release_coverage["focus_open_egress_sweep_pass"])

        # A Follow-only flat perimeter strip is still an additional weather
        # surface even when metadata calls it a seal.  Both independent gates
        # must reject the exact regression visible in the former render set.
        skirt_shape = solid((490.0, 600.0, 6.0), (-75.0, 0.0, 427.0))
        skirt_records = state_parts(open_a06)
        skirt_records.append(
            record(
                "follow",
                "A06_follow_weather_continuity_skirt",
                "A06",
                skirt_shape,
            )
        )
        skirt_checks = Checks()
        _validate_a07_brep_contract(skirt_records, skirt_checks, cq)
        skirt_coverage = _check(
            skirt_checks,
            "a07.brep.follow_a06_only_weather_coverage_and_clearance",
        )
        self.assertFalse(skirt_coverage["pass"], skirt_coverage)
        self.assertEqual(
            skirt_coverage["additional_follow_a06_surface_occurrences"],
            ["A06_follow_weather_continuity_skirt"],
        )

        skirt_states = as_skin_states(state_parts(open_a06))
        skirt_states["follow"].append(
            SkinPart(
                name="A06_follow_weather_continuity_skirt",
                shape=skirt_shape,
                color=(0.5, 0.5, 0.5, 1.0),
                material="test",
                module="A06",
                configuration="follow",
                metadata={"presentation_visibility": "hidden"},
            )
        )
        skirt_release_book = _GateBook()
        _gate_retract_then_fold(skirt_states, skirt_release_book)
        skirt_release = {
            item["id"]: item for item in skirt_release_book.checks
        }["a06_a07.follow.same_trapezoid_is_only_weather_cover"]
        self.assertFalse(skirt_release["pass"], skirt_release)
        self.assertEqual(
            skirt_release["additional_follow_a06_surface_occurrences"],
            ["A06_follow_weather_continuity_skirt"],
        )

        # A thin cap is not accepted merely because the low and Focus endpoint
        # poses themselves clear it: the nine-pose physical stroke must find it.
        cap = solid((122.0, 370.0, 8.0), (313.0, 0.0, 1084.0))
        capped_a06 = open_a06.fuse(cap).clean()
        capped_checks = Checks()
        _validate_a07_brep_contract(state_parts(capped_a06), capped_checks, cq)
        capped = _check(
            capped_checks,
            "a07.brep.follow_a06_only_weather_coverage_and_clearance",
        )
        self.assertFalse(capped["pass"], capped)
        self.assertFalse(capped["focus_open_egress_sweep_pass"])

        capped_release_book = _GateBook()
        _gate_retract_then_fold(
            as_skin_states(state_parts(capped_a06)),
            capped_release_book,
        )
        capped_release = {
            item["id"]: item for item in capped_release_book.checks
        }["a06_a07.follow.same_trapezoid_is_only_weather_cover"]
        self.assertFalse(capped_release["pass"], capped_release)
        self.assertFalse(capped_release["focus_open_egress_sweep_pass"])

    def test_release_gate_uses_world_brep_not_visibility_metadata(self) -> None:
        def solid(size: tuple[float, float, float], center: tuple[float, float, float]) -> cq.Shape:
            return cq.Workplane("XY").box(*size).translate(center).val()

        ride_shapes = {
            "A06_backrest_weather_shell": solid((40.0, 500.0, 400.0), (200.0, 0.0, 800.0)),
            "A07_mast_fixed_outer_sleeve": solid((70.0, 136.0, 300.0), (310.0, 0.0, 858.0)),
            "A07_mast_moving_inner_sleeve": solid((54.0, 120.0, 540.0), (310.0, 0.0, 738.0)),
            "A07_sensor_beam_shell": solid((94.0, 370.0, 64.0), (310.0, 0.0, 1040.0)),
        }
        hx, hy, hz = A06_A07_COMMON_FOLD_HINGE_MM

        def skin(state: str, name: str, shape: cq.Shape) -> SkinPart:
            metadata = {}
            if name == "A06_backrest_weather_shell":
                metadata = {
                    "physical_occurrence_id": "E6-A06-BACKREST-WEATHER-SHELL",
                    "physical_part_conserved": True,
                    "master_has_mast_cutout": True,
                    "same_backrest_not_extra_cover": True,
                }
            elif name in {
                "A07_mast_fixed_outer_sleeve",
                "A07_sensor_beam_shell",
            }:
                metadata = {"controlled_axis_x_mm": 310.0}
            return SkinPart(
                name=name,
                shape=shape,
                color=(0.5, 0.5, 0.5, 1.0),
                material="test",
                module="A06" if name.startswith("A06_") else "A07",
                configuration=state,
                metadata=metadata,
            )

        states: dict[str, list[SkinPart]] = {state: [] for state in ("follow", "ride", "cafe", "focus")}
        for state in ("ride", "cafe"):
            states[state] = [skin(state, name, shape) for name, shape in ride_shapes.items()]
        states["focus"] = [
            skin(
                "focus",
                name,
                shape
                if name in {"A06_backrest_weather_shell", "A07_mast_fixed_outer_sleeve"}
                else shape.translate((0.0, 0.0, 420.0)),
            )
            for name, shape in ride_shapes.items()
        ]
        states["follow"] = [
            skin(
                "follow",
                name,
                shape.rotate(
                    (hx, hy, hz),
                    (hx, hy + 1.0, hz),
                    A06_A07_FOLLOW_FOLD_DEG,
                ),
            )
            for name, shape in ride_shapes.items()
        ]
        book = _GateBook()
        _gate_retract_then_fold(states, book)
        by_id = {item["id"]: item for item in book.checks}
        for check_id in (
            "a07.ride_cafe.same_low_world_pose",
            "a07.follow.same_physical_inventory_as_low",
            "a07.ride.low_sensor_beam_exterior_readable",
            "a07.cafe.low_sensor_beam_exterior_readable",
            "a07.focus.fixed_outer_same_world_pose_as_low",
            "a07.focus.moving_inner_and_terminal_plus_420_only",
            "a06_a07.follow.same_common_hinge_transform",
        ):
            with self.subTest(check_id=check_id):
                self.assertTrue(by_id[check_id]["pass"], by_id[check_id])

        states["follow"].append(
            skin(
                "follow",
                "A07_follow_spine_cassette_cover",
                solid((40.0, 100.0, 4.0), (0.0, 0.0, 900.0)),
            )
        )
        cover_book = _GateBook()
        _gate_retract_then_fold(states, cover_book)
        cover_check = {
            item["id"]: item for item in cover_book.checks
        }["a07.follow.same_physical_inventory_as_low"]
        self.assertFalse(cover_check["pass"], cover_check)
        self.assertEqual(
            cover_check["forbidden_follow_covers"],
            ["A07_follow_spine_cassette_cover"],
        )
        states["follow"].pop()

        focus_fixed = next(
            part
            for part in states["focus"]
            if part.name == "A07_mast_fixed_outer_sleeve"
        )
        original_metadata = dict(focus_fixed.metadata)
        for label, bad_axis in (("missing", None), ("wrong", 309.0)):
            with self.subTest(fixed_outer_axis=label):
                if bad_axis is None:
                    focus_fixed.metadata.pop("controlled_axis_x_mm", None)
                else:
                    focus_fixed.metadata["controlled_axis_x_mm"] = bad_axis
                bad_book = _GateBook()
                _gate_retract_then_fold(states, bad_book)
                bad_check = {
                    item["id"]: item for item in bad_book.checks
                }["a07.focus.fixed_outer_same_world_pose_as_low"]
                self.assertFalse(bad_check["pass"], bad_check)
                focus_fixed.metadata.clear()
                focus_fixed.metadata.update(original_metadata)

    def test_release_gate_requires_one_a07_moving_spine_and_rejects_old_stages(
        self,
    ) -> None:
        production_masters = _production_a07_low_masters()
        low_shapes = {
            "A07_mast_fixed_outer_sleeve": production_masters["fixed"],
            "A07_mast_moving_inner_sleeve": production_masters["moving"],
            "A07_sensor_beam_shell": production_masters["beam"],
            "A07_microphone_acoustic_mesh": production_masters[
                "microphone_mesh"
            ],
        }
        a10_surround_fixture = (
            cq.Workplane("XY")
            .box(20.0, 20.0, 20.0)
            .translate((-1000.0, 0.0, 300.0))
            .val()
        )
        hx, hy, hz = A06_A07_COMMON_FOLD_HINGE_MM

        def skin(state: str, name: str, shape: cq.Shape) -> SkinPart:
            metadata: dict[str, object] = {
                "physical_occurrence_id": f"TEST-{name}",
                "same_brep_all_states": True,
            }
            if name == "A07_mast_moving_inner_sleeve":
                metadata.update(
                    {
                        "telescopic_stage_count": 1,
                        "one_piece_finished_observation_spine": True,
                        "three_stage_suitcase_handle_architecture_removed": True,
                        "minimum_extended_overlap_mm": 150.0,
                        "focus_translation_mm": 420.0 if state == "focus" else 0.0,
                        "cosmetic_spine_bounds_z_mm": (438.0, 1004.0),
                        "terminal_tenon_bounds_z_mm": (1000.0, 1024.0),
                        "terminal_tenon_plan_mm": (36.0, 80.0),
                        "terminal_tenon_engagement_mm": 16.0,
                        "terminal_joint_radial_assembly_gap_mm": (3.0, 3.0),
                        "terminal_joint_end_clearance_mm": 2.0,
                        "terminal_joint_dry_seam_mm": 4.0,
                    }
                )
            if name == "A07_sensor_beam_shell":
                metadata.update(
                    {
                        "controlled_axis_x_mm": 310.0,
                        "terminal_socket_plan_mm": (42.0, 86.0),
                        "terminal_socket_bounds_z_mm": (1000.0, 1026.0),
                        "terminal_socket_captures_moving_spine_tenon": True,
                    }
                )
            if name == "A07_microphone_acoustic_mesh":
                metadata.update(
                    {
                        "minimum_dry_clearance_to_terminal_tenon_mm": 1.5,
                        "terminal_tenon_acoustic_path_is_outboard": True,
                    }
                )
            if name == "A10_rear_service_surround":
                metadata.update(
                    {
                        "a07_low_spine_through_tunnel_mm": (
                            62.4,
                            128.4,
                            72.0,
                        ),
                        "a07_low_spine_tunnel_center_mm": (
                            310.0,
                            0.0,
                            465.0,
                        ),
                        "a07_low_spine_minimum_nominal_radial_clearance_mm": 3.5,
                        "a07_low_spine_tunnel_hidden_by_a06_channel": True,
                    }
                )
            return SkinPart(
                name=name,
                shape=shape,
                color=(0.5, 0.5, 0.5, 1.0),
                material="test",
                module=name.split("_", 1)[0],
                configuration=state,
                metadata=metadata,
            )

        states: dict[str, list[SkinPart]] = {
            state: [] for state in ("follow", "ride", "cafe", "focus")
        }
        for state in states:
            for name, low_shape in low_shapes.items():
                shape = low_shape
                if state == "focus" and name != "A07_mast_fixed_outer_sleeve":
                    shape = shape.translate((0.0, 0.0, 420.0))
                if state == "follow":
                    shape = shape.rotate(
                        (hx, hy, hz),
                        (hx, hy + 1.0, hz),
                        A06_A07_FOLLOW_FOLD_DEG,
                    )
                states[state].append(skin(state, name, shape))
            states[state].append(
                skin(
                    state,
                    "A10_rear_service_surround",
                    a10_surround_fixture,
                )
            )

        book = _GateBook()
        _gate_a07_single_moving_spine(states, book)
        by_id = {item["id"]: item for item in book.checks}
        for state in states:
            check_id = f"a07.{state}.single_one_piece_moving_spine"
            self.assertTrue(by_id[check_id]["pass"], by_id[check_id])
            tunnel_check_id = (
                f"a07_a10.{state}."
                "moving_spine_real_service_surround_tunnel"
            )
            self.assertTrue(
                by_id[tunnel_check_id]["pass"],
                by_id[tunnel_check_id],
            )

        validator_checks = Checks()
        _validate_a07_brep_contract(
            [
                _part_from_object(part)
                for state_parts in states.values()
                for part in state_parts
            ],
            validator_checks,
            cq,
        )
        validator_interface = _check(
            validator_checks,
            "a07.brep.single_spine_150mm_capture_and_hidden_terminal_socket",
        )
        self.assertTrue(validator_interface["pass"], validator_interface)

        legacy_states = {state: list(parts) for state, parts in states.items()}
        legacy_low = (
            cq.Workplane("XY")
            .box(30.0, 80.0, 120.0)
            .translate((310.0, 0.0, 800.0))
            .val()
        )
        for state in legacy_states:
            shape = legacy_low
            if state == "follow":
                shape = shape.rotate(
                    (hx, hy, hz),
                    (hx, hy + 1.0, hz),
                    A06_A07_FOLLOW_FOLD_DEG,
                )
            legacy_states[state].append(
                skin(
                    state,
                    "A07_mast_moving_inner_sleeve_stage_2",
                    shape,
                )
            )
        rejected = _GateBook()
        _gate_a07_single_moving_spine(legacy_states, rejected)
        rejected_by_id = {item["id"]: item for item in rejected.checks}
        for state in legacy_states:
            check_id = f"a07.{state}.single_one_piece_moving_spine"
            self.assertFalse(
                rejected_by_id[check_id]["pass"],
                rejected_by_id[check_id],
            )

    def test_source_disposition_never_invents_a04_a10_mast_stow(self) -> None:
        for state, expected in A07_MECHANISM_ENCLOSURES_BY_STATE.items():
            with self.subTest(state=state):
                decision = _internal_policy(state, f"mast_inner_{state}")
                self.assertIsNotNone(decision)
                assert decision is not None
                self.assertEqual(decision.enclosure_proxies, expected)
                self.assertFalse(
                    any(
                        proxy.startswith(("A04_", "A10_"))
                        for proxy in decision.enclosure_proxies
                    )
                )

    def test_table_root_visual_continuity_accepts_internal_roots_and_visible_necks(
        self,
    ) -> None:
        def record(
            state: str,
            name: str,
            metadata: dict[str, object],
            module: str = "A09",
        ) -> PartRecord:
            return PartRecord(
                name=name,
                module=module,
                states=frozenset({state}),
                bounds=Bounds(-480.0, -250.0, -360.0, 360.0, 480.0, 705.0),
                metadata=metadata,
            )

        cafe_root_names = (
            "A09_cafe_fixed_root_housing_right",
            "A09_cafe_fixed_yoke_bearing_carrier_right",
            "A09_cafe_rotary_hub_right",
            "A09_cafe_rotary_linear_rail_right",
            "A09_cafe_underleaf_motion_belly_right",
        )
        parts = [
            record(
                "cafe",
                "A05_table_root_structural_cassette_right",
                {
                    "primary_table_load_path": True,
                    "state_invariant_physical_occurrence": True,
                    "final_exterior_visible": False,
                },
                module="A05",
            )
        ]
        for name in cafe_root_names:
            metadata = {
                "layout_kinematic_envelope_only": True,
                "final_exterior_visible": False,
            }
            if name == "A09_cafe_underleaf_motion_belly_right":
                metadata.update(
                    {
                        "final_exterior_visible": True,
                        "root_neck_outside_armrest": True,
                        "hinge_bearing_and_lock_outside_armrest": False,
                        "internal_spreader_length_mm": 220.0,
                    }
                )
            parts.append(record("cafe", name, metadata))

        for side in ("left", "right"):
            parts.append(
                record(
                    "focus",
                    f"A05_table_root_structural_cassette_{side}",
                    {
                        "primary_table_load_path": True,
                        "state_invariant_physical_occurrence": True,
                        "final_exterior_visible": False,
                    },
                    module="A05",
                )
            )
            parts.append(
                record(
                    "focus",
                    f"A09_focus_internal_root_box_{side}",
                    {"final_exterior_visible": False},
                )
            )
            for stage_index in (1, 2, 3):
                parts.append(
                    record(
                        "focus",
                        (
                            "A09_focus_internal_nested_guide_stage_"
                            f"{stage_index}_{side}"
                        ),
                        {
                            "final_exterior_visible": False,
                            "mechanism_z_max_mm": (570.0, 632.0, 674.0)[
                                stage_index - 1
                            ],
                        },
                    )
                )
            parts.append(
                record(
                    "focus",
                    f"A09_focus_table_hidden_root_tongue_{side}",
                    {
                        "final_exterior_visible": True,
                        "root_neck_outside_armrest": True,
                        "hinge_bearing_and_lock_outside_armrest": False,
                        "internal_spreader_length_mm": 220.0,
                    },
                )
            )

        checks = Checks()
        _validate_feature_geometry(parts, checks)
        for state in ("cafe", "focus"):
            result = _check(
                checks,
                f"features.{state}.armrest_table_root_visual_continuity",
            )
            self.assertTrue(result["pass"], result)

        retired = record(
            "cafe",
            "A09_cafe_root_mechanism_fairing_right_service_segment_1",
            {},
        )
        rejected = Checks()
        _validate_feature_geometry([*parts, retired], rejected)
        result = _check(
            rejected,
            "features.cafe.armrest_table_root_visual_continuity",
        )
        self.assertFalse(result["pass"], result)

    def test_table_disposition_uses_current_roots_not_retired_fragments(
        self,
    ) -> None:
        retired_tokens = (
            "focus_armrest_to_table_root_bridge",
            "focus_root_fairing",
            "focus_underleaf_saddle",
            "focus_underleaf_motion_belly",
            "focus_table_root_crown",
            "focus_table_mount_shoe",
        )
        for side in ("left", "right"):
            expected_fold = {
                f"A09_table_underbelly_shell_{side}",
                f"A09_table_underbelly_shell_{side}_fold_half_inner",
            }
            fold = _internal_policy("focus", f"desk_leaf_fold_hinge_{side}")
            self.assertIsNotNone(fold)
            assert fold is not None
            self.assertEqual(set(fold.enclosure_proxies), expected_fold)

            expected_root = {
                f"A05_table_root_structural_cassette_{side}",
                f"A09_focus_internal_root_box_{side}",
                *(f"A09_focus_internal_nested_guide_stage_{index}_{side}" for index in (1, 2, 3)),
                f"A09_focus_table_hidden_root_tongue_{side}",
            }
            for occurrence in (f"desk_forward_carriage_{side}", f"desk_yoke_{side}"):
                with self.subTest(occurrence=occurrence):
                    decision = _internal_policy("focus", occurrence)
                    self.assertIsNotNone(decision)
                    assert decision is not None
                    self.assertEqual(set(decision.enclosure_proxies), expected_root)
                    self.assertFalse(
                        any(
                            token in proxy
                            for proxy in decision.enclosure_proxies
                            for token in retired_tokens
                        ),
                        decision.enclosure_proxies,
                    )

        cafe_expected = {
            "desk_leaf_fold_hinge_right": {
                "A09_table_underbelly_shell_right",
                "A09_table_underbelly_shell_right_fold_half_inner",
                "A09_cafe_underleaf_motion_belly_right",
            },
            "desk_forward_carriage_right": {
                "A05_table_root_structural_cassette_right",
                "A09_cafe_internal_lift_packaging_envelope_right",
                "A09_cafe_fixed_root_housing_right",
                "A09_cafe_fixed_yoke_bearing_carrier_right",
                "A09_cafe_rotary_hub_right",
                "A09_cafe_rotary_linear_rail_right",
                "A09_cafe_underleaf_motion_belly_right",
            },
            "desk_yoke_right": {
                "A05_table_root_structural_cassette_right",
                "A09_cafe_internal_lift_packaging_envelope_right",
                "A09_cafe_fixed_root_housing_right",
                "A09_cafe_fixed_yoke_bearing_carrier_right",
                "A09_cafe_rotary_hub_right",
                "A09_cafe_rotary_linear_rail_right",
                "A09_cafe_underleaf_motion_belly_right",
            },
            "desk_cafe_rotation_bearing_right": {
                "A09_cafe_fixed_yoke_bearing_carrier_right",
                "A09_cafe_rotary_hub_right",
            },
        }
        for occurrence, expected in cafe_expected.items():
            with self.subTest(occurrence=occurrence):
                decision = _internal_policy("cafe", occurrence)
                self.assertIsNotNone(decision)
                assert decision is not None
                self.assertEqual(set(decision.enclosure_proxies), expected)
                self.assertFalse(
                    any(
                        token in proxy
                        for proxy in decision.enclosure_proxies
                        for token in (
                            "cafe_armrest_to_table_root_bridge",
                            "cafe_root_mechanism_fairing",
                            "cafe_underleaf_saddle",
                            "motion_belly_service",
                            "telescopic_rail_cover",
                            "linear_guide_shoe",
                            "table_mount_shoe",
                        )
                    ),
                    decision.enclosure_proxies,
                )


if __name__ == "__main__":
    unittest.main()
