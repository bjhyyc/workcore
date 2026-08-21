"""Build V11 R08: rounded arm language with a tapered rear plan."""

from __future__ import annotations

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
import build_v11_visual_r07 as r07  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r08"
ACTIVE_STATE = "ride"


def taper_arm_rear(obj: bpy.types.Object, y_centre: float) -> None:
    if obj.type != "MESH":
        raise TypeError(obj.name)
    for vertex in obj.data.vertices:
        x = float(vertex.co.x)
        if x <= 0.100:
            factor = 1.0
        elif x >= 0.220:
            factor = 0.58
        else:
            factor = 1.0 - (x - 0.100) / 0.120 * 0.42
        vertex.co.y = y_centre + (float(vertex.co.y) - y_centre) * factor
    obj.data.update()
    r01.set_smooth(obj)
    obj["plan_taper"] = "full 94 mm HMI width through x=100 mm; smooth rear reduction to 58 percent"


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = r05.build_lower_and_arms(owner, mats)
    for side, y_centre in (("LEFT", -0.328), ("RIGHT", 0.328)):
        arm = bpy.data.objects.get(f"V11_R05_SHARED_FIXED_SCULPTED_ARM_{side}")
        if arm is None:
            raise RuntimeError(f"R08: missing {side} arm")
        taper_arm_rear(arm, y_centre)
        arm.name = f"V11_R08_SHARED_FIXED_ROUNDED_TAPERED_ARM_{side}"
        arm.data.name = arm.data.name.replace("R05", "R08")
        old_lid = bpy.data.objects.get(f"V11_R05_SHARED_FLUSH_OUTWARD_LID_SEAM_{side}")
        if old_lid is not None:
            if old_lid in objects:
                objects.remove(old_lid)
            bpy.data.objects.remove(old_lid, do_unlink=True)
        lid = r03.rounded_rect_curve(
            owner,
            f"V11_R08_SHARED_FLUSH_OUTWARD_LID_SEAM_{side}",
            (-0.0225, y_centre, 0.68235),
            0.405,
            0.078,
            0.016,
            "XY",
            mats["seam"],
            0.00045,
        )
        lid["lid_motion"] = "outward flip; retrieve folded table; close lid"
        lid["clear_access_length_mm"] = 405.0
        objects.append(lid)

    for obj in objects:
        if "R05" in obj.name:
            obj.name = obj.name.replace("R05", "R08")
        if getattr(obj, "data", None) is not None and "R05" in obj.data.name:
            obj.data.name = obj.data.name.replace("R05", "R08")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts = r07.build_a06_a07(owner, state, mats)
    for obj in parts:
        if "R07" in obj.name:
            obj.name = obj.name.replace("R07", "R08")
        if getattr(obj, "data", None) is not None and "R07" in obj.data.name:
            obj.data.name = obj.data.name.replace("R07", "R08")
    return parts


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r04.ACTIVE_STATE = ACTIVE_STATE
    r05.ACTIVE_STATE = ACTIVE_STATE
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
    payload["r08_form_changes"] = [
        "restored the smooth R05 arm terminal radius",
        "rear 120 mm of each fixed arm now tapers in plan without a thin extension",
        "R07 near-closed A06 and smoked exposed A07 centreline retained unchanged",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R08_BUILT_UNVALIDATED", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
