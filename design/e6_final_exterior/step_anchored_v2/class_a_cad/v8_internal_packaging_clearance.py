"""Physical battery/equipment/device-bay clearance against the final V8 skin.

The source-disposition ledger proves ownership, not space.  This final pass
uses the exact hash-pinned DFR5 occurrence B-Reps to open hidden equipment
portals and inner service pockets, then fails closed if any required internal
occurrence still penetrates an authored A01--A10 solid.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

import cadquery as cq

from skin_common import SkinPart, rounded_box, validate_parts
from v8_internal_layout_contract import (
    EXPECTED_DFR5_SOURCE_SOLID_COUNTS,
    REQUIRED_REPLACED_SOURCE_PROXIES,
    required_selected_occurrence_names,
)


SCRIPT_DIR = Path(__file__).resolve().parent
CONTROLLED_SOURCE = SCRIPT_DIR / "controlled_source_e6_dfr5"
SOURCE_STEP_BY_STATE = {
    state: CONTROLLED_SOURCE / f"workcore_e6_dfr5_{state}.step"
    for state in ("follow", "ride", "cafe", "focus")
}
BOOLEAN_TOLERANCE_MM3 = 1.0e-5
PACKAGING_CLEARANCE_MM = 2.0
A10_INNER_POCKET_CLEARANCE_MM = 4.0


def _intersection_volume(first: cq.Shape, second: cq.Shape) -> float:
    common = first.intersect(second)
    return 0.0 if common.isNull() else float(common.Volume())


def _bounds_overlap(first: cq.Shape, second: cq.Shape) -> bool:
    a = first.BoundingBox()
    b = second.BoundingBox()
    return not (
        a.xmax <= b.xmin
        or b.xmax <= a.xmin
        or a.ymax <= b.ymin
        or b.ymax <= a.ymin
        or a.zmax <= b.zmin
        or b.zmax <= a.zmin
    )


def _controlled_occurrence_shapes(state: str) -> dict[str, cq.Shape]:
    try:
        source_path = SOURCE_STEP_BY_STATE[state]
    except KeyError as exc:
        raise ValueError(f"Unsupported V8 internal-layout state: {state!r}") from exc
    assembly = cq.Assembly.importStep(str(source_path))
    occurrences: dict[str, cq.Shape] = {}
    for name, child in assembly.traverse():
        if name == assembly.name and not child.shapes:
            continue
        if name in occurrences or not child.shapes:
            raise RuntimeError(
                f"Controlled STEP is not a flat unique occurrence assembly: "
                f"{state}:{name}"
            )
        located = [shape.moved(child.loc) for shape in child.shapes]
        occurrences[name] = (
            located[0]
            if len(located) == 1
            else cq.Compound.makeCompound(located)
        )
    actual_solid_count = sum(
        len(shape.Solids()) for shape in occurrences.values()
    )
    expected_solid_count = EXPECTED_DFR5_SOURCE_SOLID_COUNTS[state]
    if actual_solid_count != expected_solid_count:
        raise RuntimeError(
            f"{state} controlled source has {actual_solid_count} solids; "
            f"fixed baseline is {expected_solid_count}"
        )
    missing = sorted(required_selected_occurrence_names() - set(occurrences))
    if missing:
        raise RuntimeError(
            f"{state} controlled source omits required internal occurrences: {missing}"
        )
    return occurrences


def _replace_cut_part(
    parts: list[SkinPart],
    state: str,
    name: str,
    cutters: Iterable[cq.Shape],
    *,
    relief_id: str,
    metadata: dict[str, object],
) -> None:
    matches = [(index, part) for index, part in enumerate(parts) if part.name == name]
    if len(matches) != 1:
        raise KeyError(f"{state} packaging relief requires one {name}; found {len(matches)}")
    index, part = matches[0]
    cutter_list = list(cutters)
    active: list[cq.Shape] = []
    before_common: list[float] = []
    for cutter in cutter_list:
        common = _intersection_volume(part.shape, cutter)
        before_common.append(common)
        if common > BOOLEAN_TOLERANCE_MM3:
            active.append(cutter)
    relieved = part.shape if not active else part.shape.cut(*active).clean()
    if (
        relieved.isNull()
        or not relieved.isValid()
        or relieved.Volume() <= 0.0
        or len(relieved.Solids()) != 1
    ):
        raise RuntimeError(
            f"{state} {name} packaging relief produced an invalid/non-single solid"
        )
    revised_metadata = dict(part.metadata)
    history = list(revised_metadata.get("internal_packaging_relief_history", []))
    history.append(
        {
            "relief_id": relief_id,
            "cutter_count": len(cutter_list),
            "active_cutter_count": len(active),
            "pre_cut_common_volumes_mm3": before_common,
            "nominal_clearance_mm": PACKAGING_CLEARANCE_MM,
        }
    )
    revised_metadata.update(metadata)
    revised_metadata["internal_packaging_relief_history"] = history
    revised_metadata["production_certification_claimed"] = False
    parts[index] = replace(part, shape=relieved, metadata=revised_metadata)


def _critical_intersections(
    parts: Iterable[SkinPart],
    occurrences: dict[str, cq.Shape],
) -> list[dict[str, object]]:
    collisions: list[dict[str, object]] = []
    for source_name in sorted(required_selected_occurrence_names()):
        source_shape = occurrences[source_name]
        for part in parts:
            if not _bounds_overlap(source_shape, part.shape):
                continue
            common = _intersection_volume(source_shape, part.shape)
            if common > BOOLEAN_TOLERANCE_MM3:
                collisions.append(
                    {
                        "source_occurrence": source_name,
                        "final_part": part.name,
                        "common_volume_mm3": round(common, 9),
                    }
                )
    return collisions


def _critical_internal_packaging_report_from_occurrences(
    state: str,
    parts: Iterable[SkinPart],
    occurrences: dict[str, cq.Shape],
) -> dict[str, object]:
    """Build one report from an already authenticated source occurrence map."""

    part_list = list(parts)
    collisions = _critical_intersections(part_list, occurrences)
    proxy_inventory = {part.name for part in part_list}
    missing_proxies = {
        source_name: proxy_name
        for source_name, proxy_name in REQUIRED_REPLACED_SOURCE_PROXIES.items()
        if proxy_name not in proxy_inventory
    }
    return {
        "schema_version": 1,
        "gate": "exact controlled critical internal BRep versus final A01-A10 skin",
        "state": state,
        "status": "FAIL" if collisions or missing_proxies else "PASS",
        "required_selected_occurrence_count": len(
            required_selected_occurrence_names()
        ),
        "required_replaced_source_proxies": dict(REQUIRED_REPLACED_SOURCE_PROXIES),
        "missing_replacement_proxies": missing_proxies,
        "collision_count": len(collisions),
        "collisions": collisions,
        "boolean_tolerance_mm3": BOOLEAN_TOLERANCE_MM3,
        "scope": (
            "layout-envelope clearance only; supplier-final tolerances, mounts, "
            "harnesses and manufacturing certification remain open"
        ),
    }


def critical_internal_packaging_report(
    state: str,
    parts: Iterable[SkinPart],
) -> dict[str, object]:
    """Recompute the exact named internal-vs-final-skin collision matrix."""

    return _critical_internal_packaging_report_from_occurrences(
        state,
        parts,
        _controlled_occurrence_shapes(state),
    )


def apply_v8_internal_packaging_clearance(
    state: str,
    source_parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Cut hidden access/pocket reliefs and fail on remaining hard intrusion."""

    parts = list(source_parts)
    occurrences = _controlled_occurrence_shapes(state)

    # The upper drawers translate laterally behind the removable integrated
    # side sails.  Open the obsolete A02 cosmetic web and the A04 belly side
    # wall along that real path; neither cut is a visible exterior opening.
    for side_name, side in (("left", -1), ("right", 1)):
        a02_portal = rounded_box(
            (476.0, 18.0, 104.0),
            (-20.0, side * 278.0, 365.0),
            8.0,
        )
        _replace_cut_part(
            parts,
            state,
            f"A02_main_side_shell_{side_name}",
            (a02_portal,),
            relief_id=f"upper_device_bay_{side_name}_behind_integrated_side_sail",
            metadata={
                "upper_device_bay_portal_hidden_by_integrated_side_sail": True,
                "upper_device_bay_portal_xz_mm": (476.0, 104.0),
                "drawer_lateral_service_route_preserved": True,
            },
        )
        belly_rear_portal = rounded_box(
            (50.0, 344.0, 120.0),
            (15.0, side * 170.0, 365.0),
            8.0,
        )
        _replace_cut_part(
            parts,
            state,
            "A04_underseat_belly_closeout",
            (belly_rear_portal,),
            relief_id=f"upper_device_bay_{side_name}_rear_belly_portal",
            metadata={
                "bilateral_upper_device_bay_rear_portals": True,
                "central_daily_caddy_rear_spine_retained": True,
            },
        )
        belly_portal = rounded_box(
            (476.0, 28.0, 112.0),
            (-20.0, side * 140.0, 365.0),
            8.0,
        )
        _replace_cut_part(
            parts,
            state,
            "A04_underseat_belly_closeout",
            (belly_portal,),
            relief_id=f"upper_device_bay_{side_name}_belly_portal",
            metadata={
                "bilateral_upper_device_bay_portals": True,
                "portals_hidden_behind_integrated_side_sails": True,
            },
        )

    # Seat-pan service hatch stays at the controlled Z=317 datum.  Cut only
    # its gasket seat in the belly; the hatch itself closes the opening.
    hatch_seat = rounded_box(
        (344.0, 234.0, 8.0),
        (-185.0, 0.0, 317.0),
        13.0,
    )
    _replace_cut_part(
        parts,
        state,
        "A04_underseat_belly_closeout",
        (hatch_seat,),
        relief_id="daily_caddy_final_hatch_gasket_seat",
        metadata={
            "daily_caddy_hatch_at_controlled_service_datum": True,
            "daily_caddy_hatch_nominal_perimeter_clearance_mm": 2.0,
        },
    )

    # Preserve the calm outer rear face while relieving only its inner wall
    # around the core electronics.  The guarded charge port receives a through
    # service cutter behind the single enlarged A10 door.
    a10 = next(part for part in parts if part.name == "A10_rear_service_surround")
    a10_cutters: list[cq.Shape] = []
    a10_pocket_names: list[str] = []
    for source_name in (
        "communications_5g_wifi_uwb_module",
        "compute_core_cartridge",
        "encrypted_data_vault",
        "power_distribution_unit",
        "service_charge_port_guarded",
    ):
        source_shape = occurrences[source_name]
        if _intersection_volume(a10.shape, source_shape) <= BOOLEAN_TOLERANCE_MM3:
            continue
        box = source_shape.BoundingBox()
        through = source_name == "service_charge_port_guarded"
        xmin = 293.0
        clearance = A10_INNER_POCKET_CLEARANCE_MM
        xmax = 335.0 if through else min(float(box.xmax) + clearance, 327.0)
        cutter = rounded_box(
            (
                xmax - xmin,
                float(box.ylen) + 2.0 * clearance,
                float(box.zlen) + 2.0 * clearance,
            ),
            (
                (xmin + xmax) / 2.0,
                (float(box.ymin) + float(box.ymax)) / 2.0,
                (float(box.zmin) + float(box.zmax)) / 2.0,
            ),
            4.0,
        )
        a10_cutters.append(cutter)
        a10_pocket_names.append(source_name)
    _replace_cut_part(
        parts,
        state,
        "A10_rear_service_surround",
        a10_cutters,
        relief_id="core_equipment_inner_pockets_and_guarded_port",
        metadata={
            "core_equipment_inner_pocket_occurrences": a10_pocket_names,
            "outer_rear_weather_face_retained": True,
            "guarded_charge_port_behind_single_service_door": True,
            "a10_inner_pocket_clearance_mm": A10_INNER_POCKET_CLEARANCE_MM,
        },
    )

    report = _critical_internal_packaging_report_from_occurrences(
        state,
        parts,
        occurrences,
    )
    if report["status"] != "PASS":
        raise RuntimeError(
            f"{state} critical internal packaging clearance failed: "
            f"{report['collisions']}; missing proxies={report['missing_replacement_proxies']}"
        )
    belly_matches = [
        (index, part)
        for index, part in enumerate(parts)
        if part.name == "A04_underseat_belly_closeout"
    ]
    if len(belly_matches) != 1:
        raise RuntimeError(
            f"{state} cannot attach the critical internal packaging evidence"
        )
    belly_index, belly = belly_matches[0]
    belly_metadata = dict(belly.metadata)
    belly_metadata["critical_internal_packaging_report"] = report
    parts[belly_index] = replace(belly, metadata=belly_metadata)
    errors = validate_parts(parts)
    if errors:
        raise RuntimeError(
            f"{state} internal packaging relief produced invalid final parts: {errors}"
        )
    return parts
