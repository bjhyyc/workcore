"""Rigid B-Rep partitions for the V8 A06/A07 exterior group.

The earlier appearance builders intentionally overlap several cosmetic proxy
solids.  This post-process converts those overlaps into real subtractive seats
while preserving every named physical occurrence.  It is designed to run
after ``apply_v8_collision_partitions``; controlled STEP files are never read,
written or modified here.

No collision is allowlisted.  A result containing a null part, an invalid
part, more than one solid per ``SkinPart`` or an A06/A07 hard common volume is
rejected immediately.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from typing import Iterable, Sequence

import cadquery as cq

try:
    from .skin_common import SkinPart, validate_parts
except ImportError:
    from skin_common import SkinPart, validate_parts  # type: ignore[no-redef]


STATES = {"follow", "ride", "cafe", "focus"}
HARD_COMMON_MM3 = 0.1
NUMERICAL_COMMON_MM3 = 1.0e-6


def _is_target(part: SkinPart) -> bool:
    return part.module in {"A06", "A07"} or part.name.startswith(("A06_", "A07_"))


def _index(parts: Sequence[SkinPart], name: str) -> int:
    matches = [index for index, part in enumerate(parts) if part.name == name]
    if len(matches) != 1:
        raise KeyError(f"V8 rigid mast partition requires one {name!r}; found {len(matches)}")
    return matches[0]


def _get(parts: Sequence[SkinPart], name: str) -> SkinPart:
    return parts[_index(parts, name)]


def _named(parts: Sequence[SkinPart], prefix: str) -> list[SkinPart]:
    return [part for part in parts if part.name.startswith(prefix)]


def _bbox_overlaps(shape_a: cq.Shape, shape_b: cq.Shape) -> bool:
    a = shape_a.BoundingBox()
    b = shape_b.BoundingBox()
    return (
        min(a.xmax, b.xmax) > max(a.xmin, b.xmin)
        and min(a.ymax, b.ymax) > max(a.ymin, b.ymin)
        and min(a.zmax, b.zmax) > max(a.zmin, b.zmin)
    )


def _common_volume(shape_a: cq.Shape, shape_b: cq.Shape) -> float:
    if not _bbox_overlaps(shape_a, shape_b):
        return 0.0
    common = shape_a.intersect(shape_b)
    if common.isNull():
        return 0.0
    return max(0.0, float(common.Volume()))


def _require_shape(shape: cq.Shape, label: str) -> None:
    if shape.isNull() or not shape.isValid() or shape.Volume() <= HARD_COMMON_MM3:
        raise ValueError(f"{label} became null, invalid or non-volumetric")


def _replace_shape(
    parts: list[SkinPart],
    name: str,
    shape: cq.Shape,
    *,
    role: str,
    cutters: Sequence[str],
) -> None:
    _require_shape(shape, name)
    index = _index(parts, name)
    previous = parts[index]
    metadata = dict(previous.metadata)
    history = list(metadata.get("rigid_partition_history", ()))
    history.append(
        {
            "role": role,
            "operation": "BRep_subtract",
            "cutters": list(cutters),
            "common_volume_target_mm3": 0.0,
        }
    )
    metadata.update(
        {
            "rigid_partitioned": True,
            "rigid_partition_role": role,
            "rigid_partition_history": history,
            "rigid_pair_common_volume_target_mm3": 0.0,
            "allowlisted_collision": False,
            "certification_claimed": False,
        }
    )
    parts[index] = replace(previous, shape=shape, metadata=metadata)


def _subtract_named(
    parts: list[SkinPart],
    host_name: str,
    cutter_names: Iterable[str],
    *,
    role: str,
) -> None:
    host = _get(parts, host_name)
    result = host.shape
    applied: list[str] = []
    for cutter_name in dict.fromkeys(cutter_names):
        if cutter_name == host_name:
            continue
        cutter = _get(parts, cutter_name)
        common = _common_volume(result, cutter.shape)
        if common <= NUMERICAL_COMMON_MM3:
            continue
        candidate = result.cut(cutter.shape)
        _require_shape(candidate, f"{host_name} after {cutter_name}")
        result = candidate
        applied.append(cutter_name)
    if applied:
        _replace_shape(parts, host_name, result, role=role, cutters=applied)


def _aperture_parts(parts: Sequence[SkinPart]) -> list[SkinPart]:
    tokens = (
        "smoked_window",
        "fill_light_visible_window",
        "confirmation_lens",
        "acoustic_mesh",
        "environment_sensor_grille",
        "physical_privacy_shutter",
    )
    return [
        part
        for part in parts
        if part.name.startswith("A07_") and any(token in part.name for token in tokens)
    ]


def _partition_back_weather_shell(parts: list[SkinPart]) -> None:
    # The A06 weather skin is the receiving host.  Every A07 structural member,
    # window and service insert receives a literal seat through it.  The old
    # Follow vault is excluded here because that duplicate cover yields later.
    cutters = [
        part.name
        for part in parts
        if part.name.startswith("A07_")
        and not part.name.startswith("A07_follow_observation_spine_weather_vault")
    ]
    _subtract_named(
        parts,
        "A06_backrest_weather_shell",
        cutters,
        role="A06 host shell with real A07 mast/accessory seats",
    )


def _partition_beam(parts: list[SkinPart]) -> None:
    # The sensor terminal remains the visible host.  The fixed spine, all three
    # stage service walls and every lens/mesh/grille cut actual material from
    # the beam rather than occupying the same B-Rep volume.
    cutters = ["A07_mast_fixed_outer_sleeve"]
    cutters.extend(
        part.name
        for part in parts
        if part.name.startswith("A07_mast_moving_inner_sleeve")
    )
    cutters.extend(part.name for part in _aperture_parts(parts))
    _subtract_named(
        parts,
        "A07_sensor_beam_shell",
        cutters,
        role="sensor-head host with subtractive mast socket and accessory seats",
    )


def _partition_optical_stack(state: str, parts: list[SkinPart]) -> None:
    shutter_name = "A07_physical_privacy_shutter"
    fill_names = [
        part.name
        for part in parts
        if part.name.startswith("A07_fill_light_visible_window_")
    ]
    _subtract_named(
        parts,
        "A07_sensor_beam_smoked_window",
        (shutter_name, *fill_names),
        role="smoked optical cover partitioned around shutter and task-light inserts",
    )
    for fill_name in fill_names:
        _subtract_named(
            parts,
            fill_name,
            (shutter_name,),
            role="task-light insert partitioned around exact physical shutter",
        )

    if state != "focus":
        return
    pocket_name = "A07_privacy_shutter_parked_pocket"
    pocket_cutters = [
        "A07_sensor_beam_shell",
        "A07_sensor_beam_smoked_window",
        shutter_name,
        "A07_microphone_acoustic_mesh",
        "A07_environment_sensor_grille",
        *fill_names,
    ]
    _subtract_named(
        parts,
        pocket_name,
        pocket_cutters,
        role="parked-shutter fairing partitioned from beam, optics and acoustic insert",
    )


def _partition_follow(parts: list[SkinPart]) -> None:
    # Follow has no state-only A06 field shell and no A07 vault.  The same
    # trapezoidal backrest and canonical A07 package have already received
    # their real mutual seats above and co-fold as one moving family.
    return


def _yield_rank(part: SkinPart) -> int:
    """Lower ranks yield first; protected physical inserts rank highest."""

    name = part.name
    if name.startswith("A07_follow_observation_spine_weather_vault"):
        return 0
    if name == "A06_backrest_weather_shell":
        return 10
    if name == "A06_follow_closed_field_shell":
        return 12
    if name == "A07_privacy_shutter_parked_pocket":
        return 15
    if name == "A07_sensor_beam_shell":
        return 20
    if name == "A07_sensor_beam_smoked_window":
        return 25
    if name.startswith("A07_fill_light_visible_window_"):
        return 30
    if name == "A07_mast_fixed_outer_sleeve":
        return 45
    if name.startswith("A07_mast_moving_inner_sleeve"):
        return 55
    if name == "A07_physical_privacy_shutter":
        return 1000
    if any(token in name for token in ("lens", "mesh", "grille")):
        return 900
    return 60


def _remaining_target_pairs(parts: Sequence[SkinPart]) -> list[tuple[float, str, str]]:
    collisions: list[tuple[float, str, str]] = []
    targets = [part for part in parts if _is_target(part)]
    for left, right in combinations(targets, 2):
        common = _common_volume(left.shape, right.shape)
        if common > HARD_COMMON_MM3:
            collisions.append((common, left.name, right.name))
    return collisions


def _resolve_remaining_target_pairs(parts: list[SkinPart]) -> None:
    # Specific hierarchy above carries the design intent.  This bounded second
    # pass catches service-segment pairs created upstream without hiding them in
    # an allowlist.  Subtraction is monotonic, so four passes are conservative.
    for _pass in range(4):
        collisions = _remaining_target_pairs(parts)
        if not collisions:
            return
        changed = False
        for _common, left_name, right_name in collisions:
            left = _get(parts, left_name)
            right = _get(parts, right_name)
            if _common_volume(left.shape, right.shape) <= HARD_COMMON_MM3:
                continue
            loser, winner = (
                (left, right)
                if _yield_rank(left) <= _yield_rank(right)
                else (right, left)
            )
            candidate = loser.shape.cut(winner.shape)
            if candidate.isNull() or not candidate.isValid() or candidate.Volume() <= HARD_COMMON_MM3:
                # Preserve both occurrences: if the preferred yielding proxy is
                # wholly consumed, partition the other proxy instead.
                loser, winner = winner, loser
                candidate = loser.shape.cut(winner.shape)
            _require_shape(candidate, f"remaining pair {loser.name}/{winner.name}")
            _replace_shape(
                parts,
                loser.name,
                candidate,
                role="residual A06/A07 rigid master partition",
                cutters=(winner.name,),
            )
            changed = True
        if not changed:
            break
    remaining = _remaining_target_pairs(parts)
    if remaining:
        detail = "; ".join(
            f"{a}/{b}={volume:.6f} mm3" for volume, a, b in remaining
        )
        raise ValueError(f"A06/A07 hard common volume remains: {detail}")


def _explode_service_segments(parts: Sequence[SkinPart]) -> list[SkinPart]:
    result: list[SkinPart] = []
    used_names = {part.name for part in parts}
    for part in parts:
        solids = sorted(part.shape.Solids(), key=lambda solid: solid.Volume(), reverse=True)
        if not solids:
            raise ValueError(f"{part.name} contains no solid")
        if len(solids) == 1:
            result.append(replace(part, shape=solids[0]))
            continue
        group_id = str(
            part.metadata.get(
                "service_segment_group_id",
                part.metadata.get(
                    "physical_occurrence_id",
                    f"{part.configuration.upper()}-{part.name}",
                ),
            )
        )
        for segment_index, solid in enumerate(solids, start=1):
            if segment_index == 1:
                name = part.name
            else:
                stem = f"{part.name}_rigid_service_segment_{segment_index}"
                name = stem
                suffix = 2
                while name in used_names:
                    name = f"{stem}_{suffix}"
                    suffix += 1
                used_names.add(name)
            metadata = {
                **part.metadata,
                "service_segment_group_id": group_id,
                "service_segment_index": segment_index,
                "service_segment_count": len(solids),
                "physical_occurrence_id": (
                    part.metadata.get("physical_occurrence_id", group_id)
                    if segment_index == 1
                    else f"{group_id}-RIGID-SEG-{segment_index}"
                ),
                "one_skinpart_one_solid": True,
            }
            result.append(
                replace(
                    part,
                    name=name,
                    shape=solid,
                    intent=(
                        part.intent
                        if segment_index == 1
                        else f"Service segment {segment_index}/{len(solids)} of {part.name}; the intervening volume is a real rigid partition."
                    ),
                    metadata=metadata,
                )
            )
    return result


def _validate_result(parts: Sequence[SkinPart], state: str) -> None:
    errors = validate_parts(parts)
    if errors:
        raise ValueError(f"V8 {state} mast partition validation failed: {'; '.join(errors)}")
    multi = [part.name for part in parts if len(part.shape.Solids()) != 1]
    if multi:
        raise ValueError(f"V8 {state} multi-solid SkinPart records remain: {multi}")
    remaining = _remaining_target_pairs(parts)
    if remaining:
        detail = "; ".join(
            f"{a}/{b}={volume:.6f}" for volume, a, b in remaining
        )
        raise ValueError(f"V8 {state} A06/A07 rigid collision gate failed: {detail}")


def apply_v8_mast_rigid_partitions(
    state: str,
    parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Return one-solid service parts with zero A06/A07 hard common volume."""

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 rigid mast state {state!r}")
    result = list(parts)
    _partition_back_weather_shell(result)
    _partition_beam(result)
    _partition_optical_stack(state, result)
    if state == "follow":
        _partition_follow(result)
    _resolve_remaining_target_pairs(result)
    result = _explode_service_segments(result)
    _validate_result(result, state)
    return result


__all__ = ["apply_v8_mast_rigid_partitions"]
