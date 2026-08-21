"""Build V11 R07: rounded lofted arms and near-closed Follow reveal."""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
import build_v11_visual_r03 as r03  # noqa: E402
import build_v11_visual_r04 as r04  # noqa: E402
import build_v11_visual_r05 as r05  # noqa: E402
import build_v11_visual_r06 as r06  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r07"
ACTIVE_STATE = "ride"
BASE_LOFTED_ARM = r06.lofted_arm


def rounded_lofted_arm(
    owner: bpy.types.Collection,
    name: str,
    y_centre: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    obj = BASE_LOFTED_ARM(owner, name, y_centre, mat)
    bevel = obj.modifiers.new("V11_R07_ROUNDED_ARM_TERMINALS", "BEVEL")
    bevel.width = 0.010
    bevel.segments = 7
    bevel.limit_method = "ANGLE"
    r01.apply_modifier(obj, bevel)
    r01.set_smooth(obj)
    return obj


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = r06.build_lower_and_arms(owner, mats)
    for obj in objects:
        if "R06" in obj.name:
            obj.name = obj.name.replace("R06", "R07")
        if getattr(obj, "data", None) is not None and "R06" in obj.data.name:
            obj.data.name = obj.data.name.replace("R06", "R07")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R07_{state.upper()}_A06_ICONIC_TRAPEZOID",
        0.142,
        0.238,
        0.540,
        1.025,
        0.292,
        0.260,
        mats["body"],
        0.023,
    )
    shell["source_occurrence_ids"] = "A06_backrest_moving_shell"
    shell["identity"] = "same outer trapezoid; stronger inner leather trapezoid preserves recognition"
    contact = r01.trapezoid_prism(
        owner,
        f"V11_R07_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.136,
        0.143,
        0.575,
        0.980,
        0.257,
        0.205,
        mats["leather"],
        0.014,
    )
    contact["source_occurrence_ids"] = "A06_backrest_contact_island"
    parts.extend([shell, contact])

    mast = r01.trapezoid_prism(
        owner,
        f"V11_R07_{state.upper()}_A07_EXPOSED_TAPERED_BLADE",
        0.226,
        0.244,
        0.590,
        1.060,
        0.050,
        0.035,
        mats["glass"],
        0.006,
    )
    mast["source_occurrence_ids"] = "A07_sensor_mast_moving"
    mast["mast_geometry_contract"] = "same smoked trapezoid blade; Focus translates only"
    head = r01.rounded_box(
        owner,
        f"V11_R07_{state.upper()}_A07_SENSOR_CROWN",
        (0.235, 0.0, 1.060),
        (0.032, 0.285, 0.034),
        0.015,
        mats["body_soft"],
        8,
    )
    head["source_occurrence_ids"] = "A07_sensor_head"
    window = r01.rounded_box(
        owner,
        f"V11_R07_{state.upper()}_A07_SENSOR_WINDOW",
        (0.2180, 0.0, 1.058),
        (0.003, 0.220, 0.014),
        0.006,
        mats["glass"],
        6,
    )
    window["source_occurrence_ids"] = "A07_sensor_window"
    mast_parts = [mast, head, window]
    parts.extend(mast_parts)

    if state == "focus":
        for obj in mast_parts:
            obj.location.z += 0.420
            obj["focus_translation_z_mm"] = 420.0
    elif state == "follow":
        pivot = bpy.data.objects.new("V11_R07_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.540)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-90.0)
        pivot["fold_angle_deg"] = -90.0
        pivot["allowed_children"] = "A06 shell/contact + same A07 blade/crown/window only"
        parts.append(pivot)
    return parts


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r04.ACTIVE_STATE = ACTIVE_STATE
    r05.ACTIVE_STATE = ACTIVE_STATE
    r06.ACTIVE_STATE = ACTIVE_STATE
    r06.lofted_arm = rounded_lofted_arm
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = r06.materials
    r01.clone_material_for_occurrence = r03.clone_material
    r01.should_clone_occurrence = r05.should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = r06.studio
    r01.main()

    report_path = V11_ROOT / "qa" / REVISION / f"v11_{ACTIVE_STATE}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    measured = r03.evaluated_product_bounds()
    payload["status"] = "BUILT_UNVALIDATED"
    payload["revision"] = REVISION
    payload["measured_product_bounds_after_save"] = measured
    payload["contracts"] = {
        "overall_finished_width_limit_m": 0.752,
        "measured_finished_width_m": measured["finished_width_m"],
        "a04_door_mm": "464 x 86 R18 in 466 x 88 R19; 1 mm nominal seam",
        "display_mm_pitch": "124 x 49; world-Y +8 deg; front high/rear low",
        "qi_usable_field_mm": "176 x 86; single layer",
        "focus_a07_motion_mm": 420.0 if ACTIVE_STATE == "focus" else 0.0,
        "follow_fold_deg": -90.0 if ACTIVE_STATE == "follow" else 0.0,
        "ride_footrest_default": "open" if ACTIVE_STATE == "ride" else "stowed",
    }
    payload["known_limits"] = [
        "Blender visual decision model; not a production STEP release",
        "formal saved-file geometry and rendered visibility gates remain mandatory",
    ]
    payload["r07_form_changes"] = [
        "lofted arms gain 10 mm seven-segment terminal rounding",
        "same A06 extends 15 mm and widens to a 520 mm folded front edge",
        "Follow reveal is reduced without adding any hood, filler or cosmetic cover",
        "A07 blade becomes smoked and remains a visible centreline in Follow",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R07_BUILT_UNVALIDATED", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
