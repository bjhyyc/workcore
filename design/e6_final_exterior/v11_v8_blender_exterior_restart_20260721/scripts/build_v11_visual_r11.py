"""Build V11 R11: wheel coverage comes only from the monocoque cross-section."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import bpy


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
import build_v11_visual_r03 as r03  # noqa: E402
import build_v11_visual_r09 as r09  # noqa: E402
import build_v11_visual_r10 as r10  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, sha256, state_blend_path, validate_state  # noqa: E402


REVISION = "r11"
ACTIVE_STATE = "ride"
BASE_LONGITUDINAL_LOFT = r09.longitudinal_loft


def continuous_body_loft(
    owner: bpy.types.Collection,
    name: str,
    controls: list[tuple[float, float, float, float]],
    exponent: float,
    mat: bpy.types.Material,
    ring_segments: int = 64,
) -> bpy.types.Object:
    # A lower exponent keeps the same single surface near full width until the
    # lower corner, so the upper tyre is hidden without a fender-like add-on.
    return BASE_LONGITUDINAL_LOFT(owner, name, controls, 0.18, mat, ring_segments)


def discard(objects: list[bpy.types.Object], tokens: tuple[str, ...]) -> None:
    for obj in list(objects):
        if any(token in obj.name for token in tokens):
            objects.remove(obj)
            bpy.data.objects.remove(obj, do_unlink=True)


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = r09.build_lower_and_arms(owner, mats)
    body = bpy.data.objects.get("V11_R09_SHARED_SINGLE_ASYMMETRIC_MONOCOQUE")
    if body is None:
        raise RuntimeError("R11: monocoque missing")
    body["wheel_wrap_policy_r11"] = "same monocoque cross-section remains near full width through the upper tyre; no side add-on"
    body["cross_section_signed_power"] = 0.18

    discard(
        objects,
        (
            "LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID",
            "RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID",
            "LEFT_ACCESS_LID_SEAM",
            "RIGHT_ACCESS_LID_SEAM",
        ),
    )
    left_lid = r09.rounded_prism_xy(owner, "V11_R11_A05_LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID", (0.000, -0.320, 0.6550), 0.440, 0.096, 0.0020, 0.017, mats["body"], 0.0003)
    left_lid["source_occurrence_ids"] = "A05_armrest_table_bay_lid_left"
    left_lid["motion"] = "outward flip about outer edge; retrieve table; close lid"
    left_lid["owns_qi"] = True
    right_lid = r09.rounded_prism_xy(owner, "V11_R11_A05_RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID", (0.020, 0.320, 0.6550), 0.410, 0.096, 0.0020, 0.017, mats["body"], 0.0003)
    right_lid["source_occurrence_ids"] = "A05_armrest_table_bay_lid_right"
    right_lid["motion"] = "outward flip about outer edge; fixed HMI island remains forward and exposed"
    right_lid["fixed_hmi_clearance_mm"] = 15.0
    objects.extend([left_lid, right_lid])
    objects.append(r09.flat_outline_curve(owner, "V11_R11_A05_LEFT_ACCESS_LID_SEAM", (0.000, -0.320, 0.6562), 0.440, 0.096, 0.017, mats["seam"], 0.00055))
    objects.append(r09.flat_outline_curve(owner, "V11_R11_A05_RIGHT_ACCESS_LID_SEAM", (0.020, 0.320, 0.6562), 0.410, 0.096, 0.017, mats["seam"], 0.00055))

    for name in ("V11_R09_A05_LEFT_QI_FLUSH_USABLE_FIELD_176X86", "V11_R09_A05_LEFT_QI_TARGET_RING"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.location.z -= 0.0025

    for obj in objects:
        if "R09" in obj.name:
            obj.name = obj.name.replace("R09", "R11")
        if getattr(obj, "data", None) is not None and "R09" in obj.data.name:
            obj.data.name = obj.data.name.replace("R09", "R11")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts = r09.build_a06_a07(owner, state, mats)
    for obj in parts:
        if "R09" in obj.name:
            obj.name = obj.name.replace("R09", "R11")
        if getattr(obj, "data", None) is not None and "R09" in obj.data.name:
            obj.data.name = obj.data.name.replace("R09", "R11")
    return parts


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r09.ACTIVE_STATE = ACTIVE_STATE
    r09.arm_loft = r10.arm_loft
    r09.longitudinal_loft = continuous_body_loft
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = r10.materials
    r01.clone_material_for_occurrence = r09.clone_material
    r01.should_clone_occurrence = r09.should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = r09.studio
    r01.main()

    output = state_blend_path(ACTIVE_STATE, REVISION)
    report_path = V11_ROOT / "qa" / REVISION / f"v11_{ACTIVE_STATE}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    measured = r03.evaluated_product_bounds()
    payload["status"] = "BUILT_UNVALIDATED"
    payload["revision"] = REVISION
    payload["blend_sha256"] = sha256(output)
    payload["measured_product_bounds_after_save"] = measured
    payload["contracts"] = {
        "overall_finished_width_limit_m": 0.752,
        "measured_finished_width_m": measured["finished_width_m"],
        "display": "uniform 124 x 49 x 2.5 mm plate; world-Y +8 deg; front high/rear low",
        "qi_usable_field_mm": "176 x 86; single flush field owned by left lid",
        "focus_a07_motion_mm": 420.0 if ACTIVE_STATE == "focus" else 0.0,
        "follow_fold_deg": -90.0 if ACTIVE_STATE == "follow" else 0.0,
        "footrest": "+220 mm X telescopic stow; open only in Ride default",
        "wheel_wrap": "single mother surface only; no separately readable fender or side panel",
    }
    payload["r11_form_changes"] = [
        "discarded the R10 unioned side ribbons because they read as applied panels",
        "same monocoque now supplies wheel coverage through a continuous signed-power cross-section",
        "R10 long flat arm top and truly flush 2 mm access lids retained",
    ]
    payload["known_limits"] = [
        "Blender visual/layout decision model; production BRep and internal equipment package remain pending",
        "formal saved-file tyre visibility, topology and four-state gates remain mandatory",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R11_BUILT_UNVALIDATED", ACTIVE_STATE, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
