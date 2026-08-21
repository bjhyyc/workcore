"""Direct four-state BRep contract for the final A06/A07 physical assembly."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import cadquery as cq

try:
    from .skin_common import SkinPart
    from .v8_final_appearance_closure import (
        A07_FOCUS_STROKE_MM,
        BACK_FOLD_DEG,
        BACK_HINGE,
        BACK_RAKE_DEG,
        _production_a07_low_masters,
        _production_backrest_channel_master,
        _rotate_y,
    )
except ImportError:
    from skin_common import SkinPart  # type: ignore[no-redef]
    from v8_final_appearance_closure import (  # type: ignore[no-redef]
        A07_FOCUS_STROKE_MM,
        BACK_FOLD_DEG,
        BACK_HINGE,
        BACK_RAKE_DEG,
        _production_a07_low_masters,
        _production_backrest_channel_master,
        _rotate_y,
    )


BREP_VOLUME_TOLERANCE_MM3 = 1.0e-4
BREP_BOUND_TOLERANCE_MM = 1.0e-6

A07_EXTERIOR_NAMES = (
    "A07_mast_fixed_outer_sleeve",
    "A07_mast_moving_inner_sleeve",
    "A07_sensor_beam_shell",
    "A07_sensor_beam_smoked_window",
    "A07_physical_privacy_shutter",
    "A07_microphone_acoustic_mesh",
    "A07_environment_sensor_grille",
    "A07_fill_light_visible_window_left",
    "A07_fill_light_visible_window_right",
    "A07_privacy_shutter_carriage_bezel",
    "A07_mast_throat_weather_gasket",
    "A07_mast_lock_pin_confirmation_lens_left",
    "A07_mast_lock_pin_confirmation_lens_right",
)
A07_INTERNAL_NAMES = (
    "A07_mast_lock_pin_left",
    "A07_mast_lock_pin_right",
)
A07_ALL_NAMES = (*A07_EXTERIOR_NAMES, *A07_INTERNAL_NAMES)

_NAME_TO_MASTER = {
    "A07_mast_fixed_outer_sleeve": "fixed",
    "A07_mast_moving_inner_sleeve": "moving",
    "A07_sensor_beam_shell": "beam",
    "A07_sensor_beam_smoked_window": "sensor_window",
    "A07_physical_privacy_shutter": "privacy_shutter",
    "A07_microphone_acoustic_mesh": "microphone_mesh",
    "A07_environment_sensor_grille": "environment_grille",
    "A07_fill_light_visible_window_left": "fill_window_left",
    "A07_fill_light_visible_window_right": "fill_window_right",
    "A07_privacy_shutter_carriage_bezel": "privacy_shutter_carriage_bezel",
    "A07_mast_throat_weather_gasket": "throat_gasket",
    "A07_mast_lock_pin_confirmation_lens_left": "lock_lens_left",
    "A07_mast_lock_pin_confirmation_lens_right": "lock_lens_right",
    "A07_mast_lock_pin_left": "lock_pin_engaged_left",
    "A07_mast_lock_pin_right": "lock_pin_engaged_right",
}
_FOCUS_MOVING_NAMES = {
    "A07_mast_moving_inner_sleeve",
    "A07_sensor_beam_shell",
    "A07_sensor_beam_smoked_window",
    "A07_physical_privacy_shutter",
    "A07_microphone_acoustic_mesh",
    "A07_environment_sensor_grille",
    "A07_fill_light_visible_window_left",
    "A07_fill_light_visible_window_right",
    "A07_privacy_shutter_carriage_bezel",
}
_FOCUS_PRIVACY_NAMES = {
    "A07_physical_privacy_shutter",
    "A07_privacy_shutter_carriage_bezel",
}
_EXPECTED_PHYSICAL_IDS = {
    "A07_mast_fixed_outer_sleeve": "E6-A07-MAST-FIXED-SLEEVE",
    "A07_mast_moving_inner_sleeve": "E6-A07-MAST-MOVING-SLEEVE",
    "A07_sensor_beam_shell": "E6-A07-SENSOR-BEAM-SHELL",
    "A07_sensor_beam_smoked_window": "WC-MAST-SMOKED-SENSOR-WINDOW",
    "A07_physical_privacy_shutter": "WC-MAST-PHYSICAL-PRIVACY-SHUTTER",
    "A07_microphone_acoustic_mesh": "WC-MAST-MICROPHONE-ARRAY-INTERFACE",
    "A07_environment_sensor_grille": "WC-MAST-ENVIRONMENT-SENSOR-INTERFACE",
    "A07_fill_light_visible_window_left": "WC-MAST-FILL-LIGHT-VISIBLE-WINDOW-LEFT",
    "A07_fill_light_visible_window_right": "WC-MAST-FILL-LIGHT-VISIBLE-WINDOW-RIGHT",
    "A07_privacy_shutter_carriage_bezel": "E6-A07-PRIVACY-SHUTTER-CARRIAGE-BEZEL",
    "A07_mast_throat_weather_gasket": "E6-A07-MAST-THROAT-WEATHER-GASKET",
    "A07_mast_lock_pin_confirmation_lens_left": "E6-A07-MAST-LOCK-CONFIRMATION-LEFT",
    "A07_mast_lock_pin_confirmation_lens_right": "E6-A07-MAST-LOCK-CONFIRMATION-RIGHT",
    "A07_mast_lock_pin_left": "WC-MAST-LOCK-PIN-LEFT",
    "A07_mast_lock_pin_right": "WC-MAST-LOCK-PIN-RIGHT",
}


def _shape_signature(shape: cq.Shape) -> dict[str, Any]:
    box = shape.BoundingBox()
    centre = shape.Center()
    return {
        "volume_mm3": round(float(shape.Volume()), 6),
        "area_mm2": round(float(shape.Area()), 6),
        "centre_mm": [
            round(float(centre.x), 6),
            round(float(centre.y), 6),
            round(float(centre.z), 6),
        ],
        "bounds_mm": [
            round(float(value), 6)
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
        "valid": bool(shape.isValid()),
    }


def _brep_evidence(expected: cq.Shape, actual: cq.Shape) -> dict[str, Any]:
    expected_volume = float(expected.Volume())
    actual_volume = float(actual.Volume())
    common = float(expected.intersect(actual).Volume())
    symmetric = max(0.0, expected_volume + actual_volume - 2.0 * common)
    expected_box = expected.BoundingBox()
    actual_box = actual.BoundingBox()
    bound_delta = max(
        abs(float(first) - float(second))
        for first, second in zip(
            (
                expected_box.xmin,
                expected_box.xmax,
                expected_box.ymin,
                expected_box.ymax,
                expected_box.zmin,
                expected_box.zmax,
            ),
            (
                actual_box.xmin,
                actual_box.xmax,
                actual_box.ymin,
                actual_box.ymax,
                actual_box.zmin,
                actual_box.zmax,
            ),
        )
    )
    passed = (
        expected.isValid()
        and actual.isValid()
        and symmetric <= BREP_VOLUME_TOLERANCE_MM3
        and bound_delta <= BREP_BOUND_TOLERANCE_MM
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "symmetric_difference_volume_mm3": round(symmetric, 9),
        "common_volume_mm3": round(common, 6),
        "maximum_bound_delta_mm": round(bound_delta, 9),
        "expected_signature": _shape_signature(expected),
        "actual_signature": _shape_signature(actual),
    }


def _expected_a07_shape(state: str, name: str, master: cq.Shape) -> cq.Shape:
    result = master
    if state == "focus" and name in _FOCUS_MOVING_NAMES:
        result = result.translate(
            (
                0.0,
                136.0 if name in _FOCUS_PRIVACY_NAMES else 0.0,
                A07_FOCUS_STROKE_MM,
            )
        )
    if state == "follow":
        result = _rotate_y(result, BACK_HINGE, BACK_FOLD_DEG)
    return result


def a07_state_brep_report(
    state: str,
    parts: Sequence[SkinPart],
    visible_names: Iterable[str],
) -> dict[str, Any]:
    """Prove A07 is the same physical BRep inventory in the correct pose."""

    if state not in {"follow", "ride", "cafe", "focus"}:
        raise ValueError(f"Unsupported A07 release state {state!r}")
    by_name = {part.name: part for part in parts}
    actual_a07_names = tuple(sorted(name for name in by_name if name.startswith("A07_")))
    missing = sorted(set(A07_ALL_NAMES) - set(actual_a07_names))
    extras = sorted(set(actual_a07_names) - set(A07_ALL_NAMES))
    visible = set(visible_names)
    visible_a07 = tuple(sorted(name for name in visible if name.startswith("A07_")))
    failures: list[str] = []
    if missing:
        failures.append(f"missing A07 occurrences: {missing}")
    if extras:
        failures.append(f"unexpected A07 occurrences: {extras}")
    if set(visible_a07) != set(A07_EXTERIOR_NAMES):
        failures.append(
            "A07 exterior inventory is not the exact thirteen-piece set: "
            f"{list(visible_a07)}"
        )
    if any(name in visible for name in A07_INTERNAL_NAMES):
        failures.append("A07 structural lock pins leaked into exterior presentation")

    masters = _production_a07_low_masters()
    occurrences: dict[str, Any] = {}
    physical_ids: dict[str, Any] = {}
    if not missing:
        for name in A07_ALL_NAMES:
            part = by_name[name]
            master_key = _NAME_TO_MASTER[name]
            expected = _expected_a07_shape(state, name, masters[master_key])
            evidence = _brep_evidence(expected, part.shape)
            actual_id = part.metadata.get("physical_occurrence_id")
            expected_id = _EXPECTED_PHYSICAL_IDS[name]
            evidence.update(
                {
                    "master_key": master_key,
                    "expected_physical_occurrence_id": expected_id,
                    "actual_physical_occurrence_id": actual_id,
                    "physical_occurrence_id_equal": actual_id == expected_id,
                    "focus_translation_mm": (
                        [
                            0.0,
                            136.0 if name in _FOCUS_PRIVACY_NAMES else 0.0,
                            A07_FOCUS_STROKE_MM,
                        ]
                        if state == "focus" and name in _FOCUS_MOVING_NAMES
                        else [0.0, 0.0, 0.0]
                    ),
                    "follow_hinge_pose": state == "follow",
                }
            )
            if evidence["status"] != "PASS" or actual_id != expected_id:
                failures.append(f"{state} {name} direct BRep/identity mismatch")
            occurrences[name] = evidence
            physical_ids[name] = actual_id

    backrest_name = "A06_backrest_weather_shell"
    backrest_evidence: dict[str, Any] | None = None
    if backrest_name not in by_name:
        failures.append(f"missing {backrest_name}")
    else:
        expected_backrest = _rotate_y(
            _production_backrest_channel_master(),
            BACK_HINGE,
            BACK_RAKE_DEG,
        )
        if state == "follow":
            expected_backrest = _rotate_y(
                expected_backrest,
                BACK_HINGE,
                BACK_FOLD_DEG,
            )
        backrest_evidence = _brep_evidence(
            expected_backrest,
            by_name[backrest_name].shape,
        )
        if backrest_evidence["status"] != "PASS":
            failures.append(f"{state} A06 backrest direct shared-hinge BRep mismatch")

    hinge_start = cq.Vector(*BACK_HINGE)
    hinge_end = cq.Vector(BACK_HINGE[0], BACK_HINGE[1] + 100.0, BACK_HINGE[2])
    hinge_invariant = (
        _rotate_y(
            cq.Vertex.makeVertex(hinge_start.x, hinge_start.y, hinge_start.z),
            BACK_HINGE,
            BACK_FOLD_DEG,
        ).distance(cq.Vertex.makeVertex(*BACK_HINGE))
        <= 1.0e-9
        and _rotate_y(
            cq.Vertex.makeVertex(hinge_end.x, hinge_end.y, hinge_end.z),
            BACK_HINGE,
            BACK_FOLD_DEG,
        ).distance(cq.Vertex.makeVertex(hinge_end.x, hinge_end.y, hinge_end.z))
        <= 1.0e-9
    )
    if not hinge_invariant:
        failures.append("A06/A07 shared Y-axis hinge does not remain invariant")

    return {
        "schema_version": 1,
        "gate": "direct A06/A07 four-state physical BRep pose contract",
        "state": state,
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "canonical_exterior_inventory": list(A07_EXTERIOR_NAMES),
        "canonical_internal_inventory": list(A07_INTERNAL_NAMES),
        "actual_a07_inventory": list(actual_a07_names),
        "visible_exterior_inventory": list(visible_a07),
        "physical_occurrence_ids_by_name": physical_ids,
        "occurrences": occurrences,
        "a06_backrest_brep_evidence": backrest_evidence,
        "endpoint_contract": {
            "ride_cafe_low_pose_equal": True,
            "focus_moving_translation_mm": [0.0, 0.0, 420.0],
            "focus_privacy_translation_mm": [0.0, 136.0, 420.0],
            "fixed_inventory_translation_mm": [0.0, 0.0, 0.0],
            "follow_a06_a07_shared_hinge_mm": list(BACK_HINGE),
            "follow_fold_deg": BACK_FOLD_DEG,
            "follow_shared_hinge_axis_invariant": hinge_invariant,
        },
    }


__all__ = [
    "A07_ALL_NAMES",
    "A07_EXTERIOR_NAMES",
    "A07_INTERNAL_NAMES",
    "BREP_BOUND_TOLERANCE_MM",
    "BREP_VOLUME_TOLERANCE_MM3",
    "a07_state_brep_report",
]
