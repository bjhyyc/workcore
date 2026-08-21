"""Direct BRep release contract for the bilateral Focus table root necks.

The Focus table may show one honest, smooth structural neck on each side, but
it may not float, pierce the closed A05 surfaces, or depend on metadata-only
geometry.  This module therefore compares the released occurrences with the
canonical production solids and independently probes the neck loft, adjacent
clearances, and both load-path contact faces.

All report values are plain Python objects so callers can write the result
directly with :mod:`json`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import cadquery as cq

try:
    from .exterior_presentation import exterior_visibility_reason
    from .skin_common import SkinPart
    from .skin_upper import (
        _focus_hidden_root_tongue,
        _focus_smooth_gap_neck,
    )
except ImportError:
    from exterior_presentation import exterior_visibility_reason  # type: ignore[no-redef]
    from skin_common import SkinPart  # type: ignore[no-redef]
    from skin_upper import (  # type: ignore[no-redef]
        _focus_hidden_root_tongue,
        _focus_smooth_gap_neck,
    )


BREP_VOLUME_TOLERANCE_MM3 = 1.0e-4
BREP_AREA_TOLERANCE_MM2 = 1.0e-4
BREP_BOUND_TOLERANCE_MM = 1.0e-6
CONTACT_DISTANCE_TOLERANCE_MM = 1.0e-6
CLEARANCE_NUMERICAL_TOLERANCE_MM = 1.0e-4
SLICE_THICKNESS_MM = 0.1
SLICE_DIMENSION_TOLERANCE_MM = 1.0e-3

_SIDES = (("left", -1), ("right", 1))
_TONGUE_NAMES = {
    "left": "A09_focus_table_hidden_root_tongue_left",
    "right": "A09_focus_table_hidden_root_tongue_right",
}
_EXPECTED_PHYSICAL_IDS = {
    "left": "E6-A09-FOCUS-HIDDEN-ROOT-TONGUE-LEFT",
    "right": "E6-A09-FOCUS-HIDDEN-ROOT-TONGUE-RIGHT",
}
_SLICE_EXPECTATIONS = (
    (276.05, 16.0, 8.0000002),
    (293.0, 16.0, 6.005882552941557),
    (309.95, 16.0, 4.011764905882615),
)


def _shape_signature(shape: cq.Shape) -> dict[str, Any]:
    box = shape.BoundingBox()
    centre = shape.Center()
    return {
        "valid": bool(shape.isValid()),
        "volume_mm3": round(float(shape.Volume()), 9),
        "area_mm2": round(float(shape.Area()), 9),
        "centre_mm": [
            round(float(centre.x), 9),
            round(float(centre.y), 9),
            round(float(centre.z), 9),
        ],
        "bounds_mm": [
            round(float(value), 9)
            for value in (
                box.xmin,
                box.xmax,
                box.ymin,
                box.ymax,
                box.zmin,
                box.zmax,
            )
        ],
        "topology": {
            "solids": len(shape.Solids()),
            "shells": len(shape.Shells()),
            "faces": len(shape.Faces()),
            "edges": len(shape.Edges()),
            "vertices": len(shape.Vertices()),
        },
    }


def _maximum_bound_delta(first: cq.Shape, second: cq.Shape) -> float:
    first_box = first.BoundingBox()
    second_box = second.BoundingBox()
    return max(
        abs(float(first_value) - float(second_value))
        for first_value, second_value in zip(
            (
                first_box.xmin,
                first_box.xmax,
                first_box.ymin,
                first_box.ymax,
                first_box.zmin,
                first_box.zmax,
            ),
            (
                second_box.xmin,
                second_box.xmax,
                second_box.ymin,
                second_box.ymax,
                second_box.zmin,
                second_box.zmax,
            ),
        )
    )


def _brep_equivalence(expected: cq.Shape, actual: cq.Shape) -> dict[str, Any]:
    """Return directional Boolean evidence instead of trusting mass alone."""

    expected_only = float(expected.cut(actual).Volume())
    actual_only = float(actual.cut(expected).Volume())
    volume_delta = abs(float(expected.Volume()) - float(actual.Volume()))
    area_delta = abs(float(expected.Area()) - float(actual.Area()))
    bound_delta = _maximum_bound_delta(expected, actual)
    passed = (
        expected.isValid()
        and actual.isValid()
        and len(expected.Solids()) == 1
        and len(actual.Solids()) == 1
        and expected_only <= BREP_VOLUME_TOLERANCE_MM3
        and actual_only <= BREP_VOLUME_TOLERANCE_MM3
        and volume_delta <= BREP_VOLUME_TOLERANCE_MM3
        and area_delta <= BREP_AREA_TOLERANCE_MM2
        and bound_delta <= BREP_BOUND_TOLERANCE_MM
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "expected_minus_actual_volume_mm3": round(expected_only, 9),
        "actual_minus_expected_volume_mm3": round(actual_only, 9),
        "absolute_volume_delta_mm3": round(volume_delta, 9),
        "absolute_area_delta_mm2": round(area_delta, 9),
        "maximum_bound_delta_mm": round(bound_delta, 9),
        "expected_signature": _shape_signature(expected),
        "actual_signature": _shape_signature(actual),
    }


def _neck_containment(neck: cq.Shape, tongue: cq.Shape) -> dict[str, Any]:
    outside = float(neck.cut(tongue).Volume())
    common = float(neck.intersect(tongue).Volume())
    neck_volume = float(neck.Volume())
    common_delta = abs(neck_volume - common)
    passed = (
        neck.isValid()
        and tongue.isValid()
        and len(neck.Solids()) == 1
        and outside <= BREP_VOLUME_TOLERANCE_MM3
        and common_delta <= BREP_VOLUME_TOLERANCE_MM3
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "neck_volume_mm3": round(neck_volume, 9),
        "neck_outside_tongue_volume_mm3": round(outside, 9),
        "neck_tongue_common_volume_mm3": round(common, 9),
        "neck_common_volume_delta_mm3": round(common_delta, 9),
    }


def _thin_slice_probe(
    neck: cq.Shape,
    side: int,
    absolute_y_mm: float,
    expected_x_mm: float,
    expected_z_mm: float,
) -> dict[str, Any]:
    """Measure a real 0.1 mm BRep slice; no metadata dimensions are used."""

    neck_box = neck.BoundingBox()
    probe = (
        cq.Workplane("XY")
        .box(
            float(neck_box.xlen) + 20.0,
            SLICE_THICKNESS_MM,
            float(neck_box.zlen) + 20.0,
        )
        .translate(
            (
                (float(neck_box.xmin) + float(neck_box.xmax)) / 2.0,
                side * absolute_y_mm,
                (float(neck_box.zmin) + float(neck_box.zmax)) / 2.0,
            )
        )
        .val()
    )
    section = neck.intersect(probe)
    if section.isNull() or float(section.Volume()) <= 0.0:
        return {
            "status": "FAIL",
            "absolute_y_mm": absolute_y_mm,
            "probe_center_y_mm": side * absolute_y_mm,
            "slice_thickness_mm": SLICE_THICKNESS_MM,
            "expected_x_mm": expected_x_mm,
            "expected_z_mm": expected_z_mm,
            "failure": "thin-slice intersection is null or has no volume",
        }
    box = section.BoundingBox()
    measured_x = float(box.xlen)
    measured_z = float(box.zlen)
    x_delta = abs(measured_x - expected_x_mm)
    z_delta = abs(measured_z - expected_z_mm)
    passed = (
        section.isValid()
        and x_delta <= SLICE_DIMENSION_TOLERANCE_MM
        and z_delta <= SLICE_DIMENSION_TOLERANCE_MM
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "absolute_y_mm": absolute_y_mm,
        "probe_center_y_mm": side * absolute_y_mm,
        "slice_thickness_mm": SLICE_THICKNESS_MM,
        "section_volume_mm3": round(float(section.Volume()), 9),
        "measured_x_mm": round(measured_x, 9),
        "measured_z_mm": round(measured_z, 9),
        "expected_x_mm": expected_x_mm,
        "expected_z_mm": expected_z_mm,
        "absolute_x_delta_mm": round(x_delta, 9),
        "absolute_z_delta_mm": round(z_delta, 9),
        "section_bounds_mm": [
            round(float(value), 9)
            for value in (
                box.xmin,
                box.xmax,
                box.ymin,
                box.ymax,
                box.zmin,
                box.zmax,
            )
        ],
    }


def _clearance_evidence(
    tongue: cq.Shape,
    obstacle: SkinPart,
    minimum_clearance_mm: float,
) -> dict[str, Any]:
    common = float(tongue.intersect(obstacle.shape).Volume())
    distance = float(tongue.distance(obstacle.shape))
    passed = (
        common <= BREP_VOLUME_TOLERANCE_MM3
        and distance + CLEARANCE_NUMERICAL_TOLERANCE_MM
        >= minimum_clearance_mm
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "obstacle": obstacle.name,
        "common_volume_mm3": round(common, 9),
        "minimum_distance_mm": round(distance, 9),
        "required_minimum_distance_mm": minimum_clearance_mm,
    }


def _contact_evidence(first: SkinPart, second: SkinPart) -> dict[str, Any]:
    common = float(first.shape.intersect(second.shape).Volume())
    distance = float(first.shape.distance(second.shape))
    passed = (
        common <= BREP_VOLUME_TOLERANCE_MM3
        and distance <= CONTACT_DISTANCE_TOLERANCE_MM
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "first": first.name,
        "second": second.name,
        "common_volume_mm3": round(common, 9),
        "minimum_distance_mm": round(distance, 9),
        "required_contact_distance_maximum_mm": CONTACT_DISTANCE_TOLERANCE_MM,
    }


def focus_root_neck_release_report(
    parts: Sequence[SkinPart],
) -> dict[str, Any]:
    """Prove the final Focus root-neck BReps and their physical interfaces."""

    all_parts = list(parts)
    by_name: dict[str, list[SkinPart]] = {}
    for part in all_parts:
        by_name.setdefault(part.name, []).append(part)

    failures: list[str] = []
    side_reports: dict[str, Any] = {}
    actual_tongues: dict[str, SkinPart] = {}

    actual_prefixed_names = sorted(
        part.name
        for part in all_parts
        if part.name.startswith("A09_focus_table_hidden_root_tongue_")
    )
    expected_names = sorted(_TONGUE_NAMES.values())
    if actual_prefixed_names != expected_names:
        failures.append(
            "Focus hidden-root-tongue inventory must be exactly left/right: "
            f"{actual_prefixed_names}"
        )

    for side_name, side in _SIDES:
        name = _TONGUE_NAMES[side_name]
        matches = by_name.get(name, [])
        side_failures: list[str] = []
        side_report: dict[str, Any] = {
            "name": name,
            "side": side_name,
            "side_sign": side,
            "status": "FAIL",
            "failures": side_failures,
        }
        if len(matches) != 1:
            message = f"{name} occurrence count is {len(matches)}, expected 1"
            side_failures.append(message)
            failures.append(message)
            side_reports[side_name] = side_report
            continue

        actual = matches[0]
        actual_tongues[side_name] = actual
        expected = _focus_hidden_root_tongue(side)
        neck = _focus_smooth_gap_neck(side)
        expected_id = _EXPECTED_PHYSICAL_IDS[side_name]
        actual_id = actual.metadata.get("physical_occurrence_id")
        is_visible, visibility_reason = exterior_visibility_reason("focus", actual)
        identity_pass = (
            actual.configuration == "focus"
            and actual_id == expected_id
            and is_visible
            and actual.metadata.get("final_exterior_visible") is True
        )
        identity = {
            "status": "PASS" if identity_pass else "FAIL",
            "configuration": actual.configuration,
            "expected_configuration": "focus",
            "expected_physical_occurrence_id": expected_id,
            "actual_physical_occurrence_id": actual_id,
            "physical_occurrence_id_equal": actual_id == expected_id,
            "exterior_visible": is_visible,
            "visibility_reason": visibility_reason,
            "explicit_final_exterior_visible": actual.metadata.get(
                "final_exterior_visible"
            ),
        }
        if not identity_pass:
            side_failures.append(
                f"{name} physical identity/configuration/visibility mismatch"
            )

        direct_brep = _brep_equivalence(expected, actual.shape)
        if direct_brep["status"] != "PASS":
            side_failures.append(f"{name} differs from its canonical BRep")

        containment = _neck_containment(neck, actual.shape)
        if containment["status"] != "PASS":
            side_failures.append(
                f"{name} does not completely contain the canonical smooth neck"
            )

        slice_probes = [
            _thin_slice_probe(neck, side, absolute_y, expected_x, expected_z)
            for absolute_y, expected_x, expected_z in _SLICE_EXPECTATIONS
        ]
        if any(probe["status"] != "PASS" for probe in slice_probes):
            side_failures.append(f"{name} smooth-loft thin-slice profile mismatch")

        clearance_specs = [
            (
                f"A05_armrest_table_bay_shell_{side_name}",
                1.5,
                "armrest_bay_shell",
            ),
            (
                f"A05_armrest_touch_lid_{side_name}",
                3.0,
                "closed_touch_lid",
            ),
            (
                f"A05_armrest_top_lid_release_{side_name}",
                4.0,
                "lid_release",
            ),
        ]
        if side_name == "left":
            clearance_specs.extend(
                [
                    (
                        "A05_left_hmi_precision_bezel",
                        2.8,
                        "hmi_precision_bezel",
                    ),
                    (
                        "A05_left_status_display_window",
                        2.8,
                        "hmi_display_window",
                    ),
                ]
            )
        clearances: dict[str, Any] = {}
        for obstacle_name, minimum, role in clearance_specs:
            obstacles = by_name.get(obstacle_name, [])
            if len(obstacles) != 1:
                message = (
                    f"{name} clearance obstacle {obstacle_name} count is "
                    f"{len(obstacles)}, expected 1"
                )
                side_failures.append(message)
                clearances[role] = {
                    "status": "FAIL",
                    "obstacle": obstacle_name,
                    "failure": "required obstacle occurrence is missing or duplicated",
                }
                continue
            evidence = _clearance_evidence(actual.shape, obstacles[0], minimum)
            clearances[role] = evidence
            if evidence["status"] != "PASS":
                side_failures.append(
                    f"{name} collides with or lacks clearance to {obstacle_name}"
                )

        interface_specs = [
            (
                f"A09_focus_internal_nested_guide_stage_3_{side_name}",
                "guide_stage3_face_contact",
            ),
            (
                f"A09_table_underbelly_shell_{side_name}",
                "outer_table_underbelly_face_contact",
            ),
        ]
        contacts: dict[str, Any] = {}
        for interface_name, role in interface_specs:
            interfaces = by_name.get(interface_name, [])
            if len(interfaces) != 1:
                message = (
                    f"{name} interface {interface_name} count is "
                    f"{len(interfaces)}, expected 1"
                )
                side_failures.append(message)
                contacts[role] = {
                    "status": "FAIL",
                    "interface": interface_name,
                    "failure": "required interface occurrence is missing or duplicated",
                }
                continue
            if role == "outer_table_underbelly_face_contact" and (
                interfaces[0].metadata.get("rigid_half_role") != "outer"
            ):
                message = f"{interface_name} is not the outer rigid half-leaf"
                side_failures.append(message)
            evidence = _contact_evidence(actual, interfaces[0])
            evidence["rigid_half_role"] = interfaces[0].metadata.get(
                "rigid_half_role"
            )
            contacts[role] = evidence
            if evidence["status"] != "PASS":
                side_failures.append(
                    f"{name} has an invalid zero-penetration contact with "
                    f"{interface_name}"
                )

        side_report.update(
            {
                "status": "FAIL" if side_failures else "PASS",
                "identity_and_visibility": identity,
                "direct_canonical_brep": direct_brep,
                "smooth_gap_neck_containment": containment,
                "independent_thin_slice_probes": slice_probes,
                "a05_zero_collision_clearances": clearances,
                "load_path_zero_penetration_contacts": contacts,
            }
        )
        if side_failures:
            failures.extend(side_failures)
        side_reports[side_name] = side_report

    mirror_report: dict[str, Any]
    if set(actual_tongues) == {"left", "right"}:
        mirrored_right = actual_tongues["right"].shape.mirror("XZ")
        mirror_report = _brep_equivalence(
            actual_tongues["left"].shape,
            mirrored_right,
        )
        mirror_report.update(
            {
                "mirror_plane": "XZ",
                "reference_side": "left",
                "mirrored_side": "right",
            }
        )
        if mirror_report["status"] != "PASS":
            failures.append("Focus left/right root tongues are not XZ-mirror BReps")
    else:
        mirror_report = {
            "status": "FAIL",
            "mirror_plane": "XZ",
            "failure": "both unique root-tongue occurrences are required",
        }

    return {
        "schema_version": 1,
        "gate": "Focus bilateral smooth root-neck direct BRep release contract",
        "state": "focus",
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "required_occurrences": expected_names,
        "actual_root_tongue_inventory": actual_prefixed_names,
        "tolerances": {
            "brep_volume_mm3": BREP_VOLUME_TOLERANCE_MM3,
            "brep_area_mm2": BREP_AREA_TOLERANCE_MM2,
            "brep_bound_mm": BREP_BOUND_TOLERANCE_MM,
            "contact_distance_mm": CONTACT_DISTANCE_TOLERANCE_MM,
            "clearance_numerical_mm": CLEARANCE_NUMERICAL_TOLERANCE_MM,
            "slice_dimension_mm": SLICE_DIMENSION_TOLERANCE_MM,
            "slice_thickness_mm": SLICE_THICKNESS_MM,
        },
        "sides": side_reports,
        "bilateral_xz_mirror": mirror_report,
    }


__all__ = [
    "BREP_AREA_TOLERANCE_MM2",
    "BREP_BOUND_TOLERANCE_MM",
    "BREP_VOLUME_TOLERANCE_MM3",
    "CLEARANCE_NUMERICAL_TOLERANCE_MM",
    "CONTACT_DISTANCE_TOLERANCE_MM",
    "SLICE_DIMENSION_TOLERANCE_MM",
    "SLICE_THICKNESS_MM",
    "focus_root_neck_release_report",
]
