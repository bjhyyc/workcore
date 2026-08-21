"""Deterministic saved-file geometry validation for WorkCore E6 V11 R12.

Run with Blender, not the system Python::

    D:\\blender\\blender.exe --background --factory-startup \
      --python scripts/validate_v11_r12.py

The validator deliberately reopens every saved R12 state and measures evaluated
geometry.  Generator metadata is recorded only as provenance; it is never used
as proof that a geometry requirement passed.

Units inside Blender are metres.  Reported human-facing measurements are mm.
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
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


SCRIPT_PATH = Path(__file__).resolve()
V11_ROOT = SCRIPT_PATH.parent.parent
REVISION = "r12"
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

DESIGN_COLLECTION = "40_V11_NEW_DESIGN"
FUNCTIONAL_COLLECTION = "10_LOCAL_V8_FUNCTIONAL_RENDER_OBJECTS"

ROLE_SOURCES = {
    "a06_shell": "A06_backrest_moving_shell",
    "a06_contact": "A06_backrest_contact_island",
    "a07_mast": "A07_sensor_mast_moving",
    "a07_crown": "A07_sensor_head",
    "a07_window": "A07_sensor_window",
}

EPS_M = 1.0e-9
DIM_TOL_MM = 0.05
POSE_TOL_MM = 0.05
ANGLE_TOL_DEG = 0.05
WIDTH_LIMIT_MM = 752.0
DISPLAY_CONTACT_TOL_MM = 1.0
DOOR_SEAM_MAX_OFFSET_MM = 1.2
TABLE_INBOARD_TARGET_MM = 10.0
TABLE_INBOARD_TOL_MM = 0.1
JOYSTICK_TABLE_CLEARANCE_MIN_MM = 50.0
WHEEL_VISIBLE_MAX_RATIO = 0.50
WHEEL_VISIBLE_MIN_RATIO = 0.20


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--wheel-grid",
        type=int,
        default=96,
        help="square ray grid per tyre; 96 gives 9216 lateral samples",
    )
    return parser.parse_args(raw)


def round_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def mm(value_m: float, digits: int = 3) -> float:
    return round_float(value_m * 1000.0, digits)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def collection_objects(name: str) -> list[bpy.types.Object]:
    collection = bpy.data.collections.get(name)
    if collection is None:
        return []
    return list(collection.objects)


def design_objects() -> list[bpy.types.Object]:
    return collection_objects(DESIGN_COLLECTION)


def functional_objects() -> list[bpy.types.Object]:
    return collection_objects(FUNCTIONAL_COLLECTION)


def product_objects() -> list[bpy.types.Object]:
    # Preserve collection order but avoid a duplicated link counting twice.
    result: list[bpy.types.Object] = []
    seen: set[int] = set()
    for obj in design_objects() + functional_objects():
        pointer = obj.as_pointer()
        if pointer not in seen:
            seen.add(pointer)
            result.append(obj)
    return result


def evaluated_world_geometry(
    obj: bpy.types.Object,
) -> tuple[list[Vector], list[tuple[int, ...]]]:
    """Return evaluated vertices/polygons transformed into world coordinates."""

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    if mesh is None:
        return [], []
    try:
        matrix = evaluated.matrix_world.copy()
        vertices = [matrix @ vertex.co for vertex in mesh.vertices]
        polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
        return vertices, polygons
    finally:
        evaluated.to_mesh_clear()


def raw_world_vertices(obj: bpy.types.Object) -> list[Vector]:
    if obj.type != "MESH":
        return evaluated_world_geometry(obj)[0]
    matrix = obj.matrix_world.copy()
    return [matrix @ vertex.co for vertex in obj.data.vertices]


def bounds_from_vertices(vertices: Iterable[Vector]) -> dict[str, list[float]] | None:
    points = list(vertices)
    if not points:
        return None
    minimum = [min(point[index] for point in points) for index in range(3)]
    maximum = [max(point[index] for point in points) for index in range(3)]
    return {
        "min_m": [round_float(value, 9) for value in minimum],
        "max_m": [round_float(value, 9) for value in maximum],
        "size_mm": [mm(maximum[i] - minimum[i]) for i in range(3)],
        "centre_mm": [mm((maximum[i] + minimum[i]) * 0.5) for i in range(3)],
    }


def combined_bounds(objects: Iterable[bpy.types.Object]) -> dict[str, list[float]] | None:
    vertices: list[Vector] = []
    for obj in objects:
        if obj.type in {"MESH", "CURVE", "SURFACE", "FONT"}:
            vertices.extend(evaluated_world_geometry(obj)[0])
    return bounds_from_vertices(vertices)


def world_bvh(obj: bpy.types.Object) -> BVHTree:
    vertices, polygons = evaluated_world_geometry(obj)
    if not vertices or not polygons:
        raise RuntimeError(f"cannot build BVH for empty object: {obj.name}")
    return BVHTree.FromPolygons(vertices, polygons, all_triangles=False)


def object_by_exact_source(source: str) -> bpy.types.Object | None:
    matches = [obj for obj in design_objects() if obj.get("source_occurrence_ids") == source]
    return matches[0] if len(matches) == 1 else None


def objects_by_name_token(token: str, objects: Iterable[bpy.types.Object] | None = None) -> list[bpy.types.Object]:
    haystack = list(objects) if objects is not None else product_objects()
    return [obj for obj in haystack if token in obj.name]


def oriented_dimensions_mm(obj: bpy.types.Object) -> list[float]:
    vertices, _ = evaluated_world_geometry(obj)
    if not vertices:
        return [0.0, 0.0, 0.0]
    origin = obj.matrix_world.translation
    rotation_scale = obj.matrix_world.to_3x3()
    axes = [rotation_scale.col[index].normalized() for index in range(3)]
    dimensions = []
    for axis in axes:
        projections = [(point - origin).dot(axis) for point in vertices]
        dimensions.append(mm(max(projections) - min(projections)))
    return dimensions


def local_mesh_signature(obj: bpy.types.Object) -> str:
    """Hash topology and object-local coordinates, excluding name/material."""

    if obj.type != "MESH":
        return ""
    payload = {
        "vertices": [[round_float(value, 9) for value in vertex.co] for vertex in obj.data.vertices],
        "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mesh_degeneracy(objects: Iterable[bpy.types.Object]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    totals = defaultdict(int)
    for obj in objects:
        if obj.type != "MESH":
            continue
        matrix = obj.matrix_world.copy()
        world = [matrix @ vertex.co for vertex in obj.data.vertices]
        zero_edges = 0
        for edge in obj.data.edges:
            if (world[edge.vertices[0]] - world[edge.vertices[1]]).length <= EPS_M:
                zero_edges += 1
        zero_faces = 0
        for polygon in obj.data.polygons:
            indices = list(polygon.vertices)
            if len(indices) < 3:
                zero_faces += 1
                continue
            anchor = world[indices[0]]
            area_vector = Vector((0.0, 0.0, 0.0))
            for left, right in zip(indices[1:-1], indices[2:]):
                area_vector += (world[left] - anchor).cross(world[right] - anchor) * 0.5
            if area_vector.length <= 1.0e-12:
                zero_faces += 1
        totals["mesh_objects"] += 1
        totals["vertices"] += len(obj.data.vertices)
        totals["edges"] += len(obj.data.edges)
        totals["faces"] += len(obj.data.polygons)
        totals["zero_length_edges"] += zero_edges
        totals["zero_area_faces"] += zero_faces
        if zero_edges or zero_faces:
            rows.append(
                {
                    "object": obj.name,
                    "zero_length_edges": zero_edges,
                    "zero_area_faces": zero_faces,
                }
            )
    return {"totals": dict(totals), "objects_with_degeneracy": rows}


def curve_control_points_world(obj: bpy.types.Object) -> list[Vector]:
    if obj.type != "CURVE":
        return []
    result: list[Vector] = []
    for spline in obj.data.splines:
        if spline.type == "BEZIER":
            result.extend(obj.matrix_world @ point.co for point in spline.bezier_points)
        else:
            result.extend(obj.matrix_world @ Vector(point.co[:3]) for point in spline.points)
    return result


def display_measurement() -> dict[str, Any]:
    displays = objects_by_name_token("A05_SINGLE_UNIFORM_DISPLAY", design_objects())
    if len(displays) != 1:
        return {"pass": False, "object_count": len(displays), "objects": [obj.name for obj in displays]}

    display = displays[0]
    dimensions = oriented_dimensions_mm(display)
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
    front_high_delta_mm = mm(front.z - rear.z)

    arm = object_by_exact_source("A05_armrest_table_bay_shell_left")
    contact: dict[str, Any]
    if arm is None:
        contact = {"pass": False, "reason": "left arm shell missing or duplicated"}
    else:
        bvh = world_bvh(arm)
        gaps: list[float] = []
        misses = 0
        # Avoid the rounded display perimeter.  The 5 x 3 points cover the
        # functional underside while staying within the integral saddle.
        for fx in (0.08, 0.25, 0.50, 0.75, 0.92):
            for fy in (0.18, 0.50, 0.82):
                local = Vector(
                    (
                        x_min + (x_max - x_min) * fx,
                        y_min + (y_max - y_min) * fy,
                        z_min,
                    )
                )
                underside = display.matrix_world @ local
                ray_origin = underside + Vector((0.0, 0.0, 0.020))
                hit, _normal, _index, _distance = bvh.ray_cast(
                    ray_origin, Vector((0.0, 0.0, -1.0)), 0.050
                )
                if hit is None:
                    misses += 1
                else:
                    gaps.append(mm(underside.z - hit.z, 4))
        maximum_absolute_gap = max((abs(value) for value in gaps), default=math.inf)
        contact = {
            "pass": misses == 0 and maximum_absolute_gap <= DISPLAY_CONTACT_TOL_MM,
            "sample_count": 15,
            "ray_misses": misses,
            "vertical_gap_mm": {
                "min": min(gaps) if gaps else None,
                "max": max(gaps) if gaps else None,
                "mean": round_float(sum(gaps) / len(gaps), 4) if gaps else None,
                "maximum_absolute": round_float(maximum_absolute_gap, 4)
                if math.isfinite(maximum_absolute_gap)
                else None,
            },
            "tolerance_mm": DISPLAY_CONTACT_TOL_MM,
            "algorithm": "15 inset underside samples; vertical ray to evaluated integral left-arm saddle",
        }

    dimension_errors = [
        abs(dimensions[0] - 124.0),
        abs(dimensions[1] - 49.0),
        abs(dimensions[2] - 2.5),
    ]
    geometry_pass = (
        max(dimension_errors) <= DIM_TOL_MM
        and abs(pitch_deg - 8.0) <= ANGLE_TOL_DEG
        and front_high_delta_mm > 0.0
    )
    return {
        "pass": geometry_pass and bool(contact.get("pass")),
        "object": display.name,
        "oriented_dimensions_mm": dimensions,
        "required_dimensions_mm": [124.0, 49.0, 2.5],
        "dimension_tolerance_mm": DIM_TOL_MM,
        "world_y_pitch_deg": round_float(pitch_deg, 5),
        "required_world_y_pitch_deg": 8.0,
        "front_minus_rear_height_mm": front_high_delta_mm,
        "front_high_rear_low": front_high_delta_mm > 0.0,
        "rotation_origin": display.get("rotation_origin", "not declared"),
        "support_contact": contact,
    }


def joystick_measurement() -> dict[str, Any]:
    joysticks = objects_by_name_token("A05_right_joystick", functional_objects())
    if len(joysticks) != 1:
        return {"pass": False, "object_count": len(joysticks), "objects": [obj.name for obj in joysticks]}
    joystick = joysticks[0]
    bounds = bounds_from_vertices(raw_world_vertices(joystick))
    arm = object_by_exact_source("A05_armrest_table_bay_shell_right")
    arm_bounds = bounds_from_vertices(raw_world_vertices(arm)) if arm else None
    exposed_height = None
    if bounds and arm_bounds:
        exposed_height = bounds["max_m"][2] - arm_bounds["max_m"][2]
    return {
        "pass": bounds is not None and exposed_height is not None and exposed_height > 0.0,
        "object": joystick.name,
        "bounds": bounds,
        "centre_mm": bounds["centre_mm"] if bounds else None,
        "dimensions_mm": bounds["size_mm"] if bounds else None,
        "height_above_right_arm_mm": mm(exposed_height) if exposed_height is not None else None,
        "externally_exposed_on_arm_top": exposed_height is not None and exposed_height > 0.0,
    }


def table_measurement(state: str, joystick: dict[str, Any]) -> dict[str, Any]:
    tables = [
        obj
        for obj in design_objects()
        if obj.type == "MESH" and "A09_" in obj.name and "WALNUT_SURFACE" in obj.name
    ]
    rows = []
    for obj in tables:
        bounds = bounds_from_vertices(raw_world_vertices(obj))
        rows.append({"object": obj.name, "bounds": bounds})

    joystick_bounds = None
    if joystick.get("pass"):
        matches = objects_by_name_token("A05_right_joystick", functional_objects())
        joystick_bounds = bounds_from_vertices(raw_world_vertices(matches[0])) if matches else None

    if state in {"follow", "ride"}:
        return {
            "pass": len(tables) == 0,
            "expected": "no deployed table",
            "table_count": len(tables),
            "tables": rows,
        }

    if state == "cafe":
        if len(tables) != 1 or rows[0]["bounds"] is None:
            return {
                "pass": False,
                "expected": "one right-origin table",
                "table_count": len(tables),
                "tables": rows,
            }
        bounds = rows[0]["bounds"]
        y_max_mm = bounds["max_m"][1] * 1000.0
        inboard_margin = 265.0 - y_max_mm
        clearance = None
        if joystick_bounds:
            clearance = joystick_bounds["min_m"][1] * 1000.0 - y_max_mm
        dimensions = bounds["size_mm"]
        passes = (
            "CAFE_RIGHT" in tables[0].name
            and abs(dimensions[0] - 250.0) <= DIM_TOL_MM
            and abs(dimensions[1] - 400.0) <= DIM_TOL_MM
            and inboard_margin + TABLE_INBOARD_TOL_MM >= TABLE_INBOARD_TARGET_MM
            and clearance is not None
            and clearance >= JOYSTICK_TABLE_CLEARANCE_MIN_MM
        )
        return {
            "pass": passes,
            "expected": "one 250 x 400 mm right-origin table; y<=255 mm; joystick remains reachable",
            "table_count": 1,
            "tables": rows,
            "right_arm_inner_face_y_mm": 265.0,
            "table_inboard_margin_mm": round_float(inboard_margin, 3),
            "joystick_lateral_clearance_mm": round_float(clearance, 3) if clearance is not None else None,
            "minimum_joystick_clearance_mm": JOYSTICK_TABLE_CLEARANCE_MIN_MM,
        }

    # Focus: two 400 x 247 mm leaves, 16 mm centre reveal and both outside
    # edges 10 mm inboard of their respective inner arm faces.
    if len(tables) != 2:
        return {
            "pass": False,
            "expected": "two focus leaves",
            "table_count": len(tables),
            "tables": rows,
        }
    left = next((row for row in rows if "FOCUS_LEFT" in row["object"]), None)
    right = next((row for row in rows if "FOCUS_RIGHT" in row["object"]), None)
    if left is None or right is None or left["bounds"] is None or right["bounds"] is None:
        return {"pass": False, "expected": "named left/right focus leaves", "tables": rows}
    left_bounds = left["bounds"]
    right_bounds = right["bounds"]
    left_margin = left_bounds["min_m"][1] * 1000.0 - (-265.0)
    right_margin = 265.0 - right_bounds["max_m"][1] * 1000.0
    centre_gap = (right_bounds["min_m"][1] - left_bounds["max_m"][1]) * 1000.0
    clearance = None
    if joystick_bounds:
        clearance = (
            joystick_bounds["min_m"][1] - right_bounds["max_m"][1]
        ) * 1000.0
    dimensions_pass = all(
        abs(row["bounds"]["size_mm"][0] - 400.0) <= DIM_TOL_MM
        and abs(row["bounds"]["size_mm"][1] - 247.0) <= DIM_TOL_MM
        for row in (left, right)
    )
    passes = (
        dimensions_pass
        and left_margin + TABLE_INBOARD_TOL_MM >= TABLE_INBOARD_TARGET_MM
        and right_margin + TABLE_INBOARD_TOL_MM >= TABLE_INBOARD_TARGET_MM
        and abs(centre_gap - 16.0) <= TABLE_INBOARD_TOL_MM
        and clearance is not None
        and clearance >= JOYSTICK_TABLE_CLEARANCE_MIN_MM
    )
    return {
        "pass": passes,
        "expected": "two 400 x 247 mm leaves; 10 mm inboard; 16 mm centre reveal",
        "table_count": 2,
        "tables": rows,
        "left_inboard_margin_mm": round_float(left_margin, 3),
        "right_inboard_margin_mm": round_float(right_margin, 3),
        "centre_gap_mm": round_float(centre_gap, 3),
        "joystick_lateral_clearance_mm": round_float(clearance, 3) if clearance is not None else None,
        "minimum_joystick_clearance_mm": JOYSTICK_TABLE_CLEARANCE_MIN_MM,
    }


def footrest_measurement(state: str) -> dict[str, Any]:
    deployed_tokens = (
        "A08_SINGLE_PIECE_TELESCOPIC_FOOTREST",
        "A08_NATURAL_RUBBER_TREAD_INLAY",
        "A08_LIMITED_316_LEADING_EDGE",
    )
    parts = [obj for obj in design_objects() if any(token in obj.name for token in deployed_tokens)]
    expected_count = 3 if state == "ride" else 0
    return {
        "pass": len(parts) == expected_count,
        "expected_deployed": state == "ride",
        "expected_part_count": expected_count,
        "actual_part_count": len(parts),
        "objects": [obj.name for obj in parts],
    }


def equipment_door_measurement(body: bpy.types.Object | None) -> dict[str, Any]:
    seams = [
        obj
        for obj in design_objects()
        if obj.get("source_occurrence_ids") in {"A04_equipment_door_left", "A04_equipment_door_right"}
    ]
    if body is None or len(seams) != 2:
        return {
            "pass": False,
            "seam_count": len(seams),
            "reason": "monocoque missing or equipment-door seams not exactly two",
        }
    bvh = world_bvh(body)
    rows = []
    all_distances: list[float] = []
    for seam in seams:
        distances = []
        for point in curve_control_points_world(seam):
            _nearest, _normal, _index, distance = bvh.find_nearest(point)
            if distance is not None:
                distances.append(mm(distance, 4))
        all_distances.extend(distances)
        rows.append(
            {
                "object": seam.name,
                "control_points": len(distances),
                "offset_mm": {
                    "min": min(distances) if distances else None,
                    "max": max(distances) if distances else None,
                    "mean": round_float(sum(distances) / len(distances), 4) if distances else None,
                },
                "declared_door_skin_mm": seam.get("door_skin_mm"),
                "declared_opening_mm": seam.get("opening_mm"),
                "declared_nominal_seam_mm": seam.get("nominal_seam_mm"),
                "declared_service_travel_mm": seam.get("service_travel_mm"),
            }
        )
    maximum = max(all_distances, default=math.inf)
    return {
        "pass": bool(all_distances) and maximum <= DOOR_SEAM_MAX_OFFSET_MM,
        "seam_count": len(seams),
        "maximum_curve_to_mother_surface_offset_mm": round_float(maximum, 4)
        if math.isfinite(maximum)
        else None,
        "tolerance_mm": DOOR_SEAM_MAX_OFFSET_MM,
        "algorithm": "nearest evaluated monocoque surface from each saved curve control point",
        "seams": rows,
        "production_caveat": "door rail, 300 mm travel and battery/equipment packaging still require STEP BRep validation",
    }


def ray_distance(bvh: BVHTree, origin: Vector, direction: Vector, maximum: float = 2.0) -> float | None:
    _location, _normal, _index, distance = bvh.ray_cast(origin, direction, maximum)
    return float(distance) if distance is not None else None


def wheel_visibility_for_tyre(
    tyre: bpy.types.Object,
    body_bvh: BVHTree,
    grid: int,
) -> dict[str, Any]:
    vertices = raw_world_vertices(tyre)
    bounds = bounds_from_vertices(vertices)
    if bounds is None:
        return {"pass": False, "object": tyre.name, "reason": "empty tyre mesh"}
    tyre_bvh = world_bvh(tyre)
    x_min, _y_min, z_min = bounds["min_m"]
    x_max, _y_max, z_max = bounds["max_m"]
    centre_y = sum(point.y for point in vertices) / len(vertices)
    side = "left" if centre_y < 0.0 else "right"
    outside_y = -1.0 if side == "left" else 1.0
    direction = Vector((0.0, 1.0, 0.0)) if side == "left" else Vector((0.0, -1.0, 0.0))

    projected_tyre_samples = 0
    visible_samples = 0
    hidden_samples = 0
    for ix in range(grid):
        x = x_min + (x_max - x_min) * ((ix + 0.5) / grid)
        for iz in range(grid):
            z = z_min + (z_max - z_min) * ((iz + 0.5) / grid)
            origin = Vector((x, outside_y, z))
            tyre_distance = ray_distance(tyre_bvh, origin, direction)
            if tyre_distance is None:
                continue
            projected_tyre_samples += 1
            body_distance = ray_distance(body_bvh, origin, direction)
            if body_distance is None or tyre_distance + 1.0e-6 < body_distance:
                visible_samples += 1
            else:
                hidden_samples += 1

    visible_ratio = visible_samples / projected_tyre_samples if projected_tyre_samples else math.inf
    hidden_ratio = hidden_samples / projected_tyre_samples if projected_tyre_samples else 0.0

    nearest_distances = []
    for point in vertices:
        _nearest, _normal, _index, distance = body_bvh.find_nearest(point)
        if distance is not None:
            nearest_distances.append(distance)
    surface_clearance = min(nearest_distances, default=math.inf)

    return {
        "pass": (
            projected_tyre_samples > 0
            and WHEEL_VISIBLE_MIN_RATIO <= visible_ratio <= WHEEL_VISIBLE_MAX_RATIO
        ),
        "object": tyre.name,
        "side": side,
        "grid": [grid, grid],
        "projected_tyre_samples": projected_tyre_samples,
        "visible_samples": visible_samples,
        "hidden_samples": hidden_samples,
        "visible_ratio": round_float(visible_ratio, 5)
        if math.isfinite(visible_ratio)
        else None,
        "hidden_ratio": round_float(hidden_ratio, 5),
        "accepted_visible_ratio": [WHEEL_VISIBLE_MIN_RATIO, WHEEL_VISIBLE_MAX_RATIO],
        "sampled_minimum_surface_distance_mm": mm(surface_clearance, 4)
        if math.isfinite(surface_clearance)
        else None,
    }


def wheel_wrap_measurement(body: bpy.types.Object | None, grid: int) -> dict[str, Any]:
    tyres = objects_by_name_token("source_tyre_", functional_objects())
    applied_cover_tokens = ("FENDER", "SKIRT", "RIBBON", "WHEEL_LOBE", "WHEEL_PANEL")
    applied_covers = [
        obj.name
        for obj in design_objects()
        if any(token in obj.name.upper() for token in applied_cover_tokens)
    ]
    if body is None or len(tyres) != 4:
        return {
            "pass": False,
            "tyre_count": len(tyres),
            "applied_cover_objects": applied_covers,
            "reason": "one monocoque and four local functional tyres required",
        }
    body_bvh = world_bvh(body)
    tyres_result = [wheel_visibility_for_tyre(tyre, body_bvh, grid) for tyre in tyres]
    same_mother_surface_only = not applied_covers and body.type == "MESH"
    return {
        "pass": same_mother_surface_only and all(row.get("pass") for row in tyres_result),
        "monocoque_object": body.name,
        "single_continuous_mother_surface": same_mother_surface_only,
        "applied_cover_objects": applied_covers,
        "tyre_count": len(tyres),
        "algorithm": (
            "exact lateral orthographic ray grid over each saved tyre projection; "
            "a tyre sample is hidden when the evaluated monocoque is the first ray hit"
        ),
        "interpretation": "20-50% projected tyre visible: upper half wrapped, lower running portion still legible",
        "tyres": tyres_result,
    }


def collect_motion_role_data() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role, source in ROLE_SOURCES.items():
        obj = object_by_exact_source(source)
        if obj is None:
            result[role] = {"present": False}
            continue
        vertices = raw_world_vertices(obj)
        result[role] = {
            "present": True,
            "object": obj.name,
            "local_mesh_sha256": local_mesh_signature(obj),
            "world_vertices_m": [[float(value) for value in point] for point in vertices],
            "matrix_world": [[float(value) for value in row] for row in obj.matrix_world],
        }
    return result


def expected_world_point(state: str, role: str, point: list[float]) -> Vector:
    source = Vector(point)
    if state == "focus" and role.startswith("a07_"):
        return source + Vector((0.0, 0.0, 0.420))
    if state != "follow":
        return source
    pivot = Vector((0.158, 0.0, 0.535))
    rotation = Matrix.Rotation(math.radians(-90.0), 4, "Y")
    return pivot + rotation @ (source - pivot)


def validate_motion_roles(state_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = state_data["ride"]["motion_roles"]
    rows = []
    all_pass = True
    for role in ROLE_SOURCES:
        baseline_role = baseline.get(role, {})
        hashes = {}
        transform_errors = {}
        role_pass = bool(baseline_role.get("present"))
        for state in STATES:
            current = state_data[state]["motion_roles"].get(role, {})
            hashes[state] = current.get("local_mesh_sha256")
            if not current.get("present") or not baseline_role.get("present"):
                role_pass = False
                transform_errors[state] = None
                continue
            expected_hash = baseline_role["local_mesh_sha256"]
            if current["local_mesh_sha256"] != expected_hash:
                role_pass = False
            baseline_vertices = baseline_role["world_vertices_m"]
            current_vertices = current["world_vertices_m"]
            if len(baseline_vertices) != len(current_vertices):
                role_pass = False
                transform_errors[state] = None
                continue
            maximum = 0.0
            for base_point, actual_point in zip(baseline_vertices, current_vertices):
                expected = expected_world_point(state, role, base_point)
                error = (Vector(actual_point) - expected).length
                maximum = max(maximum, error)
            transform_errors[state] = mm(maximum, 6)
            if mm(maximum, 6) > POSE_TOL_MM:
                role_pass = False
        all_pass = all_pass and role_pass
        rows.append(
            {
                "role": role,
                "source_occurrence_ids": ROLE_SOURCES[role],
                "pass": role_pass,
                "same_local_geometry_all_states": len(set(value for value in hashes.values() if value)) == 1
                and all(hashes.values()),
                "mesh_sha256_by_state": hashes,
                "maximum_world_transform_error_mm_by_state": transform_errors,
            }
        )
    return {
        "pass": all_pass,
        "pose_tolerance_mm": POSE_TOL_MM,
        "contracts": {
            "ride_cafe": "identical low pose",
            "focus": "A06 unchanged; A07 mast/crown/window translated +420 mm world Z",
            "follow": "same A06 and A07 parts rotated -90 deg world Y about common pivot (158, 0, 535) mm",
        },
        "roles": rows,
    }


def strip_heavy_motion_data(payload: dict[str, Any]) -> None:
    for state in STATES:
        for role in payload[state]["motion_roles"].values():
            role.pop("world_vertices_m", None)
            role.pop("matrix_world", None)


def state_measurements(state: str, path: Path, grid: int) -> dict[str, Any]:
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    bpy.context.view_layer.update()

    body_matches = [
        obj
        for obj in design_objects()
        if obj.get("source_occurrence_ids") == "A01,A02,A03,A04,A10"
        and "MONOCOQUE" in obj.name
    ]
    body = body_matches[0] if len(body_matches) == 1 else None
    bounds = combined_bounds(product_objects())
    width_mm = bounds["size_mm"][1] if bounds else None
    display = display_measurement()
    joystick = joystick_measurement()
    tables = table_measurement(state, joystick)
    footrest = footrest_measurement(state)
    equipment_door = equipment_door_measurement(body)
    design_degeneracy = mesh_degeneracy(design_objects())
    functional_degeneracy = mesh_degeneracy(functional_objects())
    degeneracy = mesh_degeneracy(product_objects())
    wheel_wrap = wheel_wrap_measurement(body, grid)

    return {
        "blend_file": str(path),
        "blend_sha256": sha256(path),
        "product_collections": [DESIGN_COLLECTION, FUNCTIONAL_COLLECTION],
        "product_bounds": bounds,
        "overall_finished_width": {
            "pass": width_mm is not None and width_mm <= WIDTH_LIMIT_MM + 1.0e-6,
            "measured_mm": width_mm,
            "limit_mm": WIDTH_LIMIT_MM,
        },
        "display": display,
        "joystick": joystick,
        "tables": tables,
        "footrest": footrest,
        "equipment_door_seams": equipment_door,
        "mesh_degeneracy": {
            **degeneracy,
            "pass": degeneracy["totals"].get("zero_length_edges", 0) == 0
            and degeneracy["totals"].get("zero_area_faces", 0) == 0,
            "generated_design_collection": {
                **design_degeneracy,
                "pass": design_degeneracy["totals"].get("zero_length_edges", 0) == 0
                and design_degeneracy["totals"].get("zero_area_faces", 0) == 0,
            },
            "locked_functional_clone_collection": {
                **functional_degeneracy,
                "pass": functional_degeneracy["totals"].get("zero_length_edges", 0) == 0
                and functional_degeneracy["totals"].get("zero_area_faces", 0) == 0,
            },
            "edge_threshold_m": EPS_M,
            "face_area_threshold_m2": 1.0e-12,
        },
        "wheel_wrap": wheel_wrap,
        "motion_roles": collect_motion_role_data(),
    }


def main() -> None:
    args = parse_args()
    missing = [str(path) for path in STATE_PATHS.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("missing R12 state files: " + ", ".join(missing))
    if args.wheel_grid < 32:
        raise ValueError("--wheel-grid must be at least 32")

    states: dict[str, dict[str, Any]] = {}
    for state in STATES:
        print(f"R12_VALIDATE_OPEN {state} {STATE_PATHS[state]}", flush=True)
        states[state] = state_measurements(state, STATE_PATHS[state], args.wheel_grid)
        print(
            "R12_VALIDATE_STATE",
            state,
            "width",
            states[state]["overall_finished_width"],
            "display",
            states[state]["display"].get("pass"),
            "wheel",
            states[state]["wheel_wrap"].get("pass"),
            flush=True,
        )

    motion = validate_motion_roles(states)

    joystick_centres = {
        state: states[state]["joystick"].get("centre_mm") for state in STATES
    }
    baseline_centre = joystick_centres["ride"]
    joystick_deviations = {}
    joystick_consistency_pass = baseline_centre is not None
    for state, centre in joystick_centres.items():
        if centre is None or baseline_centre is None:
            joystick_deviations[state] = None
            joystick_consistency_pass = False
            continue
        deviation = math.sqrt(sum((centre[i] - baseline_centre[i]) ** 2 for i in range(3)))
        joystick_deviations[state] = round_float(deviation, 6)
        if deviation > POSE_TOL_MM:
            joystick_consistency_pass = False
    joystick_consistency_pass = joystick_consistency_pass and all(
        states[state]["joystick"].get("pass") for state in STATES
    )
    joystick_consistency = {
        "pass": joystick_consistency_pass,
        "centre_mm_by_state": joystick_centres,
        "deviation_from_ride_mm_by_state": joystick_deviations,
        "tolerance_mm": POSE_TOL_MM,
        "contract": "same externally exposed joystick on forward right arm top in all four states",
    }

    footrest_state_logic = {
        "pass": all(states[state]["footrest"].get("pass") for state in STATES),
        "contract": "Ride deployed by default; Follow/Cafe/Focus stowed",
        "actual_deployed_by_state": {
            state: states[state]["footrest"]["actual_part_count"] > 0 for state in STATES
        },
    }

    state_gate_keys = (
        "overall_finished_width",
        "display",
        "joystick",
        "tables",
        "footrest",
        "equipment_door_seams",
        "mesh_degeneracy",
        "wheel_wrap",
    )
    checks: list[dict[str, Any]] = []
    for state in STATES:
        for key in state_gate_keys:
            checks.append(
                {
                    "id": f"{state}.{key}",
                    "pass": bool(states[state][key].get("pass")),
                }
            )
    checks.extend(
        [
            {"id": "four_state.joystick_consistency", "pass": joystick_consistency["pass"]},
            {"id": "four_state.footrest_state_logic", "pass": footrest_state_logic["pass"]},
            {"id": "four_state.a06_a07_geometry_and_motion", "pass": motion["pass"]},
        ]
    )

    strip_heavy_motion_data(states)
    overall_pass = all(check["pass"] for check in checks)
    payload = {
        "schema": "workcore.e6.v11.r12.blender_validation.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "validator": str(SCRIPT_PATH),
        "validator_sha256": sha256(SCRIPT_PATH),
        "blender_version": bpy.app.version_string,
        "revision": REVISION,
        "coordinate_convention": {
            "front": "-X",
            "rear": "+X",
            "left": "-Y",
            "right": "+Y",
            "up": "+Z",
            "units": "metres internally; millimetres in reported dimensions",
        },
        "scope": (
            "Saved Blender visual/layout decision models only. Geometry pass does not certify "
            "production BRep, mechanism strength, tolerances, battery/equipment packaging, rails, or safety."
        ),
        "overall_status": "PASS" if overall_pass else "FAIL",
        "summary": {
            "pass": overall_pass,
            "passed_checks": sum(1 for check in checks if check["pass"]),
            "failed_checks": sum(1 for check in checks if not check["pass"]),
            "failed_check_ids": [check["id"] for check in checks if not check["pass"]],
        },
        "checks": checks,
        "four_state": {
            "joystick_consistency": joystick_consistency,
            "footrest_state_logic": footrest_state_logic,
            "a06_a07_geometry_and_motion": motion,
        },
        "states": states,
        "limitations": [
            "Wheel visibility is an orthographic geometric projection, not an image-segmentation estimate.",
            "Minimum tyre/body surface distance samples saved tyre vertices; continuous clearance still needs STEP/BRep analysis.",
            "Door curve proximity proves a flush visual seam only; it does not prove rail travel or internal package clearance.",
            "Visual snapshot review remains a separate semantic gate and is not replaced by this report.",
        ],
    }
    atomic_write_json(args.output.resolve(), payload)
    print(f"R12_VALIDATION_{payload['overall_status']} {args.output.resolve()}", flush=True)
    print("R12_FAILED_CHECKS", payload["summary"]["failed_check_ids"], flush=True)


if __name__ == "__main__":
    main()
