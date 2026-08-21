"""V8 A07 mast-interface and privacy-window corrections.

This is a deliberately small post-process over the V8/V7 named A07 proxies.
It does not read, write or modify any controlled STEP assembly.  The original
``A07_mast_moving_inner_sleeve`` occurrence is retained as telescopic stage 1;
stages 2 and 3 are added as independently serviceable solids.

Coordinates are the controlled WorkCore convention (millimetres): -X front,
+X rear, +Y right, -Y left and +Z up.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import cadquery as cq

try:
    from .skin_common import (
        SkinPart,
        rounded_frame,
        rounded_rect_prism,
        validate_parts,
    )
    from .skin_upper import BACK_FOLD_DEG, BACK_HINGE
except ImportError:
    from skin_common import (  # type: ignore[no-redef]
        SkinPart,
        rounded_frame,
        rounded_rect_prism,
        validate_parts,
    )
    from skin_upper import BACK_FOLD_DEG, BACK_HINGE  # type: ignore[no-redef]


STATES = {"follow", "ride", "cafe", "focus"}
MAST_X = 310.0
# There is one physical A06/A07 co-fold hinge.  Import the controlled hard
# point instead of duplicating a numeric value here: a stale 509 mm copy once
# rotated the post-processed telescope six millimetres away from the original
# Follow occurrence and invalidated the safety-envelope proof.
MAST_FOLD_HINGE = BACK_HINGE
BEAM_LOW_Z = 1040.0
MAST_STROKE_MM = 420.0
GEOMETRY_TOL_MM = 1.0e-4
VOLUME_TOL_MM3 = 1.0e-5


def _part_index(parts: list[SkinPart], name: str) -> int:
    matches = [index for index, part in enumerate(parts) if part.name == name]
    if len(matches) != 1:
        raise KeyError(
            f"V8 A07 mast correction requires exactly one {name!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _intersection_volume(shape_a: cq.Shape, shape_b: cq.Shape) -> float:
    return float(shape_a.intersect(shape_b).Volume())


def _distance(shape_a: cq.Shape, shape_b: cq.Shape) -> float:
    return float(shape_a.distance(shape_b))


def _rotate_follow(shape: cq.Shape) -> cq.Shape:
    ox, oy, oz = MAST_FOLD_HINGE
    return shape.rotate(
        (ox, oy, oz),
        (ox, oy + 1.0, oz),
        BACK_FOLD_DEG,
    )


def _bounds_within(inner: cq.Shape, outer: cq.Shape, tol: float = 1.0e-3) -> bool:
    child = inner.BoundingBox()
    parent = outer.BoundingBox()
    return (
        child.xmin >= parent.xmin - tol
        and child.xmax <= parent.xmax + tol
        and child.ymin >= parent.ymin - tol
        and child.ymax <= parent.ymax + tol
        and child.zmin >= parent.zmin - tol
        and child.zmax <= parent.zmax + tol
    )


def _stage_sections(
    state: str,
) -> tuple[
    tuple[tuple[float, float], tuple[float, float], float],
    tuple[tuple[float, float], tuple[float, float], float],
    tuple[tuple[float, float], tuple[float, float], float],
]:
    """Return outer/inner/radius sections with a real 3 mm dry gap.

    Follow uses a conserved compact stack wholly inside the released folded
    66 x 130 mm cosmetic envelope.  The occupied-state stack uses the full
    broad-root allowance but remains inside the V7 90 x 158 mm AABB.
    """

    if state == "follow":
        return (
            ((66.0, 130.0), (60.0, 124.0), 22.0),
            ((54.0, 118.0), (48.0, 112.0), 18.0),
            ((42.0, 106.0), (34.0, 98.0), 14.0),
        )
    return (
        ((88.0, 154.0), (82.0, 148.0), 30.0),
        ((76.0, 142.0), (70.0, 136.0), 26.0),
        ((64.0, 130.0), (56.0, 120.0), 22.0),
    )


def _stage_z_ranges(state: str) -> tuple[tuple[float, float], ...]:
    """Rigid stage locations in low and 420 mm Focus configurations.

    The three Focus absolute translations are 140/280/420 mm.  Consequently
    each telescope joint contributes 140 mm, while preserving 20/21 mm of
    mechanical overlap at the two moving interfaces.  In low states the same
    three solids are radially nested without interpenetration.
    """

    low = ((818.0, 981.0), (821.0, 981.0), (820.0, 1008.0))
    if state != "focus":
        return low
    translations = (140.0, 280.0, 420.0)
    return tuple(
        (zmin + travel, zmax + travel)
        for (zmin, zmax), travel in zip(low, translations)
    )


def _connected_stage_shell(
    outer_xy: tuple[float, float],
    inner_xy: tuple[float, float],
    height: float,
    center: tuple[float, float, float],
    outer_radius: float,
) -> cq.Shape:
    """Build one constant-wall telescopic sleeve instead of four visual rails.

    ``skin_common.rounded_frame`` deliberately used a much smaller inner
    radius.  On these very thin A07 sleeves that makes the corner wall flare,
    and the later rigid partition correctly splits the result into four long
    pieces.  Those pieces read as exposed guide rods in the Focus render.  A
    radius offset equal to the radial wall keeps the annulus connected and
    makes the moving member itself the weather cover.
    """

    radial_wall = min(
        (outer_xy[0] - inner_xy[0]) / 2.0,
        (outer_xy[1] - inner_xy[1]) / 2.0,
    )
    if radial_wall <= 0.0:
        raise ValueError("A07 stage requires a positive radial wall")
    inner_radius = max(1.0, outer_radius - radial_wall)
    outer = rounded_rect_prism(outer_xy, height, center, outer_radius)
    inner = rounded_rect_prism(
        inner_xy,
        height + 4.0,
        center,
        inner_radius,
    )
    shell = outer.cut(inner)
    if not shell.isValid() or len(shell.Solids()) != 1 or shell.Volume() <= 0.0:
        raise ValueError(
            "A07 constant-wall stage did not resolve to one valid sleeve"
        )
    return shell


def _make_stages(state: str) -> tuple[cq.Shape, cq.Shape, cq.Shape]:
    sections = _stage_sections(state)
    ranges = _stage_z_ranges(state)
    stages: list[cq.Shape] = []
    for (outer_xy, inner_xy, radius), (zmin, zmax) in zip(sections, ranges):
        shape = _connected_stage_shell(
            outer_xy,
            inner_xy,
            zmax - zmin,
            (MAST_X, 0.0, (zmin + zmax) / 2.0),
            radius,
        )
        if state == "follow":
            shape = _rotate_follow(shape)
        stages.append(shape)
    return stages[0], stages[1], stages[2]


def _stage_metadata(state: str, index: int) -> dict[str, object]:
    focus = state == "focus"
    absolute_focus_travel = 140.0 * index
    if index == 1:
        parent = "A07_mast_fixed_outer_sleeve"
        overlap = 50.0 if focus else 163.0
    elif index == 2:
        parent = "A07_mast_moving_inner_sleeve"
        overlap = 20.0 if focus else 160.0
    else:
        parent = "A07_mast_moving_inner_sleeve_stage_2"
        overlap = 21.0 if focus else 160.0
    return {
        "v8_mast_interface_revision": "A07-three-independent-dry-stages",
        "telescopic_stage_count": 3,
        "telescopic_stage_index": index,
        "telescopic_parent": parent,
        "independent_serviceable_solid": True,
        "dry_running_interface": True,
        "nominal_dry_running_clearance_per_side_mm": 3.0,
        "minimum_required_dry_running_clearance_per_side_mm": 3.0,
        "overlap_with_parent_in_current_pose_mm": overlap,
        "minimum_extended_overlap_mm": 50.0 if index == 1 else (20.0 if index == 2 else 21.0),
        "positive_stop": {
            "type": "paired_internal_captured_shoulder",
            "service_access": "rear_authorised_A07_split",
            "stop_is_cosmetically_hidden": True,
        },
        "anti_rotation": "internal_dry_guide_key_not_exterior_skin",
        "incremental_focus_extension_mm": 140.0,
        "absolute_focus_translation_mm": absolute_focus_travel if focus else 0.0,
        "controlled_terminal_stroke_mm": MAST_STROKE_MM,
        "terminal_stroke_sum_semantics": "140 + 140 + 140 = 420 mm",
        "pose": "folded" if state == "follow" else ("raised_420" if focus else "low_nested"),
        "nested_without_interpenetration_in_low_state": not focus,
        "moves_with": "sensor_beam" if index == 3 else f"mast_stage_{index}",
        "certification_claimed": False,
    }


def _replace_stages(
    state: str,
    parts: list[SkinPart],
    original_stage: SkinPart,
) -> tuple[SkinPart, SkinPart, SkinPart]:
    shapes = _make_stages(state)
    names = (
        "A07_mast_moving_inner_sleeve",
        "A07_mast_moving_inner_sleeve_stage_2",
        "A07_mast_moving_inner_sleeve_stage_3",
    )
    intents = (
        "A broad root stage emerges from the fixed dorsal spine and carries the first captured dry-running telescope joint.",
        "The independent middle shroud narrows the side silhouette while retaining a captured overlap and positive stop.",
        "The independent terminal shroud forms the narrowest stage and enters the sensor-head socket without sharing solid volume.",
    )
    stage_parts: list[SkinPart] = []
    for index, (name, shape, intent) in enumerate(
        zip(names, shapes, intents),
        start=1,
    ):
        metadata = dict(original_stage.metadata)
        metadata.update(_stage_metadata(state, index))
        metadata["physical_occurrence_id"] = (
            original_stage.metadata.get("physical_occurrence_id", "E6-A07-MAST-MOVING-SLEEVE")
            if index == 1
            else f"E6-A07-MAST-MOVING-SLEEVE-STAGE-{index}"
        )
        stage_parts.append(
            replace(
                original_stage,
                name=name,
                shape=shape,
                intent=intent,
                metadata=metadata,
            )
        )

    stage_1_index = _part_index(parts, original_stage.name)
    parts[stage_1_index] = stage_parts[0]
    for extra in stage_parts[1:]:
        if any(part.name == extra.name for part in parts):
            raise ValueError(f"V8 A07 stage already exists: {extra.name}")
        parts.append(extra)
    return stage_parts[0], stage_parts[1], stage_parts[2]


def _cut_terminal_socket(
    state: str,
    beam: SkinPart,
) -> SkinPart:
    beam_z = BEAM_LOW_Z + (MAST_STROKE_MM if state == "focus" else 0.0)
    # This explicit cut overlaps the V7 keel relief and makes the terminal
    # insertion interface auditable as geometry.  In occupied states the
    # 64 x 130 mm stage-3 exterior sits in a 70 x 136 mm socket: 3 mm/side.
    socket = rounded_rect_prism(
        (70.0, 136.0),
        70.0,
        (MAST_X, 0.0, beam_z - 30.0),
        25.0,
    )
    if state == "follow":
        socket = _rotate_follow(socket)
    corrected = beam.shape.cut(socket)
    if not corrected.isValid() or len(corrected.Solids()) != 1:
        raise ValueError(f"V8 {state} A07 sensor-head socket cut is invalid")
    metadata = dict(beam.metadata)
    metadata.update(
        {
            "terminal_interface": "static_keyed_insertion_socket",
            "terminal_interface_is_sliding": False,
            "terminal_socket_section_mm": (70.0, 136.0),
            "terminal_stage_section_mm": (42.0, 106.0) if state == "follow" else (64.0, 130.0),
            "nominal_terminal_socket_clearance_per_side_mm": (
                (14.0, 15.0) if state == "follow" else (3.0, 3.0)
            ),
            "minimum_static_interface_clearance_required_mm": 0.5,
            "socket_is_real_subtractive_geometry": True,
            "retention": "hidden keyed collar and captured fastener; engineering release pending",
            "certification_claimed": False,
        }
    )
    return replace(
        beam,
        shape=corrected,
        intent=(
            "The crowned sensor terminal receives the independent third mast stage in a real keyed socket; "
            "the two service parts have no shared solid volume."
        ),
        metadata=metadata,
    )


def _separate_focus_privacy_window(
    state: str,
    parts: list[SkinPart],
) -> tuple[SkinPart | None, SkinPart | None]:
    if state != "focus":
        return None, None

    shutter_index = _part_index(parts, "A07_physical_privacy_shutter")
    window_index = _part_index(parts, "A07_sensor_beam_smoked_window")
    shutter = parts[shutter_index]
    window = parts[window_index]

    # The controlled Focus shutter remains byte-for-byte the same OCC shape.
    # Moving the optical cover +3 mm along its +X surface normal preserves its
    # full 280 x 40 mm YZ aperture and produces a 1.5 mm physical air gap from
    # the shutter's Xmax=266.5 face to the window's Xmin=268.0 face.
    separated_shape = window.shape.translate((3.0, 0.0, 0.0))
    metadata = dict(window.metadata)
    metadata.update(
        {
            "v8_privacy_separation_revision": "normal-offset-smoked-window",
            "surface_normal": "+X",
            "normal_offset_from_v7_mm": 3.0,
            "minimum_normal_clearance_to_physical_shutter_mm": 1.5,
            "projected_optical_aperture_yz_unchanged": True,
            "optical_channel": "full 280 x 40 mm projected smoked horizon remains unobstructed",
            "controlled_focus_shutter_geometry_modified": False,
            "certification_claimed": False,
        }
    )
    separated_window = replace(
        window,
        shape=separated_shape,
        intent=(
            "The smoked optical cover keeps its complete projected aperture but is offset along +X so the exact controlled Focus shutter remains a separate physical solid."
        ),
        metadata=metadata,
    )
    parts[window_index] = separated_window
    # Deliberately do not replace or transform ``shutter``.
    return shutter, separated_window


def _validate_mast_fix(
    state: str,
    parts: list[SkinPart],
    original_stage_shape: cq.Shape,
    original_shutter_shape: cq.Shape | None,
) -> None:
    errors = validate_parts(parts)
    if errors:
        raise ValueError(
            f"V8 {state} post-fix shape validation failed: " + "; ".join(errors)
        )

    stage_parts = [
        parts[_part_index(parts, "A07_mast_moving_inner_sleeve")],
        parts[_part_index(parts, "A07_mast_moving_inner_sleeve_stage_2")],
        parts[_part_index(parts, "A07_mast_moving_inner_sleeve_stage_3")],
    ]
    beam = parts[_part_index(parts, "A07_sensor_beam_shell")]
    fixed = parts[_part_index(parts, "A07_mast_fixed_outer_sleeve")]

    for stage in stage_parts:
        if not _bounds_within(stage.shape, original_stage_shape):
            raise ValueError(
                f"V8 {state} {stage.name} exceeds the original moving-mast safety AABB"
            )

    pair_specs = ((0, 1), (1, 2))
    for parent_i, child_i in pair_specs:
        parent = stage_parts[parent_i]
        child = stage_parts[child_i]
        common = _intersection_volume(parent.shape, child.shape)
        clearance = _distance(parent.shape, child.shape)
        if common > VOLUME_TOL_MM3 or clearance < 3.0 - GEOMETRY_TOL_MM:
            raise ValueError(
                f"V8 {state} dry stage interface {parent.name}/{child.name} "
                f"failed: common={common:.9f} mm^3, clearance={clearance:.6f} mm"
            )

    fixed_common = _intersection_volume(fixed.shape, stage_parts[0].shape)
    fixed_clearance = _distance(fixed.shape, stage_parts[0].shape)
    if fixed_common > VOLUME_TOL_MM3 or fixed_clearance < 3.0 - GEOMETRY_TOL_MM:
        raise ValueError(
            f"V8 {state} fixed/stage-1 dry interface failed: "
            f"common={fixed_common:.9f} mm^3, clearance={fixed_clearance:.6f} mm"
        )

    for stage in stage_parts:
        common = _intersection_volume(beam.shape, stage.shape)
        if common > VOLUME_TOL_MM3:
            raise ValueError(
                f"V8 {state} sensor beam intersects {stage.name}: "
                f"common={common:.9f} mm^3"
            )
    terminal_clearance = _distance(beam.shape, stage_parts[2].shape)
    if terminal_clearance < 0.5 - GEOMETRY_TOL_MM:
        raise ValueError(
            f"V8 {state} static terminal insertion clearance is only "
            f"{terminal_clearance:.6f} mm"
        )

    if state == "focus":
        shutter = parts[_part_index(parts, "A07_physical_privacy_shutter")]
        window = parts[_part_index(parts, "A07_sensor_beam_smoked_window")]
        if shutter.shape is not original_shutter_shape:
            raise ValueError("V8 Focus controlled privacy-shutter shape was replaced")
        common = _intersection_volume(shutter.shape, window.shape)
        clearance = _distance(shutter.shape, window.shape)
        if common > VOLUME_TOL_MM3 or clearance < 1.5 - GEOMETRY_TOL_MM:
            raise ValueError(
                "V8 Focus shutter/window separation failed: "
                f"common={common:.9f} mm^3, clearance={clearance:.6f} mm"
            )


def apply_v8_mast_fixes(
    state: str,
    parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Apply and self-validate the V8 A07 corrections for one physical state.

    The function is pure with respect to its input iterable and the filesystem:
    it returns a new list of immutable ``SkinPart`` records and writes nothing.
    """

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 mast state {state!r}")
    corrected = list(parts)

    original_stage_index = _part_index(
        corrected,
        "A07_mast_moving_inner_sleeve",
    )
    original_stage = corrected[original_stage_index]
    original_stage_shape = original_stage.shape
    original_shutter_shape: cq.Shape | None = None
    if state == "focus":
        original_shutter_shape = corrected[
            _part_index(corrected, "A07_physical_privacy_shutter")
        ].shape

    _replace_stages(state, corrected, original_stage)

    beam_index = _part_index(corrected, "A07_sensor_beam_shell")
    corrected[beam_index] = _cut_terminal_socket(state, corrected[beam_index])

    _separate_focus_privacy_window(state, corrected)
    _validate_mast_fix(
        state,
        corrected,
        original_stage_shape,
        original_shutter_shape,
    )
    return corrected


def _run_four_state_self_test() -> None:
    """Build the complete four-state V8 skin and exercise every local gate."""

    try:
        from .skin_lower import build_lower_skin
        from .skin_upper import build_upper_skin
        from .skin_v8_refinement import refine_v8_parts
    except ImportError:
        from skin_lower import build_lower_skin  # type: ignore[no-redef]
        from skin_upper import build_upper_skin  # type: ignore[no-redef]
        from skin_v8_refinement import refine_v8_parts  # type: ignore[no-redef]

    for state in ("follow", "ride", "cafe", "focus"):
        base = refine_v8_parts(
            state,
            build_lower_skin(state) + build_upper_skin(state),
        )
        corrected = apply_v8_mast_fixes(state, base)
        stage_1 = corrected[_part_index(corrected, "A07_mast_moving_inner_sleeve")]
        stage_2 = corrected[_part_index(corrected, "A07_mast_moving_inner_sleeve_stage_2")]
        stage_3 = corrected[_part_index(corrected, "A07_mast_moving_inner_sleeve_stage_3")]
        beam = corrected[_part_index(corrected, "A07_sensor_beam_shell")]
        print(
            f"PASS {state}: parts={len(corrected)}, "
            f"stage12={_distance(stage_1.shape, stage_2.shape):.3f} mm, "
            f"stage23={_distance(stage_2.shape, stage_3.shape):.3f} mm, "
            f"terminal={_distance(stage_3.shape, beam.shape):.3f} mm"
        )


if __name__ == "__main__":
    _run_four_state_self_test()


__all__ = ["apply_v8_mast_fixes"]
