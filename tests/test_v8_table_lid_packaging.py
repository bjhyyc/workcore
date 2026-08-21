from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cadquery as cq
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
from cad.build import human_envelope_parts  # noqa: E402
from cad.parameters import P  # noqa: E402
from skin_upper import build_upper_skin  # noqa: E402
from v8_table_lid_packaging import (  # noqa: E402
    CAFE_CLEARANCE_AXIS_X_MM,
    CAFE_FINAL_AXIS_X_MM,
    CAFE_FINAL_AXIS_Y_MM,
    FOCUS_AXIS_ABS_Y_MM,
    LID_FLEX_MINIMUM_INSIDE_RADIUS_MM,
    LID_FLEX_THICKNESS_MM,
    LID_FLEX_WIDTH_MM,
    LID_OPEN_ANGLE_DEG,
    MAXIMUM_FOLDED_MATERIAL_ENVELOPE_MM,
    NOMINAL_FOLDED_ENVELOPE_MM,
    STOW_AXIS_ABS_Y_MM,
    STOW_AXIS_X_MM,
    STOW_AXIS_Z_MM,
    SequenceContext,
    TABLE_ACCESS_SEQUENCE,
    cafe_half_leaf_pair,
    canonical_half_leaf,
    combined_bounds,
    extraction_axis_samples,
    extraction_motion_occurrences,
    folded_half_leaf_pair,
    folded_pack_occurrences,
    folded_pack_size,
    harness_service_loop,
    lid_harness_occurrences,
    lid_harness_pose,
    pose_lid_shape,
    unfold_motion_pose,
    unfolded_half_leaf,
    validate_use_sequence,
)


COMMON_VOLUME_TOLERANCE_MM3 = 1.0e-5
HARD_PART_MINIMUM_CLEARANCE_MM = 3.0
LEAF_TO_LEAF_MINIMUM_MOTION_GAP_MM = 1.0


def _aabb_clearance_lower_bound(first, second) -> float:
    first_box = first.BoundingBox()
    second_box = second.BoundingBox()
    separations = (
        max(
            first_box.xmin - second_box.xmax,
            second_box.xmin - first_box.xmax,
            0.0,
        ),
        max(
            first_box.ymin - second_box.ymax,
            second_box.ymin - first_box.ymax,
            0.0,
        ),
        max(
            first_box.zmin - second_box.zmax,
            second_box.zmin - first_box.zmax,
            0.0,
        ),
    )
    return sum(value * value for value in separations) ** 0.5


def _topology_signature(shape) -> tuple[int, int, int, int]:
    return (
        len(shape.Solids()),
        len(shape.Faces()),
        len(shape.Edges()),
        len(shape.Vertices()),
    )


def _assert_no_common_volume(
    case: unittest.TestCase,
    first,
    second,
    *,
    label: str,
) -> None:
    if _aabb_clearance_lower_bound(first, second) > 1.0e-7:
        return
    # A positive OCCT distance is already a proof of disjoint hard solids.
    # Only pay for the much more expensive Boolean common when the distance
    # collapses to kernel tolerance; this keeps the 61-pose audit executable
    # without weakening its fail-closed result.
    if float(first.distance(second)) > 1.0e-7:
        return
    common = float(first.intersect(second).Volume())
    case.assertLessEqual(
        common,
        COMMON_VOLUME_TOLERANCE_MM3,
        f"{label}: hard parts overlap by {common:.9f} mm^3",
    )


def _assert_minimum_clearance(
    case: unittest.TestCase,
    first,
    second,
    minimum_mm: float,
    *,
    label: str,
) -> float:
    # OCCT's exact distance has a repeatable false zero for one disjoint
    # lid-phone-stop/cam-pin pair at exactly 100 degrees.  A positive AABB
    # lower bound is already a rigorous separation proof, so use it before
    # invoking the exact solver and reserve the latter for overlapping boxes.
    lower_bound = _aabb_clearance_lower_bound(first, second)
    distance = (
        lower_bound
        if lower_bound >= minimum_mm
        else float(first.distance(second))
    )
    if distance <= 1.0e-7:
        _assert_no_common_volume(case, first, second, label=label)
    case.assertGreaterEqual(
        distance,
        minimum_mm - 1.0e-6,
        f"{label}: clearance={distance:.6f} mm",
    )
    return distance


class V8TableLidPackagingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # This is the direct Class-A Follow skin, not the much heavier complete
        # V8 state build.  It is the real fixed armrest shell/lid geometry the
        # folded table has to clear.
        parts = build_upper_skin("follow")
        cls.parts_by_name = {part.name: part for part in parts}
        cls.armrest = {}
        for side, side_name in ((-1, "left"), (1, "right")):
            shell = cls.parts_by_name[
                f"A05_armrest_table_bay_shell_{side_name}"
            ].shape
            lid_parts = [
                part
                for part in parts
                if part.name == f"A05_armrest_touch_lid_{side_name}"
                or (
                    side < 0
                    and (
                        bool(part.metadata.get("moves_with_top_lid"))
                        or part.name == "A05_left_hmi_precision_bezel"
                    )
                )
            ]
            cls.armrest[side] = {
                "shell": shell,
                "closed_lid_parts": tuple(
                    (part.name, part.shape) for part in lid_parts
                ),
                "open_lid_parts": tuple(
                    (
                        part.name,
                        pose_lid_shape(
                            part.shape,
                            side,
                            LID_OPEN_ANGLE_DEG,
                        ),
                    )
                    for part in lid_parts
                ),
            }

    def test_same_half_leaf_identity_volume_and_topology_in_every_pose(
        self,
    ) -> None:
        reference_shape = canonical_half_leaf()
        reference_volume = float(reference_shape.Volume())
        reference_topology = _topology_signature(reference_shape)
        self.assertTrue(reference_shape.isValid())
        self.assertEqual(reference_topology[0], 1)

        for side in (-1, 1):
            reference_by_id = {
                occurrence.physical_occurrence_id: occurrence
                for occurrence in (
                    unfolded_half_leaf(side, "inner"),
                    unfolded_half_leaf(side, "outer"),
                )
            }
            pose_sets = [folded_half_leaf_pair(side)]
            pose_sets.extend(
                unfold_motion_pose(side, frame / 20.0)
                for frame in range(21)
            )
            pose_sets.extend(
                tuple(
                    occurrence
                    for occurrence in pose
                    if occurrence.role == "rigid_half_leaf"
                )
                for pose in extraction_motion_occurrences(side)
            )
            if side > 0:
                pose_sets.extend(
                    cafe_half_leaf_pair(frame / 20.0, 0.0)
                    for frame in range(21)
                )
                pose_sets.extend(
                    cafe_half_leaf_pair(1.0, frame / 20.0)
                    for frame in range(21)
                )

            for pose_index, occurrences in enumerate(pose_sets):
                self.assertEqual(len(occurrences), 2)
                self.assertEqual(
                    {item.physical_occurrence_id for item in occurrences},
                    set(reference_by_id),
                )
                for occurrence in occurrences:
                    with self.subTest(
                        side=side,
                        pose=pose_index,
                        occurrence=occurrence.physical_occurrence_id,
                    ):
                        self.assertIsNot(
                            occurrence.shape,
                            reference_shape,
                            "A pose must be a transformed occurrence, not a "
                            "replacement proxy object",
                        )
                        self.assertTrue(occurrence.shape.isValid())
                        self.assertEqual(
                            _topology_signature(occurrence.shape),
                            reference_topology,
                        )
                        self.assertAlmostEqual(
                            float(occurrence.shape.Volume()),
                            reference_volume,
                            places=5,
                        )

    def test_folded_pack_is_nominal_size_and_contains_no_interpenetration(
        self,
    ) -> None:
        self.assertEqual(NOMINAL_FOLDED_ENVELOPE_MM, (430.0, 30.0, 139.0))
        self.assertEqual(
            MAXIMUM_FOLDED_MATERIAL_ENVELOPE_MM,
            (432.0, 32.0, 141.0),
        )
        for side in (-1, 1):
            occurrences = folded_pack_occurrences(side)
            measured = folded_pack_size(side)
            for axis, (actual, nominal, maximum) in enumerate(
                zip(
                    measured,
                    NOMINAL_FOLDED_ENVELOPE_MM,
                    MAXIMUM_FOLDED_MATERIAL_ENVELOPE_MM,
                )
            ):
                with self.subTest(side=side, axis=axis):
                    self.assertAlmostEqual(actual, nominal, places=6)
                    self.assertLessEqual(actual, maximum + 1.0e-6)

            for occurrence in occurrences:
                self.assertTrue(occurrence.shape.isValid(), occurrence.name)
                self.assertEqual(len(occurrence.shape.Solids()), 1)
            for first_index, first in enumerate(occurrences):
                for second in occurrences[first_index + 1 :]:
                    _assert_no_common_volume(
                        self,
                        first.shape,
                        second.shape,
                        label=(
                            f"side={side} folded pack "
                            f"{first.name} vs {second.name}"
                        ),
                    )

            bounds = combined_bounds(occurrences)
            self.assertAlmostEqual(bounds[5], 660.5, places=6)

    def test_twenty_one_unfold_frames_have_real_leaf_gap(self) -> None:
        for side in (-1, 1):
            for frame in range(21):
                first, second = unfold_motion_pose(side, frame / 20.0)
                with self.subTest(side=side, frame=frame):
                    _assert_minimum_clearance(
                        self,
                        first.shape,
                        second.shape,
                        LEAF_TO_LEAF_MINIMUM_MOTION_GAP_MM,
                        label=f"side={side} unfold frame={frame}",
                    )

    def test_stowed_complete_pack_clears_real_closed_lid_hmi_and_shell(
        self,
    ) -> None:
        for side in (-1, 1):
            obstacles = (
                ("fixed_shell", self.armrest[side]["shell"]),
                *self.armrest[side]["closed_lid_parts"],
            )
            for occurrence in folded_pack_occurrences(side):
                for obstacle_name, obstacle in obstacles:
                    label = (
                        f"side={side} stowed {occurrence.name} "
                        f"vs {obstacle_name}"
                    )
                    with self.subTest(label=label):
                        _assert_minimum_clearance(
                            self,
                            occurrence.shape,
                            obstacle,
                            HARD_PART_MINIMUM_CLEARANCE_MM,
                            label=label,
                        )

    def test_all_61_extraction_frames_clear_open_lid_hmi_and_shell(
        self,
    ) -> None:
        for side in (-1, 1):
            axes = extraction_axis_samples(side)
            poses = extraction_motion_occurrences(side)
            self.assertEqual(len(axes), 61)
            self.assertEqual(len(poses), 61)
            expected_start = (
                STOW_AXIS_X_MM,
                side * STOW_AXIS_ABS_Y_MM,
                STOW_AXIS_Z_MM,
            )
            self.assertEqual(axes[0], expected_start)
            self.assertEqual(
                axes[20],
                (
                    STOW_AXIS_X_MM,
                    side * STOW_AXIS_ABS_Y_MM,
                    699.0,
                ),
            )
            self.assertEqual(
                axes[40],
                (
                    -405.0,
                    side * STOW_AXIS_ABS_Y_MM,
                    699.0,
                ),
            )
            self.assertEqual(
                axes[-1],
                (-405.0, side * FOCUS_AXIS_ABS_Y_MM, 699.0),
            )
            obstacles = (
                ("fixed_shell", self.armrest[side]["shell"]),
                *self.armrest[side]["open_lid_parts"],
            )
            for frame, pose in enumerate(poses):
                for occurrence in pose:
                    for obstacle_name, obstacle in obstacles:
                        label = (
                            f"side={side} extraction frame={frame} "
                            f"{occurrence.name} vs {obstacle_name}"
                        )
                        with self.subTest(label=label):
                            _assert_minimum_clearance(
                                self,
                                occurrence.shape,
                                obstacle,
                                HARD_PART_MINIMUM_CLEARANCE_MM,
                                label=label,
                            )

    def test_three_leg_extraction_never_crosses_occupied_core(self) -> None:
        human = {
            part.name: part.solid for part in human_envelope_parts("focus")
        }
        core_names = tuple(
            name
            for name in human
            if any(token in name for token in ("torso", "pelvis", "thigh"))
        )
        self.assertTrue(core_names)
        for side in (-1, 1):
            minimum_distance = float("inf")
            for frame, pose in enumerate(extraction_motion_occurrences(side)):
                for occurrence in pose:
                    for human_name in core_names:
                        label = (
                            f"side={side} extraction frame={frame} "
                            f"{occurrence.name} vs {human_name}"
                        )
                        distance = _assert_minimum_clearance(
                            self,
                            occurrence.shape,
                            human[human_name],
                            P.occupant_armrest_side_clearance,
                            label=label,
                        )
                        minimum_distance = min(
                            minimum_distance,
                            distance,
                        )
            self.assertGreaterEqual(
                minimum_distance,
                P.occupant_armrest_side_clearance - 1.0e-6,
            )

    def test_cafe_rotates_at_clearance_axis_before_80_mm_return(self) -> None:
        initial = cafe_half_leaf_pair(0.0, 0.0)
        rotated = cafe_half_leaf_pair(1.0, 0.0)
        final = cafe_half_leaf_pair(1.0, 1.0)
        for frame in range(21):
            for phase, occurrences in (
                ("rotate", cafe_half_leaf_pair(frame / 20.0, 0.0)),
                ("return", cafe_half_leaf_pair(1.0, frame / 20.0)),
            ):
                first, second = occurrences
                with self.subTest(phase=phase, frame=frame):
                    _assert_minimum_clearance(
                        self,
                        first.shape,
                        second.shape,
                        LEAF_TO_LEAF_MINIMUM_MOTION_GAP_MM,
                        label=f"Cafe {phase} frame={frame}",
                    )

        initial_bounds = combined_bounds(initial)
        rotated_bounds = combined_bounds(rotated)
        final_bounds = combined_bounds(final)
        self.assertAlmostEqual(
            (initial_bounds[0] + initial_bounds[1]) / 2.0,
            CAFE_CLEARANCE_AXIS_X_MM,
            places=6,
        )
        self.assertAlmostEqual(
            (rotated_bounds[0] + rotated_bounds[1]) / 2.0,
            CAFE_CLEARANCE_AXIS_X_MM,
            places=6,
        )
        self.assertAlmostEqual(
            (final_bounds[0] + final_bounds[1]) / 2.0,
            CAFE_FINAL_AXIS_X_MM,
            places=6,
        )
        self.assertAlmostEqual(
            final_bounds[0] - rotated_bounds[0],
            CAFE_FINAL_AXIS_X_MM - CAFE_CLEARANCE_AXIS_X_MM,
            places=6,
        )
        self.assertAlmostEqual(
            final_bounds[1] - rotated_bounds[1],
            CAFE_FINAL_AXIS_X_MM - CAFE_CLEARANCE_AXIS_X_MM,
            places=6,
        )
        self.assertAlmostEqual(
            (final_bounds[2] + final_bounds[3]) / 2.0,
            CAFE_FINAL_AXIS_Y_MM,
            places=6,
        )
        self.assertEqual(initial_bounds[4:], rotated_bounds[4:])
        self.assertEqual(rotated_bounds[4:], final_bounds[4:])

    def test_exact_use_order_passes_and_every_interlock_fails_closed(
        self,
    ) -> None:
        valid_context = SequenceContext(
            parked=True,
            traction_disabled=True,
            phone_present=False,
            qi_energised=False,
            drive_pod_present=True,
            sweep_zone_clear=True,
            lid_double_latch_confirmed=True,
        )
        valid, failures = validate_use_sequence(
            TABLE_ACCESS_SEQUENCE,
            valid_context,
        )
        self.assertTrue(valid)
        self.assertEqual(failures, ())

        for index in range(len(TABLE_ACCESS_SEQUENCE)):
            missing = (
                TABLE_ACCESS_SEQUENCE[:index]
                + TABLE_ACCESS_SEQUENCE[index + 1 :]
            )
            valid, failures = validate_use_sequence(missing, valid_context)
            with self.subTest(event_missing=index):
                self.assertFalse(valid)
                self.assertIn("ordered_event_sequence_mismatch", failures)

        for index in range(len(TABLE_ACCESS_SEQUENCE) - 1):
            swapped = list(TABLE_ACCESS_SEQUENCE)
            swapped[index], swapped[index + 1] = (
                swapped[index + 1],
                swapped[index],
            )
            valid, failures = validate_use_sequence(swapped, valid_context)
            with self.subTest(adjacent_events_swapped=index):
                self.assertFalse(valid)
                self.assertIn("ordered_event_sequence_mismatch", failures)

        invalid_contexts = (
            ("parked", False, "park_or_traction_interlock_missing"),
            (
                "traction_disabled",
                False,
                "park_or_traction_interlock_missing",
            ),
            ("phone_present", True, "left_lid_phone_or_qi_interlock_open"),
            ("qi_energised", True, "left_lid_phone_or_qi_interlock_open"),
            (
                "drive_pod_present",
                False,
                "right_fixed_drive_pod_missing",
            ),
            ("sweep_zone_clear", False, "table_sweep_zone_not_clear"),
            (
                "lid_double_latch_confirmed",
                False,
                "lid_not_double_latched_before_unfold",
            ),
        )
        for field, value, expected_failure in invalid_contexts:
            context = replace(valid_context, **{field: value})
            valid, failures = validate_use_sequence(
                TABLE_ACCESS_SEQUENCE,
                context,
            )
            with self.subTest(interlock=field):
                self.assertFalse(valid)
                self.assertEqual(failures, (expected_failure,))

    def test_dynamic_lid_flex_has_two_real_ends_constant_length_and_bend_radius(
        self,
    ) -> None:
        self.assertEqual(LID_FLEX_WIDTH_MM, 6.0)
        self.assertEqual(LID_FLEX_THICKNESS_MM, 0.6)
        for side in (-1, 1):
            lengths = []
            volumes = []
            loop_axes = []
            minimum_inside_radius = float("inf")
            reference_fixed_endpoint = lid_harness_pose(
                side,
                0.0,
            ).fixed_endpoint_mm
            for angle in range(106):
                harness = lid_harness_pose(side, float(angle))
                with self.subTest(side=side, angle=angle):
                    self.assertTrue(harness.flex_circuit.isValid())
                    self.assertEqual(len(harness.flex_circuit.Solids()), 1)
                    self.assertTrue(harness.fixed_connector.isValid())
                    self.assertTrue(harness.moving_connector.isValid())
                    self.assertEqual(
                        harness.fixed_endpoint_mm,
                        reference_fixed_endpoint,
                    )
                    self.assertGreaterEqual(
                        harness.minimum_inside_bend_radius_mm,
                        LID_FLEX_MINIMUM_INSIDE_RADIUS_MM - 1.0e-6,
                    )
                lengths.append(harness.centerline_length_mm)
                volumes.append(float(harness.flex_circuit.Volume()))
                loop_axes.append(harness.rolling_loop_axis_z_mm)
                minimum_inside_radius = min(
                    minimum_inside_radius,
                    harness.minimum_inside_bend_radius_mm,
                )

            # The same copper is re-posed; neither its route length nor its
            # constant 6 x 0.6 mm section may be replaced by a new proxy.
            self.assertLessEqual(max(lengths) - min(lengths), 0.005)
            self.assertLessEqual(max(volumes) - min(volumes), 0.02)
            self.assertAlmostEqual(loop_axes[0], 510.0, places=6)
            self.assertAlmostEqual(loop_axes[-1], 524.7259545, places=5)
            self.assertGreaterEqual(minimum_inside_radius, 8.539 - 1.0e-3)

            closed = lid_harness_pose(side, 0.0)
            opened = lid_harness_pose(side, LID_OPEN_ANGLE_DEG)
            self.assertEqual(closed.fixed_endpoint_mm, opened.fixed_endpoint_mm)
            self.assertNotEqual(closed.moving_endpoint_mm, opened.moving_endpoint_mm)
            self.assertAlmostEqual(
                abs(opened.moving_endpoint_mm[1]),
                364.0431076,
                places=5,
            )
            self.assertAlmostEqual(opened.moving_endpoint_mm[2], 694.0083285, places=5)

            # These are actual terminating solids.  Positive common volumes
            # prove that the open-ended ribbon enters both connector bodies.
            for angle in range(0, 106, 5):
                harness = lid_harness_pose(side, float(angle))
                self.assertGreater(
                    float(
                        harness.flex_circuit.intersect(
                            harness.fixed_connector
                        ).Volume()
                    ),
                    1.0,
                )
                self.assertGreater(
                    float(
                        harness.flex_circuit.intersect(
                            harness.moving_connector
                        ).Volume()
                    ),
                    1.0,
                )

            occurrence_ids = {
                item.physical_occurrence_id
                for item in lid_harness_occurrences(side, 0.0)
            }
            self.assertEqual(len(occurrence_ids), 3)
            self.assertEqual(harness_service_loop(side).ShapeType(), "Solid")

    def test_full_0_to_105_degree_lid_hmi_and_dynamic_flex_sweep_is_clear(
        self,
    ) -> None:
        for side in (-1, 1):
            shell = self.armrest[side]["shell"]
            stowed_pack = folded_pack_occurrences(side)
            pack_compound = cq.Compound.makeCompound(
                [item.shape for item in stowed_pack]
            )
            angles = tuple(float(value) for value in range(106))
            harness_poses = tuple(
                lid_harness_pose(side, angle) for angle in angles
            )
            fixed_connector = harness_poses[0].fixed_connector
            self.assertGreaterEqual(
                float(fixed_connector.distance(shell)),
                0.20,
            )
            _assert_minimum_clearance(
                self,
                fixed_connector,
                pack_compound,
                HARD_PART_MINIMUM_CLEARANCE_MM,
                label=f"side={side} fixed flex connector vs stowed pack",
            )

            # One-degree compounds preserve every evaluated BRep while
            # reducing the fixed-obstacle audit to one exact distance query.
            # Unlike a convex hull, they do not fill empty space between poses.
            flex_sweep = cq.Compound.makeCompound(
                [pose.flex_circuit for pose in harness_poses]
            )
            connector_sweep = cq.Compound.makeCompound(
                [pose.moving_connector for pose in harness_poses]
            )
            _assert_minimum_clearance(
                self,
                flex_sweep,
                shell,
                HARD_PART_MINIMUM_CLEARANCE_MM,
                label=f"side={side} 0..105 dynamic flex vs fixed shell",
            )
            _assert_minimum_clearance(
                self,
                flex_sweep,
                pack_compound,
                HARD_PART_MINIMUM_CLEARANCE_MM,
                label=f"side={side} 0..105 dynamic flex vs stowed pack",
            )
            _assert_minimum_clearance(
                self,
                connector_sweep,
                shell,
                HARD_PART_MINIMUM_CLEARANCE_MM,
                label=f"side={side} 0..105 moving connector vs fixed shell",
            )
            _assert_minimum_clearance(
                self,
                connector_sweep,
                pack_compound,
                HARD_PART_MINIMUM_CLEARANCE_MM,
                label=f"side={side} 0..105 moving connector vs stowed pack",
            )

            lid_sweep_by_name = {
                name: []
                for name, _ in self.armrest[side]["closed_lid_parts"]
            }
            for angle, harness in zip(angles, harness_poses):
                moving_lid_parts = tuple(
                    (
                        name,
                        pose_lid_shape(shape, side, angle),
                    )
                    for name, shape in self.armrest[side]["closed_lid_parts"]
                )
                for name, moving_shape in moving_lid_parts:
                    lid_sweep_by_name[name].append(moving_shape)

                # The connector-captive tail is not a free-span clearance
                # surface.  Prove the physically trimmed free ribbon keeps
                # the hard-part margin, then separately prove that the
                # complete FPC has zero common volume with every lid/HMI part.
                # Pose-matched checks avoid the false cross-angle comparisons
                # introduced by a compound-vs-compound query.
                for name, moving_shape in moving_lid_parts:
                    _assert_minimum_clearance(
                        self,
                        harness.free_flex_span,
                        moving_shape,
                        HARD_PART_MINIMUM_CLEARANCE_MM,
                        label=(
                            f"side={side} angle={angle} free dynamic flex vs {name}"
                        ),
                    )
                    _assert_no_common_volume(
                        self,
                        harness.flex_circuit,
                        moving_shape,
                        label=(
                            f"side={side} angle={angle} complete dynamic flex "
                            f"vs {name}"
                        ),
                    )

            cap_name = (
                "A05_armrest_touch_lid_right"
                if side > 0
                else "A05_armrest_touch_lid_left"
            )
            cap_shapes = lid_sweep_by_name[cap_name]
            _assert_no_common_volume(
                self,
                cap_shapes[0],
                shell,
                label=f"side={side} closed cap/seal interface",
            )
            # At one degree the cap has already separated from the shell and
            # the remaining 104 integer-degree BReps are included in the same
            # non-filling compound.  Other HMI islands are clear over all 106
            # evaluated poses with the same exact compound-distance proof.
            self.assertGreater(
                float(
                    cq.Compound.makeCompound(cap_shapes[1:]).distance(shell)
                ),
                0.0,
            )
            for name, shapes in lid_sweep_by_name.items():
                if name == cap_name:
                    continue
                self.assertGreater(
                    float(cq.Compound.makeCompound(shapes).distance(shell)),
                    0.0,
                    f"side={side} 0..105 {name} touches fixed shell",
                )

            all_lid_sweep_shapes = [
                shape
                for shapes in lid_sweep_by_name.values()
                for shape in shapes
            ]
            lid_sweep_compound = cq.Compound.makeCompound(
                all_lid_sweep_shapes
            )
            _assert_minimum_clearance(
                self,
                lid_sweep_compound,
                pack_compound,
                HARD_PART_MINIMUM_CLEARANCE_MM,
                label=f"side={side} 0..105 lid/HMI sweep vs stowed pack",
            )

            # The connector/lid interface is a rigid pair, so checking the
            # closed occurrence proves every transformed occurrence exactly.
            closed_lid = next(
                shape
                for name, shape in self.armrest[side]["closed_lid_parts"]
                if name == cap_name
            )
            _assert_no_common_volume(
                self,
                harness_poses[0].moving_connector,
                closed_lid,
                label=f"side={side} moving connector/lid flush mate",
            )
            self.assertLessEqual(
                float(
                    harness_poses[0].moving_connector.distance(closed_lid)
                ),
                1.0e-5,
            )

            # With the lid fully open, every one of the 61 real extraction
            # frames stays forward of the rear flex cassette.  The positive
            # AABB lower bound is an exact separation proof here.
            open_harness = lid_harness_pose(side, LID_OPEN_ANGLE_DEG)
            for frame, pose in enumerate(extraction_motion_occurrences(side)):
                for occurrence in pose:
                    for component_name, component in (
                        ("dynamic_flex", open_harness.flex_circuit),
                        ("fixed_connector", open_harness.fixed_connector),
                        ("moving_connector", open_harness.moving_connector),
                    ):
                        lower_bound = _aabb_clearance_lower_bound(
                            component,
                            occurrence.shape,
                        )
                        self.assertGreaterEqual(
                            lower_bound,
                            HARD_PART_MINIMUM_CLEARANCE_MM - 1.0e-6,
                            (
                                f"side={side} extraction frame={frame} "
                                f"{component_name} vs {occurrence.name}: "
                                f"AABB clearance={lower_bound:.6f} mm"
                            ),
                        )

    def test_production_breps_survive_step_roundtrip(self) -> None:
        shapes = [("canonical_half_leaf", canonical_half_leaf())]
        for side in (-1, 1):
            shapes.extend(
                (
                    f"side_{side}_{index}_{occurrence.name}",
                    occurrence.shape,
                )
                for index, occurrence in enumerate(
                    folded_pack_occurrences(side)
                )
            )
            for angle in (0.0, LID_OPEN_ANGLE_DEG):
                for occurrence in lid_harness_occurrences(side, angle):
                    shapes.append(
                        (
                            f"side_{side}_angle_{angle:g}_{occurrence.name}",
                            occurrence.shape,
                        )
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            for name, before_shape in shapes:
                target = output / f"{name}.step"
                exporters.export(before_shape, str(target))
                after_shape = importers.importStep(str(target)).val()
                before = _shape_signature(before_shape)
                after = _shape_signature(after_shape)
                delta = _signature_delta(before, after)
                failures = _roundtrip_signature_failures(
                    before,
                    after,
                    delta,
                    exact_topology=True,
                )
                with self.subTest(name=name):
                    self.assertTrue(after_shape.isValid())
                    self.assertEqual(len(after_shape.Solids()), 1)
                    self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
