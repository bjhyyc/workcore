"""Executable release gates for the WorkCore E6 V8 exterior geometry.

This module is intentionally independent from ``build_class_a_skin.py``.  It
rebuilds the four V8 state skins in memory, reads the controlled STEP files as
immutable underlays, and emits geometry-backed checks.  It writes nothing
unless the caller explicitly supplies ``--output``.

Passing this gate means only that the named V8 exterior geometry satisfies the
checks implemented here.  It is *not* production certification, Class-A
surface approval, DFM sign-off, safety validation, RF validation, environmental
qualification, or a substitute for physical testing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


STATES = ("follow", "ride", "cafe", "focus")
BOOLEAN_TOLERANCE_MM3 = 1.0e-5
DISTANCE_TOLERANCE_MM = 1.0e-4
# OCCT STEP write/read can move an individual analytic/trimmed B-Rep bound by
# up to 0.01 mm while preserving its solid, centroid and mass properties.  The
# part roundtrip gate enforces that same fail-closed bound.  Envelope locks
# remain nominal dimensions; this tolerance applies only to their numerical
# comparison and is reported separately from every design allowance.
ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM = 0.01
A07_MAST_AXIS_X_MM = 310.0
A07_LOW_BEAM_CENTER_Z_MM = 1040.0
A07_FOCUS_TRANSLATION_MM = 420.0
A07_FOCUS_BEAM_CENTER_Z_MM = 1460.0
A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM = (264.5, 128.0, 1460.0)
A07_MINIMUM_DRY_CLEARANCE_MM = 0.5
A07_TERMINAL_NOMINAL_WIDTH_Y_MM = 370.0
A07_MINIMUM_EXTENDED_CAPTURE_MM = 150.0
A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM = 3.0
A07_TERMINAL_TENON_ENGAGEMENT_MM = 16.0
A07_TERMINAL_END_CLEARANCE_MM = 2.0
A07_TERMINAL_COSMETIC_DRY_SEAM_MM = 4.0
A09_LIFT_STAGE_PROFILE_CONTRACT: dict[int, dict[str, object]] = {
    1: {
        "outer_xy_mm": (72.0, 70.0),
        "inner_xy_mm": (66.0, 64.0),
        "outer_plan_radius_mm": 21.0,
        "inner_plan_radius_mm": 18.0,
        "minimum_wall_mm": 3.0,
    },
    2: {
        "outer_xy_mm": (60.0, 58.0),
        "inner_xy_mm": (54.0, 52.0),
        "outer_plan_radius_mm": 18.0,
        "inner_plan_radius_mm": 15.0,
        "minimum_wall_mm": 3.0,
    },
    3: {
        "outer_xy_mm": (48.0, 46.0),
        "inner_xy_mm": (40.0, 40.0),
        "outer_plan_radius_mm": 14.0,
        "inner_plan_radius_mm": 10.0,
        "minimum_wall_mm": 3.0,
    },
}
A09_LIFT_STAGE_Z_HARDPOINTS_MM = {
    1: (495.117310634, 574.882689366),
    2: (569.117310634, 640.882689366),
    3: (633.642857143, 693.357142857),
}
A09_LIFT_ADJACENT_RADIAL_CLEARANCE_MM = 3.0
A09_LIFT_STAGE3_MINIMUM_INTERNAL_CHANNEL_MM = 40.0
A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM = 2.4
A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM = 1.5
A07_MICROPHONE_TENON_MINIMUM_DRY_CLEARANCE_MM = 1.5
A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM = 0.2
A07_SHUTTER_CARRIAGE_MINIMUM_DRY_CLEARANCE_MM = 0.15
FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM = 60.0
FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM = 22.0
FOLLOW_SEAT_CUSHION_MAXIMUM_COMMON_VOLUME_MM3 = 70_000.0
RIGHT_CONTROL_HAND_ENVELOPE_PLAN_RADII_MM = (70.0, 52.0)
RIGHT_CONTROL_HAND_ENVELOPE_CENTER_MM = (-268.0, 333.0, 650.0)
RIGHT_CONTROL_HAND_ENVELOPE_HEIGHT_MM = 120.0
RIGHT_CONTROL_MINIMUM_TABLE_CLEARANCE_MM = 5.0
FRONT_WAIST_SURFACE_ORIENTATION = (
    "continuous_tall_vertical_u_section_with_crowned_hood"
)


def _within_locked_envelope_axis(actual_mm: float, nominal_limit_mm: float) -> bool:
    return (
        actual_mm
        <= nominal_limit_mm + ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
    )


def _workspace_root(start: Path | None = None) -> Path:
    candidate = (start or Path(__file__)).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for parent in (candidate, *candidate.parents):
        if (parent / "cad" / "parameters.py").is_file() and (parent / "build").is_dir():
            return parent
    raise FileNotFoundError(
        "Unable to locate WorkCore root containing cad/parameters.py and build/"
    )


WORKSPACE_ROOT = _workspace_root()
CAD_DIRECTORY = Path(__file__).resolve().parent
for _path in (WORKSPACE_ROOT, CAD_DIRECTORY):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import cadquery as cq  # noqa: E402
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402

from cad.parameters import P  # noqa: E402
from skin_common import (  # noqa: E402
    LUNAR_STONE,
    SkinPart,
    rounded_box,
    rounded_rect_prism,
)
from exterior_presentation import (  # noqa: E402
    A07_CANONICAL_EXTERIOR_NAMES,
    A07_CANONICAL_INTERNAL_NAMES,
    exterior_visibility_reason,
)
from v8_wheel_contract import (  # noqa: E402
    WHEEL_AXIS_Z_MM,
    WHEEL_END_CLOSED_PROBE_Z_MM,
    WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM,
    WHEEL_END_COVERAGE_PROBE_Z_MM,
    WHEEL_END_LOWER_TYRE_WITNESS_LATERAL_OFFSETS_MM,
    WHEEL_END_LOWER_TYRE_WITNESS_Z_MM,
    WHEEL_END_OPEN_PROBE_Z_MM,
    WHEEL_END_RETURN_LOWER_EDGE_Z_MM,
    WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM,
    WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
    WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
    WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM,
    WHEEL_MINIMUM_SWEPT_CLEARANCE_MM,
    WHEEL_NOMINAL_PRODUCT_WIDTH_MM,
    WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
    WHEEL_PRODUCTION_WIDTH_LIMIT_MM,
    WHEEL_SIDE_CLOSED_PROBE_Z_MM,
    WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM,
    WHEEL_SIDE_OPEN_PROBE_Z_MM,
    WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM,
)
from v8_wheel_hub_articulation import (  # noqa: E402
    evaluate_wheel_hub_articulation,
    wheel_belt_class_a_shell,
)
from v8_state_contract import (  # noqa: E402
    DEFAULT_FOOTREST_STATE,
    FOOTREST_CONTRACT_VERSION,
    default_footrest_is_deployed,
    optional_footrest_open_available,
)
from skin_upper import BACK_FOLD_DEG, BACK_HINGE, BACK_RAKE_DEG  # noqa: E402
from source_disposition import build_state_ledger, retain_exposed_names  # noqa: E402
from v8_rigid_partition_cross import a08_manual_release_corridor  # noqa: E402
from v8_footrest_drawer_brep import (  # noqa: E402
    FIXED_OCCURRENCE_NAMES as A08_FIXED_OCCURRENCE_NAMES,
    a08_footrest_drawer_occurrences,
    evaluate_a08_final_body_interfaces,
    evaluate_a08_fixed_host_clearance,
    evaluate_a08_footrest_drawer_brep,
    evaluate_a08_rear_labyrinth_sightlines,
    evaluate_a08_retained_running_gear_clearance,
)
from v8_table_lid_packaging import (  # noqa: E402
    TABLE_ACCESS_SEQUENCE,
    cafe_half_leaf_pair,
)
from v8_lid_harness_gate import evaluate_a05_lid_harness_gate  # noqa: E402
from v8_cafe_table_root_motion import (  # noqa: E402
    CAFE_COVER_PICKUP_DEAD_TRAVEL_MM,
    CAFE_FINAL_RAIL_CAPTURE_MM,
    CAFE_INTERNAL_FOLD_HARD_RETREAT_MM,
    CAFE_RETURN_TRAVEL_MM,
    cafe_root_final_occurrences,
    cafe_root_motion_pose,
    cafe_root_motion_poses,
    cafe_table_control_final_occurrences,
    cafe_table_control_pose,
)
from v8_final_appearance_closure import (  # noqa: E402
    A06_HINGE_BEARING_OUTER_RADIUS_MM,
    A06_LOCK_DISC_AXIAL_MM,
    A06_LOCK_DISC_RADIUS_MM,
    A06_LOCK_STATION_Y_MM,
    A07_AXIS_X_MM,
    A07_FOCUS_STROKE_MM,
    A07_LOCK_BORE_DIAMETER_MM,
    A07_LOCK_FOCUS_BORE_Z_MM,
    A07_LOCK_LOW_BORE_Z_MM,
    A07_LOCK_PIN_DIAMETER_MM,
    A07_LOCK_PIN_RETRACTED_X_MM,
    A07_LOCK_PIN_Y_MM,
    A07_LOCK_STATION_Z_MM,
    _production_a07_low_masters,
    a07_lock_motion_pose,
)


SOURCE_STEPS: dict[str, dict[str, Any]] = {
    "follow": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_follow.step",
        "bytes": 6_129_275,
        "sha256": "f925527ce086f2b18b0c53312733aadd6fa69aebb541d158f260d9c33b1a88fc",
        "reference_envelope_mm": (835.0, 735.0, 689.5),
    },
    "ride": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_ride.step",
        "bytes": 5_810_509,
        "sha256": "3bf21b0811845c0d0fc10fbd116c96fc2188cc6e7a54956cd5e383c6a48fbb89",
        "reference_envelope_mm": (1061.0, 735.0, 1072.0),
    },
    "cafe": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_cafe.step",
        "bytes": 6_117_206,
        "sha256": "8118b34c83bde30f316717e028279de656db4640d1c1f74e2c7fb6c96ecddd88",
        "reference_envelope_mm": (856.0, 735.0, 1072.0),
    },
    "focus": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_focus.step",
        "bytes": 6_267_448,
        "sha256": "598ad5a8686989be548140c5629a1b996b85bc833f1672850c98da400626ed4c",
        "reference_envelope_mm": (971.0, 735.0, 1492.0),
    },
}


@dataclass(frozen=True)
class _Box:
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float

    @classmethod
    def from_shape(cls, shape: cq.Shape) -> "_Box":
        # Presentation tessellation populates OCCT triangulation caches on the
        # same TopoDS shape.  CadQuery's default BoundingBox then permits that
        # display mesh (and its deflection margin) to drive the result, which
        # can falsely enlarge an unchanged STEP B-Rep by several millimetres.
        # Release evidence must come from the analytic geometry only.
        bounds = Bnd_Box()
        BRepBndLib.AddOptimal_s(
            shape.wrapped,
            bounds,
            False,  # never use cached presentation triangulation
            False,  # do not enlarge by entity tolerances
        )
        xmin, ymin, zmin, xmax, ymax, zmax = bounds.Get()
        return cls(
            float(xmin),
            float(xmax),
            float(ymin),
            float(ymax),
            float(zmin),
            float(zmax),
        )

    def union(self, other: "_Box") -> "_Box":
        return _Box(
            min(self.xmin, other.xmin),
            max(self.xmax, other.xmax),
            min(self.ymin, other.ymin),
            max(self.ymax, other.ymax),
            min(self.zmin, other.zmin),
            max(self.zmax, other.zmax),
        )

    @property
    def lengths(self) -> tuple[float, float, float]:
        return (
            self.xmax - self.xmin,
            self.ymax - self.ymin,
            self.zmax - self.zmin,
        )

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.xmin + self.xmax) / 2.0,
            (self.ymin + self.ymax) / 2.0,
            (self.zmin + self.zmax) / 2.0,
        )

    def to_dict(self) -> dict[str, float]:
        x, y, z = self.lengths
        return {
            "xmin": round(self.xmin, 3),
            "xmax": round(self.xmax, 3),
            "ymin": round(self.ymin, 3),
            "ymax": round(self.ymax, 3),
            "zmin": round(self.zmin, 3),
            "zmax": round(self.zmax, 3),
            "length_x_mm": round(x, 3),
            "width_y_mm": round(y, 3),
            "height_z_mm": round(z, 3),
        }


def _envelope_lock_evidence(
    state: str,
    source: _Box,
    production: _Box,
    reference_envelope_mm: tuple[float, float, float],
) -> dict[str, Any]:
    """Evaluate per-face skin growth and independent overall product limits.

    A Class-A return can grow beyond both ends of a controlled underlay.  The
    25 mm longitudinal allowance is therefore a limit on *each* source
    boundary, not a single 25 mm budget shared by the front and rear returns.
    Overall dimensions remain independently locked so this interpretation
    cannot conceal a one-sided translation or unconstrained product growth.
    """

    longitudinal_per_boundary_mm = 25.0
    lateral_per_boundary_mm = 17.0
    upper_vertical_mm = 10.0
    source_x, source_y, source_z = reference_envelope_mm

    boundary_limits = {
        "xmin": source.xmin - longitudinal_per_boundary_mm,
        "xmax": source.xmax + longitudinal_per_boundary_mm,
        "ymin": source.ymin - lateral_per_boundary_mm,
        "ymax": source.ymax + lateral_per_boundary_mm,
        "zmin": source.zmin,
        "zmax": source.zmax + upper_vertical_mm,
    }
    boundary_margin = {
        "xmin": production.xmin - boundary_limits["xmin"],
        "xmax": boundary_limits["xmax"] - production.xmax,
        "ymin": production.ymin - boundary_limits["ymin"],
        "ymax": boundary_limits["ymax"] - production.ymax,
        "zmin": production.zmin - boundary_limits["zmin"],
        "zmax": boundary_limits["zmax"] - production.zmax,
    }
    boundary_pass = {
        name: margin >= -ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
        for name, margin in boundary_margin.items()
    }

    overall_limits = {
        "length_x": source_x + 2.0 * longitudinal_per_boundary_mm,
        "width_y": min(
            760.0,
            source_y + lateral_per_boundary_mm,
            WHEEL_PRODUCTION_WIDTH_LIMIT_MM,
        ),
        "height_z": source_z + upper_vertical_mm,
    }
    if state == "follow":
        overall_limits = {
            "length_x": min(overall_limits["length_x"], 900.0),
            "width_y": min(overall_limits["width_y"], 760.0),
            "height_z": min(overall_limits["height_z"], 700.0),
        }

    actual_x, actual_y, actual_z = production.lengths
    actual = {
        "length_x": actual_x,
        "width_y": actual_y,
        "height_z": actual_z,
    }
    overall_axis_pass = {
        name: _within_locked_envelope_axis(actual[name], limit)
        for name, limit in overall_limits.items()
    }
    boundary_axis_pass = {
        "x": boundary_pass["xmin"] and boundary_pass["xmax"],
        "y": boundary_pass["ymin"] and boundary_pass["ymax"],
        "z": boundary_pass["zmin"] and boundary_pass["zmax"],
    }
    axis_pass = {
        "x": boundary_axis_pass["x"] and overall_axis_pass["length_x"],
        "y": boundary_axis_pass["y"] and overall_axis_pass["width_y"],
        "z": boundary_axis_pass["z"] and overall_axis_pass["height_z"],
    }
    nominal_margin = {
        name: overall_limits[name] - actual[name]
        for name in ("length_x", "width_y", "height_z")
    }
    return {
        "pass": all(axis_pass.values()),
        "allowance_interpretation": (
            "25 mm is checked independently at xmin and xmax; the overall "
            "length is separately capped at source length + 50 mm"
        ),
        "source_controlled_bounds": source.to_dict(),
        "boundary_allowance_mm": {
            "x_per_boundary": longitudinal_per_boundary_mm,
            "y_per_boundary": lateral_per_boundary_mm,
            "z_lower": 0.0,
            "z_upper": upper_vertical_mm,
        },
        "boundary_limits_mm": {
            name: round(value, 6) for name, value in boundary_limits.items()
        },
        "boundary_margin_mm": {
            name: round(value, 6) for name, value in boundary_margin.items()
        },
        "boundary_pass": boundary_pass,
        "maximum_mm": {
            name: round(value, 3) for name, value in overall_limits.items()
        },
        "nominal_margin_mm": {
            "x": round(nominal_margin["length_x"], 6),
            "y": round(nominal_margin["width_y"], 6),
            "z": round(nominal_margin["height_z"], 6),
        },
        "overall_axis_pass": overall_axis_pass,
        "axis_pass": axis_pass,
    }


class _GateBook:
    """Collect checks while making duplicate IDs and missing evidence illegal."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self._ids: set[str] = set()

    def add(
        self,
        check_id: str,
        passed: bool,
        *,
        severity: str = "hard",
        evidence_kind: str,
        requirement: str,
        **evidence: Any,
    ) -> None:
        if not check_id or check_id in self._ids:
            raise ValueError(f"Duplicate or empty V8 release-gate check ID: {check_id!r}")
        if not evidence_kind or not evidence_kind.strip():
            raise ValueError(f"Check {check_id!r} has no evidence_kind")
        if severity not in {"hard", "advisory"}:
            raise ValueError(
                f"Check {check_id!r} has unsupported severity {severity!r}"
            )
        self._ids.add(check_id)
        self.checks.append(
            {
                "id": check_id,
                "pass": bool(passed),
                "severity": severity,
                "evidence_kind": evidence_kind,
                "requirement": requirement,
                **evidence,
            }
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _part(parts: Sequence[SkinPart], name: str) -> SkinPart:
    matches = [part for part in parts if part.name == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one V8 part {name!r}; found {len(matches)}")
    return matches[0]


def _intersection_volume(first: cq.Shape, second: cq.Shape) -> float:
    return float(first.intersect(second).Volume())


def _brep_pose_evidence(reference: cq.Shape, candidate: cq.Shape) -> dict[str, Any]:
    """Compare actual B-Reps after the caller applies the declared pose inverse."""

    reference_box = _Box.from_shape(reference)
    candidate_box = _Box.from_shape(candidate)
    symmetric_difference = float(
        reference.cut(candidate).Volume() + candidate.cut(reference).Volume()
    )
    bound_delta = max(
        abs(a - b)
        for a, b in zip(
            (
                reference_box.xmin,
                reference_box.xmax,
                reference_box.ymin,
                reference_box.ymax,
                reference_box.zmin,
                reference_box.zmax,
            ),
            (
                candidate_box.xmin,
                candidate_box.xmax,
                candidate_box.ymin,
                candidate_box.ymax,
                candidate_box.zmin,
                candidate_box.zmax,
            ),
        )
    )
    return {
        "symmetric_difference_mm3": symmetric_difference,
        "volume_delta_mm3": abs(float(reference.Volume()) - float(candidate.Volume())),
        "area_delta_mm2": abs(float(reference.Area()) - float(candidate.Area())),
        "maximum_bound_delta_mm": bound_delta,
        "face_count_equal": len(reference.Faces()) == len(candidate.Faces()),
        "edge_count_equal": len(reference.Edges()) == len(candidate.Edges()),
        "reference_bounds": reference_box.to_dict(),
        "candidate_bounds": candidate_box.to_dict(),
    }


def _brep_pose_matches(evidence: Mapping[str, Any]) -> bool:
    return (
        float(evidence["symmetric_difference_mm3"]) <= 0.05
        and float(evidence["volume_delta_mm3"]) <= 0.05
        and float(evidence["area_delta_mm2"]) <= 0.05
        and float(evidence["maximum_bound_delta_mm"]) <= 0.01
        and bool(evidence["face_count_equal"])
        and bool(evidence["edge_count_equal"])
    )


def _union_boxes(shapes: Iterable[cq.Shape]) -> _Box:
    boxes = [_Box.from_shape(shape) for shape in shapes]
    if not boxes:
        raise ValueError("Cannot compute an envelope from no shapes")
    result = boxes[0]
    for item in boxes[1:]:
        result = result.union(item)
    return result


def build_v8_state(state: str) -> list[SkinPart]:
    """Build one V8 state with the same complete pipeline as the release builder."""

    state = state.strip().lower()
    if state not in STATES:
        raise ValueError(f"Unsupported V8 state {state!r}")

    from skin_lower import build_lower_skin
    from skin_upper import build_upper_skin
    from skin_v8_refinement import refine_v8_parts
    from v8_collision_partition import apply_v8_collision_partitions
    from v8_final_appearance_closure import apply_v8_final_appearance_closure
    from v8_functional_fixes import apply_v8_functional_fixes
    from v8_mast_fixes import apply_v8_mast_fixes
    from v8_rigid_partition_cross import apply_v8_cross_rigid_partitions
    from v8_rigid_partition_deployables import apply_v8_deployable_rigid_partitions
    from v8_rigid_partition_mast import apply_v8_mast_rigid_partitions
    from v8_rigid_partition_service import apply_v8_service_rigid_partitions

    parts = build_lower_skin(state) + build_upper_skin(state)
    parts = refine_v8_parts(state, parts)
    parts = apply_v8_functional_fixes(state, parts)
    parts = apply_v8_mast_fixes(state, parts)
    parts = apply_v8_collision_partitions(state, parts)
    parts = apply_v8_deployable_rigid_partitions(state, parts)
    parts = apply_v8_mast_rigid_partitions(state, parts)
    parts = apply_v8_service_rigid_partitions(state, parts)
    parts = apply_v8_cross_rigid_partitions(state, parts)
    parts = apply_v8_final_appearance_closure(state, parts)
    return parts


def build_all_v8_states() -> dict[str, list[SkinPart]]:
    return {state: build_v8_state(state) for state in STATES}


def _gate_source_integrity(
    root: Path,
    book: _GateBook,
) -> dict[str, cq.Shape]:
    source_shapes: dict[str, cq.Shape] = {}
    for state in STATES:
        baseline = SOURCE_STEPS[state]
        path = root / str(baseline["path"])
        exists = path.is_file()
        actual_bytes = path.stat().st_size if exists else None
        actual_hash = _sha256(path) if exists else None
        book.add(
            f"source.{state}.controlled_step_immutable",
            exists
            and actual_bytes == int(baseline["bytes"])
            and actual_hash == str(baseline["sha256"]),
            evidence_kind="cryptographic_hash_and_byte_count",
            requirement="V8 gates may read but must not rewrite the controlled E6-DFR5-A07-SHARED-HINGE STEP underlay.",
            path=str(path),
            expected_bytes=int(baseline["bytes"]),
            actual_bytes=actual_bytes,
            expected_sha256=str(baseline["sha256"]),
            actual_sha256=actual_hash,
        )
        if exists:
            imported = cq.importers.importStep(str(path))
            shape = imported.val() if hasattr(imported, "val") else imported
            if not isinstance(shape, cq.Shape):
                raise TypeError(f"Controlled STEP did not import as a shape: {path}")
            source_shapes[state] = shape
    return source_shapes


def _gate_part_topology(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    for state in STATES:
        parts = list(states.get(state, ()))
        names = [part.name for part in parts]
        book.add(
            f"parts.{state}.names_unique",
            bool(parts) and len(names) == len(set(names)),
            evidence_kind="in_memory_occurrence_inventory",
            requirement="Every V8 state must contain a non-empty, uniquely named skin occurrence set.",
            part_count=len(parts),
            duplicate_names=sorted({name for name in names if names.count(name) > 1}),
        )
        for name in sorted(set(names)):
            matches = [part for part in parts if part.name == name]
            part = matches[0]
            shape = part.shape
            solids = len(shape.Solids()) if not shape.isNull() else 0
            book.add(
                f"parts.{state}.{part.name}.single_valid_solid",
                len(matches) == 1
                and part.configuration == state
                and not shape.isNull()
                and shape.isValid()
                and shape.Volume() > 0.0
                and solids == 1,
                evidence_kind="brep_topology_and_volume",
                requirement="Every SkinPart must be exactly one positive, valid B-Rep solid in its declared state.",
                declared_configuration=part.configuration,
                occurrence_count=len(matches),
                solid_count=solids,
                valid=bool(shape.isValid()) if not shape.isNull() else False,
                volume_mm3=round(float(shape.Volume()), 6) if not shape.isNull() else 0.0,
            )


def _sightline(
    center: tuple[float, float, float],
    axis: str,
    exterior: float,
    thickness_mm: float = 3.0,
) -> cq.Shape:
    axis_index = {"x": 0, "y": 1}[axis]
    size = [thickness_mm, thickness_mm, thickness_mm]
    size[axis_index] = abs(exterior - center[axis_index])
    ray_center = list(center)
    ray_center[axis_index] = (exterior + center[axis_index]) / 2.0
    return cq.Workplane("XY").box(*size).translate(tuple(ray_center)).val()


def _rotate_about_back_hinge(shape: cq.Shape, degrees: float) -> cq.Shape:
    ox, oy, oz = BACK_HINGE
    return shape.rotate((ox, oy, oz), (ox, oy + 1.0, oz), degrees)


def _normalised_backrest(shape: cq.Shape, state: str) -> cq.Shape:
    result = shape
    if state == "follow":
        result = _rotate_about_back_hinge(result, -BACK_FOLD_DEG)
    return _rotate_about_back_hinge(result, -BACK_RAKE_DEG)


def _gate_retract_then_fold(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Prove one A06/A07 hinge, a readable low beam and Focus-only +420 motion."""

    forbidden_tokens = (
        "closed_field",
        "weather_vault",
        "backrest_cowl",
        "backrest_lid",
        "continuity_skirt",
        "travel_skirt",
    )
    forbidden = {
        state: sorted(
            part.name
            for part in states[state]
            if any(token in part.name.lower() for token in forbidden_tokens)
        )
        for state in STATES
    }
    backrests = {
        state: _part(states[state], "A06_backrest_weather_shell")
        for state in STATES
    }
    normalised = {
        state: _normalised_backrest(part.shape, state)
        for state, part in backrests.items()
    }
    reference = normalised["ride"]
    reference_box = _Box.from_shape(reference)
    for state in STATES:
        part = backrests[state]
        candidate = normalised[state]
        candidate_box = _Box.from_shape(candidate)
        symmetric_difference = float(
            reference.cut(candidate).Volume()
            + candidate.cut(reference).Volume()
        )
        volume_delta = abs(float(reference.Volume()) - float(candidate.Volume()))
        volume_relative = volume_delta / max(abs(float(reference.Volume())), 1.0e-9)
        area_delta = abs(float(reference.Area()) - float(candidate.Area()))
        bound_delta = max(
            abs(a - b)
            for a, b in zip(
                (
                    reference_box.xmin,
                    reference_box.xmax,
                    reference_box.ymin,
                    reference_box.ymax,
                    reference_box.zmin,
                    reference_box.zmax,
                ),
                (
                    candidate_box.xmin,
                    candidate_box.xmax,
                    candidate_box.ymin,
                    candidate_box.ymax,
                    candidate_box.zmin,
                    candidate_box.zmax,
                ),
            )
        )
        manufacturing_void_probe = (
            cq.Workplane("XY")
            .box(2.0, 2.0, 2.0)
            .translate((258.5, 150.0, 800.0))
            .val()
        )
        manufacturing_void_common = _intersection_volume(
            candidate,
            manufacturing_void_probe,
        )
        side_wall_measurements: dict[str, float] = {}
        for label, y in (("left", -230.0), ("right", 230.0)):
            wall_probe = (
                cq.Workplane("XY")
                .box(1.0, 12.0, 1.0)
                .translate((258.5, y, 800.0))
                .val()
            )
            wall_section = candidate.intersect(wall_probe)
            wall_volume = float(wall_section.Volume())
            side_wall_measurements[label] = (
                0.0
                if wall_volume <= BOOLEAN_TOLERANCE_MM3
                else float(wall_section.BoundingBox().ylen)
            )
        candidate_bbox_volume = (
            candidate_box.lengths[0]
            * candidate_box.lengths[1]
            * candidate_box.lengths[2]
        )
        solid_to_bbox_volume_ratio = float(candidate.Volume()) / max(
            candidate_bbox_volume,
            1.0e-9,
        )
        book.add(
            f"a06.{state}.same_backrest_rigid_pose",
            not forbidden[state]
            and part.metadata.get("physical_occurrence_id")
            == "E6-A06-BACKREST-WEATHER-SHELL"
            and part.metadata.get("physical_part_conserved") is True
            and part.metadata.get("master_has_mast_cutout") is True
            and part.metadata.get("same_backrest_not_extra_cover") is True
            and part.metadata.get("manufacturing_hollow_shell") is True
            and abs(
                float(
                    part.metadata.get(
                        "manufacturing_shell_nominal_wall_mm",
                        -1.0,
                    )
                )
                - 4.0
            )
            <= 0.01
            and abs(
                float(part.metadata.get("manufacturing_lower_closure_mm", -1.0))
                - 4.0
            )
            <= 0.01
            and float(part.metadata.get("manufacturing_roof_minimum_mm", 0.0))
            >= 8.0
            and manufacturing_void_common <= BOOLEAN_TOLERANCE_MM3
            and all(
                3.8 <= value <= 4.2
                for value in side_wall_measurements.values()
            )
            and 0.01 <= solid_to_bbox_volume_ratio <= 0.25
            and symmetric_difference <= 0.01
            and (volume_delta <= 0.05 or volume_relative <= 1.0e-8)
            and area_delta <= 0.01
            and bound_delta <= 0.01,
            evidence_kind="inverse_rigid_transform_brep_symmetric_difference_and_hollow_wall_probes",
            requirement=(
                "Every state must use the same channel-integrated A06 trapezoidal backrest; Follow may only apply the released hinge rotation and may not add a field shell, vault, cowl or lid."
            ),
            part=part.name,
            pose=part.metadata.get("pose"),
            physical_occurrence_id=part.metadata.get("physical_occurrence_id"),
            forbidden_occurrences=forbidden[state],
            normalised_bounds=candidate_box.to_dict(),
            normalised_symmetric_difference_mm3=round(symmetric_difference, 9),
            normalised_volume_delta_mm3=round(volume_delta, 9),
            normalised_volume_relative=volume_relative,
            normalised_area_delta_mm2=round(area_delta, 9),
            normalised_max_bound_delta_mm=round(bound_delta, 9),
            manufacturing_void_probe_common_mm3=round(
                manufacturing_void_common,
                9,
            ),
            measured_manufacturing_side_wall_mm={
                key: round(value, 6)
                for key, value in side_wall_measurements.items()
            },
            solid_to_bbox_volume_ratio=round(
                solid_to_bbox_volume_ratio,
                9,
            ),
        )

    a07_by_state = {
        state: {
            part.name: part
            for part in states[state]
            if part.name.startswith("A07_")
        }
        for state in STATES
    }

    canonical_layout = (
        A07_CANONICAL_EXTERIOR_NAMES | A07_CANONICAL_INTERNAL_NAMES
    )
    reference_cmf = {
        name: (
            a07_by_state["ride"][name].color,
            a07_by_state["ride"][name].material,
            a07_by_state["ride"][name].metadata.get("material_family"),
        )
        for name in canonical_layout
        if name in a07_by_state["ride"]
    }
    canonical_state_evidence: dict[str, object] = {}
    canonical_pass = set(reference_cmf) == canonical_layout
    for state in STATES:
        occurrences = a07_by_state[state]
        names = set(occurrences)
        exterior_names = {
            name
            for name, occurrence in occurrences.items()
            if exterior_visibility_reason(state, occurrence)[0]
        }
        internal_names = names - exterior_names
        physical_ids = [
            occurrence.metadata.get("physical_occurrence_id")
            for occurrence in occurrences.values()
        ]
        cmf_mismatches = sorted(
            name
            for name in canonical_layout & names
            if (
                occurrences[name].color,
                occurrences[name].material,
                occurrences[name].metadata.get("material_family"),
            )
            != reference_cmf.get(name)
        )
        forbidden_covers = sorted(
            name
            for name in names
            if name not in canonical_layout
            and any(
                token in name.lower()
                for token in ("cover", "cowl", "lid", "shroud", "vault")
            )
        )
        state_pass = (
            names == canonical_layout
            and exterior_names == A07_CANONICAL_EXTERIOR_NAMES
            and internal_names == A07_CANONICAL_INTERNAL_NAMES
            and all(bool(value) for value in physical_ids)
            and len(set(physical_ids)) == len(physical_ids)
            and not cmf_mismatches
            and not forbidden_covers
        )
        canonical_pass = canonical_pass and state_pass
        canonical_state_evidence[state] = {
            "status": "PASS" if state_pass else "FAIL",
            "layout_inventory": sorted(names),
            "exterior_inventory": sorted(exterior_names),
            "internal_inventory": sorted(internal_names),
            "missing_layout_occurrences": sorted(canonical_layout - names),
            "unexpected_layout_occurrences": sorted(names - canonical_layout),
            "missing_exterior_occurrences": sorted(
                A07_CANONICAL_EXTERIOR_NAMES - exterior_names
            ),
            "unexpected_exterior_occurrences": sorted(
                exterior_names - A07_CANONICAL_EXTERIOR_NAMES
            ),
            "physical_occurrence_ids": physical_ids,
            "cmf_mismatches_to_ride": cmf_mismatches,
            "forbidden_cover_occurrences": forbidden_covers,
        }
    book.add(
        "a07.four_state.canonical_exterior_inventory_and_cmf",
        canonical_pass,
        evidence_kind=(
            "frozen_layout_exterior_internal_inventory_occurrence_id_and_cmf"
        ),
        requirement=(
            "The same thirteen A07 exterior occurrences and two internal lock "
            "pins exist in Follow, Ride, Cafe and Focus.  Follow exposes the "
            "complete co-folded mast with identical CMF and may not add a "
            "cover, cowl, lid, shroud or vault."
        ),
        canonical_exterior_inventory=sorted(A07_CANONICAL_EXTERIOR_NAMES),
        canonical_internal_inventory=sorted(A07_CANONICAL_INTERNAL_NAMES),
        states=canonical_state_evidence,
    )

    # Ride and Cafe are physically identical low states.  This is an exact
    # world-pose comparison; a matching visibility label cannot make a hidden
    # or moved terminal pass.
    ride_names = set(a07_by_state["ride"])
    cafe_names = set(a07_by_state["cafe"])
    follow_names = set(a07_by_state["follow"])
    low_pose_evidence: dict[str, Any] = {}
    low_pose_pass = bool(ride_names) and ride_names == cafe_names
    for name in sorted(ride_names & cafe_names):
        evidence = _brep_pose_evidence(
            a07_by_state["ride"][name].shape,
            a07_by_state["cafe"][name].shape,
        )
        low_pose_evidence[name] = evidence
        low_pose_pass = low_pose_pass and _brep_pose_matches(evidence)
    book.add(
        "a07.ride_cafe.same_low_world_pose",
        low_pose_pass,
        evidence_kind="direct_world_pose_brep_symmetric_difference",
        requirement=(
            "Ride and Cafe must expose the same complete A07 low-state object; "
            "neither state may substitute a service-core stow or metadata-only visibility change."
        ),
        ride_inventory=sorted(ride_names),
        cafe_inventory=sorted(cafe_names),
        comparisons=low_pose_evidence,
    )

    ride_inventory = {
        name: a07_by_state["ride"][name].metadata.get(
            "physical_occurrence_id"
        )
        for name in ride_names
    }
    follow_inventory = {
        name: a07_by_state["follow"][name].metadata.get(
            "physical_occurrence_id"
        )
        for name in follow_names
    }
    forbidden_follow_covers = sorted(
        name
        for name in follow_names
        if name.lower().startswith("a07_follow_")
        and any(
            token in name.lower()
            for token in ("cover", "cowl", "lid", "shroud", "vault")
        )
    )
    book.add(
        "a07.follow.same_physical_inventory_as_low",
        bool(ride_inventory)
        and follow_inventory == ride_inventory
        and not forbidden_follow_covers,
        evidence_kind="cross_state_named_physical_occurrence_inventory",
        requirement=(
            "Follow must expose the same A07 physical occurrence inventory as "
            "the low state and may change only its shared-hinge pose; a "
            "Follow-only mast cover, cowl, lid, shroud or vault is forbidden."
        ),
        ride_inventory=ride_inventory,
        follow_inventory=follow_inventory,
        follow_only_occurrences=sorted(follow_names - ride_names),
        missing_in_follow=sorted(ride_names - follow_names),
        forbidden_follow_covers=forbidden_follow_covers,
    )

    focus_names = set(a07_by_state["focus"])
    book.add(
        "a07.focus.same_physical_inventory_as_low",
        bool(ride_names) and focus_names == ride_names,
        evidence_kind="cross_state_physical_occurrence_inventory",
        requirement=(
            "Focus changes the A07 moving pose and parks the same shutter; it may "
            "not introduce a focus-only exterior pocket, sleeve or terminal body."
        ),
        ride_inventory=sorted(ride_names),
        focus_inventory=sorted(focus_names),
        focus_only_occurrences=sorted(focus_names - ride_names),
        missing_in_focus=sorted(ride_names - focus_names),
    )

    # The crowned low terminal is a visible/readable object.  Its positive-Y
    # privacy pocket makes the shell deliberately asymmetric, so the structural
    # X=310 datum comes from the controlled mast-axis metadata rather than the
    # terminal bounding-box centre.  Three real +Z witness
    # corridors across its span must remain clear of all non-A07 solids.
    for state in ("ride", "cafe"):
        beam = _part(states[state], "A07_sensor_beam_shell")
        beam_box = _Box.from_shape(beam.shape)
        beam_axis_x = beam.metadata.get("controlled_axis_x_mm")
        sightline_axis_x = (
            float(beam_axis_x)
            if isinstance(beam_axis_x, (int, float))
            else beam_box.center[0]
        )
        other_parts = [
            part for part in states[state] if not part.name.startswith("A07_")
        ]
        ceiling = max(
            [beam_box.zmax + 50.0]
            + [_Box.from_shape(part.shape).zmax + 5.0 for part in other_parts]
        )
        obstructions: dict[str, dict[str, float]] = {}
        for y_offset in (-80.0, 0.0, 80.0):
            height = ceiling - (beam_box.zmax + 0.05)
            ray = (
                cq.Workplane("XY")
                .box(0.5, 0.5, height)
                .translate(
                    (
                        sightline_axis_x,
                        beam_box.center[1] + y_offset,
                        beam_box.zmax + 0.05 + height / 2.0,
                    )
                )
                .val()
            )
            hits: dict[str, float] = {}
            for part in other_parts:
                common = _intersection_volume(part.shape, ray)
                if common > BOOLEAN_TOLERANCE_MM3:
                    hits[part.name] = round(common, 9)
            obstructions[str(y_offset)] = hits
        book.add(
            f"a07.{state}.low_sensor_beam_exterior_readable",
            isinstance(beam_axis_x, (int, float))
            and abs(float(beam_axis_x) - A07_MAST_AXIS_X_MM) <= 0.05
            and abs(beam_box.center[2] - A07_LOW_BEAM_CENTER_Z_MM) <= 0.05
            and abs(
                beam_box.lengths[1] - A07_TERMINAL_NOMINAL_WIDTH_Y_MM
            ) <= 2.0
            and beam_box.xmin <= A07_MAST_AXIS_X_MM <= beam_box.xmax
            and all(not hits for hits in obstructions.values()),
            evidence_kind="brep_bounds_and_three_exterior_sightline_booleans",
            requirement=(
                "Ride/Cafe retain the same readable crowned low terminal registered to "
                "the one-piece spine axis X=310 "
                "at Z=1040; it may not disappear inside the rear service core."
            ),
            beam_bounds=beam_box.to_dict(),
            controlled_axis_x_mm=beam_axis_x,
            upward_sightline_obstructions_mm3=obstructions,
            required_center_mm=(
                A07_MAST_AXIS_X_MM,
                "asymmetric_terminal_plan",
                A07_LOW_BEAM_CENTER_Z_MM,
            ),
        )

    # Focus leaves the fixed outer sleeve at the low-state transform and moves
    # every structural inner sleeve plus the terminal by exactly +420 Z.
    fixed_ride = _part(states["ride"], "A07_mast_fixed_outer_sleeve")
    fixed_focus = _part(states["focus"], "A07_mast_fixed_outer_sleeve")
    fixed_evidence = _brep_pose_evidence(fixed_ride.shape, fixed_focus.shape)
    fixed_focus_axis = fixed_focus.metadata.get("controlled_axis_x_mm")
    book.add(
        "a07.focus.fixed_outer_same_world_pose_as_low",
        _brep_pose_matches(fixed_evidence)
        and isinstance(fixed_focus_axis, (int, float))
        and abs(float(fixed_focus_axis) - A07_MAST_AXIS_X_MM) <= 0.05,
        evidence_kind="direct_world_pose_brep_symmetric_difference",
        requirement=(
            "The fixed A07 outer sleeve remains on source axis X=310 in Focus; "
            "no whole-stack rearward or upward rebase is permitted."
        ),
        comparison=fixed_evidence,
        controlled_axis_x_mm=fixed_focus_axis,
        required_translation_mm=(0.0, 0.0, 0.0),
    )

    moving_names = sorted(
        name
        for name in ride_names
        if name.startswith("A07_mast_moving_inner_sleeve")
        or name.startswith("A07_sensor_beam_")
        or name.startswith("A07_fill_light_visible_window_")
        or name
        in {
            "A07_microphone_acoustic_mesh",
            "A07_environment_sensor_grille",
        }
    )
    moving_evidence: dict[str, Any] = {}
    moving_pass = bool(moving_names)
    for name in moving_names:
        ride_part = a07_by_state["ride"].get(name)
        focus_part = a07_by_state["focus"].get(name)
        if ride_part is None or focus_part is None:
            moving_pass = False
            moving_evidence[name] = {"missing": True}
            continue
        ride_box = _Box.from_shape(ride_part.shape)
        focus_box = _Box.from_shape(focus_part.shape)
        translation = tuple(
            b - a for a, b in zip(ride_box.center, focus_box.center)
        )
        normalised = focus_part.shape.translate(
            (0.0, 0.0, -A07_FOCUS_TRANSLATION_MM)
        )
        evidence = _brep_pose_evidence(ride_part.shape, normalised)
        translation_error = max(
            abs(actual - expected)
            for actual, expected in zip(
                translation,
                (0.0, 0.0, A07_FOCUS_TRANSLATION_MM),
            )
        )
        evidence["actual_world_translation_mm"] = translation
        evidence["translation_error_mm"] = translation_error
        moving_evidence[name] = evidence
        moving_pass = (
            moving_pass
            and _brep_pose_matches(evidence)
            and translation_error <= 0.01
        )
    focus_beam_box = _Box.from_shape(
        _part(states["focus"], "A07_sensor_beam_shell").shape
    )
    focus_beam_axis_x = _part(
        states["focus"], "A07_sensor_beam_shell"
    ).metadata.get("controlled_axis_x_mm")
    book.add(
        "a07.focus.moving_inner_and_terminal_plus_420_only",
        moving_pass
        and isinstance(focus_beam_axis_x, (int, float))
        and abs(float(focus_beam_axis_x) - A07_MAST_AXIS_X_MM) <= 0.05
        and abs(focus_beam_box.center[2] - A07_FOCUS_BEAM_CENTER_Z_MM) <= 0.05,
        evidence_kind="inverse_translation_brep_symmetric_difference",
        requirement=(
            "Only the A07 moving inner member(s) and sensor terminal translate in "
            "Focus, and each applies the single controlled vector (0,0,+420) mm."
        ),
        moving_occurrences=moving_names,
        comparisons=moving_evidence,
        focus_beam_bounds=focus_beam_box.to_dict(),
        controlled_axis_x_mm=focus_beam_axis_x,
        required_translation_mm=(0.0, 0.0, A07_FOCUS_TRANSLATION_MM),
    )

    # A06 and A07 receive the same Follow hinge transform.  The inverse of the
    # one A06 hinge must recover the Ride B-Rep for every structural member.
    follow_names = set(a07_by_state["follow"])
    follow_package_names = sorted(ride_names)
    common_hinge_evidence: dict[str, Any] = {}
    common_hinge_pass = bool(follow_package_names) and follow_names == ride_names
    for name in ("A06_backrest_weather_shell", *follow_package_names):
        ride_part = (
            backrests["ride"]
            if name == "A06_backrest_weather_shell"
            else a07_by_state["ride"].get(name)
        )
        follow_part = (
            backrests["follow"]
            if name == "A06_backrest_weather_shell"
            else a07_by_state["follow"].get(name)
        )
        if ride_part is None or follow_part is None:
            common_hinge_pass = False
            common_hinge_evidence[name] = {"missing": True}
            continue
        normalised = _rotate_about_back_hinge(
            follow_part.shape,
            -BACK_FOLD_DEG,
        )
        evidence = _brep_pose_evidence(ride_part.shape, normalised)
        common_hinge_evidence[name] = evidence
        common_hinge_pass = common_hinge_pass and _brep_pose_matches(evidence)
    book.add(
        "a06_a07.follow.same_common_hinge_transform",
        common_hinge_pass,
        evidence_kind="shared_inverse_hinge_brep_symmetric_difference",
        requirement=(
            "Follow must fold the same A06 trapezoidal backrest and A07 structural "
            "package through one common hinge transform; it may not relocate A07 into a service core."
        ),
        hinge_origin_mm=BACK_HINGE,
        follow_rotation_deg=BACK_FOLD_DEG,
        ride_inventory=sorted(ride_names),
        follow_inventory=sorted(follow_names),
        comparisons=common_hinge_evidence,
    )

    # The same A06 trapezoid is the only Follow weather surface.  Judge the
    # folded package after inverse common-hinge normalisation so enclosure is
    # expressed in stable product axes.  The intended architecture is an A06
    # side/rear U-channel with an open +Z Focus deployment throat; requiring an
    # upward cover witness here would silently mandate the prohibited top cap.
    follow_backrest = backrests["follow"]
    allowed_follow_a06_surfaces = {
        "A06_backrest_weather_shell",
        "A06_backrest_contact_panel",
    }
    additional_follow_a06_surfaces = sorted(
        part.name
        for part in states["follow"]
        if part.module.upper() == "A06"
        and part.name not in allowed_follow_a06_surfaces
        and part.metadata.get("a06_motion_hardware") is not True
    )
    normalised_backrest = _rotate_about_back_hinge(
        follow_backrest.shape,
        -BACK_FOLD_DEG,
    )
    backrest_box = _Box.from_shape(normalised_backrest)
    follow_members = [
        a07_by_state["follow"][name]
        for name in follow_package_names
        if name in a07_by_state["follow"]
    ]
    normalised_members = {
        part.name: _rotate_about_back_hinge(part.shape, -BACK_FOLD_DEG)
        for part in follow_members
    }
    package_box = _union_boxes(normalised_members.values())

    def lateral_probe(
        part_box: _Box,
        station_z: float,
        direction: str,
    ) -> float:
        section_mm = 0.5
        offset_mm = 0.05
        x, y, _ = part_box.center
        if direction == "-x":
            start, end = part_box.xmin - offset_mm, backrest_box.xmin - 2.0
            size = (abs(end - start), section_mm, section_mm)
            center = ((start + end) / 2.0, y, station_z)
        elif direction == "+x":
            start, end = part_box.xmax + offset_mm, backrest_box.xmax + 2.0
            size = (abs(end - start), section_mm, section_mm)
            center = ((start + end) / 2.0, y, station_z)
        elif direction == "-y":
            start, end = part_box.ymin - offset_mm, backrest_box.ymin - 2.0
            size = (section_mm, abs(end - start), section_mm)
            center = (x, (start + end) / 2.0, station_z)
        elif direction == "+y":
            start, end = part_box.ymax + offset_mm, backrest_box.ymax + 2.0
            size = (section_mm, abs(end - start), section_mm)
            center = (x, (start + end) / 2.0, station_z)
        else:  # pragma: no cover - closed local contract
            raise ValueError(f"unsupported A07 surround direction {direction!r}")
        if min(size) <= 0.0:
            return 0.0
        probe = cq.Workplane("XY").box(*size).translate(center).val()
        return _intersection_volume(probe, normalised_backrest)

    # Only the fixed sleeve and the one-piece moving spine pass through the
    # A06 channel and therefore need three-station lateral U-surround proof.
    # The crowned terminal and its inserts sit above the 1003 mm shoulder with
    # a measured dry gap; requiring U-surround around them would reintroduce
    # the prohibited rigid top vault.  The compliant throat gasket is an
    # intentional sealing interface fixed to A06, not a dry-running member.
    channel_member_names = (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
    )
    channel_members = [
        a07_by_state["follow"][name]
        for name in channel_member_names
        if name in a07_by_state["follow"]
    ]
    interface_evidence: dict[str, Any] = {}
    for part in follow_members:
        common = _intersection_volume(part.shape, follow_backrest.shape)
        clearance = float(part.shape.distance(follow_backrest.shape))
        compliant_seal = part.name == "A07_mast_throat_weather_gasket"
        interface_evidence[part.name] = {
            "a06_common_volume_mm3": round(common, 9),
            "a06_clearance_mm": round(clearance, 6),
            "intentional_compliant_seal_interface": compliant_seal,
            "interface_pass": (
                common <= BOOLEAN_TOLERANCE_MM3
                and (
                    compliant_seal
                    or clearance
                    >= A07_MINIMUM_DRY_CLEARANCE_MM
                    - DISTANCE_TOLERANCE_MM
                )
            ),
        }

    coverage_evidence: dict[str, Any] = {}
    for part in channel_members:
        part_box = _Box.from_shape(normalised_members[part.name])
        stations: list[dict[str, Any]] = []
        for fraction in (0.25, 0.5, 0.75):
            station_z = part_box.zmin + (part_box.zmax - part_box.zmin) * fraction
            hits = {
                direction: lateral_probe(part_box, station_z, direction)
                for direction in ("-x", "+x", "-y", "+y")
            }
            stations.append(
                {
                    "fraction_of_part_height": fraction,
                    "station_z_mm": round(station_z, 6),
                    "directional_a06_common_volume_mm3": {
                        direction: round(value, 9)
                        for direction, value in hits.items()
                    },
                    "u_channel_surround_pass": (
                        hits["-y"] > BOOLEAN_TOLERANCE_MM3
                        and hits["+y"] > BOOLEAN_TOLERANCE_MM3
                        and max(hits["-x"], hits["+x"])
                        > BOOLEAN_TOLERANCE_MM3
                    ),
                }
            )
        coverage_evidence[part.name] = {
            "bounds": part_box.to_dict(),
            **interface_evidence[part.name],
            "lateral_surround_stations": stations,
        }
    lateral_surround_pass = (
        len(channel_members) == len(channel_member_names)
        and len(coverage_evidence) == len(channel_member_names)
        and all(
        all(
            station["u_channel_surround_pass"]
            for station in item["lateral_surround_stations"]
        )
        for item in coverage_evidence.values()
        )
    )

    # Prove the same A06 B-Rep has a genuine open deployment throat.  Endpoint
    # transforms alone could miss a cap crossed midway through the +420 stroke,
    # so sample the actual moving sleeves and beam at nine physical B-Rep poses.
    # The 52.5 mm pitch is smaller than the 64 mm terminal height, which makes
    # a transverse cap anywhere on this pure +Z path observable at a sample.
    egress_names = sorted(
        name
        for name in ride_names
        if "mast_moving_inner_sleeve" in name
        or name == "A07_sensor_beam_shell"
    )
    focus_egress_pass = bool(egress_names)
    focus_egress_evidence: dict[str, Any] = {}
    ride_backrest = backrests["ride"]
    for name in egress_names:
        ride_part = a07_by_state["ride"].get(name)
        if ride_part is None:
            focus_egress_pass = False
            focus_egress_evidence[name] = {"missing": True}
            continue
        samples: list[dict[str, float]] = []
        for stroke_mm in (
            0.0,
            52.5,
            105.0,
            157.5,
            210.0,
            262.5,
            315.0,
            367.5,
            420.0,
        ):
            posed = ride_part.shape.translate((0.0, 0.0, stroke_mm))
            common = _intersection_volume(posed, ride_backrest.shape)
            clearance = float(posed.distance(ride_backrest.shape))
            samples.append(
                {
                    "stroke_mm": stroke_mm,
                    "a06_common_volume_mm3": round(common, 9),
                    "a06_clearance_mm": round(clearance, 6),
                }
            )
            focus_egress_pass = (
                focus_egress_pass
                and common <= BOOLEAN_TOLERANCE_MM3
                and clearance
                >= A07_MINIMUM_DRY_CLEARANCE_MM - DISTANCE_TOLERANCE_MM
            )
        focus_egress_evidence[name] = {"samples": samples}

    book.add(
        "a06_a07.follow.same_trapezoid_is_only_weather_cover",
        not forbidden["follow"]
        and not additional_follow_a06_surfaces
        and len(follow_members) == len(follow_package_names)
        and lateral_surround_pass
        and focus_egress_pass
        and all(item["interface_pass"] for item in interface_evidence.values()),
        evidence_kind="inverse_hinge_brep_u_channel_surround_and_open_egress_sweep",
        requirement=(
            "Follow exposes only the same folded A06 trapezoidal backrest surface; "
            "its real side/rear U-channel laterally surrounds the fixed sleeve "
            "and one-piece moving spine with dry clearance.  The crowned terminal "
            "remains above the shoulder without another vault, cowl, lid or cap, "
            "while the Focus deployment throat remains open."
        ),
        forbidden_occurrences=forbidden["follow"],
        allowed_follow_a06_surface_occurrences=sorted(
            allowed_follow_a06_surfaces
        ),
        additional_follow_a06_surface_occurrences=(
            additional_follow_a06_surfaces
        ),
        folded_backrest_bounds=backrest_box.to_dict(),
        folded_a07_bounds=package_box.to_dict(),
        evidence_frame="actual Follow B-Reps inverse-rotated to the common A06 hinge frame",
        lateral_u_channel_surround_pass=lateral_surround_pass,
        focus_open_egress_sweep_pass=focus_egress_pass,
        focus_open_egress_sweep=focus_egress_evidence,
        minimum_dry_clearance_mm=A07_MINIMUM_DRY_CLEARANCE_MM,
        channel_members=list(channel_member_names),
        channel_coverage=coverage_evidence,
        all_a07_a06_interfaces=interface_evidence,
    )


def _gate_fixed_backrest_root_shoulders(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Prove two hollow A04 root shoulders are fixed and conserved in all states."""

    # A collision-free cosmetic fold does not establish a production load
    # path.  Keep this inventory gate fail-closed until the final B-Reps carry
    # the hinge shaft through two bearings and expose independent positive-lock
    # witnesses plus a no-power release.  Metadata on the weather shell is not
    # accepted as a substitute for physical occurrences.
    required_motion_hardware = {
        "A06_backrest_hinge_shaft",
        "A06_backrest_hinge_bearing_left",
        "A06_backrest_hinge_bearing_right",
        "A06_backrest_positive_lock_left",
        "A06_backrest_positive_lock_right",
        "A06_backrest_lock_witness_left",
        "A06_backrest_lock_witness_right",
        "A06_backrest_manual_release",
    }
    motion_hardware_inventory = {
        state: sorted(
            part.name
            for part in states[state]
            if part.name in required_motion_hardware
        )
        for state in STATES
    }
    motion_hardware_ids = {
        state: {
            part.name: part.metadata.get("physical_occurrence_id")
            for part in states[state]
            if part.name in required_motion_hardware
        }
        for state in STATES
    }
    book.add(
        "a04_a06.production_hinge_bearings_positive_locks_and_release_inventory",
        all(
            set(motion_hardware_inventory[state]) == required_motion_hardware
            and all(motion_hardware_ids[state].values())
            for state in STATES
        )
        and all(
            motion_hardware_ids[state] == motion_hardware_ids["ride"]
            for state in STATES
        ),
        evidence_kind="four_state_physical_motion_hardware_inventory",
        requirement=(
            "The folding A06 trapezoid must have one physical hinge shaft, two "
            "physical bearings, independent left/right positive locks and lock "
            "witnesses, and a no-power manual release in every state. A swept "
            "weather-shell transform alone is not a production load path."
        ),
        required_occurrences=sorted(required_motion_hardware),
        inventories=motion_hardware_inventory,
        physical_occurrence_ids=motion_hardware_ids,
        metadata_only_substitute_permitted=False,
        production_certification_claimed=False,
    )

    # Inventory alone can still conceal a render-only mechanism.  Prove the
    # moving shaft is one conserved B-Rep, the six fixed hardware occurrences
    # remain world-invariant, both endpoint pins sit in real detent bores, and
    # the completely retracted pins plus fixed carriers clear the full 101-pose
    # A06 fold.  Distances are evaluated on the final state B-Reps.
    hardware_by_state = {
        state: {
            part.name: part
            for part in states[state]
            if part.name in required_motion_hardware
        }
        for state in STATES
    }
    fixed_hardware_names = required_motion_hardware - {
        "A06_backrest_hinge_shaft"
    }
    mechanism_brep_pass = all(
        set(hardware_by_state[state]) == required_motion_hardware
        for state in STATES
    )
    fixed_brep_evidence: dict[str, dict[str, Any]] = {}
    shaft_brep_evidence: dict[str, Any] = {}
    endpoint_evidence: dict[str, Any] = {}
    sweep_evidence: dict[str, Any] = {"evaluated": False}
    if mechanism_brep_pass:
        reference = hardware_by_state["ride"]
        for name in sorted(fixed_hardware_names):
            fixed_brep_evidence[name] = {}
            for state in STATES:
                evidence = _brep_pose_evidence(
                    reference[name].shape,
                    hardware_by_state[state][name].shape,
                )
                fixed_brep_evidence[name][state] = evidence
                mechanism_brep_pass = (
                    mechanism_brep_pass and _brep_pose_matches(evidence)
                )

        ride_shaft = reference["A06_backrest_hinge_shaft"].shape
        for state in STATES:
            candidate = hardware_by_state[state][
                "A06_backrest_hinge_shaft"
            ].shape
            if state == "follow":
                candidate = _rotate_about_back_hinge(
                    candidate,
                    -BACK_FOLD_DEG,
                )
            evidence = _brep_pose_evidence(ride_shaft, candidate)
            shaft_brep_evidence[state] = evidence
            mechanism_brep_pass = (
                mechanism_brep_pass and _brep_pose_matches(evidence)
            )

        for state in STATES:
            shaft = hardware_by_state[state][
                "A06_backrest_hinge_shaft"
            ]
            state_endpoint: dict[str, Any] = {}
            for side_name in ("left", "right"):
                side = -1.0 if side_name == "left" else 1.0
                bearing = hardware_by_state[state][
                    f"A06_backrest_hinge_bearing_{side_name}"
                ]
                pin = hardware_by_state[state][
                    f"A06_backrest_positive_lock_{side_name}"
                ]
                witness = hardware_by_state[state][
                    f"A06_backrest_lock_witness_{side_name}"
                ]
                shaft_bearing_common = _intersection_volume(
                    shaft.shape,
                    bearing.shape,
                )
                shaft_bearing_gap = float(
                    shaft.shape.distance(bearing.shape)
                )
                pin_shaft_common = _intersection_volume(
                    pin.shape,
                    shaft.shape,
                )
                pin_shaft_gap = float(pin.shape.distance(shaft.shape))
                pin_bearing_common = _intersection_volume(
                    pin.shape,
                    bearing.shape,
                )
                pin_bearing_gap = float(pin.shape.distance(bearing.shape))
                a05_shell = _part(
                    states[state],
                    f"A05_armrest_table_bay_shell_{side_name}",
                )
                shell_bearing_common = _intersection_volume(
                    a05_shell.shape,
                    bearing.shape,
                )
                shell_bearing_gap = float(
                    a05_shell.shape.distance(bearing.shape)
                )
                shell_shaft_common = _intersection_volume(
                    a05_shell.shape,
                    shaft.shape,
                )
                shell_shaft_gap = float(
                    a05_shell.shape.distance(shaft.shape)
                )
                disc_center_y = side * A06_LOCK_STATION_Y_MM
                disc_y_min = disc_center_y - A06_LOCK_DISC_AXIAL_MM / 2.0
                lock_disc = cq.Solid.makeCylinder(
                    A06_LOCK_DISC_RADIUS_MM,
                    A06_LOCK_DISC_AXIAL_MM,
                    cq.Vector(BACK_HINGE[0], disc_y_min, BACK_HINGE[2]),
                    cq.Vector(0.0, 1.0, 0.0),
                )
                shell_disc_common = _intersection_volume(
                    a05_shell.shape,
                    lock_disc,
                )
                shell_disc_gap = float(
                    a05_shell.shape.distance(lock_disc)
                )
                shell_trim_pass = (
                    len(a05_shell.shape.Solids()) == 1
                    and a05_shell.shape.isValid()
                    and shell_bearing_common <= BOOLEAN_TOLERANCE_MM3
                    and shell_bearing_gap >= 0.59
                    and shell_shaft_common <= BOOLEAN_TOLERANCE_MM3
                    and shell_shaft_gap >= 0.69
                    and shell_disc_common <= BOOLEAN_TOLERANCE_MM3
                    and shell_disc_gap >= 0.69
                    and a05_shell.metadata.get(
                        "a06_fixed_bearing_seat_present"
                    )
                    is True
                    and abs(
                        float(
                            a05_shell.metadata.get(
                                "a06_lock_disc_clearance_diameter_mm",
                                0.0,
                            )
                        )
                        - 2.0 * (A06_LOCK_DISC_RADIUS_MM + 0.7)
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and float(
                        a05_shell.metadata.get(
                            "a06_lock_disc_axial_clearance_each_side_mm",
                            0.0,
                        )
                    )
                    >= 0.7
                )
                side_pass = (
                    len(bearing.shape.Solids()) == 1
                    and len(pin.shape.Solids()) == 1
                    and shaft_bearing_common <= BOOLEAN_TOLERANCE_MM3
                    and shaft_bearing_gap >= 0.69
                    and pin_shaft_common <= BOOLEAN_TOLERANCE_MM3
                    and 0.29 <= pin_shaft_gap <= 0.31
                    and pin_bearing_common <= BOOLEAN_TOLERANCE_MM3
                    and 0.29 <= pin_bearing_gap <= 0.31
                    and pin.metadata.get("current_lock_state")
                    == "engaged_endpoint"
                    and float(
                        pin.metadata.get("commanded_motion_retraction_mm", 0.0)
                    )
                    >= 32.0
                    and witness.metadata.get(
                        "mechanically_coupled_to_lock_pin"
                    )
                    is True
                    and shell_trim_pass
                )
                mechanism_brep_pass = mechanism_brep_pass and side_pass
                state_endpoint[side_name] = {
                    "shaft_bearing_common_mm3": round(
                        shaft_bearing_common,
                        9,
                    ),
                    "shaft_bearing_gap_mm": round(shaft_bearing_gap, 6),
                    "pin_shaft_common_mm3": round(pin_shaft_common, 9),
                    "pin_shaft_radial_gap_mm": round(pin_shaft_gap, 6),
                    "pin_bearing_common_mm3": round(pin_bearing_common, 9),
                    "pin_guide_radial_gap_mm": round(pin_bearing_gap, 6),
                    "a05_trim_interfaces": {
                        "shell": a05_shell.name,
                        "shell_valid_single_solid": (
                            a05_shell.shape.isValid()
                            and len(a05_shell.shape.Solids()) == 1
                        ),
                        "bearing_common_mm3": round(
                            shell_bearing_common,
                            9,
                        ),
                        "bearing_gap_mm": round(shell_bearing_gap, 6),
                        "complete_shaft_common_mm3": round(
                            shell_shaft_common,
                            9,
                        ),
                        "complete_shaft_gap_mm": round(shell_shaft_gap, 6),
                        "lock_disc_common_mm3": round(
                            shell_disc_common,
                            9,
                        ),
                        "lock_disc_gap_mm": round(shell_disc_gap, 6),
                        "required_bearing_gap_mm": 0.6,
                        "required_shaft_and_disc_gap_mm": 0.7,
                        "status": "PASS" if shell_trim_pass else "FAIL",
                    },
                    "status": "PASS" if side_pass else "FAIL",
                }
            manual_release = hardware_by_state[state][
                "A06_backrest_manual_release"
            ]
            rear_surround = _part(
                states[state],
                "A10_rear_service_surround",
            )
            release_surround_common = _intersection_volume(
                manual_release.shape,
                rear_surround.shape,
            )
            release_surround_gap = float(
                manual_release.shape.distance(rear_surround.shape)
            )
            release_surround_pass = (
                release_surround_common <= BOOLEAN_TOLERANCE_MM3
                and release_surround_gap >= 3.0 - DISTANCE_TOLERANCE_MM
            )
            mechanism_brep_pass = (
                mechanism_brep_pass and release_surround_pass
            )
            state_endpoint["manual_release_to_a10_service_surround"] = {
                "common_volume_mm3": round(release_surround_common, 9),
                "minimum_gap_mm": round(release_surround_gap, 6),
                "status": "PASS" if release_surround_pass else "FAIL",
            }
            endpoint_evidence[state] = state_endpoint

        manual_release = reference["A06_backrest_manual_release"]
        shaft_metadata_ok = (
            reference["A06_backrest_hinge_shaft"].metadata.get(
                "torque_coupled_to_retained_backrest_structural_carrier"
            )
            is True
            and reference["A06_backrest_hinge_shaft"].metadata.get(
                "pc_abs_weather_shell_is_primary_load_path"
            )
            is False
        )
        fixed_metadata_ok = all(
            reference[f"A06_backrest_hinge_bearing_{side_name}"].metadata.get(
                "a04_pc_abs_ring_is_primary_load_path"
            )
            is False
            and reference[
                f"A06_backrest_hinge_bearing_{side_name}"
            ].metadata.get("a05_pc_abs_root_is_primary_load_path")
            is False
            and reference[
                f"A06_backrest_hinge_bearing_{side_name}"
            ].metadata.get(
                "structural_outrigger_physical_validation_required"
            )
            is True
            for side_name in ("left", "right")
        )
        release_metadata_ok = (
            manual_release.metadata.get("no_power_release") is True
            and manual_release.metadata.get(
                "independently_drives_both_lock_pins"
            )
            is True
        )
        mechanism_brep_pass = (
            mechanism_brep_pass
            and shaft_metadata_ok
            and fixed_metadata_ok
            and release_metadata_ok
        )

        retracted_pins = []
        for side_name in ("left", "right"):
            pin = reference[f"A06_backrest_positive_lock_{side_name}"]
            retraction = float(
                pin.metadata.get("commanded_motion_retraction_mm", 0.0)
            )
            retracted_pins.append(pin.shape.translate((0.0, 0.0, retraction)))
        fixed_motion_hardware = cq.Compound.makeCompound(
            [
                reference["A06_backrest_hinge_bearing_left"].shape,
                reference["A06_backrest_hinge_bearing_right"].shape,
                *retracted_pins,
            ]
        )
        ride_backrest = _part(
            states["ride"],
            "A06_backrest_weather_shell",
        ).shape
        minimum_shaft_clearance = math.inf
        minimum_shaft_angle = 0.0
        minimum_shell_clearance = math.inf
        minimum_shell_angle = 0.0
        for index in range(101):
            angle = BACK_FOLD_DEG * index / 100.0
            posed_shaft = _rotate_about_back_hinge(ride_shaft, angle)
            posed_shell = _rotate_about_back_hinge(ride_backrest, angle)
            shaft_clearance = float(
                posed_shaft.distance(fixed_motion_hardware)
            )
            shell_clearance = float(
                posed_shell.distance(fixed_motion_hardware)
            )
            if shaft_clearance < minimum_shaft_clearance:
                minimum_shaft_clearance = shaft_clearance
                minimum_shaft_angle = angle
            if shell_clearance < minimum_shell_clearance:
                minimum_shell_clearance = shell_clearance
                minimum_shell_angle = angle
        sweep_pass = (
            minimum_shaft_clearance >= 0.69
            and minimum_shell_clearance >= 4.77
        )
        mechanism_brep_pass = mechanism_brep_pass and sweep_pass
        sweep_evidence = {
            "evaluated": True,
            "sample_count": 101,
            "lock_pins_retracted_mm": 32.0,
            "minimum_shaft_to_fixed_hardware_clearance_mm": round(
                minimum_shaft_clearance,
                6,
            ),
            "minimum_shaft_clearance_fold_angle_deg": round(
                minimum_shaft_angle,
                6,
            ),
            "minimum_weather_shell_to_fixed_hardware_clearance_mm": round(
                minimum_shell_clearance,
                6,
            ),
            "minimum_shell_clearance_fold_angle_deg": round(
                minimum_shell_angle,
                6,
            ),
            "status": "PASS" if sweep_pass else "FAIL",
        }

    book.add(
        "a04_a06.production_hinge_endpoint_brep_and_101_pose_retracted_sweep",
        mechanism_brep_pass,
        evidence_kind=(
            "four_state_exact_brep_endpoint_detents_and_101_pose_retracted_"
            "hinge_sweep"
        ),
        requirement=(
            "The A06 shaft must be torque-coupled to the retained structural "
            "carrier, run in two fixed rebored carriers, engage two independent "
            "real endpoint detents, and clear the same fixed hardware through "
            "all 101 fold poses after complete mechanical pin retraction. PC-ABS "
            "trim is not accepted as the declared primary load path. Each fixed "
            "A05 root shell must remain one valid solid with zero interference "
            "to the bearing, complete shaft and redundant lock disc, including "
            "the released 0.6/0.7 mm trim clearances."
        ),
        fixed_hardware_brep_comparisons=fixed_brep_evidence,
        moving_shaft_pose_normalisation=shaft_brep_evidence,
        endpoint_interfaces=endpoint_evidence,
        fold_sweep=sweep_evidence,
        structural_outrigger_physical_validation_still_required=True,
        production_certification_claimed=False,
    )

    # The retired exposed 72/60/48 mm A09 post stack previously injected a
    # Focus-only A05 "relief" contract here.  The released root now uses a
    # small inner-sidewall port and in-cavity flat guides; its geometry and
    # metal cassette load path are proven by ``_gate_a09_layout_architecture``.
    book.add(
        "a04_a06.structural_outrigger_physical_load_path_validation_complete",
        False,
        severity="advisory",
        evidence_kind="explicit_unclosed_hinge_load_path_validation_register",
        requirement=(
            "Before tooling release, each fixed bearing through-foot needs a "
            "detailed metal chassis outrigger, fastener stack, proof load, fatigue, "
            "impact and tolerance validation. The A04/A05 PC-ABS trim interfaces "
            "are expressly not a substitute for that structural closure."
        ),
        digital_brep_hinge_mechanism_pass=mechanism_brep_pass,
        structural_outrigger_physical_validation_required=True,
        production_certification_claimed=False,
    )

    expected_names = {
        "A04_backrest_root_shoulder_left",
        "A04_backrest_root_shoulder_right",
    }
    inventories: dict[str, list[str]] = {}
    forbidden_cheeks: dict[str, list[str]] = {}
    for state in STATES:
        inventories[state] = sorted(
            part.name
            for part in states[state]
            if part.name.startswith("A04_backrest_root_shoulder_")
        )
        forbidden_cheeks[state] = sorted(
            part.name
            for part in states[state]
            if part.name.startswith("A06_backrest_root_cheek_")
        )
    book.add(
        "a04_a06.root_shoulders.two_fixed_occurrences_all_states",
        all(set(inventories[state]) == expected_names for state in STATES)
        and all(not forbidden_cheeks[state] for state in STATES),
        evidence_kind="four_state_occurrence_inventory",
        requirement=(
            "The two low backrest-root buttresses are fixed A04 body parts in all "
            "four states.  State-specific A06 cheek fragments may not disappear in Follow."
        ),
        expected_inventory=sorted(expected_names),
        inventories=inventories,
        forbidden_a06_cheeks=forbidden_cheeks,
    )

    for side_name in ("left", "right"):
        name = f"A04_backrest_root_shoulder_{side_name}"
        parts = {state: _part(states[state], name) for state in STATES}
        reference = parts["ride"]
        reference_id = reference.metadata.get("physical_occurrence_id")
        comparisons: dict[str, Any] = {}
        interfaces: dict[str, Any] = {}
        passed = True
        for state, part in parts.items():
            comparison = _brep_pose_evidence(reference.shape, part.shape)
            backrest = _part(states[state], "A06_backrest_weather_shell")
            common = _intersection_volume(part.shape, backrest.shape)
            clearance = float(part.shape.distance(backrest.shape))
            box = _Box.from_shape(part.shape)
            bbox_volume = (
                box.lengths[0] * box.lengths[1] * box.lengths[2]
            )
            hollow_ratio = float(part.shape.Volume()) / max(
                bbox_volume,
                1.0e-9,
            )
            comparisons[state] = comparison
            interfaces[state] = {
                "a06_common_volume_mm3": round(common, 9),
                "a06_clearance_mm": round(clearance, 6),
                "solid_to_bbox_volume_ratio": round(hollow_ratio, 9),
                "bounds": box.to_dict(),
            }
            passed = passed and (
                part.module == "A04"
                and part.metadata.get("physical_occurrence_id") == reference_id
                and part.metadata.get("fixed_to") == "A04_body"
                and part.metadata.get("same_brep_all_states") is True
                and part.metadata.get("state_specific_substitute") is False
                and part.metadata.get("independent_valid_solid") is True
                and abs(float(part.metadata.get("nominal_wall_mm", -1.0)) - 4.0)
                <= 0.01
                and float(
                    part.metadata.get("a06_fold_sweep_minimum_clearance_mm", 0.0)
                )
                >= 4.0
                and int(part.metadata.get("service_sliver_count", -1)) == 0
                and len(part.shape.Solids()) == 1
                and part.shape.isValid()
                and 0.02 <= hollow_ratio <= 0.50
                and common <= BOOLEAN_TOLERANCE_MM3
                and clearance >= 4.0 - DISTANCE_TOLERANCE_MM
                and _brep_pose_matches(comparison)
            )
        book.add(
            f"a04_a06.root_shoulder.{side_name}.fixed_hollow_brep_and_fold_clearance",
            passed,
            evidence_kind="four_state_direct_brep_identity_hollow_ratio_and_a06_clearance",
            requirement=(
                "Each A04 root shoulder is one hollow four-millimetre fixed-body "
                "BRep, unchanged across states and at least 4 mm clear of the actual "
                "A06 endpoints of the validated +6 to -89 degree fold sweep."
            ),
            physical_occurrence_id=reference_id,
            comparisons=comparisons,
            interfaces=interfaces,
        )


def _gate_follow_compliant_seat_preload(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Bound the intentional unoccupied Follow preload into the soft cushion."""

    seat_name = "A04_seat_cushion_contact_island"
    shell_name = "A06_backrest_weather_shell"
    follow_seat = _part(states["follow"], seat_name)
    follow_shell = _part(states["follow"], shell_name)
    common_shape = follow_seat.shape.intersect(follow_shell.shape)
    common_volume = (
        0.0 if common_shape.isNull() else float(common_shape.Volume())
    )
    common_box = (
        None
        if common_shape.isNull() or common_volume <= BOOLEAN_TOLERANCE_MM3
        else _Box.from_shape(common_shape)
    )
    nominal_preload_depth = (
        0.0 if common_box is None else common_box.lengths[2]
    )
    nominal_preload_ratio = (
        nominal_preload_depth
        / FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM
    )

    non_follow_common = {
        state: _intersection_volume(
            _part(states[state], seat_name).shape,
            _part(states[state], shell_name).shape,
        )
        for state in ("ride", "cafe", "focus")
    }
    seat_metadata_pass = all(
        _part(states[state], seat_name).metadata.get(
            "follow_backrest_preload_interface"
        )
        is True
        and _part(states[state], seat_name).metadata.get(
            "non_rigid_compliant_part"
        )
        is True
        and float(
            _part(states[state], seat_name).metadata.get(
                "follow_uncompressed_thickness_mm",
                -1.0,
            )
        )
        == FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM
        and float(
            _part(states[state], seat_name).metadata.get(
                "follow_maximum_nominal_preload_mm",
                -1.0,
            )
        )
        == FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
        and _part(states[state], seat_name).metadata.get(
            "fold_motion_requires_unoccupied_interlock"
        )
        is True
        and _part(states[state], seat_name).metadata.get(
            "supplier_compression_set_curve_required"
        )
        is True
        for state in STATES
    )
    shell_metadata_pass = all(
        _part(states[state], shell_name).metadata.get(
            "follow_seat_cushion_preload_interface"
        )
        is True
        and float(
            _part(states[state], shell_name).metadata.get(
                "follow_seat_cushion_maximum_nominal_preload_mm",
                -1.0,
            )
        )
        == FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
        and _part(states[state], shell_name).metadata.get(
            "fold_motion_requires_unoccupied_interlock"
        )
        is True
        for state in STATES
    )
    material_pass = (
        "foam" in follow_seat.material.lower()
        and "pc-abs" in follow_shell.material.lower()
    )
    book.add(
        "a04_a06.follow.compliant_cushion_preload_bounded_and_state_exclusive",
        common_volume > BOOLEAN_TOLERANCE_MM3
        and common_volume
        <= FOLLOW_SEAT_CUSHION_MAXIMUM_COMMON_VOLUME_MM3
        and nominal_preload_depth
        <= FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
        + DISTANCE_TOLERANCE_MM
        and nominal_preload_ratio
        <= (
            FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
            / FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM
        )
        + DISTANCE_TOLERANCE_MM
        and all(
            volume <= BOOLEAN_TOLERANCE_MM3
            for volume in non_follow_common.values()
        )
        and seat_metadata_pass
        and shell_metadata_pass
        and material_pass,
        evidence_kind=(
            "brep_common_volume_and_nominal_soft_compression_depth"
        ),
        requirement=(
            "Only unoccupied Follow may preload the explicitly non-rigid seat "
            "cushion under the same folded A06 shell.  The nominal digital "
            "interference must remain below the frozen 22 mm / 70,000 mm3 "
            "bounds, all operational upright states must have zero common "
            "volume, and an occupied-fold interlock plus supplier compression "
            "curve remain mandatory before physical release."
        ),
        interface_pair=(seat_name, shell_name),
        follow_common_volume_mm3=round(common_volume, 6),
        follow_common_bounds=(
            None if common_box is None else common_box.to_dict()
        ),
        follow_nominal_preload_depth_mm=round(
            nominal_preload_depth,
            6,
        ),
        cushion_uncompressed_thickness_mm=(
            FOLLOW_SEAT_CUSHION_UNCOMPRESSED_THICKNESS_MM
        ),
        nominal_preload_ratio=round(nominal_preload_ratio, 9),
        maximum_nominal_preload_mm=(
            FOLLOW_SEAT_CUSHION_MAXIMUM_NOMINAL_PRELOAD_MM
        ),
        maximum_common_volume_mm3=(
            FOLLOW_SEAT_CUSHION_MAXIMUM_COMMON_VOLUME_MM3
        ),
        non_follow_common_volume_mm3={
            state: round(value, 9)
            for state, value in non_follow_common.items()
        },
        seat_material=follow_seat.material,
        shell_material=follow_shell.material,
        seat_metadata_pass=seat_metadata_pass,
        shell_metadata_pass=shell_metadata_pass,
        fold_motion_requires_unoccupied_interlock=True,
        supplier_foam_curve_and_physical_cycle_validation_required=True,
        production_certification_claimed=False,
    )


def _luminance(color: Sequence[float]) -> float:
    if len(color) < 3:
        return 0.0
    return 0.2126 * float(color[0]) + 0.7152 * float(color[1]) + 0.0722 * float(color[2])


def _gate_a05_stowed_faces(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    legacy_side_access_prefixes = (
        "A05_table_cassette_door_",
        "A05_table_cassette_shadow_horizon_",
        "A05_table_cassette_exit_bezel_",
        "A05_table_cassette_throat_seal_",
    )
    for state in STATES:
        names = [part.name for part in states[state]]
        forbidden = sorted(
            name for name in names if name.startswith(legacy_side_access_prefixes)
        )
        for side_name in ("left", "right"):
            lid = _part(states[state], f"A05_armrest_touch_lid_{side_name}")
            shell = _part(
                states[state], f"A05_armrest_table_bay_shell_{side_name}"
            )
            hinge = _part(
                states[state], f"A05_armrest_top_lid_hinge_reveal_{side_name}"
            )
            release = _part(
                states[state], f"A05_armrest_top_lid_release_{side_name}"
            )
            sequence = tuple(lid.metadata.get("table_access_sequence", ()))
            book.add(
                f"a05.{state}.{side_name}.fixed_body_outward_top_lid_sequence",
                not forbidden
                and shell.metadata.get("legacy_side_table_opening_present") is False
                and lid.metadata.get("top_lid_outward_opening_enabled") is True
                and lid.metadata.get("full_armrest_side_opening_enabled") is False
                and float(lid.metadata.get("top_lid_open_angle_deg", 0.0)) == 105.0
                and lid.metadata.get("final_state_pose")
                == "closed_and_double_latched"
                and sequence == TABLE_ACCESS_SEQUENCE
                and hinge.metadata.get("visible_reveal_width_mm") == 1.0
                and release.metadata.get("manual_no_power") is True
                and release.metadata.get("two_action") is True
                and hinge.shape.isValid()
                and release.shape.isValid(),
                evidence_kind="inventory_brep_metadata_and_ordered_use_sequence",
                requirement=(
                    "The armrest body must remain fixed, the legacy side cassette must be absent, and the outward top lid must close and double-lock before the same table pack unfolds."
                ),
                fixed_shell=shell.name,
                top_lid=lid.name,
                hinge_reveal=hinge.name,
                manual_release=release.name,
                forbidden_legacy_side_access=forbidden,
                open_angle_deg=lid.metadata.get("top_lid_open_angle_deg"),
                final_pose=lid.metadata.get("final_state_pose"),
                ordered_sequence=sequence,
            )

        display = _part(states[state], "A05_left_status_display_window")
        cradle = _part(states[state], "A05_left_qi_phone_cradle")
        qi_target = _part(states[state], "A05_left_qi_target_ring")
        book.add(
            f"a05.{state}.left_hmi_is_human_and_phone_scale",
            tuple(display.metadata.get("outer_window_mm", ())) == (124.0, 50.0)
            and tuple(display.metadata.get("effective_active_area_mm", ()))
            == (116.0, 42.0)
            and display.metadata.get("compound_tilt_deg")
            == {"toward_occupant": 10.0, "rearward": 5.0}
            and tuple(cradle.metadata.get("cradle_surface_mm", ()))
            == (176.0, 86.0)
            and tuple(cradle.metadata.get("validated_phone_design_envelope_mm", ()))
            == (170.0, 84.0, 13.0)
            and float(cradle.metadata.get("outer_edge_inboard_of_hinge_mm", 0.0))
            >= 2.0
            and cradle.metadata.get("phone_presence_blocks_lid_release") is True
            and cradle.metadata.get("qi_deenergises_before_lid_motion") is True
            and qi_target.metadata.get("continuous_metal_loop") is False
            and qi_target.metadata.get("target_material_nonconductive") is True,
            evidence_kind="brep_metadata_phone_envelope_display_orientation_and_lid_interlock",
            requirement=(
                "The Qi area must carry a mainstream cased phone, contain no closed metal loop, and block lid motion while occupied; the display must tilt toward the passenger."
            ),
            display=display.name,
            display_window_mm=display.metadata.get("outer_window_mm"),
            display_tilt_deg=display.metadata.get("compound_tilt_deg"),
            qi_cradle=cradle.name,
            cradle_surface_mm=cradle.metadata.get("cradle_surface_mm"),
            phone_envelope_mm=cradle.metadata.get(
                "validated_phone_design_envelope_mm"
            ),
            qi_target_material=qi_target.material,
        )

    ride = states["ride"]
    pod = _part(ride, "A05_right_removable_drive_pod")
    joystick = _part(ride, "A05_right_joystick")
    authorise = _part(ride, "A05_right_authorisation_key")
    book.add(
        "a05.ride.right_drive_controls_have_real_hand_envelopes",
        tuple(pod.metadata.get("pod_envelope_mm", ())) == (120.0, 58.0, 18.0)
        and float(joystick.metadata.get("grip_diameter_mm", 0.0)) >= 30.0
        and float(joystick.metadata.get("grip_diameter_mm", 0.0)) <= 34.0
        and float(joystick.metadata.get("angular_travel_deg", 0.0)) == 18.0
        and float(
            joystick.metadata.get("full_sweep_envelope_diameter_mm", math.inf)
        )
        <= 54.0
        and float(authorise.metadata.get("button_diameter_mm", 0.0)) >= 18.0
        and float(authorise.metadata.get("button_diameter_mm", 0.0)) <= 22.0
        and float(authorise.metadata.get("joystick_center_separation_mm", 0.0))
        >= 50.0
        and pod.metadata.get("removal_required_before_top_lid_open") is False
        and pod.metadata.get("remains_mounted_to_lid_during_table_extraction")
        is True,
        evidence_kind="brep_metadata_control_grip_sweep_spacing_and_lid_interlock",
        requirement=(
            "The joystick, guarded authorisation button and palm pod must be operable by a real hand and remain mounted at the forward right-armrest station while the top lid opens."
        ),
        pod_envelope_mm=pod.metadata.get("pod_envelope_mm"),
        joystick_grip_diameter_mm=joystick.metadata.get("grip_diameter_mm"),
        joystick_sweep_diameter_mm=joystick.metadata.get(
            "full_sweep_envelope_diameter_mm"
        ),
        authorisation_button_diameter_mm=authorise.metadata.get(
            "button_diameter_mm"
        ),
        control_center_separation_mm=authorise.metadata.get(
            "joystick_center_separation_mm"
        ),
    )


def _gate_a05_lid_harness(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Fail closed on the real 0..105-degree lid/flex/table motion proof."""

    gate_id = "a05.lid_dynamic_flex_full_motion"
    try:
        canonical_parts = states["follow"]
        fixed_shells: dict[int, cq.Shape] = {}
        closed_lid_parts: dict[int, tuple[tuple[str, cq.Shape], ...]] = {}
        for side, side_name in ((-1, "left"), (1, "right")):
            fixed_shells[side] = _part(
                canonical_parts,
                f"A05_armrest_table_bay_shell_{side_name}",
            ).shape
            closed_lid_parts[side] = tuple(
                (part.name, part.shape)
                for part in canonical_parts
                if part.name == f"A05_armrest_touch_lid_{side_name}"
                or (
                    bool(part.metadata.get("moves_with_top_lid"))
                    and part.name.startswith(f"A05_{side_name}_")
                )
                or (side < 0 and part.name == "A05_left_hmi_precision_bezel")
            )
        result = evaluate_a05_lid_harness_gate(
            fixed_shells,
            closed_lid_parts,
        )
    except Exception as exc:
        book.add(
            gate_id,
            False,
            evidence_kind="fail_closed_a05_lid_harness_gate_exception",
            requirement=(
                "Both fixed armrest shells, both lid-carried connector chains, "
                "every rigid lid/HMI occurrence, the stowed table pack and all "
                "61 extraction frames must survive the real 106-pose B-Rep sweep."
            ),
            error=f"{type(exc).__name__}: {exc}",
            production_certification_claimed=False,
        )
        return

    book.add(
        gate_id,
        bool(result.get("pass")),
        evidence_kind=str(result.get("evidence_kind", "")),
        requirement=str(result.get("requirement", "")),
        hard_part_minimum_clearance_mm=result.get(
            "hard_part_minimum_clearance_mm"
        ),
        sides=result.get("sides"),
        failures=result.get("failures"),
        production_certification_claimed=False,
    )


def _gate_fixed_armrest_configuration(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    forbidden_prefixes = (
        "A05_right_transfer_positive_lock_witness",
        "A05_right_transfer_manual_release",
        "A05_right_transfer_root_fairing",
    )
    for state in STATES:
        names = [part.name for part in states[state]]
        forbidden = sorted(
            name for name in names if name.startswith(forbidden_prefixes)
        )
        shells = {
            side: _part(states[state], f"A05_armrest_table_bay_shell_{side}")
            for side in ("left", "right")
        }
        lids = {
            side: _part(states[state], f"A05_armrest_touch_lid_{side}")
            for side in ("left", "right")
        }
        for side in ("left", "right"):
            shell = shells[side]
            lid = lids[side]
            shell_box = _Box.from_shape(shell.shape)
            lid_box = _Box.from_shape(lid.shape)
            book.add(
                f"a05.{state}.{side}_armrest_is_fixed_without_transfer_language",
                not forbidden
                and shell.metadata.get("side_opening_enabled") is False
                and shell.metadata.get("fixed_continuous_armrest") is True
                and shell.metadata.get("legacy_transfer_mechanism_in_production_bom") is False
                and lid.metadata.get("fixed_continuous_armrest") is True
                and shell_box.xmax >= 247.4
                and lid_box.xmax >= 244.9
                and len(shell.shape.Solids()) == 1
                and len(lid.shape.Solids()) == 1,
                evidence_kind="part_inventory_brep_bounds_and_configuration_contract",
                requirement=(
                    "Both armrests must be fixed continuous shells with a real closed rear root and no side-opening hinge, link, release, witness or motion seam."
                ),
                fixed_shell=shell.name,
                fixed_lid=lid.name,
                shell_bounds=shell_box.to_dict(),
                lid_bounds=lid_box.to_dict(),
                fixed_continuous_armrest=shell.metadata.get("fixed_continuous_armrest"),
                side_opening_enabled=shell.metadata.get("side_opening_enabled"),
                legacy_transfer_mechanism_in_production_bom=shell.metadata.get(
                    "legacy_transfer_mechanism_in_production_bom"
                ),
                forbidden_occurrences=forbidden,
            )

    drive_controls = {
        "A05_right_removable_drive_pod",
        "A05_right_joystick",
        "A05_right_authorisation_key",
    }
    expected_pose = {state: "fixed_forward_armrest_top" for state in STATES}
    controls_by_state = {
        state: {
            part.name: part
            for part in states[state]
            if part.name in drive_controls
        }
        for state in STATES
    }
    reference_controls = controls_by_state["ride"]
    for state in STATES:
        controls = controls_by_state[state]
        present = sorted(controls)
        expected = sorted(drive_controls)
        brep_comparisons = {
            name: _brep_pose_evidence(
                reference_controls[name].shape,
                controls[name].shape,
            )
            for name in sorted(drive_controls)
            if name in reference_controls and name in controls
        }
        physical_ids = {
            name: part.metadata.get("physical_occurrence_id")
            for name, part in controls.items()
        }
        book.add(
            f"a05.{state}.same_drive_control_occurrences_have_defined_pose",
            present == expected
            and all(
                part.metadata.get("same_physical_occurrence_all_states") is True
                and part.metadata.get("state_transition_never_deletes_occurrence")
                is True
                and part.metadata.get("state_pose") == expected_pose[state]
                and part.metadata.get("drive_enabled_in_locked_state")
                is (state == "ride")
                for part in controls.values()
            )
            and all(
                part.metadata.get("externally_visible_in_locked_state") is True
                and part.metadata.get("fixed_forward_armrest_location_all_states")
                is True
                for part in controls.values()
            )
            and all(
                _brep_pose_matches(evidence)
                for evidence in brep_comparisons.values()
            )
            and len(brep_comparisons) == len(drive_controls)
            and all(physical_ids.values())
            and physical_ids
            == {
                name: part.metadata.get("physical_occurrence_id")
                for name, part in reference_controls.items()
            },
            evidence_kind=(
                "four_state_inventory_metadata_and_exact_fixed_control_brep"
            ),
            requirement=(
                "The same drive pod, joystick and authorisation key must remain exposed at one fixed forward right-armrest hand station in every state. Only Ride enables traction; table deployment may not relocate, fold or hide the controls."
            ),
            present_drive_control_occurrences=present,
            expected_drive_control_occurrences=expected,
            expected_pose=expected_pose[state],
            actual_poses={
                part.name: part.metadata.get("state_pose")
                for part in controls.values()
            },
            drive_enabled_in_locked_state={
                part.name: part.metadata.get("drive_enabled_in_locked_state")
                for part in controls.values()
            },
            externally_visible_in_locked_state={
                part.name: part.metadata.get(
                    "externally_visible_in_locked_state"
                )
                for part in controls.values()
            },
            physical_occurrence_ids=physical_ids,
            fixed_pose_brep_comparisons=brep_comparisons,
            fixed_armrest_service_lid="A05_armrest_touch_lid_right",
        )

    # A metadata flag cannot establish that a deployed desk leaves room for a
    # real operating hand.  Probe the same 140 x 104 x 120 mm elliptical hand
    # volume in Cafe and Focus against every final A09 solid.  This is the
    # uninflated hand envelope; the source geometry carries a separate 7 mm
    # cutter reserve so the released hard minimum remains 5 mm.
    hand_envelope = (
        cq.Workplane("XY")
        .ellipse(*RIGHT_CONTROL_HAND_ENVELOPE_PLAN_RADII_MM)
        .extrude(RIGHT_CONTROL_HAND_ENVELOPE_HEIGHT_MM)
        .translate(RIGHT_CONTROL_HAND_ENVELOPE_CENTER_MM)
        .val()
    )
    for state in ("cafe", "focus"):
        obstacles = [
            part
            for part in states[state]
            if part.module.upper() == "A09"
        ]
        intersections = {
            part.name: _intersection_volume(hand_envelope, part.shape)
            for part in obstacles
        }
        distances = {
            part.name: float(hand_envelope.distance(part.shape))
            for part in obstacles
        }
        limiting_name = min(distances, key=distances.get) if distances else None
        minimum_clearance = (
            distances[limiting_name] if limiting_name is not None else -math.inf
        )
        book.add(
            f"a05.{state}.fixed_drive_control_has_real_hand_clearance_to_table",
            bool(obstacles)
            and all(
                value <= BOOLEAN_TOLERANCE_MM3
                for value in intersections.values()
            )
            and minimum_clearance
            >= RIGHT_CONTROL_MINIMUM_TABLE_CLEARANCE_MM
            - DISTANCE_TOLERANCE_MM,
            evidence_kind="exact_operator_hand_envelope_to_final_a09_brep",
            requirement=(
                "The Cafe/Focus table and understructure must leave at least "
                "5 mm around a real operating-hand envelope at the invariant "
                "forward right-armrest joystick; controls may not be hidden "
                "behind or functionally blocked by the table."
            ),
            hand_envelope_plan_radii_mm=(
                RIGHT_CONTROL_HAND_ENVELOPE_PLAN_RADII_MM
            ),
            hand_envelope_center_mm=RIGHT_CONTROL_HAND_ENVELOPE_CENTER_MM,
            hand_envelope_height_mm=RIGHT_CONTROL_HAND_ENVELOPE_HEIGHT_MM,
            required_minimum_clearance_mm=(
                RIGHT_CONTROL_MINIMUM_TABLE_CLEARANCE_MM
            ),
            measured_minimum_clearance_mm=round(minimum_clearance, 6),
            limiting_a09_occurrence=limiting_name,
            intersecting_a09_occurrences={
                name: round(value, 9)
                for name, value in intersections.items()
                if value > BOOLEAN_TOLERANCE_MM3
            },
            evaluated_a09_occurrence_count=len(obstacles),
        )

    # The original V8 side field stays visually continuous over the UWB
    # hardpoint.  Its 0.8 mm inner-face recess must clear the existing bezel
    # without becoming a full-through dark slot, while the small gravity drain
    # remains a genuine, separately bounded opening.
    for state in STATES:
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            sail = _part(
                states[state],
                f"A04_A05_integrated_side_sail_{side_name}",
            )
            bezel = _part(
                states[state],
                f"A04_side_uwb_replaceable_bezel_{side_name}",
            )
            drain = _part(
                states[state],
                f"A05_table_cassette_lowpoint_drain_{side_name}",
            )
            sail_bezel_common = _intersection_volume(
                sail.shape,
                bezel.shape,
            )
            sail_bezel_gap = float(sail.shape.distance(bezel.shape))
            sail_drain_common = _intersection_volume(
                sail.shape,
                drain.shape,
            )
            outer_skin_probe = (
                cq.Workplane("XY")
                .box(1.0, 4.0, 1.0)
                .translate((-75.0, side * 369.5, 400.0))
                .val()
            )
            outer_skin_section = sail.shape.intersect(outer_skin_probe)
            measured_outer_skin = (
                0.0
                if outer_skin_section.isNull()
                else float(outer_skin_section.BoundingBox().ylen)
            )
            book.add(
                f"a04_a05.{state}.{side_name}.side_sail_hidden_uwb_recess_and_drain_partition",
                len(sail.shape.Solids()) == 1
                and sail.shape.isValid()
                and sail_bezel_common <= BOOLEAN_TOLERANCE_MM3
                and sail_bezel_gap >= 0.29
                and sail_drain_common <= BOOLEAN_TOLERANCE_MM3
                and measured_outer_skin >= 1.2 - DISTANCE_TOLERANCE_MM
                and float(sail.metadata.get("nominal_wall_mm", 0.0)) == 2.0
                and float(
                    sail.metadata.get("uwb_inner_recess_depth_mm", 0.0)
                )
                == 0.8
                and float(
                    sail.metadata.get(
                        "minimum_remaining_uwb_outer_skin_mm",
                        0.0,
                    )
                )
                >= 1.2
                and sail.metadata.get("uwb_sail_cutout_present") is False
                and sail.metadata.get("hidden_rf_transmission_zone") is True
                and sail.metadata.get(
                    "uwb_bezel_concealed_behind_rf_transparent_sail"
                )
                is True
                and tuple(
                    sail.metadata.get("cassette_drain_opening_mm", ())
                )
                == (34.0, 18.0),
                evidence_kind=(
                    "exact_side_sail_bezel_drain_brep_and_outer_skin_probe"
                ),
                requirement=(
                    "Each removable RF-transparent side sail must retain at "
                    "least 1.2 mm of uninterrupted exterior skin over the UWB "
                    "hardpoint, clear the replaceable bezel, and remain "
                    "physically partitioned from the real cassette drain. A "
                    "full-through UWB styling slot is forbidden."
                ),
                side_sail=sail.name,
                uwb_bezel=bezel.name,
                cassette_drain=drain.name,
                sail_to_uwb_bezel_common_mm3=round(
                    sail_bezel_common,
                    9,
                ),
                sail_to_uwb_bezel_gap_mm=round(sail_bezel_gap, 6),
                sail_to_drain_common_mm3=round(sail_drain_common, 9),
                measured_remaining_uwb_outer_skin_mm=round(
                    measured_outer_skin,
                    6,
                ),
                required_remaining_uwb_outer_skin_mm=1.2,
                full_through_uwb_cutout_present=sail.metadata.get(
                    "uwb_sail_cutout_present"
                ),
            )


def _gate_front_waist_closure(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    for state in STATES:
        fascia = _part(states[state], "A04_front_waist_fascia")
        bounds = _Box.from_shape(fascia.shape)
        front_probe = (
            cq.Workplane("XY")
            .box(20.0, 1.0, 1.0)
            .translate((-382.0, 0.0, 390.0))
            .val()
        )
        front_section = fascia.shape.intersect(front_probe)
        front_wall = (
            0.0
            if front_section.isNull()
            else float(front_section.BoundingBox().xlen)
        )
        side_walls: dict[str, float] = {}
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            side_probe = (
                cq.Workplane("XY")
                .box(1.0, 20.0, 1.0)
                .translate((-390.9, side * 304.0, 390.0))
                .val()
            )
            section = fascia.shape.intersect(side_probe)
            side_walls[side_name] = (
                0.0 if section.isNull() else float(section.BoundingBox().ylen)
            )
        hood_probe = (
            cq.Workplane("XY")
            .box(1.0, 1.0, 12.0)
            .translate((-335.0, 0.0, 452.0))
            .val()
        )
        hood_section = fascia.shape.intersect(hood_probe)
        hood_wall = (
            0.0
            if hood_section.isNull()
            else float(hood_section.BoundingBox().zlen)
        )
        perception = _part(states[state], "A01_perception_horizon_carrier")
        perception_common = _intersection_volume(fascia.shape, perception.shape)
        obsolete = sorted(
            part.name
            for part in states[state]
            if part.name.startswith("A04_front_waist_bridge_")
        )
        book.add(
            f"a04.{state}.front_waist_is_one_closed_u_section",
            not obsolete
            and len(fascia.shape.Solids()) == 1
            and bounds.xmin <= -471.9
            and bounds.xmax >= -309.9
            and bounds.ymin <= -306.9
            and bounds.ymax >= 306.9
            and bounds.zmin <= 365.3
            and bounds.zmax >= 455.0
            and 5.9 <= front_wall <= 6.1
            and all(5.9 <= value <= 6.1 for value in side_walls.values())
            and 2.8 <= hood_wall <= 3.2
            and perception_common <= BOOLEAN_TOLERANCE_MM3
            and fascia.metadata.get("normal_sightline_open_cavity_closed") is True
            and fascia.metadata.get("sensor_horizon_preserved") is True
            and fascia.metadata.get("horizontal_shelf_surface_present") is False
            and fascia.metadata.get("waist_surface_orientation")
            == FRONT_WAIST_SURFACE_ORIENTATION
            and 2.8
            <= float(fascia.metadata.get("sculpted_hood_wall_nominal_mm", 0.0))
            <= 3.2
            and fascia.metadata.get("a02_functional_inserts_are_physical_cutouts")
            is True
            and fascia.metadata.get("dry_split_to_seat_and_follow_skirt") is True,
            evidence_kind="brep_bounds_inventory_and_sightline_responsibility",
            requirement=(
                "One U-section fascia with an upper shoulder must close the front and oblique waist daylight line without covering the low perception horizon."
            ),
            fascia=fascia.name,
            fascia_bounds=bounds.to_dict(),
            obsolete_bridge_occurrences=obsolete,
            sensor_horizon_preserved=fascia.metadata.get(
                "sensor_horizon_preserved"
            ),
            horizontal_shelf_surface_present=fascia.metadata.get(
                "horizontal_shelf_surface_present"
            ),
            waist_surface_orientation=fascia.metadata.get(
                "waist_surface_orientation"
            ),
            required_waist_surface_orientation=(
                FRONT_WAIST_SURFACE_ORIENTATION
            ),
            measured_front_wall_mm=round(front_wall, 6),
            measured_side_wall_mm={
                key: round(value, 6) for key, value in side_walls.items()
            },
            measured_crowned_hood_wall_mm=round(hood_wall, 6),
            perception_horizon_common_volume_mm3=round(
                perception_common,
                9,
            ),
        )


def _gate_front_nose_sightline_crown(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Prove the A01 brow/crown is physical, permanent and does not seal the foot route."""

    for state in STATES:
        nose = _part(states[state], "A01_front_nose_shell")
        fascia = _part(states[state], "A04_front_waist_fascia")
        perception = _part(states[state], "A01_perception_horizon_carrier")

        brow_probe = (
            cq.Workplane("XY")
            .box(10.0, 1.0, 1.0)
            .translate((-484.0, 0.0, 349.0))
            .val()
        )
        brow_section = nose.shape.intersect(brow_probe)
        measured_brow_wall = (
            0.0
            if brow_section.isNull()
            else float(brow_section.BoundingBox().xlen)
        )

        crown_probes = {
            "centre": (-430.0, 0.0, 362.0),
            "rear": (-384.0, 0.0, 362.0),
            "left_oblique": (-430.0, -230.0, 362.0),
            "right_oblique": (-430.0, 230.0, 362.0),
        }
        crown_walls: dict[str, float] = {}
        for label, centre in crown_probes.items():
            probe = cq.Workplane("XY").box(1.0, 1.0, 12.0).translate(centre).val()
            section = nose.shape.intersect(probe)
            crown_walls[label] = (
                0.0 if section.isNull() else float(section.BoundingBox().zlen)
            )

        # The crown deliberately stops at X=-382.  This probe is farther aft,
        # inside the released footwell cut, and must remain empty in order to
        # preserve the occupant-side approach to the deployed footrest.
        foot_route_probe = (
            cq.Workplane("XY")
            .box(8.0, 80.0, 24.0)
            .translate((-350.0, 0.0, 390.0))
            .val()
        )
        foot_route_common = _intersection_volume(nose.shape, foot_route_probe)
        perception_common = _intersection_volume(nose.shape, perception.shape)
        waist_clearance = float(nose.shape.distance(fascia.shape))
        bounds = _Box.from_shape(nose.shape)

        book.add(
            f"a01.{state}.permanent_front_sightline_crown",
            len(nose.shape.Solids()) == 1
            and bounds.xmin <= -484.9
            and 2.15 <= measured_brow_wall <= 2.25
            and all(
                3.95 <= crown_walls[label] <= 4.05
                for label in ("centre", "rear")
            )
            and all(
                5.90 <= crown_walls[label] <= 6.10
                for label in ("left_oblique", "right_oblique")
            )
            and foot_route_common <= BOOLEAN_TOLERANCE_MM3
            and perception_common <= BOOLEAN_TOLERANCE_MM3
            and waist_clearance >= 1.15
            and nose.metadata.get("front_toe_bay_normal_sightline_crown") is True
            and nose.metadata.get("permanent_all_states") is True
            and nose.metadata.get("state_dependent_cover") is False
            and nose.metadata.get("user_shelf_surface_present") is False
            and nose.metadata.get("occupant_side_foot_route_preserved") is True
            and nose.metadata.get("released_perception_hardpoints_changed") is False,
            evidence_kind="brep_wall_probes_clearance_and_state_metadata",
            requirement=(
                "A permanent A01 front brow and short upper return must hide the "
                "toe-bay hardware from front, standing and oblique sightlines in "
                "all four states without moving perception hardpoints or closing "
                "the occupant-side foot route."
            ),
            nose_bounds=bounds.to_dict(),
            measured_front_brow_wall_mm=round(measured_brow_wall, 6),
            measured_upper_return_wall_mm={
                key: round(value, 6) for key, value in crown_walls.items()
            },
            foot_route_common_volume_mm3=round(foot_route_common, 9),
            perception_carrier_common_volume_mm3=round(perception_common, 9),
            measured_clearance_to_front_waist_mm=round(waist_clearance, 6),
            permanent_all_states=nose.metadata.get("permanent_all_states"),
            state_dependent_cover=nose.metadata.get("state_dependent_cover"),
            user_shelf_surface_present=nose.metadata.get(
                "user_shelf_surface_present"
            ),
        )


_A03_FOUR_STATE_CONSERVED_NAMES = (
    *(f"A03_continuous_wheel_belt_shell_{side}" for side in ("left", "right")),
    *(
        f"A03_body_colour_wheel_end_return_skin_{axle}_{side}"
        for axle in ("front", "rear")
        for side in ("left", "right")
    ),
    *(
        f"A03_wheel_end_service_cap_{axle}_{side}"
        for axle in ("front", "rear")
        for side in ("left", "right")
    ),
    *(
        f"A03_wheel_end_service_seam_backing_{axle}_{side}"
        for axle in ("front", "rear")
        for side in ("left", "right")
    ),
    *(
        f"A03_wheel_end_motion_gaiter_{axle}_{side}"
        for axle in ("front", "rear")
        for side in ("left", "right")
    ),
)


def _a03_motion_metadata_keys(name: str) -> tuple[str, ...]:
    if name.startswith("A03_continuous_wheel_belt_shell_"):
        return (
            "fixed_to_lower_body",
            "suspension_articulation_sweep_deg",
        )
    if name.startswith("A03_body_colour_wheel_end_return_skin_"):
        return ("fixed_to_lower_body",)
    if name.startswith("A03_wheel_end_service_cap_"):
        return (
            "moves_with",
            "released_articulation_pose_angles_deg",
            "neutral_service_lock_required",
        )
    if name.startswith("A03_wheel_end_service_seam_backing_"):
        return (
            "moves_with",
            "moves_with_service_cap",
            "bonded_to_service_cap_inner_face",
            "released_articulation_pose_angles_deg",
        )
    if name.startswith("A03_wheel_end_motion_gaiter_"):
        return (
            "outer_edge_moves_with",
            "inner_edge_moves_with",
            "one_piece_flexible_diaphragm",
            "released_articulation_pose_angles_deg",
            "visible_accordion_pleats",
        )
    return ()


def _evaluate_a03_four_state_conservation(
    states: Mapping[str, Sequence[SkinPart]],
) -> tuple[bool, dict[str, object], dict[str, object]]:
    """Prove that non-Ride states inherit the already-tested Ride hardware.

    This helper is intentionally independent of controlled STEP imports so a
    fast unit test can exercise identity, CMF, visibility and kinematic
    metadata without constructing four complete products.
    """

    cross_state_evidence: dict[str, object] = {}
    reference_ids: dict[str, object] = {}
    conserved_pass = True
    for name in _A03_FOUR_STATE_CONSERVED_NAMES:
        reference = _part(states["ride"], name)
        reference_id = reference.metadata.get("physical_occurrence_id")
        material_family = reference.metadata.get("material_family")
        motion_keys = _a03_motion_metadata_keys(name)
        reference_motion = {
            key: reference.metadata.get(key) for key in motion_keys
        }
        motion_metadata_complete = all(
            key in reference.metadata for key in motion_keys
        )
        reference_ids[name] = reference_id
        comparisons: dict[str, object] = {}
        name_pass = bool(reference_id) and bool(material_family)
        name_pass = name_pass and motion_metadata_complete
        for state in STATES:
            occurrence = _part(states[state], name)
            comparison = _brep_pose_evidence(
                reference.shape,
                occurrence.shape,
            )
            occurrence_motion = {
                key: occurrence.metadata.get(key) for key in motion_keys
            }
            state_pass = (
                occurrence.metadata.get("physical_occurrence_id")
                == reference_id
                and occurrence.color == reference.color
                and occurrence.material == reference.material
                and occurrence.metadata.get("material_family")
                == material_family
                and all(key in occurrence.metadata for key in motion_keys)
                and occurrence_motion == reference_motion
                and _brep_pose_matches(comparison)
            )
            if "service_seam_backing" in name:
                state_pass = state_pass and (
                    exterior_visibility_reason(state, occurrence)[0] is False
                )
            else:
                state_pass = state_pass and (
                    exterior_visibility_reason(state, occurrence)[0] is True
                )
            name_pass = name_pass and state_pass
            comparisons[state] = {
                "physical_occurrence_id": occurrence.metadata.get(
                    "physical_occurrence_id"
                ),
                "color": occurrence.color,
                "material": occurrence.material,
                "material_family": occurrence.metadata.get(
                    "material_family"
                ),
                "motion_metadata": occurrence_motion,
                "exterior_visibility": exterior_visibility_reason(
                    state,
                    occurrence,
                ),
                "brep_comparison_to_ride": comparison,
            }
        conserved_pass = conserved_pass and name_pass
        cross_state_evidence[name] = {
            "status": "PASS" if name_pass else "FAIL",
            "states": comparisons,
        }

    ids = list(reference_ids.values())
    unique_ids = (
        all(bool(value) for value in ids)
        and len(ids) == len(set(ids))
    )
    conserved_pass = conserved_pass and unique_ids
    summary = {
        "reference_state": "ride",
        "physical_occurrence_ids": reference_ids,
        "global_physical_occurrence_ids_unique": unique_ids,
        "dynamic_articulation_inherited_from_ride": True,
    }
    return conserved_pass, cross_state_evidence, summary


def _gate_wheel_arch_coverage(
    states: Mapping[str, Sequence[SkinPart]],
    root: Path,
    book: _GateBook,
) -> None:
    tyres: dict[tuple[str, str], cq.Shape] = {}
    hubs: dict[tuple[str, str], cq.Shape] = {}
    axles: dict[tuple[str, str], cq.Shape] = {}
    for axle in ("front", "rear"):
        for side_name in ("left", "right"):
            for family, destination in (
                ("tyre", tyres),
                ("hub", hubs),
                ("axle", axles),
            ):
                path = (
                    root
                    / "build"
                    / "parts"
                    / f"{family}_{axle}_{side_name}.step"
                )
                imported = cq.importers.importStep(str(path))
                shape = imported.val() if hasattr(imported, "val") else imported
                if (
                    not isinstance(shape, cq.Shape)
                    or shape.isNull()
                    or not shape.isValid()
                ):
                    raise TypeError(
                        f"Invalid controlled {family} B-Rep: {path}"
                    )
                destination[(axle, side_name)] = shape

    ride_hub_articulation: dict[tuple[str, str], dict[str, object]] = {}
    for state in STATES:
        belts = {
            side_name: _part(
                states[state],
                f"A03_continuous_wheel_belt_shell_{side_name}",
            )
            for side_name in ("left", "right")
        }
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            belt = belts[side_name]
            class_a_belt_shell = wheel_belt_class_a_shell(
                belt.shape,
                side_name,
            )
            belt_box = _Box.from_shape(belt.shape)
            for axle, wheel_x in (("front", -380.0), ("rear", 180.0)):
                tyre = tyres[(axle, side_name)]
                tyre_box = _Box.from_shape(tyre)
                sweep_angles = (-10.0, -5.0, 0.0, 5.0, 10.0)
                sweep_clearances: dict[str, float] = {}
                swept_shapes: list[cq.Shape] = []
                for angle in sweep_angles:
                    swept = (
                        tyre
                        if angle == 0.0
                        else tyre.rotate(
                            (-100.0, 0.0, 125.0),
                            (-100.0, 1.0, 125.0),
                            angle,
                        )
                    )
                    swept_shapes.append(swept)
                    sweep_clearances[f"{angle:+.1f}"] = float(
                        class_a_belt_shell.distance(swept)
                    )
                clearance = min(sweep_clearances.values())
                swept_box = _union_boxes(swept_shapes)
                crown_probe = (
                    cq.Workplane("XY")
                    .box(1.0, 1.0, 20.0)
                    .translate((wheel_x, side * 340.7, 312.2))
                    .val()
                )
                crown_section = belt.shape.intersect(crown_probe)
                crown_volume = float(crown_section.Volume())
                crown_wall = (
                    0.0
                    if crown_volume <= BOOLEAN_TOLERANCE_MM3
                    else float(crown_section.BoundingBox().zlen)
                )
                upper_probe = (
                    cq.Workplane("XY")
                    .box(1.0, 20.0, 1.0)
                    .translate((wheel_x, side * 374.45, 200.0))
                    .val()
                )
                upper_section = belt.shape.intersect(upper_probe)
                upper_volume = float(upper_section.Volume())
                side_wall = (
                    0.0
                    if upper_volume <= BOOLEAN_TOLERANCE_MM3
                    else float(upper_section.BoundingBox().ylen)
                )
                # Sample both lobes of the lower semicircle outside the hub
                # service island.  A centre-only sample would be blocked by
                # the intentionally opaque hub cap and could not prove that
                # the lower tyre half is visually open.
                side_half_wrap_samples: dict[str, dict[str, float]] = {}
                for longitudinal_offset in (
                    WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM
                ):
                    side_open_probe = (
                        cq.Workplane("XY")
                        .box(1.0, 20.0, 1.0)
                        .translate(
                            (
                                wheel_x + longitudinal_offset,
                                side * 374.45,
                                WHEEL_SIDE_OPEN_PROBE_Z_MM,
                            )
                        )
                        .val()
                    )
                    side_closed_probe = (
                        cq.Workplane("XY")
                        .box(1.0, 20.0, 1.0)
                        .translate(
                            (
                                wheel_x + longitudinal_offset,
                                side * 374.45,
                                WHEEL_SIDE_CLOSED_PROBE_Z_MM,
                            )
                        )
                        .val()
                    )
                    side_closed_section = belt.shape.intersect(
                        side_closed_probe
                    )
                    side_closed_volume = float(side_closed_section.Volume())
                    side_half_wrap_samples[
                        f"x_offset_{longitudinal_offset:+.1f}"
                    ] = {
                        "open_common_mm3": _intersection_volume(
                            belt.shape,
                            side_open_probe,
                        ),
                        "closed_wall_mm": (
                            0.0
                            if side_closed_volume <= BOOLEAN_TOLERANCE_MM3
                            else float(side_closed_section.BoundingBox().ylen)
                        ),
                    }
                side_open_common = max(
                    sample["open_common_mm3"]
                    for sample in side_half_wrap_samples.values()
                )
                side_closed_wall = min(
                    sample["closed_wall_mm"]
                    for sample in side_half_wrap_samples.values()
                )
                inboard_crown_probe = (
                    cq.Workplane("XY")
                    .box(1.0, 1.0, 20.0)
                    # Sample the horizontal crown just outboard of the
                    # dedicated inner downstand.  The old 286 mm datum passed
                    # through both features and falsely reported their union
                    # height (10.95 mm) as crown wall thickness.
                    .translate((wheel_x, side * 290.0, 312.2))
                    .val()
                )
                inboard_crown_section = belt.shape.intersect(
                    inboard_crown_probe
                )
                inboard_crown_volume = float(inboard_crown_section.Volume())
                inboard_crown_wall = (
                    0.0
                    if inboard_crown_volume <= BOOLEAN_TOLERANCE_MM3
                    else float(inboard_crown_section.BoundingBox().zlen)
                )
                inboard_downstand_probe = (
                    cq.Workplane("XY")
                    .box(1.0, 1.0, 20.0)
                    .translate((wheel_x, side * 285.75, 310.2))
                    .val()
                )
                inboard_downstand_section = belt.shape.intersect(
                    inboard_downstand_probe
                )
                inboard_downstand_volume = float(
                    inboard_downstand_section.Volume()
                )
                inboard_downstand_height = (
                    0.0
                    if inboard_downstand_volume <= BOOLEAN_TOLERANCE_MM3
                    else float(
                        inboard_downstand_section.BoundingBox().zlen
                    )
                )
                outward_x = -1.0 if axle == "front" else 1.0
                end_return_probe = (
                    cq.Workplane("XY")
                    .box(20.0, 1.0, 1.0)
                    .translate(
                        (
                            wheel_x + outward_x * 143.0,
                            side * 328.625,
                            218.5,
                        )
                    )
                    .val()
                )
                end_return_section = belt.shape.intersect(end_return_probe)
                end_return_volume = float(end_return_section.Volume())
                end_return_wall = (
                    0.0
                    if end_return_volume <= BOOLEAN_TOLERANCE_MM3
                    else float(end_return_section.BoundingBox().xlen)
                )
                end_open_probe = (
                    cq.Workplane("XY")
                    .box(20.0, 1.0, 1.0)
                    .translate(
                        (
                            wheel_x + outward_x * 143.0,
                            side * 328.625,
                            WHEEL_END_OPEN_PROBE_Z_MM,
                        )
                    )
                    .val()
                )
                end_open_common = _intersection_volume(
                    belt.shape,
                    end_open_probe,
                )
                end_closed_probe = (
                    cq.Workplane("XY")
                    .box(20.0, 1.0, 1.0)
                    .translate(
                        (
                            wheel_x + outward_x * 143.0,
                            side * 328.625,
                            WHEEL_END_CLOSED_PROBE_Z_MM,
                        )
                    )
                    .val()
                )
                end_closed_section = belt.shape.intersect(end_closed_probe)
                end_closed_volume = float(end_closed_section.Volume())
                end_closed_wall = (
                    0.0
                    if end_closed_volume <= BOOLEAN_TOLERANCE_MM3
                    else float(end_closed_section.BoundingBox().xlen)
                )
                end_coverage_walls: dict[str, float] = {}
                for lateral_offset in (
                    WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM
                ):
                    for coverage_z in WHEEL_END_COVERAGE_PROBE_Z_MM:
                        coverage_probe = (
                            cq.Workplane("XY")
                            .box(20.0, 1.0, 1.0)
                            .translate(
                                (
                                    wheel_x + outward_x * 143.0,
                                    side * (326.0 + lateral_offset),
                                    coverage_z,
                                )
                            )
                            .val()
                        )
                        coverage_section = belt.shape.intersect(
                            coverage_probe
                        )
                        coverage_volume = float(coverage_section.Volume())
                        end_coverage_walls[
                            f"y_offset_{lateral_offset:+.1f}_z_{coverage_z:.1f}"
                        ] = (
                            0.0
                            if coverage_volume <= BOOLEAN_TOLERANCE_MM3
                            else float(
                                coverage_section.BoundingBox().xlen
                            )
                        )
                cap = _part(
                    states[state],
                    f"A03_wheel_end_service_cap_{axle}_{side_name}",
                )
                backing = _part(
                    states[state],
                    f"A03_wheel_end_service_seam_backing_{axle}_{side_name}",
                )
                gaiter = _part(
                    states[state],
                    f"A03_wheel_end_motion_gaiter_{axle}_{side_name}",
                )
                if state == "ride":
                    hub_articulation = evaluate_wheel_hub_articulation(
                        axle=axle,
                        side=side_name,
                        belt=belt.shape,
                        released_cap=cap.shape,
                        released_backing=backing.shape,
                        released_gaiter=gaiter.shape,
                        controlled_hub=hubs[(axle, side_name)],
                        controlled_axle=axles[(axle, side_name)],
                        boolean_tolerance_mm3=BOOLEAN_TOLERANCE_MM3,
                        distance_tolerance_mm=DISTANCE_TOLERANCE_MM,
                    )
                    ride_hub_articulation[(axle, side_name)] = (
                        hub_articulation
                    )
                else:
                    # The strict four-state conservation proof below requires
                    # the same B-Rep, CMF, visibility and kinematic metadata as
                    # Ride.  Re-running identical five-pose OCC booleans in
                    # every presentation state only multiplies crash pressure.
                    hub_articulation = {
                        "status": "INHERITED_FROM_RIDE",
                        "source_state": "ride",
                        "axle": axle,
                        "side": side_name,
                    }
                dynamic_articulation_pass = (
                    hub_articulation.get("status") == "PASS"
                    if state == "ride"
                    else hub_articulation.get("status")
                    == "INHERITED_FROM_RIDE"
                )
                visual_skin = _part(
                    states[state],
                    f"A03_body_colour_wheel_end_return_skin_{axle}_{side_name}",
                )
                visual_skin_box = _Box.from_shape(visual_skin.shape)
                visual_skin_belt_common = _intersection_volume(
                    visual_skin.shape,
                    belt.shape,
                )
                visual_skin_belt_gap = float(
                    visual_skin.shape.distance(belt.shape)
                )
                visual_skin_x = (
                    visual_skin_box.xmin + visual_skin_box.xmax
                ) / 2.0
                visual_skin_coverage_walls: dict[str, float] = {}
                for lateral_offset in (
                    WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM
                ):
                    for coverage_z in WHEEL_END_COVERAGE_PROBE_Z_MM:
                        visual_probe = (
                            cq.Workplane("XY")
                            .box(20.0, 1.0, 1.0)
                            .translate(
                                (
                                    visual_skin_x,
                                    side * (326.0 + lateral_offset),
                                    coverage_z,
                                )
                            )
                            .val()
                        )
                        visual_section = visual_skin.shape.intersect(
                            visual_probe
                        )
                        visual_volume = float(visual_section.Volume())
                        visual_skin_coverage_walls[
                            f"y_offset_{lateral_offset:+.1f}_z_{coverage_z:.1f}"
                        ] = (
                            0.0
                            if visual_volume <= BOOLEAN_TOLERANCE_MM3
                            else float(visual_section.BoundingBox().xlen)
                        )
                visual_skin_outboard_of_tyre = (
                    visual_skin_box.xmax <= tyre_box.xmin
                    if axle == "front"
                    else visual_skin_box.xmin >= tyre_box.xmax
                )
                # Positive visibility proof: each released lower-half ray must
                # contain controlled tyre material and no intervening A03
                # weather surface.  An empty shell opening looking through to
                # the studio background can therefore never satisfy the gate.
                side_tyre_first_hit: dict[str, dict[str, float]] = {}
                for x_offset, witness_z in WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM:
                    witness = (
                        cq.Workplane("XY")
                        .box(1.5, 40.0, 1.5)
                        .translate(
                            (
                                wheel_x + x_offset,
                                side * 368.0,
                                witness_z,
                            )
                        )
                        .val()
                    )
                    tyre_common = _intersection_volume(tyre, witness)
                    occluder_common = sum(
                        _intersection_volume(shape, witness)
                        for shape in (
                            belt.shape,
                            cap.shape,
                            gaiter.shape,
                            visual_skin.shape,
                        )
                    )
                    side_tyre_first_hit[
                        f"x_offset_{x_offset:+.1f}_z_{witness_z:.1f}"
                    ] = {
                        "controlled_tyre_common_mm3": tyre_common,
                        "intervening_a03_common_mm3": occluder_common,
                    }
                end_tyre_first_hit: dict[str, dict[str, float]] = {}
                for lateral_offset in (
                    WHEEL_END_LOWER_TYRE_WITNESS_LATERAL_OFFSETS_MM
                ):
                    for witness_z in WHEEL_END_LOWER_TYRE_WITNESS_Z_MM:
                        witness = (
                            cq.Workplane("XY")
                            .box(80.0, 1.5, 1.5)
                            .translate(
                                (
                                    wheel_x + outward_x * 115.0,
                                    side * 326.0 + lateral_offset,
                                    witness_z,
                                )
                            )
                            .val()
                        )
                        tyre_common = _intersection_volume(tyre, witness)
                        occluder_common = sum(
                            _intersection_volume(shape, witness)
                            for shape in (
                                belt.shape,
                                visual_skin.shape,
                                cap.shape,
                                gaiter.shape,
                            )
                        )
                        end_tyre_first_hit[
                            f"y_offset_{lateral_offset:+.1f}_z_{witness_z:.1f}"
                        ] = {
                            "controlled_tyre_common_mm3": tyre_common,
                            "intervening_a03_common_mm3": occluder_common,
                        }
                lower_tyre_first_hit_pass = (
                    len(side_tyre_first_hit)
                    == len(WHEEL_SIDE_LOWER_TYRE_WITNESS_XZ_MM)
                    and len(end_tyre_first_hit)
                    == len(WHEEL_END_LOWER_TYRE_WITNESS_LATERAL_OFFSETS_MM)
                    * len(WHEEL_END_LOWER_TYRE_WITNESS_Z_MM)
                    and all(
                        sample["controlled_tyre_common_mm3"]
                        > BOOLEAN_TOLERANCE_MM3
                        and sample["intervening_a03_common_mm3"]
                        <= BOOLEAN_TOLERANCE_MM3
                        for sample in (
                            *side_tyre_first_hit.values(),
                            *end_tyre_first_hit.values(),
                        )
                    )
                )
                cap_common = _intersection_volume(belt.shape, cap.shape)
                backing_common = _intersection_volume(belt.shape, backing.shape)
                cap_backing_common = _intersection_volume(cap.shape, backing.shape)
                cap_backing_distance = float(cap.shape.distance(backing.shape))
                book.add(
                    f"a03.{state}.{axle}.{side_name}.continuous_belt_covers_upper_tyre",
                    len(belt.shape.Solids()) == 1
                    and clearance
                    >= WHEEL_MINIMUM_SWEPT_CLEARANCE_MM
                    - DISTANCE_TOLERANCE_MM
                    and belt_box.xmin <= tyre_box.xmin - 14.9
                    and belt_box.xmax >= tyre_box.xmax + 14.9
                    and belt_box.zmax >= swept_box.zmax + 12.0
                    and 1.85 <= crown_wall <= 1.95
                    and 1.85 <= inboard_crown_wall <= 1.95
                    # The downstand is a short rolled inner hem.  A former
                    # 10 mm drop entered the +/-10 degree swept tyre envelope;
                    # the 2.15 mm drop retains an opaque edge while preserving
                    # the same 15.5 mm motion-clearance gate as the crown.
                    and 3.9 <= inboard_downstand_height <= 4.2
                    and 1.85 <= side_wall <= 1.95
                    and 1.85 <= end_return_wall <= 1.95
                    and side_open_common <= BOOLEAN_TOLERANCE_MM3
                    and 1.85 <= side_closed_wall <= 1.95
                    and len(side_half_wrap_samples)
                    == len(WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM)
                    and end_open_common <= BOOLEAN_TOLERANCE_MM3
                    and 1.85 <= end_closed_wall <= 1.95
                    and all(
                        1.85 <= value <= 1.95
                        for value in end_coverage_walls.values()
                    )
                    and len(end_coverage_walls) == 9
                    and visual_skin.shape.isValid()
                    and len(visual_skin.shape.Solids()) == 1
                    and exterior_visibility_reason(state, visual_skin)[0]
                    is True
                    and visual_skin.color == LUNAR_STONE
                    and visual_skin_belt_common <= BOOLEAN_TOLERANCE_MM3
                    and abs(
                        visual_skin_belt_gap
                        - WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and abs(
                        visual_skin_box.lengths[0]
                        - WHEEL_END_VISUAL_SKIN_THICKNESS_MM
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and abs(
                        visual_skin_box.lengths[1]
                        - WHEEL_END_VISUAL_SKIN_Y_SPAN_MM
                    )
                    <= 0.02
                    and abs(
                        visual_skin_box.zmin
                        - WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM[0]
                    )
                    <= 0.02
                    and abs(
                        visual_skin_box.zmax
                        - WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM[1]
                    )
                    <= 0.02
                    and visual_skin_box.ymin <= tyre_box.ymin
                    and visual_skin_box.ymax >= tyre_box.ymax
                    and visual_skin_box.zmax >= tyre_box.zmax
                    and visual_skin_outboard_of_tyre
                    and len(visual_skin_coverage_walls) == 9
                    and all(
                        WHEEL_END_VISUAL_SKIN_THICKNESS_MM - 0.02
                        <= value
                        <= WHEEL_END_VISUAL_SKIN_THICKNESS_MM + 0.02
                        for value in visual_skin_coverage_walls.values()
                    )
                    and visual_skin.metadata.get("body_colour_end_return")
                    is True
                    and visual_skin.metadata.get("tyre_visual_occlusion")
                    is True
                    and visual_skin.metadata.get(
                        "covers_tyre_upper_projection"
                    )
                    is True
                    and abs(
                        float(
                            visual_skin.metadata.get(
                                "lower_half_reveal_top_z_mm",
                                -1.0,
                            )
                        )
                        - WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and visual_skin.metadata.get(
                        "half_wrap_boundary_equals_wheel_axis"
                    )
                    is True
                    and visual_skin.metadata.get(
                        "underlying_end_return_connected_to_crown_brep"
                    )
                    is True
                    and cap_common <= BOOLEAN_TOLERANCE_MM3
                    and backing_common <= BOOLEAN_TOLERANCE_MM3
                    and cap_backing_common <= BOOLEAN_TOLERANCE_MM3
                    and cap_backing_distance <= DISTANCE_TOLERANCE_MM
                    and backing.metadata.get(
                        "bonded_to_service_cap_inner_face"
                    )
                    is True
                    and backing.metadata.get("moves_with_service_cap") is True
                    and belt.metadata.get("one_piece_visible_wheel_belt") is True
                    and belt.metadata.get("full_tyre_width_crown_wrap") is True
                    and belt.metadata.get("front_and_rear_axle_plane_returns") is True
                    and 2.1
                    <= float(
                        belt.metadata.get(
                            "crown_inboard_downstand_mm",
                            0.0,
                        )
                    )
                    <= 2.2
                    and float(
                        belt.metadata.get(
                            "longitudinal_end_return_offset_from_axle_mm",
                            0.0,
                        )
                    )
                    >= 143.0
                    and belt.metadata.get("tyre_upper_half_not_exposed") is True
                    and belt.metadata.get("tyre_lower_contact_band_visible") is True
                    and belt.metadata.get("tyre_lower_contact_half_visible") is True
                    and abs(
                        float(
                            belt.metadata.get(
                                "lower_half_reveal_top_z_mm",
                                -1.0,
                            )
                        )
                        - WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM
                    )
                    <= 0.01
                    and belt.metadata.get(
                        "half_wrap_boundary_equals_wheel_axis"
                    )
                    is True
                    and belt.metadata.get("fixed_to_lower_body") is True
                    and belt.metadata.get("suspension_articulation_sweep_deg")
                    == (-10.0, 10.0)
                    and float(
                        belt.metadata.get(
                            "production_minimum_swept_tyre_clearance_target_mm",
                            0.0,
                        )
                    )
                    >= WHEEL_MINIMUM_SWEPT_CLEARANCE_MM
                    and abs(
                        float(
                            belt.metadata.get("nominal_product_width_mm", 0.0)
                        )
                        - WHEEL_NOMINAL_PRODUCT_WIDTH_MM
                    )
                    <= 0.01
                    and abs(
                        float(
                            belt.metadata.get(
                                "production_width_design_limit_mm",
                                0.0,
                            )
                        )
                        - WHEEL_PRODUCTION_WIDTH_LIMIT_MM
                    )
                    <= 0.01
                    and 2.0 * max(abs(belt_box.ymin), abs(belt_box.ymax))
                    <= WHEEL_PRODUCTION_WIDTH_LIMIT_MM
                    + ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
                    and dynamic_articulation_pass
                    and lower_tyre_first_hit_pass
                    and cap.metadata.get("flush_body_colour_service_cap") is True
                    and cap.metadata.get("moves_with")
                    == "controlled_suspension_rocker_and_wheel_hub"
                    and cap.metadata.get("neutral_service_lock_required") is True
                    and bool(cap.metadata.get("physical_occurrence_id"))
                    and backing.metadata.get("moves_with")
                    == "controlled_suspension_rocker_and_wheel_hub"
                    and gaiter.metadata.get("one_piece_flexible_diaphragm")
                    is True
                    and gaiter.metadata.get("outer_edge_moves_with")
                    == "fixed_lower_body"
                    and gaiter.metadata.get("inner_edge_moves_with")
                    == "controlled_suspension_rocker_and_wheel_hub"
                    and gaiter.metadata.get("visible_accordion_pleats") is False
                    and gaiter.metadata.get("colour_matched_to_wheel_belt")
                    is True
                    and exterior_visibility_reason(state, gaiter)[0] is True,
            evidence_kind=(
                "brep_articulation_sweep_axis_height_half_wrap_body_colour_"
                "upper_occlusion_and_service_cap"
            ),
                    requirement=(
                        "One fixed continuous wheel pod surrounds a sweep aperture; "
                        "the near-flush service cap and opaque backing move with the "
                        "hub, while one fixed-edge/moving-hole TPE diaphragm closes "
                        "every released +/-10 degree pose.  Both the "
                        "outboard elevation and the front/rear returns must remain "
                        "open below the z=125 wheel axis and closed above it.  A "
                        "lunar-stone upper end skin, continuous crown and opaque hub "
                        "service island hide the drive while the full lower tyre "
                        "semicircle remains readable."
                    ),
                    wheel_belt=belt.name,
                    wheel_belt_bounds=belt_box.to_dict(),
                    tyre_bounds=tyre_box.to_dict(),
                    swept_tyre_bounds=swept_box.to_dict(),
                    articulation_angles_deg=list(sweep_angles),
                    belt_to_tyre_clearance_by_angle_mm={
                        angle: round(value, 6)
                        for angle, value in sweep_clearances.items()
                    },
                    minimum_swept_belt_to_tyre_clearance_mm=round(clearance, 6),
                    measured_crown_wall_mm=round(crown_wall, 6),
                    measured_inboard_crown_wall_mm=round(
                        inboard_crown_wall,
                        6,
                    ),
                    measured_inboard_downstand_height_mm=round(
                        inboard_downstand_height,
                        6,
                    ),
                    measured_side_wall_mm=round(side_wall, 6),
                    measured_end_return_wall_mm=round(end_return_wall, 6),
                    wheel_axis_z_mm=WHEEL_AXIS_Z_MM,
                    lower_half_reveal_top_z_mm=(
                        WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM
                    ),
                    side_probe_longitudinal_offsets_mm=(
                        WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM
                    ),
                    side_open_probe_z_mm=WHEEL_SIDE_OPEN_PROBE_Z_MM,
                    side_open_probe_common_mm3=round(
                        side_open_common,
                        9,
                    ),
                    side_closed_probe_z_mm=WHEEL_SIDE_CLOSED_PROBE_Z_MM,
                    measured_side_closed_wall_mm=round(
                        side_closed_wall,
                        6,
                    ),
                    side_half_wrap_samples={
                        key: {
                            sample_key: round(value, 9)
                            for sample_key, value in sample.items()
                        }
                        for key, sample in side_half_wrap_samples.items()
                    },
                    end_return_lower_edge_z_mm=(
                        WHEEL_END_RETURN_LOWER_EDGE_Z_MM
                    ),
                    end_open_probe_z_mm=WHEEL_END_OPEN_PROBE_Z_MM,
                    end_open_probe_common_mm3=round(
                        end_open_common,
                        9,
                    ),
                    end_closed_probe_z_mm=WHEEL_END_CLOSED_PROBE_Z_MM,
                    measured_end_closed_wall_mm=round(
                        end_closed_wall,
                        6,
                    ),
                    end_return_opaque_coverage_grid_mm={
                        key: round(value, 6)
                        for key, value in end_coverage_walls.items()
                    },
                    body_colour_visual_end_return_skin=visual_skin.name,
                    body_colour_visual_skin_exterior_visibility=(
                        exterior_visibility_reason(state, visual_skin)
                    ),
                    body_colour_visual_skin_bounds=visual_skin_box.to_dict(),
                    body_colour_visual_skin_color=visual_skin.color,
                    body_colour_visual_skin_to_belt_common_mm3=round(
                        visual_skin_belt_common,
                        9,
                    ),
                    body_colour_visual_skin_to_belt_gap_mm=round(
                        visual_skin_belt_gap,
                        6,
                    ),
                    body_colour_visual_skin_outboard_of_tyre=(
                        visual_skin_outboard_of_tyre
                    ),
                    body_colour_visual_skin_coverage_grid_mm={
                        key: round(value, 6)
                        for key, value in visual_skin_coverage_walls.items()
                    },
                    belt_service_cap_common_mm3=round(cap_common, 9),
                    service_cap=cap.name,
                    service_seam_backing=backing.name,
                    belt_backing_common_mm3=round(backing_common, 9),
                    cap_backing_common_mm3=round(cap_backing_common, 9),
                    cap_to_backing_distance_mm=round(cap_backing_distance, 6),
                    moving_hub_cap_and_gaiter_articulation=(
                        hub_articulation
                    ),
                    side_lower_tyre_first_hit_witnesses=(
                        side_tyre_first_hit
                    ),
                    front_or_rear_lower_tyre_first_hit_witnesses=(
                        end_tyre_first_hit
                    ),
                )

        for side_name in ("left", "right"):
            pivot_cap = _part(
                states[state],
                f"A03_rocker_pivot_service_cap_{side_name}",
            )
            pivot_backing = _part(
                states[state],
                f"A03_rocker_pivot_service_seam_backing_{side_name}",
            )
            pivot_common = _intersection_volume(
                pivot_cap.shape,
                pivot_backing.shape,
            )
            pivot_distance = float(
                pivot_cap.shape.distance(pivot_backing.shape)
            )
            book.add(
                f"a03.{state}.{side_name}.rocker_service_seam_is_opaque",
                pivot_common <= BOOLEAN_TOLERANCE_MM3
                and pivot_distance >= 0.70 - DISTANCE_TOLERANCE_MM
                and pivot_backing.metadata.get(
                    "normal_sightline_background_transmission"
                )
                is False,
                evidence_kind="brep_recessed_service_seam_backing",
                requirement=(
                    "The rocker-pivot service cap must have a recessed opaque gasket behind its precision seam; no view may transmit the studio background through the annulus."
                ),
                service_cap=pivot_cap.name,
                seam_backing=pivot_backing.name,
                common_volume_mm3=round(pivot_common, 9),
                separation_mm=round(pivot_distance, 6),
            )

        left_box = _Box.from_shape(belts["left"].shape)
        right_box = _Box.from_shape(belts["right"].shape)
        book.add(
            f"a03.{state}.continuous_wheel_belts_are_bilateral_and_symmetric",
            abs(abs(left_box.ymin) - abs(right_box.ymax)) <= 0.02
            and abs(float(belts["left"].shape.Volume()) - float(belts["right"].shape.Volume()))
            <= 0.01,
            evidence_kind="brep_bilateral_outer_datum_and_volume",
            requirement=(
                "The final lower core must use exactly one continuous wheel belt per side with a symmetric Class-A outer datum, not separate front/rocker/rear plates."
            ),
            left_belt=belts["left"].name,
            right_belt=belts["right"].name,
            left_outer_y_mm=round(left_box.ymin, 6),
            right_outer_y_mm=round(right_box.ymax, 6),
            volume_difference_mm3=round(
                abs(
                    float(belts["left"].shape.Volume())
                    - float(belts["right"].shape.Volume())
                ),
                9,
            ),
        )

    conserved_pass, cross_state_evidence, conservation_summary = (
        _evaluate_a03_four_state_conservation(states)
    )
    ride_dynamic_pass = (
        len(ride_hub_articulation) == 4
        and all(
            evidence.get("status") == "PASS"
            for evidence in ride_hub_articulation.values()
        )
    )
    conservation_summary["ride_dynamic_wheel_count"] = len(
        ride_hub_articulation
    )
    conservation_summary["ride_dynamic_articulation_pass"] = (
        ride_dynamic_pass
    )
    book.add(
        "a03.four_state.same_half_wrap_and_moving_hub_island",
        conserved_pass and ride_dynamic_pass,
        evidence_kind=(
            "ride_dynamic_brep_articulation_plus_four_state_occurrence_id_"
            "cmf_visibility_kinematic_metadata_and_neutral_brep_identity"
        ),
        requirement=(
            "Follow, Ride, Cafe and Focus use the same upper-half wheel belts, "
            "body-colour end returns, moving hub caps and fixed-edge flexible "
            "gaiters.  No state may expose a hub/drive part or replace the "
            "lower tyre semicircle with a closed wheel disc."
        ),
        conserved_occurrences=cross_state_evidence,
        conservation_summary=conservation_summary,
    )


def _stage_evidence(parts: Sequence[SkinPart]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    descriptions: list[dict[str, Any]] = []
    for part in parts:
        descriptions.append(
            {
                "name": part.name,
                "physical_occurrence_id": part.metadata.get("physical_occurrence_id"),
                "stage_index": part.metadata.get(
                    "telescopic_stage_index", part.metadata.get("stage_index")
                ),
                "solid_count": len(part.shape.Solids()),
                "volume_mm3": round(float(part.shape.Volume()), 6),
            }
        )
    interfaces: dict[str, float] = {}
    for first, second in combinations(parts, 2):
        key = f"{first.name}__{second.name}"
        interfaces[f"{key}.common_volume_mm3"] = round(
            _intersection_volume(first.shape, second.shape), 9
        )
        interfaces[f"{key}.distance_mm"] = round(
            float(first.shape.distance(second.shape)), 6
        )
    return descriptions, interfaces


def _float_tuple(value: object) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(float(item) for item in value)  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return ()


def _a09_expected_instrument_spine_stage(
    state: str,
    side_name: str,
    stage_index: int,
) -> cq.Shape:
    profile = A09_LIFT_STAGE_PROFILE_CONTRACT[stage_index]
    axis_x = -430.0 if state == "cafe" else -405.0
    axis_y = -300.0 if side_name == "left" else 300.0
    zmin, zmax = A09_LIFT_STAGE_Z_HARDPOINTS_MM[stage_index]
    center = (axis_x, axis_y, (zmin + zmax) / 2.0)
    outer = rounded_rect_prism(
        _float_tuple(profile["outer_xy_mm"]),
        zmax - zmin,
        center,
        float(profile["outer_plan_radius_mm"]),
    )
    inner = rounded_rect_prism(
        _float_tuple(profile["inner_xy_mm"]),
        zmax - zmin + 4.0,
        center,
        float(profile["inner_plan_radius_mm"]),
    )
    return outer.cut(inner).clean()


def _a07_focus_inverse_translation(name: str) -> tuple[float, float, float]:
    """Return the exact inverse of each A07 occurrence's Focus-only motion."""

    if name in {
        "A07_physical_privacy_shutter",
        "A07_privacy_shutter_carriage_bezel",
    }:
        return (0.0, -136.0, -A07_FOCUS_TRANSLATION_MM)
    if (
        name == "A07_mast_moving_inner_sleeve"
        or name.startswith("A07_sensor_beam_")
        or name.startswith("A07_fill_light_visible_window_")
        or name
        in {
            "A07_microphone_acoustic_mesh",
            "A07_environment_sensor_grille",
        }
    ):
        return (0.0, 0.0, -A07_FOCUS_TRANSLATION_MM)
    return (0.0, 0.0, 0.0)


def _gate_a07_single_moving_spine(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Prove fixed sleeve + one-piece 420 mm spine + the same crowned terminal."""

    moving_name = "A07_mast_moving_inner_sleeve"
    for state in STATES:
        fixed = _part(states[state], "A07_mast_fixed_outer_sleeve")
        moving = _part(states[state], moving_name)
        terminal = _part(states[state], "A07_sensor_beam_shell")
        microphone = _part(states[state], "A07_microphone_acoustic_mesh")
        moving_stage_names = sorted(
            part.name
            for part in states[state]
            if part.name.startswith("A07_mast_moving_inner_sleeve")
        )

        fixed_shape = fixed.shape
        moving_shape = moving.shape
        terminal_shape = terminal.shape
        if state == "follow":
            fixed_shape = _rotate_about_back_hinge(fixed_shape, -BACK_FOLD_DEG)
            moving_shape = _rotate_about_back_hinge(moving_shape, -BACK_FOLD_DEG)
            terminal_shape = _rotate_about_back_hinge(
                terminal_shape,
                -BACK_FOLD_DEG,
            )

        fixed_box = _Box.from_shape(fixed_shape)
        moving_box = _Box.from_shape(moving_shape)
        terminal_box = _Box.from_shape(terminal_shape)
        sleeve_common = _intersection_volume(fixed_shape, moving_shape)
        sleeve_clearance = float(fixed_shape.distance(moving_shape))
        sleeve_axial_overlap = max(
            0.0,
            min(fixed_box.zmax, moving_box.zmax)
            - max(fixed_box.zmin, moving_box.zmin),
        )
        # The fixed sleeve now includes a real -X lock-pin bearing boss, so its
        # overall AABB is intentionally asymmetric.  Coaxiality belongs to the
        # controlled sleeve datums, not to the centre of cosmetic/accessory
        # bounding geometry.
        fixed_axis_x = fixed.metadata.get(
            "controlled_axis_x_mm",
            A07_MAST_AXIS_X_MM,
        )
        moving_axis_x = moving.metadata.get(
            "controlled_axis_x_mm",
            A07_MAST_AXIS_X_MM,
        )
        coaxial_error = (
            max(
                abs(float(fixed_axis_x) - A07_MAST_AXIS_X_MM),
                abs(float(moving_axis_x) - A07_MAST_AXIS_X_MM),
                abs(fixed_box.center[1] - moving_box.center[1]),
            )
            if isinstance(fixed_axis_x, (int, float))
            and isinstance(moving_axis_x, (int, float))
            else math.inf
        )
        terminal_common = _intersection_volume(moving_shape, terminal_shape)
        terminal_clearance = float(moving_shape.distance(terminal_shape))
        microphone_common = _intersection_volume(
            moving.shape,
            microphone.shape,
        )
        microphone_clearance = float(
            moving.shape.distance(microphone.shape)
        )
        terminal_axial_overlap = max(
            0.0,
            min(moving_box.zmax, terminal_box.zmax)
            - max(moving_box.zmin, terminal_box.zmin),
        )
        focus_z_shift = A07_FOCUS_TRANSLATION_MM if state == "focus" else 0.0

        def numeric_pair(value: object) -> tuple[float, float] | None:
            if (
                isinstance(value, (list, tuple))
                and len(value) == 2
                and all(isinstance(item, (int, float)) for item in value)
            ):
                return (float(value[0]), float(value[1]))
            return None

        tenon_bounds = numeric_pair(
            moving.metadata.get("terminal_tenon_bounds_z_mm")
        )
        cosmetic_bounds = numeric_pair(
            moving.metadata.get("cosmetic_spine_bounds_z_mm")
        )
        socket_bounds = numeric_pair(
            terminal.metadata.get("terminal_socket_bounds_z_mm")
        )
        radial_gap = numeric_pair(
            moving.metadata.get("terminal_joint_radial_assembly_gap_mm")
        )
        socket_plan = numeric_pair(
            terminal.metadata.get("terminal_socket_plan_mm")
        )
        terminal_engagement = (
            max(
                0.0,
                min(tenon_bounds[1] + focus_z_shift, terminal_box.zmax)
                - max(tenon_bounds[0] + focus_z_shift, terminal_box.zmin),
            )
            if tenon_bounds is not None
            else None
        )
        cosmetic_dry_seam = (
            terminal_box.zmin - (cosmetic_bounds[1] + focus_z_shift)
            if cosmetic_bounds is not None
            else None
        )
        socket_end_clearance = (
            socket_bounds[1] - tenon_bounds[1]
            if socket_bounds is not None and tenon_bounds is not None
            else None
        )
        socket_void_witness = rounded_box(
            (42.0, 86.0, 26.0),
            (
                A07_MAST_AXIS_X_MM,
                0.0,
                1013.0 + focus_z_shift,
            ),
            6.0,
        )
        socket_void_common = _intersection_volume(
            terminal_shape,
            socket_void_witness,
        )
        terminal_interface_metadata_pass = (
            tenon_bounds is not None
            and max(abs(a - b) for a, b in zip(tenon_bounds, (1000.0, 1024.0)))
            <= 0.05
            and cosmetic_bounds is not None
            and max(abs(a - b) for a, b in zip(cosmetic_bounds, (438.0, 1004.0)))
            <= 0.05
            and socket_bounds is not None
            and max(abs(a - b) for a, b in zip(socket_bounds, (1000.0, 1026.0)))
            <= 0.05
            and radial_gap is not None
            and max(
                abs(value - A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM)
                for value in radial_gap
            )
            <= 0.05
            and socket_plan is not None
            and max(abs(a - b) for a, b in zip(socket_plan, (42.0, 86.0)))
            <= 0.05
            and moving.metadata.get("terminal_tenon_plan_mm") == (36.0, 80.0)
            and float(moving.metadata.get("terminal_tenon_engagement_mm", -1.0))
            == A07_TERMINAL_TENON_ENGAGEMENT_MM
            and float(moving.metadata.get("terminal_joint_end_clearance_mm", -1.0))
            == A07_TERMINAL_END_CLEARANCE_MM
            and float(moving.metadata.get("terminal_joint_dry_seam_mm", -1.0))
            == A07_TERMINAL_COSMETIC_DRY_SEAM_MM
            and terminal.metadata.get(
                "terminal_socket_captures_moving_spine_tenon"
            )
            is True
        )
        terminal_axis = terminal.metadata.get("controlled_axis_x_mm")
        expected_focus_translation = (
            A07_FOCUS_TRANSLATION_MM if state == "focus" else 0.0
        )
        physical_ids = [
            fixed.metadata.get("physical_occurrence_id"),
            moving.metadata.get("physical_occurrence_id"),
            terminal.metadata.get("physical_occurrence_id"),
        ]
        book.add(
            f"a07.{state}.single_one_piece_moving_spine",
            moving_stage_names == [moving_name]
            and moving.metadata.get("telescopic_stage_count") == 1
            and moving.metadata.get("one_piece_finished_observation_spine") is True
            and moving.metadata.get("three_stage_suitcase_handle_architecture_removed")
            is True
            and float(moving.metadata.get("minimum_extended_overlap_mm", 0.0))
            >= A07_MINIMUM_EXTENDED_CAPTURE_MM
            and float(moving.metadata.get("focus_translation_mm", -1.0))
            == expected_focus_translation
            and all(physical_ids)
            and len(physical_ids) == len(set(physical_ids))
            and all(
                len(part.shape.Solids()) == 1
                for part in (fixed, moving, terminal)
            )
            and sleeve_common <= BOOLEAN_TOLERANCE_MM3
            and sleeve_clearance >= 3.0 - DISTANCE_TOLERANCE_MM
            and sleeve_axial_overlap
            >= A07_MINIMUM_EXTENDED_CAPTURE_MM - DISTANCE_TOLERANCE_MM
            and coaxial_error <= 0.01
            and terminal_common <= BOOLEAN_TOLERANCE_MM3
            and terminal_clearance > DISTANCE_TOLERANCE_MM
            and abs(
                terminal_clearance - A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM
            )
            <= 0.05
            and abs(
                terminal_axial_overlap - A07_TERMINAL_TENON_ENGAGEMENT_MM
            )
            <= 0.05
            and socket_void_common <= BOOLEAN_TOLERANCE_MM3
            and terminal_engagement is not None
            and abs(
                terminal_engagement - A07_TERMINAL_TENON_ENGAGEMENT_MM
            )
            <= 0.05
            and cosmetic_dry_seam is not None
            and abs(
                cosmetic_dry_seam - A07_TERMINAL_COSMETIC_DRY_SEAM_MM
            )
            <= 0.05
            and socket_end_clearance is not None
            and abs(
                socket_end_clearance - A07_TERMINAL_END_CLEARANCE_MM
            )
            <= 0.05
            and terminal_interface_metadata_pass
            and microphone_common <= BOOLEAN_TOLERANCE_MM3
            and microphone_clearance
            >= A07_MICROPHONE_TENON_MINIMUM_DRY_CLEARANCE_MM
            - DISTANCE_TOLERANCE_MM
            and float(
                microphone.metadata.get(
                    "minimum_dry_clearance_to_terminal_tenon_mm",
                    -1.0,
                )
            )
            == A07_MICROPHONE_TENON_MINIMUM_DRY_CLEARANCE_MM
            and microphone.metadata.get(
                "terminal_tenon_acoustic_path_is_outboard"
            )
            is True
            and isinstance(terminal_axis, (int, float))
            and abs(float(terminal_axis) - A07_MAST_AXIS_X_MM) <= 0.05,
            evidence_kind="brep_single_spine_interface_and_occurrence_identity",
            requirement=(
                "A07 contains exactly one finished moving spine inside one fixed sleeve; "
                "the same crowned terminal receives its hidden tenon through a real "
                "3 mm radial socket gap, never zero-distance face contact.  No stage 2 "
                "or stage 3 occurrence may return.  Focus preserves at least 150 mm "
                "sleeve capture while translating the one moving assembly exactly +420 mm."
            ),
            moving_stage_inventory=moving_stage_names,
            physical_occurrence_ids=physical_ids,
            fixed_bounds=fixed_box.to_dict(),
            moving_bounds=moving_box.to_dict(),
            terminal_bounds=terminal_box.to_dict(),
            sleeve_common_volume_mm3=round(sleeve_common, 9),
            sleeve_dry_clearance_mm=round(sleeve_clearance, 6),
            sleeve_axial_overlap_mm=round(sleeve_axial_overlap, 6),
            sleeve_coaxial_axis_error_mm=round(coaxial_error, 9),
            moving_to_terminal_common_volume_mm3=round(terminal_common, 9),
            moving_to_terminal_minimum_distance_mm=round(terminal_clearance, 6),
            moving_to_terminal_bbox_axial_overlap_mm=round(
                terminal_axial_overlap, 6
            ),
            terminal_socket_void_common_volume_mm3=round(
                socket_void_common, 9
            ),
            terminal_tenon_bounds_z_mm=tenon_bounds,
            terminal_socket_bounds_z_mm=socket_bounds,
            cosmetic_spine_bounds_z_mm=cosmetic_bounds,
            measured_terminal_tenon_engagement_mm=(
                round(terminal_engagement, 6)
                if terminal_engagement is not None
                else None
            ),
            measured_terminal_socket_end_clearance_mm=(
                round(socket_end_clearance, 6)
                if socket_end_clearance is not None
                else None
            ),
            measured_cosmetic_spine_to_terminal_dry_seam_mm=(
                round(cosmetic_dry_seam, 6)
                if cosmetic_dry_seam is not None
                else None
            ),
            declared_terminal_radial_gap_mm=radial_gap,
            terminal_interface_metadata_pass=terminal_interface_metadata_pass,
            moving_to_microphone_common_volume_mm3=round(
                microphone_common,
                9,
            ),
            moving_to_microphone_minimum_distance_mm=round(
                microphone_clearance,
                6,
            ),
            required_microphone_to_tenon_dry_clearance_mm=(
                A07_MICROPHONE_TENON_MINIMUM_DRY_CLEARANCE_MM
            ),
            controlled_terminal_axis_x_mm=terminal_axis,
            expected_focus_translation_mm=expected_focus_translation,
        )

        rear_surround = _part(states[state], "A10_rear_service_surround")
        surround_common = _intersection_volume(
            moving.shape,
            rear_surround.shape,
        )
        surround_clearance = float(
            moving.shape.distance(rear_surround.shape)
        )
        low_operational_state = state in {"ride", "cafe"}
        required_surround_clearance = 3.5 if low_operational_state else 0.0
        tunnel_metadata_pass = (
            rear_surround.metadata.get(
                "a07_low_spine_through_tunnel_mm"
            )
            == (62.4, 128.4, 72.0)
            and rear_surround.metadata.get(
                "a07_low_spine_tunnel_center_mm"
            )
            == (310.0, 0.0, 465.0)
            and float(
                rear_surround.metadata.get(
                    "a07_low_spine_minimum_nominal_radial_clearance_mm",
                    -1.0,
                )
            )
            == 3.5
            and rear_surround.metadata.get(
                "a07_low_spine_tunnel_hidden_by_a06_channel"
            )
            is True
        )
        book.add(
            f"a07_a10.{state}.moving_spine_real_service_surround_tunnel",
            surround_common <= BOOLEAN_TOLERANCE_MM3
            and (
                surround_clearance
                >= required_surround_clearance - DISTANCE_TOLERANCE_MM
                if low_operational_state
                else surround_clearance > DISTANCE_TOLERANCE_MM
            )
            and tunnel_metadata_pass,
            evidence_kind="exact_brep_intersection_distance_and_tunnel_metadata",
            requirement=(
                "A10 must contain a real through-tunnel for the one-piece A07 "
                "spine. Ride/Cafe require at least 3.5 mm dry clearance; Follow "
                "and Focus must remain rigidly disjoint. This interface may not "
                "be satisfied by a collision allowlist."
            ),
            moving_spine=moving.name,
            rear_service_surround=rear_surround.name,
            common_volume_mm3=round(surround_common, 9),
            measured_minimum_distance_mm=round(surround_clearance, 6),
            required_minimum_distance_mm=required_surround_clearance,
            low_operational_state=low_operational_state,
            tunnel_metadata_pass=tunnel_metadata_pass,
            collision_allowlist_permitted=False,
        )

    conserved_names = sorted(
        part.name
        for part in states["ride"]
        if part.name.startswith("A07_")
    )
    for name in conserved_names:
        parts = {state: _part(states[state], name) for state in STATES}
        reference = parts["ride"]
        evidence: dict[str, Any] = {}
        passed = True
        reference_id = reference.metadata.get("physical_occurrence_id")
        for state, part in parts.items():
            normalised = part.shape
            inverse_translation = (0.0, 0.0, 0.0)
            if state == "follow":
                normalised = _rotate_about_back_hinge(
                    normalised,
                    -BACK_FOLD_DEG,
                )
            elif state == "focus":
                inverse_translation = _a07_focus_inverse_translation(name)
                normalised = normalised.translate(inverse_translation)
            comparison = _brep_pose_evidence(reference.shape, normalised)
            passed = passed and (
                part.metadata.get("physical_occurrence_id") == reference_id
                and part.metadata.get("same_brep_all_states") is True
                and _brep_pose_matches(comparison)
            )
            evidence[state] = {
                "pose": part.metadata.get("pose"),
                "physical_occurrence_id": part.metadata.get(
                    "physical_occurrence_id"
                ),
                "declared_inverse_focus_translation_mm": inverse_translation,
                "comparison_after_declared_pose_inverse": comparison,
            }
        book.add(
            f"a07.cross_state.{name}.conserved_physical_brep",
            passed,
            evidence_kind="cross_state_brep_metric_topology_and_occurrence_identity",
            requirement=(
                "Every A07 sleeve, terminal and functional insert retains one physical "
                "BRep across Follow, Ride, Cafe and Focus; only the shared Follow hinge, "
                "the one +420 mm spine motion and the shutter's declared +136 mm park are permitted."
            ),
            physical_occurrence_id=reference_id,
            states=evidence,
        )


def _gate_a07_positive_lock_interlock(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Prove real endpoint bores, inserted pins and withdrawal before motion."""

    pin_names = ("A07_mast_lock_pin_left", "A07_mast_lock_pin_right")
    master = _production_a07_low_masters()

    # The four released states are all positively locked endpoints.  Pins stay
    # fixed in Ride/Cafe/Focus and join the one A06/A07 hinge only in Follow.
    for state in STATES:
        moving = _part(states[state], "A07_mast_moving_inner_sleeve")
        fixed = _part(states[state], "A07_mast_fixed_outer_sleeve")
        state_pins = tuple(_part(states[state], name) for name in pin_names)
        state_lenses = tuple(
            _part(
                states[state],
                f"A07_mast_lock_pin_confirmation_lens_{side_name}",
            )
            for side_name in ("left", "right")
        )
        check_moving = moving.shape
        check_fixed = fixed.shape
        check_pins = tuple(pin.shape for pin in state_pins)
        check_lenses = tuple(lens.shape for lens in state_lenses)
        if state == "follow":
            check_moving = _rotate_about_back_hinge(check_moving, -BACK_FOLD_DEG)
            check_fixed = _rotate_about_back_hinge(check_fixed, -BACK_FOLD_DEG)
            check_pins = tuple(
                _rotate_about_back_hinge(shape, -BACK_FOLD_DEG)
                for shape in check_pins
            )
            check_lenses = tuple(
                _rotate_about_back_hinge(shape, -BACK_FOLD_DEG)
                for shape in check_lenses
            )
        expected_moving = (
            master["moving"].translate((0.0, 0.0, A07_FOCUS_STROKE_MM))
            if state == "focus"
            else master["moving"]
        )
        expected_pin_shapes = (
            master["lock_pin_engaged_left"],
            master["lock_pin_engaged_right"],
        )
        pin_evidence: dict[str, Any] = {}
        lens_evidence: dict[str, Any] = {}
        passed = _brep_pose_matches(
            _brep_pose_evidence(master["fixed"], check_fixed)
        ) and _brep_pose_matches(
            _brep_pose_evidence(expected_moving, check_moving)
        )
        for side_name, part, shape in zip(
            ("left", "right"),
            state_lenses,
            check_lenses,
        ):
            expected = master[f"lock_lens_{side_name}"]
            comparison = _brep_pose_evidence(expected, shape)
            common = _intersection_volume(shape, check_fixed)
            clearance = float(shape.distance(check_fixed))
            item_pass = (
                _brep_pose_matches(comparison)
                and common <= BOOLEAN_TOLERANCE_MM3
                and 0.29 <= clearance <= 0.31
                and part.metadata.get("structural_lock_credit") is False
            )
            passed = passed and item_pass
            lens_evidence[side_name] = {
                "comparison_to_recessed_lens_master": comparison,
                "fixed_sleeve_common_volume_mm3": round(common, 9),
                "recessed_seat_radial_clearance_mm": round(clearance, 6),
                "structural_lock_credit": part.metadata.get(
                    "structural_lock_credit"
                ),
            }
        for name, part, shape, expected in zip(
            pin_names,
            state_pins,
            check_pins,
            expected_pin_shapes,
        ):
            comparison = _brep_pose_evidence(expected, shape)
            moving_common = _intersection_volume(shape, check_moving)
            fixed_common = _intersection_volume(shape, check_fixed)
            moving_distance = float(shape.distance(check_moving))
            fixed_distance = float(shape.distance(check_fixed))
            metadata_pass = (
                part.metadata.get("pin_is_structural_not_confirmation_lens")
                is True
                and part.metadata.get("commanded_motion_requires_full_retraction")
                is True
                and part.metadata.get("redundant_pair_required") is True
                and float(part.metadata.get("pin_diameter_mm", -1.0))
                == A07_LOCK_PIN_DIAMETER_MM
                and float(part.metadata.get("mating_bore_diameter_mm", -1.0))
                == A07_LOCK_BORE_DIAMETER_MM
            )
            item_pass = (
                _brep_pose_matches(comparison)
                and moving_common <= BOOLEAN_TOLERANCE_MM3
                and fixed_common <= BOOLEAN_TOLERANCE_MM3
                and abs(moving_distance - 0.25) <= 0.02
                and abs(fixed_distance - 0.25) <= 0.02
                and metadata_pass
            )
            passed = passed and item_pass
            pin_evidence[name] = {
                "comparison_to_engaged_master": comparison,
                "moving_common_volume_mm3": round(moving_common, 9),
                "fixed_common_volume_mm3": round(fixed_common, 9),
                "moving_radial_clearance_mm": round(moving_distance, 6),
                "fixed_radial_clearance_mm": round(fixed_distance, 6),
                "metadata_pass": metadata_pass,
            }
        book.add(
            f"a07.{state}.real_positive_lock_pins_engaged",
            passed,
            evidence_kind="endpoint_pin_brep_identity_clearance_and_load_owner",
            requirement=(
                "Every released state contains two conserved hardened lock pins, "
                "not just witness lenses.  Low and Focus endpoint holes meet the "
                "same fixed Z=888 station with 0.25 mm radial running clearance; "
                "each non-structural witness is separately seated 0.3 mm clear "
                "of the fixed sleeve wall."
            ),
            endpoint="focus" if state == "focus" else "low",
            lock_station_z_mm=A07_LOCK_STATION_Z_MM,
            pin_evidence=pin_evidence,
            confirmation_lens_seat_evidence=lens_evidence,
        )

    # Sample endpoints, the requested 140/280 mm stations, and an intermediate
    # point inside each third of travel.  Only endpoints may command insertion.
    strokes = (0.0, 70.0, 140.0, 210.0, 280.0, 350.0, 420.0)
    for stroke in strokes:
        pose = a07_lock_motion_pose(stroke)
        endpoint = stroke in {0.0, A07_FOCUS_STROKE_MM}
        fixed_moving_common = _intersection_volume(
            pose.fixed_sleeve,
            pose.moving_spine,
        )
        fixed_moving_clearance = float(
            pose.fixed_sleeve.distance(pose.moving_spine)
        )
        active_world_z = (
            None
            if pose.active_bore_master_z_mm is None
            else pose.active_bore_master_z_mm + stroke
        )
        pin_evidence: list[dict[str, float]] = []
        passed = (
            fixed_moving_common <= BOOLEAN_TOLERANCE_MM3
            and fixed_moving_clearance >= 3.0 - DISTANCE_TOLERANCE_MM
            and pose.pin_state == ("engaged" if endpoint else "retracted")
            and (
                active_world_z is None
                if not endpoint
                else abs(active_world_z - A07_LOCK_STATION_Z_MM) <= 1.0e-6
            )
        )
        for pin in pose.lock_pins:
            moving_common = _intersection_volume(pin, pose.moving_spine)
            fixed_common = _intersection_volume(pin, pose.fixed_sleeve)
            moving_distance = float(pin.distance(pose.moving_spine))
            fixed_distance = float(pin.distance(pose.fixed_sleeve))
            pin_box = _Box.from_shape(pin)
            if endpoint:
                kinematic_pass = (
                    abs(moving_distance - 0.25) <= 0.02
                    and abs(fixed_distance - 0.25) <= 0.02
                    and pin_box.xmax > _Box.from_shape(pose.moving_spine).xmin
                )
            else:
                kinematic_pass = (
                    pin_box.xmax
                    <= A07_LOCK_PIN_RETRACTED_X_MM[1] + DISTANCE_TOLERANCE_MM
                    and moving_distance >= 5.0 - DISTANCE_TOLERANCE_MM
                    and abs(fixed_distance - 0.25) <= 0.02
                )
            passed = passed and (
                moving_common <= BOOLEAN_TOLERANCE_MM3
                and fixed_common <= BOOLEAN_TOLERANCE_MM3
                and kinematic_pass
            )
            pin_evidence.append(
                {
                    "moving_common_volume_mm3": round(moving_common, 9),
                    "fixed_common_volume_mm3": round(fixed_common, 9),
                    "moving_minimum_distance_mm": round(moving_distance, 6),
                    "fixed_minimum_distance_mm": round(fixed_distance, 6),
                    "pin_xmax_mm": round(pin_box.xmax, 6),
                }
            )
        stroke_token = str(int(stroke)).zfill(3)
        book.add(
            f"a07.lock_motion.stroke_{stroke_token}.withdraw_before_translate",
            passed,
            evidence_kind="sampled_brep_pin_withdrawal_and_sleeve_clearance",
            requirement=(
                "Both radial pins may be inserted only at 0 or 420 mm.  Every "
                "intermediate mast pose must show the pins fully behind X=276, "
                "with at least 5 mm clearance to the translating member."
            ),
            stroke_mm=stroke,
            commanded_pin_state=pose.pin_state,
            active_bore_master_z_mm=pose.active_bore_master_z_mm,
            active_bore_world_z_mm=active_world_z,
            fixed_to_moving_common_volume_mm3=round(fixed_moving_common, 9),
            fixed_to_moving_minimum_distance_mm=round(
                fixed_moving_clearance,
                6,
            ),
            pins=pin_evidence,
        )

    # A conservative axis-aligned prism encloses every possible location of a
    # fully retracted cylindrical pin in the moving member's inverse frame.
    # Disjointness from this superset closes the continuous 0..420 mm stroke;
    # it is stronger than relying only on the seven sampled stations above.
    swept_pin_evidence: dict[str, dict[str, float]] = {}
    swept_pin_pass = True
    sweep_xmin, sweep_xmax = A07_LOCK_PIN_RETRACTED_X_MM
    sweep_zmin = A07_LOCK_STATION_Z_MM - A07_FOCUS_STROKE_MM - (
        A07_LOCK_PIN_DIAMETER_MM / 2.0
    )
    sweep_zmax = A07_LOCK_STATION_Z_MM + A07_LOCK_PIN_DIAMETER_MM / 2.0
    for side_name, y_mm in (
        ("left", -A07_LOCK_PIN_Y_MM),
        ("right", A07_LOCK_PIN_Y_MM),
    ):
        swept_superset = (
            cq.Workplane("XY")
            .box(
                sweep_xmax - sweep_xmin,
                A07_LOCK_PIN_DIAMETER_MM,
                sweep_zmax - sweep_zmin,
            )
            .translate(
                (
                    (sweep_xmin + sweep_xmax) / 2.0,
                    y_mm,
                    (sweep_zmin + sweep_zmax) / 2.0,
                )
            )
            .val()
        )
        common = _intersection_volume(master["moving"], swept_superset)
        distance = float(master["moving"].distance(swept_superset))
        swept_pin_pass = swept_pin_pass and (
            common <= BOOLEAN_TOLERANCE_MM3
            and distance >= 5.0 - DISTANCE_TOLERANCE_MM
        )
        swept_pin_evidence[side_name] = {
            "common_volume_mm3": round(common, 9),
            "minimum_distance_mm": round(distance, 6),
        }
    book.add(
        "a07.lock_motion.continuous_retracted_pin_swept_superset",
        swept_pin_pass,
        evidence_kind="conservative_full_stroke_swept_volume_brep",
        requirement=(
            "A conservative prism containing every retracted-pin position in "
            "the moving member's inverse 0..420 mm frame must remain disjoint "
            "with at least 5 mm clearance; discrete samples alone are insufficient."
        ),
        swept_superset_x_mm=(sweep_xmin, sweep_xmax),
        swept_superset_z_mm=(sweep_zmin, sweep_zmax),
        per_side=swept_pin_evidence,
    )

    def x_cylinder(radius: float, y: float, z: float) -> cq.Shape:
        return cq.Solid.makeCylinder(
            radius,
            68.0,
            cq.Vector(276.0, y, z),
            cq.Vector(1.0, 0.0, 0.0),
        )

    bearing_radius = A07_LOCK_BORE_DIAMETER_MM / 2.0 + 0.25
    bore_bearing_common: dict[str, float] = {}
    mid_web_common: dict[str, float] = {}
    for side_name, y_mm in (
        ("left", -A07_LOCK_PIN_Y_MM),
        ("right", A07_LOCK_PIN_Y_MM),
    ):
        for endpoint_name, z_mm in (
            ("low", A07_LOCK_LOW_BORE_Z_MM),
            ("focus", A07_LOCK_FOCUS_BORE_Z_MM),
        ):
            probe = x_cylinder(bearing_radius, y_mm, z_mm)
            bore_bearing_common[f"{side_name}_{endpoint_name}"] = (
                _intersection_volume(master["moving"], probe)
            )
        web_probe = x_cylinder(
            2.0,
            y_mm,
            (A07_LOCK_LOW_BORE_Z_MM + A07_LOCK_FOCUS_BORE_Z_MM) / 2.0,
        )
        mid_web_common[side_name] = _intersection_volume(
            master["moving"],
            web_probe,
        )
    moving_part = _part(states["ride"], "A07_mast_moving_inner_sleeve")
    book.add(
        "a07.lock_geometry.two_discrete_endpoint_bores_not_slot",
        all(value >= 40.0 for value in bore_bearing_common.values())
        and all(value >= 80.0 for value in mid_web_common.values())
        and moving_part.metadata.get("endpoint_lock_bores_are_discrete") is True
        and moving_part.metadata.get("longitudinal_lock_slot_present") is False,
        evidence_kind="oversize_bearing_probes_and_midspan_material_web",
        requirement=(
            "Each side has two circular endpoint bores separated by intact mast "
            "wall.  A continuous 420 mm slot cannot be used as a substitute."
        ),
        endpoint_oversize_probe_common_volume_mm3={
            key: round(value, 9) for key, value in bore_bearing_common.items()
        },
        midspan_wall_probe_common_volume_mm3={
            key: round(value, 9) for key, value in mid_web_common.items()
        },
        endpoint_master_z_mm=(
            A07_LOCK_LOW_BORE_Z_MM,
            A07_LOCK_FOCUS_BORE_Z_MM,
        ),
        endpoint_separation_mm=abs(
            A07_LOCK_LOW_BORE_Z_MM - A07_LOCK_FOCUS_BORE_Z_MM
        ),
    )


def _gate_a07_privacy_shutter(
    states: Mapping[str, Sequence[SkinPart]],
    root: Path,
    book: _GateBook,
) -> None:
    """Bind Focus to the released shutter B-Rep, pose and real dry clearances."""

    source_path = root / "build" / "parts" / "mast_privacy_shutter_parked_focus.step"
    imported = cq.importers.importStep(str(source_path))
    source = imported.val() if hasattr(imported, "val") else imported
    shutter = _part(states["focus"], "A07_physical_privacy_shutter")
    shutter_box = _Box.from_shape(shutter.shape)
    source_box = _Box.from_shape(source)
    comparison = _brep_pose_evidence(source, shutter.shape)
    center_error = max(
        abs(actual - expected)
        for actual, expected in zip(
            shutter_box.center,
            A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM,
        )
    )
    book.add(
        "a07.focus.privacy_shutter_exact_released_brep_and_pose",
        _brep_pose_matches(comparison) and center_error <= 0.05,
        evidence_kind="direct_source_to_final_world_pose_brep_symmetric_difference",
        requirement=(
            "The one Focus privacy shutter remains the untrimmed controlled B-Rep at "
            "centre (264.5,128,1460) mm; styling may create space around it but may not move it."
        ),
        source_path=str(source_path),
        source_bounds=source_box.to_dict(),
        final_bounds=shutter_box.to_dict(),
        required_center_mm=A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM,
        actual_center_mm=shutter_box.center,
        maximum_center_error_mm=round(center_error, 9),
        comparison=comparison,
    )

    neighbours = {
        "sensor_beam_shell": _part(states["focus"], "A07_sensor_beam_shell"),
        "smoked_window": _part(
            states["focus"],
            "A07_sensor_beam_smoked_window",
        ),
    }
    interfaces: dict[str, Any] = {}
    clearance_pass = True
    for label, neighbour in neighbours.items():
        common = _intersection_volume(shutter.shape, neighbour.shape)
        clearance = float(shutter.shape.distance(neighbour.shape))
        interfaces[label] = {
            "part": neighbour.name,
            "common_volume_mm3": round(common, 9),
            "clearance_mm": round(clearance, 6),
            "bounds": _Box.from_shape(neighbour.shape).to_dict(),
        }
        clearance_pass = (
            clearance_pass
            and common <= BOOLEAN_TOLERANCE_MM3
            and clearance
            >= A07_MINIMUM_DRY_CLEARANCE_MM - DISTANCE_TOLERANCE_MM
        )
    book.add(
        "a07.focus.privacy_shutter_real_dry_clearances",
        clearance_pass,
        evidence_kind="exact_brep_intersection_volume_and_distance",
        requirement=(
            "The released parked shutter may extend beyond the beam end, but it must "
            "remain a separate serviceable solid with real dry clearance to the beam and window."
        ),
        minimum_clearance_mm=A07_MINIMUM_DRY_CLEARANCE_MM,
        interfaces=interfaces,
    )

    for state in STATES:
        bezel = _part(
            states[state],
            "A07_privacy_shutter_carriage_bezel",
        )
        terminal = _part(states[state], "A07_sensor_beam_shell")
        common = _intersection_volume(bezel.shape, terminal.shape)
        clearance = float(bezel.shape.distance(terminal.shape))
        metadata_pass = (
            bezel.metadata.get("carriage_sweep_low_to_park_y_mm")
            == (-8.0, 128.0)
            and float(
                bezel.metadata.get(
                    "carriage_swept_pocket_nominal_clearance_mm",
                    -1.0,
                )
            )
            == A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM
            and bezel.metadata.get(
                "zero_common_volume_with_terminal_required"
            )
            is True
            and float(
                terminal.metadata.get(
                    "privacy_shutter_carriage_pocket_nominal_clearance_mm",
                    -1.0,
                )
            )
            == A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM
        )
        book.add(
            f"a07.{state}.privacy_shutter_bezel_real_swept_carriage_pocket",
            common <= BOOLEAN_TOLERANCE_MM3
            and clearance
            >= A07_SHUTTER_CARRIAGE_MINIMUM_DRY_CLEARANCE_MM
            - DISTANCE_TOLERANCE_MM
            and metadata_pass,
            evidence_kind="exact_brep_intersection_distance_and_motion_pocket_contract",
            requirement=(
                "The conserved moving privacy-shutter bezel must occupy a real "
                "continuous terminal carriage pocket from closed to Focus park, "
                "with zero rigid common volume and a measurable dry clearance."
            ),
            bezel=bezel.name,
            terminal=terminal.name,
            common_volume_mm3=round(common, 9),
            measured_minimum_distance_mm=round(clearance, 6),
            required_minimum_distance_mm=(
                A07_SHUTTER_CARRIAGE_MINIMUM_DRY_CLEARANCE_MM
            ),
            nominal_pocket_clearance_mm=(
                A07_SHUTTER_CARRIAGE_POCKET_NOMINAL_CLEARANCE_MM
            ),
            metadata_pass=metadata_pass,
            collision_allowlist_permitted=False,
        )


def _a08_channel(top: SkinPart, tread: SkinPart, station_x: float) -> cq.Shape:
    # The invariant platform uses three 12 x 96 mm drains in both poses.  This
    # witness stays 0.2 mm inside the released perimeter and derives X/Z from
    # the actual platform, so a stowed pose cannot be tested at Ride's datum.
    top_box = top.shape.BoundingBox()
    tread_box = tread.shape.BoundingBox()
    center_x = (top_box.xmin + top_box.xmax) / 2.0 + station_x
    zmin = min(top_box.zmin, tread_box.zmin) - 0.2
    zmax = max(top_box.zmax, tread_box.zmax) + 0.2
    return rounded_rect_prism(
        (11.6, 95.6),
        zmax - zmin,
        (center_x, 0.0, (zmin + zmax) / 2.0),
        5.8,
    )


def _gate_a08_root_enclosure(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    forbidden_prefixes = (
        "A08_footrest_root_cowl_",
        "A08_footrest_support_boot_",
        "A08_footrest_support_body_collar_",
        "A08_footrest_root_front_visor",
    )
    invariant_platform_names = {
        "A08_footrest_top_skin",
        "A08_footrest_inset_tread",
        "A08_footrest_perimeter_skin",
    }
    endpoint_reference = a08_footrest_drawer_occurrences(0.0, "ride")
    mechanism_inventory_names = set(endpoint_reference)
    non_platform_mechanism_names = (
        mechanism_inventory_names - invariant_platform_names
    )
    body_side_release_name = "A08_manual_release_paddle_shell"
    body_side_release_occurrence_id = "E6-A08-MANUAL-RELEASE-PADDLE-SHELL"
    platform_occurrence_ids = {
        "A08_footrest_top_skin": "E6-A08-PLATFORM-TOP-SKIN",
        "A08_footrest_inset_tread": "E6-A08-PLATFORM-TREAD",
        "A08_footrest_perimeter_skin": "E6-A08-PLATFORM-PERIMETER-SKIN",
    }
    for state in STATES:
        platform = {
            name: [part for part in states[state] if part.name == name]
            for name in invariant_platform_names
        }
        mechanism_present = sorted(
            part.name
            for part in states[state]
            if part.name in mechanism_inventory_names
        )
        body_side_release = [
            part for part in states[state] if part.name == body_side_release_name
        ]
        optional_open = optional_footrest_open_available(state)
        platform_parts = [members[0] for members in platform.values() if len(members) == 1]
        book.add(
            f"a08.{state}.primary_footrest_state_contract",
            all(len(members) == 1 for members in platform.values())
            and len(body_side_release) == 1
            and mechanism_present == sorted(mechanism_inventory_names)
            and all(
                part.metadata.get("footrest_pose") == DEFAULT_FOOTREST_STATE[state]
                and part.metadata.get("default_footrest_state")
                == DEFAULT_FOOTREST_STATE[state]
                and part.metadata.get("optional_footrest_open_available") is optional_open
                and part.metadata.get("optional_substate_in_primary_render_set") is False
                and part.metadata.get("footrest_contract_version")
                == FOOTREST_CONTRACT_VERSION
                and part.metadata.get("physical_occurrence_id")
                == platform_occurrence_ids[part.name]
                for part in platform_parts
            ),
            evidence_kind="state_inventory_and_primary_optional_substate_metadata",
            requirement=(
                "One invariant A08 top/tread/perimeter assembly and the complete "
                "captured-guide, cartridge, inner-rail, four-link, bearing, pin, "
                "positive-lock, synchroniser, counterbalance, manual-release and "
                "two-channel foot-zone-sensor inventory must exist in every state. "
                "Hidden stowage changes transforms but never deletes hardware."
            ),
            expected_default_state=DEFAULT_FOOTREST_STATE[state],
            expected_optional_open_available=optional_open,
            invariant_platform_counts={name: len(members) for name, members in platform.items()},
            mechanism_occurrences=mechanism_present,
            body_side_release_occurrences=[part.name for part in body_side_release],
            platform_metadata={part.name: dict(part.metadata) for part in platform_parts},
        )

        nose = _part(states[state], "A01_front_nose_shell")
        release_corridor = a08_manual_release_corridor()
        corridor_common = _intersection_volume(nose.shape, release_corridor)
        partition_history = nose.metadata.get("cross_rigid_partition_history", ())
        corridor_history = [
            record
            for record in partition_history
            if isinstance(record, Mapping)
            and record.get("interface")
            in {
                "A01_A08_manual_release_aperture",
                "A01_A08_permanent_manual_release_corridor",
            }
        ]
        book.add(
            f"a08.{state}.shared_a01_permanent_release_corridor",
            corridor_common <= BOOLEAN_TOLERANCE_MM3
            and bool(corridor_history)
            and any(
                float(record.get("functional_clearance_mm", 0.0))
                >= 1.0
                for record in corridor_history
            ),
            evidence_kind="exact_brep_corridor_boolean_and_partition_history",
            requirement=(
                "The one physical A01 nose must retain the deployed A08 manual-"
                "release corridor in every primary state, including while Cafe/"
                "Focus keep the footrest stowed."
            ),
            corridor_common_volume_mm3=round(corridor_common, 9),
            corridor_bounds=_Box.from_shape(release_corridor).to_dict(),
            partition_history=corridor_history,
            state_dependent_nose_cut_permitted=False,
            collision_allowlist_used=False,
        )

    platform_motion_evidence: dict[str, Any] = {}
    platform_motion_pass = True
    for state in STATES:
        progress = 1.0 if default_footrest_is_deployed(state) else 0.0
        motion = a08_footrest_drawer_occurrences(progress, state)
        state_evidence: dict[str, Any] = {}
        for name in sorted(invariant_platform_names):
            final = _part(states[state], name)
            proxy = motion[name]
            common = _intersection_volume(final.shape, proxy)
            final_minus_motion = float(final.shape.cut(proxy).Volume())
            motion_minus_final = float(proxy.cut(final.shape).Volume())
            symmetric_difference = (
                float(final.shape.Volume())
                + float(proxy.Volume())
                - 2.0 * common
            )
            if name in {
                "A08_footrest_top_skin",
                "A08_footrest_inset_tread",
            }:
                relation = "exact_same_brep"
                relation_pass = abs(symmetric_difference) <= 1.0e-3
            else:
                relation = "final_brep_contained_by_conservative_motion_superset"
                relation_pass = (
                    final_minus_motion <= BOOLEAN_TOLERANCE_MM3
                    and motion_minus_final > BOOLEAN_TOLERANCE_MM3
                )
            metadata_pass = final.metadata.get("motion_geometry_relation") == relation
            state_evidence[name] = {
                "relation": relation,
                "common_volume_mm3": round(common, 6),
                "symmetric_difference_mm3": round(symmetric_difference, 6),
                "final_minus_motion_volume_mm3": round(final_minus_motion, 6),
                "motion_minus_final_volume_mm3": round(motion_minus_final, 6),
                "metadata_pass": metadata_pass,
                "status": "PASS" if relation_pass and metadata_pass else "FAIL",
            }
            platform_motion_pass = (
                platform_motion_pass and relation_pass and metadata_pass
            )
        platform_motion_evidence[state] = state_evidence
    book.add(
        "a08.final_platform_brep_vs_conservative_motion_envelope",
        platform_motion_pass,
        evidence_kind="exact_brep_symmetric_difference_and_set_containment",
        requirement=(
            "The final A08 top and tread must be the exact solids swept by the "
            "motion model.  The finished perimeter may use its released rear "
            "service throat only when it is wholly contained by the larger "
            "collision envelope; equal bounding boxes alone are not evidence."
        ),
        comparisons=platform_motion_evidence,
        bounding_box_only_comparison_permitted=False,
        collision_envelope_may_be_smaller_than_final_brep=False,
    )

    endpoint_identity_evidence: dict[str, Any] = {}
    endpoint_identity_pass = True
    for state in STATES:
        progress = 1.0 if default_footrest_is_deployed(state) else 0.0
        expected = a08_footrest_drawer_occurrences(progress, state)
        actual = {part.name: part for part in states[state]}
        state_evidence: dict[str, Any] = {}
        for name in sorted(non_platform_mechanism_names):
            part = actual.get(name)
            if part is None:
                endpoint_identity_pass = False
                state_evidence[name] = {"missing": True}
                continue
            comparison = _brep_pose_evidence(expected[name], part.shape)
            expected_id = "E6-" + name.upper().replace("_", "-")
            fixed = name in A08_FIXED_OCCURRENCE_NAMES
            metadata_ok = (
                part.metadata.get("physical_occurrence_id") == expected_id
                and part.metadata.get("same_physical_occurrence_all_states")
                is True
                and part.metadata.get("a08_motion_contract")
                == "captured_drawer_over_centre_v1"
                and abs(
                    float(part.metadata.get("a08_motion_progress", -1.0))
                    - progress
                )
                <= DISTANCE_TOLERANCE_MM
                and part.metadata.get("body_side_fixed") is fixed
            )
            state_evidence[name] = {
                **comparison,
                "expected_physical_occurrence_id": expected_id,
                "actual_physical_occurrence_id": part.metadata.get(
                    "physical_occurrence_id"
                ),
                "body_side_fixed": fixed,
                "metadata_pass": metadata_ok,
            }
            endpoint_identity_pass = (
                endpoint_identity_pass
                and _brep_pose_matches(comparison)
                and metadata_ok
            )
        endpoint_identity_evidence[state] = {
            "progress": progress,
            "occurrences": state_evidence,
        }
    book.add(
        "a08.four_state_final_brep_identity_matches_motion_endpoints",
        endpoint_identity_pass,
        evidence_kind=(
            "exact_endpoint_brep_identity_physical_occurrence_and_transform"
        ),
        requirement=(
            "Every non-platform A08 mechanism occurrence in the final four-state "
            "Class-A assembly must be the exact B-Rep and endpoint transform from "
            "the captured-drawer motion model, with one stable physical identity."
        ),
        comparisons=endpoint_identity_evidence,
        collision_allowlist_permitted=False,
    )

    motion_evidence = evaluate_a08_footrest_drawer_brep(101)
    digital_motion_pass = bool(
        motion_evidence.get("brep_contract_pass")
        and int(motion_evidence.get("occurrence_count", 0)) == 48
        and motion_evidence.get("same_occurrence_inventory_all_poses")
        and motion_evidence.get("same_occurrence_inventory_all_four_states")
        and motion_evidence.get("all_occurrences_single_valid_solids")
        and motion_evidence.get(
            "rigid_occurrence_volume_topology_signature_constant"
        )
        and float(
            motion_evidence.get(
                "maximum_unintended_moving_vs_moving_common_mm3",
                float("inf"),
            )
        )
        <= BOOLEAN_TOLERANCE_MM3
        and float(
            motion_evidence.get(
                "maximum_moving_vs_fixed_common_mm3",
                float("inf"),
            )
        )
        <= BOOLEAN_TOLERANCE_MM3
        and float(
            motion_evidence.get(
                "minimum_rear_labyrinth_baffle_to_moving_distance_mm",
                0.0,
            )
        )
        >= 4.999
        and motion_evidence.get("lock_pins_retracted_during_motion") is True
        and motion_evidence.get("stowed_lock_pins_geometrically_engaged")
        is True
        and motion_evidence.get("deployed_lock_pins_geometrically_engaged")
        is True
        and motion_evidence.get("physical_foot_zone_sensors_present") is True
        and motion_evidence.get("normal_floor_foot_and_shin_sweep_is_hazard")
        is True
        and motion_evidence.get("two_channel_fail_closed_interlock_required")
        is True
    )
    book.add(
        "a08.captured_drawer_101_pose_digital_motion_contract",
        digital_motion_pass,
        evidence_kind=(
            "101_pose_exact_brep_inventory_collision_lock_and_hazard_evidence"
        ),
        requirement=(
            "At every one-percent pose the same captured-drawer inventory must "
            "remain single-solid and collision-free against itself and its fixed "
            "hardware; both endpoint lock stations must engage through real bores, "
            "all pins must retract in motion, the occupied foot-zone hazard must "
            "remain explicit, and both candidate fail-closed channel modules must "
            "remain in inventory.  Module presence is not sensor coverage proof."
        ),
        evidence=motion_evidence,
        seat_occupancy_mat_is_sufficient=False,
        human_collision_is_not_relabelled_as_clearance=True,
        collision_allowlist_permitted=False,
    )

    # A mechanism-only sweep cannot see the fixed A08 release paddle or the
    # removable A02 side carriers.  Reuse the actual invariant final B-Reps and
    # prove the complete undertray/support paths at the same one-percent poses.
    final_body_evidence = evaluate_a08_final_body_interfaces(
        _part(states["follow"], body_side_release_name).shape,
        {
            side_name: _part(
                states["follow"],
                f"A02_main_side_shell_{side_name}",
            ).shape
            for side_name in ("left", "right")
        },
        101,
    )
    book.add(
        "a08.final_body_interfaces_101_pose_undertray_release_and_support_hosts",
        final_body_evidence.get("pass") is True,
        evidence_kind="101_pose_exact_brep_against_actual_final_fixed_hosts",
        requirement=(
            "The same moving undertray must keep at least 2 mm from the fixed "
            "body-side release shell, and both moving support monocoques must "
            "keep at least 1 mm from the final A02 carriers throughout all 101 "
            "poses; endpoint-only or proxy-envelope evidence is insufficient."
        ),
        evidence=final_body_evidence,
        collision_allowlist_permitted=False,
        state_dependent_host_cut_permitted=False,
    )

    running_gear_evidence = evaluate_a08_retained_running_gear_clearance(
        {
            side: cq.importers.importStep(
                str(WORKSPACE_ROOT / "build" / "parts" / f"tyre_front_{side}.step")
            ).val()
            for side in ("left", "right")
        },
        {
            side: cq.importers.importStep(
                str(
                    WORKSPACE_ROOT
                    / "build"
                    / "parts"
                    / f"suspension_rocker_{side}.step"
                )
            ).val()
            for side in ("left", "right")
        },
        2,
    )
    book.add(
        "a08.complete_inventory_xz_motion_retained_running_gear_clearance",
        running_gear_evidence.get("pass") is True,
        evidence_kind=(
            "endpoint_complete_a08_inventory_with_lateral_invariance_vs_"
            "controlled_front_tyre_and_five_angle_rocker_breps"
        ),
        requirement=(
            "Every A08 occurrence, including the conserved moving support shells "
            "and both fixed interlock channels, must clear each retained front "
            "tyre by at least 12 mm and the controlled +/-10 degree suspension "
            "rocker sweep by at least 3 mm.  A08 motion is constrained to X/Z "
            "translation and rotation about Y, so the governing lateral gaps are "
            "verified at both endpoints rather than by another redundant 101-pose "
            "mechanism rebuild."
        ),
        evidence=running_gear_evidence,
        collision_allowlist_permitted=False,
        retained_source_breps_are_read_only=True,
    )
    book.add(
        "a08.two_channel_foot_zone_coverage_and_occlusion_validation_complete",
        bool(
            motion_evidence.get(
                "independent_sensor_detection_volume_coverage_validated"
            )
            and motion_evidence.get(
                "sensor_sightline_nose_and_footrest_occlusion_validated"
            )
            and motion_evidence.get("foot_zone_interlock_safety_function_established")
        ),
        severity="advisory",
        evidence_kind="explicit_unclosed_sensor_coverage_and_occlusion_register",
        requirement=(
            "Each fail-closed channel needs an independently controlled detection "
            "volume or sightline covering the p=0.12..1 hazardous foot-zone entry, "
            "plus proof that the final A01 nose and moving A08 assembly do not "
            "occlude it.  Two named boxes alone do not establish a safety function."
        ),
        candidate_channel_occurrences=(
            "A08_foot_zone_interlock_channel_a",
            "A08_foot_zone_interlock_channel_b",
        ),
        first_observed_hazard_progress=motion_evidence.get(
            "first_human_brep_hit_progress"
        ),
        last_observed_hazard_progress=motion_evidence.get(
            "last_human_brep_hit_progress"
        ),
        module_inventory_present=motion_evidence.get(
            "physical_foot_zone_sensors_present"
        ),
        independent_detection_volume_coverage_validated=motion_evidence.get(
            "independent_sensor_detection_volume_coverage_validated"
        ),
        final_geometry_occlusion_validated=motion_evidence.get(
            "sensor_sightline_nose_and_footrest_occlusion_validated"
        ),
        safety_function_claimed=False,
    )
    fixed_nose_evidence = evaluate_a08_fixed_host_clearance(
        _part(states["follow"], "A01_front_nose_shell").shape,
        101,
    )
    book.add(
        "a08.actual_final_a01_nose_101_pose_swept_clearance",
        fixed_nose_evidence.get("pass") is True,
        evidence_kind="101_pose_exact_brep_against_actual_final_fixed_host",
        requirement=(
            "Every moving A08 occurrence must have zero common volume with "
            "the actual invariant post-partition A01 front-nose B-Rep at each "
            "one-percent pose; an A08-only fixed-hardware sweep is insufficient."
        ),
        evidence=fixed_nose_evidence,
        surrogate_host_permitted=False,
        collision_allowlist_permitted=False,
    )
    book.add(
        "a08.production_physical_validation_and_certification_complete",
        motion_evidence.get("release_ready") is True,
        severity="advisory",
        evidence_kind="explicit_unclosed_physical_validation_register",
        requirement=(
            "A08 may be called production released only after tolerance-stack, "
            "proof-load, fatigue, contamination, pinch, and two-channel electrical "
            "validation are closed; digital B-Reps alone are not certification."
        ),
        release_ready=motion_evidence.get("release_ready"),
        open_evidence=motion_evidence.get("open_evidence"),
        production_certification_claimed=False,
    )

    reference_state = "follow"
    for name in sorted(invariant_platform_names):
        reference = _part(states[reference_state], name)
        comparisons: dict[str, object] = {}
        passed = True
        for state in STATES:
            candidate = _part(states[state], name)
            translation = (
                (245.0, 0.0, 52.0)
                if default_footrest_is_deployed(state)
                else (0.0, 0.0, 0.0)
            )
            aligned = candidate.shape.translate(translation)
            common = _intersection_volume(reference.shape, aligned)
            symmetric_difference = (
                float(reference.shape.Volume())
                + float(aligned.Volume())
                - 2.0 * common
            )
            state_ok = (
                symmetric_difference <= 1.0e-3
                and len(reference.shape.Faces()) == len(aligned.Faces())
                and len(reference.shape.Edges()) == len(aligned.Edges())
                and candidate.metadata.get("physical_occurrence_id")
                == platform_occurrence_ids[name]
            )
            passed = passed and state_ok
            comparisons[state] = {
                "alignment_translation_mm": translation,
                "common_volume_mm3": round(common, 6),
                "symmetric_difference_mm3": round(symmetric_difference, 6),
                "face_count": len(aligned.Faces()),
                "edge_count": len(aligned.Edges()),
                "status": "PASS" if state_ok else "FAIL",
            }
        book.add(
            f"a08.invariant_platform_brep.{name}",
            passed,
            evidence_kind="pose_normalised_exact_brep_symmetric_difference",
            requirement="A08 platform surface definitions may translate between poses but may not change B-Rep, topology or physical occurrence identity.",
            reference_state=reference_state,
            physical_occurrence_id=platform_occurrence_ids[name],
            comparisons=comparisons,
        )

    release_reference = _part(states["follow"], body_side_release_name)
    release_comparisons: dict[str, object] = {}
    release_passed = True
    for state in STATES:
        candidate = _part(states[state], body_side_release_name)
        common = _intersection_volume(release_reference.shape, candidate.shape)
        symmetric_difference = (
            float(release_reference.shape.Volume())
            + float(candidate.shape.Volume())
            - 2.0 * common
        )
        state_ok = (
            symmetric_difference <= 1.0e-3
            and len(release_reference.shape.Faces()) == len(candidate.shape.Faces())
            and len(release_reference.shape.Edges()) == len(candidate.shape.Edges())
            and candidate.metadata.get("physical_occurrence_id")
            == body_side_release_occurrence_id
            and candidate.metadata.get("body_side_fixed") is True
            and candidate.metadata.get("pose_invariant") is True
        )
        release_passed = release_passed and state_ok
        release_comparisons[state] = {
            "alignment_translation_mm": (0.0, 0.0, 0.0),
            "common_volume_mm3": round(common, 6),
            "symmetric_difference_mm3": round(symmetric_difference, 6),
            "face_count": len(candidate.shape.Faces()),
            "edge_count": len(candidate.shape.Edges()),
            "physical_occurrence_id": candidate.metadata.get(
                "physical_occurrence_id"
            ),
            "status": "PASS" if state_ok else "FAIL",
        }
    book.add(
        "a08.invariant_body_side_manual_release_shell_brep",
        release_passed,
        evidence_kind="identity_transform_exact_brep_symmetric_difference",
        requirement=(
            "The finished manual-release paddle is one body-side physical "
            "occurrence with identical B-Rep, topology and zero transform in "
            "Follow/Ride/Cafe/Focus."
        ),
        reference_state="follow",
        physical_occurrence_id=body_side_release_occurrence_id,
        comparisons=release_comparisons,
    )

    nose_reference = _part(states["follow"], "A01_front_nose_shell")
    nose_comparisons: dict[str, object] = {}
    nose_passed = True
    for state in STATES:
        candidate = _part(states[state], "A01_front_nose_shell")
        common = _intersection_volume(nose_reference.shape, candidate.shape)
        symmetric_difference = (
            float(nose_reference.shape.Volume())
            + float(candidate.shape.Volume())
            - 2.0 * common
        )
        state_ok = (
            symmetric_difference <= 1.0e-3
            and len(nose_reference.shape.Faces()) == len(candidate.shape.Faces())
            and len(nose_reference.shape.Edges()) == len(candidate.shape.Edges())
        )
        nose_passed = nose_passed and state_ok
        nose_comparisons[state] = {
            "alignment_translation_mm": (0.0, 0.0, 0.0),
            "common_volume_mm3": round(common, 6),
            "symmetric_difference_mm3": round(symmetric_difference, 6),
            "face_count": len(candidate.shape.Faces()),
            "edge_count": len(candidate.shape.Edges()),
            "status": "PASS" if state_ok else "FAIL",
        }
    book.add(
        "a01.invariant_front_nose_with_a08_release_corridor_brep",
        nose_passed,
        evidence_kind="identity_transform_exact_brep_symmetric_difference",
        requirement=(
            "The shared A01 front nose, including its permanent A08 manual-"
            "release corridor, must be the identical zero-transform B-Rep in "
            "Follow/Ride/Cafe/Focus; optional deployment may not change it."
        ),
        reference_state="follow",
        comparisons=nose_comparisons,
        state_dependent_nose_geometry_permitted=False,
    )

    rear_labyrinth_evidence = evaluate_a08_rear_labyrinth_sightlines()
    for state in tuple(
        state for state in STATES if default_footrest_is_deployed(state)
    ):
        root = _part(states[state], "A08_footrest_root_monocoque")
        rear_baffle = _part(
            states[state],
            "A08_footrest_rear_labyrinth_baffle",
        )
        supports = [
            _part(
                states[state],
                f"A08_footrest_support_monocoque_{side_name}",
            )
            for side_name in ("left", "right")
        ]
        obsolete = sorted(
            part.name
            for part in states[state]
            if part.name.startswith(forbidden_prefixes)
        )
        throat_probe = rounded_box((1.0, 1.0, 1.0), (-500.0, 0.0, 135.0), 0.1)
        roof_probe = rounded_box((1.0, 1.0, 1.0), (-525.0, 0.0, 156.0), 0.1)
        lower_probe = rounded_box((1.0, 1.0, 1.0), (-525.0, 0.0, 90.0), 0.1)
        throat_common = _intersection_volume(root.shape, throat_probe)
        roof_common = _intersection_volume(root.shape, roof_probe)
        lower_common = _intersection_volume(root.shape, lower_probe)
        support_common = [
            _intersection_volume(root.shape, support.shape)
            for support in supports
        ]
        support_distance = [
            float(root.shape.distance(support.shape)) for support in supports
        ]
        release = _part(states[state], "A08_manual_release_paddle_shell")
        release_common = _intersection_volume(root.shape, release.shape)
        box = _Box.from_shape(root.shape)
        book.add(
            f"a08.{state}.three_dimensional_root_pan_closes_normal_sightlines",
            not obsolete
            and len(root.shape.Solids()) == 1
            and len(rear_baffle.shape.Solids()) == 1
            and all(len(part.shape.Solids()) == 1 for part in supports)
            and box.xmin <= -527.9
            and box.xmin >= -528.1
            and box.ymin <= -259.9
            and box.ymax >= 259.9
            and box.zmax >= 159.9
            and throat_common <= BOOLEAN_TOLERANCE_MM3
            and roof_common >= 0.90
            and lower_common <= BOOLEAN_TOLERANCE_MM3
            and all(value <= BOOLEAN_TOLERANCE_MM3 for value in support_common)
            and all(value >= 2.9 for value in support_distance)
            and release_common <= BOOLEAN_TOLERANCE_MM3
            and root.metadata.get("closed_roof") is True
            and root.metadata.get("closed_front_wall") is False
            and root.metadata.get("closed_side_returns") is True
            and root.metadata.get("central_platform_and_undertray_motion_throat")
            is True
            and root.metadata.get("front_sightline_closes_with_moving_undertray")
            is False
            and root.metadata.get("front_sightline_closed_by_fixed_rear_labyrinth")
            is True
            and root.metadata.get("central_manual_release_access_from_underside")
            is True
            and rear_baffle.metadata.get("fixed_rear_sightline_closeout") is True
            and rear_labyrinth_evidence.get(
                "all_target_ride_front_sightlines_blocked"
            )
            is True
            and rear_labyrinth_evidence.get(
                "all_standing_oblique_sightlines_blocked"
            )
            is True
            and float(
                rear_labyrinth_evidence.get(
                    "minimum_baffle_intercept_x_mm",
                    0.0,
                )
            )
            >= 5.9
            and float(
                rear_labyrinth_evidence.get(
                    "normal_floor_human_common_mm3",
                    float("inf"),
                )
            )
            <= BOOLEAN_TOLERANCE_MM3
            and float(
                rear_labyrinth_evidence.get(
                    "minimum_normal_floor_human_distance_mm",
                    0.0,
                )
            )
            >= 219.9
            and rear_labyrinth_evidence.get(
                "both_guide_mount_feet_face_contact_without_common"
            )
            is True
            and rear_labyrinth_evidence.get(
                "same_fixed_baffle_brep_all_four_states"
            )
            is True,
            evidence_kind=(
                "brep_root_probes_plus_horizontal_and_standing_oblique_"
                "rear_labyrinth_rays"
            ),
            requirement=(
                "The captured-drawer root must retain its open motion throat and "
                "underside release while a separate fixed rear labyrinth B-Rep "
                "blocks every controlled front and standing-oblique sightline. "
                "The root, moving undertray or metadata alone may not be used as "
                "a substitute for physical occlusion."
            ),
            root_monocoque=root.name,
            root_bounds=box.to_dict(),
            support_monocoques=[part.name for part in supports],
            obsolete_fragment_occurrences=obsolete,
            central_motion_throat_probe_common_mm3=round(throat_common, 9),
            roof_probe_common_mm3=round(roof_common, 9),
            lower_service_probe_common_mm3=round(lower_common, 9),
            support_common_volume_mm3=[
                round(value, 9) for value in support_common
            ],
            support_dry_gap_mm=[round(value, 6) for value in support_distance],
            manual_release_common_volume_mm3=round(release_common, 9),
            rear_labyrinth_baffle=rear_baffle.name,
            rear_labyrinth_baffle_bounds=_Box.from_shape(
                rear_baffle.shape
            ).to_dict(),
            rear_labyrinth_sightline_evidence=rear_labyrinth_evidence,
        )


def _gate_a08_drains(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    for state in STATES:
        top = _part(states[state], "A08_footrest_top_skin")
        tread = _part(states[state], "A08_footrest_inset_tread")
        for station in (-50.0, 0.0, 50.0):
            witness = _a08_channel(top, tread, station)
            top_common = _intersection_volume(top.shape, witness)
            tread_common = _intersection_volume(tread.shape, witness)
            book.add(
                f"a08.{state}.drain_station_{station:+.0f}_through_top_and_tread",
                top_common <= BOOLEAN_TOLERANCE_MM3
                and tread_common <= BOOLEAN_TOLERANCE_MM3
                and len(top.shape.Solids()) == 1
                and len(tread.shape.Solids()) == 1,
                evidence_kind="brep_boolean_through_channel",
                requirement=(
                    "Each invariant A08 drain station must remain an empty channel through both PC-ABS top skin and TPE tread in every pose."
                ),
                station_offset_x_mm=station,
                released_channel_section_xy_mm=(12.0, 96.0),
                conservative_witness_section_xy_mm=(11.6, 95.6),
                channel_z_mm=[round(witness.BoundingBox().zmin, 3), round(witness.BoundingBox().zmax, 3)],
                top_common_volume_mm3=round(top_common, 9),
                tread_common_volume_mm3=round(tread_common, 9),
            )


def _gate_a09_three_stages(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    state_sides = {"cafe": ("right",), "focus": ("left", "right")}
    for state, sides in state_sides.items():
        for side_name in sides:
            stage_1_name = (
                "A09_table_lift_boot_right"
                if state == "cafe"
                else f"A09_table_lift_boot_{side_name}"
            )
            names = (
                stage_1_name,
                f"A09_table_lift_moving_stage_2_{side_name}",
                f"A09_table_lift_moving_stage_3_{side_name}",
            )
            stages = [_part(states[state], name) for name in names]
            descriptions, interfaces = _stage_evidence(stages)
            ids = [part.metadata.get("physical_occurrence_id") for part in stages]
            indices = [part.metadata.get("stage_index") for part in stages]
            common_volumes = [
                value
                for key, value in interfaces.items()
                if key.endswith(".common_volume_mm3")
            ]
            adjacent_distances = (
                float(stages[0].shape.distance(stages[1].shape)),
                float(stages[1].shape.distance(stages[2].shape)),
            )
            expected_shapes = [
                _a09_expected_instrument_spine_stage(
                    state,
                    side_name,
                    stage_index,
                )
                for stage_index in (1, 2, 3)
            ]
            profile_brep_evidence = [
                _brep_pose_evidence(expected, stage.shape)
                for expected, stage in zip(expected_shapes, stages)
            ]
            metadata_contract = []
            for stage_index, stage in enumerate(stages, start=1):
                profile = A09_LIFT_STAGE_PROFILE_CONTRACT[stage_index]
                expected_axis = (
                    -430.0 if state == "cafe" else -405.0,
                    -300.0 if side_name == "left" else 300.0,
                )
                expected_channel = (
                    A09_LIFT_STAGE3_MINIMUM_INTERNAL_CHANNEL_MM
                    if stage_index == 3
                    else min(_float_tuple(profile["inner_xy_mm"]))
                )
                metadata_contract.append(
                    stage.metadata.get("a09_lift_column_contract")
                    == "directional_squircle_instrument_spine_v1"
                    and _float_tuple(stage.metadata.get("outer_xy_mm"))
                    == _float_tuple(profile["outer_xy_mm"])
                    and _float_tuple(stage.metadata.get("inner_xy_mm"))
                    == _float_tuple(profile["inner_xy_mm"])
                    and abs(
                        float(
                            stage.metadata.get(
                                "outer_plan_radius_mm",
                                -1.0,
                            )
                        )
                        - float(profile["outer_plan_radius_mm"])
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and abs(
                        float(
                            stage.metadata.get(
                                "inner_plan_radius_mm",
                                -1.0,
                            )
                        )
                        - float(profile["inner_plan_radius_mm"])
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and abs(
                        float(stage.metadata.get("minimum_wall_mm", -1.0))
                        - float(profile["minimum_wall_mm"])
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and abs(
                        float(
                            stage.metadata.get(
                                "adjacent_radial_clearance_mm",
                                -1.0,
                            )
                        )
                        - A09_LIFT_ADJACENT_RADIAL_CLEARANCE_MM
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and abs(
                        float(
                            stage.metadata.get(
                                "minimum_internal_channel_mm",
                                -1.0,
                            )
                        )
                        - expected_channel
                    )
                    <= DISTANCE_TOLERANCE_MM
                    and _float_tuple(
                        stage.metadata.get("controlled_axis_xy_mm")
                    )
                    == expected_axis
                    and _float_tuple(
                        stage.metadata.get("released_z_bounds_mm")
                    )
                    == A09_LIFT_STAGE_Z_HARDPOINTS_MM[stage_index]
                    and float(stage.metadata.get("plan_yaw_deg", -1.0))
                    == 0.0
                    and stage.metadata.get("straight_axial_walls") is True
                    and stage.metadata.get("xy_only_squircle_rounding") is True
                    and stage.metadata.get(
                        "released_axis_and_z_bounds_preserved"
                    )
                    is True
                )
            book.add(
                f"a09.{state}.{side_name}.three_independent_table_lift_stages",
                indices == [1, 2, 3]
                and all(part.metadata.get("independent_physical_stage") is True for part in stages)
                and all(ids)
                and len(ids) == len(set(ids))
                and all(len(part.shape.Solids()) == 1 for part in stages)
                and all(value <= BOOLEAN_TOLERANCE_MM3 for value in common_volumes)
                and all(value >= 3.0 - DISTANCE_TOLERANCE_MM for value in adjacent_distances),
                evidence_kind="brep_pairwise_intersection_clearance_and_occurrence_identity",
                requirement="Each deployed A09 table lift must be three separate nested solids with a real radial gap.",
                stages=descriptions,
                pairwise_interfaces=interfaces,
                minimum_adjacent_clearance_mm=3.0,
            )
            book.add(
                f"a09.{state}.{side_name}.instrument_spine_squircle_contract",
                all(_brep_pose_matches(item) for item in profile_brep_evidence)
                and all(metadata_contract)
                and all(
                    abs(
                        value - A09_LIFT_ADJACENT_RADIAL_CLEARANCE_MM
                    )
                    <= DISTANCE_TOLERANCE_MM
                    for value in adjacent_distances
                ),
                evidence_kind=(
                    "exact_brep_profile_metadata_axis_z_hardpoint_and_clearance"
                ),
                requirement=(
                    "Each deployed A09 lift stage must be the frozen straight-"
                    "walled directional squircle sleeve: 72x70/60x58/48x46 mm "
                    "outer, the released inner profiles/radii, zero yaw, exact "
                    "axes and Z hardpoints, 3.0 mm adjacent dry gaps and a "
                    "40 mm stage-3 mechanism channel."
                ),
                profile_contract=A09_LIFT_STAGE_PROFILE_CONTRACT,
                z_hardpoints_mm=A09_LIFT_STAGE_Z_HARDPOINTS_MM,
                adjacent_clearance_mm=[
                    round(value, 9) for value in adjacent_distances
                ],
                profile_brep_evidence=profile_brep_evidence,
                metadata_contract_pass=metadata_contract,
            )


def _gate_a09_cafe_root_motion(
    cafe_parts: Sequence[SkinPart],
    book: _GateBook,
) -> None:
    """Prove the Cafe fixed/rotary/linear split using production B-Reps."""

    def _near_common(first: cq.Shape, second: cq.Shape) -> float:
        """Avoid an exact Boolean when two bodies already have a dry gap."""

        if float(first.distance(second)) > 1.0e-6:
            return 0.0
        return _intersection_volume(first, second)

    reference_final = (
        *cafe_root_final_occurrences(),
        *cafe_table_control_final_occurrences(),
    )
    reference_names = tuple(item.name for item in reference_final)
    production = {part.name: part for part in cafe_parts}
    missing = [name for name in reference_names if name not in production]
    identity_evidence: dict[str, Any] = {}
    physical_ids: list[object] = []
    if not missing:
        for reference in reference_final:
            actual = production[reference.name]
            evidence = _brep_pose_evidence(reference.shape, actual.shape)
            evidence["expected_physical_occurrence_id"] = (
                reference.physical_occurrence_id
            )
            evidence["actual_physical_occurrence_id"] = actual.metadata.get(
                "physical_occurrence_id"
            )
            evidence["physical_occurrence_id_equal"] = (
                evidence["actual_physical_occurrence_id"]
                == evidence["expected_physical_occurrence_id"]
            )
            identity_evidence[reference.name] = evidence
            physical_ids.append(evidence["actual_physical_occurrence_id"])
    production_identity_pass = (
        not missing
        and len(physical_ids) == len(set(physical_ids))
        and all(
            _brep_pose_matches(evidence)
            and evidence["physical_occurrence_id_equal"]
            for evidence in identity_evidence.values()
        )
    )
    book.add(
        "a09.cafe.right.root_motion_inventory_and_production_identity",
        production_identity_pass,
        evidence_kind="production_brep_identity_and_physical_occurrence_inventory",
        requirement=(
            "Cafe must contain the same fourteen fixed, rotary, telescopic and "
            "table-carriage occurrences plus the same two leaf-mounted manual "
            "controls proven by the motion model; a state-only cosmetic proxy "
            "may not replace or rename them."
        ),
        expected_occurrences=list(reference_names),
        missing_occurrences=missing,
        unique_physical_occurrence_ids=len(physical_ids) == len(set(physical_ids)),
        identity_evidence=identity_evidence,
    )

    root_poses = cafe_root_motion_poses(21)
    poses: list[tuple[Any, ...]] = []
    for frame, root_pose in enumerate(root_poses):
        if frame <= 20:
            rotation = frame / 20.0
            returned = 0.0
        else:
            rotation = 1.0
            returned = (frame - 20) / 20.0
        poses.append(
            (*root_pose, *cafe_table_control_pose(rotation, returned))
        )
    reference_pose_names = tuple(item.name for item in poses[0])
    reference_pose_ids = tuple(item.physical_occurrence_id for item in poses[0])
    reference_volumes = {
        item.physical_occurrence_id: float(item.shape.Volume())
        for item in poses[0]
    }
    inventory_pass = True
    maximum_hard_common = 0.0
    maximum_hard_pair: tuple[int, str, str] | None = None
    minimum_fixed_moving_gap = float("inf")
    maximum_leaf_common = 0.0
    minimum_carriage_leaf_gap = float("inf")
    maximum_mount_contact_gap = 0.0
    maximum_control_leaf_contact_gap = 0.0
    minimum_control_carriage_gap = float("inf")
    for frame, pose in enumerate(poses):
        inventory_pass = inventory_pass and (
            tuple(item.name for item in pose) == reference_pose_names
            and tuple(item.physical_occurrence_id for item in pose)
            == reference_pose_ids
            and all(
                abs(
                    float(item.shape.Volume())
                    - reference_volumes[item.physical_occurrence_id]
                )
                <= 1.0e-5
                for item in pose
            )
        )
        by_name = {item.name: item for item in pose}
        for index, first in enumerate(pose):
            for second in pose[:index]:
                if float(first.shape.distance(second.shape)) > 1.0e-6:
                    continue
                common = _intersection_volume(first.shape, second.shape)
                if common > maximum_hard_common:
                    maximum_hard_common = common
                    maximum_hard_pair = (frame, first.name, second.name)

        fixed = by_name["A09_cafe_fixed_root_housing_right"].shape
        carriage = by_name["A09_cafe_underleaf_motion_belly_right"].shape
        minimum_fixed_moving_gap = min(
            minimum_fixed_moving_gap,
            float(fixed.distance(carriage)),
        )
        if frame <= 20:
            rotation = frame / 20.0
            returned = 0.0
        else:
            rotation = 1.0
            returned = (frame - 20) / 20.0
        inner_leaf, outer_leaf = cafe_half_leaf_pair(rotation, returned)
        for item in pose:
            for leaf in (inner_leaf, outer_leaf):
                maximum_leaf_common = max(
                    maximum_leaf_common,
                    _near_common(item.shape, leaf.shape),
                )
        minimum_carriage_leaf_gap = min(
            minimum_carriage_leaf_gap,
            float(carriage.distance(outer_leaf.shape)),
        )
        for station in (1, 2, 3):
            shoe = by_name[
                f"A09_cafe_table_mount_shoe_right_{station}"
            ].shape
            maximum_mount_contact_gap = max(
                maximum_mount_contact_gap,
                float(shoe.distance(outer_leaf.shape)),
                float(shoe.distance(carriage)),
            )
        for control_name in (
            "A09_cafe_lock_release_paddle_right",
            "A09_cafe_positive_lock_witness_right",
        ):
            control = by_name[control_name].shape
            maximum_control_leaf_contact_gap = max(
                maximum_control_leaf_contact_gap,
                float(control.distance(outer_leaf.shape)),
            )
            minimum_control_carriage_gap = min(
                minimum_control_carriage_gap,
                float(control.distance(carriage)),
            )

    motion_pass = (
        inventory_pass
        and maximum_hard_common <= BOOLEAN_TOLERANCE_MM3
        and maximum_leaf_common <= BOOLEAN_TOLERANCE_MM3
        and minimum_fixed_moving_gap >= 1.99
        and minimum_carriage_leaf_gap >= 0.99
        and maximum_mount_contact_gap <= DISTANCE_TOLERANCE_MM
        and maximum_control_leaf_contact_gap <= DISTANCE_TOLERANCE_MM
        and minimum_control_carriage_gap >= 1.99
    )
    book.add(
        "a09.cafe.right.rotate_then_return_full_motion",
        motion_pass,
        evidence_kind="forty_one_pose_brep_inventory_collision_and_table_contact",
        requirement=(
            "The fixed yoke housing must remain fixed while the hub/rail rotate "
            "90 degrees and only the table carriage returns 80 mm; every rigid "
            "occurrence must remain collision-free and the three mount shoes "
            "must retain real contact with the same outer half-leaf."
        ),
        sampled_pose_count=len(poses),
        rotation_samples=21,
        return_samples=21,
        duplicated_corner_pose=False,
        inventory_conserved=inventory_pass,
        maximum_pairwise_hard_common_mm3=round(maximum_hard_common, 9),
        maximum_pairwise_hard_common_pair=maximum_hard_pair,
        maximum_table_leaf_hard_common_mm3=round(maximum_leaf_common, 9),
        minimum_fixed_to_moving_cosmetic_gap_mm=round(
            minimum_fixed_moving_gap,
            6,
        ),
        minimum_carriage_to_outer_leaf_gap_mm=round(
            minimum_carriage_leaf_gap,
            6,
        ),
        maximum_mount_contact_gap_mm=round(maximum_mount_contact_gap, 9),
        maximum_control_to_outer_leaf_contact_gap_mm=round(
            maximum_control_leaf_contact_gap,
            9,
        ),
        minimum_control_to_carriage_dry_gap_mm=round(
            minimum_control_carriage_gap,
            6,
        ),
    )

    initial = {item.name: item for item in cafe_root_motion_pose(1.0, 0.0)}
    pickup = {item.name: item for item in cafe_root_motion_pose(1.0, 0.5)}
    final = {item.name: item for item in reference_final}
    rail_box = final["A09_cafe_rotary_linear_rail_right"].shape.BoundingBox()
    carriage_box = final[
        "A09_cafe_underleaf_motion_belly_right"
    ].shape.BoundingBox()
    rail_capture = min(rail_box.xmax, carriage_box.xmax) - max(
        rail_box.xmin,
        carriage_box.xmin,
    )
    cover_travel = {
        stage: (
            final[f"A09_cafe_telescopic_rail_cover_right_{stage}"].shape.Center().x
            - initial[
                f"A09_cafe_telescopic_rail_cover_right_{stage}"
            ].shape.Center().x
        )
        for stage in (1, 2, 3)
    }
    pickup_stationary = all(
        abs(
            pickup[f"A09_cafe_telescopic_rail_cover_right_{stage}"].shape.Center().x
            - initial[
                f"A09_cafe_telescopic_rail_cover_right_{stage}"
            ].shape.Center().x
        )
        <= DISTANCE_TOLERANCE_MM
        for stage in (1, 2, 3)
    )
    final_outer_leaf = cafe_half_leaf_pair(1.0, 1.0)[1].shape
    fold_retreat = (
        float(final_outer_leaf.BoundingBox().xmax) - carriage_box.xmax
    )
    contact_gaps: dict[str, float] = {
        "hub_to_rail": float(
            final["A09_cafe_rotary_hub_right"].shape.distance(
                final["A09_cafe_rotary_linear_rail_right"].shape
            )
        ),
        "rail_to_cover_1": float(
            final["A09_cafe_rotary_linear_rail_right"].shape.distance(
                final["A09_cafe_telescopic_rail_cover_right_1"].shape
            )
        ),
        "cover_1_to_2": float(
            final["A09_cafe_telescopic_rail_cover_right_1"].shape.distance(
                final["A09_cafe_telescopic_rail_cover_right_2"].shape
            )
        ),
        "cover_2_to_3": float(
            final["A09_cafe_telescopic_rail_cover_right_2"].shape.distance(
                final["A09_cafe_telescopic_rail_cover_right_3"].shape
            )
        ),
    }
    for station in ("left", "right", "top"):
        guide = final[f"A09_cafe_linear_guide_shoe_right_{station}"].shape
        contact_gaps[f"guide_{station}_to_cover_3"] = float(
            guide.distance(
                final["A09_cafe_telescopic_rail_cover_right_3"].shape
            )
        )
        contact_gaps[f"guide_{station}_to_carriage"] = float(
            guide.distance(
                final["A09_cafe_underleaf_motion_belly_right"].shape
            )
        )
    load_path_pass = (
        rail_capture >= CAFE_FINAL_RAIL_CAPTURE_MM - 0.1
        and pickup_stationary
        and abs(cover_travel[1]) <= DISTANCE_TOLERANCE_MM
        and abs(cover_travel[2] - 20.0) <= DISTANCE_TOLERANCE_MM
        and abs(cover_travel[3] - 40.0) <= DISTANCE_TOLERANCE_MM
        and fold_retreat
        >= CAFE_INTERNAL_FOLD_HARD_RETREAT_MM - DISTANCE_TOLERANCE_MM
        and all(value <= DISTANCE_TOLERANCE_MM for value in contact_gaps.values())
    )
    book.add(
        "a09.cafe.right.load_path_capture_and_telescopic_cover",
        load_path_pass,
        evidence_kind="brep_contact_chain_capture_and_piecewise_linear_pickup",
        requirement=(
            "The load path must remain hub-to-rail-to-three nested covers-to-"
            "guide-shoes-to-carriage, retain at least 50 mm final rail capture, "
            "keep all covers nested for the first 40 mm and stop the hard "
            "carriage at least 3 mm before the internal fold."
        ),
        final_rail_capture_mm=round(rail_capture, 6),
        minimum_final_rail_capture_mm=CAFE_FINAL_RAIL_CAPTURE_MM,
        pickup_dead_travel_mm=CAFE_COVER_PICKUP_DEAD_TRAVEL_MM,
        pickup_stationary_through_dead_travel=pickup_stationary,
        final_cover_travel_mm={key: round(value, 6) for key, value in cover_travel.items()},
        final_fold_hard_retreat_mm=round(fold_retreat, 6),
        minimum_fold_hard_retreat_mm=CAFE_INTERNAL_FOLD_HARD_RETREAT_MM,
        contact_gaps_mm={key: round(value, 9) for key, value in contact_gaps.items()},
    )

    # Keep the pre-existing lift-column, base-socket and A05 dry-interface
    # evidence, but test it against the split root instead of a fake monocoque.
    stages = [
        _part(cafe_parts, "A09_table_lift_boot_right"),
        _part(cafe_parts, "A09_table_lift_moving_stage_2_right"),
        _part(cafe_parts, "A09_table_lift_moving_stage_3_right"),
    ]
    socket = _part(cafe_parts, "A09_cafe_table_lift_base_socket_right")
    armrest = _part(cafe_parts, "A05_armrest_table_bay_shell_right")
    lid = _part(cafe_parts, "A05_armrest_touch_lid_right")
    table_underbelly = _part(cafe_parts, "A09_table_underbelly_shell_right")
    paddle = _part(cafe_parts, "A09_cafe_lock_release_paddle_right")
    witness = _part(cafe_parts, "A09_cafe_positive_lock_witness_right")
    production_root_parts = [production[name] for name in reference_names] if not missing else []
    root_static_obstacles = [armrest, lid, *stages]
    root_static_common = {
        f"{root.name}->{obstacle.name}": _near_common(
            root.shape,
            obstacle.shape,
        )
        for root in production_root_parts
        for obstacle in root_static_obstacles
    }
    socket_stage_common = _near_common(socket.shape, stages[0].shape)
    socket_stage_gap = float(socket.shape.distance(stages[0].shape))
    socket_armrest_common = _near_common(socket.shape, armrest.shape)
    socket_armrest_gap = float(socket.shape.distance(armrest.shape))
    stage_a05_common = [
        _near_common(stage.shape, a05.shape)
        for stage in stages
        for a05 in (armrest, lid)
    ]
    stage_a05_gap = [
        float(stage.shape.distance(a05.shape))
        for stage in stages
        for a05 in (armrest, lid)
    ]
    stage3_underbelly_common = _near_common(
        stages[2].shape,
        table_underbelly.shape,
    )
    carriage = production.get("A09_cafe_underleaf_motion_belly_right")
    control_common = (
        {
            "release_paddle": _near_common(carriage.shape, paddle.shape),
            "positive_lock_witness": _near_common(
                carriage.shape,
                witness.shape,
            ),
        }
        if carriage is not None
        else {"release_paddle": float("inf"), "positive_lock_witness": float("inf")}
    )
    control_gap = (
        {
            "release_paddle": float(carriage.shape.distance(paddle.shape)),
            "positive_lock_witness": float(carriage.shape.distance(witness.shape)),
        }
        if carriage is not None
        else {"release_paddle": 0.0, "positive_lock_witness": 0.0}
    )
    static_interface_pass = (
        not missing
        and all(value <= BOOLEAN_TOLERANCE_MM3 for value in root_static_common.values())
        and socket_stage_common <= BOOLEAN_TOLERANCE_MM3
        and socket_stage_gap
        >= A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM - DISTANCE_TOLERANCE_MM
        and socket_armrest_common <= BOOLEAN_TOLERANCE_MM3
        and socket_armrest_gap >= 1.9
        and all(value <= BOOLEAN_TOLERANCE_MM3 for value in stage_a05_common)
        and min(stage_a05_gap)
        >= A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM - DISTANCE_TOLERANCE_MM
        and stage3_underbelly_common <= BOOLEAN_TOLERANCE_MM3
        and all(value <= BOOLEAN_TOLERANCE_MM3 for value in control_common.values())
        and min(control_gap.values()) >= 1.99
        and socket.metadata.get("closed_bottom") is True
        and socket.metadata.get(
            "normal_bottom_sightline_stage_aperture_closed"
        )
        is True
    )
    book.add(
        "a09.cafe.right.fixed_root_socket_and_service_interfaces",
        static_interface_pass,
        evidence_kind="production_brep_static_interface_matrix",
        requirement=(
            "The split Cafe root must clear A05, all three lift sleeves, the "
            "closed base socket and manual lock interfaces while keeping the "
            "stage-3/table underside and socket boundaries dry."
        ),
        root_static_common_mm3={
            key: round(value, 9) for key, value in root_static_common.items()
        },
        socket_stage_common_mm3=round(socket_stage_common, 9),
        socket_stage_gap_mm=round(socket_stage_gap, 6),
        socket_armrest_common_mm3=round(socket_armrest_common, 9),
        socket_armrest_gap_mm=round(socket_armrest_gap, 6),
        stage_a05_common_mm3=[round(value, 9) for value in stage_a05_common],
        stage_a05_gap_mm=[round(value, 6) for value in stage_a05_gap],
        stage3_table_underbelly_common_mm3=round(stage3_underbelly_common, 9),
        manual_control_common_mm3={
            key: round(value, 9) for key, value in control_common.items()
        },
        manual_control_to_carriage_dry_gap_mm={
            key: round(value, 6) for key, value in control_gap.items()
        },
    )


def _gate_a09_production_enclosures(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    enclosure_tokens = (
        "underleaf_motion_belly",
        "table_lift_base_socket",
        "table_root_crown",
    )
    for state in ("follow", "ride"):
        forbidden = sorted(
            part.name
            for part in states[state]
            if any(token in part.name for token in enclosure_tokens)
        )
        book.add(
            f"a09.{state}.deployed_table_enclosures_absent",
            not forbidden,
            evidence_kind="state_inventory_deployed_table_contract",
            requirement=(
                "Follow and Ride keep both tables fully stowed and may not show deployed underleaf bellies, lift sockets or root crowns."
            ),
            forbidden_occurrences=forbidden,
        )

    state_sides = {"cafe": ("right",), "focus": ("left", "right")}
    fragmented_root_prefixes = {
        "cafe": (
            "A09_cafe_armrest_to_table_root_bridge_right",
            "A09_cafe_root_mechanism_fairing_right",
            "A09_cafe_underleaf_saddle_right",
            "A09_cafe_underleaf_motion_belly_service_",
        ),
        "focus": (
            "A09_focus_armrest_to_table_root_bridge_",
            "A09_focus_root_fairing_",
            "A09_focus_underleaf_saddle_",
        ),
    }
    for state, prefixes in fragmented_root_prefixes.items():
        forbidden = sorted(
            part.name
            for part in states[state]
            if part.name.startswith(prefixes)
        )
        book.add(
            f"a09.{state}.fragmented_root_cosmetics_retired",
            not forbidden,
            evidence_kind="production_occurrence_inventory",
            requirement=(
                "Each deployed table root must retire the former bridge, "
                "fairing, saddle and numerical service fragments. Cafe uses "
                "the proven fixed/rotary/linear split; Focus retains one "
                "root-side monocoque per active leaf."
            ),
            forbidden_fragment_occurrences=forbidden,
        )
    for state, sides in state_sides.items():
        for side_name in sides:
            if state == "cafe":
                _gate_a09_cafe_root_motion(states[state], book)
                continue
            side = -1.0 if side_name == "left" else 1.0
            axis_x = -430.0 if state == "cafe" else -405.0
            belly_name = (
                "A09_cafe_underleaf_motion_belly_right"
                if state == "cafe"
                else f"A09_focus_underleaf_motion_belly_{side_name}"
            )
            stage_1_name = (
                "A09_table_lift_boot_right"
                if state == "cafe"
                else f"A09_table_lift_boot_{side_name}"
            )
            belly = _part(states[state], belly_name)
            stages = [
                _part(states[state], stage_1_name),
                _part(
                    states[state],
                    f"A09_table_lift_moving_stage_2_{side_name}",
                ),
                _part(
                    states[state],
                    f"A09_table_lift_moving_stage_3_{side_name}",
                ),
            ]
            socket = _part(
                states[state],
                f"A09_{state}_table_lift_base_socket_{side_name}",
            )
            fixed_armrest = _part(
                states[state],
                f"A05_armrest_table_bay_shell_{side_name}",
            )
            touch_lid = _part(
                states[state],
                f"A05_armrest_touch_lid_{side_name}",
            )
            focus_a05_obstacles = [touch_lid]
            if state == "focus" and side_name == "left":
                focus_a05_obstacles.append(
                    _part(states[state], "A05_left_hmi_precision_bezel")
                )
            focus_a05_boundary_common = [
                _intersection_volume(belly.shape, obstacle.shape)
                for obstacle in focus_a05_obstacles
            ]
            focus_a05_boundary_distance = [
                float(belly.shape.distance(obstacle.shape))
                for obstacle in focus_a05_obstacles
            ]
            focus_a05_boundary_pass = state != "focus" or (
                all(
                    value <= BOOLEAN_TOLERANCE_MM3
                    for value in focus_a05_boundary_common
                )
                and min(focus_a05_boundary_distance) >= 3.0
            )
            table_underbelly = _part(
                states[state],
                f"A09_table_underbelly_shell_{side_name}",
            )
            belly_armrest_common = _intersection_volume(
                belly.shape,
                fixed_armrest.shape,
            )
            belly_armrest_distance = float(
                belly.shape.distance(fixed_armrest.shape)
            )
            belly_underbelly_common = _intersection_volume(
                belly.shape,
                table_underbelly.shape,
            )
            belly_underbelly_distance = float(
                belly.shape.distance(table_underbelly.shape)
            )
            socket_common = _intersection_volume(
                socket.shape,
                stages[0].shape,
            )
            socket_distance = float(
                socket.shape.distance(stages[0].shape)
            )
            socket_armrest_common = _intersection_volume(
                socket.shape,
                fixed_armrest.shape,
            )
            socket_armrest_distance = float(
                socket.shape.distance(fixed_armrest.shape)
            )
            stage_a05_common = [
                _intersection_volume(stage.shape, a05_part.shape)
                for stage in stages
                for a05_part in (fixed_armrest, touch_lid)
            ]
            stage_a05_distance = [
                float(stage.shape.distance(a05_part.shape))
                for stage in stages
                for a05_part in (fixed_armrest, touch_lid)
            ]
            stage3_underbelly_common = _intersection_volume(
                stages[2].shape,
                table_underbelly.shape,
            )
            socket_bottom_probe = rounded_box(
                (1.0, 1.0, 1.0),
                (axis_x, side * 300.0, 486.5),
                0.1,
            )
            socket_bottom_common = _intersection_volume(
                socket.shape,
                socket_bottom_probe,
            )
            stage_aperture_probe = rounded_box(
                (70.0, 70.0, 42.0),
                (axis_x, side * 300.0, 670.0),
                10.0,
            )
            aperture_common = _intersection_volume(
                belly.shape,
                stage_aperture_probe,
            )
            belly_stage_common = [
                _intersection_volume(belly.shape, stage.shape)
                for stage in stages
            ]
            belly_stage_distance = [
                float(belly.shape.distance(stage.shape)) for stage in stages
            ]
            underside_probe = rounded_box(
                (1.0, 1.0, 1.0),
                (
                    -485.0 if state == "cafe" else -465.0,
                    side * (230.0 if state == "cafe" else 220.0),
                    646.5,
                ),
                0.1,
            )
            underside_common = _intersection_volume(
                belly.shape,
                underside_probe,
            )
            belly_box = _Box.from_shape(belly.shape)
            base_passed = (
                len(belly.shape.Solids()) == 1
                and len(socket.shape.Solids()) == 1
                and belly.metadata.get("closed_normal_underside") is True
                and belly.metadata.get("service_sliver_count") == 0
                and belly_armrest_common <= BOOLEAN_TOLERANCE_MM3
                and belly_armrest_distance >= 1.0 - DISTANCE_TOLERANCE_MM
                and belly_underbelly_common <= BOOLEAN_TOLERANCE_MM3
                and belly_underbelly_distance >= 0.9 - DISTANCE_TOLERANCE_MM
                and underside_common >= 0.90
                and aperture_common <= BOOLEAN_TOLERANCE_MM3
                and all(
                    value <= BOOLEAN_TOLERANCE_MM3
                    for value in belly_stage_common
                )
                and all(value >= 6.0 for value in belly_stage_distance)
                and socket.metadata.get("closed_bottom") is True
                and socket.metadata.get(
                    "normal_bottom_sightline_stage_aperture_closed"
                )
                is True
                and socket_bottom_common >= 0.90
                and socket_common <= BOOLEAN_TOLERANCE_MM3
                and socket_distance
                >= A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM
                - DISTANCE_TOLERANCE_MM
                and float(
                    socket.metadata.get(
                        "minimum_static_brep_clearance_to_stage_1_mm",
                        0.0,
                    )
                )
                >= A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM
                - DISTANCE_TOLERANCE_MM
                and abs(
                    float(
                        socket.metadata.get(
                            "minimum_static_brep_clearance_to_stage_1_mm",
                            -1.0,
                        )
                    )
                    - socket_distance
                )
                <= DISTANCE_TOLERANCE_MM
                and abs(
                    float(
                        socket.metadata.get(
                            "minimum_static_brep_clearance_contract_mm",
                            -1.0,
                        )
                    )
                    - A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM
                )
                <= DISTANCE_TOLERANCE_MM
                and socket_armrest_common <= BOOLEAN_TOLERANCE_MM3
                and socket_armrest_distance >= 1.9
                and socket.metadata.get(
                    "fixed_armrest_completes_rear_outboard_perimeter"
                )
                is True
                and float(
                    socket.metadata.get(
                        "dry_gap_to_fixed_armrest_mm",
                        0.0,
                    )
                )
                >= 1.9
                and all(
                    value <= BOOLEAN_TOLERANCE_MM3
                    for value in stage_a05_common
                )
                and min(stage_a05_distance)
                >= A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM
                - DISTANCE_TOLERANCE_MM
                and stage3_underbelly_common <= BOOLEAN_TOLERANCE_MM3
                and focus_a05_boundary_pass
            )

            extra_evidence: dict[str, Any] = (
                {
                    "focus_moving_belly_to_final_lid_and_hmi": {
                        "obstacles": [
                            obstacle.name for obstacle in focus_a05_obstacles
                        ],
                        "common_volume_mm3": [
                            round(value, 9)
                            for value in focus_a05_boundary_common
                        ],
                        "minimum_distance_mm": [
                            round(value, 6)
                            for value in focus_a05_boundary_distance
                        ],
                        "required_minimum_distance_mm": 3.0,
                        "status": (
                            "PASS" if focus_a05_boundary_pass else "FAIL"
                        ),
                    }
                }
                if state == "focus"
                else {}
            )
            if state == "focus":
                crown = _part(
                    states[state],
                    f"A09_focus_table_root_crown_{side_name}",
                )
                crown_top_probe = rounded_box(
                    (1.0, 1.0, 1.0),
                    (-405.0, side * 308.4, 703.0),
                    0.1,
                )
                crown_top_common = _intersection_volume(
                    crown.shape,
                    crown_top_probe,
                )
                crown_stage_common = _intersection_volume(
                    crown.shape,
                    stages[2].shape,
                )
                crown_stage_distance = float(
                    crown.shape.distance(stages[2].shape)
                )
                edge = _part(
                    states[state],
                    f"A09_table_edge_band_{side_name}",
                )
                crown_edge_common = _intersection_volume(
                    crown.shape,
                    edge.shape,
                )
                crown_edge_distance = float(crown.shape.distance(edge.shape))
                paddles = [
                    _part(
                        states[state],
                        f"A09_focus_lock_release_paddle_{side_name}_{station}",
                    )
                    for station in (1, 2)
                ]
                bezels = [
                    _part(
                        states[state],
                        f"A09_focus_lock_paddle_bezel_{side_name}_{station}",
                    )
                    for station in (1, 2)
                ]
                seam_seal = _part(
                    states[state],
                    f"A09_focus_centre_seam_seal_{side_name}",
                )
                lock_parts = [*bezels, *paddles]
                lock_seal_interfaces = {
                    part.name: {
                        "common_volume_mm3": round(
                            _intersection_volume(
                                part.shape,
                                seam_seal.shape,
                            ),
                            9,
                        ),
                        "minimum_distance_mm": round(
                            float(part.shape.distance(seam_seal.shape)),
                            6,
                        ),
                        "declared_center_abs_y_mm": part.metadata.get(
                            "inner_edge_lock_center_abs_y_mm"
                        ),
                        "declared_minimum_dry_clearance_mm": (
                            part.metadata.get(
                                "minimum_dry_clearance_to_centre_seal_mm"
                            )
                        ),
                    }
                    for part in lock_parts
                }
                lock_seal_clearance_pass = all(
                    interface["common_volume_mm3"]
                    <= BOOLEAN_TOLERANCE_MM3
                    and interface["minimum_distance_mm"]
                    >= 0.5 - DISTANCE_TOLERANCE_MM
                    and interface["declared_center_abs_y_mm"] == 10.0
                    and interface["declared_minimum_dry_clearance_mm"]
                    == 0.6
                    for interface in lock_seal_interfaces.values()
                )
                paddle_boxes = [_Box.from_shape(part.shape) for part in paddles]
                seam_local = all(
                    (box.ymax <= -6.1 if side < 0 else box.ymin >= 6.1)
                    for box in paddle_boxes
                )
                focus_passed = (
                    len(crown.shape.Solids()) == 1
                    and crown.metadata.get(
                        "normal_and_top_sightline_stage_aperture_closed"
                    )
                    is True
                    and crown.metadata.get("does_not_bridge_center_seam") is True
                    and crown_top_common >= 0.90
                    and crown_stage_common <= BOOLEAN_TOLERANCE_MM3
                    and crown_stage_distance >= 1.2
                    and crown_edge_common <= BOOLEAN_TOLERANCE_MM3
                    and crown_edge_distance >= 0.70
                    and seam_local
                    and lock_seal_clearance_pass
                    and all(
                        part.metadata.get("external_hinge_language_present")
                        is False
                        and part.metadata.get("does_not_bridge_center_seam")
                        is True
                        for part in paddles
                    )
                    and (
                        belly_box.ymax <= -124.9
                        if side < 0
                        else belly_box.ymin >= 124.9
                    )
                )
                base_passed = base_passed and focus_passed
                extra_evidence.update({
                    "root_crown": crown.name,
                    "root_crown_top_probe_common_mm3": round(
                        crown_top_common,
                        9,
                    ),
                    "root_crown_stage_common_mm3": round(
                        crown_stage_common,
                        9,
                    ),
                    "root_crown_stage_clearance_mm": round(
                        crown_stage_distance,
                        6,
                    ),
                    "root_crown_table_edge_common_mm3": round(
                        crown_edge_common,
                        9,
                    ),
                    "root_crown_table_edge_dry_gap_mm": round(
                        crown_edge_distance,
                        6,
                    ),
                    "centre_lock_paddle_bounds": [
                        box.to_dict() for box in paddle_boxes
                    ],
                    "centre_seam_seal": seam_seal.name,
                    "lock_to_centre_seal_interfaces": (
                        lock_seal_interfaces
                    ),
                    "lock_to_centre_seal_minimum_required_clearance_mm": 0.5,
                    "lock_to_centre_seal_clearance_pass": (
                        lock_seal_clearance_pass
                    ),
                })
            else:
                paddle = _part(
                    states[state],
                    "A09_cafe_lock_release_paddle_right",
                )
                witness = _part(
                    states[state],
                    "A09_cafe_positive_lock_witness_right",
                )
                paddle_common = _intersection_volume(
                    belly.shape,
                    paddle.shape,
                )
                paddle_distance = float(belly.shape.distance(paddle.shape))
                witness_common = _intersection_volume(
                    belly.shape,
                    witness.shape,
                )
                base_passed = (
                    base_passed
                    and paddle_common <= BOOLEAN_TOLERANCE_MM3
                    and paddle_distance >= 0.9 - DISTANCE_TOLERANCE_MM
                    and witness_common <= BOOLEAN_TOLERANCE_MM3
                )
                extra_evidence = {
                    "manual_release_common_mm3": round(paddle_common, 9),
                    "manual_release_dry_gap_mm": round(paddle_distance, 6),
                    "positive_lock_witness_common_mm3": round(
                        witness_common,
                        9,
                    ),
                }

            book.add(
                f"a09.{state}.{side_name}.table_root_is_closed_but_serviceable",
                base_passed,
                evidence_kind="brep_underleaf_wall_aperture_caps_and_service_access",
                requirement=(
                    "Each deployed table root must have a real closed underside and closed sleeve ends, retain an empty lift aperture and dry sleeve clearances, preserve Cafe manual lock access, and never bridge the Focus centre/knee seam."
                ),
                underleaf_belly=belly.name,
                underleaf_belly_bounds=belly_box.to_dict(),
                belly_fixed_armrest_common_mm3=round(
                    belly_armrest_common,
                    9,
                ),
                belly_fixed_armrest_dry_gap_mm=round(
                    belly_armrest_distance,
                    6,
                ),
                belly_table_underbelly_common_mm3=round(
                    belly_underbelly_common,
                    9,
                ),
                belly_table_underbelly_dry_gap_mm=round(
                    belly_underbelly_distance,
                    6,
                ),
                lift_base_socket=socket.name,
                socket_bottom_probe_common_mm3=round(
                    socket_bottom_common,
                    9,
                ),
                socket_stage_common_mm3=round(socket_common, 9),
                socket_stage_clearance_mm=round(socket_distance, 6),
                socket_stage_minimum_contract_mm=(
                    A09_LIFT_BASE_SOCKET_MINIMUM_DRY_CLEARANCE_MM
                ),
                fixed_armrest=fixed_armrest.name,
                socket_fixed_armrest_common_mm3=round(
                    socket_armrest_common,
                    9,
                ),
                socket_fixed_armrest_dry_gap_mm=round(
                    socket_armrest_distance,
                    6,
                ),
                underside_wall_probe_common_mm3=round(underside_common, 9),
                lift_aperture_probe_common_mm3=round(aperture_common, 9),
                belly_stage_common_mm3=[
                    round(value, 9) for value in belly_stage_common
                ],
                belly_stage_clearance_mm=[
                    round(value, 6) for value in belly_stage_distance
                ],
                stage_a05_common_mm3=[
                    round(value, 9) for value in stage_a05_common
                ],
                stage_a05_clearance_mm=[
                    round(value, 6) for value in stage_a05_distance
                ],
                stage_a05_minimum_contract_mm=(
                    A09_LIFT_A05_MINIMUM_DRY_CLEARANCE_MM
                ),
                stage3_table_underbelly_common_mm3=round(
                    stage3_underbelly_common,
                    9,
                ),
                **extra_evidence,
            )


def _a10_release_axis() -> cq.Shape:
    shape = (
        cq.Workplane("YZ")
        .circle(18.5)
        .extrude(10.0, both=True)
        .translate((329.0, 120.0, 330.0))
        .val()
    )
    if not isinstance(shape, cq.Shape):
        raise TypeError("A10 release-axis witness is not a CadQuery shape")
    return shape


def _gate_a09_layout_architecture(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    """Release the truthful table layout without supplier-detail fiction.

    Final table positions, physical load-path contacts, real exterior root
    necks and in-armrest packaging are hard geometry.  Exact catalogue guide,
    bearing and fastener details remain explicitly unfrozen.
    """

    retired_prefixes = (
        "A09_cafe_armrest_to_table_root_bridge_",
        "A09_cafe_root_mechanism_fairing_",
        "A09_cafe_underleaf_saddle_",
        "A09_focus_armrest_to_table_root_bridge_",
        "A09_focus_root_fairing_",
        "A09_focus_underleaf_saddle_",
        "A09_table_lift_moving_stage_",
    )
    retired = {
        state: sorted(
            part.name
            for part in parts
            if part.name.startswith(retired_prefixes)
        )
        for state, parts in states.items()
    }
    book.add(
        "a09.four_state.retired_exposed_prototype_supports_absent",
        all(not names for names in retired.values()),
        evidence_kind="four_state_occurrence_inventory",
        requirement=(
            "No state may recreate the prototype bridge, fairing, saddle or "
            "exposed lift-post stack."
        ),
        forbidden_occurrences=retired,
    )

    cassette_comparisons: dict[str, dict[str, object]] = {}
    cassette_pass = True
    cassette_ids: list[object] = []
    for side_name in ("left", "right"):
        name = f"A05_table_root_structural_cassette_{side_name}"
        reference = _part(states["follow"], name)
        cassette_ids.append(reference.metadata.get("physical_occurrence_id"))
        side_evidence: dict[str, object] = {}
        for state in STATES:
            actual = _part(states[state], name)
            evidence = _brep_pose_evidence(reference.shape, actual.shape)
            visible = exterior_visibility_reason(state, actual)[0]
            state_ok = (
                _brep_pose_matches(evidence)
                and actual.metadata.get("physical_occurrence_id")
                == reference.metadata.get("physical_occurrence_id")
                and actual.metadata.get("primary_table_load_path") is True
                and not visible
            )
            cassette_pass = cassette_pass and state_ok
            side_evidence[state] = {
                **evidence,
                "visible": visible,
                "status": "PASS" if state_ok else "FAIL",
            }
        cassette_comparisons[side_name] = side_evidence
    book.add(
        "a05.a09.four_state.structural_cassette_identity_and_internal_visibility",
        cassette_pass
        and all(cassette_ids)
        and len(cassette_ids) == len(set(cassette_ids)),
        evidence_kind="four_state_brep_identity_occurrence_and_visibility",
        requirement=(
            "Both tables load into state-invariant metal A05 root cassettes; "
            "the cosmetic PC-ABS armrest shell is not the primary support."
        ),
        comparisons=cassette_comparisons,
        physical_occurrence_ids=cassette_ids,
    )

    for state in ("follow", "ride"):
        exterior_a09 = sorted(
            part.name
            for part in states[state]
            if part.module == "A09" and exterior_visibility_reason(state, part)[0]
        )
        book.add(
            f"a09.{state}.deployed_table_exterior_absent",
            not exterior_a09,
            evidence_kind="state_exterior_occurrence_inventory",
            requirement=(
                "Follow and Ride keep the table leaves fully stowed and expose "
                "no A09 desk surface or support."
            ),
            exterior_a09_occurrences=exterior_a09,
        )

    cafe = states["cafe"]
    reference_cafe = cafe_root_final_occurrences()
    identity: dict[str, object] = {}
    cafe_ids: list[object] = []
    cafe_identity_pass = True
    for reference in reference_cafe:
        actual = _part(cafe, reference.name)
        evidence = _brep_pose_evidence(reference.shape, actual.shape)
        visible = exterior_visibility_reason("cafe", actual)[0]
        expected_visible = (
            reference.name == "A09_cafe_underleaf_motion_belly_right"
        )
        state_ok = (
            _brep_pose_matches(evidence)
            and actual.metadata.get("physical_occurrence_id")
            == reference.physical_occurrence_id
            and visible == expected_visible
        )
        cafe_identity_pass = cafe_identity_pass and state_ok
        cafe_ids.append(actual.metadata.get("physical_occurrence_id"))
        identity[reference.name] = {
            **evidence,
            "expected_visible": expected_visible,
            "actual_visible": visible,
            "status": "PASS" if state_ok else "FAIL",
        }
    book.add(
        "a09.cafe.final_root_upstream_identity_and_visibility",
        cafe_identity_pass
        and all(cafe_ids)
        and len(cafe_ids) == len(set(cafe_ids)),
        evidence_kind="upstream_brep_identity_occurrence_and_visibility",
        requirement=(
            "The five final Cafe root B-Reps must enter before collision "
            "partitioning; only the closed table-attached root neck may be exterior."
        ),
        expected_occurrences=[item.name for item in reference_cafe],
        identity=identity,
    )

    cafe_by_name = {part.name: part for part in cafe}
    cafe_chain = (
        "A05_table_root_structural_cassette_right",
        "A09_cafe_fixed_root_housing_right",
        "A09_cafe_fixed_yoke_bearing_carrier_right",
        "A09_cafe_rotary_hub_right",
        "A09_cafe_rotary_linear_rail_right",
        "A09_cafe_underleaf_motion_belly_right",
    )
    chain_evidence: dict[str, object] = {}
    chain_pass = True
    for first_name, second_name in zip(cafe_chain, cafe_chain[1:]):
        first = cafe_by_name[first_name].shape
        second = cafe_by_name[second_name].shape
        common = _intersection_volume(first, second)
        clearance = float(first.distance(second))
        interface_ok = (
            common <= BOOLEAN_TOLERANCE_MM3 and clearance <= 0.05 + DISTANCE_TOLERANCE_MM
        )
        chain_pass = chain_pass and interface_ok
        chain_evidence[f"{first_name}->{second_name}"] = {
            "common_volume_mm3": round(common, 9),
            "clearance_mm": round(clearance, 9),
            "status": "PASS" if interface_ok else "FAIL",
        }
    cafe_root = cafe_by_name["A09_cafe_underleaf_motion_belly_right"]
    cafe_underbelly = cafe_by_name["A09_table_underbelly_shell_right"]
    root_table_common = _intersection_volume(cafe_root.shape, cafe_underbelly.shape)
    root_table_gap = float(cafe_root.shape.distance(cafe_underbelly.shape))
    table_box = cafe_underbelly.shape.BoundingBox()
    false_detail_keys = (
        "nominal_length_mm",
        "final_carriage_capture_mm",
        "pickup_dead_travel_mm",
        "open_bottom_linear_channel",
    )
    false_detail = {
        part.name: sorted(key for key in false_detail_keys if key in part.metadata)
        for part in cafe
        if part.name in cafe_chain
    }
    book.add(
        "a09.cafe.final_static_load_path_root_neck_and_layout_limit",
        chain_pass
        and root_table_common <= BOOLEAN_TOLERANCE_MM3
        and root_table_gap <= DISTANCE_TOLERANCE_MM
        and abs(float(table_box.ymax) - 276.0) <= ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
        and cafe_root.metadata.get("internal_spreader_length_mm") == 220.0
        and cafe_root.metadata.get("root_neck_outside_armrest") is True
        and cafe_root.metadata.get("hinge_bearing_and_lock_outside_armrest") is False
        and all(not keys for keys in false_detail.values()),
        evidence_kind="brep_contact_chain_table_interface_envelope_and_metadata",
        requirement=(
            "Cafe retains the original +276 mm inboard table limit and a real "
            "cassette-to-root load chain.  One closed low-contrast neck crosses "
            "the gap and continues into a 220 mm internal spreader; no unknown "
            "supplier rail dimensions may be fabricated."
        ),
        interface_evidence=chain_evidence,
        root_to_table_common_volume_mm3=round(root_table_common, 9),
        root_to_table_clearance_mm=round(root_table_gap, 9),
        table_outer_y_mm=round(float(table_box.ymax), 6),
        false_supplier_detail_metadata=false_detail,
    )

    focus = states["focus"]
    focus_evidence: dict[str, object] = {}
    focus_pass = True
    for side_name in ("left", "right"):
        root_box = _part(focus, f"A09_focus_internal_root_box_{side_name}")
        cassette = _part(focus, f"A05_table_root_structural_cassette_{side_name}")
        stages = [
            _part(
                focus,
                f"A09_focus_internal_nested_guide_stage_{index}_{side_name}",
            )
            for index in (1, 2, 3)
        ]
        neck = _part(focus, f"A09_focus_table_hidden_root_tongue_{side_name}")
        underbelly = _part(focus, f"A09_table_underbelly_shell_{side_name}")
        interfaces = (
            ("cassette_to_root", cassette.shape, root_box.shape, 0.0),
            ("root_to_stage1", root_box.shape, stages[0].shape, 0.5),
            ("stage1_to_stage2", stages[0].shape, stages[1].shape, 0.5),
            ("stage2_to_stage3", stages[1].shape, stages[2].shape, 0.5),
            ("stage3_to_root_neck", stages[2].shape, neck.shape, 0.0),
            ("root_neck_to_table", neck.shape, underbelly.shape, 0.0),
        )
        side_interfaces: dict[str, object] = {}
        side_ok = True
        for label, first, second, minimum_clearance in interfaces:
            common = _intersection_volume(first, second)
            clearance = float(first.distance(second))
            if minimum_clearance > 0.0:
                ok = (
                    common <= BOOLEAN_TOLERANCE_MM3
                    and clearance >= minimum_clearance - DISTANCE_TOLERANCE_MM
                )
            else:
                ok = (
                    common <= BOOLEAN_TOLERANCE_MM3
                    and clearance <= DISTANCE_TOLERANCE_MM
                )
            side_ok = side_ok and ok
            side_interfaces[label] = {
                "common_volume_mm3": round(common, 9),
                "clearance_mm": round(clearance, 9),
                "status": "PASS" if ok else "FAIL",
            }
        table_box = underbelly.shape.BoundingBox()
        outer_limit = float(table_box.ymin if side_name == "left" else table_box.ymax)
        expected_limit = -276.0 if side_name == "left" else 276.0
        neck_visible = exterior_visibility_reason("focus", neck)[0]
        side_ok = side_ok and (
            abs(outer_limit - expected_limit)
            <= ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
            and neck_visible
            and neck.metadata.get("internal_spreader_length_mm") == 220.0
            and neck.metadata.get("root_neck_outside_armrest") is True
            and neck.metadata.get("hinge_bearing_and_lock_outside_armrest") is False
        )
        focus_pass = focus_pass and side_ok
        focus_evidence[side_name] = {
            "interfaces": side_interfaces,
            "table_outer_y_mm": round(outer_limit, 6),
            "root_neck_visible": neck_visible,
            "status": "PASS" if side_ok else "FAIL",
        }
    obsolete_focus_shoes = sorted(
        part.name for part in focus if "focus_table_mount_shoe" in part.name
    )
    book.add(
        "a09.focus.bilateral_internal_guides_visible_root_necks_and_spreaders",
        focus_pass and not obsolete_focus_shoes,
        evidence_kind="bilateral_brep_contact_clearance_envelope_and_visibility",
        requirement=(
            "Both Focus tables stop at +/-276 mm, load into internal A05 "
            "cassettes and expose only one honest closed root neck per side; "
            "each neck continues into a 220 mm half-leaf spreader."
        ),
        sides=focus_evidence,
        obsolete_mount_shoes=obsolete_focus_shoes,
    )


def _gate_a10_openings(
    states: Mapping[str, Sequence[SkinPart]],
    book: _GateBook,
) -> None:
    release_axis = _a10_release_axis()
    pull_cavity = rounded_box((16.0, 72.2, 32.2), (329.0, -80.0, 330.0), 10.0)
    pull_cavity = pull_cavity.fuse(
        rounded_box((16.0, 72.2, 32.2), (327.0, -80.0, 330.0), 10.0)
    ).clean()
    access_names = (
        "A10_rear_service_external_release_guard",
        "A10_rear_service_external_no_power_release",
        "A10_rear_service_pull_cup",
        "A10_rear_service_pull_grip_inlay",
    )
    for state in STATES:
        door = _part(states[state], "A10_rear_flush_service_door_skin")
        release_common = _intersection_volume(door.shape, release_axis)
        pull_common = _intersection_volume(door.shape, pull_cavity)
        access_common = {
            name: _intersection_volume(door.shape, _part(states[state], name).shape)
            for name in access_names
        }
        book.add(
            f"a10.{state}.release_and_pull_openings_are_real",
            release_common <= BOOLEAN_TOLERANCE_MM3
            and pull_common <= BOOLEAN_TOLERANCE_MM3
            and all(value <= BOOLEAN_TOLERANCE_MM3 for value in access_common.values()),
            evidence_kind="brep_boolean_aperture_and_access_partition",
            requirement=(
                "The rear service door must contain a real no-power release aperture and pull cavity, with no rigid overlap into access pieces."
            ),
            release_aperture_diameter_mm=37.0,
            pull_aperture_yz_mm=(72.0, 32.0),
            pull_cutter_yz_mm=(72.2, 32.2),
            pull_cutter_sweep_x_mm=18.0,
            release_axis_common_volume_mm3=round(release_common, 9),
            pull_cavity_common_volume_mm3=round(pull_common, 9),
            access_piece_common_volume_mm3={
                key: round(value, 9) for key, value in access_common.items()
            },
        )


def _gate_four_state_envelopes(
    states: Mapping[str, Sequence[SkinPart]],
    source_shapes: Mapping[str, cq.Shape],
    book: _GateBook,
    root: Path,
) -> None:
    for state in STATES:
        source = source_shapes.get(state)
        if source is None:
            book.add(
                f"envelope.{state}.within_locked_boundary",
                False,
                evidence_kind="controlled_trace_step_integrity",
                requirement="The immutable trace underlay must remain available while production geometry is evaluated separately.",
                error="controlled STEP unavailable",
            )
            continue

        retained_names = sorted(
            retain_exposed_names(build_state_ledger(state, repository_root=root))
        )
        retained_shapes: list[cq.Shape] = []
        missing_paths: list[str] = []
        for name in retained_names:
            part_path = root / "build" / "parts" / f"{name}.step"
            if not part_path.is_file():
                missing_paths.append(str(part_path))
                continue
            imported = cq.importers.importStep(str(part_path))
            retained = imported.val() if hasattr(imported, "val") else imported
            if not isinstance(retained, cq.Shape) or retained.isNull() or not retained.isValid():
                missing_paths.append(f"{part_path} (invalid B-Rep)")
                continue
            retained_shapes.append(retained)
        book.add(
            f"envelope.{state}.production_source_inventory_complete",
            not missing_paths and len(retained_shapes) == len(retained_names),
            evidence_kind="source_disposition_to_part_step_inventory",
            requirement=(
                "Every controlled occurrence retained on the production exterior must have a readable B-Rep; "
                "replace_surface and deleted prototype mechanisms remain trace-only."
            ),
            retained_occurrences=retained_names,
            retained_brep_count=len(retained_shapes),
            missing_or_invalid_paths=missing_paths,
        )
        if missing_paths:
            continue

        envelope = _union_boxes(
            [*(part.shape for part in states[state]), *retained_shapes]
        )
        trace_underlay_envelope = _union_boxes(
            [source, *(part.shape for part in states[state])]
        )
        source_box = _Box.from_shape(source)
        lock = _envelope_lock_evidence(
            state,
            source_box,
            envelope,
            SOURCE_STEPS[state]["reference_envelope_mm"],
        )
        book.add(
            f"envelope.{state}.within_locked_boundary",
            bool(lock["pass"]),
            evidence_kind="production_skin_plus_retained_source_brep_bounding_box",
            requirement=(
                "The production exterior (final V8 skin plus only retain_exposed controlled occurrences) "
                "must satisfy every source-boundary growth allowance and an independent overall-dimension lock; "
                "the full immutable prototype STEP is a trace underlay, not a production BOM."
            ),
            production_combined_bounds=envelope.to_dict(),
            trace_underlay_combined_bounds=trace_underlay_envelope.to_dict(),
            trace_underlay_is_not_production_bom=True,
            dorsal_mast_axis_x_mm=A07_MAST_AXIS_X_MM,
            dorsal_mast_rebase_permitted=False,
            longitudinal_final_skin_allowance_mm=25.0,
            longitudinal_final_skin_allowance_per_boundary_mm=25.0,
            lateral_wheel_skin_allowance_mm=17.0,
            wheel_nominal_product_width_mm=WHEEL_NOMINAL_PRODUCT_WIDTH_MM,
            wheel_production_width_limit_mm=WHEEL_PRODUCTION_WIDTH_LIMIT_MM,
            follow_wheel_c_wrap_motion_basis=(
                "up to 25 mm at each controlled longitudinal boundary for the "
                "143 mm axle-to-return datum and +/-10 degree tyre sweep; "
                "the independent overall length cap remains active"
                if state == "follow"
                else None
            ),
            brep_envelope_numerical_tolerance_mm=(
                ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
            ),
            **{key: value for key, value in lock.items() if key != "pass"},
        )


def run_v8_release_gates(
    *,
    parts_by_state: Mapping[str, Sequence[SkinPart]] | None = None,
    workspace_root: Path | str | None = None,
) -> dict[str, Any]:
    """Run the independent four-state V8 geometry release gate.

    ``parts_by_state`` is injectable for regression tests.  With no injection,
    the complete V8 state pipeline is rebuilt in memory in the intended order.
    """

    root = _workspace_root(Path(workspace_root) if workspace_root else WORKSPACE_ROOT)
    states = dict(parts_by_state) if parts_by_state is not None else build_all_v8_states()
    missing_states = [state for state in STATES if state not in states]
    extra_states = sorted(set(states) - set(STATES))
    if missing_states or extra_states:
        raise ValueError(
            f"V8 gate requires exactly {STATES}; missing={missing_states}, extra={extra_states}"
        )

    book = _GateBook()
    source_shapes = _gate_source_integrity(root, book)
    _gate_part_topology(states, book)
    _gate_retract_then_fold(states, book)
    _gate_fixed_backrest_root_shoulders(states, book)
    _gate_follow_compliant_seat_preload(states, book)
    _gate_a05_stowed_faces(states, book)
    _gate_a05_lid_harness(states, book)
    _gate_fixed_armrest_configuration(states, book)
    _gate_front_nose_sightline_crown(states, book)
    _gate_front_waist_closure(states, book)
    _gate_wheel_arch_coverage(states, root, book)
    _gate_a07_single_moving_spine(states, book)
    _gate_a07_positive_lock_interlock(states, book)
    _gate_a07_privacy_shutter(states, root, book)
    _gate_a08_root_enclosure(states, book)
    _gate_a08_drains(states, book)
    _gate_a09_layout_architecture(states, book)
    _gate_a10_openings(states, book)
    _gate_four_state_envelopes(states, source_shapes, book, root)

    ids_before_schema_check = [item["id"] for item in book.checks]
    evidence_kinds_before_schema_check = [item.get("evidence_kind") for item in book.checks]
    book.add(
        "report.schema.unique_ids_and_evidence_kind",
        len(ids_before_schema_check) == len(set(ids_before_schema_check))
        and all(isinstance(value, str) and bool(value.strip()) for value in evidence_kinds_before_schema_check),
        evidence_kind="report_schema_self_audit",
        requirement="Every executable check must have one unique ID and a non-empty evidence_kind.",
        audited_check_count=len(ids_before_schema_check),
    )

    failures = [
        item
        for item in book.checks
        if not item["pass"] and item.get("severity") == "hard"
    ]
    open_advisories = [
        item
        for item in book.checks
        if not item["pass"] and item.get("severity") == "advisory"
    ]
    return {
        "schema_version": 1,
        "gate": "WorkCore E6 V8 final-exterior executable release gate",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "four-state STEP-anchored V8 exterior geometry",
        "status": "PASS" if not failures else "FAIL",
        "production_certification_claimed": False,
        "decision": (
            "GEOMETRY_GATE_PASS_NOT_PRODUCTION_CERTIFICATION"
            if not failures
            else "GEOMETRY_GATE_FAIL"
        ),
        "not_certified_domains": [
            "Class-A highlight/surface continuity",
            "DFM/DFA and tooling release",
            "structural and safety validation",
            "thermal, RF and EMC validation",
            "environmental sealing and ageing",
            "human factors and physical misuse testing",
            "regulatory compliance and production approval",
        ],
        "summary": {
            "state_count": len(STATES),
            "skin_part_count": sum(len(states[state]) for state in STATES),
            "check_count": len(book.checks),
            "hard_failure_count": len(failures),
            "open_advisory_count": len(open_advisories),
        },
        "hard_failures": [item["id"] for item in failures],
        "open_advisories": [item["id"] for item in open_advisories],
        "checks": book.checks,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path; no file is written when omitted.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only status/summary/failure IDs instead of the full report.",
    )
    parser.add_argument("--compact", action="store_true", help="Write compact JSON.")
    args = parser.parse_args()

    report = run_v8_release_gates()
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=None if args.compact else 2,
            )
            + "\n",
            encoding="utf-8",
        )
    shown: Mapping[str, Any] = report
    if args.summary:
        shown = {
            "status": report["status"],
            "decision": report["decision"],
            "production_certification_claimed": report[
                "production_certification_claimed"
            ],
            "summary": report["summary"],
            "hard_failures": report["hard_failures"],
        }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["build_all_v8_states", "build_v8_state", "run_v8_release_gates"]
