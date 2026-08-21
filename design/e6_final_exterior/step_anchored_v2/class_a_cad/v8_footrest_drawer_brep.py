"""A08 captured-drawer / over-centre-link production-intent B-Reps.

This module is deliberately isolated from the final four-state builder.  It
turns :mod:`cad.footrest_production_architecture` into a complete, pose-stable
occurrence inventory which an integration layer can consume without inventing
or deleting hardware between stowed and Ride poses.

The geometry is design evidence, not a production certification.  Proof load,
fatigue, contamination, pinch, tolerance and physical interlock tests remain
separate release gates.
"""

from __future__ import annotations

import itertools
import math
from functools import lru_cache
from typing import Iterable, Mapping

import cadquery as cq

from cad.footrest_production_architecture import (
    CLEAR_HORIZONTAL_COMPONENT_MM,
    DROP_LINK_LENGTH_MM,
    LOWER_CARRIAGE_PIVOT_Z_MM,
    PLATFORM_DEPLOYED_CENTER_MM,
    PLATFORM_STOWED_CENTER_MM,
    PRIMARY_CARTRIDGE_TRAVEL_MM,
    production_footrest_pose,
)

try:
    from .skin_common import rounded_box, rounded_frame, rounded_rect_prism
except ImportError:
    from skin_common import (  # type: ignore[no-redef]
        rounded_box,
        rounded_frame,
        rounded_rect_prism,
    )


# All values are millimetres in the controlled WorkCore coordinate system.
FIXED_GUIDE_X_LIMITS_MM = (-470.0, -190.0)
FIXED_GUIDE_LENGTH_MM = FIXED_GUIDE_X_LIMITS_MM[1] - FIXED_GUIDE_X_LIMITS_MM[0]
RAIL_ABS_Y_MM = 220.0
RAIL_SECTION_CENTER_Z_MM = 78.0
FIXED_GUIDE_OUTER_YZ_MM = (36.0, 32.0)
FIXED_GUIDE_INNER_YZ_MM = (30.0, 26.0)
PRIMARY_LENGTH_MM = 200.0
PRIMARY_STOWED_CENTER_X_MM = -310.0
PRIMARY_OUTER_YZ_MM = (26.0, 22.0)
PRIMARY_INNER_YZ_MM = (20.0, 16.0)
INNER_LENGTH_MM = 200.0
INNER_STOWED_CENTER_X_MM = -308.0
INNER_OUTER_YZ_MM = (16.0, 12.0)

SUPPORT_MONOCOQUE_LENGTH_MM = 158.0
SUPPORT_MONOCOQUE_STOWED_CENTER_X_MM = -258.0
SUPPORT_MONOCOQUE_ABS_Y_MM = 274.0
SUPPORT_MONOCOQUE_CENTER_Z_MM = 110.0
SUPPORT_MONOCOQUE_OUTER_YZ_MM = (12.0, 50.0)
SUPPORT_MONOCOQUE_CAVITY_YZ_MM = (4.0, 42.0)

# Both fail-closed foot-zone channels live behind the one continuous smoked
# perception horizon.  The former side-mounted boxes occupied the controlled
# front-tyre B-Reps and would also have read as two extra robot eyes.  This
# inboard, elevated location is inside the hollow A01 nose, 18 mm behind the
# smoked mask and well above the complete A08 motion envelope.
FOOT_ZONE_INTERLOCK_CENTER_X_MM = -450.0
FOOT_ZONE_INTERLOCK_ABS_Y_MM = 200.0
FOOT_ZONE_INTERLOCK_CENTER_Z_MM = 250.0

LINK_X_OFFSETS_MM = (-40.0, 40.0)
# The plates sit inboard of the fixed-guide outer wall.  The former 209 mm
# datum put 3 mm of link material inside the primary cartridge wall.
LINK_PLATE_ABS_Y_MM = 198.0
LINK_PLATE_THICKNESS_MM = 4.0
LINK_OUTER_RADIUS_MM = 4.0
LINK_BORE_RADIUS_MM = 3.15
BEARING_OUTER_RADIUS_MM = 2.95
BEARING_INNER_RADIUS_MM = 2.25
JOINT_PIN_RADIUS_MM = 1.9

STOWED_LOCK_WORLD_X_MM = -266.188234
DEPLOYED_LOCK_WORLD_X_MM = -450.0
LOCK_BORE_RADIUS_MM = 3.2
LOCK_PIN_RADIUS_MM = 2.5
LOCK_PIN_ENGAGED_CENTER_Z_MM = 80.0
LOCK_PIN_RETRACTED_CENTER_Z_MM = 46.0
LOCK_PIN_LENGTH_MM = 28.0

PLATFORM_REFERENCE_TO_TOP_MM = 14.0
PLATFORM_REFERENCE_TO_BOTTOM_MM = 5.0
ROOT_ROOF_BOTTOM_Z_MM = 148.0
ROOT_ROOF_TOP_Z_MM = 160.0
ROOT_ROOF_X_LIMITS_MM = (-528.0, -489.0)
ROOT_ROOF_HALF_Y_MM = 260.0
ROOT_LEG_CENTER_ABS_Y_MM = 259.0
ROOT_LEG_HALF_Y_MM = 4.0

# A fixed rear closeout sits behind the complete drawer stroke.  Its face is
# five millimetres behind the stowed perimeter skin, while the two short feet
# land on the fixed-guide top faces.  Together with the deployed undertray and
# the root roof this makes a real offset labyrinth instead of a front wall
# which the moving platform would have to pass through.
REAR_LABYRINTH_BAFFLE_CENTER_X_MM = -247.0
REAR_LABYRINTH_BAFFLE_PANEL_Y_MM = 500.0
REAR_LABYRINTH_BAFFLE_PANEL_Z_LIMITS_MM = (98.0, 230.0)
REAR_LABYRINTH_BAFFLE_MINIMUM_DRY_GAP_MM = 5.0

NORMAL_FRONT_SIGHTLINE_Y_MM = tuple(float(value) for value in range(-240, 241, 60))
NORMAL_FRONT_SIGHTLINE_Z_MM = (110.0, 120.0, 135.0, 145.0)


FIXED_OCCURRENCE_NAMES = frozenset(
    {
        "A08_footrest_root_monocoque",
        "A08_footrest_rear_labyrinth_baffle",
        "A08_footrest_fixed_guide_housing_left",
        "A08_footrest_fixed_guide_housing_right",
        "A08_footrest_stowed_lock_witness_left",
        "A08_footrest_stowed_lock_witness_right",
        "A08_footrest_deployed_lock_witness_left",
        "A08_footrest_deployed_lock_witness_right",
        "A08_foot_zone_interlock_channel_a",
        "A08_foot_zone_interlock_channel_b",
        "A08_footrest_counterbalance_cartridge",
        "A08_footrest_manual_release_actuator",
        "A08_footrest_manual_release_cable",
    }
)


def _shape(value: cq.Workplane | cq.Shape) -> cq.Shape:
    if isinstance(value, cq.Shape):
        return value
    result = value.val()
    if not isinstance(result, cq.Shape):
        raise TypeError(f"Expected CadQuery shape, got {type(result)!r}")
    return result


def _single(shape: cq.Shape, label: str) -> cq.Shape:
    solids = shape.Solids()
    if shape.isNull() or not shape.isValid() or len(solids) != 1:
        raise ValueError(
            f"A08 {label} must be one valid solid; solids={len(solids)}"
        )
    if shape.Volume() <= 0.0:
        raise ValueError(f"A08 {label} has non-positive volume")
    return shape


def _axis_y_cylinder(
    radius_mm: float,
    length_mm: float,
    center: tuple[float, float, float],
) -> cq.Shape:
    cylinder = _shape(
        cq.Workplane("XZ").circle(radius_mm).extrude(length_mm, both=True)
    )
    # CadQuery's ``both`` applies the requested distance on each side.
    cylinder = cylinder.scale(1.0).translate(center)
    box = cylinder.BoundingBox()
    if abs(box.ylen - 2.0 * length_mm) <= 1.0e-6:
        # Retain a caller-facing total length rather than a half-length.
        cylinder = _shape(
            cq.Workplane("XZ")
            .circle(radius_mm)
            .extrude(length_mm / 2.0, both=True)
        ).translate(center)
    return cylinder


def _axis_z_cylinder(
    radius_mm: float,
    length_mm: float,
    center: tuple[float, float, float],
) -> cq.Shape:
    return _shape(
        cq.Workplane("XY")
        .circle(radius_mm)
        .extrude(length_mm / 2.0, both=True)
    ).translate(center)


def _axis_x_cylinder(
    radius_mm: float,
    length_mm: float,
    center: tuple[float, float, float],
) -> cq.Shape:
    return _shape(
        cq.Workplane("YZ")
        .circle(radius_mm)
        .extrude(length_mm / 2.0, both=True)
    ).translate(center)


def _segment_tube(
    radius_mm: float,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> cq.Shape:
    """Return a solid ray tube between two arbitrary points."""

    start_vector = cq.Vector(*start)
    delta = cq.Vector(*(finish - origin for origin, finish in zip(start, end)))
    length = delta.Length
    if length <= 1.0e-9:
        raise ValueError("A08 sightline segment must have positive length")
    return _single(
        cq.Solid.makeCylinder(radius_mm, length, start_vector, delta.normalized()),
        "sightline ray tube",
    )


def _axis_y_annulus(
    outer_radius_mm: float,
    inner_radius_mm: float,
    length_mm: float,
    center: tuple[float, float, float],
) -> cq.Shape:
    return _shape(
        cq.Workplane("XZ")
        .circle(outer_radius_mm)
        .circle(inner_radius_mm)
        .extrude(length_mm / 2.0, both=True)
    ).translate(center)


def _rectangular_tube_x(
    length_mm: float,
    outer_yz_mm: tuple[float, float],
    inner_yz_mm: tuple[float, float],
    center: tuple[float, float, float],
) -> cq.Shape:
    outer = _shape(
        cq.Workplane("YZ").rect(*outer_yz_mm).extrude(length_mm / 2.0, both=True)
    )
    inner = _shape(
        cq.Workplane("YZ")
        .rect(*inner_yz_mm)
        .extrude(length_mm / 2.0 + 2.0, both=True)
    )
    return _single(outer.cut(inner).translate(center), "rectangular rail tube")


def _cut_vertical_bores(
    shape: cq.Shape,
    x_positions_mm: Iterable[float],
    y_mm: float,
) -> cq.Shape:
    result = shape
    for x_mm in x_positions_mm:
        result = result.cut(
            _axis_z_cylinder(
                LOCK_BORE_RADIUS_MM,
                50.0,
                (float(x_mm), y_mm, LOWER_CARRIAGE_PIVOT_Z_MM),
            )
        )
    return _single(result, "lock-bored rail")


@lru_cache(maxsize=1)
def _platform_local_shapes() -> dict[str, cq.Shape]:
    """Return the three released exterior occurrences at a zero reference."""

    drain_offsets_x = (-50.0, 0.0, 50.0)
    top = rounded_rect_prism((206.0, 496.0), 6.0, (0.0, 0.0, 8.0), 18.0)
    for x_offset in drain_offsets_x:
        top = top.cut(
            rounded_rect_prism(
                (12.0, 96.0),
                20.0,
                (x_offset, 0.0, 10.0),
                6.0,
            )
        )
    tread = rounded_rect_prism((180.0, 468.0), 3.0, (-2.0, 0.0, 12.5), 16.0)
    for x_offset in drain_offsets_x:
        tread = tread.cut(
            rounded_box((14.0, 120.0, 10.0), (x_offset, 0.0, 12.5), 6.0)
        )
    perimeter = rounded_frame((210.0, 500.0), (192.0, 482.0), 10.0, (0.0, 0.0, 0.0), 18.0)
    undertray_outer = rounded_box((188.0, 476.0, 44.0), (0.0, 0.0, -18.0), 12.0)
    # Open upward and through the rear service throat.  Four millimetre side
    # returns and a five millimetre lower skin hide the mechanism from normal
    # low oblique views without pretending the mechanism can pass through a
    # closed box.
    undertray_inner = rounded_box((190.0, 468.0, 42.0), (5.0, 0.0, -14.0), 9.0)
    undertray = undertray_outer.cut(undertray_inner)
    # Two dry longitudinal throats serve the paired rail/link stacks when the
    # platform drops around the fixed guide mouths.
    for side in (-1, 1):
        undertray = undertray.cut(
            rounded_box((196.0, 54.0, 14.0), (0.0, side * 216.0, -37.0), 1.0)
        )
    # The synchronising shaft crosses the bottom plane only during the final
    # over-centre drop; this is a real guarded service slot, not an overlap
    # allowance.
    undertray = undertray.cut(
        # Carry the service opening through the forward lower return.  Ending
        # it at X=69 mm stranded a 38,098 mm3 cosmetic island as a second
        # solid; extending to X=95 mm removes that disconnected scrap while
        # preserving the rear/side U-shaped structural shell.
        rounded_box((104.0, 404.0, 8.0), (43.0, 0.0, -37.0), 3.0)
    )
    # At the stowed endpoint the invariant body-side no-power paddle sits at
    # world (-460, 0, 108) while the platform datum is (-360, 0, 147).  During
    # the initial down/forward phases its relative centre moves from
    # (-100, 0, -39) through the undertray to (+127, 0, -21).  Reserve that
    # complete 101-pose swept service slot, with two millimetres of dry space,
    # in this same moving B-Rep.  The remaining side rails and rear bridge stay
    # connected; no state-dependent body aperture or overlap is introduced.
    undertray = undertray.cut(
        rounded_box((232.0, 96.0, 60.0), (-16.0, 0.0, -30.0), 10.0)
    )
    return {
        "A08_footrest_top_skin": _single(top, "platform top skin"),
        "A08_footrest_inset_tread": _single(tread, "platform tread"),
        "A08_footrest_perimeter_skin": _single(perimeter, "platform perimeter"),
        "A08_footrest_platform_undertray_monocoque": _single(
            undertray,
            "platform undertray monocoque",
        ),
    }


@lru_cache(maxsize=1)
def _root_monocoque() -> cq.Shape:
    """One fixed U-shaped root cowl, clear of the complete moving envelope."""

    roof = rounded_box(
        (
            ROOT_ROOF_X_LIMITS_MM[1] - ROOT_ROOF_X_LIMITS_MM[0],
            2.0 * ROOT_ROOF_HALF_Y_MM,
            ROOT_ROOF_TOP_Z_MM - ROOT_ROOF_BOTTOM_Z_MM,
        ),
        (
            sum(ROOT_ROOF_X_LIMITS_MM) / 2.0,
            0.0,
            (ROOT_ROOF_TOP_Z_MM + ROOT_ROOF_BOTTOM_Z_MM) / 2.0,
        ),
        5.0,
    )
    legs = [
        rounded_box(
            (63.0, 2.0 * ROOT_LEG_HALF_Y_MM, 96.0),
            (-496.5, side * ROOT_LEG_CENTER_ABS_Y_MM, 106.0),
            5.0,
        )
        for side in (-1, 1)
    ]
    root = roof.fuse(legs[0]).fuse(legs[1])
    return _single(root, "fixed root monocoque")


@lru_cache(maxsize=1)
def _rear_labyrinth_baffle() -> cq.Shape:
    """Return the fixed rear sightline closeout and its guide-mount feet.

    The six-millimetre panel is deliberately behind, rather than in front of,
    the complete moving envelope.  Its two integral feet touch the fixed
    guide housings at Z=94 mm and do not enter their moving rail cavities.
    """

    panel_height = (
        REAR_LABYRINTH_BAFFLE_PANEL_Z_LIMITS_MM[1]
        - REAR_LABYRINTH_BAFFLE_PANEL_Z_LIMITS_MM[0]
    )
    panel = rounded_box(
        (6.0, REAR_LABYRINTH_BAFFLE_PANEL_Y_MM, panel_height),
        (
            REAR_LABYRINTH_BAFFLE_CENTER_X_MM,
            0.0,
            sum(REAR_LABYRINTH_BAFFLE_PANEL_Z_LIMITS_MM) / 2.0,
        ),
        3.0,
    )
    baffle = panel
    for side in (-1, 1):
        # The foot spans Z=94..100 mm: face contact at the guide roof and a
        # two-millimetre structural fuse into the panel above Z=98 mm.
        mounting_foot = rounded_box(
            (6.0, 28.0, 6.0),
            (
                REAR_LABYRINTH_BAFFLE_CENTER_X_MM,
                side * RAIL_ABS_Y_MM,
                97.0,
            ),
            2.5,
        )
        baffle = baffle.fuse(mounting_foot)
    return _single(baffle, "fixed rear labyrinth baffle")


def a08_footrest_root_nose_cutter(clearance_mm: float = 2.0) -> cq.Shape:
    """Return an integration cutter for A01 around the fixed A08 root cowl."""

    clearance_mm = float(clearance_mm)
    if clearance_mm < 0.0:
        raise ValueError("A08 root-nose cutter clearance cannot be negative")
    roof = rounded_box(
        (
            ROOT_ROOF_X_LIMITS_MM[1]
            - ROOT_ROOF_X_LIMITS_MM[0]
            + 2.0 * clearance_mm,
            2.0 * (ROOT_ROOF_HALF_Y_MM + clearance_mm),
            12.0 + 2.0 * clearance_mm,
        ),
        (sum(ROOT_ROOF_X_LIMITS_MM) / 2.0, 0.0, 154.0),
        5.0 + clearance_mm,
    )
    left = rounded_box(
        (
            63.0 + 2.0 * clearance_mm,
            2.0 * (ROOT_LEG_HALF_Y_MM + clearance_mm),
            96.0 + 2.0 * clearance_mm,
        ),
        (-496.5, -ROOT_LEG_CENTER_ABS_Y_MM, 106.0),
        5.0 + clearance_mm,
    )
    right = rounded_box(
        (
            63.0 + 2.0 * clearance_mm,
            2.0 * (ROOT_LEG_HALF_Y_MM + clearance_mm),
            96.0 + 2.0 * clearance_mm,
        ),
        (-496.5, ROOT_LEG_CENTER_ABS_Y_MM, 106.0),
        5.0 + clearance_mm,
    )
    return _single(roof.fuse(left).fuse(right), "root-nose integration cutter")


def a08_footrest_support_host_corridor(
    side: int,
    clearance_mm: float = 1.0,
) -> cq.Shape:
    """Permanent A02 service corridor for one translating support shell.

    A02 is a removable cosmetic carrier, while the A08 support monocoque is a
    conserved moving load-path cover.  The fixed carrier therefore receives
    the complete straight-line swept envelope, hidden behind the continuous
    wheel belt, rather than either part sharing rigid volume at an endpoint.
    """

    if side not in {-1, 1}:
        raise ValueError("A08 support-host corridor side must be -1 or 1")
    clearance_mm = float(clearance_mm)
    if clearance_mm < 1.0:
        raise ValueError("A08 support-host corridor requires at least 1 mm clearance")
    deployed_shift = -float(PRIMARY_CARTRIDGE_TRAVEL_MM)
    xmin = (
        SUPPORT_MONOCOQUE_STOWED_CENTER_X_MM
        - SUPPORT_MONOCOQUE_LENGTH_MM / 2.0
        + deployed_shift
        - clearance_mm
    )
    xmax = (
        SUPPORT_MONOCOQUE_STOWED_CENTER_X_MM
        + SUPPORT_MONOCOQUE_LENGTH_MM / 2.0
        + clearance_mm
    )
    return _single(
        rounded_box(
            (
                xmax - xmin,
                SUPPORT_MONOCOQUE_OUTER_YZ_MM[0] + 2.0 * clearance_mm,
                SUPPORT_MONOCOQUE_OUTER_YZ_MM[1] + 2.0 * clearance_mm,
            ),
            (
                (xmin + xmax) / 2.0,
                side * SUPPORT_MONOCOQUE_ABS_Y_MM,
                SUPPORT_MONOCOQUE_CENTER_Z_MM,
            ),
            11.0,
        ),
        "A02 support-monocoque swept host corridor",
    )


def a08_footrest_drawer_host_corridor(
    clearance_mm: float = 3.0,
) -> cq.Shape:
    """Return the permanent A01 throat for the conserved A08 drawer.

    The platform's largest moving cross-section is the 500 mm-wide perimeter
    skin.  At the stowed endpoint its highest rigid occurrence reaches Z=161
    mm; during deployment the mechanism descends to Z=55 mm while crossing
    the A01 shell's X=-484..-360 mm depth.  A straight, open-bottom throat is
    therefore the physical body aperture: it preserves every moving B-Rep and
    lets the stowed platform itself close the normal sightline.  The default
    adds a real 3 mm dry gap on both sides and above the moving envelope.
    """

    clearance_mm = float(clearance_mm)
    if clearance_mm < 3.0:
        raise ValueError(
            "A08 drawer host corridor may not use less than 3.0 mm dry clearance"
        )
    platform_half_width_mm = 250.0
    crossing_x_limits_mm = (-484.0, -360.0)
    moving_z_limits_mm = (55.0, 161.0)
    xmin = crossing_x_limits_mm[0] - clearance_mm
    xmax = crossing_x_limits_mm[1] + clearance_mm
    zmin = moving_z_limits_mm[0] - clearance_mm
    zmax = moving_z_limits_mm[1] + clearance_mm
    return _single(
        rounded_box(
            (
                xmax - xmin,
                2.0 * (platform_half_width_mm + clearance_mm),
                zmax - zmin,
            ),
            (
                (xmin + xmax) / 2.0,
                0.0,
                (zmin + zmax) / 2.0,
            ),
            2.0,
        ),
        "A01 captured-drawer host corridor",
    )


@lru_cache(maxsize=2)
def _fixed_guide(side: int) -> cq.Shape:
    y_mm = side * RAIL_ABS_Y_MM
    guide = _rectangular_tube_x(
        FIXED_GUIDE_LENGTH_MM,
        FIXED_GUIDE_OUTER_YZ_MM,
        FIXED_GUIDE_INNER_YZ_MM,
        ((FIXED_GUIDE_X_LIMITS_MM[0] + FIXED_GUIDE_X_LIMITS_MM[1]) / 2.0, y_mm, RAIL_SECTION_CENTER_Z_MM),
    )
    guide = guide.cut(
        rounded_box(
            (FIXED_GUIDE_LENGTH_MM + 4.0, 8.0, 10.0),
            (-330.0, side * 203.0, LOWER_CARRIAGE_PIVOT_Z_MM),
            2.0,
        )
    )
    return _cut_vertical_bores(
        guide,
        (STOWED_LOCK_WORLD_X_MM, DEPLOYED_LOCK_WORLD_X_MM),
        y_mm,
    )


def _primary_shift_mm(progress: float) -> float:
    pose = production_footrest_pose(progress)
    # Phase A is accomplished solely by motion of the captured inner rail.
    # The primary cartridge starts its 144 mm stroke only in phase B.
    return -pose.primary_cartridge_travel_mm


@lru_cache(maxsize=2)
def _primary_local(side: int) -> cq.Shape:
    final_shift = _primary_shift_mm(1.0)
    y_mm = side * RAIL_ABS_Y_MM
    primary = _rectangular_tube_x(
        PRIMARY_LENGTH_MM,
        PRIMARY_OUTER_YZ_MM,
        PRIMARY_INNER_YZ_MM,
        (PRIMARY_STOWED_CENTER_X_MM, y_mm, RAIL_SECTION_CENTER_Z_MM),
    )
    primary = primary.cut(
        rounded_box(
            (PRIMARY_LENGTH_MM + 4.0, 7.0, 10.0),
            (PRIMARY_STOWED_CENTER_X_MM, side * 208.0, LOWER_CARRIAGE_PIVOT_Z_MM),
            2.0,
        )
    )
    # One indexed bore locks stow; the second aligns with the fixed deployed
    # station only after the primary cartridge reaches its hard stop.
    return _cut_vertical_bores(
        primary,
        (STOWED_LOCK_WORLD_X_MM, DEPLOYED_LOCK_WORLD_X_MM - final_shift),
        y_mm,
    )


@lru_cache(maxsize=2)
def _inner_local(side: int) -> cq.Shape:
    y_mm = side * RAIL_ABS_Y_MM
    inner = rounded_box(
        (INNER_LENGTH_MM, INNER_OUTER_YZ_MM[0], INNER_OUTER_YZ_MM[1]),
        (INNER_STOWED_CENTER_X_MM, y_mm, RAIL_SECTION_CENTER_Z_MM),
        1.5,
    )
    # The same through-hole aligns with the body-side stowed pin at progress 0
    # and with the body-side deployed pin after the exact final translation.
    inner = _cut_vertical_bores(inner, (STOWED_LOCK_WORLD_X_MM,), y_mm)
    for offset in LINK_X_OFFSETS_MM:
        inner = inner.cut(
            _axis_y_cylinder(
                LINK_BORE_RADIUS_MM,
                26.0,
                (PLATFORM_STOWED_CENTER_MM[0] + offset, y_mm, LOWER_CARRIAGE_PIVOT_Z_MM),
            )
        )
    return _single(inner, "captured inner rail")


@lru_cache(maxsize=2)
def _support_monocoque_local(side: int) -> cq.Shape:
    center = (
        SUPPORT_MONOCOQUE_STOWED_CENTER_X_MM,
        side * SUPPORT_MONOCOQUE_ABS_Y_MM,
        SUPPORT_MONOCOQUE_CENTER_Z_MM,
    )
    outer = rounded_box(
        (SUPPORT_MONOCOQUE_LENGTH_MM, *SUPPORT_MONOCOQUE_OUTER_YZ_MM),
        center,
        4.0,
    )
    # The forward service opening makes the cavity inspectable and keeps this
    # a single shell occurrence rather than a hidden solid ballast proxy.
    cavity = rounded_box(
        (
            SUPPORT_MONOCOQUE_LENGTH_MM - 8.0,
            *SUPPORT_MONOCOQUE_CAVITY_YZ_MM,
        ),
        (center[0] - 6.0, center[1], center[2] - 1.0),
        1.5,
    )
    return _single(outer.cut(cavity), "primary support monocoque")


@lru_cache(maxsize=1)
def _link_local() -> cq.Shape:
    stem = rounded_box(
        (2.0 * LINK_OUTER_RADIUS_MM, LINK_PLATE_THICKNESS_MM, DROP_LINK_LENGTH_MM),
        (0.0, 0.0, 0.0),
        1.4,
    )
    bosses = [
        _axis_y_cylinder(
            LINK_OUTER_RADIUS_MM,
            LINK_PLATE_THICKNESS_MM,
            (0.0, 0.0, end * DROP_LINK_LENGTH_MM / 2.0),
        )
        for end in (-1, 1)
    ]
    link = stem.fuse(bosses[0]).fuse(bosses[1])
    for end in (-1, 1):
        link = link.cut(
            _axis_y_cylinder(
                LINK_BORE_RADIUS_MM,
                LINK_PLATE_THICKNESS_MM + 4.0,
                (0.0, 0.0, end * DROP_LINK_LENGTH_MM / 2.0),
            )
        )
    return _single(link, "drop link")


def _link_shape(
    angle_deg: float,
    midpoint: tuple[float, float, float],
) -> cq.Shape:
    return _link_local().rotate((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), -angle_deg).translate(midpoint)


def _lock_pin_shape(x_mm: float, y_mm: float, engaged: bool) -> cq.Shape:
    z_mm = LOCK_PIN_ENGAGED_CENTER_Z_MM if engaged else LOCK_PIN_RETRACTED_CENTER_Z_MM
    return _single(
        _axis_z_cylinder(LOCK_PIN_RADIUS_MM, LOCK_PIN_LENGTH_MM, (x_mm, y_mm, z_mm)),
        "rail lock pin",
    )


@lru_cache(maxsize=8)
def _lock_witness(x_mm: float, side: int, station: str) -> cq.Shape:
    del station
    return _single(
        rounded_box((10.0, 8.0, 10.0), (x_mm, side * 244.0, 52.0), 2.0),
        "lock witness envelope",
    )


@lru_cache(maxsize=1)
def _fixed_auxiliary_occurrences() -> dict[str, cq.Shape]:
    """Fixed safety, release and sightline-closeout bodies."""

    return {
        "A08_footrest_rear_labyrinth_baffle": _rear_labyrinth_baffle(),
        "A08_foot_zone_interlock_channel_a": _single(
            rounded_box(
                (20.0, 10.0, 16.0),
                (
                    FOOT_ZONE_INTERLOCK_CENTER_X_MM,
                    -FOOT_ZONE_INTERLOCK_ABS_Y_MM,
                    FOOT_ZONE_INTERLOCK_CENTER_Z_MM,
                ),
                3.0,
            ),
            "foot-zone sensor channel A",
        ),
        "A08_foot_zone_interlock_channel_b": _single(
            rounded_box(
                (20.0, 10.0, 16.0),
                (
                    FOOT_ZONE_INTERLOCK_CENTER_X_MM,
                    FOOT_ZONE_INTERLOCK_ABS_Y_MM,
                    FOOT_ZONE_INTERLOCK_CENTER_Z_MM,
                ),
                3.0,
            ),
            "foot-zone sensor channel B",
        ),
        "A08_footrest_counterbalance_cartridge": _single(
            _axis_x_cylinder(7.0, 120.0, (-330.0, 80.0, 35.0)),
            "counterbalance cartridge",
        ),
        "A08_footrest_manual_release_actuator": _single(
            rounded_box((60.0, 18.0, 12.0), (-330.0, 0.0, 35.0), 3.0),
            "manual release actuator",
        ),
        "A08_footrest_manual_release_cable": _single(
            _axis_x_cylinder(2.0, 150.0, (-405.0, 0.0, 48.0)),
            "manual release cable sheath",
        ),
    }


def a08_footrest_drawer_occurrences(
    progress: float,
    configuration: str = "ride",
) -> dict[str, cq.Shape]:
    """Return the complete same-name A08 B-Rep inventory at ``progress``.

    ``configuration`` labels an integration request only; Cafe and Focus may
    optionally use the same motion.  Follow is rejected because its footrest
    is not an authorised deployable state.
    """

    progress = float(progress)
    configuration = str(configuration).lower()
    if configuration not in {"follow", "ride", "cafe", "focus"}:
        raise ValueError("Unknown WorkCore configuration for A08 B-Reps")
    pose = production_footrest_pose(progress)
    platform_translation = pose.platform_center_mm
    primary_shift = _primary_shift_mm(progress)
    inner_shift = pose.lower_carriage_pivot_mm[0] - PLATFORM_STOWED_CENTER_MM[0]

    occurrences: dict[str, cq.Shape] = {
        name: shape.translate(platform_translation)
        for name, shape in _platform_local_shapes().items()
    }
    occurrences["A08_footrest_root_monocoque"] = _root_monocoque()
    occurrences.update(_fixed_auxiliary_occurrences())

    # One shaft occurrence follows the inner carriage without changing its
    # B-Rep.  It lies below and inboard of the rail mouths; the final physical
    # couplers to the paired links remain a proof-load/detail-design item.
    occurrences["A08_footrest_synchronising_cross_shaft"] = _axis_y_cylinder(
        2.5,
        380.0,
        (pose.lower_carriage_pivot_mm[0], 0.0, 58.0),
    )

    for side_name, side in (("left", -1), ("right", 1)):
        occurrences[f"A08_footrest_fixed_guide_housing_{side_name}"] = _fixed_guide(side)
        occurrences[f"A08_footrest_primary_cartridge_{side_name}"] = _primary_local(side).translate((primary_shift, 0.0, 0.0))
        occurrences[f"A08_footrest_captured_inner_rail_{side_name}"] = _inner_local(side).translate((inner_shift, 0.0, 0.0))
        occurrences[f"A08_footrest_support_monocoque_{side_name}"] = _support_monocoque_local(side).translate((primary_shift, 0.0, 0.0))

        link_y = side * LINK_PLATE_ABS_Y_MM
        rail_y = side * RAIL_ABS_Y_MM
        for index, (position_name, x_offset) in enumerate(
            (("front", LINK_X_OFFSETS_MM[0]), ("rear", LINK_X_OFFSETS_MM[1]))
        ):
            lower = (
                pose.lower_carriage_pivot_mm[0] + x_offset,
                link_y,
                pose.lower_carriage_pivot_mm[2],
            )
            upper = (
                pose.upper_platform_pivot_mm[0] + x_offset,
                link_y,
                pose.upper_platform_pivot_mm[2],
            )
            midpoint = tuple((a + b) / 2.0 for a, b in zip(lower, upper))
            prefix = f"A08_footrest_drop_link_{side_name}_{position_name}"
            occurrences[prefix] = _link_shape(
                pose.drop_link_angle_from_vertical_deg,
                midpoint,  # type: ignore[arg-type]
            )
            occurrences[f"{prefix}_lower_bearing"] = _axis_y_annulus(
                BEARING_OUTER_RADIUS_MM,
                BEARING_INNER_RADIUS_MM,
                LINK_PLATE_THICKNESS_MM,
                lower,
            )
            occurrences[f"{prefix}_upper_bearing"] = _axis_y_annulus(
                BEARING_OUTER_RADIUS_MM,
                BEARING_INNER_RADIUS_MM,
                LINK_PLATE_THICKNESS_MM,
                upper,
            )
            lower_pin_y = (link_y + rail_y) / 2.0
            occurrences[f"{prefix}_lower_guarded_pin"] = _axis_y_cylinder(
                JOINT_PIN_RADIUS_MM,
                abs(link_y - rail_y) + 12.0,
                (lower[0], lower_pin_y, lower[2]),
            )
            occurrences[f"{prefix}_upper_guarded_pin"] = _axis_y_cylinder(
                JOINT_PIN_RADIUS_MM,
                10.0,
                upper,
            )

        stowed_engaged = progress <= 1.0e-12
        deployed_engaged = progress >= 1.0 - 1.0e-12
        occurrences[f"A08_footrest_stowed_lock_pin_{side_name}"] = _lock_pin_shape(
            STOWED_LOCK_WORLD_X_MM,
            rail_y,
            stowed_engaged,
        )
        occurrences[f"A08_footrest_deployed_lock_pin_{side_name}"] = _lock_pin_shape(
            DEPLOYED_LOCK_WORLD_X_MM,
            rail_y,
            deployed_engaged,
        )
        occurrences[f"A08_footrest_stowed_lock_witness_{side_name}"] = _lock_witness(
            STOWED_LOCK_WORLD_X_MM,
            side,
            "stowed",
        )
        occurrences[f"A08_footrest_deployed_lock_witness_{side_name}"] = _lock_witness(
            DEPLOYED_LOCK_WORLD_X_MM,
            side,
            "deployed",
        )

    for name, shape in occurrences.items():
        _single(shape, name)
    return occurrences


def _bbox_overlap_volume(a: cq.Shape, b: cq.Shape) -> float:
    aa = a.BoundingBox()
    bb = b.BoundingBox()
    lengths = (
        min(aa.xmax, bb.xmax) - max(aa.xmin, bb.xmin),
        min(aa.ymax, bb.ymax) - max(aa.ymin, bb.ymin),
        min(aa.zmax, bb.zmax) - max(aa.zmin, bb.zmin),
    )
    if min(lengths) <= 0.0:
        return 0.0
    return lengths[0] * lengths[1] * lengths[2]


def _bbox_limits(shape: cq.Shape) -> tuple[float, float, float, float, float, float]:
    box = shape.BoundingBox()
    return (box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax)


def _bbox_limits_overlap(
    a: tuple[float, float, float, float, float, float],
    b: tuple[float, float, float, float, float, float],
) -> bool:
    return bool(
        min(a[1], b[1]) - max(a[0], b[0]) > 1.0e-9
        and min(a[3], b[3]) - max(a[2], b[2]) > 1.0e-9
        and min(a[5], b[5]) - max(a[4], b[4]) > 1.0e-9
    )


def _bbox_limits_distance(
    a: tuple[float, float, float, float, float, float],
    b: tuple[float, float, float, float, float, float],
) -> float:
    """Return the exact Euclidean lower bound between two axis-aligned boxes."""

    dx = max(a[0] - b[1], b[0] - a[1], 0.0)
    dy = max(a[2] - b[3], b[2] - a[3], 0.0)
    dz = max(a[4] - b[5], b[4] - a[5], 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _common_volume(a: cq.Shape, b: cq.Shape) -> float:
    if _bbox_overlap_volume(a, b) <= 1.0e-9:
        return 0.0
    try:
        return max(0.0, a.intersect(b).Volume())
    except Exception:
        return max(0.0, a.common(b).Volume())


def _is_intended_joint_pair(name_a: str, name_b: str) -> bool:
    """Narrow assembly-interface exclusion; never covers platform/support."""

    a, b = sorted((name_a, name_b))
    if a.startswith("A08_footrest_drop_link_"):
        prefix = a.replace("_lower_bearing", "").replace("_upper_bearing", "")
        if b.startswith(prefix) and (
            "bearing" in a
            or "bearing" in b
            or "guarded_pin" in a
            or "guarded_pin" in b
        ):
            return True
    # Link body to its own explicitly replaceable bushing.
    if "drop_link" in a and "bearing" in b:
        base = b.rsplit("_", 2)[0]
        if a == base:
            return True
    # Lower pins pass through a bored captured rail.  No other rail/link pair
    # is excluded, so a support/platform or link/cartridge error still fails.
    if "lower_guarded_pin" in a + b and "captured_inner_rail" in a + b:
        side = "left" if "left" in a else "right" if "right" in a else ""
        return bool(side and side in b)
    if "lock_pin" in a + b and any(
        token in a + b
        for token in ("fixed_guide_housing", "primary_cartridge", "captured_inner_rail")
    ):
        side = "left" if "left" in a else "right" if "right" in a else ""
        return bool(side and side in b)
    if (
        ("upper_bearing" in a + b or "upper_guarded_pin" in a + b)
        and any(
            platform_name in (a, b)
            for platform_name in (
                "A08_footrest_top_skin",
                "A08_footrest_inset_tread",
                "A08_footrest_perimeter_skin",
            )
        )
    ):
        return True
    # These are bonded/contacting layers of one platform, not a hard
    # platform-to-support collision allowance.
    if {a, b} <= {
        "A08_footrest_top_skin",
        "A08_footrest_inset_tread",
        "A08_footrest_perimeter_skin",
    }:
        return True
    return False


def _root_pair_is_analytically_disjoint(
    name_a: str,
    shape_a: cq.Shape,
    name_b: str,
    shape_b: cq.Shape,
) -> bool:
    """Fast exact-envelope certificate for the sparse U-shaped fixed root."""

    root_name = "A08_footrest_root_monocoque"
    if root_name not in (name_a, name_b):
        return False
    moving = shape_b if name_a == root_name else shape_a
    box = moving.BoundingBox()
    # Root roof is z=148..160.  Its inboard legs begin only beyond |Y|=255 mm.
    if box.zmax < ROOT_ROOF_BOTTOM_Z_MM - 1.0e-9 and (
        box.ymin > -(ROOT_LEG_CENTER_ABS_Y_MM - ROOT_LEG_HALF_Y_MM)
        and box.ymax < ROOT_LEG_CENTER_ABS_Y_MM - ROOT_LEG_HALF_Y_MM
    ):
        return True
    if box.xmin >= -465.0 - 1.0e-9 or box.xmax <= -535.0 + 1.0e-9:
        return True
    return False


@lru_cache(maxsize=1)
def a08_normal_floor_human_envelopes() -> dict[str, cq.Shape]:
    """Conservative Cafe/Focus floor-foot and shin B-Rep keep-outs.

    These are mechanism hazard envelopes, not an anthropometric certification.
    Their rear face is 5 mm forward of the stowed platform, so a valid stowed
    state is clear while the authorised forward stroke necessarily enters the
    normally occupied floor zone.
    """

    result: dict[str, cq.Shape] = {}
    for side_name, side in (("left", -1), ("right", 1)):
        result[f"A08_normal_floor_foot_{side_name}"] = _single(
            rounded_box((260.0, 90.0, 90.0), (-600.0, side * 110.0, 45.0), 20.0),
            f"normal floor foot {side_name}",
        )
        result[f"A08_normal_floor_shin_{side_name}"] = _single(
            rounded_box((100.0, 90.0, 360.0), (-520.0, side * 110.0, 260.0), 30.0),
            f"normal floor shin {side_name}",
        )
    return result


def evaluate_a08_rear_labyrinth_sightlines() -> dict[str, object]:
    """Measure the fixed baffle against the formerly open Ride sightlines.

    Thirty-six one-millimetre-diameter horizontal rays span the central 480 mm
    at the four heights which were open through the deployed mechanism.  Ten
    further oblique rays run from a 1,500 mm standing-eye datum to low targets
    immediately behind the baffle.  Every positive intersection is an actual
    B-Rep occlusion rather than a bounding-box or metadata assertion.
    """

    baffle = _rear_labyrinth_baffle()
    ray_radius_mm = 0.5
    ray_length_mm = 650.0
    ray_center_x_mm = -475.0
    ray_results: list[dict[str, float | bool]] = []
    minimum_intercept_x_mm = math.inf
    for y_mm in NORMAL_FRONT_SIGHTLINE_Y_MM:
        for z_mm in NORMAL_FRONT_SIGHTLINE_Z_MM:
            ray = _axis_x_cylinder(
                ray_radius_mm,
                ray_length_mm,
                (ray_center_x_mm, y_mm, z_mm),
            )
            common = ray.intersect(baffle)
            common_volume = max(0.0, common.Volume())
            intercept_x_mm = (
                common.BoundingBox().xlen if common_volume > 1.0e-9 else 0.0
            )
            minimum_intercept_x_mm = min(
                minimum_intercept_x_mm,
                intercept_x_mm,
            )
            ray_results.append(
                {
                    "y_mm": y_mm,
                    "z_mm": z_mm,
                    "common_volume_mm3": common_volume,
                    "intercept_x_mm": intercept_x_mm,
                    "blocked": common_volume > 1.0e-6,
                }
            )

    standing_oblique_results: list[dict[str, float | bool]] = []
    for y_mm in (-240.0, -120.0, 0.0, 120.0, 240.0):
        for target_z_mm in (110.0, 145.0):
            start = (-1000.0, y_mm, 1500.0)
            end = (-200.0, y_mm, target_z_mm)
            ray = _segment_tube(ray_radius_mm, start, end)
            common_volume = max(0.0, ray.intersect(baffle).Volume())
            standing_oblique_results.append(
                {
                    "y_mm": y_mm,
                    "target_z_mm": target_z_mm,
                    "common_volume_mm3": common_volume,
                    "blocked": common_volume > 1.0e-6,
                }
            )

    human_envelopes = a08_normal_floor_human_envelopes()
    human_common = sum(
        _common_volume(baffle, envelope)
        for envelope in human_envelopes.values()
    )
    minimum_human_distance = min(
        baffle.distance(envelope) for envelope in human_envelopes.values()
    )
    guide_interfaces = {
        side_name: {
            "distance_mm": baffle.distance(_fixed_guide(side)),
            "common_volume_mm3": _common_volume(baffle, _fixed_guide(side)),
        }
        for side_name, side in (("left", -1), ("right", 1))
    }

    baffle_signatures = []
    for state in ("follow", "ride", "cafe", "focus"):
        state_baffle = a08_footrest_drawer_occurrences(
            1.0 if state == "ride" else 0.0,
            state,
        )["A08_footrest_rear_labyrinth_baffle"]
        baffle_signatures.append(
            (
                round(state_baffle.Volume(), 6),
                len(state_baffle.Faces()),
                len(state_baffle.Edges()),
                tuple(round(value, 6) for value in _bbox_limits(state_baffle)),
            )
        )

    return {
        "status": "BRep_design_evidence_not_certification",
        "ray_count": len(ray_results),
        "ray_diameter_mm": 2.0 * ray_radius_mm,
        "ray_x_limits_mm": (
            ray_center_x_mm - ray_length_mm / 2.0,
            ray_center_x_mm + ray_length_mm / 2.0,
        ),
        "ray_y_values_mm": NORMAL_FRONT_SIGHTLINE_Y_MM,
        "ray_z_values_mm": NORMAL_FRONT_SIGHTLINE_Z_MM,
        "ray_results": ray_results,
        "all_target_ride_front_sightlines_blocked": all(
            bool(result["blocked"]) for result in ray_results
        ),
        "minimum_baffle_intercept_x_mm": minimum_intercept_x_mm,
        "standing_oblique_ray_count": len(standing_oblique_results),
        "standing_eye_point_xz_mm": (-1000.0, 1500.0),
        "standing_target_x_mm": -200.0,
        "standing_oblique_ray_results": standing_oblique_results,
        "all_standing_oblique_sightlines_blocked": all(
            bool(result["blocked"]) for result in standing_oblique_results
        ),
        "normal_floor_human_common_mm3": human_common,
        "minimum_normal_floor_human_distance_mm": minimum_human_distance,
        "guide_mount_interfaces": guide_interfaces,
        "both_guide_mount_feet_face_contact_without_common": all(
            interface["distance_mm"] <= 1.0e-7
            and interface["common_volume_mm3"] <= 1.0e-6
            for interface in guide_interfaces.values()
        ),
        "same_fixed_baffle_brep_all_four_states": len(set(baffle_signatures)) == 1,
    }


def evaluate_a08_footrest_drawer_brep(samples: int = 101) -> dict[str, object]:
    """Evaluate inventory, solid validity and exact unintended common volume."""

    if samples < 2:
        raise ValueError("A08 B-Rep evaluator requires at least two samples")
    reference = a08_footrest_drawer_occurrences(0.0)
    reference_names = tuple(sorted(reference))
    reference_signature = {
        name: (
            round(shape.Volume(), 6),
            len(shape.Solids()),
            len(shape.Faces()),
            len(shape.Edges()),
        )
        for name, shape in reference.items()
    }
    maximum_moving_common = 0.0
    maximum_moving_fixed_common = 0.0
    worst_pair: tuple[str, str] | None = None
    worst_progress = 0.0
    inventory_ok = True
    rigid_identity_signature_ok = True
    all_single_valid_solids = True
    minimum_root_to_moving_distance = math.inf
    minimum_rear_baffle_to_moving_distance = math.inf
    closest_rear_baffle_moving_occurrence: str | None = None
    closest_rear_baffle_progress = 0.0
    lock_pins_retracted_during_motion = True
    human_envelopes = a08_normal_floor_human_envelopes()
    human_bounds = {
        name: _bbox_limits(shape) for name, shape in human_envelopes.items()
    }
    first_human_hit_progress: float | None = None
    last_human_hit_progress: float | None = None
    maximum_human_common = 0.0
    worst_human_pair: tuple[str, str] | None = None
    worst_human_progress = 0.0

    for index in range(samples):
        progress = index / (samples - 1)
        occurrences = a08_footrest_drawer_occurrences(progress)
        names = tuple(sorted(occurrences))
        # OpenCascade's optimal bounding-box construction is materially more
        # expensive than the sparse Boolean operations in this mechanism.
        # Cache one exact box per rigid occurrence per pose; recomputing it for
        # every pair made the 101-point production audit needlessly quadratic
        # in bounding-box calls without adding evidence.
        pose_bounds = {
            name: _bbox_limits(shape) for name, shape in occurrences.items()
        }

        def pose_common(name_a: str, name_b: str) -> float:
            if not _bbox_limits_overlap(pose_bounds[name_a], pose_bounds[name_b]):
                return 0.0
            try:
                return max(
                    0.0,
                    occurrences[name_a].intersect(occurrences[name_b]).Volume(),
                )
            except Exception:
                return max(
                    0.0,
                    occurrences[name_a].common(occurrences[name_b]).Volume(),
                )

        inventory_ok = inventory_ok and names == reference_names
        for name, shape in occurrences.items():
            all_single_valid_solids = all_single_valid_solids and (
                not shape.isNull()
                and shape.isValid()
                and len(shape.Solids()) == 1
                and shape.Volume() > 0.0
            )
            signature = (
                round(shape.Volume(), 6),
                len(shape.Solids()),
                len(shape.Faces()),
                len(shape.Edges()),
            )
            rigid_identity_signature_ok = (
                rigid_identity_signature_ok
                and signature == reference_signature[name]
            )

        moving_names = [name for name in names if name not in FIXED_OCCURRENCE_NAMES]
        fixed_names = [name for name in names if name in FIXED_OCCURRENCE_NAMES]
        for name_a, name_b in itertools.combinations(moving_names, 2):
            if _is_intended_joint_pair(name_a, name_b):
                continue
            if _root_pair_is_analytically_disjoint(
                name_a,
                occurrences[name_a],
                name_b,
                occurrences[name_b],
            ):
                continue
            common = pose_common(name_a, name_b)
            if common > maximum_moving_common:
                maximum_moving_common = common
                worst_pair = (name_a, name_b)
                worst_progress = progress
        for moving_name in moving_names:
            for fixed_name in fixed_names:
                moving = occurrences[moving_name]
                fixed = occurrences[fixed_name]
                if fixed_name == "A08_footrest_root_monocoque":
                    minimum_root_to_moving_distance = min(
                        minimum_root_to_moving_distance,
                        moving.distance(fixed),
                    )
                if fixed_name == "A08_footrest_rear_labyrinth_baffle":
                    bbox_distance = _bbox_limits_distance(
                        pose_bounds[moving_name],
                        pose_bounds[fixed_name],
                    )
                    if bbox_distance <= minimum_rear_baffle_to_moving_distance + 1.0e-9:
                        exact_distance = moving.distance(fixed)
                        if exact_distance < minimum_rear_baffle_to_moving_distance:
                            minimum_rear_baffle_to_moving_distance = exact_distance
                            closest_rear_baffle_moving_occurrence = moving_name
                            closest_rear_baffle_progress = progress
                if _is_intended_joint_pair(moving_name, fixed_name):
                    continue
                if _root_pair_is_analytically_disjoint(
                    moving_name,
                    moving,
                    fixed_name,
                    fixed,
                ):
                    continue
                common = pose_common(moving_name, fixed_name)
                maximum_moving_fixed_common = max(
                    maximum_moving_fixed_common,
                    common,
                )

        if 0 < index < samples - 1:
            for side_name in ("left", "right"):
                guide = occurrences[f"A08_footrest_fixed_guide_housing_{side_name}"]
                primary = occurrences[f"A08_footrest_primary_cartridge_{side_name}"]
                inner = occurrences[f"A08_footrest_captured_inner_rail_{side_name}"]
                for station in ("stowed", "deployed"):
                    pin = occurrences[f"A08_footrest_{station}_lock_pin_{side_name}"]
                    fully_below_guide = (
                        pin.BoundingBox().zmax
                        <= guide.BoundingBox().zmin - 1.9
                    )
                    no_rail_common = all(
                        pose_common(
                            f"A08_footrest_{station}_lock_pin_{side_name}",
                            rail_name,
                        )
                        <= 1.0e-6
                        for rail_name in (
                            f"A08_footrest_fixed_guide_housing_{side_name}",
                            f"A08_footrest_primary_cartridge_{side_name}",
                            f"A08_footrest_captured_inner_rail_{side_name}",
                        )
                    )
                    lock_pins_retracted_during_motion = (
                        lock_pins_retracted_during_motion
                        and fully_below_guide
                        and no_rail_common
                    )

        pose_human_common = 0.0
        for moving_name in moving_names:
            moving = occurrences[moving_name]
            for human_name, human in human_envelopes.items():
                if not _bbox_limits_overlap(
                    pose_bounds[moving_name], human_bounds[human_name]
                ):
                    common = 0.0
                else:
                    try:
                        common = max(0.0, moving.intersect(human).Volume())
                    except Exception:
                        common = max(0.0, moving.common(human).Volume())
                pose_human_common += common
                if common > maximum_human_common:
                    maximum_human_common = common
                    worst_human_pair = (moving_name, human_name)
                    worst_human_progress = progress
        if pose_human_common > 1.0e-6:
            if first_human_hit_progress is None:
                first_human_hit_progress = progress
            last_human_hit_progress = progress

    def endpoint_lock_engaged(
        endpoint: dict[str, cq.Shape],
        station: str,
        side_name: str,
    ) -> bool:
        pin = endpoint[f"A08_footrest_{station}_lock_pin_{side_name}"]
        guide = endpoint[f"A08_footrest_fixed_guide_housing_{side_name}"]
        primary = endpoint[f"A08_footrest_primary_cartridge_{side_name}"]
        inner = endpoint[f"A08_footrest_captured_inner_rail_{side_name}"]
        pin_box = pin.BoundingBox()
        guide_box = guide.BoundingBox()
        axial_engagement = (
            pin_box.zmin < guide_box.zmax - 1.0
            and pin_box.zmax > guide_box.zmin + 1.0
        )
        radial_bore_gaps = [pin.distance(rail) for rail in (guide, primary, inner)]
        return bool(
            axial_engagement
            and all(0.0 < gap <= LOCK_BORE_RADIUS_MM - LOCK_PIN_RADIUS_MM + 1.0e-5 for gap in radial_bore_gaps)
            and all(_common_volume(pin, rail) <= 1.0e-6 for rail in (guide, primary, inner))
        )

    stowed_occurrences = a08_footrest_drawer_occurrences(0.0)
    deployed_occurrences = a08_footrest_drawer_occurrences(1.0)
    stowed_locks_engaged = all(
        endpoint_lock_engaged(stowed_occurrences, "stowed", side)
        for side in ("left", "right")
    )
    deployed_locks_engaged = all(
        endpoint_lock_engaged(deployed_occurrences, "deployed", side)
        for side in ("left", "right")
    )
    four_state_inventory_ok = all(
        tuple(sorted(a08_footrest_drawer_occurrences(0.0, state)))
        == reference_names
        for state in ("follow", "ride", "cafe", "focus")
    )

    stowed = production_footrest_pose(0.0)
    clear = production_footrest_pose(0.1)
    deployed = production_footrest_pose(1.0)
    result = {
        "status": "BRep_design_evidence_not_certification",
        "samples": samples,
        "occurrence_count": len(reference_names),
        "occurrence_names": reference_names,
        "same_occurrence_inventory_all_poses": inventory_ok,
        "same_occurrence_inventory_all_four_states": four_state_inventory_ok,
        "all_occurrences_single_valid_solids": all_single_valid_solids,
        "rigid_occurrence_volume_topology_signature_constant": rigid_identity_signature_ok,
        "maximum_unintended_moving_vs_moving_common_mm3": maximum_moving_common,
        "maximum_moving_vs_fixed_common_mm3": maximum_moving_fixed_common,
        "worst_moving_pair": worst_pair,
        "worst_moving_pair_progress": worst_progress,
        "minimum_root_to_moving_distance_mm": minimum_root_to_moving_distance,
        "minimum_rear_labyrinth_baffle_to_moving_distance_mm": (
            minimum_rear_baffle_to_moving_distance
        ),
        "closest_rear_labyrinth_baffle_moving_occurrence": (
            closest_rear_baffle_moving_occurrence
        ),
        "closest_rear_labyrinth_baffle_progress": closest_rear_baffle_progress,
        "stowed_platform_center_mm": stowed.platform_center_mm,
        "clear_platform_center_mm": clear.platform_center_mm,
        "deployed_platform_center_mm": deployed.platform_center_mm,
        "clear_tread_highest_z_mm": clear.platform_center_mm[2] + PLATFORM_REFERENCE_TO_TOP_MM,
        "root_roof_bottom_z_mm": ROOT_ROOF_BOTTOM_Z_MM,
        "deployed_primary_shift_mm": _primary_shift_mm(1.0),
        "deployed_inner_shift_mm": deployed.lower_carriage_pivot_mm[0] - PLATFORM_STOWED_CENTER_MM[0],
        "link_pin_length_mm": DROP_LINK_LENGTH_MM,
        "lock_pins_retracted_during_motion": lock_pins_retracted_during_motion,
        "stowed_lock_pins_geometrically_engaged": stowed_locks_engaged,
        "deployed_lock_pins_geometrically_engaged": deployed_locks_engaged,
        "physical_foot_zone_sensors_present": all(
            name in reference
            for name in (
                "A08_foot_zone_interlock_channel_a",
                "A08_foot_zone_interlock_channel_b",
            )
        ),
        "normal_floor_foot_and_shin_sweep_is_hazard": True,
        "two_channel_fail_closed_interlock_required": True,
        "independent_sensor_detection_volume_coverage_validated": False,
        "sensor_sightline_nose_and_footrest_occlusion_validated": False,
        "foot_zone_interlock_safety_function_established": False,
        "human_swept_volume_clearance_pass": maximum_human_common <= 1.0e-6,
        "human_envelope_count": len(human_envelopes),
        "first_human_brep_hit_progress": first_human_hit_progress,
        "last_human_brep_hit_progress": last_human_hit_progress,
        "maximum_single_pair_human_common_mm3": maximum_human_common,
        "worst_human_pair": worst_human_pair,
        "worst_human_pair_progress": worst_human_progress,
        "platform_geometry_role": (
            "top and tread are the exact final B-Reps; the motion perimeter is a "
            "conservative solid superset of the final rear-service-throat B-Rep; "
            "integration proves exact equality or set containment, not bbox equality"
        ),
        "release_ready": False,
        "open_evidence": (
            "complete tolerance-stack swept clearance",
            "body/human/ground adaptive swept-volume integration",
            "proof load, fatigue, contamination and pinch tests",
            "two-channel electrical lock witness validation",
            "independent foot-zone sensor detection-volume coverage and occlusion validation",
        ),
    }
    result["brep_contract_pass"] = bool(
        inventory_ok
        and four_state_inventory_ok
        and all_single_valid_solids
        and rigid_identity_signature_ok
        and maximum_moving_common <= 1.0e-6
        and maximum_moving_fixed_common <= 1.0e-6
        and minimum_rear_baffle_to_moving_distance
        >= REAR_LABYRINTH_BAFFLE_MINIMUM_DRY_GAP_MM - 1.0e-6
        and lock_pins_retracted_during_motion
        and stowed_locks_engaged
        and deployed_locks_engaged
        and result["clear_tread_highest_z_mm"] <= ROOT_ROOF_BOTTOM_Z_MM - 5.0 + 1.0e-6
    )
    return result


def evaluate_a08_fixed_host_clearance(
    fixed_host: cq.Shape,
    samples: int = 101,
) -> dict[str, object]:
    """Sweep every moving A08 solid against one final fixed host B-Rep.

    The caller owns the final A01 nose definition.  Keeping it as an explicit
    argument avoids a circular dependency while ensuring the release gate
    checks the actual post-partition production host rather than a surrogate.
    """

    if samples < 2:
        raise ValueError("A08 fixed-host evaluator requires at least two samples")
    if fixed_host.isNull() or not fixed_host.isValid():
        raise ValueError("A08 fixed-host evaluator received an invalid host")
    host_bounds = _bbox_limits(fixed_host)
    maximum_common = 0.0
    worst_name: str | None = None
    worst_progress = 0.0
    hit_samples: list[dict[str, object]] = []
    for index in range(samples):
        progress = index / (samples - 1)
        occurrences = a08_footrest_drawer_occurrences(progress)
        sample_hits: list[dict[str, object]] = []
        for name, moving in occurrences.items():
            if name in FIXED_OCCURRENCE_NAMES:
                continue
            if not _bbox_limits_overlap(_bbox_limits(moving), host_bounds):
                continue
            try:
                common = max(0.0, moving.intersect(fixed_host).Volume())
            except Exception:
                common = max(0.0, moving.common(fixed_host).Volume())
            if common > 1.0e-6:
                sample_hits.append(
                    {"moving_occurrence": name, "common_volume_mm3": common}
                )
                if common > maximum_common:
                    maximum_common = common
                    worst_name = name
                    worst_progress = progress
        if sample_hits:
            hit_samples.append(
                {"progress": progress, "interferences": sample_hits}
            )
    return {
        "samples": samples,
        "actual_final_host_brep_used": True,
        "maximum_moving_vs_fixed_host_common_mm3": maximum_common,
        "worst_moving_occurrence": worst_name,
        "worst_progress": worst_progress,
        "hit_samples": hit_samples,
        "pass": maximum_common <= 1.0e-6,
    }


def evaluate_a08_final_body_interfaces(
    body_side_release_shell: cq.Shape,
    support_hosts: Mapping[str, cq.Shape],
    samples: int = 101,
) -> dict[str, object]:
    """Sweep the final undertray/supports against their actual fixed hosts.

    This closes two integration gaps which an A08-only mechanism audit cannot
    see: the invariant body-side release shell crosses the undertray's inverse
    path during the initial drop, and each translating support passes through
    the removable A02 cosmetic carrier.  All supplied shapes are final B-Reps;
    no proxy boxes or endpoint-only comparisons are accepted here.
    """

    if samples < 2:
        raise ValueError("A08 final-body evaluator requires at least two samples")
    if set(support_hosts) != {"left", "right"}:
        raise ValueError("A08 final-body evaluator requires left/right A02 hosts")
    supplied = (body_side_release_shell, *support_hosts.values())
    if any(shape.isNull() or not shape.isValid() for shape in supplied):
        raise ValueError("A08 final-body evaluator received an invalid host B-Rep")

    release_bounds = _bbox_limits(body_side_release_shell)
    host_bounds = {
        side: _bbox_limits(shape) for side, shape in support_hosts.items()
    }
    maximum_release_common = 0.0
    minimum_release_gap = math.inf
    worst_release_progress = 0.0
    closest_release_progress = 0.0
    maximum_support_common = 0.0
    minimum_support_gap = math.inf
    worst_support: tuple[str, float] | None = None
    closest_support: tuple[str, float] | None = None

    for index in range(samples):
        progress = index / (samples - 1)
        occurrences = a08_footrest_drawer_occurrences(progress)
        undertray = occurrences["A08_footrest_platform_undertray_monocoque"]
        undertray_bounds = _bbox_limits(undertray)
        release_common = (
            _common_volume(undertray, body_side_release_shell)
            if _bbox_limits_overlap(undertray_bounds, release_bounds)
            else 0.0
        )
        release_bbox_gap = _bbox_limits_distance(
            undertray_bounds,
            release_bounds,
        )
        if release_bbox_gap <= minimum_release_gap + 1.0e-9:
            release_gap = float(undertray.distance(body_side_release_shell))
            if release_gap < minimum_release_gap:
                minimum_release_gap = release_gap
                closest_release_progress = progress
        if release_common > maximum_release_common:
            maximum_release_common = release_common
            worst_release_progress = progress

        for side in ("left", "right"):
            support = occurrences[f"A08_footrest_support_monocoque_{side}"]
            support_bounds = _bbox_limits(support)
            host = support_hosts[side]
            common = (
                _common_volume(support, host)
                if _bbox_limits_overlap(support_bounds, host_bounds[side])
                else 0.0
            )
            bbox_gap = _bbox_limits_distance(support_bounds, host_bounds[side])
            if bbox_gap <= minimum_support_gap + 1.0e-9:
                gap = float(support.distance(host))
                if gap < minimum_support_gap:
                    minimum_support_gap = gap
                    closest_support = (side, progress)
            if common > maximum_support_common:
                maximum_support_common = common
                worst_support = (side, progress)

    return {
        "samples": samples,
        "actual_final_body_side_release_brep_used": True,
        "actual_final_a02_host_breps_used": True,
        "maximum_undertray_to_body_release_common_mm3": maximum_release_common,
        "minimum_undertray_to_body_release_gap_mm": minimum_release_gap,
        "worst_undertray_release_progress": worst_release_progress,
        "closest_undertray_release_progress": closest_release_progress,
        "maximum_support_to_a02_host_common_mm3": maximum_support_common,
        "minimum_support_to_a02_host_gap_mm": minimum_support_gap,
        "worst_support_host_pair": worst_support,
        "closest_support_host_pair": closest_support,
        "pass": bool(
            maximum_release_common <= 1.0e-6
            and minimum_release_gap >= 2.0 - 1.0e-6
            and maximum_support_common <= 1.0e-6
            and minimum_support_gap >= 1.0 - 1.0e-6
        ),
    }


def evaluate_a08_retained_running_gear_clearance(
    front_tyres: Mapping[str, cq.Shape],
    suspension_rockers: Mapping[str, cq.Shape],
    samples: int = 101,
    rocker_angles_deg: tuple[float, ...] = (-10.0, -5.0, 0.0, 5.0, 10.0),
    minimum_tyre_clearance_mm: float = 12.0,
    minimum_rocker_clearance_mm: float = 3.0,
) -> dict[str, object]:
    """Prove every A08 occurrence clears retained front running gear.

    The controlled tyre and suspension-rocker STEP solids are not members of
    the A08 mechanism inventory, so an A08-only self-collision audit cannot see
    them.  This evaluator checks the complete 48-occurrence A08 inventory at
    every requested motion sample against both front tyres and the five
    controlled rocker articulation angles.  A disjoint bounding-box distance
    is a rigorous lower bound; whenever it falls below a required clearance,
    the actual OCC distance/common operation is used instead.  No occurrence
    name or contact allowlist is accepted.
    """

    if samples < 2:
        raise ValueError("A08 running-gear evaluator requires at least two samples")
    if set(front_tyres) != {"left", "right"}:
        raise ValueError("A08 running-gear evaluator requires left/right front tyres")
    if set(suspension_rockers) != {"left", "right"}:
        raise ValueError("A08 running-gear evaluator requires left/right rockers")
    if not rocker_angles_deg:
        raise ValueError("A08 running-gear evaluator requires rocker angles")
    supplied = (*front_tyres.values(), *suspension_rockers.values())
    if any(shape.isNull() or not shape.isValid() for shape in supplied):
        raise ValueError("A08 running-gear evaluator received an invalid B-Rep")

    tyre_bounds = {side: _bbox_limits(shape) for side, shape in front_tyres.items()}
    rocker_sweeps = {
        side: {
            angle: (
                shape
                if abs(angle) <= 1.0e-12
                else shape.rotate(
                    (-100.0, 0.0, 125.0),
                    (-100.0, 1.0, 125.0),
                    angle,
                )
            )
            for angle in rocker_angles_deg
        }
        for side, shape in suspension_rockers.items()
    }
    rocker_bounds = {
        side: {angle: _bbox_limits(shape) for angle, shape in sweeps.items()}
        for side, sweeps in rocker_sweeps.items()
    }

    minimum_tyre_gap = math.inf
    minimum_rocker_gap = math.inf
    maximum_tyre_common = 0.0
    maximum_rocker_common = 0.0
    closest_tyre_pair: tuple[str, str, float] | None = None
    closest_rocker_pair: tuple[str, str, float, float] | None = None
    exact_distance_evaluations = 0
    pair_evaluations = 0
    reference_lateral_bounds: dict[str, tuple[float, float]] = {}
    lateral_bounds_invariant = True

    for index in range(samples):
        progress = index / (samples - 1)
        occurrences = a08_footrest_drawer_occurrences(progress)
        for name, occurrence in occurrences.items():
            occurrence_bounds = _bbox_limits(occurrence)
            lateral_bounds = (occurrence_bounds[2], occurrence_bounds[3])
            if name not in reference_lateral_bounds:
                reference_lateral_bounds[name] = lateral_bounds
            else:
                lateral_bounds_invariant = lateral_bounds_invariant and all(
                    abs(actual - reference) <= 1.0e-6
                    for actual, reference in zip(
                        lateral_bounds,
                        reference_lateral_bounds[name],
                    )
                )
            for side in ("left", "right"):
                pair_evaluations += 1
                tyre_bbox_gap = _bbox_limits_distance(
                    occurrence_bounds,
                    tyre_bounds[side],
                )
                if tyre_bbox_gap < minimum_tyre_clearance_mm:
                    exact_distance_evaluations += 1
                    tyre_gap = float(occurrence.distance(front_tyres[side]))
                    tyre_common = (
                        _common_volume(occurrence, front_tyres[side])
                        if _bbox_limits_overlap(occurrence_bounds, tyre_bounds[side])
                        else 0.0
                    )
                else:
                    tyre_gap = tyre_bbox_gap
                    tyre_common = 0.0
                if tyre_gap < minimum_tyre_gap:
                    minimum_tyre_gap = tyre_gap
                    closest_tyre_pair = (side, name, progress)
                maximum_tyre_common = max(maximum_tyre_common, tyre_common)

                for angle in rocker_angles_deg:
                    pair_evaluations += 1
                    target = rocker_sweeps[side][angle]
                    target_bounds = rocker_bounds[side][angle]
                    rocker_bbox_gap = _bbox_limits_distance(
                        occurrence_bounds,
                        target_bounds,
                    )
                    if rocker_bbox_gap < minimum_rocker_clearance_mm:
                        exact_distance_evaluations += 1
                        rocker_gap = float(occurrence.distance(target))
                        rocker_common = (
                            _common_volume(occurrence, target)
                            if _bbox_limits_overlap(occurrence_bounds, target_bounds)
                            else 0.0
                        )
                    else:
                        rocker_gap = rocker_bbox_gap
                        rocker_common = 0.0
                    if rocker_gap < minimum_rocker_gap:
                        minimum_rocker_gap = rocker_gap
                        closest_rocker_pair = (side, name, progress, angle)
                    maximum_rocker_common = max(
                        maximum_rocker_common,
                        rocker_common,
                    )

    return {
        "samples": samples,
        "occurrence_count_per_pose": len(a08_footrest_drawer_occurrences(0.0)),
        "rocker_angles_deg": rocker_angles_deg,
        "pair_evaluations": pair_evaluations,
        "exact_distance_evaluations": exact_distance_evaluations,
        "minimum_front_tyre_clearance_mm": minimum_tyre_gap,
        "required_front_tyre_clearance_mm": minimum_tyre_clearance_mm,
        "maximum_front_tyre_common_mm3": maximum_tyre_common,
        "closest_front_tyre_pair": closest_tyre_pair,
        "minimum_rocker_sweep_clearance_mm": minimum_rocker_gap,
        "required_rocker_sweep_clearance_mm": minimum_rocker_clearance_mm,
        "maximum_rocker_sweep_common_mm3": maximum_rocker_common,
        "closest_rocker_sweep_pair": closest_rocker_pair,
        "bbox_separation_used_as_rigorous_lower_bound": True,
        "motion_axis_contract": "translations_in_xz_and_rotations_about_y_only",
        "lateral_bounds_invariant_across_sampled_endpoints": lateral_bounds_invariant,
        "collision_allowlist_permitted": False,
        "pass": bool(
            lateral_bounds_invariant
            and maximum_tyre_common <= 1.0e-6
            and minimum_tyre_gap >= minimum_tyre_clearance_mm - 1.0e-6
            and maximum_rocker_common <= 1.0e-6
            and minimum_rocker_gap >= minimum_rocker_clearance_mm - 1.0e-6
        ),
    }


__all__ = [
    "FIXED_OCCURRENCE_NAMES",
    "a08_footrest_drawer_host_corridor",
    "a08_footrest_drawer_occurrences",
    "a08_footrest_root_nose_cutter",
    "a08_footrest_support_host_corridor",
    "a08_normal_floor_human_envelopes",
    "evaluate_a08_final_body_interfaces",
    "evaluate_a08_footrest_drawer_brep",
    "evaluate_a08_fixed_host_clearance",
    "evaluate_a08_rear_labyrinth_sightlines",
    "evaluate_a08_retained_running_gear_clearance",
]
