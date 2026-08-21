"""STEP-anchored upper Class-A cladding for WorkCore E6.

This is an independent exterior-skin study.  It reads no production STEP and
writes nothing.  The controlled E6 coordinates and hard points are repeated
locally so importing this module cannot mutate ``cad/`` or ``build/``.

Coordinates (mm): -X front, +X rear, +Y right, -Y left, +Z up.
Supported states: Follow, Ride, Cafe and Focus.  Alias names from the controlled
assembly (``follow_closed``, ``seat_ready``, ``cafe`` and ``desk``) are accepted.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import cadquery as cq

try:  # Package import in the final Class-A assembly.
    from .skin_common import (
        CHAMPAGNE,
        ESPRESSO,
        GRAPHITE_BROWN,
        LUNAR_STONE,
        SAFETY_RED,
        SMOKED_UMBER,
        TPE_DARK,
        SkinPart,
        cut_many,
        rounded_box,
        rounded_frame,
        rounded_rect_prism,
        union_many,
    )
except ImportError:  # Direct module loading during isolated CAD validation.
    from skin_common import (  # type: ignore[no-redef]
        CHAMPAGNE,
        ESPRESSO,
        GRAPHITE_BROWN,
        LUNAR_STONE,
        SAFETY_RED,
        SMOKED_UMBER,
        TPE_DARK,
        SkinPart,
        cut_many,
        rounded_box,
        rounded_frame,
        rounded_rect_prism,
        union_many,
    )

try:
    from .v8_table_lid_packaging import (
        CAFE_FINAL_AXIS_Y_MM,
        FOCUS_LOCK_STATIONS_X_MM,
        TABLE_ACCESS_SEQUENCE,
        cafe_half_leaf_pair,
        unfolded_half_leaf,
    )
except ImportError:
    from v8_table_lid_packaging import (  # type: ignore[no-redef]
        CAFE_FINAL_AXIS_Y_MM,
        FOCUS_LOCK_STATIONS_X_MM,
        TABLE_ACCESS_SEQUENCE,
        cafe_half_leaf_pair,
        unfolded_half_leaf,
    )

try:
    from .v8_cafe_table_root_motion import (
        CAFE_PADDLE_OUTER_UNDERSIDE_Y_MM,
        CAFE_CONTROL_TOP_Z_MM,
        CAFE_WITNESS_OUTER_UNDERSIDE_Y_MM,
        cafe_root_final_occurrences,
        cafe_table_control_final_occurrences,
    )
except ImportError:
    from v8_cafe_table_root_motion import (  # type: ignore[no-redef]
        CAFE_PADDLE_OUTER_UNDERSIDE_Y_MM,
        CAFE_CONTROL_TOP_Z_MM,
        CAFE_WITNESS_OUTER_UNDERSIDE_Y_MM,
        cafe_root_final_occurrences,
        cafe_table_control_final_occurrences,
    )


# Controlled E6-DFR5-A07-SHARED-HINGE hard points (unchanged interfaces remain
# traceable through parent DFR4 to the preserved E6-DFR3 source).  These are
# not styling variables.
ARM_X_MIN = -380.0
ARM_X_MAX = 140.0
ARM_X_CENTRE = (ARM_X_MIN + ARM_X_MAX) / 2.0
ARM_LENGTH = ARM_X_MAX - ARM_X_MIN
ARM_INNER_Y = 310.0
ARM_OUTER_Y = 367.5
ARM_Z_MIN = 420.0
ARM_Z_MAX = 680.0

BACK_HINGE = (160.0, 0.0, 515.0)
BACK_RAKE_DEG = 6.0
BACK_FOLD_DEG = -95.0

MAST_X = 310.0
MAST_FOLD_HINGE = BACK_HINGE
MAST_STROKE = 420.0
BEAM_LOW_Z = 1040.0
BEAM_SIZE = (80.0, 320.0, 64.0)

TABLE_LENGTH = 430.0
TABLE_WIDTH = 270.0
TABLE_THICKNESS = 12.0
TABLE_Z = 705.0 - TABLE_THICKNESS / 2.0
TABLE_GAP = 12.0
TABLE_FOCUS_X = -405.0
TABLE_CAFE_X = -350.0
TABLE_CAFE_POLE_X = -272.0

# Focus is no longer carried by the exposed prototype posts at X=-405,
# Y=+/-300.  Each leaf now terminates in a flat, fully concealed telescopic
# root inside its adjacent A05 armrest cavity.  These are packaging hardpoints,
# not styling variables: the complete fixed/moving root stays below the closed
# lid and inside the useful cavity rather than demanding a top aperture.
FOCUS_ROOT_AXIS_X = -343.0
FOCUS_ROOT_AXIS_ABS_Y = 338.75
FOCUS_ROOT_CAVITY_X_MM = (-361.0, -325.0)
FOCUS_ROOT_CAVITY_RIGHT_Y_MM = (317.5, 360.0)
FOCUS_ROOT_MECHANISM_Z_MAX_MM = 674.0


_STATE_ALIASES = {
    "follow": "follow",
    "follow_closed": "follow",
    "stowed": "follow",
    "obstacle": "follow",
    "ride": "ride",
    "seat": "ride",
    "seat_ready": "ride",
    "transfer": "ride",
    "cafe": "cafe",
    "café": "cafe",
    "focus": "focus",
    "desk": "focus",
}


def _normalise_state(config: str | Mapping[str, Any]) -> str:
    if isinstance(config, Mapping):
        raw = config.get("configuration", config.get("state", config.get("mode", "")))
    else:
        raw = config
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _STATE_ALIASES[key]
    except KeyError as exc:
        allowed = ", ".join(("follow", "ride", "cafe", "focus"))
        raise ValueError(f"Unsupported upper-skin state {raw!r}; expected {allowed}") from exc


def _rotate_y(shape: cq.Shape, origin: tuple[float, float, float], degrees: float) -> cq.Shape:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox, oy + 1.0, oz), degrees)


def _rotate_x(shape: cq.Shape, origin: tuple[float, float, float], degrees: float) -> cq.Shape:
    ox, oy, oz = origin
    return shape.rotate((ox, oy, oz), (ox + 1.0, oy, oz), degrees)


def _trapezoid_prism(
    bottom_width: float,
    top_width: float,
    height: float,
    depth: float,
    *,
    x_center: float,
    z0: float,
    corner_radius: float = 0.0,
) -> cq.Shape:
    """Extrude an upright YZ trapezoid, with a conservative edge fillet."""

    body = (
        cq.Workplane("YZ")
        .polyline(
            [
                (-bottom_width / 2.0, 0.0),
                (bottom_width / 2.0, 0.0),
                (top_width / 2.0, height),
                (-top_width / 2.0, height),
            ]
        )
        .close()
        .extrude(depth / 2.0, both=True)
    )
    if corner_radius > 0.0:
        for radius in (corner_radius, corner_radius * 0.6, corner_radius * 0.3):
            try:
                body = body.edges("|X").fillet(radius)
                break
            except Exception:
                continue
    return body.translate((x_center, 0.0, z0)).val()


def _rounded_rect_wire_xy(
    size_xy: tuple[float, float],
    center_xy: tuple[float, float],
    z: float,
    radius: float,
) -> cq.Wire:
    """Build a rounded XY section wire for curvature-controlled lofts.

    ``rounded_box`` is deliberately retained for local covers and cutters, but
    the primary A05/A07 volumes need changing sections rather than one constant
    radius box.  Sketch fillets keep the plan corner radius independent of the
    very small skin thickness.
    """

    sx, sy = size_xy
    cx, cy = center_xy
    safe = min(radius, sx * 0.49, sy * 0.49)
    sketch = cq.Sketch().rect(sx, sy)
    if safe > 0.0:
        sketch = sketch.vertices().fillet(safe)
    wire = sketch.reset().wires().val()
    if not isinstance(wire, cq.Wire):
        raise TypeError("Rounded loft section did not resolve to a wire")
    return wire.translate((cx, cy, z))


def _rounded_rect_wire_xz(
    size_xz: tuple[float, float],
    center: tuple[float, float, float],
    radius: float,
) -> cq.Wire:
    """Create one consistently oriented rounded wire on a world XZ plane."""

    sx, sz = size_xz
    safe = min(radius, sx * 0.45, sz * 0.45)
    sketch = cq.Sketch().rect(sx, sz)
    if safe > 0.0:
        sketch = sketch.vertices().fillet(safe)
    faces = sketch._faces.Faces()
    if len(faces) != 1:
        raise ValueError("Rounded XZ loft section did not create one face")
    return (
        faces[0]
        .outerWire()
        .rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 90.0)
        .translate(center)
    )


def _rounded_loft_z(
    sections: tuple[
        tuple[tuple[float, float], tuple[float, float], float, float],
        ...,
    ],
) -> cq.Solid:
    """Create one smooth solid through ``(size, centre, z, radius)`` sections."""

    if len(sections) < 2:
        raise ValueError("A rounded loft requires at least two sections")
    wires = [
        _rounded_rect_wire_xy(size_xy, center_xy, z, radius)
        for size_xy, center_xy, z, radius in sections
    ]
    body = cq.Solid.makeLoft(wires, ruled=False)
    if not body.isValid():
        raise ValueError("Rounded section loft produced an invalid solid")
    return body


def _rounded_panel_xz(
    size_xz: tuple[float, float],
    thickness_y: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    """Thin rounded panel with its calm presentation face on the XZ plane."""

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


def _rounded_trapezoid_wire_yz(
    bottom_width: float,
    top_width: float,
    height: float,
    *,
    x: float,
    z0: float,
    corner_radius: float,
) -> cq.Wire:
    """Rounded trapezoid section located on a global YZ plane."""

    points = (
        (-bottom_width / 2.0, 0.0),
        (bottom_width / 2.0, 0.0),
        (top_width / 2.0, height),
        (-top_width / 2.0, height),
    )
    sketch = cq.Sketch().polygon(points)
    safe = min(corner_radius, bottom_width * 0.2, top_width * 0.2, height * 0.2)
    if safe > 0.0:
        sketch = sketch.vertices().fillet(safe)
    wire = sketch.reset().wires().val()
    if not isinstance(wire, cq.Wire):
        raise TypeError("Crowned trapezoid section did not resolve to a wire")
    plane = cq.Plane((x, 0.0, z0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
    return wire.moved(cq.Location(plane))


def _crowned_trapezoid_skin(
    bottom_width: float,
    top_width: float,
    height: float,
    depth: float,
    *,
    x_center: float,
    z0: float,
    corner_radius: float,
    end_inset: float,
) -> cq.Solid:
    """Thin, volume-conserving A06 lens inside the released prism envelope."""

    end_bottom = bottom_width - 2.0 * end_inset
    end_top = top_width - 2.0 * end_inset
    wires = [
        _rounded_trapezoid_wire_yz(
            end_bottom,
            end_top,
            height,
            x=x_center - depth / 2.0,
            z0=z0,
            corner_radius=corner_radius,
        ),
        _rounded_trapezoid_wire_yz(
            bottom_width,
            top_width,
            height,
            x=x_center,
            z0=z0,
            corner_radius=corner_radius,
        ),
        _rounded_trapezoid_wire_yz(
            end_bottom,
            end_top,
            height,
            x=x_center + depth / 2.0,
            z0=z0,
            corner_radius=corner_radius,
        ),
    ]
    body = cq.Solid.makeLoft(wires, ruled=False)
    if not body.isValid():
        raise ValueError("Crowned trapezoid skin produced an invalid solid")
    return body


def _ring_xy(
    outer_diameter: float,
    inner_diameter: float,
    height: float,
    center: tuple[float, float, float],
) -> cq.Shape:
    cx, cy, cz = center
    ring = (
        cq.Workplane("XY")
        .circle(outer_diameter / 2.0)
        .circle(inner_diameter / 2.0)
        .extrude(height)
        .translate((cx, cy, cz - height / 2.0))
    )
    return ring.val()


def _part(
    name: str,
    shape: cq.Shape,
    color: tuple[float, float, float, float],
    material: str,
    module: str,
    state: str,
    intent: str,
    **metadata: Any,
) -> SkinPart:
    return SkinPart(
        name=name,
        shape=shape,
        color=color,
        material=material,
        module=module,
        configuration=state,
        intent=intent,
        metadata=metadata,
    )


def _right_table_root_tongue_passage() -> cq.Shape:
    """Fixed A05 passage for the Cafe leaf's concealed docking tongue.

    The hard opening is wholly behind the right armrest's occupant-side inner
    face.  It clears the final 11 x 23 mm vertical tongue by 1 mm per side and
    lets the top lid return to its exact locked datum after table extraction.
    """

    return rounded_box(
        (13.0, 25.0, 46.0),
        (-353.5, 328.0, 672.0),
        3.5,
    )


def _focus_table_root_sidewall_passage(side: int) -> cq.Shape:
    """Small A05 inner-wall port for one Focus leaf-attached root tongue.

    The port is deliberately below the closed lid.  It clears the 16 x 3 mm
    horizontal tongue by at least one millimetre per hard side while crossing
    only the occupant-side wall; no rail, hinge or support bracket is allowed
    to follow the tongue outside the armrest cavity.
    """

    if side not in {-1, 1}:
        raise ValueError(f"Focus root side must be -1 or 1, got {side}")
    return rounded_box(
        (19.0, 18.0, 7.0),
        (FOCUS_ROOT_AXIS_X, side * 312.0, 653.5),
        2.5,
    )


def _table_root_structural_cassette(side: int) -> cq.Shape:
    """One state-invariant metal root rail inside each A05 cavity.

    The 1.5 mm folded backplate stays behind the folded table pack.  Its upper
    local lug reaches the Café fixed housing, while the main face reaches the
    Focus root box.  Both interfaces are real face contacts; the cosmetic
    PC-ABS armrest shell is not treated as the primary table load path.
    """

    if side not in {-1, 1}:
        raise ValueError(f"A05 table-root cassette side must be -1 or 1, got {side}")
    backplate = rounded_box(
        (1.5, 32.0, 185.0),
        (-361.25, side * 338.75, 572.5),
        0.6,
    )
    cafe_lug = rounded_box(
        (1.5, 22.0, 32.0),
        (-359.75, side * 338.75, 642.0),
        0.5,
    )
    cassette = backplate.fuse(cafe_lug).clean()
    if cassette.isNull() or not cassette.isValid() or len(cassette.Solids()) != 1:
        raise ValueError(f"A05 side {side} table-root cassette is invalid")
    return cassette


def _table_root_structural_cassette_clearance(side: int) -> cq.Shape:
    """One-millimetre assembly/service keepout around the metal cassette.

    The keepout remains inside the hollow armrest and only relieves the inner
    PC-ABS fillet at the rear of the table bay.  Its rear face is still 17 mm
    inboard of the exterior rear datum, so it cannot create an exterior slot.
    """

    if side not in {-1, 1}:
        raise ValueError(f"A05 cassette-clearance side must be -1 or 1, got {side}")
    return rounded_box(
        (5.0, 34.0, 187.0),
        (-360.5, side * 338.75, 572.5),
        0.8,
    )


def _armrest_shell(side: int, state: str) -> list[SkinPart]:
    side_name = "right" if side > 0 else "left"
    y_center = side * ((ARM_INNER_Y + ARM_OUTER_Y) / 2.0)
    width = ARM_OUTER_Y - ARM_INNER_Y

    # Three changing plan sections turn the released 520 mm table bay into a
    # soft wing without shortening its structural datum.  The bottom section is
    # exactly X=-380..+140; the upper sections retreat inside that envelope.
    # The hollow is sized around the nominal 430 x 30 x 139 mm two-half-leaf
    # pack and its 432 x 32 x 141 mm maximum material envelope.
    outer = _rounded_loft_z(
        (
            ((ARM_LENGTH, width), (ARM_X_CENTRE, y_center), ARM_Z_MIN, 23.0),
            ((514.0, width), (ARM_X_CENTRE, y_center), 548.0, 24.0),
            ((506.0, width), (-122.0, y_center), 675.0, 23.0),
        )
    )
    inner = _rounded_loft_z(
        (
            ((493.0, 45.5), (ARM_X_CENTRE, y_center), 427.0, 17.0),
            ((490.0, 45.5), (ARM_X_CENTRE, y_center), 548.0, 18.0),
            ((480.0, 45.5), (-122.0, y_center), 676.0, 17.0),
        )
    )
    shell = outer.cut(inner)
    if not shell.isValid() or len(shell.Solids()) != 1:
        raise ValueError(f"A05 {side_name} soft-wing shell is not one valid solid")

    # The left HMI is a real service aperture, not a graphic applied to a lid.
    if side < 0:
        hmi_aperture = rounded_box(
            (292.0, 51.0, 34.0),
            (-225.0, -333.0, 678.0),
            6.0,
        )
        estop_access = rounded_box(
            (76.0, 34.0, 68.0),
            (-276.0, -306.0, 590.0),
            12.0,
        )
        shell = cut_many(shell, (hmi_aperture, estop_access))
    elif side > 0:
        pod_aperture = rounded_box(
            (124.0, 62.0, 30.0),
            (-250.0, 333.0, 680.0),
            12.0,
        )
        shell = shell.cut(pod_aperture)
        if state != "focus":
            shell = shell.cut(_right_table_root_tongue_passage())

    if state == "focus":
        shell = shell.cut(_focus_table_root_sidewall_passage(side))

    # The armrest body never opens sideways.  The same two-half-leaf table is
    # lifted through the full-length top opening after the lid has rotated
    # outward about its outer X-axis hinge.  Only a small gravity drain passes
    # through the outboard wall; the former 438 x 136 mm side throat was a
    # prototype shortcut and is deliberately absent from the final object.
    cassette_drain_tunnel = rounded_box(
        (24.0, 24.0, 10.0),
        (-300.0, side * 366.5, 526.0),
        3.0,
    )
    lid_release_aperture = rounded_box(
        (42.0, 8.0, 18.0),
        (-340.0, side * 313.0, 642.0),
        4.0,
    )
    shell = cut_many(
        shell,
        (
            cassette_drain_tunnel,
            lid_release_aperture,
            _table_root_structural_cassette_clearance(side),
        ),
    )
    if not shell.isValid() or len(shell.Solids()) != 1:
        raise ValueError(f"A05 {side_name} shell lost integrity at top-access bay")

    parts = [
        _part(
            f"A05_armrest_table_bay_shell_{side_name}",
            shell,
            LUNAR_STONE,
            "fine-matte PC-ABS structural cosmetic shell",
            "A05",
            state,
            "Continuous 520 mm armrest body enclosing table bundle, rail, latch and wiring.",
            physical_occurrence_id=f"E6-A05-ARMREST-SHELL-{side_name.upper()}",
            controlled_x_range_mm=(ARM_X_MIN, ARM_X_MAX),
            controlled_inner_y_mm=side * ARM_INNER_Y,
            controlled_outer_y_mm=side * ARM_OUTER_Y,
            exact_structural_length_mm=ARM_LENGTH,
            nominal_folded_table_bundle_mm=(430.0, 30.0, 139.0),
            maximum_folded_table_material_envelope_mm=(432.0, 32.0, 141.0),
            table_extraction_direction="upward_through_top_lid",
            legacy_side_table_aperture_present=False,
            fixed_armrest_body=True,
            surface_sections_z_mm=(ARM_Z_MIN, 548.0, 675.0),
            concealed_table_root_tongue_passage=(
                state == "focus" or side > 0
            ),
            table_root_tongue_passage_center_mm=(
                (
                    (FOCUS_ROOT_AXIS_X, side * 312.0, 653.5)
                    if state == "focus"
                    else (-353.5, 328.0, 672.0)
                    if side > 0
                    else None
                )
            ),
            table_root_hardware_inside_armrest_cavity=(
                state == "focus" or side > 0
            ),
            focus_root_passage_is_inner_sidewall_only=(state == "focus"),
            focus_closed_lid_top_aperture_present=False,
            table_root_cassette_internal_clearance_mm=1.0,
            table_root_cassette_keepout_reaches_exterior=False,
        )
    ]
    parts.append(
        _part(
            f"A05_table_root_structural_cassette_{side_name}",
            _table_root_structural_cassette(side),
            GRAPHITE_BROWN,
            "1.5 mm folded 316 stainless structural root rail with local hardpoint lug",
            "A05",
            state,
            "A state-invariant metal rail behind the folded table pack carries the concealed table root into the integrated chassis hardpoints; the PC-ABS armrest shell remains a weather and touch surface, not the primary cantilever support.",
            physical_occurrence_id=(
                f"E6-A05-TABLE-ROOT-STRUCTURAL-CASSETTE-{side_name.upper()}"
            ),
            fixed_to="A04_A05_integrated_side_sail_structural_hardpoints",
            state_invariant_physical_occurrence=True,
            sheet_thickness_mm=1.5,
            focus_root_contact_x_mm=-360.5,
            cafe_root_contact_x_mm=-359.0,
            primary_table_load_path=True,
            service_access="top_lid_open_table_pack_removed",
            final_exterior_visible=False,
            supplier_fastener_pattern_pending=True,
            production_certification_claimed=False,
        )
    )

    # A single body-colour lid spans the bay and remains visually quiet in all
    # four final states.  The complete armrest body is fixed; only this lid
    # rotates outward about the outer longitudinal edge.  Local functional
    # islands grow inward from that hinge, so no feature sweeps down into the
    # exterior shell during the 105 degree opening motion.
    cap = _rounded_loft_z(
        (
            ((506.0, width), (-122.0, y_center), 675.0, 23.0),
            ((500.0, width - 2.0), (-122.0, y_center), ARM_Z_MAX, 22.0),
        )
    )
    if side < 0:
        # 182 x 90 mm support carries a 170 x 84 x 13 mm cased-phone
        # envelope without moving the hinge outboard or widening the product.
        qi_support = rounded_rect_prism(
            (182.0, 90.0),
            5.0,
            (-136.0, -322.5, 677.5),
            18.0,
        )
        display_origin = (-294.0, -333.0, 681.0)
        display_plinth = rounded_box((142.0, 62.0, 8.0), display_origin, 10.0)
        display_plinth = _rotate_x(display_plinth, display_origin, -10.0)
        display_plinth = _rotate_y(display_plinth, display_origin, 5.0)
        cap = cap.fuse(qi_support).fuse(display_plinth)
        display_recess = rounded_box(
            (130.0, 54.0, 12.0),
            (-294.0, -333.0, 683.5),
            7.0,
        )
        display_recess = _rotate_x(
            display_recess, (-294.0, -333.0, 683.5), -10.0
        )
        display_recess = _rotate_y(
            display_recess, (-294.0, -333.0, 683.5), 5.0
        )
        cap = cap.cut(display_recess)
    else:
        pod_support = rounded_rect_prism(
            (124.0, 62.0),
            5.0,
            (-250.0, 336.5, 677.5),
            16.0,
        )
        cap = cap.fuse(pod_support).cut(
            rounded_box((122.0, 60.0, 14.0), (-250.0, 336.0, 684.0), 12.0)
        )
        if state != "focus":
            cap = cap.cut(_right_table_root_tongue_passage())

    # A one-millimetre elastomer reveal is the only visible evidence of the
    # concealed continuous hinge.  Its groove is cut at the cap's outer edge,
    # never through the fixed side wall.
    hinge_groove = rounded_box(
        (500.0, 1.5, 3.0),
        (-122.0, side * 366.75, 677.5),
        0.5,
    )
    cap = cap.cut(hinge_groove)
    if not cap.isValid() or len(cap.Solids()) != 1:
        raise ValueError(f"A05 {side_name} outward-opening top lid is invalid")

    parts.append(
        _part(
            f"A05_armrest_touch_lid_{side_name}",
            cap,
            LUNAR_STONE,
            "tone-matched hydrophobic microtexture over moulded service lid",
            "A05",
            state,
            "A calm body-colour lid flips outward for table extraction; the table is unfolded and raised clear of the fixed control sweep before the lid closes, then the concealed support docks through the sealed inner gland.",
            physical_occurrence_id=f"E6-A05-ARMREST-LID-{side_name.upper()}",
            table_bay_lid_closed=True,
            exact_armrest_length_mm=ARM_LENGTH,
            fixed_armrest_body=True,
            full_armrest_side_opening_enabled=False,
            top_lid_outward_opening_enabled=True,
            top_lid_open_angle_deg=105.0,
            top_lid_hinge_axis_mm=(
                (ARM_X_MIN, side * ARM_OUTER_Y, 676.0),
                (247.5, side * ARM_OUTER_Y, 676.0),
            ),
            final_state_pose="closed_and_double_latched",
            table_access_sequence=TABLE_ACCESS_SEQUENCE,
            hmi_moves_with_lid=True,
            right_drive_pod_remains_mounted_during_lid_motion=side > 0,
            closes_around_concealed_table_root_tongue=(
                side > 0 and state != "focus"
            ),
            table_root_tongue_hard_clearance_mm=(
                1.0 if side > 0 and state != "focus" else None
            ),
            focus_lid_has_no_table_root_aperture=(state == "focus"),
        )
    )

    if side > 0 and state != "focus":
        tongue_gland = rounded_frame(
            (15.0, 27.0),
            (13.0, 25.0),
            1.2,
            (-353.5, 328.0, 680.6),
            3.5,
        )
        parts.append(
            _part(
                "A05_right_table_root_tongue_compression_gland",
                tongue_gland,
                TPE_DARK,
                "replaceable self-closing hydrophobic TPE compression gland",
                "A05",
                state,
                "A fifteen-by-twenty-seven-millimetre flush gland seals the fixed lid passage around the table-attached root tongue and self-closes when the table is stowed; no hinge, rail or bracket is exposed on the armrest exterior.",
                physical_occurrence_id="E6-A05-RIGHT-TABLE-ROOT-TONGUE-GLAND",
                fixed_to="A05_armrest_touch_lid_right",
                passage_outer_xy_mm=(15.0, 27.0),
                hard_clearance_xy_mm=(13.0, 25.0),
                final_table_tongue_section_xy_mm=(11.0, 23.0),
                nominal_radial_compression_reserve_mm=1.0,
                self_closing_internal_duckbill=True,
                replaceable_from_lid_underside=True,
                final_exterior_visible=True,
                functional_opening="sealed_table_root_tongue_passage",
            )
        )

    hinge_reveal = rounded_box(
        (500.0, 1.0, 2.0),
        (-122.0, side * 367.0, 677.5),
        0.4,
    )
    lid_release = rounded_box(
        (36.0, 4.0, 12.0),
        (-340.0, side * 310.0, 642.0),
        3.0,
    )
    cassette_drain_cut = rounded_box(
        (24.0, 12.0, 10.0),
        (-300.0, side * 366.5, 526.0),
        3.0,
    )
    drain_outer = rounded_box(
        (30.0, 3.0, 14.0),
        (-300.0, side * 368.0, 526.0),
        4.0,
    )
    drain_inner = rounded_box(
        (20.0, 5.0, 6.0),
        (-300.0, side * 368.0, 526.0),
        2.0,
    )
    cassette_drain_bezel = drain_outer.cut(drain_inner)
    parts.extend(
        [
            _part(
                f"A05_armrest_top_lid_hinge_reveal_{side_name}",
                hinge_reveal,
                TPE_DARK,
                "one-millimetre replaceable hydrophobic hinge reveal",
                "A05",
                state,
                "A single hairline at the outboard edge marks the concealed longitudinal hinge without suggesting that the whole armrest opens sideways.",
                physical_occurrence_id=f"E6-A05-TOP-LID-HINGE-REVEAL-{side_name.upper()}",
                hinge_axis_y_mm=side * ARM_OUTER_Y,
                visible_reveal_width_mm=1.0,
                top_lid_only=True,
            ),
            _part(
                f"A05_armrest_top_lid_release_{side_name}",
                lid_release,
                GRAPHITE_BROWN,
                "recessed glove-operable two-action mechanical paddle",
                "A05",
                state,
                "A small inboard paddle releases the double latch without power; the fixed armrest shell itself never moves.",
                physical_occurrence_id=f"E6-A05-TOP-LID-RELEASE-{side_name.upper()}",
                manual_no_power=True,
                two_action=True,
                releases="two_independent_top_lid_rotary_latches",
                requires_parked_and_traction_disabled=True,
                functional_opening="top_lid_release manual_no_power",
                controlled_center_z_mm=642.0,
                focus_root_neck_minimum_clearance_mm=4.0,
                touch_surface="fixed_inboard_vertical_face",
            ),
            _part(
                f"A05_table_cassette_lowpoint_drain_{side_name}",
                cassette_drain_bezel,
                TPE_DARK,
                "replaceable hydrophobic TPE low-point drain bezel",
                "A05",
                state,
                "A small through-slot at the fixed bay low point drains rain and cleaning fluid; it is not a table deployment opening.",
                physical_occurrence_id=f"E6-A05-TABLE-CASSETTE-DRAIN-{side_name.upper()}",
                functional_opening="table_cassette_lowpoint_drain cleaning_probe_access",
                through_opening_mm=(20.0, 6.0),
                controlled_center_z_mm=526.0,
                legacy_side_table_exit=False,
                gravity_drain=True,
                cleaning_probe_access=True,
            ),
        ]
    )

    if side > 0:
        # The right transfer arm has a released rear hinge/link stack beyond
        # the nominal X=140 armrest shell.  Enclose that complete mechanism in
        # one open-front shoulder with a minimum three-millimetre cavity reserve
        # instead of cropping it out of the final presentation.
        hinge_outer = rounded_box(
            (70.0, 55.499, 196.0),
            (208.0, 346.75, 588.0),
            8.0,
        )
        hinge_inner = rounded_box(
            (70.0, 51.0, 190.0),
            (205.0, 348.5, 588.0),
            8.0,
        )
        hinge_shell = hinge_outer.cut(hinge_inner)
        link_outer = rounded_box(
            (120.0, 55.499, 38.0),
            (177.0, 346.75, 490.0),
            13.0,
        )
        link_inner = rounded_box(
            (114.0, 48.0, 32.0),
            (174.0, 347.0, 490.0),
            10.0,
        )
        link_shell = link_outer.cut(link_inner)
        transfer_root = union_many((hinge_shell, link_shell))
        parts.append(
            _part(
                "A05_right_transfer_root_fairing",
                transfer_root,
                LUNAR_STONE,
                "split impact-resistant PC-ABS transfer-root fairing",
                "A05",
                state,
                "One swept rear shoulder encloses the complete right transfer hinge and link shrouds while remaining removable for inspection.",
                physical_occurrence_id="E6-A05-RIGHT-TRANSFER-ROOT-FAIRING",
                source_occurrence_ids=(
                    "armrest_transfer_hinge_shroud_right",
                    "armrest_transfer_link_shroud_right",
                ),
                disposition="internal_enclosed",
                minimum_source_sweep_clearance_mm=0.4995,
                outboard_cladding_margin_mm=0.4995,
                minimum_inboard_and_vertical_margin_mm=6.0,
                service_split=True,
            )
        )

        lock_witness = rounded_box(
            (44.0, 4.0, 18.0),
            (40.0, 307.5, 652.0),
            2.0,
        )
        lock_release = rounded_box(
            (32.0, 6.0, 10.0),
            (40.0, 303.0, 652.0),
            3.0,
        )
        parts.extend(
            [
                _part(
                    "A05_right_transfer_positive_lock_witness",
                    lock_witness,
                    CHAMPAGNE,
                    "mechanically indexed lock-state witness plate",
                    "A05",
                    state,
                    "A source-linked flush/not-flush witness makes the right transfer arm lock state readable without relying on a display.",
                    physical_occurrence_id="E6-A05-RIGHT-TRANSFER-LOCK-WITNESS",
                    source_occurrence_ids=("armrest_transfer_positive_lock_right",),
                    controlled_source_center_mm=(40.0, 318.0, 652.0),
                    lock_station_id="right_transfer_positive_lock",
                    linkage_id="right_transfer_lock_mechanical_link",
                    functional_opening="right_transfer_lock_witness",
                ),
                _part(
                    "A05_right_transfer_manual_release",
                    lock_release,
                    GRAPHITE_BROWN,
                    "glove-operable two-action mechanical release paddle",
                    "A05",
                    state,
                    "A recessed exterior paddle preserves no-power transfer release while preventing accidental operation in Ride.",
                    physical_occurrence_id="E6-A05-RIGHT-TRANSFER-MANUAL-RELEASE",
                    source_occurrence_ids=("armrest_transfer_positive_lock_right",),
                    controlled_source_center_mm=(40.0, 318.0, 652.0),
                    lock_station_id="right_transfer_positive_lock",
                    linkage_id="right_transfer_lock_mechanical_link",
                    manual_no_power=True,
                    two_action=True,
                    functional_opening="right_transfer_lock_release manual_no_power",
                ),
            ]
        )

    if side < 0:
        display_center = (-294.0, -333.0, 683.5)
        hmi_bezel = rounded_frame(
            (138.0, 62.0),
            (128.0, 52.0),
            2.0,
            display_center,
            10.0,
        )
        hmi_bezel = _rotate_x(hmi_bezel, display_center, -10.0)
        hmi_bezel = _rotate_y(hmi_bezel, display_center, 5.0)
        display = rounded_box(
            (124.0, 50.0, 3.0),
            display_center,
            5.0,
        )
        display = _rotate_x(display, display_center, -10.0)
        display = _rotate_y(display, display_center, 5.0)

        # The support wing is larger than the charging insert; the insert itself
        # is sized for the current large-phone family plus a normal case.  The
        # phone may not remain on the lid during opening, and the coil is
        # de-energised before the latch releases.
        qi_pad = rounded_rect_prism(
            (176.0, 86.0),
            1.0,
            (-136.0, -322.5, 680.5),
            16.0,
        )
        qi_ring = _ring_xy(56.0, 48.0, 0.25, (-136.0, -322.5, 681.125))
        qi_stop_front = rounded_box(
            (4.0, 80.0, 3.0),
            (-222.0, -322.5, 682.5),
            2.0,
        )
        qi_stop_rear = rounded_box(
            (4.0, 80.0, 3.0),
            (-50.0, -322.5, 682.5),
            2.0,
        )

        # Correct the prototype axis error: the stop is mounted on the inner
        # armrest wall and therefore projects along Y, not along X into the
        # folded-table envelope.
        estop_guard = (
            cq.Workplane("XZ")
            .circle(22.0)
            .circle(17.0)
            .extrude(8.0)
            .translate((-294.0, -312.0, 590.0))
            .val()
        )
        estop_button = (
            cq.Workplane("XZ")
            .circle(15.0)
            .extrude(10.0)
            .translate((-294.0, -306.0, 590.0))
            .val()
        )
        parts.extend(
            [
                _part(
                    "A05_left_hmi_precision_bezel",
                    hmi_bezel,
                    CHAMPAGNE,
                    "non-conductive satin champagne PVD polymer bezel",
                    "A05",
                    state,
                    "A display-only precision reveal rises on a smooth compound curve; no conductive loop surrounds the Qi coil.",
                    physical_occurrence_id="E6-A05-HMI-BEZEL-LEFT",
                    display_only=True,
                    qi_closed_metal_loop_present=False,
                    compound_tilt_deg={"toward_occupant": 10.0, "rearward": 5.0},
                ),
                _part(
                    "A05_left_status_display_window",
                    display,
                    SMOKED_UMBER,
                    "anti-glare bonded display cover",
                    "A05",
                    state,
                    "The 124 x 50 mm status window tilts ten degrees toward the passenger and five degrees rearward for a natural seated sightline.",
                    physical_occurrence_id="WC-HMI-STATUS-DISPLAY-LEFT",
                    controlled_center_mm=display_center,
                    outer_window_mm=(124.0, 50.0),
                    effective_active_area_mm=(116.0, 42.0),
                    compound_tilt_deg={"toward_occupant": 10.0, "rearward": 5.0},
                    nominal_surface_normal=(0.0858, 0.1736, 0.9811),
                    anti_glare=True,
                    moves_with_top_lid=True,
                ),
                _part(
                    "A05_left_qi_phone_cradle",
                    qi_pad,
                    TPE_DARK,
                    "replaceable micro-ribbed high-friction non-conductive TPE insert",
                    "A05",
                    state,
                    "A real phone cradle supports a 170 x 84 x 13 mm cased device while keeping its entire outer edge inboard of the lid hinge axis.",
                    physical_occurrence_id="E6-A05-QI-PHONE-CRADLE-LEFT",
                    cradle_surface_mm=(176.0, 86.0),
                    validated_phone_design_envelope_mm=(170.0, 84.0, 13.0),
                    outer_edge_y_mm=-365.5,
                    hinge_axis_y_mm=-367.5,
                    outer_edge_inboard_of_hinge_mm=2.0,
                    recessed_depth_mm=1.0,
                    phone_presence_blocks_lid_release=True,
                    qi_deenergises_before_lid_motion=True,
                    fod_and_temperature_monitoring_required=True,
                    moves_with_top_lid=True,
                ),
                _part(
                    "A05_left_qi_target_ring",
                    qi_ring,
                    CHAMPAGNE,
                    "non-metallic ceramic-ink printed Qi target",
                    "A05",
                    state,
                    "A non-conductive 56 mm target locates the coil without an eddy-current loop; charging electronics remain below the sealed cradle.",
                    physical_occurrence_id="WC-HMI-QI2-TARGET-LEFT",
                    controlled_diameter_mm=56.0,
                    continuous_metal_loop=False,
                    target_material_nonconductive=True,
                    moves_with_top_lid=True,
                ),
                _part(
                    "A05_left_qi_phone_stop_front",
                    qi_stop_front,
                    TPE_DARK,
                    "two-shot moulded compliant phone end stop",
                    "A05",
                    state,
                    "A three-millimetre soft stop prevents forward slide without becoming a visual rail.",
                    physical_occurrence_id="E6-A05-QI-PHONE-STOP-FRONT",
                    stop_height_mm=3.0,
                    moves_with_top_lid=True,
                ),
                _part(
                    "A05_left_qi_phone_stop_rear",
                    qi_stop_rear,
                    TPE_DARK,
                    "two-shot moulded compliant phone end stop",
                    "A05",
                    state,
                    "A three-millimetre soft stop completes the usable phone cradle without a bulky pocket.",
                    physical_occurrence_id="E6-A05-QI-PHONE-STOP-REAR",
                    stop_height_mm=3.0,
                    moves_with_top_lid=True,
                ),
                _part(
                    "A05_left_emergency_stop_guard",
                    estop_guard,
                    GRAPHITE_BROWN,
                    "impact-resistant PC-ABS guard",
                    "A05",
                    state,
                    "Guarded but unobscured mechanical emergency-stop access on the inner wall, clear of the folded-table pack.",
                    physical_occurrence_id="WC-HMI-E-STOP-GUARD-LEFT",
                    controlled_center_mm=(-294.0, -308.0, 590.0),
                    mounting_axis="Y",
                    table_pack_intrusion=False,
                ),
                _part(
                    "A05_left_mechanical_emergency_stop",
                    estop_button,
                    SAFETY_RED,
                    "safety-rated twist-release stop interface",
                    "A05",
                    state,
                    "Visible, directly reachable hardwired stop; never hidden by the cosmetic skin.",
                    physical_occurrence_id="WC-HMI-MECHANICAL-E-STOP-LEFT",
                    controlled_center_mm=(-294.0, -301.0, 590.0),
                    controlled_diameter_mm=30.0,
                    mounting_axis="Y",
                ),
            ]
        )
    else:
        # The controlled pod/joystick/key datums are safety and ergonomic hard
        # points and the same three physical occurrences remain exposed at one
        # fixed forward hand station in all four states.  The right control
        # island moves with the outward-opening top lid during table extraction
        # and returns to this exact armrest-top datum before table deployment.
        # Cafe/Focus/Follow disable traction electrically; they never relocate,
        # fold or conceal the joystick behind the deployed table.
        pod_offset = (0.0, 0.0, 0.0)
        control_pose = "fixed_forward_armrest_top"
        externally_visible = True
        drive_enabled = state == "ride"

        pod = rounded_box((120.0, 58.0, 18.0), (-250.0, 333.0, 690.0), 12.0)
        joystick_seat = (
            cq.Workplane("XY")
            .circle(9.0)
            .extrude(24.0)
            .translate((-268.0, 333.0, 694.0))
            .val()
        )
        authorise_seat = (
            cq.Workplane("XY")
            .circle(15.5)
            .extrude(20.0)
            .translate((-216.0, 333.0, 692.0))
            .val()
        )
        pod = pod.cut(joystick_seat).cut(authorise_seat).translate(pod_offset)
        joystick_shaft = (
            cq.Workplane("XY")
            .circle(7.0)
            .extrude(24.0)
            .translate((-268.0, 333.0, 697.0))
            .val()
        )
        joystick_grip = rounded_box(
            (32.0, 32.0, 22.0),
            (-268.0, 333.0, 720.0),
            10.0,
        )
        joystick = joystick_shaft.fuse(joystick_grip)
        joystick = joystick.translate(pod_offset)
        authorise_guard = (
            cq.Workplane("XY")
            .circle(14.5)
            .extrude(3.0)
            .translate((-216.0, 333.0, 698.0))
            .val()
        )
        authorise_button = (
            cq.Workplane("XY")
            .circle(10.0)
            .extrude(5.0)
            .translate((-216.0, 333.0, 700.0))
            .val()
        )
        authorise = authorise_guard.fuse(authorise_button).translate(pod_offset)
        pod_center = tuple(
            base + delta
            for base, delta in zip((-250.0, 333.0, 690.0), pod_offset)
        )
        joystick_box = joystick.BoundingBox()
        joystick_center = (
            (joystick_box.xmin + joystick_box.xmax) / 2.0,
            (joystick_box.ymin + joystick_box.ymax) / 2.0,
            (joystick_box.zmin + joystick_box.zmax) / 2.0,
        )
        authorise_center = tuple(
            base + delta
            for base, delta in zip((-216.0, 333.0, 702.5), pod_offset)
        )
        parts.extend(
            [
                _part(
                    "A05_right_removable_drive_pod",
                    pod,
                    GRAPHITE_BROWN,
                    "soft-touch removable control pod",
                    "A05",
                    state,
                    "A 120 x 58 mm removable pod provides a small palm landing while keeping the armrest top low and calm.",
                    physical_occurrence_id="WC-HMI-RIGHT-DRIVE-POD",
                    controlled_center_mm=pod_center,
                    pod_envelope_mm=(120.0, 58.0, 18.0),
                    palm_support_present=True,
                    embedded_depth_mm=0.0,
                    removal_required_before_top_lid_open=False,
                    remains_mounted_to_lid_during_table_extraction=True,
                    moves_with_top_lid=True,
                    fixed_to="A05_armrest_touch_lid_right",
                    fixed_forward_armrest_location_all_states=True,
                    functional_opening="drive_hmi control_pod joystick authorization_key",
                    same_physical_occurrence_all_states=True,
                    state_pose=control_pose,
                    externally_visible_in_locked_state=externally_visible,
                    drive_enabled_in_locked_state=drive_enabled,
                    table_deployed_pose_uses_clear_rear_lid_zone=False,
                    table_deployed_control_remains_forward_and_hand_reachable=(
                        state in {"cafe", "focus"}
                    ),
                ),
                _part(
                    "A05_right_joystick",
                    joystick,
                    TPE_DARK,
                    "safety-rated spring-return joystick",
                    "A05",
                    state,
                    "A 32 mm grip and 24 mm visible shaft provide a real spring-return control with a bounded hand sweep.",
                    physical_occurrence_id="WC-HMI-RIGHT-JOYSTICK",
                    controlled_center_mm=joystick_center,
                    grip_diameter_mm=32.0,
                    visible_shaft_length_mm=24.0,
                    angular_travel_deg=18.0,
                    full_sweep_envelope_diameter_mm=52.0,
                    spring_return_neutral=True,
                    same_physical_occurrence_all_states=True,
                    state_pose=control_pose,
                    externally_visible_in_locked_state=externally_visible,
                    drive_enabled_in_locked_state=drive_enabled,
                    joystick_attitude="upright_fixed_forward",
                    folded_flat_when_traction_disabled=False,
                    table_deployed_hand_reach_must_remain_clear=True,
                    moves_with_top_lid=True,
                    fixed_to="A05_armrest_touch_lid_right",
                ),
                _part(
                    "A05_right_authorisation_key",
                    authorise,
                    CHAMPAGNE,
                    "two-action drive-authorisation control",
                    "A05",
                    state,
                    "A guarded 20 mm button, 52 mm from the joystick centre, requires a separate deliberate drive-authorisation action.",
                    physical_occurrence_id="WC-HMI-RIGHT-AUTHORISATION-KEY",
                    controlled_center_mm=authorise_center,
                    button_diameter_mm=20.0,
                    guard_diameter_mm=29.0,
                    joystick_center_separation_mm=52.0,
                    two_action=True,
                    same_physical_occurrence_all_states=True,
                    state_pose=control_pose,
                    externally_visible_in_locked_state=externally_visible,
                    drive_enabled_in_locked_state=drive_enabled,
                    moves_with_top_lid=True,
                    fixed_to="A05_armrest_touch_lid_right",
                ),
            ]
        )

    return parts


def _backrest_parts(state: str) -> list[SkinPart]:
    # One hollow perimeter tray now performs all three visible A06 jobs: rear
    # cosmetic shell, structural side close-out and the broad Follow weather
    # cover.  The previous pair of thin, separated plates exposed the carrier
    # in side view and became two floating layers after the real -95 degree
    # fold.  A 96 mm crowned envelope surrounds the controlled 80 mm backrest
    # stack; an internal cavity leaves an eight-millimetre nominal wall and the
    # front opening receives the removable contact island.
    body_outer = _crowned_trapezoid_skin(
        606.0,
        326.0,
        526.0,
        96.0,
        x_center=207.0,
        z0=515.0,
        corner_radius=18.0,
        end_inset=5.0,
    )
    body_cavity = _crowned_trapezoid_skin(
        584.0,
        306.0,
        506.0,
        80.0,
        x_center=207.0,
        z0=525.0,
        corner_radius=15.0,
        end_inset=4.0,
    )
    contact_opening = _crowned_trapezoid_skin(
        528.0,
        256.0,
        450.0,
        24.0,
        x_center=155.0,
        z0=552.0,
        corner_radius=18.0,
        end_inset=3.0,
    )
    backrest_body = cut_many(body_outer, (body_cavity, contact_opening))
    if not backrest_body.isValid() or len(backrest_body.Solids()) != 1:
        raise ValueError("A06 perimeter weather body is not one valid hollow solid")
    body_reference_volume = backrest_body.Volume()

    contact_panel = _crowned_trapezoid_skin(
        516.0,
        248.0,
        442.0,
        14.0,
        x_center=158.0,
        z0=556.0,
        corner_radius=16.0,
        end_inset=4.0,
    )
    contact_panel_reference_volume = contact_panel.Volume()

    # Rake and Follow fold are applied to the complete tray and the same contact
    # island about the released hinge.  No state-specific substitute surface is
    # introduced, so the weather object is the upright backrest itself.
    backrest_body = _rotate_y(backrest_body, BACK_HINGE, BACK_RAKE_DEG)
    contact_panel = _rotate_y(contact_panel, BACK_HINGE, BACK_RAKE_DEG)

    pose = "upright"
    if state == "follow":
        backrest_body = _rotate_y(backrest_body, BACK_HINGE, BACK_FOLD_DEG)
        contact_panel = _rotate_y(contact_panel, BACK_HINGE, BACK_FOLD_DEG)
        pose = "folded_weather_cover"

    # A06 and A07 visually overlap, but the back shell must never occupy the
    # released telescoping-member sweep.  Cut a five-millimetre cosmetic relief
    # around the complete 54 x 120 mm inner member before it meets the spine.
    # In Follow the cutter receives the exact mast-fold transform, not the
    # slightly different backrest rake transform.
    mast_sweep_relief = rounded_box(
        (72.0, 138.0, 582.0),
        (MAST_X, 0.0, 755.0),
        6.0,
    )
    if state == "follow":
        mast_sweep_relief = _rotate_y(
            mast_sweep_relief,
            MAST_FOLD_HINGE,
            BACK_FOLD_DEG,
        )
    backrest_body = backrest_body.cut(mast_sweep_relief)
    if not backrest_body.isValid() or len(backrest_body.Solids()) != 1:
        raise ValueError("A06 mast-sweep relief disconnected the weather body")

    parts = [
        _part(
            "A06_backrest_weather_shell",
            backrest_body,
            LUNAR_STONE,
            "UV-stable fine-matte PC-ABS hollow perimeter weather body",
            "A06",
            state,
            "One deep crowned perimeter shell encloses the back carrier upright and becomes the complete broad weather cover in Follow.",
            physical_occurrence_id="E6-A06-BACKREST-WEATHER-SHELL",
            pose=pose,
            controlled_hinge_mm=BACK_HINGE,
            upright_rake_deg=BACK_RAKE_DEG,
            follow_fold_deg=BACK_FOLD_DEG,
            physical_part_conserved=True,
            reference_volume_mm3=round(body_reference_volume, 6),
            controlled_backrest_stack_depth_mm=80.0,
            cosmetic_envelope_depth_mm=96.0,
            nominal_shell_wall_mm=8.0,
            mast_sweep_relief_mm=5.0,
            moves_with="backrest_hinge",
        ),
        _part(
            "A06_backrest_contact_panel",
            contact_panel,
            ESPRESSO,
            "removable breathable 3D-knit contact pad",
            "A06",
            state,
            "A replaceable human-contact island within, not instead of, the controlled trapezoidal back.",
            physical_occurrence_id="E6-A06-BACKREST-CONTACT-PANEL",
            pose=pose,
            reference_volume_mm3=round(contact_panel_reference_volume, 6),
            physical_part_conserved=True,
            recessed_in_perimeter_body=True,
            moves_with="backrest_hinge",
        ),
    ]

    if state == "follow":
        # A conserved overlap skirt hides the seat-cushion edge and the former
        # 46 mm black daylight line when the back becomes the travel cover.  It
        # keys into both A05 wings and stops just below the folded A06 body.
        continuity_skirt = rounded_frame(
            (510.0, 630.0),
            (482.0, 602.0),
            55.0,
            (-75.0, 0.0, 485.0),
            28.0,
        )
        parts.append(
            _part(
                "A06_follow_weather_continuity_skirt",
                continuity_skirt,
                LUNAR_STONE,
                "body-colour overlap-moulded PC-ABS travel waist seal",
                "A06",
                state,
                "A continuous overlap waist makes the folded back, seat edge and two armrest wings read as one closed travel object without hiding the contact cushion in Ride.",
                physical_occurrence_id="E6-A06-FOLLOW-CONTINUITY-SKIRT",
                overlap_with_a05_mm=5.0,
                overlap_with_folded_a06_mm=1.5,
                service_removable=True,
            )
        )
    else:
        # Two hollow shoulder cheeks close the hinge/root void while leaving a
        # 200 mm clear central channel for the telescoping observation spine.
        # Each cheek physically overlaps A04 below and A06 above, eliminating
        # the layered-board appearance without turning the seat into a cockpit.
        for side_name, side in (("left", -1), ("right", 1)):
            cheek_outer = rounded_box(
                (100.0, 210.0, 80.0),
                (255.0, side * 205.0, 500.0),
                24.0,
            )
            cheek_inner = rounded_box(
                (90.0, 184.0, 70.0),
                (250.0, side * 197.0, 505.0),
                20.0,
            )
            root_cheek = cheek_outer.cut(cheek_inner)
            if not root_cheek.isValid() or len(root_cheek.Solids()) != 1:
                raise ValueError(f"A06 {side_name} root cheek is not one valid solid")
            parts.append(
                _part(
                    f"A06_backrest_root_cheek_{side_name}",
                    root_cheek,
                    LUNAR_STONE,
                    "split serviceable PC-ABS backrest-root cheek",
                    "A06",
                    state,
                    "A deep side cheek hides the hinge/link cavity and blends the backrest into the body shoulder while preserving the central mast channel.",
                    physical_occurrence_id=f"E6-A06-BACKREST-ROOT-CHEEK-{side_name.upper()}",
                    central_mast_channel_width_mm=200.0,
                    service_split=True,
                )
            )

    return parts


def _mast_parts(state: str) -> list[SkinPart]:
    raised = state == "focus"
    folded = state == "follow"
    beam_z = BEAM_LOW_Z + (MAST_STROKE if raised else 0.0)
    travel = MAST_STROKE if raised else 0.0

    # The fixed observation spine is one long, open-ended dorsal shell from the
    # backrest root to the sensor beam.  It replaces the short shroud plus a
    # separate wedge which made the raised mast read as a suitcase pull handle.
    # The asymmetric X section leans into A06 but retains a continuous 72 x
    # 136 mm running aperture centred on the released MAST_X datum.
    if folded:
        # The broad upright dorsal blade nests into a tighter conserved fold
        # cassette in Follow; retaining the released folded X depth is what
        # keeps the whole observation object below the locked travel roof.
        outer_sleeve_blank = _rounded_loft_z(
            (
                ((86.0, 170.0), (305.5, 0.0), 505.0, 34.0),
                ((86.0, 158.0), (305.5, 0.0), 704.0, 32.0),
                ((84.0, 152.0), (305.5, 0.0), 1008.0, 30.0),
            )
        )
        outer_sleeve_clearance = _rounded_loft_z(
            (
                ((72.0, 136.0), (MAST_X, 0.0), 503.0, 18.0),
                ((72.0, 136.0), (MAST_X, 0.0), 1010.0, 18.0),
            )
        )
    else:
        outer_sleeve_blank = _rounded_loft_z(
            (
                ((126.0, 198.0), (306.0, 0.0), 505.0, 42.0),
                ((112.0, 190.0), (307.0, 0.0), 704.0, 40.0),
                ((100.0, 176.0), (309.0, 0.0), 1008.0, 36.0),
            )
        )
        outer_sleeve_clearance = _rounded_loft_z(
            (
                ((94.0, 166.0), (MAST_X, 0.0), 503.0, 28.0),
                ((94.0, 166.0), (MAST_X, 0.0), 1010.0, 28.0),
            )
        )
    outer_sleeve = outer_sleeve_blank.cut(outer_sleeve_clearance)

    # The bilateral lock pins remain at Y=+/-52, Z=888.  A narrow service path
    # reaches each pin from the side, but a flush smoked confirmation lens fills
    # the exterior opening.  The interface therefore reads as an intentional
    # safety witness rather than two missing chunks in the mast shell.
    lock_pin_centres = ((MAST_X, -52.0, 888.0), (MAST_X, 52.0, 888.0))
    lock_access_centres = ((MAST_X, -78.0, 888.0), (MAST_X, 78.0, 888.0))
    outer_sleeve = cut_many(
        outer_sleeve,
        tuple(
            rounded_box(
                (80.0, 18.0, 18.0) if folded else (112.0, 54.0, 20.0),
                centre,
                5.0 if folded else 6.0,
            )
            for centre in lock_access_centres
        ),
    )
    if not outer_sleeve.isValid() or len(outer_sleeve.Solids()) != 1:
        raise ValueError("A07 fixed observation spine is not one valid shell")

    lock_lenses: list[tuple[str, cq.Shape, tuple[float, float, float]]] = []
    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        centre = (MAST_X, side * (78.5 if folded else 99.5), 888.0)
        lock_lenses.append(
            (
                side_name,
                rounded_box(
                    (76.0, 3.0, 16.0) if folded else (94.0, 3.0, 16.0),
                    centre,
                    4.5,
                ),
                centre,
            )
        )

    if raised:
        # Three overlapping, successively smaller shells make the full 420 mm
        # lift read as a deliberate instrument spine.  The released 54 x 116
        # mm moving member remains continuously enclosed inside every stage.
        inner_stage = union_many(
            (
                rounded_frame(
                    (90.0, 158.0),
                    (74.0, 140.0),
                    170.0,
                    (MAST_X, 0.0, 1043.0),
                    34.0,
                ),
                rounded_frame(
                    (84.0, 150.0),
                    (68.0, 132.0),
                    170.0,
                    (MAST_X, 0.0, 1203.0),
                    32.0,
                ),
                rounded_frame(
                    (78.0, 142.0),
                    (62.0, 124.0),
                    150.0,
                    (MAST_X, 0.0, 1353.0),
                    30.0,
                ),
            )
        )
    elif folded:
        inner_stage = rounded_frame(
            (66.0, 130.0),
            (54.0, 116.0),
            540.0,
            (MAST_X, 0.0, 738.0),
            28.0,
        )
    else:
        # In low states the same three stages are nested inside the fixed
        # dorsal sleeve and present only one quiet body-colour blade.
        inner_stage = rounded_frame(
            (90.0, 158.0),
            (74.0, 140.0),
            540.0,
            (MAST_X, 0.0, 738.0),
            34.0,
        )
    if not inner_stage.isValid() or len(inner_stage.Solids()) != 1:
        raise ValueError("A07 telescopic observation blade is not one valid solid")

    # The sensor terminal is a crowned instrument lens with a central keel,
    # not a hand-grip crossbar.  The exact 80 x 320 x 64 mm released envelope is
    # retained at the two widest sections; the keel overlaps that shell and
    # closes around the moving stage with two millimetres cosmetic clearance.
    beam_outer = _rounded_loft_z(
        (
            ((74.0, 286.0), (MAST_X, 0.0), beam_z - 32.0, 24.0),
            ((80.0, 320.0), (MAST_X, 0.0), beam_z - 18.0, 28.0),
            ((80.0, 320.0), (MAST_X, 0.0), beam_z + 18.0, 28.0),
            ((74.0, 292.0), (MAST_X, 0.0), beam_z + 32.0, 24.0),
        )
    )
    beam_inner = _rounded_loft_z(
        (
            ((62.0, 266.0), (MAST_X + 2.0, 0.0), beam_z - 25.0, 18.0),
            ((68.0, 294.0), (MAST_X + 2.0, 0.0), beam_z - 14.0, 20.0),
            ((68.0, 294.0), (MAST_X + 2.0, 0.0), beam_z + 14.0, 20.0),
            ((62.0, 270.0), (MAST_X + 2.0, 0.0), beam_z + 25.0, 18.0),
        )
    )
    beam_shell = beam_outer.cut(beam_inner)

    keel_outer = _rounded_loft_z(
        (
            (
                (84.0, 146.0) if folded else (100.0, 178.0),
                (MAST_X, 0.0),
                beam_z - (48.0 if folded else 54.0),
                28.0 if folded else 34.0,
            ),
            (
                (82.0, 178.0) if folded else (94.0, 206.0),
                (MAST_X, 0.0),
                beam_z - 30.0 if folded else beam_z - 32.0,
                30.0 if folded else 34.0,
            ),
            (
                (80.0, 214.0) if folded else (82.0, 228.0),
                (MAST_X, 0.0),
                beam_z - 12.0,
                30.0,
            ),
        )
    )
    keel_clearance = _rounded_loft_z(
        (
            ((70.0, 136.0), (MAST_X, 0.0), beam_z - 50.0, 13.0),
            ((70.0, 136.0), (MAST_X, 0.0), beam_z - 10.0, 13.0),
        )
    )
    terminal_keel = keel_outer.cut(keel_clearance)
    beam_shell = beam_shell.fuse(terminal_keel)

    sensor_aperture = rounded_box(
        (18.0, 286.0, 44.0),
        (267.0, 0.0, beam_z + 1.0),
        9.0,
    )
    microphone_aperture = rounded_box(
        (18.0, 174.0, 7.0),
        (267.0, 0.0, beam_z - 24.0),
        2.5,
    )
    environment_aperture = rounded_box(
        (30.0, 28.0, 12.0),
        (MAST_X, 112.0, beam_z + 30.0),
        6.0,
    )
    fill_light_apertures = tuple(
        rounded_box(
            (18.0, 46.0, 26.0),
            (266.0, side * 130.0, beam_z),
            6.0,
        )
        for side in (-1, 1)
    )
    beam_shell = cut_many(
        beam_shell,
        (
            sensor_aperture,
            microphone_aperture,
            environment_aperture,
            *fill_light_apertures,
        ),
    )
    if not beam_shell.isValid() or len(beam_shell.Solids()) != 1:
        raise ValueError("A07 crowned sensor terminal is not one valid shell")

    sensor_window = rounded_box(
        (5.0, 280.0, 40.0),
        (267.5, 0.0, beam_z + 1.0),
        9.0,
    )
    fill_light_windows = [
        (
            "right" if side > 0 else "left",
            rounded_box(
                (8.0, 42.0, 22.0),
                (266.0, side * 130.0, beam_z),
                6.0,
            ),
        )
        for side in (-1, 1)
    ]
    # Focus restores the controlled parked shutter centre and full source
    # bounds (Y=65..191).  A real open-front pocket below receives that
    # overhang; the beam itself remains the released 320 mm wide item.
    shutter_y = 128.0 if raised else -8.0
    privacy_shutter = rounded_box(
        (4.0, 126.0, 34.0),
        (264.5, shutter_y, beam_z),
        6.0,
    )

    privacy_pocket: cq.Shape | None = None
    if raised:
        pocket_outer = rounded_box(
            (18.0, 144.0, 46.0),
            (267.0, 128.0, beam_z),
            9.0,
        )
        pocket_cavity = rounded_box(
            (17.0, 136.0, 40.0),
            (263.5, 128.0, beam_z),
            7.0,
        )
        privacy_pocket = pocket_outer.cut(pocket_cavity)
        if not privacy_pocket.isValid() or len(privacy_pocket.Solids()) != 1:
            raise ValueError("A07 Focus privacy-shutter parked pocket is invalid")

    microphone_mesh = rounded_box(
        (5.0, 170.0, 5.0),
        (267.5, 0.0, beam_z - 24.0),
        2.5,
    )
    environment_grille = rounded_box(
        (26.0, 24.0, 4.0),
        (MAST_X, 112.0, beam_z + 30.0),
        5.0,
    )

    if folded:
        outer_sleeve = _rotate_y(outer_sleeve, MAST_FOLD_HINGE, BACK_FOLD_DEG)
        inner_stage = _rotate_y(inner_stage, MAST_FOLD_HINGE, BACK_FOLD_DEG)
        lock_lenses = [
            (
                side_name,
                _rotate_y(lens, MAST_FOLD_HINGE, BACK_FOLD_DEG),
                centre,
            )
            for side_name, lens, centre in lock_lenses
        ]
        beam_shell = _rotate_y(beam_shell, MAST_FOLD_HINGE, BACK_FOLD_DEG)
        sensor_window = _rotate_y(sensor_window, MAST_FOLD_HINGE, BACK_FOLD_DEG)
        fill_light_windows = [
            (
                side_name,
                _rotate_y(window, MAST_FOLD_HINGE, BACK_FOLD_DEG),
            )
            for side_name, window in fill_light_windows
        ]
        privacy_shutter = _rotate_y(privacy_shutter, MAST_FOLD_HINGE, BACK_FOLD_DEG)
        microphone_mesh = _rotate_y(
            microphone_mesh, MAST_FOLD_HINGE, BACK_FOLD_DEG
        )
        environment_grille = _rotate_y(
            environment_grille, MAST_FOLD_HINGE, BACK_FOLD_DEG
        )
        if privacy_pocket is not None:
            privacy_pocket = _rotate_y(
                privacy_pocket, MAST_FOLD_HINGE, BACK_FOLD_DEG
            )

    pose = "folded" if folded else ("raised_420" if raised else "low")
    parts = [
        _part(
            "A07_mast_fixed_outer_sleeve",
            outer_sleeve,
            LUNAR_STONE,
            "replaceable fine-matte PC-ABS continuous dorsal spine shroud",
            "A07",
            state,
            "One fixed dorsal shell connects A06 to the terminal while enclosing the full low-stage mechanism behind a continuous silhouette.",
            physical_occurrence_id="E6-A07-MAST-FIXED-SLEEVE",
            structural_hard_point_mm=(70.0, 136.0, 300.0),
            pose=pose,
            functional_opening="mast_lock_pin behind_flush_confirmation_lens",
            controlled_lock_pin_centres_mm=lock_pin_centres,
            upright_access_lens_centres_mm=lock_access_centres,
            continuous_running_aperture_mm=(72.0, 136.0) if folded else (94.0, 166.0),
            minimum_cosmetic_clearance_to_moving_sleeve_mm=3.0 if folded else 2.0,
        ),
        _part(
            "A07_mast_moving_inner_sleeve",
            inner_stage,
            LUNAR_STONE,
            "body-colour ceramic-coated low-friction aluminium moving spine",
            "A07",
            state,
            "A three-stage body-colour observation blade translates exactly 420 mm in Focus and terminates in a broad dorsal keel rather than a flagpole.",
            physical_occurrence_id="E6-A07-MAST-MOVING-SLEEVE",
            commanded_translation_mm=travel,
            controlled_stroke_mm=MAST_STROKE,
            telescopic_stage_count=3,
            minimum_internal_aperture_mm=(62.0, 124.0),
            nested_inside_fixed_sleeve_in_low_states=not raised,
            pose=pose,
            moves_with="sensor_beam",
        ),
        _part(
            "A07_sensor_beam_shell",
            beam_shell,
            LUNAR_STONE,
            "fine-matte PC-ABS thin sensor-beam shell",
            "A07",
            state,
            "Crowned 320 x 80 mm instrument terminal and central keel terminate the spine as one observation object, not a hand grip.",
            physical_occurrence_id="E6-A07-SENSOR-BEAM-SHELL",
            controlled_plan_mm=(320.0, 80.0),
            controlled_center_z_mm=beam_z,
            pose=pose,
            moves_with="sensor_beam",
        ),
        _part(
            "A07_sensor_beam_smoked_window",
            sensor_window,
            SMOKED_UMBER,
            "IR-transparent smoked polycarbonate",
            "A07",
            state,
            "The controlled 280 x 40 mm sensor window is the only dark optical horizon.",
            physical_occurrence_id="WC-MAST-SMOKED-SENSOR-WINDOW",
            controlled_size_mm=(5.0, 280.0, 40.0),
            controlled_center_z_mm=beam_z,
            pose=pose,
            moves_with="sensor_beam",
        ),
        _part(
            "A07_physical_privacy_shutter",
            privacy_shutter,
            ESPRESSO,
            "opaque mechanically linked privacy shutter",
            "A07",
            state,
            "A physical 126 x 34 mm shutter closes the optical horizon except when deliberately parked in Focus.",
            physical_occurrence_id="WC-MAST-PHYSICAL-PRIVACY-SHUTTER",
            controlled_size_mm=(4.0, 126.0, 34.0),
            shutter_position="parked" if raised else "closed",
            controlled_center_y_mm=shutter_y,
            pose=pose,
            moves_with="sensor_beam",
        ),
        _part(
            "A07_microphone_acoustic_mesh",
            microphone_mesh,
            GRAPHITE_BROWN,
            "Hydrophobic laser-perforated stainless acoustic mesh",
            "A07",
            state,
            "A narrow perforated line directly below the optical horizon makes acoustic intent legible without exposing capsules.",
            physical_occurrence_id="WC-MAST-MICROPHONE-ARRAY-INTERFACE",
            functional_opening="mast_microphone_acoustic_interface",
            pose=pose,
            moves_with="sensor_beam",
        ),
        _part(
            "A07_environment_sensor_grille",
            environment_grille,
            GRAPHITE_BROWN,
            "Hydrophobic ePTFE environmental-sensor grille",
            "A07",
            state,
            "A single protected top-deck grille makes air exchange readable and keeps it distinct from the optical horizon.",
            physical_occurrence_id="WC-MAST-ENVIRONMENT-SENSOR-INTERFACE",
            functional_opening="mast_environment_air_exchange",
            pose=pose,
            moves_with="sensor_beam",
        ),
    ]

    for side_name, lens, upright_centre in lock_lenses:
        parts.append(
            _part(
                f"A07_mast_lock_pin_confirmation_lens_{side_name}",
                lens,
                SMOKED_UMBER,
                "flush smoked elastomer-sealed lock confirmation lens",
                "A07",
                state,
                "A removable flush witness lens preserves direct lock-pin inspection without leaving a raw hole in the spine.",
                physical_occurrence_id=f"E6-A07-MAST-LOCK-LENS-{side_name.upper()}",
                functional_opening="mast_lock_pin_access service_confirmation_lens",
                controlled_lock_pin_center_mm=(
                    MAST_X,
                    52.0 if side_name == "right" else -52.0,
                    888.0,
                ),
                upright_lens_center_mm=upright_centre,
                pose=pose,
            )
        )

    for side_name, window in fill_light_windows:
        parts.append(
            _part(
                f"A07_fill_light_visible_window_{side_name}",
                window,
                SMOKED_UMBER,
                "smoked warm-neutral diffusing optical-grade polycarbonate",
                "A07",
                state,
                "A source-aligned flush visible-light window keeps the task-light corridor free of opaque cosmetic skin.",
                physical_occurrence_id=f"WC-MAST-FILL-LIGHT-VISIBLE-WINDOW-{side_name.upper()}",
                functional_opening="fill_light_visible_window optical_corridor",
                controlled_center_mm=(
                    266.0,
                    130.0 if side_name == "right" else -130.0,
                    beam_z,
                ),
                controlled_size_mm=(8.0, 42.0, 22.0),
                active_only_in="focus",
                moves_with="sensor_beam",
                pose=pose,
            )
        )

    if privacy_pocket is not None:
        parts.append(
            _part(
                "A07_privacy_shutter_parked_pocket",
                privacy_pocket,
                LUNAR_STONE,
                "body-colour open-front shutter parking fairing",
                "A07",
                state,
                "A real serviceable pocket receives the complete Focus shutter overhang while leaving its opaque face physically visible.",
                physical_occurrence_id="E6-A07-PRIVACY-SHUTTER-PARKED-POCKET",
                functional_opening="privacy_shutter parked_pocket",
                controlled_source_shutter_bounds_mm={
                    "ymin": 65.0,
                    "ymax": 191.0,
                    "zmin": beam_z - 17.0,
                    "zmax": beam_z + 17.0,
                },
                internal_cavity_bounds_mm={
                    "ymin": 60.0,
                    "ymax": 196.0,
                    "zmin": beam_z - 20.0,
                    "zmax": beam_z + 20.0,
                },
                final_outer_ymax_mm=200.0,
                minimum_internal_clearance_mm=2.0,
                moves_with="sensor_beam",
                pose=pose,
            )
        )

    return parts


def _segmented_lift_boot(
    center_x: float,
    center_y: float,
) -> cq.Shape:
    """Three nested cosmetic stages around the released 32 mm lift tube.

    The stepped silhouette makes the 192 mm change in height legible as a
    controlled telescopic interface instead of a generic square post.  Every
    inner aperture remains at least 36 mm across, leaving two millimetres of
    radial reserve around the structural tube.
    """

    segments = (
        rounded_frame(
            (64.0, 64.0),
            (44.0, 44.0),
            70.0,
            (center_x, center_y, 525.0),
            22.0,
        ),
        rounded_frame(
            (58.0, 58.0),
            (40.0, 40.0),
            70.0,
            (center_x, center_y, 585.0),
            20.0,
        ),
        rounded_frame(
            (52.0, 52.0),
            (36.0, 36.0),
            72.0,
            (center_x, center_y, 646.0),
            18.0,
        ),
    )
    boot = union_many(segments)
    if not boot.isValid():
        raise ValueError("Segmented A09 lift boot is not valid")
    return boot


def _focus_flat_root_box(side: int) -> cq.Shape:
    """Closed-bottom fixed root housing wholly inside one A05 cavity."""

    axis = (FOCUS_ROOT_AXIS_X, side * FOCUS_ROOT_AXIS_ABS_Y)
    wall = rounded_frame(
        (35.0, 42.0),
        (32.0, 40.0),
        55.0,
        (axis[0], axis[1], 507.5),
        14.0,
    )
    bottom = rounded_rect_prism(
        (35.0, 42.0),
        2.5,
        (axis[0], axis[1], 481.25),
        14.0,
    )
    root = wall.fuse(bottom).clean()
    if root.isNull() or not root.isValid() or len(root.Solids()) != 1:
        raise ValueError(f"Focus side {side} flat internal root box is invalid")
    return root


def _focus_nested_root_stage(side: int, stage_index: int) -> cq.Shape:
    """Return one independent flat guide sleeve at its deployed hardpoints."""

    profiles = {
        # outer XY, inner XY, zmin, zmax, outer corner radius
        1: ((30.0, 38.5), (26.0, 34.5), 492.0, 570.0, 6.5),
        2: ((24.0, 32.0), (20.0, 28.0), 548.0, 632.0, 5.5),
        3: ((18.0, 26.0), (14.0, 22.0), 610.0, 674.0, 4.5),
    }
    try:
        outer_xy, inner_xy, zmin, zmax, radius = profiles[stage_index]
    except KeyError as exc:
        raise ValueError(f"Unsupported Focus root stage {stage_index}") from exc
    stage = rounded_frame(
        outer_xy,
        inner_xy,
        zmax - zmin,
        (
            FOCUS_ROOT_AXIS_X,
            side * FOCUS_ROOT_AXIS_ABS_Y,
            (zmin + zmax) / 2.0,
        ),
        radius,
    ).clean()
    if stage.isNull() or not stage.isValid() or len(stage.Solids()) != 1:
        raise ValueError(
            f"Focus side {side} internal guide stage {stage_index} is invalid"
        )
    return stage


def _focus_smooth_gap_neck(side: int) -> cq.Shape:
    """Return the tapered closed neck across only the 34 mm exterior gap."""

    if side not in {-1, 1}:
        raise ValueError(f"Focus root-neck side must be -1 or 1, got {side}")
    table_section = _rounded_rect_wire_xz(
        (16.0, 8.0),
        (FOCUS_ROOT_AXIS_X, side * 276.0, 689.0),
        2.4,
    )
    armrest_section = _rounded_rect_wire_xz(
        (16.0, 4.0),
        (FOCUS_ROOT_AXIS_X, side * 310.0, 691.0),
        1.4,
    )
    neck = cq.Solid.makeLoft(
        (table_section, armrest_section),
        ruled=False,
    )
    if neck.isNull() or not neck.isValid() or len(neck.Solids()) != 1:
        raise ValueError(f"Focus side {side} smooth gap neck is invalid")
    return neck


def _focus_hidden_root_tongue(side: int) -> cq.Shape:
    """Leaf-attached closed root neck plus an internal load spreader.

    The hinge, guide and lock remain inside A05.  A single smooth neck must
    physically span the 34 mm table-to-armrest gap; hiding that load member in
    renderer metadata made the old table appear to float.  The same occurrence
    rises through a cut pocket into a real 220 mm spreader inside the outer
    half-leaf, bypassing the cosmetic undertray.
    """

    underleaf_blade = rounded_box(
        (16.0, 34.0, 2.5),
        (FOCUS_ROOT_AXIS_X, side * 289.0, 691.25),
        1.2,
    )
    # The long twelve-millimetre walnut table edge stays visually quiet.  The
    # one honest root neck fills only the original |Y|=276..310 mm gap: it is
    # eight millimetres deep under the table, then rolls smoothly to four
    # millimetres at the armrest so the raised left HMI lid and bezel retain
    # their real clearance.  This is the same structural occurrence, never a
    # floating cosmetic fairing or a second visible support.
    smooth_gap_neck = _focus_smooth_gap_neck(side)
    vertical_turn = rounded_box(
        (16.0, 16.0, 38.5),
        (FOCUS_ROOT_AXIS_X, side * 290.0, 673.25),
        # Three millimetres retains a measured volumetric lap into the lower
        # stage link.  A four-millimetre end radius erased that two-millimetre
        # nominal overlap at the fillet and split the STEP load path.
        3.0,
    )
    stage_link = rounded_box(
        (16.0, 29.75, 3.0),
        (FOCUS_ROOT_AXIS_X, side * 310.875, 653.5),
        1.2,
    )
    spreader_riser = rounded_box(
        (16.0, 12.0, 3.3),
        (FOCUS_ROOT_AXIS_X, side * 274.0, 693.45),
        1.2,
    )
    internal_spreader = rounded_box(
        (220.0, 24.0, 4.0),
        (FOCUS_ROOT_AXIS_X, side * 262.0, 697.0),
        2.0,
    )
    tongue = (
        underleaf_blade.fuse(smooth_gap_neck)
        .fuse(vertical_turn)
        .fuse(stage_link)
        .fuse(spreader_riser)
        .fuse(internal_spreader)
        .clean()
    )
    if tongue.isNull() or not tongue.isValid() or len(tongue.Solids()) != 1:
        raise ValueError(f"Focus side {side} hidden root tongue is invalid")
    return tongue


def _focus_table_mount_shoes(side: int) -> tuple[cq.Shape, ...]:
    """Three compliant face-contact pads between tongue and outer half-leaf."""

    return tuple(
        rounded_box(
            (4.0, 4.0, 0.5),
            (station_x, side * 274.0, 692.75),
            0.8,
        )
        for station_x in (-349.0, -343.0, -337.0)
    )


def _internal_cafe_lift_boot() -> cq.Shape:
    """Compact three-stage lift shroud inside the right-armrest cavity."""

    segments = (
        rounded_frame(
            (42.0, 42.0),
            (34.0, 34.0),
            70.0,
            (TABLE_CAFE_POLE_X, 338.75, 525.0),
            12.0,
        ),
        rounded_frame(
            (38.0, 38.0),
            (30.0, 30.0),
            70.0,
            (TABLE_CAFE_POLE_X, 338.75, 585.0),
            11.0,
        ),
        rounded_frame(
            (34.0, 34.0),
            (26.0, 26.0),
            54.0,
            (TABLE_CAFE_POLE_X, 338.75, 647.0),
            10.0,
        ),
    )
    boot = union_many(segments).clean()
    if boot.isNull() or not boot.isValid() or len(boot.Solids()) != 1:
        raise ValueError("Internal Cafe A09 lift boot is not one valid solid")
    return boot


def _open_bottom_saddle(
    outer_sections: tuple[
        tuple[tuple[float, float], tuple[float, float], float, float], ...
    ],
    inner_sections: tuple[
        tuple[tuple[float, float], tuple[float, float], float, float], ...
    ],
) -> cq.Shape:
    """One thin, drainable transition shell between a lift boot and a leaf."""

    saddle = _rounded_loft_z(outer_sections).cut(_rounded_loft_z(inner_sections))
    if not saddle.isValid() or len(saddle.Solids()) != 1:
        raise ValueError("A09 under-leaf saddle is not one valid open-bottom shell")
    return saddle


def _right_control_hand_keepout() -> cq.Shape:
    """Conservative operator-hand volume around the invariant right joystick."""

    return (
        cq.Workplane("XY")
        # The verified operating-hand envelope is 70 x 52 mm in plan.  A
        # seven-millimetre radial manufacturing/trim reserve keeps the curved
        # Cafe under-leaf saddle at least five millimetres away after B-Rep
        # tolerances; six millimetres produced only 4.949 mm in the exact
        # distance solver and is therefore not released.
        .ellipse(77.0, 59.0)
        .extrude(120.0)
        .translate((-268.0, 333.0, 650.0))
        .val()
    )


def _table_edge_and_underbody(
    side: int,
    state: str,
    center_x: float,
    center_y: float,
    size_xy: tuple[float, float],
) -> list[SkinPart]:
    side_name = "right" if side > 0 else "left"
    sx, sy = size_xy
    # Do not create a continuous 430 x 270 x 12 proxy here.  The final visible
    # table must be made from the exact same two canonical rigid half-leaf
    # B-Reps used by the stow/extraction/unfold motion proof.  A former whole-
    # panel proxy left a 2 mm undertray, about 8 mm of rigid core and most of
    # the top laminate bridging the nominal fold line; the decorative shallow
    # groove could never make that object fold.
    if state == "focus":
        half_occurrences = {
            half: unfolded_half_leaf(
                side,
                half,
                axis_x=center_x,
                axis_abs_y=abs(center_y),
                axis_z=TABLE_Z,
            )
            for half in ("outer", "inner")
        }
    elif state == "cafe":
        cafe_pair = cafe_half_leaf_pair(1.0, 1.0)
        half_occurrences = {
            "inner": cafe_pair[0],
            "outer": cafe_pair[1],
        }
    else:
        raise ValueError(f"A09 deployed half-leaf skin is not defined for {state}")

    top_skin_cutter = rounded_rect_prism(
        (sx - 24.0, sy - 24.0),
        2.0,
        (center_x, center_y, 704.0),
        6.0,
    )
    underbelly_cutter = rounded_rect_prism(
        (sx, sy),
        2.0,
        (center_x, center_y, 694.0),
        8.0,
    )
    half_regions: dict[str, dict[str, cq.Shape]] = {}
    for half, occurrence in half_occurrences.items():
        leaf = occurrence.shape
        top_skin = leaf.intersect(top_skin_cutter)
        underbelly = leaf.intersect(underbelly_cutter)
        edge = leaf.cut(top_skin).cut(underbelly)
        regions = {
            "leaf": leaf,
            "top": top_skin,
            "underbelly": underbelly,
            "edge": edge,
        }
        if any(
            shape.isNull()
            or not shape.isValid()
            or len(shape.Solids()) != 1
            or float(shape.Volume()) <= 0.0
            for shape in regions.values()
        ):
            raise ValueError(
                f"A09 {state} {side_name} {half} rigid half-leaf partition is invalid"
            )
        half_regions[half] = regions

    # The one permitted external root neck continues into a real metal
    # spreader inside the outer half-leaf.  Carve that conserved occurrence
    # out of the cosmetic undertray/core partition so the final assembly has
    # no hidden common volume and the load path never relies on PC-ABS overlap.
    if state == "focus":
        structural_root = _focus_hidden_root_tongue(side)
    else:
        structural_root = next(
            occurrence.shape
            for occurrence in cafe_root_final_occurrences()
            if occurrence.name == "A09_cafe_underleaf_motion_belly_right"
        )
    for region_name in ("underbelly", "edge"):
        relieved = half_regions["outer"][region_name].cut(structural_root).clean()
        if (
            relieved.isNull()
            or not relieved.isValid()
            or len(relieved.Solids()) != 1
            or float(relieved.Volume()) <= 0.0
        ):
            raise ValueError(
                f"A09 {state} {side_name} outer {region_name} root pocket is invalid"
            )
        half_regions["outer"][region_name] = relieved

    # The one-millimetre TPE insert is now the only material crossing the
    # physical gap.  Every PC-ABS/core/laminate region terminates on its own
    # canonical half-leaf.  Focus runs the fold along global X; Cafe is the
    # same occurrence rotated ninety degrees, so the fold runs along global Y.
    if sx > sy:
        fold_flexure_size = (sx - 24.0, 1.0, 0.4)
    else:
        fold_flexure_size = (1.0, sy - 24.0, 0.4)
    fold_flexure = rounded_box(
        fold_flexure_size,
        (center_x, center_y, 704.75),
        0.35,
    )
    lock_opening: str | None = None
    paddle_bezel_shapes: list[cq.Shape] = []
    if state == "focus":
        # Two shallow leaf-local pockets receive the physical over-centre
        # paddles.  They do not cut the bottom skin or open the entire inner
        # rail, so the final surface remains a closed, cleanable object.
        paddle_pockets = tuple(
            rounded_box(
                (58.0, 12.0, 3.0),
                (lock_x, side * 12.0, 704.5),
                4.0,
            )
            for lock_x in FOCUS_LOCK_STATIONS_X_MM
        )
        paddle_bezel_shapes = [
            half_regions["inner"]["leaf"].intersect(pocket)
            for pocket in paddle_pockets
        ]
        half_regions["inner"]["top"] = cut_many(
            half_regions["inner"]["top"],
            paddle_pockets,
        )
        half_regions["inner"]["edge"] = cut_many(
            half_regions["inner"]["edge"],
            paddle_pockets,
        )
        lock_opening = (
            "focus_centre_latch desk_lock_pin table_lock_release inspection_access"
        )
    parts: list[SkinPart] = []
    for half in ("outer", "inner"):
        suffix = "" if half == "outer" else "_fold_half_inner"
        id_suffix = "" if half == "outer" else "-FOLD-HALF-INNER"
        half_id = (
            f"WC-A09-TABLE-HALF-LEAF-{side_name.upper()}-{half.upper()}"
        )
        common_metadata = {
            "physical_leaf_id": half_id,
            "rigid_half_leaf_occurrence_id": half_id,
            "rigid_half_role": half,
            "controlled_rigid_half_leaf_mm": (430.0, 134.5, 12.0),
            "controlled_complete_table_mm": (
                TABLE_LENGTH,
                TABLE_WIDTH,
                TABLE_THICKNESS,
            ),
            "source_occurrence_ids": (f"desk_panel_{side_name}",),
            "disposition": "replace_surface",
            "proxy_group_id": (
                f"E6-A09-TABLE-LEAF-FINAL-{side_name.upper()}"
            ),
            "functional_opening": (
                lock_opening if half == "inner" else None
            ),
            "centre_lock_stations_x_mm": (
                FOCUS_LOCK_STATIONS_X_MM
                if state == "focus" and half == "inner"
                else None
            ),
            "static_brep_from_motion_canonical_half_leaf": True,
            "rigid_leaf_control_relief_present": False,
            "right_control_clearance_by_centre_side_table_index": side > 0,
            "deployed_outboard_table_limit_mm": (
                276.0 if side > 0 else -276.0
            ),
            "book_matched_with_other_half": True,
            "veneer_grain_datum_continuous_across_fold": True,
            "rigid_skin_bridges_fold_hinge": False,
        }
        parts.extend(
            [
                _part(
                    f"A09_table_edge_band_{side_name}{suffix}",
                    half_regions[half]["edge"],
                    LUNAR_STONE,
                    "body-colour replaceable impact edge-close band",
                    "A09",
                    state,
                    "One rigid half-leaf perimeter terminates at the real fold gap; no PC-ABS edge or core bridges to the other half.",
                    physical_occurrence_id=(
                        f"E6-A09-TABLE-EDGE-{side_name.upper()}{id_suffix}"
                    ),
                    **common_metadata,
                ),
                _part(
                    f"A09_table_top_skin_{side_name}{suffix}",
                    half_regions[half]["top"],
                    ESPRESSO,
                    "book-matched natural smoked-walnut veneer over balanced lightweight core with low-sheen repairable hardwax finish",
                    "A09",
                    state,
                    "One book-matched natural-veneer field ends at the physical one-millimetre fold gap and moves only with its own rigid half-leaf; matched grain preserves one calm visual field without a false rigid bridge.",
                    physical_occurrence_id=(
                        f"E6-A09-TABLE-TOP-SKIN-{side_name.upper()}{id_suffix}"
                    ),
                    final_presentation_proxy_for=f"desk_panel_{side_name}",
                    **common_metadata,
                ),
                _part(
                    f"A09_table_underbelly_shell_{side_name}{suffix}",
                    half_regions[half]["underbelly"],
                    GRAPHITE_BROWN,
                    "thin thermoformed PC-ABS undertray",
                    "A09",
                    state,
                    "One independent undertray covers its rigid half-leaf and stops before the fold gap, leaving no hidden hard bridge.",
                    physical_occurrence_id=(
                        f"E6-A09-TABLE-UNDERBELLY-{side_name.upper()}{id_suffix}"
                    ),
                    **common_metadata,
                ),
            ]
        )

    parts.append(
        _part(
            f"A09_table_fold_flexure_{side_name}",
            fold_flexure,
            TPE_DARK,
            "recessed replaceable one-millimetre TPE fold-line insert",
            "A09",
            state,
            "A quiet recessed seam identifies the two real half-leaves and the concealed under-mounted fold hinge without exposing hardware.",
            physical_occurrence_id=f"E6-A09-TABLE-FOLD-FLEXURE-{side_name.upper()}",
            physical_leaf_id=f"WC-DESK-PANEL-{side_name.upper()}",
            rigid_half_leaf_mm=(430.0, 134.5, 12.0),
            fold_seam_width_mm=1.0,
            concealed_dual_cam_pin_outer_diameter_mm=4.0,
            anti_rub_spacing_mm=1.5,
            unfolds_only_after_pack_clears_open_top_lid=True,
            lid_remains_open_during_unfold=True,
            lid_closes_only_after_table_reaches_90_mm_control_clearance=True,
            only_flexible_material_crossing_fold_gap=True,
            disposition="replace_surface",
            proxy_group_id=f"E6-A09-TABLE-LEAF-FINAL-{side_name.upper()}",
        )
    )
    if state == "focus":
        for station, (lock_x, paddle_bezel) in enumerate(
            zip(FOCUS_LOCK_STATIONS_X_MM, paddle_bezel_shapes),
            start=1,
        ):
            parts.append(
                _part(
                    f"A09_focus_lock_paddle_bezel_{side_name}_{station}",
                    paddle_bezel,
                    GRAPHITE_BROWN,
                    "sealed replaceable lock-paddle pocket bezel",
                    "A09",
                    state,
                    "A leaf-local bezel exactly fills the source-envelope surface partition around the mechanical paddle without bridging the centre seam.",
                    physical_occurrence_id=f"E6-A09-FOCUS-LOCK-BEZEL-{side_name.upper()}-{station}",
                    lock_station_id=f"focus_centre_lock_{station}",
                    linkage_id=f"focus_centre_lock_linkage_{station}",
                    controlled_station_x_mm=lock_x,
                    functional_opening="focus_lock_release_pocket sealed_access",
                )
            )
        seam_seal = rounded_box(
            (390.0, 3.0, 5.0),
            (center_x, side * 7.5, 698.5),
            1.5,
        )
        parts.append(
            _part(
                f"A09_focus_centre_seam_seal_{side_name}",
                seam_seal,
                TPE_DARK,
                "replaceable hydrophobic centre-edge TPE seal",
                "A09",
                state,
                "Independent inner-edge seals preserve the twelve-millimetre escape, pinch and liquid-drain seam without bridging the leaves.",
                physical_occurrence_id=f"E6-A09-FOCUS-CENTRE-SEAL-{side_name.upper()}",
                controlled_center_gap_mm=TABLE_GAP,
                functional_opening="focus_table_centre_drain pinch_control escape_seam",
            )
        )
    return parts


def _table_parts(state: str) -> list[SkinPart]:
    if state in ("follow", "ride"):
        # The physical leaves remain in the A05 cassettes; no exterior A09
        # surface is emitted, so Ride cannot accidentally read as a desk.
        return []

    parts: list[SkinPart] = []
    if state == "cafe":
        # Right leaf only.  The controlled 90-degree turn swaps its visible X/Y
        # spans while retaining the same 430 x 270 x 12 mm physical part.
        side = 1
        panel_y = CAFE_FINAL_AXIS_Y_MM
        parts.extend(
            _table_edge_and_underbody(
                side,
                state,
                TABLE_CAFE_X,
                panel_y,
                (TABLE_WIDTH, TABLE_LENGTH),
            )
        )
        pole_boot = _internal_cafe_lift_boot()
        # The previous exposed bridge/fairing/saddle stack is deliberately not
        # emitted.  The final A09 mechanism module supplies one compact internal
        # cartridge plus the table-attached thin tongue; there is no cosmetic
        # proxy outside the right armrest inner face.
        final_controls = {
            occurrence.name: occurrence
            for occurrence in cafe_table_control_final_occurrences()
        }
        release_paddle = final_controls[
            "A09_cafe_lock_release_paddle_right"
        ].shape
        lock_witness = final_controls[
            "A09_cafe_positive_lock_witness_right"
        ].shape
        parts.extend(
            [
                _part(
                    "A09_cafe_internal_lift_packaging_envelope_right",
                    pole_boot,
                    GRAPHITE_BROWN,
                    "internal three-zone deployment-mechanism packaging envelope",
                    "A09",
                    state,
                    "A conservative internal envelope reserves a feasible lift/deploy cartridge inside the right armrest without asserting an unknown supplier mechanism or exposing a column beside the table.",
                    physical_occurrence_id="E6-A09-CAFE-INTERNAL-LIFT-PACKAGING-ENVELOPE-RIGHT",
                    controlled_pole_center_mm=(TABLE_CAFE_POLE_X, 338.75),
                    supplier_mechanism_not_frozen=True,
                    layout_packaging_reservation=True,
                    internal_clear_aperture_minimum_mm=26.0,
                    packaged_inside_armrest_cavity_y_mm=(316.0, 361.5),
                    measured_y_bounds_mm=(317.75, 359.75),
                    final_exterior_visible=False,
                    production_certification_claimed=False,
                ),
                _part(
                    "A09_cafe_lock_release_paddle_right",
                    release_paddle,
                    GRAPHITE_BROWN,
                    "glove-operable internal mechanical release paddle",
                    "A09",
                    state,
                    "The two-action paddle remains inside the fixed right-armrest cartridge and releases the deployed root lock through a captive mechanical linkage; it is reached only through the opened top service lid and is never an exposed table bracket.",
                    physical_occurrence_id=final_controls[
                        "A09_cafe_lock_release_paddle_right"
                    ].physical_occurrence_id,
                    internal_control_center_mm=(
                        -338.0,
                        CAFE_PADDLE_OUTER_UNDERSIDE_Y_MM,
                        632.0,
                    ),
                    controlled_lock_interfaces=(
                        "cafe_deployment_interlock",
                        "cafe_deployed_root_lock",
                    ),
                    lock_station_id="cafe_right_translation_rotation_lock",
                    linkage_id="cafe_right_table_lock_linkage",
                    linkage_type="captive_push_pull_mechanical_linkage",
                    moves_with="fixed_internal_armrest_lock_cartridge",
                    manual_no_power=True,
                    two_action=True,
                    final_exterior_visible=False,
                    packaged_inside_armrest_cavity_y_mm=(316.0, 361.5),
                    functional_opening="cafe_lock_release table_lock_release table_release_interface",
                ),
                _part(
                    "A09_cafe_positive_lock_witness_right",
                    lock_witness,
                    GRAPHITE_BROWN,
                    "internal mechanically indexed lock-state witness",
                    "A09",
                    state,
                    "A small mechanical ring stays inside the fixed armrest cartridge and is inspected through the opened service lid; the locked exterior carries no decorative light or exposed moving witness.",
                    physical_occurrence_id=final_controls[
                        "A09_cafe_positive_lock_witness_right"
                    ].physical_occurrence_id,
                    internal_witness_center_mm=(
                        round(float(lock_witness.Center().x), 6),
                        round(float(lock_witness.Center().y), 6),
                        round(float(lock_witness.Center().z), 6),
                    ),
                    controlled_lock_interfaces=(
                        "cafe_deployment_interlock",
                        "cafe_deployed_root_lock",
                    ),
                    lock_station_id="cafe_right_translation_rotation_lock",
                    linkage_id="cafe_right_table_lock_linkage",
                    linkage_type="captive_push_pull_mechanical_linkage",
                    moves_with="fixed_internal_armrest_lock_cartridge",
                    final_exterior_visible=False,
                    packaged_inside_armrest_cavity_y_mm=(316.0, 361.5),
                    functional_opening="cafe_rotation_lock_pin table_positive_lock inspection_access",
                ),
            ]
        )
        for occurrence in cafe_root_final_occurrences():
            exterior_root = (
                occurrence.name == "A09_cafe_underleaf_motion_belly_right"
            )
            if occurrence.role == "fixed_drainable_yoke_housing":
                material = "blackened aluminium internal drainable root housing"
            elif occurrence.role == "fixed_aluminium_yoke_outer_race_and_lift_collar":
                material = "hard-anodised aluminium fixed bearing carrier"
            elif occurrence.role == "catalog_bearing_inner_race_and_rail_pedestal":
                material = "supplier-envelope sealed rotary bearing hub"
            elif occurrence.role == "internal_rotary_torque_key":
                material = "blackened stainless internal rotary torque key"
            elif occurrence.role == "table_attached_closed_root_neck_and_internal_spreader":
                material = "low-gloss graphite stainless closed root neck and 220 mm internal spreader"
            else:
                raise ValueError(
                    f"Unsupported Cafe layout root role {occurrence.role!r}"
                )
            parts.append(
                _part(
                    occurrence.name,
                    occurrence.shape,
                    GRAPHITE_BROWN,
                    material,
                    "A09",
                    state,
                    (
                        "One calm closed root neck is the only structural member outside the armrest; "
                        "its 220 mm spreader is embedded inside the outer half-leaf."
                        if exterior_root
                        else "Internal Cafe root hardware remains behind the fixed A05 weather skin and transfers load into the metal structural cassette."
                    ),
                    physical_occurrence_id=occurrence.physical_occurrence_id,
                    motion_owner=occurrence.motion_owner,
                    layout_kinematic_envelope_only=True,
                    supplier_component_not_frozen=True,
                    final_exterior_visible=exterior_root,
                    root_neck_outside_armrest=exterior_root,
                    hinge_bearing_and_lock_outside_armrest=False,
                    internal_spreader_length_mm=(220.0 if exterior_root else None),
                    visible_gap_neck_y_bounds_mm=(
                        (276.0, 310.0) if exterior_root else None
                    ),
                    visible_gap_neck_section_mm=(
                        (22.0, 8.0) if exterior_root else None
                    ),
                    visible_gap_neck_is_smooth_closed_envelope=exterior_root,
                    production_certification_claimed=False,
                )
            )
        return parts

    # Focus: both original leaves, each 430 x 270 x 12 mm, with the controlled
    # twelve-millimetre centre seam.  No fairing bridges that safety gap.
    for side in (-1, 1):
        side_name = "right" if side > 0 else "left"
        panel_y = side * (TABLE_GAP / 2.0 + TABLE_WIDTH / 2.0)
        parts.extend(
            _table_edge_and_underbody(
                side,
                state,
                TABLE_FOCUS_X,
                panel_y,
                (TABLE_LENGTH, TABLE_WIDTH),
            )
        )
        root_box = _focus_flat_root_box(side)
        root_stages = tuple(
            _focus_nested_root_stage(side, stage_index)
            for stage_index in (1, 2, 3)
        )
        hidden_tongue = _focus_hidden_root_tongue(side)
        parts.extend(
            [
                _part(
                    f"A09_focus_internal_root_box_{side_name}",
                    root_box,
                    GRAPHITE_BROWN,
                    "blackened aluminium closed-bottom flat root housing",
                    "A09",
                    state,
                    "A compact fixed housing occupies only the released A05 inner cavity and provides a closed structural floor for the nested guides; it creates no exterior collar or top opening.",
                    physical_occurrence_id=(
                        f"E6-A09-FOCUS-INTERNAL-ROOT-BOX-{side_name.upper()}"
                    ),
                    controlled_axis_xy_mm=(
                        FOCUS_ROOT_AXIS_X,
                        side * FOCUS_ROOT_AXIS_ABS_Y,
                    ),
                    controlled_cavity_x_mm=FOCUS_ROOT_CAVITY_X_MM,
                    controlled_cavity_y_mm=(
                        tuple(-value for value in reversed(FOCUS_ROOT_CAVITY_RIGHT_Y_MM))
                        if side < 0
                        else FOCUS_ROOT_CAVITY_RIGHT_Y_MM
                    ),
                    outer_xy_mm=(35.0, 42.0),
                    closed_bottom=True,
                    open_top_inside_closed_armrest=True,
                    final_exterior_visible=False,
                    fixed_to=(
                        f"A05_table_root_structural_cassette_{side_name}"
                    ),
                    mechanism_z_max_mm=535.0,
                ),
            ]
        )
        for stage_index, stage_shape in enumerate(root_stages, start=1):
            outer_xy = ((30.0, 38.5), (24.0, 32.0), (18.0, 26.0))[
                stage_index - 1
            ]
            z_bounds = ((492.0, 570.0), (548.0, 632.0), (610.0, 674.0))[
                stage_index - 1
            ]
            parts.append(
                _part(
                    (
                        f"A09_focus_internal_nested_guide_stage_"
                        f"{stage_index}_{side_name}"
                    ),
                    stage_shape,
                    GRAPHITE_BROWN,
                    "blackened aluminium compact dry-running guide sleeve",
                    "A09",
                    state,
                    "One independent flat nested guide remains wholly below the closed armrest lid and inside its cavity; no telescopic post is exposed beside the table.",
                    physical_occurrence_id=(
                        f"E6-A09-FOCUS-INTERNAL-GUIDE-{stage_index}-"
                        f"{side_name.upper()}"
                    ),
                    controlled_axis_xy_mm=(
                        FOCUS_ROOT_AXIS_X,
                        side * FOCUS_ROOT_AXIS_ABS_Y,
                    ),
                    stage_index=stage_index,
                    outer_xy_mm=outer_xy,
                    deployed_z_bounds_mm=z_bounds,
                    nested_overlap_mm=(None, 22.0, 22.0)[stage_index - 1],
                    independent_physical_stage=True,
                    final_exterior_visible=False,
                    mechanism_z_max_mm=z_bounds[1],
                    closed_lid_top_aperture_present=False,
                )
            )
        parts.append(
            _part(
                f"A09_focus_table_hidden_root_tongue_{side_name}",
                hidden_tongue,
                GRAPHITE_BROWN,
                "low-gloss graphite stainless closed root neck and 220 mm internal spreader",
                "A09",
                state,
                "The outer half-leaf carries one smooth closed root neck across the unavoidable 34 mm gap; its hinge, guides and lock remain inside A05 while a real 220 mm spreader continues inside the table core.",
                physical_occurrence_id=(
                    f"E6-A09-FOCUS-HIDDEN-ROOT-TONGUE-{side_name.upper()}"
                ),
                moves_with=f"focus_{side_name}_outer_root_half_leaf",
                physical_leaf_id=(
                    f"WC-A09-TABLE-HALF-LEAF-{side_name.upper()}-OUTER"
                ),
                crosses_a05_only_at="inner_sidewall_structural_port",
                root_neck_outside_armrest=True,
                hinge_bearing_and_lock_outside_armrest=False,
                underleaf_blade_y_bounds_mm=(
                    (-306.0, -272.0) if side < 0 else (272.0, 306.0)
                ),
                visible_gap_neck_y_bounds_mm=(
                    (-310.0, -276.0) if side < 0 else (276.0, 310.0)
                ),
                visible_gap_neck_table_section_xz_mm=(16.0, 8.0),
                visible_gap_neck_armrest_section_xz_mm=(16.0, 4.0),
                visible_gap_neck_top_z_mm=693.0,
                visible_gap_neck_minimum_hmi_clearance_mm=2.8,
                visible_gap_neck_is_smooth_tapered_loft=True,
                vertical_turn_y_span_mm=16.0,
                vertical_turn_center_abs_y_mm=290.0,
                sidewall_link_z_bounds_mm=(652.0, 655.0),
                internal_spreader_length_mm=220.0,
                internal_spreader_section_mm=(220.0, 24.0, 4.0),
                cosmetic_undertray_is_primary_load_path=False,
                final_exterior_visible=True,
                does_not_bridge_table_internal_fold=True,
                production_certification_claimed=False,
            )
        )
        for station, lock_x in enumerate(FOCUS_LOCK_STATIONS_X_MM, start=1):
            release_paddle = rounded_box(
                (50.0, 6.0, 3.0),
                (lock_x, side * 10.0, 706.5),
                1.5,
            )
            parts.append(
                _part(
                        f"A09_focus_lock_release_paddle_{side_name}_{station}",
                        release_paddle,
                        CHAMPAGNE,
                        "glove-operable over-centre mechanical lock paddle",
                        "A09",
                        state,
                        "A leaf-local over-centre paddle gives tactile release and a mechanical flush/not-flush lock witness while preserving the centre seam.",
                        physical_occurrence_id=f"E6-A09-FOCUS-LOCK-PADDLE-{side_name.upper()}-{station}",
                        controlled_station_x_mm=lock_x,
                        controlled_center_gap_mm=TABLE_GAP,
                        lock_station_id=f"focus_centre_lock_{station}",
                        linkage_id=f"focus_centre_lock_linkage_{station}",
                        manual_no_power=True,
                        functional_opening="focus_lock_release table_lock_release table_release_interface table_positive_lock desk_lock_pin",
                )
            )
    return parts


def build_upper_skin(config: str | Mapping[str, Any]) -> list[SkinPart]:
    """Build A05/A06/A07/A09 upper exterior parts for one E6 state.

    The function is pure: it returns closed solids and does not export files or
    alter the controlled assembly.  Call ``skin_common.validate_parts`` before
    any optional export performed by an external driver.
    """

    state = _normalise_state(config)
    parts: list[SkinPart] = []
    parts.extend(_armrest_shell(-1, state))
    parts.extend(_armrest_shell(1, state))
    parts.extend(_backrest_parts(state))
    parts.extend(_mast_parts(state))
    parts.extend(_table_parts(state))
    return parts


__all__ = ["build_upper_skin"]
