"""Inspect the immutable V8 clean GLBs through Blender 5.1.

The script writes only a JSON report below V11 and does not save a blend.
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from v11_common import (  # noqa: E402
    GEOMETRY_REPORT,
    PIPELINE_ID,
    STATES,
    atomic_write_json,
    config,
    reference_role,
    validate_source,
)


def object_bounds(obj: bpy.types.Object) -> dict[str, list[float]]:
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = [min(point[index] for point in points) for index in range(3)]
    maximum = [max(point[index] for point in points) for index in range(3)]
    return {
        "minimum_m": [round(value, 6) for value in minimum],
        "maximum_m": [round(value, 6) for value in maximum],
        "size_m": [round(maximum[i] - minimum[i], 6) for i in range(3)],
        "centre_m": [round((minimum[i] + maximum[i]) * 0.5, 6) for i in range(3)],
    }


def state_inventory(state: str) -> dict[str, object]:
    source, source_hash = validate_source(state)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(
        filepath=str(source),
        import_pack_images=True,
        merge_vertices=False,
        import_shading="NORMALS",
        import_scene_as_collection=True,
        import_merge_material_slots=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"{state}: import failed: {result}")

    normalizer = bpy.data.objects.new(f"V11__{state.upper()}__CAD_AXIS_ROOT", None)
    bpy.context.scene.collection.objects.link(normalizer)
    normalizer.rotation_euler = (-math.pi / 2.0, 0.0, 0.0)
    for obj in bpy.data.objects:
        if obj != normalizer and obj.parent is None:
            obj.parent = normalizer
    bpy.context.view_layer.update()

    meshes = sorted((obj for obj in bpy.data.objects if obj.type == "MESH"), key=lambda x: x.name)
    expected = config()["states"][state]
    if len(meshes) != int(expected["expected_mesh_count"]):
        raise RuntimeError(
            f"{state}: mesh count {len(meshes)} != {expected['expected_mesh_count']}"
        )

    records = []
    role_counts: Counter[str] = Counter()
    for obj in meshes:
        role = reference_role(obj.name)
        role_counts[role] += 1
        records.append(
            {
                "occurrence_id": obj.name,
                "role": role,
                "bounds": object_bounds(obj),
                "vertex_count": len(obj.data.vertices),
                "polygon_count": len(obj.data.polygons),
                "materials": [
                    slot.material.name for slot in obj.material_slots if slot.material is not None
                ],
            }
        )

    all_points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    minimum = [min(point[i] for point in all_points) for i in range(3)]
    maximum = [max(point[i] for point in all_points) for i in range(3)]
    return {
        "source": str(source),
        "source_sha256": source_hash,
        "mesh_count": len(meshes),
        "role_counts": dict(sorted(role_counts.items())),
        "bounds_m": {
            "minimum": [round(value, 6) for value in minimum],
            "maximum": [round(value, 6) for value in maximum],
        },
        "objects": records,
    }


def main() -> None:
    report: dict[str, object] = {
        "schema_version": 1,
        "pipeline_id": PIPELINE_ID,
        "status": "PASS",
        "blender_version": bpy.app.version_string,
        "states": {},
    }
    for state in STATES:
        report["states"][state] = state_inventory(state)
        print("V11_V8_GEOMETRY_OK", state, report["states"][state]["mesh_count"], flush=True)
    atomic_write_json(GEOMETRY_REPORT, report)
    print("V11_V8_GEOMETRY_REPORT", GEOMETRY_REPORT, flush=True)


if __name__ == "__main__":
    main()

