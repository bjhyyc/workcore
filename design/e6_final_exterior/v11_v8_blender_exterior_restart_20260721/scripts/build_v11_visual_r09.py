"""Build V11 R09: one-piece monocoque, closed Follow and usable HMI/table layout.

R09 is the first revision after the saved-file R08 audit.  It keeps the V8
hardpoints and four-state kinematics, but replaces the stacked upper saddle,
wheel lobes, wedge display, exposed table roots and rotating footrest proxy.
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
import build_v11_visual_r03 as r03  # noqa: E402
import build_v11_visual_r05 as r05  # noqa: E402
from v11_common import (  # noqa: E402
    V11_ROOT,
    atomic_write_json,
    read_json,
    sha256,
    state_blend_path,
    validate_state,
)


REVISION = "r09"
ACTIVE_STATE = "ride"
BASE_STUDIO = r01.configure_studio


def tuned_material(
    name: str,
    colour: tuple[float, float, float, float],
    roughness: float,
    metallic: float = 0.0,
    specular: float = 0.20,
) -> bpy.types.Material:
    mat = r01.material(name, colour, roughness, metallic)
    node = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if node:
        socket = node.inputs.get("Specular IOR Level")
        if socket:
            socket.default_value = specular
        socket = node.inputs.get("Coat Weight")
        if socket:
            socket.default_value = 0.018 if metallic < 0.5 else 0.008
    return mat


def add_micro_bump(mat: bpy.types.Material, scale: float, strength: float, distance: float) -> None:
    if not mat.node_tree:
        return
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if not bsdf:
        return
    tex = nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 3.0
    tex.inputs["Roughness"].default_value = 0.72
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links.new(tex.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def walnut_material(name: str, grain_axis: str) -> bpy.types.Material:
    mat = tuned_material(name, (0.055, 0.012, 0.0035, 1.0), 0.43, 0.0, 0.24)
    if not mat.node_tree:
        return mat
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if not bsdf:
        return mat
    texcoord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 5.2
    noise.inputs["Detail"].default_value = 5.0
    noise.inputs["Roughness"].default_value = 0.78
    noise.inputs["Distortion"].default_value = 0.35
    if grain_axis == "X":
        mapping.inputs["Scale"].default_value = (1.2, 16.0, 2.0)
    else:
        mapping.inputs["Scale"].default_value = (16.0, 1.2, 2.0)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.26
    ramp.color_ramp.elements[0].color = (0.012, 0.0016, 0.00045, 1.0)
    ramp.color_ramp.elements[1].position = 0.78
    ramp.color_ramp.elements[1].color = (0.105, 0.026, 0.006, 1.0)
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.075
    bump.inputs["Distance"].default_value = 0.00045
    links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def materials() -> dict[str, bpy.types.Material]:
    result = {
        "body": tuned_material("V11_R09_MAT_WARM_GRAPHITE_MINERAL", (0.0072, 0.0056, 0.0044, 1.0), 0.58, 0.015, 0.18),
        "body_soft": tuned_material("V11_R09_MAT_OBSIDIAN_MINERAL", (0.0016, 0.0019, 0.0020, 1.0), 0.55, 0.0, 0.15),
        "seam": tuned_material("V11_R09_MAT_FUNCTIONAL_SHADOW", (0.00012, 0.00014, 0.00015, 1.0), 0.91, 0.0, 0.08),
        "glass": tuned_material("V11_R09_MAT_SMOKED_SENSOR_GLASS", (0.00045, 0.0024, 0.0040, 1.0), 0.15, 0.22, 0.36),
        "leather": tuned_material("V11_R09_MAT_NATURAL_OXBLOOD_LEATHER", (0.031, 0.0040, 0.0016, 1.0), 0.69, 0.0, 0.18),
        "shadow_leather": tuned_material("V11_R09_MAT_FOLLOW_SHADOW_LEATHER", (0.0010, 0.00065, 0.00055, 1.0), 0.82, 0.0, 0.10),
        "walnut_x": walnut_material("V11_R09_MAT_NATURAL_WALNUT_GRAIN_X", "X"),
        "walnut_y": walnut_material("V11_R09_MAT_NATURAL_WALNUT_GRAIN_Y", "Y"),
        "stainless": tuned_material("V11_R09_MAT_316_BRUSHED_STAINLESS", (0.20, 0.215, 0.22, 1.0), 0.43, 0.92, 0.30),
        "tire": tuned_material("V11_R09_MAT_TIRE", (0.00045, 0.00052, 0.00052, 1.0), 0.95, 0.0, 0.06),
        "control": tuned_material("V11_R09_MAT_CONTROL_ISLAND", (0.0008, 0.0010, 0.0012, 1.0), 0.46, 0.0, 0.17),
    }
    add_micro_bump(result["body"], 46.0, 0.018, 0.00030)
    add_micro_bump(result["body_soft"], 52.0, 0.015, 0.00025)
    add_micro_bump(result["leather"], 125.0, 0.10, 0.00065)
    return result


def clone_material(occurrence: str, mats: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if occurrence.startswith("source_tyre_"):
        return mats["tire"]
    return mats["control"]


def should_clone(occurrence: str, state: str) -> bool:
    return occurrence.startswith("source_tyre_") or occurrence in {
        "A05_right_joystick",
        "A05_right_authorisation_key",
        "A05_left_mechanical_emergency_stop",
    }


def clean_mesh(obj: bpy.types.Object, distance: float = 1.0e-8) -> None:
    if obj.type != "MESH":
        return
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=distance)
    bmesh.ops.dissolve_degenerate(bm, dist=distance, edges=bm.edges)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def rounded_prism_xy(
    owner: bpy.types.Collection,
    name: str,
    centre: tuple[float, float, float],
    length_x: float,
    width_y: float,
    thickness_z: float,
    radius_xy: float,
    mat: bpy.types.Material,
    edge_bevel: float = 0.0006,
) -> bpy.types.Object:
    outline = r03.rounded_rectangle_points(length_x, width_y, radius_xy, 10)
    cx, cy, cz = centre
    bottom = cz - thickness_z * 0.5
    top = cz + thickness_z * 0.5
    vertices = [(cx + x, cy + y, bottom) for x, y in outline] + [(cx + x, cy + y, top) for x, y in outline]
    count = len(outline)
    faces: list[tuple[int, ...]] = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    if edge_bevel > 0.0:
        bevel = obj.modifiers.new("V11_R09_MICRO_EDGE", "BEVEL")
        bevel.width = min(edge_bevel, thickness_z * 0.30)
        bevel.segments = 3
        bevel.limit_method = "ANGLE"
        r01.apply_modifier(obj, bevel)
    r01.set_smooth(obj)
    clean_mesh(obj)
    return obj


def rounded_prism_yz(
    owner: bpy.types.Collection,
    name: str,
    centre: tuple[float, float, float],
    width_y: float,
    height_z: float,
    thickness_x: float,
    radius_yz: float,
    mat: bpy.types.Material,
    edge_bevel: float = 0.0005,
) -> bpy.types.Object:
    outline = r03.rounded_rectangle_points(width_y, height_z, radius_yz, 10)
    cx, cy, cz = centre
    front = cx - thickness_x * 0.5
    back = cx + thickness_x * 0.5
    vertices = [(front, cy + y, cz + z) for y, z in outline] + [(back, cy + y, cz + z) for y, z in outline]
    count = len(outline)
    faces: list[tuple[int, ...]] = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    if edge_bevel > 0.0:
        bevel = obj.modifiers.new("V11_R09_MICRO_EDGE", "BEVEL")
        bevel.width = min(edge_bevel, thickness_x * 0.30)
        bevel.segments = 3
        bevel.limit_method = "ANGLE"
        r01.apply_modifier(obj, bevel)
    r01.set_smooth(obj)
    clean_mesh(obj)
    return obj


def interpolate_controls(controls: list[tuple[float, ...]], steps: int = 5) -> list[tuple[float, ...]]:
    result: list[tuple[float, ...]] = []
    for left, right in zip(controls[:-1], controls[1:]):
        for index in range(steps):
            raw = index / steps
            t = raw * raw * (3.0 - 2.0 * raw)
            result.append(tuple(a + (b - a) * t for a, b in zip(left, right)))
    result.append(controls[-1])
    return result


def longitudinal_loft(
    owner: bpy.types.Collection,
    name: str,
    controls: list[tuple[float, float, float, float]],
    exponent: float,
    mat: bpy.types.Material,
    ring_segments: int = 64,
) -> bpy.types.Object:
    stations = interpolate_controls(controls, 6)
    vertices: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []
    for x, half_y, z_centre, half_z in stations:
        ring: list[int] = []
        for index in range(ring_segments):
            angle = 2.0 * math.pi * index / ring_segments
            c = math.cos(angle)
            s = math.sin(angle)
            ring.append(len(vertices))
            vertices.append(
                (
                    x,
                    half_y * math.copysign(abs(c) ** exponent, c),
                    z_centre + half_z * math.copysign(abs(s) ** exponent, s),
                )
            )
        rings.append(ring)
    faces: list[tuple[int, ...]] = [tuple(reversed(rings[0]))]
    for left, right in zip(rings[:-1], rings[1:]):
        for index in range(ring_segments):
            nxt = (index + 1) % ring_segments
            faces.append((left[index], left[nxt], right[nxt], right[index]))
    faces.append(tuple(rings[-1]))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    r01.set_smooth(obj)
    clean_mesh(obj)
    return obj


def arm_loft(
    owner: bpy.types.Collection,
    name: str,
    side: str,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    # x, inner-|y|, outer-|y|, bottom-z, top-z.  The forward inner cheek
    # follows the folded A06 taper, then releases into a low 110 mm arm bay.
    controls = [
        (-0.382, 0.250, 0.354, 0.470, 0.625),
        (-0.352, 0.232, 0.375, 0.435, 0.654),
        (-0.300, 0.252, 0.375, 0.423, 0.655),
        (-0.205, 0.265, 0.375, 0.420, 0.655),
        (0.170, 0.265, 0.375, 0.430, 0.654),
        (0.225, 0.282, 0.358, 0.458, 0.625),
        (0.252, 0.306, 0.336, 0.505, 0.572),
    ]
    stations = interpolate_controls(controls, 5)
    ring_segments = 56
    exponent = 0.16
    sign = -1.0 if side == "LEFT" else 1.0
    vertices: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []
    for x, inner, outer, bottom, top in stations:
        centre_abs = (inner + outer) * 0.5
        half_y = (outer - inner) * 0.5
        centre_y = sign * centre_abs
        z_centre = (bottom + top) * 0.5
        half_z = (top - bottom) * 0.5
        ring: list[int] = []
        for index in range(ring_segments):
            angle = 2.0 * math.pi * index / ring_segments
            c = math.cos(angle)
            s = math.sin(angle)
            ring.append(len(vertices))
            vertices.append(
                (
                    x,
                    centre_y + half_y * math.copysign(abs(c) ** exponent, c),
                    z_centre + half_z * math.copysign(abs(s) ** exponent, s),
                )
            )
        rings.append(ring)
    faces: list[tuple[int, ...]] = [tuple(reversed(rings[0]))]
    for left, right in zip(rings[:-1], rings[1:]):
        for index in range(ring_segments):
            nxt = (index + 1) % ring_segments
            faces.append((left[index], left[nxt], right[nxt], right[index]))
    faces.append(tuple(rings[-1]))
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    owner.objects.link(obj)
    r01.set_smooth(obj)
    clean_mesh(obj)
    return obj


def boolean(body: bpy.types.Object, tool: bpy.types.Object, operation: str, name: str) -> None:
    modifier = body.modifiers.new(name, "BOOLEAN")
    modifier.operation = operation
    modifier.solver = "EXACT"
    modifier.object = tool
    r01.apply_modifier(body, modifier)
    bpy.data.objects.remove(tool, do_unlink=True)
    clean_mesh(body)


def cut_wheel_cavities(body: bpy.types.Object, owner: bpy.types.Collection) -> None:
    for x_centre in (-0.380, 0.180):
        for sign in (-1.0, 1.0):
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=80,
                radius=0.139,
                depth=0.095,
                location=(x_centre, sign * 0.3175, 0.125),
                rotation=(math.pi * 0.5, 0.0, 0.0),
            )
            cutter = bpy.context.object
            cutter.name = "V11_R09_TEMP_INTERNAL_WHEEL_CLEARANCE"
            r01.move_to_collection(cutter, owner)
            boolean(body, cutter, "DIFFERENCE", "V11_R09_INTERNAL_WHEEL_CAVITY")


def cut_tapered_seat_well(body: bpy.types.Object, owner: bpy.types.Collection, mat: bpy.types.Material) -> None:
    cutter = r05.polygon_prism_xy(
        owner,
        "V11_R09_TEMP_TAPERED_SEAT_WELL",
        [(-0.342, -0.222), (-0.342, 0.222), (0.182, 0.263), (0.182, -0.263)],
        0.422,
        0.700,
        0.032,
        mat,
    )
    boolean(body, cutter, "DIFFERENCE", "V11_R09_TAPERED_SEAT_WELL")


def projected_curve(
    owner: bpy.types.Collection,
    name: str,
    target: bpy.types.Object,
    plane: str,
    centre_uv: tuple[float, float],
    width: float,
    height: float,
    radius: float,
    mat: bpy.types.Material,
    line_width: float,
) -> bpy.types.Object:
    outline = r03.rounded_rectangle_points(width, height, radius, 10)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(target, depsgraph)
    points: list[Vector] = []
    for u, v in outline:
        if plane == "RIGHT_XZ":
            origin = Vector((centre_uv[0] + u, 1.0, centre_uv[1] + v))
            direction = Vector((0.0, -1.0, 0.0))
        elif plane == "LEFT_XZ":
            origin = Vector((centre_uv[0] + u, -1.0, centre_uv[1] + v))
            direction = Vector((0.0, 1.0, 0.0))
        elif plane == "REAR_YZ":
            origin = Vector((1.0, centre_uv[0] + u, centre_uv[1] + v))
            direction = Vector((-1.0, 0.0, 0.0))
        elif plane == "FRONT_YZ":
            origin = Vector((-1.0, centre_uv[0] + u, centre_uv[1] + v))
            direction = Vector((1.0, 0.0, 0.0))
        else:
            raise ValueError(plane)
        hit, normal, _index, _distance = tree.ray_cast(origin, direction, 3.0)
        if hit is None or normal is None:
            raise RuntimeError(f"{name}: projection missed {plane} at {(u, v)}")
        points.append(hit + normal.normalized() * 0.00035)
    curve = bpy.data.curves.new(name + "_CURVE", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = line_width * 0.5
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for target_point, value in zip(spline.points, points):
        target_point.co = (*value, 1.0)
    spline.use_cyclic_u = True
    curve.materials.append(mat)
    obj = bpy.data.objects.new(name, curve)
    owner.objects.link(obj)
    obj["projection_target"] = target.name
    obj["surface_offset_mm"] = 0.35
    return obj


def flat_outline_curve(
    owner: bpy.types.Collection,
    name: str,
    centre: tuple[float, float, float],
    width: float,
    height: float,
    radius: float,
    mat: bpy.types.Material,
    line_width: float,
) -> bpy.types.Object:
    return r03.rounded_rect_curve(owner, name, centre, width, height, radius, "XY", mat, line_width)


def sloped_support_wedge(owner: bpy.types.Collection, mat: bpy.types.Material) -> bpy.types.Object:
    x_front, x_rear = -0.358, -0.230
    y0, y1 = -0.349, -0.291
    z_bottom = 0.648
    z_front, z_rear = 0.6990, 0.6815
    vertices = [
        (x_front, y0, z_bottom), (x_front, y1, z_bottom),
        (x_rear, y1, z_bottom), (x_rear, y0, z_bottom),
        (x_front, y0, z_front), (x_front, y1, z_front),
        (x_rear, y1, z_rear), (x_rear, y0, z_rear),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new("V11_R09_LEFT_DISPLAY_INTEGRATED_SADDLE_MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new("V11_R09_TEMP_LEFT_DISPLAY_INTEGRATED_SADDLE", mesh)
    owner.objects.link(obj)
    clean_mesh(obj)
    return obj


def add_storage_cavity(arm: bpy.types.Object, owner: bpy.types.Collection, x_centre: float, mat: bpy.types.Material) -> None:
    cutter = r01.rounded_box(
        owner,
        "V11_R09_TEMP_TABLE_STORAGE_CAVITY",
        (x_centre, -0.320 if "LEFT" in arm.name else 0.320, 0.570),
        (0.400, 0.075, 0.180),
        0.014,
        mat,
        6,
    )
    boolean(arm, cutter, "DIFFERENCE", "V11_R09_REAL_TABLE_STORAGE_CAVITY")
    arm["internal_table_pack_envelope_mm"] = [400.0, 75.0, 180.0]
    arm["target_folded_table_pack_mm"] = [395.0, 72.0, 30.0]


def create_display(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    display = rounded_prism_xy(
        owner,
        "V11_R09_A05_SINGLE_UNIFORM_DISPLAY_124X49X2P5",
        (-0.294, -0.320, 0.6915),
        0.124,
        0.049,
        0.0025,
        0.006,
        mats["glass"],
        0.0004,
    )
    display.rotation_mode = "XYZ"
    display.rotation_euler.y = math.radians(8.0)
    display["source_occurrence_ids"] = "A05_left_status_display_window"
    display["display_face_mm"] = [124.0, 49.0]
    display["uniform_normal_thickness_mm"] = 2.5
    display["world_y_pitch_deg"] = 8.0
    display["slope"] = "front high; rear low"
    return display


def create_qi(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    pad = rounded_prism_xy(
        owner,
        "V11_R09_A05_LEFT_QI_FLUSH_USABLE_FIELD_176X86",
        (-0.126, -0.320, 0.6580),
        0.176,
        0.086,
        0.0012,
        0.015,
        mats["control"],
        0.0002,
    )
    pad["source_occurrence_ids"] = "A05_left_qi_phone_cradle"
    pad["usable_phone_field_mm"] = [176.0, 86.0]
    pad["ownership"] = "left outward-flip lid; unavailable only while retrieving table"
    ring_points = []
    for index in range(64):
        angle = 2.0 * math.pi * index / 64
        ring_points.append((-0.126 + 0.027 * math.cos(angle), -0.320 + 0.027 * math.sin(angle), 0.6588))
    curve = bpy.data.curves.new("V11_R09_QI_TARGET_RING_CURVE", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.00025
    curve.bevel_resolution = 2
    spline = curve.splines.new("POLY")
    spline.points.add(len(ring_points) - 1)
    for target, value in zip(spline.points, ring_points):
        target.co = (*value, 1.0)
    spline.use_cyclic_u = True
    curve.materials.append(mats["stainless"])
    ring = bpy.data.objects.new("V11_R09_A05_LEFT_QI_TARGET_RING", curve)
    owner.objects.link(ring)
    ring["source_occurrence_ids"] = "A05_left_qi_target_ring"
    return [pad, ring]


def table_supports(
    owner: bpy.types.Collection,
    side: str,
    x_positions: tuple[float, float],
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    sign = -1.0 if side == "LEFT" else 1.0
    centre_y = sign * 0.258
    parts = []
    for index, x_value in enumerate(x_positions, start=1):
        tongue = rounded_prism_xy(
            owner,
            f"V11_R09_A09_{side}_HIDDEN_INBOARD_NECK_{index}",
            (x_value, centre_y, 0.668),
            0.060,
            0.026,
            0.008,
            0.006,
            mats["control"],
            0.0007,
        )
        tongue["mechanism_policy"] = "hinge and support remain inside arm; only neck crosses inner wall beneath tabletop"
        parts.append(tongue)
    return parts


def build_tables(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    if ACTIVE_STATE == "cafe":
        table = rounded_prism_xy(
            owner,
            "V11_R09_A09_CAFE_RIGHT_SINGLE_CALM_WALNUT_SURFACE",
            (-0.335, 0.055, 0.678),
            0.250,
            0.400,
            0.012,
            0.020,
            mats["walnut_y"],
            0.0011,
        )
        table["source_occurrence_ids"] = "A09_table_top_skin_right,A09_table_edge_band_right,A09_table_underbelly_shell_right"
        table["deployed_bounds_policy"] = "entire surface at y<=255 mm; right arm inner face y=265 mm"
        table["joystick_lateral_clearance_mm"] = 62.0
        objects.append(table)
        objects.extend(table_supports(owner, "RIGHT", (-0.420, -0.270), mats))
    elif ACTIVE_STATE == "focus":
        for side, centre_y in (("LEFT", -0.1315), ("RIGHT", 0.1315)):
            table = rounded_prism_xy(
                owner,
                f"V11_R09_A09_FOCUS_{side}_CONTINUOUS_WALNUT_SURFACE",
                (-0.350, centre_y, 0.678),
                0.400,
                0.247,
                0.012,
                0.020,
                mats["walnut_x"],
                0.0011,
            )
            table["source_occurrence_ids"] = f"A09_table_top_skin_{side.lower()},A09_table_edge_band_{side.lower()},A09_table_underbelly_shell_{side.lower()}"
            table["deployed_bounds_policy"] = "surface stays 10 mm inboard of arm inner face; 16 mm centre reveal"
            objects.append(table)
            objects.extend(table_supports(owner, side, (-0.470, -0.230), mats))
    return objects


def build_footrest(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    if ACTIVE_STATE == "ride":
        platform = rounded_prism_xy(
            owner,
            "V11_R09_A08_SINGLE_PIECE_TELESCOPIC_FOOTREST",
            (-0.605, 0.0, 0.098),
            0.206,
            0.496,
            0.024,
            0.024,
            mats["body"],
            0.0015,
        )
        platform["source_occurrence_ids"] = "A08_footrest_platform,A08_footrest_top_skin,A08_left_support,A08_right_support"
        platform["motion"] = "+220 mm X translation into internal front cassette; no external rods"
        platform["default_state"] = "deployed and positively locked in Ride"
        tread = rounded_prism_xy(
            owner,
            "V11_R09_A08_NATURAL_RUBBER_TREAD_INLAY",
            (-0.616, 0.0, 0.1108),
            0.166,
            0.430,
            0.0016,
            0.020,
            mats["control"],
            0.0002,
        )
        tread["source_occurrence_ids"] = "A08_footrest_tread_inlay"
        lip = rounded_prism_xy(
            owner,
            "V11_R09_A08_LIMITED_316_LEADING_EDGE",
            (-0.704, 0.0, 0.101),
            0.007,
            0.452,
            0.008,
            0.003,
            mats["stainless"],
            0.0005,
        )
        lip["source_occurrence_ids"] = "A08_footrest_leading_edge"
        objects.extend([platform, tread, lip])
    return objects


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    body = longitudinal_loft(
        owner,
        "V11_R09_SHARED_SINGLE_ASYMMETRIC_MONOCOQUE",
        [
            (-0.535, 0.275, 0.270, 0.205),
            (-0.495, 0.342, 0.283, 0.190),
            (-0.405, 0.371, 0.292, 0.182),
            (-0.190, 0.375, 0.298, 0.180),
            (0.085, 0.375, 0.298, 0.180),
            (0.230, 0.355, 0.292, 0.176),
            (0.315, 0.300, 0.282, 0.160),
            (0.345, 0.245, 0.275, 0.145),
        ],
        0.29,
        mats["body_soft"],
        72,
    )
    body["source_occurrence_ids"] = "A01,A02,A03,A04,A10"
    body["design_intent"] = "one low half-egg monocoque; wheel coverage is the mother surface, never a fender"
    body["finished_width_mm"] = 750.0
    cut_wheel_cavities(body, owner)
    cut_tapered_seat_well(body, owner, mats["seam"])
    objects.append(body)

    horizon = rounded_prism_yz(
        owner,
        "V11_R09_A01_SINGLE_FLUSH_PERCEPTION_HORIZON",
        (-0.5367, 0.0, 0.295),
        0.310,
        0.026,
        0.0034,
        0.010,
        mats["glass"],
        0.00045,
    )
    horizon["source_occurrence_ids"] = "A01_perception_horizon_smoked_mask"
    objects.append(horizon)

    arms: dict[str, bpy.types.Object] = {}
    for side in ("LEFT", "RIGHT"):
        arm = arm_loft(owner, f"V11_R09_SHARED_FIXED_LOW_ARM_{side}", side, mats["body"])
        arm["source_occurrence_ids"] = f"A05_armrest_table_bay_shell_{side.lower()}"
        arm["fixed_armrest"] = True
        arm["maximum_main_top_mm"] = 655.0
        add_storage_cavity(arm, owner, 0.000 if side == "LEFT" else 0.020, mats["seam"])
        arms[side] = arm
        objects.append(arm)

    display_saddle = sloped_support_wedge(owner, mats["body"])
    boolean(arms["LEFT"], display_saddle, "UNION", "V11_R09_UNION_FIXED_DISPLAY_SADDLE")
    control_island = r01.rounded_box(
        owner,
        "V11_R09_TEMP_RIGHT_FIXED_HMI_ISLAND",
        (-0.265, 0.320, 0.676),
        (0.130, 0.090, 0.042),
        0.012,
        mats["body"],
        7,
    )
    boolean(arms["RIGHT"], control_island, "UNION", "V11_R09_UNION_FIXED_RIGHT_HMI_ISLAND")
    arms["RIGHT"]["fixed_hmi_bounds_mm"] = "x=-330..-200; contains joystick and authorisation; never moves with lid"

    left_lid = rounded_prism_xy(
        owner,
        "V11_R09_A05_LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID",
        (0.000, -0.320, 0.6558),
        0.440,
        0.100,
        0.0040,
        0.017,
        mats["body"],
        0.00045,
    )
    left_lid["source_occurrence_ids"] = "A05_armrest_table_bay_lid_left"
    left_lid["motion"] = "outward flip about outer edge; retrieve table; close lid"
    left_lid["owns_qi"] = True
    right_lid = rounded_prism_xy(
        owner,
        "V11_R09_A05_RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID",
        (0.020, 0.320, 0.6558),
        0.410,
        0.100,
        0.0040,
        0.017,
        mats["body"],
        0.00045,
    )
    right_lid["source_occurrence_ids"] = "A05_armrest_table_bay_lid_right"
    right_lid["motion"] = "outward flip about outer edge; fixed HMI island remains forward and exposed"
    right_lid["fixed_hmi_clearance_mm"] = 15.0
    objects.extend([left_lid, right_lid])
    left_seam = flat_outline_curve(owner, "V11_R09_A05_LEFT_ACCESS_LID_SEAM", (0.000, -0.320, 0.6582), 0.440, 0.100, 0.017, mats["seam"], 0.0007)
    right_seam = flat_outline_curve(owner, "V11_R09_A05_RIGHT_ACCESS_LID_SEAM", (0.020, 0.320, 0.6582), 0.410, 0.100, 0.017, mats["seam"], 0.0007)
    objects.extend([left_seam, right_seam])

    seat = r05.polygon_prism_xy(
        owner,
        "V11_R09_SHARED_TAPERED_NATURAL_LEATHER_SEAT",
        [(-0.312, -0.215), (-0.312, 0.215), (0.145, 0.245), (0.145, -0.245)],
        0.434,
        0.505,
        0.025,
        mats["shadow_leather"] if ACTIVE_STATE == "follow" else mats["leather"],
    )
    clean_mesh(seat)
    seat["source_occurrence_ids"] = "A04_seat_cushion_contact_island"
    seat["contact_width_front_rear_mm"] = [430.0, 490.0]
    objects.append(seat)

    objects.append(create_display(owner, mats))
    objects.extend(create_qi(owner, mats))

    for side, plane in (("LEFT", "LEFT_XZ"), ("RIGHT", "RIGHT_XZ")):
        door = projected_curve(
            owner,
            f"V11_R09_A04_{side}_FLUSH_EQUIPMENT_DOOR_SEAM",
            body,
            plane,
            (-0.020, 0.366),
            0.466,
            0.088,
            0.019,
            mats["seam"],
            0.0007,
        )
        door["source_occurrence_ids"] = f"A04_equipment_door_{side.lower()}"
        door["door_skin_is_mother_surface"] = True
        door["door_skin_mm"] = "464 x 86 R18"
        door["opening_mm"] = "466 x 88 R19"
        door["nominal_seam_mm"] = 1.0
        door["service_travel_mm"] = 300.0
        door["internal_rail_validation"] = "mandatory after STEP round-trip"
        objects.append(door)

    rear = projected_curve(
        owner,
        "V11_R09_A10_FLUSH_REAR_SERVICE_DOOR_SEAM",
        body,
        "REAR_YZ",
        (0.0, 0.315),
        0.370,
        0.198,
        0.024,
        mats["seam"],
        0.0007,
    )
    rear["source_occurrence_ids"] = "A10_rear_flush_service_door_skin"
    objects.append(rear)

    footrest_seam = projected_curve(
        owner,
        "V11_R09_A08_FRONT_TELESCOPIC_CASSETTE_SEAM",
        body,
        "FRONT_YZ",
        (0.0, 0.103),
        0.506,
        0.032,
        0.012,
        mats["seam"],
        0.00075,
    )
    footrest_seam["source_occurrence_ids"] = "A08_footrest_cassette_opening"
    footrest_seam["stow_motion"] = "+220 mm X telescopic translation; 506 x 32 mm physical opening"
    footrest_seam["default_state"] = "open in Ride; closed in Follow/Cafe/Focus; optional only when parked"
    objects.append(footrest_seam)

    objects.extend(build_footrest(owner, mats))
    objects.extend(build_tables(owner, mats))
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R09_{state.upper()}_A06_ICONIC_FRONT_TRAPEZOID",
        0.135,
        0.265,
        0.535,
        1.035,
        0.258,
        0.215,
        mats["body"],
        0.018,
    )
    clean_mesh(shell)
    shell["source_occurrence_ids"] = "A06_backrest_moving_shell"
    shell["identity"] = "same strong front-view trapezoid in all states; same part is Follow upper surface"
    contact = r01.trapezoid_prism(
        owner,
        f"V11_R09_{state.upper()}_A06_NATURAL_LEATHER_CONTACT",
        0.127,
        0.136,
        0.572,
        0.987,
        0.235,
        0.188,
        mats["leather"],
        0.003,
    )
    clean_mesh(contact)
    contact["source_occurrence_ids"] = "A06_backrest_contact_island"
    parts.extend([shell, contact])

    mast = r01.trapezoid_prism(
        owner,
        f"V11_R09_{state.upper()}_A07_ORIGINAL_EXPOSED_TRAPEZOID_BLADE",
        0.270,
        0.290,
        0.575,
        1.065,
        0.050,
        0.034,
        mats["glass"],
        0.005,
    )
    clean_mesh(mast)
    mast["source_occurrence_ids"] = "A07_sensor_mast_moving"
    mast["motion_contract"] = "same exposed mesh; Ride/Cafe low, Focus +420 mm Z, Follow co-fold"
    crown = r01.rounded_box(
        owner,
        f"V11_R09_{state.upper()}_A07_COMPACT_SENSOR_CROWN",
        (0.280, 0.0, 1.065),
        (0.034, 0.240, 0.032),
        0.011,
        mats["body_soft"],
        7,
    )
    clean_mesh(crown)
    crown["source_occurrence_ids"] = "A07_sensor_head"
    window = rounded_prism_yz(
        owner,
        f"V11_R09_{state.upper()}_A07_SENSOR_WINDOW",
        (0.2618, 0.0, 1.064),
        0.190,
        0.012,
        0.0024,
        0.005,
        mats["glass"],
        0.00035,
    )
    window["source_occurrence_ids"] = "A07_sensor_window"
    mast_parts = [mast, crown, window]
    parts.extend(mast_parts)

    if state == "focus":
        for obj in mast_parts:
            obj.location.z += 0.420
            obj["focus_translation_z_mm"] = 420.0
    elif state == "follow":
        pivot = bpy.data.objects.new("V11_R09_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.535)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-90.0)
        pivot["fold_angle_deg"] = -90.0
        pivot["allowed_children"] = "same A06 shell/contact and same A07 blade/crown/window only; no hood or filler"
        parts.append(pivot)
    return parts


def studio(scene: bpy.types.Scene, owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> None:
    BASE_STUDIO(scene, owner, state, mats)
    if scene.world and scene.world.use_nodes:
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.105, 0.095, 0.086, 1.0)
            background.inputs["Strength"].default_value = 0.62
    settings = {
        "V11_KEY": (980.0, (1.0, 0.88, 0.76)),
        "V11_FILL": (720.0, (0.72, 0.82, 1.0)),
        "V11_RIM": (820.0, (1.0, 0.69, 0.48)),
    }
    for name, (energy, colour) in settings.items():
        light = bpy.data.objects.get(name)
        if light and light.type == "LIGHT":
            light.data.energy = energy
            light.data.color = colour
    scene.view_settings.exposure = -0.08


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
        "a04_door_mm": "mother-surface door; 464 x 86 R18 in 466 x 88 R19; 1 mm nominal seam; 300 mm rail",
        "display": "uniform 124 x 49 x 2.5 mm plate; world-Y +8 deg; front high/rear low",
        "qi_usable_field_mm": "176 x 86; single flush field on left lid",
        "focus_a07_motion_mm": 420.0 if ACTIVE_STATE == "focus" else 0.0,
        "follow_fold_deg": -90.0 if ACTIVE_STATE == "follow" else 0.0,
        "footrest": "+220 mm X telescopic stow; open only in Ride default",
        "table": "Cafe right only; Focus both; all surfaces >=10 mm inboard of arm inner face",
    }
    payload["r09_form_changes"] = [
        "one longitudinally lofted monocoque replaces the saddle-plus-wheel-lobe stack",
        "fixed low arms now follow the folded A06 taper and sit within 8 mm of its main top plane",
        "A06 outer shell itself is the strong front-view trapezoid and the only Follow upper surface",
        "uniform thin display, fixed right HMI island and non-overlapping outward-flip access lids",
        "real table storage cavities and closed lids; only hidden under-table necks cross the inner wall",
        "single-piece telescopic footrest replaces the impossible rotating platform",
        "A04/A10/A08 seams are ray-projected onto the saved mother surface",
        "procedural walnut, leather and mineral microtexture replace flat prototype colours",
    ]
    payload["known_limits"] = [
        "Blender visual/layout decision model; production BRep and internal 31-item equipment package are not yet revalidated",
        "table hand sweep, rail strength, tyre tolerance/debris and service travel require STEP round-trip gates",
        "build status remains unvalidated until the saved blend is reopened by the R09 validator",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R09_BUILT_UNVALIDATED", ACTIVE_STATE, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
