"""V8 object-character refinements layered over the validated V7 hardpoints.

This module deliberately keeps the V7 geometry builders intact.  It replaces
only named cosmetic proxy shapes (preserving their physical occurrence IDs)
and adds a small number of independently serviceable closure parts.  The
controlled E6-DFR5-A07-SHARED-HINGE primary STEP assemblies and preserved
DFR4/DFR3 trace assemblies remain read-only.

Coordinates (mm): -X front / foot side, +X rear, +Y right, -Y left, +Z up.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import cadquery as cq

try:
    from .skin_common import (
        CHAMPAGNE,
        LUNAR_STONE,
        SAFETY_RED,
        SMOKED_UMBER,
        TPE_DARK,
        SkinPart,
        cut_many,
        rounded_box,
        union_many,
    )
except ImportError:
    from skin_common import (  # type: ignore[no-redef]
        CHAMPAGNE,
        LUNAR_STONE,
        SAFETY_RED,
        SMOKED_UMBER,
        TPE_DARK,
        SkinPart,
        cut_many,
        rounded_box,
        union_many,
    )

try:
    from .v8_state_contract import default_footrest_is_deployed
except ImportError:
    from v8_state_contract import default_footrest_is_deployed  # type: ignore[no-redef]


STATES = {"follow", "ride", "cafe", "focus"}


def _rounded_rect_wire_xy(
    size_xy: tuple[float, float],
    center_xy: tuple[float, float],
    z: float,
    radius: float,
) -> cq.Wire:
    sx, sy = size_xy
    cx, cy = center_xy
    safe = min(radius, sx * 0.49, sy * 0.49)
    sketch = cq.Sketch().rect(sx, sy)
    if safe > 0.0:
        sketch = sketch.vertices().fillet(safe)
    wire = sketch.reset().wires().val()
    if not isinstance(wire, cq.Wire):
        raise TypeError("V8 rounded section did not resolve to a wire")
    return wire.translate((cx, cy, z))


def _rounded_loft_z(
    sections: tuple[
        tuple[tuple[float, float], tuple[float, float], float, float],
        ...,
    ],
) -> cq.Solid:
    wires = [
        _rounded_rect_wire_xy(size_xy, center_xy, z, radius)
        for size_xy, center_xy, z, radius in sections
    ]
    body = cq.Solid.makeLoft(wires, ruled=False)
    if not body.isValid():
        raise ValueError("V8 rounded loft is invalid")
    return body


def _rounded_panel_xz(
    size_xz: tuple[float, float],
    thickness_y: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    sx, sz = size_xz
    body = cq.Workplane("XZ").rect(sx, sz).extrude(thickness_y / 2.0, both=True)
    try:
        body = body.edges("|Y").fillet(min(radius, sx * 0.45, sz * 0.45))
    except Exception:
        pass
    return body.translate(center).val()


def _replace_named(
    parts: list[SkinPart],
    name: str,
    *,
    shape: cq.Shape | None = None,
    color: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    intent: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    for index, part in enumerate(parts):
        if part.name != name:
            continue
        merged_metadata = dict(part.metadata)
        if metadata:
            merged_metadata.update(metadata)
        parts[index] = replace(
            part,
            shape=shape if shape is not None else part.shape,
            color=color if color is not None else part.color,
            material=material if material is not None else part.material,
            intent=intent if intent is not None else part.intent,
            metadata=merged_metadata,
        )
        return
    raise KeyError(f"V8 refinement could not find required proxy {name}")


def _new_part(
    name: str,
    shape: cq.Shape,
    color: tuple[float, float, float, float],
    material: str,
    module: str,
    state: str,
    intent: str,
    **metadata: object,
) -> SkinPart:
    return SkinPart(
        name=name,
        shape=shape,
        color=color,
        material=material,
        module=module,
        configuration=state,
        intent=intent,
        metadata=dict(metadata),
    )


def _quiet_stowed_cassette_faces(state: str, parts: list[SkinPart]) -> None:
    """Forbid the superseded side cassette and freeze top-only table access."""

    legacy_prefixes = (
        "A05_table_cassette_door_",
        "A05_table_cassette_shadow_horizon_",
        "A05_table_cassette_exit_bezel_",
        "A05_table_cassette_throat_seal_",
    )
    parts[:] = [
        part for part in parts if not part.name.startswith(legacy_prefixes)
    ]
    for side_name in ("left", "right"):
        _replace_named(
            parts,
            f"A05_armrest_touch_lid_{side_name}",
            metadata={
                "legacy_side_table_access_present": False,
                "only_table_access_path": "outward_flipping_top_lid",
                "final_render_pose": "closed_and_latched",
                "v8_object_character_gate": "fixed_body_top_access_only",
            },
        )


def _follow_closed_field(state: str, parts: list[SkinPart]) -> None:
    if state != "follow":
        return

    # Follow has no state-only field shell or vault.  The same trapezoidal A06
    # backrest and complete A07 package co-fold on one hinge and remain the
    # only upper surfaces.  Keep only the independent mechanical emergency
    # stop interface below; it does not cover either moving object.
    guard = (
        cq.Workplane("XZ")
        .circle(22.0)
        .circle(17.0)
        .extrude(4.0, both=True)
        .translate((-294.0, -367.0, 590.0))
        .val()
    )
    button = (
        cq.Workplane("XZ")
        .circle(15.0)
        .extrude(3.5, both=True)
        .translate((-294.0, -367.5, 590.0))
        .val()
    )
    # Preserve the exact controlled stop proxy at its source hardpoint inside
    # the shell.  A separate purely mechanical exterior actuator links to it;
    # this avoids falsifying the controlled ergonomic datum while keeping an
    # emergency stop reachable in the closed Follow state.
    parts.extend(
        [
            _new_part(
                "A05_follow_external_emergency_stop_guard",
                guard,
                CHAMPAGNE,
                "satin anodised impact guard with sealed mechanical plunger",
                "A05",
                state,
                "A guarded exterior actuator reaches the unchanged hardwired stop through the closed-field shell.",
                physical_occurrence_id="E6-A05-FOLLOW-EXTERNAL-ESTOP-GUARD",
                source_control_center_mm=(-294.0, -320.0, 590.0),
                final_exterior_projection_center_mm=(-294.0, -367.0, 590.0),
                mechanical_plunger_link_mm=47.0,
                functional_opening="follow_mechanical_emergency_stop",
            ),
            _new_part(
                "A05_follow_external_mechanical_emergency_stop",
                button,
                SAFETY_RED,
                "safety-rated red twist-release actuator over sealed mechanical linkage",
                "A05",
                state,
                "The only proud upper control in Follow is a directly mechanical emergency stop actuator.",
                physical_occurrence_id="E6-A05-FOLLOW-EXTERNAL-ESTOP",
                source_control_center_mm=(-294.0, -320.0, 590.0),
                final_exterior_projection_center_mm=(-294.0, -367.5, 590.0),
                mechanical_plunger_link_mm=47.5,
                manual_no_power=True,
                functional_opening="follow_mechanical_emergency_stop emergency_stop",
            ),
        ]
    )

    status_witness = _rounded_panel_xz(
        (92.0, 12.0),
        3.0,
        (-208.0, -368.5, 650.0),
        6.0,
    )
    parts.append(
        _new_part(
            "A05_follow_neutral_status_witness",
            status_witness,
            SMOKED_UMBER,
            "sealed neutral-density status lens with patterned non-colour redundancy",
            "A05",
            state,
            "A single quiet physical witness reports stopped/moving/attention states without exposing a dormant screen.",
            physical_occurrence_id="E6-A05-FOLLOW-NEUTRAL-STATUS-WITNESS",
            active_content_restricted_to="motion stopped attention fault",
            no_task_content=True,
            readable_distance_target_m=2.0,
            usability_validation_required=True,
        )
    )


def _smooth_table_supports(state: str, parts: list[SkinPart]) -> None:
    """Preserve the real A05-internal roots supplied by ``skin_upper``.

    The retired prototype pass replaced Café's compact in-cavity cartridge
    with an X=-430/Y=300 exterior column.  That contradicted the armrest
    packaging contract and recreated exactly the exposed support the final
    design forbids.  Café and Focus therefore require no styling rebody here;
    their mechanism skins are owned by the production root modules.
    """

    del state, parts


def _footrest_deployment_header(state: str, parts: list[SkinPart]) -> None:
    if not default_footrest_is_deployed(state):
        return
    outer = rounded_box((92.0, 520.0, 76.0), (-505.0, 0.0, 113.0), 26.0)
    inner = rounded_box((104.0, 474.0, 66.0), (-498.0, 0.0, 96.0), 20.0)
    header = outer.cut(inner)
    header = header.cut(
        rounded_box((112.0, 100.0, 62.0), (-505.0, 0.0, 116.0), 18.0)
    )
    halves = {
        "left": header.intersect(
            rounded_box((120.0, 212.0, 100.0), (-505.0, -156.0, 113.0), 8.0)
        ),
        "right": header.intersect(
            rounded_box((120.0, 212.0, 100.0), (-505.0, 156.0, 113.0), 8.0)
        ),
    }
    for side_name, half in halves.items():
        if not half.isValid() or half.Volume() <= 0.0:
            raise ValueError(f"V8 {state} {side_name} footrest header is invalid")
        _replace_named(
            parts,
            f"A08_footrest_root_cowl_{side_name}",
            shape=half,
            material="split body-colour open-bottom PC-ABS deployment header",
            intent=(
                "The two service halves form one calm transverse header over both support roots; "
                "the central no-power release remains visibly open."
            ),
            metadata={
                "moving_with_footrest": True,
                "open_bottom": True,
                "centre_manual_latch_unobstructed": True,
                "gravity_drain": True,
                "paired_continuous_header": True,
                "header_outer_span_y_mm": 520.0,
                "central_release_opening_y_mm": 100.0,
                "v8_object_character_gate": "one_deployment_drawer_not_two_hinges",
            },
        )


def refine_v8_parts(state: str, base_parts: Iterable[SkinPart]) -> list[SkinPart]:
    """Return V8 refinements while preserving every V7 proxy identity."""

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 state {state!r}")
    parts = list(base_parts)
    _quiet_stowed_cassette_faces(state, parts)
    _follow_closed_field(state, parts)
    _smooth_table_supports(state, parts)
    _footrest_deployment_header(state, parts)
    return parts


__all__ = ["refine_v8_parts"]
