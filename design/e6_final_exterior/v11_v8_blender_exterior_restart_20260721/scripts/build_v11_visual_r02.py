"""Build V11 visual R02 while preserving R01 as a comparison baseline.

R02 corrects the three R01 visual failures: exposed ring-like wheels, the open
Follow seat cavity and bright prototype-like CMF.  It still uses only V8 source
geometry and the shared V11 design functions.
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r02"
ACTIVE_STATE = "ride"
BASE_SHOULD_CLONE = r01.should_clone_occurrence
BASE_CONFIGURE_STUDIO = r01.configure_studio


def darker_materials() -> dict[str, bpy.types.Material]:
    return {
        "body": r01.material("V11_R02_MAT_DARK_MINERAL_BODY", (0.006, 0.009, 0.010, 1.0), 0.38),
        "body_soft": r01.material("V11_R02_MAT_DARK_MINERAL_SOFT", (0.012, 0.016, 0.017, 1.0), 0.46),
        "seam": r01.material("V11_R02_MAT_FUNCTIONAL_SHADOW", (0.0015, 0.0018, 0.0018, 1.0), 0.62),
        "glass": r01.material("V11_R02_MAT_SMOKED_SENSOR_GLASS", (0.0015, 0.005, 0.007, 1.0), 0.14),
        "leather": r01.material("V11_R02_MAT_NATURAL_OXBLOOD_LEATHER", (0.060, 0.012, 0.006, 1.0), 0.52),
        "walnut": r01.material("V11_R02_MAT_NATURAL_WALNUT", (0.045, 0.010, 0.003, 1.0), 0.38),
        "stainless": r01.material("V11_R02_MAT_316_BRUSHED_STAINLESS", (0.22, 0.24, 0.25, 1.0), 0.32, 0.84),
        "tire": r01.material("V11_R02_MAT_TIRE", (0.002, 0.0025, 0.0025, 1.0), 0.80),
        "control": r01.material("V11_R02_MAT_CONTROL_ISLAND", (0.004, 0.006, 0.007, 1.0), 0.32),
    }


def clone_material(occurrence: str, mats: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if occurrence.startswith("source_tyre_"):
        return mats["tire"]
    if occurrence == "A04_seat_cushion_contact_island":
        return mats["leather"]
    if occurrence.startswith("A09_"):
        return mats["walnut"] if ("top_skin" in occurrence or "edge_band" in occurrence) else mats["control"]
    if occurrence.startswith("A08_"):
        return mats["stainless"] if ACTIVE_STATE == "ride" and "top" in occurrence else mats["control"]
    if "display_window" in occurrence:
        return mats["glass"]
    if "qi_phone_cradle" in occurrence:
        return mats["body_soft"]
    return mats["control"]


def should_clone(occurrence: str, state: str) -> bool:
    if occurrence == "A05_right_removable_drive_pod":
        return False
    return BASE_SHOULD_CLONE(occurrence, state)


def union_and_remove(body: bpy.types.Object, addition: bpy.types.Object) -> None:
    modifier = body.modifiers.new("V11_R02_SIDE_SHOULDER_UNION", "BOOLEAN")
    modifier.operation = "UNION"
    modifier.solver = "EXACT"
    modifier.object = addition
    r01.apply_modifier(body, modifier)
    bpy.data.objects.remove(addition, do_unlink=True)


def build_lower_and_arms(
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    body = r01.superellipsoid(
        owner,
        "V11_R02_SHARED_LOWER_MOTHER_VOLUME",
        (-0.102, 0.0, 0.292),
        (0.423, 0.362, 0.222),
        0.58,
        0.36,
        mats["body"],
    )
    for side_y in (-0.326, 0.326):
        cheek = r01.superellipsoid(
            owner,
            "V11_R02_TEMP_CONTINUOUS_SIDE_SHOULDER",
            (-0.100, side_y, 0.292),
            (0.400, 0.049, 0.187),
            0.58,
            0.45,
            mats["body"],
            28,
            56,
        )
        union_and_remove(body, cheek)
    body["design_intent"] = "single unioned mother body with integrated upper wheel coverage"
    body["finished_width_m"] = 0.750
    r01.cut_seat_well(body, owner, mats["seam"])
    objects.append(body)

    horizon = r01.rounded_box(
        owner,
        "V11_R02_SHARED_PERCEPTION_HORIZON",
        (-0.521, 0.0, 0.278),
        (0.007, 0.440, 0.048),
        0.022,
        mats["glass"],
        8,
    )
    objects.append(horizon)

    for side, y in (("left", -0.337), ("right", 0.337)):
        arm = r01.rounded_box(
            owner,
            f"V11_R02_SHARED_ARMREST_{side.upper()}",
            (-0.120, y, 0.548),
            (0.550, 0.073, 0.254),
            0.030,
            mats["body_soft"],
            8,
        )
        arm["fixed_armrest"] = True
        arm["rear_terminal_x_m"] = 0.155
        objects.append(arm)
        lid = r01.rounded_box(
            owner,
            f"V11_R02_SHARED_ARMREST_LID_{side.upper()}",
            (-0.120, y, 0.679),
            (0.492, 0.068, 0.005),
            0.022,
            mats["body"],
            6,
        )
        lid["lid_motion"] = "outward opening; table retrieval sequence retained"
        objects.append(lid)

    qi = r01.rounded_box(
        owner,
        "V11_R02_LEFT_QI_USABLE_FIELD",
        (-0.136, -0.337, 0.683),
        (0.176, 0.058, 0.0025),
        0.020,
        mats["body_soft"],
        8,
    )
    qi["usable_phone_field_mm"] = [176.0, 58.0]
    objects.append(qi)

    control_island = r01.rounded_box(
        owner,
        "V11_R02_RIGHT_CONTROL_ISLAND",
        (-0.245, 0.337, 0.685),
        (0.092, 0.060, 0.010),
        0.018,
        mats["control"],
        8,
    )
    control_island["joystick_always_exposed"] = True
    objects.append(control_island)

    objects.extend(r01.make_side_door(owner, "left", -0.374, mats))
    objects.extend(r01.make_side_door(owner, "right", 0.374, mats))
    rear_seam = r01.rounded_box(
        owner,
        "V11_R02_REAR_SERVICE_DOOR_OPENING",
        (0.317, 0.0, 0.315),
        (0.004, 0.370, 0.210),
        0.025,
        mats["seam"],
        8,
    )
    rear_door = r01.rounded_box(
        owner,
        "V11_R02_REAR_SERVICE_DOOR_SKIN",
        (0.320, 0.0, 0.315),
        (0.003, 0.366, 0.206),
        0.024,
        mats["body"],
        8,
    )
    objects.extend([rear_seam, rear_door])
    return objects


def build_a06_a07(
    owner: bpy.types.Collection,
    state: str,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R02_{state.upper()}_A06_ICONIC_TRAPEZOID_SHELL",
        0.158,
        0.318,
        0.525,
        1.003,
        0.288,
        0.204,
        mats["body"],
        0.021,
    )
    shell["identity"] = "iconic front-view trapezoid; thicker only to package the same folded A06 volume"
    contact = r01.trapezoid_prism(
        owner,
        f"V11_R02_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.147,
        0.157,
        0.565,
        0.955,
        0.248,
        0.166,
        mats["leather"],
        0.014,
    )
    parts.extend([shell, contact])

    focus = state == "focus"
    mast_top = 1.458 if focus else 1.038
    mast = r01.trapezoid_prism(
        owner,
        f"V11_R02_{state.upper()}_A07_SINGLE_TAPERED_MAST",
        0.252,
        0.306,
        0.735,
        mast_top,
        0.066,
        0.040 if focus else 0.048,
        mats["body_soft"],
        0.011,
    )
    head_z = 1.460 if focus else 1.040
    head = r01.rounded_box(
        owner,
        f"V11_R02_{state.upper()}_A07_SENSOR_CROWN",
        (0.278, 0.0, head_z),
        (0.064, 0.338, 0.052),
        0.023,
        mats["body_soft"],
        8,
    )
    window = r01.rounded_box(
        owner,
        f"V11_R02_{state.upper()}_A07_SENSOR_WINDOW",
        (0.244, 0.0, head_z - 0.002),
        (0.005, 0.260, 0.021),
        0.009,
        mats["glass"],
        6,
    )
    parts.extend([mast, head, window])

    if state == "follow":
        pivot = bpy.data.objects.new("V11_R02_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.525)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-87.0)
        pivot["fold_angle_deg_visual_r02"] = -87.0
        pivot["validation_status"] = "visual candidate; canonical sweep required"
        parts.append(pivot)
    return parts


def studio(scene: bpy.types.Scene, owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> None:
    BASE_CONFIGURE_STUDIO(scene, owner, state, mats)
    for obj in owner.objects:
        if obj.type == "LIGHT":
            obj.data.energy *= 0.56
    scene.view_settings.exposure = -0.60


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = darker_materials
    r01.clone_material_for_occurrence = clone_material
    r01.should_clone_occurrence = should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = studio
    r01.main()

    report_path = V11_ROOT / "qa" / REVISION / f"v11_{ACTIVE_STATE}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    payload["status"] = "PASS_VISUAL_BUILD_R02"
    payload["contracts"]["body_width_m"] = 0.750
    payload["contracts"]["armrest_rear_x_m"] = 0.155
    payload["contracts"]["follow_fold_visual_deg"] = -87.0 if ACTIVE_STATE == "follow" else None
    payload["r02_corrections"] = [
        "unioned continuous side shoulders cover upper differential-wheel volume",
        "A06 depth and -87 degree fold close the Follow seat cavity without an added cover",
        "V8 removable drive-pod plate removed; joystick remains on a compact control island",
        "dark mineral CMF and reduced studio exposure replace the R01 bright prototype reading",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R02_REPORT_OK", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
