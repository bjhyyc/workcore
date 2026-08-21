"""First-principles A05/A09 lid, packaging and table-motion contract.

This module is deliberately independent from the four final presentation
poses.  It models the same two rigid half-leaves through stow, extraction,
unfolding and the Cafe rotation sequence.  It also defines the only permitted
user sequence for the fixed armrest body and outward-opening top lid.

Coordinates (mm): -X front, +X rear, +Y right, -Y left, +Z up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import cadquery as cq

try:
    from .skin_common import rounded_box, rounded_rect_prism
except ImportError:
    from skin_common import rounded_box, rounded_rect_prism  # type: ignore[no-redef]


HALF_LEAF_LENGTH_MM = 430.0
HALF_LEAF_WIDTH_MM = 134.5
HALF_LEAF_THICKNESS_MM = 12.0
FOLD_SEAM_MM = 1.0
HALF_LEAF_CENTRE_OFFSET_MM = HALF_LEAF_WIDTH_MM / 2.0 + FOLD_SEAM_MM / 2.0
# No rigid half-leaf is cut around the right-armrest controls.  The deployed
# table is indexed wholly toward the occupant/product centre from the armrest
# inner face: Focus already
# stops at Y=+276 mm, and Cafe now returns to the same +276 mm outer limit.
# This keeps all four real veneer fields rectangular/book-matchable and avoids
# an unmotivated mirrored bite in the control-free left Focus leaf.
# Both mechanical centre-lock releases must remain on uninterrupted inner-leaf
# material.  The former rear station at X=-255 mm sat inside the new
# X=-320..-60 mm operator-hand bay and was therefore cut out of the canonical
# B-Rep.  X=-360 mm retains an 11 mm minimum plan-land outside the 58 mm-wide
# release pocket while keeping the two stations comfortably separated.
FOCUS_LOCK_STATIONS_X_MM = (-555.0, -360.0)

STOW_AXIS_X_MM = -115.0
STOW_AXIS_ABS_Y_MM = 343.0
# The first physically modelled arrangement at Z=535.5 cleared the moving
# left display plinth by only 0.0817 mm.  That is a kernel non-intersection,
# not a manufacturable clearance.  Lower the complete, unchanged two-leaf
# occurrence by 10 mm so its material envelope tops at Z=660.5 and retains a
# real tolerance reserve below every lid-carried HMI hard part.
STOW_AXIS_Z_MM = 525.5
FOCUS_AXIS_X_MM = -405.0
FOCUS_AXIS_ABS_Y_MM = 141.0
DEPLOYED_LEAF_CENTRE_Z_MM = 699.0
CAFE_CLEARANCE_AXIS_X_MM = -430.0
CAFE_FINAL_AXIS_X_MM = -350.0
# After the ninety-degree Cafe turn the same coordinated 80 mm return also
# indexes the complete leaf toward the occupant/product centre.  Its final Y
# centre is +61 mm, so the 430 mm span ends at +276 mm: 34 mm on the centre
# side of the right armrest inner face (Y=+310 mm) and 5 mm clear of the
# verified operating-hand envelope.
CAFE_FINAL_AXIS_Y_MM = 61.0
CAFE_INBOARD_RETURN_TRAVEL_MM = CAFE_FINAL_AXIS_Y_MM - FOCUS_AXIS_ABS_Y_MM

NOMINAL_FOLDED_ENVELOPE_MM = (430.0, 30.0, 139.0)
MAXIMUM_FOLDED_MATERIAL_ENVELOPE_MM = (432.0, 32.0, 141.0)
LID_OPEN_ANGLE_DEG = 105.0
LID_HINGE_ABS_Y_MM = 367.5
LID_HINGE_Z_MM = 676.0

# The lid electronics cross the moving interface through a controlled
# dynamic-flex cassette at the rear 40 mm of the table bay.  A round cable
# service loop cannot fit there: a nominal 24 mm cable inside-bend radius plus
# cable diameter is wider than the 45.5 mm internal armrest cavity, and the
# former 64 mm torus was both outside the armrest and topologically closed.
# A 0.6 mm high-flex FPC is the production-feasible expression.  Its full
# 6 mm conductor width remains rearward of the table pack's X=100 mm material
# limit throughout extraction, while a rolling U-bend keeps its centreline
# length constant as the lid moves.
LID_FLEX_CENTRE_X_MM = 108.0
LID_FLEX_WIDTH_MM = 6.0
LID_FLEX_THICKNESS_MM = 0.6
LID_FLEX_ROLLING_RADIUS_MM = 10.0
LID_FLEX_MINIMUM_INSIDE_RADIUS_MM = 8.0
LID_FLEX_FIXED_RADIAL_MM = 330.0
LID_FLEX_MOVING_TRACK_RADIAL_MM = 350.0
LID_FLEX_FIXED_ENDPOINT_Z_MM = 562.0
LID_FLEX_TOP_GUIDE_Z_MM = 610.0
LID_FLEX_LOOP_REFERENCE_Z_MM = 510.0
LID_FLEX_MOVING_ENDPOINT_CLOSED_RADIAL_MM = 351.0
LID_FLEX_MOVING_ENDPOINT_CLOSED_Z_MM = 668.0
LID_FLEX_BEZIER_START_HANDLE_MM = 10.0
LID_FLEX_BEZIER_END_HANDLE_MM = 20.0
LID_FLEX_MOVING_TANGENT_CLOSED_DEG = 120.0
# The final 1.5 mm of copper centreline is captive in the lid-side connector
# and its strain-relief mouth.  Model the free span from a physically trimmed
# centreline instead of subtracting two tangent solids in the release gate;
# the latter is numerically asymmetric in OCC at one mirrored 74-degree pose.
LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM = 1.5
LID_FLEX_MOVING_CONNECTOR_ENTRY_SETBACK_MM = 0.1
LID_FLEX_MOVING_CAPTURE_SECTION_MM = (6.4, 1.0)
LID_FLEX_MOVING_RELIEF_SECTION_MM = (8.0, 2.0)
LID_FLEX_MOVING_CAPTURE_INSERTION_MM = 1.0

TABLE_ACCESS_SEQUENCE = (
    "traction_disabled_and_parked",
    "clear_lid_payload_and_deenergise_table_motion",
    "release_double_latch",
    "flip_lid_outward_to_105_deg_stop",
    "lift_same_folded_table_pack_through_top",
    "move_folded_pack_forward_clear_of_lid",
    "unfold_table_clear_of_open_lid",
    "raise_table_90_mm_above_fixed_control_sweep",
    "close_and_confirm_double_latch",
    "extend_concealed_support_through_sealed_inner_gland",
    "rotate_table_90_deg_at_clearance_height",
    "return_table_inboard_at_clearance_height",
    "lower_and_confirm_final_root_lock",
)


@dataclass(frozen=True)
class MechanismOccurrence:
    name: str
    physical_occurrence_id: str
    shape: cq.Shape
    role: str


@dataclass(frozen=True)
class SequenceContext:
    parked: bool
    traction_disabled: bool
    phone_present: bool = False
    qi_energised: bool = False
    drive_pod_present: bool = True
    sweep_zone_clear: bool = True
    lid_double_latch_confirmed: bool = True


@dataclass(frozen=True)
class LidHarnessPose:
    """One physically connected dynamic-flex occurrence at a lid angle.

    ``flex_circuit`` is one open-ended swept solid, not a closed torus.  Its
    first end is held by ``fixed_connector`` and never moves; its other end
    terminates inside ``moving_connector``, which is the exact rigid transform
    of the connector mounted under the lid.  The rolling-loop Z datum changes
    to preserve the same centreline length without stretching the copper.
    """

    side: int
    angle_deg: float
    flex_circuit: cq.Shape
    free_flex_span: cq.Shape
    centerline: cq.Wire
    fixed_connector: cq.Shape
    moving_connector: cq.Shape
    moving_connector_capture: cq.Shape
    fixed_endpoint_mm: tuple[float, float, float]
    moving_endpoint_mm: tuple[float, float, float]
    moving_tangent: tuple[float, float, float]
    centerline_length_mm: float
    rolling_loop_axis_z_mm: float
    minimum_inside_bend_radius_mm: float


def _rotate_x(
    shape: cq.Shape,
    origin: tuple[float, float, float],
    degrees: float,
) -> cq.Shape:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox + 1.0, oy, oz), degrees)


def _rotate_z(
    shape: cq.Shape,
    origin: tuple[float, float, float],
    degrees: float,
) -> cq.Shape:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox, oy, oz + 1.0), degrees)


@lru_cache(maxsize=1)
def canonical_half_leaf() -> cq.Shape:
    """Return the one production half-leaf BRep used in every pose."""

    return rounded_rect_prism(
        (HALF_LEAF_LENGTH_MM, HALF_LEAF_WIDTH_MM),
        HALF_LEAF_THICKNESS_MM,
        (0.0, 0.0, 0.0),
        8.0,
    )


def _half_id(side: int, half: str) -> str:
    side_name = "RIGHT" if side > 0 else "LEFT"
    return f"WC-A09-TABLE-HALF-LEAF-{side_name}-{half.upper()}"


def _axis(side: int, x: float, z: float, abs_y: float) -> tuple[float, float, float]:
    if side not in {-1, 1}:
        raise ValueError(f"Table side must be -1 or +1, got {side}")
    return (x, side * abs_y, z)


def unfolded_half_leaf(
    side: int,
    half: str,
    *,
    axis_x: float = FOCUS_AXIS_X_MM,
    axis_abs_y: float = FOCUS_AXIS_ABS_Y_MM,
    axis_z: float = DEPLOYED_LEAF_CENTRE_Z_MM,
) -> MechanismOccurrence:
    """Return one flat half-leaf at a Focus-style deployment axis."""

    if half not in {"inner", "outer"}:
        raise ValueError(f"Half must be 'inner' or 'outer', got {half!r}")
    axis_y = side * axis_abs_y
    offset = (
        -side * HALF_LEAF_CENTRE_OFFSET_MM
        if half == "inner"
        else side * HALF_LEAF_CENTRE_OFFSET_MM
    )
    side_name = "right" if side > 0 else "left"
    shape = canonical_half_leaf().translate((axis_x, axis_y + offset, axis_z))
    return MechanismOccurrence(
        name=f"A09_table_half_leaf_{side_name}_{half}",
        physical_occurrence_id=_half_id(side, half),
        shape=shape,
        role="rigid_half_leaf",
    )


def folded_half_leaf_pair(
    side: int,
    *,
    axis_x: float = STOW_AXIS_X_MM,
    axis_abs_y: float = STOW_AXIS_ABS_Y_MM,
    axis_z: float = STOW_AXIS_Z_MM,
) -> tuple[MechanismOccurrence, MechanismOccurrence]:
    """Return the same two half-leaves vertically folded with 1.5 mm anti-rub gap."""

    return unfold_motion_pose(
        side,
        0.0,
        axis_x=axis_x,
        axis_abs_y=axis_abs_y,
        axis_z=axis_z,
    )


def unfold_motion_pose(
    side: int,
    progress: float,
    *,
    axis_x: float = FOCUS_AXIS_X_MM,
    axis_abs_y: float = FOCUS_AXIS_ABS_Y_MM,
    axis_z: float = DEPLOYED_LEAF_CENTRE_Z_MM,
) -> tuple[MechanismOccurrence, MechanismOccurrence]:
    """Pose both half-leaves from vertical pack (0) to flat table (1)."""

    if not 0.0 <= progress <= 1.0:
        raise ValueError(f"Unfold progress must be in [0,1], got {progress}")
    axis = _axis(side, axis_x, axis_z, axis_abs_y)
    # The compact dual-axis hinge cams the two rigid leaves another 2 mm apart
    # around mid-stroke.  A linear collapse of the folded 1.5 mm anti-rub gap
    # makes the twelve-millimetre solids cross at about 45 degrees even though
    # both endpoints are clear; the sinusoidal cam term is therefore a physical
    # motion requirement, not animation easing.
    stack_offset = (
        6.75 * (1.0 - progress)
        + 2.0 * math.sin(math.pi * progress)
    )
    posed: list[MechanismOccurrence] = []
    for half in ("inner", "outer"):
        flat = unfolded_half_leaf(
            side,
            half,
            axis_x=axis_x,
            axis_abs_y=axis_abs_y,
            axis_z=axis_z,
        )
        folded_angle = -90.0 * side if half == "inner" else 90.0 * side
        shape = _rotate_x(flat.shape, axis, folded_angle * (1.0 - progress))
        y_shift = (
            -side * stack_offset if half == "inner" else side * stack_offset
        )
        shape = shape.translate((0.0, y_shift, 0.0))
        posed.append(
            MechanismOccurrence(
                name=flat.name,
                physical_occurrence_id=flat.physical_occurrence_id,
                shape=shape,
                role=flat.role,
            )
        )
    return posed[0], posed[1]


def folded_pack_hardware(
    side: int,
    *,
    axis_x: float = STOW_AXIS_X_MM,
    axis_abs_y: float = STOW_AXIS_ABS_Y_MM,
    axis_z: float = STOW_AXIS_Z_MM,
) -> tuple[MechanismOccurrence, ...]:
    """Return non-intersecting cam-hinge hardware inside the folded pack.

    The former proxy used one 8 mm diameter, 432 mm long cylinder on the
    virtual fold axis.  That cylinder occupied about 3363 mm3 of *each* rigid
    leaf, so it was not a hinge at all.  The production-intent envelope uses
    two 4 mm cam pins below the leaf material and a one-millimetre central
    latch spine.  The pins are deliberately shorter than the 430 mm leaves;
    the leaves, not hidden hardware, therefore define the nominal length.
    """

    axis = _axis(side, axis_x, axis_z, axis_abs_y)
    side_name = "right" if side > 0 else "left"
    hardware: list[MechanismOccurrence] = []
    for pin_index, y_offset in enumerate((-4.5, 4.5), start=1):
        pin = (
            cq.Workplane("YZ")
            .circle(2.0)
            .extrude(210.0, both=True)
            .translate((axis_x, axis[1] + y_offset, axis_z - 2.0))
            .val()
        )
        hardware.append(
            MechanismOccurrence(
                f"A09_table_fold_cam_pin_{side_name}_{pin_index}",
                (
                    f"WC-A09-TABLE-FOLD-CAM-PIN-"
                    f"{side_name.upper()}-{pin_index}"
                ),
                pin,
                "concealed_dual_axis_translating_cam_pin",
            )
        )
    latch_spine = rounded_box(
        (420.0, 1.0, 4.0),
        (axis_x, axis[1], axis_z - 2.0),
        0.4,
    )
    hardware.append(
        MechanismOccurrence(
            f"A09_table_fold_latch_spine_{side_name}",
            f"WC-A09-TABLE-FOLD-LATCH-SPINE-{side_name.upper()}",
            latch_spine,
            "central_folded_pack_positive_latch_spine",
        )
    )
    for station, offset in enumerate((-14.0, 14.0), start=1):
        guide = rounded_box(
            (420.0, 2.0, 6.0),
            (axis_x, axis[1] + offset, axis_z + 64.5),
            1.0,
        )
        hardware.append(
            MechanismOccurrence(
                f"A09_table_anti_rub_guide_{side_name}_{station}",
                f"WC-A09-TABLE-ANTI-RUB-GUIDE-{side_name.upper()}-{station}",
                guide,
                "replaceable_anti_rub_guide",
            )
        )
    return tuple(hardware)


def folded_pack_occurrences(side: int) -> tuple[MechanismOccurrence, ...]:
    return (*folded_half_leaf_pair(side), *folded_pack_hardware(side))


def cafe_half_leaf_pair(progress_rotation: float = 1.0, progress_return: float = 1.0) -> tuple[MechanismOccurrence, ...]:
    """Return the right leaf through its 90-degree Cafe turn and indexed return.

    The post-rotation return is one coordinated X/Y carriage move: +80 mm in X
    preserves the original V8 Cafe station while -80 mm in Y brings the complete
    tabletop to the same +276 mm occupant-side limit used by Focus.  Return remains
    interlocked until the ninety-degree turn is complete.
    """

    if not 0.0 <= progress_rotation <= 1.0 or not 0.0 <= progress_return <= 1.0:
        raise ValueError("Cafe rotation and return progress must each be in [0,1]")
    axis = (CAFE_CLEARANCE_AXIS_X_MM, FOCUS_AXIS_ABS_Y_MM, DEPLOYED_LEAF_CENTRE_Z_MM)
    x_return = (CAFE_FINAL_AXIS_X_MM - CAFE_CLEARANCE_AXIS_X_MM) * progress_return
    y_return = CAFE_INBOARD_RETURN_TRAVEL_MM * progress_return
    result: list[MechanismOccurrence] = []
    for half in ("inner", "outer"):
        occurrence = unfolded_half_leaf(
            1,
            half,
            axis_x=CAFE_CLEARANCE_AXIS_X_MM,
        )
        shape = _rotate_z(occurrence.shape, axis, 90.0 * progress_rotation)
        shape = shape.translate((x_return, y_return, 0.0))
        result.append(
            MechanismOccurrence(
                occurrence.name,
                occurrence.physical_occurrence_id,
                shape,
                occurrence.role,
            )
        )
    return tuple(result)


def extraction_axis_samples(
    side: int,
    samples_per_leg: int = 21,
    *,
    target_axis_x: float = FOCUS_AXIS_X_MM,
) -> tuple[tuple[float, float, float], ...]:
    """Return the captive three-leg extraction path.

    A direct diagonal from the armrest bay to the deployed fold axis crossed
    the seated torso keep-out by about 113124 mm3.  The physical carriage must
    therefore execute three positively interlocked orthogonal moves: lift
    clear of the top aperture, travel forward while it remains outside the
    occupant's lateral envelope, then translate inward only after the complete
    430 mm pack is ahead of the torso.  With 21 samples per leg this produces
    61 unique poses, including both corner poses exactly once.
    """

    if samples_per_leg < 2:
        raise ValueError("Each extraction leg needs at least two samples")
    start = _axis(side, STOW_AXIS_X_MM, STOW_AXIS_Z_MM, STOW_AXIS_ABS_Y_MM)
    high = _axis(side, STOW_AXIS_X_MM, DEPLOYED_LEAF_CENTRE_Z_MM, STOW_AXIS_ABS_Y_MM)
    forward_clear = _axis(
        side,
        target_axis_x,
        DEPLOYED_LEAF_CENTRE_Z_MM,
        STOW_AXIS_ABS_Y_MM,
    )
    target = _axis(
        side,
        target_axis_x,
        DEPLOYED_LEAF_CENTRE_Z_MM,
        FOCUS_AXIS_ABS_Y_MM,
    )

    def lerp(a: tuple[float, float, float], b: tuple[float, float, float], t: float) -> tuple[float, float, float]:
        return tuple(x + (y - x) * t for x, y in zip(a, b))  # type: ignore[return-value]

    lift = tuple(lerp(start, high, index / (samples_per_leg - 1)) for index in range(samples_per_leg))
    forward = tuple(
        lerp(high, forward_clear, index / (samples_per_leg - 1))
        for index in range(1, samples_per_leg)
    )
    inward = tuple(
        lerp(forward_clear, target, index / (samples_per_leg - 1))
        for index in range(1, samples_per_leg)
    )
    return (*lift, *forward, *inward)


def extraction_motion_occurrences(
    side: int,
    samples_per_leg: int = 21,
    *,
    target_axis_x: float = FOCUS_AXIS_X_MM,
) -> tuple[tuple[MechanismOccurrence, ...], ...]:
    poses = []
    for x, y, z in extraction_axis_samples(
        side,
        samples_per_leg,
        target_axis_x=target_axis_x,
    ):
        poses.append(
            (
                *unfold_motion_pose(
                    side,
                    0.0,
                    axis_x=x,
                    axis_abs_y=abs(y),
                    axis_z=z,
                ),
                *folded_pack_hardware(
                    side,
                    axis_x=x,
                    axis_abs_y=abs(y),
                    axis_z=z,
                ),
            )
        )
    return tuple(poses)


def pose_lid_shape(closed_shape: cq.Shape, side: int, angle_deg: float) -> cq.Shape:
    """Rotate a complete lid/HMI occurrence outward about the outer X axis."""

    if side not in {-1, 1}:
        raise ValueError(f"Lid side must be -1 or +1, got {side}")
    if not 0.0 <= angle_deg <= LID_OPEN_ANGLE_DEG:
        raise ValueError(f"Lid angle must be in [0,{LID_OPEN_ANGLE_DEG}], got {angle_deg}")
    origin = (0.0, side * LID_HINGE_ABS_Y_MM, LID_HINGE_Z_MM)
    signed_angle = -side * angle_deg
    return _rotate_x(closed_shape, origin, signed_angle)


def lid_sweep(closed_shape: cq.Shape, side: int, samples: int = 22) -> tuple[cq.Shape, ...]:
    if samples < 2:
        raise ValueError("Lid sweep needs at least two samples")
    return tuple(
        pose_lid_shape(closed_shape, side, LID_OPEN_ANGLE_DEG * index / (samples - 1))
        for index in range(samples)
    )


def _harness_radial_point(
    side: int,
    radial_mm: float,
    z_mm: float,
) -> cq.Vector:
    return cq.Vector(LID_FLEX_CENTRE_X_MM, side * radial_mm, z_mm)


def _harness_moving_endpoint_rz(
    angle_deg: float,
) -> tuple[float, float]:
    """Return the lid-fixed flex endpoint in outward-radial/Z coordinates."""

    radians = math.radians(angle_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    radial_delta = (
        LID_FLEX_MOVING_ENDPOINT_CLOSED_RADIAL_MM
        - LID_HINGE_ABS_Y_MM
    )
    z_delta = LID_FLEX_MOVING_ENDPOINT_CLOSED_Z_MM - LID_HINGE_Z_MM
    # Both left and right lids share this radial-frame transform.  The global
    # X-axis rotations have opposite signs, but outward radial is side*Y.
    return (
        LID_HINGE_ABS_Y_MM
        + radial_delta * cosine
        + z_delta * sine,
        LID_HINGE_Z_MM
        - radial_delta * sine
        + z_delta * cosine,
    )


def _harness_moving_tangent_rz(
    angle_deg: float,
) -> tuple[float, float]:
    """Return the flex tangent that is rigidly fixed in the moving lid."""

    tangent_radians = math.radians(LID_FLEX_MOVING_TANGENT_CLOSED_DEG)
    closed_radial = math.cos(tangent_radians)
    closed_z = math.sin(tangent_radians)
    radians = math.radians(angle_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        closed_radial * cosine + closed_z * sine,
        -closed_radial * sine + closed_z * cosine,
    )


def _harness_bezier_controls_rz(
    angle_deg: float,
) -> tuple[tuple[float, float], ...]:
    moving_radial, moving_z = _harness_moving_endpoint_rz(angle_deg)
    tangent_radial, tangent_z = _harness_moving_tangent_rz(angle_deg)
    return (
        (LID_FLEX_MOVING_TRACK_RADIAL_MM, LID_FLEX_TOP_GUIDE_Z_MM),
        (
            LID_FLEX_MOVING_TRACK_RADIAL_MM,
            LID_FLEX_TOP_GUIDE_Z_MM + LID_FLEX_BEZIER_START_HANDLE_MM,
        ),
        (
            moving_radial
            - LID_FLEX_BEZIER_END_HANDLE_MM * tangent_radial,
            moving_z - LID_FLEX_BEZIER_END_HANDLE_MM * tangent_z,
        ),
        (moving_radial, moving_z),
    )


def _harness_bezier_edge(side: int, angle_deg: float) -> cq.Edge:
    controls = [
        _harness_radial_point(side, radial, z)
        for radial, z in _harness_bezier_controls_rz(angle_deg)
    ]
    return cq.Edge.makeBezier(controls)


@lru_cache(maxsize=1)
def _closed_harness_bezier_length_mm() -> float:
    return float(_harness_bezier_edge(1, 0.0).Length())


def _harness_bezier_minimum_centerline_radius_mm(
    angle_deg: float,
    samples: int = 801,
) -> float:
    """Numerically bound the cubic's minimum curvature radius."""

    if samples < 3:
        raise ValueError("Harness curvature audit needs at least three samples")
    controls = _harness_bezier_controls_rz(angle_deg)
    p0, p1, p2, p3 = controls
    minimum = float("inf")
    for index in range(samples):
        parameter = index / (samples - 1)
        complement = 1.0 - parameter
        first = (
            3.0 * complement * complement * (p1[0] - p0[0])
            + 6.0 * complement * parameter * (p2[0] - p1[0])
            + 3.0 * parameter * parameter * (p3[0] - p2[0]),
            3.0 * complement * complement * (p1[1] - p0[1])
            + 6.0 * complement * parameter * (p2[1] - p1[1])
            + 3.0 * parameter * parameter * (p3[1] - p2[1]),
        )
        second = (
            6.0 * complement * (p2[0] - 2.0 * p1[0] + p0[0])
            + 6.0 * parameter * (p3[0] - 2.0 * p2[0] + p1[0]),
            6.0 * complement * (p2[1] - 2.0 * p1[1] + p0[1])
            + 6.0 * parameter * (p3[1] - 2.0 * p2[1] + p1[1]),
        )
        speed = math.hypot(first[0], first[1])
        cross = abs(first[0] * second[1] - first[1] * second[0])
        if cross > 1.0e-12:
            minimum = min(minimum, speed**3 / cross)
    return minimum


@lru_cache(maxsize=2)
def _fixed_harness_connector(side: int) -> cq.Shape:
    if side not in {-1, 1}:
        raise ValueError(f"Harness side must be -1 or +1, got {side}")
    # The rear tab stops 0.2 mm short of the internal shell for a controlled
    # structural-adhesive bondline.  Its radial position stays outside the
    # folded pack even though it reaches rearward to the fixed wall.
    connector = rounded_box(
        (8.0, 14.0, 10.0),
        (LID_FLEX_CENTRE_X_MM, side * 327.0, 563.0),
        2.0,
    )
    mount_tab = rounded_box(
        (8.0, 4.0, 6.0),
        (114.0, side * 322.0, 563.0),
        1.0,
    )
    return connector.fuse(mount_tab)


@lru_cache(maxsize=2)
def _closed_moving_harness_capture(side: int, *, outer: bool) -> cq.Shape:
    if side not in {-1, 1}:
        raise ValueError(f"Harness side must be -1 or +1, got {side}")
    tangent_radial, tangent_z = _harness_moving_tangent_rz(0.0)
    tangent = cq.Vector(0.0, side * tangent_radial, tangent_z)
    endpoint = cq.Vector(
        LID_FLEX_CENTRE_X_MM,
        side * LID_FLEX_MOVING_ENDPOINT_CLOSED_RADIAL_MM,
        LID_FLEX_MOVING_ENDPOINT_CLOSED_Z_MM,
    )
    start = endpoint - tangent.multiply(
        LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM
    )
    section = (
        LID_FLEX_MOVING_RELIEF_SECTION_MM
        if outer
        else LID_FLEX_MOVING_CAPTURE_SECTION_MM
    )
    return (
        cq.Workplane(
            cq.Plane(
                origin=start,
                xDir=(1.0, 0.0, 0.0),
                normal=tangent,
            )
        )
        .rect(*section)
        .extrude(
            LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM
            + LID_FLEX_MOVING_CAPTURE_INSERTION_MM
        )
        .val()
    )


@lru_cache(maxsize=2)
def _closed_moving_harness_connector(side: int) -> cq.Shape:
    if side not in {-1, 1}:
        raise ValueError(f"Harness side must be -1 or +1, got {side}")
    # The upper face is coincident with the lid's Z=675 mm underside datum.
    # The flex endpoint enters the lower/outboard quadrant of this stiffened
    # board connector.  A real tangent-aligned strain-relief body surrounds a
    # supplier-unfrozen 6.4 x 1.0 mm capture envelope for the 6.0 x 0.6 mm FPC;
    # the complete connector then follows the lid rigidly.
    main_body = rounded_box(
        (8.0, 12.0, 8.0),
        (LID_FLEX_CENTRE_X_MM, side * 348.0, 671.0),
        2.0,
    )
    connector = main_body.fuse(
        _closed_moving_harness_capture(side, outer=True)
    ).clean()
    if connector.isNull() or not connector.isValid() or len(connector.Solids()) != 1:
        raise ValueError(f"A05 side={side} moving connector is not one valid solid")
    return connector


@lru_cache(maxsize=512)
def lid_harness_pose(side: int, angle_deg: float) -> LidHarnessPose:
    """Build the connected rear-cassette dynamic flex at one lid angle."""

    if side not in {-1, 1}:
        raise ValueError(f"Harness side must be -1 or +1, got {side}")
    if not 0.0 <= angle_deg <= LID_OPEN_ANGLE_DEG:
        raise ValueError(
            f"Harness angle must be in [0,{LID_OPEN_ANGLE_DEG}], got {angle_deg}"
        )

    angle = float(angle_deg)
    bezier = _harness_bezier_edge(side, angle)
    # Raising the U-bend by half of the changing free-tail length removes the
    # same length from each straight leg.  The complete copper centreline is
    # consequently constant without an elastic/stretching assumption.
    rolling_loop_z = LID_FLEX_LOOP_REFERENCE_Z_MM + 0.5 * (
        float(bezier.Length()) - _closed_harness_bezier_length_mm()
    )
    fixed = _harness_radial_point(
        side,
        LID_FLEX_FIXED_RADIAL_MM,
        LID_FLEX_FIXED_ENDPOINT_Z_MM,
    )
    loop_start = _harness_radial_point(
        side,
        LID_FLEX_FIXED_RADIAL_MM,
        rolling_loop_z,
    )
    loop_mid = _harness_radial_point(
        side,
        (
            LID_FLEX_FIXED_RADIAL_MM
            + LID_FLEX_MOVING_TRACK_RADIAL_MM
        )
        / 2.0,
        rolling_loop_z - LID_FLEX_ROLLING_RADIUS_MM,
    )
    loop_end = _harness_radial_point(
        side,
        LID_FLEX_MOVING_TRACK_RADIAL_MM,
        rolling_loop_z,
    )
    top_guide = _harness_radial_point(
        side,
        LID_FLEX_MOVING_TRACK_RADIAL_MM,
        LID_FLEX_TOP_GUIDE_Z_MM,
    )
    centerline = cq.Wire.assembleEdges(
        (
            cq.Edge.makeLine(fixed, loop_start),
            cq.Edge.makeThreePointArc(loop_start, loop_mid, loop_end),
            cq.Edge.makeLine(loop_end, top_guide),
            bezier,
        )
    )
    profile_plane = cq.Plane(
        origin=fixed,
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, 0.0, -1.0),
    )
    flex = (
        cq.Workplane(profile_plane)
        .rect(LID_FLEX_WIDTH_MM, LID_FLEX_THICKNESS_MM)
        # The path is planar in radial/Z.  A fixed-binormal sweep preserves
        # the real 6.0 x 0.6 mm section and keeps X exactly 105..111 mm;
        # Frenet transport spuriously shears the ribbon and changes its volume.
        .sweep(centerline, isFrenet=False)
        .val()
    )
    if not flex.isValid() or len(flex.Solids()) != 1:
        raise ValueError(
            f"A05 side={side} angle={angle:g} dynamic flex is not one valid solid"
        )

    bezier_length = float(bezier.Length())
    free_span_exclusion = (
        LID_FLEX_MOVING_CONNECTOR_CAPTURE_LENGTH_MM
        + LID_FLEX_MOVING_CONNECTOR_ENTRY_SETBACK_MM
    )
    if bezier_length <= free_span_exclusion:
        raise ValueError("A05 moving flex tail is shorter than connector capture")
    free_bezier_fraction = (
        bezier_length - free_span_exclusion
    ) / bezier_length
    free_bezier = bezier.trim(
        bezier.paramAt(0.0),
        bezier.paramAt(free_bezier_fraction),
    )
    free_centerline = cq.Wire.assembleEdges(
        (
            cq.Edge.makeLine(fixed, loop_start),
            cq.Edge.makeThreePointArc(loop_start, loop_mid, loop_end),
            cq.Edge.makeLine(loop_end, top_guide),
            free_bezier,
        )
    )
    free_flex_span = (
        cq.Workplane(profile_plane)
        .rect(LID_FLEX_WIDTH_MM, LID_FLEX_THICKNESS_MM)
        .sweep(free_centerline, isFrenet=False)
        .val()
    )
    if (
        free_flex_span.isNull()
        or not free_flex_span.isValid()
        or len(free_flex_span.Solids()) != 1
    ):
        raise ValueError(
            f"A05 side={side} angle={angle:g} free flex span is not one valid solid"
        )

    moving_radial, moving_z = _harness_moving_endpoint_rz(angle)
    tangent_radial, tangent_z = _harness_moving_tangent_rz(angle)
    minimum_centerline_radius = min(
        LID_FLEX_ROLLING_RADIUS_MM,
        _harness_bezier_minimum_centerline_radius_mm(angle),
    )
    return LidHarnessPose(
        side=side,
        angle_deg=angle,
        flex_circuit=flex,
        free_flex_span=free_flex_span,
        centerline=centerline,
        fixed_connector=_fixed_harness_connector(side),
        moving_connector=pose_lid_shape(
            _closed_moving_harness_connector(side),
            side,
            angle,
        ),
        moving_connector_capture=pose_lid_shape(
            _closed_moving_harness_capture(side, outer=False),
            side,
            angle,
        ),
        fixed_endpoint_mm=(fixed.x, fixed.y, fixed.z),
        moving_endpoint_mm=(
            LID_FLEX_CENTRE_X_MM,
            side * moving_radial,
            moving_z,
        ),
        moving_tangent=(0.0, side * tangent_radial, tangent_z),
        centerline_length_mm=float(centerline.Length()),
        rolling_loop_axis_z_mm=rolling_loop_z,
        minimum_inside_bend_radius_mm=(
            minimum_centerline_radius - LID_FLEX_THICKNESS_MM / 2.0
        ),
    )


def lid_harness_occurrences(
    side: int,
    angle_deg: float,
) -> tuple[MechanismOccurrence, ...]:
    pose = lid_harness_pose(side, angle_deg)
    side_name = "right" if side > 0 else "left"
    return (
        MechanismOccurrence(
            f"A05_lid_dynamic_flex_{side_name}",
            f"WC-A05-LID-DYNAMIC-FLEX-{side_name.upper()}",
            pose.flex_circuit,
            "open_ended_constant_length_dynamic_flex",
        ),
        MechanismOccurrence(
            f"A05_lid_flex_fixed_connector_{side_name}",
            f"WC-A05-LID-FLEX-FIXED-CONNECTOR-{side_name.upper()}",
            pose.fixed_connector,
            "fixed_shell_side_fpc_connector",
        ),
        MechanismOccurrence(
            f"A05_lid_flex_moving_connector_{side_name}",
            f"WC-A05-LID-FLEX-MOVING-CONNECTOR-{side_name.upper()}",
            pose.moving_connector,
            "lid_fixed_fpc_connector",
        ),
    )


@lru_cache(maxsize=2)
def harness_service_loop(side: int) -> cq.Shape:
    """Compatibility name for the real closed-lid dynamic flex solid."""

    return lid_harness_pose(side, 0.0).flex_circuit


def validate_use_sequence(events: Sequence[str], context: SequenceContext) -> tuple[bool, tuple[str, ...]]:
    """Fail closed unless the exact physical use order and interlocks hold."""

    failures: list[str] = []
    if tuple(events) != TABLE_ACCESS_SEQUENCE:
        failures.append("ordered_event_sequence_mismatch")
    if not context.parked or not context.traction_disabled:
        failures.append("park_or_traction_interlock_missing")
    if context.phone_present or context.qi_energised:
        failures.append("left_lid_phone_or_qi_interlock_open")
    if not context.drive_pod_present:
        failures.append("right_fixed_drive_pod_missing")
    if not context.sweep_zone_clear:
        failures.append("table_sweep_zone_not_clear")
    if not context.lid_double_latch_confirmed:
        failures.append("lid_not_double_latched_before_unfold")
    return (not failures, tuple(failures))


def combined_bounds(occurrences: Iterable[MechanismOccurrence]) -> tuple[float, float, float, float, float, float]:
    boxes = [item.shape.BoundingBox() for item in occurrences]
    if not boxes:
        raise ValueError("Cannot bound an empty mechanism occurrence set")
    return (
        min(box.xmin for box in boxes),
        max(box.xmax for box in boxes),
        min(box.ymin for box in boxes),
        max(box.ymax for box in boxes),
        min(box.zmin for box in boxes),
        max(box.zmax for box in boxes),
    )


def folded_pack_size(side: int) -> tuple[float, float, float]:
    xmin, xmax, ymin, ymax, zmin, zmax = combined_bounds(folded_pack_occurrences(side))
    return (xmax - xmin, ymax - ymin, zmax - zmin)


__all__ = [
    "CAFE_CLEARANCE_AXIS_X_MM",
    "CAFE_FINAL_AXIS_X_MM",
    "CAFE_FINAL_AXIS_Y_MM",
    "CAFE_INBOARD_RETURN_TRAVEL_MM",
    "DEPLOYED_LEAF_CENTRE_Z_MM",
    "FOCUS_AXIS_ABS_Y_MM",
    "FOCUS_AXIS_X_MM",
    "HALF_LEAF_LENGTH_MM",
    "HALF_LEAF_THICKNESS_MM",
    "HALF_LEAF_WIDTH_MM",
    "LID_FLEX_MINIMUM_INSIDE_RADIUS_MM",
    "LID_FLEX_THICKNESS_MM",
    "LID_FLEX_WIDTH_MM",
    "LidHarnessPose",
    "LID_OPEN_ANGLE_DEG",
    "MAXIMUM_FOLDED_MATERIAL_ENVELOPE_MM",
    "MechanismOccurrence",
    "NOMINAL_FOLDED_ENVELOPE_MM",
    "SequenceContext",
    "TABLE_ACCESS_SEQUENCE",
    "cafe_half_leaf_pair",
    "canonical_half_leaf",
    "combined_bounds",
    "extraction_axis_samples",
    "extraction_motion_occurrences",
    "folded_half_leaf_pair",
    "folded_pack_occurrences",
    "folded_pack_size",
    "harness_service_loop",
    "lid_harness_occurrences",
    "lid_harness_pose",
    "lid_sweep",
    "pose_lid_shape",
    "unfold_motion_pose",
    "unfolded_half_leaf",
    "validate_use_sequence",
]
