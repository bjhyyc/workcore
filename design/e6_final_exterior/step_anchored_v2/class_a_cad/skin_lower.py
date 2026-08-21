"""STEP-anchored lower exterior skins for WorkCore E6.

The controlled E6 STEP files remain read-only.  This module only creates a
separate cosmetic-skin study around their released datums.  It intentionally
leaves tyres, wheel travel, perception windows, tactile bumper, service access,
manual releases and drainage visible and reachable.

Coordinate convention (mm): -X front / foot side, +X rear, +Y right,
-Y left, +Z up.
"""

from __future__ import annotations

import cadquery as cq

from cad.parameters import P

from skin_common import (
    CHARCOAL_KNIT,
    CHAMPAGNE,
    GRAPHITE_BROWN,
    LUNAR_STONE,
    SMOKED_UMBER,
    TPE_DARK,
    SkinPart,
    cut_many,
    rounded_box,
    rounded_frame,
    rounded_rect_prism,
    union_many,
)
from v8_state_contract import (
    default_footrest_is_deployed,
    footrest_state_evidence,
)


_FOLLOW_STATES = {"follow", "follow_closed", "stowed", "obstacle"}
_RIDE_STATES = {
    "ride",
    "seat",
    "seat_ready",
    "cafe",
    "café",
    "focus",
    "desk",
    "deployed",
    "transfer",
}


def _configuration_name(config: object) -> str:
    """Return a controlled lower-case configuration label.

    ``build_lower_skin`` deliberately accepts either a state string or a small
    configuration object exposing ``name`` / ``configuration``.  This keeps
    the skin module usable by an assembly driver without importing ``cad.build``.
    """

    if isinstance(config, str):
        value = config
    else:
        value = getattr(config, "name", getattr(config, "configuration", str(config)))
    value = str(value).strip().lower()
    aliases = {
        "follow-closed": "follow_closed",
        "seat-ready": "seat_ready",
        "café": "cafe",
    }
    value = aliases.get(value, value)
    if value not in _FOLLOW_STATES | _RIDE_STATES:
        raise ValueError(
            f"Unsupported E6 lower-skin configuration {value!r}; expected one of "
            f"{sorted(_FOLLOW_STATES | _RIDE_STATES)}"
        )
    return value


def _smooth_side_panel(y_center: float, thickness: float) -> cq.Shape:
    """Extrude the controlled side silhouette with smooth upper/lower rails."""

    # Two interpolation curves replace the faceted prototype outline.  Their
    # end seams stay near the real front/rear module breaks, while the long
    # visible rails remain curvature-smooth and free of automotive wheel arches.
    profile = (
        cq.Workplane("XZ")
        .moveTo(-468.0, 145.0)
        .spline(
            [
                (-455.0, 115.0),
                (-400.0, 103.0),
                (200.0, 103.0),
                (285.0, 115.0),
                (316.0, 145.0),
            ],
            includeCurrent=True,
        )
        .lineTo(320.0, 346.0)
        .spline(
            [
                (300.0, 380.0),
                (270.0, 398.0),
                (210.0, 405.0),
                (-330.0, 405.0),
                (-420.0, 380.0),
                (-458.0, 330.0),
                (-468.0, 322.0),
            ],
            includeCurrent=True,
        )
        .close()
    )
    return (
        profile
        .extrude(thickness / 2.0, both=True)
        .translate((0.0, y_center, 0.0))
        .val()
    )


def _rounded_rect_wire_xy(
    size_xy: tuple[float, float],
    center_xy: tuple[float, float],
    z: float,
    radius: float,
) -> cq.Wire:
    """Rounded XY section used for continuous Class-A cushion lofts."""

    sx, sy = size_xy
    cx, cy = center_xy
    safe = min(radius, sx * 0.49, sy * 0.49)
    sketch = cq.Sketch().rect(sx, sy)
    if safe > 0.0:
        sketch = sketch.vertices().fillet(safe)
    wire = sketch.reset().wires().val()
    if not isinstance(wire, cq.Wire):
        raise TypeError("Rounded lower-skin loft section did not resolve to a wire")
    return wire.translate((cx, cy, z))


def _rounded_loft_z(
    sections: tuple[
        tuple[tuple[float, float], tuple[float, float], float, float],
        ...,
    ],
) -> cq.Solid:
    """Smooth solid through rounded sections without thickness-limited radii."""

    wires = [
        _rounded_rect_wire_xy(size_xy, center_xy, z, radius)
        for size_xy, center_xy, z, radius in sections
    ]
    body = cq.Solid.makeLoft(wires, ruled=False)
    if not body.isValid():
        raise ValueError("Rounded lower-skin loft produced an invalid solid")
    return body


def _cylinder_y(
    radius: float,
    length: float,
    center: tuple[float, float, float],
) -> cq.Shape:
    """Cylinder with its axis on global Y, centred on ``center``."""

    return (
        cq.Workplane("XZ")
        .circle(radius)
        .extrude(length / 2.0, both=True)
        .translate(center)
        .val()
    )


def _rounded_panel_xz(
    size_xz: tuple[float, float],
    thickness_y: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    """Thin service panel whose large rounded face lies in the XZ plane."""

    sx, sz = size_xz
    body = (
        cq.Workplane("XZ")
        .rect(sx, sz)
        .extrude(thickness_y / 2.0, both=True)
    )
    try:
        body = body.edges("|Y").fillet(min(radius, sx * 0.45, sz * 0.45))
    except Exception:
        pass
    return body.translate(center).val()


def _rounded_panel_yz(
    size_yz: tuple[float, float],
    thickness_x: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    """Thin service panel whose large rounded face lies in the YZ plane."""

    sy, sz = size_yz
    body = (
        cq.Workplane("YZ")
        .rect(sy, sz)
        .extrude(thickness_x / 2.0, both=True)
    )
    try:
        body = body.edges("|X").fillet(min(radius, sy * 0.45, sz * 0.45))
    except Exception:
        pass
    return body.translate(center).val()


def _panel_shell(
    outer_size: tuple[float, float, float],
    outer_center: tuple[float, float, float],
    wall: float,
    radius: float,
    open_axis: str,
) -> cq.Shape:
    """Create a robust open-backed cosmetic shell from two rounded solids."""

    sx, sy, sz = outer_size
    cx, cy, cz = outer_center
    if wall <= 0 or min(sx, sy, sz) <= wall * 2.0:
        raise ValueError("Panel shell wall is incompatible with outer size")
    outer = rounded_box(outer_size, outer_center, radius)
    if open_axis == "+X":
        inner_size = (sx + wall * 2.0, sy - wall * 2.0, sz - wall * 2.0)
        inner_center = (cx + wall, cy, cz)
    elif open_axis == "-Z":
        inner_size = (sx - wall * 2.0, sy - wall * 2.0, sz + wall * 2.0)
        inner_center = (cx, cy, cz - wall)
    else:
        raise ValueError(f"Unsupported open axis: {open_axis}")
    inner = rounded_box(inner_size, inner_center, max(2.0, radius - wall))
    return outer.cut(inner)


def _skin_part(
    name: str,
    shape: cq.Shape,
    color: tuple[float, float, float, float],
    material: str,
    module: str,
    configuration: str,
    intent: str,
    **metadata: object,
) -> SkinPart:
    return SkinPart(
        name=name,
        shape=shape,
        color=color,
        material=material,
        module=module,
        configuration=configuration,
        intent=intent,
        metadata=dict(metadata),
    )


def _front_nose(configuration: str) -> list[SkinPart]:
    """A01: U-shaped perception nose with real optical and bumper openings."""

    # The shell bridges from the E6 body nose (-470) back to the released
    # front-perception modules near X=-378.  The footwell begins only above the
    # complete low core: cutting the fascia down through the sensor band made
    # the modules look suspended in an empty frame, although the actual foot
    # route is above them.
    outer = _panel_shell(
        (136.0, 526.0, 252.0),
        (-416.0, 0.0, 238.0),
        wall=6.0,
        radius=30.0,
        open_axis="+X",
    )
    footwell = rounded_box(
        (180.0, 420.0, 80.0),
        (-416.0, 0.0, 390.0),
        20.0,
    )

    # Window locations are projected to the Class-A front fascia while their
    # internal module hardpoints remain unchanged at X=-378 / -391.5.
    window_cutters = [
        rounded_box((20.0, 58.0, 30.0), (-478.0, -80.0, 250.0), 6.0),
        rounded_box((20.0, 58.0, 30.0), (-478.0, 80.0, 250.0), 6.0),
        rounded_box((20.0, 84.0, 30.0), (-478.0, 0.0, 315.0), 6.0),
    ]
    nose = cut_many(outer, [footwell, *window_cutters])

    # Each released module receives a genuine open-backed local enclosure.
    # A very thin low bridge joins the three pods outside all optical tunnels,
    # so the user reads one instrument horizon instead of three floating boxes.
    pod_shapes: list[cq.Shape] = []
    pod_specs = (
        (-80.0, 250.0, 52.0, 24.0),
        (80.0, 250.0, 52.0, 24.0),
        (0.0, 315.0, 78.0, 24.0),
    )
    for y, z, width, height in pod_specs:
        outer_pod = rounded_box(
            (116.0, width + 18.0, height + 18.0),
            (-424.0, y, z),
            11.0,
        )
        inner_tunnel = rounded_box(
            (108.0, width + 10.0, height + 10.0),
            (-416.0, y, z),
            8.0,
        )
        pod = outer_pod.cut(inner_tunnel)
        pod = pod.cut(rounded_box((22.0, width, height), (-482.0, y, z), 5.0))
        pod_shapes.append(pod)

    low_bridge = rounded_box((24.0, 420.0, 20.0), (-448.0, 0.0, 221.0), 8.0)
    centre_riser = rounded_box((24.0, 18.0, 64.0), (-448.0, 0.0, 263.0), 8.0)
    # One continuous T-shaped outer instrument face hides the individual pod,
    # bridge and riser silhouettes.  Only the three coplanar optical windows
    # survive at the exterior datum; the carrier remains serviceable behind.
    horizon_face = rounded_box((8.0, 430.0, 58.0), (-478.0, 0.0, 250.0), 20.0)
    leg_face = rounded_box((8.0, 104.0, 90.0), (-478.0, 0.0, 309.0), 20.0)
    instrument_face = union_many((horizon_face, leg_face))
    instrument_face = cut_many(instrument_face, window_cutters)
    perception_carrier = union_many(
        (*pod_shapes, low_bridge, centre_riser, instrument_face)
    )

    # The windows are independent replaceable IR-transparent parts.  Their
    # outer face is exactly flush with the pod datum at X=-482 mm.
    windows = [
        ("left_tof", -80.0, 250.0, 52.0, 24.0),
        ("right_tof", 80.0, 250.0, 52.0, 24.0),
        ("leg_scanner", 0.0, 315.0, 78.0, 24.0),
    ]
    # One wide smoked horizon absorbs the three independently serviceable
    # optical zones.  It is deliberately a single calm field rather than the
    # previous T-shaped cluster, which read as three robot eyes on stalks.
    smoked_outer = _rounded_panel_yz(
        (456.0, 122.0),
        4.0,
        (-480.0, 0.0, 274.0),
        24.0,
    )
    smoked_mask = cut_many(smoked_outer, window_cutters)
    parts = [
        _skin_part(
            "A01_front_nose_shell",
            nose,
            LUNAR_STONE,
            "UV-stabilised PC-ABS, satin mineral coating",
            "A01",
            configuration,
            "Wraps the exposed front frame and sensor carriers while preserving the open footwell.",
            datum_x_mm=-470.0,
            shell_wall_mm=6.0,
        ),
        _skin_part(
            "A01_perception_horizon_carrier",
            perception_carrier,
            LUNAR_STONE,
            "UV-stabilised PC-ABS instrument carrier with internal flocking",
            "A01",
            configuration,
            "A single continuous instrument face and open-backed tunnels fully enclose the three released modules; only the flush windows remain visually separate.",
            optical_tunnels=3,
            low_bridge_z_range_mm=(211.0, 231.0),
            module_x_range_mm=(-482.0, -366.0),
            transfer_route_preserved=True,
        ),
        _skin_part(
            "A01_perception_horizon_smoked_mask",
            smoked_mask,
            SMOKED_UMBER,
            "Hard-coated smoked polycarbonate with opaque internal mask",
            "A01",
            configuration,
            "One calm full-width optical horizon unifies the three flush sensor zones while keeping their modules and fasteners behind the final skin.",
            functional_opening="navigation_horizon front_tof_left front_tof_right front_leg_scanner_window",
            optical_zone_count=3,
            coplanar_service_windows=True,
            presentation_geometry="single rounded rectangle; never T-shaped or eye-like",
        ),
    ]
    for label, y, z, width, height in windows:
        panel = rounded_box((4.0, width, height), (-480.0, y, z), 5.0)
        parts.append(
            _skin_part(
                f"A01_front_{label}_window",
                panel,
                SMOKED_UMBER,
                "Hard-coated IR-transparent smoked polycarbonate",
                "A01",
                configuration,
                "Serviceable optical window aligned to the released perception module.",
                optical_keepout="uncoated inner face; gasketed perimeter",
            )
        )

    bumper = rounded_box((12.0, 500.0, 24.0), (-482.0, 0.0, 160.0), 7.0)
    parts.append(
        _skin_part(
            "A01_front_tactile_bumper_skin",
            bumper,
            TPE_DARK,
            "Replaceable conductive TPE pressure-bumper membrane",
            "A01",
            configuration,
            "Carries the dual-channel tactile edge; intentionally proud of the painted shell.",
            released_bumper_x_mm=-471.0,
        )
    )
    return parts


def _side_shells(configuration: str) -> list[SkinPart]:
    """A02: left/right main side skins with functional penetrations."""

    # Smooth, low, non-automotive outline.  The outer face is Y=+/-281,
    # leaving 13 mm to each tyre's released inner face at Y=+/-294 and 3 mm
    # to the full +/-10 degree rocker sweep keep-out.
    parts: list[SkinPart] = []
    for side_name, side in (("left", -1), ("right", 1)):
        y_center = side * 278.0
        panel = _smooth_side_panel(y_center, 6.0)

        # Axle access holes are large enough for the 25 mm axles and their
        # released 6 mm service reserve.  The wheel/tyre volume is not covered.
        cutters: list[cq.Shape] = [
            _cylinder_y(P.axle_diameter / 2.0 + 8.0, 24.0, (x, y_center, P.wheel_center_z))
            for x in (P.wheel_x_front, P.wheel_x_rear)
        ]

        # Side ultrasonic transducers are direct exposed faces: no continuous
        # painted skin is placed in front of them.
        cutters.extend(
            _cylinder_y(10.0, 24.0, (x, y_center, 320.0))
            for x in (-445.0, 295.0)
        )

        # Two hydrophobic acoustic slots per side and the side UWB radome.
        cutters.extend(
            rounded_box((76.0, 24.0, 12.0), (x, y_center, 233.0), 4.0)
            for x in (-120.0, 20.0)
        )
        cutters.append(
            rounded_box((126.0, 24.0, 26.0), (-75.0, y_center, 400.0), 6.0)
        )

        # Open-bottom drain notches remain visible and clear of the recessed
        # downward optical windows at Y=+/-140.
        cutters.extend(
            rounded_box((22.0, 24.0, 24.0), (x, y_center, 103.0), 5.0)
            for x in (-300.0, -20.0, 235.0)
        )
        panel = cut_many(panel, cutters)
        parts.append(
            _skin_part(
                f"A02_main_side_shell_{side_name}",
                panel,
                LUNAR_STONE,
                "Long-fibre reinforced PC-ABS cosmetic carrier",
                "A02",
                configuration,
                "Covers chassis rails, device-bay edges and non-service fasteners without hiding wheel contact.",
                outer_face_y_mm=side * 281.0,
                tyre_inner_face_y_mm=side * 294.0,
                minimum_running_clearance_mm=P.wheel_running_clearance + 1.0,
                removable="quarter-turn internal fasteners from service side",
                functional_opening=(
                    "side_ultrasonic_faces downward_cliff_sensor_windows "
                    "acoustic_microphone_uwb_rf_windows"
                ),
            )
        )

        # Replace the prototype faces with final, flush, independently
        # serviceable functional membranes.  Only the active face is exposed;
        # the module, harness and fasteners remain behind A02.
        functional_y = side * 283.0
        for position_name, x in (("front", -445.0), ("rear", 295.0)):
            face = _cylinder_y(8.0, 3.0, (x, functional_y, 320.0))
            parts.append(
                _skin_part(
                    f"A02_side_ultrasonic_face_{position_name}_{side_name}",
                    face,
                    SMOKED_UMBER,
                    "Hydrophobic acoustic-transparent ultrasonic membrane",
                    "A02",
                    configuration,
                    "Flush final transducer face; the released module stays enclosed behind the main side shell.",
                    functional_opening="side_ultrasonic_face",
                    controlled_center_mm=(x, functional_y, 320.0),
                )
            )

        for slot_index, x in enumerate((-120.0, 20.0), start=1):
            mesh = rounded_box((70.0, 3.0, 8.0), (x, functional_y, 233.0), 3.0)
            parts.append(
                _skin_part(
                    f"A02_acoustic_mesh_{side_name}_{slot_index}",
                    mesh,
                    GRAPHITE_BROWN,
                    "Laser-perforated hydrophobic acoustic mesh",
                    "A02",
                    configuration,
                    "A narrow replaceable acoustic membrane closes the microphone slot without hiding its function.",
                    functional_opening="voice_acoustic_slot",
                )
            )

    # Four downward optical faces remain on the protected bottom plane.  The
    # released source windows occupy Z=96..99; the final exterior panes sit
    # immediately below them at Z=93..96, with an open gasket/bezel tunnel up
    # to the source datum.  Putting a proxy above the source would leave the
    # real -Z optical path hidden behind the final skin.
    for axle_name, x in (("front", -425.0), ("rear", 280.0)):
        for side_name, y in (("left", -140.0), ("right", 140.0)):
            window = rounded_box((16.0, 16.0, 3.0), (x, y, 94.5), 4.0)
            bezel = rounded_frame(
                (24.0, 24.0),
                (18.0, 18.0),
                7.0,
                (x, y, 99.5),
                6.0,
            )
            parts.extend(
                [
                    _skin_part(
                        f"A02_cliff_ir_window_{axle_name}_{side_name}",
                        window,
                        SMOKED_UMBER,
                        "Hard-coated downward IR window with replaceable gasket",
                        "A02",
                        configuration,
                        "Flush bottom-facing exterior pane below the released source window, outside tyre and rocker sweeps.",
                        functional_opening="downward_cliff_ir_window",
                        controlled_center_mm=(x, y, 94.5),
                        source_z_range_mm=(96.0, 99.0),
                        final_z_range_mm=(93.0, 96.0),
                        disposition="replace_with_external_proxy",
                        optical_axis="-Z",
                    ),
                    _skin_part(
                        f"A02_cliff_ir_bezel_{axle_name}_{side_name}",
                        bezel,
                        GRAPHITE_BROWN,
                        "Replaceable matte optical tunnel and gasket carrier",
                        "A02",
                        configuration,
                        "An open opaque tunnel shields stray light without crossing the released downward field of view.",
                        functional_opening="downward_cliff_ir_optical_tunnel",
                        open_aperture_mm=(18.0, 18.0),
                        source_to_proxy_tunnel_z_mm=(96.0, 103.0),
                    ),
                ]
            )
    return parts


def _wheel_bridge_and_caps(configuration: str) -> list[SkinPart]:
    """A03: rocker bridge covers and independent wheel-end service caps."""

    parts: list[SkinPart] = []
    bridge_x = (P.wheel_x_front + P.wheel_x_rear) / 2.0
    # 12 mm tangential clearance at both wheel envelopes:
    # front rear-most X=-255; rear front-most X=+55 -> [-243,+43].
    bridge_length = (
        P.wheel_x_rear
        - P.wheel_x_front
        - P.wheel_diameter
        - 2.0 * P.wheel_running_clearance
    )
    for side_name, side in (("left", -1), ("right", 1)):
        y = side * 356.0
        bridge = rounded_box(
            (bridge_length, 20.0, 82.0),
            (bridge_x, y, P.wheel_center_z + 5.0),
            10.0,
        )
        bridge = cut_many(
            bridge,
            [
                rounded_box((20.0, 28.0, 22.0), (bridge_x - 92.0, y, 91.0), 5.0),
                rounded_box((20.0, 28.0, 22.0), (bridge_x + 92.0, y, 91.0), 5.0),
            ],
        )
        parts.append(
            _skin_part(
                f"A03_wheel_interspace_bridge_{side_name}",
                bridge,
                GRAPHITE_BROWN,
                "Replaceable impact-modified PC-ABS rocker shroud",
                "A03",
                configuration,
                "Covers the central rocker and stops only between wheel sweeps; tyre tread remains fully visible.",
                wheel_tangential_clearance_mm=P.wheel_running_clearance,
                lower_drain_notches=2,
            )
        )

        pivot_cap_y = side * 368.0
        pivot_cap = _cylinder_y(34.0, 5.0, (bridge_x, pivot_cap_y, P.wheel_center_z))
        parts.append(
            _skin_part(
                f"A03_rocker_pivot_service_cap_{side_name}",
                pivot_cap,
                CHAMPAGNE,
                "Hard-anodised aluminium bayonet service cap",
                "A03",
                configuration,
                "Tool-indexed removable cap; does not imply a steering joint.",
            )
        )

        for axle_name, wheel_x in (("front", P.wheel_x_front), ("rear", P.wheel_x_rear)):
            # 46 mm radius sits inside the released tyre's 53 mm hub opening.
            cap_y = side * (P.wheel_y + P.wheel_width / 2.0 + 4.0)
            cap = _cylinder_y(46.0, 6.0, (wheel_x, cap_y, P.wheel_center_z))
            parts.append(
                _skin_part(
                    f"A03_wheel_end_service_cap_{axle_name}_{side_name}",
                    cap,
                    GRAPHITE_BROWN,
                    "Glass-filled PA12 service cap with retained seal",
                    "A03",
                    configuration,
                    "Covers axle-end fasteners while leaving the tyre, hub heat path and removal route intact.",
                    cap_radius_mm=46.0,
                    tyre_hub_opening_radius_mm=53.0,
                )
            )
    return parts


def _seat_pan_ring(configuration: str) -> list[SkinPart]:
    """A04: upper-deck closeout, equipment doors and recovery interface."""

    ring = rounded_frame(
        (620.0, 700.0),
        (500.0, 610.0),
        28.0,
        (-65.0, 0.0, 454.0),
        34.0,
    )
    # Delete the front cross-bar, leaving two honest side returns and an aft
    # bridge.  The resulting U does not turn the seat into a closed cockpit.
    front_opening = rounded_box((150.0, 730.0, 52.0), (-350.0, 0.0, 454.0), 8.0)
    ring = ring.cut(front_opening)

    # Small liquid paths at both forward tips, away from the seat cushion.
    ring = cut_many(
        ring,
        [
            rounded_box((22.0, 24.0, 36.0), (-292.0, y, 446.0), 5.0)
            for y in (-326.0, 326.0)
        ],
    )
    # The controlled recovery crossbar occupies the aft bridge.  Remove that
    # local cosmetic material and replace it with an open-bottom over-shell so
    # the handle remains load-path honest, graspable and latch-accessible.
    ring = ring.cut(rounded_box((82.0, 570.0, 48.0), (230.0, 0.0, 464.0), 10.0))

    parts = [
        _skin_part(
            "A04_open_u_seat_pan_ring",
            ring,
            LUNAR_STONE,
            "Painted PC-ABS upper-deck close-out ring",
            "A04",
            configuration,
            "Covers the exposed seat carrier perimeter while keeping the front transfer/footwell route open.",
            seat_keepout_mm=(P.seat_length, P.seat_width),
            liquid_paths=2,
        )
    ]

    # The controlled source item is a rectangular seat *envelope*, not a
    # released Class-A cushion.  Replace it inside the same 470 x 590 x 60 mm
    # box with a crowned, waterfall-front contact object.  Keeping the raw
    # black envelope in the final GLB made every state read as a medical chair
    # and left a black waist band visible in Follow.
    seat_cushion = _rounded_loft_z(
        (
            ((450.0, 570.0), (-75.0, 0.0), 440.0, 54.0),
            ((468.0, 588.0), (-75.0, 0.0), 450.0, 58.0),
            ((460.0, 580.0), (-82.0, 0.0), 485.0, 56.0),
            ((430.0, 550.0), (-90.0, 0.0), 500.0, 52.0),
        )
    )
    parts.append(
        _skin_part(
            "A04_seat_cushion_contact_island",
            seat_cushion,
            CHARCOAL_KNIT,
            "replaceable breathable 3D-knit cushion over energy-absorbing foam",
            "A04",
            configuration,
            "A crowned soft island replaces the crude rectangular source envelope at the exact seat hardpoint; a restrained waterfall front keeps the human-contact object separate from the core shell.",
            physical_occurrence_id="E6-A04-SEAT-CUSHION-CONTACT-ISLAND",
            source_occurrence_ids=("seat_cushion_envelope",),
            disposition="replace_surface",
            source_envelope_mm=(470.0, 590.0, 60.0),
            physical_part_conserved=True,
        )
    )

    # A smooth open-top belly hides the daily-caddy carrier, slides and
    # miscellaneous seat structure from the forward transfer view.  The
    # internal controlled lid remains untouched inside the cavity.
    belly_outer = rounded_box((390.0, 280.0, 90.0), (-175.0, 0.0, 355.0), 30.0)
    belly_inner = rounded_box((378.0, 268.0, 96.0), (-175.0, 0.0, 360.0), 25.0)
    # The open-top tray alone reads as a hollow equipment frame when viewed
    # through the front transfer opening.  A single broad kick close-out is
    # fused into its forward wall: it adds only 6 mm to the released envelope,
    # keeps the whole top service route open and turns the under-seat volume
    # into one visually closed body rather than another perimeter rail.
    belly_front_closeout = _rounded_panel_yz(
        (260.0, 78.0),
        8.0,
        (-372.0, 0.0, 350.0),
        24.0,
    )
    belly = union_many((belly_outer.cut(belly_inner), belly_front_closeout))
    parts.append(
        _skin_part(
            "A04_underseat_belly_closeout",
            belly,
            LUNAR_STONE,
            "Deep-draw PC-ABS underseat cosmetic tray",
            "A04",
            configuration,
            "Closes the visible caddy/seat-carrier volume with a continuous forward kick surface while retaining an open top for authorized lift-out access.",
            controlled_caddy_inside=True,
            open_top=True,
            forward_transfer_clearance=True,
            forward_kick_closeout_x_mm=(-376.0, -368.0),
        )
    )

    caddy_hatch = rounded_rect_prism(
        (340.0, 230.0),
        4.0,
        (-185.0, 0.0, 317.0),
        12.0,
    )
    parts.append(
        _skin_part(
            "A04_daily_caddy_flush_hatch",
            caddy_hatch,
            LUNAR_STONE,
            "Gasketed PC-ABS lift-out access hatch",
            "A04",
            configuration,
            "A single flush internal seat-pan hatch replaces the controlled prototype lid at the same datum; with the product unoccupied, both lateral equipment drawers open first and the caddy then lifts vertically without adding an exterior seam.",
            functional_opening="daily_caddy_access",
            released_caddy_xy_mm=(340.0, 230.0),
            released_hatch_center_z_mm=317.0,
            source_lid_replaced_one_for_one=True,
            final_exterior_visible=False,
            access_requires_unoccupied=True,
            access_requires_both_upper_drawers_open=True,
            no_third_exterior_drawer_seam=True,
        )
    )

    # Final outer service skins sit beyond the released drawer fronts and below
    # the A05 armrests.  They hide drawer-wall/cot-latch noise as one clean
    # module while preserving a dedicated release and the original UWB datum.
    for side_name, side in (("left", -1), ("right", 1)):
        service_y = side * 363.0
        door = _rounded_panel_xz((464.0, 86.0), 4.0, (-20.0, service_y, 366.0), 18.0)
        # Continue the removable equipment skin up to the A05 root datum.  It
        # closes the former 9.6 mm daylight line without inventing a separate
        # garnish: the transition is one fused return on the existing door.
        root_transition = _rounded_panel_xz(
            (520.0, 14.0),
            4.0,
            (-120.0, side * 365.0, 412.5),
            6.0,
        )
        # Keep the released UWB radome wholly exposed.  The transition remains
        # continuous above the radome and joins the door on both sides.
        root_transition = root_transition.cut(
            rounded_box(
                (132.0, 12.0, 12.0),
                (-75.0, side * 365.0, 408.0),
                4.0,
            )
        )
        door = union_many((door, root_transition))
        parts.append(
            _skin_part(
                f"A04_upper_equipment_door_{side_name}",
                door,
                LUNAR_STONE,
                "Gasketed painted magnesium/PC-ABS equipment-bay door",
                "A04",
                configuration,
                "One flush serviceable skin covers the exposed drawer front and cot latch, then turns continuously into the A05 root without deleting their access path.",
                functional_opening="upper_equipment_bay",
                source_drawer_clearance_mm=23.0,
                tool_less_release=True,
                armrest_root_transition_z_mm=(405.5, 419.5),
                armrest_root_visual_gap_mm=0.5,
            )
        )

        release = _rounded_panel_xz(
            (30.0, 10.0),
            2.0,
            (176.0, side * 366.0, 366.0),
            4.0,
        )
        parts.append(
            _skin_part(
                f"A04_upper_equipment_release_{side_name}",
                release,
                CHAMPAGNE,
                "Anodised aluminium two-action release paddle",
                "A04",
                configuration,
                "A small deliberate release preserves cot/drawer access without exposing the prototype latch stack.",
                functional_opening="cots_latch drawer_release",
            )
        )

        uwb = _rounded_panel_xz(
            (120.0, 20.0),
            2.0,
            (-75.0, side * 366.0, 400.0),
            7.0,
        )
        parts.append(
            _skin_part(
                f"A04_side_uwb_radome_{side_name}",
                uwb,
                SMOKED_UMBER,
                "Paint-matched RF-transparent polycarbonate radome",
                "A04",
                configuration,
                "Flush final UWB window at the released side datum; electronics remain behind the equipment door.",
                functional_opening="side_uwb_rf_window",
                controlled_center_mm=(-75.0, side * 366.0, 400.0),
            )
        )

    # A body-colour dorsal cap now conceals the structural crossbar from every
    # normal viewing direction.  The oversized, downward-shifted inner volume
    # leaves the underside and both positive latches open for a real hand.
    recovery_outer = rounded_box((62.0, 556.0, 42.0), (245.0, 0.0, 483.0), 15.0)
    recovery_inner = rounded_box((50.0, 544.0, 60.0), (245.0, 0.0, 466.0), 11.0)
    recovery_skin = recovery_outer.cut(recovery_inner)
    parts.append(
        _skin_part(
            "A04_recovery_handle_grip_shell",
            recovery_skin,
            LUNAR_STONE,
            "Body-colour PC-ABS recovery-handle shroud over the released load path",
            "A04",
            configuration,
            "A continuous body-colour cap hides the stowed recovery crossbar while leaving the hand route and both positive latches reachable from below.",
            functional_opening="manual_recovery_handle positive_latches",
            open_bottom=True,
            source_clearance_mm=2.0,
        )
    )
    recovery_grip = rounded_box((42.0, 360.0, 3.0), (245.0, 0.0, 495.0), 1.3)
    parts.append(
        _skin_part(
            "A04_recovery_handle_grip_inlay",
            recovery_grip,
            TPE_DARK,
            "Replaceable warm-touch moulded TPE grip inlay",
            "A04",
            configuration,
            "A recessed contact island on the hidden underside identifies the grasp zone without making a structural bar part of the exterior graphic.",
            functional_opening="manual_recovery_handle_grasp_zone",
            recessed_under_shroud=True,
        )
    )
    return parts


def _footrest_skin(configuration: str) -> list[SkinPart]:
    """A08: final footrest skin and two moving support boots."""

    parts: list[SkinPart] = []
    state_evidence = footrest_state_evidence(configuration)
    deployed = default_footrest_is_deployed(configuration)
    platform_x = P.footrest_deployed_x if deployed else -360.0
    platform_z = (
        P.footrest_deployed_z + P.footrest_thickness / 2.0
        if deployed
        else 147.0
    )

    top = rounded_rect_prism(
        (P.footrest_length - 4.0, P.footrest_width - 4.0),
        6.0,
        (platform_x, 0.0, platform_z + 8.0),
        18.0,
    )
    # Author the final three through-drains in the canonical source B-Rep.
    # The functional-fix pass reuses the same 12 x 96 mm tools and is therefore
    # an idempotent verification, not a second state-dependent geometry edit.
    drain_offsets_x = (-50.0, 0.0, 50.0)
    top = cut_many(
        top,
        [
            rounded_rect_prism(
                (12.0, 96.0),
                20.0,
                (platform_x + x_offset, 0.0, platform_z + 10.0),
                6.0,
            )
            for x_offset in drain_offsets_x
        ],
    )
    tread = rounded_rect_prism(
        (P.footrest_length - 30.0, P.footrest_width - 32.0),
        3.0,
        (platform_x - 2.0, 0.0, platform_z + 12.5),
        16.0,
    )
    tread = cut_many(
        tread,
        [
            rounded_box(
                (14.0, 120.0, 10.0),
                (platform_x + x_offset, 0.0, platform_z + 12.5),
                6.0,
            )
            for x_offset in drain_offsets_x
        ],
    )
    edge = rounded_frame(
        (P.footrest_length, P.footrest_width),
        (P.footrest_length - 18.0, P.footrest_width - 18.0),
        P.footrest_thickness,
        (
            platform_x,
            0.0,
            platform_z,
        ),
        18.0,
    )
    # One continuous rear service throat receives the central release and both
    # captured-rail roots.  The former three cutters were centred 20 mm beyond
    # the +105 mm platform edge and removed essentially no material; moving
    # hardware therefore had no physical route through the perimeter.  A
    # single wide opening also avoids isolating a loose rear-centre strip while
    # retaining the two 9 mm corner ligaments into the side rails.
    edge = edge.cut(
        rounded_box(
            (28.0, 456.0, 30.0),
            (platform_x + 101.0, 0.0, platform_z + 1.0),
            6.0,
        )
    )
    if not edge.isValid() or len(edge.Solids()) != 1:
        raise ValueError(
            f"A08 {configuration} rear service throat split the perimeter"
        )
    parts.extend(
        [
            _skin_part(
                "A08_footrest_top_skin",
                top,
                LUNAR_STONE,
                "Impact-modified PC-ABS thin structural footrest shell",
                "A08",
                configuration,
                "The same light continuous platform shell remains one physical object in stowed and deployed poses; no mode-specific surrogate plate is permitted.",
                physical_occurrence_id="E6-A08-PLATFORM-TOP-SKIN",
                controlled_outer_envelope_mm=(
                    P.footrest_length,
                    P.footrest_width,
                    P.footrest_thickness,
                ),
                **state_evidence,
            ),
            _skin_part(
                "A08_footrest_inset_tread",
                tread,
                GRAPHITE_BROWN,
                "Replaceable high-grip moulded TPE inset",
                "A08",
                configuration,
                "A shallow warm-dark contact island provides grip and drainage without turning the whole footrest into a separate black board.",
                drain_slots=3,
                inset_height_mm=3.0,
                physical_occurrence_id="E6-A08-PLATFORM-TREAD",
                **state_evidence,
            ),
            _skin_part(
                "A08_footrest_perimeter_skin",
                edge,
                LUNAR_STONE,
                "Impact-modified PC-ABS bonded edge close-out",
                "A08",
                configuration,
                "Hides sandwich-panel edges while leaving the rear latch and support roots accessible.",
                physical_occurrence_id="E6-A08-PLATFORM-PERIMETER-SKIN",
                **state_evidence,
            ),
        ]
    )

    # WC-A08-MANUAL-LATCH is fixed to the body side in the controlled DFR4
    # contract; unlike the platform and supports, it does not translate when
    # the footrest changes pose.  Its finished, glove-operable over-shell is
    # therefore the same physical exterior occurrence in all four primary
    # states.  The A01 pass owns one permanent underside clearance corridor.
    latch_outer = rounded_box((58.0, 92.0, 38.0), (-460.0, 0.0, 108.0), 10.0)
    latch_inner = rounded_box((62.0, 82.0, 28.0), (-460.0, 0.0, 108.0), 7.0)
    latch_shell = latch_outer.cut(latch_inner)
    parts.append(
        _skin_part(
            "A08_manual_release_paddle_shell",
            latch_shell,
            CHAMPAGNE,
            "split anodised aluminium/TPE over-shell around safety-rated latch",
            "A08",
            configuration,
            "The one body-side finished paddle wraps the controlled no-power footrest latch in every pose while leaving its rear movement and authorised underside actuation open.",
            functional_opening="footrest_manual_latch no_power_release",
            physical_occurrence_id="E6-A08-MANUAL-RELEASE-PADDLE-SHELL",
            body_side_fixed=True,
            pose_invariant=True,
            moves_with="body",
            source_clearance_mm=1.0,
            open_along_x=True,
            real_mechanical_link_required=True,
            rigid_source_common_volume_target_mm3=0.0,
            **state_evidence,
        )
    )

    if not deployed:
        return parts

    support_length = abs(
        (P.body_x - P.body_length / 2.0) - P.footrest_deployed_x
    )
    support_x = (
        P.body_x - P.body_length / 2.0 + P.footrest_deployed_x
    ) / 2.0
    for side_name, side in (("left", -1), ("right", 1)):
        outer = rounded_box(
            (support_length + 14.0, 54.0, 50.0),
            (support_x, side * 220.0, P.footrest_deployed_z + 20.0),
            18.0,
        )
        # Open at both ends around the released 40 mm support fairing so this
        # remains a moving boot, not a fixed obstruction over the mechanism.
        inner = rounded_box(
            (support_length + 28.0, 38.0, 36.0),
            (support_x, side * 220.0, P.footrest_deployed_z + 20.0),
            12.0,
        )
        boot = outer.cut(inner)
        drain = rounded_box(
            (32.0, 16.0, 14.0),
            (support_x, side * 220.0, P.footrest_deployed_z - 3.0),
            5.0,
        )
        boot = boot.cut(drain)
        parts.append(
            _skin_part(
                f"A08_footrest_support_boot_{side_name}",
                boot,
                LUNAR_STONE,
                "body-colour segmented UV/oil-resistant telescoping support shroud",
                "A08",
                configuration,
                "Fully shrouds the exposed deployment support while moving with it and preserving end release paths.",
                released_support_section_mm=P.footrest_support_section,
                open_ends=True,
                lower_drain=True,
                **state_evidence,
            )
        )

        # The moving TPE boot now disappears into a fixed body-colour root
        # collar instead of terminating as an exposed tube.  Its inner opening
        # clears the complete boot by 2 mm per side, remains open along X and
        # has a bottom drain, so neither travel nor contamination inspection is
        # compromised.
        collar_outer = rounded_box(
            (24.0, 76.0, 72.0),
            (-464.0, side * 220.0, P.footrest_deployed_z + 20.0),
            16.0,
        )
        collar_inner = rounded_box(
            (36.0, 58.0, 54.0),
            (-464.0, side * 220.0, P.footrest_deployed_z + 20.0),
            12.0,
        )
        collar = collar_outer.cut(collar_inner)
        collar = collar.cut(
            rounded_box(
                (14.0, 18.0, 14.0),
                (-464.0, side * 220.0, P.footrest_deployed_z - 15.0),
                4.0,
            )
        )
        parts.append(
            _skin_part(
                f"A08_footrest_support_body_collar_{side_name}",
                collar,
                LUNAR_STONE,
                "Impact-modified PC-ABS fixed support-root collar",
                "A08",
                configuration,
                "A fixed body-colour collar receives the moving support boot so no released bracket or tube is exposed at the body end.",
                moving_boot_clearance_mm=2.0,
                open_along_x=True,
                lower_drain=True,
                **state_evidence,
            )
        )

        # A broad open-bottom root cowl overlaps the collar and the rear third
        # of the footplate.  This makes the two protected support members read
        # as one deployment drawer instead of two add-on tubes, while the
        # centre latch remains completely unobstructed between the cowls.
        cowl_outer = rounded_box(
            (88.0, 230.0, 70.0),
            (-510.0, side * 150.0, 98.0),
            24.0,
        )
        cowl_inner = rounded_box(
            (100.0, 198.0, 58.0),
            (-510.0, side * 150.0, 86.0),
            18.0,
        )
        root_cowl = cowl_outer.cut(cowl_inner)
        if not root_cowl.isValid() or len(root_cowl.Solids()) != 1:
            raise ValueError(f"A08 {side_name} footrest root cowl is invalid")
        parts.append(
            _skin_part(
                f"A08_footrest_root_cowl_{side_name}",
                root_cowl,
                LUNAR_STONE,
                "body-colour open-bottom PC-ABS deployment-root cowl",
                "A08",
                configuration,
                "A smooth side saddle overlaps the support boot, fixed collar and rear footplate edge so the deployed assembly reads as one protected drawer.",
                moving_with_footrest=True,
                open_bottom=True,
                open_along_x=True,
                centre_manual_latch_unobstructed=True,
                gravity_drain=True,
                **state_evidence,
            )
        )

    return parts


def _rear_service_frame(configuration: str) -> list[SkinPart]:
    """A10: rear close-out, final service-door skin and sensing apertures."""

    # One deep rear shell now keys 25 mm into the controlled body envelope and
    # continues down to Z=99.  This replaces the former 14 mm picture-frame
    # applique and its visually suspended lower edge with a single load-bearing
    # volume.  All service and sensing apertures are cut through its full depth.
    outer = rounded_box((38.0, 500.0, 366.0), (314.0, 0.0, 282.0), 18.0)
    # One enlarged aperture clears the complete guarded charge-port envelope
    # at Y=-140 as well as disconnect/brake service.  The former 316 x 178 mm
    # cut clipped the real 72 mm-wide charge-port B-Rep and forced the core
    # equipment into the rear surround.  A single larger door is visually
    # quieter than adding secondary service seams.
    aperture = rounded_box((50.0, 376.0, 216.0), (314.0, 0.0, 316.0), 16.0)
    rear_tof_tunnel = rounded_box((50.0, 58.0, 30.0), (314.0, 0.0, 133.0), 6.0)
    pressure_vent_tunnel = rounded_box(
        (50.0, 58.0, 58.0),
        (314.0, 0.0, 178.0),
        8.0,
    )
    # The one-piece low A07 moving spine begins at Z=438 and passes through
    # the former solid top rail of this surround.  A real rounded through-slot
    # clears its 54.33 x 120.88 mm maximum low section by at least 3.5 mm per
    # side; leaving the rail uncut creates 24,517 mm3 of hidden rigid
    # interference in Ride/Cafe even though the exterior silhouette looks
    # closed.  A06's continuous channel remains the weather/sightline cover.
    mast_low_spine_tunnel = rounded_box(
        (62.4, 128.4, 72.0),
        (310.0, 0.0, 465.0),
        12.0,
    )
    frame = cut_many(
        outer,
        (
            aperture,
            rear_tof_tunnel,
            pressure_vent_tunnel,
            mast_low_spine_tunnel,
        ),
    )

    # Bottom drain breaks prevent the new lower apron becoming a water trough.
    # They finish below the ToF tunnel and remain clear of the pressure vent.
    frame = cut_many(
        frame,
        [
            rounded_box((50.0, 24.0, 24.0), (314.0, y, 99.0), 6.0)
            for y in (-170.0, 0.0, 170.0)
        ],
    )
    door_skin = _rounded_panel_yz((366.0, 206.0), 3.0, (329.0, 0.0, 316.0), 20.0)
    # The source rear UWB radome and horn sit behind this otherwise conductive
    # magnesium door.  Real through-apertures are mandatory; exterior appliques
    # alone would still leave RF and acoustic paths blocked.
    rear_uwb_door_tunnel = rounded_box(
        (12.0, 90.0, 34.0),
        (329.0, 0.0, 270.0),
        7.0,
    )
    horn_door_tunnel = rounded_box(
        (12.0, 68.0, 30.0),
        (329.0, 0.0, 400.0),
        6.0,
    )
    door_skin = cut_many(door_skin, (rear_uwb_door_tunnel, horn_door_tunnel))
    # Keep the status line at the controlled source Z=420 datum on the fixed
    # upper surround.  The earlier Z=410 cosmetic shift put the lens directly
    # through the horn mesh (655.4 mm3 common volume) and also made a fixed
    # status interface appear to travel with the removable service door.  At
    # Z=420 its lower edge is 2.5 mm above the horn outlet and the service pass
    # cuts an honest seat into the fixed surround.
    status_lens = _rounded_panel_yz((140.0, 7.0), 2.0, (331.5, 0.0, 420.0), 3.0)
    rear_tof = _rounded_panel_yz((50.0, 22.0), 2.0, (332.0, 0.0, 133.0), 6.0)
    rear_uwb = _rounded_panel_yz((80.0, 24.0), 2.0, (332.0, 0.0, 270.0), 7.0)
    horn_mesh = _rounded_panel_yz((64.0, 28.0), 2.0, (332.0, 0.0, 400.0), 6.0)
    service_release_guard = (
        cq.Workplane("YZ")
        .circle(18.0)
        .circle(13.0)
        .extrude(4.0)
        .translate((330.0, 120.0, 330.0))
        .val()
    )
    service_release_turn = (
        cq.Workplane("YZ")
        .circle(11.0)
        .extrude(4.0)
        .translate((331.0, 120.0, 330.0))
        .val()
    )
    # Two millimetres of rear inset preserve the glove opening while reserving
    # enough locked Follow length for a real 1.90 mm front wheel-arch return.
    pull_cup_outer = rounded_box((8.0, 70.0, 30.0), (331.0, -80.0, 330.0), 10.0)
    pull_cup_inner = rounded_box((10.0, 54.0, 18.0), (333.0, -80.0, 330.0), 7.0)
    service_pull_cup = pull_cup_outer.cut(pull_cup_inner)
    service_pull_grip = _rounded_panel_yz(
        (50.0, 10.0),
        2.0,
        (330.5, -80.0, 330.0),
        4.0,
    )
    vent_bezel = _rounded_panel_yz((76.0, 66.0), 3.0, (332.0, 0.0, 178.0), 12.0)
    vent_bezel = vent_bezel.cut(
        rounded_box((8.0, 50.0, 50.0), (332.0, 0.0, 178.0), 7.0)
    )

    return [
        _skin_part(
            "A10_rear_service_surround",
            frame,
            LUNAR_STONE,
            "Painted PC-ABS rear close-out surround",
            "A10",
            configuration,
            "Covers rear enclosure edges while leaving the whole flush door, guarded ports, status line and horn serviceable.",
            service_aperture_mm=(376.0, 216.0),
            single_enlarged_service_door=True,
            guarded_charge_port_full_brep_clearance=True,
            pressure_vent_unobstructed=True,
            drain_breaks=3,
            shell_x_range_mm=(295.0, 333.0),
            lower_apron_z_range_mm=(99.0, 222.0),
            rear_tof_through_tunnel_mm=(58.0, 30.0),
            pressure_vent_through_tunnel_mm=(58.0, 58.0),
            a07_low_spine_through_tunnel_mm=(62.4, 128.4, 72.0),
            a07_low_spine_tunnel_center_mm=(310.0, 0.0, 465.0),
            a07_low_spine_minimum_nominal_radial_clearance_mm=3.5,
            a07_low_spine_tunnel_hidden_by_a06_channel=True,
        ),
        _skin_part(
            "A10_rear_flush_service_door_skin",
            door_skin,
            LUNAR_STONE,
            "Gasketed painted magnesium service-door outer skin",
            "A10",
            configuration,
            "One flush final door skin hides charge, disconnect and brake-release hardware until authorized service opening.",
            functional_opening="rear_service_door charge_port battery_disconnect brake_release",
            source_door_clearance_mm=1.5,
            quarter_turn_internal_release=True,
            through_apertures=("rear_uwb_rf_window", "rear_horn_acoustic_outlet"),
            rear_uwb_door_aperture_yz_mm=(90.0, 34.0),
            rear_horn_door_aperture_yz_mm=(68.0, 30.0),
            release_via="E6-A10-REAR-SERVICE-EXTERNAL-RELEASE",
            handhold_via="E6-A10-REAR-SERVICE-PULL-CUP",
            access_chain=("external_release", "door_open", "charge_disconnect_brake"),
        ),
        _skin_part(
            "A10_rear_status_lens",
            status_lens,
            CHAMPAGNE,
            "Diffused sealed status lens with non-colour redundant pattern",
            "A10",
            configuration,
            "A restrained rear status line remains readable at two metres without becoming a decorative light band.",
            functional_opening="rear_status_light",
            controlled_source_center_z_mm=420.0,
            fixed_to_rear_service_surround=True,
            service_door_carried=False,
            minimum_horn_mesh_edge_gap_mm=2.5,
        ),
        _skin_part(
            "A10_rear_tof_window",
            rear_tof,
            SMOKED_UMBER,
            "Hard-coated IR-transparent polycarbonate",
            "A10",
            configuration,
            "Flush rear ranging window at the released datum.",
            functional_opening="rear_tof_window",
        ),
        _skin_part(
            "A10_rear_uwb_radome",
            rear_uwb,
            SMOKED_UMBER,
            "RF-transparent paint-matched polycarbonate",
            "A10",
            configuration,
            "Flush rear UWB window; module and fasteners remain behind the rear skin.",
            functional_opening="rear_uwb_rf_window",
            source_radome_bbox_mm=((327.0, 330.0), (-40.0, 40.0), (258.0, 282.0)),
            door_perimeter_clearance_mm=2.0,
        ),
        _skin_part(
            "A10_rear_horn_acoustic_mesh",
            horn_mesh,
            GRAPHITE_BROWN,
            "Hydrophobic laser-microperforated stainless acoustic mesh",
            "A10",
            configuration,
            "A dedicated through-door acoustic outlet preserves the rear warning horn while hiding the transducer and fasteners.",
            functional_opening="rear_horn_acoustic_outlet",
            source_horn_bbox_mm=((319.0, 325.0), (-30.0, 30.0), (386.0, 414.0)),
            membrane="hydrophobic ePTFE-backed microperforated mesh",
            ip_validation_required=True,
            sound_pressure_validation_required=True,
        ),
        _skin_part(
            "A10_rear_service_external_release_guard",
            service_release_guard,
            CHAMPAGNE,
            "satin anodised guard ring around keyed quarter-turn release",
            "A10",
            configuration,
            "A guarded exterior datum makes the closed service door enterable with main power absent.",
            physical_occurrence_id="E6-A10-REAR-SERVICE-RELEASE-GUARD",
            functional_opening="rear_service_door_external_release",
        ),
        _skin_part(
            "A10_rear_service_external_no_power_release",
            service_release_turn,
            GRAPHITE_BROWN,
            "keyed two-action mechanical quarter-turn release",
            "A10",
            configuration,
            "A glove-operable, keyed two-action release opens the service door without electrical power.",
            physical_occurrence_id="E6-A10-REAR-SERVICE-EXTERNAL-RELEASE",
            functional_opening="rear_service_door_external_release manual_no_power",
            manual_no_power=True,
            two_action=True,
            access_via="external_rear_surface",
            releases=("charge_port", "battery_disconnect", "brake_release"),
        ),
        _skin_part(
            "A10_rear_service_pull_cup",
            service_pull_cup,
            LUNAR_STONE,
            "moulded open-front service-door pull cup",
            "A10",
            configuration,
            "A sealed undercut grip provides a real handhold after release without adding a luggage handle.",
            physical_occurrence_id="E6-A10-REAR-SERVICE-PULL-CUP",
            functional_opening="rear_service_door_handhold",
            glove_clearance_mm=(54.0, 18.0),
            open_axis="+X",
        ),
        _skin_part(
            "A10_rear_service_pull_grip_inlay",
            service_pull_grip,
            TPE_DARK,
            "replaceable high-grip TPE pull surface",
            "A10",
            configuration,
            "A dark tactile surface is visible only inside the authorized service grip recess.",
            physical_occurrence_id="E6-A10-REAR-SERVICE-PULL-INLAY",
            functional_opening="rear_service_door_handhold",
        ),
        _skin_part(
            "A10_pressure_relief_vent_bezel",
            vent_bezel,
            GRAPHITE_BROWN,
            "High-temperature glass-filled PA12 vent bezel",
            "A10",
            configuration,
            "An open bezel leaves the battery pressure-relief duct unobstructed while preventing it reading as an exposed pipe.",
            functional_opening="battery_pressure_relief",
            unobstructed_opening_mm=(50.0, 50.0),
            nominal_free_area_mm2=2500.0,
            source_mouth_area_mm2=1764.0,
            discharge_direction="rearward_away_from_occupant",
        ),
    ]


def build_lower_skin(config: object) -> list[SkinPart]:
    """Build all lower Class-A skin modules for one controlled E6 state.

    Returned shapes are separate serviceable solids.  No boolean operation is
    performed on the source STEP assembly and no file is written by this
    function.
    """

    configuration = _configuration_name(config)
    return [
        *_front_nose(configuration),
        *_side_shells(configuration),
        *_wheel_bridge_and_caps(configuration),
        *_seat_pan_ring(configuration),
        *_footrest_skin(configuration),
        *_rear_service_frame(configuration),
    ]


__all__ = ["build_lower_skin"]
