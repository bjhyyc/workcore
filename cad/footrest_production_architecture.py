"""Executable A08 replacement kinematics.

This module freezes the one-degree-of-freedom datum selected in
``a08_production_motion_architecture.md``.  The production-intent rail, link,
lock and monocoque solids are authored by ``v8_footrest_drawer_brep`` and are
installed in the four final Class-A states by
``v8_final_appearance_closure``.  This file remains the kinematic datum only:
its mathematical law is not B-Rep collision evidence and is never physical
proof-load, fatigue, contamination, pinch or certification evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


PLATFORM_STOWED_CENTER_MM = (-360.0, 0.0, 147.0)
PLATFORM_DEPLOYED_CENTER_MM = (-605.0, 0.0, 95.0)
PLATFORM_THICKNESS_MM = 10.0
LOWER_CARRIAGE_PIVOT_Z_MM = 80.0
DROP_LINK_LENGTH_MM = 62.0
CLEAR_VERTICAL_COMPONENT_MM = 44.0
DEPLOYED_VERTICAL_COMPONENT_MM = 10.0
PRIMARY_CARTRIDGE_TRAVEL_MM = 144.0
FINAL_SKIN_HIGHEST_POINT_ABOVE_PLATFORM_CENTER_MM = 14.0
TACTILE_BUMPER_MINIMUM_Z_MM = 148.0
REQUIRED_TACTILE_BUMPER_DRY_GAP_MM = 5.0


def _horizontal_component(vertical_component_mm: float) -> float:
    return math.sqrt(
        DROP_LINK_LENGTH_MM**2 - float(vertical_component_mm) ** 2
    )


CLEAR_HORIZONTAL_COMPONENT_MM = _horizontal_component(
    CLEAR_VERTICAL_COMPONENT_MM
)
DEPLOYED_HORIZONTAL_COMPONENT_MM = _horizontal_component(
    DEPLOYED_VERTICAL_COMPONENT_MM
)
TOTAL_CAPTURED_RAIL_TRAVEL_MM = (
    abs(PLATFORM_DEPLOYED_CENTER_MM[0] - PLATFORM_STOWED_CENTER_MM[0])
    - DEPLOYED_HORIZONTAL_COMPONENT_MM
)
INNER_CARRIAGE_TRAVEL_MM = (
    TOTAL_CAPTURED_RAIL_TRAVEL_MM
    + CLEAR_HORIZONTAL_COMPONENT_MM
    - PRIMARY_CARTRIDGE_TRAVEL_MM
)
CLEAR_LINK_ANGLE_DEG = math.degrees(
    math.acos(CLEAR_VERTICAL_COMPONENT_MM / DROP_LINK_LENGTH_MM)
)
DEPLOYED_LINK_ANGLE_DEG = math.degrees(
    math.acos(DEPLOYED_VERTICAL_COMPONENT_MM / DROP_LINK_LENGTH_MM)
)


REQUIRED_PHYSICAL_OCCURRENCE_IDS = (
    "WC-A08-PLATFORM",
    "WC-A08-FIXED-ROOT-HOUSING",
    "WC-A08-PRIMARY-CARTRIDGE-LEFT",
    "WC-A08-PRIMARY-CARTRIDGE-RIGHT",
    "WC-A08-INNER-CARRIAGE-LEFT",
    "WC-A08-INNER-CARRIAGE-RIGHT",
    "WC-A08-DROP-LINK-LEFT-FRONT",
    "WC-A08-DROP-LINK-LEFT-REAR",
    "WC-A08-DROP-LINK-RIGHT-FRONT",
    "WC-A08-DROP-LINK-RIGHT-REAR",
    "WC-A08-DEPLOYED-LOCK-LEFT",
    "WC-A08-DEPLOYED-LOCK-RIGHT",
    "WC-A08-SYNCHRONISING-CROSS-SHAFT",
    "WC-A08-COUNTERBALANCE",
    "WC-A08-MANUAL-RELEASE",
    "WC-A08-FOOT-ZONE-INTERLOCK-A",
    "WC-A08-FOOT-ZONE-INTERLOCK-B",
)


@dataclass(frozen=True)
class FootrestProductionPose:
    progress: float
    phase: str
    platform_center_mm: tuple[float, float, float]
    lower_carriage_pivot_mm: tuple[float, float, float]
    upper_platform_pivot_mm: tuple[float, float, float]
    drop_link_angle_from_vertical_deg: float
    primary_cartridge_travel_mm: float
    inner_carriage_travel_mm: float
    captured_rail_travel_mm: float
    platform_pitch_deg: float = 0.0

    @property
    def link_pin_distance_mm(self) -> float:
        return math.dist(
            self.lower_carriage_pivot_mm,
            self.upper_platform_pivot_mm,
        )

    @property
    def platform_bottom_z_mm(self) -> float:
        return self.platform_center_mm[2] - PLATFORM_THICKNESS_MM / 2.0


def _lerp(start: float, end: float, u: float) -> float:
    return start + (end - start) * u


def production_footrest_pose(progress: float) -> FootrestProductionPose:
    """Return the connected drawer/drop-link pose at normalised progress 0..1."""

    progress = float(progress)
    if not 0.0 <= progress <= 1.0:
        raise ValueError(
            f"A08 production motion progress must be in [0, 1], got {progress}"
        )

    if progress <= 0.1:
        phase = "tactile_edge_clearance"
        local = progress / 0.1
        angle_deg = _lerp(0.0, CLEAR_LINK_ANGLE_DEG, local)
        horizontal_component = DROP_LINK_LENGTH_MM * math.sin(
            math.radians(angle_deg)
        )
        # Retract the captured inner carriage by exactly the link's forward
        # component.  The platform therefore descends at constant X instead of
        # swinging through the final 148 mm tactile-bumper datum.
        lower_pivot_x = PLATFORM_STOWED_CENTER_MM[0] + horizontal_component
        primary_travel = 0.0
        inner_travel = CLEAR_HORIZONTAL_COMPONENT_MM - horizontal_component
    elif progress <= 0.7:
        phase = "captured_drawer_extension"
        local = (progress - 0.1) / 0.6
        angle_deg = CLEAR_LINK_ANGLE_DEG
        extension_from_clear = (
            PRIMARY_CARTRIDGE_TRAVEL_MM + INNER_CARRIAGE_TRAVEL_MM
        ) * local
        primary_travel = min(
            extension_from_clear,
            PRIMARY_CARTRIDGE_TRAVEL_MM,
        )
        inner_travel = max(
            0.0,
            extension_from_clear - PRIMARY_CARTRIDGE_TRAVEL_MM,
        )
        lower_pivot_x = (
            PLATFORM_STOWED_CENTER_MM[0]
            + CLEAR_HORIZONTAL_COMPONENT_MM
            - primary_travel
            - inner_travel
        )
    else:
        phase = "over_centre_drop_and_lock"
        local = (progress - 0.7) / 0.3
        angle_deg = _lerp(CLEAR_LINK_ANGLE_DEG, DEPLOYED_LINK_ANGLE_DEG, local)
        primary_travel = PRIMARY_CARTRIDGE_TRAVEL_MM
        inner_travel = INNER_CARRIAGE_TRAVEL_MM
        lower_pivot_x = (
            PLATFORM_STOWED_CENTER_MM[0]
            - TOTAL_CAPTURED_RAIL_TRAVEL_MM
        )

    angle_rad = math.radians(angle_deg)
    horizontal_component = DROP_LINK_LENGTH_MM * math.sin(angle_rad)
    vertical_component = DROP_LINK_LENGTH_MM * math.cos(angle_rad)
    rail_travel = PLATFORM_STOWED_CENTER_MM[0] - lower_pivot_x
    lower_pivot = (
        lower_pivot_x,
        0.0,
        LOWER_CARRIAGE_PIVOT_Z_MM,
    )
    upper_pivot = (
        lower_pivot[0] - horizontal_component,
        0.0,
        lower_pivot[2] + vertical_component,
    )
    platform_center = (
        upper_pivot[0],
        0.0,
        upper_pivot[2] + PLATFORM_THICKNESS_MM / 2.0,
    )
    return FootrestProductionPose(
        progress=progress,
        phase=phase,
        platform_center_mm=platform_center,
        lower_carriage_pivot_mm=lower_pivot,
        upper_platform_pivot_mm=upper_pivot,
        drop_link_angle_from_vertical_deg=angle_deg,
        primary_cartridge_travel_mm=primary_travel,
        inner_carriage_travel_mm=inner_travel,
        captured_rail_travel_mm=rail_travel,
    )


def production_motion_contract_evidence(samples: int = 101) -> dict[str, object]:
    """Return deterministic kinematic evidence; this is not a B-Rep collision gate."""

    if samples < 2:
        raise ValueError("A08 production evidence requires at least two samples")
    poses = [
        production_footrest_pose(index / (samples - 1))
        for index in range(samples)
    ]
    return {
        "status": "KINEMATIC_DATUM_ONLY_NOT_RELEASED",
        "samples": samples,
        "same_required_occurrence_inventory": REQUIRED_PHYSICAL_OCCURRENCE_IDS,
        "minimum_platform_bottom_z_mm": min(
            pose.platform_bottom_z_mm for pose in poses
        ),
        "maximum_link_length_error_mm": max(
            abs(pose.link_pin_distance_mm - DROP_LINK_LENGTH_MM)
            for pose in poses
        ),
        "platform_x_monotonic_forward": all(
            later.platform_center_mm[0] <= earlier.platform_center_mm[0] + 1.0e-9
            for earlier, later in zip(poses, poses[1:])
        ),
        "primary_cartridge_travel_monotonic": all(
            later.primary_cartridge_travel_mm
            >= earlier.primary_cartridge_travel_mm - 1.0e-9
            for earlier, later in zip(poses, poses[1:])
        ),
        "tactile_bumper_clearance_mm": (
            TACTILE_BUMPER_MINIMUM_Z_MM
            - (
                production_footrest_pose(0.1).platform_center_mm[2]
                + FINAL_SKIN_HIGHEST_POINT_ABOVE_PLATFORM_CENTER_MM
            )
        ),
        "release_ready": False,
        "missing_evidence": (
            "final_BRep_inventory",
            "moving_vs_moving_clearance",
            "moving_vs_fixed_clearance",
            "human_and_ground_swept_volume",
            "positive_lock_BReps",
            "tolerance_stack",
            "proof_load_and_fatigue_test",
        ),
    }


__all__ = [
    "FootrestProductionPose",
    "REQUIRED_PHYSICAL_OCCURRENCE_IDS",
    "production_footrest_pose",
    "production_motion_contract_evidence",
]
