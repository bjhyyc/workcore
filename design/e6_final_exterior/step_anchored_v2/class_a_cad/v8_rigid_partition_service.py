"""V8 rigid insert seats and service-boundary partitions.

This pass is intentionally downstream of ``v8_collision_partition``.  It does
not suppress any collision pair and does not delete a physical occurrence.
Instead, functional inserts keep their released geometry while the adjacent
rigid host receives a real Boolean seat, aperture, or service partition.

Only pairs involving A01, A03, A04, A05 or A10 and their immediately adjacent
rigid covers are touched.  Any Boolean that creates independent cover pieces is
expanded with the existing ``service_segment`` identity convention so every
returned :class:`SkinPart` contains exactly one solid.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Sequence

import cadquery as cq

try:
    from .skin_common import SkinPart, rounded_box
except ImportError:
    from skin_common import SkinPart, rounded_box  # type: ignore[no-redef]


STATES = {"follow", "ride", "cafe", "focus"}
_HARD_INTERFERENCE_MM3 = 0.1


def _index(parts: Sequence[SkinPart]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, part in enumerate(parts):
        if part.name in result:
            raise ValueError(f"duplicate rigid-part name {part.name!r}")
        result[part.name] = index
    return result


def _required(parts: Sequence[SkinPart], name: str) -> SkinPart:
    try:
        return parts[_index(parts)[name]]
    except KeyError as exc:
        raise KeyError(f"V8 rigid partition missing required part {name!r}") from exc


def _named(parts: Sequence[SkinPart], prefix: str) -> list[SkinPart]:
    return [part for part in parts if part.name.startswith(prefix)]


def _valid_positive(shape: cq.Shape, label: str) -> None:
    if shape.isNull() or not shape.isValid() or shape.Volume() <= 0.0:
        raise ValueError(f"{label} is null, invalid, or non-positive after partition")
    if not shape.Solids():
        raise ValueError(f"{label} contains no solid after partition")


def _common_volume(first: cq.Shape, second: cq.Shape) -> float:
    a = first.BoundingBox()
    b = second.BoundingBox()
    if any(
        min(getattr(a, f"{axis}max"), getattr(b, f"{axis}max"))
        <= max(getattr(a, f"{axis}min"), getattr(b, f"{axis}min"))
        for axis in ("x", "y", "z")
    ):
        return 0.0
    return float(first.intersect(second).Volume())


def _clearance_box(shape: cq.Shape, margin: float) -> cq.Shape:
    """Manufacturable seat envelope around a compact insert."""

    box = shape.BoundingBox()
    return rounded_box(
        (
            box.xlen + 2.0 * margin,
            box.ylen + 2.0 * margin,
            box.zlen + 2.0 * margin,
        ),
        (
            (box.xmin + box.xmax) / 2.0,
            (box.ymin + box.ymax) / 2.0,
            (box.zmin + box.zmax) / 2.0,
        ),
        min(4.0, max(0.25, margin)),
    )


def _replace_shape(
    parts: list[SkinPart],
    name: str,
    shape: cq.Shape,
    partition_kind: str,
) -> None:
    _valid_positive(shape, name)
    index = _index(parts)[name]
    previous = parts[index]
    metadata = dict(previous.metadata)
    history = list(metadata.get("rigid_partition_history", ()))
    if partition_kind not in history:
        history.append(partition_kind)
    metadata.update(
        {
            "rigid_partition_history": tuple(history),
            "rigid_pair_common_volume_target_mm3": 0.0,
            "physical_occurrence_conserved": True,
        }
    )
    parts[index] = replace(previous, shape=shape, metadata=metadata)


def _cut_host_by_shapes(
    parts: list[SkinPart],
    host_name: str,
    cutters: Iterable[cq.Shape],
    partition_kind: str,
) -> None:
    host = _required(parts, host_name)
    result = host.shape
    removed = False
    for cutter in cutters:
        common = _common_volume(result, cutter)
        if common <= _HARD_INTERFERENCE_MM3:
            continue
        candidate = result.cut(cutter)
        _valid_positive(candidate, f"{host_name}/{partition_kind}")
        residual = _common_volume(candidate, cutter)
        if residual > _HARD_INTERFERENCE_MM3:
            raise ValueError(
                f"{host_name} retains {residual:.6f} mm3 after {partition_kind}"
            )
        result = candidate
        removed = True
    if removed:
        _replace_shape(parts, host_name, result, partition_kind)


def _cut_host_by_parts(
    parts: list[SkinPart],
    host_name: str,
    cutters: Iterable[SkinPart],
    partition_kind: str,
    *,
    clearance_mm: float = 0.0,
) -> None:
    shapes = [
        _clearance_box(part.shape, clearance_mm)
        if clearance_mm > 0.0
        else part.shape
        for part in cutters
        if part.name != host_name
    ]
    _cut_host_by_shapes(parts, host_name, shapes, partition_kind)


def _side_parts(parts: Sequence[SkinPart], prefix: str, side: str) -> list[SkinPart]:
    return [
        part
        for part in parts
        if part.name.startswith(prefix) and side in part.name.lower()
    ]


def _partition_a01(parts: list[SkinPart]) -> None:
    """Seat the perception inserts and partition the adjacent A04 belly."""

    nose = _required(parts, "A01_front_nose_shell")
    carrier = _required(parts, "A01_perception_horizon_carrier")
    bumper = _required(parts, "A01_front_tactile_bumper_skin")
    mask = _required(parts, "A01_perception_horizon_smoked_mask")
    windows = [
        _required(parts, name)
        for name in (
            "A01_front_left_tof_window",
            "A01_front_right_tof_window",
            "A01_front_leg_scanner_window",
        )
    ]

    # Work from the original carrier envelope before opening its insert seats;
    # the nose therefore receives one continuous carrier aperture.
    _cut_host_by_parts(
        parts,
        nose.name,
        (carrier, bumper),
        "A01_nose_carrier_and_tactile_partition",
    )
    _cut_host_by_parts(
        parts,
        carrier.name,
        (mask, *windows),
        "A01_perception_insert_seats",
        clearance_mm=0.2,
    )

    belly = _required(parts, "A04_underseat_belly_closeout")
    _cut_host_by_parts(
        parts,
        belly.name,
        (carrier,),
        "A01_A04_front_carrier_partition",
    )

def _partition_a03(parts: list[SkinPart]) -> None:
    """Make each pivot service cap a real insert in its interspace bridge."""

    for side in ("left", "right"):
        cap = _required(parts, f"A03_rocker_pivot_service_cap_{side}")
        bridge = _required(parts, f"A03_wheel_interspace_bridge_{side}")
        _cut_host_by_parts(
            parts,
            bridge.name,
            (cap,),
            "A03_service_cap_counterbore",
            clearance_mm=0.25,
        )


def _partition_a04(parts: list[SkinPart], state: str) -> None:
    """Partition the seat ring, recovery grip and adjacent A05/A06 covers."""

    ring = _required(parts, "A04_open_u_seat_pan_ring")
    grip_shell = _required(parts, "A04_recovery_handle_grip_shell")
    grip_inlay = _required(parts, "A04_recovery_handle_grip_inlay")

    # The A06 covers are immediate cosmetic neighbours; they yield around the
    # load-path-honest recovery grip and the fixed seat-pan ring.
    if state == "follow":
        fields = _named(parts, "A06_follow_closed_field_shell")
        for field in fields:
            _cut_host_by_parts(
                parts,
                field.name,
                (ring, grip_shell, grip_inlay),
                "A04_A06_follow_field_partition",
            )
    else:
        for cheek in _named(parts, "A06_backrest_root_cheek_"):
            _cut_host_by_parts(
                parts,
                cheek.name,
                (grip_shell, grip_inlay),
                "A04_A06_recovery_grip_partition",
            )

    bay_shells = _named(parts, "A05_armrest_table_bay_shell_")
    transfer_fairings = _named(parts, "A05_right_transfer_root_fairing")
    _cut_host_by_parts(
        parts,
        ring.name,
        (*bay_shells, *transfer_fairings),
        "A04_ring_A05_bay_fairing_partition",
    )
    _cut_host_by_parts(
        parts,
        grip_shell.name,
        (grip_inlay,),
        "A04_recovery_grip_inlay_seat",
        clearance_mm=0.2,
    )


def _partition_follow_external_controls(parts: list[SkinPart], state: str) -> None:
    if state != "follow":
        return
    # Follow controls pierce the fixed left shell directly.  The removed side
    # cassette door is not a valid host because the table leaves now exit only
    # through the outward-flipping top lid.
    shell = _required(parts, "A05_armrest_table_bay_shell_left")
    controls = [
        _required(parts, name)
        for name in (
            "A05_follow_external_emergency_stop_guard",
            "A05_follow_external_mechanical_emergency_stop",
            "A05_follow_neutral_status_witness",
        )
    ]
    _cut_host_by_parts(
        parts,
        shell.name,
        controls,
        "A05_follow_external_control_real_apertures",
        clearance_mm=0.4,
    )


def _partition_a05_hmi(parts: list[SkinPart]) -> None:
    status = _named(parts, "A05_left_status_display_window")
    for bezel in _named(parts, "A05_left_hmi_precision_bezel"):
        _cut_host_by_parts(
            parts,
            bezel.name,
            status,
            "A05_HMI_window_insert_seat",
            clearance_mm=0.2,
        )

    for side in ("left", "right"):
        lids = _named(parts, f"A05_armrest_touch_lid_{side}")
        inserts = [
            *(_side_parts(parts, "A05_left_hmi_precision_bezel", side)),
            *(_side_parts(parts, "A05_left_status_display_window", side)),
            *(_side_parts(parts, "A05_left_qi_phone_cradle", side)),
        ]
        for lid in lids:
            _cut_host_by_parts(
                parts,
                lid.name,
                inserts,
                "A05_touch_lid_functional_insert_partition",
            )

    left_shells = _named(parts, "A05_armrest_table_bay_shell_left")
    estop_inserts = [
        *(_named(parts, "A05_left_emergency_stop_guard")),
        *(_named(parts, "A05_left_mechanical_emergency_stop")),
    ]
    for shell in left_shells:
        _cut_host_by_parts(
            parts,
            shell.name,
            estop_inserts,
            "A05_inner_wall_estop_mounting_aperture",
            clearance_mm=0.2,
        )


def _partition_a05_cassette_and_transfer(parts: list[SkinPart]) -> None:
    fairings = _named(parts, "A05_right_transfer_root_fairing")
    if fairings:
        bay = _required(parts, "A05_armrest_table_bay_shell_right")
        _cut_host_by_parts(
            parts,
            bay.name,
            fairings,
            "A05_transfer_fairing_bay_partition",
        )

    for side in ("left", "right"):
        drains = _named(parts, f"A05_table_cassette_lowpoint_drain_{side}")
        for shell in _named(parts, f"A05_armrest_table_bay_shell_{side}"):
            _cut_host_by_parts(
                parts,
                shell.name,
                drains,
                "A05_cassette_gravity_drain_partition",
                clearance_mm=0.2,
            )

    releases = _named(parts, "A05_right_transfer_manual_release")
    witnesses = _named(parts, "A05_right_transfer_positive_lock_witness")
    for release in releases:
        _cut_host_by_parts(
            parts,
            release.name,
            witnesses,
            "A05_transfer_release_witness_partition",
            clearance_mm=0.15,
        )


def _partition_a05(parts: list[SkinPart], state: str) -> None:
    _partition_follow_external_controls(parts, state)
    _partition_a05_hmi(parts)
    _partition_a05_cassette_and_transfer(parts)


def _partition_a10(parts: list[SkinPart]) -> None:
    surround = _required(parts, "A10_rear_service_surround")
    vent = _required(parts, "A10_pressure_relief_vent_bezel")
    status = _required(parts, "A10_rear_status_lens")
    _cut_host_by_parts(
        parts,
        surround.name,
        (vent, status),
        "A10_vent_and_status_service_seats",
        clearance_mm=0.2,
    )

    pull = _required(parts, "A10_rear_service_pull_cup")
    inlay = _required(parts, "A10_rear_service_pull_grip_inlay")
    _cut_host_by_parts(
        parts,
        pull.name,
        (inlay,),
        "A10_pull_grip_inlay_seat",
        clearance_mm=0.2,
    )


def _next_segment_identity(
    root_name: str,
    group_id: str,
    used_names: set[str],
    used_occurrences: set[str],
) -> tuple[str, str]:
    segment = 2
    while True:
        name = f"{root_name}_service_segment_{segment}"
        occurrence = f"{group_id}-SEG-{segment}"
        if name not in used_names and occurrence not in used_occurrences:
            used_names.add(name)
            used_occurrences.add(occurrence)
            return name, occurrence
        segment += 1


def _explode_service_segments(parts: list[SkinPart]) -> list[SkinPart]:
    """Apply the established one-SkinPart/one-solid service-segment rule."""

    used_names = {part.name for part in parts}
    used_occurrences = {
        str(part.metadata.get("physical_occurrence_id"))
        for part in parts
        if part.metadata.get("physical_occurrence_id")
    }
    expanded: list[SkinPart] = []
    for part in parts:
        solids = sorted(part.shape.Solids(), key=lambda solid: solid.Volume(), reverse=True)
        if not solids:
            raise ValueError(f"{part.name} has no solid before service segmentation")
        if len(solids) == 1:
            expanded.append(replace(part, shape=solids[0]))
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
        root_name = part.name.split("_service_segment_", 1)[0]
        first_metadata = {
            **part.metadata,
            "service_segment_group_id": group_id,
            "physical_occurrence_conserved": True,
        }
        expanded.append(replace(part, shape=solids[0], metadata=first_metadata))
        for solid in solids[1:]:
            name, occurrence = _next_segment_identity(
                root_name,
                group_id,
                used_names,
                used_occurrences,
            )
            expanded.append(
                replace(
                    part,
                    name=name,
                    shape=solid,
                    intent=(
                        f"Service-split continuation of {root_name}; no rigid bridge "
                        "crosses the functional seat or neighbouring cover."
                    ),
                    metadata={
                        **part.metadata,
                        "service_segment_group_id": group_id,
                        "physical_occurrence_id": occurrence,
                        "physical_occurrence_conserved": True,
                    },
                )
            )

    groups: dict[str, list[int]] = {}
    for index, part in enumerate(expanded):
        group = part.metadata.get("service_segment_group_id")
        if group is not None:
            groups.setdefault(str(group), []).append(index)
    for group_id, indices in groups.items():
        count = len(indices)
        for segment_index, index in enumerate(indices, start=1):
            part = expanded[index]
            expanded[index] = replace(
                part,
                metadata={
                    **part.metadata,
                    "service_segment_group_id": group_id,
                    "service_segment_index": segment_index,
                    "service_segment_count": count,
                },
            )

    seen: set[str] = set()
    for part in expanded:
        if part.name in seen:
            raise ValueError(f"service segmentation produced duplicate name {part.name!r}")
        seen.add(part.name)
        _valid_positive(part.shape, part.name)
        if len(part.shape.Solids()) != 1:
            raise ValueError(f"{part.name} still contains multiple solids")
    return expanded


def apply_v8_service_rigid_partitions(
    state: str,
    base_parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Return solid-partitioned A01/A03/A04/A05/A10 service geometry."""

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 state {state!r}; expected {sorted(STATES)}")
    parts = list(base_parts)
    _index(parts)
    _partition_a01(parts)
    _partition_a03(parts)
    _partition_a04(parts, state)
    _partition_a05(parts, state)
    _partition_a10(parts)
    return _explode_service_segments(parts)


__all__ = ["apply_v8_service_rigid_partitions"]
