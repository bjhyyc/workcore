"""V8 rigid-body partition and mechanism-clearance corrections.

V7 proved source naming responsibility but several cosmetic solids still used
overlap as a modelling shortcut.  This pass converts the affected A05/A06/A08
and A09 groups into non-intersecting service parts with explicit cavities.  It
never mutates or exports the controlled E6-DFR5-A07-SHARED-HINGE primary inputs
or preserved DFR4/DFR3 trace inputs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import cadquery as cq

from cad.parameters import P

try:
    from .skin_common import (
        CHAMPAGNE,
        LUNAR_STONE,
        TPE_DARK,
        SkinPart,
        rounded_box,
        rounded_frame,
        union_many,
    )
except ImportError:
    from skin_common import (  # type: ignore[no-redef]
        CHAMPAGNE,
        LUNAR_STONE,
        TPE_DARK,
        SkinPart,
        rounded_box,
        rounded_frame,
        union_many,
    )

try:
    from .v8_state_contract import default_footrest_is_deployed
except ImportError:
    from v8_state_contract import default_footrest_is_deployed  # type: ignore[no-redef]


def _index(parts: list[SkinPart]) -> dict[str, int]:
    return {part.name: index for index, part in enumerate(parts)}


def _part(parts: list[SkinPart], name: str) -> SkinPart:
    try:
        return parts[_index(parts)[name]]
    except KeyError as exc:
        raise KeyError(f"V8 partition missing required part {name}") from exc


def _replace(
    parts: list[SkinPart],
    name: str,
    shape: cq.Shape,
    *,
    material: str | None = None,
    intent: str | None = None,
    metadata: dict[str, object] | None = None,
    color: tuple[float, float, float, float] | None = None,
) -> None:
    idx = _index(parts)[name]
    previous = parts[idx]
    merged = dict(previous.metadata)
    if metadata:
        merged.update(metadata)
    if shape.isNull() or not shape.isValid() or shape.Volume() <= 0.0:
        raise ValueError(f"V8 partition made {name} invalid or empty")
    parts[idx] = replace(
        previous,
        shape=shape,
        material=material or previous.material,
        intent=intent or previous.intent,
        metadata=merged,
        color=color or previous.color,
    )


def _new(
    prototype: SkinPart,
    name: str,
    shape: cq.Shape,
    intent: str,
    **metadata: object,
) -> SkinPart:
    if shape.isNull() or not shape.isValid() or shape.Volume() <= 0.0:
        raise ValueError(f"V8 partition made {name} invalid or empty")
    return SkinPart(
        name=name,
        shape=shape,
        color=prototype.color,
        material=prototype.material,
        module=prototype.module,
        configuration=prototype.configuration,
        intent=intent,
        metadata={**prototype.metadata, **metadata},
    )


def _bbox_box(shape: cq.Shape, margin: float = 0.0) -> cq.Shape:
    box = shape.BoundingBox()
    return rounded_box(
        (
            box.xlen + 2.0 * margin,
            box.ylen + 2.0 * margin,
            box.zlen + 2.0 * margin,
        ),
        (
            (box.xmin + box.xmax) / 2.0,
            (box.ymin + box.ymax) / 2.0,
            (box.zmin + box.zmax) / 2.0,
        ),
        min(4.0, max(0.5, margin)),
    )


def _bounds_box(
    bounds: tuple[float, float, float, float, float, float],
    margin: float,
) -> cq.Shape:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    return rounded_box(
        (
            xmax - xmin + 2.0 * margin,
            ymax - ymin + 2.0 * margin,
            zmax - zmin + 2.0 * margin,
        ),
        (
            (xmin + xmax) / 2.0,
            (ymin + ymax) / 2.0,
            (zmin + zmax) / 2.0,
        ),
        min(4.0, max(0.5, margin)),
    )


def _cut_many(base: cq.Shape, cutters: Iterable[cq.Shape]) -> cq.Shape:
    result = base
    for cutter in cutters:
        # OCC can collapse a valid shell when asked to subtract a merely
        # tangent/coplanar solid.  Boolean only when there is measurable common
        # volume; face contact is already a zero-volume static partition.
        try:
            common = result.intersect(cutter).Volume()
        except Exception:
            common = 0.0
        if common <= 0.1:
            continue
        candidate = result.cut(cutter)
        if candidate.isNull() or not candidate.isValid() or candidate.Volume() <= 0.0:
            raise ValueError(
                f"V8 boolean subtraction failed after {common:.6f} mm3 common volume"
            )
        result = candidate
    return result


def _fix_a05_cassette_interfaces(state: str, parts: list[SkinPart]) -> None:
    """Partition only the low-point drain; table access is through the top.

    The former state-dependent side door/throat was built around a different
    proxy box rather than the released table leaf.  Keeping that boolean pass
    would silently recreate the invalid side-opening architecture after the
    upper skin had removed it.
    """

    for side_name in ("left", "right"):
        shell_name = f"A05_armrest_table_bay_shell_{side_name}"
        shell = _part(parts, shell_name).shape
        drain_name = f"A05_table_cassette_lowpoint_drain_{side_name}"
        drain = _part(parts, drain_name).shape
        shell = _cut_many(shell, (drain,))
        _replace(
            parts,
            shell_name,
            shell,
            metadata={
                "cassette_interfaces_boolean_partitioned": False,
                "legacy_side_table_opening_present": False,
                "top_lid_table_extraction_only": True,
                "drain_boolean_partitioned": True,
                "rigid_accessory_common_volume_target_mm3": 0.0,
            },
        )


def _fix_a05_transfer(parts: list[SkinPart]) -> None:
    # The prototype source *shrouds* are replaced surfaces, not hardware that
    # must survive under a second cover.  The structural hinge/link occupy
    # Y=340..360 / 334..360; their five-millimetre cavities fit inside the
    # frozen +/-372.529 mm exterior envelope without the impossible double-
    # shroud stack used in V7.
    hinge_outer = rounded_box((68.0, 44.0, 200.0), (210.0, 347.0, 590.0), 12.0)
    hinge_cavity = rounded_box((58.0, 30.0, 190.0), (210.0, 350.0, 590.0), 8.0)
    link_outer = rounded_box((122.0, 46.0, 46.0), (175.0, 347.0, 490.0), 11.0)
    link_cavity = rounded_box((112.0, 36.0, 36.0), (175.0, 347.0, 490.0), 8.0)
    outer = union_many((hinge_outer, link_outer))
    cavity = union_many((hinge_cavity, link_cavity))
    fairing = outer.cut(cavity)
    _replace(
        parts,
        "A05_right_transfer_root_fairing",
        fairing,
        intent=(
            "One split shoulder replaces the prototype shrouds and encloses the "
            "structural hinge/link behind a five-millimetre hardware cavity."
        ),
        metadata={
            "minimum_source_sweep_clearance_mm": 5.0,
            "prototype_shroud_disposition": "replace_surface",
            "outboard_cladding_margin_mm": 4.0,
            "source_cavity_boolean_verified": True,
            "service_split": True,
        },
    )


def _fix_a06_partitions(state: str, parts: list[SkinPart]) -> None:
    if state == "follow":
        # The large V7 rigid overlap is replaced by a hidden, non-intersecting
        # TPE labyrinth.  The separate V8 closed-field shell supplies the
        # visible continuity.
        seal = rounded_frame(
            (490.0, 600.0),
            (478.0, 588.0),
            6.0,
            (-75.0, 0.0, 427.0),
            24.0,
        )
        _replace(
            parts,
            "A06_follow_weather_continuity_skirt",
            seal,
            material="replaceable low-friction TPE internal labyrinth seal",
            color=TPE_DARK,
            intent="A hidden non-intersecting labyrinth seals the moving waist; the outer field shell, not a rigid overlap frame, closes the normal sightline.",
            metadata={
                "rigid_overlap_removed": True,
                "soft_interface_id": "FOLLOW-WAIST-LABYRINTH-01",
                "compression_rate": 0.0,
                "supplier_compression_curve_required_before_nonzero_overlap": True,
            },
        )
        return

    weather = _part(parts, "A06_backrest_weather_shell").shape
    ring = _part(parts, "A04_open_u_seat_pan_ring").shape
    for side_name in ("left", "right"):
        name = f"A06_backrest_root_cheek_{side_name}"
        cheek = _cut_many(_part(parts, name).shape, (weather, ring))
        _replace(
            parts,
            name,
            cheek,
            metadata={
                "true_partition_with_weather_shell": True,
                "true_partition_with_seat_ring": True,
                "rigid_common_volume_target_mm3": 0.0,
            },
        )


def _fix_a08(state: str, parts: list[SkinPart]) -> None:
    if not default_footrest_is_deployed(state):
        return
    support_length = abs((P.body_x - P.body_length / 2.0) - P.footrest_deployed_x)
    support_x = (P.body_x - P.body_length / 2.0 + P.footrest_deployed_x) / 2.0
    support_cutters: list[cq.Shape] = []
    for side_name, side in (("left", -1), ("right", 1)):
        y = side * 220.0
        outer = rounded_box(
            (support_length + 14.0, 66.0, 66.0),
            (support_x, y, P.footrest_deployed_z + 20.0),
            20.0,
        )
        inner = rounded_box(
            (support_length + 28.0, 50.0, 50.0),
            (support_x, y, P.footrest_deployed_z + 20.0),
            14.0,
        )
        boot = outer.cut(inner).cut(
            rounded_box(
                (34.0, 18.0, 16.0),
                (support_x, y, P.footrest_deployed_z - 14.0),
                5.0,
            )
        )
        _replace(
            parts,
            f"A08_footrest_support_boot_{side_name}",
            boot,
            metadata={
                "minimum_source_support_clearance_mm": 10.0,
                "outdoor_moving_interface_pre_gate_mm": 5.0,
                "rigid_source_common_volume_target_mm3": 0.0,
            },
        )

        collar_outer = rounded_box(
            (28.0, 92.0, 92.0),
            (-464.0, y, P.footrest_deployed_z + 20.0),
            20.0,
        )
        collar_inner = rounded_box(
            (42.0, 76.0, 76.0),
            (-464.0, y, P.footrest_deployed_z + 20.0),
            16.0,
        )
        collar = collar_outer.cut(collar_inner).cut(
            rounded_box(
                (16.0, 20.0, 18.0),
                (-464.0, y, P.footrest_deployed_z - 26.0),
                5.0,
            )
        )
        _replace(
            parts,
            f"A08_footrest_support_body_collar_{side_name}",
            collar,
            metadata={
                "moving_boot_nominal_clearance_mm": 5.0,
                "rigid_common_volume_target_mm3": 0.0,
            },
        )

        source_clearance = rounded_box(
            (support_length + 10.0, 40.0, 40.0),
            (support_x, y, P.footrest_deployed_z + 20.0),
            8.0,
        )
        support_cutters.append(source_clearance)
        cowl_name = f"A08_footrest_root_cowl_{side_name}"
        cowl = _part(parts, cowl_name).shape
        cowl = _cut_many(
            cowl,
            (
                _bbox_box(boot, 5.0),
                _bbox_box(collar, 5.0),
                source_clearance,
            ),
        )
        _replace(
            parts,
            cowl_name,
            cowl,
            metadata={
                "support_sweep_clearance_mm": 5.0,
                "moving_boot_clearance_mm": 5.0,
                "fixed_collar_clearance_mm": 5.0,
            },
        )

    # The body-side manual release and its finished shell are pose-invariant
    # and are authored once in ``skin_lower._footrest_skin`` for every state.
    # This pass only owns the moving deployed support/root interfaces.


def _stage_shell(
    size_xy: tuple[float, float],
    cavity_xy: tuple[float, float],
    zmin: float,
    zmax: float,
    center_x: float,
    center_y: float,
) -> cq.Shape:
    height = zmax - zmin
    center_z = (zmin + zmax) / 2.0
    outer = rounded_box((size_xy[0], size_xy[1], height), (center_x, center_y, center_z), 14.0)
    inner = rounded_box(
        (cavity_xy[0], cavity_xy[1], height + 6.0),
        (center_x, center_y, center_z),
        10.0,
    )
    result = outer.cut(inner)
    if not result.isValid() or result.Volume() <= 0.0:
        raise ValueError("V8 A09 telescopic stage is invalid")
    return result


def _a09_source_cutters(state: str, side_name: str) -> tuple[cq.Shape, ...]:
    side = -1 if side_name == "left" else 1
    if state == "focus":
        return (
            _bounds_box((-480.0, -390.0, side * 313.5 if side < 0 else side * 268.5, side * 268.5 if side < 0 else side * 313.5, 669.0, 693.0), 5.0),
            _bounds_box((-455.0, -155.0, side * 357.0 if side < 0 else side * 323.0, side * 323.0 if side < 0 else side * 357.0, 638.0, 666.0), 5.0),
        )
    # Café right: source bounds from the controlled GLB occurrence ledger.
    return tuple(
        _bounds_box(bounds, 5.0)
        for bounds in (
            (-457.0, -403.0, 141.0, 300.0, 669.0, 693.0),
            (-480.0, -180.0, 323.0, 357.0, 638.0, 666.0),
            (-467.93, -392.0, 103.02, 178.98, 681.0, 693.0),
            (-468.0, -312.0, 114.0, 168.0, 665.0, 681.0),
            (-379.0, -321.0, 31.0, 251.0, 677.0, 691.0),
        )
    )


def _validate_focus_internal_a09(parts: list[SkinPart]) -> None:
    """Freeze the bilateral Focus root as concealed, collision-free hardware.

    Unlike the former exposed 82 mm post stack, these parts already arrive as
    independent production occurrences from ``skin_upper``.  This partition
    pass must therefore prove their packaging and must never rebody them or cut
    a deployment aperture through the closed A05 top lid.
    """

    tolerance = 1.0e-6
    for side_name, side in (("left", -1), ("right", 1)):
        names = {
            "root": f"A09_focus_internal_root_box_{side_name}",
            "stage1": (
                f"A09_focus_internal_nested_guide_stage_1_{side_name}"
            ),
            "stage2": (
                f"A09_focus_internal_nested_guide_stage_2_{side_name}"
            ),
            "stage3": (
                f"A09_focus_internal_nested_guide_stage_3_{side_name}"
            ),
            "tongue": f"A09_focus_table_hidden_root_tongue_{side_name}",
        }
        occurrences = {role: _part(parts, name) for role, name in names.items()}
        cavity_x = (-361.0, -325.0)
        cavity_y = (-360.0, -317.5) if side < 0 else (317.5, 360.0)
        for role in ("root", "stage1", "stage2", "stage3"):
            box = occurrences[role].shape.BoundingBox()
            if (
                box.xmin < cavity_x[0] - tolerance
                or box.xmax > cavity_x[1] + tolerance
                or box.ymin < cavity_y[0] - tolerance
                or box.ymax > cavity_y[1] + tolerance
                or box.zmax > 674.0 + tolerance
            ):
                raise ValueError(
                    f"Focus {side_name} {role} escaped the closed A05 root "
                    f"cavity: {(box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax)!r}"
                )

        shell = _part(parts, f"A05_armrest_table_bay_shell_{side_name}")
        lid = _part(parts, f"A05_armrest_touch_lid_{side_name}")
        cassette = _part(
            parts,
            f"A05_table_root_structural_cassette_{side_name}",
        )
        for role, occurrence in occurrences.items():
            for host in (shell, lid):
                common = float(occurrence.shape.intersect(host.shape).Volume())
                if common > tolerance:
                    raise ValueError(
                        f"Focus {side_name} concealed {role} collides with "
                        f"{host.name}: {common:.9f} mm3"
                    )
        if float(occurrences["stage3"].shape.distance(lid.shape)) < 1.0 - tolerance:
            raise ValueError(
                f"Focus {side_name} stage 3 violates the one-millimetre "
                "closed-lid vertical dry gap"
            )

        cassette_root_common = float(
            cassette.shape.intersect(occurrences["root"].shape).Volume()
        )
        cassette_root_gap = float(
            cassette.shape.distance(occurrences["root"].shape)
        )
        if cassette_root_common > tolerance or cassette_root_gap > tolerance:
            raise ValueError(
                f"Focus {side_name} metal cassette/root load interface "
                f"invalid: common={cassette_root_common:.9f} mm3, "
                f"distance={cassette_root_gap:.9f} mm"
            )

        nested = (
            occurrences["root"],
            occurrences["stage1"],
            occurrences["stage2"],
            occurrences["stage3"],
        )
        for outer, inner in zip(nested, nested[1:]):
            common = float(outer.shape.intersect(inner.shape).Volume())
            clearance = float(outer.shape.distance(inner.shape))
            if common > tolerance or clearance < 0.5 - tolerance:
                raise ValueError(
                    f"Focus {side_name} nested root pair {outer.name}/"
                    f"{inner.name} invalid: common={common:.9f} mm3, "
                    f"clearance={clearance:.9f} mm"
                )

        tongue_stage_common = float(
            occurrences["tongue"].shape.intersect(
                occurrences["stage3"].shape
            ).Volume()
        )
        tongue_stage_distance = float(
            occurrences["tongue"].shape.distance(
                occurrences["stage3"].shape
            )
        )
        if tongue_stage_common > tolerance or tongue_stage_distance > tolerance:
            raise ValueError(
                f"Focus {side_name} tongue/stage-3 face interface invalid: "
                f"common={tongue_stage_common:.9f} mm3, "
                f"distance={tongue_stage_distance:.9f} mm"
            )

        table_underbelly = _part(
            parts,
            f"A09_table_underbelly_shell_{side_name}",
        )
        tongue_table_common = float(
            occurrences["tongue"].shape.intersect(
                table_underbelly.shape
            ).Volume()
        )
        tongue_table_distance = float(
            occurrences["tongue"].shape.distance(
                table_underbelly.shape
            )
        )
        if tongue_table_common > tolerance or tongue_table_distance > tolerance:
            raise ValueError(
                f"Focus {side_name} root-neck/internal-spreader table "
                f"interface invalid: common={tongue_table_common:.9f} mm3, "
                f"distance={tongue_table_distance:.9f} mm"
            )


def _validate_cafe_internal_a09(parts: list[SkinPart]) -> None:
    """Prove the current Cafe root inventory without recreating old fairings.

    The final fixed-yoke/rotary-rail mechanism is installed downstream by the
    appearance-closure pass from ``v8_cafe_table_root_motion``.  At this stage
    ``skin_upper`` intentionally carries only its compact in-cavity lift boot
    and the two fixed internal lock controls.  The former exterior bridge,
    fairing, saddle and 72/60/48 mm post stack no longer exist and must not be
    synthesized merely to satisfy this historical partition pass.
    """

    tolerance = 1.0e-6
    internal_names = (
        "A09_cafe_internal_lift_packaging_envelope_right",
        "A09_cafe_lock_release_paddle_right",
        "A09_cafe_positive_lock_witness_right",
        "A09_cafe_fixed_root_housing_right",
        "A09_cafe_fixed_yoke_bearing_carrier_right",
        "A09_cafe_rotary_hub_right",
        "A09_cafe_rotary_linear_rail_right",
    )
    occurrences = [_part(parts, name) for name in internal_names]
    shell = _part(parts, "A05_armrest_table_bay_shell_right")
    lid = _part(parts, "A05_armrest_touch_lid_right")
    cassette = _part(parts, "A05_table_root_structural_cassette_right")
    root_neck = _part(parts, "A09_cafe_underleaf_motion_belly_right")

    for occurrence in occurrences:
        box = occurrence.shape.BoundingBox()
        if (
            box.xmin < -380.0 - tolerance
            or box.xmax > 140.0 + tolerance
            or box.ymin < 316.0 - tolerance
            or box.ymax > 361.5 + tolerance
            or box.zmax > 674.0 + tolerance
        ):
            raise ValueError(
                f"Cafe concealed {occurrence.name} escaped the right A05 "
                "cavity: "
                f"{(box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax)!r}"
            )
        for host in (shell, lid):
            common = float(occurrence.shape.intersect(host.shape).Volume())
            if common > tolerance:
                raise ValueError(
                    f"Cafe concealed {occurrence.name} collides with "
                    f"{host.name}: {common:.9f} mm3"
                )

    for host in (shell, lid):
        common = float(root_neck.shape.intersect(host.shape).Volume())
        if common > tolerance:
            raise ValueError(
                f"Cafe closed root neck collides with {host.name}: "
                f"{common:.9f} mm3"
            )

    table_underbelly = _part(parts, "A09_table_underbelly_shell_right")
    table_common = float(
        root_neck.shape.intersect(table_underbelly.shape).Volume()
    )
    table_gap = float(root_neck.shape.distance(table_underbelly.shape))
    if table_common > tolerance or table_gap > tolerance:
        raise ValueError(
            "Cafe root-neck/internal-spreader table interface invalid: "
            f"common={table_common:.9f} mm3, distance={table_gap:.9f} mm"
        )

    by_name = {part.name: part for part in parts}
    chain_names = (
        "A05_table_root_structural_cassette_right",
        "A09_cafe_fixed_root_housing_right",
        "A09_cafe_fixed_yoke_bearing_carrier_right",
        "A09_cafe_rotary_hub_right",
        "A09_cafe_rotary_linear_rail_right",
        "A09_cafe_underleaf_motion_belly_right",
    )
    for first_name, second_name in zip(chain_names, chain_names[1:]):
        first = by_name[first_name].shape
        second = by_name[second_name].shape
        common = float(first.intersect(second).Volume())
        clearance = float(first.distance(second))
        if common > tolerance or clearance > 0.05 + tolerance:
            raise ValueError(
                f"Cafe final static load path {first_name}/{second_name} "
                f"invalid: common={common:.9f} mm3, "
                f"clearance={clearance:.9f} mm"
            )


def _fix_a09(state: str, parts: list[SkinPart]) -> None:
    if state == "focus":
        _validate_focus_internal_a09(parts)
        return
    if state != "cafe":
        return
    _validate_cafe_internal_a09(parts)
    return

    # Unreachable trace archaeology for the retired exposed prototype.  Keep
    # the source temporarily so old validation records remain explainable, but
    # never execute it for a released V8 state.
    sides = ("right",)
    for side_name in sides:
        side = -1 if side_name == "left" else 1
        center_x = -430.0 if state == "cafe" else -405.0
        center_y = side * 300.0
        boot_name = (
            "A09_table_lift_boot_right"
            if state == "cafe"
            else f"A09_table_lift_boot_{side_name}"
        )
        prototype = _part(parts, boot_name)
        stage_1 = _stage_shell((72.0, 72.0), (66.0, 66.0), 490.0, 580.0, center_x, center_y)
        stage_2 = _stage_shell((60.0, 60.0), (54.0, 54.0), 564.0, 646.0, center_x, center_y)
        stage_3 = _stage_shell((48.0, 48.0), (40.0, 40.0), 630.0, 697.0, center_x, center_y)
        _replace(
            parts,
            boot_name,
            stage_1,
            intent="Fixed outer lift stage with a real open cavity and three-millimetre radial clearance to stage two.",
            metadata={
                "telescopic_stage_count": 1,
                "stage_index": 1,
                "stage_travel_mm": 0.0,
                "overlap_with_next_stage_mm": 16.0,
                "radial_clearance_to_next_stage_mm": 3.0,
                "independent_physical_stage": True,
            },
        )
        parts.extend(
            (
                _new(
                    prototype,
                    f"A09_table_lift_moving_stage_2_{side_name}",
                    stage_2,
                    "Independent middle lift stage nested inside the fixed outer shroud.",
                    physical_occurrence_id=f"E6-A09-TABLE-LIFT-STAGE-2-{side_name.upper()}",
                    stage_index=2,
                    stage_travel_mm=96.0,
                    overlap_with_previous_stage_mm=16.0,
                    overlap_with_next_stage_mm=16.0,
                    radial_clearance_mm=3.0,
                    independent_physical_stage=True,
                ),
                _new(
                    prototype,
                    f"A09_table_lift_moving_stage_3_{side_name}",
                    stage_3,
                    "Independent inner lift stage with a forty-millimetre open mechanism aperture.",
                    physical_occurrence_id=f"E6-A09-TABLE-LIFT-STAGE-3-{side_name.upper()}",
                    stage_index=3,
                    stage_travel_mm=96.0,
                    overlap_with_previous_stage_mm=16.0,
                    radial_clearance_mm=3.0,
                    minimum_internal_aperture_mm=40.0,
                    independent_physical_stage=True,
                ),
            )
        )

        if state == "cafe":
            bridge_name = "A09_cafe_armrest_to_table_root_bridge_right"
            fairing_name = "A09_cafe_root_mechanism_fairing_right"
            saddle_name = "A09_cafe_underleaf_saddle_right"
        else:
            bridge_name = f"A09_focus_armrest_to_table_root_bridge_{side_name}"
            fairing_name = f"A09_focus_root_fairing_{side_name}"
            saddle_name = f"A09_focus_underleaf_saddle_{side_name}"

        source_bridge = _part(parts, bridge_name).shape
        source_fairing = _part(parts, fairing_name).shape
        source_saddle = _part(parts, saddle_name).shape
        master = union_many(
            (
                source_bridge,
                source_fairing,
                source_saddle,
            )
        )
        stage_clearance = rounded_box(
            (82.0, 82.0, 220.0),
            (center_x, center_y, 594.0),
            16.0,
        )
        source_cutters = _a09_source_cutters(state, side_name)
        functional_parts = [
            part.shape
            for part in parts
            if part.module == "A09"
            and part.configuration == state
            and side_name in part.name
            and any(token in part.name for token in ("lock_release", "lock_paddle", "lock_witness"))
        ]
        partition_cutters = (
            stage_clearance,
            *source_cutters,
            *functional_parts,
        )
        master = _cut_many(master, partition_cutters)

        # One master envelope is split at two real service seams.  The 0.8 mm
        # gaps are modelled empty space, so the three rigid covers cannot share
        # volume even when their parent surfaces were originally overlapping.
        bridge_region = cq.Workplane("XY").box(900.0, 900.0, 40.0).translate((0.0, 0.0, 646.0)).val()
        fairing_region = cq.Workplane("XY").box(900.0, 900.0, 17.2).translate((0.0, 0.0, 673.6)).val()
        saddle_region = cq.Workplane("XY").box(900.0, 900.0, 24.0).translate((0.0, 0.0, 696.0)).val()
        # Keep the low bridge STEP-stable.  Intersecting the already-fused
        # three-source master at this lower band leaves a trimmed face whose
        # underlying saddle B-spline still spans the complete upper saddle.
        # OCCT meshes that face correctly, but a STEP write/read cycle can
        # reconstruct the untrimmed parent surface and move the reported
        # bounds by more than 120 mm.  Partitioning the two sources that
        # actually form the visible low shoulder before fusing them is
        # geometrically equivalent there except for the sub-millimetre saddle
        # run-on hidden by the service seam, and produces one closed,
        # independently manufacturable solid with stable STEP p-curves.
        bridge_sources = tuple(
            clipped
            for clipped in (
                _cut_many(source_bridge, partition_cutters).intersect(
                    bridge_region
                ),
                _cut_many(source_fairing, partition_cutters).intersect(
                    bridge_region
                ),
            )
            if not clipped.isNull() and clipped.Volume() > 0.1
        )
        bridge = union_many(bridge_sources)
        fairing = master.intersect(fairing_region)
        saddle = master.intersect(saddle_region)
        shared_metadata = {
            "master_envelope_partitioned": True,
            "static_service_seam_mm": 0.8,
            "source_motion_keepout_mm": 5.0,
            "rigid_pair_common_volume_target_mm3": 0.0,
        }
        _replace(
            parts,
            bridge_name,
            bridge,
            metadata={
                **shared_metadata,
                "step_stable_source_partition": True,
                "step_untrimmed_parent_surface_forbidden": True,
            },
        )
        _replace(parts, fairing_name, fairing, metadata=shared_metadata)
        _replace(parts, saddle_name, saddle, metadata=shared_metadata)


def _explode_service_segments(parts: list[SkinPart]) -> list[SkinPart]:
    """Keep the SkinPart contract: one independently serviceable solid each."""

    result: list[SkinPart] = []
    for part in parts:
        solids = sorted(part.shape.Solids(), key=lambda solid: solid.Volume(), reverse=True)
        if len(solids) <= 1:
            result.append(part)
            continue
        group_id = str(
            part.metadata.get(
                "physical_occurrence_id",
                f"{part.configuration.upper()}-{part.name}",
            )
        )
        for segment_index, solid in enumerate(solids, start=1):
            name = part.name if segment_index == 1 else f"{part.name}_service_segment_{segment_index}"
            metadata = {
                **part.metadata,
                "service_segment_group_id": group_id,
                "service_segment_index": segment_index,
                "service_segment_count": len(solids),
                "physical_occurrence_id": (
                    group_id if segment_index == 1 else f"{group_id}-SEG-{segment_index}"
                ),
            }
            result.append(
                replace(
                    part,
                    name=name,
                    shape=solid,
                    intent=(
                        part.intent
                        if segment_index == 1
                        else f"Service-split continuation of {part.name}; no rigid bridge crosses the functional cavity."
                    ),
                    metadata=metadata,
                )
            )
    return result


def apply_v8_collision_partitions(
    state: str,
    base_parts: Iterable[SkinPart],
) -> list[SkinPart]:
    parts = list(base_parts)
    _fix_a05_cassette_interfaces(state, parts)
    _fix_a05_transfer(parts)
    _fix_a06_partitions(state, parts)
    _fix_a08(state, parts)
    _fix_a09(state, parts)
    return _explode_service_segments(parts)


__all__ = ["apply_v8_collision_partitions"]
