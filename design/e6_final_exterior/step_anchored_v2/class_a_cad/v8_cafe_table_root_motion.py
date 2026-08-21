"""Production-intent Cafe table root, internal bearing and docking tongue.

The Cafe leaf does not carry one impossible shell that is simultaneously
fixed to the lift column and translated 80 mm with the table.  The load path
is split into the parts that actually own each degree of freedom:

* every fixed/rotary bearing, lock and guide B-Rep is packaged inside the
  right-armrest usable cavity (Y=316..361.5 mm);
* the same two rigid half-leaves remain the visible table and index to an
  outboard limit of Y=276 mm in both Focus and Cafe;
* one table-attached closed root neck is the only member crossing the 34 mm
  gap to the armrest.  Its structural blade receives an eight-millimetre
  radiused exterior envelope only across that gap, then drops into the
  concealed internal cartridge;
* all bearings, rails, shoes and lock hardware remain behind the armrest skin.

Coordinates are millimetres in the controlled E6 frame: -X front, +Y right,
+Z up.  This module is geometry-only and never writes release artefacts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import cadquery as cq

try:
    from .skin_common import rounded_box, rounded_rect_prism
    from .v8_table_lid_packaging import (
        CAFE_CLEARANCE_AXIS_X_MM,
        CAFE_FINAL_AXIS_X_MM,
        CAFE_INBOARD_RETURN_TRAVEL_MM,
        DEPLOYED_LEAF_CENTRE_Z_MM,
        FOCUS_AXIS_ABS_Y_MM,
        MechanismOccurrence,
        cafe_half_leaf_pair,
    )
except ImportError:
    from skin_common import rounded_box, rounded_rect_prism  # type: ignore[no-redef]
    from v8_table_lid_packaging import (  # type: ignore[no-redef]
        CAFE_CLEARANCE_AXIS_X_MM,
        CAFE_FINAL_AXIS_X_MM,
        CAFE_INBOARD_RETURN_TRAVEL_MM,
        DEPLOYED_LEAF_CENTRE_Z_MM,
        FOCUS_AXIS_ABS_Y_MM,
        MechanismOccurrence,
        cafe_half_leaf_pair,
    )


CAFE_TABLE_ROTATION_AXIS_MM = (
    CAFE_CLEARANCE_AXIS_X_MM,
    FOCUS_AXIS_ABS_Y_MM,
    DEPLOYED_LEAF_CENTRE_Z_MM,
)
# The complete mechanism cartridge is inside the released right-armrest
# cavity.  These bounds retain at least 0.5 mm from the stated usable
# Y=316..361.5 mm envelope; the surrounding A05 shell provides the weather
# surface and no rail/bearing B-Rep is exposed on the outboard face.
CAFE_INTERNAL_CAVITY_Y_MIN_MM = 316.0
CAFE_INTERNAL_CAVITY_Y_MAX_MM = 361.5
CAFE_ROOT_AXIS_MM = (-337.0, 338.75, 648.0)
CAFE_RETURN_TRAVEL_MM = CAFE_FINAL_AXIS_X_MM - CAFE_CLEARANCE_AXIS_X_MM
CAFE_COVER_PICKUP_DEAD_TRAVEL_MM = 40.0
# Component suppliers are not frozen at this layout-appearance stage.  Do not
# invent a catalogue linear-rail length or capture value: the released B-Reps
# below prove the final static load path and reserve the in-armrest kinematic
# volume, while detailed bearings/guides remain a later engineering release.
CAFE_FINAL_RAIL_CAPTURE_MM = 0.0
CAFE_INTERNAL_FOLD_HARD_RETREAT_MM = 3.0
CAFE_PADDLE_OUTER_UNDERSIDE_Y_MM = 326.5
CAFE_WITNESS_OUTER_UNDERSIDE_Y_MM = 336.0
CAFE_CONTROL_TOP_Z_MM = 636.0
# The former same-height 90-degree sweep passed directly through the fixed
# drive pod, joystick, closed top lid and A05 shell.  The final endpoint is not
# changed: deployment now uses one 90 mm transient clearance lift, rotates and
# returns above the complete fixed-control sweep, then lowers into the original
# locked Cafe datum.  Ninety millimetres leaves a measured 13 mm worst-case
# hard-part reserve in the actual final geometry; 80 mm was collision-free but
# retained only 3 mm and is therefore not a production-layout reserve.
CAFE_ROTATION_CLEARANCE_LIFT_MM = 90.0

# These dimensions are packaging envelopes, not invented supplier hardware.
# The 11 x 23 mm riser is the already released final tongue section and passes
# through the existing 13 x 25 mm sealed A05 hard opening with 1 mm per-side
# clearance.  Its base rotary joint remains below the closed lid inside A05;
# only the smooth guided tongue and telescoping arm can emerge transiently.
CAFE_SUPPORT_RISER_SECTION_MM = (11.0, 23.0)
CAFE_SUPPORT_PASSAGE_CENTRE_XY_MM = (-353.5, 328.0)
CAFE_SUPPORT_RISER_LOWER_Z_MM = 650.0
CAFE_SUPPORT_ARM_Z_MM = 687.0
CAFE_SUPPORT_ARM_RADIUS_MM = 4.0
CAFE_SUPPORT_FINAL_TABLE_ANCHOR_MM = (-363.0, 276.0, CAFE_SUPPORT_ARM_Z_MM)
CAFE_SUPPORT_MASTER_TABLE_ANCHOR_MM = (-215.0, 154.0, CAFE_SUPPORT_ARM_Z_MM)


@dataclass(frozen=True)
class CafeRootOccurrence:
    """One conserved Cafe-root occurrence in a particular mechanism pose."""

    name: str
    physical_occurrence_id: str
    shape: cq.Shape
    role: str
    motion_owner: str


@dataclass(frozen=True)
class CafeDeploymentFrame:
    """One legal post-extraction Cafe clearance-motion frame.

    The actual table leaves and closed root belly remain rigid occurrences.
    ``support_envelopes`` is explicitly a parameterised swept packaging volume
    for the later supplier mechanism; it does not claim a released catalogue
    rail, bearing or telescopic-stage design.
    """

    phase: str
    phase_index: int
    phase_progress: float
    rotation_progress: float
    return_progress: float
    lift_mm: float
    lid_angle_deg: float
    support_docked: bool
    leaf_occurrences: tuple[MechanismOccurrence, ...]
    root_occurrences: tuple[CafeRootOccurrence, ...]
    support_envelopes: tuple[CafeRootOccurrence, ...]


def _rotate_z_about(
    shape: cq.Shape,
    axis: tuple[float, float, float],
    progress: float,
) -> cq.Shape:
    ox, oy, oz = axis
    return shape.rotate(
        (ox, oy, oz),
        (ox, oy, oz + 1.0),
        90.0 * progress,
    )


def _rotate_root_z(shape: cq.Shape, progress: float) -> cq.Shape:
    return _rotate_z_about(shape, CAFE_ROOT_AXIS_MM, progress)


def _pose_table_attached(
    shape: cq.Shape,
    rotation_progress: float,
    return_progress: float,
) -> cq.Shape:
    """Apply the exact rigid transform used by the conserved right leaf."""

    return _rotate_z_about(
        shape,
        CAFE_TABLE_ROTATION_AXIS_MM,
        rotation_progress,
    ).translate(
        (
            CAFE_RETURN_TRAVEL_MM * return_progress,
            CAFE_INBOARD_RETURN_TRAVEL_MM * return_progress,
            0.0,
        )
    )


def _pose_table_attached_point(
    point: tuple[float, float, float],
    rotation_progress: float,
    return_progress: float,
    lift_mm: float = 0.0,
) -> tuple[float, float, float]:
    """Apply the conserved table transform to one packaging datum."""

    if not 0.0 <= rotation_progress <= 1.0:
        raise ValueError("Cafe point rotation progress must be in [0,1]")
    if not 0.0 <= return_progress <= 1.0:
        raise ValueError("Cafe point return progress must be in [0,1]")
    if return_progress > 0.0 and rotation_progress < 1.0:
        raise ValueError("Cafe point return is interlocked until the 90-degree stop")
    if lift_mm < 0.0:
        raise ValueError("Cafe clearance lift cannot be negative")
    ox, oy, _ = CAFE_TABLE_ROTATION_AXIS_MM
    x, y, z = point
    radians = math.radians(90.0 * rotation_progress)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    dx = x - ox
    dy = y - oy
    return (
        ox
        + dx * cosine
        - dy * sine
        + CAFE_RETURN_TRAVEL_MM * return_progress,
        oy
        + dx * sine
        + dy * cosine
        + CAFE_INBOARD_RETURN_TRAVEL_MM * return_progress,
        z + lift_mm,
    )


def _u_channel_y(
    *,
    length: float,
    outer_width: float,
    outer_height: float,
    inner_width: float,
    inner_height: float,
    center_y: float,
    outer_center_z: float,
    inner_center_z: float,
    radius: float,
) -> cq.Shape:
    """Open-bottom, open-ended U-channel whose local travel axis is Y."""

    outer = (
        cq.Workplane("XY")
        .box(outer_width, length, outer_height)
        .edges("|Y")
        .fillet(min(radius, outer_width * 0.2, outer_height * 0.2))
        .translate((CAFE_CLEARANCE_AXIS_X_MM, center_y, outer_center_z))
        .val()
    )
    inner = (
        cq.Workplane("XY")
        .box(inner_width, length + 2.0, inner_height)
        .edges("|Y")
        .fillet(
            min(
                max(radius - 1.0, 0.5),
                inner_width * 0.2,
                inner_height * 0.2,
            )
        )
        .translate((CAFE_CLEARANCE_AXIS_X_MM, center_y, inner_center_z))
        .val()
    )
    shape = outer.cut(inner).clean()
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Cafe telescopic cover is not one valid U-channel")
    return shape


@lru_cache(maxsize=1)
def fixed_root_housing_master() -> cq.Shape:
    """Drainable fixed shell wholly inside the right-armrest cavity."""

    outer = rounded_box((44.0, 39.0, 46.0), (-337.0, 338.75, 642.0), 7.0)
    cavity = rounded_box((36.0, 31.0, 38.0), (-337.0, 338.75, 644.0), 5.0)
    # A small occupant-side/bottom service mouth drains into the existing A05 bay;
    # it never opens through the outboard armrest skin.
    service_mouth = rounded_box(
        (24.0, 18.0, 12.0),
        (-337.0, 324.0, 621.0),
        3.0,
    )
    tongue_passage = rounded_box(
        (22.0, 38.0, 22.0),
        (-350.0, 330.0, 658.0),
        3.0,
    )
    internal_rail_mouth = rounded_box(
        (24.0, 27.0, 20.0),
        (-314.0, 339.0, 659.0),
        3.0,
    )
    top_service_mouth = rounded_box(
        (44.0, 35.0, 10.0),
        (-337.0, 338.75, 663.0),
        4.0,
    )
    shape = (
        outer.cut(cavity)
        .cut(service_mouth)
        .cut(tongue_passage)
        .cut(internal_rail_mouth)
        .cut(top_service_mouth)
        .clean()
    )
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Cafe fixed root housing is not one valid solid")
    return shape


@lru_cache(maxsize=1)
def fixed_yoke_bearing_carrier_master() -> cq.Shape:
    """Compact aluminium yoke and bearing outer race inside the cartridge."""

    axis_x, axis_y, _ = CAFE_ROOT_AXIS_MM
    # The cross beam reaches the fixed housing's two internal X walls.  The
    # previous 20 mm cosmetic bar floated 5.5 mm from its host and could not
    # carry table load into the armrest cassette.
    beam = rounded_box((36.0, 14.0, 8.0), (axis_x, axis_y, 650.0), 3.0)
    outer_race = (
        cq.Workplane("XY")
        .circle(10.0)
        .circle(8.0)
        .extrude(8.0)
        .translate((axis_x, axis_y, 646.0))
        .val()
    )
    inner_race_sweep = (
        cq.Workplane("XY")
        .circle(7.0)
        .extrude(14.0)
        .translate((axis_x, axis_y, 643.0))
        .val()
    )
    shape = beam.fuse(outer_race).cut(inner_race_sweep).clean()
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Cafe yoke/bearing carrier is not one valid solid")
    return shape


@lru_cache(maxsize=1)
def rotary_hub_master() -> cq.Shape:
    """Internal bearing inner race plus a compact rail pedestal."""

    axis_x, axis_y, _ = CAFE_ROOT_AXIS_MM
    inner_race = (
        cq.Workplane("XY")
        .circle(7.0)
        .circle(4.0)
        .extrude(7.0)
        .translate((axis_x, axis_y, 647.0))
        .val()
    )
    pedestal = (
        cq.Workplane("XY")
        .circle(6.0)
        .extrude(6.0)
        .translate((axis_x, axis_y, 654.0))
        .val()
    )
    shape = inner_race.fuse(pedestal).clean()
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Cafe rotary hub is not one valid solid")
    return shape


@lru_cache(maxsize=1)
def rotary_rail_master() -> cq.Shape:
    """Short internal torque key joining the hub to the final root neck.

    This is deliberately not labelled as an 80 mm linear rail.  In the final
    locked Cafe pose it bridges the five-millimetre dry span between the
    bearing hub and the table-attached root neck.  The inverse transform makes
    the returned shape the master for the existing rotary pose helper.
    """

    final_key = rounded_box(
        (5.0, 6.0, 6.0),
        (-345.5, 336.5, 657.0),
        1.2,
    )
    ox, oy, oz = CAFE_ROOT_AXIS_MM
    return final_key.rotate(
        (ox, oy, oz),
        (ox, oy, oz + 1.0),
        -90.0,
    )


@lru_cache(maxsize=1)
def moving_carriage_cover_master() -> cq.Shape:
    """Master pose of the table-attached smooth closed root neck.

    In the locked Cafe pose the conserved structural blade lies directly below
    the outer leaf (Y=272..338 mm, Z=690..692.5 mm).  Only its unavoidable
    Y=276..310 mm exterior gap span receives an eight-millimetre, softly
    radiused graphite envelope; the remaining blade and the narrow drop enter
    A05 behind the fixed weather skin.  The inverse rigid transform below
    expresses that same conserved occurrence in the unrotated clearance pose.
    """

    horizontal = rounded_box(
        (22.0, 66.0, 2.5),
        (-363.0, 305.0, 691.25),
        1.0,
    )
    visible_gap_envelope = rounded_box(
        (22.0, 34.0, 8.0),
        (-363.0, 293.0, 689.0),
        3.0,
    )
    # The fixed yoke ends at Z=654.  Stop the table-owned drop at that same
    # datum instead of passing 3.5 mm through the non-adjacent yoke beam.  The
    # shifted torque key occupies Z=654..660 and still joins the hub to this
    # drop laterally, so the five-piece load chain is conserved without two
    # solids claiming the same material.
    internal_drop = rounded_box(
        (11.0, 23.0, 38.5),
        (-353.5, 328.0, 673.25),
        3.0,
    )
    # A real 220 mm stainless spreader is embedded inside the outer rigid
    # half-leaf.  A short riser joins it to the smooth external root neck, so
    # the load does not pass through the cosmetic PC-ABS undertray.  All hinge
    # and bearing hardware remains on the armrest side of the small gland.
    internal_spreader = rounded_box(
        (22.0, 220.0, 4.0),
        (-364.0, 164.0, 697.0),
        2.0,
    )
    spreader_riser = rounded_box(
        (20.0, 12.0, 3.3),
        (-363.0, 276.0, 693.45),
        1.2,
    )
    final_shape = (
        horizontal.fuse(visible_gap_envelope)
        .fuse(internal_drop)
        .fuse(spreader_riser)
        .fuse(internal_spreader)
        .clean()
    )
    translated_back = final_shape.translate(
        (-CAFE_RETURN_TRAVEL_MM, -CAFE_INBOARD_RETURN_TRAVEL_MM, 0.0)
    )
    ox, oy, oz = CAFE_TABLE_ROTATION_AXIS_MM
    shape = translated_back.rotate(
        (ox, oy, oz),
        (ox, oy, oz + 1.0),
        -90.0,
    ).clean()
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Cafe moving carriage cover is not one valid solid")
    return shape


@lru_cache(maxsize=3)
def telescopic_cover_master(stage: int) -> cq.Shape:
    """Return one of three nested constant-volume internal guide covers."""

    profiles = {
        1: ((16.0, 10.0, 3.0), (12.0, 6.0, 5.0), 1.5),
        2: ((18.0, 12.0, 3.0), (17.0, 11.0, 5.0), 1.5),
        3: ((20.0, 14.0, 3.0), (19.0, 13.0, 5.0), 1.5),
    }
    if stage not in profiles:
        raise ValueError(f"Cafe rail-cover stage must be 1..3, got {stage}")
    outer_size, inner_size, radius = profiles[stage]
    center = (-337.0, 338.75, 667.0)
    outer = rounded_box(outer_size, center, radius)
    inner = rounded_box(inner_size, center, max(0.8, radius - 1.0))
    shape = outer.cut(inner).clean()
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError(f"Cafe internal guide cover stage {stage} is invalid")
    return shape


@lru_cache(maxsize=3)
def linear_guide_shoe_master(station: str) -> cq.Shape:
    """PEEK shoes retained inside the compact guide-cover cartridge."""

    if station == "left":
        return rounded_box((1.0, 6.0, 1.0), (-347.25, 338.75, 665.0), 0.35)
    if station == "right":
        return rounded_box((1.0, 6.0, 1.0), (-326.75, 338.75, 665.0), 0.35)
    if station == "top":
        return rounded_box((10.0, 6.0, 1.0), (-337.0, 338.75, 665.0), 0.35)
    raise ValueError(f"Unknown Cafe rail guide station {station!r}")


@lru_cache(maxsize=3)
def table_mount_shoe_master(station: int) -> cq.Shape:
    """One conserved compliant shoe between the tongue and outer leaf."""

    final_x_by_station = {1: -370.0, 2: -363.0, 3: -356.0}
    if station not in final_x_by_station:
        raise ValueError(f"Cafe table mount station must be 1..3, got {station}")
    final_shape = rounded_rect_prism(
        (6.0, 4.0),
        0.5,
        (final_x_by_station[station], 274.0, 692.75),
        1.0,
    )
    translated_back = final_shape.translate(
        (-CAFE_RETURN_TRAVEL_MM, -CAFE_INBOARD_RETURN_TRAVEL_MM, 0.0)
    )
    ox, oy, oz = CAFE_TABLE_ROTATION_AXIS_MM
    return translated_back.rotate(
        (ox, oy, oz),
        (ox, oy, oz + 1.0),
        -90.0,
    )


@lru_cache(maxsize=1)
def cafe_lock_release_paddle_master() -> cq.Shape:
    """Glove-operable mechanical release inside the armrest cartridge."""

    return rounded_box(
        (24.0, 4.0, 8.0),
        (-338.0, 326.5, 632.0),
        2.0,
    )


@lru_cache(maxsize=1)
def cafe_positive_lock_witness_master() -> cq.Shape:
    """Mechanical witness behind the sealed occupant-side service interface."""

    shape = (
        cq.Workplane("XZ")
        .circle(5.0)
        .circle(2.5)
        .extrude(4.0)
        .translate((-326.0, 338.0, 632.0))
        .val()
        .clean()
    )
    if shape.isNull() or not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Cafe positive-lock witness is not one valid ring")
    return shape


@lru_cache(maxsize=256)
def cafe_table_control_pose(
    rotation_progress: float,
    return_progress: float,
) -> tuple[CafeRootOccurrence, ...]:
    """Return the two conserved controls inside the fixed armrest cartridge."""

    if not 0.0 <= rotation_progress <= 1.0:
        raise ValueError("Cafe control rotation progress must be in [0,1]")
    if not 0.0 <= return_progress <= 1.0:
        raise ValueError("Cafe control return progress must be in [0,1]")
    if return_progress > 0.0 and rotation_progress < 1.0:
        raise ValueError(
            "Cafe control return is interlocked until rotation reaches 90 degrees"
        )
    occurrences = (
        (
            "A09_cafe_lock_release_paddle_right",
            "E6-A09-CAFE-LOCK-RELEASE-RIGHT",
            cafe_lock_release_paddle_master(),
            "armrest_internal_two_action_manual_release",
        ),
        (
            "A09_cafe_positive_lock_witness_right",
            "E6-A09-CAFE-POSITIVE-LOCK-WITNESS-RIGHT",
            cafe_positive_lock_witness_master(),
            "armrest_internal_mechanical_lock_witness",
        ),
    )
    return tuple(
        CafeRootOccurrence(
            name,
            physical_id,
            master,
            role,
            "fixed_internal_armrest_lock_cartridge",
        )
        for name, physical_id, master, role in occurrences
    )


@lru_cache(maxsize=1)
def cafe_table_control_final_occurrences() -> tuple[CafeRootOccurrence, ...]:
    return cafe_table_control_pose(1.0, 1.0)


@lru_cache(maxsize=256)
def cafe_root_motion_pose(
    rotation_progress: float,
    return_progress: float,
) -> tuple[CafeRootOccurrence, ...]:
    """Return the complete conserved internal root and table-tongue mechanism.

    The coordinated +80 mm X / -80 mm centre-side return is interlocked until
    the 90-degree table turn reaches its indexed stop.  All fixed, rotating,
    guide, lock and witness B-Reps remain within Y=316..361.5 mm; only the
    table-attached thin tongue follows the leaf across the inner-face gap.
    """

    if not 0.0 <= rotation_progress <= 1.0:
        raise ValueError("Cafe rotation progress must be in [0,1]")
    if not 0.0 <= return_progress <= 1.0:
        raise ValueError("Cafe return progress must be in [0,1]")
    if return_progress > 0.0 and rotation_progress < 1.0:
        raise ValueError("Cafe return is interlocked until rotation reaches 90 degrees")

    fixed = (
        (
            "A09_cafe_fixed_root_housing_right",
            "WC-A09-CAFE-FIXED-ROOT-HOUSING-RIGHT",
            fixed_root_housing_master(),
            "fixed_drainable_yoke_housing",
            "fixed_lift_root",
        ),
        (
            "A09_cafe_fixed_yoke_bearing_carrier_right",
            "WC-A09-CAFE-FIXED-YOKE-BEARING-CARRIER-RIGHT",
            fixed_yoke_bearing_carrier_master(),
            "fixed_aluminium_yoke_outer_race_and_lift_collar",
            "fixed_lift_root",
        ),
    )
    result = [CafeRootOccurrence(*item) for item in fixed]

    rotating = (
        (
            "A09_cafe_rotary_hub_right",
            "WC-A09-CAFE-ROTARY-HUB-RIGHT",
            rotary_hub_master(),
            "catalog_bearing_inner_race_and_rail_pedestal",
            "cafe_rotary_carriage",
        ),
        (
            "A09_cafe_rotary_linear_rail_right",
            "WC-A09-CAFE-ROTARY-LINEAR-RAIL-RIGHT",
            rotary_rail_master(),
            "internal_rotary_torque_key",
            "cafe_rotary_hub",
        ),
    )
    for name, physical_id, master, role, owner in rotating:
        result.append(
            CafeRootOccurrence(
                name,
                physical_id,
                _rotate_root_z(master, rotation_progress),
                role,
                owner,
            )
        )

    moving_cover = _pose_table_attached(
        moving_carriage_cover_master(),
        rotation_progress,
        return_progress,
    )
    result.append(
        CafeRootOccurrence(
            "A09_cafe_underleaf_motion_belly_right",
            "WC-A09-CAFE-TABLE-CARRIAGE-MONOCOQUE-RIGHT",
            moving_cover,
            "table_attached_closed_root_neck_and_internal_spreader",
            "cafe_right_outer_root_half_leaf",
        )
    )
    return tuple(result)


@lru_cache(maxsize=8)
def cafe_root_motion_poses(
    samples_per_leg: int = 21,
) -> tuple[tuple[CafeRootOccurrence, ...], ...]:
    """Sample the legal rotate-then-return path without duplicating the corner."""

    if samples_per_leg < 2:
        raise ValueError("Cafe root sweep needs at least two samples per leg")
    rotation = tuple(
        cafe_root_motion_pose(index / (samples_per_leg - 1), 0.0)
        for index in range(samples_per_leg)
    )
    returned = tuple(
        cafe_root_motion_pose(1.0, index / (samples_per_leg - 1))
        for index in range(1, samples_per_leg)
    )
    return (*rotation, *returned)


def cafe_transient_support_envelope(
    rotation_progress: float,
    return_progress: float,
    lift_mm: float,
) -> CafeRootOccurrence:
    """Return the connected guided-support packaging envelope for one pose.

    The fixed rotary joint stays below the A05 lid.  A production mechanism may
    realise this reserve with nested tubes, a rolling carriage or equivalent;
    this layout-level solid only proves that a connected load path can occupy
    the released sealed passage and clear the exterior controls without moving
    the final table or control datums.
    """

    if lift_mm < 0.0:
        raise ValueError("Cafe support lift cannot be negative")
    centre_x, centre_y = CAFE_SUPPORT_PASSAGE_CENTRE_XY_MM
    arm_z = CAFE_SUPPORT_ARM_Z_MM + lift_mm
    riser_height = arm_z - CAFE_SUPPORT_RISER_LOWER_Z_MM
    if riser_height <= 0.0:
        raise ValueError("Cafe support riser height must remain positive")
    riser = rounded_box(
        (
            CAFE_SUPPORT_RISER_SECTION_MM[0],
            CAFE_SUPPORT_RISER_SECTION_MM[1],
            riser_height,
        ),
        (
            centre_x,
            centre_y,
            CAFE_SUPPORT_RISER_LOWER_Z_MM + riser_height / 2.0,
        ),
        3.0,
    )
    start = cq.Vector(centre_x, centre_y, arm_z)
    end_xyz = _pose_table_attached_point(
        CAFE_SUPPORT_MASTER_TABLE_ANCHOR_MM,
        rotation_progress,
        return_progress,
        lift_mm,
    )
    end = cq.Vector(*end_xyz)
    vector = end - start
    length = float(vector.Length)
    if length <= 2.0 * CAFE_SUPPORT_ARM_RADIUS_MM:
        raise ValueError("Cafe support arm lost its telescoping span")
    direction = vector.normalized()
    # Trim one radius at each end; the overlapping riser and table-root sockets
    # provide the real end captures without creating a protruding ball joint.
    arm = cq.Solid.makeCylinder(
        CAFE_SUPPORT_ARM_RADIUS_MM,
        length - 2.0 * CAFE_SUPPORT_ARM_RADIUS_MM,
        start + direction.multiply(CAFE_SUPPORT_ARM_RADIUS_MM),
        direction,
    )
    connector = (
        riser.fuse(arm)
        .fuse(
            cq.Solid.makeSphere(
                CAFE_SUPPORT_ARM_RADIUS_MM,
                start,
            )
        )
        .clean()
    )
    if connector.isNull() or not connector.isValid():
        raise ValueError("Cafe transient support envelope is invalid")
    return CafeRootOccurrence(
        "A09_cafe_transient_guided_support_envelope_right",
        "WC-A09-CAFE-GUIDED-SUPPORT-ENVELOPE-RIGHT",
        connector,
        "parameterised_guided_support_packaging_not_supplier_part",
        "fixed_joint_inside_A05_with_smooth_transient_tongue",
    )


def cafe_clearance_deployment_frames(
    samples_per_leg: int = 21,
) -> tuple[CafeDeploymentFrame, ...]:
    """Return the legal lift/rotate/return/lower post-extraction path.

    The outward lid remains at 105 degrees while the unchanged table and root
    belly rise.  After the lid has closed at full clearance height, the smooth
    support tongue docks through the sealed inner gland; rotation and return
    then occur above the fixed pod/joystick sweep before the same rigid bodies
    lower into their unchanged final Cafe B-Reps.
    """

    if samples_per_leg < 2:
        raise ValueError("Cafe clearance motion needs at least two samples per leg")

    def frame(
        phase: str,
        phase_index: int,
        progress: float,
        rotation: float,
        returned: float,
        lift: float,
        lid_angle: float,
        support_docked: bool,
    ) -> CafeDeploymentFrame:
        leaves = tuple(
            MechanismOccurrence(
                occurrence.name,
                occurrence.physical_occurrence_id,
                occurrence.shape.translate((0.0, 0.0, lift)),
                occurrence.role,
            )
            for occurrence in cafe_half_leaf_pair(rotation, returned)
        )
        roots = tuple(
            CafeRootOccurrence(
                occurrence.name,
                occurrence.physical_occurrence_id,
                (
                    occurrence.shape.translate((0.0, 0.0, lift))
                    if occurrence.motion_owner
                    == "cafe_right_outer_root_half_leaf"
                    else occurrence.shape
                ),
                occurrence.role,
                occurrence.motion_owner,
            )
            for occurrence in cafe_root_motion_pose(rotation, returned)
        )
        supports = (
            (
                cafe_transient_support_envelope(
                    rotation,
                    returned,
                    lift,
                ),
            )
            if support_docked
            else ()
        )
        return CafeDeploymentFrame(
            phase,
            phase_index,
            progress,
            rotation,
            returned,
            lift,
            lid_angle,
            support_docked,
            leaves,
            roots,
            supports,
        )

    denominator = samples_per_leg - 1
    frames: list[CafeDeploymentFrame] = []
    for index in range(samples_per_leg):
        progress = index / denominator
        frames.append(
            frame(
                "raise_with_lid_open",
                index,
                progress,
                0.0,
                0.0,
                CAFE_ROTATION_CLEARANCE_LIFT_MM * progress,
                105.0,
                False,
            )
        )
    # The lid-close sweep is validated independently at the stationary raised
    # pose.  This exact docking frame begins only after double-latch confirmation.
    frames.append(
        frame(
            "dock_support_after_lid_close",
            0,
            1.0,
            0.0,
            0.0,
            CAFE_ROTATION_CLEARANCE_LIFT_MM,
            0.0,
            True,
        )
    )
    for index in range(1, samples_per_leg):
        progress = index / denominator
        frames.append(
            frame(
                "rotate_at_clearance_height",
                index,
                progress,
                progress,
                0.0,
                CAFE_ROTATION_CLEARANCE_LIFT_MM,
                0.0,
                True,
            )
        )
    for index in range(1, samples_per_leg):
        progress = index / denominator
        frames.append(
            frame(
                "return_inboard_at_clearance_height",
                index,
                progress,
                1.0,
                progress,
                CAFE_ROTATION_CLEARANCE_LIFT_MM,
                0.0,
                True,
            )
        )
    for index in range(1, samples_per_leg):
        progress = index / denominator
        frames.append(
            frame(
                "lower_into_final_root_lock",
                index,
                progress,
                1.0,
                1.0,
                CAFE_ROTATION_CLEARANCE_LIFT_MM * (1.0 - progress),
                0.0,
                True,
            )
        )
    return tuple(frames)


@lru_cache(maxsize=1)
def cafe_root_final_occurrences() -> tuple[CafeRootOccurrence, ...]:
    return cafe_root_motion_pose(1.0, 1.0)


__all__ = [
    "CAFE_PADDLE_OUTER_UNDERSIDE_Y_MM",
    "CAFE_CONTROL_TOP_Z_MM",
    "CAFE_ROTATION_CLEARANCE_LIFT_MM",
    "CAFE_SUPPORT_ARM_RADIUS_MM",
    "CAFE_SUPPORT_PASSAGE_CENTRE_XY_MM",
    "CAFE_SUPPORT_RISER_SECTION_MM",
    "CAFE_WITNESS_OUTER_UNDERSIDE_Y_MM",
    "CAFE_COVER_PICKUP_DEAD_TRAVEL_MM",
    "CAFE_FINAL_RAIL_CAPTURE_MM",
    "CAFE_INTERNAL_FOLD_HARD_RETREAT_MM",
    "CAFE_RETURN_TRAVEL_MM",
    "CAFE_ROOT_AXIS_MM",
    "CAFE_TABLE_ROTATION_AXIS_MM",
    "CAFE_INTERNAL_CAVITY_Y_MIN_MM",
    "CAFE_INTERNAL_CAVITY_Y_MAX_MM",
    "CafeRootOccurrence",
    "CafeDeploymentFrame",
    "cafe_clearance_deployment_frames",
    "cafe_root_final_occurrences",
    "cafe_root_motion_pose",
    "cafe_root_motion_poses",
    "cafe_lock_release_paddle_master",
    "cafe_positive_lock_witness_master",
    "cafe_table_control_final_occurrences",
    "cafe_table_control_pose",
    "cafe_transient_support_envelope",
    "fixed_root_housing_master",
    "fixed_yoke_bearing_carrier_master",
    "linear_guide_shoe_master",
    "moving_carriage_cover_master",
    "rotary_hub_master",
    "rotary_rail_master",
    "table_mount_shoe_master",
    "telescopic_cover_master",
]
