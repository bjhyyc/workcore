"""Independent A05 top-lid dynamic-flex production gate.

The main V8 release gate can call :func:`evaluate_a05_lid_harness_gate` after
it has built the final state parts.  This module deliberately accepts the real
fixed-shell and closed-lid BReps as inputs, so it neither imports nor rebuilds
the full four-state assembly and can be tested without release-gate recursion.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import cadquery as cq

try:
    from .v8_table_lid_packaging import (
        LID_FLEX_MINIMUM_INSIDE_RADIUS_MM,
        LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM,
        LID_FLEX_MOVING_CONNECTOR_ENTRY_SETBACK_MM,
        LID_OPEN_ANGLE_DEG,
        extraction_motion_occurrences,
        folded_pack_occurrences,
        lid_harness_pose,
        pose_lid_shape,
    )
except ImportError:
    from v8_table_lid_packaging import (  # type: ignore[no-redef]
        LID_FLEX_MINIMUM_INSIDE_RADIUS_MM,
        LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM,
        LID_FLEX_MOVING_CONNECTOR_ENTRY_SETBACK_MM,
        LID_OPEN_ANGLE_DEG,
        extraction_motion_occurrences,
        folded_pack_occurrences,
        lid_harness_pose,
        pose_lid_shape,
    )


HARD_PART_MINIMUM_CLEARANCE_MM = 3.0
BOOLEAN_VOLUME_TOLERANCE_MM3 = 1.0e-5
CENTERLINE_LENGTH_VARIATION_LIMIT_MM = 0.005
FLEX_VOLUME_VARIATION_LIMIT_MM3 = 0.02
FIXED_CONNECTOR_BONDLINE_RANGE_MM = (0.15, 0.35)


def _aabb_clearance_lower_bound(first: cq.Shape, second: cq.Shape) -> float:
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


def _clearance(first: cq.Shape, second: cq.Shape) -> float:
    lower_bound = _aabb_clearance_lower_bound(first, second)
    if lower_bound >= HARD_PART_MINIMUM_CLEARANCE_MM:
        return lower_bound
    return float(first.distance(second))


def _angle_samples(step_deg: float) -> tuple[float, ...]:
    if step_deg <= 0.0 or step_deg > LID_OPEN_ANGLE_DEG:
        raise ValueError(
            f"Lid harness gate step must be in (0,{LID_OPEN_ANGLE_DEG}]"
        )
    count = int(round(LID_OPEN_ANGLE_DEG / step_deg))
    if abs(count * step_deg - LID_OPEN_ANGLE_DEG) > 1.0e-9:
        raise ValueError("Lid harness gate step must divide 105 degrees exactly")
    return tuple(index * step_deg for index in range(count + 1))


def evaluate_a05_lid_harness_gate(
    fixed_shell_by_side: Mapping[int, cq.Shape],
    closed_lid_parts_by_side: Mapping[
        int,
        Sequence[tuple[str, cq.Shape]],
    ],
    *,
    angle_step_deg: float = 1.0,
) -> dict[str, Any]:
    """Evaluate real BReps over the complete 0..105 degree lid motion.

    ``closed_lid_parts_by_side`` must include the body-colour lid and every
    rigid HMI part that moves with it.  A one-degree default produces 106
    actual occurrences per side.  Compounds retain those occurrences without
    filling the space between them, while pose-matched checks avoid comparing
    a flex at one angle to a lid at another.
    """

    if set(fixed_shell_by_side) != {-1, 1}:
        raise ValueError("A05 flex gate requires fixed shells for sides -1 and +1")
    if set(closed_lid_parts_by_side) != {-1, 1}:
        raise ValueError("A05 flex gate requires lid/HMI parts for sides -1 and +1")
    angles = _angle_samples(float(angle_step_deg))
    evidence: dict[str, Any] = {}
    all_failures: list[str] = []

    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        shell = fixed_shell_by_side[side]
        closed_parts = tuple(closed_lid_parts_by_side[side])
        if not closed_parts:
            raise ValueError(f"A05 {side_name} lid part list is empty")
        cap_name = f"A05_armrest_touch_lid_{side_name}"
        cap_matches = [shape for name, shape in closed_parts if name == cap_name]
        if len(cap_matches) != 1:
            raise ValueError(
                f"A05 {side_name} gate needs exactly one {cap_name!r}"
            )
        cap_closed = cap_matches[0]

        poses = tuple(lid_harness_pose(side, angle) for angle in angles)
        pack = cq.Compound.makeCompound(
            [item.shape for item in folded_pack_occurrences(side)]
        )
        flex_sweep = cq.Compound.makeCompound(
            [pose.flex_circuit for pose in poses]
        )
        connector_sweep = cq.Compound.makeCompound(
            [pose.moving_connector for pose in poses]
        )
        flex_shell_clearance = float(flex_sweep.distance(shell))
        flex_pack_clearance = float(flex_sweep.distance(pack))
        moving_connector_shell_clearance = float(
            connector_sweep.distance(shell)
        )
        moving_connector_pack_clearance = float(
            connector_sweep.distance(pack)
        )
        fixed_connector = poses[0].fixed_connector
        fixed_connector_pack_clearance = _clearance(fixed_connector, pack)
        fixed_connector_shell_bondline = float(
            fixed_connector.distance(shell)
        )

        lid_sweep_by_name: dict[str, list[cq.Shape]] = {
            name: [] for name, _ in closed_parts
        }
        flex_to_lid_proven_clearance = float("inf")
        flex_to_lid_worst_pose: dict[str, object] | None = None
        maximum_flex_lid_common = 0.0
        maximum_flex_lid_common_pose: dict[str, object] | None = None
        minimum_flex_capture_common = float("inf")
        minimum_flex_capture_pose: float | None = None
        maximum_free_capture_common = 0.0
        maximum_free_capture_pose: float | None = None
        maximum_capture_outside_connector = 0.0
        maximum_capture_outside_connector_pose: float | None = None
        for angle, pose in zip(angles, poses):
            # The final 1.5 mm of FPC centreline is intentionally captive in
            # the lid-mounted connector/strain relief.  The packaging model
            # builds the free span from that physically shortened centreline;
            # avoid a tangent solid subtraction whose OCC result is unstable
            # at one mirrored 74-degree pose.  The complete FPC still receives
            # a separate zero-common-volume proof against every lid/HMI part.
            free_span = pose.free_flex_span
            if free_span.isNull() or not free_span.isValid():
                raise ValueError(
                    f"A05 {side_name} free FPC span is invalid at {angle:g} deg"
                )
            flex_capture_common = float(
                pose.flex_circuit.intersect(
                    pose.moving_connector_capture
                ).Volume()
            )
            free_capture_common = float(
                free_span.intersect(pose.moving_connector_capture).Volume()
            )
            capture_outside_connector = float(
                pose.moving_connector_capture.cut(
                    pose.moving_connector
                ).Volume()
            )
            if flex_capture_common < minimum_flex_capture_common:
                minimum_flex_capture_common = flex_capture_common
                minimum_flex_capture_pose = angle
            if free_capture_common > maximum_free_capture_common:
                maximum_free_capture_common = free_capture_common
                maximum_free_capture_pose = angle
            if capture_outside_connector > maximum_capture_outside_connector:
                maximum_capture_outside_connector = capture_outside_connector
                maximum_capture_outside_connector_pose = angle
            for name, closed_shape in closed_parts:
                moving_shape = pose_lid_shape(
                    closed_shape,
                    side,
                    angle,
                )
                lid_sweep_by_name[name].append(moving_shape)
                clearance = _clearance(free_span, moving_shape)
                common = float(
                    pose.flex_circuit.intersect(moving_shape).Volume()
                )
                if clearance < flex_to_lid_proven_clearance:
                    flex_to_lid_proven_clearance = clearance
                    flex_to_lid_worst_pose = {
                        "angle_deg": angle,
                        "part": name,
                        "free_span_clearance_mm": clearance,
                    }
                if common > maximum_flex_lid_common:
                    maximum_flex_lid_common = common
                    maximum_flex_lid_common_pose = {
                        "angle_deg": angle,
                        "part": name,
                        "common_volume_mm3": common,
                    }

        cap_shapes = lid_sweep_by_name[cap_name]
        cap_closed_common = float(cap_shapes[0].intersect(shell).Volume())
        cap_open_clearance = float(
            cq.Compound.makeCompound(cap_shapes[1:]).distance(shell)
        )
        hmi_shell_clearances = {
            name: float(cq.Compound.makeCompound(shapes).distance(shell))
            for name, shapes in lid_sweep_by_name.items()
            if name != cap_name
        }
        full_lid_sweep = cq.Compound.makeCompound(
            [
                shape
                for shapes in lid_sweep_by_name.values()
                for shape in shapes
            ]
        )
        lid_pack_clearance = float(full_lid_sweep.distance(pack))

        moving_connector_cap_common = float(
            poses[0].moving_connector.intersect(cap_closed).Volume()
        )
        moving_connector_cap_gap = float(
            poses[0].moving_connector.distance(cap_closed)
        )
        connector_entry_common = min(
            float(
                pose.flex_circuit.intersect(pose.moving_connector).Volume()
            )
            for pose in (poses[0], poses[-1])
        )
        fixed_entry_common = min(
            float(
                pose.flex_circuit.intersect(pose.fixed_connector).Volume()
            )
            for pose in (poses[0], poses[-1])
        )

        lengths = [pose.centerline_length_mm for pose in poses]
        volumes = [float(pose.flex_circuit.Volume()) for pose in poses]
        minimum_inside_radius = min(
            pose.minimum_inside_bend_radius_mm for pose in poses
        )
        open_pose = poses[-1]
        extraction_aabb_clearance = float("inf")
        for extraction_pose in extraction_motion_occurrences(side):
            for table_occurrence in extraction_pose:
                for component in (
                    open_pose.flex_circuit,
                    open_pose.fixed_connector,
                    open_pose.moving_connector,
                ):
                    extraction_aabb_clearance = min(
                        extraction_aabb_clearance,
                        _aabb_clearance_lower_bound(
                            component,
                            table_occurrence.shape,
                        ),
                    )

        minima = {
            "flex_to_fixed_shell_mm": flex_shell_clearance,
            "flex_to_stowed_pack_mm": flex_pack_clearance,
            "flex_to_corresponding_lid_hmi_mm": flex_to_lid_proven_clearance,
            "moving_connector_to_fixed_shell_mm": (
                moving_connector_shell_clearance
            ),
            "moving_connector_to_stowed_pack_mm": (
                moving_connector_pack_clearance
            ),
            "fixed_connector_to_stowed_pack_mm": (
                fixed_connector_pack_clearance
            ),
            "lid_hmi_sweep_to_stowed_pack_mm": lid_pack_clearance,
            "open_harness_to_61_pose_extraction_aabb_mm": (
                extraction_aabb_clearance
            ),
        }
        failures: list[str] = []
        for label, value in minima.items():
            if value < HARD_PART_MINIMUM_CLEARANCE_MM - 1.0e-6:
                failures.append(f"{label}={value:.6f}<3.0")
        if maximum_flex_lid_common > BOOLEAN_VOLUME_TOLERANCE_MM3:
            failures.append(
                "flex_to_lid_hmi_common="
                f"{maximum_flex_lid_common:.9f}mm3"
            )
        if cap_closed_common > BOOLEAN_VOLUME_TOLERANCE_MM3:
            failures.append(
                f"closed_cap_shell_common={cap_closed_common:.9f}mm3"
            )
        if cap_open_clearance <= 0.0:
            failures.append("cap_did_not_separate_after_one_degree")
        for name, clearance in hmi_shell_clearances.items():
            if clearance <= 0.0:
                failures.append(f"{name}_touches_fixed_shell")
        if not (
            FIXED_CONNECTOR_BONDLINE_RANGE_MM[0]
            <= fixed_connector_shell_bondline
            <= FIXED_CONNECTOR_BONDLINE_RANGE_MM[1]
        ):
            failures.append(
                "fixed_connector_bondline="
                f"{fixed_connector_shell_bondline:.6f}mm_out_of_range"
            )
        if moving_connector_cap_common > BOOLEAN_VOLUME_TOLERANCE_MM3:
            failures.append(
                "moving_connector_cap_common="
                f"{moving_connector_cap_common:.9f}mm3"
            )
        if moving_connector_cap_gap > 1.0e-5:
            failures.append(
                f"moving_connector_cap_gap={moving_connector_cap_gap:.9f}mm"
            )
        if connector_entry_common <= 1.0 or fixed_entry_common <= 1.0:
            failures.append("flex_does_not_enter_both_physical_connectors")
        expected_capture_volume = (
            LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM * 6.0 * 0.6
        )
        if minimum_flex_capture_common < expected_capture_volume - 0.05:
            failures.append(
                "moving_capture_does_not_contain_1p5mm_fpc_tail="
                f"{minimum_flex_capture_common:.9f}mm3"
            )
        if maximum_free_capture_common > BOOLEAN_VOLUME_TOLERANCE_MM3:
            failures.append(
                "free_fpc_intrudes_moving_capture="
                f"{maximum_free_capture_common:.9f}mm3"
            )
        if maximum_capture_outside_connector > BOOLEAN_VOLUME_TOLERANCE_MM3:
            failures.append(
                "moving_capture_outside_connector_body="
                f"{maximum_capture_outside_connector:.9f}mm3"
            )
        length_variation = max(lengths) - min(lengths)
        volume_variation = max(volumes) - min(volumes)
        if length_variation > CENTERLINE_LENGTH_VARIATION_LIMIT_MM:
            failures.append(
                f"centerline_length_variation={length_variation:.6f}mm"
            )
        if volume_variation > FLEX_VOLUME_VARIATION_LIMIT_MM3:
            failures.append(f"flex_volume_variation={volume_variation:.6f}mm3")
        if minimum_inside_radius < LID_FLEX_MINIMUM_INSIDE_RADIUS_MM:
            failures.append(
                f"minimum_inside_bend_radius={minimum_inside_radius:.6f}mm"
            )

        all_failures.extend(f"{side_name}:{item}" for item in failures)
        evidence[side_name] = {
            "pass": not failures,
            "angle_step_deg": angle_step_deg,
            "evaluated_pose_count": len(angles),
            "moving_connector_capture_length_mm": (
                LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM
            ),
            "moving_connector_entry_setback_mm": (
                LID_FLEX_MOVING_CONNECTOR_ENTRY_SETBACK_MM
            ),
            "moving_connector_capture_evidence": {
                "minimum_complete_fpc_common_volume_mm3": round(
                    minimum_flex_capture_common,
                    6,
                ),
                "minimum_complete_fpc_common_angle_deg": (
                    minimum_flex_capture_pose
                ),
                "maximum_free_fpc_common_volume_mm3": round(
                    maximum_free_capture_common,
                    6,
                ),
                "maximum_free_fpc_common_angle_deg": (
                    maximum_free_capture_pose
                ),
                "maximum_capture_outside_connector_volume_mm3": round(
                    maximum_capture_outside_connector,
                    6,
                ),
                "maximum_capture_outside_connector_angle_deg": (
                    maximum_capture_outside_connector_pose
                ),
                "supplier_contact_geometry_frozen": False,
            },
            "minimum_clearances_mm": {
                key: round(value, 6) for key, value in minima.items()
            },
            "minimum_inside_bend_radius_mm": round(
                minimum_inside_radius,
                6,
            ),
            "centerline_length_range_mm": [
                round(min(lengths), 6),
                round(max(lengths), 6),
            ],
            "centerline_length_variation_mm": round(length_variation, 6),
            "flex_volume_range_mm3": [
                round(min(volumes), 6),
                round(max(volumes), 6),
            ],
            "flex_volume_variation_mm3": round(volume_variation, 6),
            "rolling_loop_axis_z_range_mm": [
                round(min(pose.rolling_loop_axis_z_mm for pose in poses), 6),
                round(max(pose.rolling_loop_axis_z_mm for pose in poses), 6),
            ],
            "fixed_connector_shell_bondline_mm": round(
                fixed_connector_shell_bondline,
                6,
            ),
            "closed_cap_shell_common_volume_mm3": round(
                cap_closed_common,
                9,
            ),
            "cap_open_sweep_minimum_shell_clearance_mm": round(
                cap_open_clearance,
                9,
            ),
            "hmi_sweep_minimum_shell_clearance_mm": {
                name: round(value, 6)
                for name, value in hmi_shell_clearances.items()
            },
            "moving_connector_cap_common_volume_mm3": round(
                moving_connector_cap_common,
                9,
            ),
            "moving_connector_cap_gap_mm": round(
                moving_connector_cap_gap,
                9,
            ),
            "minimum_flex_fixed_connector_common_volume_mm3": round(
                fixed_entry_common,
                6,
            ),
            "minimum_flex_moving_connector_common_volume_mm3": round(
                connector_entry_common,
                6,
            ),
            "free_flex_to_lid_hmi_worst_pose": flex_to_lid_worst_pose,
            "maximum_complete_flex_to_lid_hmi_common_volume_mm3": round(
                maximum_flex_lid_common,
                9,
            ),
            "maximum_complete_flex_to_lid_hmi_common_pose": (
                maximum_flex_lid_common_pose
            ),
            "connector_captive_segment_excluded_from_free_span_clearance": True,
            "failures": failures,
        }

    return {
        "gate_id": "a05.lid_dynamic_flex_full_motion",
        "pass": not all_failures,
        "evidence_kind": (
            "one_degree_brep_motion_sweep_constant_length_curvature_"
            "connector_and_extraction_clearance"
        ),
        "requirement": (
            "The open-ended rear FPC must remain physically connected to one "
            "fixed and one lid-carried connector, retain length and section, "
            "respect its bend radius, and clear the fixed shell, all lid/HMI "
            "poses, the stowed table and all 61 extraction poses.  Only the "
            "segment physically captive inside the moving connector is excluded "
            "from the three-millimetre free-span clearance."
        ),
        "hard_part_minimum_clearance_mm": HARD_PART_MINIMUM_CLEARANCE_MM,
        "sides": evidence,
        "failures": all_failures,
        "production_certification_claimed": False,
    }


__all__ = [
    "BOOLEAN_VOLUME_TOLERANCE_MM3",
    "CENTERLINE_LENGTH_VARIATION_LIMIT_MM",
    "FLEX_VOLUME_VARIATION_LIMIT_MM3",
    "FIXED_CONNECTOR_BONDLINE_RANGE_MM",
    "HARD_PART_MINIMUM_CLEARANCE_MM",
    "evaluate_a05_lid_harness_gate",
]
