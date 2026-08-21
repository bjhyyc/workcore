"""V8 solid-functional corrections layered over the V7/V8 exterior parts.

The controlled STEP assemblies and the V7 release are read-only.  This module
only replaces the shapes of named skin proxies (with ``dataclasses.replace``)
and adds two independently serviceable, non-conductive UWB bezel parts.

Coordinate convention (mm): -X front, +X rear, +Y right, -Y left, +Z up.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import cadquery as cq

from cad.parameters import P

try:
    from .skin_common import (
        SMOKED_UMBER,
        SkinPart,
        cut_many,
        rounded_box,
        rounded_rect_prism,
    )
except ImportError:
    from skin_common import (  # type: ignore[no-redef]
        SMOKED_UMBER,
        SkinPart,
        cut_many,
        rounded_box,
        rounded_rect_prism,
    )

STATES = {"follow", "ride", "cafe", "focus"}
_BOOLEAN_TOLERANCE_MM3 = 1.0e-5

# A04 released RF hardpoints.  The source radomes occupy X=-135..-15,
# Z=390..410 and end at Y=-356 / +356 on the inboard faces.  The final radomes
# end at Y=-367 / +367 on the outboard faces.  One millimetre of axial and two
# millimetres of X/Z perimeter clearance turn that complete span into a real
# aperture instead of the former ~9,120 mm3 magnesium-door obstruction.
_A04_RF_APERTURE_XZ_MM = (124.0, 24.0)
_A04_RF_CORRIDOR_Y_MM = 13.0
_A04_RF_CORRIDOR_CENTER_ABS_Y_MM = 361.5
_A04_RF_CENTER_XZ_MM = (-75.0, 400.0)

# A10 access datums already used by the V7 release/pull components.
_A10_RELEASE_CENTER_YZ_MM = (120.0, 330.0)
_A10_RELEASE_APERTURE_DIAMETER_MM = 37.0
_A10_PULL_CENTER_YZ_MM = (-80.0, 330.0)
_A10_PULL_APERTURE_YZ_MM = (72.0, 32.0)

# A08 uses three released 12 x 96 mm through-slots.  Their cutter is a true
# 2.5D rounded rectangle with flat Z ends, not an all-edge-fillet capsule that
# narrows again at the platform faces and can retain hidden water-catching
# slivers.
_A08_DRAIN_SLOT_XY_MM = (12.0, 96.0)
_A08_DRAIN_SLOT_X_OFFSETS_MM = (-50.0, 0.0, 50.0)


def _require_shape(shape: cq.Shape, label: str) -> None:
    """Reject null, invalid or non-volumetric Boolean results immediately."""

    if shape.isNull():
        raise ValueError(f"{label} resolved to a null shape")
    if not shape.isValid():
        raise ValueError(f"{label} resolved to an invalid shape")
    if shape.Volume() <= 0.0:
        raise ValueError(f"{label} has non-positive volume")
    if not shape.Solids():
        raise ValueError(f"{label} contains no solid")


def _intersection_volume(first: cq.Shape, second: cq.Shape) -> float:
    return float(first.intersect(second).Volume())


def _find_index(parts: list[SkinPart], name: str) -> int:
    matches = [index for index, part in enumerate(parts) if part.name == name]
    if len(matches) != 1:
        raise KeyError(
            f"V8 functional fix expected exactly one {name!r}, found {len(matches)}"
        )
    return matches[0]


def _replace_shape(parts: list[SkinPart], name: str, shape: cq.Shape) -> SkinPart:
    """Replace only ``shape``; identity and the original metadata object stay."""

    _require_shape(shape, name)
    index = _find_index(parts, name)
    original = parts[index]
    replacement = replace(original, shape=shape)
    if replacement.name != original.name or replacement.metadata is not original.metadata:
        raise AssertionError(f"{name} identity/metadata changed during shape replacement")
    parts[index] = replacement
    return replacement


def _rounded_panel_xz(
    size_xz: tuple[float, float],
    thickness_y: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    """Small Y-thickness rounded panel used for the replaceable RF bezel."""

    sx, sz = size_xz
    panel = cq.Workplane("XZ").rect(sx, sz).extrude(thickness_y / 2.0, both=True)
    try:
        panel = panel.edges("|Y").fillet(min(radius, sx * 0.45, sz * 0.45))
    except Exception:
        # The bezel remains a valid prismatic service part if OCC rejects a
        # cosmetic edge fillet; aperture dimensions remain unchanged.
        pass
    result = panel.translate(center).val()
    if not isinstance(result, cq.Shape):
        raise TypeError("A04 UWB bezel panel did not resolve to a CadQuery shape")
    return result


def _uwb_bezel(state: str, side_name: str, side: int) -> SkinPart:
    """Return a 4 mm radial, replaceable non-conductive aperture bezel."""

    center = (-75.0, side * 368.0, 400.0)
    outer = _rounded_panel_xz((132.0, 32.0), 2.0, center, 7.0)
    inner = _rounded_panel_xz(_A04_RF_APERTURE_XZ_MM, 4.0, center, 6.0)
    bezel = outer.cut(inner)
    _require_shape(bezel, f"A04 {side_name} replaceable UWB bezel")
    if len(bezel.Solids()) != 1:
        raise ValueError(f"A04 {side_name} UWB bezel must remain one service part")
    return SkinPart(
        name=f"A04_side_uwb_replaceable_bezel_{side_name}",
        shape=bezel,
        color=SMOKED_UMBER,
        material="replaceable non-conductive RF-grade polycarbonate bezel",
        module="A04",
        configuration=state,
        intent=(
            "A removable non-conductive precision frame finishes the real side-UWB "
            "through-aperture without restoring conductive material in the RF corridor."
        ),
        metadata={
            "physical_occurrence_id": (
                f"E6-A04-SIDE-UWB-REPLACEABLE-BEZEL-{side_name.upper()}"
            ),
            "functional_opening": "side_uwb_rf_window",
            "non_conductive": True,
            "replaceable": True,
            "door_aperture_xz_mm": _A04_RF_APERTURE_XZ_MM,
            "source_to_final_corridor_y_mm": _A04_RF_CORRIDOR_Y_MM,
            "radial_bezel_width_mm": 4.0,
        },
    )


def _upsert_new_part(parts: list[SkinPart], new_part: SkinPart) -> None:
    """Append on first application; keep metadata stable on repeat application."""

    matches = [index for index, part in enumerate(parts) if part.name == new_part.name]
    if not matches:
        parts.append(new_part)
        return
    if len(matches) != 1:
        raise KeyError(f"Duplicate V8 service part {new_part.name!r}")
    index = matches[0]
    original = parts[index]
    parts[index] = replace(
        original,
        shape=new_part.shape,
        color=new_part.color,
        material=new_part.material,
        intent=new_part.intent,
    )


def _cut_a04_side_rf_corridors(state: str, parts: list[SkinPart]) -> None:
    for side_name, side in (("left", -1), ("right", 1)):
        door_name = f"A04_upper_equipment_door_{side_name}"
        radome_name = f"A04_side_uwb_radome_{side_name}"
        door_index = _find_index(parts, door_name)
        radome_index = _find_index(parts, radome_name)
        door = parts[door_index].shape
        radome = parts[radome_index].shape

        corridor = rounded_box(
            (
                _A04_RF_APERTURE_XZ_MM[0],
                _A04_RF_CORRIDOR_Y_MM,
                _A04_RF_APERTURE_XZ_MM[1],
            ),
            (
                _A04_RF_CENTER_XZ_MM[0],
                side * _A04_RF_CORRIDOR_CENTER_ABS_Y_MM,
                _A04_RF_CENTER_XZ_MM[1],
            ),
            6.0,
        )
        cut_door = door.cut(corridor)
        fixed_door = _replace_shape(parts, door_name, cut_door)
        if _intersection_volume(fixed_door.shape, corridor) > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(f"{door_name} still blocks the side-UWB RF corridor")
        if _intersection_volume(fixed_door.shape, radome) > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(f"{door_name} still intersects its final UWB radome")

        bezel = _uwb_bezel(state, side_name, side)
        if _intersection_volume(bezel.shape, fixed_door.shape) > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(f"A04 {side_name} UWB bezel intersects the cut door")
        if _intersection_volume(bezel.shape, radome) > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(f"A04 {side_name} UWB bezel intersects the radome")
        _upsert_new_part(parts, bezel)


def _a10_release_axis_cutter() -> cq.Shape:
    cutter = (
        cq.Workplane("YZ")
        .circle(_A10_RELEASE_APERTURE_DIAMETER_MM / 2.0)
        .extrude(10.0, both=True)
        .translate(
            (
                329.0,
                _A10_RELEASE_CENTER_YZ_MM[0],
                _A10_RELEASE_CENTER_YZ_MM[1],
            )
        )
        .val()
    )
    if not isinstance(cutter, cq.Shape):
        raise TypeError("A10 release-axis cutter did not resolve to a shape")
    return cutter


def _cut_a10_manual_access(parts: list[SkinPart]) -> None:
    door_name = "A10_rear_flush_service_door_skin"
    door_index = _find_index(parts, door_name)
    door = parts[door_index].shape
    release_axis = _a10_release_axis_cutter()
    # The production pull cup is inset 2 mm in X to reserve the locked Follow
    # length for the front wheel-arch return.  Sweep the original cutter by the
    # same 2 mm instead of making a thicker rounded box: changing box thickness
    # would also change its 3-D corner blend and therefore the visible YZ edge.
    # Add 0.10 mm manufacturing/Boolean relief per YZ side behind the cup; the
    # nominal 72 x 32 mm opening and its visible trim remain unchanged.
    pull_cutter_yz = (
        _A10_PULL_APERTURE_YZ_MM[0] + 0.2,
        _A10_PULL_APERTURE_YZ_MM[1] + 0.2,
    )
    pull_cavity_nominal = rounded_box(
        (16.0, pull_cutter_yz[0], pull_cutter_yz[1]),
        (329.0, _A10_PULL_CENTER_YZ_MM[0], _A10_PULL_CENTER_YZ_MM[1]),
        10.0,
    )
    pull_cavity_inset = rounded_box(
        (16.0, pull_cutter_yz[0], pull_cutter_yz[1]),
        (327.0, _A10_PULL_CENTER_YZ_MM[0], _A10_PULL_CENTER_YZ_MM[1]),
        10.0,
    )
    pull_cavity = pull_cavity_nominal.fuse(pull_cavity_inset).clean()
    cut_door = cut_many(door, (release_axis, pull_cavity))
    fixed_door = _replace_shape(parts, door_name, cut_door)

    for label, cutter in (
        ("no-power release axis", release_axis),
        ("pull-cup/finger cavity", pull_cavity),
    ):
        if _intersection_volume(fixed_door.shape, cutter) > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(f"A10 service door still blocks its {label}")

    # These are the complete existing exterior access pieces, not metadata-only
    # proxies.  The cut door must have zero material overlap with every one.
    access_names = (
        "A10_rear_service_external_release_guard",
        "A10_rear_service_external_no_power_release",
        "A10_rear_service_pull_cup",
        "A10_rear_service_pull_grip_inlay",
    )
    for name in access_names:
        access_part = parts[_find_index(parts, name)]
        overlap = _intersection_volume(fixed_door.shape, access_part.shape)
        if overlap > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(
                f"A10 service door still intersects {name}: {overlap:.6f} mm3"
            )


def _a08_drain_cutters(
    top: SkinPart,
    tread: SkinPart,
) -> tuple[cq.Shape, cq.Shape, cq.Shape]:
    top_box = top.shape.BoundingBox()
    tread_box = tread.shape.BoundingBox()
    center_x = (top_box.xmin + top_box.xmax) / 2.0
    zmin = min(top_box.zmin, tread_box.zmin) - 1.0
    zmax = max(top_box.zmax, tread_box.zmax) + 1.0
    center_z = (zmin + zmax) / 2.0
    return tuple(
        rounded_rect_prism(
            _A08_DRAIN_SLOT_XY_MM,
            zmax - zmin,
            (center_x + x_offset, 0.0, center_z),
            6.0,
        )
        for x_offset in _A08_DRAIN_SLOT_X_OFFSETS_MM
    )  # type: ignore[return-value]


def _cut_a08_through_drains(parts: list[SkinPart]) -> None:
    top_name = "A08_footrest_top_skin"
    tread_name = "A08_footrest_inset_tread"
    top = parts[_find_index(parts, top_name)]
    tread = parts[_find_index(parts, tread_name)]
    cutters = _a08_drain_cutters(top, tread)

    top_box = top.shape.BoundingBox()
    center_x = (top_box.xmin + top_box.xmax) / 2.0
    outermost_min_x = center_x + min(_A08_DRAIN_SLOT_X_OFFSETS_MM) - _A08_DRAIN_SLOT_XY_MM[0] / 2.0
    outermost_max_x = center_x + max(_A08_DRAIN_SLOT_X_OFFSETS_MM) + _A08_DRAIN_SLOT_XY_MM[0] / 2.0
    x_ligament = min(outermost_min_x - top_box.xmin, top_box.xmax - outermost_max_x)
    y_ligament = min(
        -_A08_DRAIN_SLOT_XY_MM[1] / 2.0 - top_box.ymin,
        top_box.ymax - _A08_DRAIN_SLOT_XY_MM[1] / 2.0,
    )
    if x_ligament < 45.0 or y_ligament < 195.0:
        raise ValueError(
            "A08 drain layout violates retained structural boundary: "
            f"X={x_ligament:.3f} mm, Y={y_ligament:.3f} mm"
        )

    fixed_top = _replace_shape(parts, top_name, cut_many(top.shape, cutters))
    # Re-cut the canonical source openings with the same tool.  This is an
    # idempotent through-channel proof; it must not create a second drain
    # pattern or change the pose-invariant platform B-Rep.
    fixed_tread = _replace_shape(parts, tread_name, cut_many(tread.shape, cutters))
    if len(fixed_top.shape.Solids()) != 1 or len(fixed_tread.shape.Solids()) != 1:
        raise ValueError("A08 drain cuts must not split the top shell or TPE inset")

    for station, cutter in zip(_A08_DRAIN_SLOT_X_OFFSETS_MM, cutters):
        top_overlap = _intersection_volume(fixed_top.shape, cutter)
        tread_overlap = _intersection_volume(fixed_tread.shape, cutter)
        if max(top_overlap, tread_overlap) > _BOOLEAN_TOLERANCE_MM3:
            raise ValueError(
                "A08 drain is not continuous at "
                f"X offset {station:+.1f} mm: top={top_overlap:.6f}, "
                f"tread={tread_overlap:.6f} mm3"
            )


def apply_v8_functional_fixes(
    state: str,
    parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Apply the A04/A10/A08 solid fixes and return a new part list.

    Every existing proxy keeps its name and exact metadata object.  The same
    physical A08 platform is present in every pose, so its through-tread drains
    are cut in all four primary states at the platform-local coordinates.
    """

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 state {state!r}; expected {sorted(STATES)}")
    result = list(parts)
    _cut_a04_side_rf_corridors(state, result)
    _cut_a10_manual_access(result)
    _cut_a08_through_drains(result)
    return result


__all__ = ["apply_v8_functional_fixes"]
