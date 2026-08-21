"""Targeted saved-file QA for the Blender-only V11 R14 exterior pass.

This deliberately does not run or claim STEP, structural, packaging or motion
validation.  It verifies only the six R14 visual changes and four-state file
consistency needed before rendering the delivery series.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import traceback
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from v11_common import V11_ROOT, atomic_write_json, sha256, state_blend_path  # noqa: E402


REVISION = "r14"
STATES = ("follow", "ride", "cafe", "focus")
OUTPUT = V11_ROOT / "qa" / REVISION / "validation_summary.json"


def rounded(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def by_token(token: str) -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if token in obj.name]


def occurrence(identifier: str) -> bpy.types.Object | None:
    return next(
        (obj for obj in bpy.data.objects if str(obj.get("wc_occurrence_id", "")) == identifier),
        None,
    )


def local_dimensions_mm(obj: bpy.types.Object) -> list[float]:
    points = [vertex.co for vertex in obj.data.vertices]
    return [
        rounded((max(point[index] for point in points) - min(point[index] for point in points)) * 1000.0)
        for index in range(3)
    ]


def world_bounds_mm(obj: bpy.types.Object) -> dict[str, list[float]]:
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    mins = [min(point[index] for point in points) * 1000.0 for index in range(3)]
    maxs = [max(point[index] for point in points) * 1000.0 for index in range(3)]
    return {
        "min": [rounded(value) for value in mins],
        "max": [rounded(value) for value in maxs],
        "centre": [rounded((lo + hi) * 0.5) for lo, hi in zip(mins, maxs)],
        "dimensions": [rounded(hi - lo) for lo, hi in zip(mins, maxs)],
    }


def mesh_hash(obj: bpy.types.Object) -> str:
    digest = hashlib.sha256()
    for vertex in obj.data.vertices:
        digest.update(struct.pack("<3d", *(round(float(value), 8) for value in vertex.co)))
    for polygon in obj.data.polygons:
        digest.update(struct.pack("<I", len(polygon.vertices)))
        for index in polygon.vertices:
            digest.update(struct.pack("<I", int(index)))
    return digest.hexdigest()


def one(token: str) -> bpy.types.Object:
    matches = by_token(token)
    if len(matches) != 1:
        raise RuntimeError(f"{token}: expected one object, found {[obj.name for obj in matches]}")
    return matches[0]


def inspect_state(state: str) -> dict[str, Any]:
    path = state_blend_path(state, REVISION)
    bpy.ops.wm.open_mainfile(filepath=str(path))
    scene = bpy.context.scene
    if str(scene.get("wc_state", "")) != state:
        raise RuntimeError(f"{state}: scene state mismatch")
    if str(scene.get("visual_revision", "")) != REVISION:
        raise RuntimeError(f"{state}: scene revision mismatch")

    display = one("A05_SINGLE_FLUSH_DISPLAY")
    display_dims = local_dimensions_mm(display)
    display_pitch = rounded(math.degrees(display.rotation_euler.y), 4)
    forbidden_supports = [
        obj.name
        for obj in bpy.data.objects
        if any(token in obj.name.upper() for token in ("DISPLAY_SADDLE", "HMI_PLINTH"))
        and not obj.name.startswith("V11_R14_TEMP_INTERNAL")
    ]
    display_pass = (
        all(abs(value - target) <= 0.6 for value, target in zip(display_dims, (124.0, 86.0, 2.5)))
        and abs(display_pitch - 8.0) <= 0.05
        and list(display.get("display_face_mm", [])) == [124.0, 86.0]
        and not forbidden_supports
    )

    shell = one("A06_ICONIC_FRONT_TRAPEZOID")
    contact = one("A06_NATURAL_MAILLARD_LEATHER_CONTACT")
    shell_widths = list(shell.get("front_view_width_bottom_top_mm", []))
    contact_widths = list(contact.get("front_view_width_bottom_top_mm", []))
    contact_materials = [slot.material.name for slot in contact.material_slots if slot.material]
    trapezoid_pass = (
        shell_widths == [516.0, 400.0]
        and contact_widths == [470.0, 346.0]
        and shell_widths[1] / shell_widths[0] <= 0.78
        and any("MAILLARD" in name for name in contact_materials)
    )

    crown = one("A07_INTEGRATED_OPTICAL_CROWN")
    window = one("A07_SINGLE_SMOKED_OPTICAL_WINDOW")
    crown_dims = local_dimensions_mm(crown)
    window_dims = local_dimensions_mm(window)
    crown_pass = (
        all(abs(value - target) <= 0.8 for value, target in zip(crown_dims, (60.0, 300.0, 52.0)))
        and abs(window_dims[0] - 2.4) <= 0.5
        and abs(window_dims[1] - 250.0) <= 0.8
        and abs(window_dims[2] - 26.0) <= 0.8
    )

    joystick = occurrence("A05_right_joystick")
    key = occurrence("A05_right_authorisation_key")
    if joystick is None or key is None:
        raise RuntimeError(f"{state}: right controls missing")
    joystick_bounds = world_bounds_mm(joystick)
    key_bounds = world_bounds_mm(key)
    right_arm = one("FIXED_LOW_ARM_RIGHT")
    control_pass = (
        abs(float(right_arm.get("maximum_main_top_mm", -1.0)) - 674.0) <= 0.1
        and abs(float(joystick.get("r14_visual_z_shift_mm", 0.0)) + 23.0) <= 0.1
        and abs(float(key.get("r14_visual_z_shift_mm", 0.0)) + 23.0) <= 0.1
        and 706.0 <= joystick_bounds["max"][2] <= 710.0
    )

    seat = one("TAPERED_NATURAL_LEATHER_SEAT")
    top_faces = [polygon for polygon in seat.data.polygons if polygon.normal.z > 0.985]
    seat_materials = [slot.material.name for slot in seat.material_slots if slot.material]
    seat_pass = (
        bool(top_faces)
        and all(not polygon.use_smooth for polygon in top_faces)
        and bool(seat_materials)
    )
    body = one("SINGLE_ASYMMETRIC_MONOCOQUE")
    relief = float(body.get("front_thigh_relief_extension_mm", -1.0))
    relief_pass = abs(relief - 68.0) <= 0.1

    partials = [str(path) for path in path.parent.glob("*.partial.blend")]
    return {
        "state": state,
        "blend": str(path),
        "blend_bytes": path.stat().st_size,
        "blend_sha256": sha256(path),
        "partial_blends": partials,
        "checks": {
            "display_124x86_single_layer": {
                "pass": display_pass,
                "object": display.name,
                "local_dimensions_mm": display_dims,
                "pitch_deg": display_pitch,
                "forbidden_support_objects": forbidden_supports,
                "mesh_hash": mesh_hash(display),
            },
            "a06_trapezoid_and_maillard": {
                "pass": trapezoid_pass,
                "shell_width_bottom_top_mm": shell_widths,
                "contact_width_bottom_top_mm": contact_widths,
                "contact_materials": contact_materials,
                "shell_mesh_hash": mesh_hash(shell),
                "contact_mesh_hash": mesh_hash(contact),
            },
            "a07_optical_crown": {
                "pass": crown_pass,
                "crown_dimensions_mm": crown_dims,
                "window_dimensions_mm": window_dims,
                "crown_mesh_hash": mesh_hash(crown),
                "window_mesh_hash": mesh_hash(window),
            },
            "lower_external_right_controls": {
                "pass": control_pass,
                "right_arm_target_top_mm": right_arm.get("maximum_main_top_mm"),
                "joystick_bounds_mm": joystick_bounds,
                "authorisation_key_bounds_mm": key_bounds,
                "joystick_mesh_hash": mesh_hash(joystick),
            },
            "seat_surface_and_thigh_relief": {
                "pass": seat_pass and relief_pass,
                "flat_top_face_count": len(top_faces),
                "all_top_faces_flat": all(not polygon.use_smooth for polygon in top_faces),
                "seat_materials": seat_materials,
                "front_thigh_relief_extension_mm": relief,
                "seat_mesh_hash": mesh_hash(seat),
            },
            "saved_file_atomicity": {
                "pass": path.is_file() and path.stat().st_size > 1024 and not partials,
                "partial_blends": partials,
            },
        },
    }


def consistency(states: dict[str, dict[str, Any]], check: str, field: str) -> dict[str, Any]:
    values = {state: states[state]["checks"][check][field] for state in STATES}
    return {"pass": len(set(values.values())) == 1, "values": values}


def main() -> None:
    missing = [str(state_blend_path(state, REVISION)) for state in STATES if not state_blend_path(state, REVISION).is_file()]
    if missing:
        raise FileNotFoundError("Missing R14 blends: " + ", ".join(missing))
    states = {state: inspect_state(state) for state in STATES}
    checks = []
    for state in STATES:
        for check_id, result in states[state]["checks"].items():
            checks.append({"id": f"{state}.{check_id}", "pass": bool(result["pass"])})

    cross_state = {
        "display_geometry": consistency(states, "display_124x86_single_layer", "mesh_hash"),
        "a06_shell_geometry": consistency(states, "a06_trapezoid_and_maillard", "shell_mesh_hash"),
        "a06_contact_geometry": consistency(states, "a06_trapezoid_and_maillard", "contact_mesh_hash"),
        "a07_crown_geometry": consistency(states, "a07_optical_crown", "crown_mesh_hash"),
        "joystick_geometry": consistency(states, "lower_external_right_controls", "joystick_mesh_hash"),
        "seat_geometry": consistency(states, "seat_surface_and_thigh_relief", "seat_mesh_hash"),
    }
    checks.extend({"id": f"four_state.{name}", "pass": value["pass"]} for name, value in cross_state.items())
    failures = [check["id"] for check in checks if not check["pass"]]
    payload = {
        "schema_version": 1,
        "revision": REVISION,
        "scope": "saved Blender exterior appearance only; no STEP/motion/structure/packaging claim",
        "overall_status": "PASS" if not failures else "FAIL",
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failures),
            "failed": len(failures),
            "failed_check_ids": failures,
        },
        "states": states,
        "four_state_consistency": cross_state,
    }
    atomic_write_json(OUTPUT, payload)
    print(f"R14_VISUAL_VALIDATION_{payload['overall_status']} {OUTPUT}", flush=True)
    print(json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
