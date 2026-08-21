"""Final rigid-volume partitions for the V8 A08/A09 deployable surfaces.

The earlier mechanism pass established functional envelopes and real staged
parts.  This pass removes the remaining modelling-shortcut common volumes at
trim interfaces.  It does not alter controlled E6-DFR5-A07-SHARED-HINGE
primary geometry or preserved DFR4/DFR3 trace geometry, and it does not
use collision allowlists: visible inserts retain their volume while their
host/under-structure receives an exact B-Rep seat.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Sequence

import cadquery as cq

try:
    from .skin_common import SkinPart
except ImportError:
    from skin_common import SkinPart  # type: ignore[no-redef]

try:
    from .v8_state_contract import default_footrest_is_deployed
except ImportError:
    from v8_state_contract import default_footrest_is_deployed  # type: ignore[no-redef]


STATES = {"follow", "ride", "cafe", "focus"}


def _matching(parts: Sequence[SkinPart], stem: str) -> list[SkinPart]:
    return [
        part
        for part in parts
        if part.name == stem or part.name.startswith(f"{stem}_service_segment_")
    ]


def _common_volume(left: cq.Shape, right: cq.Shape) -> float:
    try:
        common = left.intersect(right)
        return 0.0 if common.isNull() else max(0.0, float(common.Volume()))
    except Exception:
        return 0.0


def _cut_shape(base: cq.Shape, cutters: Iterable[cq.Shape]) -> tuple[cq.Shape, float]:
    result = base
    removed = 0.0
    for cutter in cutters:
        common = _common_volume(result, cutter)
        if common <= 0.1:
            continue
        candidate = result.cut(cutter)
        if candidate.isNull() or not candidate.isValid() or candidate.Volume() <= 0.1:
            raise ValueError(
                f"V8 deployable partition consumed/invalidated a part after "
                f"{common:.6f} mm3 common volume"
            )
        result = candidate
        removed += common
    return result, removed


def _cut_stem(
    parts: list[SkinPart],
    target_stem: str,
    cutter_stems: Sequence[str],
    *,
    interface: str,
) -> None:
    cutters = [
        part.shape
        for stem in cutter_stems
        for part in _matching(parts, stem)
    ]
    if not cutters:
        return
    for index, part in enumerate(parts):
        if part.name != target_stem and not part.name.startswith(
            f"{target_stem}_service_segment_"
        ):
            continue
        shape, removed = _cut_shape(part.shape, cutters)
        if removed <= 0.1:
            continue
        metadata = {
            **part.metadata,
            "v8_rigid_partition": True,
            "v8_partition_interface": interface,
            "v8_partition_removed_common_volume_mm3": round(removed, 6),
            "rigid_pair_common_volume_target_mm3": 0.0,
        }
        parts[index] = replace(part, shape=shape, metadata=metadata)


def _partition_a08(parts: list[SkinPart]) -> None:
    # The tread and perimeter/top skins are the visible datum.  The boots and
    # root cowls terminate beneath them instead of occupying their material.
    visible_surfaces = (
        "A08_footrest_top_skin",
        "A08_footrest_inset_tread",
        "A08_footrest_perimeter_skin",
    )
    for side in ("left", "right"):
        _cut_stem(
            parts,
            f"A08_footrest_support_boot_{side}",
            visible_surfaces,
            interface=f"A08-{side}-boot-to-visible-footrest-seat",
        )
        _cut_stem(
            parts,
            f"A08_footrest_root_cowl_{side}",
            visible_surfaces,
            interface=f"A08-{side}-root-cowl-to-visible-footrest-seat",
        )

    # The manual latch remains a proud, replaceable physical control.  Its two
    # cosmetic hosts receive the real aperture; the safety control is not
    # thinned merely to make a collision report pass.
    for host in ("A08_footrest_top_skin", "A08_footrest_perimeter_skin"):
        _cut_stem(
            parts,
            host,
            ("A08_manual_release_paddle_shell",),
            interface="A08-manual-release-real-seat",
        )


def _partition_a09(state: str, parts: list[SkinPart]) -> None:
    if state == "focus":
        # The final Focus root has no exterior saddle, bridge or fairing to
        # partition.  Its compact guide stages are independently modelled
        # inside A05 and the leaf-attached tongue crosses only the already-cut
        # inner-wall port.  Preserve the real centre-seam seal groove, which is
        # unrelated to the concealed root mechanism.
        for side in ("left", "right"):
            _cut_stem(
                parts,
                f"A09_table_edge_band_{side}_fold_half_inner",
                (f"A09_focus_centre_seam_seal_{side}",),
                interface=f"A09-focus-{side}-centre-seal-groove",
            )
        return
    if state == "cafe":
        # Cafe now enters this pass with only the in-cavity lift boot and fixed
        # internal controls.  The exact fixed-yoke/rotary-rail root is installed
        # downstream from ``v8_cafe_table_root_motion``; the former exposed
        # saddle/bridge/fairing and moving post stages are deliberately absent.
        # There is consequently no rigid exterior interface to partition here.
        return
    else:
        return

    for side in sides:
        underbelly = f"A09_table_underbelly_shell_{side}"
        # The support saddle ends at the underside skin rather than being
        # buried through it.
        _cut_stem(
            parts,
            saddle[side],
            (underbelly,),
            interface=f"A09-{state}-{side}-saddle-underbelly-seat",
        )
        # The innermost telescopic member enters a real pocket in the
        # underbelly.  This keeps all three stages independent and serviceable.
        _cut_stem(
            parts,
            underbelly,
            (f"A09_table_lift_moving_stage_3_{side}",),
            interface=f"A09-{state}-{side}-stage3-underbelly-pocket",
        )
        # Earlier z-region partitioning left a narrow residual at the bridge /
        # fairing boundary.  The fairing is the replaceable cover, so it
        # receives the exact bridge boundary and no hidden rigid overlap.
        _cut_stem(
            parts,
            fairing[side],
            (bridge[side],),
            interface=f"A09-{state}-{side}-bridge-fairing-service-seam",
        )

def _explode(parts: Sequence[SkinPart]) -> list[SkinPart]:
    """Return one valid solid per SkinPart after the new service cuts."""

    result: list[SkinPart] = []
    used_names: set[str] = set()
    for part in parts:
        solids = sorted(part.shape.Solids(), key=lambda solid: solid.Volume(), reverse=True)
        if not solids:
            raise ValueError(f"V8 deployable partition left {part.name} without a solid")
        group = str(
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
                suffix = segment_index
                name = f"{part.name}_v8_partition_segment_{suffix}"
                while name in used_names:
                    suffix += 1
                    name = f"{part.name}_v8_partition_segment_{suffix}"
            if name in used_names:
                raise ValueError(f"duplicate V8 deployable segment name {name}")
            used_names.add(name)
            metadata = {
                **part.metadata,
                "service_segment_group_id": group,
                "service_segment_index": segment_index,
                "service_segment_count": len(solids),
                "physical_occurrence_id": (
                    str(part.metadata.get("physical_occurrence_id", group))
                    if segment_index == 1
                    else f"{group}-V8-PART-{segment_index}"
                ),
            }
            result.append(
                replace(
                    part,
                    name=name,
                    shape=solid,
                    intent=(
                        part.intent
                        if segment_index == 1
                        else f"Service-split continuation of {part.name} after a real rigid-interface seat."
                    ),
                    metadata=metadata,
                )
            )
    return result


def apply_v8_deployable_rigid_partitions(
    state: str,
    base_parts: Iterable[SkinPart],
) -> list[SkinPart]:
    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"unsupported V8 state {state!r}")
    parts = list(base_parts)
    if default_footrest_is_deployed(state):
        _partition_a08(parts)
    _partition_a09(state, parts)
    return _explode(parts)


__all__ = ["apply_v8_deployable_rigid_partitions"]
