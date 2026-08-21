"""Build the immutable four-state V8 reference master for V11.

V8 files are read-only.  Replaceable V8 skin is kept as viewport wire and is
hidden from beauty renders.  Functional and locked pieces retain their source
occurrence IDs so later design revisions can be checked against them.
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from v11_common import (  # noqa: E402
    PIPELINE_ID,
    REFERENCE_BLEND,
    REFERENCE_REPORT,
    STATES,
    atomic_write_json,
    config,
    reference_role,
    sha256,
    validate_source,
)


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


def evaluated_bounds(objects: list[bpy.types.Object]) -> dict[str, list[float]]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("No mesh bounds")
    minimum = [min(point[i] for point in points) for i in range(3)]
    maximum = [max(point[i] for point in points) for i in range(3)]
    return {
        "minimum_m": [round(value, 6) for value in minimum],
        "maximum_m": [round(value, 6) for value in maximum],
        "size_m": [round(maximum[i] - minimum[i], 6) for i in range(3)],
    }


def configure_scene(scene: bpy.types.Scene, state: str) -> None:
    scene.name = f"V11_{state.upper()}"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene["pipeline_id"] = PIPELINE_ID
    scene["wc_state"] = state
    scene["source_policy"] = "V8 clean GLB only; V9/V10 geometry excluded"


def import_state(state: str) -> tuple[bpy.types.Scene, dict[str, object]]:
    source, source_hash = validate_source(state)
    scene = bpy.data.scenes.new(f"V11_{state.upper()}")
    bpy.context.window.scene = scene
    configure_scene(scene, state)

    root = new_child(scene.collection, f"V11__{state.upper()}__ROOT")
    hierarchy = new_child(root, "00_V8_IMPORT_HIERARCHY")
    locked = new_child(root, "10_LOCKED_HARDPOINTS")
    functional = new_child(root, "20_FUNCTIONAL_REFERENCES")
    replaceable = new_child(root, "30_REPLACEABLE_V8_SKIN")
    design = new_child(root, "40_V11_NEW_DESIGN")
    qa = new_child(root, "50_QA_HELPERS")
    studio = new_child(root, "60_STUDIO")

    root["source_glb"] = str(source)
    root["source_glb_sha256"] = source_hash
    root["unit_contract"] = "1 Blender unit = 1 metre"
    root["axis_contract"] = "corrected Blender XYZ = WorkCore CAD XYZ"
    design["purpose"] = "All V11 visible exterior design geometry belongs here"
    qa["not_product_geometry"] = True
    studio["not_product_geometry"] = True

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
        raise RuntimeError(f"{state}: glTF import failed: {result}")
    imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    expected_count = int(config()["states"][state]["expected_mesh_count"])
    if len(meshes) != expected_count:
        raise RuntimeError(f"{state}: mesh count {len(meshes)} != {expected_count}")

    normalizer = bpy.data.objects.new(f"V11__{state.upper()}__CAD_AXIS_ROOT", None)
    hierarchy.objects.link(normalizer)
    normalizer.rotation_mode = "XYZ"
    normalizer.rotation_euler = (-math.pi / 2.0, 0.0, 0.0)
    normalizer["axis_transform"] = "Rx(-90deg) exactly once; no scale transform"

    role_counts: Counter[str] = Counter()
    occurrence_ids: list[str] = []
    for obj in sorted(imported, key=lambda item: item.name):
        original = obj.name
        occurrence_ids.append(original)
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
        role_counts[role] += 1
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

    replaceable.hide_render = True
    replaceable.hide_select = True
    bpy.context.view_layer.update()
    expected_bounds = config()["states"][state]["expected_bounds_m"]
    actual_bounds = evaluated_bounds(meshes)
    for axis in range(3):
        if abs(actual_bounds["minimum_m"][axis] - float(expected_bounds[0][axis])) > 0.001:
            raise RuntimeError(f"{state}: minimum bound drift on axis {axis}: {actual_bounds}")
        if abs(actual_bounds["maximum_m"][axis] - float(expected_bounds[1][axis])) > 0.001:
            raise RuntimeError(f"{state}: maximum bound drift on axis {axis}: {actual_bounds}")

    return scene, {
        "source_glb": str(source),
        "source_glb_sha256": source_hash,
        "mesh_count": len(meshes),
        "role_counts": dict(sorted(role_counts.items())),
        "occurrence_ids_unique": len(set(occurrence_ids)) == len(occurrence_ids),
        "corrected_bounds": actual_bounds,
        "collections": {
            "root": root.name,
            "locked": locked.name,
            "functional": functional.name,
            "replaceable": replaceable.name,
            "design": design.name,
            "qa": qa.name,
            "studio": studio.name,
        },
    }


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    report: dict[str, object] = {
        "schema_version": 1,
        "pipeline_id": PIPELINE_ID,
        "status": "PASS",
        "blender_version": bpy.app.version_string,
        "states": {},
    }
    scenes: dict[str, bpy.types.Scene] = {}
    for state in STATES:
        scenes[state], report["states"][state] = import_state(state)
        print("V11_REFERENCE_IMPORTED", state, flush=True)

    REFERENCE_BLEND.parent.mkdir(parents=True, exist_ok=True)
    temporary = REFERENCE_BLEND.with_name(REFERENCE_BLEND.stem + ".partial.blend")
    if temporary.exists():
        temporary.unlink()
    bpy.context.window.scene = scenes["ride"]
    bpy.ops.wm.save_as_mainfile(
        filepath=str(temporary), check_existing=False, compress=True, relative_remap=True
    )
    if not temporary.is_file() or temporary.stat().st_size < 1024:
        raise RuntimeError(f"Incomplete blend write: {temporary}")
    os.replace(temporary, REFERENCE_BLEND)
    report["reference_blend"] = str(REFERENCE_BLEND)
    report["reference_blend_sha256"] = sha256(REFERENCE_BLEND)
    atomic_write_json(REFERENCE_REPORT, report)
    print("V11_REFERENCE_MASTER_OK", REFERENCE_BLEND, flush=True)


if __name__ == "__main__":
    main()
