from __future__ import annotations

import base64
import atexit
import csv
import json
import math
import sys
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parameters import P  # noqa: E402
from engineering import analyze as engineering_analyze  # noqa: E402
from mobility import analyze as mobility_analyze, write_access_csv  # noqa: E402
from power_thermal import analyze as power_thermal_analyze  # noqa: E402
from readiness import analyze_and_write as readiness_analyze_and_write  # noqa: E402
from release_manifest import write_release_manifest  # noqa: E402
from artifact_publish import publish_staged_release  # noqa: E402
from footrest_state import (  # noqa: E402
    CONTRACT_VERSION as FOOTREST_CONTRACT_VERSION,
    FootrestPose,
    resolve_footrest_pose,
)


ROOT = Path(__file__).resolve().parents[1]
# E6-DFR3 in ``build/`` is a preserved controlled input.  The corrected source
# builder publishes only to a versioned sibling so an ordinary build command
# cannot silently overwrite the trace baseline used by the V8 study.
PUBLISHED_BUILD = ROOT / "build_e6_dfr4"
STAGING_ROOT = ROOT / ".build-staging-e6-dfr4"
BUILD = PUBLISHED_BUILD
PARTS_DIR = BUILD / "parts"
_BUILD_TERMINAL = False
_CURRENT_RUN_ID = ""


def _bind_output(build_dir: Path) -> None:
    global BUILD, PARTS_DIR
    BUILD = build_dir
    PARTS_DIR = BUILD / "parts"


def _write_build_status(status: str, **details) -> None:
    payload = {
        "schema_version": 1,
        "revision": "E6-DFR4",
        "run_id": _CURRENT_RUN_ID,
        "status": status,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "artifact generation status only; this is not a product release decision",
        **details,
    }
    (BUILD / "build_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _mark_interrupted_build() -> None:
    if not _BUILD_TERMINAL and BUILD.exists():
        _write_build_status(
            "INTERRUPTED_OR_FAILED",
            reason="The build process ended before a complete, hash-bound manifest was written.",
        )


@dataclass
class Part:
    name: str
    shape: cq.Workplane
    material: str
    process: str
    density_g_cm3: float
    color: tuple[float, float, float, float]
    configuration: str = "both"
    quantity: int = 1
    mass_override_kg: float | None = None
    vendor: str = ""
    vendor_part_number: str = ""
    source_url: str = ""
    maturity: str = "custom"
    physical_occurrence_id: str = ""
    option_code: str = "BASE"
    include_in_ebom: bool = True
    definition_revision: str = "E6R2-A"
    identity_basis: str = "LEGACY_NAME"
    mechanism_pose: str = ""
    mechanism_contract: str = ""

    @property
    def solid(self):
        return self.shape.val()

    @property
    def volume_mm3(self) -> float:
        return float(self.solid.Volume())

    @property
    def mass_kg(self) -> float:
        if self.mass_override_kg is not None:
            return self.mass_override_kg
        return self.volume_mm3 * self.density_g_cm3 / 1_000_000.0

    @property
    def total_mass_kg(self) -> float:
        return self.mass_kg * self.quantity


ALUMINUM = ("6061-T6 aluminium", "Extrusion / CNC / weld", 2.70, (0.63, 0.66, 0.69, 1.0))
SHEET_AL = ("5052-H32 aluminium", "Fold / weld / powder coat", 2.68, (0.24, 0.26, 0.29, 1.0))
STEEL = ("17-4PH stainless steel", "Turn / grind", 7.75, (0.78, 0.79, 0.80, 1.0))
PCABS = ("PC-ABS", "Injection mould / thermoform", 1.14, (0.18, 0.19, 0.21, 1.0))
RUBBER = ("TPE tyre", "Mould", 1.10, (0.04, 0.045, 0.05, 1.0))
FOAM = ("Upholstery envelope", "Foam / leather trim", 0.18, (0.38, 0.22, 0.12, 1.0))
FABRIC = ("PU-coated polyester", "Cut / sew / weld", 1.20, (0.07, 0.075, 0.085, 0.88))
SANDWICH = ("Aluminium honeycomb sandwich", "Bond / edge-close / veneer", 0.75, (0.46, 0.29, 0.16, 1.0))
AL7075 = ("7075-T6 aluminium", "Extrusion / CNC / hard anodize", 2.81, (0.69, 0.70, 0.72, 1.0))
POM = ("POM bearing grade", "Machine / mould", 1.41, (0.86, 0.84, 0.76, 1.0))
ELECTRICAL = ("Purchased electrical module", "COTS / harness", 0.0, (0.18, 0.38, 0.52, 1.0))
PURCHASED = ("Purchased component", "COTS", 0.0, (0.30, 0.32, 0.34, 1.0))
HUMAN = ("95th-percentile clothed keep-out", "Validation envelope only", 0.0, (0.95, 0.47, 0.20, 0.42))
EQUIPMENT = ("Equipment keep-out", "Validation envelope only", 0.0, (0.16, 0.55, 0.86, 0.42))
TPE_BOOT = ("TPE protective bellows", "Mould / clip-fit", 1.05, (0.07, 0.08, 0.09, 1.0))
SAFETY_CONTROL = ("Safety-rated control envelope", "COTS / guarded mount", 0.0, (0.88, 0.12, 0.10, 1.0))
SMOKED_SENSOR = ("IR-transparent smoked polycarbonate", "Mould / bonded window", 1.20, (0.035, 0.045, 0.050, 0.94))
STATUS_LIGHT = ("Diffused low-luminance status optic", "Mould / light pipe", 1.05, (0.88, 0.68, 0.28, 0.72))
RADOME_WINDOW = ("RF-transparent PC-ABS radome", "Mould / bonded insert", 1.12, (0.14, 0.12, 0.10, 0.96))
ACOUSTIC_MEMBRANE = ("Hydrophobic acoustic membrane", "Bond / laser-perforated carrier", 0.90, (0.07, 0.075, 0.08, 0.96))


def part(
    name: str,
    shape: cq.Workplane,
    spec,
    *,
    configuration="both",
    quantity=1,
    mass_override_kg=None,
    vendor="",
    vendor_part_number="",
    source_url="",
    maturity="custom",
    physical_occurrence_id=None,
    option_code="BASE",
    include_in_ebom=True,
    definition_revision="E6R2-A",
    mechanism_pose="",
    mechanism_contract="",
) -> Part:
    material, process, density, color = spec
    return Part(
        name=name,
        shape=shape,
        material=material,
        process=process,
        density_g_cm3=density,
        color=color,
        configuration=configuration,
        quantity=quantity,
        mass_override_kg=mass_override_kg,
        vendor=vendor,
        vendor_part_number=vendor_part_number,
        source_url=source_url,
        maturity=maturity,
        physical_occurrence_id=physical_occurrence_id or name,
        option_code=option_code,
        include_in_ebom=include_in_ebom,
        definition_revision=definition_revision,
        identity_basis="CONTROLLED_ID" if physical_occurrence_id else "LEGACY_NAME",
        mechanism_pose=mechanism_pose,
        mechanism_contract=mechanism_contract,
    )


def rounded_box(length: float, width: float, height: float, radius: float) -> cq.Workplane:
    radius = min(radius, length / 2 - 0.01, width / 2 - 0.01)
    return cq.Workplane("XY").box(length, width, height).edges("|Z").fillet(radius)


def hollow_box(length: float, width: float, height: float, wall: float) -> cq.Workplane:
    outer = cq.Workplane("XY").box(length, width, height)
    # Open-ended rectangular tube.  The previous helper removed the X walls
    # and retained Z end caps, which was the opposite of the telescopic-mast
    # interface and caused false material occupancy along the sliding stroke.
    inner = cq.Workplane("XY").box(
        length - 2 * wall,
        width - 2 * wall,
        height + 2,
    )
    return outer.cut(inner)


def rounded_shell(length: float, width: float, height: float, radius: float, wall: float) -> cq.Workplane:
    outer = rounded_box(length, width, height, radius)
    inner = rounded_box(
        length - 2 * wall,
        width - 2 * wall,
        height - 2 * wall,
        max(radius - wall, 1.0),
    )
    return outer.cut(inner)


def tube_x(length: float, side: float, wall: float) -> cq.Workplane:
    outer = cq.Workplane("YZ").rect(side, side).extrude(length / 2, both=True)
    inner = cq.Workplane("YZ").rect(side - 2 * wall, side - 2 * wall).extrude(length / 2 + 1, both=True)
    return outer.cut(inner)


def tube_y(length: float, side: float, wall: float) -> cq.Workplane:
    outer = cq.Workplane("XZ").rect(side, side).extrude(length / 2, both=True)
    inner = cq.Workplane("XZ").rect(side - 2 * wall, side - 2 * wall).extrude(length / 2 + 1, both=True)
    return outer.cut(inner)


def rotate_about_y(shape: cq.Workplane, origin: tuple[float, float, float], angle: float) -> cq.Workplane:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox, oy + 1, oz), angle)


def rotate_about_x(shape: cq.Workplane, origin: tuple[float, float, float], angle: float) -> cq.Workplane:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox + 1, oy, oz), angle)


def rotate_about_z(shape: cq.Workplane, origin: tuple[float, float, float], angle: float) -> cq.Workplane:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox, oy, oz + 1), angle)


def polygon_prism(points: list[tuple[float, float]], height: float, z0: float) -> cq.Workplane:
    return cq.Workplane("XY").polyline(points).close().extrude(height).translate((0, 0, z0))


def tapered_back(width_bottom: float, width_top: float, height: float, thickness: float) -> cq.Workplane:
    section = (
        cq.Workplane("YZ")
        .polyline(
            [
                (-width_bottom / 2, 0),
                (width_bottom / 2, 0),
                (width_top / 2, height),
                (-width_top / 2, height),
            ]
        )
        .close()
        .extrude(thickness / 2, both=True)
        .translate((P.back_hinge_x + thickness / 2, 0, P.back_hinge_z))
    )
    return rotate_about_y(section, (P.back_hinge_x, 0, P.back_hinge_z), P.back_rake_deg)


def tapered_back_frame() -> cq.Workplane:
    thickness = 40.0
    outer = tapered_back(P.back_width, 300.0, P.back_height, thickness)
    border = 40.0
    inner = (
        cq.Workplane("YZ")
        .polyline(
            [
                (-(P.back_width - 2 * border) / 2, border),
                ((P.back_width - 2 * border) / 2, border),
                ((300.0 - 2 * border) / 2, P.back_height - border),
                (-(300.0 - 2 * border) / 2, P.back_height - border),
            ]
        )
        .close()
        .extrude(thickness / 2 + 1, both=True)
        .translate((P.back_hinge_x + thickness / 2, 0, P.back_hinge_z))
    )
    inner = rotate_about_y(inner, (P.back_hinge_x, 0, P.back_hinge_z), P.back_rake_deg)
    return outer.cut(inner)


def armrest_outline(side: int, inset: float = 0.0) -> list[tuple[float, float]]:
    pts = [
        (P.armrest_x_min + inset, P.armrest_inner_y + inset),
        (P.armrest_x_chamfer_start - inset, P.armrest_inner_y + inset),
        (P.armrest_x_max - inset, P.armrest_chamfer_y + inset),
        (P.armrest_x_max - inset, P.armrest_outer_y - inset),
        (P.armrest_x_min + inset, P.armrest_outer_y - inset),
    ]
    return [(x, side * y) for x, y in pts]


def armrest_shell_segment(side: int, z_min: float, z_max: float) -> cq.Workplane:
    h = z_max - z_min
    outer = polygon_prism(armrest_outline(side), h, z_min)
    inner = polygon_prism(
        armrest_outline(side, P.armrest_wall),
        h - P.armrest_wall + 2,
        z_min + P.armrest_wall,
    )
    return outer.cut(inner)


def armrest_shell(side: int) -> cq.Workplane:
    seat_top = P.seat_z + P.seat_height / 2
    return armrest_shell_segment(side, seat_top + 2.0, P.armrest_top_z - 4.0)


def armrest_base_shell(side: int) -> cq.Workplane:
    seat_top = P.seat_z + P.seat_height / 2
    return armrest_shell_segment(side, P.armrest_bottom_z, seat_top - 2.0)


def wheel_parts() -> list[Part]:
    result: list[Part] = []
    tyre_r = P.wheel_diameter / 2
    hub_r = 48.0
    for axle in ("front", "rear"):
        x = P.wheel_x_front if axle == "front" else P.wheel_x_rear
        for side in (-1, 1):
            y = side * P.wheel_y
            tag = f"{axle}_{'right' if side > 0 else 'left'}"
            tyre = (
                cq.Workplane("XZ")
                .circle(tyre_r)
                .circle(hub_r + 5)
                .extrude(P.wheel_width / 2, both=True)
                .translate((x, y, P.wheel_center_z))
            )
            hub = (
                cq.Workplane("XZ")
                .circle(hub_r)
                .circle(P.axle_diameter / 2)
                .extrude(P.wheel_width / 2 + 1, both=True)
                .translate((x, y, P.wheel_center_z))
            )
            axle_length = P.wheel_y + P.wheel_width / 2 - P.frame_width / 2
            axle_center_y = side * (P.frame_width / 2 + axle_length / 2)
            axle_shape = (
                cq.Workplane("XZ")
                .circle(P.axle_diameter / 2)
                .extrude(axle_length / 2, both=True)
                .translate((x, axle_center_y, P.wheel_center_z))
            )
            result.extend(
                [
                    part(f"tyre_{tag}", tyre, RUBBER),
                    part(f"hub_{tag}", hub, ALUMINUM),
                    part(f"axle_{tag}", axle_shape, STEEL),
                ]
            )
    # A central rocker on each side preserves four-wheel ground contact over
    # diagonal thresholds and prevents the rigid chassis from becoming the
    # suspension. Hub motor torque reactions close through the rocker, while
    # replaceable elastomer stops limit articulation to the validated range.
    rocker_length = P.wheel_x_rear - P.wheel_x_front
    rocker_x = (P.wheel_x_front + P.wheel_x_rear) / 2.0
    # The visual concept used a 36 mm square rocker in an 18 mm lateral gap,
    # which necessarily occupied the tyre.  The production envelope is a deep
    # 7075 plate/link: 50 mm in Z for bending stiffness and only 10 mm in Y.
    rocker_y = P.lower_body_width / 2.0 + 9.0
    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        rocker = rounded_box(
            rocker_length,
            P.rocker_lateral_thickness,
            P.rocker_section,
            4,
        ).translate(
            (rocker_x, side * rocker_y, P.wheel_center_z)
        )
        result.append(part(f"suspension_rocker_{side_name}", rocker, AL7075))
        pivot = (
            cq.Workplane("XZ")
            .circle(18)
            .circle(10)
            .extrude(P.rocker_lateral_thickness / 2, both=True)
            .translate((rocker_x, side * rocker_y, P.wheel_center_z))
        )
        result.append(part(f"suspension_centre_pivot_{side_name}", pivot, STEEL))
        for x_offset in (-42.0, 42.0):
            stop = rounded_box(24, P.rocker_lateral_thickness, 18, 4).translate(
                (rocker_x + x_offset, side * rocker_y, P.wheel_center_z + 36)
            )
            result.append(part(f"suspension_elastomer_stop_{side_name}_{int(x_offset):+d}", stop, RUBBER))
        wheel_gap = rocker_length - P.wheel_diameter - 10.0
        fairing = rounded_box(wheel_gap, 12, P.rocker_fairing_height, 6).translate(
            (rocker_x, side * (P.body_width / 2 - 6), P.wheel_center_z)
        )
        result.append(part(f"wheel_arch_side_fairing_{side_name}", fairing, PCABS))
    return result


def chassis_parts() -> list[Part]:
    z = P.frame_z
    x0 = P.body_x
    parts = [
        part(
            "chassis_rail_left",
            tube_x(P.frame_length, P.frame_tube, P.frame_wall).translate((x0, -P.frame_width / 2, z)),
            ALUMINUM,
        ),
        part(
            "chassis_rail_right",
            tube_x(P.frame_length, P.frame_tube, P.frame_wall).translate((x0, P.frame_width / 2, z)),
            ALUMINUM,
        ),
    ]
    # Crossmembers flank the structural battery cassette instead of passing through it.
    for i, x in enumerate((-390.0, -220.0, 210.0)):
        parts.append(
            part(
                f"chassis_crossmember_{i + 1}",
                tube_y(P.frame_width, P.frame_tube, P.frame_wall).translate((x, 0, z)),
                ALUMINUM,
            )
        )
    return parts


def internal_module_parts() -> list[Part]:
    modules = [
        ("battery_lfp_16s30ah_1p536kwh", (360, 440, 90), (0, 0, 145), 20.5, "16s-30ah-lfp-pack-envelope"),
        ("compute_core_cartridge", (94, 140, 130), (268, -110, 225), 3.4, "compute-cartridge"),
        ("encrypted_data_vault", (94, 140, 55), (268, -110, 327.5), 0.6, "encrypted-removable-data-vault"),
        ("communications_5g_wifi_uwb_module", (94, 180, 140), (268, 135, 240), 1.6, "5g-wifi6e-uwb-module-envelope"),
        ("power_distribution_unit", (94, 440, 40), (268, 0, 390), 3.8, "48v-150a-dual-bus-pdu-envelope"),
        ("drive_imu_controller", (160, 140, 28), (10, 0, 225), 2.0, "independent-safety-motion-controller-envelope"),
        ("safety_backup_battery_24v60wh", (100, 100, 45), (150, 0, 272), 1.2, "24v-60wh-safety-rail-envelope"),
    ]
    result = []
    for name, dims, pos, mass, vendor_pn in modules:
        shape = cq.Workplane("XY").box(*dims).translate(pos)
        result.append(
            part(
                name,
                shape,
                ELECTRICAL,
                mass_override_kg=mass,
                vendor_part_number=vendor_pn,
                maturity="interface-envelope",
            )
        )
    # Battery faults are directed away from the occupant: a structural cassette,
    # rear pressure vent and a continuous under-seat fire barrier are mandatory
    # interfaces, not cosmetic covers.
    cassette = rounded_shell(380, 460, 110, 18, 3.0).translate((0, 0, 145))
    result.append(part("battery_safety_cassette", cassette, SHEET_AL))
    vent = cq.Workplane("XY").box(130, 42, 42).translate((265, 0, 178))
    result.append(part("battery_pressure_vent_duct", vent, SHEET_AL, mass_override_kg=0.45))
    firewall = cq.Workplane("XY").box(700, 520, 3).translate((-65, 0, 418.5))
    for side in (-1, 1):
        handle_passage = (
            cq.Workplane("XY")
            .circle(P.obstacle_handle_outer_od / 2 + 3.0)
            .extrude(7)
            .translate((P.obstacle_handle_x, side * P.obstacle_handle_tube_y, 416.0))
        )
        firewall = firewall.cut(handle_passage)
    result.append(part("occupant_energy_firewall", firewall, SHEET_AL))
    for x in (-150.0, 170.0):
        sensor = cq.Workplane("XY").box(28, 28, 10).translate((x, 0, 202))
        result.append(
            part(
                f"battery_compartment_temperature_sensor_{int(x)}",
                sensor,
                ELECTRICAL,
                mass_override_kg=0.04,
                vendor_part_number="dual-channel-temperature-sensor-envelope",
                maturity="interface-envelope",
            )
        )
    return result


def v37_follow_sensor_parts(configuration: str) -> list[Part]:
    """Restore the original v37 follow-perception layout as real CAD envelopes.

    The source model explicitly keeps every navigation-critical sensor at base
    level so the folded product can still follow its owner.  Coordinates below
    preserve that architecture while moving the side windows to the current E6
    skin datums.  They are packaging interfaces, not a claim that the selected
    devices already constitute a certified protective system.
    """
    result: list[Part] = []

    # X-Ray boxes in v37 are packaging volumes.  E6 models the internal module
    # and its 2-3 mm optical window separately so the BOM and final CMF cannot
    # mistake a large translucent block for a production sensor aperture.
    front_optical = [
        ("front_tof_left", (24, 120, 30), (-378, -80, 250), (3, 52, 24), (-391.5, -80, 250), "short-range-tof-module-envelope"),
        ("front_tof_right", (24, 120, 30), (-378, 80, 250), (3, 52, 24), (-391.5, 80, 250), "short-range-tof-module-envelope"),
        ("leg_scanner", (24, 90, 30), (-378, 0, 315), (3, 78, 24), (-391.5, 0, 315), "protective-field-scanner-interface-envelope"),
        ("rear_tof", (18, 60, 30), (311, 0, 133), (3, 50, 22), (321.5, 0, 133), "short-range-tof-module-envelope"),
    ]
    for name, module_dims, module_pos, window_dims, window_pos, interface_id in front_optical:
        result.extend(
            [
                part(
                    f"follow_{name}_module",
                    rounded_box(*module_dims, 4).translate(module_pos),
                    PURCHASED,
                    configuration=configuration,
                    mass_override_kg=0.06,
                    vendor_part_number=interface_id,
                    maturity="supplier-selection-gate",
                ),
                part(
                    f"follow_{name}_window",
                    rounded_box(*window_dims, 3).translate(window_pos),
                    SMOKED_SENSOR,
                    configuration=configuration,
                    mass_override_kg=0.01,
                    vendor_part_number="qualified-ir-window-and-gasket",
                    maturity="material-validation-gate",
                ),
            ]
        )

    # Four side ultrasonics remain behind the wheel-arch liner, raised above
    # the 250 mm tyre and rocker sweep.  Only a sealed transducer face is
    # exposed; ultrasound is never sent through a continuous cosmetic window.
    for x_name, x in (("front", -445.0), ("rear", 295.0)):
        for side_name, side in (("left", -1), ("right", 1)):
            module_y = side * (P.lower_body_width / 2 - 15.0)
            face_y = side * (P.lower_body_width / 2 + 1.5)
            face = (
                cq.Workplane("XZ")
                .circle(7.0)
                .extrude(3.0, both=True)
                .translate((x, face_y, 320))
            )
            result.extend(
                [
                    part(
                        f"follow_side_ultrasonic_module_{x_name}_{side_name}",
                        rounded_box(30, 24, 30, 6).translate((x, module_y, 320)),
                        PURCHASED,
                        configuration=configuration,
                        mass_override_kg=0.04,
                        vendor_part_number="sealed-ultrasonic-transducer-envelope",
                        maturity="supplier-selection-gate",
                    ),
                    part(
                        f"follow_side_ultrasonic_face_{x_name}_{side_name}",
                        face,
                        SMOKED_SENSOR,
                        configuration=configuration,
                        mass_override_kg=0.01,
                        vendor_part_number="sealed-transducer-face-no-cosmetic-cover",
                        maturity="interface-envelope",
                    ),
                ]
            )

    # UWB identity/ranging: DWM3001C modules sit behind two side RF inserts and
    # one rear service-door radome.  The 120 mm inlay language comes from v37.
    for side_name, side in (("left", -1), ("right", 1)):
        result.extend(
            [
                part(
                    f"follow_uwb_side_module_{side_name}",
                    rounded_box(27, 8, 20, 4).translate(
                        (-75, side * (P.body_width / 2 - 18.0), 400)
                    ),
                    ELECTRICAL,
                    configuration=configuration,
                    mass_override_kg=0.012,
                    vendor="Qorvo",
                    vendor_part_number="DWM3001C",
                    source_url="https://www.qorvo.com/products/p/DWM3001C",
                    maturity="candidate-cots",
                ),
                part(
                    f"follow_uwb_side_radome_{side_name}",
                    rounded_box(120, 4, 20, 4).translate(
                        (-75, side * (P.body_width / 2 - 2.0), 400)
                    ),
                    RADOME_WINDOW,
                    configuration=configuration,
                    mass_override_kg=0.04,
                    vendor_part_number="rf-transparent-cmf-insert",
                    maturity="material-validation-gate",
                ),
            ]
        )
    result.extend(
        [
            part(
                "follow_uwb_rear_module",
                rounded_box(27, 20, 8, 4).translate((305, 0, 270)),
                ELECTRICAL,
                configuration=configuration,
                mass_override_kg=0.012,
                vendor="Qorvo",
                vendor_part_number="DWM3001C",
                source_url="https://www.qorvo.com/products/p/DWM3001C",
                maturity="candidate-cots",
            ),
            part(
                "follow_uwb_rear_radome",
                rounded_box(3, 80, 24, 5).translate((328.5, 0, 270)),
                RADOME_WINDOW,
                configuration=configuration,
                mass_override_kg=0.03,
                vendor_part_number="rear-service-door-rf-radome",
                maturity="material-validation-gate",
            ),
        ]
    )

    # v37 draws two long X-Ray bars but labels four microphones: E6 resolves
    # that as two microphones per side behind four hydrophobic acoustic slots.
    for side_name, side in (("left", -1), ("right", 1)):
        result.append(
            part(
                f"follow_voice_mic_strip_{side_name}",
                rounded_box(290, 10, 14, 4).translate(
                    (-50, side * (P.lower_body_width / 2 - 8.0), 233)
                ),
                ELECTRICAL,
                configuration=configuration,
                mass_override_kg=0.08,
                vendor_part_number="two-microphone-side-array-envelope",
                maturity="interface-envelope",
            )
        )
        for aperture_index, x in enumerate((-120.0, 20.0), 1):
            result.append(
                part(
                    f"follow_voice_acoustic_slot_{side_name}_{aperture_index}",
                    rounded_box(70, 3, 8, 3).translate(
                        (x, side * (P.lower_body_width / 2 + 1.5), 233)
                    ),
                    ACOUSTIC_MEMBRANE,
                    configuration=configuration,
                    mass_override_kg=0.003,
                    vendor_part_number="ip-rated-acoustic-membrane-envelope",
                    maturity="material-validation-gate",
                )
            )

    # Downward modules are recessed above the 95 mm chassis protection plane;
    # only the small optical apertures face the ground.
    for x_name, x in (("front", -425.0), ("rear", 280.0)):
        for side_name, side in (("left", -1), ("right", 1)):
            window = (
                cq.Workplane("XY")
                .circle(8.0)
                .extrude(3.0)
                .translate((x, side * 140.0, 96.0))
            )
            result.extend(
                [
                    part(
                        f"follow_cliff_ir_module_{x_name}_{side_name}",
                        rounded_box(30, 40, 12, 4).translate((x, side * 140.0, 105)),
                        PURCHASED,
                        configuration=configuration,
                        mass_override_kg=0.03,
                        vendor_part_number="downward-cliff-tof-ir-envelope",
                        maturity="supplier-selection-gate",
                    ),
                    part(
                        f"follow_cliff_ir_window_{x_name}_{side_name}",
                        window,
                        SMOKED_SENSOR,
                        configuration=configuration,
                        mass_override_kg=0.005,
                        vendor_part_number="recessed-downward-ir-window",
                        maturity="material-validation-gate",
                    ),
                ]
            )

    result.append(
        part(
            "follow_front_tactile_bumper_membrane",
            rounded_box(8, 500, 20, 4).translate((-471, 0, 160)),
            TPE_BOOT,
            configuration=configuration,
            mass_override_kg=0.18,
            vendor_part_number="dual-channel-pressure-bumper-envelope",
            maturity="supplier-selection-gate",
        )
    )

    for side_name, side in (("left", -1), ("right", 1)):
        antenna = rounded_box(10, 8, 260, 3).translate((150, side * 180.0, 800))
        if configuration in ("stowed", "follow", "obstacle"):
            antenna = rotate_about_y(
                antenna,
                (P.back_hinge_x, 0, P.back_hinge_z),
                -95.0,
            )
        result.append(
            part(
                f"follow_hidden_backrest_antenna_{side_name}",
                antenna,
                ELECTRICAL,
                configuration=configuration,
                mass_override_kg=0.05,
                vendor_part_number="sub6-wifi-uwb-flex-antenna-envelope",
                maturity="interface-envelope",
            )
        )
    return result


def user_control_and_service_parts(configuration: str) -> list[Part]:
    """P0 HMI, v37 armrest accessories and rear service interfaces.

    The right armrest carries the removable drive pod, joystick and authorization
    key.  The left armrest carries the status display and Qi tray.  The emergency
    stop remains a separate mechanical channel.  Rear service interfaces are
    guarded and sit outside the cosmetic shell so production access is not routed
    through the occupant compartment.
    """
    result: list[Part] = []
    if configuration in ("stowed", "follow", "obstacle", "cafe"):
        # Closed travel/follow states store the removable pod inside the
        # personal bay. Café also parks and removes drive authority before the
        # right-hand table turns across the occupant; the pod cannot become a
        # wrist obstruction or an accidental command.
        pod_position = (-100, -200, 252)
    else:
        pod_position = (-250, P.armrest_hmi_y, P.armrest_top_z + 10)
    pod = rounded_box(110, 52, 18, 8).translate(pod_position)
    if configuration == "transfer":
        transfer_pivot = (
            P.armrest_x_max + 70.0,
            P.armrest_outer_y - 10.0,
            P.seat_z + P.seat_height / 2,
        )
        pod = rotate_about_z(pod, transfer_pivot, -100.0)
    result.append(
        part(
            "hmi_drive_control_pod_right",
            pod,
            ELECTRICAL,
            mass_override_kg=0.42,
            vendor_part_number="right-armrest-removable-drive-pod-envelope",
            maturity="interface-envelope",
            physical_occurrence_id="WC-HMI-RIGHT-DRIVE-POD",
        )
    )
    joystick = (
        cq.Workplane("XY")
        .circle(10)
        .extrude(28)
        .translate((pod_position[0] - 18, pod_position[1], pod_position[2] + 9))
    )
    authorize_key = (
        cq.Workplane("XY")
        .circle(13)
        .extrude(8)
        .translate((pod_position[0] + 34, pod_position[1], pod_position[2] + 9))
    )
    if configuration == "transfer":
        joystick = rotate_about_z(joystick, transfer_pivot, -100.0)
        authorize_key = rotate_about_z(authorize_key, transfer_pivot, -100.0)
    result.append(
        part(
            "hmi_joystick_right",
            joystick,
            SAFETY_CONTROL,
            mass_override_kg=0.12,
            vendor_part_number="spring-return-proportional-joystick-envelope",
            maturity="supplier-selection-gate",
            physical_occurrence_id="WC-HMI-RIGHT-JOYSTICK",
        )
    )
    result.append(
        part(
            "hmi_drive_authorization_key_right",
            authorize_key,
            SAFETY_CONTROL,
            mass_override_kg=0.06,
            vendor_part_number="two-action-drive-authorization-key-envelope",
            maturity="supplier-selection-gate",
            physical_occurrence_id="WC-HMI-RIGHT-AUTHORIZATION-KEY",
        )
    )

    # v37 left-armrest recessed tray: a pitched status screen at the front and
    # a Qi2 charging target at the rear.  The tray remains below the removable
    # joystick height so transport can meet the 700 mm envelope with the pod
    # stored in the equipment drawer.
    tray_z = P.armrest_top_z + 3.0
    tray = rounded_box(286, 54, 6, 8).translate((-225, -P.armrest_hmi_y, tray_z))
    display_center = (-294, -P.armrest_hmi_y, P.armrest_top_z - 0.5)
    display = rounded_box(
        P.armrest_display_length,
        P.armrest_display_width,
        6,
        5,
    ).translate(display_center)
    display = rotate_about_y(
        display,
        display_center,
        -P.armrest_display_pitch_deg,
    )
    qi_coil = (
        cq.Workplane("XY")
        .circle(P.armrest_qi_coil_od / 2)
        .circle(P.armrest_qi_coil_od / 2 - 4)
        .extrude(2)
        .translate((-136, -P.armrest_hmi_y, tray_z + 3.0))
    )
    qi_module = rounded_box(68, 48, 8, 5).translate(
        (-136, -P.armrest_hmi_y, P.armrest_top_z - 6.0)
    )
    qi_sensor = (
        cq.Workplane("XY")
        .circle(4.5)
        .extrude(2)
        .translate((-136, -P.armrest_hmi_y, tray_z + 4.5))
    )
    result.extend(
        [
            part("hmi_left_display_qi_tray", tray, PCABS, mass_override_kg=0.16),
            part(
                "hmi_status_display_left",
                display,
                ELECTRICAL,
                mass_override_kg=0.12,
                vendor_part_number="124x50mm-sunlight-readable-status-display-envelope",
                maturity="interface-envelope",
            ),
            part(
                "hmi_qi2_charging_coil_left",
                qi_coil,
                ELECTRICAL,
                mass_override_kg=0.05,
                vendor_part_number="qi2-15w-transmitter-coil-envelope",
                maturity="supplier-selection-gate",
            ),
            part(
                "hmi_qi2_power_fod_module_left",
                qi_module,
                ELECTRICAL,
                mass_override_kg=0.08,
                vendor_part_number="qi2-fod-temperature-controller-envelope",
                maturity="supplier-selection-gate",
            ),
            part(
                "hmi_qi2_presence_temperature_sensor_left",
                qi_sensor,
                ELECTRICAL,
                mass_override_kg=0.01,
                vendor_part_number="qi2-presence-temperature-sensor-envelope",
                maturity="interface-envelope",
            ),
        ]
    )
    # The hardwired stop is integrated into the inner-front armrest volume:
    # visually quiet, reachable from the seat and still reachable by a helper.
    estop_housing = rounded_box(44, 30, 46, 8).translate(
        (-260, -320, 590)
    )
    estop_button = (
        cq.Workplane("YZ")
        .circle(15)
        .extrude(12)
        .translate((-294, -320, 590))
    )
    result.extend(
        [
            part("hmi_emergency_stop_guard", estop_housing, PCABS, mass_override_kg=0.22),
            part(
                "hmi_mechanical_emergency_stop",
                estop_button,
                SAFETY_CONTROL,
                mass_override_kg=0.10,
                vendor_part_number="twist-release-dual-channel-estop-envelope",
                maturity="supplier-selection-gate",
            ),
        ]
    )

    rear_interfaces = [
        ("service_charge_port_guarded", -140, 260, "sealed-58p4v-charge-inlet-envelope"),
        ("service_battery_disconnect_guarded", 0, 330, "lockable-service-disconnect-envelope"),
        ("service_brake_release_guarded", 140, 365, "two-action-manual-brake-release-envelope"),
    ]
    for name, y, z, interface_id in rear_interfaces:
        result.append(
            part(
                name,
                rounded_box(8, 72, 72, 4).translate((323, y, z)),
                SAFETY_CONTROL if "disconnect" in name else ELECTRICAL,
                mass_override_kg=0.20,
                vendor_part_number=interface_id,
                maturity="interface-envelope",
            )
        )
    # One flush rear service door replaces three exposed blocks.  A thin,
    # low-luminance line communicates follow/charge/fault without advertising
    # a robotic identity in the café.
    service_door = rounded_box(6, 310, 172, 12).translate((323, 0, 330))
    status_light = rounded_box(5, 140, 7, 3).translate((327, 0, 420))
    rear_horn = rounded_box(6, 60, 28, 3).translate((322, 0, 400))
    result.extend(
        [
            part("service_rear_flush_door", service_door, PCABS, mass_override_kg=0.22),
            part(
                "hmi_rear_status_light",
                status_light,
                STATUS_LIGHT,
                mass_override_kg=0.04,
                vendor_part_number="low-luminance-rgbw-status-lightpipe-envelope",
                maturity="interface-envelope",
            ),
            part(
                "service_rear_horn_behind_door",
                rear_horn,
                ELECTRICAL,
                mass_override_kg=0.12,
                vendor_part_number="low-profile-audible-alert-envelope",
                maturity="interface-envelope",
            ),
        ]
    )
    return result


def obstacle_pull_handle_parts(configuration: str) -> list[Part]:
    """v37-derived rear telescopic obstacle-assist handle.

    The extended state is only represented in the dedicated unoccupied
    ``obstacle`` configuration.  In every occupied state the tubes are nested
    below the rear deck and the crossbar is latched into its shallow recess.
    """
    result: list[Part] = []
    extended = configuration == "obstacle"
    x = P.obstacle_handle_x
    deck_z = P.obstacle_handle_deck_z
    tube_y = P.obstacle_handle_tube_y

    recess = rounded_box(52, P.obstacle_handle_crossbar_width + 12, 4, 8).translate(
        (x, 0, deck_z + 2)
    )
    result.append(part("obstacle_handle_deck_recess", recess, PCABS, mass_override_kg=0.08))

    if extended:
        outer_z0 = deck_z
        outer_h = 420.0
        inner_z0 = outer_z0 + outer_h - 5.0
        inner_h = P.obstacle_handle_extended_top_z - 32.0 - inner_z0
        crossbar_z = P.obstacle_handle_extended_top_z - 13.0
    else:
        outer_z0 = 205.0
        outer_h = deck_z - 25.0 - outer_z0
        inner_z0 = outer_z0 + 8.0
        inner_h = outer_h - 16.0
        crossbar_z = deck_z + 13.0

    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        outer = (
            cq.Workplane("XY")
            .circle(P.obstacle_handle_outer_od / 2)
            .circle(P.obstacle_handle_outer_od / 2 - P.obstacle_handle_wall)
            .extrude(outer_h)
            .translate((x, side * tube_y, outer_z0))
        )
        inner = (
            cq.Workplane("XY")
            .circle(P.obstacle_handle_inner_od / 2)
            .circle(P.obstacle_handle_inner_od / 2 - P.obstacle_handle_wall)
            .extrude(inner_h)
            .translate((x, side * tube_y, inner_z0))
        )
        latch = rounded_box(38, 34, 22, 5).translate((x, side * tube_y, deck_z - 8))
        result.extend(
            [
                part(
                    f"obstacle_handle_outer_tube_{side_name}_{'extended' if extended else 'stowed'}",
                    outer,
                    STEEL,
                    configuration=configuration,
                ),
                part(
                    f"obstacle_handle_inner_tube_{side_name}_{'extended' if extended else 'stowed'}",
                    inner,
                    STEEL,
                    configuration=configuration,
                ),
                part(
                    f"obstacle_handle_positive_latch_{side_name}",
                    latch,
                    STEEL,
                    configuration=configuration,
                ),
            ]
        )

    crossbar = rounded_box(46, P.obstacle_handle_crossbar_width, 26, 12).translate(
        (x, 0, crossbar_z)
    )
    grip = rounded_box(40, 380, 5, 2).translate((x - 24, 0, crossbar_z + 2))
    result.extend(
        [
            part(
                f"obstacle_handle_crossbar_{'extended' if extended else 'stowed'}",
                crossbar,
                ALUMINUM,
                configuration=configuration,
            ),
            part(
                f"obstacle_handle_grip_inlay_{'extended' if extended else 'stowed'}",
                grip,
                TPE_BOOT,
                configuration=configuration,
            ),
        ]
    )
    return result


def drawer_tray(length: float, depth: float, height: float, wall: float) -> cq.Workplane:
    bottom = cq.Workplane("XY").box(length, depth, wall).translate((0, 0, -height / 2 + wall / 2))
    side_a = cq.Workplane("XY").box(wall, depth, height).translate((-length / 2 + wall / 2, 0, 0))
    side_b = cq.Workplane("XY").box(wall, depth, height).translate((length / 2 - wall / 2, 0, 0))
    rear = cq.Workplane("XY").box(length, wall, height).translate((0, -depth / 2 + wall / 2, 0))
    return bottom.union(side_a).union(side_b).union(rear)


def drawer_parts() -> list[Part]:
    result: list[Part] = []
    slide_url = "https://www.accuride.com/media/amasty/amfile/attach/5d3275f703c9dec3898e9331b075578e.pdf"
    latch_url = "https://southco.com/en_us_int/r4-10-30-905-20"
    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        # E6 keeps one personal bay and one compute/tool bay.  The lower tier
        # is deleted to reduce mass, seams and the mobile equipment-cabinet look.
        for tier in (1,):
            tier_name = "upper"
            length = P.upper_drawer_length if tier else P.lower_drawer_length
            x_center = P.upper_drawer_x if tier else P.lower_drawer_x
            z_center = P.upper_drawer_z if tier else P.lower_drawer_z
            y_center = side * (195.0 if tier else 200.0)
            tray_depth = P.laptop_bay_depth if tier else P.lower_drawer_depth
            tray_height = P.upper_drawer_height if tier else P.lower_drawer_height
            front_height = P.upper_drawer_front_height if tier else P.lower_drawer_front_height
            tray = drawer_tray(length, tray_depth, tray_height, 1.5)
            if side < 0:
                tray = tray.rotate((0, 0, 0), (0, 0, 1), 180)
            tray = tray.translate((x_center, y_center, z_center))
            result.append(part(f"drawer_tray_{side_name}_{tier_name}", tray, SHEET_AL))

            front = rounded_box(length + 12, 10, front_height, 5).translate(
                (x_center, side * 333.0, z_center)
            )
            result.append(part(f"drawer_front_{side_name}_{tier_name}", front, PCABS))

            for rail_side in (-1, 1):
                slide_x = x_center + rail_side * (length / 2 + P.drawer_slide_thickness / 2)
                slide = cq.Workplane("XY").box(
                    P.drawer_slide_thickness,
                    P.laptop_slide_length if tier else P.drawer_slide_length,
                    P.drawer_slide_height,
                ).translate((slide_x, y_center, z_center - 12))
                result.append(
                    part(
                        f"cots_slide_{side_name}_{tier_name}_{'a' if rail_side < 0 else 'b'}",
                        slide,
                        PURCHASED,
                        mass_override_kg=0.40,
                        vendor="Accuride",
                        vendor_part_number="3832-E12-DO" if tier else "3832-E10-DO",
                        source_url=slide_url,
                        maturity="candidate-cots",
                    )
                )

            if tier:
                device_y = side * 190.0
                liner = rounded_box(410, 270, 8, 12).translate((x_center, device_y, 330))
                result.append(
                    part(
                        f"device_bay_shock_liner_{side_name}",
                        liner,
                        FOAM,
                        mass_override_kg=0.18,
                    )
                )
                if side > 0:
                    device = rounded_box(
                        P.laptop_envelope_length,
                        P.laptop_envelope_depth,
                        P.laptop_envelope_height,
                        8,
                    ).translate((x_center, device_y, 349))
                    device_name = "laptop_16in_keepout_right"
                    interface_id = "365x255x28-main-laptop-design-envelope"
                else:
                    device = rounded_box(330, 230, 30, 8).translate((x_center, device_y, 349))
                    device_name = "universal_flat_device_keepout_left"
                    interface_id = "330x230x30-tablet-a4-or-14in-laptop-envelope"
                result.append(
                    part(
                        device_name,
                        device,
                        EQUIPMENT,
                        mass_override_kg=0.0,
                        vendor_part_number=interface_id,
                        maturity="validation-envelope",
                    )
                )

            latch = cq.Workplane("XY").box(
                P.drawer_latch_length,
                P.drawer_latch_width,
                P.drawer_latch_height,
            ).translate((x_center, side * 304.0, z_center + 30))
            result.append(
                part(
                    f"cots_latch_{side_name}_{tier_name}",
                    latch,
                    PURCHASED,
                    mass_override_kg=0.25,
                    vendor="Southco",
                    vendor_part_number="R4-10-30-905-20",
                    source_url=latch_url,
                    maturity="candidate-cots",
                )
            )
    return result


def daily_caddy_parts() -> list[Part]:
    """Independent 4.9 L daily-items caddy below the seat centre.

    It is intentionally separate from the two flat device bays so an occasional
    dual-computer user still has a home for chargers, mouse, headset and personal
    items.  Access is by an unpowered seat-pan service lid while unoccupied; no
    third exterior drawer seam is added.
    """
    length, width, height, wall = 330.0, 220.0, 70.0, 1.5
    bin_shape = drawer_tray(length, width, height, wall)
    front = cq.Workplane("XY").box(length, wall, height).translate(
        (0, width / 2 - wall / 2, 0)
    )
    # Keep a real service/optical clearance corridor behind the three front
    # follow-sensor modules.  The caddy is biased 25 mm aft versus the first
    # packaging study; this preserves its net volume without treating the
    # sensor envelopes as penetrable cosmetic geometry.
    caddy_x = -185.0
    bin_shape = bin_shape.union(front).translate((caddy_x, 0, 275))
    liner = rounded_box(310, 200, 8, 10).translate((caddy_x, 0, 245))
    lid = rounded_box(340, 230, 4, 12).translate((caddy_x, 0, 317))
    return [
        part("daily_caddy_liftout_bin_4p9l", bin_shape, SHEET_AL, mass_override_kg=0.62),
        part("daily_caddy_soft_liner", liner, FOAM, mass_override_kg=0.10),
        part("daily_caddy_unpowered_access_lid", lid, PCABS, mass_override_kg=0.18),
    ]


def body_and_seat_parts(configuration: str) -> list[Part]:
    lower = rounded_shell(P.lower_body_length, P.lower_body_width, P.lower_body_height, 42, 3.0).translate(
        (P.body_x, 0, P.lower_body_z)
    )
    upper = rounded_shell(P.body_length, P.body_width, P.upper_deck_height, 35, 3.0).translate(
        (P.body_x, 0, P.upper_deck_z)
    )
    # Supplier-cut apertures are referenced from chassis datums, never from cosmetic skins.
    for side in (-1, 1):
        upper_cavity = cq.Workplane("XY").box(
            P.upper_drawer_length + 40,
            P.laptop_bay_depth + 12,
            P.upper_drawer_height + 16,
        ).translate((P.upper_drawer_x, side * 195, P.upper_drawer_z))
        lower = lower.cut(upper_cavity)
        upper = upper.cut(upper_cavity)
    # The under-floor LFP cassette is a separately sealed structural module.
    # Its service opening is real geometry, avoiding the previous impossible
    # condition where the cassette occupied the lower enclosure floor skin.
    battery_service_aperture = cq.Workplane("XY").box(410, 490, 132).translate((0, 0, 140))
    lower = lower.cut(battery_service_aperture)
    # Rear vent penetrations are controlled interfaces, not unreported shell
    # collisions.  The duct exits away from the occupant through this aperture.
    rear_vent_aperture = cq.Workplane("XY").box(138, 50, 50).translate((286, 0, 178))
    lower = lower.cut(rear_vent_aperture)
    rear_service_aperture = cq.Workplane("XY").box(30, 300, 160).translate((315, 0, 330))
    lower = lower.cut(rear_service_aperture)
    rear_tof_aperture = cq.Workplane("XY").box(12, 56, 28).translate((318, 0, 133))
    lower = lower.cut(rear_tof_aperture)
    for x in (-445.0, 295.0):
        for side in (-1, 1):
            ultrasonic_aperture = (
                cq.Workplane("XZ")
                .circle(8.5)
                .extrude(8.0, both=True)
                .translate((x, side * (P.lower_body_width / 2), 320))
            )
            lower = lower.cut(ultrasonic_aperture)
    for x in (-120.0, 20.0):
        for side in (-1, 1):
            mic_aperture = rounded_box(72, 10, 10, 3).translate(
                (x, side * (P.lower_body_width / 2), 233)
            )
            lower = lower.cut(mic_aperture)
    for side in (-1, 1):
        for wheel_x in (P.wheel_x_front, P.wheel_x_rear):
            axle_service_bore = (
                cq.Workplane("XZ")
                .circle(P.axle_diameter / 2 + 6.0)
                .extrude(40, both=True)
                .translate((wheel_x, side * (P.lower_body_width / 2), P.wheel_center_z))
            )
            lower = lower.cut(axle_service_bore)
    # The upper deck is a perimeter deck over the lower enclosure, not a second
    # solid floor occupying the same material.  Remove the central overlap and
    # retain the wider side shelves and perimeter return.
    upper_lower_interface = cq.Workplane("XY").box(
        P.lower_body_length,
        P.lower_body_width,
        112,
    ).translate((P.body_x, 0, 405))
    upper = upper.cut(upper_lower_interface)
    for side in (-1, 1):
        uwb_radome_aperture = rounded_box(124, 12, 24, 5).translate(
            (-75, side * (P.body_width / 2 - 2.0), 400)
        )
        upper = upper.cut(uwb_radome_aperture)
    for side in (-1, 1):
        armrest_mount_aperture = polygon_prism(
            armrest_outline(side, -2.0),
            90.0,
            P.armrest_bottom_z - 4.0,
        )
        upper = upper.cut(armrest_mount_aperture)
    # Front footwell: a carried person's shins must enter the body envelope
    # without crossing a cosmetic wall. The opening is structural-trimmed later.
    footwell = cq.Workplane("XY").box(270, 510, 400).translate(
        (-385, 0, 315)
    )
    lower = lower.cut(footwell)
    seat_pocket = rounded_box(P.seat_length + 2, P.seat_width + 2, 46, 29).translate(
        (P.seat_x, 0, 463)
    )
    upper = upper.cut(seat_pocket)
    seat = rounded_box(P.seat_length, P.seat_width, P.seat_height, 28).translate(
        (P.seat_x, 0, P.seat_z)
    )

    # v37 taper is retained; the hinge remains fixed and the armrest supplies sweep clearance.
    back_frame = tapered_back_frame()
    back_pad = tapered_back(P.back_width - 90.0, 240.0, P.back_height - 90.0, 18.0).translate((-18, 0, 0))
    back_shell = tapered_back(P.back_width, 300.0, P.back_height, 6.0).translate((40, 0, 0))
    if configuration in ("stowed", "follow", "obstacle"):
        # Travel state is honest geometry: the back and its attached mast fold onto the seat.
        back_frame = rotate_about_y(back_frame, (P.back_hinge_x, 0, P.back_hinge_z), -95.0)
        back_pad = rotate_about_y(back_pad, (P.back_hinge_x, 0, P.back_hinge_z), -95.0)
        back_shell = rotate_about_y(back_shell, (P.back_hinge_x, 0, P.back_hinge_z), -95.0)

    result = [
        part("lower_body_enclosure", lower, SHEET_AL),
        part("upper_deck_panel", upper, PCABS),
        part(
            "seat_structural_pan",
            rounded_box(P.seat_length - 8, P.seat_width - 8, 3, 24).translate((P.seat_x, 0, 438.5)),
            SHEET_AL,
        ),
        part("seat_cushion_envelope", seat, FOAM),
        part("backrest_structural_carrier", back_frame, ALUMINUM),
        part("backrest_cushion_envelope", back_pad, FOAM),
        part("backrest_rear_cosmetic_shell", back_shell, PCABS),
    ]
    if configuration in ("stowed", "follow", "obstacle"):
        # The folded trapezoidal rear shell is the weather cover.  E6's former
        # 650 x 600 x 150 mm travel cap hid that defining surface, created more
        # than 100 mm of false height and intersected the folded mast package.
        # Production protection is therefore local: a soft leading water lip,
        # two side drain/seal rails and a narrow hinge bridge.  No second body
        # is wrapped around the folded back.
        front_water_lip = rounded_box(16, 570, 10, 4).translate((-369, 0, 550))
        result.append(
            part(
                "travel_front_tpe_water_lip",
                front_water_lip,
                TPE_BOOT,
                configuration=configuration,
                mass_override_kg=0.08,
            )
        )
        for side in (-1, 1):
            side_name = "right" if side > 0 else "left"
            drain_rail = rounded_box(500, 10, 8, 3).translate(
                (-105, side * 301, 551)
            )
            drain_outlet = rounded_box(24, 12, 8, 3).translate(
                (-350, side * 301, 547)
            )
            drain_rail = drain_rail.union(drain_outlet)
            result.extend(
                [
                    part(
                        f"travel_side_tpe_seal_drain_{side_name}",
                        drain_rail,
                        TPE_BOOT,
                        configuration=configuration,
                        mass_override_kg=0.05,
                    ),
                ]
            )
        hinge_bridge = rounded_shell(64, 580, 26, 10, 2.5).translate((200, 0, 534))
        result.append(
            part(
                "travel_hinge_local_weather_bridge",
                hinge_bridge,
                PCABS,
                configuration=configuration,
                mass_override_kg=0.28,
            )
        )
    occupancy_sensor = cq.Workplane("XY").box(180, 120, 4).translate((P.seat_x, 0, P.seat_z - 5))
    result.append(
        part(
            "seat_occupancy_sensor",
            occupancy_sensor,
            ELECTRICAL,
            mass_override_kg=0.15,
            vendor_part_number="dual-zone-occupancy-mat-envelope",
            maturity="interface-envelope",
        )
    )
    # The restraint remains a safety interface but disappears from the normal
    # CMF: retractors, buckle dock and anchors sit inside the cushion/pan seam.
    buckle_dock = rounded_box(62, 34, 18, 5).translate((-25, 100, 462))
    result.append(part("pelvic_belt_hidden_buckle_dock", buckle_dock, PURCHASED, mass_override_kg=0.12))
    for side in (-1, 1):
        retractor = rounded_box(36, 24, 52, 5).translate((118, side * 272, 466))
        result.append(
            part(
                f"pelvic_belt_hidden_retractor_{side:+d}",
                retractor,
                PURCHASED,
                mass_override_kg=0.22,
            )
        )
        anchor = cq.Workplane("XY").box(40, 24, 4).translate((132, side * 270, 442))
        result.append(part(f"pelvic_belt_hidden_anchor_{side:+d}", anchor, STEEL))
    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        arm_base = armrest_base_shell(side)
        arm = armrest_shell(side)
        carriage_slot = cq.Workplane("XY").box(32, 44, 36).translate(
            (P.armrest_x_min, side * 340.0, P.armrest_top_z - 28)
        )
        arm = arm.cut(carriage_slot)
        # Closed in every user state, including deployed desk. The lid only opens
        # during the interlocked service/deployment sequence and must re-latch
        # before either desk half is allowed to unfold.
        lid = polygon_prism(armrest_outline(side, 1.0), 4.0, P.armrest_top_z - 4.0)
        if configuration == "transfer" and side > 0:
            pivot = (
                P.armrest_x_max + 70.0,
                side * (P.armrest_outer_y - 10.0),
                P.seat_z + P.seat_height / 2,
            )
            arm = rotate_about_z(arm, pivot, -100.0)
            lid = rotate_about_z(lid, pivot, -100.0)
        result.append(part(f"armrest_base_shell_{side_name}", arm_base, PCABS))
        result.append(part(f"armrest_shell_{side_name}", arm, PCABS))
        result.append(part(f"armrest_lid_{side_name}", lid, ALUMINUM))
        if side > 0:
            pivot = (
                P.armrest_x_max + 70.0,
                side * (P.armrest_outer_y - 10.0),
                P.seat_z + P.seat_height / 2,
            )
            hinge_height = P.armrest_top_z - pivot[2]
            hinge = (
                cq.Workplane("XY")
                .circle(10)
                .circle(5)
                .extrude(hinge_height)
                .translate(pivot)
            )
            result.append(
                part(
                    f"armrest_transfer_hinge_{side_name}",
                    hinge,
                    STEEL,
                    physical_occurrence_id="WC-ARMREST-RIGHT-TRANSFER-HINGE",
                )
            )
            hinge_link = cq.Workplane("XY").box(90, 26, 16).translate(
                (
                    P.armrest_x_max + 35.0,
                    side * (P.armrest_outer_y - 13),
                    P.seat_z + P.seat_height / 2 - 10,
                )
            )
            if configuration == "transfer":
                hinge_link = rotate_about_z(hinge_link, pivot, -100.0)
            result.append(
                part(
                    f"armrest_transfer_link_{side_name}",
                    hinge_link,
                    STEEL,
                    physical_occurrence_id="WC-ARMREST-RIGHT-TRANSFER-LINK",
                )
            )
            hinge_shroud = rounded_shell(48, 48, hinge_height, 10, 2.5).translate(
                (pivot[0], pivot[1], pivot[2] + hinge_height / 2)
            )
            result.append(
                part(
                    f"armrest_transfer_hinge_shroud_{side_name}",
                    hinge_shroud,
                    PCABS,
                    physical_occurrence_id="WC-ARMREST-RIGHT-TRANSFER-HINGE-SHROUD",
                )
            )
            link_shroud = rounded_box(102, 42, 26, 7).translate(
                (
                    P.armrest_x_max + 35.0,
                    side * (P.armrest_outer_y - 13),
                    P.seat_z + P.seat_height / 2 - 10,
                )
            )
            if configuration == "transfer":
                link_shroud = rotate_about_z(link_shroud, pivot, -100.0)
            result.append(
                part(
                    f"armrest_transfer_link_shroud_{side_name}",
                    link_shroud,
                    PCABS,
                    physical_occurrence_id="WC-ARMREST-RIGHT-TRANSFER-LINK-SHROUD",
                )
            )
            lock = rounded_box(44, 24, 18, 4).translate(
                (P.armrest_x_chamfer_start, side * (P.armrest_inner_y + 8), P.armrest_top_z - 28)
            )
            result.append(
                part(
                    f"armrest_transfer_positive_lock_{side_name}",
                    lock,
                    STEEL,
                    physical_occurrence_id="WC-ARMREST-RIGHT-TRANSFER-POSITIVE-LOCK",
                )
            )
    return result


def table_parts(configuration: str) -> list[Part]:
    result: list[Part] = []
    if configuration == "cafe":
        # Standard HMI layout: the right drive pod is first parked inside the
        # body, then the right panel becomes the single Café surface.  The left
        # display/Qi side remains completely open.  The panel does not simply
        # yaw in its occupied position: it clears forward, rotates about its
        # centre of mass, then slides 80 mm back into comfortable reach.
        for side in (-1, 1):
            side_name = "right" if side > 0 else "left"
            if side < 0:
                bundle = cq.Workplane("XY").box(
                    P.table_length, P.table_stowed_thickness, P.table_stowed_height
                ).translate(
                    (
                        P.table_stowed_x,
                        side * P.table_stowed_y,
                        P.armrest_top_z - P.table_stowed_height / 2 - 10,
                    )
                )
                result.append(
                    part(
                        "desk_bundle_stowed_left",
                        bundle,
                        SANDWICH,
                        configuration=configuration,
                    )
                )
                continue

            panel_y = side * (P.table_centre_safety_gap / 2 + P.table_half_width / 2)
            rotation_centre = (
                P.cafe_rotation_clearance_x,
                panel_y,
                P.table_surface_z - P.table_thickness / 2,
            )
            panel = rounded_box(
                P.table_length,
                P.table_half_width,
                P.table_thickness,
                8,
            ).translate(rotation_centre)
            panel = rotate_about_z(
                panel,
                rotation_centre,
                -side * P.cafe_rotation_deg,
            ).translate((P.cafe_table_x - P.cafe_rotation_clearance_x, 0, 0))
            fold_hinge = (
                cq.Workplane("YZ")
                .circle(4.0)
                .extrude(P.table_length / 2, both=True)
                .translate(
                    (
                        P.cafe_rotation_clearance_x,
                        panel_y,
                        P.table_surface_z - P.table_thickness - 2,
                    )
                )
            )
            fold_hinge = rotate_about_z(
                fold_hinge,
                rotation_centre,
                -side * P.cafe_rotation_deg,
            ).translate((P.cafe_table_x - P.cafe_rotation_clearance_x, 0, 0))
            fold_rigidizers = []
            for lock_index, x_lock in enumerate(
                (P.cafe_rotation_clearance_x - 150, P.cafe_rotation_clearance_x + 150), 1
            ):
                rigidizer = rounded_box(54, 18, 7, 3).translate(
                    (x_lock, panel_y, P.table_surface_z - P.table_thickness - 5)
                )
                rigidizer = rotate_about_z(
                    rigidizer,
                    rotation_centre,
                    -side * P.cafe_rotation_deg,
                ).translate((P.cafe_table_x - P.cafe_rotation_clearance_x, 0, 0))
                fold_rigidizers.append((lock_index, rigidizer))

            pole_base_z = P.armrest_bottom_z + 70.0
            pole_h = P.table_surface_z - P.table_thickness - pole_base_z
            pole = (
                cq.Workplane("XY")
                .circle(P.table_pole_od / 2)
                .circle(P.table_pole_od / 2 - P.table_pole_wall)
                .extrude(pole_h)
                .translate((P.cafe_rotation_clearance_x, side * P.table_pole_y, pole_base_z))
            )
            pole_boot = (
                cq.Workplane("XY")
                .circle(25)
                .circle(18)
                .extrude(pole_h - 12)
                .translate((P.cafe_rotation_clearance_x, side * P.table_pole_y, pole_base_z + 6))
            )
            yoke_length = abs(side * P.table_pole_y - panel_y)
            yoke = cq.Workplane("XY").box(54, yoke_length, 24).translate(
                (
                    P.cafe_rotation_clearance_x,
                    (side * P.table_pole_y + panel_y) / 2,
                    P.table_surface_z - P.table_thickness - 12,
                )
            )
            carriage = cq.Workplane("XY").box(300, 34, 28).translate(
                (P.cafe_rotation_clearance_x + 100, side * 340.0, P.armrest_top_z - 28)
            )
            bearing_z0 = P.table_surface_z - P.table_thickness - 12
            turntable = (
                cq.Workplane("XY")
                .circle(P.cafe_turntable_od / 2)
                .circle(P.cafe_turntable_id / 2)
                .extrude(12)
                .translate((P.cafe_rotation_clearance_x, panel_y, bearing_z0))
            )
            # After the 90-degree turn this rail is fore/aft.  Its 80 mm locked
            # travel brings the surface back toward the user without moving the
            # lift column or placing the rotary bearing away from the load path.
            slide_travel = P.cafe_table_x - P.cafe_rotation_clearance_x
            slide_centre_x = P.cafe_rotation_clearance_x + slide_travel / 2
            translation_rail = rounded_box(
                abs(slide_travel) + P.cafe_turntable_od,
                54,
                16,
                5,
            ).translate((slide_centre_x, panel_y, bearing_z0 - 8))
            underdeck_spine = rounded_box(
                58,
                P.cafe_underdeck_spine_length,
                14,
                5,
            ).translate((P.cafe_table_x, panel_y, P.table_surface_z - P.table_thickness - 9))
            index_plate = (
                cq.Workplane("XY")
                .circle(P.cafe_turntable_od / 2 + 7)
                .circle(P.cafe_turntable_od / 2 + 2)
                .extrude(4)
                .translate((P.cafe_rotation_clearance_x, panel_y, bearing_z0 + 8))
            )
            lock_pin = (
                cq.Workplane("XY")
                .circle(P.cafe_lock_pin_diameter / 2)
                .extrude(20)
                .translate(
                    (
                        P.cafe_rotation_clearance_x,
                        panel_y + side * (P.cafe_turntable_od / 2 + 4),
                        bearing_z0 - 2,
                    )
                )
            )
            translation_lock = rounded_box(36, 24, 16, 4).translate(
                (P.cafe_table_x - 22, panel_y, bearing_z0 - 8)
            )
            result.extend(
                [
                    part(f"desk_panel_{side_name}", panel, SANDWICH, configuration=configuration),
                    part(f"desk_leaf_fold_hinge_{side_name}", fold_hinge, STEEL, configuration=configuration),
                    part(f"desk_lift_tube_{side_name}", pole, ALUMINUM, configuration=configuration),
                    part(f"desk_lift_column_boot_{side_name}", pole_boot, TPE_BOOT, configuration=configuration),
                    part(
                        f"desk_cafe_transverse_yoke_{side_name}",
                        yoke,
                        ALUMINUM,
                        configuration=configuration,
                        physical_occurrence_id=f"WC-DESK-CAFE-TRANSVERSE-YOKE-{side_name.upper()}",
                    ),
                    part(f"desk_forward_carriage_{side_name}", carriage, ALUMINUM, configuration=configuration),
                    part(f"desk_cafe_rotation_bearing_{side_name}", turntable, STEEL, configuration=configuration),
                    part(f"desk_cafe_rotation_index_plate_{side_name}", index_plate, STEEL, configuration=configuration),
                    part(f"desk_cafe_rotation_lock_pin_{side_name}", lock_pin, STEEL, configuration=configuration),
                    part(f"desk_cafe_translation_rail_{side_name}", translation_rail, AL7075, configuration=configuration),
                    part(f"desk_cafe_underdeck_spine_{side_name}", underdeck_spine, AL7075, configuration=configuration),
                    part(f"desk_cafe_translation_lock_{side_name}", translation_lock, STEEL, configuration=configuration),
                ]
            )
            for lock_index, rigidizer in fold_rigidizers:
                result.append(
                    part(
                        f"desk_leaf_rigidizer_{side_name}_{lock_index}",
                        rigidizer,
                        STEEL,
                        configuration=configuration,
                    )
                )

    elif configuration == "desk":
        for side in (-1, 1):
            side_name = "right" if side > 0 else "left"
            panel_y = side * (P.table_centre_safety_gap / 2 + P.table_half_width / 2)
            panel = rounded_box(P.table_length, P.table_half_width, P.table_thickness, 8).translate(
                (P.table_x, panel_y, P.table_surface_z - P.table_thickness / 2)
            )
            fold_hinge = (
                cq.Workplane("YZ")
                .circle(4.0)
                .extrude(P.table_length / 2, both=True)
                .translate((P.table_x, panel_y, P.table_surface_z - P.table_thickness - 2))
            )
            pole_base_z = P.armrest_bottom_z + 70.0
            pole_h = P.table_surface_z - P.table_thickness - pole_base_z
            pole = (
                cq.Workplane("XY")
                .circle(P.table_pole_od / 2)
                .circle(P.table_pole_od / 2 - P.table_pole_wall)
                .extrude(pole_h)
                .translate((P.table_x, side * P.table_pole_y, pole_base_z))
            )
            pole_boot = (
                cq.Workplane("XY")
                .circle(25)
                .circle(18)
                .extrude(pole_h - 12)
                .translate((P.table_x, side * P.table_pole_y, pole_base_z + 6))
            )
            yoke = cq.Workplane("XY").box(90, 45, 24).translate(
                (
                    P.table_x - 30.0,
                    side * (P.table_centre_safety_gap / 2 + P.table_half_width + 15),
                    P.table_surface_z - P.table_thickness - 12,
                )
            )
            carriage = cq.Workplane("XY").box(300, 34, 28).translate(
                (P.table_x + 100, side * 340.0, P.armrest_top_z - 28)
            )
            result.extend(
                [
                    part(f"desk_panel_{side_name}", panel, SANDWICH, configuration=configuration),
                    part(f"desk_leaf_fold_hinge_{side_name}", fold_hinge, STEEL, configuration=configuration),
                    part(f"desk_lift_tube_{side_name}", pole, ALUMINUM, configuration=configuration),
                    part(f"desk_lift_column_boot_{side_name}", pole_boot, TPE_BOOT, configuration=configuration),
                    part(
                        f"desk_yoke_{side_name}",
                        yoke,
                        ALUMINUM,
                        configuration=configuration,
                        physical_occurrence_id=f"WC-DESK-FOCUS-YOKE-{side_name.upper()}",
                    ),
                    part(f"desk_forward_carriage_{side_name}", carriage, ALUMINUM, configuration=configuration),
                ]
            )
            for lock_index, x_lock in enumerate((P.table_x - 150, P.table_x + 150), 1):
                rigidizer = rounded_box(54, 18, 7, 3).translate(
                    (x_lock, panel_y, P.table_surface_z - P.table_thickness - 5)
                )
                result.append(
                    part(
                        f"desk_leaf_rigidizer_{side_name}_{lock_index}",
                        rigidizer,
                        STEEL,
                        configuration=configuration,
                    )
                )
        # Positive centre latches; friction hinges are not structural locks.
        for x in (P.table_x - 150, P.table_x + 150):
            latch = cq.Workplane("XY").box(60, 18, 8).translate((x, 0, P.table_surface_z - 8))
            result.append(part(f"desk_centre_latch_{int(x)}", latch, STEEL, configuration="desk"))
            lock_pin = (
                cq.Workplane("XZ")
                .circle(P.desk_lock_pin_diameter / 2)
                .extrude(25, both=True)
                .translate((x, 0, P.table_surface_z - 6))
            )
            result.append(part(f"desk_lock_pin_{int(x)}", lock_pin, STEEL, configuration="desk"))
    else:
        for side in (-1, 1):
            side_name = "right" if side > 0 else "left"
            stowed_y = side * P.table_stowed_y
            bundle = cq.Workplane("XY").box(
                P.table_length, P.table_stowed_thickness, P.table_stowed_height
            ).translate(
                (
                    P.table_stowed_x,
                    stowed_y,
                    P.armrest_top_z - P.table_stowed_height / 2 - 10,
                )
            )
            if configuration == "transfer" and side > 0:
                pivot = (
                    P.armrest_x_max + 70.0,
                    side * (P.armrest_outer_y - 10.0),
                    P.seat_z + P.seat_height / 2,
                )
                bundle = rotate_about_z(bundle, pivot, -100.0)
            result.append(part(f"desk_bundle_stowed_{side_name}", bundle, SANDWICH, configuration=configuration))
    return result


def _footrest_local_shapes() -> dict[str, cq.Workplane]:
    """Return the four pose-invariant A08 production B-Rep definitions."""

    body_front_x = P.body_x - P.body_length / 2.0
    support_length = abs(body_front_x - P.footrest_deployed_x)
    return {
        "platform": rounded_box(
            P.footrest_length,
            P.footrest_width,
            P.footrest_thickness,
            4.0,
        ),
        "support": tube_x(
            support_length,
            P.footrest_support_section,
            P.footrest_support_wall,
        ),
        "boot": tube_x(
            support_length,
            P.footrest_support_section + 10.0,
            3.0,
        ),
        "latch": cq.Workplane("XY").box(46.0, 80.0, 26.0),
    }


def footrest_parts(
    configuration: str,
    footrest_pose: FootrestPose | str | None = None,
) -> list[Part]:
    """Build one invariant six-occurrence A08 assembly in the requested pose.

    E6-DFR3 incorrectly used a 210 x 500 x 10 mm one-piece stowed surrogate
    and a different 250 x 540 x 20 mm six-piece deployed assembly.  That made
    the same product gain 2.3406 kg when the user opened the footrest.  DFR4
    defines every physical occurrence exactly once and changes only rigid
    placement between ``STOWED`` and ``DEPLOYED_LOCKED``.

    The platform remains horizontal and retracts into the front cassette.  The
    two protected link/boot pairs rotate upright inside the hollow optical
    nose; their B-Rep, material, volume, mass, physical ID and definition
    revision are pose-invariant.
    """

    pose = resolve_footrest_pose(configuration, footrest_pose)
    pose_token = pose.value
    body_front_x = P.body_x - P.body_length / 2.0

    # One production platform definition in both poses.  210 mm depth gives a
    # useful shoe-support surface while fitting the released 210 x 500 front
    # cassette without enlarging the optical nose envelope.
    local = _footrest_local_shapes()
    platform_local = local["platform"]
    support_local = local["support"]
    boot_local = local["boot"]
    latch_local = local["latch"]

    if pose is FootrestPose.STOWED:
        platform_center = (-360.0, 0.0, 147.0)
        # Both complete link/boot pairs rotate upright into the hollow optical
        # nose, above the chassis and out of the feet-to-floor corridor.  They
        # sit between the centre perception stack and the side transducers;
        # the released shell is not enlarged and no physical occurrence is
        # deleted in the stowed pose.
        support_center_x = -400.0
        support_center_z = 220.0
    else:
        # Preserve the released DFR3 top-of-footrest datum (Z=100 mm) while
        # using the single 10 mm production platform definition.
        platform_center = (
            P.footrest_deployed_x,
            0.0,
            P.footrest_deployed_z + 5.0,
        )
        support_center_x = (body_front_x + P.footrest_deployed_x) / 2.0
        support_center_z = P.footrest_deployed_z + 20.0

    common_keywords = {
        "configuration": configuration,
        "definition_revision": "E6R4-A",
        "mechanism_pose": pose.value,
        "mechanism_contract": FOOTREST_CONTRACT_VERSION,
    }
    result = [
        part(
            f"footrest_platform_{pose_token}",
            platform_local.translate(platform_center),
            SANDWICH,
            physical_occurrence_id="WC-A08-PLATFORM",
            **common_keywords,
        )
    ]
    for side_name, side in (("left", -1), ("right", 1)):
        if pose is FootrestPose.STOWED:
            center = (support_center_x, side * 210.0, support_center_z)
            support_shape = support_local.rotate(
                (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 90.0
            ).translate(center)
            boot_shape = boot_local.rotate(
                (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 90.0
            ).translate(center)
        else:
            center = (support_center_x, side * 220.0, support_center_z)
            support_shape = support_local.translate(center)
            boot_shape = boot_local.translate(center)
        result.extend(
            [
                part(
                    f"footrest_support_{side_name}_{pose_token}",
                    support_shape,
                    ALUMINUM,
                    physical_occurrence_id=f"WC-A08-SUPPORT-{side_name.upper()}",
                    **common_keywords,
                ),
                part(
                    f"footrest_support_boot_{side_name}_{pose_token}",
                    boot_shape,
                    TPE_BOOT,
                    physical_occurrence_id=f"WC-A08-SUPPORT-BOOT-{side_name.upper()}",
                    **common_keywords,
                ),
            ]
        )

    # The manual positive latch is body-side and therefore has an identity
    # transform between poses.  It is nevertheless present in every state and
    # shares the same stable occurrence ID and definition.
    latch_center = (body_front_x + 10.0, 0.0, P.footrest_deployed_z + 18.0)
    result.append(
        part(
            f"footrest_manual_latch_{pose_token}",
            latch_local.translate(latch_center),
            STEEL,
            physical_occurrence_id="WC-A08-MANUAL-LATCH",
            **common_keywords,
        )
    )
    return result


def footrest_motion_parts(configuration: str, progress: float) -> list[Part]:
    """Sample the authorised Cafe/Focus stow-to-deploy path.

    ``progress`` is normalised 0..1.  The cam sequence first lowers the
    platform 6.5 mm below the tactile edge, then translates it and rotates the
    two protected links outside chassis crossmember 1, and finally lowers the
    platform onto the deployed supports.  Five or more samples are used by the
    DFR4 gate; this helper intentionally rejects non-Cafe/Focus modes.
    """

    # This both validates the configuration and rejects an unauthorised
    # optional open request in Follow or other modes.
    resolve_footrest_pose(configuration, FootrestPose.DEPLOYED_LOCKED)
    progress = float(progress)
    if not 0.0 <= progress <= 1.0:
        raise ValueError(f"A08 motion progress must be in [0, 1], got {progress}")

    body_front_x = P.body_x - P.body_length / 2.0
    support_length = abs(body_front_x - P.footrest_deployed_x)
    local = _footrest_local_shapes()
    platform_local = local["platform"]
    support_local = local["support"]
    boot_local = local["boot"]

    def lerp(start: float, end: float, u: float) -> float:
        return start + (end - start) * u

    # Platform cam: lower beneath the tactile edge, slide clear of the nose,
    # wait for the links, then settle onto the two deployed supports.
    if progress <= 0.1:
        platform_center = (
            -360.0,
            0.0,
            lerp(147.0, 140.5, progress / 0.1),
        )
    elif progress <= 0.4:
        platform_center = (
            lerp(-360.0, P.footrest_deployed_x, (progress - 0.1) / 0.3),
            0.0,
            140.5,
        )
    elif progress <= 0.9:
        platform_center = (P.footrest_deployed_x, 0.0, 140.5)
    else:
        platform_center = (
            P.footrest_deployed_x,
            0.0,
            lerp(140.5, P.footrest_deployed_z + 5.0, (progress - 0.9) / 0.1),
        )

    # Link cam: after the platform clears, raise the vertical cassette above
    # the bumper, translate it outside the nose, rotate to horizontal, lower
    # below the bumper, then return 12.5 mm to the locked body hardpoint.
    deployed_support_x = (body_front_x + P.footrest_deployed_x) / 2.0
    if progress <= 0.4:
        support_x, support_z, support_angle, support_y = -400.0, 220.0, 90.0, 210.0
    elif progress <= 0.5:
        u = (progress - 0.4) / 0.1
        support_x, support_z, support_angle, support_y = -400.0, lerp(220.0, 240.0, u), 90.0, 210.0
    elif progress <= 0.65:
        u = (progress - 0.5) / 0.15
        support_x, support_z, support_angle, support_y = lerp(-400.0, -550.0, u), 240.0, 90.0, lerp(210.0, 220.0, u)
    elif progress <= 0.75:
        u = (progress - 0.65) / 0.1
        support_x, support_z, support_angle, support_y = -550.0, 240.0, lerp(90.0, 0.0, u), 220.0
    elif progress <= 0.85:
        u = (progress - 0.75) / 0.1
        support_x, support_z, support_angle, support_y = -550.0, lerp(240.0, P.footrest_deployed_z + 20.0, u), 0.0, 220.0
    elif progress <= 0.9:
        u = (progress - 0.85) / 0.05
        support_x, support_z, support_angle, support_y = lerp(-550.0, deployed_support_x, u), P.footrest_deployed_z + 20.0, 0.0, 220.0
    else:
        support_x, support_z, support_angle, support_y = deployed_support_x, P.footrest_deployed_z + 20.0, 0.0, 220.0

    transition_token = f"transition_{int(round(progress * 1000.0)):04d}"
    common_keywords = {
        "configuration": configuration,
        "definition_revision": "E6R4-A",
        "mechanism_pose": transition_token,
        "mechanism_contract": FOOTREST_CONTRACT_VERSION,
        "include_in_ebom": False,
    }
    result = [
        part(
            f"footrest_platform_{transition_token}",
            platform_local.translate(platform_center),
            SANDWICH,
            physical_occurrence_id="WC-A08-PLATFORM",
            **common_keywords,
        )
    ]

    for side_name, side in (("left", -1), ("right", 1)):
        center = (support_x, side * support_y, support_z)
        support_shape = support_local.rotate(
            (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), support_angle
        ).translate(center)
        boot_shape = boot_local.rotate(
            (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), support_angle
        ).translate(center)
        result.extend(
            [
                part(
                    f"footrest_support_{side_name}_{transition_token}",
                    support_shape,
                    ALUMINUM,
                    physical_occurrence_id=f"WC-A08-SUPPORT-{side_name.upper()}",
                    **common_keywords,
                ),
                part(
                    f"footrest_support_boot_{side_name}_{transition_token}",
                    boot_shape,
                    TPE_BOOT,
                    physical_occurrence_id=f"WC-A08-SUPPORT-BOOT-{side_name.upper()}",
                    **common_keywords,
                ),
            ]
        )

    latch_center = (body_front_x + 10.0, 0.0, P.footrest_deployed_z + 18.0)
    result.append(
        part(
            f"footrest_manual_latch_{transition_token}",
            local["latch"].translate(latch_center),
            STEEL,
            physical_occurrence_id="WC-A08-MANUAL-LATCH",
            **common_keywords,
        )
    )
    return result


def human_envelope_parts(
    configuration: str = "seat",
    footrest_pose: FootrestPose | str | None = None,
) -> list[Part]:
    """Return a seated keep-out matched to the actual A08 pose.

    Ride/deployed reviews place the feet on the locked platform.  Parked Cafe
    and Focus defaults place the feet on the floor with a forward-raked lower
    leg envelope, so a floating or platform-only occupant cannot accidentally
    pass the ergonomic gate.
    """

    pose = resolve_footrest_pose(configuration, footrest_pose)
    seat_top = P.seat_z + P.seat_height / 2
    footrest_top = P.footrest_deployed_z + P.footrest_thickness / 2
    pelvis = rounded_box(
        P.occupant_pelvis_depth,
        P.occupant_pelvis_width,
        P.occupant_pelvis_height,
        38,
    ).translate((45, 0, seat_top + P.occupant_pelvis_height / 2))
    torso = rounded_box(
        P.occupant_torso_depth,
        P.occupant_torso_width,
        P.occupant_torso_height,
        55,
    ).translate((45, 0, seat_top + 105 + P.occupant_torso_height / 2))
    head = cq.Workplane("XY").sphere(P.occupant_head_diameter / 2).translate(
        (65, 0, seat_top + 665)
    )
    result = [
        part("human_pelvis_keepout", pelvis, HUMAN, mass_override_kg=0.0),
        part("human_torso_keepout", torso, HUMAN, mass_override_kg=0.0),
        part("human_head_keepout", head, HUMAN, mass_override_kg=0.0),
    ]
    for side in (-1, 1):
        if pose is FootrestPose.DEPLOYED_LOCKED:
            thigh = rounded_box(330, 190, 105, 35).translate(
                (-205, side * 142, seat_top + 20)
            )
            shin_height = seat_top - footrest_top - 20
            shin = rounded_box(150, 175, shin_height, 38).translate(
                (-430, side * 142, footrest_top + 20 + shin_height / 2)
            )
            foot = rounded_box(240, 180, 70, 28).translate(
                (P.footrest_deployed_x, side * 142, footrest_top + 35)
            )
        else:
            # 95th-percentile clothed lower-leg route from the front of the
            # long seat to an ordinary floor contact.  The longer upper-leg
            # envelope puts the knee just ahead of the tactile nose; a nearly
            # vertical 130 mm-deep lower leg then clears the complete product
            # without an anatomically impossible bend through the body.
            thigh = rounded_box(500.0, 190.0, 105.0, 35.0).translate(
                (-280.0, side * 142.0, seat_top + 20.0)
            )
            shin = rounded_box(130.0, 175.0, 400.0, 35.0).translate(
                (-545.0, side * 142.0, 265.0)
            )
            foot = rounded_box(240.0, 180.0, 70.0, 28.0).translate(
                (-585.0, side * 142.0, 35.0)
            )
        upper_arm = rounded_box(105, 90, 290, 35).translate((0, side * 245, seat_top + 275))
        forearm = rounded_box(300, 85, 75, 30).translate((-260, side * 185, P.table_surface_z + 30))
        result.extend(
            [
                part(f"human_thigh_{side:+d}", thigh, HUMAN, mass_override_kg=0.0),
                part(f"human_shin_{side:+d}", shin, HUMAN, mass_override_kg=0.0),
                part(f"human_foot_{side:+d}", foot, HUMAN, mass_override_kg=0.0),
                part(f"human_upper_arm_{side:+d}", upper_arm, HUMAN, mass_override_kg=0.0),
                part(f"human_forearm_{side:+d}", forearm, HUMAN, mass_override_kg=0.0),
            ]
        )
    return result


def beam_shell(z: float) -> cq.Workplane:
    outer = rounded_box(P.beam_depth, P.beam_width, P.beam_height, 18).translate((P.beam_x, 0, z))
    inner = rounded_box(
        P.beam_depth - 2 * P.beam_wall,
        P.beam_width - 2 * P.beam_wall,
        P.beam_height - 2 * P.beam_wall,
        12,
    ).translate((P.beam_x, 0, z))
    return outer.cut(inner)


def mast_and_beam_parts(configuration: str) -> list[Part]:
    deployed = configuration in ("focus", "deployed")
    outdoor_package = configuration == "deployed"
    folded = configuration == "folded"
    beam_z = P.beam_stowed_z + (P.mast_stroke if deployed else 0)
    outer_h = P.mast_outer_height
    outer_top = P.beam_stowed_z - P.beam_height / 2
    outer_z = outer_top - outer_h / 2
    outer = hollow_box(P.mast_outer_depth, P.mast_outer_width, outer_h, 5).translate(
        (P.mast_outer_x, 0, outer_z)
    )
    outer_shroud = rounded_shell(
        P.mast_outer_depth + 12,
        P.mast_outer_width + 16,
        outer_h,
        12,
        2.5,
    ).translate((P.mast_outer_x, 0, outer_z))
    shroud_end_opening = rounded_box(
        P.mast_outer_depth + 7,
        P.mast_outer_width + 11,
        outer_h + 2,
        9,
    ).translate((P.mast_outer_x, 0, outer_z))
    outer_shroud = outer_shroud.cut(shroud_end_opening)
    inner_h = P.mast_stroke + P.mast_overlap_deployed
    inner_base_top = P.beam_stowed_z - P.beam_height / 2
    inner_base_z = inner_base_top - inner_h / 2
    inner = hollow_box(P.mast_inner_depth, P.mast_inner_width, inner_h, 4).translate(
        (P.mast_outer_x, 0, inner_base_z)
    )
    lock_z = outer_top - 120.0
    for side in (-1, 1):
        lock_bore = (
            cq.Workplane("YZ")
            .circle(5.5)
            .extrude(50, both=True)
            .translate((P.mast_outer_x, side * 52, lock_z))
        )
        outer = outer.cut(lock_bore)
        outer_shroud = outer_shroud.cut(lock_bore)
        for inner_lock_z in (lock_z, lock_z - P.mast_stroke):
            inner_lock_bore = (
                cq.Workplane("YZ")
                .circle(5.5)
                .extrude(50, both=True)
                .translate((P.mast_outer_x, side * 52, inner_lock_z))
            )
            inner = inner.cut(inner_lock_bore)
    inner = inner.translate((0, 0, beam_z - P.beam_stowed_z))
    beam = beam_shell(beam_z)
    result = [
        part(
            f"mast_outer_{configuration}", outer, ALUMINUM, configuration=configuration,
            physical_occurrence_id="WC-MAST-OUTER"
        ),
        part(
            f"mast_outer_cosmetic_shroud_{configuration}", outer_shroud, PCABS, configuration=configuration,
            physical_occurrence_id="WC-MAST-OUTER-COSMETIC-SHROUD"
        ),
        part(
            f"mast_inner_{configuration}", inner, ALUMINUM, configuration=configuration,
            physical_occurrence_id="WC-MAST-INNER"
        ),
        part(
            f"sensor_beam_shell_{configuration}", beam, PCABS, configuration=configuration,
            physical_occurrence_id="WC-SENSOR-BEAM-SHELL"
        ),
    ]
    if outdoor_package:
        roller = (
            cq.Workplane("XZ")
            .circle(P.roller_od / 2)
            .circle(P.roller_id / 2)
            .extrude(P.roller_length / 2, both=True)
            .translate((P.beam_x - 15, 0, beam_z))
        )
        roller_motor = (
            cq.Workplane("XZ")
            .circle(12.5)
            .extrude(75, both=True)
            .translate((P.beam_x - 15, 0, beam_z))
        )
        result.extend(
            [
                part(
                    "canopy_roller_outdoor", roller, ALUMINUM, configuration=configuration,
                    physical_occurrence_id="WC-OPT-OUTDOOR-CANOPY-ROLLER",
                    option_code="OPT-OUTDOOR-CANOPY",
                ),
                part(
                    "canopy_roller_motor_outdoor",
                    roller_motor,
                    PURCHASED,
                    configuration=configuration,
                    mass_override_kg=0.8,
                    vendor_part_number="24V-60rpm-2Nm-tubular-envelope",
                    maturity="supplier-selection-gate",
                    physical_occurrence_id="WC-OPT-OUTDOOR-CANOPY-ROLLER-MOTOR",
                    option_code="OPT-OUTDOOR-CANOPY",
                ),
            ]
        )

    # The bar reads as one smoked, flush surface rather than a surveillance
    # cluster.  The mechanical shutter is closed in ride/café states and parks
    # at the edge only after the user explicitly raises Focus mode.
    sensor_window = rounded_box(5, 280, 40, 9).translate((267.5, 0, beam_z))
    result.append(
        part(
            f"mast_smoked_sensor_window_{configuration}",
            sensor_window,
            SMOKED_SENSOR,
            configuration=configuration,
            mass_override_kg=0.10,
            physical_occurrence_id="WC-MAST-SMOKED-SENSOR-WINDOW",
        )
    )
    if deployed:
        shutter = rounded_box(4, 126, 34, 6).translate((264.5, 128, beam_z))
        shutter_name = f"mast_privacy_shutter_parked_{configuration}"
    else:
        shutter = rounded_box(4, 126, 34, 6).translate((264.5, -8, beam_z))
        shutter_name = f"mast_privacy_shutter_closed_{configuration}"
    result.append(
        part(
            shutter_name,
            shutter,
            PCABS,
            configuration=configuration,
            mass_override_kg=0.06,
            physical_occurrence_id="WC-MAST-PHYSICAL-PRIVACY-SHUTTER",
        )
    )

    # Devices sit immediately behind the smoked face.  They are creator/privacy
    # peripherals; folded following depends on the restored base-level suite.
    mast_devices = [
        ("mast_camera_4k", (18, 46, 24), (276, 42, beam_z + 4), 0.18, "4k-camera-10w-envelope"),
        ("mast_camera_depth_ir", (18, 66, 24), (276, -52, beam_z + 4), 0.20, "depth-ir-camera-12w-envelope"),
        ("mast_microphone_array", (10, 170, 10), (276, 0, beam_z - 19), 0.10, "beamforming-mic-array-5w-envelope"),
        ("mast_environment_sensor", (12, 24, 18), (276, 112, beam_z + 4), 0.04, "environment-status-sensor-4w-envelope"),
    ]
    for device_name, dims, pos, mass, vendor_pn in mast_devices:
        result.append(
            part(
                f"{device_name}_{configuration}",
                rounded_box(*dims, 4).translate(pos),
                ELECTRICAL,
                configuration=configuration,
                mass_override_kg=mass,
                vendor_part_number=vendor_pn,
                maturity="interface-envelope",
                physical_occurrence_id=f"WC-{device_name.upper().replace('_', '-')}",
            )
        )
    if deployed:
        for side in (-1, 1):
            lamp = rounded_box(8, 42, 22, 5).translate((266, side * 130, beam_z))
            result.append(
                part(
                    f"mast_fill_light_{configuration}_{side:+d}",
                    lamp,
                    ELECTRICAL,
                    configuration=configuration,
                    mass_override_kg=0.10,
                    vendor_part_number="dimmable-fill-light-8w-envelope",
                    maturity="interface-envelope",
                    physical_occurrence_id=f"WC-OPT-CREATOR-FILL-LIGHT-{'RIGHT' if side > 0 else 'LEFT'}",
                    option_code="OPT-CREATOR-LIGHTS",
                )
            )
    harness_height = max(80.0, beam_z - P.beam_height / 2 - (outer_z - outer_h / 2) - 20.0)
    harness_z = outer_z - outer_h / 2 + 10.0 + harness_height / 2
    mast_harness = rounded_box(12, 8, harness_height, 3).translate((P.mast_outer_x, 65, harness_z))
    result.append(
        part(
            f"mast_harness_24v_data_{configuration}",
            mast_harness,
            ELECTRICAL,
            configuration=configuration,
            mass_override_kg=0.32,
            vendor_part_number="1p5mm2-power-cat6a-safety-pair-hybrid",
            maturity="routing-envelope",
        )
    )
    if outdoor_package:
        for side in (-1, 1):
            wind_sensor = cq.Workplane("XY").box(20, 12, 6).translate(
                (P.beam_x, side * (P.beam_width / 2 - 25), beam_z + P.beam_height / 2 + 3)
            )
            result.append(
                part(
                    f"wind_sensor_{configuration}_{side:+d}",
                    wind_sensor,
                    ELECTRICAL,
                    configuration=configuration,
                    mass_override_kg=0.03,
                    vendor_part_number="redundant-wind-sensor-envelope",
                    maturity="supplier-selection-gate",
                    physical_occurrence_id=f"WC-OPT-OUTDOOR-WIND-SENSOR-{'RIGHT' if side > 0 else 'LEFT'}",
                    option_code="OPT-OUTDOOR-CANOPY",
                )
            )
    # Replaceable bearing pads define the sliding fit; skins and weldments do not.
    for level, z in enumerate((outer_z - outer_h / 2 + 55, outer_z + outer_h / 2 - 55), 1):
        for side in (-1, 1):
            x_pad = cq.Workplane("XY").box(P.mast_guide_pad_thickness, 120, 70).translate(
                (P.mast_outer_x + side * (P.mast_inner_depth / 2 + P.mast_guide_pad_thickness / 2), 0, z)
            )
            y_pad = cq.Workplane("XY").box(36, P.mast_guide_pad_thickness, 70).translate(
                (P.mast_outer_x, side * (P.mast_inner_width / 2 + P.mast_guide_pad_thickness / 2), z)
            )
            side_name = "RIGHT" if side > 0 else "LEFT"
            result.append(
                part(
                    f"mast_guide_x_{configuration}_{level}_{side:+d}", x_pad, POM,
                    configuration=configuration,
                    physical_occurrence_id=f"WC-MAST-GUIDE-X-L{level}-{side_name}",
                )
            )
            result.append(
                part(
                    f"mast_guide_y_{configuration}_{level}_{side:+d}", y_pad, POM,
                    configuration=configuration,
                    physical_occurrence_id=f"WC-MAST-GUIDE-Y-L{level}-{side_name}",
                )
            )

    actuator_top = outer_top - 10.0
    actuator_bottom = actuator_top - P.mast_actuator_built_in
    actuator = (
        cq.Workplane("XY")
        .circle(P.mast_actuator_diameter / 2)
        .extrude(P.mast_actuator_built_in)
        .translate((P.mast_outer_x, -45.0, actuator_bottom))
    )
    result.append(
        part(
            f"cots_mast_actuator_{configuration}",
            actuator,
            PURCHASED,
            configuration=configuration,
            mass_override_kg=1.5,
            vendor="LINAK",
            vendor_part_number="LA20-240mm-envelope",
            source_url="https://cdn.linak.com/-/media/files/data-sheet-source/en/linear-actuator-la20-data-sheet-eng.pdf",
            maturity="candidate-cots-2to1-reeving",
        )
    )
    for pulley_index, z in enumerate((outer_top - 45, outer_top - 95), 1):
        pulley = (
            cq.Workplane("XZ")
            .circle(20)
            .circle(14)
            .extrude(8, both=True)
            .translate((P.mast_outer_x, 40.0, z))
        )
        result.append(part(f"mast_reeving_pulley_{configuration}_{pulley_index}", pulley, AL7075, configuration=configuration))
    for side in (-1, 1):
        lock_pin = (
            cq.Workplane("YZ")
            .circle(5)
            .extrude(40, both=True)
            .translate((P.mast_outer_x, side * 52, lock_z))
        )
        result.append(part(f"mast_lock_pin_{configuration}_{side:+d}", lock_pin, STEEL, configuration=configuration))
    if folded:
        for candidate in result:
            candidate.shape = rotate_about_y(
                candidate.shape,
                (P.back_hinge_x, 0, P.mast_fold_hinge_z),
                -95.0,
            )
    return result


def canopy_deployed_parts() -> list[Part]:
    beam_z = P.beam_stowed_z + P.mast_stroke
    canopy_z = beam_z + P.outdoor_package_cassette_height + 6.0
    hinge = (P.beam_x - P.beam_depth / 2, 0, canopy_z + 4)
    x_hinge = hinge[0]
    cassette = rounded_shell(
        96,
        P.roller_length + 40,
        P.outdoor_package_cassette_height,
        18,
        3.0,
    ).translate((P.beam_x + 14, 0, beam_z + P.outdoor_package_cassette_height / 2))
    result: list[Part] = [
        part(
            "outdoor_canopy_detachable_cassette",
            cassette,
            PCABS,
            configuration="deployed",
            physical_occurrence_id="WC-OPT-OUTDOOR-CANOPY-CASSETTE",
            option_code="OPT-OUTDOOR-CANOPY",
        )
    ]

    for side in (-1, 1):
        y = side * P.canopy_arm_y
        first = cq.Workplane("XY").box(P.canopy_arm_segment, P.canopy_arm_width, P.canopy_arm_height)
        first = first.translate((x_hinge - P.canopy_arm_segment / 2, y, canopy_z))
        second = cq.Workplane("XY").box(P.canopy_arm_segment, P.canopy_arm_width, P.canopy_arm_height)
        second = second.translate((x_hinge - 1.5 * P.canopy_arm_segment, y, canopy_z))
        first = rotate_about_y(first, hinge, P.canopy_pitch_deg)
        second = rotate_about_y(second, hinge, P.canopy_pitch_deg)
        result.extend(
            [
                part(
                    f"canopy_arm_inboard_{side:+d}", first, AL7075, configuration="deployed",
                    physical_occurrence_id=f"WC-OPT-OUTDOOR-CANOPY-ARM-INBOARD-{'RIGHT' if side > 0 else 'LEFT'}",
                    option_code="OPT-OUTDOOR-CANOPY",
                ),
                part(
                    f"canopy_arm_outboard_{side:+d}", second, AL7075, configuration="deployed",
                    physical_occurrence_id=f"WC-OPT-OUTDOOR-CANOPY-ARM-OUTBOARD-{'RIGHT' if side > 0 else 'LEFT'}",
                    option_code="OPT-OUTDOOR-CANOPY",
                ),
            ]
        )

    fabric = cq.Workplane("XY").box(
        P.canopy_projection, P.canopy_total_width, P.canopy_fabric_thickness
    ).translate((x_hinge - P.canopy_projection / 2, 0, canopy_z + P.canopy_arm_height / 2 + 1.5))
    fabric = rotate_about_y(fabric, hinge, P.canopy_pitch_deg)
    result.append(
        part(
            "canopy_fabric_deployed", fabric, FABRIC, configuration="deployed",
            physical_occurrence_id="WC-OPT-OUTDOOR-CANOPY-FABRIC",
            option_code="OPT-OUTDOOR-CANOPY",
        )
    )

    front_x = x_hinge - P.canopy_projection
    front_z = canopy_z
    front = cq.Workplane("XY").box(P.front_rail_depth, P.canopy_total_width, P.front_rail_height)
    front = front.translate((front_x, 0, front_z))
    front = rotate_about_y(front, hinge, P.canopy_pitch_deg)
    result.append(
        part(
            "canopy_front_rail_deployed", front, ALUMINUM, configuration="deployed",
            physical_occurrence_id="WC-OPT-OUTDOOR-CANOPY-FRONT-RAIL",
            option_code="OPT-OUTDOOR-CANOPY",
        )
    )
    return result


def common_parts(
    configuration: str,
    footrest_pose: FootrestPose | str | None = None,
) -> list[Part]:
    return (
        chassis_parts()
        + wheel_parts()
        + internal_module_parts()
        + v37_follow_sensor_parts(configuration)
        + user_control_and_service_parts(configuration)
        + body_and_seat_parts(configuration)
        + drawer_parts()
        + daily_caddy_parts()
        + table_parts(configuration)
        + footrest_parts(configuration, footrest_pose)
        + obstacle_pull_handle_parts(configuration)
    )


def build_configuration(
    configuration: str,
    footrest_pose: FootrestPose | str | None = None,
) -> list[Part]:
    mast_state = (
        "focus"
        if configuration == "desk"
        else ("deployed" if configuration == "deployed" else
        ("folded" if configuration in ("stowed", "follow", "obstacle") else "stowed"))
    )
    parts = common_parts(configuration, footrest_pose) + mast_and_beam_parts(mast_state)
    if configuration == "deployed":
        parts += canopy_deployed_parts()
    if configuration == "internal":
        hidden_prefixes = (
            "lower_body_enclosure",
            "upper_deck_panel",
            "seat_cushion_envelope",
            "seat_structural_pan",
            "seat_occupancy_sensor",
            "pelvic_belt_",
            "backrest_",
            "armrest_",
            "drawer_front_",
            "sensor_beam_",
            "mast_",
            "desk_bundle_",
            "wheel_arch_side_fairing_",
            "footrest_",
            "canopy_",
            "wind_sensor_",
            "cots_mast_actuator_",
        )
        hidden_exact = {"battery_safety_cassette", "occupant_energy_firewall"}
        parts = [
            candidate
            for candidate in parts
            if candidate.name not in hidden_exact
            and not candidate.name.startswith(hidden_prefixes)
        ]
    if configuration == "obstacle":
        # v37 handling posture: front wheels lift while the rear tyre contact
        # remains the ground pivot. This state is unoccupied and low-speed only.
        pivot = (P.wheel_x_rear, 0.0, 0.0)
        parts = [
            replace(
                candidate,
                shape=rotate_about_y(candidate.shape, pivot, P.obstacle_handle_tilt_deg),
                configuration="obstacle",
            )
            for candidate in parts
        ]
    return parts


def storage_review_parts(parts: list[Part], include_running_gear: bool = False) -> list[Part]:
    """High-contrast storage scene, optionally with wheel/chassis context."""
    storage_prefixes = (
        "drawer_tray_",
        "drawer_front_",
        "cots_slide_",
        "cots_latch_",
        "laptop_",
        "universal_",
        "device_bay_",
        "daily_caddy_",
    )
    running_prefixes = (
        "tyre_",
        "hub_",
        "axle_",
        "suspension_",
        "wheel_arch_",
        "chassis_",
    )
    result = []
    for candidate in parts:
        is_storage = candidate.name.startswith(storage_prefixes)
        is_running = candidate.name.startswith(running_prefixes)
        if not is_storage and not (include_running_gear and is_running):
            continue
        name = candidate.name
        side = 1 if "right" in name else (-1 if "left" in name else 0)
        travel = 0.0
        if side and name.startswith(("drawer_", "cots_", "laptop_", "universal_", "device_bay_")):
            travel = P.drawer_slide_travel if "_lower" in name else P.laptop_slide_travel
            if name.startswith("cots_slide_"):
                travel *= 0.5
        shape = candidate.shape.translate((0, side * travel, 0)) if travel else candidate.shape
        color = candidate.color
        if name.startswith("drawer_tray_"):
            color = (0.05, 0.78, 0.92, 1.0)
        elif name.startswith("drawer_front_"):
            color = (1.0, 0.42, 0.05, 1.0)
        elif name.startswith("cots_slide_"):
            color = (0.82, 0.87, 0.92, 1.0)
        elif name.startswith("cots_latch_"):
            color = (0.95, 0.15, 0.18, 1.0)
        elif name.startswith("laptop_"):
            color = (0.35, 0.95, 0.45, 0.92)
        elif name.startswith("universal_"):
            # The left bay is intentionally not empty: this blue envelope is
            # the removable 14-inch/A4/tablet or daily-organizer interface.
            # Give it equal visual weight to the green 16-inch main bay.
            color = (0.18, 0.72, 0.98, 0.92)
        elif name.startswith("daily_caddy_"):
            color = (0.72, 0.42, 0.95, 0.90)
        result.append(replace(candidate, shape=shape, color=color, configuration="storage_review"))
    return result


def electrical_thermal_review_parts(parts: list[Part]) -> list[Part]:
    """High-contrast electrical architecture, harness and thermal-routing scene."""
    context_prefixes = (
        "chassis_",
        "battery_safety_cassette",
        "occupant_energy_firewall",
        "mast_outer_",
        "mast_inner_",
        "sensor_beam_shell_",
        "lower_body_enclosure",
        "upper_deck_panel",
        "armrest_shell_",
        "armrest_base_shell_",
    )
    electrical_prefixes = (
        "battery_lfp_",
        "compute_",
        "encrypted_",
        "communications_",
        "drive_imu_",
        "parked_ac_",
        "safety_backup_",
        "mast_camera_",
        "mast_fill_light_",
        "mast_microphone_",
        "mast_environment_",
        "mast_harness_",
        "canopy_roller_motor_",
        "cots_mast_actuator_",
        "hmi_",
        "service_",
    )
    result: list[Part] = []
    for candidate in parts:
        if candidate.name == "power_distribution_unit":
            continue
        if candidate.name.startswith(context_prefixes):
            result.append(replace(candidate, color=(0.28, 0.31, 0.34, 0.28), configuration="electrical_review"))
        elif candidate.name.startswith(electrical_prefixes):
            color = (0.10, 0.72, 0.95, 1.0)
            if candidate.name.startswith("battery_lfp_"):
                color = (0.24, 0.82, 0.38, 1.0)
            elif candidate.name.startswith(("parked_ac_", "safety_backup_")):
                color = (0.65, 0.42, 0.95, 1.0)
            elif candidate.name.startswith(("hmi_mechanical_emergency_stop", "service_battery_disconnect")):
                color = (0.95, 0.12, 0.10, 1.0)
            elif candidate.name.startswith("hmi_"):
                color = (0.72, 0.45, 0.98, 1.0)
            elif candidate.name.startswith("service_"):
                color = (0.98, 0.58, 0.12, 1.0)
            result.append(replace(candidate, color=color, configuration="electrical_review"))

    # The 94 x 440 x 40 mm PDU bay is partitioned into serviceable functions;
    # gaps between modules are intentional wiring and extraction clearances.
    pdu_cells = [
        ("pdu_service_disconnect", -192, 38, (0.95, 0.28, 0.18, 1.0)),
        ("pdu_main_fuse_150a", -148, 38, (0.95, 0.66, 0.12, 1.0)),
        ("pdu_precharge_dual_contactors", -92, 62, (0.95, 0.42, 0.12, 1.0)),
        ("pdu_48v24v_750w", -8, 88, (0.12, 0.68, 0.95, 1.0)),
        ("pdu_48v12v_240w", 76, 66, (0.10, 0.78, 0.78, 1.0)),
        ("pdu_dual_usbc_pd_140w", 143, 56, (0.42, 0.86, 0.32, 1.0)),
        ("pdu_managed_poe_switch", 194, 36, (0.38, 0.68, 1.0, 1.0)),
    ]
    for name, y, width, color in pdu_cells:
        result.append(
            replace(
                part(name, rounded_box(78, width, 27, 4).translate((268, y, 390)), ELECTRICAL, mass_override_kg=0.0),
                color=color,
                configuration="electrical_review",
            )
        )

    harness_parts = [
        ("harness_48v_main_35mm2", rounded_box(245, 16, 16, 4).translate((135, -205, 205)), (0.93, 0.20, 0.16, 1.0)),
        ("harness_24v_aux_6mm2", rounded_box(330, 12, 12, 3).translate((95, 205, 330)), (0.95, 0.72, 0.12, 1.0)),
        ("harness_motor_left_6mm2", rounded_box(560, 10, 10, 3).translate((-100, -282, 145)), (0.94, 0.28, 0.18, 1.0)),
        ("harness_motor_right_6mm2", rounded_box(560, 10, 10, 3).translate((-100, 282, 145)), (0.94, 0.28, 0.18, 1.0)),
        ("harness_data_spine_cat6a", rounded_box(420, 8, 8, 2).translate((55, 232, 350)), (0.20, 0.82, 0.96, 1.0)),
    ]
    for name, shape, color in harness_parts:
        result.append(replace(part(name, shape, ELECTRICAL, mass_override_kg=0.0), color=color, configuration="electrical_review"))

    # Rear heat exchanger is outside the sealed electronics plenum; the two
    # monitored blowers remain inside and can each sustain a degraded mode.
    result.append(
        replace(
            part("thermal_rear_finned_heat_exchanger", rounded_box(18, 260, 180, 5).translate((332, 0, 290)), ALUMINUM),
            color=(0.70, 0.74, 0.78, 1.0),
            configuration="electrical_review",
        )
    )
    for side in (-1, 1):
        fan = cq.Workplane("YZ").circle(34).extrude(12, both=True).translate((317, side * 72, 290))
        result.append(
            replace(
                part(f"thermal_electronics_blower_{side:+d}", fan, ELECTRICAL, mass_override_kg=0.0),
                color=(0.12, 0.86, 0.72, 1.0),
                configuration="electrical_review",
            )
        )
    return result


def export_assembly(parts: Iterable[Part], configuration: str) -> cq.Assembly:
    assembly = cq.Assembly(name=f"WorkCore_E6_{configuration}")
    for p in parts:
        assembly.add(p.shape, name=p.name, color=cq.Color(*p.color))
    stem = {
        "stowed": "workcore_stowed",
        "follow": "workcore_follow_closed",
        "obstacle": "workcore_obstacle_assist",
        "seat": "workcore_seat_ready",
        "cafe": "workcore_cafe",
        "internal": "workcore_internal_layout",
        "transfer": "workcore_transfer_ready",
        "desk": "workcore_desk",
        "deployed": "workcore_canopy_deployed",
    }[configuration]
    target = BUILD / f"{stem}.step"
    assembly.save(str(target), exportType="STEP", mode="default")
    return assembly


def export_parts(parts_by_config: dict[str, list[Part]]) -> None:
    seen: set[str] = set()
    for parts in parts_by_config.values():
        for p in parts:
            if p.name in seen:
                continue
            cq.exporters.export(p.shape, str(PARTS_DIR / f"{p.name}.step"))
            seen.add(p.name)


def export_glb(parts: list[Part], configuration: str) -> None:
    import numpy as np
    import trimesh

    scene = trimesh.Scene()
    for p in parts:
        vertices, triangles = p.solid.tessellate(1.0, 0.25)
        vertices_np = np.array([[v.x, v.y, v.z] for v in vertices], dtype=float)
        faces_np = np.array(triangles, dtype=int)
        mesh = trimesh.Trimesh(vertices=vertices_np, faces=faces_np, process=False)
        mesh.visual.face_colors = [int(255 * c) for c in p.color]
        scene.add_geometry(mesh, node_name=p.name, geom_name=p.name)
    filename = {
        "stowed": "workcore_stowed.glb",
        "follow": "workcore_follow_closed.glb",
        "obstacle": "workcore_obstacle_assist.glb",
        "seat": "workcore_seat_ready.glb",
        "cafe": "workcore_cafe.glb",
        "internal": "workcore_internal_layout.glb",
        "transfer": "workcore_transfer_ready.glb",
        "desk": "workcore_desk.glb",
        "deployed": "workcore_canopy_deployed.glb",
        "occupied": "workcore_desk_occupied_review.glb",
        "storage": "workcore_storage_review.glb",
        "storage_wheel": "workcore_storage_wheel_review.glb",
        "electrical": "workcore_electrical_thermal_review.glb",
    }[configuration]
    (BUILD / filename).write_bytes(scene.export(file_type="glb"))


def aabb(shape: cq.Workplane) -> dict[str, float]:
    bb = shape.val().BoundingBox()
    return {
        "xmin": bb.xmin,
        "xmax": bb.xmax,
        "ymin": bb.ymin,
        "ymax": bb.ymax,
        "zmin": bb.zmin,
        "zmax": bb.zmax,
    }


def gap_y(a: cq.Workplane, b: cq.Workplane) -> float:
    aa, bb = aabb(a), aabb(b)
    return max(bb["ymin"] - aa["ymax"], aa["ymin"] - bb["ymax"], 0.0)


def aabb_overlaps(a: cq.Workplane, b: cq.Workplane, margin: float = 0.0) -> bool:
    aa, bb = aabb(a), aabb(b)
    return (
        aa["xmin"] - margin < bb["xmax"]
        and aa["xmax"] + margin > bb["xmin"]
        and aa["ymin"] - margin < bb["ymax"]
        and aa["ymax"] + margin > bb["ymin"]
        and aa["zmin"] - margin < bb["zmax"]
        and aa["zmax"] + margin > bb["zmin"]
    )


def _named_side(name: str) -> str | None:
    for side in ("left", "right"):
        if f"_{side}" in name or name.startswith(f"{side}_"):
            return side
    return None


def _named_tier(name: str) -> str | None:
    for tier in ("upper", "lower"):
        if f"_{tier}" in name or name.startswith(f"{tier}_"):
            return tier
    return None


def _same_named_attribute(names: set[str], extractor) -> bool:
    values = {value for name in names if (value := extractor(name)) is not None}
    return len(values) <= 1


def controlled_overlap_reason(name_a: str, name_b: str, configuration: str) -> str | None:
    names = {name_a, name_b}
    joined = "|".join(sorted(names))
    if all(name.startswith("chassis_") for name in names):
        return "welded_chassis_joint"
    if any(name.startswith("axle_") for name in names) and any(
        name.startswith(("hub_", "chassis_rail_", "suspension_rocker_")) for name in names
    ):
        return "wheel_bearing_or_axle_joint"
    if any(name.startswith("suspension_rocker_") for name in names) and any(
        name.startswith("suspension_centre_pivot_") for name in names
    ):
        return "rocker_pivot_joint"
    if any(name.startswith("hub_") for name in names) and any(
        name.startswith("suspension_rocker_") for name in names
    ):
        return "hub_to_rocker_bearing_mount"
    if "battery_safety_cassette" in names and any(
        name.startswith("battery_compartment_temperature_sensor_") for name in names
    ):
        return "embedded_battery_sensor"
    if all(name.startswith(("drawer_tray_", "drawer_front_", "cots_slide_", "cots_latch_")) for name in names) and _same_named_attribute(names, _named_side) and _same_named_attribute(names, _named_tier):
        return "drawer_fastened_interface"
    if all(name.startswith("daily_caddy_") for name in names):
        return "daily_caddy_liner_or_lid_interface"
    if "seat_cushion_envelope" in names and any(
        name.startswith(("seat_occupancy_sensor", "pelvic_belt_hidden_")) for name in names
    ):
        return "embedded_softgoods_interface"
    if all(name.startswith("pelvic_belt_hidden_") for name in names):
        return "restraint_anchor_or_retractor_joint"
    if configuration in ("stowed", "follow", "obstacle") and names == {
        "seat_cushion_envelope",
        "backrest_cushion_envelope",
    }:
        return "controlled_softgoods_stow_compression"
    if configuration in ("stowed", "follow", "obstacle") and any(
        name.startswith("follow_hidden_backrest_antenna_") for name in names
    ) and "seat_cushion_envelope" in names:
        return "flex_antenna_under_stowed_softgoods"
    if all(name.startswith("backrest_") for name in names):
        return "backrest_laminated_assembly"
    if all(
        name.startswith(("mast_", "cots_mast_actuator_"))
        for name in names
    ):
        return "telescopic_mast_guided_or_locking_interface"
    if all(name.startswith("footrest_") for name in names):
        return "footrest_linkage_interface"
    if all(name.startswith("obstacle_handle_") for name in names):
        return "obstacle_handle_telescopic_or_latched_interface"
    if any(name.startswith("obstacle_handle_") for name in names) and any(
        name in {"lower_body_enclosure", "upper_deck_panel"} for name in names
    ):
        return "obstacle_handle_body_mount_or_recess"
    if all(name.startswith("hmi_") for name in names) and _same_named_attribute(names, _named_side):
        return "armrest_hmi_mounted_interface"
    if any(name.startswith("hmi_") for name in names) and any(
        name.startswith(("armrest_lid_", "armrest_shell_")) for name in names
    ) and _same_named_attribute(names, _named_side):
        return "armrest_hmi_mounted_interface"
    if all(name.startswith("service_") for name in names):
        return "guarded_rear_service_bay_interface"
    if any(name.startswith("service_") for name in names) and any(
        name == "lower_body_enclosure" for name in names
    ):
        return "rear_service_aperture_or_mount"
    if any(name.startswith("follow_") for name in names) and any(
        name.startswith(
            (
                "lower_body_enclosure",
                "upper_deck_panel",
                "backrest_",
                "wheel_arch_",
            )
        )
        for name in names
    ):
        return "v37_embedded_follow_sensor_or_window"
    if any(name.startswith("travel_") and "tpe_" in name for name in names) and any(
        name == "backrest_rear_cosmetic_shell" for name in names
    ):
        return "folded_weather_seal_compression"
    if any(name.startswith("mast_smoked_sensor_window_") for name in names) and any(
        name.startswith("sensor_beam_shell_") for name in names
    ):
        return "flush_mast_sensor_window"
    if any(name.startswith("sensor_beam_shell_") for name in names) and any(
        name.startswith(
            (
                "mast_camera_",
                "mast_microphone_",
                "mast_environment_",
            )
        )
        for name in names
    ):
        return "sensor_beam_embedded_device"
    if configuration in ("stowed", "follow", "obstacle") and any(
        name.startswith(("mast_smoked_sensor_window_", "mast_privacy_shutter_"))
        for name in names
    ) and "backrest_rear_cosmetic_shell" in names:
        return "folded_sensor_bar_backrest_mount"
    if "upper_deck_panel" in names and any(name.startswith("mast_inner_") for name in names):
        return "mast_deck_mount_passage"
    closed_transfer_mount_pairs = {
        frozenset({"armrest_base_shell_right", "armrest_transfer_link_right"}),
        frozenset({"armrest_base_shell_right", "armrest_transfer_link_shroud_right"}),
    }
    if frozenset(names) in closed_transfer_mount_pairs:
        return "transfer_closed_mount_inside_base_shell"
    if all(name.startswith(("armrest_transfer_", "armrest_shell_")) for name in names):
        return "transfer_hinge_or_shroud_interface"
    if all(name.startswith(("desk_", "armrest_lid_")) for name in names) and _same_named_attribute(names, _named_side):
        return "desk_fastened_or_latched_interface"
    if any(name.startswith(("desk_bundle_stowed_", "desk_forward_carriage_")) for name in names) and any(
        name.startswith("armrest_shell_") for name in names
    ) and _same_named_attribute(names, _named_side):
        return "desk_mechanism_inside_armrest_cavity"
    if all(name.startswith(("canopy_arm_", "canopy_front_rail_", "sensor_beam_shell_")) for name in names):
        return "canopy_hinge_or_front_rail_joint"
    if any(name.startswith(("outdoor_canopy_", "canopy_roller_")) for name in names) and any(
        name.startswith(("sensor_beam_shell_", "mast_", "canopy_")) for name in names
    ):
        return "detachable_outdoor_package_interface"
    if "occupant_energy_firewall" in names and any(name.startswith("upper_deck_panel") for name in names):
        return "firewall_sealed_flange"
    return None


def validate_footrest_contract(configs: dict[str, list[Part]]) -> list[dict]:
    """Fail-closed DFR4 A08 identity, state, clearance and sweep gates."""

    checks: list[dict] = []
    required_ids = {
        "WC-A08-PLATFORM",
        "WC-A08-SUPPORT-LEFT",
        "WC-A08-SUPPORT-RIGHT",
        "WC-A08-SUPPORT-BOOT-LEFT",
        "WC-A08-SUPPORT-BOOT-RIGHT",
        "WC-A08-MANUAL-LATCH",
    }
    primary_sources = ("follow", "seat", "cafe", "desk")
    by_state: dict[str, dict[str, Part]] = {}
    for configuration in primary_sources:
        occurrences = [
            candidate
            for candidate in configs[configuration]
            if candidate.name.startswith("footrest_")
        ]
        index = {candidate.physical_occurrence_id: candidate for candidate in occurrences}
        by_state[configuration] = index
        expected_pose = resolve_footrest_pose(configuration).value
        checks.append(
            {
                "configuration": configuration,
                "check": "a08_primary_pose_and_occurrence_inventory",
                "expected_pose": expected_pose,
                "detected_poses": sorted({candidate.mechanism_pose for candidate in occurrences}),
                "physical_occurrence_ids": sorted(index),
                "contract_versions": sorted({candidate.mechanism_contract for candidate in occurrences}),
                "pass": (
                    len(occurrences) == 6
                    and set(index) == required_ids
                    and all(candidate.mechanism_pose == expected_pose for candidate in occurrences)
                    and all(candidate.mechanism_contract == FOOTREST_CONTRACT_VERSION for candidate in occurrences)
                    and all(candidate.identity_basis == "CONTROLLED_ID" for candidate in occurrences)
                ),
            }
        )

    identity_errors: list[dict[str, object]] = []
    reference = by_state["follow"]
    for occurrence_id in sorted(required_ids):
        base = reference.get(occurrence_id)
        if base is None:
            identity_errors.append({"physical_occurrence_id": occurrence_id, "error": "missing_reference"})
            continue
        for configuration in primary_sources[1:]:
            candidate = by_state[configuration].get(occurrence_id)
            if candidate is None:
                identity_errors.append(
                    {"physical_occurrence_id": occurrence_id, "configuration": configuration, "error": "missing"}
                )
                continue
            mismatches: list[str] = []
            if candidate.material != base.material:
                mismatches.append("material")
            if candidate.process != base.process:
                mismatches.append("process")
            if candidate.definition_revision != base.definition_revision:
                mismatches.append("definition_revision")
            if abs(candidate.volume_mm3 - base.volume_mm3) > 0.01:
                mismatches.append("volume")
            if abs(candidate.mass_kg - base.mass_kg) > 1.0e-9:
                mismatches.append("mass")
            if len(candidate.solid.Faces()) != len(base.solid.Faces()):
                mismatches.append("face_count")
            if len(candidate.solid.Edges()) != len(base.solid.Edges()):
                mismatches.append("edge_count")
            if mismatches:
                identity_errors.append(
                    {
                        "physical_occurrence_id": occurrence_id,
                        "configuration": configuration,
                        "mismatches": mismatches,
                    }
                )
    total_masses = {
        configuration: round(sum(candidate.mass_kg for candidate in index.values()), 9)
        for configuration, index in by_state.items()
    }
    checks.append(
        {
            "configuration": "follow/seat/cafe/desk",
            "check": "a08_cross_pose_definition_material_mass_conservation",
            "definition_revision": "E6R4-A",
            "total_mass_kg_by_state": total_masses,
            "identity_errors": identity_errors,
            "pass": not identity_errors and len(set(total_masses.values())) == 1,
        }
    )

    def exact_external_hits(moving: list[Part], stationary: list[Part]) -> list[dict[str, object]]:
        hits: list[dict[str, object]] = []
        for candidate in moving:
            for other in stationary:
                if not aabb_overlaps(candidate.shape, other.shape):
                    continue
                common = candidate.solid.intersect(other.solid)
                volume = 0.0 if common.isNull() else float(common.Volume())
                if volume > 0.01:
                    hits.append(
                        {
                            "moving": candidate.name,
                            "stationary": other.name,
                            "common_volume_mm3": round(volume, 6),
                        }
                    )
        return hits

    def exact_internal_hits(moving: list[Part]) -> list[dict[str, object]]:
        """Return hard A08 self-collisions, excluding a rail inside its own boot.

        The previous sweep gate only compared A08 with the rest of the product.
        That allowed a support to pass through the platform while the complete
        product still reported PASS.  A matching structural rail/boot pair is a
        deliberate nested enclosure; every other positive common volume is a
        hard mechanism collision until a real pocket or joint is authored.
        """

        nested_pairs = {
            frozenset(
                {
                    "WC-A08-SUPPORT-LEFT",
                    "WC-A08-SUPPORT-BOOT-LEFT",
                }
            ),
            frozenset(
                {
                    "WC-A08-SUPPORT-RIGHT",
                    "WC-A08-SUPPORT-BOOT-RIGHT",
                }
            ),
        }
        hits: list[dict[str, object]] = []
        moving_without_fixed_latch = [
            candidate
            for candidate in moving
            if candidate.physical_occurrence_id != "WC-A08-MANUAL-LATCH"
        ]
        for index, candidate in enumerate(moving_without_fixed_latch):
            for other in moving_without_fixed_latch[index + 1 :]:
                pair = frozenset(
                    {
                        candidate.physical_occurrence_id,
                        other.physical_occurrence_id,
                    }
                )
                if pair in nested_pairs:
                    continue
                if not aabb_overlaps(candidate.shape, other.shape):
                    continue
                common = candidate.solid.intersect(other.solid)
                volume = 0.0 if common.isNull() else float(common.Volume())
                if volume > 0.01:
                    hits.append(
                        {
                            "moving_a": candidate.name,
                            "moving_b": other.name,
                            "common_volume_mm3": round(volume, 6),
                        }
                    )
        return hits

    def rigid_arm_endpoints(candidate: Part) -> tuple[tuple[float, float, float], ...]:
        """Infer the two centre-line ends of the released straight A08 arm."""

        bounds = aabb(candidate.shape)
        center = (
            (bounds["xmin"] + bounds["xmax"]) / 2.0,
            (bounds["ymin"] + bounds["ymax"]) / 2.0,
            (bounds["zmin"] + bounds["zmax"]) / 2.0,
        )
        if (bounds["xmax"] - bounds["xmin"]) >= (
            bounds["zmax"] - bounds["zmin"]
        ):
            return (
                (bounds["xmin"], center[1], center[2]),
                (bounds["xmax"], center[1], center[2]),
            )
        return (
            (center[0], center[1], bounds["zmin"]),
            (center[0], center[1], bounds["zmax"]),
        )

    for configuration in ("cafe", "desk"):
        default_product = configs[configuration]
        stationary = [
            candidate
            for candidate in default_product
            if not candidate.name.startswith("footrest_")
        ]
        optional_open = build_configuration(
            configuration,
            FootrestPose.DEPLOYED_LOCKED,
        )
        endpoint_a08 = [
            candidate
            for candidate in optional_open
            if candidate.name.startswith("footrest_")
        ]
        endpoint_hits = exact_external_hits(endpoint_a08, stationary)
        checks.append(
            {
                "configuration": f"{configuration}_footrest_open",
                "check": "a08_optional_open_endpoint_external_clearance",
                "exact_interferences": endpoint_hits,
                "pass": not endpoint_hits,
            }
        )

        sweep_failures: list[dict[str, object]] = []
        for sample in range(21):
            progress = sample / 20.0
            hits = exact_external_hits(
                footrest_motion_parts(configuration, progress),
                stationary,
            )
            if hits:
                sweep_failures.append(
                    {"progress": progress, "exact_interferences": hits}
                )
        checks.append(
            {
                "configuration": f"{configuration}_footrest_open",
                "check": "a08_stow_to_open_21_point_swept_clearance",
                "sample_progress": [sample / 20.0 for sample in range(21)],
                "failures": sweep_failures,
                "pass": not sweep_failures,
            }
        )

        # Production-motion audit: use a 1 % increment and check both A08
        # self-clearance and the occupied feet-to-floor corridor.  This is
        # intentionally independent of the coarser legacy external sweep so a
        # future change cannot make the stronger evidence disappear by
        # relabelling the older check.
        dense_internal_failures: list[dict[str, object]] = []
        occupied_sweep_hits: list[dict[str, object]] = []
        floor_route = [
            candidate
            for candidate in human_envelope_parts(configuration)
            if candidate.name.startswith(("human_shin_", "human_foot_"))
        ]
        for sample in range(101):
            progress = sample / 100.0
            moving = footrest_motion_parts(configuration, progress)
            internal_hits = exact_internal_hits(moving)
            if internal_hits:
                dense_internal_failures.append(
                    {
                        "progress": progress,
                        "exact_interferences": internal_hits,
                    }
                )
            human_hits = exact_external_hits(moving, floor_route)
            if human_hits:
                occupied_sweep_hits.append(
                    {
                        "progress": progress,
                        "exact_interferences": human_hits,
                    }
                )

        checks.append(
            {
                "configuration": f"{configuration}_footrest_open",
                "check": "a08_stow_to_open_101_point_internal_clearance",
                "sample_progress": [sample / 100.0 for sample in range(101)],
                "failures": dense_internal_failures,
                "pass": not dense_internal_failures,
            }
        )

        # A seated Cafe/Focus user is allowed to keep their feet on the floor.
        # Therefore optional deployment needs a safety-rated foot-zone clear
        # input; the ordinary seat mat cannot prove that the shins and shoes
        # have left this sweep.  No such controlled occurrence exists today.
        sweep_clear_interlocks = sorted(
            candidate.name
            for candidate in default_product
            if candidate.name.startswith(
                (
                    "footrest_sweep_clear_interlock",
                    "foot_zone_safety_presence_sensor",
                )
            )
        )
        checks.append(
            {
                "configuration": f"{configuration}_footrest_open",
                "check": "a08_occupied_floor_route_requires_safety_rated_clear_interlock",
                "occupied_sweep_hit_samples": occupied_sweep_hits,
                "controlled_interlock_occurrences": sweep_clear_interlocks,
                "seat_occupancy_mat_is_sufficient": False,
                "pass": not occupied_sweep_hits or bool(sweep_clear_interlocks),
            }
        )

        # A rigid link can only rotate about a real fixed hinge if one of its
        # centre-line endpoints is invariant.  A captured linear guide is also
        # acceptable, but it must exist as a controlled physical occurrence.
        # Pure space interpolation with neither condition is not a load path.
        captured_guides = sorted(
            candidate.name
            for candidate in default_product
            if candidate.name.startswith(
                (
                    "footrest_captured_guide_",
                    "footrest_linear_carriage_",
                    "footrest_four_bar_",
                )
            )
        )
        endpoint_load_path: dict[str, object] = {}
        endpoint_load_path_pass = True
        for side_name in ("left", "right"):
            occurrence_id = f"WC-A08-SUPPORT-{side_name.upper()}"
            stowed_support = by_state[configuration][occurrence_id]
            deployed_support = next(
                candidate
                for candidate in endpoint_a08
                if candidate.physical_occurrence_id == occurrence_id
            )
            stowed_ends = rigid_arm_endpoints(stowed_support)
            deployed_ends = rigid_arm_endpoints(deployed_support)
            minimum_endpoint_drift = min(
                math.dist(stowed_end, deployed_end)
                for stowed_end in stowed_ends
                for deployed_end in deployed_ends
            )
            side_pass = minimum_endpoint_drift <= 0.1 or bool(captured_guides)
            endpoint_load_path_pass = endpoint_load_path_pass and side_pass
            endpoint_load_path[side_name] = {
                "stowed_endpoints_mm": stowed_ends,
                "deployed_endpoints_mm": deployed_ends,
                "minimum_endpoint_drift_mm": round(minimum_endpoint_drift, 6),
                "fixed_hinge_endpoint_present": minimum_endpoint_drift <= 0.1,
                "pass": side_pass,
            }
        checks.append(
            {
                "configuration": f"{configuration}_footrest_open",
                "check": "a08_support_fixed_hinge_or_captured_guide_load_path",
                "side_evidence": endpoint_load_path,
                "captured_guide_occurrences": captured_guides,
                "pass": endpoint_load_path_pass,
            }
        )

        floor_route = [
            candidate
            for candidate in human_envelope_parts(configuration)
            if candidate.name.startswith(("human_shin_", "human_foot_"))
        ]
        floor_hits = exact_external_hits(floor_route, default_product)
        foot_bounds = [
            aabb(candidate.shape)
            for candidate in floor_route
            if candidate.name.startswith("human_foot_")
        ]
        checks.append(
            {
                "configuration": configuration,
                "check": "occupied_feet_to_floor_route_with_a08_stowed",
                "exact_interferences": floor_hits,
                "foot_ground_zmin_mm": [round(bounds["zmin"], 6) for bounds in foot_bounds],
                "pass": (
                    not floor_hits
                    and len(foot_bounds) == 2
                    and all(abs(bounds["zmin"]) <= 1.0e-6 for bounds in foot_bounds)
                ),
            }
        )
    return checks


def validate(configs: dict[str, list[Part]]) -> dict:
    checks = []
    for config, parts in configs.items():
        for p in parts:
            valid = bool(p.solid.isValid())
            checks.append({"configuration": config, "check": f"solid_valid:{p.name}", "pass": valid})

    checks.extend(validate_footrest_contract(configs))

    stowed = {p.name: p for p in configs["stowed"]}
    lower = stowed["lower_body_enclosure"].shape
    for wheel_name in ("tyre_front_left", "tyre_front_right", "tyre_rear_left", "tyre_rear_right"):
        clearance = gap_y(lower, stowed[wheel_name].shape)
        checks.append(
            {
                "configuration": "stowed",
                "check": f"wheel_running_clearance:{wheel_name}",
                "actual_mm": round(clearance, 3),
                "required_mm": P.wheel_running_clearance,
                "pass": clearance >= P.wheel_running_clearance,
            }
        )

    for side_name in ("left", "right"):
        rocker_clearance = stowed[f"suspension_rocker_{side_name}"].solid.distance(lower.val())
        checks.append(
            {
                "configuration": "stowed",
                "check": f"suspension_rocker_body_clearance:{side_name}",
                "actual_mm": round(float(rocker_clearance), 3),
                "minimum_mm": 3.0,
                "pass": rocker_clearance >= 3.0 - 1e-6,
            }
        )

    # P0 production gate: every lower/upper drawer member is swept through its
    # full travel while the wheel rocker is sampled through both articulation
    # limits.  Static screenshots cannot substitute for this check.
    rocker_x = (P.wheel_x_front + P.wheel_x_rear) / 2.0
    articulation_angles = (-P.rocker_articulation_deg, -5.0, 0.0, 5.0, P.rocker_articulation_deg)
    for side, side_name in ((-1, "left"), (1, "right")):
        running_gear = [
            candidate
            for candidate in configs["stowed"]
            if side_name in candidate.name
            and candidate.name.startswith(
                (
                    "tyre_",
                    "hub_",
                    "axle_",
                    "suspension_rocker_",
                    "suspension_centre_pivot_",
                    "suspension_elastomer_stop_",
                    "wheel_arch_side_fairing_",
                )
            )
        ]
        for tier_name, travel in (("upper", P.laptop_slide_travel),):
            drawer_members = [
                candidate
                for candidate in configs["stowed"]
                if f"_{side_name}_{tier_name}" in candidate.name
                and candidate.name.startswith(("drawer_tray_", "drawer_front_", "cots_slide_", "cots_latch_"))
            ]
            minimum_clearance = math.inf
            worst_case = None
            collisions = []
            for angle in articulation_angles:
                transformed_gear = []
                for gear in running_gear:
                    rotating = gear.name.startswith(("tyre_", "hub_", "axle_", "suspension_rocker_"))
                    gear_shape = (
                        rotate_about_y(
                            gear.shape,
                            (rocker_x, 0, P.wheel_center_z),
                            angle,
                        )
                        if rotating and abs(angle) > 1e-9
                        else gear.shape
                    )
                    transformed_gear.append((gear.name, gear_shape))
                for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                    displacement = side * travel * fraction
                    for member in drawer_members:
                        moved = member.shape.translate((0, displacement, 0))
                        for gear_name, gear_shape in transformed_gear:
                            if aabb_overlaps(moved, gear_shape):
                                volume = float(moved.val().intersect(gear_shape.val()).Volume())
                                if volume > 0.1:
                                    collisions.append(
                                        {
                                            "drawer": member.name,
                                            "running_gear": gear_name,
                                            "angle_deg": angle,
                                            "travel_fraction": fraction,
                                            "intersection_volume_mm3": round(volume, 3),
                                        }
                                    )
                                    continue
                            distance = float(moved.val().distance(gear_shape.val()))
                            if distance < minimum_clearance:
                                minimum_clearance = distance
                                worst_case = {
                                    "drawer": member.name,
                                    "running_gear": gear_name,
                                    "angle_deg": angle,
                                    "travel_fraction": fraction,
                                }
            checks.append(
                {
                    "configuration": "drawer_motion_and_suspension_sweep",
                    "check": f"drawer_running_gear_swept_clearance:{side_name}:{tier_name}",
                    "samples": len(articulation_angles) * 5,
                    "actual_mm": round(float(minimum_clearance), 3),
                    "minimum_mm": P.drawer_dynamic_clearance,
                    "worst_case": worst_case,
                    "collisions": collisions,
                    "pass": not collisions and minimum_clearance >= P.drawer_dynamic_clearance,
                }
            )

    # Telescopic engagement at full extension.
    checks.append(
        {
            "configuration": "deployed",
            "check": "mast_minimum_overlap",
            "actual_mm": P.mast_overlap_deployed,
            "required_mm": 120.0,
            "pass": P.mast_overlap_deployed >= 120.0,
        }
    )

    # Human-factors checks.  These are design checks, not a substitute for user trials.
    seat_top = P.seat_z + P.seat_height / 2
    ux_checks = [
        ("seat_top_height", seat_top, 381.0, 559.0),
        ("seat_usable_depth", P.seat_usable_depth, 381.0, 432.0),
        ("seat_width", P.seat_width, 457.0, math.inf),
        ("armrest_height_above_seat", P.armrest_top_z - seat_top, 178.0, 267.0),
        ("desk_surface_height", P.table_surface_z, 559.0, 762.0),
    ]
    for name, actual, minimum, maximum in ux_checks:
        checks.append(
            {
                "configuration": "both",
                "check": f"human_factors:{name}",
                "actual_mm": round(actual, 3),
                "minimum_mm": minimum,
                "maximum_mm": None if math.isinf(maximum) else maximum,
                "pass": actual >= minimum and actual <= maximum,
            }
        )

    overall = {}
    # v37 claim is checked across the sweep, not trusted as a source-code comment.
    back_envelope = tapered_back(P.back_width, 300.0, P.back_height, P.back_thickness)
    sweep_distances = []
    for i in range(40):
        angle = -95.0 * i / 39
        swept = rotate_about_y(back_envelope, (P.back_hinge_x, 0, P.back_hinge_z), angle)
        sweep_distances.append(
            min(
                swept.val().distance(stowed["armrest_shell_left"].solid),
                swept.val().distance(stowed["armrest_shell_right"].solid),
                swept.val().distance(stowed["armrest_base_shell_left"].solid),
                swept.val().distance(stowed["armrest_base_shell_right"].solid),
            )
        )
    minimum_sweep_clearance = min(sweep_distances)
    checks.append(
        {
            "configuration": "folded_sweep",
            "check": "back_armrest_swept_clearance",
            "actual_mm": round(float(minimum_sweep_clearance), 3),
            "required_mm": 8.0,
            "samples": 40,
            "pass": minimum_sweep_clearance >= 8.0,
        }
    )
    folded_back = rotate_about_y(back_envelope, (P.back_hinge_x, 0, P.back_hinge_z), -95.0)
    for side_name in ("left", "right"):
        for segment_name in ("armrest_shell", "armrest_base_shell"):
            common_volume = folded_back.val().intersect(
                stowed[f"{segment_name}_{side_name}"].solid
            ).Volume()
            checks.append(
                {
                    "configuration": "folded_sweep",
                    "check": f"back_{segment_name}_no_intersection:{side_name}",
                    "intersection_volume_mm3": round(float(common_volume), 3),
                    "pass": common_volume < 0.1,
                }
            )

    mass_limits = [
        ("lower_body_enclosure", 20.0),
        ("upper_deck_panel", 8.0),
        ("backrest_structural_carrier", 10.0),
    ]
    for name, maximum in mass_limits:
        candidate = stowed[name]
        checks.append(
            {
                "configuration": "both",
                "check": f"mass_budget:{name}",
                "actual_kg": round(candidate.mass_kg, 4),
                "maximum_kg": maximum,
                "pass": candidate.mass_kg <= maximum,
            }
        )

    # Packaging groups: report the worst unintended overlap instead of hiding it in a render.
    module_names = {
        "battery_lfp_16s30ah_1p536kwh",
        "compute_core_cartridge",
        "encrypted_data_vault",
        "communications_5g_wifi_uwb_module",
        "power_distribution_unit",
        "drive_imu_controller",
        "safety_backup_battery_24v60wh",
    }
    modules = [p for p in configs["stowed"] if p.name in module_names]
    module_pair_overlaps = []
    module_pair_clearances = []
    for index, module in enumerate(modules):
        for candidate in modules[index + 1 :]:
            volume = float(module.solid.intersect(candidate.solid).Volume())
            distance = float(module.solid.distance(candidate.solid))
            if volume > 0.1:
                module_pair_overlaps.append(
                    {"a": module.name, "b": candidate.name, "volume_mm3": volume}
                )
            module_pair_clearances.append(
                {"a": module.name, "b": candidate.name, "clearance_mm": round(distance, 3)}
            )
    checks.append(
        {
            "configuration": "stowed",
            "check": "internal_module_pair_no_intersection",
            "overlaps": module_pair_overlaps,
            "clearances": module_pair_clearances,
            "pass": not module_pair_overlaps,
        }
    )
    minimum_module_clearance = min(item["clearance_mm"] for item in module_pair_clearances)
    checks.append(
        {
            "configuration": "stowed",
            "check": "internal_module_pair_minimum_service_clearance",
            "actual_mm": minimum_module_clearance,
            "minimum_mm": 5.0,
            "pass": minimum_module_clearance >= 5.0,
        }
    )
    moving_storage = [
        p
        for p in configs["stowed"]
        if p.name.startswith(("chassis_", "drawer_tray_", "cots_slide_", "cots_latch_"))
    ]
    overlaps = []
    for module in modules:
        for candidate in moving_storage:
            volume = float(module.solid.intersect(candidate.solid).Volume())
            if volume > 0.1:
                overlaps.append({"a": module.name, "b": candidate.name, "volume_mm3": volume})
    checks.append(
        {
            "configuration": "stowed",
            "check": "internal_modules_vs_chassis_and_drawers",
            "overlaps": overlaps,
            "pass": not overlaps,
        }
    )

    device_envelopes = (
        ("right", "laptop_16in_keepout_right", [P.laptop_envelope_length, P.laptop_envelope_depth, P.laptop_envelope_height]),
        ("left", "universal_flat_device_keepout_left", [330.0, 230.0, 30.0]),
    )
    for side_name, device_name, envelope_mm in device_envelopes:
        device = stowed[device_name]
        tray = stowed[f"drawer_tray_{side_name}_upper"]
        front = stowed[f"drawer_front_{side_name}_upper"]
        tray_intersection = float(device.solid.intersect(tray.solid).Volume())
        front_intersection = float(device.solid.intersect(front.solid).Volume())
        tray_clearance = float(device.solid.distance(tray.solid))
        front_clearance = float(device.solid.distance(front.solid))
        checks.append(
            {
                "configuration": "stowed",
                "check": f"device_envelope_fits_upper_bay:{side_name}",
                "device": device_name,
                "envelope_mm": envelope_mm,
                "tray_clearance_mm": round(tray_clearance, 3),
                "front_clearance_mm": round(front_clearance, 3),
                "intersection_volume_mm3": round(tray_intersection + front_intersection, 3),
                "minimum_clearance_mm": 8.0,
                "pass": tray_intersection < 0.1
                and front_intersection < 0.1
                and tray_clearance >= 8.0
                and front_clearance >= 8.0,
            }
        )

    caddy_net_l = (330.0 - 3.0) * (220.0 - 3.0) * (70.0 - 1.5) / 1_000_000.0
    checks.append(
        {
            "configuration": "stowed",
            "check": "independent_daily_caddy_capacity",
            "actual_l": round(caddy_net_l, 3),
            "minimum_l": 4.5,
            "pass": caddy_net_l >= 4.5,
        }
    )

    front_overlaps = []
    shells = [stowed["lower_body_enclosure"], stowed["upper_deck_panel"]]
    for front in [p for p in configs["stowed"] if p.name.startswith("drawer_front_")]:
        for shell in shells:
            volume = float(front.solid.intersect(shell.solid).Volume())
            if volume > 0.1:
                front_overlaps.append({"a": front.name, "b": shell.name, "volume_mm3": volume})
    checks.append(
        {
            "configuration": "stowed",
            "check": "drawer_fronts_vs_cut_apertures",
            "overlaps": front_overlaps,
            "pass": not front_overlaps,
        }
    )

    mast_clearance_x = (P.mast_outer_depth - 10 - P.mast_inner_depth) / 2 - P.mast_guide_pad_thickness
    mast_clearance_y = (P.mast_outer_width - 10 - P.mast_inner_width) / 2 - P.mast_guide_pad_thickness
    for axis, actual in (("x", mast_clearance_x), ("y", mast_clearance_y)):
        checks.append(
            {
                "configuration": "both",
                "check": f"mast_running_clearance_{axis}",
                "actual_mm": actual,
                "minimum_mm": 1.0,
                "pass": actual >= 1.0,
            }
        )

    canopy_pack_required = 4 * P.canopy_arm_height + 2 * P.moving_clearance
    canopy_pack_available = P.outdoor_package_cassette_height - 2 * P.beam_wall
    checks.append(
        {
            "configuration": "stowed",
            "check": "canopy_arm_stack_fits_beam_cavity",
            "required_mm": canopy_pack_required,
            "available_mm": canopy_pack_available,
            "pass": canopy_pack_required <= canopy_pack_available,
        }
    )
    roller_motor_radial_clearance = P.roller_id / 2 - 12.5
    checks.append(
        {
            "configuration": "both",
            "check": "roller_motor_radial_clearance",
            "actual_mm": roller_motor_radial_clearance,
            "minimum_mm": 3.0,
            "pass": roller_motor_radial_clearance >= 3.0,
        }
    )

    desk = {p.name: p for p in configs["desk"]}
    panel_gap = gap_y(desk["desk_panel_left"].shape, desk["desk_panel_right"].shape)
    checks.append(
        {
            "configuration": "desk",
            "check": "desk_halves_centre_gap",
            "actual_mm": round(panel_gap, 3),
            "minimum_mm": 10.0,
            "maximum_mm": 20.0,
            "pass": panel_gap >= 10.0 and panel_gap <= 20.0,
        }
    )
    for side_name in ("left", "right"):
        panel = desk[f"desk_panel_{side_name}"]
        lid = desk[f"armrest_lid_{side_name}"]
        intersection = panel.solid.intersect(lid.solid).Volume()
        panel_lid_clearance = panel.solid.distance(lid.solid)
        checks.append(
            {
                "configuration": "desk",
                "check": f"closed_lid_panel_clearance:{side_name}",
                "intersection_volume_mm3": round(float(intersection), 3),
                "actual_mm": round(float(panel_lid_clearance), 3),
                "minimum_mm": 8.0,
                "pass": intersection < 0.1 and panel_lid_clearance >= 8.0,
            }
        )
        carriage = desk[f"desk_forward_carriage_{side_name}"]
        carriage_lid_clearance = carriage.solid.distance(lid.solid)
        checks.append(
            {
                "configuration": "desk",
                "check": f"closed_lid_carriage_clearance:{side_name}",
                "actual_mm": round(float(carriage_lid_clearance), 3),
                "minimum_mm": 8.0,
                "pass": carriage_lid_clearance >= 8.0,
            }
        )
        lid_box = aabb(lid.shape)
        checks.append(
            {
                "configuration": "desk",
                "check": f"armrest_lid_closed_final_position:{side_name}",
                "actual_top_z_mm": round(lid_box["zmax"], 3),
                "required_top_z_mm": P.armrest_top_z,
                "pass": abs(lid_box["zmax"] - P.armrest_top_z) < 0.01,
            }
        )
        checks.append(
            {
                "configuration": "desk",
                "check": f"desk_panel_mass:{side_name}",
                "actual_kg": round(panel.mass_kg, 4),
                "maximum_kg": 1.5,
                "pass": panel.mass_kg <= 1.5,
            }
        )

    # Primary controls remain reachable outside the work surface plan and the
    # emergency stop is a physically separate channel.  This is a package
    # check only; operating force and usability are DVP&R gates.
    desk_panels = [desk["desk_panel_left"].solid, desk["desk_panel_right"].solid]
    for control_name in (
        "hmi_drive_control_pod_right",
        "hmi_joystick_right",
        "hmi_drive_authorization_key_right",
        "hmi_status_display_left",
        "hmi_qi2_charging_coil_left",
        "hmi_emergency_stop_guard",
        "hmi_mechanical_emergency_stop",
    ):
        control = desk[control_name].solid
        intersection = sum(float(control.intersect(panel).Volume()) for panel in desk_panels)
        clearance = min(float(control.distance(panel)) for panel in desk_panels)
        checks.append(
            {
                "configuration": "desk",
                "check": f"hmi_outside_desk_sweep:{control_name}",
                "intersection_volume_mm3": round(intersection, 3),
                "actual_clearance_mm": round(clearance, 3),
                "minimum_clearance_mm": 20.0,
                "pass": intersection < 0.1 and clearance >= 20.0,
            }
        )

    # v37 feature-retention checks: asymmetric armrest controls and the rear
    # obstacle-assist pull handle must be real solids in the review/BOM, not
    # annotations.  Functional force, temperature and fatigue remain DVP&R gates.
    seat_ready = {p.name: p for p in configs["seat"]}
    required_armrest_accessories = (
        "hmi_drive_control_pod_right",
        "hmi_joystick_right",
        "hmi_drive_authorization_key_right",
        "hmi_status_display_left",
        "hmi_qi2_charging_coil_left",
        "hmi_qi2_power_fod_module_left",
        "hmi_qi2_presence_temperature_sensor_left",
    )
    checks.append(
        {
            "configuration": "seat",
            "check": "v37_asymmetric_armrest_accessories_present",
            "required_parts": list(required_armrest_accessories),
            "missing_parts": [name for name in required_armrest_accessories if name not in seat_ready],
            "pass": all(name in seat_ready for name in required_armrest_accessories),
        }
    )
    follow_ready = {p.name: p for p in configs["follow"]}
    required_follow_suite = (
        "follow_front_tof_left_module",
        "follow_front_tof_left_window",
        "follow_front_tof_right_module",
        "follow_front_tof_right_window",
        "follow_leg_scanner_module",
        "follow_leg_scanner_window",
        "follow_rear_tof_module",
        "follow_rear_tof_window",
        "follow_side_ultrasonic_module_front_left",
        "follow_side_ultrasonic_face_front_left",
        "follow_side_ultrasonic_module_front_right",
        "follow_side_ultrasonic_face_front_right",
        "follow_side_ultrasonic_module_rear_left",
        "follow_side_ultrasonic_face_rear_left",
        "follow_side_ultrasonic_module_rear_right",
        "follow_side_ultrasonic_face_rear_right",
        "follow_uwb_side_module_left",
        "follow_uwb_side_radome_left",
        "follow_uwb_side_module_right",
        "follow_uwb_side_radome_right",
        "follow_uwb_rear_module",
        "follow_uwb_rear_radome",
        "follow_voice_mic_strip_left",
        "follow_voice_mic_strip_right",
        "follow_voice_acoustic_slot_left_1",
        "follow_voice_acoustic_slot_left_2",
        "follow_voice_acoustic_slot_right_1",
        "follow_voice_acoustic_slot_right_2",
        "follow_cliff_ir_module_front_left",
        "follow_cliff_ir_window_front_left",
        "follow_cliff_ir_module_front_right",
        "follow_cliff_ir_window_front_right",
        "follow_cliff_ir_module_rear_left",
        "follow_cliff_ir_window_rear_left",
        "follow_cliff_ir_module_rear_right",
        "follow_cliff_ir_window_rear_right",
        "follow_front_tactile_bumper_membrane",
        "follow_hidden_backrest_antenna_left",
        "follow_hidden_backrest_antenna_right",
    )
    checks.append(
        {
            "configuration": "follow",
            "check": "v37_folded_follow_sensor_suite_present",
            "required_parts": list(required_follow_suite),
            "missing_parts": [name for name in required_follow_suite if name not in follow_ready],
            "pass": all(name in follow_ready for name in required_follow_suite),
        }
    )
    base_navigation_parts = [
        candidate
        for name, candidate in follow_ready.items()
        if name.startswith("follow_")
        and not name.startswith(("follow_hidden_", "follow_voice_"))
    ]
    highest_base_sensor_z = max(aabb(candidate.shape)["zmax"] for candidate in base_navigation_parts)
    checks.append(
        {
            "configuration": "follow",
            "check": "follow_navigation_sensors_remain_below_fold_line",
            "highest_sensor_z_mm": round(highest_base_sensor_z, 3),
            "maximum_mm": 470.0,
            "pass": highest_base_sensor_z <= 470.0,
        }
    )
    checks.append(
        {
            "configuration": "follow",
            "check": "drive_controls_present_but_stowed_below_fold_line",
            "joystick_present": "hmi_joystick_right" in follow_ready,
            "authorization_key_present": "hmi_drive_authorization_key_right" in follow_ready,
            "joystick_top_z_mm": round(aabb(follow_ready["hmi_joystick_right"].shape)["zmax"], 3),
            "authorization_key_top_z_mm": round(
                aabb(follow_ready["hmi_drive_authorization_key_right"].shape)["zmax"], 3
            ),
            "maximum_stowed_top_z_mm": 500.0,
            "pass": (
                aabb(follow_ready["hmi_joystick_right"].shape)["zmax"] < 500.0
                and aabb(follow_ready["hmi_drive_authorization_key_right"].shape)["zmax"] < 500.0
            ),
        }
    )
    required_local_weather_parts = (
        "travel_front_tpe_water_lip",
        "travel_side_tpe_seal_drain_left",
        "travel_side_tpe_seal_drain_right",
        "travel_hinge_local_weather_bridge",
    )
    checks.append(
        {
            "configuration": "follow",
            "check": "folded_back_is_weather_cover_without_false_outer_cap",
            "legacy_cap_present": "travel_cap_closed_surface" in follow_ready,
            "missing_local_weather_parts": [
                name for name in required_local_weather_parts if name not in follow_ready
            ],
            "pass": (
                "travel_cap_closed_surface" not in follow_ready
                and all(name in follow_ready for name in required_local_weather_parts)
            ),
        }
    )
    folded_rigid_weather_targets = [
        candidate.solid
        for name, candidate in follow_ready.items()
        if name.startswith(("backrest_", "mast_", "sensor_beam_", "obstacle_handle_"))
    ]
    hinge_bridge = follow_ready["travel_hinge_local_weather_bridge"].solid
    hinge_bridge_intersections = [
        float(hinge_bridge.intersect(target).Volume())
        for target in folded_rigid_weather_targets
    ]
    checks.append(
        {
            "configuration": "follow",
            "check": "local_hinge_weather_bridge_zero_rigid_interference",
            "maximum_intersection_volume_mm3": round(max(hinge_bridge_intersections), 3),
            "pass": max(hinge_bridge_intersections) < 0.1,
        }
    )
    display_box = aabb(seat_ready["hmi_status_display_left"].shape)
    qi_box = aabb(seat_ready["hmi_qi2_charging_coil_left"].shape)
    checks.append(
        {
            "configuration": "seat",
            "check": "left_display_and_qi_remain_on_armrest_surface",
            "display_top_z_mm": round(display_box["zmax"], 3),
            "qi_top_z_mm": round(qi_box["zmax"], 3),
            "armrest_top_z_mm": P.armrest_top_z,
            "maximum_accessory_top_z_mm": 690.0,
            "pass": (
                display_box["zmax"] >= P.armrest_top_z + 6.0
                and display_box["zmax"] <= 690.0
                and qi_box["zmin"] >= P.armrest_top_z
                and qi_box["zmax"] <= 690.0
            ),
        }
    )

    stowed_map = {p.name: p for p in configs["stowed"]}
    obstacle_map = {p.name: p for p in configs["obstacle"]}
    stowed_bar = stowed_map["obstacle_handle_crossbar_stowed"]
    extended_bar = obstacle_map["obstacle_handle_crossbar_extended"]
    stowed_bar_box = aabb(stowed_bar.shape)
    extended_bar_box = aabb(extended_bar.shape)
    checks.extend(
        [
            {
                "configuration": "stowed",
                "check": "obstacle_handle_crossbar_latched_below_stow_limit",
                "actual_top_z_mm": round(stowed_bar_box["zmax"], 3),
                "maximum_top_z_mm": 500.0,
                "pass": stowed_bar_box["zmax"] <= 500.0,
            },
            {
                "configuration": "obstacle",
                "check": "obstacle_handle_extended_operating_height",
                "actual_top_z_mm": round(extended_bar_box["zmax"], 3),
                "minimum_top_z_mm": 1320.0,
                "pass": extended_bar_box["zmax"] >= 1320.0,
            },
            {
                "configuration": "obstacle",
                "check": "obstacle_assist_front_lift_angle",
                "actual_deg": P.obstacle_handle_tilt_deg,
                "required_deg": 8.0,
                "pass": abs(P.obstacle_handle_tilt_deg - 8.0) < 1e-9,
            },
        ]
    )

    # E6 human-centred verification. A mass point is not a person: the occupied
    # volume and the two-stage desk path are checked as real solids.
    human = {candidate.name: candidate for candidate in human_envelope_parts()}
    torso = human["human_torso_keepout"].solid
    pelvis = human["human_pelvis_keepout"].solid
    head = human["human_head_keepout"].solid

    cafe = {candidate.name: candidate for candidate in configs["cafe"]}
    cafe_panel = cafe["desk_panel_right"]
    cafe_panel_box = aabb(cafe_panel.shape)
    cafe_panel_depth = cafe_panel_box["xmax"] - cafe_panel_box["xmin"]
    cafe_panel_width = cafe_panel_box["ymax"] - cafe_panel_box["ymin"]
    checks.append(
        {
            "configuration": "cafe",
            "check": "single_panel_rotated_transverse_430_by_270",
            "depth_x_mm": round(cafe_panel_depth, 3),
            "width_y_mm": round(cafe_panel_width, 3),
            "target_depth_mm": P.table_half_width,
            "target_width_mm": P.table_length,
            "pass": (
                abs(cafe_panel_depth - P.table_half_width) < 0.1
                and abs(cafe_panel_width - P.table_length) < 0.1
            ),
        }
    )
    required_cafe_mechanism = (
        "desk_cafe_rotation_bearing_right",
        "desk_cafe_rotation_index_plate_right",
        "desk_cafe_rotation_lock_pin_right",
        "desk_cafe_translation_rail_right",
        "desk_cafe_underdeck_spine_right",
        "desk_cafe_translation_lock_right",
        "desk_leaf_fold_hinge_right",
        "desk_leaf_rigidizer_right_1",
        "desk_leaf_rigidizer_right_2",
        "desk_bundle_stowed_left",
    )
    checks.append(
        {
            "configuration": "cafe",
            "check": "cafe_rotation_translation_positive_lock_hardware_present",
            "missing_parts": [name for name in required_cafe_mechanism if name not in cafe],
            "pass": all(name in cafe for name in required_cafe_mechanism),
        }
    )
    checks.append(
        {
            "configuration": "cafe",
            "check": "drive_pod_parked_before_cafe_table_motion",
            "joystick_present": "hmi_joystick_right" in cafe,
            "authorization_key_present": "hmi_drive_authorization_key_right" in cafe,
            "pod_top_z_mm": round(aabb(cafe["hmi_drive_control_pod_right"].shape)["zmax"], 3),
            "joystick_top_z_mm": round(aabb(cafe["hmi_joystick_right"].shape)["zmax"], 3),
            "authorization_key_top_z_mm": round(
                aabb(cafe["hmi_drive_authorization_key_right"].shape)["zmax"], 3
            ),
            "pass": (
                aabb(cafe["hmi_drive_control_pod_right"].shape)["zmax"] < 500.0
                and aabb(cafe["hmi_joystick_right"].shape)["zmax"] < 500.0
                and aabb(cafe["hmi_drive_authorization_key_right"].shape)["zmax"] < 500.0
            ),
        }
    )

    cafe_panel_y = P.table_centre_safety_gap / 2 + P.table_half_width / 2
    cafe_rotation_panel = rounded_box(
        P.table_length,
        P.table_half_width,
        P.table_thickness,
        8,
    ).translate(
        (
            P.cafe_rotation_clearance_x,
            cafe_panel_y,
            P.table_surface_z - P.table_thickness / 2,
        )
    )
    cafe_rotation_origin = (
        P.cafe_rotation_clearance_x,
        cafe_panel_y,
        P.table_surface_z - P.table_thickness / 2,
    )
    cafe_rotation_clearances = []
    for angle in range(0, -int(P.cafe_rotation_deg) - 1, -5):
        rotated = rotate_about_z(cafe_rotation_panel, cafe_rotation_origin, float(angle)).val()
        cafe_rotation_clearances.append(min(rotated.distance(torso), rotated.distance(pelvis)))
    minimum_cafe_rotation_clearance = min(cafe_rotation_clearances)
    checks.append(
        {
            "configuration": "cafe_motion_occupied",
            "check": "cafe_forward_clear_rotate_sweep_to_occupant_core",
            "actual_mm": round(float(minimum_cafe_rotation_clearance), 3),
            "minimum_mm": P.occupant_table_body_clearance,
            "samples": len(cafe_rotation_clearances),
            "pass": minimum_cafe_rotation_clearance >= P.occupant_table_body_clearance,
        }
    )
    cafe_final_core_clearance = min(cafe_panel.solid.distance(torso), cafe_panel.solid.distance(pelvis))
    cafe_final_thigh_clearance = min(
        cafe_panel.solid.distance(human[f"human_thigh_{side:+d}"].solid)
        for side in (-1, 1)
    )
    cafe_hmi_clearance = min(
        cafe_panel.solid.distance(cafe["hmi_status_display_left"].solid),
        cafe_panel.solid.distance(cafe["hmi_qi2_charging_coil_left"].solid),
    )
    cafe_right_lid_clearance = cafe_panel.solid.distance(cafe["armrest_lid_right"].solid)
    cafe_open_left_width = cafe_panel_box["ymin"] + P.armrest_outer_y
    checks.extend(
        [
            {
                "configuration": "cafe_occupied",
                "check": "cafe_transverse_panel_to_occupant_core",
                "actual_mm": round(float(cafe_final_core_clearance), 3),
                "minimum_mm": P.occupant_table_body_clearance,
                "pass": cafe_final_core_clearance >= P.occupant_table_body_clearance,
            },
            {
                "configuration": "cafe_occupied",
                "check": "cafe_transverse_panel_to_thighs",
                "actual_mm": round(float(cafe_final_thigh_clearance), 3),
                "minimum_mm": P.occupant_thigh_clearance,
                "pass": cafe_final_thigh_clearance >= P.occupant_thigh_clearance,
            },
            {
                "configuration": "cafe",
                "check": "cafe_left_display_qi_clearance",
                "actual_mm": round(float(cafe_hmi_clearance), 3),
                "minimum_mm": 50.0,
                "pass": cafe_hmi_clearance >= 50.0,
            },
            {
                "configuration": "cafe",
                "check": "cafe_panel_to_closed_right_armrest_lid",
                "actual_mm": round(float(cafe_right_lid_clearance), 3),
                "minimum_mm": 8.0,
                "pass": cafe_right_lid_clearance >= 8.0,
            },
            {
                "configuration": "cafe",
                "check": "cafe_left_social_open_band",
                "actual_mm": round(float(cafe_open_left_width), 3),
                "minimum_mm": 250.0,
                "pass": cafe_open_left_width >= 250.0,
            },
        ]
    )
    cafe_stowed_bundle_box = aabb(cafe["desk_bundle_stowed_left"].shape)
    checks.append(
        {
            "configuration": "cafe",
            "check": "honest_two_leaf_table_bundle_fits_armrest_bay",
            "actual_height_mm": round(
                cafe_stowed_bundle_box["zmax"] - cafe_stowed_bundle_box["zmin"], 3
            ),
            "required_height_mm": P.table_stowed_height,
            "bundle_top_z_mm": round(cafe_stowed_bundle_box["zmax"], 3),
            "armrest_lid_bottom_z_mm": P.armrest_top_z - 4.0,
            "pass": (
                abs(
                    (cafe_stowed_bundle_box["zmax"] - cafe_stowed_bundle_box["zmin"])
                    - P.table_stowed_height
                )
                < 0.1
                and cafe_stowed_bundle_box["zmax"] <= P.armrest_top_z - 4.0
            ),
        }
    )

    panels = [desk["desk_panel_left"].solid, desk["desk_panel_right"].solid]
    body_clearance = min(
        min(panel.distance(torso), panel.distance(pelvis))
        for panel in panels
    )
    checks.append(
        {
            "configuration": "desk_occupied",
            "check": "occupant_core_to_deployed_desk_clearance",
            "actual_mm": round(float(body_clearance), 3),
            "minimum_mm": P.occupant_table_body_clearance,
            "pass": body_clearance >= P.occupant_table_body_clearance,
        }
    )
    thigh_clearance = min(
        panel.distance(human[f"human_thigh_{side:+d}"].solid)
        for panel in panels
        for side in (-1, 1)
    )
    checks.append(
        {
            "configuration": "desk_occupied",
            "check": "occupant_thigh_to_desk_underside_clearance",
            "actual_mm": round(float(thigh_clearance), 3),
            "minimum_mm": P.occupant_thigh_clearance,
            "pass": thigh_clearance >= P.occupant_thigh_clearance,
        }
    )

    side_translation_sweeps = []
    sweep_xmin = min(P.table_stowed_x, P.table_x) - P.table_length / 2
    sweep_xmax = max(P.table_stowed_x, P.table_x) + P.table_length / 2
    for side in (-1, 1):
        sweep = cq.Workplane("XY").box(
            sweep_xmax - sweep_xmin,
            P.table_stowed_thickness,
            P.table_stowed_height,
        ).translate(
            (
                (sweep_xmin + sweep_xmax) / 2,
                side * P.table_stowed_y,
                P.armrest_top_z - P.table_stowed_height / 2 - 10,
            )
        )
        side_translation_sweeps.append(sweep.val())
    translation_clearance = min(
        min(sweep.distance(torso), sweep.distance(pelvis))
        for sweep in side_translation_sweeps
    )
    checks.append(
        {
            "configuration": "desk_motion_occupied",
            "check": "occupant_core_to_guarded_forward_translation_sweep",
            "actual_mm": round(float(translation_clearance), 3),
            "minimum_mm": P.occupant_armrest_side_clearance,
            "pass": translation_clearance >= P.occupant_armrest_side_clearance,
        }
    )
    unfold_sweep = cq.Workplane("XY").box(
        P.table_length,
        2 * P.table_half_width + P.table_centre_safety_gap,
        32,
    ).translate((P.table_x, 0, P.table_surface_z - 16))
    unfold_clearance = min(unfold_sweep.val().distance(torso), unfold_sweep.val().distance(pelvis))
    checks.append(
        {
            "configuration": "desk_motion_occupied",
            "check": "occupant_core_to_forward_unfold_sweep",
            "actual_mm": round(float(unfold_clearance), 3),
            "minimum_mm": P.occupant_table_body_clearance,
            "pass": unfold_clearance >= P.occupant_table_body_clearance,
        }
    )

    seat_ready = {p.name: p for p in configs["seat"]}
    seat_deck_overlap = seat_ready["seat_cushion_envelope"].solid.intersect(
        seat_ready["upper_deck_panel"].solid
    ).Volume()
    checks.append(
        {
            "configuration": "seat_occupied",
            "check": "seat_cushion_clear_recessed_upper_deck",
            "intersection_volume_mm3": round(float(seat_deck_overlap), 3),
            "pass": seat_deck_overlap < 0.1,
        }
    )

    # Secondary-user P0: the upper right armrest and its desk cassette swing
    # rearward/outboard, leaving an unobstructed side-transfer prism above the
    # cushion. The fixed base terminates below the seat top.
    transfer = {p.name: p for p in configs["transfer"]}
    transfer_keepout = cq.Workplane("XY").box(P.seat_length, 420, 330).translate(
        (P.seat_x, P.seat_width / 2 + 210, seat_top + 165)
    )
    transfer_overlaps = []
    for candidate_name in (
        "armrest_shell_right",
        "armrest_lid_right",
        "desk_bundle_stowed_right",
    ):
        volume = transfer_keepout.val().intersect(transfer[candidate_name].solid).Volume()
        if volume > 0.1:
            transfer_overlaps.append(
                {"part": candidate_name, "intersection_volume_mm3": round(float(volume), 3)}
            )
    checks.append(
        {
            "configuration": "transfer",
            "check": "right_side_transfer_keepout_clear",
            "transfer_keepout_mm": {"length_x": P.seat_length, "outboard_y": 420.0, "height_z": 330.0},
            "overlaps": transfer_overlaps,
            "pass": not transfer_overlaps,
        }
    )
    base_top = aabb(transfer["armrest_base_shell_right"].shape)["zmax"]
    checks.append(
        {
            "configuration": "transfer",
            "check": "fixed_armrest_base_below_seat_top",
            "actual_top_z_mm": round(base_top, 3),
            "seat_top_z_mm": seat_top,
            "pass": base_top <= seat_top,
        }
    )
    for side_name in ("left", "right"):
        for human_name in ("human_pelvis_keepout", "human_torso_keepout"):
            intersection = human[human_name].solid.intersect(seat_ready[f"armrest_shell_{side_name}"].solid).Volume()
            checks.append(
                {
                    "configuration": "seat_occupied",
                    "check": f"occupant_no_armrest_intrusion:{human_name}:{side_name}",
                    "intersection_volume_mm3": round(float(intersection), 3),
                    "pass": intersection < 0.1,
                }
            )
    shin_intrusion = sum(
        human[f"human_shin_{side:+d}"].solid.intersect(seat_ready["lower_body_enclosure"].solid).Volume()
        for side in (-1, 1)
    )
    checks.append(
        {
            "configuration": "seat_occupied",
            "check": "occupant_shins_clear_front_footwell",
            "intersection_volume_mm3": round(float(shin_intrusion), 3),
            "pass": shin_intrusion < 0.1,
        }
    )
    foot_intrusions = []
    for side in (-1, 1):
        foot = human[f"human_foot_{side:+d}"].solid
        for candidate_name in (
            "lower_body_enclosure",
            "tyre_front_left",
            "tyre_front_right",
        ):
            volume = foot.intersect(seat_ready[candidate_name].solid).Volume()
            if volume > 0.1:
                foot_intrusions.append(
                    {"foot": side, "part": candidate_name, "intersection_volume_mm3": float(volume)}
                )
    checks.append(
        {
            "configuration": "seat_occupied",
            "check": "occupant_feet_clear_body_and_front_wheels",
            "overlaps": foot_intrusions,
            "pass": not foot_intrusions,
        }
    )
    head_clearance = head.distance(seat_ready["sensor_beam_shell_stowed"].solid)
    checks.append(
        {
            "configuration": "seat_occupied",
            "check": "occupant_head_to_sensor_beam_clearance",
            "actual_mm": round(float(head_clearance), 3),
            "minimum_mm": 40.0,
            "pass": head_clearance >= 40.0,
        }
    )
    egress_width = 2 * P.armrest_inner_y
    checks.append(
        {
            "configuration": "seat_occupied",
            "check": "front_egress_clear_width",
            "actual_mm": egress_width,
            "minimum_mm": P.occupant_torso_width + 40.0,
            "pass": egress_width >= P.occupant_torso_width + 40.0,
        }
    )

    # Broad static audit across the user-visible configurations.  Every exact
    # solid overlap must either be absent or mapped to a named manufacturing
    # interface; the report never silently converts an unclassified clash into
    # a pass.
    for configuration in ("stowed", "follow", "seat", "cafe", "transfer", "desk", "deployed", "obstacle"):
        parts = configs[configuration]
        unexpected = []
        controlled_counts: dict[str, int] = {}
        controlled_interfaces = []
        exact_tests = 0
        for index, candidate in enumerate(parts):
            for other in parts[index + 1 :]:
                if not aabb_overlaps(candidate.shape, other.shape):
                    continue
                exact_tests += 1
                intersection = candidate.solid.intersect(other.solid)
                volume = float(intersection.Volume())
                if volume <= 0.1:
                    continue
                reason = controlled_overlap_reason(candidate.name, other.name, configuration)
                if reason:
                    controlled_counts[reason] = controlled_counts.get(reason, 0) + 1
                    intersection_bounds = intersection.BoundingBox()
                    controlled_interfaces.append(
                        {
                            "a": candidate.name,
                            "b": other.name,
                            "reason": reason,
                            "intersection_volume_mm3": round(volume, 3),
                            "intersection_bbox_mm": {
                                "x": round(intersection_bounds.xlen, 3),
                                "y": round(intersection_bounds.ylen, 3),
                                "z": round(intersection_bounds.zlen, 3),
                            },
                        }
                    )
                else:
                    unexpected.append(
                        {
                            "a": candidate.name,
                            "b": other.name,
                            "intersection_volume_mm3": round(volume, 3),
                        }
                    )
        checks.append(
            {
                "configuration": configuration,
                "check": f"production_static_unclassified_interference:{configuration}",
                "broad_phase_pairs": len(parts) * (len(parts) - 1) // 2,
                "exact_tests": exact_tests,
                "controlled_interface_counts": controlled_counts,
                "controlled_interfaces": controlled_interfaces,
                "unexpected_overlaps": unexpected,
                "pass": not unexpected,
            }
        )

    for config, parts in configs.items():
        boxes = [aabb(p.shape) for p in parts]
        overall[config] = {
            "length_x_mm": max(b["xmax"] for b in boxes) - min(b["xmin"] for b in boxes),
            "width_y_mm": max(b["ymax"] for b in boxes) - min(b["ymin"] for b in boxes),
            "height_z_mm": max(b["zmax"] for b in boxes) - min(0.0, min(b["zmin"] for b in boxes)),
        }
    return {"revision": "E6R2", "overall_envelopes": overall, "checks": checks}


def write_bom(configs: dict[str, list[Part]]) -> None:
    all_parts: dict[str, Part] = {}
    for parts in configs.values():
        for p in parts:
            all_parts[p.name] = p
    with (BUILD / "bom.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "part_number",
                "description",
                "configuration",
                "qty",
                "material",
                "process",
                "volume_mm3",
                "estimated_mass_kg",
                "vendor",
                "vendor_part_number",
                "maturity",
                "source_url",
            ]
        )
        for i, p in enumerate(sorted(all_parts.values(), key=lambda item: item.name), 1):
            writer.writerow(
                [
                    f"WC-E6-{i:03d}",
                    p.name,
                    p.configuration,
                    p.quantity,
                    p.material,
                    p.process,
                    f"{p.volume_mm3:.3f}",
                    f"{p.mass_kg:.4f}",
                    p.vendor,
                    p.vendor_part_number,
                    p.maturity,
                    p.source_url,
                ]
            )


def write_interface_register(configs: dict[str, list[Part]]) -> None:
    """Export one controlled envelope per non-custom supplier/interface item."""
    selected: dict[tuple[str, str], Part] = {}
    for parts in configs.values():
        for candidate in parts:
            if candidate.maturity == "custom":
                continue
            key = (candidate.vendor, candidate.vendor_part_number or candidate.name)
            selected.setdefault(key, candidate)

    with (BUILD / "cots_interface_register.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "representative_part",
                "vendor",
                "vendor_part_number_or_interface_id",
                "maturity",
                "envelope_x_mm",
                "envelope_y_mm",
                "envelope_z_mm",
                "estimated_mass_kg",
                "source_url",
            ]
        )
        for candidate in sorted(selected.values(), key=lambda item: (item.vendor, item.vendor_part_number)):
            box = aabb(candidate.shape)
            writer.writerow(
                [
                    candidate.name,
                    candidate.vendor,
                    candidate.vendor_part_number,
                    candidate.maturity,
                    f"{box['xmax'] - box['xmin']:.3f}",
                    f"{box['ymax'] - box['ymin']:.3f}",
                    f"{box['zmax'] - box['zmin']:.3f}",
                    f"{candidate.mass_kg:.4f}",
                    candidate.source_url,
                ]
            )


def write_tolerance_register(geometry_report: dict, engineering_report: dict) -> None:
    geometry = {check["check"]: check for check in geometry_report["checks"]}
    engineering = {check["check"]: check for check in engineering_report["checks"]}

    wheel = min(
        check["actual_mm"]
        for name, check in geometry.items()
        if name.startswith("wheel_running_clearance:")
    )
    rows = [
        (
            "wheel-to-body running clearance",
            "minimum",
            wheel,
            P.wheel_running_clearance,
            wheel - P.wheel_running_clearance,
            "Body skin is clearance-only; axle brackets reference chassis datums.",
        ),
        (
            "backrest swept clearance",
            "minimum",
            geometry["back_armrest_swept_clearance"]["actual_mm"],
            geometry["back_armrest_swept_clearance"]["required_mm"],
            geometry["back_armrest_swept_clearance"]["actual_mm"]
            - geometry["back_armrest_swept_clearance"]["required_mm"],
            "Retain fixed hinge datum; trim/chamfer replaceable armrest shell only.",
        ),
        (
            "mast guide running clearance X per side",
            "minimum",
            geometry["mast_running_clearance_x"]["actual_mm"],
            geometry["mast_running_clearance_x"]["minimum_mm"],
            geometry["mast_running_clearance_x"]["actual_mm"]
            - geometry["mast_running_clearance_x"]["minimum_mm"],
            "Select-fit POM guide-pad thickness; do not hand-grind mast tubes.",
        ),
        (
            "mast guide running clearance Y per side",
            "minimum",
            geometry["mast_running_clearance_y"]["actual_mm"],
            geometry["mast_running_clearance_y"]["minimum_mm"],
            geometry["mast_running_clearance_y"]["actual_mm"]
            - geometry["mast_running_clearance_y"]["minimum_mm"],
            "Select-fit POM guide-pad thickness; verify start force and free play.",
        ),
        (
            "canopy arm stack reserve",
            "minimum",
            geometry["canopy_arm_stack_fits_beam_cavity"]["available_mm"]
            - geometry["canopy_arm_stack_fits_beam_cavity"]["required_mm"],
            0.0,
            geometry["canopy_arm_stack_fits_beam_cavity"]["available_mm"]
            - geometry["canopy_arm_stack_fits_beam_cavity"]["required_mm"],
            "Adjust hard stops and removable lid; foam compression is not a stack solution.",
        ),
        (
            "roller-motor radial clearance",
            "minimum",
            geometry["roller_motor_radial_clearance"]["actual_mm"],
            geometry["roller_motor_radial_clearance"]["minimum_mm"],
            geometry["roller_motor_radial_clearance"]["actual_mm"]
            - geometry["roller_motor_radial_clearance"]["minimum_mm"],
            "Control motor OD and roller ID on the supplier interface drawing.",
        ),
        (
            "desk centre safety gap minimum",
            "minimum",
            geometry["desk_halves_centre_gap"]["actual_mm"],
            geometry["desk_halves_centre_gap"]["minimum_mm"],
            geometry["desk_halves_centre_gap"]["actual_mm"]
            - geometry["desk_halves_centre_gap"]["minimum_mm"],
            "Do not close the gap by filing hinges; retain rounded non-trapping edges.",
        ),
        (
            "desk centre safety gap maximum",
            "maximum",
            geometry["desk_halves_centre_gap"]["actual_mm"],
            geometry["desk_halves_centre_gap"]["maximum_mm"],
            geometry["desk_halves_centre_gap"]["maximum_mm"]
            - geometry["desk_halves_centre_gap"]["actual_mm"],
            "Adjust centre lock tongue; hinge datum must not be filed during assembly.",
        ),
        (
            "drawer bracket adjustment each side",
            "minimum",
            engineering["drawer_bracket_adjustment"]["actual_mm"],
            engineering["drawer_bracket_adjustment"]["minimum_mm"],
            engineering["drawer_bracket_adjustment"]["actual_mm"]
            - engineering["drawer_bracket_adjustment"]["minimum_mm"],
            "Use replaceable slotted rail bracket; cosmetic front is aligned last.",
        ),
    ]
    with (BUILD / "tolerance_register.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "interface",
                "limit_type",
                "actual_mm",
                "requirement_mm",
                "margin_mm",
                "status",
                "production_rework_control",
            ]
        )
        for interface, limit_type, actual, requirement, margin, control in rows:
            writer.writerow(
                [
                    interface,
                    limit_type,
                    f"{actual:.3f}",
                    f"{requirement:.3f}",
                    f"{margin:.3f}",
                    "PASS" if margin >= -1e-9 else "FAIL",
                    control,
                ]
            )


def write_review_html(
    geometry_report: dict,
    engineering_report: dict,
    mobility_report: dict,
    power_report: dict,
    readiness_report: dict,
) -> None:
    model_files = {
        "stowed": BUILD / "workcore_stowed.glb",
        "follow": BUILD / "workcore_follow_closed.glb",
        "obstacle": BUILD / "workcore_obstacle_assist.glb",
        "seat": BUILD / "workcore_seat_ready.glb",
        "cafe": BUILD / "workcore_cafe.glb",
        "internal": BUILD / "workcore_internal_layout.glb",
        "transfer": BUILD / "workcore_transfer_ready.glb",
        "desk": BUILD / "workcore_desk.glb",
        "occupied": BUILD / "workcore_desk_occupied_review.glb",
        "storage": BUILD / "workcore_storage_review.glb",
        "storage_wheel": BUILD / "workcore_storage_wheel_review.glb",
        "electrical": BUILD / "workcore_electrical_thermal_review.glb",
        "deployed": BUILD / "workcore_canopy_deployed.glb",
    }
    encoded = {name: base64.b64encode(path.read_bytes()).decode("ascii") for name, path in model_files.items()}
    three_vendor = ROOT / "cad" / "vendor" / "three-r128" / "package"
    three_js = (three_vendor / "build" / "three.min.js").read_text(encoding="utf-8")
    orbit_js = (three_vendor / "examples" / "js" / "controls" / "OrbitControls.js").read_text(
        encoding="utf-8"
    )
    gltf_js = (three_vendor / "examples" / "js" / "loaders" / "GLTFLoader.js").read_text(
        encoding="utf-8"
    )
    desk_stability = engineering_report["scenarios"]["desk_occupied_rated"]["stability"]
    all_checks = (
        geometry_report["checks"]
        + engineering_report["checks"]
        + mobility_report["checks"]
        + power_report["checks"]
    )
    failed_checks = [check for check in all_checks if not check["pass"]]
    solid_validity_checks = sum(
        str(check.get("check", "")).startswith("solid_valid:")
        for check in geometry_report["checks"]
    )
    drawer_sweep_checks = [
        check
        for check in geometry_report["checks"]
        if check["check"].startswith("drawer_running_gear_swept_clearance:")
    ]
    metrics = {
        "checks": len(all_checks),
        "passed_checks": len(all_checks) - len(failed_checks),
        "failed_checks": len(failed_checks),
        "solid_validity_checks": solid_validity_checks,
        "semantic_or_analytical_checks": len(all_checks) - solid_validity_checks,
        "drawer_min_clearance_mm": min(check["actual_mm"] for check in drawer_sweep_checks),
        "drawer_sweep_samples": sum(check["samples"] for check in drawer_sweep_checks),
        "stowed_mass_kg": engineering_report["scenarios"]["stowed_unoccupied"]["centre_of_mass"]["mass_kg"],
        "desk_tip_deg": min(
            desk_stability["front_tip_angle_deg"],
            desk_stability["rear_tip_angle_deg"],
            desk_stability["side_tip_angle_deg"],
        ),
        "wind_7_sf": engineering_report["wind"]["operational_tip_safety_factor"],
        "wind_20_sf": engineering_report["wind"]["structural_tip_safety_factor_without_retraction"],
        "retract_s": engineering_report["canopy_arm"]["theoretical_retract_time_s"],
        "turning_circle_mm": engineering_report["mobility"]["occupied_turning_circle_mm"],
        "obstacle_mm": P.rated_vertical_obstacle_mm,
        "stowed": mobility_report["stowed_envelope_mm"],
        "battery_kwh": power_report["energy"]["nominal_energy_wh"] / 1000.0,
        "community_runtime_h": power_report["mission_profiles"]["community_workday"]["estimated_runtime_h"],
        "mobile_peak_kw": power_report["traction"]["mobile_system_peak_w"] / 1000.0,
        "mast_power_w": sum(power_report["mast_loads_w"].values()),
        "thermal_airflow_cfm": power_report["thermal"]["zones"]["electronics"]["required_airflow_with_margin_cfm"],
        "production_evidence_percent": readiness_report["production_evidence_index_percent"],
        "production_p0_open": readiness_report["p0_not_closed"],
    }
    html = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WorkCore E6R2 四态产品与工程评审</title>
<style>
  *{box-sizing:border-box} html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#111820;color:#edf2f7;font-family:Inter,"Microsoft YaHei",sans-serif}
  #view{position:fixed;inset:0;width:100%;height:100%}
  .panel{position:fixed;z-index:2;background:rgba(16,24,33,.91);border:1px solid #344452;box-shadow:0 16px 42px rgba(0,0,0,.35);backdrop-filter:blur(12px)}
  #top{left:18px;top:18px;width:470px;border-radius:14px;padding:16px;max-height:calc(100% - 36px);overflow:auto}
  #info{right:18px;top:18px;width:310px;border-radius:14px;padding:16px}
  h1{font-size:18px;margin:0 0 5px;letter-spacing:.2px} .sub{font-size:12px;color:#9fb0bf;margin-bottom:13px}
  .states{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.states button,.tool{appearance:none;border:1px solid #405564;border-radius:9px;background:#1b2934;color:#dbe6ee;padding:9px 5px;cursor:pointer}
  button:hover{border-color:#56b6c2}.states button.active{background:#126879;border-color:#62d4df;color:white}
  .tools{display:flex;gap:7px;margin-top:9px;flex-wrap:wrap}.tool{font-size:12px;flex:1;min-width:90px}.tool.active{background:#126879;border-color:#62d4df;color:white}
  .group-title{font-size:11px;color:#8195a5;margin-top:12px;margin-bottom:5px;letter-spacing:.08em}.layers{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.layers .tool{min-width:0;padding:7px 4px}
  .metric{display:flex;justify-content:space-between;gap:15px;padding:8px 0;border-bottom:1px solid #2c3a45;font-size:12px}.metric b{font-variant-numeric:tabular-nums;color:#fff}
  .ok{color:#70d6a0}.warn{margin-top:12px;padding:10px;border-radius:9px;background:#442b1d;border:1px solid #79502f;color:#ffd7ad;font-size:12px;line-height:1.55}
  #part{margin-top:10px;padding:9px;border-radius:8px;background:#0d141b;font:12px ui-monospace,Consolas,monospace;color:#89dceb;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #status{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:2;padding:8px 13px;border-radius:99px;background:rgba(12,18,24,.83);border:1px solid #35434e;color:#bfd0dc;font-size:12px}
  @media(max-width:760px){#top{width:calc(100% - 36px)}#info{top:auto;bottom:18px;width:calc(100% - 36px)}#status{display:none}}
</style>
</head>
<body>
<canvas id="view"></canvas>
<section id="top" class="panel">
  <h1>WorkCore E6R2 · 个人移动智能工作伴体</h1>
  <div class="sub">收纳随行 · 载人漫行 · 社交驻停 · 专注工作</div>
  <div class="group-title">四态产品体验</div>
  <div class="states">
    <button data-state="follow" class="active">随行</button>
    <button data-state="seat">漫行</button>
    <button data-state="cafe">咖啡驻停</button>
    <button data-state="desk">专注工作</button>
  </div>
  <div class="group-title">工程与附件状态</div>
  <div class="states">
    <button data-state="stowed">收纳校核</button>
    <button data-state="obstacle">越障拉杆</button>
    <button data-state="storage">设备仓</button>
    <button data-state="storage_wheel">仓轮关系</button>
    <button data-state="electrical">电气热管理</button>
    <button data-state="internal">内部</button>
    <button data-state="transfer">移乘</button>
    <button data-state="occupied">载人</button>
    <button data-state="deployed">户外包</button>
  </div>
  <div class="group-title">机构运动</div>
  <div class="tools">
    <button id="lowerMotion" class="tool" style="display:none">已删除下层仓</button>
    <button id="upperMotion" class="tool">上层仓：打开</button>
    <button id="closeMotion" class="tool">全部收回</button>
  </div>
  <div class="group-title">部件显隐</div>
  <div class="layers">
    <button class="tool active" data-layer="shell">外壳</button>
    <button class="tool active" data-layer="storage">设备仓</button>
    <button class="tool active" data-layer="running">轮系</button>
    <button class="tool active" data-layer="internal">内构</button>
    <button class="tool active" data-layer="furniture">座椅桌板</button>
    <button class="tool active" data-layer="canopy">智能脊柱/户外包</button>
    <button class="tool active" data-layer="human">人体包络</button>
    <button id="showAll" class="tool">显示全部</button>
  </div>
  <div class="tools"><button id="reset" class="tool">重置视角</button><button id="wire" class="tool">线框：关</button><button id="hidePart" class="tool">隐藏所选</button></div>
  <div id="part">零件：点击模型识别</div>
</section>
<aside id="info" class="panel">
  <h1>自动名义校核摘要</h1>
  <div class="sub ok" id="checks"></div>
  <div class="metric"><span>语义/解析 · 实体有效性</span><b id="checkKinds"></b></div>
  <div class="metric"><span>收纳空载质量</span><b id="mass"></b></div>
  <div class="metric"><span>桌面额定工况最小倾覆角</span><b id="tip"></b></div>
  <div class="metric"><span>7 m/s 自动回收边界 SF</span><b id="wind7"></b></div>
  <div class="metric"><span>理论紧急回收时间</span><b id="time"></b></div>
  <div class="metric"><span>载人原地转向直径</span><b id="turn"></b></div>
  <div class="metric"><span>额定垂直越障</span><b id="obstacle"></b></div>
  <div class="metric"><span>收纳 L×W×H</span><b id="stowed"></b></div>
  <div class="metric"><span>设备仓—轮系最差动态间隙</span><b id="drawerClear"></b></div>
  <div class="metric"><span>电池标称 / 社区工作日续航</span><b id="energy"></b></div>
  <div class="metric"><span>移动峰值 / 桅杆预算</span><b id="power"></b></div>
  <div class="metric"><span>电子仓所需风量</span><b id="airflow"></b></div>
  <div class="metric"><span>量产证据完整度</span><b id="readiness"></b></div>
  <div class="metric"><span>未关闭量产P0门</span><b id="readinessP0"></b></div>
  <div class="warn" id="warning"></div>
</aside>
<div id="status">左键旋转 · 滚轮缩放 · 右键平移</div>
<script>__THREE_JS__</script>
<script>__ORBIT_JS__</script>
<script>__GLTF_JS__</script>
<script>
const MODELS=__MODEL_DATA__;
const METRICS=__METRICS__;
addEventListener('error',e=>{const s=document.getElementById('status');if(s)s.textContent='页面错误：'+(e.message||'未知错误')});
const canvas=document.getElementById('view');
const renderer=new THREE.WebGLRenderer({canvas,antialias:true}); renderer.setPixelRatio(Math.min(devicePixelRatio,2)); renderer.outputEncoding=THREE.sRGBEncoding;
const scene=new THREE.Scene(); scene.background=new THREE.Color(0x111820);
const camera=new THREE.PerspectiveCamera(42,innerWidth/innerHeight,1,12000); camera.up.set(0,0,1);
const controls=new THREE.OrbitControls(camera,canvas); controls.enableDamping=true; controls.dampingFactor=.07;
scene.add(new THREE.HemisphereLight(0xdbeafe,0x18212b,1.45));
const key=new THREE.DirectionalLight(0xffffff,1.3);key.position.set(1000,1800,1200);scene.add(key);
const fill=new THREE.DirectionalLight(0x8bc7ff,.55);fill.position.set(-1400,900,-1000);scene.add(fill);
const grid=new THREE.GridHelper(3200,32,0x334550,0x25323b);grid.rotation.x=Math.PI/2;scene.add(grid);
let root=null,wire=false,lastFit=null,selected=null,activeState='follow',drawerBaseOpen=0,lateralAxis=new THREE.Vector3(0,1,0);
const layerState={shell:true,storage:true,running:true,internal:true,furniture:true,canopy:true,human:true};
const hiddenParts=new Set();
const motionValue={lower:0,upper:0},motionTarget={lower:0,upper:0};
const loader=new THREE.GLTFLoader();
function bufferFrom64(value){const raw=atob(value),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);return bytes.buffer}
function fit(){if(!root)return;const box=new THREE.Box3().setFromObject(root),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),m=Math.max(size.x,size.y,size.z);controls.target.copy(center);camera.position.set(center.x+m*1.25,center.y+m*.82,center.z+m*1.35);camera.near=Math.max(1,m/1000);camera.far=m*12;camera.updateProjectionMatrix();controls.update();lastFit={center,m}}
function setWire(){if(!root)return;root.traverse(o=>{if(o.isMesh){const mats=Array.isArray(o.material)?o.material:[o.material];mats.forEach(m=>m.wireframe=wire)}})}
function partName(o){return o?.name||o?.parent?.name||'未命名'}
function category(name){name=name.toLowerCase();if(name.startsWith('human_'))return'human';if(/^(drawer_|cots_slide_|cots_latch_|laptop_|universal_|device_bay_|daily_caddy_)/.test(name))return'storage';if(/^(tyre_|hub_|axle_|suspension_|wheel_arch_|chassis_|obstacle_handle_)/.test(name))return'running';if(/^(battery_|compute_|encrypted_|communications_|power_distribution_|drive_imu_|occupant_energy_|safety_backup_|pdu_|harness_|thermal_|hmi_|service_|follow_)/.test(name))return'internal';if(/^(mast_|sensor_beam_|canopy_|outdoor_|wind_sensor_|cots_mast_)/.test(name))return'canopy';if(/^(seat_|backrest_|armrest_|desk_|footrest_|pelvic_belt_)/.test(name))return'furniture';return'shell'}
function applyVisibility(){const counts={shell:0,storage:0,running:0,internal:0,furniture:0,canopy:0,human:0};if(!root)return counts;root.traverse(o=>{if(o.isMesh){const n=partName(o),k=category(n);counts[k]=(counts[k]||0)+1;o.visible=layerState[k]&&!hiddenParts.has(n)}});return counts}
function setLayerPreset(name){Object.keys(layerState).forEach(k=>layerState[k]=true);document.querySelectorAll('[data-layer]').forEach(b=>b.classList.toggle('active',layerState[b.dataset.layer]))}
function emphasizeStorageScene(){if(!root)return;root.traverse(o=>{if(!o.isMesh||category(partName(o))!=='storage')return;const n=partName(o),recolor=m=>{const c=m.clone();if(n.startsWith('drawer_front_'))c.color.setHex(0xf59e0b);else if(n.startsWith('cots_slide_'))c.color.setHex(0xcbd5e1);else c.color.setHex(0x22d3ee);if(c.emissive)c.emissive.setHex(0x062b33);return c};o.material=Array.isArray(o.material)?o.material.map(recolor):recolor(o.material)})}
function findMesh(token){let found=null;if(root)root.traverse(o=>{if(!found&&o.isMesh&&partName(o).includes(token))found=o});return found}
function refreshLateralAxis(){const l=findMesh('tyre_front_left'),r=findMesh('tyre_front_right');if(l&&r){const lc=new THREE.Box3().setFromObject(l).getCenter(new THREE.Vector3()),rc=new THREE.Box3().setFromObject(r).getCenter(new THREE.Vector3());lateralAxis.copy(rc.sub(l).normalize())}else lateralAxis.set(0,1,0)}
function captureBasePositions(){if(!root)return;root.traverse(o=>{if(o.isMesh)o.userData.reviewBase=o.position.clone()})}
function applyDrawerMotion(){if(!root)return;root.traverse(o=>{if(!o.isMesh||!o.userData.reviewBase)return;const n=partName(o);o.position.copy(o.userData.reviewBase);let tier=null,travel=0;if(n.includes('_lower')){tier='lower';travel=254}else if(n.includes('_upper')||/^(laptop_|universal_|device_bay_)/.test(n)){tier='upper';travel=305}if(!tier)return;const side=n.includes('right')?1:(n.includes('left')?-1:0);if(!side)return;const railFactor=n.startsWith('cots_slide_')?0.5:1;o.position.addScaledVector(lateralAxis,side*travel*(motionValue[tier]-drawerBaseOpen)*railFactor)})}
function updateMotion(){for(const tier of ['lower','upper']){const delta=motionTarget[tier]-motionValue[tier];if(Math.abs(delta)>.001)motionValue[tier]+=delta*.12;else motionValue[tier]=motionTarget[tier]}applyDrawerMotion();document.getElementById('lowerMotion').textContent='下层仓：'+(motionTarget.lower?'收回':'打开');document.getElementById('upperMotion').textContent='上层仓：'+(motionTarget.upper?'收回':'打开')}
function disposeRoot(){if(!root)return;root.traverse(o=>{if(o.isMesh){o.geometry?.dispose();const mats=Array.isArray(o.material)?o.material:[o.material];mats.forEach(m=>m?.dispose())}});scene.remove(root);root=null}
function loadState(name){activeState=name;drawerBaseOpen=name.startsWith('storage')?1:0;const modelName=name;document.getElementById('status').textContent='正在载入 E6R2 '+name+'…';disposeRoot();selected=null;motionValue.lower=motionValue.upper=motionTarget.lower=motionTarget.upper=drawerBaseOpen;setLayerPreset(name);document.getElementById('part').textContent='零件：点击模型识别';loader.parse(bufferFrom64(MODELS[modelName]),'',g=>{root=g.scene;scene.add(root);captureBasePositions();refreshLateralAxis();setWire();const counts=applyVisibility();fit();if(name.startsWith('storage')){if(counts.storage<1){document.getElementById('status').textContent='错误：设备仓节点未识别';return}document.getElementById('status').textContent=(name==='storage'?'纯设备仓':'设备仓—轮系关系')+'：'+counts.storage+' 个仓体/滑轨节点；上方按钮可收回'}else if(name==='follow')document.getElementById('status').textContent='随行态：梯形后壳自身成盖 · 无外包封帽 · v37基座感知持续工作';else if(name==='cafe')document.getElementById('status').textContent='咖啡态：右摇杆入仓 · 右桌板前移—旋转90°—回移正锁 · 左侧开放';else if(name==='electrical')document.getElementById('status').textContent='电气热管理：点击模块查看 PDU、线束、智能脊柱负载和散热路径';else document.getElementById('status').textContent='点击识别 · 双击隐藏 · 左键旋转 · 滚轮缩放 · 右键平移';},e=>{document.getElementById('status').textContent='模型载入失败：'+e});document.querySelectorAll('[data-state]').forEach(b=>b.classList.toggle('active',b.dataset.state===name))}
document.querySelectorAll('[data-state]').forEach(b=>b.onclick=()=>loadState(b.dataset.state));
document.getElementById('reset').onclick=fit;document.getElementById('wire').onclick=()=>{wire=!wire;document.getElementById('wire').textContent='线框：'+(wire?'开':'关');setWire()};
document.getElementById('lowerMotion').onclick=()=>motionTarget.lower=motionTarget.lower?0:1;
document.getElementById('upperMotion').onclick=()=>motionTarget.upper=motionTarget.upper?0:1;
document.getElementById('closeMotion').onclick=()=>motionTarget.lower=motionTarget.upper=0;
document.querySelectorAll('[data-layer]').forEach(b=>b.onclick=()=>{const k=b.dataset.layer;layerState[k]=!layerState[k];b.classList.toggle('active',layerState[k]);applyVisibility()});
document.getElementById('showAll').onclick=()=>{hiddenParts.clear();Object.keys(layerState).forEach(k=>layerState[k]=true);document.querySelectorAll('[data-layer]').forEach(b=>b.classList.add('active'));applyVisibility()};
document.getElementById('hidePart').onclick=()=>{if(selected){hiddenParts.add(partName(selected));applyVisibility();selected=null;document.getElementById('part').textContent='零件：已隐藏，可点“显示全部”恢复'}};
const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();
function pick(e){pointer.x=e.clientX/innerWidth*2-1;pointer.y=-(e.clientY/innerHeight)*2+1;ray.setFromCamera(pointer,camera);const hit=root?ray.intersectObject(root,true)[0]:null;if(hit){selected=hit.object;document.getElementById('part').textContent='零件：'+partName(selected)}return hit}
canvas.addEventListener('pointerdown',pick);canvas.addEventListener('dblclick',e=>{const hit=pick(e);if(hit){hiddenParts.add(partName(hit.object));applyVisibility();selected=null;document.getElementById('part').textContent='零件：已隐藏，可点“显示全部”恢复'}});
function resize(){renderer.setSize(innerWidth,innerHeight,false);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix()}addEventListener('resize',resize);resize();
canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();document.getElementById('status').textContent='WebGL 显存上下文已丢失：请关闭重复评审标签页后刷新当前页'});
canvas.addEventListener('webglcontextrestored',()=>loadState(activeState));
document.getElementById('checks').textContent=METRICS.failed_checks?METRICS.failed_checks+' 项失败 / '+METRICS.checks+' 项':METRICS.passed_checks+' / '+METRICS.checks+' 项名义检查通过';
document.getElementById('checks').classList.toggle('ok',METRICS.failed_checks===0);
document.getElementById('checkKinds').textContent=METRICS.semantic_or_analytical_checks+' · '+METRICS.solid_validity_checks;
document.getElementById('mass').textContent=METRICS.stowed_mass_kg.toFixed(1)+' kg';
document.getElementById('tip').textContent=METRICS.desk_tip_deg.toFixed(1)+'°';
document.getElementById('wind7').textContent=METRICS.wind_7_sf.toFixed(2);
document.getElementById('time').textContent=METRICS.retract_s.toFixed(2)+' s';
document.getElementById('turn').textContent=METRICS.turning_circle_mm.toFixed(0)+' mm';
document.getElementById('obstacle').textContent=METRICS.obstacle_mm.toFixed(0)+' mm';
document.getElementById('stowed').textContent=METRICS.stowed.length_x_mm.toFixed(0)+'×'+METRICS.stowed.width_y_mm.toFixed(0)+'×'+METRICS.stowed.height_z_mm.toFixed(0)+' mm';
document.getElementById('drawerClear').textContent=METRICS.drawer_min_clearance_mm.toFixed(1)+' mm / '+METRICS.drawer_sweep_samples+' 组合';
document.getElementById('energy').textContent=METRICS.battery_kwh.toFixed(3)+' kWh / '+METRICS.community_runtime_h.toFixed(2)+' h';
document.getElementById('power').textContent=METRICS.mobile_peak_kw.toFixed(2)+' kW / '+METRICS.mast_power_w.toFixed(0)+' W';
document.getElementById('airflow').textContent=METRICS.thermal_airflow_cfm.toFixed(1)+' CFM';
document.getElementById('readiness').textContent=METRICS.production_evidence_percent.toFixed(1)+'%（证据，不是认证概率）';
document.getElementById('readinessP0').textContent=METRICS.production_p0_open+' 项';
document.getElementById('warning').textContent='当前结论：仅允许进入受控 EVT 工程样机准备，不允许设计冻结、DVT、PVT 或量产。以上为名义模型检查，不包含制造公差、磨损、实物、法规、供应商或过程能力证据。Follow 仅限空载折叠、主人可见与白名单私域路线 Beta；户外顶棚是可拆附件，7 m/s 必须自动回收。';
function animate(){requestAnimationFrame(animate);updateMotion();controls.update();renderer.render(scene,camera)}loadState('follow');animate();
</script>
</body>
</html>"""
    html = html.replace("__MODEL_DATA__", json.dumps(encoded, separators=(",", ":")))
    html = html.replace("__METRICS__", json.dumps(metrics, separators=(",", ":")))
    html = html.replace("__THREE_JS__", three_js)
    html = html.replace("__ORBIT_JS__", orbit_js)
    html = html.replace("__GLTF_JS__", gltf_js)
    (BUILD / "workcore_e6_review.html").write_text(html, encoding="utf-8")
    (BUILD / "workcore_e6_review_offline.html").write_text(html, encoding="utf-8")
    # Compatibility copies keep existing bookmarks and the currently open
    # local review tab working while clearly presenting E6 inside the page.
    (BUILD / "workcore_e4_review.html").write_text(html, encoding="utf-8")
    (BUILD / "workcore_e4_review_offline.html").write_text(html, encoding="utf-8")


def render_preview(parts: list[Part], target: Path, configuration: str) -> None:
    import vtk

    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.91, 0.92, 0.93)
    for p in parts:
        vertices, triangles = p.solid.tessellate(1.5, 0.3)
        points = vtk.vtkPoints()
        for v in vertices:
            points.InsertNextPoint(v.x, v.y, v.z)
        cells = vtk.vtkCellArray()
        for tri in triangles:
            cell = vtk.vtkTriangle()
            cell.GetPointIds().SetId(0, tri[0])
            cell.GetPointIds().SetId(1, tri[1])
            cell.GetPointIds().SetId(2, tri[2])
            cells.InsertNextCell(cell)
        poly = vtk.vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(cells)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*p.color[:3])
        actor.GetProperty().SetOpacity(p.color[3])
        actor.GetProperty().SetInterpolationToPBR()
        actor.GetProperty().SetMetallic(0.25 if "aluminium" in p.material or "steel" in p.material else 0.0)
        actor.GetProperty().SetRoughness(0.45)
        renderer.AddActor(actor)

    floor = vtk.vtkPlaneSource()
    floor.SetOrigin(-1300, -1000, 0)
    floor.SetPoint1(900, -1000, 0)
    floor.SetPoint2(-1300, 1000, 0)
    floor.Update()
    floor_mapper = vtk.vtkPolyDataMapper()
    floor_mapper.SetInputConnection(floor.GetOutputPort())
    floor_actor = vtk.vtkActor()
    floor_actor.SetMapper(floor_mapper)
    floor_actor.GetProperty().SetColor(0.77, 0.78, 0.79)
    renderer.AddActor(floor_actor)

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1600, 1100)
    window.AddRenderer(renderer)
    camera = renderer.GetActiveCamera()
    if configuration == "deployed":
        camera.SetPosition(2350, -2450, 1900)
        camera.SetFocalPoint(-150, 0, 750)
    elif configuration == "occupied":
        camera.SetPosition(-2250, -2100, 1450)
        camera.SetFocalPoint(-180, 0, 660)
    elif configuration == "obstacle":
        camera.SetPosition(2100, -2300, 1750)
        camera.SetFocalPoint(0, 0, 720)
    else:
        camera.SetPosition(1900, -2200, 1500)
        camera.SetFocalPoint(-50, 0, 560)
    camera.SetViewUp(0, 0, 1)
    renderer.ResetCameraClippingRange()
    window.Render()
    image_filter = vtk.vtkWindowToImageFilter()
    image_filter.SetInput(window)
    image_filter.SetInputBufferTypeToRGBA()
    image_filter.ReadFrontBufferOff()
    image_filter.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(target))
    writer.SetInputConnection(image_filter.GetOutputPort())
    writer.Write()
    window.Finalize()


def main() -> None:
    global _BUILD_TERMINAL, _CURRENT_RUN_ID
    _BUILD_TERMINAL = False
    _CURRENT_RUN_ID = uuid.uuid4().hex
    staged_build = STAGING_ROOT / _CURRENT_RUN_ID / "build"
    _bind_output(staged_build)
    BUILD.mkdir(parents=True, exist_ok=False)
    PARTS_DIR.mkdir(exist_ok=False)
    _write_build_status("IN_PROGRESS")
    atexit.register(_mark_interrupted_build)
    configs = {
        "stowed": build_configuration("stowed"),
        "follow": build_configuration("follow"),
        "obstacle": build_configuration("obstacle"),
        "seat": build_configuration("seat"),
        "cafe": build_configuration("cafe"),
        "internal": build_configuration("internal"),
        "transfer": build_configuration("transfer"),
        "desk": build_configuration("desk"),
        "deployed": build_configuration("deployed"),
    }
    for config, parts in configs.items():
        export_assembly(parts, config)
        export_glb(parts, config)
        render_preview(parts, BUILD / f"preview_{config}.png", config)
    occupied_review = configs["desk"] + human_envelope_parts("desk")
    export_glb(occupied_review, "occupied")
    render_preview(occupied_review, BUILD / "preview_desk_occupied.png", "occupied")
    storage_review = storage_review_parts(configs["seat"], include_running_gear=False)
    export_glb(storage_review, "storage")
    render_preview(storage_review, BUILD / "preview_storage.png", "storage")
    storage_wheel_review = storage_review_parts(configs["seat"], include_running_gear=True)
    export_glb(storage_wheel_review, "storage_wheel")
    render_preview(storage_wheel_review, BUILD / "preview_storage_wheel.png", "storage")
    electrical_review = electrical_thermal_review_parts(configs["seat"])
    export_glb(electrical_review, "electrical")
    render_preview(electrical_review, BUILD / "preview_electrical_thermal.png", "internal")
    export_parts(configs)
    write_bom(configs)
    write_interface_register(configs)
    report = validate(configs)
    (BUILD / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    engineering_report = engineering_analyze(configs, P)
    (BUILD / "engineering_report.json").write_text(
        json.dumps(engineering_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    mobility_report = mobility_analyze(report, engineering_report, P)
    (BUILD / "mobility_report.json").write_text(
        json.dumps(mobility_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_access_csv(mobility_report, BUILD / "access_scenarios.csv")
    power_report = power_thermal_analyze(configs, P)
    (BUILD / "power_thermal_report.json").write_text(
        json.dumps(power_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    readiness_report = readiness_analyze_and_write(
        configs,
        {
            "geometry": report,
            "engineering": engineering_report,
            "mobility": mobility_report,
            "power_thermal": power_report,
        },
        BUILD,
    )
    write_tolerance_register(report, engineering_report)
    write_review_html(report, engineering_report, mobility_report, power_report, readiness_report)
    failed = [check for check in report["checks"] if not check["pass"]]
    failed += [check for check in engineering_report["checks"] if not check["pass"]]
    failed += [check for check in mobility_report["checks"] if not check["pass"]]
    failed += [check for check in power_report["checks"] if not check["pass"]]
    geometry_checks = report["checks"]
    all_checks = geometry_checks + engineering_report["checks"] + mobility_report["checks"] + power_report["checks"]
    solid_validity_count = sum(
        str(check.get("check", "")).startswith("solid_valid:") for check in geometry_checks
    )
    if failed:
        _write_build_status("FAILED", failed_automated_check_count=len(failed))
        _BUILD_TERMINAL = True
        print(
            json.dumps(
                {
                    "revision": "E6-DFR4",
                    "parts": {k: len(v) for k, v in configs.items()},
                    "failed_checks": failed,
                    "semantic_or_analytical_checks": len(all_checks) - solid_validity_count,
                    "solid_validity_checks": solid_validity_count,
                    "production_evidence_percent": readiness_report["production_evidence_index_percent"],
                    "production_p0_not_closed": readiness_report["p0_not_closed"],
                    "release_manifest_written": False,
                },
                indent=2,
            )
        )
        raise SystemExit(2)

    _write_build_status(
        "COMPLETE",
        failed_automated_check_count=0,
        publish_state="STAGED_AND_HASH_BOUND",
    )
    manifest = write_release_manifest(
        ROOT,
        BUILD,
        revision="E6-DFR4",
        configs=configs,
        reports={
            "geometry": report,
            "engineering": engineering_report,
            "mobility": mobility_report,
            "power_thermal": power_report,
            "readiness": readiness_report,
        },
        logical_build_dir=PUBLISHED_BUILD,
        run_id=_CURRENT_RUN_ID,
    )
    publication = publish_staged_release(
        root=ROOT,
        staged_build=BUILD,
        public_build=PUBLISHED_BUILD,
        manifest=manifest,
        run_id=_CURRENT_RUN_ID,
    )
    _BUILD_TERMINAL = True
    print(
        json.dumps(
            {
                "revision": "E6-DFR4",
                "parts": {k: len(v) for k, v in configs.items()},
                "failed_checks": failed,
                "semantic_or_analytical_checks": manifest["automated_checks"]["semantic_or_analytical"],
                "solid_validity_checks": manifest["automated_checks"]["solid_validity"],
                "production_evidence_percent": readiness_report["production_evidence_index_percent"],
                "production_p0_not_closed": readiness_report["p0_not_closed"],
                "publication": publication,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
