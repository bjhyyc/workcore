"""Final-product exterior closures for the E6 V8 release candidate.

This pass is intentionally last in the geometry pipeline.  Earlier modules
prove hardpoint, kinematic and service ownership; this module gives those
resolved mechanisms their production-facing weather surfaces.  It never reads
or writes the controlled ``build/`` STEP files.

Coordinates are millimetres in the controlled convention: -X front, +Y right,
+Z up.  The new surfaces are deliberately quiet: no decorative fake vents,
fasteners, screens or side-transfer cues are introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from math import cos, radians, sin
import os
from pathlib import Path
from typing import Iterable

import cadquery as cq

try:
    from .skin_common import (
        CHAMPAGNE,
        ESPRESSO,
        GRAPHITE_BROWN,
        LUNAR_STONE,
        OXBLOOD_LEATHER,
        SATIN_STAINLESS,
        SMOKED_WALNUT,
        SMOKED_UMBER,
        TPE_DARK,
        SkinPart,
        rounded_box,
        rounded_rect_prism,
        validate_parts,
    )
except ImportError:
    from skin_common import (  # type: ignore[no-redef]
        CHAMPAGNE,
        ESPRESSO,
        GRAPHITE_BROWN,
        LUNAR_STONE,
        OXBLOOD_LEATHER,
        SATIN_STAINLESS,
        SMOKED_WALNUT,
        SMOKED_UMBER,
        TPE_DARK,
        SkinPart,
        rounded_box,
        rounded_rect_prism,
        validate_parts,
    )

try:
    from .v8_state_contract import default_footrest_is_deployed
except ImportError:
    from v8_state_contract import default_footrest_is_deployed  # type: ignore[no-redef]

try:
    from .v8_wheel_contract import (
        WHEEL_AXIS_Z_MM,
        WHEEL_END_RETURN_LOWER_EDGE_Z_MM,
        WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM,
        WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
        WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
        WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM,
        WHEEL_ARTICULATION_POSE_ANGLES_DEG,
        WHEEL_HUB_BACKING_PLAN_XZ_MM,
        WHEEL_HUB_BACKING_THICKNESS_Y_MM,
        WHEEL_HUB_CAP_PLAN_XZ_MM,
        WHEEL_HUB_CAP_THICKNESS_Y_MM,
        WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM,
        WHEEL_HUB_GAITER_FIXED_EDGE_OVERLAP_MM,
        WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM,
        WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM,
        WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM,
        WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM,
        WHEEL_HUB_GAITER_THICKNESS_Y_MM,
        WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
    )
except ImportError:
    from v8_wheel_contract import (  # type: ignore[no-redef]
        WHEEL_AXIS_Z_MM,
        WHEEL_END_RETURN_LOWER_EDGE_Z_MM,
        WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM,
        WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
        WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
        WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM,
        WHEEL_ARTICULATION_POSE_ANGLES_DEG,
        WHEEL_HUB_BACKING_PLAN_XZ_MM,
        WHEEL_HUB_BACKING_THICKNESS_Y_MM,
        WHEEL_HUB_CAP_PLAN_XZ_MM,
        WHEEL_HUB_CAP_THICKNESS_Y_MM,
        WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM,
        WHEEL_HUB_GAITER_FIXED_EDGE_OVERLAP_MM,
        WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM,
        WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM,
        WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM,
        WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM,
        WHEEL_HUB_GAITER_THICKNESS_Y_MM,
        WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
    )

try:
    from .v8_wheel_hub_articulation import (
        wheel_hub_fixed_carrier_return,
        wheel_hub_fixed_aperture_cutter,
        wheel_hub_stack_pose,
    )
except ImportError:
    from v8_wheel_hub_articulation import (  # type: ignore[no-redef]
        wheel_hub_fixed_carrier_return,
        wheel_hub_fixed_aperture_cutter,
        wheel_hub_stack_pose,
    )

try:
    from .v8_footrest_drawer_brep import (
        FIXED_OCCURRENCE_NAMES as A08_FIXED_OCCURRENCE_NAMES,
        a08_footrest_drawer_host_corridor,
        a08_footrest_drawer_occurrences,
        a08_footrest_root_nose_cutter,
        a08_footrest_support_host_corridor,
    )
except ImportError:
    from v8_footrest_drawer_brep import (  # type: ignore[no-redef]
        FIXED_OCCURRENCE_NAMES as A08_FIXED_OCCURRENCE_NAMES,
        a08_footrest_drawer_host_corridor,
        a08_footrest_drawer_occurrences,
        a08_footrest_root_nose_cutter,
        a08_footrest_support_host_corridor,
    )

try:
    from .v8_cafe_table_root_motion import (
        CAFE_COVER_PICKUP_DEAD_TRAVEL_MM,
        CAFE_FINAL_RAIL_CAPTURE_MM,
        CAFE_INTERNAL_FOLD_HARD_RETREAT_MM,
        CAFE_RETURN_TRAVEL_MM,
        CafeRootOccurrence,
        cafe_root_final_occurrences,
    )
except ImportError:
    from v8_cafe_table_root_motion import (  # type: ignore[no-redef]
        CAFE_COVER_PICKUP_DEAD_TRAVEL_MM,
        CAFE_FINAL_RAIL_CAPTURE_MM,
        CAFE_INTERNAL_FOLD_HARD_RETREAT_MM,
        CAFE_RETURN_TRAVEL_MM,
        CafeRootOccurrence,
        cafe_root_final_occurrences,
    )

try:
    from .skin_upper import (
        BACK_FOLD_DEG,
        BACK_HINGE,
        BACK_RAKE_DEG,
        FOCUS_LOCK_STATIONS_X_MM,
        _crowned_trapezoid_skin,
        _rotate_y,
        _rounded_loft_z,
        _rounded_trapezoid_wire_yz,
    )
except ImportError:
    from skin_upper import (  # type: ignore[no-redef]
        BACK_FOLD_DEG,
        BACK_HINGE,
        BACK_RAKE_DEG,
        FOCUS_LOCK_STATIONS_X_MM,
        _crowned_trapezoid_skin,
        _rotate_y,
        _rounded_loft_z,
        _rounded_trapezoid_wire_yz,
    )


STATES = {"follow", "ride", "cafe", "focus"}
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WHEEL_BELT_TAUPE = (0.39, 0.36, 0.32, 1.0)

# Frozen A09 instrument-spine appearance contract.  The stages remain three
# independent dry-running physical occurrences on the released axes and final
# B-Rep Z hardpoints.  Only their exterior language changes: XY-only squircle
# rounding gives straight axial walls and a restrained two-millimetre Y bias,
# avoiding the fully rounded square "pill-box" stack of the engineering skin.
A09_LIFT_STAGE_PROFILE_CONTRACT: dict[int, dict[str, object]] = {
    1: {
        "outer_xy_mm": (72.0, 70.0),
        "inner_xy_mm": (66.0, 64.0),
        "outer_plan_radius_mm": 21.0,
        "inner_plan_radius_mm": 18.0,
        "minimum_wall_mm": 3.0,
    },
    2: {
        "outer_xy_mm": (60.0, 58.0),
        "inner_xy_mm": (54.0, 52.0),
        "outer_plan_radius_mm": 18.0,
        "inner_plan_radius_mm": 15.0,
        "minimum_wall_mm": 3.0,
    },
    3: {
        "outer_xy_mm": (48.0, 46.0),
        "inner_xy_mm": (40.0, 40.0),
        "outer_plan_radius_mm": 14.0,
        "inner_plan_radius_mm": 10.0,
        "minimum_wall_mm": 3.0,
    },
}
A09_LIFT_STAGE_Z_HARDPOINTS_MM = {
    1: (495.117310634, 574.882689366),
    2: (569.117310634, 640.882689366),
    3: (633.642857143, 693.357142857),
}
A09_LIFT_ADJACENT_RADIAL_CLEARANCE_MM = 3.0
A09_LIFT_STAGE3_MINIMUM_INTERNAL_CHANNEL_MM = 40.0
A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM = 2.4
A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM = 1.5
A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM = 1.0e-6
A07_MICROPHONE_TENON_MINIMUM_DRY_CLEARANCE_MM = 1.5
A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM = 0.2
A07_LOCK_STATION_Z_MM = 888.0
A07_LOCK_LOW_BORE_Z_MM = 888.0
A07_LOCK_FOCUS_BORE_Z_MM = 468.0
A07_LOCK_PIN_Y_MM = 34.0
A07_LOCK_PIN_DIAMETER_MM = 8.0
A07_LOCK_BORE_DIAMETER_MM = 8.5
A07_LOCK_PIN_ENGAGED_X_MM = (265.0, 291.0)
A07_LOCK_PIN_RETRACTED_X_MM = (265.0, 276.0)
A07_LOCK_HOUSING_X_MM = (264.5, 270.0)
A07_LOCK_HOUSING_DIAMETER_MM = 17.0
A07_LOCK_ENDPOINT_TOLERANCE_MM = 1.0e-6
A07_FIXED_THROAT_COLLAR_INNER_X_MM = 60.8
A07_FIXED_THROAT_COLLAR_INNER_Y_MM = 126.8
A07_FIXED_TO_MOVING_MINIMUM_RADIAL_CLEARANCE_MM = 3.0
FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM = 60.0
FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM = 22.0
FOLLOW_SEAT_CUSHION_MAXIMUM_COMMON_VOLUME_MM3 = 70_000.0
FRONT_NOSE_WAIST_DRY_SPLIT_MM = 1.2
FRONT_NOSE_WAIST_CLEARANCE_ENVELOPE_OFFSET_MM = 1.55
SIDE_SAIL_OUTER_FACE_ABS_Y_MM = 370.5
FOLLOW_EXTERNAL_CONTROL_SEATING_GAP_MM = 0.3
FOLLOW_STATUS_WITNESS_PERIMETER_CLEARANCE_MM = 0.4
FOLLOW_ESTOP_PLUNGER_OPENING_DIAMETER_MM = 12.0

# A06 production hinge hardpoints.  The shaft is torque-coupled to the
# conserved internal structural carrier by two clamped drive hubs; the PC-ABS
# weather shell receives clearance pockets and is not used as the primary load
# path.  Bearings and endpoint locks sit outboard of the moving trapezoid,
# inside the fixed A05 rear-root cavities.
A06_HINGE_SHAFT_RADIUS_MM = 8.0
A06_HINGE_RUNNING_RADIUS_MM = 8.7
A06_HINGE_SHAFT_Y_LIMIT_MM = 342.0
A06_HINGE_BEARING_Y_MM = 312.5
A06_HINGE_BEARING_AXIAL_MM = 14.0
A06_HINGE_BEARING_OUTER_RADIUS_MM = 15.0
A06_HINGE_DRIVE_HUB_Y_MM = 260.0
A06_HINGE_DRIVE_HUB_AXIAL_MM = 8.0
A06_HINGE_DRIVE_HUB_RADIUS_MM = 16.0
A06_HINGE_DRIVE_HUB_POCKET_RADIUS_MM = 16.5
A06_LOCK_STATION_Y_MM = 333.5
A06_LOCK_DISC_AXIAL_MM = 10.0
A06_LOCK_DISC_RADIUS_MM = 26.0
A06_LOCK_PIN_RADIUS_MM = 4.0
A06_LOCK_BORE_RADIUS_MM = 4.3
A06_LOCK_PIN_ENGAGED_Z_MM = (512.0, 572.0)
A06_LOCK_PIN_RETRACTION_MM = 32.0


@dataclass(frozen=True)
class A07LockMotionPose:
    """One commanded A07 stroke with the fail-closed radial locks posed."""

    stroke_mm: float
    pin_state: str
    active_bore_master_z_mm: float | None
    fixed_sleeve: cq.Shape
    moving_spine: cq.Shape
    lock_pins: tuple[cq.Shape, cq.Shape]


@lru_cache(maxsize=1)
def _canonical_privacy_shutter() -> cq.Shape:
    path = REPOSITORY_ROOT / "build" / "parts" / "mast_privacy_shutter_parked_focus.step"
    imported = cq.importers.importStep(str(path)).val()
    return _valid_single(imported, "controlled A07 privacy shutter")


def _new_part(
    name: str,
    shape: cq.Shape,
    color: tuple[float, float, float, float],
    material: str,
    module: str,
    state: str,
    intent: str,
    **metadata: object,
) -> SkinPart:
    return SkinPart(
        name=name,
        shape=shape,
        color=color,
        material=material,
        module=module,
        configuration=state,
        intent=intent,
        metadata=dict(metadata),
    )


def _replace_matching(
    parts: list[SkinPart],
    predicate: object,
    *,
    color: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    intent: str | None = None,
    metadata: dict[str, object] | None = None,
) -> int:
    changed = 0
    for index, part in enumerate(parts):
        if not predicate(part):  # type: ignore[operator]
            continue
        merged = dict(part.metadata)
        if metadata:
            merged.update(metadata)
        parts[index] = replace(
            part,
            color=part.color if color is None else color,
            material=part.material if material is None else material,
            intent=part.intent if intent is None else intent,
            metadata=merged,
        )
        changed += 1
    return changed


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
        pass
    return body.translate(center).val()


def _rounded_panel_yz(
    size_yz: tuple[float, float],
    thickness_x: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    sy, sz = size_yz
    body = cq.Workplane("YZ").rect(sy, sz).extrude(thickness_x / 2.0, both=True)
    try:
        body = body.edges("|X").fillet(min(radius, sy * 0.45, sz * 0.45))
    except Exception:
        pass
    return body.translate(center).val()


def _valid_single(shape: cq.Shape, label: str) -> cq.Shape:
    if shape.isNull() or not shape.isValid() or shape.Volume() <= 0.0:
        raise ValueError(f"{label} is not a positive valid B-Rep")
    solids = list(shape.Solids())
    if len(solids) != 1:
        raise ValueError(f"{label} must be one serviceable solid; got {len(solids)}")
    return shape


def _outward_clearance_envelope(
    shape: cq.Shape,
    offset_mm: float,
    label: str,
) -> tuple[cq.Shape | None, str]:
    """Return a true three-dimensional OCC offset for an assembly dry split.

    Exact Boolean partitioning produces coincident faces.  A positive solid
    offset is the appropriate manufacturing cutter because it follows every
    local surface normal, including oblique and rounded transitions.  OCC can
    reject unusually complex C0 topology, so callers retain a deterministic
    translated-envelope fallback rather than silently dropping the gap.
    """

    try:
        from OCP.BRepOffset import BRepOffset_Mode
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
        from OCP.GeomAbs import GeomAbs_JoinType

        builder = BRepOffsetAPI_MakeOffsetShape()
        builder.PerformByJoin(
            shape.wrapped,
            float(offset_mm),
            1.0e-4,
            BRepOffset_Mode.BRepOffset_Skin,
            False,
            False,
            GeomAbs_JoinType.GeomAbs_Arc,
            True,
        )
        if not builder.IsDone():
            return None, "translated_octant_fallback_offset_not_done"
        envelope = cq.Shape.cast(builder.Shape()).fix()
        if (
            envelope.isNull()
            or not envelope.isValid()
            or envelope.Volume() <= shape.Volume()
            or len(envelope.Solids()) != 1
        ):
            return None, "translated_octant_fallback_offset_invalid"
        return envelope, "occ_positive_solid_offset"
    except Exception as exc:  # pragma: no cover - exercised only on OCC failure
        return None, f"translated_octant_fallback_{type(exc).__name__}"


def _wheel_upper_fairings(state: str, parts: list[SkinPart]) -> None:
    """Cover each tyre crown while preserving contact, heat and hub service."""

    for axle, wheel_x, outward_x in (
        ("front", -380.0, -1.0),
        ("rear", 180.0, 1.0),
    ):
        for side_name, side in (("left", -1), ("right", 1)):
            if state == "follow" and axle == "front":
                # Follow has no deployed footrest to dominate length.  Keep the
                # front arch inside the 855.003 mm production lock while
                # retaining a 12.52 mm return-to-tyre gap.  The service pull
                # cup is inset in ``skin_lower`` so this end return can use the
                # same 1.90 mm production wall as the other arch surfaces.
                fairing_x = -381.55
                fairing_x_span = 275.50
                outward_edge_x = -518.47
                end_return_thickness_x = 1.90
                longitudinal_clearance = 12.52
            else:
                fairing_x = wheel_x + outward_x * 1.2
                fairing_x_span = 274.80
                outward_edge_x = wheel_x + outward_x * 138.6
                end_return_thickness_x = None
                longitudinal_clearance = 12.65
            if side < 0:
                # The prototype +Y transfer-hinge shroud is trace-only and is
                # absent from the fixed-armrest production BOM.  Keeping trace
                # and production envelopes distinct permits a symmetric,
                # manufacturable Class-A wall instead of a 0.30 mm compromise.
                spat_y = -371.50
                spat_thickness = 1.90
                crown_y_center = -327.90
                crown_y_width = 86.20
                fairing_material = (
                    "impact-modified mineral-matte PC-ABS fixed wheel-arch shell"
                )
                locked_outer_y = -372.45
                return_y_center = -328.625
                return_y_width = 87.65
            else:
                spat_y = 371.5
                spat_thickness = 1.9
                crown_y_center = 327.9
                crown_y_width = 86.2
                fairing_material = (
                    "impact-modified mineral-matte PC-ABS fixed wheel-arch shell"
                )
                locked_outer_y = 372.45
                return_y_center = 328.625
                return_y_width = 87.65
            spat = _rounded_panel_xz(
                (fairing_x_span, 166.0),
                spat_thickness,
                (fairing_x, spat_y, 187.5),
                36.0,
            )
            # A real hub aperture, coaxial with the Y-axis wheel datum.  The
            # 54.5 mm radius leaves 8.5 mm around the current 46 mm hub cap.
            hub_aperture = (
                cq.Workplane("XZ")
                .circle(54.5)
                .extrude(6.0, both=True)
                .translate((wheel_x, spat_y, 125.0))
                .val()
            )
            spat = spat.cut(hub_aperture)
            # A true constant-wall crown: 1.90 mm horizontal Class-A skin plus
            # a 1.90 mm outer downstand.  The former 8 mm solid slab rendered
            # correctly but was not a credible moulding section and could sink
            # or warp in production.
            crown_top = rounded_box(
                (fairing_x_span, crown_y_width, 1.9),
                (fairing_x, crown_y_center, 269.55),
                0.8,
            )
            crown_outer_downstand = rounded_box(
                (fairing_x_span, 1.9, 8.0),
                (fairing_x, side * 370.95, 266.5),
                0.8,
            )
            crown = crown_top.fuse(crown_outer_downstand).clean()
            # The longitudinally outward return is what prevents an end-on
            # view from showing a complete black tyre.  Its inner face stays
            # 12.65 mm beyond the 125 mm tyre radius, while the inboard end of
            # the crown remains at the previous collision-safe datum.
            end_return = _rounded_panel_yz(
                (return_y_width, 145.5),
                (
                    end_return_thickness_x
                    if end_return_thickness_x is not None
                    else spat_thickness
                ),
                (outward_edge_x, return_y_center, 197.75),
                26.0,
            )
            fairing = _valid_single(
                spat.fuse(crown).fuse(end_return),
                f"{state} {axle} {side_name} upper wheel fairing",
            )
            parts.append(
                _new_part(
                    f"A03_wheel_fairing_upper_{axle}_{side_name}",
                    fairing,
                    LUNAR_STONE,
                    fairing_material,
                    "A03",
                    state,
                    (
                        "The fixed body absorbs the tyre crown and internal drive view; "
                        "only the lower contact tread, motion gap and service hub remain legible."
                    ),
                    physical_occurrence_id=(
                        f"E6-A03-WHEEL-FAIRING-UPPER-{axle.upper()}-{side_name.upper()}"
                    ),
                    role="wheel_fairing",
                    fixed_to_lower_body=True,
                    wheel_axis_mm=(wheel_x, side * 326.0, 125.0),
                    hub_service_aperture_radius_mm=54.5,
                    minimum_tyre_clearance_target_mm=12.5,
                    longitudinal_return_minimum_tyre_clearance_mm=longitudinal_clearance,
                    tyre_upper_half_is_not_exposed=True,
                    lower_contact_tread_deliberately_visible=True,
                    locked_outer_y_mm=locked_outer_y,
                    nominal_wall_thickness_mm=1.9,
                    crown_top_wall_thickness_mm=1.9,
                    crown_outer_downstand_wall_thickness_mm=1.9,
                    longitudinal_return_wall_thickness_mm=1.9,
                    minimum_geometric_overlap_target_mm=1.0,
                    production_bom_excludes_legacy_transfer_hinge_shroud=True,
                    production_certification_claimed=False,
                )
            )

    # A separate dry-split rocker skin joins the two arches on each flank.
    # It sits just outside the existing structural bridge/service cap and is
    # therefore a weather surface, not a rigid bridge between moving wheels.
    for side_name, side in (("left", -1), ("right", 1)):
        rocker_y = -371.5 if side < 0 else 371.5
        rocker_thickness = 1.9
        rocker = _rounded_panel_xz(
            (286.0, 166.0),
            rocker_thickness,
            (-100.0, rocker_y, 187.5),
            32.0,
        )
        parts.append(
            _new_part(
                f"A03_lower_rocker_side_shell_{side_name}",
                _valid_single(rocker, f"{state} {side_name} lower rocker shell"),
                LUNAR_STONE,
                "impact-modified mineral-matte PC-ABS continuous rocker weather skin",
                "A03",
                state,
                "A continuous calm side skirt hides the drive and suspension strip between the two wheel arches while preserving independent wheel wells.",
                physical_occurrence_id=(
                    f"E6-A03-LOWER-ROCKER-SIDE-SHELL-{side_name.upper()}"
                ),
                fixed_to_lower_body=True,
                dry_gap_to_wheel_arch_each_end_mm=0.8,
                internal_structural_bridge_retained=True,
                locked_outer_y_mm=-372.45 if side < 0 else 372.45,
                nominal_wall_thickness_mm=1.9,
            )
        )

    _replace_matching(
        parts,
        lambda part: part.name.startswith("A03_wheel_end_service_cap_"),
        color=LUNAR_STONE,
        material="body-colour flush wheel-end service cap with precision dry seam",
        intent="A body-colour flush hub service island replaces the visually exposed black wheel-centre disc.",
        metadata={
            "flush_body_colour_service_cap": True,
            "precision_service_seam_mm": 1.0,
        },
    )


def _continuous_wheel_belts(state: str, parts: list[SkinPart]) -> None:
    """Replace segmented plates with a fixed swept-clear wheel pod per side."""

    cap_templates = {
        part.name: part
        for part in parts
        if part.name.startswith("A03_wheel_end_service_cap_")
        or part.name.startswith("A03_rocker_pivot_service_cap_")
    }
    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A03_wheel_fairing_upper_")
        and not part.name.startswith("A03_lower_rocker_side_shell_")
        and not part.name.startswith("A03_wheel_end_service_cap_")
        and not part.name.startswith("A03_rocker_pivot_service_cap_")
    ]

    for side_name, side in (("left", -1), ("right", 1)):
        # A 12.55 mm nominal tyre-to-sidewall gap left effectively no
        # production allowance above the former 12.5 mm numerical gate.  Move
        # the complete outer return 2.95 mm outboard while retaining its
        # 1.9 mm wall: the inner weather face is now |Y|=373.5 mm, exactly
        # 15.5 mm beyond the controlled tyre sidewall at |Y|=358 mm.  The
        # resulting 750.8 mm product width remains inside the new 752 mm
        # production design target and does not alter any wheel hardpoint.
        outer_y = side * 374.45
        # The visible side is one continuous retro-futurist wheel pod, not a
        # front plate + rocker plate + rear plate.  Its two calm upper lobes
        # rise only above the wheel sweep; the centre drops to keep the low
        # core visually grounded and to avoid a featureless rectangular slab.
        vertical = (
            cq.Workplane("XZ")
            .moveTo(-520.0, 32.0)
            .lineTo(-520.0, 205.0)
            .threePointArc((-512.0, 272.0), (-470.0, 315.0))
            .lineTo(-290.0, 315.0)
            .threePointArc((-252.0, 306.0), (-222.0, 264.0))
            .lineTo(22.0, 264.0)
            .threePointArc((52.0, 306.0), (90.0, 315.0))
            .lineTo(270.0, 315.0)
            .threePointArc((312.0, 272.0), (320.0, 205.0))
            .lineTo(320.0, 32.0)
            .close()
            .extrude(0.95, both=True)
            .translate((0.0, outer_y, 0.0))
            .val()
        )
        # Carry the crown from the outer cosmetic face to just outside the
        # A02 structural side shell.  The earlier 63.4 mm strip covered only
        # the outboard part of the 64 mm tyre and still showed a black crown
        # from front/rear and inner-oblique views.
        # Preserve the established |Y|=284.8 mm inboard crown edge while
        # carrying the same calm surface to the new |Y|=375.4 mm outer skin.
        hood_center_y = side * 330.1
        # Extend each hood only at its longitudinal outside end so it meets
        # the transverse return as one B-Rep.  The former X=-520/+320 hood
        # limits stopped 2.05 mm short of the return; subsequent booleans
        # discarded those isolated solids and left the tyres visually bare in
        # exact front/rear views.  Inboard hardpoints remain unchanged.
        front_hood = rounded_rect_prism(
            (289.9, 90.6),
            1.9,
            (-379.95, hood_center_y, 315.1),
            24.0,
        )
        rear_hood = rounded_rect_prism(
            (289.9, 90.6),
            1.9,
            (179.95, hood_center_y, 315.1),
            24.0,
        )
        inner_edge_y = side * 285.75
        front_inner_downstand = rounded_box(
            (285.0, 1.9, 2.2),
            (-377.5, inner_edge_y, 313.1),
            0.8,
        )
        rear_inner_downstand = rounded_box(
            (285.0, 1.9, 2.2),
            (177.5, inner_edge_y, 313.1),
            0.8,
        )
        belt = (
            vertical.fuse(front_hood)
            .fuse(rear_hood)
            .fuse(front_inner_downstand)
            .fuse(rear_inner_downstand)
        )

        # Thin transverse returns at the longitudinal wheel extremes turn the
        # side belt and full-width crown into a genuine upper C-wrap.  The
        # return datum sits 4.5 mm beyond the nominal tyre radius for the
        # sampled suspension sweep, while its lower edge is locked to the
        # z=125 mm wheel axis so the complete lower tyre half remains legible
        # in exact front/rear views.
        for wheel_x, outward_x in ((-380.0, -1.0), (180.0, 1.0)):
            return_top_z = 315.0
            return_height = return_top_z - WHEEL_END_RETURN_LOWER_EDGE_Z_MM
            end_return = _rounded_panel_yz(
                (90.6, return_height),
                1.9,
                (
                    wheel_x + outward_x * 143.95,
                    side * 330.1,
                    (return_top_z + WHEEL_END_RETURN_LOWER_EDGE_Z_MM) / 2.0,
                ),
                26.0,
            )
            belt = belt.fuse(end_return)

        # Cut a true lower semicircle at both axle stations.  The oversized
        # 138.5 mm cutter leaves a controlled 13.5 mm radial reveal around the
        # 125 mm tyre.  The hub service island is no longer fixed: its cap and
        # opaque backing rotate with the suspension rocker, while a single
        # colour-matched TPE diaphragm bridges to this fixed sweep aperture.
        # That keeps the hub and axle hidden at every released articulation
        # pose without closing the lower tyre semicircle.
        # This is the physical half-wrap boundary, not a token tread slot.
        for axle, wheel_x, outward_x in (
            ("front", -380.0, -1.0),
            ("rear", 180.0, 1.0),
        ):
            tyre_circle = (
                cq.Workplane("XZ")
                .circle(138.5)
                .extrude(5.0, both=True)
                .translate((wheel_x, outer_y, WHEEL_AXIS_Z_MM))
                .val()
            )
            lower_half_space = (
                cq.Workplane("XY")
                .box(300.0, 10.0, 500.0)
                .translate(
                    (
                        wheel_x,
                        outer_y,
                        WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM - 250.0,
                    )
                )
                .val()
            )
            belt = belt.cut(tyre_circle.intersect(lower_half_space))
            # Remove the complete longitudinal *outside* half below the wheel
            # axis.  The former vertical belt boundary sat beyond the circular
            # cutter and left a widening triangular spat at both product ends.
            # The inter-wheel recessed bridge remains untouched on the inward
            # side, while the exterior tyre half now owns the true silhouette.
            outer_lower_half = (
                cq.Workplane("XY")
                .box(1000.0, 10.0, 500.0)
                .translate(
                    (
                        wheel_x + outward_x * 500.0,
                        outer_y,
                        WHEEL_AXIS_Z_MM - 250.0,
                    )
                )
                .val()
            )
            belt = belt.cut(outer_lower_half)
            belt = belt.cut(
                wheel_hub_fixed_aperture_cutter(axle, side_name)
            )
            # The gaiter's rolled-in fixed edge is supported by a real hidden
            # return fused into this same belt B-Rep.  It sits outboard of the
            # controlled tyre, clears all five running-gear poses and adds no
            # new exterior occurrence or styling seam.
            belt = belt.fuse(
                wheel_hub_fixed_carrier_return(axle, side_name)
            )

        pivot_aperture = _rounded_panel_xz(
            (58.0, 46.0),
            10.0,
            (-100.0, outer_y, 125.0),
            11.0,
        )
        belt = _valid_single(
            belt.cut(pivot_aperture),
            f"{state} {side_name} continuous wheel belt",
        )
        parts.append(
            _new_part(
                f"A03_continuous_wheel_belt_shell_{side_name}",
                belt,
                WHEEL_BELT_TAUPE,
                "1.9 mm impact-modified mineral-matte PC-ABS continuous wheel belt",
                "A03",
                state,
                "One continuous side-and-crown shell absorbs both tyre upper halves and the drive strip into the low core volume.",
                physical_occurrence_id=(
                    f"E6-A03-CONTINUOUS-WHEEL-BELT-{side_name.upper()}"
                ),
                role="wheel_fairing",
                one_piece_visible_wheel_belt=True,
                full_tyre_width_crown_wrap=True,
                front_and_rear_axle_plane_returns=True,
                longitudinal_end_return_offset_from_axle_mm=143.95,
                longitudinal_sweep_clearance_beyond_tyre_radius_mm=4.5,
                longitudinal_return_connected_to_crown_brep=True,
                crown_inboard_edge_y_mm=side * 284.8,
                crown_inboard_downstand_mm=2.15,
                tyre_lower_contact_half_visible=True,
                tyre_lower_contact_band_visible=True,
                tyre_upper_half_not_exposed=True,
                crown_minimum_tyre_clearance_mm=15.5,
                lower_half_reveal_top_z_mm=WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
                half_wrap_boundary_equals_wheel_axis=True,
                hub_service_aperture_owner=(
                    "moving cap plus dished flexible gaiter on hidden fused carrier"
                ),
                axis_below_longitudinal_outer_wedges_removed=True,
                hidden_gaiter_carrier_return_fused_into_belt=True,
                hub_service_aperture_pose_angles_deg=(
                    WHEEL_ARTICULATION_POSE_ANGLES_DEG
                ),
                hub_service_aperture_profile_clearance_mm=(
                    WHEEL_HUB_FIXED_APERTURE_PROFILE_CLEARANCE_MM
                ),
                rocker_service_aperture_size_mm=(58.0, 46.0),
                suspension_articulation_sweep_deg=(-10.0, 10.0),
                swept_tyre_roof_clearance_target_mm=15.5,
                swept_tyre_side_clearance_target_mm=15.5,
                service_position="neutral_suspension_locked",
                fixed_to_lower_body=True,
                nominal_wall_thickness_mm=1.9,
                locked_outer_y_mm=side * 375.4,
                production_width_design_limit_mm=752.0,
                nominal_product_width_mm=750.8,
                nominal_width_margin_to_design_limit_mm=1.2,
                width_growth_for_production_clearance_mm=5.9,
                previous_minimum_swept_tyre_clearance_mm=12.55,
                production_minimum_swept_tyre_clearance_target_mm=15.5,
                production_certification_claimed=False,
            )
        )

        # A light body-colour facing on each transverse return makes the
        # physical C-wrap legible from exact front/rear views.  Without this
        # facing, the dark structural return and the dark tyre collapse into
        # one tall wheel-shaped rectangle even though the tyre is physically
        # covered.  The facing is a real replaceable impact skin with one
        # restrained perimeter split; it adds no decorative line to the side
        # elevation and leaves the complete lower tyre half visually dark.
        for axle, wheel_x, outward_x in (
            ("front", -380.0, -1.0),
            ("rear", 180.0, 1.0),
        ):
            facing_bottom_z, facing_top_z = WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM
            facing = _rounded_panel_yz(
                (
                    WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
                    facing_top_z - facing_bottom_z,
                ),
                WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
                (
                    wheel_x + outward_x * 145.5,
                    side * 330.1,
                    (facing_bottom_z + facing_top_z) / 2.0,
                ),
                25.0,
            )
            parts.append(
                _new_part(
                    f"A03_body_colour_wheel_end_return_skin_{axle}_{side_name}",
                    _valid_single(
                        facing,
                        f"{state} {axle} {side_name} body-colour wheel-end return skin",
                    ),
                    LUNAR_STONE,
                    "1.0 mm body-colour replaceable PC-ABS wheel-end impact facing",
                    "A03",
                    state,
                    "A quiet body-colour end facing absorbs only the tyre upper projection into the low core while the lower semicircle remains visibly readable.",
                    physical_occurrence_id=(
                        "E6-A03-BODY-COLOUR-WHEEL-END-RETURN-SKIN-"
                        f"{axle.upper()}-{side_name.upper()}"
                    ),
                    material_family="body_colour_pc_abs_mineral_matte",
                    body_colour_end_return=True,
                    tyre_visual_occlusion=True,
                    covers_tyre_upper_projection=True,
                    underlying_end_return_connected_to_crown_brep=True,
                    end_facing_plan_yz_mm=(
                        WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
                        facing_top_z - facing_bottom_z,
                    ),
                    end_facing_z_bounds_mm=WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM,
                    lower_half_reveal_top_z_mm=WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
                    half_wrap_boundary_equals_wheel_axis=True,
                    nominal_wall_thickness_mm=(
                        WHEEL_END_VISUAL_SKIN_THICKNESS_MM
                    ),
                    dry_gap_to_underlying_end_return_mm=(
                        WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM
                    ),
                    longitudinal_outer_offset_from_axle_mm=146.0,
                    fixed_to_lower_body=True,
                    replaceable_after_corner_impact=True,
                    decorative_graphics_or_fake_seams=False,
                    production_certification_claimed=False,
                )
            )

        for axle, wheel_x in (("front", -380.0), ("rear", 180.0)):
            name = f"A03_wheel_end_service_cap_{axle}_{side_name}"
            template = cap_templates[name]
            neutral_pose = wheel_hub_stack_pose(axle, side_name, 0.0)
            metadata = dict(template.metadata)
            metadata.update(
                {
                    "physical_occurrence_id": (
                        "E6-A03-WHEEL-END-SERVICE-CAP-"
                        f"{axle.upper()}-{side_name.upper()}"
                    ),
                    "flush_body_colour_service_cap": True,
                    "precision_service_seam_mm": 1.0,
                    "service_cap_size_mm": WHEEL_HUB_CAP_PLAN_XZ_MM,
                    "service_cap_is_non_circular": True,
                    "moves_with": "controlled_suspension_rocker_and_wheel_hub",
                    "released_articulation_pose_angles_deg": (
                        WHEEL_ARTICULATION_POSE_ANGLES_DEG
                    ),
                    "neutral_service_lock_required": True,
                    "same_brep_all_product_states": True,
                    "normal_sightline_hub_and_axle_occluded_all_poses": True,
                    "nominal_cap_wall_mm": WHEEL_HUB_CAP_THICKNESS_Y_MM,
                    "near_flush_proud_mm": 0.1,
                    "finished_local_product_width_mm": 751.0,
                    "production_width_design_limit_mm": 752.0,
                    "final_exterior_visible": True,
                }
            )
            parts.append(
                replace(
                    template,
                    shape=_valid_single(neutral_pose.cap, name),
                    color=WHEEL_BELT_TAUPE,
                    material=(
                        "body-colour moving flush wheel-end service cap on "
                        "suspension rocker"
                    ),
                    intent=(
                        "A soft-cornered service island follows the hub through "
                        "wheel articulation, preserving access at the neutral "
                        "service lock without exposing a dark hub face."
                    ),
                    metadata=metadata,
                )
            )
            # The opaque backing belongs to the same moving family.  The
            # fixed belt touches only the diaphragm's hidden outer flange;
            # no rigid cap is asked to bridge a roughly 97 mm vertical hub
            # sweep or to remain aligned with a moving service fastener.
            parts.append(
                _new_part(
                    f"A03_wheel_end_service_seam_backing_{axle}_{side_name}",
                    _valid_single(
                        neutral_pose.backing,
                        f"{name} moving opaque backing",
                    ),
                    ESPRESSO,
                    "moving closed-cell dark EPDM wheel-end seam backing",
                    "A03",
                    state,
                    "A recessed backing follows the cap and closes its precision seam throughout rocker travel.",
                    physical_occurrence_id=(
                        f"E6-A03-WHEEL-END-SEAM-BACKING-{axle.upper()}-{side_name.upper()}"
                    ),
                    material_family="closed_cell_dark_epdm",
                    backs_service_cap=name,
                    bonded_to_service_cap_inner_face=True,
                    moves_with_service_cap=True,
                    moves_with="controlled_suspension_rocker_and_wheel_hub",
                    released_articulation_pose_angles_deg=(
                        WHEEL_ARTICULATION_POSE_ANGLES_DEG
                    ),
                    nominal_uncompressed_thickness_mm=(
                        WHEEL_HUB_BACKING_THICKNESS_Y_MM
                    ),
                    backing_plan_mm=WHEEL_HUB_BACKING_PLAN_XZ_MM,
                    aperture_perimeter_clearance_mm=0.2,
                    normal_sightline_background_transmission=False,
                    service_seam_nominal_mm=1.0,
                    same_brep_all_product_states=True,
                    final_exterior_visible=False,
                    production_certification_claimed=False,
                )
            )
            parts.append(
                _new_part(
                    f"A03_wheel_end_motion_gaiter_{axle}_{side_name}",
                    _valid_single(
                        neutral_pose.gaiter,
                        f"{name} fixed-edge moving-hole gaiter",
                    ),
                    WHEEL_BELT_TAUPE,
                    "colour-matched low-gloss self-skinning TPE wheel-end diaphragm",
                    "A03",
                    state,
                    "One smooth diaphragm hides the swept hub opening: its outer flange is overmoulded behind the fixed belt and its inner edge follows the moving service cap without visible bellows or exposed drive hardware.",
                    physical_occurrence_id=(
                        f"E6-A03-WHEEL-END-MOTION-GAITER-{axle.upper()}-{side_name.upper()}"
                    ),
                    outer_edge_moves_with="fixed_lower_body",
                    inner_edge_moves_with=(
                        "controlled_suspension_rocker_and_wheel_hub"
                    ),
                    one_piece_flexible_diaphragm=True,
                    released_articulation_pose_angles_deg=(
                        WHEEL_ARTICULATION_POSE_ANGLES_DEG
                    ),
                    fixed_edge_hidden_overlap_mm=(
                        WHEEL_HUB_GAITER_FIXED_EDGE_OVERLAP_MM
                    ),
                    fixed_edge_abs_y_mm=WHEEL_HUB_GAITER_FIXED_EDGE_ABS_Y_MM,
                    fixed_edge_plan_xz_mm=WHEEL_HUB_GAITER_FIXED_EDGE_PLAN_XZ_MM,
                    moving_collar_abs_y_mm=(
                        WHEEL_HUB_GAITER_MOVING_COLLAR_ABS_Y_MM
                    ),
                    shallow_dished_membrane_not_planar_swept_union=True,
                    hidden_carrier_fused_into_continuous_belt=True,
                    moving_inner_aperture_xz_mm=(
                        WHEEL_HUB_GAITER_INNER_APERTURE_XZ_MM
                    ),
                    nominal_membrane_thickness_mm=(
                        WHEEL_HUB_GAITER_THICKNESS_Y_MM
                    ),
                    colour_matched_to_wheel_belt=True,
                    visible_accordion_pleats=False,
                    hub_and_axle_normal_sightline_occlusion=True,
                    same_topology_all_released_poses=True,
                    same_brep_all_product_states=True,
                    final_exterior_visible=True,
                    production_certification_claimed=False,
                )
            )

        pivot_name = f"A03_rocker_pivot_service_cap_{side_name}"
        pivot_template = cap_templates[pivot_name]
        pivot_cap = _rounded_panel_xz(
            (56.0, 44.0),
            1.7,
            (-100.0, outer_y, 125.0),
            10.0,
        )
        pivot_metadata = dict(pivot_template.metadata)
        pivot_metadata.update(
            {
                "flush_body_colour_service_cap": True,
                "precision_service_seam_mm": 1.0,
                "service_cap_size_mm": (56.0, 44.0),
                "service_cap_is_non_circular": True,
            }
        )
        parts.append(
            replace(
                pivot_template,
                shape=_valid_single(pivot_cap, pivot_name),
                color=WHEEL_BELT_TAUPE,
                material="body-colour flush removable rocker-pivot service cap",
                intent="A restrained flush cap exposes the central rocker pivot only during authorised service.",
                metadata=pivot_metadata,
            )
        )
        pivot_backing = _rounded_panel_xz(
            (60.0, 48.0),
            0.8,
            (-100.0, outer_y - side * 2.0, 125.0),
            11.0,
        )
        parts.append(
            _new_part(
                f"A03_rocker_pivot_service_seam_backing_{side_name}",
                _valid_single(
                    pivot_backing,
                    f"{state} {side_name} rocker-pivot dark seam backing",
                ),
                ESPRESSO,
                "closed-cell dark EPDM rocker-pivot service-seam backing",
                "A03",
                state,
                "A recessed opaque gasket gives the rocker service island a controlled dark dry seam without a background crescent.",
                physical_occurrence_id=(
                    f"E6-A03-ROCKER-PIVOT-SEAM-BACKING-{side_name.upper()}"
                ),
                fixed_to_lower_body=True,
                backs_service_cap=pivot_name,
                normal_sightline_background_transmission=False,
                service_seam_nominal_mm=1.0,
                production_certification_claimed=False,
            )
        )


def _front_waist_closure(state: str, parts: list[SkinPart]) -> None:
    """Close the true waist datum with one vertical U-section, never a shelf."""

    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A04_front_waist_bridge_")
        and part.name != "A04_front_waist_fascia"
    ]
    # Bring the front waist to the underside of the seat ring so the core reads
    # as one continuous volume instead of a fascia, exposed cushion roll and
    # another floating cross-member.  The rear edge remains outside the foot
    # route and is physically trimmed to the compliant cushion below.
    z0, z1 = 365.2, 478.0
    z_center = (z0 + z1) / 2.0
    front = _rounded_panel_yz(
        (614.0, z1 - z0),
        6.0,
        (-421.0, 0.0, z_center),
        22.0,
    )
    left_return = _rounded_panel_xz(
        (108.0, z1 - z0),
        6.0,
        (-364.0, -304.0, z_center),
        18.0,
    )
    right_return = _rounded_panel_xz(
        (108.0, z1 - z0),
        6.0,
        (-364.0, 304.0, z_center),
        18.0,
    )
    outer_sections = (
        (-421.0, 610.0, 600.0, 26.0, 438.0, 8.0),
        (-360.0, 590.0, 570.0, 30.0, 437.0, 11.0),
        (-335.0, 560.0, 535.0, 34.0, 434.0, 13.0),
        (-310.0, 525.0, 505.0, 28.0, 432.0, 10.0),
    )
    inner_sections = (
        (-418.0, 604.0, 594.0, 24.0, 438.0, 7.0),
        (-360.0, 584.0, 564.0, 28.0, 437.0, 10.0),
        (-335.0, 554.0, 529.0, 32.0, 434.0, 12.0),
        (-307.0, 519.0, 499.0, 26.0, 432.0, 9.0),
    )

    def loft(
        sections: tuple[tuple[float, float, float, float, float, float], ...]
    ) -> cq.Shape:
        wires = [
            _rounded_trapezoid_wire_yz(
                bottom_width,
                top_width,
                height,
                x=x,
                z0=z0,
                corner_radius=radius,
            )
            for x, bottom_width, top_width, height, z0, radius in sections
        ]
        return cq.Solid.makeLoft(wires, ruled=False)

    hood = _valid_single(
        loft(outer_sections).cut(loft(inner_sections)),
        f"{state} sculpted front waist hood",
    )
    fascia = front.fuse(left_return).fuse(right_return).fuse(hood)

    # A02 owns real side-facing optical/service inserts at this datum.  They
    # are subtracted as physical inlays rather than hidden behind, or collided
    # with, a cosmetic plate.  The remaining U-section stays one service part.
    for obstacle in parts:
        if obstacle.module != "A02":
            continue
        if fascia.distance(obstacle.shape) <= 0.01:
            fascia = fascia.cut(obstacle.shape)
    for obstacle in parts:
        if obstacle.name != "A04_seat_cushion_contact_island":
            continue
        if fascia.distance(obstacle.shape) <= 0.01:
            fascia = fascia.cut(obstacle.shape)
    nose_matches = [
        part for part in parts if part.name == "A01_front_nose_shell"
    ]
    if len(nose_matches) != 1:
        raise KeyError(
            f"{state} front waist requires one A01 nose; "
            f"found {len(nose_matches)}"
        )
    nose_shape = nose_matches[0].shape
    nose_common = fascia.intersect(nose_shape)
    nose_common_volume = (
        0.0 if nose_common.isNull() else float(nose_common.Volume())
    )
    # This is a directional assembly split: the waist installs above the A01
    # nose and its local mating edge is removed in +Z.  A former generic OCC
    # offset frequently rejected the multi-aperture nose and then evaluated a
    # 27-copy three-dimensional fallback, making one state take more than five
    # minutes and threatening desktop stability.  The actual pre-partition
    # common B-Rep is a narrow local interface.  Its expanded bounding prism
    # is a single conservative service-gap cutter: it covers the complete
    # common region plus 1.2 mm on every side without offsetting or re-cutting
    # the rest of the nose.
    split = FRONT_NOSE_WAIST_DRY_SPLIT_MM
    cutter_offset = FRONT_NOSE_WAIST_CLEARANCE_ENVELOPE_OFFSET_MM
    local_clearance_margin = max(cutter_offset, split + 0.8)
    if nose_common_volume > 1.0e-6:
        common_box = nose_common.BoundingBox()
        clearance_cutter = (
            cq.Workplane("XY")
            .box(
                common_box.xlen + 2.0 * local_clearance_margin,
                common_box.ylen + 2.0 * local_clearance_margin,
                common_box.zlen + 2.0 * local_clearance_margin,
            )
            .translate(
                (
                    (common_box.xmin + common_box.xmax) / 2.0,
                    (common_box.ymin + common_box.ymax) / 2.0,
                    (common_box.zmin + common_box.zmax) / 2.0,
                )
            )
            .val()
        )
        nose_clearance_cutters = (clearance_cutter,)
        clearance_method = "expanded_local_common_brep_bounding_prism"
    else:
        # Defensive tangent-only case around the proven interface coordinates.
        nose_clearance_cutters = (
            cq.Workplane("XY")
            .box(12.0, 492.0, 18.0)
            .translate((-383.0, 0.0, 369.0))
            .val(),
        )
        clearance_method = "tangent_interface_local_bounding_prism"
    clearance_common_volumes: list[float] = []
    for cutter in nose_clearance_cutters:
        common = fascia.intersect(cutter)
        clearance_common_volumes.append(
            0.0 if common.isNull() else float(common.Volume())
        )
    if any(volume > 1.0e-6 for volume in clearance_common_volumes):
        fascia = fascia.cut(*nose_clearance_cutters)
    fascia = _valid_single(
        fascia,
        f"{state} continuous front waist fascia",
    )
    measured_nose_gap = float(fascia.distance(nose_shape))
    if measured_nose_gap < split - 0.02:
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape

        extrema = BRepExtrema_DistShapeShape(
            fascia.wrapped,
            nose_shape.wrapped,
        )
        extrema.Perform()
        contact_solutions: list[tuple[float, ...]] = []
        if extrema.IsDone():
            for solution in range(1, min(extrema.NbSolution(), 12) + 1):
                first = extrema.PointOnShape1(solution)
                second = extrema.PointOnShape2(solution)
                contact_solutions.append(
                    (
                        first.X(),
                        first.Y(),
                        first.Z(),
                        second.X(),
                        second.Y(),
                        second.Z(),
                    )
                )
        raise ValueError(
            f"{state} A01/A04 directed dry split is only "
            f"{measured_nose_gap:.6f} mm; required {split:.6f} mm; "
            f"contact_solutions={contact_solutions!r}"
        )
    parts.append(
        _new_part(
            "A04_front_waist_fascia",
            fascia,
            LUNAR_STONE,
            "mineral-matte PC-ABS removable U-section front waist fascia",
            "A04",
            state,
            "A single thin vertical U-section closes the front and oblique daylight line at the real waist datum without projecting a tray surface.",
            physical_occurrence_id="E6-A04-FRONT-WAIST-FASCIA",
            lower_gap_to_a01_nominal_mm=FRONT_NOSE_WAIST_DRY_SPLIT_MM,
            upper_gap_to_seat_ring_nominal_mm=2.0,
            rear_gap_to_a02_side_shell_nominal_mm=1.0,
            armrest_inner_gap_nominal_mm=3.0,
            service_removable=True,
            sensor_horizon_preserved=True,
            controlled_firewall_forward_clearance_nominal_mm=3.0,
            controlled_firewall_xmin_mm=-415.0,
            normal_sightline_open_cavity_closed=True,
            horizontal_shelf_surface_present=False,
            waist_surface_orientation="continuous_tall_vertical_u_section_with_crowned_hood",
            sculpted_hood_wall_nominal_mm=3.0,
            dry_split_to_seat_and_follow_skirt=True,
            a02_functional_inserts_are_physical_cutouts=True,
            a01_nose_physical_partition=True,
            removed_a01_nose_common_volume_mm3=nose_common_volume,
            a01_nose_clearance_envelope=clearance_method,
            a01_nose_clearance_envelope_offset_mm=cutter_offset,
            a01_nose_clearance_local_prism_margin_mm=(
                local_clearance_margin
            ),
            a01_nose_clearance_cutter_common_volumes_mm3=tuple(
                clearance_common_volumes
            ),
            measured_a01_nose_dry_split_mm=measured_nose_gap,
            production_certification_claimed=False,
        )
    )


def _front_nose_sightline_crown(state: str, parts: list[SkinPart]) -> None:
    """Make the toe-bay read as a closed instrument nose, not an open prototype cavity.

    The crown is a permanent A01 weather surface in every state.  Its shallow
    front brow continues the smoked perception horizon, while the short upper
    return hides the toe-bay hardware from normal standing sightlines.  The
    occupant-side opening remains unobstructed; this is neither a user shelf
    nor a state-dependent lid.
    """

    matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == "A01_front_nose_shell"
    ]
    if len(matches) != 1:
        raise KeyError(
            f"{state} requires exactly one A01_front_nose_shell; "
            f"found {len(matches)}"
        )
    index, nose = matches[0]

    # The 2.2 mm brow sits 0.8 mm ahead of the released perception carrier.
    # Its lower edge keeps a 1.2 mm dry split above the smoked horizon.  The
    # former horizontal slab created a second front tier, so a shallow weather
    # ramp now continues the brow into the waist datum without becoming a
    # usable shelf.
    brow = _rounded_panel_yz(
        (500.0, 25.8),
        2.2,
        (-483.9, 0.0, 349.1),
        10.0,
    )
    upper_return = rounded_rect_prism(
        (104.0, 500.0),
        3.0,
        (-433.0, 0.0, 359.0),
        18.0,
    )
    upper_return = _rotate_y(
        upper_return,
        (-433.0, 0.0, 359.0),
        -12.2,
    )
    closed_nose = _valid_single(
        nose.shape.fuse(brow).fuse(upper_return),
        f"{state} A01 permanent front sightline crown",
    )
    carrier_matches = [
        part
        for part in parts
        if part.name == "A01_perception_horizon_carrier"
    ]
    if len(carrier_matches) != 1:
        raise KeyError(
            f"{state} A01 crown requires one perception carrier; "
            f"found {len(carrier_matches)}"
        )
    # The carrier is a separate serviceable internal occurrence.  Partition
    # its exact installation envelope from the weather shell so both parts
    # meet without hidden material interpenetration.  No exterior datum or
    # optical hardpoint changes.
    carrier = carrier_matches[0]
    carrier_common = closed_nose.intersect(carrier.shape)
    carrier_common_volume = (
        0.0 if carrier_common.isNull() else float(carrier_common.Volume())
    )
    if carrier_common_volume > 1.0e-6:
        closed_nose = _valid_single(
            closed_nose.cut(carrier.shape),
            f"{state} A01 crown with perception-carrier installation pocket",
        )
    metadata = dict(nose.metadata)
    metadata.update(
        {
            "front_toe_bay_normal_sightline_crown": True,
            "permanent_all_states": True,
            "state_dependent_cover": False,
            "user_shelf_surface_present": False,
            "front_brow_wall_nominal_mm": 2.2,
            "upper_return_wall_nominal_mm": 3.0,
            "upper_return_slope_deg": 12.2,
            "dry_split_above_smoked_horizon_mm": 1.2,
            "dry_split_to_front_waist_mm": FRONT_NOSE_WAIST_DRY_SPLIT_MM,
            "occupant_side_foot_route_preserved": True,
            "released_perception_hardpoints_changed": False,
            "perception_carrier_installation_pocket_partitioned": True,
            "removed_carrier_common_volume_mm3": carrier_common_volume,
            "production_certification_claimed": False,
        }
    )
    parts[index] = replace(
        nose,
        shape=closed_nose,
        intent=(
            "Wraps the released front frame and sensor carriers with a permanent "
            "brow-and-crown weather surface, hiding toe-bay hardware from normal "
            "sightlines while preserving the occupant-side foot route."
        ),
        metadata=metadata,
    )


def _unified_front_perception_horizon(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Replace visible sensor cut-outs with one calm smoked optical field."""

    matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == "A01_perception_horizon_smoked_mask"
    ]
    if len(matches) != 1:
        raise KeyError(
            f"{state} requires one A01 perception horizon; found {len(matches)}"
        )
    index, horizon = matches[0]
    # The lens sits just ahead of the structural nose.  Sensor modules and the
    # A08 dual-channel foot-zone optics remain at their controlled hardpoints
    # behind spectrally tuned, visually uniform zones; no individual robot-eye
    # apertures are expressed on the exterior.
    unified = _rounded_panel_yz(
        (456.0, 122.0),
        3.0,
        (-487.0, 0.0, 274.0),
        28.0,
    )
    metadata = dict(horizon.metadata)
    metadata.update(
        {
            "one_continuous_perception_horizon": True,
            "individual_sensor_apertures_visually_suppressed": True,
            "controlled_sensor_hardpoints_moved": False,
            "hidden_spectral_transmission_zones": True,
            "front_outer_lens_dry_gap_to_nose_mm": 0.5,
            "decorative_light_strip": False,
            "production_certification_claimed": False,
        }
    )
    parts[index] = replace(
        horizon,
        shape=_valid_single(unified, f"{state} unified perception horizon"),
        color=SMOKED_UMBER,
        material=(
            "single low-gloss smoked polycarbonate optical field with hidden "
            "sensor-specific transmission zones"
        ),
        intent=(
            "One quiet smoked horizon communicates the forward sensing datum "
            "without exposing a collection of cameras or robot eyes."
        ),
        metadata=metadata,
    )


def _fixed_right_armrest(state: str, parts: list[SkinPart]) -> None:
    """Make both armrests continuous fixed shells with closed rear roots."""

    parts[:] = [
        part
        for part in parts
        if not (
            part.name.startswith("A05_armrest_table_bay_shell_")
            and "_service_segment_" in part.name
        )
        and not (
            part.name.startswith("A05_armrest_touch_lid_")
            and "_service_segment_" in part.name
        )
    ]
    seat_ring_matches = [
        part for part in parts if part.name == "A04_open_u_seat_pan_ring"
    ]
    if len(seat_ring_matches) != 1:
        raise KeyError(
            f"{state} fixed armrests require one A04 seat ring; found {len(seat_ring_matches)}"
        )
    seat_ring = seat_ring_matches[0].shape

    for side_name, side in (("left", -1), ("right", 1)):
        shell_name = f"A05_armrest_table_bay_shell_{side_name}"
        shell_matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name == shell_name
        ]
        if len(shell_matches) != 1:
            raise KeyError(
                f"{state} requires one fixed {side_name} A05 shell; found {len(shell_matches)}"
            )
        shell_index, shell_part = shell_matches[0]
        y_center = side * 338.75
        root_outer = _rounded_loft_z(
            (
                ((115.0, 57.5), (190.0, y_center), 420.0, 22.0),
                ((93.0, 57.5), (178.5, y_center), 548.0, 22.0),
                ((54.0, 57.5), (159.0, y_center), 675.0, 20.0),
            )
        )
        root_inner = _rounded_loft_z(
            (
                ((98.0, 45.5), (188.0, y_center), 424.0, 17.0),
                ((75.0, 45.5), (176.5, y_center), 548.0, 17.0),
                ((37.0, 45.5), (157.5, y_center), 671.0, 15.0),
            )
        )
        root_extension = _valid_single(
            root_outer.cut(root_inner),
            f"{state} {side_name} fixed armrest root extension",
        )
        fixed_shell = _valid_single(
            shell_part.shape.fuse(root_extension).cut(seat_ring),
            f"{state} {side_name} continuous fixed armrest shell",
        )
        shell_metadata = dict(shell_part.metadata)
        shell_metadata.update(
            {
                "side_opening_enabled": False,
                "fixed_continuous_armrest": True,
                "fixed_armrest_body": True,
                "top_lid_table_extraction_only": True,
                "legacy_side_table_opening_present": False,
                "v8_final_configuration": "bilateral_fixed_armrests",
                "closed_rear_root_x_range_mm": (132.5, 247.5),
                "rear_root_profile": "tapered_continuous_loft",
                "legacy_transfer_mechanism_in_production_bom": False,
                "normal_sightline_hinge_or_link_visible": False,
                "right_control_under_lid_recess": False,
                "right_control_fixed_forward_armrest_top": side > 0,
                "right_control_recess_bounds_mm": None,
            }
        )
        parts[shell_index] = replace(
            shell_part,
            shape=fixed_shell,
            intent="A continuous fixed wing encloses the table bay and rear root; the body has no side-opening hinge, link or table throat, while the separate top lid alone flips outward.",
            metadata=shell_metadata,
        )

        lid_name = f"A05_armrest_touch_lid_{side_name}"
        lid_matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name == lid_name
        ]
        if len(lid_matches) != 1:
            raise KeyError(
                f"{state} requires one fixed {side_name} A05 lid; found {len(lid_matches)}"
            )
        lid_index, lid_part = lid_matches[0]
        lid_extension = rounded_rect_prism(
            (120.0, 55.5),
            5.0,
            (185.0, y_center, 677.5),
            18.0,
        )
        fixed_lid = _valid_single(
            lid_part.shape.fuse(lid_extension),
            f"{state} {side_name} continuous fixed armrest lid",
        )
        # The compliant phone stops are genuine two-shot inserts.  Give each
        # one a shallow 0.2 mm-per-side mould seat in the rigid lid/plinth so
        # the TPE never survives as an interpenetrating applique.
        qi_stop_names: list[str] = []
        for stop in parts:
            if not stop.name.startswith(f"A05_{side_name}_qi_phone_stop_"):
                continue
            box = stop.shape.BoundingBox()
            seat = rounded_box(
                (box.xlen + 0.4, box.ylen + 0.4, box.zlen + 0.4),
                (
                    (box.xmin + box.xmax) / 2.0,
                    (box.ymin + box.ymax) / 2.0,
                    (box.zmin + box.zmax) / 2.0,
                ),
                1.0,
            )
            if float(fixed_lid.intersect(seat).Volume()) > 1.0e-6:
                fixed_lid = _valid_single(
                    fixed_lid.cut(seat).clean(),
                    f"{state} {side_name} lid with {stop.name} overmould seat",
                )
            qi_stop_names.append(stop.name)
        lid_metadata = dict(lid_part.metadata)
        lid_metadata.update(
            {
                "side_opening_enabled": False,
                "fixed_continuous_armrest": True,
                "fixed_armrest_body": True,
                "rear_root_lid_continuous": True,
                "top_lid_outward_opening_enabled": True,
                "top_lid_open_angle_deg": 105.0,
                "top_lid_hinge_side": "outer_longitudinal_edge",
                "four_final_states_lid_closed": True,
                "table_must_be_extracted_before_lid_recloses": True,
                "table_unfold_interlocked_until_lid_double_latched": True,
                "qi_phone_stop_overmould_seats": tuple(qi_stop_names),
                "qi_phone_stop_nominal_perimeter_clearance_mm": 0.2,
            }
        )
        parts[lid_index] = replace(
            lid_part,
            shape=fixed_lid,
            intent="The top lid continues over the sealed rear root and flips outward as one controlled panel; it is shown closed and double-latched in every final product state.",
            metadata=lid_metadata,
        )

    # The current product configuration has no transfer hinge, lock or manual
    # release.  Remove every generated transfer-language occurrence after all
    # legacy partition passes; the unmodified controlled source remains only in
    # the explicitly labelled trace/QA underlay.
    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A05_right_transfer_positive_lock_witness")
        and not part.name.startswith("A05_right_transfer_manual_release")
        and not part.name.startswith("A05_right_transfer_root_fairing")
    ]


def _integrated_upper_side_sails(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Join the fixed armrest and equipment bay behind one calm side field.

    Each sail is a real removable two-millimetre exterior panel placed outside
    the fixed A04/A05 structures.  It does not delete those structures, create
    a side-opening armrest or interfere with the independently opening top lid.
    """

    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A04_A05_integrated_side_sail_")
    ]
    # Follow's mechanical emergency stop was released against the former A05
    # outer wall.  The quiet two-millimetre sail is farther outboard, so seat
    # the existing guard and actuator on that new exterior datum instead of
    # burying them in the panel.  X/Z ergonomic hardpoints do not move; only
    # the sealed plunger length along the panel normal is updated.
    if state == "follow":
        surface_mounted_controls = {
            "A05_follow_external_emergency_stop_guard",
            "A05_follow_external_mechanical_emergency_stop",
        }
        target_inner_face_y = -(
            SIDE_SAIL_OUTER_FACE_ABS_Y_MM
            + FOLLOW_EXTERNAL_CONTROL_SEATING_GAP_MM
        )
        for index, part in enumerate(parts):
            if part.name not in surface_mounted_controls:
                continue
            bounds = part.shape.BoundingBox()
            y_shift = target_inner_face_y - float(bounds.ymax)
            seated_shape = part.shape.translate((0.0, y_shift, 0.0))
            seated_bounds = seated_shape.BoundingBox()
            centre = (
                (float(seated_bounds.xmin) + float(seated_bounds.xmax)) / 2.0,
                (float(seated_bounds.ymin) + float(seated_bounds.ymax)) / 2.0,
                (float(seated_bounds.zmin) + float(seated_bounds.zmax)) / 2.0,
            )
            metadata = dict(part.metadata)
            source_center = metadata.get("source_control_center_mm")
            link_length = None
            if (
                isinstance(source_center, (tuple, list))
                and len(source_center) == 3
            ):
                link_length = abs(centre[1] - float(source_center[1]))
            metadata.update(
                {
                    "final_exterior_projection_center_mm": centre,
                    "mechanical_plunger_link_mm": link_length,
                    "surface_mounted_to_integrated_side_sail": True,
                    "seating_gap_to_sail_outer_face_mm": (
                        FOLLOW_EXTERNAL_CONTROL_SEATING_GAP_MM
                    ),
                    "released_xz_hardpoint_changed": False,
                    "production_certification_claimed": False,
                }
            )
            parts[index] = replace(
                part,
                shape=_valid_single(
                    seated_shape,
                    f"{state} {part.name} seated on side sail",
                ),
                metadata=metadata,
            )
    outline = (
        (-392.0, 350.0),
        (-382.0, 640.0),
        (-355.0, 673.0),
        (210.0, 673.0),
        (242.0, 648.0),
        (250.0, 610.0),
        (250.0, 350.0),
        (218.0, 318.0),
        (-350.0, 318.0),
    )
    for side_name, side in (("left", -1), ("right", 1)):
        sail_workplane = (
            cq.Workplane("XZ")
            .polyline(outline)
            .close()
            .extrude(1.0, both=True)
        )
        try:
            sail_workplane = sail_workplane.edges("|Y").fillet(16.0)
        except Exception:
            pass
        sail = sail_workplane.translate(
            (0.0, side * 369.5, 0.0)
        ).val()
        # Keep the original single quiet RF-transparent field.  Only the real
        # gravity drain needs a small through-opening; the UWB frame remains
        # serviceable behind the removable sail and must not add a dark slot.
        drain_opening = _rounded_panel_xz(
            (34.0, 18.0),
            4.0,
            (-300.0, side * 369.5, 526.0),
            6.0,
        )
        # A shallow inner-face pocket clears the existing replaceable UWB
        # bezel while retaining more than one millimetre of uninterrupted
        # RF-transparent exterior skin.  The hardpoint does not move and no
        # new dark exterior slot is introduced.
        uwb_inner_recess = _rounded_panel_xz(
            (133.0, 33.0),
            0.8,
            (-75.0, side * 368.9, 400.0),
            7.5,
        )
        sail_cutters = [drain_opening, uwb_inner_recess]
        follow_external_interfaces = state == "follow" and side_name == "left"
        if follow_external_interfaces:
            # Only the hidden plunger passage pierces the field under the
            # surface-mounted emergency stop.  The status witness remains a
            # restrained recessed lens in its own 0.4 mm perimeter seat.
            plunger_opening = (
                cq.Workplane("XZ")
                .circle(FOLLOW_ESTOP_PLUNGER_OPENING_DIAMETER_MM / 2.0)
                .extrude(2.0, both=True)
                .translate((-294.0, -369.5, 590.0))
                .val()
            )
            witness_clearance = FOLLOW_STATUS_WITNESS_PERIMETER_CLEARANCE_MM
            status_witness_opening = _rounded_panel_xz(
                (92.0 + 2.0 * witness_clearance, 12.0 + 2.0 * witness_clearance),
                4.0,
                (-208.0, -369.5, 650.0),
                6.0 + witness_clearance,
            )
            sail_cutters.extend((plunger_opening, status_witness_opening))
        sail = _valid_single(
            sail.cut(*sail_cutters),
            f"{state} {side_name} side sail with physical service openings",
        )
        parts.append(
            _new_part(
                f"A04_A05_integrated_side_sail_{side_name}",
                _valid_single(
                    sail,
                    f"{state} {side_name} integrated upper side sail",
                ),
                LUNAR_STONE,
                "2 mm mineral-matte RF-transparent PC-ABS removable side sail",
                "A04",
                state,
                "One quiet removable side field visually joins the fixed armrest table bay to the upper equipment shoulder without adding a side-opening seam.",
                physical_occurrence_id=(
                    f"E6-A04-A05-INTEGRATED-SIDE-SAIL-{side_name.upper()}"
                ),
                fixed_to_upper_body=True,
                armrest_side_opening_enabled=False,
                service_removal_requires_safe_power_isolation=True,
                nominal_wall_mm=2.0,
                inner_face_abs_y_mm=368.5,
                outer_face_abs_y_mm=SIDE_SAIL_OUTER_FACE_ABS_Y_MM,
                dry_gap_to_a05_outer_wall_mm=1.0,
                minimum_gap_to_a03_outer_belt_mm=3.0,
                upper_dry_gap_to_lid_mm=2.0,
                lower_edge_tucks_behind_a03_belt=True,
                hidden_rf_transmission_zone=True,
                uwb_sail_cutout_present=False,
                uwb_inner_recess_depth_mm=0.8,
                minimum_remaining_uwb_outer_skin_mm=1.2,
                uwb_bezel_concealed_behind_rf_transparent_sail=True,
                cassette_drain_opening_mm=(34.0, 18.0),
                follow_external_control_interfaces=follow_external_interfaces,
                follow_estop_hidden_plunger_opening_diameter_mm=(
                    FOLLOW_ESTOP_PLUNGER_OPENING_DIAMETER_MM
                    if follow_external_interfaces
                    else None
                ),
                follow_status_witness_perimeter_clearance_mm=(
                    FOLLOW_STATUS_WITNESS_PERIMETER_CLEARANCE_MM
                    if follow_external_interfaces
                    else None
                ),
                service_interfaces_physically_partitioned=True,
                decorative_graphics_or_fake_seams=False,
                production_certification_claimed=False,
            )
        )


def _focus_drive_control_stow(state: str, parts: list[SkinPart]) -> None:
    """Conserve one exposed right-hand control pod at one fixed hand datum."""

    control_names = {
        "A05_right_removable_drive_pod",
        "A05_right_joystick",
        "A05_right_authorisation_key",
    }
    parts[:] = [
        part
        for part in parts
        if not any(
            part.name.startswith(name + "_service_segment_")
            for name in control_names
        )
    ]
    found = {part.name for part in parts if part.name in control_names}
    if found != control_names:
        raise KeyError(
            f"{state} must conserve the complete right control pod; missing "
            + ", ".join(sorted(control_names - found))
        )
    expected_pose = "fixed_forward_armrest_top"
    for index, part in enumerate(parts):
        if part.name not in control_names:
            continue
        metadata = dict(part.metadata)
        metadata.update(
            {
                "same_physical_occurrence_all_states": True,
                "state_pose": expected_pose,
                "state_transition_never_deletes_occurrence": True,
                "table_deployed_control_pose": (
                    "fixed_forward_armrest_top_clear_of_table_sweep"
                    if state in {"cafe", "focus"}
                    else None
                ),
                "externally_visible_in_locked_state": True,
                "fixed_forward_armrest_location_all_states": True,
                "moves_with_top_lid": True,
                "fixed_to": "A05_armrest_touch_lid_right",
                "service_motion_owner": "right_top_lid_0_to_105_deg",
                "joystick_may_fold_or_relocate_by_state": False,
                "drive_enabled_in_locked_state": state == "ride",
                "production_certification_claimed": False,
            }
        )
        parts[index] = replace(part, metadata=metadata)


@lru_cache(maxsize=1)
def _production_a08_root_release_paddle() -> cq.Shape:
    """Low-profile underside paddle for the conserved no-power A08 release.

    The former hollow over-shell projected as a closed luggage-handle loop in
    front elevation.  This is one broad glove-operable leaf tucked completely
    inside the fixed root plan.  Its rear edge remains the captive pivot datum;
    the existing hidden lever and cable provide the motion transfer to the
    unchanged safety-rated latch.
    """

    face = rounded_box(
        (3.0, 80.0, 18.0),
        (-485.5, 0.0, 104.0),
        4.0,
    )
    underside_lip = rounded_box(
        (8.0, 80.0, 4.0),
        (-489.5, 0.0, 96.0),
        2.0,
    )
    return _valid_single(
        face.fuse(underside_lip).clean(),
        "A08 recessed solid bottom-edge no-power release paddle",
    )


def _footrest_sightline_closure(state: str, parts: list[SkinPart]) -> None:
    """Install one physical captured-drawer A08 inventory in every state.

    Follow/Cafe/Focus use the stowed endpoint and Ride uses the deployed,
    positively locked endpoint.  Hidden stowage changes transforms, never the
    BOM.  The existing top/tread/perimeter occurrences remain authoritative
    because they contain the final through-drains and rear service cut-outs;
    the motion module supplies their endpoint datum and every mechanism B-Rep.
    """

    progress = 1.0 if default_footrest_is_deployed(state) else 0.0
    occurrences = a08_footrest_drawer_occurrences(progress, state)
    platform_names = {
        "A08_footrest_top_skin",
        "A08_footrest_inset_tread",
        "A08_footrest_perimeter_skin",
    }
    paddle_name = "A08_manual_release_paddle_shell"
    replaceable_occurrences = set(occurrences) - platform_names - {paddle_name}

    # Retire the fragmented prototype cowls/collars and any earlier version of
    # the production mechanism before installing this deterministic inventory.
    obsolete_prefixes = (
        "A08_footrest_root_cowl_",
        "A08_footrest_support_boot_",
        "A08_footrest_support_body_collar_",
    )
    parts[:] = [
        part
        for part in parts
        if not part.name.startswith(obsolete_prefixes)
        and part.name != "A08_footrest_root_front_visor"
        and part.name not in replaceable_occurrences
    ]

    # Preserve the one released manual-control occurrence and its function,
    # but remove the front-elevation closed loop that read as a carry handle.
    # The finished leaf is recessed 35 mm behind the root's foremost datum and
    # fully inside its X/Y/Z envelope.  Its 4 mm lower return is reachable by a
    # gloved hand without adding a front bezel, closed handle aperture or
    # state-dependent part; the original latch begins 1.0 mm behind it.
    paddle_matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == paddle_name
    ]
    if len(paddle_matches) != 1:
        raise KeyError(
            f"{state} requires one conserved {paddle_name}; "
            f"found {len(paddle_matches)}"
        )
    paddle_index, paddle = paddle_matches[0]
    paddle_metadata = dict(paddle.metadata)
    paddle_metadata.update(
        {
            "physical_occurrence_id": "E6-A08-MANUAL-RELEASE-PADDLE-SHELL",
            "same_physical_occurrence_all_states": True,
            "same_brep_all_states": True,
            "body_side_fixed": True,
            "moves_with": "A01_body",
            "functional_opening": "footrest_manual_latch no_power_release",
            "root_front_datum_x_mm": -528.0,
            "paddle_front_x_mm": -493.5,
            "paddle_recess_from_root_front_mm": 34.5,
            "paddle_face_mm": (80.0, 18.0),
            "paddle_underside_lip_depth_mm": 8.0,
            "paddle_visible_front_height_mm": 18.0,
            "source_latch_front_clearance_mm": 1.0,
            "fully_inside_a08_root_xyz_envelope": True,
            "closed_loop_or_carry_handle_outline": False,
            "glove_operable_underside_leaf": True,
            "rear_edge_captive_pivot": True,
            "hidden_mechanical_link_to_conserved_latch_required": True,
            "real_mechanical_link_required": True,
            "authorised_underside_actuation_only": True,
            "production_certification_claimed": False,
        }
    )
    parts[paddle_index] = replace(
        paddle,
        shape=_production_a08_root_release_paddle(),
        color=LUNAR_STONE,
        material=(
            "body-colour glass-filled PA paddle with a warm-touch TPE "
            "underside contact face"
        ),
        intent=(
            "A single recessed bottom-edge leaf preserves the conserved no-power "
            "footrest release while eliminating a front-visible luggage-handle "
            "loop; the gloved hand route remains within the fixed A08 root recess."
        ),
        metadata=paddle_metadata,
    )

    # The fixed root is one invariant service interface.  Give A01 the same
    # permanent dry corridor in all four states; optional Cafe/Focus opening
    # therefore cannot manufacture state-dependent body geometry.
    nose_matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == "A01_front_nose_shell"
    ]
    if len(nose_matches) != 1:
        raise KeyError(
            f"{state} requires one A01_front_nose_shell for A08; "
            f"found {len(nose_matches)}"
        )
    nose_index, nose = nose_matches[0]
    root_cutter = a08_footrest_root_nose_cutter(2.0)
    drawer_corridor = a08_footrest_drawer_host_corridor(3.0)
    root_common = float(nose.shape.intersect(root_cutter).Volume())
    root_relief = nose.shape if root_common <= 1.0e-6 else _valid_single(
        nose.shape.cut(root_cutter),
        f"{state} A01 permanent A08 drawer-root corridor",
    )
    drawer_common = float(root_relief.intersect(drawer_corridor).Volume())
    cut_nose = (
        root_relief
        if drawer_common <= 1.0e-6
        else _valid_single(
            root_relief.cut(drawer_corridor),
            f"{state} A01 permanent A08 captured-drawer throat",
        )
    )
    nose_metadata = dict(nose.metadata)
    partition_history = list(
        nose_metadata.get("cross_rigid_partition_history", ())
    )
    partition_history.append(
        {
            "interface": "A01_A08_permanent_drawer_root_corridor",
            "role": "fixed_A01_host_with_pose_invariant_A08_root_aperture",
            "operation": "BRep_subtract",
            "cutter": "A08_footrest_root_nose_cutter",
            "common_volume_removed_mm3": root_common,
            "functional_clearance_mm": 2.0,
        }
    )
    partition_history.append(
        {
            "interface": "A01_A08_permanent_captured_drawer_throat",
            "role": "fixed_A01_host_yields_to_conserved_A08_motion_BReps",
            "operation": "BRep_subtract",
            "cutter": "a08_footrest_drawer_host_corridor",
            "common_volume_removed_mm3": drawer_common,
            "functional_clearance_mm": 3.0,
        }
    )
    nose_metadata.update(
        {
            "cross_rigid_partitioned": True,
            "cross_rigid_partition_history": partition_history,
            "a08_drawer_root_corridor_permanent_all_states": True,
            "a08_drawer_root_clearance_mm": 2.0,
            "a08_captured_drawer_throat_clearance_mm": 3.0,
            "a08_captured_drawer_throat_permanent_all_states": True,
            "a08_moving_occurrences_preserved_uncut": True,
            "state_dependent_a08_nose_cut": False,
        }
    )
    parts[nose_index] = replace(
        nose,
        shape=cut_nose,
        metadata=nose_metadata,
    )

    # The support monocoques translate behind the continuous wheel belts.  A02
    # is a removable cosmetic carrier, so it receives one invariant swept
    # service corridor per side instead of being allowed to occupy the same
    # volume as a moving support at either locked endpoint.
    for side_name, side in (("left", -1), ("right", 1)):
        shell_name = f"A02_main_side_shell_{side_name}"
        shell_matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name == shell_name
        ]
        if len(shell_matches) != 1:
            raise KeyError(
                f"{state} A08 support corridor requires one {shell_name}; "
                f"found {len(shell_matches)}"
            )
        shell_index, shell = shell_matches[0]
        corridor = a08_footrest_support_host_corridor(side, 1.0)
        common = float(shell.shape.intersect(corridor).Volume())
        relieved = (
            shell.shape
            if common <= 1.0e-6
            else _valid_single(
                shell.shape.cut(corridor).clean(),
                f"{state} {side_name} A02 swept A08 support corridor",
            )
        )
        shell_metadata = dict(shell.metadata)
        history = list(shell_metadata.get("cross_rigid_partition_history", ()))
        history.append(
            {
                "interface": "A02_A08_support_monocoque_swept_corridor",
                "operation": "BRep_subtract",
                "cutter": "a08_footrest_support_host_corridor",
                "common_volume_removed_mm3": common,
                "functional_clearance_mm": 1.0,
                "hidden_behind": f"A03_continuous_wheel_belt_shell_{side_name}",
            }
        )
        shell_metadata.update(
            {
                "cross_rigid_partitioned": True,
                "cross_rigid_partition_history": history,
                "a08_support_swept_corridor_permanent_all_states": True,
                "a08_support_swept_corridor_clearance_mm": 1.0,
                "moving_a08_support_preserved_uncut": True,
            }
        )
        parts[shell_index] = replace(
            shell,
            shape=relieved,
            metadata=shell_metadata,
        )

    # Keep the released final platform surfaces, and compare their actual
    # solids with the motion B-Reps.  Top and tread must be exact B-Rep
    # matches.  The motion perimeter intentionally retains the rear service
    # throat material removed from the finished perimeter, so it may only be
    # used as a conservative collision superset: the finished solid must be
    # wholly contained by it, never merely share the same bounding box.
    for name in sorted(platform_names):
        indices = [index for index, part in enumerate(parts) if part.name == name]
        if len(indices) != 1:
            raise KeyError(f"{state} requires one {name}; found {len(indices)}")
        index = indices[0]
        part = parts[index]
        actual_box = part.shape.BoundingBox()
        datum_box = occurrences[name].BoundingBox()
        maximum_bound_error = max(
            abs(actual - expected)
            for actual, expected in zip(
                (
                    actual_box.xmin,
                    actual_box.xmax,
                    actual_box.ymin,
                    actual_box.ymax,
                    actual_box.zmin,
                    actual_box.zmax,
                ),
                (
                    datum_box.xmin,
                    datum_box.xmax,
                    datum_box.ymin,
                    datum_box.ymax,
                    datum_box.zmin,
                    datum_box.zmax,
                ),
            )
        )
        if maximum_bound_error > 1.0e-6:
            raise ValueError(
                f"{state} {name} misses captured-drawer endpoint by "
                f"{maximum_bound_error:.9f} mm"
            )
        common_volume = float(part.shape.intersect(occurrences[name]).Volume())
        final_minus_motion = float(part.shape.cut(occurrences[name]).Volume())
        motion_minus_final = float(occurrences[name].cut(part.shape).Volume())
        symmetric_difference = (
            float(part.shape.Volume())
            + float(occurrences[name].Volume())
            - 2.0 * common_volume
        )
        if name in {"A08_footrest_top_skin", "A08_footrest_inset_tread"}:
            if abs(symmetric_difference) > 1.0e-3:
                raise ValueError(
                    f"{state} {name} is not the same B-Rep as the A08 motion "
                    f"solid; symmetric difference={symmetric_difference:.9f} mm3"
                )
            motion_geometry_relation = "exact_same_brep"
        else:
            if final_minus_motion > 1.0e-6:
                raise ValueError(
                    f"{state} {name} escapes its conservative A08 motion "
                    f"envelope by {final_minus_motion:.9f} mm3"
                )
            motion_geometry_relation = "final_brep_contained_by_conservative_motion_superset"
        metadata = dict(part.metadata)
        metadata.update(
            {
                "a08_motion_contract": "captured_drawer_over_centre_v1",
                "a08_motion_progress": progress,
                "motion_datum_maximum_bound_error_mm": maximum_bound_error,
                "motion_geometry_relation": motion_geometry_relation,
                "motion_common_volume_mm3": common_volume,
                "motion_symmetric_difference_mm3": symmetric_difference,
                "final_minus_motion_volume_mm3": final_minus_motion,
                "motion_minus_final_volume_mm3": motion_minus_final,
                "same_physical_occurrence_all_states": True,
                "moves_with": "footrest_platform",
                "two_channel_foot_zone_clear_required_before_motion": True,
                "production_certification_claimed": False,
            }
        )
        parts[index] = replace(part, metadata=metadata)

    for name in sorted(replaceable_occurrences):
        shape = _valid_single(occurrences[name], f"{state} {name}")
        fixed = name in A08_FIXED_OCCURRENCE_NAMES
        if "monocoque" in name or "labyrinth_baffle" in name:
            color = LUNAR_STONE
            material = "impact-modified mineral-matte PC-ABS serviceable monocoque"
        elif "witness" in name or "sensor" in name or "interlock" in name:
            color = SMOKED_UMBER
            material = "sealed safety-rated sensing module with smoked optical window"
        elif "bearing" in name:
            color = GRAPHITE_BROWN
            material = "replaceable dry-running polymer plain bearing"
        elif "pin" in name or "link" in name or "shaft" in name:
            color = CHAMPAGNE
            material = "hard-anodised 6061-T6 mechanism member"
        else:
            color = GRAPHITE_BROWN
            material = "hard-anodised nested aluminium load-path cartridge"

        metadata: dict[str, object] = {
            "physical_occurrence_id": "E6-" + name.upper().replace("_", "-"),
            "a08_motion_contract": "captured_drawer_over_centre_v1",
            "a08_motion_progress": progress,
            "same_physical_occurrence_all_states": True,
            "body_side_fixed": fixed,
            "moves_with": "A01_body" if fixed else "A08_commanded_motion",
            "captured_linear_guide_load_path": (
                "guide" in name or "cartridge" in name or "rail" in name
            ),
            "collision_allowlist_permitted": False,
            "two_channel_foot_zone_clear_required_before_motion": True,
            "production_certification_claimed": False,
        }
        if name == "A08_footrest_root_monocoque":
            metadata.update(
                {
                    "closed_roof": True,
                    "closed_front_wall": False,
                    "closed_side_returns": True,
                    "central_platform_and_undertray_motion_throat": True,
                    "front_sightline_closes_with_moving_undertray": False,
                    "front_sightline_closed_by_fixed_rear_labyrinth": True,
                    "lower_drain_and_service_opening": True,
                    "central_manual_release_access_from_underside": True,
                    "normal_front_sightline_closed_by_root_alone": False,
                    "normal_top_and_oblique_sightlines_closed_by_root_alone": False,
                    "pose_invariant": True,
                }
            )
        if name == "A08_footrest_rear_labyrinth_baffle":
            metadata.update(
                {
                    "fixed_rear_sightline_closeout": True,
                    "normal_front_and_standing_oblique_sightlines_closed": True,
                    "minimum_moving_dry_gap_mm": 5.0,
                    "guide_mount_feet_face_contact": True,
                    "human_foot_and_shin_common_volume_mm3": 0.0,
                    "pose_invariant": True,
                }
            )
        if "support_monocoque" in name:
            metadata.update(
                {
                    "independent_moving_support_shell": True,
                    "outer_side_sightline_closeout": True,
                    "minimum_platform_dry_split_mm": 4.0,
                    "controlled_front_tyre_clearance_mm": 14.0,
                    "controlled_rocker_sweep_clearance_mm": 4.0,
                }
            )
        if "lock_pin" in name:
            station = "stowed" if "stowed" in name else "deployed"
            engaged = (station == "stowed" and progress == 0.0) or (
                station == "deployed" and progress == 1.0
            )
            metadata.update(
                {
                    "positive_lock_station": station,
                    "positive_lock_engaged": engaged,
                    "retracted_during_motion": True,
                    "load_bypasses_actuator_at_locked_endpoint": True,
                }
            )
        if "foot_zone" in name or "interlock" in name:
            metadata.update(
                {
                    "safety_channel": "A" if name.endswith("_a") else "B",
                    "fail_closed": True,
                    "seat_mat_alone_sufficient": False,
                    "motion_enable_requires_both_channels_clear": True,
                    "concealed_behind_single_smoked_perception_horizon": True,
                    "separate_exterior_robot_eye_created": False,
                }
            )
        parts.append(
            _new_part(
                name,
                shape,
                color,
                material,
                "A08",
                state,
                "A physical member of the captured twin-drawer and paired over-centre footrest load path; the occurrence remains on the BOM in every state.",
                **metadata,
            )
        )


def _underleaf_pod(
    *,
    outer_size: tuple[float, float, float],
    outer_center: tuple[float, float, float],
    cavity_size: tuple[float, float, float],
    cavity_center: tuple[float, float, float],
    stage_center_xy: tuple[float, float],
    label: str,
) -> cq.Shape:
    outer = rounded_box(outer_size, outer_center, 18.0)
    cavity = rounded_box(cavity_size, cavity_center, 15.0)
    shell = outer.cut(cavity)
    aperture = rounded_box(
        (86.0, 86.0, outer_size[2] + 12.0),
        (stage_center_xy[0], stage_center_xy[1], outer_center[2]),
        12.0,
    )
    return _valid_single(shell.cut(aperture), label)


def _mirror_table_sections_y(
    sections: tuple[
        tuple[tuple[float, float], tuple[float, float], float, float],
        ...,
    ],
    side: int,
) -> tuple[
    tuple[tuple[float, float], tuple[float, float], float, float],
    ...,
]:
    return tuple(
        (size, (center[0], side * abs(center[1])), z, radius)
        for size, center, z, radius in sections
    )


def _focus_table_a05_clearance_guard(side: int) -> cq.Shape:
    """Conservative symmetric exclusion for A05 plus the inboard HMI crown."""

    # The final fixed lid contains a tilted HMI plinth on the left and a
    # continuous rear-root extension on both sides.  Their compound fillets
    # reach farther inboard than the earlier axis-aligned bay proxy.  Carry the
    # armrest exclusion five millimetres inward, then reserve a second five-
    # millimetre HMI crown strip through the complete monocoque top.  This is a
    # physical trimming boundary on the moving belly, not a collision waiver.
    y_min, y_max = (
        (-368.6, -303.9) if side < 0 else (303.9, 368.6)
    )
    armrest = (
        cq.Workplane("XY")
        .box(629.7, y_max - y_min, 262.2)
        .translate(
            (
                (-381.1 + 248.6) / 2.0,
                (y_min + y_max) / 2.0,
                550.0,
            )
        )
        .val()
    )
    strip_y_min, strip_y_max = (
        (-303.9, -298.9) if side < 0 else (298.9, 303.9)
    )
    hmi_strip = (
        cq.Workplane("XY")
        .box(620.7, 5.0, 50.0)
        .translate(
            (
                (-372.1 + 248.6) / 2.0,
                (strip_y_min + strip_y_max) / 2.0,
                667.0,
            )
        )
        .val()
    )
    high_y_min, high_y_max = (
        (-368.6, -298.9) if side < 0 else (298.9, 368.6)
    )
    hmi_high_band = (
        cq.Workplane("XY")
        .box(620.7, high_y_max - high_y_min, 15.9)
        .translate(
            (
                (-372.1 + 248.6) / 2.0,
                (high_y_min + high_y_max) / 2.0,
                (681.1 + 697.0) / 2.0,
            )
        )
        .val()
    )
    return armrest.fuse(hmi_strip).fuse(hmi_high_band)


def _cafe_table_a05_clearance_guard() -> cq.Shape:
    """Conservative fixed A05 boundary with a real 1.1 mm Café dry split."""

    return (
        cq.Workplane("XY")
        .box(629.7, 59.7, 262.2)
        .translate(
            (
                (-381.1 + 248.6) / 2.0,
                (308.9 + 368.6) / 2.0,
                550.0,
            )
        )
        .val()
    )


def _cafe_table_functional_keepouts() -> tuple[cq.Shape, cq.Shape]:
    """One-millimetre service boundaries around the released Café locks."""

    return (
        rounded_box(
            (48.0, 22.0, 8.0),
            (-372.0, 120.0, 689.0),
            6.0,
        ),
        rounded_box(
            (22.0, 22.0, 6.0),
            (-430.0, 183.0, 691.0),
            5.0,
        ),
    )


@lru_cache(maxsize=1)
def _cafe_underleaf_monocoque_master() -> cq.Shape:
    """One waisted hollow shell from the Café lift root into its right leaf."""

    outer_sections = (
        ((134.0, 142.0), (-430.0, 290.0), 643.0, 26.0),
        ((134.0, 142.0), (-430.0, 290.0), 647.0, 26.0),
        ((162.0, 158.0), (-421.0, 272.0), 658.0, 28.0),
        ((212.0, 190.0), (-404.0, 244.0), 674.0, 31.0),
        ((246.0, 224.0), (-383.0, 216.0), 686.0, 34.0),
        ((250.0, 238.0), (-360.0, 205.0), 691.8, 35.0),
        ((250.0, 238.0), (-360.0, 205.0), 692.0, 35.0),
    )
    # Six millimetres of XY shell allowance prevent the local B-spline
    # self-crossing found in the former nominal-four-millimetre eccentric
    # loft; the lower closure remains four millimetres and is the design
    # minimum wall in this exterior envelope study.
    inner_sections = (
        ((122.0, 130.0), (-430.0, 290.0), 647.0, 20.0),
        ((122.0, 130.0), (-430.0, 290.0), 650.0, 20.0),
        ((150.0, 146.0), (-421.0, 272.0), 658.0, 22.0),
        ((200.0, 178.0), (-404.0, 244.0), 674.0, 25.0),
        ((234.0, 212.0), (-383.0, 216.0), 686.0, 28.0),
        ((238.0, 226.0), (-360.0, 205.0), 692.0, 29.0),
        ((238.0, 226.0), (-360.0, 205.0), 696.0, 29.0),
    )
    shell = _rounded_loft_z(outer_sections).cut(
        _rounded_loft_z(inner_sections)
    )
    shell = shell.cut(
        rounded_box(
            (82.0, 82.0, 68.0),
            (-430.0, 300.0, 670.0),
            16.0,
        )
    )
    shell = shell.cut(_cafe_table_a05_clearance_guard())
    for keepout in _cafe_table_functional_keepouts():
        shell = shell.cut(keepout)
    # The Café table is still the same two 430 x 134.5 mm rigid half-leaves.
    # After the +90 degree turn their internal fold lies at X=-350 mm and the
    # load-bearing outer/root half occupies the more-negative X side.  The
    # previous cosmetic belly crossed 115 mm into the free half and physically
    # locked the fold.  Keep the rigid support at least 3 mm behind the fold.
    root_half_space = (
        cq.Workplane("XY")
        .box(1400.0, 1200.0, 500.0)
        .translate((-1053.0, 0.0, 600.0))
        .val()
    )
    shell = shell.intersect(root_half_space)
    return _valid_single(
        shell.clean(),
        "Café waisted underleaf monocoque",
    )


@lru_cache(maxsize=2)
def _focus_underleaf_monocoque_master(side: int) -> cq.Shape:
    """One four-millimetre hollow waist from each lift root into its leaf."""

    if side not in {-1, 1}:
        raise ValueError(f"Focus table side must be -1 or 1, got {side}")
    outer_base = (
        ((134.0, 140.0), (-405.0, 280.0), 643.0, 26.0),
        ((134.0, 140.0), (-405.0, 280.0), 647.0, 26.0),
        ((158.0, 148.0), (-408.0, 258.0), 658.0, 27.0),
        ((210.0, 160.0), (-410.0, 236.0), 674.0, 30.0),
        ((264.0, 166.0), (-407.0, 213.0), 686.0, 32.0),
        ((276.0, 164.0), (-405.0, 207.0), 691.8, 32.0),
        ((276.0, 164.0), (-405.0, 207.0), 692.0, 32.0),
    )
    inner_base = (
        ((126.0, 132.0), (-405.0, 280.0), 647.0, 22.0),
        ((126.0, 132.0), (-405.0, 280.0), 650.0, 22.0),
        ((150.0, 140.0), (-408.0, 258.0), 658.0, 23.0),
        ((202.0, 152.0), (-410.0, 236.0), 674.0, 26.0),
        ((256.0, 158.0), (-407.0, 213.0), 686.0, 28.0),
        ((268.0, 156.0), (-405.0, 207.0), 692.0, 28.0),
        ((268.0, 156.0), (-405.0, 207.0), 696.0, 28.0),
    )
    outer = _rounded_loft_z(_mirror_table_sections_y(outer_base, side))
    cavity = _rounded_loft_z(_mirror_table_sections_y(inner_base, side))
    stage_aperture = rounded_box(
        (82.0, 82.0, 68.0),
        (-405.0, side * 300.0, 670.0),
        16.0,
    )
    # Each Focus table has its own internal fold at Y=side*141 mm.  Retain the
    # monocoque only on the outer/root half and hold its hard edge 3 mm away
    # from that fold; the free inner half must be able to rotate through all
    # twenty-one validated fold poses without a hidden PC-ABS bridge.
    root_half_space = (
        cq.Workplane("XY")
        .box(1400.0, 600.0, 500.0)
        .translate((0.0, side * 444.0, 600.0))
        .val()
    )
    return _valid_single(
        outer.cut(cavity)
        .cut(stage_aperture)
        .cut(_focus_table_a05_clearance_guard(side))
        .intersect(root_half_space)
        .clean(),
        f"Focus underleaf monocoque side {side}",
    )


@lru_cache(maxsize=2)
def _focus_root_tapered_cap_master(side: int) -> cq.Shape:
    """Low open-bottom four-millimetre cap at one Focus lift mouth."""

    if side not in {-1, 1}:
        raise ValueError(f"Focus table side must be -1 or 1, got {side}")
    outer_base = (
        ((92.0, 63.2), (-405.0, 308.425), 694.8, 18.0),
        ((92.0, 63.2), (-405.0, 308.425), 696.0, 18.0),
        ((88.0, 59.2), (-405.5, 307.725), 700.0, 17.0),
        ((84.0, 55.2), (-406.0, 307.025), 704.0, 16.0),
        ((84.0, 55.2), (-406.0, 307.025), 704.2, 16.0),
    )
    inner_base = (
        ((84.0, 55.2), (-405.0, 308.425), 694.2, 14.0),
        ((84.0, 55.2), (-405.0, 308.425), 696.0, 14.0),
        ((80.0, 51.2), (-405.5, 307.725), 698.0, 13.0),
        ((76.0, 47.2), (-406.0, 307.025), 700.2, 12.0),
    )
    outer = _rounded_loft_z(_mirror_table_sections_y(outer_base, side))
    cavity = _rounded_loft_z(_mirror_table_sections_y(inner_base, side))
    return _valid_single(
        outer.cut(cavity).clean(),
        f"Focus tapered table-root cap side {side}",
    )


def _clear_pod_from_a05(
    pod: cq.Shape,
    parts: list[SkinPart],
    label: str,
) -> list[cq.Shape]:
    """Exact-cut deployed A09 skin from the fixed A05 bay surfaces."""

    cleared = pod
    for obstacle in parts:
        if obstacle.module != "A05":
            continue
        if cleared.distance(obstacle.shape) <= 0.01:
            cleared = cleared.cut(obstacle.shape)
    if cleared.isNull() or not cleared.isValid() or cleared.Volume() <= 0.0:
        raise ValueError(f"{label} vanished or became invalid after A05 clearance")
    solids = sorted(cleared.Solids(), key=lambda shape: shape.Volume(), reverse=True)
    if not solids:
        raise ValueError(f"{label} has no solid after A05 clearance")
    return [_valid_single(shape, f"{label} component {index}") for index, shape in enumerate(solids, 1)]


def _cafe_root_skin_part(
    state: str,
    occurrence: CafeRootOccurrence,
) -> SkinPart:
    """Apply truthful CMF/visibility to one upstream Cafe layout occurrence."""

    common = {
        "physical_occurrence_id": occurrence.physical_occurrence_id,
        "motion_owner": occurrence.motion_owner,
        "root_layout_architecture": (
            "a05_metal_cassette_internal_bearing_single_closed_root_neck"
        ),
        "layout_kinematic_envelope_only": True,
        "supplier_component_not_frozen": True,
        "production_certification_claimed": False,
    }
    role = occurrence.role
    if role == "fixed_drainable_yoke_housing":
        return _new_part(
            occurrence.name,
            occurrence.shape,
            GRAPHITE_BROWN,
            "blackened aluminium internal drainable root housing",
            "A09",
            state,
            "The fixed housing remains inside the right armrest and bolts to the real A05 metal cassette; it is never used as an exterior styling shell.",
            fixed_to="A05_table_root_structural_cassette_right",
            final_exterior_visible=False,
            underside_service_and_drain_opening=True,
            **common,
        )
    if role == "fixed_aluminium_yoke_outer_race_and_lift_collar":
        return _new_part(
            occurrence.name,
            occurrence.shape,
            CHAMPAGNE,
            "hard-anodised 7075 aluminium fixed yoke and outer bearing carrier",
            "A09",
            state,
            "A 36 mm cross-beam reaches both internal housing walls and carries the bearing outer race without a floating cosmetic gap.",
            fixed_cross_beam_length_mm=36.0,
            outer_race_inner_diameter_mm=16.0,
            final_exterior_visible=False,
            **common,
        )
    if role == "catalog_bearing_inner_race_and_rail_pedestal":
        return _new_part(
            occurrence.name,
            occurrence.shape,
            GRAPHITE_BROWN,
            "supplier-envelope sealed rotary bearing hub",
            "A09",
            state,
            "The internal hub reserves a sealed rotary-bearing package and meets the short torque key at the final locked endpoint; detailed rollers and fasteners remain supplier-controlled.",
            supplier_controlled_rolling_elements_required=True,
            final_exterior_visible=False,
            **common,
        )
    if role == "internal_rotary_torque_key":
        return _new_part(
            occurrence.name,
            occurrence.shape,
            GRAPHITE_BROWN,
            "blackened stainless internal rotary torque key",
            "A09",
            state,
            "A real four-millimetre key closes the final static gap from the bearing hub to the closed table root neck; it is not misrepresented as a ninety-millimetre linear rail.",
            measured_bridge_span_mm=4.0,
            final_exterior_visible=False,
            **common,
        )
    if role == "table_attached_closed_root_neck_and_internal_spreader":
        return _new_part(
            occurrence.name,
            occurrence.shape,
            GRAPHITE_BROWN,
            "low-gloss graphite stainless closed root neck and internal spreader",
            "A09",
            state,
            "The one unavoidable member outside A05 is a smooth closed neck in the table's underside shadow; the same solid continues 220 mm inside the outer half-leaf so no hinge, rail or fastener is exposed.",
            moves_with="cafe_right_outer_root_half_leaf",
            physical_leaf_id="WC-A09-TABLE-HALF-LEAF-RIGHT-OUTER",
            internal_spreader_length_mm=220.0,
            internal_spreader_section_mm=(22.0, 220.0, 4.0),
            visible_gap_neck_y_bounds_mm=(276.0, 310.0),
            visible_gap_neck_section_mm=(22.0, 8.0),
            visible_gap_neck_is_smooth_closed_envelope=True,
            root_neck_outside_armrest=True,
            hinge_bearing_and_lock_outside_armrest=False,
            does_not_bridge_internal_fold=True,
            final_exterior_visible=True,
            **common,
        )
    raise ValueError(f"Unsupported Cafe root mechanism role {role!r}")


def _table_understructure_closure(state: str, parts: list[SkinPart]) -> None:
    if state == "cafe":
        # Retire only the exposed prototype vocabulary.  The five final layout
        # root occurrences now enter upstream in ``skin_upper`` so every
        # collision/partition pass sees the actual B-Reps.  Closure may style
        # those occurrences but may not delete and regenerate them downstream.
        retired_prefixes = (
            "A09_cafe_armrest_to_table_root_bridge_right",
            "A09_cafe_root_mechanism_fairing_right",
            "A09_cafe_underleaf_saddle_right",
            "A09_cafe_telescopic_rail_cover_",
            "A09_cafe_linear_guide_shoe_",
            "A09_cafe_table_mount_shoe_",
            "A09_table_lift_boot_right",
            "A09_table_lift_moving_stage_2_right",
            "A09_table_lift_moving_stage_3_right",
            "A09_cafe_table_lift_base_socket_right",
        )
        parts[:] = [
            part
            for part in parts
            if not part.name.startswith(retired_prefixes)
        ]
        for occurrence in cafe_root_final_occurrences():
            matches = [
                (index, part)
                for index, part in enumerate(parts)
                if part.name == occurrence.name
            ]
            if len(matches) != 1:
                raise KeyError(
                    f"cafe requires one upstream {occurrence.name}; "
                    f"found {len(matches)}"
                )
            index, actual = matches[0]
            common = float(actual.shape.intersect(occurrence.shape).Volume())
            symmetric_difference = (
                float(actual.shape.Volume())
                + float(occurrence.shape.Volume())
                - 2.0 * common
            )
            if symmetric_difference > 1.0e-3:
                raise ValueError(
                    f"cafe upstream root {occurrence.name} changed before "
                    f"appearance closure: symmetric_difference="
                    f"{symmetric_difference:.9f} mm3"
                )
            parts[index] = _cafe_root_skin_part(state, occurrence)
    elif state == "focus":
        # The exposed prototype bridge/fairing/saddle/belly language is fully
        # retired.  The source model now provides one fixed flat root box,
        # three compact nested guides and one leaf-attached hidden tongue per
        # side, all packaged inside A05 except for the permitted tongue through
        # its small inner-wall port.  Appearance closure must not add a second
        # cosmetic load path around that physically resolved mechanism.
        retired_prefixes = (
            "A09_focus_armrest_to_table_root_bridge_",
            "A09_focus_root_fairing_",
            "A09_focus_underleaf_saddle_",
            "A09_focus_underleaf_motion_belly_",
            "A09_focus_table_root_crown_",
            "A09_focus_table_lift_base_socket_",
            "A09_table_lift_boot_left",
            "A09_table_lift_boot_right",
            "A09_table_lift_moving_stage_2_left",
            "A09_table_lift_moving_stage_2_right",
            "A09_table_lift_moving_stage_3_left",
            "A09_table_lift_moving_stage_3_right",
        )
        parts[:] = [
            part
            for part in parts
            if not part.name.startswith(retired_prefixes)
        ]
        for side_name, side in (("left", -1), ("right", 1)):
            required_names = (
                f"A09_focus_internal_root_box_{side_name}",
                f"A09_focus_internal_nested_guide_stage_1_{side_name}",
                f"A09_focus_internal_nested_guide_stage_2_{side_name}",
                f"A09_focus_internal_nested_guide_stage_3_{side_name}",
                f"A09_focus_table_hidden_root_tongue_{side_name}",
            )
            missing = [
                name
                for name in required_names
                if sum(part.name == name for part in parts) != 1
            ]
            if missing:
                raise KeyError(
                    f"focus {side_name} concealed table root is incomplete: "
                    f"{missing!r}"
                )


def _focus_table_root_crowns(state: str, parts: list[SkinPart]) -> None:
    """Retire exterior root crowns and keep the real centre lock pockets."""

    if state != "focus":
        return

    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A09_focus_table_root_crown_")
    ]
    for side_name, side in (("left", -1), ("right", 1)):
        # Move the two mechanical releases from the top surface into real
        # pockets in the inner vertical edge.  The released identities remain
        # tactile and serviceable, but no four-piece "piano hinge" highlight
        # stitches the two leaves together from normal/top sightlines.
        edge_matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name
            == f"A09_table_edge_band_{side_name}_fold_half_inner"
        ]
        if len(edge_matches) != 1:
            raise KeyError(
                f"focus requires one {side_name} inner folding-half edge band for lock pockets; "
                f"found {len(edge_matches)}"
            )
        edge_index, edge_part = edge_matches[0]
        edge_shape = edge_part.shape
        for lock_x in FOCUS_LOCK_STATIONS_X_MM:
            edge_shape = edge_shape.cut(
                rounded_box(
                    (32.0, 2.0, 8.0),
                    (lock_x, side * 10.0, 700.0),
                    2.0,
                )
            )
        edge_metadata = dict(edge_part.metadata)
        edge_metadata.update(
            {
                "inner_edge_mechanical_lock_pocket_count": 2,
                "lock_pockets_do_not_reduce_center_gap": True,
                "top_surface_lock_hardware_removed": True,
            }
        )
        parts[edge_index] = replace(
            edge_part,
            shape=_valid_single(
                edge_shape.clean(),
                f"focus {side_name} table edge with lock pockets",
            ),
            metadata=edge_metadata,
        )

        for station, lock_x in enumerate(FOCUS_LOCK_STATIONS_X_MM, start=1):
            bezel_outer = rounded_box(
                (30.0, 0.8, 7.0),
                (lock_x, side * 10.0, 700.0),
                2.0,
            )
            bezel_inner = rounded_box(
                (24.0, 1.2, 5.0),
                (lock_x, side * 10.0, 700.0),
                1.5,
            )
            refinements = (
                (
                    f"A09_focus_lock_paddle_bezel_{side_name}_{station}",
                    _valid_single(
                        bezel_outer.cut(bezel_inner).clean(),
                        f"focus {side_name} lock bezel {station}",
                    ),
                    "A thin frame sits inside the leaf's vertical seam edge and locates the mechanical release without drawing a hinge across the tabletop.",
                ),
                (
                    f"A09_focus_lock_release_paddle_{side_name}_{station}",
                    rounded_box(
                        (22.0, 0.6, 4.2),
                        (lock_x, side * 10.0, 700.0),
                        1.2,
                    ),
                    "A tactile vertical inner-edge release remains entirely on one leaf, below the top plane and outside the controlled twelve-millimetre escape seam.",
                ),
            )
            for name, shape, intent in refinements:
                matches = [
                    (index, part)
                    for index, part in enumerate(parts)
                    if part.name == name
                ]
                if len(matches) != 1:
                    raise KeyError(
                        f"focus requires one {name} for flush lock refinement; "
                        f"found {len(matches)}"
                    )
                index, part = matches[0]
                metadata = dict(part.metadata)
                metadata.update(
                    {
                        "controlled_center_gap_mm": 12.0,
                        "does_not_bridge_center_seam": True,
                        "flush_inner_edge_lock_witness": True,
                        "external_hinge_language_present": False,
                        "top_surface_projection_mm": 0.0,
                        "vertical_inner_edge_mount": True,
                        "inner_edge_lock_center_abs_y_mm": 10.0,
                        "minimum_dry_clearance_to_centre_seal_mm": 0.6,
                    }
                )
                parts[index] = replace(
                    part,
                    shape=_valid_single(shape, f"focus flush {name}"),
                    intent=intent,
                    metadata=metadata,
                )


def _a09_lift_stage_name(state: str, side_name: str, stage_index: int) -> str:
    if stage_index == 1:
        return (
            "A09_table_lift_boot_right"
            if state == "cafe"
            else f"A09_table_lift_boot_{side_name}"
        )
    return f"A09_table_lift_moving_stage_{stage_index}_{side_name}"


def _a09_instrument_spine_stage(
    current_stage: cq.Shape,
    stage_index: int,
) -> cq.Shape:
    """Rebody one A09 stage without moving its released axis or Z extrema."""

    if stage_index not in A09_LIFT_STAGE_PROFILE_CONTRACT:
        raise ValueError(f"Unsupported A09 lift stage index {stage_index}")
    profile = A09_LIFT_STAGE_PROFILE_CONTRACT[stage_index]
    current_box = current_stage.BoundingBox()
    expected_zmin, expected_zmax = A09_LIFT_STAGE_Z_HARDPOINTS_MM[stage_index]
    if (
        abs(float(current_box.zmin) - expected_zmin)
        > A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
        or abs(float(current_box.zmax) - expected_zmax)
        > A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
    ):
        raise ValueError(
            f"A09 stage {stage_index} upstream Z hardpoints changed: "
            f"{current_box.zmin:.9f}..{current_box.zmax:.9f} mm"
        )

    center = (
        (current_box.xmin + current_box.xmax) / 2.0,
        (current_box.ymin + current_box.ymax) / 2.0,
        (current_box.zmin + current_box.zmax) / 2.0,
    )
    outer_xy = tuple(float(value) for value in profile["outer_xy_mm"])
    inner_xy = tuple(float(value) for value in profile["inner_xy_mm"])
    outer = rounded_rect_prism(
        outer_xy,
        current_box.zlen,
        center,
        float(profile["outer_plan_radius_mm"]),
    )
    inner = rounded_rect_prism(
        inner_xy,
        current_box.zlen + 4.0,
        center,
        float(profile["inner_plan_radius_mm"]),
    )
    candidate = _valid_single(
        outer.cut(inner).clean(),
        f"A09 instrument-spine stage {stage_index}",
    )
    candidate_box = candidate.BoundingBox()
    expected_bounds = (
        outer_xy[0],
        outer_xy[1],
        current_box.zmin,
        current_box.zmax,
    )
    actual_bounds = (
        candidate_box.xlen,
        candidate_box.ylen,
        candidate_box.zmin,
        candidate_box.zmax,
    )
    if any(
        abs(float(actual) - float(expected))
        > A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
        for actual, expected in zip(actual_bounds, expected_bounds)
    ):
        raise ValueError(
            f"A09 stage {stage_index} failed frozen profile/Z bounds: "
            f"actual={actual_bounds!r}, expected={expected_bounds!r}"
        )
    return candidate


def _a09_instrument_spine_lift_columns(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Legacy lift-column appearance pass retained for trace archaeology.

    Both deployed table roots are now supplied as final physical mechanisms:
    Café by ``v8_cafe_table_root_motion`` and Focus by the bilateral A05-internal
    flat guides from ``skin_upper``.  Rebodying either one against the former
    X=-430/-405 exposed-column contract would recreate the rejected prototype.
    """

    if state in {"cafe", "focus"}:
        return
    if state not in {"cafe", "focus"}:
        return
    axes = (
        (("right", -430.0, 300.0),)
        if state == "cafe"
        else (("left", -405.0, -300.0), ("right", -405.0, 300.0))
    )
    for side_name, axis_x, axis_y in axes:
        candidate_stages: list[SkinPart] = []
        for stage_index in (1, 2, 3):
            name = _a09_lift_stage_name(state, side_name, stage_index)
            matches = [
                (index, part)
                for index, part in enumerate(parts)
                if part.name == name
            ]
            if len(matches) != 1:
                raise KeyError(
                    f"{state} requires one {name} for A09 instrument-spine "
                    f"closure; found {len(matches)}"
                )
            part_index, current_part = matches[0]
            current_box = current_part.shape.BoundingBox()
            current_axis = (
                (current_box.xmin + current_box.xmax) / 2.0,
                (current_box.ymin + current_box.ymax) / 2.0,
            )
            if any(
                abs(actual - expected) > A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
                for actual, expected in zip(current_axis, (axis_x, axis_y))
            ):
                raise ValueError(
                    f"{state} {side_name} A09 stage {stage_index} axis moved: "
                    f"{current_axis!r}"
                )

            profile = A09_LIFT_STAGE_PROFILE_CONTRACT[stage_index]
            shape = _a09_instrument_spine_stage(
                current_part.shape,
                stage_index,
            )
            metadata = dict(current_part.metadata)
            metadata.update(
                {
                    "a09_lift_column_contract": (
                        "directional_squircle_instrument_spine_v1"
                    ),
                    "stage_index": stage_index,
                    "outer_xy_mm": profile["outer_xy_mm"],
                    "inner_xy_mm": profile["inner_xy_mm"],
                    "outer_plan_radius_mm": profile[
                        "outer_plan_radius_mm"
                    ],
                    "inner_plan_radius_mm": profile[
                        "inner_plan_radius_mm"
                    ],
                    "minimum_wall_mm": profile["minimum_wall_mm"],
                    "adjacent_radial_clearance_mm": (
                        A09_LIFT_ADJACENT_RADIAL_CLEARANCE_MM
                    ),
                    "minimum_internal_channel_mm": (
                        A09_LIFT_STAGE3_MINIMUM_INTERNAL_CHANNEL_MM
                        if stage_index == 3
                        else min(
                            float(value)
                            for value in profile["inner_xy_mm"]
                        )
                    ),
                    "controlled_axis_xy_mm": (axis_x, axis_y),
                    "released_z_bounds_mm": (
                        A09_LIFT_STAGE_Z_HARDPOINTS_MM[stage_index]
                    ),
                    "plan_yaw_deg": 0.0,
                    "straight_axial_walls": True,
                    "xy_only_squircle_rounding": True,
                    "released_axis_and_z_bounds_preserved": True,
                    "independent_physical_stage": True,
                    "production_certification_claimed": False,
                }
            )
            candidate = replace(
                current_part,
                shape=shape,
                material=(
                    "body-colour straight-sided PC-ABS/aluminium directional "
                    "squircle instrument-spine sleeve"
                ),
                intent=(
                    "One independent straight-walled XY-squircle lift stage "
                    "removes the prototype pill-box stack while preserving "
                    "the released table axis, Z hardpoints and dry mechanism "
                    "channel."
                ),
                metadata=metadata,
            )
            parts[part_index] = candidate
            candidate_stages.append(candidate)

        for first, second in zip(candidate_stages, candidate_stages[1:]):
            common_volume = float(first.shape.intersect(second.shape).Volume())
            clearance = float(first.shape.distance(second.shape))
            if (
                common_volume > 1.0e-5
                or abs(
                    clearance - A09_LIFT_ADJACENT_RADIAL_CLEARANCE_MM
                )
                > A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
            ):
                raise ValueError(
                    f"{state} {side_name} A09 adjacent stages violate the "
                    f"3.0 mm dry contract: common={common_volume:.9f} mm^3, "
                    f"distance={clearance:.9f} mm"
                )

        # The deployable partition ran against the previous fully rounded
        # stage.  Re-cut the final table underbelly with the new straight-sided
        # stage 3 so the formal pass order cannot leave a hidden intersection.
        underbelly_name = f"A09_table_underbelly_shell_{side_name}"
        underbelly_matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name == underbelly_name
        ]
        if len(underbelly_matches) != 1:
            raise KeyError(
                f"{state} requires one {underbelly_name} for the A09 stage-3 "
                f"pocket; found {len(underbelly_matches)}"
            )
        underbelly_index, underbelly = underbelly_matches[0]
        recut = _valid_single(
            underbelly.shape.cut(candidate_stages[2].shape).clean(),
            f"{state} {side_name} A09 stage-3 underbelly pocket",
        )
        parts[underbelly_index] = replace(
            underbelly,
            shape=recut,
            metadata={
                **underbelly.metadata,
                "a09_instrument_spine_stage3_pocket_recut": True,
                "stage3_profile_contract": (
                    "directional_squircle_instrument_spine_v1"
                ),
            },
        )


def _a09_focus_a05_lift_clearance_corridors(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Re-cut the fixed Focus bay edge to the frozen moving-stage dry gap."""

    if state != "focus":
        return
    # The final mechanism uses a small inner-sidewall tongue port and never a
    # lid aperture.  Prove the resolved B-Reps as delivered; do not hide a
    # collision by cutting the fixed shell or its touch lid in this late pass.
    for side_name in ("left", "right"):
        mechanism_names = (
            f"A09_focus_internal_root_box_{side_name}",
            f"A09_focus_internal_nested_guide_stage_1_{side_name}",
            f"A09_focus_internal_nested_guide_stage_2_{side_name}",
            f"A09_focus_internal_nested_guide_stage_3_{side_name}",
            f"A09_focus_table_hidden_root_tongue_{side_name}",
        )
        mechanisms: list[SkinPart] = []
        for name in mechanism_names:
            matches = [part for part in parts if part.name == name]
            if len(matches) != 1:
                raise KeyError(
                    f"focus requires one {name} for closed-lid packaging; "
                    f"found {len(matches)}"
                )
            mechanisms.append(matches[0])
        hosts: list[SkinPart] = []
        for name in (
            f"A05_armrest_table_bay_shell_{side_name}",
            f"A05_armrest_touch_lid_{side_name}",
        ):
            matches = [part for part in parts if part.name == name]
            if len(matches) != 1:
                raise KeyError(
                    f"focus requires one {name} for closed-lid packaging; "
                    f"found {len(matches)}"
                )
            hosts.append(matches[0])
        common = [
            float(mechanism.shape.intersect(host.shape).Volume())
            for mechanism in mechanisms
            for host in hosts
        ]
        if any(value > 1.0e-5 for value in common):
            raise ValueError(
                f"focus {side_name} concealed A09/A05 packaging collision: "
                f"{common!r}"
            )
        stage_3 = mechanisms[3]
        lid = hosts[1]
        lid_gap = float(stage_3.shape.distance(lid.shape))
        if lid_gap < 1.0 - A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM:
            raise ValueError(
                f"focus {side_name} closed-lid stage-3 gap fell below 1 mm: "
                f"{lid_gap:.9f} mm"
            )
    return

    for side_name in ("left", "right"):
        stage_names = (
            f"A09_table_lift_boot_{side_name}",
            f"A09_table_lift_moving_stage_2_{side_name}",
            f"A09_table_lift_moving_stage_3_{side_name}",
        )
        stages: list[SkinPart] = []
        for name in stage_names:
            matches = [part for part in parts if part.name == name]
            if len(matches) != 1:
                raise KeyError(
                    f"focus requires one {name} for the A09/A05 dry corridor; "
                    f"found {len(matches)}"
                )
            stages.append(matches[0])

        shell_name = f"A05_armrest_table_bay_shell_{side_name}"
        shell_matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name == shell_name
        ]
        if len(shell_matches) != 1:
            raise KeyError(
                f"focus requires one {shell_name} for the A09/A05 dry "
                f"corridor; found {len(shell_matches)}"
            )
        shell_index, shell = shell_matches[0]
        relieved_shape = shell.shape
        recut_stage_names: list[str] = []
        for stage_index, stage in enumerate(stages, start=1):
            if (
                float(relieved_shape.distance(stage.shape))
                >= A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM
                - A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
            ):
                continue
            profile = A09_LIFT_STAGE_PROFILE_CONTRACT[stage_index]
            outer_xy = tuple(
                float(value) for value in profile["outer_xy_mm"]
            )
            stage_box = stage.shape.BoundingBox()
            relief = rounded_rect_prism(
                (
                    outer_xy[0]
                    + 2.0 * A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM,
                    outer_xy[1]
                    + 2.0 * A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM,
                ),
                stage_box.zlen
                + 2.0 * A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM,
                (
                    (stage_box.xmin + stage_box.xmax) / 2.0,
                    (stage_box.ymin + stage_box.ymax) / 2.0,
                    (stage_box.zmin + stage_box.zmax) / 2.0,
                ),
                float(profile["outer_plan_radius_mm"])
                + A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM,
            )
            relieved_shape = _valid_single(
                relieved_shape.cut(relief).clean(),
                f"focus {side_name} A05 fixed bay A09 dry corridor",
            )
            recut_stage_names.append(stage.name)

        lid_name = f"A05_armrest_touch_lid_{side_name}"
        lid_matches = [part for part in parts if part.name == lid_name]
        if len(lid_matches) != 1:
            raise KeyError(
                f"focus requires one {lid_name} for the A09/A05 dry "
                f"corridor; found {len(lid_matches)}"
            )
        a05_shapes = (relieved_shape, lid_matches[0].shape)
        common_volumes = [
            float(stage.shape.intersect(a05_shape).Volume())
            for stage in stages
            for a05_shape in a05_shapes
        ]
        clearances = [
            float(stage.shape.distance(a05_shape))
            for stage in stages
            for a05_shape in a05_shapes
        ]
        minimum_clearance = min(clearances)
        if (
            any(value > 1.0e-5 for value in common_volumes)
            or minimum_clearance
            < A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM
            - A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
        ):
            raise ValueError(
                f"focus {side_name} A09/A05 corridor violates the frozen "
                f"{A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM:.1f} mm dry gap: "
                f"minimum={minimum_clearance:.9f} mm, "
                f"common={common_volumes!r}"
            )
        metadata = dict(shell.metadata)
        metadata.update(
            {
                "a09_focus_lift_dry_corridor_recut": bool(
                    recut_stage_names
                ),
                "a09_focus_lift_dry_corridor_stage_names": tuple(
                    recut_stage_names
                ),
                "a09_focus_lift_minimum_dry_clearance_contract_mm": (
                    A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM
                ),
                "a09_focus_lift_minimum_static_brep_clearance_mm": (
                    minimum_clearance
                ),
                "fixed_continuous_armrest": True,
                "side_opening_enabled": False,
            }
        )
        parts[shell_index] = replace(
            shell,
            shape=relieved_shape,
            metadata=metadata,
        )


def _table_lift_base_sockets(state: str, parts: list[SkinPart]) -> None:
    """Legacy exposed-column socket pass, disabled by the final mechanisms."""

    if state in {"cafe", "focus"}:
        # Café owns an exact internal fixed-root housing; Focus owns a bilateral
        # closed-bottom flat root box.  Adding the former 82 x 82 mm socket here
        # would duplicate those load paths and push them through A05.
        return
    if state not in {"cafe", "focus"}:
        return
    axes = (
        (("right", 1, -430.0),)
        if state == "cafe"
        else (("left", -1, -405.0), ("right", 1, -405.0))
    )
    for side_name, side, axis_x in axes:
        centre = (axis_x, side * 300.0, 489.0)
        outer = rounded_box((82.0, 82.0, 10.0), centre, 16.0)
        inner = rounded_box(
            (76.0, 76.0, 10.0),
            (axis_x, side * 300.0, 494.0),
            13.0,
        )
        # The fixed A05 armrest owns the rear-outboard quadrant of this root.
        # Notch the moving-service socket back from that ownership boundary
        # instead of stacking a second shell through it.  The orthogonal
        # 2.0/2.5 mm split is deliberately larger than a cosmetic reveal and
        # leaves the fixed armrest as the fourth perimeter wall.
        fixed_armrest_notch = (
            cq.Workplane("XY")
            .box(40.0, 44.0, 14.0)
            .translate((-362.0, side * 329.5, 489.0))
            .val()
        )
        socket = _valid_single(
            outer.cut(inner).cut(fixed_armrest_notch),
            f"{state} {side_name} table lift base socket",
        )
        stage_1_name = _a09_lift_stage_name(state, side_name, 1)
        stage_1_matches = [part for part in parts if part.name == stage_1_name]
        if len(stage_1_matches) != 1:
            raise KeyError(
                f"{state} requires one {stage_1_name} before base-socket "
                f"closure; found {len(stage_1_matches)}"
            )
        stage_1 = stage_1_matches[0]
        stage_common = float(socket.intersect(stage_1.shape).Volume())
        stage_clearance = float(socket.distance(stage_1.shape))
        if (
            stage_common > 1.0e-5
            or stage_clearance
            < A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM
            - A09_LIFT_STAGE_GEOMETRY_TOLERANCE_MM
        ):
            raise ValueError(
                f"{state} {side_name} A09 base socket violates the frozen "
                f"dry interface: common={stage_common:.9f} mm^3, "
                f"distance={stage_clearance:.9f} mm"
            )
        parts.append(
            _new_part(
                f"A09_{state}_table_lift_base_socket_{side_name}",
                socket,
                LUNAR_STONE,
                "impact-modified PC-ABS closed-bottom table-lift service socket",
                "A09",
                state,
                "A shallow closed-bottom socket receives the first moving sleeve with a real perimeter clearance and prevents the nested stage cavity reading as an open line-frame from below.",
                physical_occurrence_id=(
                    f"E6-A09-{state.upper()}-TABLE-LIFT-BASE-SOCKET-{side_name.upper()}"
                ),
                fixed_to="table_lift_structural_root",
                open_top=True,
                closed_bottom=True,
                nominal_side_wall_mm=3.0,
                nominal_bottom_wall_mm=5.0,
                radial_clearance_to_stage_1_mm=2.0,
                socket_lip_vertical_setback_to_stage_1_mm=1.1,
                central_bottom_vertical_clearance_to_stage_1_mm=6.1,
                minimum_static_brep_clearance_to_stage_1_mm=round(
                    stage_clearance,
                    9,
                ),
                minimum_static_brep_clearance_contract_mm=(
                    A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM
                ),
                dry_gap_to_fixed_armrest_mm=2.0,
                fixed_armrest_completes_rear_outboard_perimeter=True,
                normal_bottom_sightline_stage_aperture_closed=True,
                production_certification_claimed=False,
            )
        )


def _connected_sleeve(
    outer_xy: tuple[float, float],
    inner_xy: tuple[float, float],
    height: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    radial_wall = min(
        (outer_xy[0] - inner_xy[0]) / 2.0,
        (outer_xy[1] - inner_xy[1]) / 2.0,
    )
    if radial_wall <= 0.0:
        raise ValueError("A07 sleeve requires a positive radial wall")
    outer = rounded_rect_prism(outer_xy, height, center, radius)
    inner = rounded_rect_prism(
        inner_xy,
        height + 4.0,
        center,
        max(1.0, radius - radial_wall),
    )
    return _valid_single(outer.cut(inner), "A07 connected sleeve")


def _a07_x_cylinder(
    radius_mm: float,
    x_range_mm: tuple[float, float],
    y_mm: float,
    z_mm: float,
) -> cq.Shape:
    """Build an analytic X-axis cylinder from an explicit minimum/maximum X."""

    xmin, xmax = x_range_mm
    if radius_mm <= 0.0 or xmax <= xmin:
        raise ValueError("A07 lock cylinder requires positive radius and length")
    return cq.Solid.makeCylinder(
        radius_mm,
        xmax - xmin,
        cq.Vector(xmin, y_mm, z_mm),
        cq.Vector(1.0, 0.0, 0.0),
    )


A07_AXIS_X_MM = 310.0
A07_FOCUS_STROKE_MM = 420.0
A07_CHANNEL_CLEARANCE_MM = 5.0
A07_CHANNEL_WALL_MM = 3.5
A07_CHANNEL_ROOT_Z_MM = 567.5
A07_LOW_BEAM_Z_MM = 1040.0
A07_LOW_BEAM_TOP_Z_MM = 1072.0
A07_CHANNEL_THROAT_TOP_Z_MM = 1003.0
A07_CHANNEL_SIDEWALL_TOP_Z_MM = 1003.0
A07_CONTROLLED_LOW_ENVELOPES = (
    (
        "controlled_fixed_cosmetic_shroud",
        (82.0, 152.0, 300.0),
        (A07_AXIS_X_MM, 0.0, 858.0),
    ),
    (
        "controlled_low_moving_inner",
        (54.4, 120.8, 570.0),
        (A07_AXIS_X_MM, 0.0, 723.0),
    ),
    (
        "controlled_low_sensor_beam",
        (94.0, 370.0, 64.0),
        (303.0, 24.0, A07_LOW_BEAM_Z_MM),
    ),
    (
        "controlled_mast_actuator",
        (40.0, 40.0, 410.0),
        (A07_AXIS_X_MM, -45.0, 793.0),
    ),
)


def _fuse_single_shapes(
    shapes: Iterable[cq.Shape],
    label: str,
) -> cq.Shape:
    values = list(shapes)
    if not values:
        raise ValueError(f"{label} has no solids")
    result = values[0]
    for value in values[1:]:
        result = result.fuse(value).clean()
    return _valid_single(result, label)


def _a07_rounded_offset_guard(
    size_xyz: tuple[float, float, float],
    center_xyz: tuple[float, float, float],
    offset_mm: float,
) -> cq.Shape:
    """Euclidean rounded offset of one controlled A07 low-state AABB."""

    expanded = tuple(value + 2.0 * offset_mm for value in size_xyz)
    low_axes = (
        cq.Workplane("XY")
        .box(*expanded)
        .edges()
        .fillet(offset_mm)
        .val()
        .translate(center_xyz)
    )
    # A06 is stored in its canonical, unraked frame.  The occupied A07 stays
    # vertical, so pre-rotate its receiving channel by -6 degrees; applying
    # the normal A06 +6 degree pose restores the exact controlled low axes.
    return _rotate_y(low_axes, BACK_HINGE, -BACK_RAKE_DEG)


def _a06_observation_roof_keep() -> cq.Shape:
    """Quiet 1003 mm low-axis shoulder below the conserved sensor terminal.

    A former front-high transition was collision-safe but produced a sharp
    side-view horn beside the Focus spine.  The production shoulder is one
    calm horizontal datum, exactly five millimetres below the terminal bottom.
    This is not an egress cap: the terminal is already above it in every low
    state and only the moving spine crosses the compliant central throat.
    """

    return (
        cq.Workplane("XZ")
        .moveTo(-1000.0, -1000.0)
        .lineTo(2000.0, -1000.0)
        .lineTo(2000.0, A07_CHANNEL_THROAT_TOP_Z_MM)
        .lineTo(-1000.0, A07_CHANNEL_THROAT_TOP_Z_MM)
        .close()
        .extrude(1000.0, both=True)
        .val()
    )


def _a06_y_cylinder(
    radius_mm: float,
    y_range_mm: tuple[float, float],
    *,
    x_mm: float = BACK_HINGE[0],
    z_mm: float = BACK_HINGE[2],
) -> cq.Shape:
    """Return an analytic Y-axis cylinder from ordered world coordinates."""

    ymin, ymax = y_range_mm
    if radius_mm <= 0.0 or ymax <= ymin:
        raise ValueError("A06 Y-cylinder requires positive radius and length")
    return cq.Solid.makeCylinder(
        radius_mm,
        ymax - ymin,
        cq.Vector(x_mm, ymin, z_mm),
        cq.Vector(0.0, 1.0, 0.0),
    )


def _a06_centred_radial_bore(
    radius_mm: float,
    y_mm: float,
    master_axis_angle_deg: float,
    length_mm: float = 56.0,
) -> cq.Shape:
    """One transverse lock bore through a shaft disc in the master frame.

    ``master_axis_angle_deg`` is measured from +Z by a positive rotation about
    +Y.  The two endpoint bores differ by the exact 95 degree fold travel and
    become vertical only at their respective upright or Follow endpoint.
    """

    angle = radians(master_axis_angle_deg)
    axis = cq.Vector(sin(angle), 0.0, cos(angle))
    half = 0.5 * length_mm
    origin = cq.Vector(
        BACK_HINGE[0] - axis.x * half,
        y_mm,
        BACK_HINGE[2] - axis.z * half,
    )
    return cq.Solid.makeCylinder(radius_mm, length_mm, origin, axis)


@lru_cache(maxsize=1)
def _production_backrest_hinge_shaft_master() -> cq.Shape:
    """Moving shaft, carrier drive hubs and two redundant detent discs."""

    shaft = _a06_y_cylinder(
        A06_HINGE_SHAFT_RADIUS_MM,
        (-A06_HINGE_SHAFT_Y_LIMIT_MM, A06_HINGE_SHAFT_Y_LIMIT_MM),
    )
    moving_members: list[cq.Shape] = [shaft]
    for side in (-1, 1):
        hub_y = side * A06_HINGE_DRIVE_HUB_Y_MM
        moving_members.append(
            _a06_y_cylinder(
                A06_HINGE_DRIVE_HUB_RADIUS_MM,
                (
                    hub_y - A06_HINGE_DRIVE_HUB_AXIAL_MM / 2.0,
                    hub_y + A06_HINGE_DRIVE_HUB_AXIAL_MM / 2.0,
                ),
            )
        )
        disc_y = side * A06_LOCK_STATION_Y_MM
        moving_members.append(
            _a06_y_cylinder(
                A06_LOCK_DISC_RADIUS_MM,
                (
                    disc_y - A06_LOCK_DISC_AXIAL_MM / 2.0,
                    disc_y + A06_LOCK_DISC_AXIAL_MM / 2.0,
                ),
            )
        )

    assembly = _fuse_single_shapes(
        moving_members,
        "A06 hinge shaft, drive hubs and redundant lock discs",
    )
    # The master is posed +6 degrees in occupied states and -89 degrees in
    # Follow.  Therefore -6 and +89 degree master bores become vertical at the
    # two physical endpoints while remaining deliberately misaligned between.
    for side in (-1, 1):
        y_mm = side * A06_LOCK_STATION_Y_MM
        for angle_deg in (-BACK_RAKE_DEG, -(BACK_RAKE_DEG + BACK_FOLD_DEG)):
            assembly = assembly.cut(
                _a06_centred_radial_bore(
                    A06_LOCK_BORE_RADIUS_MM,
                    y_mm,
                    angle_deg,
                )
            )
    return _valid_single(
        assembly.clean(),
        "A06 machined hinge shaft assembly with two endpoint detents per side",
    )


@lru_cache(maxsize=2)
def _production_backrest_hinge_bearing_master(side: int) -> cq.Shape:
    """Fixed bearing carrier, through-foot and captured lock guide."""

    if side not in {-1, 1}:
        raise ValueError(f"A06 bearing side must be -1 or 1, got {side}")
    bearing_y = side * A06_HINGE_BEARING_Y_MM
    half_axial = A06_HINGE_BEARING_AXIAL_MM / 2.0
    bearing_range = (
        bearing_y - half_axial,
        bearing_y + half_axial,
    )
    if side < 0:
        bearing_range = tuple(sorted(bearing_range))  # type: ignore[assignment]

    ring = _a06_y_cylinder(
        A06_HINGE_BEARING_OUTER_RADIUS_MM,
        bearing_range,
    )
    # This carrier is fully inside the sealed A05 rear-root cavity.  Its foot
    # uses z=468 only as a trim datum and requires through-fastening to a hidden
    # metal chassis outrigger; neither A04 nor A05 PC-ABS is declared a load
    # path.  The stem is re-bored after fusion so it can never fill the shaft
    # running bore.
    foot = rounded_box(
        (46.0, 31.0, 8.0),
        (165.0, side * 334.5, 472.5),
        3.0,
    )
    stem = rounded_box(
        (34.0, 12.0, 36.0),
        (160.0, side * 321.0, 492.5),
        4.0,
    )
    post = rounded_box(
        (12.0, 8.0, 28.0),
        (160.0, side * 321.0, 543.0),
        3.0,
    )
    bridge = rounded_box(
        (12.0, 18.0, 8.0),
        (160.0, side * 327.0, 556.0),
        3.0,
    )
    collar_outer = cq.Solid.makeCylinder(
        9.0,
        28.0,
        cq.Vector(BACK_HINGE[0], side * A06_LOCK_STATION_Y_MM, 544.0),
        cq.Vector(0.0, 0.0, 1.0),
    )
    carrier = _fuse_single_shapes(
        (ring, foot, stem, post, bridge, collar_outer),
        f"A06 fixed bearing and lock carrier side {side}",
    )

    shaft_bore = _a06_y_cylinder(
        A06_HINGE_RUNNING_RADIUS_MM,
        (304.0, 351.0) if side > 0 else (-351.0, -304.0),
    )
    pin_bore = cq.Solid.makeCylinder(
        A06_LOCK_BORE_RADIUS_MM,
        32.0,
        cq.Vector(BACK_HINGE[0], side * A06_LOCK_STATION_Y_MM, 542.0),
        cq.Vector(0.0, 0.0, 1.0),
    )
    return _valid_single(
        carrier.cut(shaft_bore).cut(pin_bore).clean(),
        f"A06 re-bored fixed bearing and captured lock guide side {side}",
    )


def _production_backrest_positive_lock_pin(side: int) -> cq.Shape:
    if side not in {-1, 1}:
        raise ValueError(f"A06 lock side must be -1 or 1, got {side}")
    z0, z1 = A06_LOCK_PIN_ENGAGED_Z_MM
    return cq.Solid.makeCylinder(
        A06_LOCK_PIN_RADIUS_MM,
        z1 - z0,
        cq.Vector(BACK_HINGE[0], side * A06_LOCK_STATION_Y_MM, z0),
        cq.Vector(0.0, 0.0, 1.0),
    )


def _a06_hinge_weather_clearance_master() -> cq.Shape:
    """Shaft running bore plus two carrier-hub pockets in the A06 shell."""

    cutters: list[cq.Shape] = [
        _a06_y_cylinder(
            A06_HINGE_RUNNING_RADIUS_MM,
            (-305.0, 305.0),
        )
    ]
    for side in (-1, 1):
        hub_y = side * A06_HINGE_DRIVE_HUB_Y_MM
        cutters.append(
            _a06_y_cylinder(
                A06_HINGE_DRIVE_HUB_POCKET_RADIUS_MM,
                (
                    hub_y - (A06_HINGE_DRIVE_HUB_AXIAL_MM + 1.0) / 2.0,
                    hub_y + (A06_HINGE_DRIVE_HUB_AXIAL_MM + 1.0) / 2.0,
                ),
            )
        )
    return _fuse_single_shapes(cutters, "A06 shaft and drive-hub weather pockets")


@lru_cache(maxsize=1)
def _production_backrest_channel_master() -> cq.Shape:
    """One continuous A06 monocoque around the conserved low A07 spine."""

    # The earlier base + retained wall + dorsal shell composition was
    # collision-safe but visibly read as a rectangular patch applied to the
    # back of a thinner backrest.  This single smooth low-axis loft carries the
    # same front contact surface and the rear observation volume in one B-Rep.
    outer_low = _rounded_loft_z(
        (
            ((183.5, 606.0), (250.75, 0.0), 515.0, 28.0),
            ((189.0, 580.0), (252.5, 0.0), 567.5, 32.0),
            ((199.0, 520.0), (258.5, 0.0), 700.0, 36.0),
            ((204.0, 455.0), (263.0, 0.0), 800.0, 40.0),
            ((206.0, 380.0), (266.0, 0.0), 950.0, 40.0),
            ((198.0, 344.0), (267.0, 0.0), 1015.0, 40.0),
            ((184.0, 337.0), (268.0, 0.0), 1068.0, 38.0),
        )
    )
    outer_low = _valid_single(
        outer_low.intersect(_a06_observation_roof_keep()).clean(),
        "shared A06 continuous outer monocoque",
    )
    # The Class-A surface must also describe a mouldable product, not a
    # render-only solid block.  A matching six-section void leaves four-
    # millimetre perimeter walls, a four-millimetre lower closure and an
    # eight-millimetre roof below the A07 terminal.  The dedicated A07 channel
    # is cut afterwards, so its controlled five-millimetre clearances remain
    # authoritative wherever the general hollow volume approaches the spine.
    manufacturing_void_low = _rounded_loft_z(
        (
            ((175.5, 598.0), (250.75, 0.0), 519.0, 24.0),
            ((181.0, 572.0), (252.5, 0.0), 567.5, 28.0),
            ((191.0, 512.0), (258.5, 0.0), 700.0, 32.0),
            ((196.0, 447.0), (263.0, 0.0), 800.0, 36.0),
            ((198.0, 372.0), (266.0, 0.0), 950.0, 36.0),
            ((194.0, 345.0), (267.0, 0.0), 995.0, 36.0),
        )
    )
    comfort_cavity_low = _crowned_trapezoid_skin(
        584.0,
        306.0,
        506.0,
        80.0,
        x_center=207.0,
        z0=525.0,
        corner_radius=15.0,
        end_inset=4.0,
    )
    contact_opening_low = _crowned_trapezoid_skin(
        528.0,
        256.0,
        433.0,
        24.0,
        x_center=155.0,
        z0=552.0,
        corner_radius=18.0,
        end_inset=3.0,
    )

    # The terminal is already 5 mm above the rear shoulder and therefore never
    # crosses A06.  Only the fixed/moving spine and its internal actuator need
    # a through-channel.  Building that clearance directly into the single
    # loft removes both the old open bathtub and the external dorsal patch.
    channel_envelopes = tuple(
        envelope
        for envelope in A07_CONTROLLED_LOW_ENVELOPES
        if envelope[0] != "controlled_low_sensor_beam"
    )
    channel_low = _rotate_y(
        _fuse_single_shapes(
            tuple(
                _a07_rounded_offset_guard(
                    size_xyz,
                    center_xyz,
                    A07_CHANNEL_CLEARANCE_MM,
                )
                for _, size_xyz, center_xyz in channel_envelopes
            ),
            "A06 one-stage A07 low-axis clearance union",
        ),
        BACK_HINGE,
        BACK_RAKE_DEG,
    )
    low_master = (
        outer_low.cut(manufacturing_void_low)
        .cut(comfort_cavity_low)
        .cut(contact_opening_low)
        .cut(channel_low)
        .cut(_a06_hinge_weather_clearance_master())
        .clean()
    )
    # Close the original backrest top as one structural weather shoulder.
    # When A06 folds this becomes the leading edge of the Follow upper field;
    # leaving the manufacturing void open here exposed a large U-shaped cavity
    # after the correctly stowed A07 terminal was removed from presentation.
    # The only remaining aperture is the controlled fixed-sleeve throat.
    roof_outer = rounded_box(
        (198.0, 360.0, 4.0),
        (267.0, 0.0, 1001.0),
        34.0,
    )
    fixed_sleeve_throat = rounded_box(
        (96.0, 166.0, 12.0),
        (A07_AXIS_X_MM, 0.0, 1001.0),
        22.0,
    )
    roof_ring = _valid_single(
        roof_outer.cut(fixed_sleeve_throat).clean(),
        "A06 integral observation-throat roof ring",
    )
    low_master = _valid_single(
        low_master.fuse(roof_ring).clean(),
        "shared A06 closed monocoque, hinge bore and A07 precision throat",
    )
    return _rotate_y(
        low_master,
        BACK_HINGE,
        -BACK_RAKE_DEG,
    )


@lru_cache(maxsize=1)
def _production_backrest_contact_panel_master() -> cq.Shape:
    """Shortened conserved contact island below the quiet A06 roof datum."""

    return _valid_single(
        _crowned_trapezoid_skin(
            516.0,
            248.0,
            425.0,
            14.0,
            x_center=158.0,
            z0=556.0,
            corner_radius=16.0,
            end_inset=4.0,
        ),
        "shared A06 production contact panel",
    )


def _shared_backrest_master(state: str, parts: list[SkinPart]) -> None:
    """Install one channel-integrated A06 BRep and apply only its state pose."""

    candidates = [
        part
        for part in parts
        if part.name in {
            "A06_backrest_weather_shell",
            "A06_follow_closed_field_shell",
        }
    ]
    if not candidates:
        raise KeyError(f"{state} has no A06 backrest identity source")
    identity = candidates[0]
    contact_candidates = [
        part for part in parts if part.name == "A06_backrest_contact_panel"
    ]
    if len(contact_candidates) != 1:
        raise KeyError(
            f"{state} requires one A06 contact-panel identity; "
            f"found {len(contact_candidates)}"
        )
    contact_identity = contact_candidates[0]
    seat_matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == "A04_seat_cushion_contact_island"
    ]
    if len(seat_matches) != 1:
        raise KeyError(
            f"{state} requires one A04 seat-cushion identity; "
            f"found {len(seat_matches)}"
        )
    seat_index, seat = seat_matches[0]
    seat_metadata = dict(seat.metadata)
    seat_metadata.update(
        {
            "non_rigid_compliant_part": True,
            "follow_backrest_preload_interface": True,
            "follow_uncompressed_thickness_mm": (
                FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM
            ),
            "follow_maximum_nominal_preload_mm": (
                FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
            ),
            "fold_motion_requires_unoccupied_interlock": True,
            "supplier_compression_set_curve_required": True,
            "physical_preload_validation_required": True,
            "production_certification_claimed": False,
        }
    )
    parts[seat_index] = replace(seat, metadata=seat_metadata)

    master = _production_backrest_channel_master()
    master_volume = float(master.Volume())
    master_area = float(master.Area())
    master_faces = len(master.Faces())
    master_edges = len(master.Edges())
    posed = _rotate_y(master, BACK_HINGE, BACK_RAKE_DEG)
    pose = "upright"
    if state == "follow":
        posed = _rotate_y(posed, BACK_HINGE, BACK_FOLD_DEG)
        pose = "folded_weather_surface"

    contact_master = _production_backrest_contact_panel_master()
    contact_master_volume = float(contact_master.Volume())
    posed_contact = _rotate_y(
        contact_master,
        BACK_HINGE,
        BACK_RAKE_DEG,
    )
    if state == "follow":
        posed_contact = _rotate_y(
            posed_contact,
            BACK_HINGE,
            BACK_FOLD_DEG,
        )

    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A06_backrest_weather_shell")
        and not part.name.startswith("A06_follow_closed_field_shell")
        and part.name != "A06_follow_weather_continuity_skirt"
        and part.name != "A06_backrest_contact_panel"
    ]
    metadata = dict(identity.metadata)
    metadata.update(
        {
            "physical_occurrence_id": "E6-A06-BACKREST-WEATHER-SHELL",
            "pose": pose,
            "role": "backrest",
            "controlled_hinge_mm": BACK_HINGE,
            "upright_rake_deg": BACK_RAKE_DEG,
            "follow_fold_deg": BACK_FOLD_DEG,
            "physical_part_conserved": True,
            "master_brep_volume_mm3": master_volume,
            "master_brep_area_mm2": master_area,
            "master_brep_face_count": master_faces,
            "master_brep_edge_count": master_edges,
            "master_has_mast_cutout": True,
            "mast_channel_axis_x_mm": A07_AXIS_X_MM,
            "mast_channel_clearance_mm": A07_CHANNEL_CLEARANCE_MM,
            "mast_channel_nominal_wall_mm": A07_CHANNEL_WALL_MM,
            "mast_channel_root_z_mm": A07_CHANNEL_ROOT_Z_MM,
            "mast_channel_open_throat_top_z_mm": (
                A07_CHANNEL_THROAT_TOP_Z_MM
            ),
            "mast_channel_sidewall_top_z_mm": (
                A07_CHANNEL_SIDEWALL_TOP_Z_MM
            ),
            "mast_channel_has_top_cap": False,
            "mast_channel_top_cap_absence_reason": (
                "the finished terminal begins five millimetres above the rear "
                "shoulder in every low state; only the moving spine crosses the "
                "central compliant throat"
            ),
            "mast_channel_below_terminal_shoulder_z_mm": 1003.0,
            "low_terminal_vertical_dry_gap_mm": 5.0,
            "ride_cafe_height_margin_mm": 10.0,
            "follow_height_margin_mm": 3.192169,
            "one_continuous_outer_monocoque": True,
            "manufacturing_hollow_shell": True,
            "manufacturing_shell_nominal_wall_mm": 4.0,
            "manufacturing_lower_closure_mm": 4.0,
            "manufacturing_roof_minimum_mm": 8.0,
            "visible_dorsal_patch_removed": True,
            "shared_a06_a07_fold_hinge": True,
            "shared_a06_a07_fold_hinge_mm": BACK_HINGE,
            "a07_fold_sampling_count": 81,
            "a07_focus_stroke_sampling_count": 9,
            "same_backrest_not_extra_cover": True,
            "surface_has_no_additional_cover": True,
            "follow_only_waist_skirt_removed": True,
            "allowed_follow_a06_surface_occurrences": (
                "A06_backrest_weather_shell",
                "A06_backrest_contact_panel",
            ),
            "normal_sightline_internal_hardware_hidden": True,
            "follow_seat_cushion_preload_interface": True,
            "follow_seat_cushion_maximum_nominal_preload_mm": (
                FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
            ),
            "follow_seat_cushion_maximum_common_volume_mm3": (
                FOLLOW_SEAT_CUSHION_MAXIMUM_COMMON_VOLUME_MM3
            ),
            "fold_motion_requires_unoccupied_interlock": True,
            "physical_preload_validation_required": True,
            "production_certification_claimed": False,
        }
    )
    parts.append(
        replace(
            identity,
            name="A06_backrest_weather_shell",
            shape=posed,
            color=LUNAR_STONE,
            material="UV-stable mineral-matte PC-ABS channel-integrated hollow backrest monocoque",
            intent=(
                "The same trapezoidal backrest carries one smooth observation "
                "channel in every state and rotates directly into the sole "
                "Follow upper surface; no second cover appears."
            ),
            metadata=metadata,
        )
    )
    contact_metadata = dict(contact_identity.metadata)
    contact_metadata.update(
        {
            "physical_occurrence_id": "E6-A06-BACKREST-CONTACT-PANEL",
            "pose": pose,
            "physical_part_conserved": True,
            "same_brep_all_states": True,
            "moves_with": "backrest_hinge",
            "master_brep_volume_mm3": contact_master_volume,
            "production_contact_height_mm": 425.0,
            "top_frame_to_roof_nominal_mm": 23.6,
            "contact_opening_perimeter_dry_gap_mm": 3.9,
            "surface_has_no_additional_cover": True,
            "production_certification_claimed": False,
        }
    )
    parts.append(
        replace(
            contact_identity,
            name="A06_backrest_contact_panel",
            shape=posed_contact,
            color=ESPRESSO,
            material="removable breathable 3D-knit production contact island",
            intent=(
                "The same shortened trapezoidal contact island leaves a calm "
                "structural frame below the flat observation shoulder and "
                "folds only with the conserved A06 backrest."
            ),
            metadata=contact_metadata,
        )
    )


@lru_cache(maxsize=2)
def _fixed_backrest_root_shoulder_master(side: int) -> cq.Shape:
    """One hollow fixed-body shoulder below, never attached to, moving A06.

    The previous A06-labelled side boxes existed only in Ride/Cafe/Focus and
    vanished in Follow.  These much quieter rear buttresses are A04 fixed-body
    parts.  Their complete upper surface stays at z=511 mm: four millimetres
    below the closest sampled point of the conserved A06 sweep.  Moving the
    volume aft also leaves the fixed recovery grip a real four-millimetre dry
    split, so no boolean service slivers are needed.
    """

    if side not in {-1, 1}:
        raise ValueError(f"A04 root shoulder side must be -1 or 1, got {side}")
    outer = _rounded_loft_z(
        (
            ((58.0, 190.0), (309.0, side * 207.0), 469.5, 22.0),
            ((60.0, 190.0), (310.0, side * 207.0), 492.0, 23.0),
            ((72.0, 178.0), (316.0, side * 206.5), 511.0, 24.0),
        )
    )
    inner = _rounded_loft_z(
        (
            ((50.0, 182.0), (309.0, side * 207.0), 473.5, 18.0),
            ((52.0, 182.0), (310.0, side * 207.0), 492.0, 19.0),
            ((64.0, 170.0), (316.0, side * 206.5), 507.0, 20.0),
        )
    )
    return _valid_single(
        outer.cut(inner).clean(),
        f"A04 fixed backrest-root shoulder side {side}",
    )


def _fixed_body_backrest_root_shoulders(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Replace state-specific A06 cheek fragments with two conserved A04 parts."""

    parts[:] = [
        part
        for part in parts
        if not part.name.startswith("A06_backrest_root_cheek_")
        and not part.name.startswith("A04_backrest_root_shoulder_")
    ]
    for side_name, side in (("left", -1), ("right", 1)):
        shoulder = _fixed_backrest_root_shoulder_master(side)
        parts.append(
            _new_part(
                f"A04_backrest_root_shoulder_{side_name}",
                shoulder,
                LUNAR_STONE,
                "four-millimetre mineral-matte PC-ABS fixed-body hollow shoulder",
                "A04",
                state,
                "A low tapered rear buttress closes the fixed body below the moving trapezoidal backrest without becoming part of its fold or appearing only in one state.",
                physical_occurrence_id=(
                    f"E6-A04-FIXED-BACKREST-ROOT-SHOULDER-{side_name.upper()}"
                ),
                fixed_to="A04_body",
                same_brep_all_states=True,
                state_specific_substitute=False,
                nominal_wall_mm=4.0,
                central_channel_minimum_width_mm=222.5,
                outboard_extent_maximum_abs_y_mm=302.8793,
                fixed_armrest_minimum_dry_gap_mm=7.1207,
                recovery_grip_minimum_dry_gap_mm=4.0,
                seat_ring_minimum_dry_gap_mm=35.2093,
                a06_fold_sweep_start_deg=6.0,
                a06_fold_sweep_end_deg=-89.0,
                a06_fold_sweep_increment_deg=2.5,
                a06_fold_sweep_minimum_clearance_mm=4.0,
                service_sliver_count=0,
                independent_valid_solid=True,
                production_certification_claimed=False,
            )
        )


def _a06_fixed_manual_release() -> cq.Shape:
    """Central no-power paddle and captured pivot for two hidden cables."""

    # Keep the no-power release in the single A10 service aperture, but place
    # it in the real 40 mm vertical corridor between the compute cartridges
    # (ending at Z=310) and the PDU (starting at Z=370).  The former Z=410
    # position physically penetrated the controlled PDU by 2,949.64 mm3.
    paddle = rounded_box((44.0, 24.0, 6.0), (282.0, 0.0, 350.0), 3.0)
    cross_shaft = _a06_y_cylinder(
        3.0,
        (-17.0, 17.0),
        x_mm=264.0,
        z_mm=354.0,
    )
    return _fuse_single_shapes(
        (paddle, cross_shaft),
        "A06 no-power dual-cable manual release",
    )


def _production_backrest_hinge_hardware(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Install one real A06 shaft/bearing/lock inventory in every state.

    The moving shaft and drive hubs receive the same A06 pose as the trapezoid.
    Bearings, guided lock pins, witnesses and manual release remain fixed to the
    A04/A05 body.  During a commanded fold both pins must retract 28 mm before
    the shaft can leave either endpoint detent.
    """

    hardware_names = {
        "A06_backrest_hinge_shaft",
        "A06_backrest_hinge_bearing_left",
        "A06_backrest_hinge_bearing_right",
        "A06_backrest_positive_lock_left",
        "A06_backrest_positive_lock_right",
        "A06_backrest_lock_witness_left",
        "A06_backrest_lock_witness_right",
        "A06_backrest_manual_release",
    }
    parts[:] = [part for part in parts if part.name not in hardware_names]

    # Seat each bearing through the inner A05 rear-root wall.  The cutter is
    # invariant across states and remains wholly inside the fixed root; it does
    # not create a side-opening seam or alter the top-lid extraction sequence.
    for side_name, side in (("left", -1), ("right", 1)):
        shell_name = f"A05_armrest_table_bay_shell_{side_name}"
        matches = [
            (index, part)
            for index, part in enumerate(parts)
            if part.name == shell_name
        ]
        if len(matches) != 1:
            raise KeyError(
                f"{state} A06 bearing seat requires one {shell_name}; "
                f"found {len(matches)}"
            )
        index, shell = matches[0]
        seat_range = (
            (304.0, 322.0) if side > 0 else (-322.0, -304.0)
        )
        bearing_seat = _a06_y_cylinder(
            A06_HINGE_BEARING_OUTER_RADIUS_MM + 0.6,
            seat_range,
        )
        bearing_stem_seat = rounded_box(
            # Clear the complete inboard carrier stem and its lower foot
            # transition with a real 1 mm nominal trim reserve.  The former
            # 38 x 18 x 44 pocket left two hidden 22.93 mm3 intersections at
            # the X-min/lower-root corner on both sides.
            (40.0, 28.0, 48.0),
            (160.0, side * 316.0, 491.0),
            4.0,
        )
        # The tapered rear root already contains this carrier void as part of
        # its manufacturing hollow.  It is retained as an explicit clearance
        # witness but must not be subtracted a second time: on the mirrored
        # left shell an empty-space Boolean produced invalid extra and negative
        # solids even though the cutter had zero common volume with the shell.
        bearing_carrier_cavity = rounded_box(
            (74.0, 44.0, 122.0),
            (170.0, side * 338.75, 520.0),
            8.0,
        )
        witness_pocket = rounded_box(
            (14.0, 12.0, 10.0),
            (180.0, side * 363.5, 490.0),
            2.0,
        )
        disc_y = side * A06_LOCK_STATION_Y_MM
        lock_disc_clearance = _a06_y_cylinder(
            A06_LOCK_DISC_RADIUS_MM + 0.7,
            (
                min(
                    disc_y - A06_LOCK_DISC_AXIAL_MM / 2.0 - 0.7,
                    disc_y + A06_LOCK_DISC_AXIAL_MM / 2.0 + 0.7,
                ),
                max(
                    disc_y - A06_LOCK_DISC_AXIAL_MM / 2.0 - 0.7,
                    disc_y + A06_LOCK_DISC_AXIAL_MM / 2.0 + 0.7,
                ),
            ),
        )
        cavity_overlap = shell.shape.intersect(bearing_carrier_cavity)
        cavity_common = (
            0.0 if cavity_overlap.isNull() else abs(float(cavity_overlap.Volume()))
        )
        if side < 0 and cavity_common > 1.0e-6:
            raise ValueError(
                f"{state} left A05 nominal carrier void unexpectedly contains "
                f"{cavity_common:.6f} mm3 of shell material"
            )
        # Fuse the two overlapping inboard tools, then execute one two-tool
        # difference with the independent outboard witness pocket.  This keeps
        # the shell as one valid solid without serial global clean operations.
        bearing_through_seat = bearing_seat.fuse(bearing_stem_seat)
        seated_shell_candidate = shell.shape.cut(
            bearing_through_seat,
            lock_disc_clearance,
            witness_pocket,
        )
        seated_shell = _valid_single(
            seated_shell_candidate,
            f"{state} {side_name} fixed A05 shell with A06 bearing and witness seats",
        )
        shell_metadata = dict(shell.metadata)
        shell_metadata.update(
            {
                "a06_fixed_bearing_seat_present": True,
                "a06_bearing_seat_diameter_mm": 31.2,
                "a06_bearing_running_bore_diameter_mm": 17.4,
                "a06_bearing_stem_seat_mm": (40.0, 28.0, 48.0),
                "a06_hidden_bearing_carrier_cavity_mm": (74.0, 44.0, 122.0),
                "a06_hidden_cavity_inside_nominal_root_void": True,
                "a06_hidden_cavity_boolean_recut": False,
                "a06_hidden_cavity_source_common_volume_mm3": cavity_common,
                "a06_lock_disc_clearance_diameter_mm": (
                    2.0 * (A06_LOCK_DISC_RADIUS_MM + 0.7)
                ),
                "a06_lock_disc_axial_clearance_each_side_mm": 0.7,
                "a06_lock_witness_recess_present": True,
                "side_opening_enabled": False,
                "production_certification_claimed": False,
            }
        )
        parts[index] = replace(shell, shape=seated_shell, metadata=shell_metadata)

    shaft_master = _production_backrest_hinge_shaft_master()
    shaft = _rotate_y(shaft_master, BACK_HINGE, BACK_RAKE_DEG)
    shaft_pose = "upright_endpoint_locked"
    if state == "follow":
        shaft = _rotate_y(shaft, BACK_HINGE, BACK_FOLD_DEG)
        shaft_pose = "follow_endpoint_locked"
    parts.append(
        _new_part(
            "A06_backrest_hinge_shaft",
            shaft,
            CHAMPAGNE,
            "17-4PH stainless shaft with two clamped carrier hubs and detent discs",
            "A06",
            state,
            "One concealed full-width shaft is torque-coupled to the retained backrest structural carrier; two outboard discs provide independent upright and Follow endpoint detents.",
            physical_occurrence_id="E6-A06-HINGE-SHAFT-ASSEMBLY",
            a06_motion_hardware=True,
            exterior_weather_surface=False,
            pose=shaft_pose,
            moves_with="A06_backrest_hinge",
            controlled_hinge_mm=BACK_HINGE,
            same_master_brep_all_states=True,
            shaft_diameter_mm=2.0 * A06_HINGE_SHAFT_RADIUS_MM,
            weather_running_bore_diameter_mm=2.0 * A06_HINGE_RUNNING_RADIUS_MM,
            carrier_drive_hub_diameter_mm=2.0 * A06_HINGE_DRIVE_HUB_RADIUS_MM,
            carrier_drive_hub_centres_y_mm=(
                -A06_HINGE_DRIVE_HUB_Y_MM,
                A06_HINGE_DRIVE_HUB_Y_MM,
            ),
            torque_coupled_to_retained_backrest_structural_carrier=True,
            pc_abs_weather_shell_is_primary_load_path=False,
            redundant_lock_disc_centres_y_mm=(
                -A06_LOCK_STATION_Y_MM,
                A06_LOCK_STATION_Y_MM,
            ),
            endpoint_detent_separation_deg=abs(BACK_FOLD_DEG),
            finite_element_and_proof_load_validation_required=True,
            production_certification_claimed=False,
        )
    )

    for side_name, side in (("left", -1), ("right", 1)):
        bearing = _production_backrest_hinge_bearing_master(side)
        parts.append(
            _new_part(
                f"A06_backrest_hinge_bearing_{side_name}",
                bearing,
                GRAPHITE_BROWN,
                "sealed angular-contact bearing in passivated fixed carrier",
                "A06",
                state,
                "A fixed outboard bearing sits beyond the moving trapezoid and carries an integral lock-pin guide inside the sealed A05 rear root; its through-foot still requires a metal chassis outrigger before tooling release.",
                physical_occurrence_id=(
                    f"E6-A06-HINGE-BEARING-CARRIER-{side_name.upper()}"
                ),
                a06_motion_hardware=True,
                exterior_weather_surface=False,
                fixed_to="provisional_hidden_metal_chassis_outrigger",
                same_brep_all_states=True,
                bearing_axis_y_mm=side * A06_HINGE_BEARING_Y_MM,
                bearing_outer_diameter_mm=(
                    2.0 * A06_HINGE_BEARING_OUTER_RADIUS_MM
                ),
                bearing_running_bore_diameter_mm=(
                    2.0 * A06_HINGE_RUNNING_RADIUS_MM
                ),
                shaft_radial_running_clearance_mm=(
                    A06_HINGE_RUNNING_RADIUS_MM - A06_HINGE_SHAFT_RADIUS_MM
                ),
                a04_trim_datum_z_mm=468.0,
                a04_trim_dry_gap_mm=0.5,
                a04_pc_abs_ring_is_primary_load_path=False,
                a05_pc_abs_root_is_primary_load_path=False,
                a05_side_opening_created=False,
                structural_outrigger_physical_validation_required=True,
                structural_fastener_detail_required_before_tooling=True,
                proof_load_validation_required=True,
                production_certification_claimed=False,
            )
        )

        pin = _production_backrest_positive_lock_pin(side)
        parts.append(
            _new_part(
                f"A06_backrest_positive_lock_{side_name}",
                pin,
                CHAMPAGNE,
                "hardened stainless fail-engaged radial lock pin",
                "A06",
                state,
                "One independently guided pin enters only the matching shaft-disc endpoint bore and must withdraw completely before any backrest rotation is authorised.",
                physical_occurrence_id=(
                    f"E6-A06-POSITIVE-LOCK-PIN-{side_name.upper()}"
                ),
                a06_motion_hardware=True,
                exterior_weather_surface=False,
                fixed_guide="integral_with_corresponding_bearing_carrier",
                same_endpoint_brep_all_states=True,
                current_lock_state="engaged_endpoint",
                lock_station_y_mm=side * A06_LOCK_STATION_Y_MM,
                engaged_z_range_mm=A06_LOCK_PIN_ENGAGED_Z_MM,
                pin_diameter_mm=2.0 * A06_LOCK_PIN_RADIUS_MM,
                mating_bore_diameter_mm=2.0 * A06_LOCK_BORE_RADIUS_MM,
                diametral_running_clearance_mm=(
                    2.0 * (A06_LOCK_BORE_RADIUS_MM - A06_LOCK_PIN_RADIUS_MM)
                ),
                commanded_motion_retraction_mm=A06_LOCK_PIN_RETRACTION_MM,
                commanded_motion_minimum_disc_clearance_mm=3.0,
                redundant_pair_required=True,
                unoccupied_fold_interlock_required=True,
                proof_load_validation_required=True,
                production_certification_claimed=False,
            )
        )

        witness = _rounded_panel_xz(
            (12.0, 8.0),
            4.0,
            (180.0, side * 365.5, 490.0),
            2.0,
        )
        parts.append(
            _new_part(
                f"A06_backrest_lock_witness_{side_name}",
                witness,
                (0.34, 0.15, 0.045, 0.92),
                "smoked amber mechanical lock witness lens",
                "A06",
                state,
                "A small inward-facing witness at the fixed rear root reports the corresponding physical pin, without adding controls or graphics to the folding trapezoid.",
                physical_occurrence_id=(
                    f"E6-A06-LOCK-WITNESS-{side_name.upper()}"
                ),
                a06_motion_hardware=True,
                exterior_weather_surface=False,
                fixed_to="A05_outer_rear_root",
                same_brep_all_states=True,
                mechanically_coupled_to_lock_pin=True,
                independent_left_right_confirmation=True,
                electronic_confirmation_not_required=True,
                production_certification_claimed=False,
            )
        )

    parts.append(
        _new_part(
            "A06_backrest_manual_release",
            _a06_fixed_manual_release(),
            GRAPHITE_BROWN,
            "glass-filled PA no-power paddle with stainless cross-shaft",
            "A06",
            state,
            "A guarded central paddle behind the recovery grip operates two independent mechanical cables so both pins can be withdrawn without electrical power.",
            physical_occurrence_id="E6-A06-DUAL-CABLE-MANUAL-RELEASE",
            a06_motion_hardware=True,
            exterior_weather_surface=False,
            fixed_to="A04_rear_frame",
            same_brep_all_states=True,
            no_power_release=True,
            independently_drives_both_lock_pins=True,
            final_release_paddle_center_z_mm=350.0,
            controlled_core_equipment_vertical_corridor_mm=(310.0, 370.0),
            pdu_brep_clearance_required=True,
            release_requires_deliberate_two_stage_action=True,
            fold_motion_requires_unoccupied_interlock=True,
            cable_routing_and_force_validation_required=True,
            production_certification_claimed=False,
        )
    )


def _prototype_retract_then_fold_layout(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Replace the prototype folding mast with one retract-then-fold system."""

    identity_by_name = {
        part.name: part for part in parts if part.name.startswith("A07_")
    }
    required_identity = (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
        "A07_sensor_beam_shell",
        "A07_sensor_beam_smoked_window",
        "A07_physical_privacy_shutter",
        "A07_microphone_acoustic_mesh",
        "A07_environment_sensor_grille",
    )
    missing = [name for name in required_identity if name not in identity_by_name]
    if missing:
        raise KeyError(f"{state} production mast is missing identities: {missing}")
    parts[:] = [part for part in parts if not part.name.startswith("A07_")]

    occupied_axis_x = 366.0
    stowed_axis_x = 237.0
    beam_low_z = 1040.0
    # The terminal retracts five millimetres below the first draft datum so
    # the unperforated folded backrest retains more than 80 mm of true BRep
    # separation; only the terminal moves lower, preserving the service-core
    # floor clearance of the nested sleeves.
    beam_stowed_z = 395.0
    focus_travel = 420.0
    is_focus = state == "focus"
    is_follow = state == "follow"
    is_low = state in {"ride", "cafe"}
    visibility = (
        "internal_stowed"
        if is_follow
        else (
            "exterior_low_observation_spine"
            if is_low
            else "exterior_raised_observation_spine"
        )
    )
    pose = (
        "retracted_inside_rear_service_core"
        if is_follow
        else ("low" if is_low else "raised_420")
    )

    fixed_master = _connected_sleeve(
        (110.0, 190.0),
        (94.0, 166.0),
        250.0,
        (occupied_axis_x, 0.0, 855.0),
        40.0,
    )
    lock_accesses = tuple(
        rounded_box(
            (100.0, 18.0, 18.0),
            (occupied_axis_x, side * 96.0, 888.0),
            5.0,
        )
        for side in (-1, 1)
    )
    fixed_master = _valid_single(
        fixed_master.cut(lock_accesses[0]).cut(lock_accesses[1]),
        "A07 short fixed mast cassette",
    )
    fixed_delta = (
        (stowed_axis_x - occupied_axis_x, 0.0, 215.0 - 855.0)
        if is_follow
        else (0.0, 0.0, 0.0)
    )
    fixed_shape = fixed_master.translate(fixed_delta)

    stage_specs = (
        (
            "A07_mast_moving_inner_sleeve",
            (88.0, 154.0),
            (82.0, 148.0),
            30.0,
            (790.0, 1010.0),
            140.0,
        ),
        (
            "A07_mast_moving_inner_sleeve_stage_2",
            (76.0, 142.0),
            (70.0, 136.0),
            26.0,
            (820.0, 1010.0),
            280.0,
        ),
        (
            "A07_mast_moving_inner_sleeve_stage_3",
            (64.0, 130.0),
            (56.0, 120.0),
            22.0,
            (820.0, 1008.0),
            420.0,
        ),
    )
    # In the fully retracted stack the two outer moving sleeves stop below the
    # terminal keel.  Only the innermost stage enters the terminal's dedicated
    # 3 mm dry-running socket, so the conserved sensor beam never has to share
    # solid volume with a larger parent sleeve.
    stowed_ranges = ((110.0, 330.0), (140.0, 330.0), (180.0, 368.0))
    stage_parents = (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
        "A07_mast_moving_inner_sleeve_stage_2",
    )
    stowed_parent_overlaps = (220.0, 190.0, 150.0)
    stage_parts: list[SkinPart] = []
    original_stage = identity_by_name["A07_mast_moving_inner_sleeve"]
    for index, spec in enumerate(stage_specs, start=1):
        name, outer_xy, inner_xy, radius, low_range, focus_offset = spec
        base = _connected_sleeve(
            outer_xy,
            inner_xy,
            low_range[1] - low_range[0],
            (
                occupied_axis_x,
                0.0,
                (low_range[0] + low_range[1]) / 2.0,
            ),
            radius,
        )
        if is_follow:
            target = stowed_ranges[index - 1]
            delta = (
                stowed_axis_x - occupied_axis_x,
                0.0,
                target[0] - low_range[0],
            )
        elif is_focus:
            delta = (0.0, 0.0, focus_offset)
        else:
            delta = (0.0, 0.0, 0.0)
        shape = base.translate(delta)
        metadata = dict(original_stage.metadata)
        metadata.update(
            {
                "physical_occurrence_id": (
                    "E6-A07-MAST-MOVING-SLEEVE"
                    if index == 1
                    else f"E6-A07-MAST-MOVING-SLEEVE-STAGE-{index}"
                ),
                "pose": pose,
                "presentation_visibility": visibility,
                "telescopic_stage_index": index,
                "telescopic_stage_count": 3,
                "telescopic_parent": stage_parents[index - 1],
                "same_brep_all_states": True,
                "independent_serviceable_solid": True,
                "dry_running_interface": True,
                "nominal_dry_running_clearance_per_side_mm": 3.0,
                "minimum_required_dry_running_clearance_per_side_mm": 3.0,
                "overlap_with_parent_in_current_pose_mm": (
                    50.0
                    if is_focus
                    else (
                        stowed_parent_overlaps[index - 1]
                        if is_follow
                        else (190.0, 190.0, 188.0)[index - 1]
                    )
                ),
                "minimum_extended_overlap_mm": 50.0,
                "incremental_focus_extension_mm": 140.0,
                "absolute_focus_translation_mm": focus_offset if is_focus else 0.0,
                "controlled_terminal_stroke_mm": focus_travel,
                "terminal_stroke_sum_semantics": "140 + 140 + 140 = 420 mm",
                "nested_without_interpenetration_in_low_state": not is_focus,
                "moves_with": (
                    "sensor_beam" if index == 3 else f"mast_stage_{index}"
                ),
                "focus_z_range_mm": (
                    low_range[0] + focus_offset,
                    low_range[1] + focus_offset,
                ),
                "stowed_z_range_mm": stowed_ranges[index - 1],
                "low_z_range_mm": low_range,
                "follow_motion_sequence": "fully_retract_before_backrest_fold",
                "low_spine_required_in_ride_and_cafe": True,
                "focus_only_high_extension": True,
                "production_certification_claimed": False,
            }
        )
        stage_parts.append(
            replace(
                original_stage,
                name=name,
                shape=shape,
                intent=(
                    "One of three conserved dry-running mast sleeves; it nests in "
                    "the rear service core before the backrest is allowed to fold."
                ),
                metadata=metadata,
            )
        )

    beam_outer = _rounded_loft_z(
        (
            ((74.0, 286.0), (occupied_axis_x, 0.0), beam_low_z - 32.0, 24.0),
            ((80.0, 320.0), (occupied_axis_x, 0.0), beam_low_z - 18.0, 28.0),
            ((80.0, 320.0), (occupied_axis_x, 0.0), beam_low_z + 18.0, 28.0),
            ((74.0, 292.0), (occupied_axis_x, 0.0), beam_low_z + 32.0, 24.0),
        )
    )
    beam_inner = _rounded_loft_z(
        (
            ((62.0, 266.0), (occupied_axis_x + 2.0, 0.0), beam_low_z - 25.0, 18.0),
            ((68.0, 294.0), (occupied_axis_x + 2.0, 0.0), beam_low_z - 14.0, 20.0),
            ((68.0, 294.0), (occupied_axis_x + 2.0, 0.0), beam_low_z + 14.0, 20.0),
            ((62.0, 270.0), (occupied_axis_x + 2.0, 0.0), beam_low_z + 25.0, 18.0),
        )
    )
    beam_shell = beam_outer.cut(beam_inner)
    keel_outer = _rounded_loft_z(
        (
            ((100.0, 178.0), (occupied_axis_x, 0.0), beam_low_z - 54.0, 34.0),
            ((94.0, 206.0), (occupied_axis_x, 0.0), beam_low_z - 32.0, 34.0),
            ((82.0, 228.0), (occupied_axis_x, 0.0), beam_low_z - 12.0, 30.0),
        )
    )
    keel_clearance = _rounded_loft_z(
        (
            ((70.0, 136.0), (occupied_axis_x, 0.0), beam_low_z - 50.0, 13.0),
            ((70.0, 136.0), (occupied_axis_x, 0.0), beam_low_z - 10.0, 13.0),
        )
    )
    beam_shell = beam_shell.fuse(keel_outer).cut(keel_clearance)
    apertures = (
        rounded_box((18.0, 286.0, 44.0), (occupied_axis_x - 43.0, 0.0, beam_low_z + 1.0), 9.0),
        rounded_box((18.0, 174.0, 7.0), (occupied_axis_x - 43.0, 0.0, beam_low_z - 24.0), 2.5),
        rounded_box((30.0, 28.0, 12.0), (occupied_axis_x, 112.0, beam_low_z + 30.0), 6.0),
        rounded_box((18.0, 46.0, 26.0), (occupied_axis_x - 44.0, -130.0, beam_low_z), 6.0),
        rounded_box((18.0, 46.0, 26.0), (occupied_axis_x - 44.0, 130.0, beam_low_z), 6.0),
        rounded_rect_prism((70.0, 136.0), 70.0, (occupied_axis_x, 0.0, beam_low_z - 30.0), 25.0),
    )
    for aperture in apertures:
        beam_shell = beam_shell.cut(aperture)
    beam_master = _valid_single(beam_shell, "A07 conserved sensor beam shell")
    beam_delta = (
        (stowed_axis_x - occupied_axis_x, 0.0, beam_stowed_z - beam_low_z)
        if is_follow
        else (0.0, 0.0, focus_travel if is_focus else 0.0)
    )

    def pose_shape(shape: cq.Shape) -> cq.Shape:
        return shape.translate(beam_delta)

    sensor_window = rounded_box(
        (5.0, 280.0, 40.0),
        (occupied_axis_x - 39.5, 0.0, beam_low_z + 1.0),
        9.0,
    )
    microphone_mesh = rounded_box(
        (5.0, 170.0, 5.0),
        (occupied_axis_x - 42.5, 0.0, beam_low_z - 24.0),
        2.5,
    )
    environment_grille = rounded_box(
        (26.0, 24.0, 4.0),
        (occupied_axis_x, 112.0, beam_low_z + 30.0),
        5.0,
    )
    privacy_x = (
        occupied_axis_x + 15.0
        if is_focus
        else occupied_axis_x - 45.5
    )
    privacy_y = 0.0 if is_focus else -8.0
    privacy_shutter = _canonical_privacy_shutter().translate(
        (
            privacy_x - 264.5,
            privacy_y - 128.0,
            beam_low_z - 1460.0,
        )
    )
    fill_windows = {
        side_name: rounded_box(
            (8.0, 42.0, 22.0),
            (occupied_axis_x - 44.0, side * 130.0, beam_low_z),
            6.0,
        )
        for side_name, side in (("left", -1), ("right", 1))
    }
    for window in fill_windows.values():
        sensor_window = sensor_window.cut(window)
    sensor_window = _valid_single(
        sensor_window,
        "A07 partitioned smoked sensor window",
    )

    def replaced_a07(
        name: str,
        shape: cq.Shape,
        *,
        material: str,
        intent: str,
        physical_id: str,
    ) -> SkinPart:
        source = identity_by_name.get(name, identity_by_name[required_identity[0]])
        metadata = dict(source.metadata)
        metadata.update(
            {
                "physical_occurrence_id": physical_id,
                "pose": pose,
                "presentation_visibility": visibility,
                "same_brep_all_states": True,
                "follow_motion_sequence": "fully_retract_before_backrest_fold",
                "stowed_envelope_bounds_mm": (
                    (181.0, 293.0, -165.0, 165.0, 90.0, 429.0)
                    if is_follow
                    else None
                ),
                "low_spine_required_in_ride_and_cafe": True,
                "focus_only_high_extension": True,
                "occupied_axis_x_mm": occupied_axis_x,
                "fixed_during_ride_cafe_to_focus_extension": True,
                "production_certification_claimed": False,
            }
        )
        return replace(
            source,
            name=name,
            shape=shape,
            material=material,
            intent=intent,
            metadata=metadata,
        )

    fixed_part = replaced_a07(
        "A07_mast_fixed_outer_sleeve",
        fixed_shape,
        material="mineral-matte PC-ABS short retracting mast cassette",
        intent=(
            "The conserved root cassette retracts only for Follow; it remains on "
            "one occupied axis through Ride, Cafe and the complete Focus extension."
        ),
        physical_id="E6-A07-MAST-FIXED-SLEEVE",
    )
    beam_part = replaced_a07(
        "A07_sensor_beam_shell",
        pose_shape(beam_master),
        material="fine-matte PC-ABS instrument terminal shell",
        intent=(
            "The conserved terminal is internal only in Follow, forms the low "
            "observation edge in Ride/Cafe, and rises exactly 420 mm in Focus."
        ),
        physical_id="E6-A07-SENSOR-BEAM-SHELL",
    )
    inserts = [
        replaced_a07(
            "A07_sensor_beam_smoked_window",
            pose_shape(sensor_window),
            material="IR-transparent smoked polycarbonate",
            intent="A single restrained optical horizon, internal and physically shuttered in Follow.",
            physical_id="WC-MAST-SMOKED-SENSOR-WINDOW",
        ),
        replaced_a07(
            "A07_physical_privacy_shutter",
            pose_shape(privacy_shutter),
            material="opaque mechanically linked privacy shutter",
            intent="The physical privacy shutter remains a separate conserved solid in every state.",
            physical_id="WC-MAST-PHYSICAL-PRIVACY-SHUTTER",
        ),
        replaced_a07(
            "A07_microphone_acoustic_mesh",
            pose_shape(microphone_mesh),
            material="hydrophobic laser-perforated stainless acoustic mesh",
            intent="The acoustic interface follows the conserved sensor terminal into the stow cassette.",
            physical_id="WC-MAST-MICROPHONE-ARRAY-INTERFACE",
        ),
        replaced_a07(
            "A07_environment_sensor_grille",
            pose_shape(environment_grille),
            material="hydrophobic ePTFE environmental-sensor grille",
            intent="The environmental interface follows the sensor terminal and is inactive inside Follow stow.",
            physical_id="WC-MAST-ENVIRONMENT-SENSOR-INTERFACE",
        ),
    ]
    for side_name, window in fill_windows.items():
        inserts.append(
            replaced_a07(
                f"A07_fill_light_visible_window_{side_name}",
                pose_shape(window),
                material="smoked warm-neutral optical polycarbonate",
                intent="The task-light window is conserved with the sensor terminal and active only in Focus.",
                physical_id=f"WC-MAST-FILL-LIGHT-VISIBLE-WINDOW-{side_name.upper()}",
            )
        )
    for side_name, side in (("left", -1), ("right", 1)):
        lens_master = rounded_box(
            (94.0, 3.0, 16.0),
            (occupied_axis_x, side * 96.5, 888.0),
            4.5,
        )
        inserts.append(
            replaced_a07(
                f"A07_mast_lock_pin_confirmation_lens_{side_name}",
                lens_master.translate(fixed_delta),
                material="flush smoked lock-confirmation lens",
                intent="A direct lock witness remains on the short mast cassette and moves into authorised service stow.",
                physical_id=f"E6-A07-MAST-LOCK-LENS-{side_name.upper()}",
            )
        )

    parts.extend((fixed_part, *stage_parts, beam_part, *inserts))


@lru_cache(maxsize=1)
def _production_a07_low_masters() -> dict[str, cq.Shape]:
    """Build the conserved one-stage A07 surfaces on controlled low axes."""

    # Keep the released 708 mm lower datum, but terminate the broad structural
    # sleeve below the A06 roof and fuse a short flush throat collar to it.  The
    # collar fills the existing 96 x 166 mm A06 opening to a two-millimetre
    # perimeter seal, while its 60.8 x 126.8 mm running aperture preserves at
    # least three millimetres of true radial clearance around the one-piece
    # moving spine through the complete 420 mm stroke.  In Follow this existing
    # mast member therefore reads as the continuation of the folded trapezoid,
    # not as a proud black-framed handle.  No lid, cover or new occurrence is
    # introduced and the same B-Rep remains in all four states.
    fixed_main = _connected_sleeve(
        (82.0, 152.0),
        (66.0, 136.0),
        290.0,
        (A07_AXIS_X_MM, 0.0, 853.0),
        28.0,
    )
    fixed_flush_collar = _connected_sleeve(
        (92.0, 162.0),
        (
            A07_FIXED_THROAT_COLLAR_INNER_X_MM,
            A07_FIXED_THROAT_COLLAR_INNER_Y_MM,
        ),
        7.0,
        (A07_AXIS_X_MM, 0.0, 999.5),
        24.0,
    )
    fixed = _fuse_single_shapes(
        (fixed_main, fixed_flush_collar),
        "A07 fixed sleeve with integral flush A06 throat collar",
    )
    # Two hidden deep-bearing bosses support the radial lock pins from the
    # fixed A06 channel side.  The pins enter from -X, cross the fixed front
    # wall and engage one discrete bore in the moving member.  A boss is real
    # load-bearing material; the visible witness lens is not credited as a
    # structural lock.
    fixed_lock_bores: list[cq.Shape] = []
    for side in (-1, 1):
        y_mm = side * A07_LOCK_PIN_Y_MM
        boss_outer = _a07_x_cylinder(
            A07_LOCK_HOUSING_DIAMETER_MM / 2.0,
            A07_LOCK_HOUSING_X_MM,
            y_mm,
            A07_LOCK_STATION_Z_MM,
        )
        fixed = fixed.fuse(boss_outer).clean()
        fixed_lock_bores.append(
            _a07_x_cylinder(
                A07_LOCK_BORE_DIAMETER_MM / 2.0,
                (255.0, 294.0),
                y_mm,
                A07_LOCK_STATION_Z_MM,
            )
        )
    for bore in fixed_lock_bores:
        fixed = fixed.cut(bore)
    # The smoked confirmation lenses are recessed inserts, not decorative
    # solids occupying the fixed sleeve wall.  Two real 0.3 mm radial / 1 mm
    # axial seats preserve the structural lock bosses at Y=+/-34 mm.
    for side in (-1, 1):
        fixed = fixed.cut(
            _a07_x_cylinder(
                4.5,
                (268.5, 273.5),
                side * 52.0,
                A07_LOCK_STATION_Z_MM,
            )
        )
    fixed = _valid_single(fixed.clean(), "A07 fixed sleeve with lock-pin bosses")
    moving_outer = _rounded_loft_z(
        (
            ((54.0, 120.0), (A07_AXIS_X_MM, 0.0), 438.0, 10.0),
            ((54.0, 120.0), (A07_AXIS_X_MM, 0.0), 588.0, 10.0),
            ((51.0, 112.0), (A07_AXIS_X_MM, 0.0), 800.0, 12.0),
            ((48.0, 104.0), (A07_AXIS_X_MM, 0.0), 1004.0, 14.0),
        )
    )
    moving_inner = _rounded_loft_z(
        (
            ((46.0, 112.0), (A07_AXIS_X_MM, 0.0), 442.0, 8.0),
            ((46.0, 112.0), (A07_AXIS_X_MM, 0.0), 590.0, 8.0),
            ((43.0, 104.0), (A07_AXIS_X_MM, 0.0), 800.0, 10.0),
            ((40.0, 96.0), (A07_AXIS_X_MM, 0.0), 1000.0, 12.0),
        )
    )
    moving_shell = _valid_single(
        moving_outer.cut(moving_inner).clean(),
        "A07 gently tapered one-piece moving spine",
    )
    # A five-millimetre integral guide pilot extends the same moving
    # occurrence below its broad cosmetic body.  Its narrower 44 x 100 mm
    # envelope preserves the released A10 tunnel clearance, while providing
    # a real 150 mm fixed-sleeve capture at the +420 mm Focus endpoint.  This
    # avoids falsifying the capture with metadata or lowering the full-width
    # body into the service surround.
    capture_pilot = _connected_sleeve(
        (44.0, 100.0),
        (36.0, 92.0),
        5.0,
        (A07_AXIS_X_MM, 0.0, 435.5),
        8.0,
    )
    moving_shell = _valid_single(
        moving_shell.fuse(capture_pilot).clean(),
        "A07 one-piece moving spine with integral capture pilot",
    )
    terminal_tenon_outer = rounded_rect_prism(
        (36.0, 80.0),
        24.0,
        (A07_AXIS_X_MM, 0.0, 1012.0),
        8.0,
    )
    terminal_tenon_inner = rounded_rect_prism(
        (28.0, 72.0),
        28.0,
        (A07_AXIS_X_MM, 0.0, 1012.0),
        6.0,
    )
    terminal_tenon = _valid_single(
        terminal_tenon_outer.cut(terminal_tenon_inner),
        "A07 terminal capture tenon",
    )
    moving = _valid_single(
        moving_shell.fuse(terminal_tenon).clean(),
        "A07 moving spine with captured terminal tenon",
    )
    # A source-aligned fixed lock station needs two *discrete* hole sets in
    # the translating member.  At the low endpoint Z=888 aligns directly;
    # after +420 mm the second master hole at Z=468 reaches the same station.
    # No longitudinal slot is permitted between them, preserving the front
    # wall as a continuous compression/shear web through the travel range.
    moving_lock_bores = tuple(
        _a07_x_cylinder(
            A07_LOCK_BORE_DIAMETER_MM / 2.0,
            (276.0, 344.0),
            side * A07_LOCK_PIN_Y_MM,
            bore_z,
        )
        for side in (-1, 1)
        for bore_z in (A07_LOCK_LOW_BORE_Z_MM, A07_LOCK_FOCUS_BORE_Z_MM)
    )
    for bore in moving_lock_bores:
        moving = moving.cut(bore)
    moving = _valid_single(
        moving.clean(),
        "A07 moving spine with two discrete endpoint lock-hole sets",
    )

    # A restrained instrument crown replaces the constant-section hammerhead.
    # Repeated end sections clamp the smooth loft and prevent spline overshoot
    # below the controlled 1008 mm docking plane.
    beam_outer = _rounded_loft_z(
        (
            ((64.0, 164.0), (310.0, 0.0), 1008.0, 16.0),
            ((64.0, 164.0), (310.0, 0.0), 1012.0, 16.0),
            ((76.0, 260.0), (308.0, 8.0), 1024.0, 18.0),
            ((88.0, 340.0), (305.0, 18.0), 1038.0, 20.0),
            ((92.0, 368.0), (304.0, 24.0), 1054.0, 20.0),
            ((82.0, 344.0), (309.0, 24.0), 1068.0, 18.0),
            ((82.0, 344.0), (309.0, 24.0), 1072.0, 18.0),
        )
    )
    beam_inner = _rounded_loft_z(
        (
            ((44.0, 120.0), (310.0, 0.0), 1016.0, 10.0),
            ((44.0, 120.0), (310.0, 0.0), 1020.0, 10.0),
            ((56.0, 220.0), (308.0, 8.0), 1030.0, 11.0),
            ((68.0, 300.0), (306.0, 18.0), 1042.0, 12.0),
            ((70.0, 320.0), (306.0, 22.0), 1054.0, 12.0),
            ((54.0, 270.0), (309.0, 22.0), 1060.0, 10.0),
            ((54.0, 270.0), (309.0, 22.0), 1064.0, 10.0),
        )
    )
    beam_shell = _valid_single(
        beam_outer.cut(beam_inner).clean(),
        "A07 crowned terminal before functional apertures",
    )
    # The spine terminates four millimetres below the crown.  Its hollow tenon
    # then engages a deeper keyed socket instead of relying on the former
    # zero-distance face contact at z=1008.  The 3 mm radial assembly space is
    # reserved for hidden structural keys / captive fasteners in detailed ME.
    terminal_socket = rounded_box(
        (42.0, 86.0, 26.0),
        (A07_AXIS_X_MM, 0.0, 1013.0),
        6.0,
    )
    beam_shell = _valid_single(
        beam_shell.cut(terminal_socket).clean(),
        "A07 crowned terminal with captured spine socket",
    )
    apertures = (
        rounded_box((20.0, 286.0, 44.0), (264.0, 0.0, 1040.0), 9.0),
        rounded_box((20.0, 72.0, 44.0), (264.0, 164.0, 1040.0), 9.0),
        rounded_box((22.0, 60.0, 12.0), (330.0, -75.0, 1071.0), 5.0),
        rounded_box((16.0, 80.0, 10.0), (284.5, 0.0, 1011.0), 4.0),
        rounded_box((16.0, 20.0, 10.0), (310.0, -56.0, 1011.0), 4.0),
        rounded_box((16.0, 20.0, 10.0), (310.0, 56.0, 1011.0), 4.0),
    )
    for aperture in apertures:
        beam_shell = beam_shell.cut(aperture)
    # The physical privacy bezel is a moving carriage, not a decorative
    # applique.  Its closed centre is Y=-8 and its Focus park is Y=+128, so
    # the terminal needs one continuous swept service pocket across both
    # endpoints.  The 0.2 mm enlargement on every axis removes the residual
    # rounded-corner interference while preserving a deliberate dry reveal.
    shutter_carriage_swept_pocket = rounded_box(
        (2.4, 270.4, 42.4),
        (268.0, 60.0, A07_LOW_BEAM_Z_MM),
        0.8,
    )
    beam_shell = beam_shell.cut(shutter_carriage_swept_pocket)
    beam_shell = _valid_single(
        beam_shell.clean(),
        "A07 crowned one-stage sensor terminal",
    )

    sensor_window = rounded_box(
        (2.0, 276.0, 30.0),
        (261.0, 0.0, 1044.0),
        8.0,
    )
    microphone_mesh = rounded_box(
        (12.0, 76.0, 2.0),
        (284.5, 0.0, 1010.5),
        2.0,
    )
    environment_grille = rounded_box(
        (18.0, 56.0, 2.0),
        (330.0, -75.0, 1070.0),
        3.0,
    )
    fill_windows = {
        side_name: rounded_box(
            (12.0, 16.0, 2.0),
            (310.0, side * 56.0, 1010.5),
            4.0,
        )
        for side_name, side in (("left", -1), ("right", 1))
    }

    closed_shutter = _canonical_privacy_shutter().translate(
        (0.0, -136.0, -A07_FOCUS_STROKE_MM)
    )
    bezel_outer = rounded_box(
        (2.0, 134.0, 42.0),
        (268.0, -8.0, A07_LOW_BEAM_Z_MM),
        6.0,
    )
    bezel_inner = rounded_box(
        (4.0, 128.0, 36.0),
        (268.0, -8.0, A07_LOW_BEAM_Z_MM),
        5.0,
    )
    shutter_bezel = _valid_single(
        bezel_outer.cut(bezel_inner),
        "A07 moving privacy-shutter carriage bezel",
    )
    throat_outer = rounded_box(
        (96.0, 166.0, 1.5),
        (A07_AXIS_X_MM, 0.0, 1003.75),
        12.0,
    )
    throat_inner = rounded_box(
        (92.0, 162.0, 3.5),
        (A07_AXIS_X_MM, 0.0, 1003.75),
        10.0,
    )
    throat_gasket = _valid_single(
        throat_outer.cut(throat_inner).clean(),
        "A07 fixed labyrinth throat gasket",
    )
    lock_lenses = {
        side_name: (
            cq.Workplane("YZ")
            .circle(4.2)
            .extrude(1.5, both=True)
            .translate((271.0, side * 52.0, 888.0))
            .val()
        )
        for side_name, side in (("left", -1), ("right", 1))
    }
    lock_pins_engaged = {
        side_name: _a07_x_cylinder(
            A07_LOCK_PIN_DIAMETER_MM / 2.0,
            A07_LOCK_PIN_ENGAGED_X_MM,
            side * A07_LOCK_PIN_Y_MM,
            A07_LOCK_STATION_Z_MM,
        )
        for side_name, side in (("left", -1), ("right", 1))
    }
    lock_pins_retracted = {
        side_name: _a07_x_cylinder(
            A07_LOCK_PIN_DIAMETER_MM / 2.0,
            A07_LOCK_PIN_RETRACTED_X_MM,
            side * A07_LOCK_PIN_Y_MM,
            A07_LOCK_STATION_Z_MM,
        )
        for side_name, side in (("left", -1), ("right", 1))
    }
    return {
        "fixed": fixed,
        "moving": moving,
        "beam": beam_shell,
        "sensor_window": sensor_window,
        "privacy_shutter": closed_shutter,
        "privacy_shutter_carriage_bezel": shutter_bezel,
        "microphone_mesh": microphone_mesh,
        "environment_grille": environment_grille,
        "fill_window_left": fill_windows["left"],
        "fill_window_right": fill_windows["right"],
        "throat_gasket": throat_gasket,
        "lock_lens_left": lock_lenses["left"],
        "lock_lens_right": lock_lenses["right"],
        "lock_pin_engaged_left": lock_pins_engaged["left"],
        "lock_pin_engaged_right": lock_pins_engaged["right"],
        "lock_pin_retracted_left": lock_pins_retracted["left"],
        "lock_pin_retracted_right": lock_pins_retracted["right"],
    }


def a07_lock_motion_pose(stroke_mm: float) -> A07LockMotionPose:
    """Pose the released A07 lock for one 0..420 mm commanded stroke.

    Both pins are positively engaged only at the two indexed endpoints.  Any
    intermediate command first withdraws the pins fully behind the fixed
    sleeve's inner wall; mast translation is therefore never asked to drag a
    pin through aluminium.  The actuator/interlock command order is enforced
    by the returned physical pose rather than by a visibility flag.
    """

    stroke = float(stroke_mm)
    if not -A07_LOCK_ENDPOINT_TOLERANCE_MM <= stroke <= (
        A07_FOCUS_STROKE_MM + A07_LOCK_ENDPOINT_TOLERANCE_MM
    ):
        raise ValueError(
            f"A07 stroke {stroke_mm!r} is outside 0..{A07_FOCUS_STROKE_MM} mm"
        )
    stroke = min(max(stroke, 0.0), A07_FOCUS_STROKE_MM)
    at_low = abs(stroke) <= A07_LOCK_ENDPOINT_TOLERANCE_MM
    at_focus = (
        abs(stroke - A07_FOCUS_STROKE_MM)
        <= A07_LOCK_ENDPOINT_TOLERANCE_MM
    )
    engaged = at_low or at_focus
    masters = _production_a07_low_masters()
    key = "engaged" if engaged else "retracted"
    return A07LockMotionPose(
        stroke_mm=stroke,
        pin_state=key,
        active_bore_master_z_mm=(
            A07_LOCK_LOW_BORE_Z_MM
            if at_low
            else A07_LOCK_FOCUS_BORE_Z_MM if at_focus else None
        ),
        fixed_sleeve=masters["fixed"],
        moving_spine=masters["moving"].translate((0.0, 0.0, stroke)),
        lock_pins=(
            masters[f"lock_pin_{key}_left"],
            masters[f"lock_pin_{key}_right"],
        ),
    )


def _production_mast_layout(state: str, parts: list[SkinPart]) -> None:
    """Install one conserved low spine; Focus only translates it +420 mm."""

    identity_by_name = {
        part.name: part for part in parts if part.name.startswith("A07_")
    }
    required = (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
        "A07_sensor_beam_shell",
        "A07_sensor_beam_smoked_window",
        "A07_physical_privacy_shutter",
        "A07_microphone_acoustic_mesh",
        "A07_environment_sensor_grille",
    )
    missing = [name for name in required if name not in identity_by_name]
    if missing:
        raise KeyError(f"{state} production A07 is missing identities: {missing}")
    parts[:] = [part for part in parts if not part.name.startswith("A07_")]

    masters = _production_a07_low_masters()
    is_focus = state == "focus"
    is_follow = state == "follow"
    pose = "folded_with_same_backrest" if is_follow else (
        "raised_420" if is_focus else "low"
    )
    visibility = (
        "exposed_cofolded_mast"
        if is_follow
        else (
            "raised_observation_spine"
            if is_focus
            else "low_observation_horizon"
        )
    )
    terminal_visibility = (
        "folded_low_sensor_horizon_on_same_backrest"
        if is_follow
        else visibility
    )

    def posed(
        shape: cq.Shape,
        *,
        focus_translation: bool,
        privacy_translation: bool = False,
    ) -> cq.Shape:
        result = shape
        if is_focus and focus_translation:
            delta_y = 136.0 if privacy_translation else 0.0
            result = result.translate(
                (0.0, delta_y, A07_FOCUS_STROKE_MM)
            )
        if is_follow:
            result = _rotate_y(
                result,
                BACK_HINGE,
                BACK_FOLD_DEG,
            )
        return result

    def replaced(
        source_name: str,
        final_name: str,
        shape: cq.Shape,
        *,
        material: str,
        intent: str,
        physical_id: str,
        focus_translation: bool,
        privacy_translation: bool = False,
        **extra: object,
    ) -> SkinPart:
        source = identity_by_name[source_name]
        metadata = dict(source.metadata)
        metadata.update(
            {
                "physical_occurrence_id": physical_id,
                "pose": pose,
                "presentation_visibility": visibility,
                "same_brep_all_states": True,
                "controlled_axis_x_mm": A07_AXIS_X_MM,
                "controlled_low_pose": True,
                "ride_cafe_same_low_pose": True,
                "fixed_through_ride_cafe_focus": not focus_translation,
                "focus_translation_mm": (
                    A07_FOCUS_STROKE_MM
                    if is_focus and focus_translation
                    else 0.0
                ),
                "focus_translation_exactly_420_mm": focus_translation,
                "follow_shared_hinge_mm": BACK_HINGE,
                "follow_shared_hinge_delta_from_dfr4_mm": 6.0,
                "follow_fold_deg": BACK_FOLD_DEG,
                "follow_locked_to_same_backrest_before_fold": True,
                "three_stage_suitcase_handle_architecture_removed": True,
                "one_piece_finished_observation_spine": True,
                "production_certification_claimed": False,
                **extra,
            }
        )
        # Every part built by this helper belongs to the canonical thirteen-
        # piece A07 exterior bill.  Follow changes only the shared A06 hinge
        # pose; the separate hardened pins created below remain internal.
        metadata["final_exterior_visible"] = True
        return replace(
            source,
            name=final_name,
            shape=posed(
                shape,
                focus_translation=focus_translation,
                privacy_translation=privacy_translation,
            ),
            material=material,
            intent=intent,
            metadata=metadata,
        )

    fixed = replaced(
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_fixed_outer_sleeve",
        masters["fixed"],
        material="mineral-matte PC-ABS fixed observation sleeve",
        intent=(
            "The same fixed sleeve remains on X=310 in Ride, Cafe and Focus "
            "and is enclosed by the channel fused into A06."
        ),
        physical_id="E6-A07-MAST-FIXED-SLEEVE",
        focus_translation=False,
        moves_with="A06_backrest_hinge_in_follow_only",
        fixed_in_operational_states=True,
        controlled_low_bounds_mm=(
            264.0,
            356.0,
            -81.0,
            81.0,
            708.0,
            1003.0,
        ),
        lock_station_z_mm=A07_LOCK_STATION_Z_MM,
        lock_pin_support_boss_x_mm=A07_LOCK_HOUSING_X_MM,
        lock_pin_support_boss_diameter_mm=A07_LOCK_HOUSING_DIAMETER_MM,
        lock_pin_bore_diameter_mm=A07_LOCK_BORE_DIAMETER_MM,
        fixed_wall_and_external_boss_share_lock_load=True,
        throat_collar_inner_aperture_mm=(
            A07_FIXED_THROAT_COLLAR_INNER_X_MM,
            A07_FIXED_THROAT_COLLAR_INNER_Y_MM,
        ),
        fixed_to_moving_minimum_radial_clearance_contract_mm=(
            A07_FIXED_TO_MOVING_MINIMUM_RADIAL_CLEARANCE_MM
        ),
    )
    moving = replaced(
        "A07_mast_moving_inner_sleeve",
        "A07_mast_moving_inner_sleeve",
        masters["moving"],
        material="body-colour ceramic-coated low-friction aluminium spine",
        intent=(
            "One finished moving member stays hidden in the low A06 channel "
            "and exposes only its deliberate 420 mm Focus extension."
        ),
        physical_id="E6-A07-MAST-MOVING-SLEEVE",
        focus_translation=True,
        moves_with="sensor_terminal_focus_axis_and_A06_follow_hinge",
        telescopic_stage_count=1,
        controlled_low_bounds_mm=(
            282.8,
            337.2,
            -60.4,
            60.4,
            433.0,
            1024.0,
        ),
        cosmetic_spine_bounds_z_mm=(438.0, 1004.0),
        integral_capture_pilot_bounds_z_mm=(433.0, 438.0),
        integral_capture_pilot_outer_plan_mm=(44.0, 100.0),
        integral_capture_pilot_internal_channel_mm=(36.0, 92.0),
        terminal_tenon_bounds_z_mm=(1000.0, 1024.0),
        terminal_tenon_plan_mm=(36.0, 80.0),
        terminal_tenon_wall_mm=4.0,
        terminal_tenon_engagement_mm=16.0,
        terminal_joint_radial_assembly_gap_mm=(3.0, 3.0),
        terminal_joint_end_clearance_mm=2.0,
        terminal_joint_dry_seam_mm=4.0,
        terminal_joint_hidden_captive_fastening_required=True,
        minimum_extended_overlap_mm=150.0,
        endpoint_lock_bore_master_z_mm=(
            A07_LOCK_LOW_BORE_Z_MM,
            A07_LOCK_FOCUS_BORE_Z_MM,
        ),
        endpoint_lock_bore_world_z_mm=A07_LOCK_STATION_Z_MM,
        endpoint_lock_bore_diameter_mm=A07_LOCK_BORE_DIAMETER_MM,
        endpoint_lock_bores_are_discrete=True,
        longitudinal_lock_slot_present=False,
        lock_release_required_before_focus_motion=True,
        focus_motion_inhibited_until_both_pins_retracted=True,
        terminal_load_path=(
            "sensor_terminal",
            "moving_spine_endpoint_bore",
            "two_hardened_lock_pins",
            "fixed_sleeve_deep_bearing_bosses",
            "A06_structural_channel",
        ),
    )
    beam = replaced(
        "A07_sensor_beam_shell",
        "A07_sensor_beam_shell",
        masters["beam"],
        material="fine-matte PC-ABS crowned sensor-terminal shell",
        intent=(
            "The same terminal is the low Ride/Cafe sensing horizon, folds "
            "as one locked assembly with A06 in Follow, and translates exactly "
            "420 mm in Focus."
        ),
        physical_id="E6-A07-SENSOR-BEAM-SHELL",
        focus_translation=True,
        moves_with="sensor_terminal_focus_axis_and_A06_follow_hinge",
        controlled_low_center_z_mm=A07_LOW_BEAM_Z_MM,
        controlled_plan_mm=(94.0, 370.0),
        terminal_socket_plan_mm=(42.0, 86.0),
        terminal_socket_bounds_z_mm=(1000.0, 1026.0),
        terminal_socket_captures_moving_spine_tenon=True,
        presentation_visibility=terminal_visibility,
        integrated_privacy_pocket_positive_y_mm=208.1,
        privacy_shutter_carriage_swept_pocket_center_y_mm=60.0,
        privacy_shutter_carriage_swept_pocket_plan_mm=(2.4, 270.4),
        privacy_shutter_carriage_swept_pocket_height_mm=42.4,
        privacy_shutter_carriage_pocket_nominal_clearance_mm=(
            A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM
        ),
        crowned_terminal_not_constant_section=True,
        low_horizon_visually_required=True,
    )
    sensor_window = replaced(
        "A07_sensor_beam_smoked_window",
        "A07_sensor_beam_smoked_window",
        masters["sensor_window"],
        material="IR-transparent smoked polycarbonate recessed optical horizon",
        intent=(
            "One quiet smoked horizon distinguishes navigation from the "
            "physically shuttered work camera without a cluster of robot eyes."
        ),
        physical_id="WC-MAST-SMOKED-SENSOR-WINDOW",
        focus_translation=True,
        moves_with="sensor_terminal_focus_axis_and_A06_follow_hinge",
        presentation_visibility=terminal_visibility,
        controlled_source_center_x_mm=267.5,
        final_recessed_center_x_mm=261.0,
        physical_shutter_dry_gap_mm=0.5,
        fully_recessed_inside_terminal_aperture=True,
    )
    shutter = replaced(
        "A07_physical_privacy_shutter",
        "A07_physical_privacy_shutter",
        masters["privacy_shutter"],
        material="opaque mechanically linked physical privacy shutter",
        intent=(
            "The same opaque shutter covers the low optical horizon and parks "
            "visibly at the right edge only after Focus is locked."
        ),
        physical_id="WC-MAST-PHYSICAL-PRIVACY-SHUTTER",
        focus_translation=True,
        privacy_translation=True,
        moves_with="sensor_terminal_and_privacy_shutter",
        presentation_visibility=terminal_visibility,
        shutter_position="parked" if is_focus else "closed",
        controlled_focus_center_mm=(264.5, 128.0, 1460.0),
    )
    microphone = replaced(
        "A07_microphone_acoustic_mesh",
        "A07_microphone_acoustic_mesh",
        masters["microphone_mesh"],
        material="hydrophobic laser-perforated stainless acoustic mesh",
        intent="One restrained acoustic line follows the conserved terminal.",
        physical_id="WC-MAST-MICROPHONE-ARRAY-INTERFACE",
        focus_translation=True,
        moves_with="sensor_terminal_focus_axis_and_A06_follow_hinge",
        presentation_visibility=terminal_visibility,
        acoustic_mesh_plan_mm=(12.0, 76.0),
        acoustic_mesh_low_center_mm=(284.5, 0.0, 1010.5),
        minimum_dry_clearance_to_terminal_tenon_mm=(
            A07_MICROPHONE_TENON_MINIMUM_DRY_CLEARANCE_MM
        ),
        terminal_tenon_acoustic_path_is_outboard=True,
    )
    environment = replaced(
        "A07_environment_sensor_grille",
        "A07_environment_sensor_grille",
        masters["environment_grille"],
        material="hydrophobic ePTFE environmental-sensor grille",
        intent="A protected top-deck air-exchange interface follows the terminal.",
        physical_id="WC-MAST-ENVIRONMENT-SENSOR-INTERFACE",
        focus_translation=True,
        moves_with="sensor_terminal_focus_axis_and_A06_follow_hinge",
        presentation_visibility=terminal_visibility,
    )

    inserts: list[SkinPart] = []
    for side_name in ("left", "right"):
        source_name = f"A07_fill_light_visible_window_{side_name}"
        source = identity_by_name.get(
            source_name,
            identity_by_name["A07_sensor_beam_smoked_window"],
        )
        metadata = dict(source.metadata)
        metadata.update(
            {
                "physical_occurrence_id": (
                    f"WC-MAST-FILL-LIGHT-VISIBLE-WINDOW-{side_name.upper()}"
                ),
                "pose": pose,
                "presentation_visibility": visibility,
                "same_brep_all_states": True,
                "controlled_axis_x_mm": A07_AXIS_X_MM,
                "focus_translation_mm": (
                    A07_FOCUS_STROKE_MM if is_focus else 0.0
                ),
                "moves_with": "sensor_terminal_focus_axis_and_A06_follow_hinge",
                "light_pipe_turns_to_protected_terminal_underside": True,
                "active_only_in": "focus",
                "production_certification_claimed": False,
            }
        )
        metadata["final_exterior_visible"] = True
        inserts.append(
            replace(
                source,
                name=source_name,
                shape=posed(
                    masters[f"fill_window_{side_name}"],
                    focus_translation=True,
                ),
                material="smoked warm-neutral diffusing optical polycarbonate",
                intent=(
                    "A protected underside light pipe illuminates the work "
                    "surface without colliding with the parked privacy shutter."
                ),
                metadata=metadata,
            )
        )

    bezel_shape = posed(
        masters["privacy_shutter_carriage_bezel"],
        focus_translation=True,
        privacy_translation=True,
    )
    bezel = _new_part(
        "A07_privacy_shutter_carriage_bezel",
        bezel_shape,
        LUNAR_STONE,
        "mineral-matte PC-ABS moving privacy-shutter edge bezel",
        "A07",
        state,
        (
            "The conserved bezel frames the closed shutter and travels with it "
            "to make the Focus parked position a deliberate physical state."
        ),
        physical_occurrence_id="E6-A07-PRIVACY-SHUTTER-CARRIAGE-BEZEL",
        pose=pose,
        same_brep_all_states=True,
        controlled_focus_center_mm=(268.0, 128.0, 1460.0),
        moves_with="sensor_terminal_and_privacy_shutter",
        focus_translation_mm=(
            A07_FOCUS_STROKE_MM if is_focus else 0.0
        ),
        privacy_lateral_translation_mm=136.0 if is_focus else 0.0,
        enclosed_inside_integrated_terminal_pocket=True,
        carriage_sweep_low_to_park_y_mm=(-8.0, 128.0),
        carriage_swept_pocket_nominal_clearance_mm=(
            A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM
        ),
        zero_common_volume_with_terminal_required=True,
        production_certification_claimed=False,
        final_exterior_visible=True,
    )
    throat_gasket = _new_part(
        "A07_mast_throat_weather_gasket",
        posed(masters["throat_gasket"], focus_translation=False),
        LUNAR_STONE,
        "body-colour low-gloss fluorosilicone A07 flush labyrinth seal",
        "A07",
        state,
        (
            "A fixed compliant dark reveal closes the five-millimetre dry gap "
            "without creating a rigid cap in the Focus deployment path."
        ),
        physical_occurrence_id="E6-A07-MAST-THROAT-WEATHER-GASKET",
        pose=pose,
        same_brep_all_states=True,
        fixed_to_backrest_channel=True,
        moves_with="A06_backrest_hinge_in_follow_only",
        low_terminal_vertical_dry_gap_mm=5.0,
        minimum_moving_spine_radial_gap_mm=1.5,
        visible_perimeter_lip_mm=2.0,
        flush_to_a06_roof_top_z_mm=1003.0,
        black_frame_or_handle_reading=False,
        body_colour_visual_continuity_with_a06=True,
        follows_shared_backrest_hinge_in_follow=True,
        final_exterior_visible=True,
        production_certification_claimed=False,
    )
    lock_lenses: list[SkinPart] = []
    for side_name in ("left", "right"):
        lock_lenses.append(
            _new_part(
                f"A07_mast_lock_pin_confirmation_lens_{side_name}",
                posed(
                    masters[f"lock_lens_{side_name}"],
                    focus_translation=False,
                ),
                CHAMPAGNE,
                "recessed mechanically driven lock-confirmation witness lens",
                "A07",
                state,
                (
                    "A service-visible mechanical witness is driven by the "
                    "lock actuator, while the separate hardened pin carries "
                    "the structural load; the lens is not credited as a lock."
                ),
                physical_occurrence_id=(
                    f"E6-A07-MAST-LOCK-CONFIRMATION-{side_name.upper()}"
                ),
                pose=pose,
                same_brep_all_states=True,
                fixed_to_outer_sleeve=True,
                moves_with="A07_fixed_sleeve",
                mechanically_linked_to=f"A07_mast_lock_pin_{side_name}",
                structural_lock_credit=False,
                follows_shared_backrest_hinge_in_follow=True,
                production_certification_claimed=False,
                final_exterior_visible=True,
            )
        )
    lock_pins: list[SkinPart] = []
    for side_name in ("left", "right"):
        lock_pins.append(
            _new_part(
                f"A07_mast_lock_pin_{side_name}",
                posed(
                    masters[f"lock_pin_engaged_{side_name}"],
                    focus_translation=False,
                ),
                CHAMPAGNE,
                "hardened stainless positive-lock pin with dry-film coating",
                "A07",
                state,
                (
                    "The same radial pin is fully inserted only after the low "
                    "or Focus endpoint bore reaches Z=888; before any mast "
                    "translation it withdraws behind the fixed sleeve inner wall."
                ),
                physical_occurrence_id=(
                    f"WC-MAST-LOCK-PIN-{side_name.upper()}"
                ),
                pose=pose,
                same_brep_all_states=True,
                fixed_world_pose_through_ride_cafe_focus=True,
                follows_shared_backrest_hinge_in_follow=True,
                pin_axis="X",
                pin_center_y_mm=(
                    -A07_LOCK_PIN_Y_MM
                    if side_name == "left"
                    else A07_LOCK_PIN_Y_MM
                ),
                lock_station_z_mm=A07_LOCK_STATION_Z_MM,
                pin_diameter_mm=A07_LOCK_PIN_DIAMETER_MM,
                mating_bore_diameter_mm=A07_LOCK_BORE_DIAMETER_MM,
                diametral_running_clearance_mm=(
                    A07_LOCK_BORE_DIAMETER_MM - A07_LOCK_PIN_DIAMETER_MM
                ),
                current_lock_state=(
                    "engaged_focus_endpoint" if is_focus else "engaged_low_endpoint"
                ),
                commanded_motion_requires_full_retraction=True,
                retracted_x_range_mm=A07_LOCK_PIN_RETRACTED_X_MM,
                engaged_x_range_mm=A07_LOCK_PIN_ENGAGED_X_MM,
                pin_is_structural_not_confirmation_lens=True,
                redundant_pair_required=True,
                final_exterior_visible=False,
                production_certification_claimed=False,
            )
        )
    parts.extend(
        (
            fixed,
            moving,
            beam,
            sensor_window,
            shutter,
            bezel,
            microphone,
            environment,
            throat_gasket,
            *lock_pins,
            *lock_lenses,
            *inserts,
        )
    )


def _regularize_occupied_backrest_step_topology(
    state: str,
    parts: list[SkinPart],
) -> None:
    """Stabilise the shared Ride/Cafe upper backrest B-spline extremum."""

    if state not in {"ride", "cafe"}:
        return
    matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == "A06_backrest_weather_shell"
    ]
    if len(matches) != 1:
        raise KeyError(
            f"{state} STEP topology regularisation requires one A06 backrest shell; found {len(matches)}"
        )
    index, part = matches[0]
    if part.metadata.get("master_has_mast_cutout") is True:
        # The channel-integrated DFR5 master has already passed a direct STEP
        # round trip with zero face/edge drift.  Re-splitting it at z=1030
        # perturbs the rounded deployment throat and is neither necessary nor
        # topology preserving.
        metadata = dict(part.metadata)
        metadata.update(
            {
                "step_roundtrip_topology_regularization": (
                    "not_required_channel_master_direct_roundtrip_pass"
                ),
                "step_topology_regularization_relative_volume_delta": 0.0,
                "visible_surface_change_intended": False,
            }
        )
        parts[index] = replace(part, metadata=metadata)
        return
    bounds = part.shape.BoundingBox()
    margin = 10.0
    split_z = 1030.0
    x_size = bounds.xlen + 2.0 * margin
    y_size = bounds.ylen + 2.0 * margin
    lower_z_min = bounds.zmin - margin
    upper_z_max = bounds.zmax + margin
    lower_half_space = (
        cq.Workplane("XY")
        .box(x_size, y_size, split_z - lower_z_min)
        .translate(
            (
                (bounds.xmin + bounds.xmax) / 2.0,
                (bounds.ymin + bounds.ymax) / 2.0,
                (lower_z_min + split_z) / 2.0,
            )
        )
        .val()
    )
    upper_half_space = (
        cq.Workplane("XY")
        .box(x_size, y_size, upper_z_max - split_z)
        .translate(
            (
                (bounds.xmin + bounds.xmax) / 2.0,
                (bounds.ymin + bounds.ymax) / 2.0,
                (split_z + upper_z_max) / 2.0,
            )
        )
        .val()
    )
    regularized = _valid_single(
        part.shape.intersect(lower_half_space).fuse(
            part.shape.intersect(upper_half_space)
        ),
        f"{state} A06 backrest STEP topology regularisation",
    )
    relative_volume_delta = abs(
        float(part.shape.Volume()) - float(regularized.Volume())
    ) / max(abs(float(part.shape.Volume())), 1.0e-9)
    if relative_volume_delta > 1.0e-8:
        raise ValueError(
            f"{state} A06 backrest topology regularisation changed volume by "
            f"{relative_volume_delta:.9e}"
        )
    metadata = dict(part.metadata)
    metadata.update(
        {
            "step_roundtrip_topology_regularization": (
                "split_refuse_world_z_1030_mm"
            ),
            "step_topology_regularization_relative_volume_delta": (
                relative_volume_delta
            ),
            "visible_surface_change_intended": False,
        }
    )
    parts[index] = replace(part, shape=regularized, metadata=metadata)


def _coherent_material_language(state: str, parts: list[SkinPart]) -> None:
    """Apply one restrained, authentic retro-future CMF hierarchy.

    Natural materials are limited to the surfaces where touch, wear and ageing
    make them meaningful.  They are never simulated by printed grain on the
    primary weather shell, and metal is kept to narrow precision boundaries so
    the product does not become a material collage.
    """

    stainless_names = {
        "A05_left_hmi_precision_bezel",
        "A06_backrest_lock_witness_left",
        "A06_backrest_lock_witness_right",
        "A07_privacy_shutter_carriage_bezel",
        "A07_mast_lock_pin_confirmation_lens_left",
        "A07_mast_lock_pin_confirmation_lens_right",
    }
    for index, part in enumerate(parts):
        metadata = dict(part.metadata)
        replacement = part
        if part.name in {
            "A04_seat_cushion_contact_island",
            "A06_backrest_contact_panel",
        }:
            metadata.update(
                {
                    "authentic_natural_material": True,
                    "material_family": "semi_aniline_full_grain_leather",
                    "imitation_grain_or_printed_texture": False,
                    "replaceable_contact_cover": True,
                    "cleaning_and_ageing_sample_required": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=OXBLOOD_LEATHER,
                material=(
                    "replaceable deep-oxblood semi-aniline full-grain leather "
                    "over a compliant contact substrate"
                ),
                metadata=metadata,
            )
        elif part.name == "A05_right_removable_drive_pod":
            metadata.update(
                {
                    "authentic_natural_material": True,
                    "material_family": "full_grain_leather_hand_contact",
                    "imitation_grain_or_printed_texture": False,
                    "replaceable_wear_wrap": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=OXBLOOD_LEATHER,
                material="replaceable full-grain leather hand-contact wrap over the conserved control pod",
                metadata=metadata,
            )
        elif part.name.startswith("A09_table_top_skin_"):
            metadata.update(
                {
                    "authentic_natural_material": True,
                    "material_family": "natural_smoked_walnut_veneer",
                    "imitation_wood_print_or_film": False,
                    "book_matched_leaf_pair": True,
                    "low_sheen_repairable_hardwax_finish": True,
                    "balanced_backer_required": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=SMOKED_WALNUT,
                material=(
                    "book-matched natural smoked-walnut veneer over a balanced "
                    "lightweight core with a low-sheen repairable hardwax finish"
                ),
                metadata=metadata,
            )
        elif part.name.startswith("A09_table_edge_band_"):
            metadata.update(
                {
                    "authentic_natural_material": True,
                    "material_family": "solid_smoked_walnut_lipping",
                    "imitation_wood_print_or_film": False,
                    "continuous_visual_mass_with_table_top": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=SMOKED_WALNUT,
                material="solid smoked-walnut protective lipping matched to the natural veneer field",
                metadata=metadata,
            )
        elif part.name.startswith("A09_table_fold_flexure_"):
            metadata.pop("authentic_metal", None)
            metadata.pop("decorative_metal_area_minimised", None)
            metadata.update(
                {
                    "material_family": "replaceable_tpe_fold_flexure",
                    "elastomeric_flexible_fold_insert": True,
                    "only_flexible_material_crossing_fold_gap": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=TPE_DARK,
                material="recessed replaceable one-millimetre TPE fold-line insert",
                metadata=metadata,
            )
        elif (
            part.name.startswith("A09_table_underbelly_shell_")
            or part.name.startswith("A09_table_lift_boot_")
            or part.name.startswith("A09_table_lift_moving_stage_")
            or part.name.startswith("A09_cafe_underleaf_motion_belly_")
            or part.name.startswith("A09_focus_underleaf_motion_belly_")
            or part.name.startswith("A09_cafe_table_lift_base_socket_")
            or part.name.startswith("A09_focus_table_lift_base_socket_")
            or part.name.startswith("A09_focus_table_root_crown_")
            or part.name.startswith("A09_focus_internal_root_box_")
            or part.name.startswith("A09_focus_internal_nested_guide_stage_")
            or part.name.startswith("A09_focus_table_hidden_root_tongue_")
        ):
            metadata.update(
                {
                    "visual_role": "recessed_load_path_shadow_field",
                    "high_contrast_mechanism_stack_suppressed": True,
                    "material_family": "bead_blast_blackened_metal_or_dark_service_shell",
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=GRAPHITE_BROWN,
                material=(
                    "low-gloss blackened load-path finish that visually recedes "
                    "beneath the warm natural contact surfaces"
                ),
                metadata=metadata,
            )
        elif part.name.startswith("A03_wheel_end_motion_gaiter_"):
            metadata.update(
                {
                    "visual_role": "flush_colour_matched_wheel_motion_field",
                    "material_family": "warm_graphite_self_skinning_tpe",
                    "high_gloss_or_piano_black": False,
                    "perimeter_flange_hidden_behind_fixed_belt": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=GRAPHITE_BROWN,
                material=(
                    "warm-graphite colour-matched low-gloss self-skinning "
                    "TPE wheel-end diaphragm"
                ),
                metadata=metadata,
            )
        elif (
            part.name == "A01_front_nose_shell"
            or part.name.startswith("A02_main_side_shell_")
            or part.name.startswith("A03_continuous_wheel_belt_shell_")
            or part.name.startswith("A03_wheel_end_service_cap_")
            or part.name.startswith("A03_rocker_pivot_service_cap_")
            or part.name == "A08_footrest_root_monocoque"
            or part.name == "A10_rear_service_surround"
            or part.name == "A10_rear_flush_service_door_skin"
        ):
            metadata.update(
                {
                    "visual_role": "single_low_complete_core_volume",
                    "material_family": "warm_graphite_mineral_matte",
                    "high_gloss_or_piano_black": False,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=GRAPHITE_BROWN,
                material="warm low-gloss graphite mineral composite exterior field",
                metadata=metadata,
            )
        elif part.name == "A07_sensor_beam_shell":
            metadata.update(
                {
                    "visual_role": "thin_precision_observation_terminal",
                    "material_family": "lunar_stone_mineral_matte",
                    "headrest_or_decorative_spoiler_reading_prohibited": True,
                    "same_body_colour_all_states": True,
                    "follow_cofolded_terminal_not_an_added_cover": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=LUNAR_STONE,
                material="body-colour mineral-matte precision sensor-terminal shell",
                metadata=metadata,
            )
        elif part.name in stainless_names:
            metadata.update(
                {
                    "authentic_metal": True,
                    "material_family": "fine_brushed_stainless_steel",
                    "decorative_metal_area_minimised": True,
                    "production_certification_claimed": False,
                }
            )
            replacement = replace(
                part,
                color=SATIN_STAINLESS,
                material="fine-brushed stainless-steel precision boundary",
                metadata=metadata,
            )
        parts[index] = replacement


def apply_v8_final_appearance_closure(
    state: str,
    source_parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Apply the frozen final-appearance rules and return a new part list."""

    if state not in STATES:
        raise ValueError(f"Unsupported V8 final-appearance state: {state!r}")
    parts = list(source_parts)
    stages = (
        _wheel_upper_fairings,
        _continuous_wheel_belts,
        _front_nose_sightline_crown,
        _unified_front_perception_horizon,
        _front_waist_closure,
        _fixed_right_armrest,
        _integrated_upper_side_sails,
        _focus_drive_control_stow,
        _footrest_sightline_closure,
        _table_understructure_closure,
        _a09_instrument_spine_lift_columns,
        _a09_focus_a05_lift_clearance_corridors,
        _table_lift_base_sockets,
        _focus_table_root_crowns,
        _shared_backrest_master,
        _fixed_body_backrest_root_shoulders,
        _production_backrest_hinge_hardware,
        _production_mast_layout,
        _regularize_occupied_backrest_step_topology,
        _coherent_material_language,
    )
    trace_stages = os.environ.get("WORKCORE_CAD_STAGE_TRACE") == "1"
    for stage in stages:
        if trace_stages:
            print(
                f"[v8-appearance:{state}] {stage.__name__} start",
                flush=True,
            )
        stage(state, parts)
        if trace_stages:
            print(
                f"[v8-appearance:{state}] {stage.__name__} complete "
                f"({len(parts)} parts)",
                flush=True,
            )

    errors = validate_parts(parts)
    if errors:
        raise ValueError(
            f"V8 final-appearance closure invalid for {state}: " + "; ".join(errors)
        )
    return parts
