"""Build V11 visual R01 from immutable V8 references.

R01 is the first fresh exterior proposal.  It replaces the visible V8 skin
with one continuous lower mother volume, integrated wheel coverage, compact
fixed armrests, a slim iconic A06 trapezoid and one tapered A07 mast.  It does
not import any V9 or V10 geometry.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Iterable

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from v11_common import (  # noqa: E402
    PIPELINE_ID,
    PREVIEW_ROOT,
    V11_ROOT,
    atomic_write_json,
    read_json,
    reference_library_path,
    reference_library_report_path,
    sha256,
    state_blend_path,
    validate_source,
    validate_state,
)


REVISION = "r01"
REPORT_ROOT = V11_ROOT / "qa" / REVISION


def args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    return parser.parse_args(argv)


def new_child(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
    result = bpy.data.collections.new(name)
    parent.children.link(result)
    return result


def move_to_collection(obj: bpy.types.Object, owner: bpy.types.Collection) -> None:
    if owner not in obj.users_collection:
        owner.objects.link(obj)
    for existing in tuple(obj.users_collection):
        if existing != owner:
            existing.objects.unlink(obj)


def material(
    name: str,
    colour: tuple[float, float, float, float],
    roughness: float,
    metallic: float = 0.0,
) -> bpy.types.Material:
    result = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    result.use_nodes = True
    result.diffuse_color = colour
    node = result.node_tree.nodes.get("Principled BSDF") if result.node_tree else None
    if node:
        if node.inputs.get("Base Color"):
            node.inputs["Base Color"].default_value = colour
        if node.inputs.get("Roughness"):
            node.inputs["Roughness"].default_value = roughness
        if node.inputs.get("Metallic"):
            node.inputs["Metallic"].default_value = metallic
        if node.inputs.get("Coat Weight"):
            node.inputs["Coat Weight"].default_value = 0.08 if metallic < 0.5 else 0.02
    return result


def build_materials() -> dict[str, bpy.types.Material]:
    return {
        "body": material("V11_MAT_DARK_MINERAL_BODY", (0.025, 0.031, 0.032, 1.0), 0.32),
        "body_soft": material("V11_MAT_DARK_MINERAL_SOFT", (0.045, 0.050, 0.049, 1.0), 0.43),
        "seam": material("V11_MAT_FUNCTIONAL_SHADOW", (0.004, 0.005, 0.005, 1.0), 0.58),
        "glass": material("V11_MAT_SMOKED_SENSOR_GLASS", (0.006, 0.012, 0.014, 1.0), 0.12),
        "leather": material("V11_MAT_NATURAL_OXBLOOD_LEATHER", (0.155, 0.045, 0.028, 1.0), 0.48),
        "walnut": material("V11_MAT_NATURAL_WALNUT", (0.105, 0.032, 0.012, 1.0), 0.34),
        "stainless": material("V11_MAT_316_BRUSHED_STAINLESS", (0.34, 0.36, 0.37, 1.0), 0.27, 0.86),
        "tire": material("V11_MAT_TIRE", (0.008, 0.009, 0.009, 1.0), 0.76),
        "control": material("V11_MAT_CONTROL_ISLAND", (0.018, 0.020, 0.021, 1.0), 0.28),
    }


def assign_object_material(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    if obj.type != "MESH":
        return
    if len(obj.material_slots) == 0:
        return
    for slot in obj.material_slots:
        slot.link = "OBJECT"
        slot.material = mat


def clone_material_for_occurrence(occurrence: str, mats: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if occurrence.startswith("source_tyre_"):
        return mats["tire"]
    if occurrence == "A04_seat_cushion_contact_island":
        return mats["leather"]
    if occurrence.startswith("A09_"):
        if "top_skin" in occurrence or "edge_band" in occurrence:
            return mats["walnut"]
        return mats["control"]
    if occurrence.startswith("A08_"):
        if "tread" in occurrence:
            return mats["control"]
        return mats["stainless"]
    if "display_window" in occurrence:
        return mats["glass"]
    if "qi_phone_cradle" in occurrence:
        return mats["body_soft"]
    return mats["control"]


def should_clone_occurrence(occurrence: str, state: str) -> bool:
    if occurrence.startswith("source_tyre_"):
        return True
    if occurrence == "A04_seat_cushion_contact_island":
        return True
    if occurrence.startswith(("A08_", "A09_")):
        return True
    fixed = {
        "A05_right_joystick",
        "A05_right_authorisation_key",
        "A05_right_removable_drive_pod",
        "A05_left_status_display_window",
        "A05_left_mechanical_emergency_stop",
        "A05_left_qi_phone_cradle",
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


def find_layer_collection(root: bpy.types.LayerCollection, name: str) -> bpy.types.LayerCollection | None:
    if root.collection.name == name:
        return root
    for child in root.children:
        found = find_layer_collection(child, name)
        if found is not None:
            return found
    return None


def link_reference_and_clone(
    scene: bpy.types.Scene,
    state: str,
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> tuple[bpy.types.Collection, list[bpy.types.Object]]:
    library_path = reference_library_path(state)
    report = read_json(reference_library_report_path(state))
    if sha256(library_path) != str(report["output_library_sha256"]):
        raise RuntimeError(f"{state}: reference library drifted")
    root_name = str(report["root_collection"])
    with bpy.data.libraries.load(str(library_path), link=True) as (source, target):
        if root_name not in source.collections:
            raise RuntimeError(f"Missing {root_name} in {library_path}")
        target.collections = [root_name]
    reference = target.collections[0]
    if reference is None:
        raise RuntimeError(f"Failed to link {root_name}")
    scene.collection.children.link(reference)
    bpy.context.view_layer.update()

    clones: list[bpy.types.Object] = []
    for source_obj in sorted(reference.all_objects, key=lambda value: value.name):
        if source_obj.type != "MESH":
            continue
        occurrence = str(source_obj.get("wc_occurrence_id", ""))
        if not should_clone_occurrence(occurrence, state):
            continue
        clone = bpy.data.objects.new(f"V11SRC__{state.upper()}__{occurrence}", source_obj.data)
        owner.objects.link(clone)
        clone.matrix_world = source_obj.matrix_world.copy()
        clone["wc_occurrence_id"] = occurrence
        clone["wc_state"] = state
        clone["wc_source"] = "linked V8 mesh data; local render object"
        assign_object_material(clone, clone_material_for_occurrence(occurrence, mats))
        clones.append(clone)

    layer = find_layer_collection(bpy.context.view_layer.layer_collection, reference.name)
    if layer is None:
        raise RuntimeError(f"Could not find linked reference layer {reference.name}")
    layer.exclude = True
    bpy.context.view_layer.update()
    return reference, clones


def set_smooth(obj: bpy.types.Object) -> None:
    if obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True


def apply_modifier(obj: bpy.types.Object, modifier: bpy.types.Modifier) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def rounded_box(
    owner: bpy.types.Collection,
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    radius: float,
    mat: bpy.types.Material,
    segments: int = 6,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    move_to_collection(obj, owner)
    bevel = obj.modifiers.new("V11_CONTINUOUS_EDGE", "BEVEL")
    bevel.width = radius
    bevel.segments = segments
    bevel.limit_method = "ANGLE"
    apply_modifier(obj, bevel)
    set_smooth(obj)
    obj.data.materials.append(mat)
    return obj


def signed_power(value: float, exponent: float) -> float:
    return math.copysign(abs(value) ** exponent, value)


def superellipsoid(
    owner: bpy.types.Collection,
    name: str,
    centre: tuple[float, float, float],
    radii: tuple[float, float, float],
    exponent_vertical: float,
    exponent_plan: float,
    mat: bpy.types.Material,
    lat_segments: int = 36,
    lon_segments: int = 72,
) -> bpy.types.Object:
    cx, cy, cz = centre
    ax, ay, az = radii
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    bottom = len(vertices)
    vertices.append((cx, cy, cz - az))
    ring_indices: list[list[int]] = []
    for lat in range(1, lat_segments):
        phi = -math.pi * 0.5 + math.pi * lat / lat_segments
        cphi = signed_power(math.cos(phi), exponent_vertical)
        z = cz + az * signed_power(math.sin(phi), exponent_vertical)
        ring: list[int] = []
        for lon in range(lon_segments):
            theta = 2.0 * math.pi * lon / lon_segments
            x = cx + ax * cphi * signed_power(math.cos(theta), exponent_plan)
            y = cy + ay * cphi * signed_power(math.sin(theta), exponent_plan)
            ring.append(len(vertices))
            vertices.append((x, y, z))
        ring_indices.append(ring)
    top = len(vertices)
    vertices.append((cx, cy, cz + az))
    first = ring_indices[0]
    for lon in range(lon_segments):
        faces.append((bottom, first[(lon + 1) % lon_segments], first[lon]))
    for lower, upper in zip(ring_indices[:-1], ring_indices[1:]):
        for lon in range(lon_segments):
            nxt = (lon + 1) % lon_segments
            faces.append((lower[lon], lower[nxt], upper[nxt], upper[lon]))
    last = ring_indices[-1]
    for lon in range(lon_segments):
        faces.append((last[lon], last[(lon + 1) % lon_segments], top))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    mesh.materials.append(mat)
    set_smooth(obj)
    return obj


def trapezoid_prism(
    owner: bpy.types.Collection,
    name: str,
    x_front: float,
    x_back: float,
    z_bottom: float,
    z_top: float,
    y_bottom_half: float,
    y_top_half: float,
    mat: bpy.types.Material,
    bevel_width: float,
) -> bpy.types.Object:
    vertices = [
        (x_front, -y_bottom_half, z_bottom),
        (x_front, y_bottom_half, z_bottom),
        (x_front, y_top_half, z_top),
        (x_front, -y_top_half, z_top),
        (x_back, -y_bottom_half, z_bottom),
        (x_back, y_bottom_half, z_bottom),
        (x_back, y_top_half, z_top),
        (x_back, -y_top_half, z_top),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    bevel = obj.modifiers.new("V11_TRAPEZOID_EDGE", "BEVEL")
    bevel.width = bevel_width
    bevel.segments = 6
    bevel.limit_method = "ANGLE"
    apply_modifier(obj, bevel)
    set_smooth(obj)
    return obj


def cut_seat_well(
    body: bpy.types.Object,
    owner: bpy.types.Collection,
    seam_mat: bpy.types.Material,
) -> None:
    cutter = rounded_box(
        owner,
        "V11_TEMP_SEAT_WELL_CUTTER",
        (-0.075, 0.0, 0.580),
        (0.540, 0.610, 0.300),
        0.090,
        seam_mat,
        8,
    )
    boolean = body.modifiers.new("V11_SEAT_WELL", "BOOLEAN")
    boolean.operation = "DIFFERENCE"
    boolean.solver = "EXACT"
    boolean.object = cutter
    apply_modifier(body, boolean)
    bpy.data.objects.remove(cutter, do_unlink=True)


def make_side_door(
    owner: bpy.types.Collection,
    side: str,
    y: float,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    sign = 1.0 if side == "right" else -1.0
    seam = rounded_box(
        owner,
        f"V11_A04_EQUIPMENT_OPENING_{side.upper()}",
        (-0.020, y, 0.366),
        (0.466, 0.004, 0.088),
        0.019,
        mats["seam"],
        8,
    )
    door = rounded_box(
        owner,
        f"V11_A04_EQUIPMENT_DOOR_{side.upper()}",
        (-0.020, y + sign * 0.0025, 0.366),
        (0.464, 0.003, 0.086),
        0.018,
        mats["body"],
        8,
    )
    door["door_contract"] = "464x86_R18"
    door["opening_contract"] = "466x88_R19"
    door["nominal_seam_mm"] = 1.0
    door["service_travel_mm"] = 300.0
    return [seam, door]


def build_lower_and_arms(
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    body = superellipsoid(
        owner,
        "V11_SHARED_LOWER_MOTHER_VOLUME",
        (-0.102, 0.0, 0.290),
        (0.423, 0.371, 0.220),
        0.58,
        0.43,
        mats["body"],
    )
    body["design_intent"] = "single lower mother surface; integrated differential-wheel half-wrap"
    cut_seat_well(body, owner, mats["seam"])
    objects.append(body)

    horizon = rounded_box(
        owner,
        "V11_SHARED_PERCEPTION_HORIZON",
        (-0.521, 0.0, 0.276),
        (0.010, 0.500, 0.060),
        0.027,
        mats["glass"],
        8,
    )
    objects.append(horizon)

    for side, y in (("left", -0.336), ("right", 0.336)):
        arm = rounded_box(
            owner,
            f"V11_SHARED_ARMREST_{side.upper()}",
            (-0.110, y, 0.548),
            (0.540, 0.072, 0.254),
            0.034,
            mats["body_soft"],
            8,
        )
        arm["fixed_armrest"] = True
        arm["rear_terminal_x_m"] = 0.160
        objects.append(arm)
        cap = rounded_box(
            owner,
            f"V11_SHARED_ARMREST_TOP_{side.upper()}",
            (-0.110, y, 0.679),
            (0.500, 0.068, 0.006),
            0.026,
            mats["body"],
            6,
        )
        objects.append(cap)

    qi = rounded_box(
        owner,
        "V11_LEFT_QI_USABLE_FIELD",
        (-0.136, -0.336, 0.684),
        (0.176, 0.058, 0.003),
        0.020,
        mats["body_soft"],
        8,
    )
    qi["usable_phone_field_mm"] = [176.0, 58.0]
    objects.append(qi)

    objects.extend(make_side_door(owner, "left", -0.373, mats))
    objects.extend(make_side_door(owner, "right", 0.373, mats))

    rear_seam = rounded_box(
        owner,
        "V11_REAR_SERVICE_DOOR_OPENING",
        (0.318, 0.0, 0.315),
        (0.006, 0.370, 0.210),
        0.025,
        mats["seam"],
        8,
    )
    rear_door = rounded_box(
        owner,
        "V11_REAR_SERVICE_DOOR_SKIN",
        (0.322, 0.0, 0.315),
        (0.004, 0.366, 0.206),
        0.024,
        mats["body"],
        8,
    )
    objects.extend([rear_seam, rear_door])
    return objects


def parent_rigid(parts: Iterable[bpy.types.Object], parent: bpy.types.Object) -> None:
    bpy.context.view_layer.update()
    inverse = parent.matrix_world.inverted()
    for obj in parts:
        obj.parent = parent
        obj.matrix_parent_inverse = inverse


def build_a06_a07(
    owner: bpy.types.Collection,
    state: str,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = trapezoid_prism(
        owner,
        f"V11_{state.upper()}_A06_ICONIC_TRAPEZOID_SHELL",
        0.158,
        0.248,
        0.525,
        1.003,
        0.288,
        0.204,
        mats["body"],
        0.020,
    )
    shell["identity"] = "front-view iconic trapezoid; same physical A06 intent"
    contact = trapezoid_prism(
        owner,
        f"V11_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.148,
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
    mast = trapezoid_prism(
        owner,
        f"V11_{state.upper()}_A07_SINGLE_TAPERED_MAST",
        0.240,
        0.296,
        0.735,
        mast_top,
        0.071,
        0.043 if focus else 0.050,
        mats["body_soft"],
        0.012,
    )
    mast["motion_contract"] = "Ride/Cafe low; Focus same member +420mm; Follow co-folds with A06"
    head_z = 1.460 if focus else 1.040
    head = rounded_box(
        owner,
        f"V11_{state.upper()}_A07_SENSOR_CROWN",
        (0.270, 0.0, head_z),
        (0.070, 0.350, 0.056),
        0.025,
        mats["body_soft"],
        8,
    )
    window = rounded_box(
        owner,
        f"V11_{state.upper()}_A07_SENSOR_WINDOW",
        (0.233, 0.0, head_z - 0.002),
        (0.006, 0.274, 0.024),
        0.010,
        mats["glass"],
        6,
    )
    parts.extend([mast, head, window])

    if state == "follow":
        pivot = bpy.data.objects.new("V11_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.525)
        pivot.rotation_mode = "XYZ"
        parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-83.0)
        pivot["fold_angle_deg_visual_r01"] = -83.0
        pivot["validation_status"] = "visual candidate; canonical sweep required"
        parts.append(pivot)
    return parts


def make_area_light(
    owner: bpy.types.Collection,
    name: str,
    location: tuple[float, float, float],
    energy: float,
    size: float,
    colour: tuple[float, float, float],
) -> bpy.types.Object:
    data = bpy.data.lights.new(name + "_DATA", "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = colour
    obj = bpy.data.objects.new(name, data)
    owner.objects.link(obj)
    obj.location = location
    return obj


def point_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def configure_studio(
    scene: bpy.types.Scene,
    owner: bpy.types.Collection,
    state: str,
    mats: dict[str, bpy.types.Material],
) -> None:
    ground_mat = material("V11_MAT_STUDIO_GROUND", (0.105, 0.095, 0.084, 1.0), 0.72)
    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, -0.003))
    ground = bpy.context.object
    ground.name = "V11_STUDIO_GROUND"
    move_to_collection(ground, owner)
    ground.data.materials.append(ground_mat)
    ground["not_product_geometry"] = True

    world = bpy.data.worlds.new("V11_STUDIO_WORLD")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.035, 0.031, 0.028, 1.0)
        background.inputs["Strength"].default_value = 0.38
    scene.world = world

    key = make_area_light(owner, "V11_KEY", (-1.2, 1.6, 2.25), 1050.0, 2.1, (1.0, 0.82, 0.68))
    fill = make_area_light(owner, "V11_FILL", (-0.3, -1.8, 1.25), 680.0, 2.4, (0.60, 0.72, 1.0))
    rim = make_area_light(owner, "V11_RIM", (1.5, 0.5, 1.65), 900.0, 1.6, (1.0, 0.55, 0.32))
    point_at(key, (-0.08, 0.0, 0.42))
    point_at(fill, (-0.08, 0.0, 0.46))
    point_at(rim, (0.02, 0.0, 0.50))

    camera_data = bpy.data.cameras.new("V11_CAMERA_DATA")
    camera = bpy.data.objects.new("V11_CAMERA", camera_data)
    owner.objects.link(camera)
    camera_data.lens = 58.0
    camera_data.sensor_width = 36.0
    if state == "follow":
        camera.location = (-1.52, 1.38, 1.18)
        target = (-0.08, 0.0, 0.42)
    elif state == "focus":
        camera.location = (-2.05, 1.85, 1.92)
        target = (-0.10, 0.0, 0.72)
    else:
        camera.location = (-1.78, 1.58, 1.52)
        target = (-0.10, 0.0, 0.57)
    point_at(camera, target)
    scene.camera = camera

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass


def world_bounds(objects: Iterable[bpy.types.Object]) -> dict[str, list[float]]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects if obj.type == "MESH" for corner in obj.bound_box]
    minimum = [min(point[i] for point in points) for i in range(3)]
    maximum = [max(point[i] for point in points) for i in range(3)]
    return {
        "minimum_m": [round(value, 6) for value in minimum],
        "maximum_m": [round(value, 6) for value in maximum],
        "size_m": [round(maximum[i] - minimum[i], 6) for i in range(3)],
    }


def main() -> None:
    state = validate_state(args().state)
    validate_source(state)
    output = state_blend_path(state, REVISION)
    report_path = REPORT_ROOT / f"v11_{state}_{REVISION}_build_report.json"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = f"V11_{state.upper()}_{REVISION.upper()}"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"
    scene["pipeline_id"] = PIPELINE_ID
    scene["wc_state"] = state
    scene["visual_revision"] = REVISION
    scene["source_policy"] = "V8 references only; no V9/V10 geometry"

    root = new_child(scene.collection, f"V11__{state.upper()}__{REVISION.upper()}__ROOT")
    sources = new_child(root, "10_LOCAL_V8_FUNCTIONAL_RENDER_OBJECTS")
    design = new_child(root, "40_V11_NEW_DESIGN")
    studio = new_child(root, "60_STUDIO")
    studio["not_product_geometry"] = True
    mats = build_materials()

    reference, clones = link_reference_and_clone(scene, state, sources, mats)
    design_objects = build_lower_and_arms(design, mats)
    design_objects.extend(build_a06_a07(design, state, mats))
    configure_studio(scene, studio, state, mats)
    bpy.context.view_layer.update()

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial.blend")
    if temporary.exists():
        temporary.unlink()
    bpy.ops.wm.save_as_mainfile(
        filepath=str(temporary), check_existing=False, compress=True, relative_remap=True
    )
    if not temporary.is_file() or temporary.stat().st_size < 1024:
        raise RuntimeError(f"Incomplete state blend: {temporary}")
    os.replace(temporary, output)

    report = {
        "schema_version": 1,
        "pipeline_id": PIPELINE_ID,
        "status": "PASS_VISUAL_BUILD_R01",
        "state": state,
        "revision": REVISION,
        "blender_version": bpy.app.version_string,
        "output_blend": str(output),
        "output_blend_sha256": sha256(output),
        "linked_reference_library": str(reference_library_path(state)),
        "linked_reference_collection": reference.name,
        "local_v8_functional_clone_count": len(clones),
        "local_v8_occurrence_ids": sorted(str(obj.get("wc_occurrence_id")) for obj in clones),
        "new_design_object_count": len(design_objects),
        "new_design_bounds": world_bounds(design_objects),
        "contracts": {
            "body_width_m": 0.742,
            "armrest_rear_x_m": 0.160,
            "a04_door_mm": [464.0, 86.0, 18.0],
            "a04_opening_mm": [466.0, 88.0, 19.0],
            "a04_nominal_seam_mm": 1.0,
            "display_mm": [124.0, 49.0],
            "focus_mast_delta_z_mm": 420.0,
            "follow_fold_visual_deg": -83.0 if state == "follow" else None,
        },
        "known_limits": [
            "Visual Blender proposal only; not production Class-A or STEP release.",
            "A06/A07 kinematic sweep is not yet rerun on canonical BRep.",
            "R01 uses V8 table and footrest mesh data as immutable functional proxies.",
            "Surface curvature, parting and CMF require visual review before STEP rebuild.",
        ],
    }
    atomic_write_json(report_path, report)
    print("V11_VISUAL_R01_OK", state, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)

