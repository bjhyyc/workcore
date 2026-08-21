"""Build V11 R12: tighter monocoque lower corner for true half wheel wrap."""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r03 as r03  # noqa: E402
import build_v11_visual_r09 as r09  # noqa: E402
import build_v11_visual_r11 as r11  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, sha256, state_blend_path  # noqa: E402


REVISION = "r12"
BASE_BUILD_LOWER = r11.build_lower_and_arms
BASE_BUILD_A06_A07 = r11.build_a06_a07


def continuous_body_loft(
    owner: bpy.types.Collection,
    name: str,
    controls: list[tuple[float, float, float, float]],
    exponent: float,
    mat: bpy.types.Material,
    ring_segments: int = 64,
) -> bpy.types.Object:
    return r11.BASE_LONGITUDINAL_LOFT(owner, name, controls, 0.08, mat, ring_segments)


def create_display(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    # Build in object-local coordinates.  R09 built at world coordinates and
    # then rotated about world origin, which displaced the screen upward/rear.
    display = r09.rounded_prism_xy(
        owner,
        "V11_R12_A05_SINGLE_UNIFORM_DISPLAY_124X49X2P5",
        (0.0, 0.0, 0.0),
        0.124,
        0.049,
        0.0025,
        0.006,
        mats["glass"],
        0.0004,
    )
    display.location = (-0.294, -0.320, 0.6915)
    display.rotation_mode = "XYZ"
    display.rotation_euler.y = math.radians(8.0)
    display["source_occurrence_ids"] = "A05_left_status_display_window"
    display["display_face_mm"] = [124.0, 49.0]
    display["uniform_normal_thickness_mm"] = 2.5
    display["world_y_pitch_deg"] = 8.0
    display["rotation_origin"] = "own geometric centre; underside mates to integral arm saddle"
    display["slope"] = "front high; rear low"
    return display


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = BASE_BUILD_LOWER(owner, mats)
    for obj in objects:
        if obj.name == "V11_R11_SHARED_SINGLE_ASYMMETRIC_MONOCOQUE":
            obj["cross_section_signed_power"] = 0.08
            obj["wheel_wrap_policy_r12"] = "one continuous body stays outside tyre through wheel centre, then returns before the contact patch"
        if "R11" in obj.name:
            obj.name = obj.name.replace("R11", "R12")
        if getattr(obj, "data", None) is not None and "R11" in obj.data.name:
            obj.data.name = obj.data.name.replace("R11", "R12")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = BASE_BUILD_A06_A07(owner, state, mats)
    for obj in objects:
        if "R11" in obj.name:
            obj.name = obj.name.replace("R11", "R12")
        if getattr(obj, "data", None) is not None and "R11" in obj.data.name:
            obj.data.name = obj.data.name.replace("R11", "R12")
    return objects


def main() -> None:
    r11.REVISION = REVISION
    r09.create_display = create_display
    r11.continuous_body_loft = continuous_body_loft
    r11.build_lower_and_arms = build_lower_and_arms
    r11.build_a06_a07 = build_a06_a07
    r11.main()

    state = r11.ACTIVE_STATE
    output = state_blend_path(state, REVISION)
    report_path = V11_ROOT / "qa" / REVISION / f"v11_{state}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    measured = r03.evaluated_product_bounds()
    payload["status"] = "BUILT_UNVALIDATED"
    payload["revision"] = REVISION
    payload["blend_sha256"] = sha256(output)
    payload["measured_product_bounds_after_save"] = measured
    payload["r12_form_changes"] = [
        "same monocoque signed-power cross-section tightened from 0.18 to 0.08",
        "upper tyre coverage now comes from continuous curvature with no fender, panel, lobe or new seam",
        "R11 Follow closure, HMI ownership, table cavities and telescopic footrest are unchanged",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R12_BUILT_UNVALIDATED", state, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
