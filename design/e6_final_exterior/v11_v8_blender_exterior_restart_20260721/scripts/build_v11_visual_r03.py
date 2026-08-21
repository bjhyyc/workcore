"""Build the V11 R03 form-direction gate from immutable V8 references.

R03 deliberately replaces the stacked-box R01/R02 appearance.  The visible
product is organised as a continuous dark lower plinth, a quieter inset upper
saddle, two sculpted fixed arm volumes, and the same A06/A07 rigid pair in all
four states.  The file is still a Blender visual decision model; production
STEP work starts only after the form direction passes review.
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path
from typing import Iterable

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, validate_state  # noqa: E402


REVISION = "r03"
ACTIVE_STATE = "ride"
BASE_CONFIGURE_STUDIO = r01.configure_studio


def materials() -> dict[str, bpy.types.Material]:
    return {
        "body": r01.material("V11_R03_MAT_UPPER_BRONZE_MINERAL", (0.060, 0.040, 0.027, 1.0), 0.46, 0.03),
        "body_soft": r01.material("V11_R03_MAT_LOWER_VOLCANIC_MINERAL", (0.006, 0.008, 0.009, 1.0), 0.39),
        "seam": r01.material("V11_R03_MAT_FUNCTIONAL_SHADOW", (0.0008, 0.0010, 0.0011, 1.0), 0.68),
        "glass": r01.material("V11_R03_MAT_SMOKED_SENSOR_GLASS", (0.0015, 0.0060, 0.0085, 1.0), 0.16, 0.22),
        "leather": r01.material("V11_R03_MAT_NATURAL_OXBLOOD_LEATHER", (0.050, 0.008, 0.004, 1.0), 0.58),
        "shadow_leather": r01.material("V11_R03_MAT_FOLLOW_SHADOW_LEATHER", (0.006, 0.004, 0.003, 1.0), 0.68),
        "walnut": r01.material("V11_R03_MAT_NATURAL_WALNUT_VENEER", (0.045, 0.010, 0.003, 1.0), 0.40),
        "stainless": r01.material("V11_R03_MAT_316_BRUSHED_STAINLESS", (0.26, 0.28, 0.29, 1.0), 0.33, 0.88),
        "tire": r01.material("V11_R03_MAT_TIRE", (0.0015, 0.0018, 0.0018, 1.0), 0.86),
        "control": r01.material("V11_R03_MAT_CONTROL_ISLAND", (0.003, 0.004, 0.005, 1.0), 0.31),
    }


def clone_material(occurrence: str, mats: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if occurrence.startswith("source_tyre_"):
        return mats["tire"]
    if occurrence.startswith("A09_"):
        return mats["walnut"] if ("top_skin" in occurrence or "edge_band" in occurrence) else mats["control"]
    if occurrence.startswith("A08_"):
        return mats["stainless"] if ("top" in occurrence or "tread" not in occurrence) else mats["control"]
    if "emergency_stop" in occurrence:
        return mats["control"]
    return mats["control"]


def should_clone(occurrence: str, state: str) -> bool:
    if occurrence.startswith("source_tyre_"):
        return True
    if state == "ride" and occurrence.startswith("A08_"):
        return True
    if state in {"cafe", "focus"} and occurrence.startswith("A09_"):
        return True
    fixed = {
        "A05_right_joystick",
        "A05_right_authorisation_key",
        "A05_left_mechanical_emergency_stop",
    }
    if state == "follow":
        fixed.update(
            {
                "A05_follow_external_emergency_stop_guard",
                "A05_follow_external_mechanical_emergency_stop",
                "A05_follow_neutral_status_witness",
            }
        )
    return occurrence in fixed


def polygon_prism_xz(
    owner: bpy.types.Collection,
    name: str,
    points: list[tuple[float, float]],
    y_centre: float,
    thickness: float,
    bevel_width: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    y0 = y_centre - thickness * 0.5
    y1 = y_centre + thickness * 0.5
    vertices = [(x, y0, z) for x, z in points] + [(x, y1, z) for x, z in points]
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
    bevel = obj.modifiers.new("V11_R03_SCULPTED_CONTINUITY", "BEVEL")
    bevel.width = bevel_width
    bevel.segments = 8
    bevel.limit_method = "ANGLE"
    r01.apply_modifier(obj, bevel)
    r01.set_smooth(obj)
    return obj


def rounded_rectangle_points(width: float, height: float, radius: float, segments: int = 8) -> list[tuple[float, float]]:
    half_w = width * 0.5
    half_h = height * 0.5
    r = min(radius, half_w, half_h)
    centres = [
        (half_w - r, half_h - r, 0.0),
        (-half_w + r, half_h - r, math.pi * 0.5),
        (-half_w + r, -half_h + r, math.pi),
        (half_w - r, -half_h + r, math.pi * 1.5),
    ]
    points: list[tuple[float, float]] = []
    for cx, cy, start in centres:
        for step in range(segments + 1):
            angle = start + (math.pi * 0.5) * step / segments
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def rounded_rect_curve(
    owner: bpy.types.Collection,
    name: str,
    centre: tuple[float, float, float],
    width: float,
    height: float,
    radius: float,
    plane: str,
    mat: bpy.types.Material,
    line_width: float = 0.0008,
) -> bpy.types.Object:
    cx, cy, cz = centre
    outline = rounded_rectangle_points(width, height, radius)
    curve = bpy.data.curves.new(name + "_CURVE", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = line_width * 0.5
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(outline) - 1)
    for target, (u, v) in zip(spline.points, outline):
        if plane == "XZ":
            target.co = (cx + u, cy, cz + v, 1.0)
        elif plane == "YZ":
            target.co = (cx, cy + u, cz + v, 1.0)
        elif plane == "XY":
            target.co = (cx + u, cy + v, cz, 1.0)
        else:
            raise ValueError(plane)
    spline.use_cyclic_u = True
    curve.materials.append(mat)
    obj = bpy.data.objects.new(name, curve)
    owner.objects.link(obj)
    return obj


def subtract_wheel_envelopes(body: bpy.types.Object, owner: bpy.types.Collection) -> None:
    for x_centre in (-0.380, 0.180):
        for y_centre in (-0.317, 0.317):
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=64,
                radius=0.139,
                depth=0.154,
                location=(x_centre, y_centre, 0.125),
                rotation=(math.pi * 0.5, 0.0, 0.0),
            )
            cutter = bpy.context.object
            cutter.name = "V11_R03_TEMP_WHEEL_MOTION_ENVELOPE"
            r01.move_to_collection(cutter, owner)
            modifier = body.modifiers.new("V11_R03_TRUE_WHEEL_CAVITY", "BOOLEAN")
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.object = cutter
            r01.apply_modifier(body, modifier)
            bpy.data.objects.remove(cutter, do_unlink=True)


def display_wedge(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    x_front, x_rear = -0.356, -0.232
    y0, y1 = -0.3525, -0.3035
    bottom = 0.6820
    rear_top = 0.6830
    front_top = rear_top + (x_rear - x_front) * math.tan(math.radians(8.0))
    vertices = [
        (x_front, y0, bottom),
        (x_front, y1, bottom),
        (x_rear, y1, bottom),
        (x_rear, y0, bottom),
        (x_front, y0, front_top),
        (x_front, y1, front_top),
        (x_rear, y1, rear_top),
        (x_rear, y0, rear_top),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new("V11_R03_SINGLE_LAYER_DISPLAY_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(mats["glass"])
    obj = bpy.data.objects.new("V11_R03_A05_SINGLE_LAYER_DISPLAY_124X49_8DEG", mesh)
    owner.objects.link(obj)
    bevel = obj.modifiers.new("V11_R03_DISPLAY_EDGE", "BEVEL")
    bevel.width = 0.0012
    bevel.segments = 5
    bevel.limit_method = "ANGLE"
    r01.apply_modifier(obj, bevel)
    r01.set_smooth(obj)
    obj["display_contract_mm"] = "124 x 49"
    obj["display_pitch_world_y_deg"] = 8.0
    obj["display_slope"] = "front high; rear low"
    return obj


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []

    lower = r01.superellipsoid(
        owner,
        "V11_R03_SHARED_LOWER_CONTINUOUS_PLINTH",
        (-0.100, 0.0, 0.290),
        (0.430, 0.360, 0.205),
        0.54,
        0.34,
        mats["body_soft"],
        40,
        80,
    )
    subtract_wheel_envelopes(lower, owner)
    r01.cut_seat_well(lower, owner, mats["seam"])
    lower["source_occurrence_ids"] = "A01,A02,A03,A04"
    lower["wheel_cavity_radial_clearance_mm"] = 14.0
    objects.append(lower)

    upper = r01.superellipsoid(
        owner,
        "V11_R03_SHARED_INSET_UPPER_SADDLE",
        (-0.100, 0.0, 0.430),
        (0.415, 0.348, 0.137),
        0.56,
        0.34,
        mats["body"],
        36,
        72,
    )
    r01.cut_seat_well(upper, owner, mats["seam"])
    upper["source_occurrence_ids"] = "A04,A05"
    objects.append(upper)

    for side, y_centre in (("LEFT", -0.369), ("RIGHT", 0.369)):
        skin = r01.rounded_box(
            owner,
            f"V11_R03_SHARED_CONTINUOUS_SIDE_SKIN_{side}",
            (-0.100, y_centre, 0.258),
            (0.840, 0.012, 0.335),
            0.058,
            mats["body_soft"],
            10,
        )
        skin["wheel_wrap_policy"] = "single body mother surface; no separate wheel fender"
        objects.append(skin)

    perception = r01.rounded_box(
        owner,
        "V11_R03_FLUSH_FRONT_PERCEPTION_HORIZON",
        (-0.529, 0.0, 0.296),
        (0.004, 0.310, 0.030),
        0.013,
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
        arm = polygon_prism_xz(
            owner,
            f"V11_R03_SHARED_FIXED_SCULPTED_ARM_{side}",
            arm_profile,
            y_centre,
            0.094,
            0.018,
            mats["body"],
        )
        arm["fixed_armrest"] = True
        arm["source_occurrence_ids"] = f"A05_armrest_table_bay_shell_{side.lower()}"
        objects.append(arm)
        lid = rounded_rect_curve(
            owner,
            f"V11_R03_SHARED_FLUSH_OUTWARD_LID_SEAM_{side}",
            (-0.010, y_centre, 0.6826),
            0.430,
            0.083,
            0.017,
            "XY",
            mats["seam"],
            0.0008,
        )
        lid["lid_motion"] = "outward flip; retrieve table; close lid"
        objects.append(lid)

    seat = r01.superellipsoid(
        owner,
        "V11_R03_SHARED_NATURAL_LEATHER_SEAT",
        (-0.072, 0.0, 0.479),
        (0.245, 0.260, 0.045),
        0.52,
        0.30,
        mats["shadow_leather"] if ACTIVE_STATE == "follow" else mats["leather"],
        30,
        64,
    )
    seat["seat_contact_width_mm"] = 520.0
    seat["layout_correction"] = "narrowed from V8 visual cushion to release 94 mm usable arm width"
    objects.append(seat)

    qi = r01.rounded_box(
        owner,
        "V11_R03_A05_SINGLE_QI_FIELD_176X86",
        (-0.136, -0.328, 0.6832),
        (0.176, 0.086, 0.0012),
        0.017,
        mats["control"],
        8,
    )
    qi["usable_phone_field_mm"] = [176.0, 86.0]
    qi["single_layer"] = True
    objects.append(qi)
    objects.append(display_wedge(owner, mats))

    control_plinth = r01.rounded_box(
        owner,
        "V11_R03_A05_INTEGRATED_RIGHT_CONTROL_PLINTH",
        (-0.249, 0.333, 0.6895),
        (0.112, 0.058, 0.015),
        0.012,
        mats["control"],
        8,
    )
    control_plinth["joystick_policy"] = "always exposed at forward right armrest top"
    objects.append(control_plinth)

    for side, y in (("LEFT", -0.3740), ("RIGHT", 0.3740)):
        door_seam = rounded_rect_curve(
            owner,
            f"V11_R03_A04_FLUSH_EQUIPMENT_DOOR_SEAM_{side}",
            (-0.020, y, 0.366),
            0.466,
            0.088,
            0.019,
            "XZ",
            mats["seam"],
            0.0010,
        )
        door_seam["door_skin_mm"] = "464 x 86 R18"
        door_seam["opening_mm"] = "466 x 88 R19"
        door_seam["nominal_seam_mm"] = 1.0
        door_seam["service_travel_mm"] = 300.0
        objects.append(door_seam)

    rear_seam = rounded_rect_curve(
        owner,
        "V11_R03_A10_FLUSH_REAR_SERVICE_DOOR_SEAM",
        (0.3290, 0.0, 0.315),
        0.370,
        0.210,
        0.025,
        "YZ",
        mats["seam"],
        0.0010,
    )
    rear_seam["source_occurrence_ids"] = "A10_rear_service_door"
    objects.append(rear_seam)

    if ACTIVE_STATE != "ride":
        stow_seam = rounded_rect_curve(
            owner,
            "V11_R03_A08_FLUSH_STOWED_FOOTREST_SEAM",
            (-0.5295, 0.0, 0.145),
            0.390,
            0.054,
            0.018,
            "YZ",
            mats["seam"],
            0.0009,
        )
        stow_seam["footrest_state"] = "stowed; no exposed bracket or hanging frame"
        objects.append(stow_seam)

    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R03_{state.upper()}_A06_ICONIC_TRAPEZOID",
        0.142,
        0.238,
        0.540,
        1.010,
        0.292,
        0.245,
        mats["body"],
        0.023,
    )
    shell["source_occurrence_ids"] = "A06_backrest_moving_shell"
    shell["identity"] = "same front-view trapezoid in all four states"
    contact = r01.trapezoid_prism(
        owner,
        f"V11_R03_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.136,
        0.143,
        0.575,
        0.965,
        0.257,
        0.214,
        mats["leather"],
        0.014,
    )
    contact["source_occurrence_ids"] = "A06_backrest_contact_island"
    parts.extend([shell, contact])

    mast = r01.trapezoid_prism(
        owner,
        f"V11_R03_{state.upper()}_A07_SINGLE_TAPERED_MAST",
        0.214,
        0.255,
        0.590,
        1.045,
        0.055,
        0.038,
        mats["body_soft"],
        0.010,
    )
    mast["source_occurrence_ids"] = "A07_sensor_mast_moving"
    mast["mast_geometry_contract"] = "identical rigid mesh; Focus translation only"
    head = r01.rounded_box(
        owner,
        f"V11_R03_{state.upper()}_A07_SENSOR_CROWN",
        (0.235, 0.0, 1.045),
        (0.058, 0.326, 0.046),
        0.020,
        mats["body_soft"],
        8,
    )
    head["source_occurrence_ids"] = "A07_sensor_head"
    window = r01.rounded_box(
        owner,
        f"V11_R03_{state.upper()}_A07_SENSOR_WINDOW",
        (0.2045, 0.0, 1.043),
        (0.003, 0.250, 0.019),
        0.008,
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
        pivot = bpy.data.objects.new("V11_R03_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.540)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-90.0)
        pivot["fold_angle_deg"] = -90.0
        pivot["allowed_children"] = "A06 shell/contact + same A07 mast/crown/window only"
        parts.append(pivot)
    return parts


def studio(scene: bpy.types.Scene, owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> None:
    BASE_CONFIGURE_STUDIO(scene, owner, state, mats)
    if scene.world and scene.world.use_nodes:
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.028, 0.026, 0.024, 1.0)
            background.inputs["Strength"].default_value = 0.48
    light_settings = {
        "V11_KEY": (920.0, (1.0, 0.92, 0.82)),
        "V11_FILL": (560.0, (0.78, 0.86, 1.0)),
        "V11_RIM": (760.0, (1.0, 0.74, 0.58)),
    }
    for name, (energy, colour) in light_settings.items():
        light = bpy.data.objects.get(name)
        if light and light.type == "LIGHT":
            light.data.energy = energy
            light.data.color = colour
    scene.view_settings.exposure = -0.30


def evaluated_product_bounds() -> dict[str, list[float] | float]:
    product_objects = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type in {"MESH", "CURVE"}
        and obj.library is None
        and not bool(obj.get("not_product_geometry", False))
        and not obj.hide_render
    ]
    minima = [float("inf")] * 3
    maxima = [float("-inf")] * 3
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in product_objects:
        if obj.type == "CURVE":
            points = []
            for spline in obj.data.splines:
                for point in spline.points:
                    points.append(obj.matrix_world @ Vector(point.co[:3]))
            padding = float(obj.data.bevel_depth)
        else:
            evaluated = obj.evaluated_get(depsgraph)
            points = [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
            padding = 0.0
        if not points:
            continue
        for axis in range(3):
            minima[axis] = min(minima[axis], *(float(point[axis]) - padding for point in points))
            maxima[axis] = max(maxima[axis], *(float(point[axis]) + padding for point in points))
    size = [maxima[index] - minima[index] for index in range(3)]
    return {"minimum_m": minima, "maximum_m": maxima, "size_m": size, "finished_width_m": size[1]}


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = materials
    r01.clone_material_for_occurrence = clone_material
    r01.should_clone_occurrence = should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = studio
    r01.main()

    report_path = V11_ROOT / "qa" / REVISION / f"v11_{ACTIVE_STATE}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    measured = evaluated_product_bounds()
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
        "wheel cavity and outer coverage require saved-file intersection and visibility gates",
        "visual review must pass Ride and Follow before Cafe/Focus can be accepted",
    ]
    payload["r03_form_changes"] = [
        "continuous side skins hide the upper wheel volumes without separate fenders",
        "flush curve-only A04/A10 seams replace pasted door plates",
        "sculpted fixed arms replace rectangular walls and retain an exposed right joystick",
        "same A06/A07 geometry is upright, translated +420 mm, or rigidly folded -90 degrees",
        "single 124x49 display wedge is pitched +8 degrees world Y; single 176x86 Qi field",
        "Follow seat uses shadow leather only as the same folded A06 closes above it",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R03_BUILT_UNVALIDATED", ACTIVE_STATE, report_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
