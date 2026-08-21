"""Shared V8 differential-wheel half-wrap release contract.

The production exterior covers the complete upper tyre crown, hub and drive,
but it must not turn the wheel into either a fully exposed black disc or a
nearly solid body-colour end plate.  The wheel axis at ``z=125 mm`` is the
single visual boundary: the lower tyre half remains readable from both the
side elevation and the front/rear axle views, while the enclosure closes
immediately above that datum.  These constants are consumed by the geometry,
independent validator and executable release gates so the word "half-wrap"
cannot drift back into a token contact-band opening.
"""

from __future__ import annotations


# The controlled tyre is 250 mm high at rest and its axis is the half-wrap
# datum.  Side probes are offset longitudinally from the hub service island so
# they sample the actual tyre opening, not the deliberately covered hub.
WHEEL_AXIS_Z_MM = 125.0
WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM = WHEEL_AXIS_Z_MM
WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM = (-80.0, 80.0)
WHEEL_SIDE_OPEN_PROBE_Z_MM = 110.0
WHEEL_SIDE_CLOSED_PROBE_Z_MM = 150.0

# Positive tyre witnesses make the release proof optical as well as
# subtractive.  Each tuple is ``(longitudinal offset from the axle, world Z)``
# and traces the lower semicircle outside the deliberately opaque hub island.
# A compliant gate must find controlled tyre material at every point *and* a
# clear outward ray from the tyre sidewall to the Class-A exterior.  Merely
# leaving two small holes in the belt can therefore no longer pass.
WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM = (
    (-92.0, 40.0),
    (92.0, 40.0),
    (-80.0, 70.0),
    (80.0, 70.0),
    (-100.0, 105.0),
    (100.0, 105.0),
)

# Front/rear transverse returns use the same axis-height boundary.  A coverage
# grid above it prevents a token eyebrow from masquerading as an upper wrap.
WHEEL_END_RETURN_LOWER_EDGE_Z_MM = WHEEL_AXIS_Z_MM
WHEEL_END_OPEN_PROBE_Z_MM = 110.0
WHEEL_END_CLOSED_PROBE_Z_MM = 150.0
WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM = (-28.0, 0.0, 28.0)
WHEEL_END_COVERAGE_PROBE_Z_MM = (150.0, 210.0, 270.0)
# Front/rear lower-half witnesses use a 3 x 3 grid.  The gate proves that the
# first physical object behind every outward axial ray is the controlled tyre,
# not studio background visible through a token slit.
WHEEL_END_LOWER_TYRE_WITNESS_LATERAL_OFFSETS_MM = (-28.0, 0.0, 28.0)
WHEEL_END_LOWER_TYRE_WITNESS_Z_MM = (40.0, 90.0, 110.0)
WHEEL_END_VISUAL_SKIN_THICKNESS_MM = 1.0
WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM = 0.1
WHEEL_END_VISUAL_SKIN_Y_SPAN_MM = 88.6
WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM = (126.0, 314.0)

# Existing V8 production-intent packaging limits.
WHEEL_MINIMUM_SWEPT_CLEARANCE_MM = 15.5
WHEEL_NOMINAL_PRODUCT_WIDTH_MM = 750.8
WHEEL_PRODUCTION_WIDTH_LIMIT_MM = 752.0
WHEEL_BELT_NOMINAL_WALL_THICKNESS_MM = 1.9

# The controlled suspension is a bilateral rocker rotating about the Y axis.
# Hub, axle-end cap and its opaque backing are one kinematic family; treating
# the cap as fixed exposes the hub at the negative articulation endpoint.
WHEEL_ROCKER_PIVOT_MM = (-100.0, 0.0, WHEEL_AXIS_Z_MM)
WHEEL_ARTICULATION_POSE_ANGLES_DEG = (-10.0, -5.0, 0.0, 5.0, 10.0)
WHEEL_AXLE_X_MM = (("front", -380.0), ("rear", 180.0))

# Small moving service island retained from the resolved V8 appearance.  The
# shell opening is one smooth rounded sweep envelope; the former five-panel
# boolean union produced pointed lobes below the tyre and is not a releasable
# Class-A boundary.  A shallow dished TPE diaphragm keeps its moving collar on
# the backing while its fixed edge rolls inboard to a carrier return fused into
# the continuous belt.  No separate mud flap or dangling membrane is allowed.
WHEEL_HUB_CAP_PLAN_XZ_MM = (108.0, 104.0)
WHEEL_HUB_CAP_THICKNESS_Y_MM = 1.2
WHEEL_HUB_CAP_ABS_Y_MM = 374.9
WHEEL_HUB_BACKING_PLAN_XZ_MM = (109.6, 105.6)
WHEEL_HUB_BACKING_THICKNESS_Y_MM = 0.8
WHEEL_HUB_BACKING_ABS_Y_MM = 373.9
WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM = 2.0
WHEEL_HUB_FIXED_APERTURE_CUTTER_THICKNESS_Y_MM = 12.0
WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM = 374.45
WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM = (130.0, 224.0)
WHEEL_HUB_FIXED_APERTURE_CORNER_RADIUS_MM = 46.0
# Magnitude of the chord-envelope shift *toward the rocker pivot*.  Front and
# rear axle stations therefore apply opposite world-X signs; treating this as
# an unconditional +X offset places the rear carrier eight millimetres away
# from its true swept centre and collapses endpoint running-gear clearance.
WHEEL_HUB_SWEEP_ENVELOPE_CENTER_X_OFFSET_MM = 4.0
WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM = (106.0, 102.0)
WHEEL_HUB_GAITER_FIXED_EDGE_OVERLAP_MM = 8.0
WHEEL_HUB_GAITER_THICKNESS_Y_MM = 0.4
WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM = (139.4, 232.8)
WHEEL_HUB_GAITER_FIXED_EDGE_CORNER_RADIUS_MM = 50.0
WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM = 361.2
WHEEL_HUB_GAITER_MOVING_COLLAR_PLAN_XZ_MM = (112.0, 108.0)
WHEEL_HUB_GAITER_MOVING_COLLAR_CORNER_RADIUS_MM = 20.0
WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM = 373.5
WHEEL_HUB_GAITER_MOVING_VOID_ABS_Y_MM = 373.7
WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM = (132.0, 226.0)
WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3 = 0.05
WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3 = 0.01
WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM = 14.0
# The dished TPE field may run one millimetre closer than the rigid cap and
# carrier, but still retains a thirteen-millimetre non-contact envelope at all
# five released rocker poses.  This is not a collision waiver: common volume
# remains exactly zero and the measured distance is reported pose by pose.
WHEEL_HUB_FLEXIBLE_RUNNING_GEAR_MIN_CLEARANCE_MM = 13.0


def _validate_contract() -> None:
    """Fail fast if a later edit collapses the half-wrap contract."""

    if not (
        0.0
        < WHEEL_SIDE_OPEN_PROBE_Z_MM
        < WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM
        < WHEEL_SIDE_CLOSED_PROBE_Z_MM
    ):
        raise ValueError("Invalid V8 wheel side half-wrap probe ordering")
    if not (
        WHEEL_END_OPEN_PROBE_Z_MM
        < WHEEL_END_RETURN_LOWER_EDGE_Z_MM
        < WHEEL_END_CLOSED_PROBE_Z_MM
    ):
        raise ValueError("Invalid V8 wheel-end half-wrap probe ordering")
    if abs(WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM - WHEEL_AXIS_Z_MM) > 1.0e-9:
        raise ValueError("V8 side half-wrap boundary must remain on the wheel axis")
    if abs(WHEEL_END_RETURN_LOWER_EDGE_Z_MM - WHEEL_AXIS_Z_MM) > 1.0e-9:
        raise ValueError("V8 wheel-end half-wrap boundary must remain on the axis")
    if len(WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM) < 2:
        raise ValueError("V8 side reveal requires witnesses on both sides of the hub")
    if len(WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM) < 5:
        raise ValueError("V8 side reveal requires a real lower-tyre witness arc")
    if any(
        not (0.0 <= z_mm < WHEEL_AXIS_Z_MM)
        for _, z_mm in WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM
    ):
        raise ValueError("V8 side tyre witnesses must remain below the wheel axis")
    if WHEEL_END_CLOSED_PROBE_Z_MM not in WHEEL_END_COVERAGE_PROBE_Z_MM:
        raise ValueError("V8 wheel end-closed datum must be part of the coverage grid")
    if any(
        z_mm < WHEEL_END_RETURN_LOWER_EDGE_Z_MM
        for z_mm in WHEEL_END_COVERAGE_PROBE_Z_MM
    ):
        raise ValueError("V8 wheel end coverage probes must stay above the axis")
    if (
        len(WHEEL_END_LOWER_TYRE_WITNESS_LATERAL_OFFSETS_MM) < 3
        or len(WHEEL_END_LOWER_TYRE_WITNESS_Z_MM) < 3
        or any(
            not (0.0 < z_mm < WHEEL_AXIS_Z_MM)
            for z_mm in WHEEL_END_LOWER_TYRE_WITNESS_Z_MM
        )
    ):
        raise ValueError("V8 wheel-end lower tyre proof requires a 3 x 3 grid")
    if not (
        WHEEL_END_VISUAL_SKIN_THICKNESS_MM > 0.0
        and 0.0 <= WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM < 1.0
        and WHEEL_END_VISUAL_SKIN_Y_SPAN_MM
        > 2.0
        * max(
            abs(offset)
            for offset in WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM
        )
        and WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM[0]
        > WHEEL_END_RETURN_LOWER_EDGE_Z_MM
        and WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM[1]
        >= max(WHEEL_END_COVERAGE_PROBE_Z_MM)
    ):
        raise ValueError(
            "Invalid V8 body-colour wheel-end visual-occlusion skin contract"
        )
    if WHEEL_NOMINAL_PRODUCT_WIDTH_MM > WHEEL_PRODUCTION_WIDTH_LIMIT_MM:
        raise ValueError("V8 nominal wheel-belt width exceeds its production limit")
    if WHEEL_ARTICULATION_POSE_ANGLES_DEG != (-10.0, -5.0, 0.0, 5.0, 10.0):
        raise ValueError("V8 wheel articulation gate must retain five released poses")
    if len({name for name, _ in WHEEL_AXLE_X_MM}) != 2:
        raise ValueError("V8 wheel contract requires front and rear axle stations")
    if not (
        WHEEL_HUB_CAP_PLAN_XZ_MM[0] < WHEEL_HUB_BACKING_PLAN_XZ_MM[0]
        and WHEEL_HUB_CAP_PLAN_XZ_MM[1] < WHEEL_HUB_BACKING_PLAN_XZ_MM[1]
        and WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM[0]
        < WHEEL_HUB_CAP_PLAN_XZ_MM[0]
        and WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM[1]
        < WHEEL_HUB_CAP_PLAN_XZ_MM[1]
        and WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM > 0.0
        and WHEEL_HUB_GAITER_FIXED_EDGE_OVERLAP_MM
        > WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM
        and WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM[0]
        < WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM[0]
        and WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM[1]
        < WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM[1]
        and WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM[0]
        > WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM[0]
        and WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM[1]
        > WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM[1]
        and WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM[0]
        < WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM[0]
        and WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM[1]
        < WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM[1]
        and WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM
        < WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM
        and WHEEL_HUB_GAITER_THICKNESS_Y_MM > 0.0
        and WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM > 0.0
        and WHEEL_HUB_FLEXIBLE_RUNNING_GEAR_MIN_CLEARANCE_MM > 0.0
    ):
        raise ValueError("Invalid V8 moving hub-cap / flexible-gaiter stack")
    cap_inner_y = WHEEL_HUB_CAP_ABS_Y_MM - WHEEL_HUB_CAP_THICKNESS_Y_MM / 2.0
    backing_outer_y = (
        WHEEL_HUB_BACKING_ABS_Y_MM + WHEEL_HUB_BACKING_THICKNESS_Y_MM / 2.0
    )
    backing_inner_y = (
        WHEEL_HUB_BACKING_ABS_Y_MM - WHEEL_HUB_BACKING_THICKNESS_Y_MM / 2.0
    )
    gaiter_moving_collar_outer_y = WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM
    fixed_shell_inner_y = (
        WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM
        - WHEEL_BELT_NOMINAL_WALL_THICKNESS_MM / 2.0
    )
    if (
        abs(cap_inner_y - backing_outer_y) > 1.0e-9
        or abs(backing_inner_y - gaiter_moving_collar_outer_y) > 1.0e-9
        or not (WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM < fixed_shell_inner_y)
        or abs(fixed_shell_inner_y - gaiter_moving_collar_outer_y) > 1.0e-9
    ):
        raise ValueError(
            "V8 moving cap/backing/collar and the dished gaiter carrier stack "
            "must retain its released dry-interface ordering"
        )


_validate_contract()


__all__ = [
    "WHEEL_AXIS_Z_MM",
    "WHEEL_ARTICULATION_POSE_ANGLES_DEG",
    "WHEEL_AXLE_X_MM",
    "WHEEL_BELT_NOMINAL_WALL_THICKNESS_MM",
    "WHEEL_END_CLOSED_PROBE_Z_MM",
    "WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM",
    "WHEEL_END_COVERAGE_PROBE_Z_MM",
    "WHEEL_END_LOWER_TYRE_WITNESS_LATERAL_OFFSETS_MM",
    "WHEEL_END_LOWER_TYRE_WITNESS_Z_MM",
    "WHEEL_END_OPEN_PROBE_Z_MM",
    "WHEEL_END_RETURN_LOWER_EDGE_Z_MM",
    "WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM",
    "WHEEL_END_VISUAL_SKIN_THICKNESS_MM",
    "WHEEL_END_VISUAL_SKIN_Y_SPAN_MM",
    "WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM",
    "WHEEL_MINIMUM_SWEPT_CLEARANCE_MM",
    "WHEEL_NOMINAL_PRODUCT_WIDTH_MM",
    "WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM",
    "WHEEL_HUB_BACKING_ABS_Y_MM",
    "WHEEL_HUB_BACKING_PLAN_XZ_MM",
    "WHEEL_HUB_BACKING_THICKNESS_Y_MM",
    "WHEEL_HUB_CAP_ABS_Y_MM",
    "WHEEL_HUB_CAP_PLAN_XZ_MM",
    "WHEEL_HUB_CAP_THICKNESS_Y_MM",
    "WHEEL_HUB_FIXED_APERTURE_CUTTER_THICKNESS_Y_MM",
    "WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM",
    "WHEEL_HUB_FIXED_APERTURE_PLAN_XZ_MM",
    "WHEEL_HUB_FIXED_APERTURE_CORNER_RADIUS_MM",
    "WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM",
    "WHEEL_HUB_SWEEP_ENVELOPE_CENTER_X_OFFSET_MM",
    "WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM",
    "WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM",
    "WHEEL_HUB_GAITER_FIXED_EDGE_CORNER_RADIUS_MM",
    "WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM",
    "WHEEL_HUB_GAITER_MOVING_COLLAR_PLAN_XZ_MM",
    "WHEEL_HUB_GAITER_MOVING_COLLAR_CORNER_RADIUS_MM",
    "WHEEL_HUB_GAITER_MOVING_VOID_ABS_Y_MM",
    "WHEEL_HUB_GAITER_FIXED_CARRIER_INNER_PLAN_XZ_MM",
    "WHEEL_HUB_GAITER_FIXED_EDGE_OVERLAP_MM",
    "WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM",
    "WHEEL_HUB_GAITER_THICKNESS_Y_MM",
    "WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3",
    "WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM",
    "WHEEL_HUB_FLEXIBLE_RUNNING_GEAR_MIN_CLEARANCE_MM",
    "WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3",
    "WHEEL_PRODUCTION_WIDTH_LIMIT_MM",
    "WHEEL_SIDE_CLOSED_PROBE_Z_MM",
    "WHEEL_SIDE_OPEN_PROBE_Z_MM",
    "WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM",
    "WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM",
    "WHEEL_ROCKER_PIVOT_MM",
]
