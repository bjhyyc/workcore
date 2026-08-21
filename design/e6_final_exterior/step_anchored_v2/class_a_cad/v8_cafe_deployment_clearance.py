"""Exact layout-level clearance proof for the final V8 Cafe table sequence.

The final Cafe endpoint is unchanged.  This module exists because a static
endpoint check cannot prove that the table can be taken from the outward-open
top lid while the right drive pod remains present, nor that the old same-height
90-degree turn avoids the closed lid and joystick.  Supplier components are
not frozen, so the guided support is deliberately an honest packaging envelope
rather than a fabricated catalogue mechanism.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import cadquery as cq

try:
    from .skin_common import SkinPart
    from .v8_cafe_table_root_motion import (
        CAFE_INBOARD_RETURN_TRAVEL_MM,
        CAFE_ROTATION_CLEARANCE_LIFT_MM,
        CAFE_RETURN_TRAVEL_MM,
        CAFE_TABLE_ROTATION_AXIS_MM,
        cafe_clearance_deployment_frames,
    )
    from .v8_table_lid_packaging import (
        CAFE_CLEARANCE_AXIS_X_MM,
        DEPLOYED_LEAF_CENTRE_Z_MM,
        FOCUS_AXIS_ABS_Y_MM,
        LID_OPEN_ANGLE_DEG,
        SequenceContext,
        TABLE_ACCESS_SEQUENCE,
        extraction_motion_occurrences,
        pose_lid_shape,
        unfold_motion_pose,
        validate_use_sequence,
    )
except ImportError:
    from skin_common import SkinPart  # type: ignore[no-redef]
    from v8_cafe_table_root_motion import (  # type: ignore[no-redef]
        CAFE_INBOARD_RETURN_TRAVEL_MM,
        CAFE_ROTATION_CLEARANCE_LIFT_MM,
        CAFE_RETURN_TRAVEL_MM,
        CAFE_TABLE_ROTATION_AXIS_MM,
        cafe_clearance_deployment_frames,
    )
    from v8_table_lid_packaging import (  # type: ignore[no-redef]
        CAFE_CLEARANCE_AXIS_X_MM,
        DEPLOYED_LEAF_CENTRE_Z_MM,
        FOCUS_AXIS_ABS_Y_MM,
        LID_OPEN_ANGLE_DEG,
        SequenceContext,
        TABLE_ACCESS_SEQUENCE,
        extraction_motion_occurrences,
        pose_lid_shape,
        unfold_motion_pose,
        validate_use_sequence,
    )


BOOLEAN_TOLERANCE_MM3 = 1.0e-5
OPEN_EXTRACTION_MINIMUM_CLEARANCE_MM = 1.0
LID_CLOSE_MINIMUM_CLEARANCE_MM = 5.0
FIXED_CONTROL_MINIMUM_CLEARANCE_MM = 5.0
MOTION_SAMPLES_PER_LEG = 21
LID_SWEEP_SAMPLES = 22

_FIXED_RIGHT_OBSTACLE_NAMES = (
    "A05_armrest_table_bay_shell_right",
    "A05_armrest_top_lid_hinge_reveal_right",
    "A05_armrest_top_lid_release_right",
    "A05_table_cassette_lowpoint_drain_right",
)
_CLOSED_RIGHT_OBSTACLE_NAMES = (
    *_FIXED_RIGHT_OBSTACLE_NAMES,
    "A05_armrest_touch_lid_right",
    "A05_right_table_root_tongue_compression_gland",
    "A05_right_removable_drive_pod",
    "A05_right_joystick",
    "A05_right_authorisation_key",
)
_CONTROL_NAMES = (
    "A05_right_removable_drive_pod",
    "A05_right_joystick",
    "A05_right_authorisation_key",
)
_FINAL_ROOT_NAME = "A09_cafe_underleaf_motion_belly_right"


def _shape_signature(shape: cq.Shape) -> dict[str, Any]:
    box = shape.BoundingBox()
    centre = shape.Center()
    return {
        "volume_mm3": round(float(shape.Volume()), 6),
        "area_mm2": round(float(shape.Area()), 6),
        "centre_mm": [
            round(float(centre.x), 6),
            round(float(centre.y), 6),
            round(float(centre.z), 6),
        ],
        "bounds_mm": [
            round(float(value), 6)
            for value in (
                box.xmin,
                box.xmax,
                box.ymin,
                box.ymax,
                box.zmin,
                box.zmax,
            )
        ],
        "topology": {
            "solids": len(shape.Solids()),
            "shells": len(shape.Shells()),
            "faces": len(shape.Faces()),
            "edges": len(shape.Edges()),
            "vertices": len(shape.Vertices()),
        },
        "valid": bool(shape.isValid()),
    }


def _common_volume(first: cq.Shape, second: cq.Shape) -> float:
    if float(first.distance(second)) > 1.0e-7:
        return 0.0
    return float(first.intersect(second).Volume())


def _collisions_against_named_obstacles(
    moving: Sequence[tuple[str, cq.Shape]],
    obstacles: Sequence[tuple[str, cq.Shape]],
    *,
    phase: str,
    frame: int,
) -> tuple[list[dict[str, Any]], float, tuple[str, str] | None]:
    collisions: list[dict[str, Any]] = []
    minimum_distance = float("inf")
    minimum_pair: tuple[str, str] | None = None
    obstacle_compound = cq.Compound.makeCompound([shape for _, shape in obstacles])
    for moving_name, moving_shape in moving:
        distance = float(moving_shape.distance(obstacle_compound))
        if distance < minimum_distance:
            minimum_distance = distance
            minimum_pair = (moving_name, "obstacle_compound")
        if distance > 1.0e-7:
            continue
        compound_common = float(moving_shape.intersect(obstacle_compound).Volume())
        if compound_common <= BOOLEAN_TOLERANCE_MM3:
            continue
        for obstacle_name, obstacle_shape in obstacles:
            common = _common_volume(moving_shape, obstacle_shape)
            pair_distance = float(moving_shape.distance(obstacle_shape))
            if pair_distance < minimum_distance:
                minimum_distance = pair_distance
                minimum_pair = (moving_name, obstacle_name)
            if common > BOOLEAN_TOLERANCE_MM3:
                collisions.append(
                    {
                        "phase": phase,
                        "frame": frame,
                        "moving": moving_name,
                        "obstacle": obstacle_name,
                        "common_volume_mm3": round(common, 9),
                    }
                )
    return collisions, minimum_distance, minimum_pair


def _final_identity_evidence(
    expected: cq.Shape,
    actual: cq.Shape,
) -> dict[str, Any]:
    expected_volume = float(expected.Volume())
    actual_volume = float(actual.Volume())
    common = float(expected.intersect(actual).Volume())
    symmetric_volume = max(0.0, expected_volume + actual_volume - 2.0 * common)
    expected_box = expected.BoundingBox()
    actual_box = actual.BoundingBox()
    maximum_bound_delta = max(
        abs(float(first) - float(second))
        for first, second in zip(
            (
                expected_box.xmin,
                expected_box.xmax,
                expected_box.ymin,
                expected_box.ymax,
                expected_box.zmin,
                expected_box.zmax,
            ),
            (
                actual_box.xmin,
                actual_box.xmax,
                actual_box.ymin,
                actual_box.ymax,
                actual_box.zmin,
                actual_box.zmax,
            ),
        )
    )
    passed = (
        symmetric_volume <= BOOLEAN_TOLERANCE_MM3
        and maximum_bound_delta <= 1.0e-6
        and len(expected.Solids()) == len(actual.Solids()) == 1
        and expected.isValid()
        and actual.isValid()
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "expected_volume_mm3": round(expected_volume, 6),
        "actual_volume_mm3": round(actual_volume, 6),
        "common_volume_mm3": round(common, 6),
        "symmetric_difference_volume_mm3": round(symmetric_volume, 9),
        "maximum_bound_delta_mm": round(maximum_bound_delta, 9),
        "expected_signature": _shape_signature(expected),
        "actual_signature": _shape_signature(actual),
    }


def _pose_released_cafe_table_shape(
    final_shape: cq.Shape,
    rotation_progress: float,
    return_progress: float,
    lift_mm: float,
) -> cq.Shape:
    """Pose one actual final table-layer BRep without substituting a proxy."""

    ox, oy, oz = CAFE_TABLE_ROTATION_AXIS_MM
    master = final_shape.translate(
        (
            -CAFE_RETURN_TRAVEL_MM,
            -CAFE_INBOARD_RETURN_TRAVEL_MM,
            0.0,
        )
    ).rotate(
        (ox, oy, oz),
        (ox, oy, oz + 1.0),
        -90.0,
    )
    return master.rotate(
        (ox, oy, oz),
        (ox, oy, oz + 1.0),
        90.0 * rotation_progress,
    ).translate(
        (
            CAFE_RETURN_TRAVEL_MM * return_progress,
            CAFE_INBOARD_RETURN_TRAVEL_MM * return_progress,
            lift_mm,
        )
    )


def critical_cafe_deployment_report(
    parts: Sequence[SkinPart],
    *,
    motion_samples_per_leg: int = MOTION_SAMPLES_PER_LEG,
    lid_sweep_samples: int = LID_SWEEP_SAMPLES,
) -> dict[str, Any]:
    """Prove the actual final Cafe table can follow its complete user sequence."""

    if motion_samples_per_leg < 2 or lid_sweep_samples < 2:
        raise ValueError("Cafe deployment audit needs at least two samples per leg")
    by_name = {part.name: part for part in parts}
    duplicates = sorted(
        name
        for name in {part.name for part in parts}
        if sum(part.name == name for part in parts) != 1
    )
    actual_table_parts = [
        part
        for part in parts
        if part.metadata.get("rigid_half_leaf_occurrence_id")
        or part.name == "A09_table_fold_flexure_right"
    ]
    actual_table_names = tuple(sorted(part.name for part in actual_table_parts))
    if len(actual_table_parts) < 7:
        failures.append(
            "released Cafe table-layer inventory is incomplete: "
            f"{list(actual_table_names)}"
        )
    required_names = set(_CLOSED_RIGHT_OBSTACLE_NAMES) | {_FINAL_ROOT_NAME}
    required_names.update(actual_table_names)
    missing = sorted(required_names - set(by_name))
    failures: list[str] = []
    if duplicates:
        failures.append(f"duplicate final part names: {duplicates}")
    if missing:
        failures.append(f"missing final Cafe parts: {missing}")
    if failures:
        return {
            "schema_version": 1,
            "gate": "Cafe complete top-access and high-clearance deployment BRep",
            "state": "cafe",
            "status": "FAIL",
            "failures": failures,
            "collisions": [],
            "missing_parts": missing,
            "duplicate_parts": duplicates,
        }

    fixed_obstacles = [
        (name, by_name[name].shape) for name in _FIXED_RIGHT_OBSTACLE_NAMES
    ]
    closed_obstacles = [
        (name, by_name[name].shape) for name in _CLOSED_RIGHT_OBSTACLE_NAMES
    ]
    control_obstacles = [(name, by_name[name].shape) for name in _CONTROL_NAMES]
    lid_carried = [
        part
        for part in parts
        if part.name == "A05_armrest_touch_lid_right"
        or (
            bool(part.metadata.get("moves_with_top_lid"))
            and part.metadata.get("fixed_to") == "A05_armrest_touch_lid_right"
        )
    ]
    expected_lid_carried = {
        "A05_armrest_touch_lid_right",
        "A05_right_removable_drive_pod",
        "A05_right_joystick",
        "A05_right_authorisation_key",
    }
    if {part.name for part in lid_carried} != expected_lid_carried:
        failures.append("right lid-carried control inventory drifted")

    collisions: list[dict[str, Any]] = []
    minimum_open_clearance = float("inf")
    minimum_open_pair: tuple[str, str] | None = None
    open_lid_obstacles = [
        *fixed_obstacles,
        *[
            (
                part.name,
                pose_lid_shape(part.shape, 1, LID_OPEN_ANGLE_DEG),
            )
            for part in lid_carried
        ],
    ]

    extraction_poses = extraction_motion_occurrences(
        1,
        motion_samples_per_leg,
        target_axis_x=CAFE_CLEARANCE_AXIS_X_MM,
    )
    for frame_index, pose in enumerate(extraction_poses):
        frame_collisions, distance, pair = _collisions_against_named_obstacles(
            [(occurrence.name, occurrence.shape) for occurrence in pose],
            open_lid_obstacles,
            phase="extract_folded_pack_with_lid_open",
            frame=frame_index,
        )
        collisions.extend(frame_collisions)
        if distance < minimum_open_clearance:
            minimum_open_clearance = distance
            minimum_open_pair = pair

    unfold_poses = tuple(
        unfold_motion_pose(
            1,
            index / (motion_samples_per_leg - 1),
            axis_x=CAFE_CLEARANCE_AXIS_X_MM,
            axis_abs_y=FOCUS_AXIS_ABS_Y_MM,
            axis_z=DEPLOYED_LEAF_CENTRE_Z_MM,
        )
        for index in range(motion_samples_per_leg)
    )
    for frame_index, pose in enumerate(unfold_poses):
        frame_collisions, distance, pair = _collisions_against_named_obstacles(
            [(occurrence.name, occurrence.shape) for occurrence in pose],
            open_lid_obstacles,
            phase="unfold_clear_of_open_lid",
            frame=frame_index,
        )
        collisions.extend(frame_collisions)
        if distance < minimum_open_clearance:
            minimum_open_clearance = distance
            minimum_open_pair = pair

    deployment_frames = cafe_clearance_deployment_frames(motion_samples_per_leg)
    raised_frame = next(
        frame
        for frame in deployment_frames
        if frame.phase == "raise_with_lid_open"
        and abs(frame.lift_mm - CAFE_ROTATION_CLEARANCE_LIFT_MM) <= 1.0e-9
    )
    raised_moving = [
        *[
            (
                part.name,
                _pose_released_cafe_table_shape(
                    part.shape,
                    raised_frame.rotation_progress,
                    raised_frame.return_progress,
                    raised_frame.lift_mm,
                ),
            )
            for part in actual_table_parts
        ],
        *[
            (item.name, item.shape)
            for item in raised_frame.root_occurrences
            if item.motion_owner == "cafe_right_outer_root_half_leaf"
        ],
    ]
    minimum_lid_close_clearance = float("inf")
    minimum_lid_close_pair: tuple[str, str] | None = None
    for frame_index in range(lid_sweep_samples):
        angle = LID_OPEN_ANGLE_DEG * frame_index / (lid_sweep_samples - 1)
        obstacles = [
            *fixed_obstacles,
            *[
                (part.name, pose_lid_shape(part.shape, 1, angle))
                for part in lid_carried
            ],
        ]
        frame_collisions, distance, pair = _collisions_against_named_obstacles(
            raised_moving,
            obstacles,
            phase="close_lid_below_raised_table_before_support_dock",
            frame=frame_index,
        )
        collisions.extend(frame_collisions)
        if distance < minimum_lid_close_clearance:
            minimum_lid_close_clearance = distance
            minimum_lid_close_pair = pair

    minimum_closed_clearance = float("inf")
    minimum_closed_pair: tuple[str, str] | None = None
    minimum_control_clearance = float("inf")
    minimum_control_pair: tuple[str, str] | None = None
    rigid_reference_volumes: dict[str, float] = {}
    rigid_volume_drift = 0.0
    frame_inventory: list[dict[str, Any]] = []
    for frame_index, frame in enumerate(deployment_frames):
        posed_table = [
            (
                part.name,
                _pose_released_cafe_table_shape(
                    part.shape,
                    frame.rotation_progress,
                    frame.return_progress,
                    frame.lift_mm,
                ),
            )
            for part in actual_table_parts
        ]
        moving = [
            *posed_table,
            *[
                (item.name, item.shape)
                for item in frame.root_occurrences
                if item.motion_owner == "cafe_right_outer_root_half_leaf"
            ],
            *[(item.name, item.shape) for item in frame.support_envelopes],
        ]
        for name, shape in moving:
            if name.startswith("A09_cafe_transient_"):
                continue
            volume = float(shape.Volume())
            if name not in rigid_reference_volumes:
                rigid_reference_volumes[name] = volume
            rigid_volume_drift = max(
                rigid_volume_drift,
                abs(volume - rigid_reference_volumes[name]),
            )
        obstacles = (
            open_lid_obstacles
            if frame.phase == "raise_with_lid_open"
            else closed_obstacles
        )
        frame_collisions, distance, pair = _collisions_against_named_obstacles(
            moving,
            obstacles,
            phase=frame.phase,
            frame=frame_index,
        )
        collisions.extend(frame_collisions)
        if distance < minimum_closed_clearance:
            minimum_closed_clearance = distance
            minimum_closed_pair = pair
        control_collisions, control_distance, control_pair = (
            _collisions_against_named_obstacles(
                moving,
                control_obstacles,
                phase=f"{frame.phase}_fixed_control_clearance",
                frame=frame_index,
            )
        )
        collisions.extend(control_collisions)
        if control_distance < minimum_control_clearance:
            minimum_control_clearance = control_distance
            minimum_control_pair = control_pair
        frame_inventory.append(
            {
                "phase": frame.phase,
                "phase_index": frame.phase_index,
                "phase_progress": round(frame.phase_progress, 6),
                "rotation_progress": round(frame.rotation_progress, 6),
                "return_progress": round(frame.return_progress, 6),
                "lift_mm": round(frame.lift_mm, 6),
                "lid_angle_deg": round(frame.lid_angle_deg, 6),
                "support_docked": frame.support_docked,
                "rigid_occurrence_names": [
                    *[name for name, _ in posed_table],
                    *[
                        item.name
                        for item in frame.root_occurrences
                        if item.motion_owner
                        == "cafe_right_outer_root_half_leaf"
                    ],
                ],
                "support_envelope_names": [
                    item.name for item in frame.support_envelopes
                ],
            }
        )

    final_frame = deployment_frames[-1]
    expected_final = {
        **{
            part.name: _pose_released_cafe_table_shape(
                part.shape,
                final_frame.rotation_progress,
                final_frame.return_progress,
                final_frame.lift_mm,
            )
            for part in actual_table_parts
        },
        **{
            item.name: item.shape
            for item in final_frame.root_occurrences
            if item.motion_owner == "cafe_right_outer_root_half_leaf"
        },
    }
    final_identity = {
        name: _final_identity_evidence(shape, by_name[name].shape)
        for name, shape in expected_final.items()
    }
    sequence_valid, sequence_failures = validate_use_sequence(
        TABLE_ACCESS_SEQUENCE,
        SequenceContext(
            parked=True,
            traction_disabled=True,
            phone_present=False,
            qi_energised=False,
            drive_pod_present=True,
            sweep_zone_clear=True,
            lid_double_latch_confirmed=True,
        ),
    )

    if collisions:
        failures.append(f"{len(collisions)} exact hard-part collisions")
    if minimum_open_clearance < OPEN_EXTRACTION_MINIMUM_CLEARANCE_MM - 1.0e-6:
        failures.append(
            "open-lid extraction/unfold clearance is "
            f"{minimum_open_clearance:.6f} mm"
        )
    if minimum_lid_close_clearance < LID_CLOSE_MINIMUM_CLEARANCE_MM - 1.0e-6:
        failures.append(
            f"raised table/lid-close clearance is {minimum_lid_close_clearance:.6f} mm"
        )
    if minimum_control_clearance < FIXED_CONTROL_MINIMUM_CLEARANCE_MM - 1.0e-6:
        failures.append(
            f"fixed control sweep clearance is {minimum_control_clearance:.6f} mm"
        )
    if rigid_volume_drift > 1.0e-5:
        failures.append(f"rigid moving occurrence volume drift is {rigid_volume_drift}")
    if any(evidence["status"] != "PASS" for evidence in final_identity.values()):
        failures.append("final motion endpoint does not match released Cafe BReps")
    if not sequence_valid:
        failures.append("table access sequence/interlock contract failed")
    if final_frame.lift_mm != 0.0 or final_frame.rotation_progress != 1.0 or final_frame.return_progress != 1.0:
        failures.append("Cafe deployment path did not terminate at the final locked pose")

    return {
        "schema_version": 1,
        "gate": "Cafe complete top-access and high-clearance deployment BRep",
        "state": "cafe",
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "collision_count": len(collisions),
        "collisions": collisions,
        "final_endpoint_unchanged": all(
            evidence["status"] == "PASS" for evidence in final_identity.values()
        ),
        "clearance_lift_mm": CAFE_ROTATION_CLEARANCE_LIFT_MM,
        "old_same_height_path_released": False,
        "support_policy": (
            "parameterised connected guided-support packaging envelope; supplier "
            "rail/bearing/telescopic architecture is not claimed"
        ),
        "support_joint_location": "inside A05 below closed top lid",
        "only_smooth_tongue_crosses_sealed_gland": True,
        "table_support_hinges_outside_armrest": False,
        "right_controls_remain_present_and_lid_carried_during_extraction": True,
        "right_controls_return_to_fixed_top_datum_before_rotation": True,
        "motion_samples_per_leg": motion_samples_per_leg,
        "extraction_pose_count": len(extraction_poses),
        "unfold_pose_count": len(unfold_poses),
        "lid_close_pose_count": lid_sweep_samples,
        "post_extraction_pose_count": len(deployment_frames),
        "minimum_open_extraction_unfold_clearance_mm": round(
            minimum_open_clearance, 6
        ),
        "minimum_open_extraction_unfold_pair": minimum_open_pair,
        "minimum_raised_table_lid_close_clearance_mm": round(
            minimum_lid_close_clearance, 6
        ),
        "minimum_raised_table_lid_close_pair": minimum_lid_close_pair,
        "minimum_closed_motion_clearance_mm": round(
            minimum_closed_clearance, 6
        ),
        "minimum_closed_motion_pair": minimum_closed_pair,
        "minimum_fixed_control_clearance_mm": round(
            minimum_control_clearance, 6
        ),
        "minimum_fixed_control_pair": minimum_control_pair,
        "rigid_occurrence_maximum_volume_drift_mm3": round(
            rigid_volume_drift, 9
        ),
        "final_brep_identity": final_identity,
        "table_access_sequence": list(TABLE_ACCESS_SEQUENCE),
        "sequence_interlock_status": "PASS" if sequence_valid else "FAIL",
        "sequence_interlock_failures": list(sequence_failures),
        "closed_obstacle_inventory": list(_CLOSED_RIGHT_OBSTACLE_NAMES),
        "released_table_rigid_layer_inventory": list(actual_table_names),
        "lid_carried_inventory": sorted(expected_lid_carried),
        "final_part_signatures": {
            name: _shape_signature(by_name[name].shape)
            for name in sorted(required_names)
        },
        "frames": frame_inventory,
    }


__all__ = [
    "BOOLEAN_TOLERANCE_MM3",
    "FIXED_CONTROL_MINIMUM_CLEARANCE_MM",
    "LID_CLOSE_MINIMUM_CLEARANCE_MM",
    "LID_SWEEP_SAMPLES",
    "MOTION_SAMPLES_PER_LEG",
    "OPEN_EXTRACTION_MINIMUM_CLEARANCE_MM",
    "critical_cafe_deployment_report",
]
