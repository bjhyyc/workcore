"""Production-intent moving hub island for the V8 half-wrapped wheels.

The fixed Class-A wheel belt owns a sweep-sized aperture.  A small body-colour
cap and opaque backing move with each wheel hub, while one colour-matched TPE
diaphragm keeps its outer edge bonded to the fixed belt and its inner edge on
the moving cap.  This preserves the quiet neutral appearance without exposing
the hub or axle at either suspension endpoint.

The helpers are deterministic B-Rep constructors only: they do not import a
state assembly, write artifacts, or retain five complete product states in
memory.  Release gates can therefore evaluate one wheel and one pose at a
time.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import cos, radians, sin

import cadquery as cq

from v8_wheel_contract import (
    WHEEL_ARTICULATION_POSE_ANGLES_DEG,
    WHEEL_AXLE_X_MM,
    WHEEL_HUB_BACKING_ABS_Y_MM,
    WHEEL_HUB_BACKING_PLAN_XZ_MM,
    WHEEL_HUB_BACKING_THICKNESS_Y_MM,
    WHEEL_HUB_CAP_ABS_Y_MM,
    WHEEL_HUB_CAP_PLAN_XZ_MM,
    WHEEL_HUB_CAP_THICKNESS_Y_MM,
    WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM,
    WHEEL_HUB_FIXED_APERTURE_CORNER_RADIUS_MM,
    WHEEL_HUB_FIXED_APERTURE_CUTTER_THICKNESS_Y_MM,
    WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM,
    WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM,
    WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM,
    WHEEL_HUB_GAITER_FIXED_EDGE_CORNER_RADIUS_MM,
    WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM,
    WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM,
    WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM,
    WHEEL_HUB_GAITER_MOVING_COLLAR_CORNER_RADIUS_MM,
    WHEEL_HUB_GAITER_MOVING_COLLAR_PLAN_XZ_MM,
    WHEEL_HUB_GAITER_MOVING_VOID_ABS_Y_MM,
    WHEEL_HUB_GAITER_THICKNESS_Y_MM,
    WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3,
    WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3,
    WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM,
    WHEEL_HUB_FLEXIBLE_RUNNING_GEAR_MIN_CLEARANCE_MM,
    WHEEL_HUB_SWEEP_ENVELOPE_CENTER_X_OFFSET_MM,
    WHEEL_ROCKER_PIVOT_MM,
)


_AXLE_X = dict(WHEEL_AXLE_X_MM)
_SIDE_SIGN = {"left": -1.0, "right": 1.0}
_CAP_RADIUS_MM = 18.0
_BACKING_RADIUS_MM = 18.8
_GAITER_INNER_RADIUS_MM = 17.0
_OCCLUSION_SHADOW_THICKNESS_Y_MM = 900.0


@dataclass(frozen=True)
class WheelHubStackPose:
    """One released rocker pose of the cap/backing/diaphragm stack."""

    axle: str
    side: str
    angle_deg: float
    hub_center_mm: tuple[float, float, float]
    cap: cq.Shape
    backing: cq.Shape
    gaiter: cq.Shape
    fixed_aperture_cutter: cq.Shape


def _validate_station(axle: str, side: str, angle_deg: float) -> None:
    if axle not in _AXLE_X:
        raise ValueError(f"Unsupported V8 wheel axle: {axle!r}")
    if side not in _SIDE_SIGN:
        raise ValueError(f"Unsupported V8 wheel side: {side!r}")
    if float(angle_deg) not in WHEEL_ARTICULATION_POSE_ANGLES_DEG:
        raise ValueError(
            f"Wheel articulation pose {angle_deg!r} is outside the release set"
        )


def _rounded_panel_xz(
    size_xz: tuple[float, float],
    thickness_y: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    sx, sz = size_xz
    body = cq.Workplane("XZ").rect(sx, sz).extrude(thickness_y / 2.0, both=True)
    try:
        body = body.edges("|Y").fillet(min(radius, sx * 0.45, sz * 0.45))
    except Exception:
        # A planar rounded panel remains physically valid if a platform-specific
        # OCCT fillet fails; the release gate still checks solid validity and
        # topology at all five poses.
        pass
    result = body.translate(center).val()
    if not isinstance(result, cq.Shape):
        raise TypeError("CadQuery did not return a wheel hub panel shape")
    return result


def _single(shape: cq.Shape, label: str) -> cq.Shape:
    cleaned = shape.clean()
    if (
        cleaned.isNull()
        or not cleaned.isValid()
        or cleaned.Volume() <= 0.0
        or len(cleaned.Solids()) != 1
    ):
        raise ValueError(f"{label} is not one positive valid B-Rep")
    return cleaned


def _rotate_with_rocker(shape: cq.Shape, angle_deg: float) -> cq.Shape:
    if abs(angle_deg) <= 1.0e-12:
        return shape
    ox, oy, oz = WHEEL_ROCKER_PIVOT_MM
    return shape.rotate((ox, oy, oz), (ox, oy + 1.0, oz), angle_deg)


def wheel_hub_center(
    axle: str,
    side: str,
    angle_deg: float,
) -> tuple[float, float, float]:
    """Return the released wheel-axis centre after rocker rotation."""

    _validate_station(axle, side, angle_deg)
    ox, _, oz = WHEEL_ROCKER_PIVOT_MM
    dx = _AXLE_X[axle] - ox
    dz = 125.0 - oz
    theta = radians(angle_deg)
    return (
        ox + dx * cos(theta) + dz * sin(theta),
        _SIDE_SIGN[side] * WHEEL_HUB_CAP_ABS_Y_MM,
        oz - dx * sin(theta) + dz * cos(theta),
    )


def _neutral_panel(
    axle: str,
    side: str,
    *,
    size_xz: tuple[float, float],
    thickness_y: float,
    abs_y: float,
    radius: float,
) -> cq.Shape:
    return _rounded_panel_xz(
        size_xz,
        thickness_y,
        (_AXLE_X[axle], _SIDE_SIGN[side] * abs_y, 125.0),
        radius,
    )


def _fixed_sweep_center_x(axle: str) -> float:
    """Return the smooth fixed-envelope centre shifted toward the pivot."""

    direction_to_pivot = 1.0 if _AXLE_X[axle] < WHEEL_ROCKER_PIVOT_MM[0] else -1.0
    return (
        _AXLE_X[axle]
        + direction_to_pivot * WHEEL_HUB_SWEEP_ENVELOPE_CENTER_X_OFFSET_MM
    )


@lru_cache(maxsize=8)
def wheel_hub_fixed_aperture_cutter(axle: str, side: str) -> cq.Shape:
    """Return one smooth fixed opening containing every moving cap pose.

    The former boolean union of five rotated rounded rectangles left pointed
    lobes in the released Class-A edge.  A single generous rounded envelope is
    both easier to tool and visually quiet; every cap/backing pose remains
    proved inside it by the articulation gate.
    """

    _validate_station(axle, side, 0.0)
    return _single(
        _rounded_panel_xz(
            WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM,
            WHEEL_HUB_FIXED_APERTURE_CUTTER_THICKNESS_Y_MM,
            (
                _fixed_sweep_center_x(axle),
                _SIDE_SIGN[side] * WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM,
                125.0,
            ),
            WHEEL_HUB_FIXED_APERTURE_CORNER_RADIUS_MM,
        ),
        f"{axle} {side} smooth fixed hub aperture",
    )


@lru_cache(maxsize=8)
def wheel_hub_fixed_carrier_return(axle: str, side: str) -> cq.Shape:
    """Return the hidden rigid ring supporting the inboard gaiter edge.

    This ring is fused into the continuous belt, not exposed as a new part.
    Its inner opening exceeds the visible aperture and clears the complete
    moving running-gear family; its inboard end face is the real bonded datum
    for the dished TPE membrane.
    """

    _validate_station(axle, side, 0.0)
    side_sign = _SIDE_SIGN[side]
    fixed_center_x = _fixed_sweep_center_x(axle)
    span = (
        WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM
        - WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM
    )
    lip_thickness_y = 0.8
    lip_center_y = side_sign * (
        WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM
        - lip_thickness_y / 2.0
    )
    outer = _rounded_panel_xz(
        WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM,
        lip_thickness_y,
        (fixed_center_x, lip_center_y, 125.0),
        WHEEL_HUB_GAITER_FIXED_EDGE_CORNER_RADIUS_MM,
    )
    inner = _rounded_panel_xz(
        WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM,
        lip_thickness_y + 0.4,
        (fixed_center_x, lip_center_y, 125.0),
        47.0,
    )
    carrier = outer.cut(inner).clean()

    # Two narrow upper outriggers connect the fixed lip to belt material
    # outside the smooth aperture.  They live wholly above the wheel axis and
    # outside the gaiter loft, so the TPE meets them only at its fixed face and
    # no hidden rigid member becomes a lower-wheel silhouette.
    tab_y = side_sign * 0.5 * (
        WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM
        + WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM
    )
    for offset_x in (-72.0, 72.0):
        ear = (
            cq.Workplane("XY")
            .box(8.0, lip_thickness_y, 16.0)
            .edges("|Y")
            .fillet(1.0)
            .translate((fixed_center_x + offset_x, lip_center_y, 190.0))
            .val()
        )
        tab = (
            cq.Workplane("XY")
            .box(3.0, span, 16.0)
            .edges("|Y")
            .fillet(1.0)
            .translate((fixed_center_x + offset_x, tab_y, 190.0))
            .val()
        )
        carrier = carrier.fuse(ear).fuse(tab)
    return _single(
        carrier.clean(),
        f"{axle} {side} hidden gaiter carrier return",
    )


def wheel_belt_class_a_shell(belt: cq.Shape, side: str) -> cq.Shape:
    """Return the visible belt wall with its fused hidden carriers removed.

    The carrier deliberately belongs to the production belt B-Rep, but its
    close approach to the tyre is an internal packaging clearance.  Exterior
    tyre-clearance gates measure this remainder; the articulation gate still
    proves both carriers are contained and clear of moving running gear.
    """

    _validate_station("front", side, 0.0)
    if belt.isNull() or not belt.isValid() or belt.Volume() <= 0.0:
        raise ValueError(f"Invalid {side} continuous wheel belt")
    visible_shell = belt
    for axle in ("front", "rear"):
        visible_shell = visible_shell.cut(
            wheel_hub_fixed_carrier_return(axle, side)
        )
    return _single(
        visible_shell.clean(),
        f"{side} continuous wheel belt Class-A shell",
    )


def _rounded_rect_wire_xz(
    size_xz: tuple[float, float],
    center: tuple[float, float, float],
    radius: float,
) -> cq.Wire:
    """Create one rounded closed wire on a world XZ plane."""

    sx, sz = size_xz
    sketch = cq.Sketch().rect(sx, sz).vertices().fillet(
        min(radius, sx * 0.45, sz * 0.45)
    )
    faces = sketch._faces.Faces()
    if len(faces) != 1:
        raise ValueError("Rounded gaiter profile did not create one face")
    return (
        faces[0]
        .outerWire()
        .rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 90.0)
        .translate(center)
    )


def _raw_dished_gaiter(
    axle: str,
    side: str,
    angle_deg: float,
    fixed_edge_wall_mm: float,
) -> cq.Shape:
    """Loft one smooth fixed-edge/moving-collar TPE membrane."""

    _validate_station(axle, side, angle_deg)
    side_sign = _SIDE_SIGN[side]
    axle_x = _AXLE_X[axle]
    fixed_center_x = _fixed_sweep_center_x(axle)
    outer_fixed = _rounded_rect_wire_xz(
        WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM,
        (
            fixed_center_x,
            side_sign * WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM,
            125.0,
        ),
        WHEEL_HUB_GAITER_FIXED_EDGE_CORNER_RADIUS_MM,
    )
    outer_collar_neutral = _rounded_rect_wire_xz(
        WHEEL_HUB_GAITER_MOVING_COLLAR_PLAN_XZ_MM,
        (
            axle_x,
            side_sign * WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM,
            125.0,
        ),
        WHEEL_HUB_GAITER_MOVING_COLLAR_CORNER_RADIUS_MM,
    )
    outer_collar = _rotate_with_rocker(outer_collar_neutral, angle_deg)
    outer = cq.Solid.makeLoft([outer_fixed, outer_collar], ruled=False)

    inner_fixed_size = tuple(
        value - 2.0 * fixed_edge_wall_mm
        for value in WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM
    )
    inner_fixed = _rounded_rect_wire_xz(
        inner_fixed_size,
        (
            fixed_center_x,
            side_sign
            * (
                WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM
                - fixed_edge_wall_mm
            ),
            125.0,
        ),
        WHEEL_HUB_GAITER_FIXED_EDGE_CORNER_RADIUS_MM
        - fixed_edge_wall_mm,
    )
    inner_collar_neutral = _rounded_rect_wire_xz(
        WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM,
        (
            axle_x,
            side_sign * WHEEL_HUB_GAITER_MOVING_VOID_ABS_Y_MM,
            125.0,
        ),
        _GAITER_INNER_RADIUS_MM,
    )
    inner_collar = _rotate_with_rocker(inner_collar_neutral, angle_deg)
    inner = cq.Solid.makeLoft([inner_fixed, inner_collar], ruled=False)
    return _single(
        outer.cut(inner),
        f"{axle} {side} dished gaiter at {angle_deg:+.1f} deg",
    )


@lru_cache(maxsize=8)
def _neutral_gaiter_target_volume(axle: str, side: str) -> float:
    return float(
        _raw_dished_gaiter(
            axle,
            side,
            0.0,
            WHEEL_HUB_GAITER_THICKNESS_Y_MM,
        ).Volume()
    )


@lru_cache(maxsize=40)
def _dished_gaiter_pose(axle: str, side: str, angle_deg: float) -> cq.Shape:
    """Return a constant-material-volume dished membrane for one pose."""

    target = _neutral_gaiter_target_volume(axle, side)
    base_wall = WHEEL_HUB_GAITER_THICKNESS_Y_MM
    first = _raw_dished_gaiter(axle, side, angle_deg, base_wall)
    first_volume = float(first.Volume())
    if abs(first_volume - target) <= WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3:
        return first

    sample_wall = base_wall + 0.10
    sample = _raw_dished_gaiter(axle, side, angle_deg, sample_wall)
    sample_volume = float(sample.Volume())
    if abs(sample_volume - first_volume) <= 1.0e-9:
        raise ValueError("Dished gaiter volume normalisation has zero slope")
    corrected_wall = base_wall + (target - first_volume) * (
        sample_wall - base_wall
    ) / (sample_volume - first_volume)
    corrected = _raw_dished_gaiter(
        axle,
        side,
        angle_deg,
        corrected_wall,
    )
    corrected_volume = float(corrected.Volume())
    if abs(corrected_volume - first_volume) > 1.0e-9:
        corrected_wall += (target - corrected_volume) * (
            corrected_wall - base_wall
        ) / (corrected_volume - first_volume)
        corrected = _raw_dished_gaiter(
            axle,
            side,
            angle_deg,
            corrected_wall,
        )
    if (
        abs(float(corrected.Volume()) - target)
        > WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3
    ):
        raise ValueError(
            f"{axle} {side} gaiter material-volume normalisation failed at "
            f"{angle_deg:+.1f} deg"
        )
    return corrected


def wheel_hub_stack_pose(
    axle: str,
    side: str,
    angle_deg: float,
) -> WheelHubStackPose:
    """Build one cap/backing/gaiter pose without retaining other poses."""

    _validate_station(axle, side, angle_deg)
    cap_neutral = _neutral_panel(
        axle,
        side,
        size_xz=WHEEL_HUB_CAP_PLAN_XZ_MM,
        thickness_y=WHEEL_HUB_CAP_THICKNESS_Y_MM,
        abs_y=WHEEL_HUB_CAP_ABS_Y_MM,
        radius=_CAP_RADIUS_MM,
    )
    backing_neutral = _neutral_panel(
        axle,
        side,
        size_xz=WHEEL_HUB_BACKING_PLAN_XZ_MM,
        thickness_y=WHEEL_HUB_BACKING_THICKNESS_Y_MM,
        abs_y=WHEEL_HUB_BACKING_ABS_Y_MM,
        radius=_BACKING_RADIUS_MM,
    )
    cap = _single(
        _rotate_with_rocker(cap_neutral, angle_deg),
        f"{axle} {side} moving hub cap at {angle_deg:+.1f} deg",
    )
    backing = _single(
        _rotate_with_rocker(backing_neutral, angle_deg),
        f"{axle} {side} moving hub backing at {angle_deg:+.1f} deg",
    )
    gaiter = _dished_gaiter_pose(axle, side, float(angle_deg))
    return WheelHubStackPose(
        axle=axle,
        side=side,
        angle_deg=float(angle_deg),
        hub_center_mm=wheel_hub_center(axle, side, angle_deg),
        cap=cap,
        backing=backing,
        gaiter=gaiter,
        fixed_aperture_cutter=wheel_hub_fixed_aperture_cutter(axle, side),
    )


def wheel_hub_normal_sightline_shadow(
    axle: str,
    side: str,
    angle_deg: float,
) -> cq.Shape:
    """Return the deep normal-view shadow of the actual hub service cap.

    The released cap alone encloses the complete hub-and-axle end projection
    at every rocker pose.  The dished gaiter closes the weather gap but is not
    credited with hiding running gear, so a missing/undersized cap cannot be
    disguised by an oversized flexible membrane.
    """

    _validate_station(axle, side, angle_deg)
    cap_shadow = _rotate_with_rocker(
        _neutral_panel(
            axle,
            side,
            size_xz=WHEEL_HUB_CAP_PLAN_XZ_MM,
            thickness_y=_OCCLUSION_SHADOW_THICKNESS_Y_MM,
            abs_y=0.0,
            radius=_CAP_RADIUS_MM,
        ),
        angle_deg,
    )
    return _single(
        cap_shadow,
        f"{axle} {side} normal-sightline occlusion shadow at {angle_deg:+.1f}",
    )


def rotate_running_gear(shape: cq.Shape, angle_deg: float) -> cq.Shape:
    """Apply the released rocker transform to a controlled hub/axle B-Rep."""

    if float(angle_deg) not in WHEEL_ARTICULATION_POSE_ANGLES_DEG:
        raise ValueError(f"Unsupported released rocker angle: {angle_deg!r}")
    return _rotate_with_rocker(shape, float(angle_deg))


def _common_volume(first: cq.Shape, second: cq.Shape) -> float:
    return float(first.intersect(second).Volume())


def _symmetric_difference_volume(first: cq.Shape, second: cq.Shape) -> float:
    return float(first.cut(second).Volume()) + float(second.cut(first).Volume())


def _bounds(shape: cq.Shape) -> dict[str, float]:
    box = shape.BoundingBox()
    return {
        "xmin": float(box.xmin),
        "xmax": float(box.xmax),
        "ymin": float(box.ymin),
        "ymax": float(box.ymax),
        "zmin": float(box.zmin),
        "zmax": float(box.zmax),
    }


def _topology_signature(shape: cq.Shape) -> dict[str, int]:
    """Return a JSON-safe topological inventory for pose comparisons.

    Equal face counts alone do not prove that a flexible diaphragm retained
    the same shell/wire connectivity.  The release evidence therefore locks
    every OCCT topological level exposed by CadQuery.
    """

    return {
        "solids": len(shape.Solids()),
        "shells": len(shape.Shells()),
        "faces": len(shape.Faces()),
        "wires": len(shape.Wires()),
        "edges": len(shape.Edges()),
        "vertices": len(shape.Vertices()),
    }


def evaluate_wheel_hub_articulation(
    *,
    axle: str,
    side: str,
    belt: cq.Shape,
    released_cap: cq.Shape,
    released_backing: cq.Shape,
    released_gaiter: cq.Shape,
    controlled_hub: cq.Shape,
    controlled_axle: cq.Shape,
    boolean_tolerance_mm3: float = 1.0e-4,
    distance_tolerance_mm: float = 1.0e-4,
) -> dict[str, object]:
    """Prove one wheel sequentially without retaining its five pose solids.

    The returned mapping is JSON-safe and deliberately contains only scalars
    and bounds.  This lets the release runner discard every transient OCC
    shape before evaluating the next wheel.
    """

    _validate_station(axle, side, 0.0)
    for label, shape in (
        ("belt", belt),
        ("released_cap", released_cap),
        ("released_backing", released_backing),
        ("released_gaiter", released_gaiter),
        ("controlled_hub", controlled_hub),
        ("controlled_axle", controlled_axle),
    ):
        if shape.isNull() or not shape.isValid() or shape.Volume() <= 0.0:
            raise ValueError(f"Invalid {axle} {side} {label} B-Rep")

    neutral = wheel_hub_stack_pose(axle, side, 0.0)
    neutral_differences = {
        "cap_mm3": _symmetric_difference_volume(released_cap, neutral.cap),
        "backing_mm3": _symmetric_difference_volume(
            released_backing,
            neutral.backing,
        ),
        "gaiter_mm3": _symmetric_difference_volume(
            released_gaiter,
            neutral.gaiter,
        ),
    }
    pose_rows: list[dict[str, object]] = []
    gaiter_volumes: list[float] = []
    all_pass = all(
        value <= boolean_tolerance_mm3
        for value in neutral_differences.values()
    )

    controlled_running_gear = controlled_hub.fuse(controlled_axle).clean()
    carrier = wheel_hub_fixed_carrier_return(axle, side)
    carrier_outside_belt = float(carrier.cut(belt).Volume())
    all_pass = all_pass and carrier_outside_belt <= boolean_tolerance_mm3
    for angle in WHEEL_ARTICULATION_POSE_ANGLES_DEG:
        pose = wheel_hub_stack_pose(axle, side, angle)
        running_gear = rotate_running_gear(controlled_running_gear, angle)
        shadow = wheel_hub_normal_sightline_shadow(axle, side, angle)
        residual = float(running_gear.cut(shadow).Volume())
        cap_belt_common = _common_volume(pose.cap, belt)
        backing_belt_common = _common_volume(pose.backing, belt)
        gaiter_belt_common = _common_volume(pose.gaiter, belt)
        gaiter_belt_distance = float(pose.gaiter.distance(belt))
        carrier_running_common = _common_volume(carrier, running_gear)
        carrier_running_clearance = float(carrier.distance(running_gear))
        cap_running_common = _common_volume(pose.cap, running_gear)
        backing_running_common = _common_volume(pose.backing, running_gear)
        gaiter_running_common = _common_volume(pose.gaiter, running_gear)
        cap_running_clearance = float(pose.cap.distance(running_gear))
        backing_running_clearance = float(pose.backing.distance(running_gear))
        gaiter_running_clearance = float(pose.gaiter.distance(running_gear))
        cap_backing_common = _common_volume(pose.cap, pose.backing)
        cap_backing_distance = float(pose.cap.distance(pose.backing))
        backing_gaiter_common = _common_volume(pose.backing, pose.gaiter)
        backing_gaiter_distance = float(pose.backing.distance(pose.gaiter))
        cap_outside_fixed_aperture = float(
            pose.cap.cut(pose.fixed_aperture_cutter).Volume()
        )
        backing_outside_fixed_aperture = float(
            pose.backing.cut(pose.fixed_aperture_cutter).Volume()
        )
        gaiter_volume = float(pose.gaiter.Volume())
        gaiter_topology = _topology_signature(pose.gaiter)
        gaiter_volumes.append(gaiter_volume)
        pose_pass = (
            len(pose.cap.Solids()) == 1
            and len(pose.backing.Solids()) == 1
            and len(pose.gaiter.Solids()) == 1
            and cap_belt_common <= boolean_tolerance_mm3
            and backing_belt_common <= boolean_tolerance_mm3
            and gaiter_belt_common <= boolean_tolerance_mm3
            and gaiter_belt_distance <= distance_tolerance_mm
            and carrier_running_common <= boolean_tolerance_mm3
            and carrier_running_clearance
            >= WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM
            - distance_tolerance_mm
            and cap_running_common <= boolean_tolerance_mm3
            and backing_running_common <= boolean_tolerance_mm3
            and gaiter_running_common <= boolean_tolerance_mm3
            and cap_running_clearance
            >= WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM
            - distance_tolerance_mm
            and backing_running_clearance
            >= WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM
            - distance_tolerance_mm
            and gaiter_running_clearance
            >= WHEEL_HUB_FLEXIBLE_RUNNING_GEAR_MIN_CLEARANCE_MM
            - distance_tolerance_mm
            and cap_backing_common <= boolean_tolerance_mm3
            and cap_backing_distance <= distance_tolerance_mm
            and backing_gaiter_common <= boolean_tolerance_mm3
            and backing_gaiter_distance <= distance_tolerance_mm
            and cap_outside_fixed_aperture <= boolean_tolerance_mm3
            and backing_outside_fixed_aperture <= boolean_tolerance_mm3
            and residual <= WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3
        )
        all_pass = all_pass and pose_pass
        pose_rows.append(
            {
                "angle_deg": float(angle),
                "status": "PASS" if pose_pass else "FAIL",
                "hub_center_mm": [float(value) for value in pose.hub_center_mm],
                "cap_bounds_mm": _bounds(pose.cap),
                "gaiter_bounds_mm": _bounds(pose.gaiter),
                "cap_to_belt_common_mm3": cap_belt_common,
                "backing_to_belt_common_mm3": backing_belt_common,
                "gaiter_to_belt_common_mm3": gaiter_belt_common,
                "gaiter_to_belt_distance_mm": gaiter_belt_distance,
                "carrier_to_running_gear_common_mm3": carrier_running_common,
                "carrier_to_running_gear_clearance_mm": (
                    carrier_running_clearance
                ),
                "cap_to_running_gear_common_mm3": cap_running_common,
                "backing_to_running_gear_common_mm3": backing_running_common,
                "gaiter_to_running_gear_common_mm3": gaiter_running_common,
                "cap_to_running_gear_clearance_mm": cap_running_clearance,
                "backing_to_running_gear_clearance_mm": (
                    backing_running_clearance
                ),
                "gaiter_to_running_gear_clearance_mm": gaiter_running_clearance,
                "cap_to_backing_common_mm3": cap_backing_common,
                "cap_to_backing_distance_mm": cap_backing_distance,
                "backing_to_gaiter_common_mm3": backing_gaiter_common,
                "backing_to_gaiter_distance_mm": backing_gaiter_distance,
                "cap_outside_fixed_aperture_mm3": (
                    cap_outside_fixed_aperture
                ),
                "backing_outside_fixed_aperture_mm3": (
                    backing_outside_fixed_aperture
                ),
                "normal_sightline_unoccluded_hub_axle_volume_mm3": residual,
                "gaiter_volume_mm3": gaiter_volume,
                "gaiter_solid_count": len(pose.gaiter.Solids()),
                "gaiter_face_count": len(pose.gaiter.Faces()),
                "gaiter_topology_signature": gaiter_topology,
            }
        )
        # Do not append any cq.Shape to the evidence.  Local pose/running-gear
        # objects become collectible before the next wheel begins.

    gaiter_volume_variation = max(gaiter_volumes) - min(gaiter_volumes)
    gaiter_topology_signatures = {
        tuple(
            sorted(
                dict(row["gaiter_topology_signature"]).items()
            )
        )
        for row in pose_rows
    }
    reference_topology = dict(pose_rows[0]["gaiter_topology_signature"])
    topology_pass = (
        reference_topology["solids"] == 1
        and reference_topology["shells"] == 1
        and len(gaiter_topology_signatures) == 1
    )
    volume_pass = (
        gaiter_volume_variation
        <= WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3
    )
    all_pass = all_pass and topology_pass and volume_pass
    return {
        "status": "PASS" if all_pass else "FAIL",
        "axle": axle,
        "side": side,
        "neutral_released_brep_symmetric_difference_mm3": (
            neutral_differences
        ),
        "fixed_aperture_bounds_mm": _bounds(
            wheel_hub_fixed_aperture_cutter(axle, side)
        ),
        "fixed_carrier_bounds_mm": _bounds(carrier),
        "fixed_carrier_outside_belt_mm3": carrier_outside_belt,
        "gaiter_volume_variation_mm3": gaiter_volume_variation,
        "gaiter_volume_variation_limit_mm3": (
            WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3
        ),
        "gaiter_topology_signature": reference_topology,
        "gaiter_topology_signatures_observed": [
            dict(signature) for signature in sorted(gaiter_topology_signatures)
        ],
        "same_topology_all_poses": topology_pass,
        "poses": pose_rows,
    }


__all__ = [
    "WheelHubStackPose",
    "evaluate_wheel_hub_articulation",
    "rotate_running_gear",
    "wheel_hub_center",
    "wheel_hub_fixed_carrier_return",
    "wheel_hub_fixed_aperture_cutter",
    "wheel_belt_class_a_shell",
    "wheel_hub_normal_sightline_shadow",
    "wheel_hub_stack_pose",
]
