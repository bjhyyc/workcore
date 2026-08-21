"""Build V11 R10 from the R09 audit: continuous side skirt and flush arm lids."""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
import build_v11_visual_r03 as r03  # noqa: E402
import build_v11_visual_r09 as r09  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, sha256, state_blend_path, validate_state  # noqa: E402


REVISION = "r10"
ACTIVE_STATE = "ride"


def materials() -> dict[str, bpy.types.Material]:
    mats = r09.materials()
    body = mats["body"]
    body.diffuse_color = (0.0032, 0.0024, 0.0019, 1.0)
    if body.node_tree:
        node = body.node_tree.nodes.get("Principled BSDF")
        if node:
            node.inputs["Base Color"].default_value = body.diffuse_color
    lower = mats["body_soft"]
    lower.diffuse_color = (0.0010, 0.0012, 0.0013, 1.0)
    if lower.node_tree:
        node = lower.node_tree.nodes.get("Principled BSDF")
        if node:
            node.inputs["Base Color"].default_value = lower.diffuse_color
    return mats


def arm_loft(
    owner: bpy.types.Collection,
    name: str,
    side: str,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    controls = [
        (-0.382, 0.250, 0.354, 0.470, 0.625),
        (-0.352, 0.232, 0.375, 0.435, 0.654),
        (-0.300, 0.252, 0.375, 0.423, 0.655),
        (-0.205, 0.265, 0.375, 0.420, 0.655),
        (0.225, 0.265, 0.375, 0.432, 0.654),
        (0.262, 0.284, 0.356, 0.468, 0.622),
        (0.290, 0.309, 0.334, 0.515, 0.566),
    ]
    stations = r09.interpolate_controls(controls, 5)
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
    r09.clean_mesh(obj)
    return obj


def rounded_prism_xz(
    owner: bpy.types.Collection,
    name: str,
    centre: tuple[float, float, float],
    length_x: float,
    height_z: float,
    thickness_y: float,
    radius_xz: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    outline = r03.rounded_rectangle_points(length_x, height_z, radius_xz, 12)
    cx, cy, cz = centre
    y0 = cy - thickness_y * 0.5
    y1 = cy + thickness_y * 0.5
    vertices = [(cx + x, y0, cz + z) for x, z in outline] + [(cx + x, y1, cz + z) for x, z in outline]
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
    r01.set_smooth(obj)
    r09.clean_mesh(obj)
    return obj


def discard(objects: list[bpy.types.Object], tokens: tuple[str, ...]) -> None:
    for obj in list(objects):
        if any(token in obj.name for token in tokens):
            objects.remove(obj)
            bpy.data.objects.remove(obj, do_unlink=True)


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = r09.build_lower_and_arms(owner, mats)
    body = bpy.data.objects.get("V11_R09_SHARED_SINGLE_ASYMMETRIC_MONOCOQUE")
    if body is None:
        raise RuntimeError("R10: R09 monocoque missing")

    discard(
        objects,
        (
            "A04_LEFT_FLUSH_EQUIPMENT_DOOR_SEAM",
            "A04_RIGHT_FLUSH_EQUIPMENT_DOOR_SEAM",
            "A10_FLUSH_REAR_SERVICE_DOOR_SEAM",
            "A08_FRONT_TELESCOPIC_CASSETTE_SEAM",
            "LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID",
            "RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID",
            "LEFT_ACCESS_LID_SEAM",
            "RIGHT_ACCESS_LID_SEAM",
        ),
    )

    for side, y_centre in (("LEFT", -0.370), ("RIGHT", 0.370)):
        ribbon = rounded_prism_xz(
            owner,
            f"V11_R10_TEMP_{side}_CONTINUOUS_WHEEL_SIDE_SKIRT",
            (-0.100, y_centre, 0.255),
            0.820,
            0.310,
            0.010,
            0.065,
            mats["body_soft"],
        )
        r09.boolean(body, ribbon, "UNION", f"V11_R10_UNION_{side}_CONTINUOUS_SIDE_SKIRT")
    body["wheel_wrap_policy_r10"] = "single unioned 820 mm side mother surface; lower 44 percent of tyre remains readable"

    left_lid = r09.rounded_prism_xy(owner, "V11_R10_A05_LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID", (0.000, -0.320, 0.6550), 0.440, 0.096, 0.0020, 0.017, mats["body"], 0.0003)
    left_lid["source_occurrence_ids"] = "A05_armrest_table_bay_lid_left"
    left_lid["motion"] = "outward flip about outer edge; retrieve table; close lid"
    left_lid["owns_qi"] = True
    right_lid = r09.rounded_prism_xy(owner, "V11_R10_A05_RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID", (0.020, 0.320, 0.6550), 0.410, 0.096, 0.0020, 0.017, mats["body"], 0.0003)
    right_lid["source_occurrence_ids"] = "A05_armrest_table_bay_lid_right"
    right_lid["motion"] = "outward flip about outer edge; fixed HMI island remains forward and exposed"
    right_lid["fixed_hmi_clearance_mm"] = 15.0
    objects.extend([left_lid, right_lid])
    objects.append(r09.flat_outline_curve(owner, "V11_R10_A05_LEFT_ACCESS_LID_SEAM", (0.000, -0.320, 0.6562), 0.440, 0.096, 0.017, mats["seam"], 0.00055))
    objects.append(r09.flat_outline_curve(owner, "V11_R10_A05_RIGHT_ACCESS_LID_SEAM", (0.020, 0.320, 0.6562), 0.410, 0.096, 0.017, mats["seam"], 0.00055))

    for name in ("V11_R09_A05_LEFT_QI_FLUSH_USABLE_FIELD_176X86", "V11_R09_A05_LEFT_QI_TARGET_RING"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.location.z -= 0.0025

    for side, plane in (("LEFT", "LEFT_XZ"), ("RIGHT", "RIGHT_XZ")):
        door = r09.projected_curve(owner, f"V11_R10_A04_{side}_FLUSH_EQUIPMENT_DOOR_SEAM", body, plane, (-0.020, 0.366), 0.466, 0.088, 0.019, mats["seam"], 0.00065)
        door["source_occurrence_ids"] = f"A04_equipment_door_{side.lower()}"
        door["door_skin_is_mother_surface"] = True
        door["door_skin_mm"] = "464 x 86 R18"
        door["opening_mm"] = "466 x 88 R19"
        door["nominal_seam_mm"] = 1.0
        door["service_travel_mm"] = 300.0
        door["internal_rail_validation"] = "mandatory after STEP round-trip"
        objects.append(door)
    rear = r09.projected_curve(owner, "V11_R10_A10_FLUSH_REAR_SERVICE_DOOR_SEAM", body, "REAR_YZ", (0.0, 0.315), 0.370, 0.198, 0.024, mats["seam"], 0.00065)
    rear["source_occurrence_ids"] = "A10_rear_flush_service_door_skin"
    objects.append(rear)
    footrest = r09.projected_curve(owner, "V11_R10_A08_FRONT_TELESCOPIC_CASSETTE_SEAM", body, "FRONT_YZ", (0.0, 0.103), 0.506, 0.032, 0.012, mats["seam"], 0.00070)
    footrest["source_occurrence_ids"] = "A08_footrest_cassette_opening"
    footrest["stow_motion"] = "+220 mm X telescopic translation; 506 x 32 mm physical opening"
    objects.append(footrest)

    for obj in objects:
        if "R09" in obj.name:
            obj.name = obj.name.replace("R09", "R10")
        if getattr(obj, "data", None) is not None and "R09" in obj.data.name:
            obj.data.name = obj.data.name.replace("R09", "R10")
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    parts = r09.build_a06_a07(owner, state, mats)
    for obj in parts:
        if "R09" in obj.name:
            obj.name = obj.name.replace("R09", "R10")
        if getattr(obj, "data", None) is not None and "R09" in obj.data.name:
            obj.data.name = obj.data.name.replace("R09", "R10")
    return parts


def main() -> None:
    global ACTIVE_STATE
    ACTIVE_STATE = validate_state(r01.args().state)
    r09.ACTIVE_STATE = ACTIVE_STATE
    r09.arm_loft = arm_loft
    r01.REVISION = REVISION
    r01.REPORT_ROOT = V11_ROOT / "qa" / REVISION
    r01.build_materials = materials
    r01.clone_material_for_occurrence = r09.clone_material
    r01.should_clone_occurrence = r09.should_clone
    r01.build_lower_and_arms = build_lower_and_arms
    r01.build_a06_a07 = build_a06_a07
    r01.configure_studio = r09.studio
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
        "qi_usable_field_mm": "176 x 86; single flush field owned by left lid",
        "focus_a07_motion_mm": 420.0 if ACTIVE_STATE == "focus" else 0.0,
        "follow_fold_deg": -90.0 if ACTIVE_STATE == "follow" else 0.0,
        "footrest": "+220 mm X telescopic stow; open only in Ride default",
    }
    payload["r10_form_changes"] = [
        "two 10 mm skins are boolean-unioned as one continuous 820 mm side mother surface, not separate fenders",
        "arm full-width top now continues through the access-lid rear edge before dissolving into the body",
        "2 mm closed lids sit flush and Qi is lowered onto its owning left lid",
        "upper bronze is darkened to keep Follow closer to a quiet black-box object",
    ]
    payload["known_limits"] = [
        "Blender visual/layout decision model; production BRep and internal equipment package remain pending",
        "formal saved-file validation and complete view coverage remain mandatory",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R10_BUILT_UNVALIDATED", ACTIVE_STATE, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
