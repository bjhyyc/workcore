"""Full saved-file geometry validation for WorkCore E6 V11 R13.

This validator extends the R12 measurement library but defines R13 contracts
independently.  In particular, the same A08 footrest assembly must exist in all
four files: deployed in Ride and translated exactly +220 mm world X into a real
cassette in Follow/Cafe/Focus.

Run::

    D:\\blender\\blender.exe --background --factory-startup \
      --python scripts/validate_v11_r13.py -- --wheel-grid 160

Blender units are metres.  Report dimensions are millimetres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import bpy
from mathutils import Vector


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
V11_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
import validate_v11_r12 as base  # noqa: E402


REVISION = "r13"
STATES = ("follow", "ride", "cafe", "focus")
STATE_PATHS = {
    state: V11_ROOT
    / "blender"
    / "states"
    / REVISION
    / f"workcore_e6_v11_{state}_{REVISION}.blend"
    for state in STATES
}
DEFAULT_OUTPUT = V11_ROOT / "qa" / REVISION / "validation_summary.json"

BODY_SOURCE = (
    "A01_front_nose_shell,A02_main_side_shell_left,A02_main_side_shell_right,"
    "A03_continuous_wheel_belt_shell_left,A03_continuous_wheel_belt_shell_right,"
    "A04_open_u_seat_pan_ring,A04_underseat_belly_closeout,A10_rear_service_surround"
)
ROLE_SOURCES = {
    "a06_shell": "A06_backrest_weather_shell",
    "a06_contact": "A06_backrest_contact_panel",
    "a07_mast": "A07_mast_fixed_outer_sleeve,A07_mast_moving_inner_sleeve",
    "a07_crown": "A07_sensor_beam_shell",
    "a07_window": "A07_sensor_beam_smoked_window",
}
FOOTREST_ROLE_TOKENS = {
    "platform": "A08_SINGLE_PIECE_TELESCOPIC_FOOTREST",
    "tread": "A08_NATURAL_RUBBER_TREAD_INLAY",
    "leading_edge": "A08_LIMITED_316_LEADING_EDGE",
}

WIDTH_LIMIT_MM = 752.0
DIM_TOL_MM = 0.05
POSE_TOL_MM = 0.05
ANGLE_TOL_DEG = 0.05
DISPLAY_CONTACT_TOL_MM = 0.75
DOOR_SEAM_MAX_OFFSET_MM = 1.2
FOOTREST_TRANSLATION_MM = 220.0
FOOTREST_TRANSLATION_TOL_MM = 0.05
CAVITY_CONTAINMENT_TOL_MM = 0.10
BODY_PENETRATION_TOL_MM = 0.25
EMERGENCY_VISIBLE_RATIO_MIN = 0.60
EMERGENCY_PROTRUSION_MIN_MM = 1.0
TABLE_JOYSTICK_EDGE_CLEARANCE_MIN_MM = 100.0


# Rebind the R12 helper module's data-driven role functions to R13.
base.REVISION = REVISION
base.STATES = STATES
base.STATE_PATHS = STATE_PATHS
base.ROLE_SOURCES = ROLE_SOURCES


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--wheel-grid", type=int, default=128)
    parser.add_argument("--emergency-grid", type=int, default=80)
    return parser.parse_args(raw)


def body_object() -> bpy.types.Object | None:
    matches = [
        obj
        for obj in base.design_objects()
        if obj.type == "MESH"
        and "SINGLE_ASYMMETRIC_MONOCOQUE" in obj.name
        and obj.get("source_occurrence_ids") == BODY_SOURCE
    ]
    return matches[0] if len(matches) == 1 else None


def functional_occurrence(occurrence: str) -> bpy.types.Object | None:
    matches = [
        obj
        for obj in base.functional_objects()
        if str(obj.get("wc_occurrence_id", "")) == occurrence
    ]
    return matches[0] if len(matches) == 1 else None


def object_bounds(obj: bpy.types.Object | None) -> dict[str, list[float]] | None:
    return base.bounds_from_vertices(base.raw_world_vertices(obj)) if obj is not None else None


def mesh_shape_signature(obj: bpy.types.Object) -> str:
    """Translation-invariant mesh signature used for the baked A08 geometry."""

    vertices = [vertex.co.copy() for vertex in obj.data.vertices]
    centre = sum(vertices, Vector((0.0, 0.0, 0.0))) / max(len(vertices), 1)
    payload = {
        "vertices": [
            # One-micron quantisation removes harmless float32 error caused by
            # baking the same shape at X positions 220 mm apart.  The separate
            # vertex-by-vertex pose gate remains 0.05 mm and is authoritative.
            [base.round_float(value, 6) for value in (vertex - centre)] for vertex in vertices
        ],
        "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def topology_measurement(objects: Iterable[bpy.types.Object]) -> dict[str, Any]:
    objects = list(objects)
    degeneracy = base.mesh_degeneracy(objects)
    rows: list[dict[str, Any]] = []
    totals = defaultdict(int)
    for obj in objects:
        if obj.type != "MESH":
            continue
        incidence: dict[tuple[int, int], int] = defaultdict(int)
        for polygon in obj.data.polygons:
            indices = list(polygon.vertices)
            for left, right in zip(indices, indices[1:] + indices[:1]):
                incidence[tuple(sorted((left, right)))] += 1
        mesh_edges = {tuple(sorted(edge.vertices)) for edge in obj.data.edges}
        loose = sum(1 for edge in mesh_edges if incidence.get(edge, 0) == 0)
        boundary = sum(1 for count in incidence.values() if count == 1)
        multi_face = sum(1 for count in incidence.values() if count > 2)
        implicit_edges = sum(1 for edge in incidence if edge not in mesh_edges)
        nonmanifold = loose + boundary + multi_face + implicit_edges
        totals["mesh_objects"] += 1
        totals["loose_edges"] += loose
        totals["boundary_edges"] += boundary
        totals["multi_face_edges"] += multi_face
        totals["implicit_polygon_edges"] += implicit_edges
        totals["nonmanifold_edges"] += nonmanifold
        if nonmanifold:
            rows.append(
                {
                    "object": obj.name,
                    "loose_edges": loose,
                    "boundary_edges": boundary,
                    "multi_face_edges": multi_face,
                    "implicit_polygon_edges": implicit_edges,
                    "nonmanifold_edges": nonmanifold,
                }
            )
    zero_edges = degeneracy["totals"].get("zero_length_edges", 0)
    zero_faces = degeneracy["totals"].get("zero_area_faces", 0)
    passed = zero_edges == 0 and zero_faces == 0 and totals["nonmanifold_edges"] == 0
    return {
        "pass": passed,
        "degeneracy": degeneracy,
        "manifold_totals": dict(totals),
        "objects_with_nonmanifold_edges": rows,
        "criteria": "zero zero-length edges, zero zero-area faces, every mesh edge used by exactly two faces",
    }


def display_measurement() -> dict[str, Any]:
    displays = base.objects_by_name_token("A05_SINGLE_FLUSH_DISPLAY", base.design_objects())
    if len(displays) != 1:
        return {"pass": False, "object_count": len(displays), "objects": [obj.name for obj in displays]}
    display = displays[0]
    dimensions = base.oriented_dimensions_mm(display)
    axis_x = display.matrix_world.to_3x3().col[0].normalized()
    pitch_deg = math.degrees(math.atan2(-axis_x.z, axis_x.x))
    local_vertices = [vertex.co.copy() for vertex in display.data.vertices]
    x_min = min(point.x for point in local_vertices)
    x_max = max(point.x for point in local_vertices)
    y_min = min(point.y for point in local_vertices)
    y_max = max(point.y for point in local_vertices)
    z_min = min(point.z for point in local_vertices)
    front = display.matrix_world @ Vector((x_min, 0.0, 0.0))
    rear = display.matrix_world @ Vector((x_max, 0.0, 0.0))
    front_high_delta_mm = base.mm(front.z - rear.z)

    arm = base.object_by_exact_source("A05_armrest_table_bay_shell_left")
    gaps: list[float] = []
    misses = 0
    if arm is not None:
        arm_bvh = base.world_bvh(arm)
        for fx in (0.08, 0.25, 0.50, 0.75, 0.92):
            for fy in (0.18, 0.50, 0.82):
                underside = display.matrix_world @ Vector(
                    (
                        x_min + (x_max - x_min) * fx,
                        y_min + (y_max - y_min) * fy,
                        z_min,
                    )
                )
                hit, _normal, _index, _distance = arm_bvh.ray_cast(
                    underside + Vector((0.0, 0.0, 0.020)),
                    Vector((0.0, 0.0, -1.0)),
                    0.050,
                )
                if hit is None:
                    misses += 1
                else:
                    gaps.append(base.mm(underside.z - hit.z, 4))
    else:
        misses = 15
    maximum_absolute = max((abs(value) for value in gaps), default=math.inf)
    contact_pass = misses == 0 and maximum_absolute <= DISPLAY_CONTACT_TOL_MM

    forbidden_support_tokens = ("DISPLAY_SADDLE", "HMI_ISLAND", "HMI_PLINTH")
    separate_supports = [
        obj.name
        for obj in base.design_objects()
        if any(token in obj.name.upper() for token in forbidden_support_tokens)
    ]
    geometry_pass = (
        abs(dimensions[0] - 124.0) <= DIM_TOL_MM
        and abs(dimensions[1] - 49.0) <= DIM_TOL_MM
        and abs(dimensions[2] - 2.5) <= DIM_TOL_MM
        and abs(pitch_deg - 8.0) <= ANGLE_TOL_DEG
        and front_high_delta_mm > 0.0
    )
    return {
        "pass": geometry_pass and contact_pass and not separate_supports,
        "object": display.name,
        "oriented_dimensions_mm": dimensions,
        "required_dimensions_mm": [124.0, 49.0, 2.5],
        "world_y_pitch_deg": base.round_float(pitch_deg, 5),
        "front_minus_rear_height_mm": front_high_delta_mm,
        "front_high_rear_low": front_high_delta_mm > 0.0,
        "direct_arm_contact": {
            "pass": contact_pass,
            "sample_count": 15,
            "ray_misses": misses,
            "vertical_gap_mm": {
                "min": min(gaps) if gaps else None,
                "max": max(gaps) if gaps else None,
                "mean": base.round_float(sum(gaps) / len(gaps), 4) if gaps else None,
                "maximum_absolute": base.round_float(maximum_absolute, 4)
                if math.isfinite(maximum_absolute)
                else None,
            },
            "tolerance_mm": DISPLAY_CONTACT_TOL_MM,
        },
        "separate_support_objects": separate_supports,
        "contract": "one glass layer lands directly on the continuous left-arm mother surface",
    }


def material_base_colour(obj: bpy.types.Object) -> dict[str, Any]:
    materials = [slot.material for slot in obj.material_slots if slot.material is not None]
    rows = []
    for material in materials:
        colour = None
        if material.use_nodes and material.node_tree:
            principled = next(
                (node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"),
                None,
            )
            if principled is not None and principled.inputs.get("Base Color") is not None:
                colour = [float(value) for value in principled.inputs["Base Color"].default_value]
        rows.append({"material": material.name, "base_colour_linear_rgba": colour})
    is_red = any(
        row["base_colour_linear_rgba"] is not None
        and row["base_colour_linear_rgba"][0] >= 0.10
        and row["base_colour_linear_rgba"][0] >= row["base_colour_linear_rgba"][1] * 5.0
        and row["base_colour_linear_rgba"][0] >= row["base_colour_linear_rgba"][2] * 5.0
        for row in rows
    )
    return {"pass": is_red, "materials": rows}


def emergency_visibility(stop: bpy.types.Object, guard: bpy.types.Object, grid: int) -> dict[str, Any]:
    stop_bounds = object_bounds(stop)
    if stop_bounds is None:
        return {"pass": False, "reason": "empty emergency-stop mesh"}
    stop_bvh = base.world_bvh(stop)
    occluders = [
        obj
        for obj in base.design_objects()
        if obj.type == "MESH" and obj != stop
    ] + [guard]
    occluder_bvhs = [base.world_bvh(obj) for obj in occluders]
    x_min, _y_min, z_min = stop_bounds["min_m"]
    x_max, _y_max, z_max = stop_bounds["max_m"]
    direction = Vector((0.0, 1.0, 0.0))
    projected = 0
    visible = 0
    for ix in range(grid):
        x = x_min + (x_max - x_min) * ((ix + 0.5) / grid)
        for iz in range(grid):
            z = z_min + (z_max - z_min) * ((iz + 0.5) / grid)
            origin = Vector((x, -1.0, z))
            stop_distance = base.ray_distance(stop_bvh, origin, direction)
            if stop_distance is None:
                continue
            projected += 1
            distances = [base.ray_distance(bvh, origin, direction) for bvh in occluder_bvhs]
            nearest = min((value for value in distances if value is not None), default=math.inf)
            if stop_distance <= nearest + 1.0e-6:
                visible += 1
    ratio = visible / projected if projected else 0.0
    return {
        "pass": projected > 0 and ratio >= EMERGENCY_VISIBLE_RATIO_MIN,
        "grid": [grid, grid],
        "projected_stop_samples": projected,
        "visible_samples": visible,
        "visible_ratio": base.round_float(ratio, 5),
        "minimum_visible_ratio": EMERGENCY_VISIBLE_RATIO_MIN,
        "view": "orthographic from left/service side (-Y toward +Y)",
    }


def emergency_stop_measurement(grid: int) -> dict[str, Any]:
    stop = functional_occurrence("A05_left_mechanical_emergency_stop")
    guard = functional_occurrence("A05_left_emergency_stop_guard")
    body = body_object()
    if stop is None or guard is None or body is None:
        return {
            "pass": False,
            "stop_present": stop is not None,
            "guard_present": guard is not None,
            "body_present": body is not None,
        }
    stop_bounds = object_bounds(stop)
    guard_bounds = object_bounds(guard)
    body_bounds = object_bounds(body)
    assert stop_bounds and guard_bounds and body_bounds
    body_left_y = body_bounds["min_m"][1]
    stop_protrusion = (body_left_y - stop_bounds["min_m"][1]) * 1000.0
    guard_protrusion = (body_left_y - guard_bounds["min_m"][1]) * 1000.0
    guard_contains_stop_xz = (
        guard_bounds["min_m"][0] <= stop_bounds["min_m"][0]
        and guard_bounds["max_m"][0] >= stop_bounds["max_m"][0]
        and guard_bounds["min_m"][2] <= stop_bounds["min_m"][2]
        and guard_bounds["max_m"][2] >= stop_bounds["max_m"][2]
    )
    colour = material_base_colour(stop)
    visibility = emergency_visibility(stop, guard, grid)
    accessible = (
        stop_protrusion >= EMERGENCY_PROTRUSION_MIN_MM
        and visibility["pass"]
        and guard_contains_stop_xz
    )
    return {
        "pass": accessible and colour["pass"],
        "stop_object": stop.name,
        "guard_object": guard.name,
        "stop_bounds": stop_bounds,
        "guard_bounds": guard_bounds,
        "body_leftmost_y_mm": base.mm(body_left_y),
        "stop_outward_protrusion_beyond_body_mm": base.round_float(stop_protrusion, 3),
        "guard_outward_protrusion_beyond_body_mm": base.round_float(guard_protrusion, 3),
        "minimum_stop_protrusion_mm": EMERGENCY_PROTRUSION_MIN_MM,
        "guard_encloses_stop_projection_xz": guard_contains_stop_xz,
        "red_material": colour,
        "left_side_visibility": visibility,
        "visible_and_touchable": accessible,
    }


def table_measurement(state: str, joystick: dict[str, Any]) -> dict[str, Any]:
    tables = [
        obj
        for obj in base.design_objects()
        if obj.type == "MESH" and "A09_" in obj.name and "WALNUT_SURFACE" in obj.name
    ]
    supports = [
        obj
        for obj in base.design_objects()
        if obj.type == "MESH" and "A09_" in obj.name and "HIDDEN_INBOARD_NECK" in obj.name
    ]
    table_rows = [{"object": obj.name, "bounds": object_bounds(obj)} for obj in tables]
    support_rows = [{"object": obj.name, "bounds": object_bounds(obj)} for obj in supports]
    joystick_bounds = None
    joystick_obj = functional_occurrence("A05_right_joystick")
    if joystick_obj is not None:
        joystick_bounds = object_bounds(joystick_obj)

    if state in {"follow", "ride"}:
        return {
            "pass": len(tables) == 0 and len(supports) == 0,
            "table_count": len(tables),
            "support_neck_count": len(supports),
            "tables": table_rows,
            "support_necks": support_rows,
            "expected": "no deployed table or exposed support neck",
        }

    if state == "cafe":
        if len(tables) != 1 or len(supports) != 2 or table_rows[0]["bounds"] is None:
            return {
                "pass": False,
                "table_count": len(tables),
                "support_neck_count": len(supports),
                "tables": table_rows,
                "support_necks": support_rows,
            }
        bounds = table_rows[0]["bounds"]
        assert bounds is not None
        y_min = bounds["min_m"][1] * 1000.0
        y_max = bounds["max_m"][1] * 1000.0
        edge_clearance = (
            joystick_bounds["min_m"][1] * 1000.0 - y_max if joystick_bounds else None
        )
        centre_clearance = (
            joystick_bounds["centre_mm"][1] - y_max if joystick_bounds else None
        )
        supports_under = all(
            row["bounds"] is not None
            and row["bounds"]["max_m"][2] <= bounds["min_m"][2] + 5.0e-5
            for row in support_rows
        )
        passed = (
            "CAFE_RIGHT" in tables[0].name
            and abs(bounds["size_mm"][0] - 250.0) <= DIM_TOL_MM
            and abs(bounds["size_mm"][1] - 400.0) <= DIM_TOL_MM
            and abs(y_min - (-190.0)) <= DIM_TOL_MM
            and abs(y_max - 210.0) <= DIM_TOL_MM
            and edge_clearance is not None
            and edge_clearance >= TABLE_JOYSTICK_EDGE_CLEARANCE_MIN_MM
            and supports_under
        )
        return {
            "pass": passed,
            "table_count": 1,
            "support_neck_count": 2,
            "tables": table_rows,
            "support_necks": support_rows,
            "required_y_bounds_mm": [-190.0, 210.0],
            "actual_y_bounds_mm": [base.round_float(y_min, 3), base.round_float(y_max, 3)],
            "joystick_edge_clearance_mm": base.round_float(edge_clearance, 3)
            if edge_clearance is not None
            else None,
            "joystick_centreline_clearance_mm": base.round_float(centre_clearance, 3)
            if centre_clearance is not None
            else None,
            "minimum_edge_clearance_mm": TABLE_JOYSTICK_EDGE_CLEARANCE_MIN_MM,
            "supports_entirely_at_or_below_table_underside": supports_under,
        }

    if len(tables) != 2 or len(supports) != 4:
        return {
            "pass": False,
            "table_count": len(tables),
            "support_neck_count": len(supports),
            "tables": table_rows,
            "support_necks": support_rows,
        }
    left = next((row for row in table_rows if "FOCUS_LEFT" in row["object"]), None)
    right = next((row for row in table_rows if "FOCUS_RIGHT" in row["object"]), None)
    if left is None or right is None or left["bounds"] is None or right["bounds"] is None:
        return {"pass": False, "tables": table_rows, "support_necks": support_rows}
    left_bounds = left["bounds"]
    right_bounds = right["bounds"]
    centre_gap = (right_bounds["min_m"][1] - left_bounds["max_m"][1]) * 1000.0
    edge_clearance = (
        (joystick_bounds["min_m"][1] - right_bounds["max_m"][1]) * 1000.0
        if joystick_bounds
        else None
    )
    supports_under = all(
        row["bounds"] is not None
        and row["bounds"]["max_m"][2] <= 0.672 + 5.0e-5
        for row in support_rows
    )
    passed = (
        all(
            abs(row["bounds"]["size_mm"][0] - 400.0) <= DIM_TOL_MM
            and abs(row["bounds"]["size_mm"][1] - 202.0) <= DIM_TOL_MM
            for row in (left, right)
        )
        and abs(left_bounds["min_m"][1] * 1000.0 - (-210.0)) <= DIM_TOL_MM
        and abs(left_bounds["max_m"][1] * 1000.0 - (-8.0)) <= DIM_TOL_MM
        and abs(right_bounds["min_m"][1] * 1000.0 - 8.0) <= DIM_TOL_MM
        and abs(right_bounds["max_m"][1] * 1000.0 - 210.0) <= DIM_TOL_MM
        and abs(centre_gap - 16.0) <= DIM_TOL_MM
        and edge_clearance is not None
        and edge_clearance >= TABLE_JOYSTICK_EDGE_CLEARANCE_MIN_MM
        and supports_under
    )
    return {
        "pass": passed,
        "table_count": 2,
        "support_neck_count": 4,
        "tables": table_rows,
        "support_necks": support_rows,
        "required_y_bounds_mm": {"left": [-210.0, -8.0], "right": [8.0, 210.0]},
        "centre_gap_mm": base.round_float(centre_gap, 3),
        "joystick_edge_clearance_mm": base.round_float(edge_clearance, 3)
        if edge_clearance is not None
        else None,
        "minimum_edge_clearance_mm": TABLE_JOYSTICK_EDGE_CLEARANCE_MIN_MM,
        "supports_entirely_at_or_below_table_underside": supports_under,
    }


def footrest_parts() -> dict[str, bpy.types.Object | None]:
    result: dict[str, bpy.types.Object | None] = {}
    for role, token in FOOTREST_ROLE_TOKENS.items():
        matches = base.objects_by_name_token(token, base.design_objects())
        result[role] = matches[0] if len(matches) == 1 else None
    return result


def footrest_role_data() -> dict[str, Any]:
    result = {}
    for role, obj in footrest_parts().items():
        if obj is None:
            result[role] = {"present": False}
            continue
        result[role] = {
            "present": True,
            "object": obj.name,
            "stowed_name": "STOWED" in obj.name,
            "shape_sha256": mesh_shape_signature(obj),
            "topology_sha256": hashlib.sha256(
                json.dumps(
                    [list(polygon.vertices) for polygon in obj.data.polygons],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "world_vertices_m": [[float(value) for value in point] for point in base.raw_world_vertices(obj)],
            "bounds": object_bounds(obj),
        }
    return result


def cavity_envelope(state: str) -> dict[str, list[float]]:
    if state == "ride":
        centre_x, length_x = -0.493, 0.450
    else:
        centre_x, length_x = -0.3875, 0.245
    return {
        "min_m": [centre_x - length_x * 0.5, -0.253, 0.084],
        "max_m": [centre_x + length_x * 0.5, 0.253, 0.122],
        "size_mm": [length_x * 1000.0, 506.0, 38.0],
    }


def signed_body_clearance_samples(
    part: bpy.types.Object,
    body_bvh: Any,
) -> dict[str, Any]:
    vertices = base.raw_world_vertices(part)
    signed: list[float] = []
    signed_points: list[tuple[float, Vector, Vector]] = []
    parity_inside = 0
    misses = 0
    for point in vertices:
        nearest, normal, _index, _distance = body_bvh.find_nearest(point)
        if nearest is None or normal is None:
            misses += 1
            continue
        value = (point - nearest).dot(normal) * 1000.0
        signed.append(value)
        signed_points.append((value, point, nearest))
        # The monocoque is independently required to be closed/manifold.  A
        # ray-parity test is therefore a more reliable solid-membership test
        # than the nearest-face normal around the cassette's open front edge.
        direction = Vector((0.83719, 0.33173, 0.43511)).normalized()
        cursor = point + direction * 1.0e-7
        intersections = 0
        for _iteration in range(64):
            hit, _hit_normal, _hit_index, _hit_distance = body_bvh.ray_cast(
                cursor, direction, 5.0
            )
            if hit is None:
                break
            intersections += 1
            cursor = hit + direction * 1.0e-6
        if intersections % 2 == 1:
            parity_inside += 1
    penetrating = sum(1 for value in signed if value < -BODY_PENETRATION_TOL_MM)
    minimum_row = min(signed_points, key=lambda row: row[0]) if signed_points else None
    penetrating_world = [point for value, point, _nearest in signed_points if value < -BODY_PENETRATION_TOL_MM]
    penetration_bounds = base.bounds_from_vertices(penetrating_world)
    return {
        "pass": misses == 0 and parity_inside == 0,
        "sample_count": len(vertices),
        "nearest_query_misses": misses,
        "minimum_signed_clearance_mm": base.round_float(min(signed), 4) if signed else None,
        "maximum_signed_clearance_mm": base.round_float(max(signed), 4) if signed else None,
        "minimum_clearance_sample_world_mm": [base.mm(value, 4) for value in minimum_row[1]]
        if minimum_row
        else None,
        "nearest_body_point_at_minimum_world_mm": [base.mm(value, 4) for value in minimum_row[2]]
        if minimum_row
        else None,
        "penetrating_samples_beyond_tolerance": penetrating,
        "penetrating_sample_bounds": penetration_bounds,
        "inside_monocoque_samples_by_ray_parity": parity_inside,
        "solid_membership_gate": "closed-mesh ray parity; signed nearest-normal value retained as diagnostic",
        "penetration_tolerance_mm": BODY_PENETRATION_TOL_MM,
        "sign_convention": "positive is outside monocoque material / in free space",
    }


def footrest_measurement(state: str, body: bpy.types.Object | None) -> dict[str, Any]:
    parts = footrest_parts()
    if body is None or any(obj is None for obj in parts.values()):
        return {
            "pass": False,
            "body_present": body is not None,
            "roles_present": {role: obj is not None for role, obj in parts.items()},
            "role_data": footrest_role_data(),
        }
    physical_parts = [obj for obj in parts.values() if obj is not None]
    assembly_bounds = base.combined_bounds(physical_parts)
    envelope = cavity_envelope(state)
    assert assembly_bounds is not None
    margins = {
        "x_min": (assembly_bounds["min_m"][0] - envelope["min_m"][0]) * 1000.0,
        "x_max": (envelope["max_m"][0] - assembly_bounds["max_m"][0]) * 1000.0,
        "y_min": (assembly_bounds["min_m"][1] - envelope["min_m"][1]) * 1000.0,
        "y_max": (envelope["max_m"][1] - assembly_bounds["max_m"][1]) * 1000.0,
        "z_min": (assembly_bounds["min_m"][2] - envelope["min_m"][2]) * 1000.0,
        "z_max": (envelope["max_m"][2] - assembly_bounds["max_m"][2]) * 1000.0,
    }
    containment_pass = min(margins.values()) >= -CAVITY_CONTAINMENT_TOL_MM

    declared = list(body.get("a08_real_cassette_void_mm", []))
    expected_declared = envelope["size_mm"]
    declared_pass = len(declared) == 3 and all(
        abs(float(declared[index]) - expected_declared[index]) <= DIM_TOL_MM
        for index in range(3)
    )
    translation_declared = float(body.get("a08_stow_translation_x_mm", math.nan))
    translation_property_pass = abs(translation_declared - FOOTREST_TRANSLATION_MM) <= DIM_TOL_MM

    body_bvh = base.world_bvh(body)
    collision_rows = []
    interference_pass = True
    for role, part in parts.items():
        assert part is not None
        overlap_pairs = len(body_bvh.overlap(base.world_bvh(part)))
        signed = signed_body_clearance_samples(part, body_bvh)
        part_pass = overlap_pairs == 0 and signed["pass"]
        interference_pass = interference_pass and part_pass
        collision_rows.append(
            {
                "role": role,
                "object": part.name,
                "pass": part_pass,
                "triangle_overlap_pairs_with_monocoque": overlap_pairs,
                "signed_clearance": signed,
            }
        )

    expected_stowed = state != "ride"
    naming_pass = all(("STOWED" in obj.name) == expected_stowed for obj in physical_parts)
    return {
        "pass": containment_pass
        and declared_pass
        and translation_property_pass
        and interference_pass
        and naming_pass,
        "expected_stowed": expected_stowed,
        "same_three_physical_roles_present": True,
        "stowed_naming_matches_state": naming_pass,
        "assembly_bounds": assembly_bounds,
        "cassette_envelope": envelope,
        "cassette_containment_margins_mm": {
            key: base.round_float(value, 4) for key, value in margins.items()
        },
        "cassette_containment_pass": containment_pass,
        "saved_body_cassette_void_mm": declared,
        "saved_body_cassette_void_matches_contract": declared_pass,
        "saved_body_stow_translation_x_mm": translation_declared,
        "saved_body_stow_translation_matches_contract": translation_property_pass,
        "mother_surface_interference_pass": interference_pass,
        "part_collision_checks": collision_rows,
        "role_data": footrest_role_data(),
    }


def validate_footrest_four_state(states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = states["ride"]["footrest"]["role_data"]
    rows = []
    all_pass = True
    for role in FOOTREST_ROLE_TOKENS:
        baseline_role = baseline.get(role, {})
        hashes = {}
        topology_hashes = {}
        errors = {}
        role_pass = bool(baseline_role.get("present"))
        for state in STATES:
            current = states[state]["footrest"]["role_data"].get(role, {})
            hashes[state] = current.get("shape_sha256")
            topology_hashes[state] = current.get("topology_sha256")
            if not current.get("present") or not baseline_role.get("present"):
                errors[state] = None
                role_pass = False
                continue
            if current.get("topology_sha256") != baseline_role.get("topology_sha256"):
                role_pass = False
            base_vertices = baseline_role["world_vertices_m"]
            current_vertices = current["world_vertices_m"]
            if len(base_vertices) != len(current_vertices):
                errors[state] = None
                role_pass = False
                continue
            expected_translation = 0.0 if state == "ride" else FOOTREST_TRANSLATION_MM / 1000.0
            maximum = 0.0
            for base_point, current_point in zip(base_vertices, current_vertices):
                expected = Vector(base_point) + Vector((expected_translation, 0.0, 0.0))
                maximum = max(maximum, (Vector(current_point) - expected).length)
            errors[state] = base.mm(maximum, 6)
            if errors[state] > FOOTREST_TRANSLATION_TOL_MM:
                role_pass = False
        rows.append(
            {
                "role": role,
                "pass": role_pass,
                "diagnostic_translation_invariant_shape_sha256_by_state": hashes,
                "bitwise_quantised_shape_hashes_identical": len(set(hashes.values())) == 1,
                "topology_sha256_by_state": topology_hashes,
                "same_topology_all_states": len(set(topology_hashes.values())) == 1,
                "maximum_expected_pose_error_mm_by_state": errors,
                "geometry_and_pose_gate": (
                    "same polygon topology plus vertex-by-vertex agreement with Ride + expected X translation; "
                    "bitwise centred-coordinate hash is diagnostic only"
                ),
            }
        )
        all_pass = all_pass and role_pass
    state_gates = all(states[state]["footrest"].get("pass") for state in STATES)
    return {
        "pass": all_pass and state_gates,
        "same_geometry_and_exact_translation_pass": all_pass,
        "all_state_cavity_and_interference_gates_pass": state_gates,
        "contract": "Ride deployed; identical geometry translated exactly +220 mm world X in Follow/Cafe/Focus",
        "translation_tolerance_mm": FOOTREST_TRANSLATION_TOL_MM,
        "roles": rows,
    }


def equipment_door_measurement(body: bpy.types.Object | None) -> dict[str, Any]:
    seams = [
        obj
        for obj in base.design_objects()
        if obj.type == "CURVE" and "A04_" in obj.name and "EQUIPMENT_DOOR_SEAM" in obj.name
    ]
    if body is None or len(seams) != 2:
        return {"pass": False, "seam_count": len(seams), "body_present": body is not None}
    bvh = base.world_bvh(body)
    rows = []
    all_distances = []
    for seam in seams:
        distances = []
        for point in base.curve_control_points_world(seam):
            _nearest, _normal, _index, distance = bvh.find_nearest(point)
            if distance is not None:
                distances.append(base.mm(distance, 4))
        all_distances.extend(distances)
        rows.append(
            {
                "object": seam.name,
                "source_occurrence_ids": seam.get("source_occurrence_ids"),
                "control_points": len(distances),
                "offset_mm": {
                    "min": min(distances) if distances else None,
                    "max": max(distances) if distances else None,
                    "mean": base.round_float(sum(distances) / len(distances), 4)
                    if distances
                    else None,
                },
            }
        )
    maximum = max(all_distances, default=math.inf)
    return {
        "pass": bool(all_distances) and maximum <= DOOR_SEAM_MAX_OFFSET_MM,
        "seam_count": len(seams),
        "maximum_curve_to_mother_surface_offset_mm": base.round_float(maximum, 4)
        if math.isfinite(maximum)
        else None,
        "tolerance_mm": DOOR_SEAM_MAX_OFFSET_MM,
        "seams": rows,
    }


def state_measurements(
    state: str,
    path: Path,
    wheel_grid: int,
    emergency_grid: int,
) -> dict[str, Any]:
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    bpy.context.view_layer.update()
    body = body_object()
    products = base.product_objects()
    bounds = base.combined_bounds(products)
    width_mm = bounds["size_mm"][1] if bounds else None
    extrema_rows = []
    for obj in products:
        if obj.type not in {"MESH", "CURVE", "SURFACE", "FONT"}:
            continue
        vertices = base.evaluated_world_geometry(obj)[0]
        if vertices:
            extrema_rows.append(
                {
                    "object": obj.name,
                    "minimum_y_mm": base.mm(min(point.y for point in vertices), 6),
                    "maximum_y_mm": base.mm(max(point.y for point in vertices), 6),
                }
            )
    left_driver = min(extrema_rows, key=lambda row: row["minimum_y_mm"]) if extrema_rows else None
    right_driver = max(extrema_rows, key=lambda row: row["maximum_y_mm"]) if extrema_rows else None
    display = display_measurement()
    joystick = base.joystick_measurement()
    emergency = emergency_stop_measurement(emergency_grid)
    tables = table_measurement(state, joystick)
    footrest = footrest_measurement(state, body)
    doors = equipment_door_measurement(body)
    design_topology = topology_measurement(base.design_objects())
    functional_topology = topology_measurement(base.functional_objects())
    product_topology = topology_measurement(base.product_objects())
    topology = {
        **product_topology,
        "generated_design_collection": design_topology,
        "locked_functional_clone_collection": functional_topology,
    }
    wheel_wrap = base.wheel_wrap_measurement(body, wheel_grid)
    return {
        "blend_file": str(path),
        "blend_sha256": base.sha256(path),
        "product_collections": [base.DESIGN_COLLECTION, base.FUNCTIONAL_COLLECTION],
        "product_bounds": bounds,
        "overall_finished_width": {
            "pass": width_mm is not None and width_mm <= WIDTH_LIMIT_MM + 1.0e-6,
            "measured_mm": width_mm,
            "limit_mm": WIDTH_LIMIT_MM,
            "left_width_driver": left_driver,
            "right_width_driver": right_driver,
        },
        "display": display,
        "joystick": joystick,
        "emergency_stop": emergency,
        "tables": tables,
        "footrest": footrest,
        "equipment_door_seams": doors,
        "mesh_topology": topology,
        "wheel_wrap": wheel_wrap,
        "motion_roles": base.collect_motion_role_data(),
    }


def four_state_object_consistency(
    states: dict[str, dict[str, Any]],
    key: str,
    centre_path: tuple[str, ...],
    tolerance_mm: float,
) -> dict[str, Any]:
    centres = {}
    for state in STATES:
        value: Any = states[state][key]
        for path_item in centre_path:
            value = value.get(path_item) if isinstance(value, dict) else None
        centres[state] = value
    baseline = centres["ride"]
    deviations = {}
    passed = baseline is not None and all(states[state][key].get("pass") for state in STATES)
    for state, centre in centres.items():
        if centre is None or baseline is None:
            deviations[state] = None
            passed = False
            continue
        deviation = math.sqrt(sum((centre[index] - baseline[index]) ** 2 for index in range(3)))
        deviations[state] = base.round_float(deviation, 6)
        if deviation > tolerance_mm:
            passed = False
    return {
        "pass": passed,
        "centre_mm_by_state": centres,
        "deviation_from_ride_mm_by_state": deviations,
        "tolerance_mm": tolerance_mm,
    }


def strip_heavy_data(states: dict[str, dict[str, Any]]) -> None:
    for state in STATES:
        for role in states[state]["motion_roles"].values():
            role.pop("world_vertices_m", None)
            role.pop("matrix_world", None)
        for role in states[state]["footrest"]["role_data"].values():
            role.pop("world_vertices_m", None)


def main() -> None:
    args = parse_args()
    missing = [str(path) for path in STATE_PATHS.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("missing R13 state files: " + ", ".join(missing))
    if args.wheel_grid < 32 or args.emergency_grid < 32:
        raise ValueError("ray grids must be at least 32")

    states: dict[str, dict[str, Any]] = {}
    for state in STATES:
        print(f"R13_VALIDATE_OPEN {state} {STATE_PATHS[state]}", flush=True)
        states[state] = state_measurements(
            state,
            STATE_PATHS[state],
            args.wheel_grid,
            args.emergency_grid,
        )
        print(
            "R13_VALIDATE_STATE",
            state,
            "width",
            states[state]["overall_finished_width"].get("measured_mm"),
            "display",
            states[state]["display"].get("pass"),
            "estop",
            states[state]["emergency_stop"].get("pass"),
            "footrest",
            states[state]["footrest"].get("pass"),
            "wheel",
            states[state]["wheel_wrap"].get("pass"),
            flush=True,
        )

    motion = base.validate_motion_roles(states)
    joystick_consistency = four_state_object_consistency(
        states, "joystick", ("centre_mm",), POSE_TOL_MM
    )
    joystick_consistency["contract"] = "same externally exposed right-arm joystick in all states"
    emergency_consistency = four_state_object_consistency(
        states, "emergency_stop", ("stop_bounds", "centre_mm"), POSE_TOL_MM
    )
    emergency_consistency["contract"] = "same red, guarded, left-side accessible stop in all states"
    footrest_consistency = validate_footrest_four_state(states)

    state_gate_keys = (
        "overall_finished_width",
        "display",
        "joystick",
        "emergency_stop",
        "tables",
        "footrest",
        "equipment_door_seams",
        "mesh_topology",
        "wheel_wrap",
    )
    checks = [
        {"id": f"{state}.{key}", "pass": bool(states[state][key].get("pass"))}
        for state in STATES
        for key in state_gate_keys
    ]
    checks.extend(
        [
            {"id": "four_state.joystick_consistency", "pass": joystick_consistency["pass"]},
            {"id": "four_state.emergency_stop_consistency", "pass": emergency_consistency["pass"]},
            {"id": "four_state.footrest_geometry_translation_and_stow", "pass": footrest_consistency["pass"]},
            {"id": "four_state.a06_a07_geometry_and_motion", "pass": motion["pass"]},
        ]
    )

    strip_heavy_data(states)
    overall_pass = all(check["pass"] for check in checks)
    payload = {
        "schema": "workcore.e6.v11.r13.blender_validation.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "validator": str(SCRIPT_PATH),
        "validator_sha256": base.sha256(SCRIPT_PATH),
        "measurement_library": str(Path(base.__file__).resolve()),
        "measurement_library_sha256": base.sha256(Path(base.__file__).resolve()),
        "blender_version": bpy.app.version_string,
        "revision": REVISION,
        "coordinate_convention": {
            "front": "-X",
            "rear": "+X",
            "left": "-Y",
            "right": "+Y",
            "up": "+Z",
        },
        "scope": (
            "Saved Blender visual/layout models. This does not certify production BRep, rail/lock strength, "
            "debris tolerance, sealing, electrical safety or battery/equipment packaging."
        ),
        "overall_status": "PASS" if overall_pass else "FAIL",
        "summary": {
            "pass": overall_pass,
            "passed_checks": sum(1 for check in checks if check["pass"]),
            "failed_checks": sum(1 for check in checks if not check["pass"]),
            "failed_check_ids": [check["id"] for check in checks if not check["pass"]],
        },
        "asset_class_gates": {
            "generated_design_mesh_topology": {
                "pass": all(
                    states[state]["mesh_topology"]["generated_design_collection"]["pass"]
                    for state in STATES
                ),
                "by_state": {
                    state: states[state]["mesh_topology"]["generated_design_collection"]["pass"]
                    for state in STATES
                },
            },
            "locked_v8_proxy_topology": {
                "pass": all(
                    states[state]["mesh_topology"]["locked_functional_clone_collection"]["pass"]
                    for state in STATES
                ),
                "by_state": {
                    state: states[state]["mesh_topology"]["locked_functional_clone_collection"]["pass"]
                    for state in STATES
                },
                "note": "kept separate from generated design topology; threshold was not relaxed",
            },
        },
        "checks": checks,
        "four_state": {
            "joystick_consistency": joystick_consistency,
            "emergency_stop_consistency": emergency_consistency,
            "footrest_geometry_translation_and_stow": footrest_consistency,
            "a06_a07_geometry_and_motion": motion,
        },
        "states": states,
        "limitations": [
            "Wheel wrap is measured by exact lateral orthographic ray ordering against the evaluated mother body.",
            "Footrest/body collision uses triangle overlap plus outward-normal signed vertex clearance; STEP/BRep swept-volume validation remains mandatory.",
            "Cassette envelope validation checks the saved body void declaration, actual A08 bounds and body non-interference.",
            "Emergency-stop touchability is a geometric visibility/protrusion gate, not a human-factors certification.",
            "Visual render review remains a separate semantic gate.",
        ],
    }
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, args.output)
    print(f"R13_VALIDATION_{payload['overall_status']} {args.output}", flush=True)
    print("R13_FAILED_CHECKS", payload["summary"]["failed_check_ids"], flush=True)


if __name__ == "__main__":
    main()
