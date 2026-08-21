"""Build V11 R04: continuous wheel-wrapping mother body and compressed A07.

R04 preserves the useful R03 packaging result (the same A06 closes the Follow
seat well) while removing every separate-looking side cover.  Wheel cavities
are cut from inside the lower body and stop before its outer skin, leaving one
unbroken body surface above the tyre contact patches.
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
import build_v11_visual_r03 as r03  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r04"
ACTIVE_STATE = "ride"


def materials() -> dict[str, bpy.types.Material]:
    return {
        "body": r01.material("V11_R04_MAT_DEEP_BRONZE_MINERAL", (0.018, 0.011, 0.007, 1.0), 0.44, 0.025),
        "body_soft": r01.material("V11_R04_MAT_VOLCANIC_BLACK_MINERAL", (0.0028, 0.0036, 0.0040, 1.0), 0.42),
        "seam": r01.material("V11_R04_MAT_FUNCTIONAL_SHADOW", (0.0004, 0.0005, 0.0006, 1.0), 0.78),
        "glass": r01.material("V11_R04_MAT_SMOKED_SENSOR_GLASS", (0.0008, 0.0040, 0.0065, 1.0), 0.15, 0.20),
        "leather": r01.material("V11_R04_MAT_NATURAL_OXBLOOD_LEATHER", (0.032, 0.0045, 0.0020, 1.0), 0.60),
        "shadow_leather": r01.material("V11_R04_MAT_FOLLOW_SHADOW_LEATHER", (0.0025, 0.0018, 0.0015, 1.0), 0.72),
        "walnut": r01.material("V11_R04_MAT_NATURAL_WALNUT_VENEER", (0.030, 0.0065, 0.0020, 1.0), 0.42),
        "stainless": r01.material("V11_R04_MAT_316_BRUSHED_STAINLESS", (0.22, 0.235, 0.24, 1.0), 0.36, 0.90),
        "tire": r01.material("V11_R04_MAT_TIRE", (0.0010, 0.0012, 0.0012, 1.0), 0.88),
        "control": r01.material("V11_R04_MAT_CONTROL_ISLAND", (0.0018, 0.0022, 0.0025, 1.0), 0.34),
    }


def subtract_internal_wheel_cavities(body: bpy.types.Object, owner: bpy.types.Collection) -> None:
    """Cut motion envelopes without piercing the 14 mm outer mother skin."""
    for x_centre in (-0.380, 0.180):
        for sign in (-1.0, 1.0):
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=64,
                radius=0.139,
                depth=0.124,
                location=(x_centre, sign * 0.300, 0.125),
                rotation=(math.pi * 0.5, 0.0, 0.0),
            )
            cutter = bpy.context.object
            cutter.name = "V11_R04_TEMP_INTERNAL_WHEEL_ENVELOPE"
            r01.move_to_collection(cutter, owner)
            modifier = body.modifiers.new("V11_R04_INTERNAL_WHEEL_CAVITY", "BOOLEAN")
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.object = cutter
            r01.apply_modifier(body, modifier)
            bpy.data.objects.remove(cutter, do_unlink=True)


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []

    lower = r01.superellipsoid(
        owner,
        "V11_R04_SHARED_SINGLE_WHEEL_WRAPPING_MOTHER_BODY",
        (-0.100, 0.0, 0.290),
        (0.430, 0.375, 0.205),
        0.54,
        0.34,
        mats["body_soft"],
        40,
        80,
    )
    subtract_internal_wheel_cavities(lower, owner)
    r01.cut_seat_well(lower, owner, mats["seam"])
    lower["source_occurrence_ids"] = "A01,A02,A03,A04"
    lower["outer_skin_policy"] = "unbroken mother body; no discrete fender or side plate"
    lower["wheel_envelope_radius_mm"] = 139.0
    lower["outer_skin_nominal_mm"] = 14.0
    objects.append(lower)

    upper = r01.superellipsoid(
        owner,
        "V11_R04_SHARED_INSET_UPPER_SADDLE",
        (-0.100, 0.0, 0.430),
        (0.415, 0.352, 0.137),
        0.56,
        0.34,
        mats["body"],
        36,
        72,
    )
    r01.cut_seat_well(upper, owner, mats["seam"])
    upper["source_occurrence_ids"] = "A04,A05"
    objects.append(upper)

    perception = r01.rounded_box(
        owner,
        "V11_R04_FLUSH_FRONT_PERCEPTION_HORIZON",
        (-0.529, 0.0, 0.296),
        (0.004, 0.300, 0.026),
        0.011,
        mats["glass"],
        8,
    )
    objects.append(perception)

    arm_profile = [
        (-0.405, 0.438),
        (-0.402, 0.610),
        (-0.365, 0.664),
        (-0.315, 0.682),
        (0.145, 0.682),
        (0.202, 0.647),
        (0.220, 0.585),
        (0.205, 0.470),
        (0.164, 0.430),
        (-0.330, 0.418),
    ]
    for side, y_centre in (("LEFT", -0.328), ("RIGHT", 0.328)):
        arm = r03.polygon_prism_xz(
            owner,
            f"V11_R04_SHARED_FIXED_SCULPTED_ARM_{side}",
            arm_profile,
            y_centre,
            0.094,
            0.018,
            mats["body"],
        )
        arm["fixed_armrest"] = True
        arm["source_occurrence_ids"] = f"A05_armrest_table_bay_shell_{side.lower()}"
        objects.append(arm)
        lid = r03.rounded_rect_curve(
            owner,
            f"V11_R04_SHARED_FLUSH_OUTWARD_LID_SEAM_{side}",
            (-0.010, y_centre, 0.6824),
            0.430,
            0.083,
            0.017,
            "XY",
            mats["seam"],
            0.00055,
        )
        lid["lid_motion"] = "outward flip; retrieve table; close lid"
        objects.append(lid)

    seat = r01.superellipsoid(
        owner,
        "V11_R04_SHARED_NATURAL_LEATHER_SEAT",
        (-0.072, 0.0, 0.479),
        (0.245, 0.260, 0.045),
        0.52,
        0.30,
        mats["shadow_leather"] if ACTIVE_STATE == "follow" else mats["leather"],
        30,
        64,
    )
    seat["seat_contact_width_mm"] = 520.0
    seat["layout_correction"] = "520 mm ergonomic contact width releases 94 mm usable arm package"
    objects.append(seat)

    qi = r01.rounded_box(
        owner,
        "V11_R04_A05_SINGLE_QI_FIELD_176X86",
        (-0.136, -0.328, 0.6830),
        (0.176, 0.086, 0.0010),
        0.017,
        mats["control"],
        8,
    )
    qi["usable_phone_field_mm"] = [176.0, 86.0]
    qi["single_layer"] = True
    objects.append(qi)
    display = r03.display_wedge(owner, mats)
    display.name = "V11_R04_A05_SINGLE_LAYER_DISPLAY_124X49_8DEG"
    display.data.name = "V11_R04_SINGLE_LAYER_DISPLAY_MESH"
    objects.append(display)

    control_plinth = r01.rounded_box(
        owner,
        "V11_R04_A05_INTEGRATED_RIGHT_CONTROL_PLINTH",
        (-0.249, 0.333, 0.6895),
        (0.112, 0.058, 0.015),
        0.012,
        mats["control"],
        8,
    )
    control_plinth["joystick_policy"] = "always exposed at forward right armrest top"
    objects.append(control_plinth)

    for side, y in (("LEFT", -0.3738), ("RIGHT", 0.3738)):
        door_seam = r03.rounded_rect_curve(
            owner,
            f"V11_R04_A04_FLUSH_EQUIPMENT_DOOR_SEAM_{side}",
            (-0.020, y, 0.366),
            0.466,
            0.088,
            0.019,
            "XZ",
            mats["seam"],
            0.00055,
        )
        door_seam["door_skin_mm"] = "464 x 86 R18"
        door_seam["opening_mm"] = "466 x 88 R19"
        door_seam["nominal_seam_mm"] = 1.0
        door_seam["service_travel_mm"] = 300.0
        objects.append(door_seam)

    rear_seam = r03.rounded_rect_curve(
        owner,
        "V11_R04_A10_FLUSH_REAR_SERVICE_DOOR_SEAM",
        (0.3290, 0.0, 0.315),
        0.370,
        0.210,
        0.025,
        "YZ",
        mats["seam"],
        0.00055,
    )
    rear_seam["source_occurrence_ids"] = "A10_rear_service_door"
    objects.append(rear_seam)

    if ACTIVE_STATE != "ride":
        stow_seam = r03.rounded_rect_curve(
            owner,
            "V11_R04_A08_FLUSH_STOWED_FOOTREST_SEAM",
            (-0.5294, 0.0, 0.145),
            0.390,
            0.054,
            0.018,
            "YZ",
            mats["seam"],
            0.00050,
        )
        stow_seam["footrest_state"] = "stowed; no exposed bracket or hanging frame"
        objects.append(stow_seam)
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R04_{state.upper()}_A06_ICONIC_TRAPEZOID",
        0.142,
        0.238,
        0.540,
        1.010,
        0.292,
        0.255,
        mats["body"],
        0.023,
    )
    shell["source_occurrence_ids"] = "A06_backrest_moving_shell"
    shell["identity"] = "same centred front-view trapezoid in every state"
    contact = r01.trapezoid_prism(
        owner,
        f"V11_R04_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.136,
        0.143,
        0.575,
        0.965,
        0.257,
        0.222,
        mats["leather"],
        0.014,
    )
    contact["source_occurrence_ids"] = "A06_backrest_contact_island"
    parts.extend([shell, contact])

    mast = r01.trapezoid_prism(
        owner,
        f"V11_R04_{state.upper()}_A07_SINGLE_COMPRESSED_TAPERED_MAST",
        0.207,
        0.231,
        0.590,
        1.045,
        0.050,
        0.035,
        mats["body_soft"],
        0.008,
    )
    mast["source_occurrence_ids"] = "A07_sensor_mast_moving"
    mast["mast_geometry_contract"] = "identical rigid mesh; Focus translation only"
    head = r01.rounded_box(
        owner,
        f"V11_R04_{state.upper()}_A07_SENSOR_CROWN",
        (0.219, 0.0, 1.045),
        (0.044, 0.310, 0.038),
        0.017,
        mats["body_soft"],
        8,
    )
    head["source_occurrence_ids"] = "A07_sensor_head"
    window = r01.rounded_box(
        owner,
        f"V11_R04_{state.upper()}_A07_SENSOR_WINDOW",
        (0.1955, 0.0, 1.043),
        (0.003, 0.238, 0.016),
        0.007,
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
        pivot = bpy.data.objects.new("V11_R04_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.540)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-90.0)
        pivot["fold_angle_deg"] = -90.0
        pivot["allowed_children"] = "A06 shell/contact + same A07 mast/crown/window only"
        parts.append(pivot)
    return parts


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = materials
    r01.clone_material_for_occurrence = r03.clone_material
    r01.should_clone_occurrence = r03.should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = r03.studio
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
    }
    payload["known_limits"] = [
        "Blender visual decision model; not a production STEP release",
        "saved-file wheel clearance and tyre-exposure gates still required",
        "Ride and Follow visual gates precede Cafe/Focus acceptance",
    ]
    payload["r04_form_changes"] = [
        "removed every discrete side cover and wheel-fender object",
        "wheel motion cavities stop inside a 14 mm continuous outer mother skin",
        "darker low-gloss bronze/volcanic CMF exposes form without prototype silver",
        "A06 front/top taper widened enough to close the Follow seat edges",
        "same A07 mast compressed in X so its Follow dorsal ridge aligns with A06",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R04_BUILT_UNVALIDATED", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
