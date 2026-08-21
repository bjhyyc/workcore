"""Cross-module rigid partitions for the V8 A01/A08 and A05/A09 interfaces.

This pass is deliberately independent from the release builder and controlled
STEP files.  It resolves only two interface families:

* A01 front nose/bumper versus A08 boot, collar, cowl and manual paddle;
* A05 bay/touch/HMI surfaces versus A09 lift boot, root fairing and bridge.

The visible A01 shell and touch-facing A05 surfaces retain precedence.  A08
and A09 inner covers normally receive exact subtractive seats.  Two functional
exceptions create real, clearance-relieved apertures in the visible host:
the A08 manual release and the A09 table-lift deployment corridor.  The A08
release corridor is permanent in the shared A01 nose in every primary state;
it must not appear only after Cafe or Focus enters its optional-open substate.

No pair is allowlisted and no occurrence is deleted.  Boolean results that
separate into multiple solids are emitted as individually named service
segments while retaining the original occurrence name for the largest solid.
Passing the local check is static B-Rep evidence only, not dynamic, tolerance,
load, sealing, safety or production certification.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from typing import Iterable, Sequence

import cadquery as cq

try:
    from .skin_common import SkinPart, rounded_box, validate_parts
except ImportError:
    from skin_common import SkinPart, rounded_box, validate_parts  # type: ignore[no-redef]


STATES = {"follow", "ride", "cafe", "focus"}
HARD_COMMON_MM3 = 0.1
NUMERICAL_COMMON_MM3 = 1.0e-6
FUNCTIONAL_CLEARANCE_MM = 1.0
MAX_PARTITION_OPERATIONS = 256

# The body-side DFR4 A08 manual-release over-shell is generated from the
# controlled 46 x 80 x 26 mm latch occurrence with a 6 mm over-shell allowance
# on every side.  This interface envelope is therefore 58 x 92 x 38 mm at the
# released centre below in every pose.  Keeping the clearance cutter explicit
# and invariant makes the A01 underside notch a property of the one physical
# nose shell, not geometry that appears only when a render changes state.
_A08_MANUAL_RELEASE_OUTER_SIZE_MM = (58.0, 92.0, 38.0)
_A08_MANUAL_RELEASE_CENTER_MM = (-460.0, 0.0, 108.0)

_A01_VISIBLE_NAMES = {
    "A01_front_nose_shell",
    "A01_front_tactile_bumper_skin",
}
_A08_INTERFACE_TOKENS = (
    "A08_footrest_support_boot_",
    "A08_footrest_support_body_collar_",
    "A08_footrest_root_cowl_",
    "A08_manual_release_paddle_shell",
)
_A05_TOUCH_TOKENS = (
    "A05_armrest_table_bay_shell_",
    "A05_armrest_touch_lid_",
    "A05_left_status_display_window",
    "A05_left_hmi_precision_bezel",
)
_A09_INTERFACE_TOKENS = (
    "A09_table_lift_boot_",
    "A09_cafe_root_mechanism_fairing_",
    "A09_focus_root_fairing_",
    "A09_cafe_armrest_to_table_root_bridge_",
    "A09_focus_armrest_to_table_root_bridge_",
    "A09_focus_internal_root_box_",
    "A09_focus_internal_nested_guide_stage_",
    "A09_focus_table_hidden_root_tongue_",
)


def _starts_with_any(name: str, tokens: Sequence[str]) -> bool:
    return any(name.startswith(token) for token in tokens)


def _is_a01_visible(part: SkinPart) -> bool:
    return part.module == "A01" and part.name in _A01_VISIBLE_NAMES


def _is_a08_interface(part: SkinPart) -> bool:
    return part.module == "A08" and _starts_with_any(
        part.name, _A08_INTERFACE_TOKENS
    )


def _is_a05_touch(part: SkinPart) -> bool:
    return part.module == "A05" and _starts_with_any(part.name, _A05_TOUCH_TOKENS)


def _is_a09_interface(part: SkinPart) -> bool:
    return part.module == "A09" and _starts_with_any(
        part.name, _A09_INTERFACE_TOKENS
    )


def _is_target_pair(left: SkinPart, right: SkinPart) -> bool:
    return (
        (_is_a01_visible(left) and _is_a08_interface(right))
        or (_is_a08_interface(left) and _is_a01_visible(right))
        or (_is_a05_touch(left) and _is_a09_interface(right))
        or (_is_a09_interface(left) and _is_a05_touch(right))
    )


def _bbox_overlaps(left: cq.Shape, right: cq.Shape) -> bool:
    a = left.BoundingBox()
    b = right.BoundingBox()
    return (
        min(a.xmax, b.xmax) > max(a.xmin, b.xmin)
        and min(a.ymax, b.ymax) > max(a.ymin, b.ymin)
        and min(a.zmax, b.zmax) > max(a.zmin, b.zmin)
    )


def _common_volume(left: cq.Shape, right: cq.Shape) -> float:
    if not _bbox_overlaps(left, right):
        return 0.0
    common = left.intersect(right)
    if common.isNull():
        return 0.0
    return max(0.0, float(common.Volume()))


def _shape_ok(shape: cq.Shape) -> bool:
    return (
        not shape.isNull()
        and shape.isValid()
        and float(shape.Volume()) > HARD_COMMON_MM3
        and bool(shape.Solids())
    )


def _clearance_box(shape: cq.Shape, margin_mm: float) -> cq.Shape:
    bounds = shape.BoundingBox()
    return rounded_box(
        (
            float(bounds.xlen) + 2.0 * margin_mm,
            float(bounds.ylen) + 2.0 * margin_mm,
            float(bounds.zlen) + 2.0 * margin_mm,
        ),
        (
            (float(bounds.xmin) + float(bounds.xmax)) / 2.0,
            (float(bounds.ymin) + float(bounds.ymax)) / 2.0,
            (float(bounds.zmin) + float(bounds.zmax)) / 2.0,
        ),
        min(4.0, max(0.5, margin_mm)),
    )


def a08_manual_release_corridor(
    margin_mm: float = FUNCTIONAL_CLEARANCE_MM,
) -> cq.Shape:
    """Return the invariant body-side A08 release travel/hand-clearance cutter."""

    if margin_mm < FUNCTIONAL_CLEARANCE_MM:
        raise ValueError(
            "A08 manual-release corridor may not use less than the released "
            f"{FUNCTIONAL_CLEARANCE_MM:.1f} mm functional clearance"
        )
    return rounded_box(
        tuple(
            dimension + 2.0 * margin_mm
            for dimension in _A08_MANUAL_RELEASE_OUTER_SIZE_MM
        ),
        _A08_MANUAL_RELEASE_CENTER_MM,
        min(4.0, max(0.5, margin_mm)),
    )


def _index(parts: Sequence[SkinPart], name: str) -> int:
    matches = [index for index, part in enumerate(parts) if part.name == name]
    if len(matches) != 1:
        raise KeyError(
            f"V8 cross rigid partition requires one {name!r}; found {len(matches)}"
        )
    return matches[0]


def _replace_cut(
    parts: list[SkinPart],
    host_name: str,
    cutter: cq.Shape,
    *,
    cutter_name: str,
    interface: str,
    role: str,
    clearance_mm: float,
) -> None:
    index = _index(parts, host_name)
    host = parts[index]
    common_before = _common_volume(host.shape, cutter)
    if common_before <= HARD_COMMON_MM3:
        return
    candidate = host.shape.cut(cutter)
    if not _shape_ok(candidate):
        raise ValueError(
            f"V8 cross partition {interface} would consume or invalidate "
            f"{host_name} while cutting {cutter_name}; common="
            f"{common_before:.6f} mm3"
        )
    metadata = dict(host.metadata)
    history = list(metadata.get("cross_rigid_partition_history", ()))
    history.append(
        {
            "interface": interface,
            "role": role,
            "operation": "BRep_subtract",
            "cutter": cutter_name,
            "common_volume_removed_mm3": common_before,
            "functional_clearance_mm": clearance_mm,
        }
    )
    metadata.update(
        {
            "cross_rigid_partitioned": True,
            "cross_rigid_partition_role": role,
            "cross_rigid_partition_history": history,
            "cross_pair_common_volume_target_mm3": 0.0,
            "allowlisted_collision": False,
            "certification_claimed": False,
        }
    )
    parts[index] = replace(host, shape=candidate, metadata=metadata)


def _ordered_pair(left: SkinPart, right: SkinPart) -> tuple[SkinPart, SkinPart]:
    if _is_a01_visible(left) or _is_a05_touch(left):
        return left, right
    return right, left


def _partition_one_pair(
    parts: list[SkinPart],
    protected: SkinPart,
    yielding: SkinPart,
) -> None:
    if _is_a01_visible(protected) and _is_a08_interface(yielding):
        if yielding.name.startswith("A08_manual_release_paddle_shell"):
            # Safety-rated manual control stays whole and receives a real
            # clearance-relieved aperture through whichever A01 surface it
            # reaches.  The same invariant cutter is also applied when A08 is
            # stowed, so optional Cafe/Focus deployment never changes A01.
            aperture = a08_manual_release_corridor()
            outside = yielding.shape.cut(aperture)
            outside_volume = 0.0 if outside.isNull() else float(outside.Volume())
            if outside_volume > HARD_COMMON_MM3:
                raise ValueError(
                    "A08 manual-release over-shell escaped its controlled "
                    f"corridor by {outside_volume:.6f} mm3"
                )
            _replace_cut(
                parts,
                protected.name,
                aperture,
                cutter_name=yielding.name,
                interface="A01_A08_manual_release_aperture",
                role="visible_A01_host_with_real_safety_control_aperture",
                clearance_mm=FUNCTIONAL_CLEARANCE_MM,
            )
            return
        _replace_cut(
            parts,
            yielding.name,
            protected.shape,
            cutter_name=protected.name,
            interface="A01_A08_front_deployable_partition",
            role="inboard_A08_cover_yields_to_visible_A01_surface",
            clearance_mm=0.0,
        )
        return

    if _is_a05_touch(protected) and _is_a09_interface(yielding):
        if yielding.name.startswith(
            (
                "A09_focus_internal_root_box_",
                "A09_focus_internal_nested_guide_stage_",
                "A09_focus_table_hidden_root_tongue_",
            )
        ):
            # Focus internal hardware has already been packaged against the
            # real A05 cavity and its small inner-wall port.  Cutting either
            # occurrence here would hide a packaging regression and could
            # silently reopen the closed top lid, so any residual common
            # volume is a hard design failure.
            common = _common_volume(protected.shape, yielding.shape)
            raise ValueError(
                f"Focus concealed root collision {protected.name!r}/"
                f"{yielding.name!r}: {common:.9f} mm3"
            )
        if yielding.name.startswith("A09_table_lift_boot_") and protected.name.startswith(
            ("A05_armrest_table_bay_shell_", "A05_armrest_touch_lid_")
        ):
            # The independently serviceable lift boot is the real deployment
            # throat.  A05 receives an explicit aperture instead of hiding the
            # collision inside either cosmetic part.
            aperture = _clearance_box(yielding.shape, FUNCTIONAL_CLEARANCE_MM)
            _replace_cut(
                parts,
                protected.name,
                aperture,
                cutter_name=yielding.name,
                interface="A05_A09_table_lift_deployment_aperture",
                role="touch_surface_with_real_deployment_corridor",
                clearance_mm=FUNCTIONAL_CLEARANCE_MM,
            )
            return
        _replace_cut(
            parts,
            yielding.name,
            protected.shape,
            cutter_name=protected.name,
            interface="A05_A09_touch_surface_partition",
            role="inboard_A09_root_cover_yields_to_A05_touch_surface",
            clearance_mm=0.0,
        )
        return
    raise ValueError(
        f"Unsupported V8 cross rigid pair {protected.name!r}/{yielding.name!r}"
    )


def _next_hard_pair(parts: Sequence[SkinPart]) -> tuple[SkinPart, SkinPart] | None:
    targets = [
        part
        for part in parts
        if _is_a01_visible(part)
        or _is_a08_interface(part)
        or _is_a05_touch(part)
        or _is_a09_interface(part)
    ]
    for left, right in combinations(targets, 2):
        if not _is_target_pair(left, right):
            continue
        if _common_volume(left.shape, right.shape) > HARD_COMMON_MM3:
            return _ordered_pair(left, right)
    return None


def _explode_multisolids(parts: Sequence[SkinPart]) -> list[SkinPart]:
    result: list[SkinPart] = []
    reserved_names = {part.name for part in parts}
    for part in parts:
        solids = sorted(
            list(part.shape.Solids()),
            key=lambda solid: float(solid.Volume()),
            reverse=True,
        )
        if not solids:
            raise ValueError(f"V8 cross partition left {part.name} without a solid")
        if len(solids) == 1:
            # Store the solid itself, not a one-solid compound, so the release
            # invariant is unambiguous after STEP export/reload.
            result.append(replace(part, shape=solids[0]))
            continue

        group_id = str(
            part.metadata.get("physical_occurrence_id", f"{part.configuration}-{part.name}")
        )
        for segment_index, solid in enumerate(solids, start=1):
            name = part.name
            if segment_index > 1:
                suffix = segment_index
                name = f"{part.name}_cross_segment_{suffix}"
                while name in reserved_names:
                    suffix += 1
                    name = f"{part.name}_cross_segment_{suffix}"
                reserved_names.add(name)
            metadata = dict(part.metadata)
            metadata.update(
                {
                    "cross_service_segment_group_id": group_id,
                    "cross_service_segment_index": segment_index,
                    "cross_service_segment_count": len(solids),
                    "physical_occurrence_id": (
                        group_id
                        if segment_index == 1
                        else f"{group_id}-CROSS-SEG-{segment_index}"
                    ),
                    "certification_claimed": False,
                }
            )
            result.append(
                replace(
                    part,
                    name=name,
                    shape=solid,
                    intent=(
                        part.intent
                        if segment_index == 1
                        else f"Cross-interface service continuation of {part.name}."
                    ),
                    metadata=metadata,
                )
            )
    return result


def _assert_cross_pairs_clear(parts: Sequence[SkinPart], state: str) -> None:
    failures: list[str] = []
    targets = [
        part
        for part in parts
        if _is_a01_visible(part)
        or _is_a08_interface(part)
        or _is_a05_touch(part)
        or _is_a09_interface(part)
    ]
    for left, right in combinations(targets, 2):
        if not _is_target_pair(left, right):
            continue
        common = _common_volume(left.shape, right.shape)
        if common > HARD_COMMON_MM3:
            failures.append(f"{left.name}/{right.name}={common:.6f} mm3")
    if failures:
        raise ValueError(
            f"V8 {state} cross rigid partitions remain: " + "; ".join(failures)
        )


def apply_v8_cross_rigid_partitions(
    state: str,
    parts: Iterable[SkinPart],
) -> list[SkinPart]:
    """Resolve the V8 A01/A08 and A05/A09 hard cross-module volumes.

    The input iterable is not mutated.  All existing names remain present;
    multi-solid Boolean results are emitted as separate service occurrences.
    """

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 cross-partition state {state!r}")
    result = list(parts)
    original_names = {part.name for part in result}
    if len(original_names) != len(result):
        raise ValueError(f"V8 {state} cross partition input contains duplicate names")

    operations = 0
    while True:
        pair = _next_hard_pair(result)
        if pair is None:
            break
        protected, yielding = pair
        _partition_one_pair(result, protected, yielding)
        operations += 1
        if operations > MAX_PARTITION_OPERATIONS:
            raise RuntimeError(
                f"V8 {state} cross rigid partition did not converge after "
                f"{MAX_PARTITION_OPERATIONS} operations"
            )

    # A01 is one physical moulding across Follow/Ride/Cafe/Focus.  Cut the
    # released underside corridor even when the primary state keeps A08
    # stowed.  This is a real permanent service/motion opening, not a collision
    # allowlist and not optional-state-only geometry.
    _replace_cut(
        result,
        "A01_front_nose_shell",
        a08_manual_release_corridor(),
        cutter_name="E6-A08-MANUAL-RELEASE-DEPLOYED-CORRIDOR",
        interface="A01_A08_permanent_manual_release_corridor",
        role="shared_A01_nose_with_permanent_underside_release_corridor",
        clearance_mm=FUNCTIONAL_CLEARANCE_MM,
    )

    result = _explode_multisolids(result)
    missing = sorted(original_names - {part.name for part in result})
    if missing:
        raise ValueError(f"V8 {state} cross partition deleted occurrences: {missing}")
    errors = validate_parts(result)
    single_solid_errors = [
        part.name for part in result if len(part.shape.Solids()) != 1
    ]
    if errors or single_solid_errors:
        raise ValueError(
            f"V8 {state} cross partition invalid output: "
            f"errors={errors}, non_single={single_solid_errors}"
        )
    _assert_cross_pairs_clear(result, state)
    return result


def _official_cross_collision_self_test() -> None:
    """Rebuild four states and filter the official collision report to scope."""

    try:
        from .skin_lower import build_lower_skin
        from .skin_upper import build_upper_skin
        from .skin_v8_refinement import refine_v8_parts
        from .v8_collision_partition import apply_v8_collision_partitions
        from .v8_functional_fixes import apply_v8_functional_fixes
        from .v8_mast_fixes import apply_v8_mast_fixes
        from .v8_qa_gates import rigid_pair_collision_report
        from .v8_rigid_partition_deployables import (
            apply_v8_deployable_rigid_partitions,
        )
        from .v8_rigid_partition_mast import apply_v8_mast_rigid_partitions
    except ImportError:
        from skin_lower import build_lower_skin  # type: ignore[no-redef]
        from skin_upper import build_upper_skin  # type: ignore[no-redef]
        from skin_v8_refinement import refine_v8_parts  # type: ignore[no-redef]
        from v8_collision_partition import apply_v8_collision_partitions  # type: ignore[no-redef]
        from v8_functional_fixes import apply_v8_functional_fixes  # type: ignore[no-redef]
        from v8_mast_fixes import apply_v8_mast_fixes  # type: ignore[no-redef]
        from v8_qa_gates import rigid_pair_collision_report  # type: ignore[no-redef]
        from v8_rigid_partition_deployables import (  # type: ignore[no-redef]
            apply_v8_deployable_rigid_partitions,
        )
        from v8_rigid_partition_mast import apply_v8_mast_rigid_partitions  # type: ignore[no-redef]

    for state in ("follow", "ride", "cafe", "focus"):
        built = build_lower_skin(state) + build_upper_skin(state)
        for operation in (
            refine_v8_parts,
            apply_v8_functional_fixes,
            apply_v8_mast_fixes,
            apply_v8_collision_partitions,
            apply_v8_deployable_rigid_partitions,
            apply_v8_mast_rigid_partitions,
            apply_v8_cross_rigid_partitions,
        ):
            built = operation(state, built)
        scoped = [
            part
            for part in built
            if _is_a01_visible(part)
            or _is_a08_interface(part)
            or _is_a05_touch(part)
            or _is_a09_interface(part)
        ]
        report = rigid_pair_collision_report(scoped, state, allowlist=())
        modules = {part.name: part.module for part in scoped}
        hard_cross = [
            record
            for record in report["hard_collisions"]
            if {modules[record["a"]], modules[record["b"]]}
            in ({"A01", "A08"}, {"A05", "A09"})
        ]
        if hard_cross:
            raise ValueError(f"V8 {state} official cross report failed: {hard_cross}")
        print(
            f"PASS {state}: scoped_parts={len(scoped)}, "
            f"official_exact_booleans={report['exact_boolean_count']}, "
            "hard_cross=0, allowlist=0"
        )


if __name__ == "__main__":
    _official_cross_collision_self_test()


__all__ = ["apply_v8_cross_rigid_partitions"]
