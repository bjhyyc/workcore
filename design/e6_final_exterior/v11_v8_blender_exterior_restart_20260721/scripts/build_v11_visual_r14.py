"""Build V11 R14: Leica-like CMF and disciplined exterior proportion pass.

R14 is intentionally a Blender-only appearance revision derived from R13.
It does not alter any STEP asset or claim a new kinematic/packaging release.
The pass addresses six visible issues: Maillard upholstery, a clearly readable
A06 trapezoid, a wider single-layer display, a credible A07 optical crown, a
lower integrated joystick landing, and a calmer front-thigh transition.
"""

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
import build_v11_visual_r05 as r05  # noqa: E402
import build_v11_visual_r09 as r09  # noqa: E402
import build_v11_visual_r10 as r10  # noqa: E402
import build_v11_visual_r11 as r11  # noqa: E402
import build_v11_visual_r13 as r13  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, sha256, state_blend_path  # noqa: E402


REVISION = "r14"
BASE_R10_MATERIALS = r10.materials
BASE_R13_BUILD_LOWER = r13.build_lower_and_arms
BASE_R13_BUILD_A06_A07 = r13.build_a06_a07
BASE_R13_LINK_REFERENCE = r13.link_reference_and_clean_clone


def _principled(mat: bpy.types.Material) -> bpy.types.Node | None:
    return mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None


def _set_surface(
    mat: bpy.types.Material,
    colour: tuple[float, float, float, float],
    roughness: float,
    specular: float,
    coat: float,
) -> None:
    mat.diffuse_color = colour
    node = _principled(mat)
    if node is None:
        return
    node.inputs["Base Color"].default_value = colour
    node.inputs["Roughness"].default_value = roughness
    socket = node.inputs.get("Specular IOR Level")
    if socket is not None:
        socket.default_value = specular
    socket = node.inputs.get("Coat Weight")
    if socket is not None:
        socket.default_value = coat


def _retune_bump(mat: bpy.types.Material, scale: float, strength: float, distance: float) -> None:
    if not mat.node_tree:
        return
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexNoise" and node.inputs.get("Scale") is not None:
            node.inputs["Scale"].default_value = scale
        elif node.bl_idname == "ShaderNodeBump":
            node.inputs["Strength"].default_value = strength
            node.inputs["Distance"].default_value = distance


def materials() -> dict[str, bpy.types.Material]:
    mats = BASE_R10_MATERIALS()

    # The contact surfaces are one restrained Maillard family: the A06 panel
    # is roasted chestnut and the seat is a darker espresso-brown companion.
    # This removes the previous coral/red read without adding decorative CMF.
    _set_surface(mats["leather"], (0.0210, 0.0070, 0.0025, 1.0), 0.64, 0.20, 0.010)
    _retune_bump(mats["leather"], 180.0, 0.050, 0.00026)
    mats["leather"].name = "V11_R14_MAT_NATURAL_MAILLARD_ESPRESSO_LEATHER"

    backrest = r09.tuned_material(
        "V11_R14_MAT_NATURAL_MAILLARD_ROASTED_CHESTNUT_LEATHER",
        (0.0300, 0.0105, 0.0035, 1.0),
        0.63,
        0.0,
        0.21,
    )
    r09.add_micro_bump(backrest, 180.0, 0.050, 0.00026)
    _set_surface(backrest, (0.0300, 0.0105, 0.0035, 1.0), 0.63, 0.21, 0.010)
    mats["backrest_leather"] = backrest

    # A slightly tighter reflection and finer mineral grain carries precision
    # through large surfaces without introducing bright trim or fake seams.
    _set_surface(mats["body"], (0.0032, 0.0024, 0.0019, 1.0), 0.50, 0.20, 0.012)
    _retune_bump(mats["body"], 90.0, 0.010, 0.00012)
    _set_surface(mats["body_soft"], (0.0010, 0.0012, 0.0013, 1.0), 0.50, 0.18, 0.010)
    _retune_bump(mats["body_soft"], 96.0, 0.009, 0.00011)
    _set_surface(mats["glass"], (0.00035, 0.0017, 0.0026, 1.0), 0.10, 0.42, 0.050)

    optic = r09.tuned_material(
        "V11_R14_MAT_SATIN_BLACK_OPTICAL_HOUSING",
        (0.0022, 0.0018, 0.0015, 1.0),
        0.30,
        0.30,
        0.30,
    )
    _set_surface(optic, (0.0022, 0.0018, 0.0015, 1.0), 0.30, 0.30, 0.010)
    mats["optic_housing"] = optic

    for mat in mats.values():
        for token in ("R13", "R12", "R11", "R10", "R09"):
            if token in mat.name:
                mat.name = mat.name.replace(token, "R14")
    return mats


def integrated_arm_loft(
    owner: bpy.types.Collection,
    name: str,
    side: str,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    # The inner prow opens by 8-10 mm near the thigh, while the global arm
    # hardpoints and rear closure remain unchanged.  The right control landing
    # is a shallow continuation of the mother surface, not a separate plinth.
    controls = [
        (-0.382, 0.238, 0.354, 0.470, 0.662),
        (-0.358, 0.230, 0.375, 0.435, 0.6723),
        (-0.300, 0.233, 0.375, 0.423, 0.6645),
        (-0.230, 0.238, 0.375, 0.420, 0.6550),
        (-0.185, 0.240, 0.375, 0.420, 0.6550),
        (-0.150, 0.242, 0.375, 0.421, 0.6550),
        (0.145, 0.258, 0.375, 0.427, 0.6540),
        (0.225, 0.265, 0.375, 0.432, 0.6540),
        (0.262, 0.284, 0.356, 0.468, 0.6220),
        (0.290, 0.309, 0.334, 0.515, 0.5660),
    ]
    stations = r09.interpolate_controls(controls, 6)
    ring_segments = 64
    exponent = 0.16
    sign = -1.0 if side == "LEFT" else 1.0
    vertices: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []

    for x, inner, outer, bottom, top in stations:
        if side == "LEFT" and -0.358 <= x <= -0.230:
            # The 124 mm screen keeps the accepted +8 degree direct landing.
            top = 0.67226 + (x + 0.358) * ((0.65476 - 0.67226) / 0.128)
        elif side == "RIGHT":
            if -0.358 <= x < -0.330:
                top = 0.6723 + (x + 0.358) * ((0.6740 - 0.6723) / 0.028)
            elif -0.330 <= x <= -0.200:
                top = 0.6740
            elif -0.200 < x <= -0.150:
                top = 0.6740 + (x + 0.200) * ((0.6550 - 0.6740) / 0.050)

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


def create_display(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    display = r09.rounded_prism_xy(
        owner,
        "V11_R14_A05_SINGLE_FLUSH_DISPLAY_124X86X2P5",
        (0.0, 0.0, 0.0),
        0.124,
        0.086,
        0.0025,
        0.009,
        mats["glass"],
        0.0004,
    )
    display.location = (-0.294, -0.320, 0.66487)
    display.rotation_mode = "XYZ"
    display.rotation_euler.y = math.radians(8.0)
    display["source_occurrence_ids"] = "A05_left_status_display_window"
    display["display_face_mm"] = [124.0, 86.0]
    display["qi_matching_cross_arm_width_mm"] = 86.0
    display["uniform_normal_thickness_mm"] = 2.5
    display["world_y_pitch_deg"] = 8.0
    display["rotation_origin"] = "own geometric centre"
    display["support"] = "single glass layer lands directly on continuous left-arm mother surface"
    display["slope"] = "front high; rear low"
    return display


def _flat_primary_faces(obj: bpy.types.Object, axis: str) -> None:
    if obj.type != "MESH":
        return
    for polygon in obj.data.polygons:
        component = getattr(polygon.normal, axis)
        if abs(component) > 0.985:
            polygon.use_smooth = False
    obj.data.update()


def _extend_front_thigh_relief(
    body: bpy.types.Object,
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> None:
    # Extend only the central seat-well depression 68 mm toward the front.
    # The exterior side cheeks and the A08 cassette remain untouched.
    cutter = r05.polygon_prism_xy(
        owner,
        "V11_R14_TEMP_FRONT_THIGH_RELIEF",
        [(-0.410, -0.210), (-0.410, 0.210), (-0.332, 0.222), (-0.332, -0.222)],
        0.422,
        0.700,
        0.024,
        mats["seam"],
    )
    r09.boolean(body, cutter, "DIFFERENCE", "V11_R14_FRONT_THIGH_RELIEF")
    body["front_thigh_relief_extension_mm"] = 68.0
    body["front_thigh_relief_policy"] = "central mother-surface depression; no new cover, seam or moving part"


def _rename_revision(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        for token in ("R13", "R12", "R11", "R10", "R09"):
            if token in obj.name:
                obj.name = obj.name.replace(token, "R14")
            if getattr(obj, "data", None) is not None and token in obj.data.name:
                obj.data.name = obj.data.name.replace(token, "R14")


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = BASE_R13_BUILD_LOWER(owner, mats)
    _rename_revision(objects)
    body = next((obj for obj in objects if "SINGLE_ASYMMETRIC_MONOCOQUE" in obj.name), None)
    if body is None:
        raise RuntimeError("R14 monocoque missing")
    _extend_front_thigh_relief(body, owner, mats)

    for obj in objects:
        if "TAPERED_NATURAL_LEATHER_SEAT" in obj.name:
            _flat_primary_faces(obj, "z")
            obj["surface_shading"] = "top and bottom contact planes flat; radiused perimeter smooth"
        elif "FIXED_LOW_ARM_RIGHT" in obj.name:
            obj["maximum_main_top_mm"] = 674.0
            obj["hmi_integration"] = "lower 674 mm shallow mother-surface landing; no separate plinth"
        elif "FIXED_LOW_ARM_LEFT" in obj.name:
            obj["maximum_main_top_mm"] = 673.0
            obj["hmi_integration"] = "124 x 86 display lands directly on arm mother surface"
    return objects


def build_a06_a07_base(
    owner: bpy.types.Collection,
    state: str,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    parts: list[bpy.types.Object] = []
    shell = r01.trapezoid_prism(
        owner,
        f"V11_R14_{state.upper()}_A06_ICONIC_FRONT_TRAPEZOID",
        0.135,
        0.265,
        0.535,
        1.035,
        0.258,
        0.200,
        mats["body"],
        0.018,
    )
    r09.clean_mesh(shell)
    _flat_primary_faces(shell, "x")
    shell["source_occurrence_ids"] = "A06_backrest_weather_shell"
    shell["front_view_width_bottom_top_mm"] = [516.0, 400.0]
    shell["identity"] = "same immediately readable front-view trapezoid in all states; same part is Follow upper surface"

    contact = r01.trapezoid_prism(
        owner,
        f"V11_R14_{state.upper()}_A06_NATURAL_MAILLARD_LEATHER_CONTACT",
        0.127,
        0.136,
        0.572,
        0.987,
        0.235,
        0.173,
        mats["backrest_leather"],
        0.003,
    )
    r09.clean_mesh(contact)
    _flat_primary_faces(contact, "x")
    contact["source_occurrence_ids"] = "A06_backrest_contact_panel"
    contact["front_view_width_bottom_top_mm"] = [470.0, 346.0]
    contact["cmf"] = "natural roasted-chestnut Maillard leather; no red coating"
    parts.extend([shell, contact])

    mast = r01.trapezoid_prism(
        owner,
        f"V11_R14_{state.upper()}_A07_ORIGINAL_EXPOSED_TRAPEZOID_BLADE",
        0.270,
        0.290,
        0.575,
        1.065,
        0.050,
        0.034,
        mats["glass"],
        0.005,
    )
    r09.clean_mesh(mast)
    _flat_primary_faces(mast, "x")
    mast["source_occurrence_ids"] = "A07_mast_fixed_outer_sleeve,A07_mast_moving_inner_sleeve"
    mast["motion_contract"] = "same exposed mesh; Ride/Cafe low, Focus +420 mm Z, Follow co-fold"

    crown = r01.rounded_box(
        owner,
        f"V11_R14_{state.upper()}_A07_INTEGRATED_OPTICAL_CROWN",
        (0.280, 0.0, 1.073),
        (0.060, 0.300, 0.052),
        0.014,
        mats["optic_housing"],
        8,
    )
    r09.clean_mesh(crown)
    crown["source_occurrence_ids"] = "A07_sensor_beam_shell"
    crown["visual_envelope_mm"] = [60.0, 300.0, 52.0]
    crown["packaging_status"] = "credible exterior volume only; internal camera/light package dimensions remain TBD"

    window = r09.rounded_prism_yz(
        owner,
        f"V11_R14_{state.upper()}_A07_SINGLE_SMOKED_OPTICAL_WINDOW",
        (0.2488, 0.0, 1.073),
        0.250,
        0.026,
        0.0024,
        0.007,
        mats["glass"],
        0.00035,
    )
    window["source_occurrence_ids"] = "A07_sensor_beam_smoked_window"
    window["integration"] = "all cameras and fill-light apertures remain visually concealed behind one optical band"

    mast_parts = [mast, crown, window]
    parts.extend(mast_parts)
    if state == "focus":
        for obj in mast_parts:
            obj.location.z += 0.420
            obj["focus_translation_z_mm"] = 420.0
    elif state == "follow":
        pivot = bpy.data.objects.new("V11_R14_FOLLOW_A06_A07_COMMON_HINGE", None)
        owner.objects.link(pivot)
        pivot.location = (0.158, 0.0, 0.535)
        pivot.rotation_mode = "XYZ"
        r01.parent_rigid(parts, pivot)
        pivot.rotation_euler.y = math.radians(-90.0)
        pivot["fold_angle_deg"] = -90.0
        pivot["allowed_children"] = "same A06 shell/contact and same A07 blade/crown/window only; no hood or filler"
        parts.append(pivot)
    return parts


def build_a06_a07(
    owner: bpy.types.Collection,
    state: str,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    objects = BASE_R13_BUILD_A06_A07(owner, state, mats)
    _rename_revision(objects)
    return objects


def link_reference_and_lower_controls(
    scene: bpy.types.Scene,
    state: str,
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> tuple[bpy.types.Collection, list[bpy.types.Object]]:
    reference, clones = BASE_R13_LINK_REFERENCE(scene, state, owner, mats)
    for clone in clones:
        occurrence = str(clone.get("wc_occurrence_id", ""))
        if occurrence in {"A05_right_joystick", "A05_right_authorisation_key"}:
            clone.matrix_world.translation.z -= 0.023
            clone["r14_visual_z_shift_mm"] = -23.0
            clone["r14_mounting_relation"] = "same fixed external control; lowered with the continuous arm mother surface"
    safety_red = bpy.data.materials.get("V11_R13_MAT_MECHANICAL_SAFETY_RED")
    if safety_red is not None:
        safety_red.name = "V11_R14_MAT_MECHANICAL_SAFETY_RED"
    return reference, clones


def main() -> None:
    r13.REVISION = REVISION
    r13._rename_revision = _rename_revision
    r13.integrated_arm_loft = integrated_arm_loft
    r13.create_display = create_display
    r13.build_lower_and_arms = build_lower_and_arms
    r13.build_a06_a07 = build_a06_a07
    r13.link_reference_and_clean_clone = link_reference_and_lower_controls
    r09.build_a06_a07 = build_a06_a07_base
    r10.materials = materials
    r13.main()

    state = r11.ACTIVE_STATE
    output = state_blend_path(state, REVISION)
    report_path = V11_ROOT / "qa" / REVISION / f"v11_{state}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    payload["status"] = "BUILT_UNVALIDATED"
    payload["revision"] = REVISION
    payload["blend_sha256"] = sha256(output)
    payload["measured_product_bounds_after_save"] = r03.evaluated_product_bounds()
    contracts = payload.setdefault("contracts", {})
    contracts["display"] = "single 124 x 86 x 2.5 mm glass; cross-arm width matches Qi 86 mm; world-Y +8 deg; front high/rear low"
    contracts["a06_front_width_bottom_top_mm"] = [516.0, 400.0]
    contracts["a06_contact_width_bottom_top_mm"] = [470.0, 346.0]
    contracts["a07_crown_visual_envelope_mm"] = [60.0, 300.0, 52.0]
    contracts["right_control_mother_surface_top_mm"] = 674.0
    contracts["right_controls_visual_shift_z_mm"] = -23.0
    contracts["front_thigh_relief_extension_mm"] = 68.0
    payload["r14_form_changes"] = [
        "A06 and seat upholstery move from coral red to a restrained roasted-chestnut/espresso Maillard family",
        "A06 shell is now 516/400 mm bottom/top and its leather contact is 470/346 mm for an immediate trapezoid read",
        "single-layer display grows from 124 x 49 to 124 x 86 mm and remains directly supported at +8 degrees",
        "A07 receives one 60 x 300 x 52 mm satin-black optical crown with a single concealed smoked window",
        "right joystick mother surface drops from 697 to 674 mm and the joystick/key move with it by 23 mm",
        "central seat-well depression extends 68 mm toward the front to soften the hard thigh cross-lip",
        "large seat and A06 planes use flat normals while their precision radii remain smooth",
    ]
    payload["scope_r14"] = "Blender exterior proportion/CMF only; no STEP, kinematic or internal equipment revalidation claimed"
    payload["known_limits"] = [
        "A07 crown is a credible visual packaging envelope; exact camera, fill-light and thermal hardware remain TBD",
        "R14 deliberately does not change or validate STEP/BRep, motion paths, structural joints or production tooling",
        "Saved-file and render QA remain required before visual approval",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R14_BUILT_UNVALIDATED", state, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
