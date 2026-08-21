"""Build one immutable V8 state reference library for V11."""

from __future__ import annotations

import argparse
import math
import os
import sys
import traceback
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from v11_common import (  # noqa: E402
    PIPELINE_ID,
    atomic_write_json,
    config,
    reference_library_path,
    reference_library_report_path,
    reference_role,
    sha256,
    validate_source,
    validate_state,
)


def args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    return parser.parse_args(argv)


def new_child(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
    result = bpy.data.collections.new(name)
    parent.children.link(result)
    return result


def link_only(obj: bpy.types.Object, owner: bpy.types.Collection) -> None:
    if owner not in obj.users_collection:
        owner.objects.link(obj)
    for existing in tuple(obj.users_collection):
        if existing != owner:
            existing.objects.unlink(obj)


def bounds(objects: list[bpy.types.Object]) -> tuple[list[float], list[float]]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (
        [min(point[i] for point in points) for i in range(3)],
        [max(point[i] for point in points) for i in range(3)],
    )


def main() -> None:
    state = validate_state(args().state)
    source, source_hash = validate_source(state)
    output = reference_library_path(state)
    report_path = reference_library_report_path(state)
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = f"V11REF_{state.upper()}"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"

    root = new_child(scene.collection, f"V11REF__{state.upper()}__V8_CLEAN")
    hierarchy = new_child(root, "00_IMPORT_HIERARCHY")
    locked = new_child(root, "10_LOCKED_HARDPOINTS")
    functional = new_child(root, "20_FUNCTIONAL_REFERENCES")
    replaceable = new_child(root, "30_REPLACEABLE_V8_SKIN")
    root["pipeline_id"] = PIPELINE_ID
    root["wc_state"] = state
    root["source_glb"] = str(source)
    root["source_glb_sha256"] = source_hash
    root["unit_contract"] = "1 Blender unit = 1 metre"
    root["axis_contract"] = "corrected Blender XYZ = WorkCore CAD XYZ"
    replaceable.hide_render = True
    replaceable.hide_select = True

    before = {obj.as_pointer() for obj in bpy.data.objects}
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
    imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    expected_count = int(config()["states"][state]["expected_mesh_count"])
    if len(meshes) != expected_count:
        raise RuntimeError(f"{state}: mesh count {len(meshes)} != {expected_count}")

    normalizer = bpy.data.objects.new(f"V11REF__{state.upper()}__CAD_AXIS_ROOT", None)
    hierarchy.objects.link(normalizer)
    normalizer.rotation_euler = (-math.pi / 2.0, 0.0, 0.0)
    normalizer["axis_transform"] = "Rx(-90deg) exactly once; no scale transform"

    counts: Counter[str] = Counter()
    ids: list[str] = []
    for obj in sorted(imported, key=lambda value: value.name):
        original = obj.name
        ids.append(original)
        obj["wc_occurrence_id"] = original
        obj["wc_state"] = state
        obj["wc_source_kind"] = "V8_CLEAN_GLB"
        if obj.parent is None:
            obj.parent = normalizer
        if obj.type != "MESH":
            obj["wc_reference_role"] = "IMPORT_HIERARCHY"
            obj.name = f"V11REF__{state.upper()}__{original}"
            link_only(obj, hierarchy)
            continue
        role = reference_role(original)
        counts[role] += 1
        obj["wc_reference_role"] = role
        obj.name = f"V11REF__{state.upper()}__{original}"
        if role == "LOCKED_HARDPOINT":
            link_only(obj, locked)
        elif role == "FUNCTIONAL_REFERENCE":
            link_only(obj, functional)
        else:
            obj.display_type = "WIRE"
            obj.color = (0.10, 0.32, 0.52, 0.16)
            link_only(obj, replaceable)

    bpy.context.view_layer.update()
    minimum, maximum = bounds(meshes)
    expected_bounds = config()["states"][state]["expected_bounds_m"]
    for axis in range(3):
        if abs(minimum[axis] - float(expected_bounds[0][axis])) > 0.001:
            raise RuntimeError(f"{state}: min bound drift axis {axis}")
        if abs(maximum[axis] - float(expected_bounds[1][axis])) > 0.001:
            raise RuntimeError(f"{state}: max bound drift axis {axis}")

    temporary = output.with_name(output.stem + ".partial.blend")
    if temporary.exists():
        temporary.unlink()
    bpy.ops.wm.save_as_mainfile(
        filepath=str(temporary), check_existing=False, compress=True, relative_remap=True
    )
    if not temporary.is_file() or temporary.stat().st_size < 1024:
        raise RuntimeError(f"Incomplete reference library: {temporary}")
    os.replace(temporary, output)
    report = {
        "schema_version": 1,
        "pipeline_id": PIPELINE_ID,
        "status": "PASS",
        "state": state,
        "blender_version": bpy.app.version_string,
        "source_glb": str(source),
        "source_glb_sha256": source_hash,
        "output_library": str(output),
        "output_library_sha256": sha256(output),
        "root_collection": root.name,
        "mesh_count": len(meshes),
        "role_counts": dict(sorted(counts.items())),
        "occurrence_ids_unique": len(set(ids)) == len(ids),
        "corrected_bounds_m": {
            "minimum": [round(value, 6) for value in minimum],
            "maximum": [round(value, 6) for value in maximum],
        },
    }
    atomic_write_json(report_path, report)
    print("V11_REFERENCE_LIBRARY_OK", state, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)

