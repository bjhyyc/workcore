"""Build V11 R05, the first full Ride/Follow form-direction candidate.

Changes from R04 are deliberately subtractive: the wheel cover becomes part of
the lower body's own unioned volume, the V8 exposed footrest stack is replaced
by one clean skin at the same working envelope, the seat narrows toward the
front so the same stronger trapezoidal A06 closes it in Follow, and A07 becomes
a thin exposed blade rather than a headrest-like column.
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
import build_v11_visual_r04 as r04  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r05"
ACTIVE_STATE = "ride"


def materials() -> dict[str, bpy.types.Material]:
    return {
        "body": r01.material("V11_R05_MAT_SMOKED_BRONZE_MINERAL", (0.0115, 0.0068, 0.0042, 1.0), 0.48, 0.025),
        "body_soft": r01.material("V11_R05_MAT_VOLCANIC_BLACK_MINERAL", (0.0022, 0.0028, 0.0031, 1.0), 0.46),
        "seam": r01.material("V11_R05_MAT_FUNCTIONAL_SHADOW", (0.00025, 0.00030, 0.00035, 1.0), 0.82),
        "glass": r01.material("V11_R05_MAT_SMOKED_SENSOR_GLASS", (0.0006, 0.0030, 0.0050, 1.0), 0.16, 0.18),
        "leather": r01.material("V11_R05_MAT_NATURAL_OXBLOOD_LEATHER", (0.024, 0.0032, 0.0014, 1.0), 0.62),
        "shadow_leather": r01.material("V11_R05_MAT_FOLLOW_SHADOW_LEATHER", (0.0018, 0.0012, 0.0010, 1.0), 0.74),
        "walnut": r01.material("V11_R05_MAT_NATURAL_WALNUT_VENEER", (0.026, 0.0055, 0.0018, 1.0), 0.44),
        "stainless": r01.material("V11_R05_MAT_316_BRUSHED_STAINLESS", (0.20, 0.215, 0.22, 1.0), 0.38, 0.90),
        "tire": r01.material("V11_R05_MAT_TIRE", (0.0008, 0.0009, 0.0009, 1.0), 0.90),
        "control": r01.material("V11_R05_MAT_CONTROL_ISLAND", (0.0014, 0.0017, 0.0019, 1.0), 0.38),
    }


def should_clone(occurrence: str, state: str) -> bool:
    if occurrence.startswith("source_tyre_"):
        return True
    if state in {"cafe", "focus"} and occurrence.startswith("A09_"):
        return True
    return occurrence in {
        "A05_right_joystick",
        "A05_right_authorisation_key",
        "A05_left_mechanical_emergency_stop",
    }


def polygon_prism_xy(
    owner: bpy.types.Collection,
    name: str,
    points: list[tuple[float, float]],
    z_bottom: float,
    z_top: float,
    bevel_width: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    vertices = [(x, y, z_bottom) for x, y in points] + [(x, y, z_top) for x, y in points]
    count = len(points)
    faces: list[tuple[int, ...]] = [tuple(reversed(range(count))), tuple(range(count, 2 * count))]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    bevel = obj.modifiers.new("V11_R05_CUSHION_CONTINUITY", "BEVEL")
    bevel.width = bevel_width
    bevel.segments = 10
    bevel.limit_method = "ANGLE"
    r01.apply_modifier(obj, bevel)
    r01.set_smooth(obj)
    return obj


def union_into(body: bpy.types.Object, addition: bpy.types.Object, name: str) -> None:
    modifier = body.modifiers.new(name, "BOOLEAN")
    modifier.operation = "UNION"
    modifier.solver = "EXACT"
    modifier.object = addition
    r01.apply_modifier(body, modifier)
    bpy.data.objects.remove(addition, do_unlink=True)


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = r04.build_lower_and_arms(owner, mats)
    lower = bpy.data.objects.get("V11_R04_SHARED_SINGLE_WHEEL_WRAPPING_MOTHER_BODY")
    if lower is None:
        raise RuntimeError("R05: lower mother body missing")

    for y_centre in (-0.325, 0.325):
        lobe = r01.superellipsoid(
            owner,
            "V11_R05_TEMP_CONTINUOUS_SIDE_LOBE",
            (-0.100, y_centre, 0.265),
            (0.425, 0.050, 0.190),
            0.46,
            0.28,
            mats["body_soft"],
            34,
            68,
        )
        union_into(lower, lobe, "V11_R05_UNIONED_WHEEL_SHOULDER")
    r04.subtract_internal_wheel_cavities(lower, owner)
    lower["wheel_wrap_policy_r05"] = "two broad lobes permanently unioned into one lower body; no fender objects"

    old_seat = bpy.data.objects.get("V11_R04_SHARED_NATURAL_LEATHER_SEAT")
    if old_seat is not None:
        if old_seat in objects:
            objects.remove(old_seat)
        bpy.data.objects.remove(old_seat, do_unlink=True)
    seat = polygon_prism_xy(
        owner,
        "V11_R05_SHARED_TAPERED_NATURAL_LEATHER_SEAT",
        [(-0.315, -0.225), (-0.315, 0.225), (0.165, 0.258), (0.165, -0.258)],
        0.438,
        0.520,
        0.034,
        mats["shadow_leather"] if ACTIVE_STATE == "follow" else mats["leather"],
    )
    seat["front_contact_width_mm"] = 450.0
    seat["rear_contact_width_mm"] = 516.0
    seat["closure_reason"] = "front taper is ergonomically usable and fits beneath the same folded A06"
    objects.append(seat)

    if ACTIVE_STATE == "ride":
        root = r01.rounded_box(
            owner,
            "V11_R05_A08_INTEGRATED_FOOTREST_ROOT",
            (-0.500, 0.0, 0.124),
            (0.055, 0.500, 0.060),
            0.021,
            mats["body_soft"],
            8,
        )
        platform = r01.rounded_box(
            owner,
            "V11_R05_A08_SINGLE_SKIN_DEPLOYED_FOOTREST",
            (-0.605, 0.0, 0.083),
            (0.205, 0.492, 0.050),
            0.022,
            mats["body"],
            10,
        )
        tread = r01.rounded_box(
            owner,
            "V11_R05_A08_NATURAL_RUBBER_TREAD_INLAY",
            (-0.605, 0.0, 0.109),
            (0.170, 0.430, 0.003),
            0.019,
            mats["control"],
            8,
        )
        platform["deployed_envelope_source"] = "V8 A08 bounds"
        platform["default_state"] = "open in Ride"
        root["stow_motion"] = "single inward rotation into flush front bay"
        objects.extend([root, platform, tread])

    for obj in objects:
        if "R04" in obj.name:
            obj.name = obj.name.replace("R04", "R05")
        if getattr(obj, "data", None) is not None and "R04" in obj.data.name:
            obj.data.name = obj.data.name.replace("R04", "R05")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R05_{state.upper()}_A06_ICONIC_TRAPEZOID",
        0.142,
        0.238,
        0.540,
        1.010,
        0.292,
        0.235,
        mats["body"],
        0.023,
    )
    shell["source_occurrence_ids"] = "A06_backrest_moving_shell"
    shell["identity"] = "stronger centred trapezoid; same rigid mesh in every state"
    contact = r01.trapezoid_prism(
        owner,
        f"V11_R05_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.136,
        0.143,
        0.575,
        0.965,
        0.257,
        0.202,
        mats["leather"],
        0.014,
    )
    contact["source_occurrence_ids"] = "A06_backrest_contact_island"
    parts.extend([shell, contact])

    mast = r01.trapezoid_prism(
        owner,
        f"V11_R05_{state.upper()}_A07_EXPOSED_TAPERED_BLADE",
        0.226,
        0.244,
        0.590,
        1.045,
        0.050,
        0.035,
        mats["body_soft"],
        0.006,
    )
    mast["source_occurrence_ids"] = "A07_sensor_mast_moving"
    mast["mast_geometry_contract"] = "same exposed trapezoid blade; Focus translates only"
    head = r01.rounded_box(
        owner,
        f"V11_R05_{state.upper()}_A07_SENSOR_CROWN",
        (0.235, 0.0, 1.045),
        (0.032, 0.285, 0.034),
        0.015,
        mats["body_soft"],
        8,
    )
    head["source_occurrence_ids"] = "A07_sensor_head"
    window = r01.rounded_box(
        owner,
        f"V11_R05_{state.upper()}_A07_SENSOR_WINDOW",
        (0.2180, 0.0, 1.043),
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
        pivot = bpy.data.objects.new("V11_R05_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.540)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-90.0)
        pivot["fold_angle_deg"] = -90.0
        pivot["allowed_children"] = "A06 shell/contact + same A07 blade/crown/window only"
        parts.append(pivot)
    return parts


def studio(scene: bpy.types.Scene, owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> None:
    r03.studio(scene, owner, state, mats)
    light_settings = {"V11_KEY": 680.0, "V11_FILL": 380.0, "V11_RIM": 520.0}
    for name, energy in light_settings.items():
        light = bpy.data.objects.get(name)
        if light and light.type == "LIGHT":
            light.data.energy = energy
    if scene.world and scene.world.use_nodes:
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Strength"].default_value = 0.30
    scene.view_settings.exposure = -0.55


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r04.ACTIVE_STATE = ACTIVE_STATE
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = materials
    r01.clone_material_for_occurrence = r03.clone_material
    r01.should_clone_occurrence = should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = studio
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
        "saved-file geometry, wheel clearance and visibility gates still required",
        "Cafe and Focus are generated only after Ride/Follow form review",
    ]
    payload["r05_form_changes"] = [
        "broad wheel shoulders are boolean-unioned into the lower mother body",
        "new tapered seat and stronger same-part A06 close Follow without a hood",
        "A07 is a slim externally visible trapezoid blade in all states",
        "Ride footrest is one clean rounded skin at the V8 operating envelope",
        "Follow-only external safety protrusions were removed from the width envelope",
        "smoked bronze, oxblood leather and volcanic mineral replace pale prototype CMF",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R05_BUILT_UNVALIDATED", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
