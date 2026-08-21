"""Build V11 R06 with lofted arm volumes and production-intent dark CMF."""

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
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r06"
ACTIVE_STATE = "ride"


def tuned_material(
    name: str,
    colour: tuple[float, float, float, float],
    roughness: float,
    metallic: float = 0.0,
    specular: float = 0.22,
) -> bpy.types.Material:
    mat = r01.material(name, colour, roughness, metallic)
    node = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if node:
        if node.inputs.get("Specular IOR Level"):
            node.inputs["Specular IOR Level"].default_value = specular
        if node.inputs.get("Coat Weight"):
            node.inputs["Coat Weight"].default_value = 0.025 if metallic < 0.5 else 0.01
    return mat


def materials() -> dict[str, bpy.types.Material]:
    return {
        "body": tuned_material("V11_R06_MAT_WARM_GRAPHITE_MINERAL", (0.0048, 0.0040, 0.0034, 1.0), 0.56, 0.02, 0.19),
        "body_soft": tuned_material("V11_R06_MAT_VOLCANIC_BLACK_MINERAL", (0.0012, 0.0015, 0.0017, 1.0), 0.52, 0.0, 0.16),
        "seam": tuned_material("V11_R06_MAT_FUNCTIONAL_SHADOW", (0.00018, 0.00020, 0.00022, 1.0), 0.88, 0.0, 0.10),
        "glass": tuned_material("V11_R06_MAT_SMOKED_SENSOR_GLASS", (0.0005, 0.0026, 0.0044, 1.0), 0.17, 0.20, 0.38),
        "leather": tuned_material("V11_R06_MAT_NATURAL_OXBLOOD_LEATHER", (0.022, 0.0028, 0.0012, 1.0), 0.68, 0.0, 0.20),
        "shadow_leather": tuned_material("V11_R06_MAT_FOLLOW_SHADOW_LEATHER", (0.0012, 0.0008, 0.0007, 1.0), 0.78, 0.0, 0.12),
        "walnut": tuned_material("V11_R06_MAT_NATURAL_WALNUT_VENEER", (0.024, 0.0048, 0.0015, 1.0), 0.48, 0.0, 0.24),
        "stainless": tuned_material("V11_R06_MAT_316_BRUSHED_STAINLESS", (0.18, 0.19, 0.195, 1.0), 0.42, 0.90, 0.32),
        "tire": tuned_material("V11_R06_MAT_TIRE", (0.00055, 0.00065, 0.00065, 1.0), 0.94, 0.0, 0.08),
        "control": tuned_material("V11_R06_MAT_CONTROL_ISLAND", (0.0010, 0.0012, 0.0014, 1.0), 0.44, 0.0, 0.18),
    }


def lofted_arm(
    owner: bpy.types.Collection,
    name: str,
    y_centre: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    # x, bottom-z, top-z, half-width-y.  The long middle remains flat enough
    # for HMI and lid packaging; only the last 35 mm dissolves into the rear.
    stations = [
        (-0.405, 0.438, 0.652, 0.040),
        (-0.360, 0.425, 0.681, 0.047),
        (-0.300, 0.418, 0.682, 0.047),
        (0.120, 0.428, 0.682, 0.044),
        (0.182, 0.445, 0.680, 0.039),
        (0.220, 0.470, 0.600, 0.026),
    ]
    ring_segments = 48
    exponent = 0.10
    vertices: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []
    for x, z_bottom, z_top, half_y in stations:
        z_centre = (z_bottom + z_top) * 0.5
        half_z = (z_top - z_bottom) * 0.5
        ring: list[int] = []
        for index in range(ring_segments):
            angle = 2.0 * math.pi * index / ring_segments
            c = math.cos(angle)
            s = math.sin(angle)
            y = y_centre + half_y * math.copysign(abs(c) ** exponent, c)
            z = z_centre + half_z * math.copysign(abs(s) ** exponent, s)
            ring.append(len(vertices))
            vertices.append((x, y, z))
        rings.append(ring)
    faces: list[tuple[int, ...]] = []
    faces.append(tuple(reversed(rings[0])))
    for left, right in zip(rings[:-1], rings[1:]):
        for index in range(ring_segments):
            nxt = (index + 1) % ring_segments
            faces.append((left[index], left[nxt], right[nxt], right[index]))
    faces.append(tuple(rings[-1]))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    r01.set_smooth(obj)
    obj["arm_generation"] = "six-station superelliptic loft"
    obj["outer_width_limit_m"] = 0.375
    return obj


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = r05.build_lower_and_arms(owner, mats)
    for side in ("LEFT", "RIGHT"):
        old = bpy.data.objects.get(f"V11_R05_SHARED_FIXED_SCULPTED_ARM_{side}")
        if old is not None:
            if old in objects:
                objects.remove(old)
            bpy.data.objects.remove(old, do_unlink=True)
        old_lid = bpy.data.objects.get(f"V11_R05_SHARED_FLUSH_OUTWARD_LID_SEAM_{side}")
        if old_lid is not None:
            if old_lid in objects:
                objects.remove(old_lid)
            bpy.data.objects.remove(old_lid, do_unlink=True)

    for side, y_centre in (("LEFT", -0.328), ("RIGHT", 0.328)):
        arm = lofted_arm(owner, f"V11_R06_SHARED_FIXED_LOFTED_ARM_{side}", y_centre, mats["body"])
        arm["fixed_armrest"] = True
        arm["source_occurrence_ids"] = f"A05_armrest_table_bay_shell_{side.lower()}"
        objects.append(arm)
        lid = r03.rounded_rect_curve(
            owner,
            f"V11_R06_SHARED_FLUSH_OUTWARD_LID_SEAM_{side}",
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
            obj.name = obj.name.replace("R05", "R06")
        if getattr(obj, "data", None) is not None and "R05" in obj.data.name:
            obj.data.name = obj.data.name.replace("R05", "R06")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts = r05.build_a06_a07(owner, state, mats)
    for obj in parts:
        if "R05" in obj.name:
            obj.name = obj.name.replace("R05", "R06")
        if getattr(obj, "data", None) is not None and "R05" in obj.data.name:
            obj.data.name = obj.data.name.replace("R05", "R06")
    return parts


def studio(scene: bpy.types.Scene, owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> None:
    r05.studio(scene, owner, state, mats)
    scene.view_settings.exposure = -0.35


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r05.ACTIVE_STATE = ACTIVE_STATE
    r04.ACTIVE_STATE = ACTIVE_STATE
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = materials
    r01.clone_material_for_occurrence = r03.clone_material
    r01.should_clone_occurrence = r05.should_clone
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
        "saved-file geometry and tyre-visibility gates must still pass",
        "Cafe/Focus tables remain V8 motion references until the shared form is accepted",
    ]
    payload["r06_form_changes"] = [
        "flat extruded arm walls replaced by six-station lofted fixed volumes",
        "arm tail dissolves into the rear shoulder without any thin extension",
        "low-specular graphite mineral prevents pale painted-prototype highlights",
        "R05 A06/A07/seat/footrest layout retained without adding Follow covers",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R06_BUILT_UNVALIDATED", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
