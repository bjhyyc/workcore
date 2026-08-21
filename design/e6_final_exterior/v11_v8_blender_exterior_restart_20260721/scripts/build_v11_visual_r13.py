"""Build V11 R13: integrated HMI prow, true wheel wrap and real footrest cassette.

R13 keeps the V8 hardpoints and the accepted R12 four-state logic.  It only
changes surfaces or voids that failed saved-file/visual review:

* the display and joystick now land on the arm mother surfaces, with no
  separately readable saddle or HMI plinth;
* the one-piece lower monocoque continues downward around the wheels;
* the A08 stow path is a physical cavity and the same footrest parts remain
  inside it in Follow/Cafe/Focus;
* generated-object traceability uses real V8 occurrence IDs.
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_v11_visual_r01 as r01  # noqa: E402
import build_v11_visual_r03 as r03  # noqa: E402
import build_v11_visual_r09 as r09  # noqa: E402
import build_v11_visual_r10 as r10  # noqa: E402
import build_v11_visual_r11 as r11  # noqa: E402
import build_v11_visual_r12 as r12  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, sha256, state_blend_path  # noqa: E402


REVISION = "r13"
BASE_R12_BUILD_LOWER = r12.build_lower_and_arms
BASE_R12_BUILD_A06_A07 = r12.build_a06_a07
BASE_ROUNDED_BOX = r01.rounded_box
BASE_LINK_REFERENCE_AND_CLONE = r01.link_reference_and_clone
BASE_BUILD_FOOTREST = r09.build_footrest
BASE_BUILD_TABLES = r09.build_tables
BASE_SHOULD_CLONE = r09.should_clone


def continuous_body_loft(
    owner: bpy.types.Collection,
    name: str,
    controls: list[tuple[float, float, float, float]],
    exponent: float,
    mat: bpy.types.Material,
    ring_segments: int = 64,
) -> bpy.types.Object:
    if "SINGLE_ASYMMETRIC_MONOCOQUE" in name:
        # x, half-y, z-centre, half-z.  The top line is retained from R12;
        # the lower line now forms a 50-85 mm ground-clearance half-egg skirt.
        controls = [
            (-0.535, 0.275, 0.2925, 0.1825),  # bottom 110, top 475 mm
            (-0.495, 0.360, 0.2740, 0.1990),  # body widens before front tyre
            (-0.405, 0.375, 0.2645, 0.2095),  # bottom  55, top 474 mm
            (-0.190, 0.375, 0.2640, 0.2140),  # bottom  50, top 478 mm
            (0.085, 0.375, 0.2640, 0.2140),
            (0.230, 0.375, 0.2615, 0.2065),  # stays outside rear tyre
            (0.315, 0.300, 0.2635, 0.1785),  # bottom  85, top 442 mm
            (0.345, 0.245, 0.2725, 0.1475),  # bottom 125, top 420 mm
        ]
    # Softer than R12's 0.08 plate-like corner, while the lower envelope now
    # supplies the wheel coverage rather than an applied fender.
    return r11.BASE_LONGITUDINAL_LOFT(owner, name, controls, 0.16, mat, ring_segments)


def integrated_arm_loft(
    owner: bpy.types.Collection,
    name: str,
    side: str,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    # x, inner-|y|, outer-|y|, bottom-z, top-z.  The front inner edges close
    # toward the folded A06, while leaving at least 15 mm per side around the
    # 430 mm seat at the occupant entry plane.
    controls = [
        (-0.382, 0.230, 0.354, 0.470, 0.662),
        (-0.358, 0.220, 0.375, 0.435, 0.6723),
        (-0.300, 0.225, 0.375, 0.423, 0.6645),
        (-0.230, 0.230, 0.375, 0.420, 0.6550),
        (-0.185, 0.235, 0.375, 0.420, 0.655),
        (0.145, 0.258, 0.375, 0.427, 0.654),
        (0.225, 0.265, 0.375, 0.432, 0.654),
        (0.262, 0.284, 0.356, 0.468, 0.622),
        (0.290, 0.309, 0.334, 0.515, 0.566),
    ]
    stations = r09.interpolate_controls(controls, 6)
    ring_segments = 64
    exponent = 0.16
    sign = -1.0 if side == "LEFT" else 1.0
    vertices: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []

    for x, inner, outer, bottom, top in stations:
        if side == "LEFT" and -0.358 <= x <= -0.230:
            # Exact underside plane for the +8 degree, 124 mm display.
            top = 0.67226 + (x + 0.358) * ((0.65476 - 0.67226) / 0.128)
        elif side == "RIGHT" and -0.330 <= x <= -0.200:
            # Direct landing plane for the fixed V8 joystick (bottom z=697 mm).
            top = 0.6970

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


def embedded_display_stub(owner: bpy.types.Collection, mat: bpy.types.Material) -> bpy.types.Object:
    # R09's caller performs a union.  This fully internal stub makes that
    # historical call a no-op; the visible support is now the arm itself.
    return BASE_ROUNDED_BOX(
        owner,
        "V11_R13_TEMP_INTERNAL_DISPLAY_UNION_STUB",
        (-0.285, -0.320, 0.585),
        (0.010, 0.010, 0.010),
        0.002,
        mat,
        3,
    )


def rounded_box_without_hmi_plinth(
    owner: bpy.types.Collection,
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    radius: float,
    mat: bpy.types.Material,
    segments: int = 6,
) -> bpy.types.Object:
    if name == "V11_R09_TEMP_RIGHT_FIXED_HMI_ISLAND":
        return BASE_ROUNDED_BOX(
            owner,
            "V11_R13_TEMP_INTERNAL_HMI_UNION_STUB",
            (-0.265, 0.320, 0.585),
            (0.010, 0.010, 0.010),
            0.002,
            mat,
            3,
        )
    return BASE_ROUNDED_BOX(owner, name, location, dimensions, radius, mat, segments)


def create_display(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    display = r09.rounded_prism_xy(
        owner,
        "V11_R13_A05_SINGLE_FLUSH_DISPLAY_124X49X2P5",
        (0.0, 0.0, 0.0),
        0.124,
        0.049,
        0.0025,
        0.006,
        mats["glass"],
        0.0004,
    )
    # Rear underside is flush with the 655 mm arm top; the front rises only
    # by the required 8-degree face angle, avoiding a tall display pedestal.
    display.location = (-0.294, -0.320, 0.66487)
    display.rotation_mode = "XYZ"
    display.rotation_euler.y = math.radians(8.0)
    display["source_occurrence_ids"] = "A05_left_status_display_window"
    display["display_face_mm"] = [124.0, 49.0]
    display["uniform_normal_thickness_mm"] = 2.5
    display["world_y_pitch_deg"] = 8.0
    display["rotation_origin"] = "own geometric centre"
    display["support"] = "single glass layer lands directly on continuous left-arm mother surface"
    display["slope"] = "front high; rear low"
    return display


def build_footrest_all_states(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    if r09.ACTIVE_STATE == "ride":
        return BASE_BUILD_FOOTREST(owner, mats)

    # Same three physical parts, translated +220 mm into the cassette.
    platform = r09.rounded_prism_xy(
        owner,
        "V11_R13_A08_SINGLE_PIECE_TELESCOPIC_FOOTREST_STOWED",
        (-0.385, 0.0, 0.098),
        0.206,
        0.496,
        0.024,
        0.024,
        mats["body"],
        0.0015,
    )
    platform["source_occurrence_ids"] = (
        "A08_footrest_platform_undertray_monocoque,A08_footrest_top_skin,"
        "A08_footrest_support_monocoque_left,A08_footrest_support_monocoque_right"
    )
    platform["motion"] = "same A08 assembly; +220 mm X from Ride-open position"
    platform["default_state"] = "stowed in Follow/Cafe/Focus"
    tread = r09.rounded_prism_xy(
        owner,
        "V11_R13_A08_NATURAL_RUBBER_TREAD_INLAY_STOWED",
        (-0.396, 0.0, 0.1108),
        0.166,
        0.430,
        0.0016,
        0.020,
        mats["control"],
        0.0002,
    )
    tread["source_occurrence_ids"] = "A08_footrest_inset_tread"
    lip = r09.rounded_prism_xy(
        owner,
        "V11_R13_A08_LIMITED_316_LEADING_EDGE_STOWED",
        (-0.484, 0.0, 0.101),
        0.007,
        0.452,
        0.008,
        0.003,
        mats["stainless"],
        0.0005,
    )
    lip["source_occurrence_ids"] = "A08_footrest_perimeter_skin"
    return [platform, tread, lip]


def build_tables_clear_of_integrated_arms(
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    objects = BASE_BUILD_TABLES(owner, mats)
    if r09.ACTIVE_STATE == "cafe":
        for obj in objects:
            if "CAFE_RIGHT_SINGLE_CALM_WALNUT_SURFACE" in obj.name:
                # y=-190..+210 mm: 10 mm inside the closest right-arm face.
                for vertex in obj.data.vertices:
                    vertex.co.y -= 0.045
                obj.data.update()
                obj["deployed_bounds_policy"] = "surface y=-190..+210 mm; at least 10 mm inboard of integrated arm"
                obj["joystick_lateral_clearance_mm"] = 123.0
            elif "RIGHT_HIDDEN_INBOARD_NECK" in obj.name:
                for vertex in obj.data.vertices:
                    vertex.co.y = 0.215 + (vertex.co.y - 0.258) * (30.0 / 26.0)
                obj.data.update()
    elif r09.ACTIVE_STATE == "focus":
        for obj in objects:
            if "FOCUS_LEFT_CONTINUOUS_WALNUT_SURFACE" in obj.name:
                for vertex in obj.data.vertices:
                    vertex.co.y = -0.109 + (vertex.co.y + 0.1315) * (0.101 / 0.1235)
                obj.data.update()
                obj["deployed_bounds_policy"] = "surface y=-210..-8 mm; 16 mm centre reveal"
            elif "FOCUS_RIGHT_CONTINUOUS_WALNUT_SURFACE" in obj.name:
                for vertex in obj.data.vertices:
                    vertex.co.y = 0.109 + (vertex.co.y - 0.1315) * (0.101 / 0.1235)
                obj.data.update()
                obj["deployed_bounds_policy"] = "surface y=+8..+210 mm; 16 mm centre reveal"
                obj["joystick_lateral_clearance_mm"] = 123.0
            elif "LEFT_HIDDEN_INBOARD_NECK" in obj.name:
                for vertex in obj.data.vertices:
                    vertex.co.y = -0.215 + (vertex.co.y + 0.258) * (30.0 / 26.0)
                obj.data.update()
            elif "RIGHT_HIDDEN_INBOARD_NECK" in obj.name:
                for vertex in obj.data.vertices:
                    vertex.co.y = 0.215 + (vertex.co.y - 0.258) * (30.0 / 26.0)
                obj.data.update()
    return objects


def link_reference_and_clean_clone(
    scene: bpy.types.Scene,
    state: str,
    owner: bpy.types.Collection,
    mats: dict[str, bpy.types.Material],
) -> tuple[bpy.types.Collection, list[bpy.types.Object]]:
    reference, clones = BASE_LINK_REFERENCE_AND_CLONE(scene, state, owner, mats)
    for clone in clones:
        occurrence = str(clone.get("wc_occurrence_id", ""))
        if occurrence == "A05_right_joystick":
            clone.data = clone.data.copy()
            r09.clean_mesh(clone, 1.0e-8)
            clone["mesh_cleanup"] = "local render copy only; zero-length/zero-area V8 tessellation removed"
        elif occurrence in {"A05_left_mechanical_emergency_stop", "A05_left_emergency_stop_guard"}:
            # Recreate the V8 Follow external mounting relation on the new
            # 750 mm envelope: outermost y=-377 mm, so overall width stays
            # at the 752 mm hard limit while the control is visible/touchable.
            if occurrence == "A05_left_mechanical_emergency_stop":
                target_y = -0.3712  # 10 mm world-Y depth => outer face -376.2 mm
                red = bpy.data.materials.get("V11_R13_MAT_MECHANICAL_SAFETY_RED")
                if red is None:
                    red = r09.tuned_material(
                        "V11_R13_MAT_MECHANICAL_SAFETY_RED",
                        (0.62, 0.0012, 0.0005, 1.0),
                        0.46,
                        0.0,
                        0.12,
                    )
                r01.assign_object_material(clone, red)
                clone["safety_colour"] = "mechanical red; never neutralised by state"
            else:
                target_y = -0.3722  # 8 mm guard depth => outer face -376.2 mm
            bpy.context.view_layer.update()
            centre_y = sum((clone.matrix_world @ Vector(corner)).y for corner in clone.bound_box) / 8.0
            clone.matrix_world.translation.y += target_y - centre_y
            clone["external_access"] = "left/service side; visible and touchable in all four states"
    return reference, clones


def should_clone_with_emergency_guard(occurrence: str, state: str) -> bool:
    return BASE_SHOULD_CLONE(occurrence, state) or occurrence == "A05_left_emergency_stop_guard"


def _rename_revision(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if "R12" in obj.name:
            obj.name = obj.name.replace("R12", "R13")
        if getattr(obj, "data", None) is not None and "R12" in obj.data.name:
            obj.data.name = obj.data.name.replace("R12", "R13")


def _correct_traceability(objects: list[bpy.types.Object]) -> None:
    exact: tuple[tuple[str, str], ...] = (
        ("SINGLE_ASYMMETRIC_MONOCOQUE", "A01_front_nose_shell,A02_main_side_shell_left,A02_main_side_shell_right,A03_continuous_wheel_belt_shell_left,A03_continuous_wheel_belt_shell_right,A04_open_u_seat_pan_ring,A04_underseat_belly_closeout,A10_rear_service_surround"),
        ("FIXED_LOW_ARM_LEFT", "A05_armrest_table_bay_shell_left"),
        ("FIXED_LOW_ARM_RIGHT", "A05_armrest_table_bay_shell_right"),
        ("LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID", "A05_armrest_touch_lid_left"),
        ("RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID", "A05_armrest_touch_lid_right"),
        ("A04_LEFT_FLUSH_EQUIPMENT_DOOR_SEAM", "A04_upper_equipment_door_left"),
        ("A04_RIGHT_FLUSH_EQUIPMENT_DOOR_SEAM", "A04_upper_equipment_door_right"),
        ("A08_SINGLE_PIECE_TELESCOPIC_FOOTREST", "A08_footrest_platform_undertray_monocoque,A08_footrest_top_skin,A08_footrest_support_monocoque_left,A08_footrest_support_monocoque_right"),
        ("A08_NATURAL_RUBBER_TREAD_INLAY", "A08_footrest_inset_tread"),
        ("A08_LIMITED_316_LEADING_EDGE", "A08_footrest_perimeter_skin"),
        ("A08_FRONT_TELESCOPIC_CASSETTE_SEAM", "A08_footrest_root_monocoque"),
    )
    for obj in objects:
        for token, ids in exact:
            if token in obj.name:
                obj["source_occurrence_ids"] = ids
                break


def _cut_real_footrest_cassette(body: bpy.types.Object, owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> None:
    if r09.ACTIVE_STATE == "ride":
        centre_x = -0.493
        length_x = 0.450  # open sweep from x=-718 to -268 mm
    else:
        centre_x = -0.3875
        length_x = 0.245  # closed skin remains; internal void x=-510..-265 mm
    cutter = BASE_ROUNDED_BOX(
        owner,
        "V11_R13_TEMP_A08_REAL_CASSETTE_VOID",
        (centre_x, 0.0, 0.103),
        (length_x, 0.506, 0.038),
        0.012,
        mats["seam"],
        6,
    )
    r09.boolean(body, cutter, "DIFFERENCE", "V11_R13_A08_REAL_CASSETTE_VOID")
    body["a08_real_cassette_void_mm"] = [length_x * 1000.0, 506.0, 38.0]
    body["a08_stow_translation_x_mm"] = 220.0
    body["a08_cassette_state"] = "front open in Ride" if r09.ACTIVE_STATE == "ride" else "internal void behind closed mother-surface skin"


def build_lower_and_arms(owner: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = BASE_R12_BUILD_LOWER(owner, mats)
    _rename_revision(objects)
    body = next((obj for obj in objects if "SINGLE_ASYMMETRIC_MONOCOQUE" in obj.name), None)
    if body is None:
        raise RuntimeError("R13 monocoque missing")
    _cut_real_footrest_cassette(body, owner, mats)
    body["cross_section_signed_power"] = 0.16
    body["wheel_wrap_policy_r13"] = "one continuous lower mother surface; no fender, side ribbon or cover object"
    body["minimum_nominal_ground_clearance_mm"] = 50.0

    for obj in objects:
        if "FIXED_LOW_ARM_LEFT" in obj.name:
            obj["maximum_main_top_mm"] = 699.0
            obj["hmi_integration"] = "display lands directly on arm mother surface; no separate saddle"
        elif "FIXED_LOW_ARM_RIGHT" in obj.name:
            obj["maximum_main_top_mm"] = 697.0
            obj["hmi_integration"] = "joystick lands directly on arm mother surface; no separate plinth"
        if "A04_" in obj.name and "EQUIPMENT_DOOR_SEAM" in obj.name and obj.type == "CURVE":
            obj.data.bevel_depth = 0.0005  # 1.0 mm visible nominal seam
            obj.data.bevel_resolution = 4

    _correct_traceability(objects)
    return objects


def build_a06_a07(owner: bpy.types.Collection, state: str, mats: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    objects = BASE_R12_BUILD_A06_A07(owner, state, mats)
    _rename_revision(objects)
    for obj in objects:
        if "A06_ICONIC_FRONT_TRAPEZOID" in obj.name:
            obj["source_occurrence_ids"] = "A06_backrest_weather_shell"
        elif "A06_NATURAL_LEATHER_CONTACT" in obj.name:
            obj["source_occurrence_ids"] = "A06_backrest_contact_panel"
        elif "A07_ORIGINAL_EXPOSED_TRAPEZOID_BLADE" in obj.name:
            obj["source_occurrence_ids"] = "A07_mast_fixed_outer_sleeve,A07_mast_moving_inner_sleeve"
        elif "A07_COMPACT_SENSOR_CROWN" in obj.name:
            obj["source_occurrence_ids"] = "A07_sensor_beam_shell"
        elif "A07_SENSOR_WINDOW" in obj.name:
            obj["source_occurrence_ids"] = "A07_sensor_beam_smoked_window"
    return objects


def main() -> None:
    r12.REVISION = REVISION
    r12.continuous_body_loft = continuous_body_loft
    r12.create_display = create_display
    r12.build_lower_and_arms = build_lower_and_arms
    r12.build_a06_a07 = build_a06_a07
    r10.arm_loft = integrated_arm_loft
    r09.sloped_support_wedge = embedded_display_stub
    r09.build_footrest = build_footrest_all_states
    r09.build_tables = build_tables_clear_of_integrated_arms
    r09.should_clone = should_clone_with_emergency_guard
    r01.rounded_box = rounded_box_without_hmi_plinth
    r01.link_reference_and_clone = link_reference_and_clean_clone
    r12.main()

    state = r11.ACTIVE_STATE
    output = state_blend_path(state, REVISION)
    report_path = V11_ROOT / "qa" / REVISION / f"v11_{state}_{REVISION}_build_report.json"
    payload = read_json(report_path)
    payload["status"] = "BUILT_UNVALIDATED"
    payload["revision"] = REVISION
    payload["blend_sha256"] = sha256(output)
    payload["measured_product_bounds_after_save"] = r03.evaluated_product_bounds()
    payload["r13_form_changes"] = [
        "single 124 x 49 x 2.5 mm display now lands on a slope sculpted into the left arm mother surface",
        "fixed joystick lands on the right arm mother surface; the separate HMI plinth is removed",
        "lower half-egg monocoque extends to 50-85 mm nominal ground clearance for real wheel wrapping",
        "physical 506 x 34 mm A08 cassette void replaces the drawn-only stow seam",
        "same A08 platform, tread and leading edge remain modelled inside Follow/Cafe/Focus",
        "V8 joystick render clone is locally topology-cleaned without changing its exterior form",
        "generated surfaces now cite real V8 occurrence IDs",
    ]
    payload["known_limits"] = [
        "Blender visual/layout decision model; production Class-A BRep, structure, sealing and equipment package remain STEP gates",
        "hand envelope, footrest rail/lock strength, tyre debris clearance and 300 mm equipment-door rail require full-scale/STEP validation",
    ]
    atomic_write_json(report_path, payload)
    print("V11_VISUAL_R13_BUILT_UNVALIDATED", state, output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
