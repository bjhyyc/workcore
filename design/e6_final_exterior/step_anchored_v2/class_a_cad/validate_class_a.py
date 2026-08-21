"""Independent validation for the STEP-anchored E6 Class-A skin.

The validator is deliberately read-only with respect to ``build/``.  It can be
called in three ways:

1. from the Class-A build script with in-memory ``SkinPart`` objects;
2. from the command line with a JSON manifest;
3. from the command line with a Python provider module that returns parts.

The JSON contract is intentionally permissive while the exterior build is
evolving.  A manifest may contain ``parts`` as a flat list or as a mapping from
configuration to lists.  Every part needs a name, module, configuration and
bounds.  Bounds may be ``xmin`` ... ``zmax``, ``min``/``max`` arrays, or
``center``/``size`` arrays.  Optional ``step_path`` entries enable direct solid
clearance checks.  Equivalent in-memory objects only need ``name``, ``module``,
``configuration``, ``bounds()`` and ``shape`` attributes (the ``SkinPart`` API).

Hard failures produce a non-zero process exit.  ``--allow-missing-evidence``
only downgrades absent design evidence during an intermediate build; measured
collisions, bad positions, envelope overruns and source STEP hash changes remain
hard failures.  Reports are JSON and never write into the controlled ``build``
tree.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


STATES = ("follow", "ride", "cafe", "focus")
STATE_ALIASES = {
    "follow": "follow",
    "follow_closed": "follow",
    "ride": "ride",
    "seat": "ride",
    "seat_ready": "ride",
    "cafe": "cafe",
    "café": "cafe",
    "focus": "focus",
    "desk": "focus",
    "deployed_desk": "focus",
}

# These are the four controlled E6-DFR5-A07-SHARED-HINGE state files used as
# the immutable engineering underlay for this exterior release candidate.
# E6-DFR3 and parent E6-DFR4 remain preserved as trace evidence.
SOURCE_STEP_BASELINE = {
    "follow": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_follow.step",
        "bytes": 6_129_275,
        "sha256": "f925527ce086f2b18b0c53312733aadd6fa69aebb541d158f260d9c33b1a88fc",
        "reference_envelope_mm": (835.0, 735.0, 689.5),
        "bounds_mm": {
            "xmin": -505.0,
            "xmax": 330.0,
            "ymin": -361.0,
            "ymax": 374.0,
            "zmin": 0.0,
            "zmax": 695.4227814713706,
        },
    },
    "ride": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_ride.step",
        "bytes": 5_810_509,
        "sha256": "3bf21b0811845c0d0fc10fbd116c96fc2188cc6e7a54956cd5e383c6a48fbb89",
        "reference_envelope_mm": (1061.0, 735.0, 1072.0),
        "bounds_mm": {
            "xmin": -710.0,
            "xmax": 351.0,
            "ymin": -361.0,
            "ymax": 374.0,
            "zmin": 0.0,
            "zmax": 1072.0,
        },
    },
    "cafe": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_cafe.step",
        "bytes": 6_117_206,
        "sha256": "8118b34c83bde30f316717e028279de656db4640d1c1f74e2c7fb6c96ecddd88",
        "reference_envelope_mm": (856.0, 735.0, 1072.0),
        "bounds_mm": {
            "xmin": -505.0,
            "xmax": 351.0,
            "ymin": -361.0,
            "ymax": 374.0,
            "zmin": 0.0,
            "zmax": 1072.0,
        },
    },
    "focus": {
        "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_focus.step",
        "bytes": 6_267_448,
        "sha256": "598ad5a8686989be548140c5629a1b996b85bc833f1672850c98da400626ed4c",
        "reference_envelope_mm": (971.0, 735.0, 1492.0),
        "bounds_mm": {
            "xmin": -620.0,
            "xmax": 351.0,
            "ymin": -361.0,
            "ymax": 374.0,
            "zmin": 0.0,
            "zmax": 1492.0,
        },
    },
}

SOURCE_MANIFEST_BASELINE = {
    "path": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/e6_dfr5_a07_hinge_manifest.json",
    "bytes": 253_631,
    "sha256": "dc27774b66320f8580c7bcd7d23a5c0f97e8e2187a808809f8116e811bc601a4",
}

# Final skin is allowed a production-realistic reveal beyond the current
# engineering underlay, but not an unconstrained change of product architecture.
# Follow needs up to 25 mm at each longitudinal source boundary for the
# released wheel C-wrap and the independently fixed rear finish.  That
# per-boundary allowance is paired with a separate source-length + 50 mm
# overall lock; it is not an unconstrained 50 mm translation.  Laterally, a
# 17 mm per-boundary check and a separate 752 mm overall product-width lock
# close the actual moulding stack: 15.5 mm swept-tyre clearance plus a 1.9 mm
# weather wall produces a 750.8 mm nominal exterior.  This is the same
# contract enforced by ``v8_release_gates._gate_four_state_envelopes``.
ENVELOPE_ALLOWANCE_MM = {"x": 25.0, "y": 17.0, "z": 10.0}
ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM = 0.01

# Frozen A06/A07 kinematic hard points.  These values describe the controlled
# product architecture, not a styling allowance: Ride and Cafe share the same
# low A07 pose, Focus leaves the fixed outer sleeve in place and translates the
# moving sleeve/terminal only, and Follow applies the same additional hinge
# transform as A06.  In particular, there is no permission to rebase the whole
# occupied mast rearward merely to make a new fairing fit.
A07_MAST_AXIS_X_MM = 310.0
A07_LOW_BEAM_CENTER_Z_MM = 1040.0
A07_FOCUS_TRANSLATION_MM = 420.0
A07_FOCUS_BEAM_CENTER_Z_MM = (
    A07_LOW_BEAM_CENTER_Z_MM + A07_FOCUS_TRANSLATION_MM
)
A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM = (264.5, 128.0, 1460.0)
A07_TERMINAL_NOMINAL_WIDTH_Y_MM = 370.0
A07_MINIMUM_EXTENDED_CAPTURE_MM = 150.0
A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM = 3.0
A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM = {
    "xmin_min": -450.0,
    "xmax_max": 230.0,
    "ymin_min": -211.0,
    "ymax_max": 211.0,
    "zmin_min": 550.0,
    "zmax_max": 705.0,
    "xspan_min": 600.0,
    "yspan_min": 360.0,
    "zspan_min": 100.0,
}
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
RIGHT_CONTROL_HAND_ENVELOPE_PLAN_RADII_MM = (70.0, 52.0)
RIGHT_CONTROL_HAND_ENVELOPE_CENTER_MM = (-268.0, 333.0, 650.0)
RIGHT_CONTROL_HAND_ENVELOPE_HEIGHT_MM = 120.0
RIGHT_CONTROL_MINIMUM_TABLE_CLEARANCE_MM = 5.0
A06_A07_COMMON_FOLD_HINGE_MM = (160.0, 0.0, 515.0)
A06_A07_FOLLOW_FOLD_DEG = -95.0
A06_LOCK_STATION_Y_MM = 333.5
A06_LOCK_DISC_AXIAL_MM = 10.0
A06_LOCK_DISC_RADIUS_MM = 26.0
SOURCE_ENVELOPE_KEYS = {
    "follow": "follow",
    "ride": "seat",
    "cafe": "cafe",
    "focus": "desk",
}


def _workspace_root(start: Path | None = None) -> Path:
    candidate = (start or Path(__file__)).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for parent in (candidate, *candidate.parents):
        if (parent / "cad" / "parameters.py").is_file() and (parent / "build").is_dir():
            return parent
    raise FileNotFoundError("Unable to locate workspace root containing cad/parameters.py and build/")


WORKSPACE_ROOT = _workspace_root()
CLASS_A_DIRECTORY = Path(__file__).resolve().parent
for _import_path in (WORKSPACE_ROOT, CLASS_A_DIRECTORY):
    if str(_import_path) not in sys.path:
        sys.path.insert(0, str(_import_path))

from v8_state_contract import (  # noqa: E402
    DEFAULT_FOOTREST_STATE,
    FOOTREST_CONTRACT_VERSION,
    default_footrest_is_deployed,
    optional_footrest_open_available,
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


def _canonical_state(value: Any) -> str | None:
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return STATE_ALIASES.get(text)


def _states(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset(STATES)
    if isinstance(value, str):
        if value.strip().lower() in {"all", "both", "common", "any", "*"}:
            return frozenset(STATES)
        values = [item for item in value.replace(";", ",").split(",") if item.strip()]
    elif isinstance(value, Sequence):
        values = list(value)
    else:
        values = [value]
    result = {_canonical_state(item) for item in values}
    result.discard(None)
    return frozenset(result)


@dataclass(frozen=True)
class Bounds:
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float

    @property
    def xlen(self) -> float:
        return self.xmax - self.xmin

    @property
    def ylen(self) -> float:
        return self.ymax - self.ymin

    @property
    def zlen(self) -> float:
        return self.zmax - self.zmin

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.xmin + self.xmax) / 2.0,
            (self.ymin + self.ymax) / 2.0,
            (self.zmin + self.zmax) / 2.0,
        )

    def union(self, other: "Bounds") -> "Bounds":
        return Bounds(
            min(self.xmin, other.xmin),
            max(self.xmax, other.xmax),
            min(self.ymin, other.ymin),
            max(self.ymax, other.ymax),
            min(self.zmin, other.zmin),
            max(self.zmax, other.zmax),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "xmin": round(self.xmin, 3),
            "xmax": round(self.xmax, 3),
            "ymin": round(self.ymin, 3),
            "ymax": round(self.ymax, 3),
            "zmin": round(self.zmin, 3),
            "zmax": round(self.zmax, 3),
            "xlen": round(self.xlen, 3),
            "ylen": round(self.ylen, 3),
            "zlen": round(self.zlen, 3),
        }

    @classmethod
    def from_value(cls, value: Any) -> "Bounds":
        if isinstance(value, Bounds):
            return value
        if callable(value):
            value = value()
        if not isinstance(value, Mapping):
            raise TypeError(f"Bounds must be a mapping, received {type(value)!r}")
        if all(key in value for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")):
            return cls(*(float(value[key]) for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")))
        if "min" in value and "max" in value:
            lo, hi = value["min"], value["max"]
            return cls(float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]), float(lo[2]), float(hi[2]))
        if "center" in value and "size" in value:
            center, size = value["center"], value["size"]
            half = [float(item) / 2.0 for item in size]
            return cls(
                float(center[0]) - half[0],
                float(center[0]) + half[0],
                float(center[1]) - half[1],
                float(center[1]) + half[1],
                float(center[2]) - half[2],
                float(center[2]) + half[2],
            )
        raise KeyError("Bounds require min/max, center/size, or xmin...zmax values")


def _bounds_from_shape(shape: Any) -> Bounds:
    if hasattr(shape, "val") and callable(shape.val):
        shape = shape.val()
    box = shape.BoundingBox()
    return Bounds(float(box.xmin), float(box.xmax), float(box.ymin), float(box.ymax), float(box.zmin), float(box.zmax))


def _union_bounds(values: Iterable[Bounds]) -> Bounds | None:
    result: Bounds | None = None
    for value in values:
        result = value if result is None else result.union(value)
    return result


def _bounds_pose_delta(
    reference: Bounds,
    candidate: Bounds,
    candidate_to_reference_translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> float:
    """Maximum six-plane delta after applying a declared rigid translation."""

    dx, dy, dz = candidate_to_reference_translation
    reference_values = (
        reference.xmin,
        reference.xmax,
        reference.ymin,
        reference.ymax,
        reference.zmin,
        reference.zmax,
    )
    candidate_values = (
        candidate.xmin + dx,
        candidate.xmax + dx,
        candidate.ymin + dy,
        candidate.ymax + dy,
        candidate.zmin + dz,
        candidate.zmax + dz,
    )
    return max(abs(a - b) for a, b in zip(reference_values, candidate_values))


@dataclass
class PartRecord:
    name: str
    module: str
    states: frozenset[str]
    bounds: Bounds
    metadata: dict[str, Any] = field(default_factory=dict)
    step_path: Path | None = None
    shape: Any = None

    @property
    def search_text(self) -> str:
        tags = [self.name, self.module]
        tags.extend(f"{key} {value}" for key, value in self.metadata.items())
        return " ".join(tags).lower().replace("-", "_")


@dataclass
class OpeningRecord:
    name: str
    states: frozenset[str]
    bounds: Bounds | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        return (self.name + " " + " ".join(f"{k} {v}" for k, v in self.metadata.items())).lower().replace("-", "_")


class Checks:
    def __init__(self, *, allow_missing_evidence: bool = False) -> None:
        self.items: list[dict[str, Any]] = []
        self.allow_missing_evidence = allow_missing_evidence
        self._ids: set[str] = set()
        self._duplicate_id_count = 0

    def add(
        self,
        check_id: str,
        passed: bool,
        *,
        severity: str = "hard",
        missing_evidence: bool = False,
        **details: Any,
    ) -> None:
        if check_id in self._ids:
            self._duplicate_id_count += 1
            duplicate_report_id = (
                f"report.schema.duplicate_check_id.{self._duplicate_id_count}"
            )
            self._ids.add(duplicate_report_id)
            self.items.append(
                {
                    "id": duplicate_report_id,
                    "pass": False,
                    "severity": "hard",
                    "duplicate_check_id": check_id,
                    "requirement": "Every validation check ID must be globally unique.",
                }
            )
            return
        self._ids.add(check_id)
        effective = "warning" if missing_evidence and self.allow_missing_evidence else severity
        item = {"id": check_id, "pass": bool(passed), "severity": effective}
        if missing_evidence:
            item["missing_evidence"] = True
        item.update(details)
        self.items.append(item)

    @property
    def hard_failures(self) -> list[dict[str, Any]]:
        return [item for item in self.items if item["severity"] == "hard" and not item["pass"]]

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return [item for item in self.items if item["severity"] == "warning" and not item["pass"]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_release_hashes(root: Path) -> dict[str, dict[str, Any]]:
    path = root / SOURCE_MANIFEST_BASELINE["path"]
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("artifacts", {}).get("files", [])
    return {str(item.get("path", "")).replace("\\", "/"): item for item in files}


def _validate_source_steps(root: Path, checks: Checks) -> None:
    release_hashes = _manifest_release_hashes(root)
    source_manifest = root / SOURCE_MANIFEST_BASELINE["path"]
    manifest_exists = source_manifest.is_file()
    manifest_hash = _sha256(source_manifest) if manifest_exists else None
    manifest_bytes = source_manifest.stat().st_size if manifest_exists else None
    manifest_payload = (
        json.loads(source_manifest.read_text(encoding="utf-8"))
        if manifest_exists
        else {}
    )
    checks.add(
        "source.release_manifest_present",
        bool(release_hashes)
        and manifest_hash == SOURCE_MANIFEST_BASELINE["sha256"]
        and manifest_bytes == SOURCE_MANIFEST_BASELINE["bytes"],
        missing_evidence=not manifest_exists,
        path=SOURCE_MANIFEST_BASELINE["path"],
        expected_sha256=SOURCE_MANIFEST_BASELINE["sha256"],
        actual_sha256=manifest_hash,
        expected_bytes=SOURCE_MANIFEST_BASELINE["bytes"],
        actual_bytes=manifest_bytes,
    )
    source_validation = manifest_payload.get("validation", {})
    optional_states = manifest_payload.get("optional_validation_states", [])
    optional_state_names = {
        str(value) for value in optional_states
    } if isinstance(optional_states, Sequence) and not isinstance(optional_states, str) else set()
    checks.add(
        "source.a08_contract_and_optional_states_validated",
        manifest_payload.get("footrest_contract_version") == FOOTREST_CONTRACT_VERSION
        and source_validation.get("status") == "PASS"
        and int(source_validation.get("failed_count", -1)) == 0
        and {"cafe_footrest_open", "focus_footrest_open"}.issubset(optional_state_names),
        missing_evidence=not manifest_exists,
        requirement=(
            "The pinned DFR5 source manifest must retain the A08 pose contract, "
            "zero failed source checks, and explicit Café/Focus optional-open substates."
        ),
        expected_contract_version=FOOTREST_CONTRACT_VERSION,
        actual_contract_version=manifest_payload.get("footrest_contract_version"),
        validation_status=source_validation.get("status"),
        validation_failed_count=source_validation.get("failed_count"),
        optional_validation_states=sorted(optional_state_names),
    )
    source_states = manifest_payload.get("states", {})
    source_base = Path(SOURCE_MANIFEST_BASELINE["path"]).parent
    for optional_state in ("cafe_footrest_open", "focus_footrest_open"):
        state_payload = (
            source_states.get(optional_state, {})
            if isinstance(source_states, Mapping)
            else {}
        )
        checks.add(
            f"source.{optional_state}.contract_semantics",
            state_payload.get("primary_render_state") is False
            and state_payload.get("footrest_pose") == "deployed_locked"
            and state_payload.get("optional_footrest_open_available") is True
            and int(state_payload.get("a08_occurrence_count", -1)) == 6
            and abs(float(state_payload.get("a08_total_mass_kg", -1.0)) - 1.890986991)
            <= 1.0e-9,
            missing_evidence=not state_payload,
            requirement=(
                "Each Café/Focus optional-open source state must be explicitly "
                "excluded from the primary render series and retain the six-item "
                "A08 deployed-locked contract at invariant mass."
            ),
            state_manifest=state_payload,
        )
        for extension_key in ("step", "glb"):
            filename = state_payload.get(extension_key)
            logical_path = (
                (source_base / str(filename)).as_posix()
                if filename
                else ""
            )
            file_path = root / logical_path if logical_path else None
            manifest_item = release_hashes.get(logical_path)
            exists = bool(file_path and file_path.is_file())
            actual_hash = _sha256(file_path) if exists and file_path else None
            actual_bytes = file_path.stat().st_size if exists and file_path else None
            checks.add(
                f"source.{optional_state}.{extension_key}_manifest_binding",
                exists
                and bool(manifest_item)
                and actual_hash == manifest_item.get("sha256")
                and actual_bytes == int(manifest_item.get("bytes", -1)),
                missing_evidence=not exists or not manifest_item,
                path=logical_path,
                actual_sha256=actual_hash,
                actual_bytes=actual_bytes,
                manifest_entry=manifest_item,
            )
    for state, expected in SOURCE_STEP_BASELINE.items():
        path = root / expected["path"]
        exists = path.is_file()
        checks.add(f"source.{state}.step_present", exists, path=expected["path"])
        if not exists:
            continue
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        checks.add(
            f"source.{state}.immutable_hash",
            actual_hash == expected["sha256"] and actual_size == expected["bytes"],
            path=expected["path"],
            expected_sha256=expected["sha256"],
            actual_sha256=actual_hash,
            expected_bytes=expected["bytes"],
            actual_bytes=actual_size,
        )
        manifest_item = release_hashes.get(expected["path"])
        checks.add(
            f"source.{state}.release_manifest_binding",
            bool(manifest_item)
            and manifest_item.get("sha256") == expected["sha256"]
            and int(manifest_item.get("bytes", -1)) == expected["bytes"],
            missing_evidence=not manifest_item,
            manifest_entry=manifest_item,
        )


def _part_from_mapping(item: Mapping[str, Any], default_state: str | None, base: Path) -> PartRecord:
    metadata = dict(item.get("metadata") or {})
    if "intent" in item and "intent" not in metadata:
        metadata["intent"] = item["intent"]
    if "material" in item and "material" not in metadata:
        metadata["material"] = item["material"]
    for key in ("role", "feature", "feature_id", "opening_id", "side", "moves_with", "deployed", "clearance_exempt"):
        if key in item and key not in metadata:
            metadata[key] = item[key]
    bounds_value = item.get("bounds") or item.get("bbox") or item.get("envelope")
    if bounds_value is None:
        bounds_value = item
    step_value = item.get("step_path") or item.get("step") or item.get("file")
    step_path = None
    if step_value:
        step_path = Path(str(step_value))
        if not step_path.is_absolute():
            step_path = (base / step_path).resolve()
    return PartRecord(
        name=str(item.get("name") or item.get("part_name") or item.get("id") or "unnamed"),
        module=str(item.get("module") or item.get("group") or metadata.get("module") or "unassigned"),
        states=_states(item.get("configuration", item.get("configurations", default_state))),
        bounds=Bounds.from_value(bounds_value),
        metadata=metadata,
        step_path=step_path,
    )


def _part_from_object(item: Any, default_state: str | None = None) -> PartRecord:
    metadata = dict(getattr(item, "metadata", {}) or {})
    material = getattr(item, "material", None)
    intent = getattr(item, "intent", None)
    if material is not None and "material" not in metadata:
        metadata["material"] = material
    if intent and "intent" not in metadata:
        metadata["intent"] = intent
    state_value = getattr(item, "configuration", default_state)
    shape = getattr(item, "shape", None)
    raw_bounds = getattr(item, "bounds", None)
    bounds = Bounds.from_value(raw_bounds) if raw_bounds is not None else _bounds_from_shape(shape)
    return PartRecord(
        name=str(getattr(item, "name", "unnamed")),
        module=str(getattr(item, "module", metadata.get("module", "unassigned"))),
        states=_states(state_value),
        bounds=bounds,
        metadata=metadata,
        shape=shape,
    )


def _flatten_parts(value: Any, base: Path) -> list[PartRecord]:
    result: list[PartRecord] = []
    if isinstance(value, Mapping):
        # A single serialized part has a name/bounds; otherwise treat keys as states.
        if any(key in value for key in ("name", "part_name", "bounds", "bbox")):
            return [_part_from_mapping(value, None, base)]
        for key, members in value.items():
            state = _canonical_state(key)
            if state is None or not isinstance(members, Iterable) or isinstance(members, (str, bytes, Mapping)):
                continue
            for item in members:
                if isinstance(item, PartRecord):
                    result.append(item)
                else:
                    result.append(_part_from_mapping(item, state, base) if isinstance(item, Mapping) else _part_from_object(item, state))
        return result
    for item in value or []:
        if isinstance(item, PartRecord):
            result.append(item)
        else:
            result.append(_part_from_mapping(item, None, base) if isinstance(item, Mapping) else _part_from_object(item))
    return result


def _extract_parts(payload: Mapping[str, Any], base: Path) -> list[PartRecord]:
    for key in ("parts", "skin_parts", "parts_by_configuration", "configurations"):
        if key in payload:
            return _flatten_parts(payload[key], base)
    # Native build_class_a_skin.py layout: each state owns its serialized parts
    # and exported STEP directory.  Keeping this adapter here avoids coupling
    # the builder to a second manifest format.
    state_payloads = payload.get("states")
    if isinstance(state_payloads, Mapping):
        result: list[PartRecord] = []
        for state_name, state_payload in state_payloads.items():
            state = _canonical_state(state_name)
            if state is None or not isinstance(state_payload, Mapping):
                continue
            for item in state_payload.get("parts", []) or []:
                if not isinstance(item, Mapping):
                    continue
                record = _part_from_mapping(item, state, base)
                if record.step_path is None:
                    record.step_path = (base / state / "parts" / f"{record.name}.step").resolve()
                result.append(record)
        return result
    return []


def _opening_from_mapping(item: Mapping[str, Any], default_state: str | None = None) -> OpeningRecord:
    bounds = None
    raw_bounds = item.get("bounds") or item.get("bbox") or item.get("envelope")
    if raw_bounds:
        bounds = Bounds.from_value(raw_bounds)
    name = str(item.get("id") or item.get("name") or item.get("opening_id") or "unnamed_opening")
    metadata = {key: value for key, value in item.items() if key not in {"bounds", "bbox", "envelope"}}
    return OpeningRecord(name, _states(item.get("configuration", item.get("configurations", default_state))), bounds, metadata)


def _extract_openings(payload: Mapping[str, Any], parts: Sequence[PartRecord]) -> list[OpeningRecord]:
    result: list[OpeningRecord] = []
    raw = payload.get("functional_openings") or payload.get("openings") or []
    if isinstance(raw, Mapping):
        for state_name, entries in raw.items():
            for item in entries or []:
                result.append(_opening_from_mapping(item, _canonical_state(state_name)))
    else:
        for item in raw:
            if isinstance(item, Mapping):
                result.append(_opening_from_mapping(item))
    state_payloads = payload.get("states")
    if isinstance(state_payloads, Mapping):
        for state_name, state_payload in state_payloads.items():
            if not isinstance(state_payload, Mapping):
                continue
            for item in state_payload.get("functional_openings", []) or []:
                if isinstance(item, Mapping):
                    result.append(_opening_from_mapping(item, _canonical_state(state_name)))
    for part in parts:
        text = part.search_text
        opening_id = part.metadata.get("functional_opening") or part.metadata.get("opening_id")
        proxy_word = any(word in text for word in ("opening", "cutout", "window", "shutter", "service_door", "service_surround", "emergency_stop", "drain", "release"))
        if opening_id or proxy_word:
            result.append(OpeningRecord(str(opening_id or part.name), part.states, part.bounds, dict(part.metadata)))
        # A single rear service aperture intentionally exposes the controlled
        # door, charge port, battery disconnect and brake release.  Emit the
        # four semantic proxies from that explicit aperture metadata.
        if "service_aperture_mm" in part.metadata:
            for semantic_id in ("rear_service_door", "charge_port", "battery_disconnect", "brake_release"):
                result.append(OpeningRecord(semantic_id, part.states, part.bounds, {"source_part": part.name}))
        if any("drain" in str(key).lower() for key in part.metadata):
            result.append(OpeningRecord("drainage", part.states, part.bounds, {"source_part": part.name}))
    return result


def _load_json_manifest(path: Path) -> tuple[dict[str, Any], list[PartRecord]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("Class-A manifest root must be a JSON object")
    data = dict(payload)
    return data, _extract_parts(data, path.parent)


def _provider_payload(module_path: Path) -> tuple[dict[str, Any], list[PartRecord]]:
    module_name = f"workcore_class_a_provider_{hashlib.sha1(str(module_path).encode()).hexdigest()[:10]}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load provider module {module_path}")
    import_paths = [str(module_path.parent), str(_workspace_root(module_path))]
    sys.path[0:0] = import_paths
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        del sys.path[: len(import_paths)]

    provided: Any = None
    for name in ("validation_payload", "build_all", "build_configurations", "get_parts", "build_parts"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            provided = candidate()
            break
    if provided is None:
        for name in ("PARTS_BY_CONFIGURATION", "CONFIGURATIONS", "PARTS"):
            if hasattr(module, name):
                provided = getattr(module, name)
                break
    if provided is None:
        state_builders: dict[str, Any] = {}
        for state in STATES:
            for name in (f"build_{state}", f"build_{state}_skin", f"{state}_parts"):
                candidate = getattr(module, name, None)
                if callable(candidate):
                    state_builders[state] = candidate()
                    break
        provided = state_builders
    if provided is not None and isinstance(provided, Mapping) and not provided:
        provided = None
    if provided is None:
        lower_builder = getattr(module, "build_lower_skin", None)
        upper_builder = getattr(module, "build_upper_skin", None)
        if callable(lower_builder) and callable(upper_builder):
            provided = {
                state: list(lower_builder(state)) + list(upper_builder(state))
                for state in STATES
            }
    if provided is None:
        raise AttributeError("Provider exposes no supported parts API")

    evidence = getattr(module, "VALIDATION_EVIDENCE", {}) or {}
    openings = getattr(module, "FUNCTIONAL_OPENINGS", []) or []
    if isinstance(provided, Mapping) and any(key in provided for key in ("parts", "skin_parts", "configurations")):
        payload = dict(provided)
    else:
        payload = {"parts": provided}
    payload.setdefault("validation_evidence", evidence)
    payload.setdefault("functional_openings", openings)
    return payload, _extract_parts(payload, module_path.parent)


def _shape_of(record: PartRecord, search_roots: Sequence[Path], cq: Any) -> Any | None:
    if record.shape is not None:
        return record.shape.val() if hasattr(record.shape, "val") else record.shape
    candidates: list[Path] = []
    if record.step_path is not None:
        candidates.append(record.step_path)
    filename = f"{record.name}.step"
    for root in search_roots:
        for pattern in (
            f"{next(iter(record.states), '')}/{filename}",
            f"parts/{next(iter(record.states), '')}/{filename}",
            f"steps/{next(iter(record.states), '')}/{filename}",
            filename,
        ):
            candidates.append(root / pattern)
        # Recursive fallback supports any export layout while names are unique.
        candidates.extend(root.glob(f"**/{filename}"))
    for candidate in candidates:
        if candidate.is_file():
            record.step_path = candidate.resolve()
            imported = cq.importers.importStep(str(candidate))
            record.shape = imported.val() if hasattr(imported, "val") else imported
            return record.shape
    return None


def _import_cadquery() -> Any | None:
    try:
        import cadquery as cq  # type: ignore

        return cq
    except Exception:
        return None


def _source_envelopes(root: Path) -> dict[str, dict[str, float]]:
    path = root / "build" / "validation.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("overall_envelopes") or {})


def _validate_envelopes(
    root: Path,
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any | None,
) -> None:
    references = _source_envelopes(root)
    for state in STATES:
        state_parts = [part for part in parts if state in part.states]
        checks.add(
            f"envelope.{state}.skin_parts_present",
            bool(state_parts),
            missing_evidence=not state_parts,
            part_count=len(state_parts),
        )
        if not state_parts:
            continue
        skin_box = _union_bounds(part.bounds for part in state_parts)
        source_key = SOURCE_ENVELOPE_KEYS[state]
        reference = references.get(source_key)
        checks.add(
            f"envelope.{state}.source_reference_present",
            bool(reference),
            missing_evidence=not reference,
            source_key=source_key,
        )
        if skin_box is None or not reference:
            continue

        source_baseline_box = Bounds.from_value(
            SOURCE_STEP_BASELINE[state]["bounds_mm"]
        )
        reference_envelope_mm = tuple(
            float(value)
            for value in SOURCE_STEP_BASELINE[state]["reference_envelope_mm"]
        )
        final_box = skin_box
        trace_underlay_box = skin_box.union(source_baseline_box)
        if cq is not None:
            source_path = root / SOURCE_STEP_BASELINE[state]["path"]
            try:
                source_shape = cq.importers.importStep(str(source_path))
                source_shape = source_shape.val() if hasattr(source_shape, "val") else source_shape
                source_step_box = _bounds_from_shape(source_shape)
                trace_underlay_box = skin_box.union(source_step_box)
                source_bound_delta = max(
                    abs(a - b)
                    for a, b in zip(
                        (
                            source_baseline_box.xmin,
                            source_baseline_box.xmax,
                            source_baseline_box.ymin,
                            source_baseline_box.ymax,
                            source_baseline_box.zmin,
                            source_baseline_box.zmax,
                        ),
                        (
                            source_step_box.xmin,
                            source_step_box.xmax,
                            source_step_box.ymin,
                            source_step_box.ymax,
                            source_step_box.zmin,
                            source_step_box.zmax,
                        ),
                    )
                )
                checks.add(
                    f"envelope.{state}.source_step_bounds_match_hash_bound_baseline",
                    source_bound_delta
                    <= ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM,
                    maximum_bound_delta_mm=round(source_bound_delta, 9),
                    tolerance_mm=ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM,
                    expected_bounds=source_baseline_box.to_dict(),
                    actual_bounds=source_step_box.to_dict(),
                )
            except Exception as exc:
                checks.add(
                    f"envelope.{state}.source_step_bbox_readable",
                    False,
                    missing_evidence=True,
                    error=str(exc),
                )

            try:
                from source_disposition import build_state_ledger, retain_exposed_names

                retained_names = sorted(
                    retain_exposed_names(
                        build_state_ledger(state, repository_root=root)
                    )
                )
                retained_boxes = []
                missing_paths = []
                for name in retained_names:
                    part_path = root / "build" / "parts" / f"{name}.step"
                    if not part_path.is_file():
                        missing_paths.append(str(part_path))
                        continue
                    retained_shape = cq.importers.importStep(str(part_path))
                    retained_shape = (
                        retained_shape.val()
                        if hasattr(retained_shape, "val")
                        else retained_shape
                    )
                    retained_boxes.append(_bounds_from_shape(retained_shape))
                checks.add(
                    f"envelope.{state}.production_source_inventory_complete",
                    not missing_paths and len(retained_boxes) == len(retained_names),
                    missing_evidence=bool(missing_paths),
                    retained_occurrences=retained_names,
                    retained_brep_count=len(retained_boxes),
                    missing_paths=missing_paths,
                )
                if retained_boxes and not missing_paths:
                    final_box = skin_box.union(_union_bounds(retained_boxes))
            except Exception as exc:
                checks.add(
                    f"envelope.{state}.production_source_inventory_complete",
                    False,
                    missing_evidence=True,
                    error=str(exc),
                )

        boundary_limits = {
            "xmin": source_baseline_box.xmin - ENVELOPE_ALLOWANCE_MM["x"],
            "xmax": source_baseline_box.xmax + ENVELOPE_ALLOWANCE_MM["x"],
            "ymin": source_baseline_box.ymin - ENVELOPE_ALLOWANCE_MM["y"],
            "ymax": source_baseline_box.ymax + ENVELOPE_ALLOWANCE_MM["y"],
            "zmin": source_baseline_box.zmin,
            "zmax": source_baseline_box.zmax + ENVELOPE_ALLOWANCE_MM["z"],
        }
        boundary_margin = {
            "xmin": final_box.xmin - boundary_limits["xmin"],
            "xmax": boundary_limits["xmax"] - final_box.xmax,
            "ymin": final_box.ymin - boundary_limits["ymin"],
            "ymax": boundary_limits["ymax"] - final_box.ymax,
            "zmin": final_box.zmin - boundary_limits["zmin"],
            "zmax": boundary_limits["zmax"] - final_box.zmax,
        }
        boundary_pass = {
            name: margin >= -ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
            for name, margin in boundary_margin.items()
        }
        limits = {
            "x": reference_envelope_mm[0]
            + 2.0 * ENVELOPE_ALLOWANCE_MM["x"],
            "y": min(
                760.0,
                reference_envelope_mm[1] + ENVELOPE_ALLOWANCE_MM["y"],
                WHEEL_PRODUCTION_WIDTH_LIMIT_MM,
            ),
            "z": reference_envelope_mm[2] + ENVELOPE_ALLOWANCE_MM["z"],
        }
        if state == "follow":
            limits = {"x": min(limits["x"], 900.0), "y": min(limits["y"], 760.0), "z": min(limits["z"], 700.0)}
        actual = {"x": final_box.xlen, "y": final_box.ylen, "z": final_box.zlen}
        axis_boundaries = {
            "x": ("xmin", "xmax"),
            "y": ("ymin", "ymax"),
            "z": ("zmin", "zmax"),
        }
        for axis in ("x", "y", "z"):
            faces = axis_boundaries[axis]
            overall_pass = (
                actual[axis]
                <= limits[axis] + ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
            )
            checks.add(
                f"envelope.{state}.{axis}_within_lock",
                overall_pass and all(boundary_pass[face] for face in faces),
                actual_mm=round(actual[axis], 3),
                maximum_mm=round(limits[axis], 3),
                source_mm=round(
                    reference_envelope_mm[{"x": 0, "y": 1, "z": 2}[axis]],
                    3,
                ),
                source_controlled_bounds=source_baseline_box.to_dict(),
                boundary_limits_mm={
                    face: round(boundary_limits[face], 6) for face in faces
                },
                boundary_margin_mm={
                    face: round(boundary_margin[face], 6) for face in faces
                },
                boundary_pass={face: boundary_pass[face] for face in faces},
                overall_dimension_pass=overall_pass,
                allowance_per_boundary_mm=(
                    ENVELOPE_ALLOWANCE_MM[axis]
                    if axis in ("x", "y")
                    else {"lower": 0.0, "upper": ENVELOPE_ALLOWANCE_MM["z"]}
                ),
                allowance_interpretation=(
                    "Each source boundary is checked independently and the "
                    "overall product dimension is capped separately."
                ),
                brep_envelope_numerical_tolerance_mm=(
                    ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM
                ),
                production_envelope_basis="final_skin_plus_retain_exposed_controlled_occurrences",
                dorsal_mast_axis_x_mm=(
                    A07_MAST_AXIS_X_MM if axis == "x" else None
                ),
                dorsal_mast_rebase_permitted=False if axis == "x" else None,
                trace_underlay_bounds=trace_underlay_box.to_dict(),
            )


ROLE_WORDS = {
    "lower_core": ("lower_core", "lower_body", "side_shell", "core_shell", "front_nose", "rear_tail"),
    "wheel_fairing": ("wheel_fairing", "wheel_arch", "rocker_fairing", "side_skirt", "bridge_skirt", "wheel_interspace_bridge"),
    "armrest": ("armrest",),
    "backrest": ("backrest", "back_shell", "rear_cosmetic_shell"),
    "footrest": ("footrest", "foot_support", "footplate"),
    "footrest_boot": ("footrest_boot", "support_boot", "foot_support_shroud"),
    "table": ("table_leaf", "desk_leaf", "desk_panel", "table_panel", "table_edge_band", "work_surface"),
    "table_undertray": ("table_undertray", "desk_undertray", "table_underbelly", "underdeck", "root_capsule", "root_mechanism_fairing", "root_fairing", "table_mechanism_shroud"),
    "mast": ("mast", "spine", "sensor_beam", "sensor_head"),
    "mast_shroud": ("mast_shroud", "spine_shroud", "outer_shroud", "inner_shroud", "mast_fixed_outer_sleeve", "mast_moving_inner_sleeve"),
}


def _role_parts(parts: Sequence[PartRecord], state: str, role: str) -> list[PartRecord]:
    words = ROLE_WORDS[role]
    result = []
    for part in parts:
        if state not in part.states:
            continue
        explicit = " ".join(str(part.metadata.get(key, "")) for key in ("role", "feature", "feature_id")).lower()
        name = part.name.lower().replace("-", "_")
        module = part.module.lower().replace("-", "_")
        if any(word in name or word in explicit for word in words):
            result.append(part)
        elif any(word == module or module.endswith("_" + word) for word in words):
            result.append(part)
    return result


def _side(part: PartRecord) -> str:
    explicit = str(part.metadata.get("side", "")).lower()
    text = part.name.lower()
    if "left" in explicit or explicit in {"l", "-1"} or "left" in text:
        return "left"
    if "right" in explicit or explicit in {"r", "+1", "1"} or "right" in text:
        return "right"
    return "right" if part.bounds.center[1] > 25.0 else "left" if part.bounds.center[1] < -25.0 else "center"


def _metadata_float_tuple(value: object) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(float(item) for item in value)  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return ()


def _check_range(value: float, minimum: float, maximum: float) -> bool:
    return minimum - 1e-6 <= value <= maximum + 1e-6


def _module_parts(parts: Sequence[PartRecord], state: str, module: str) -> list[PartRecord]:
    """Return explicit final-skin records for one appearance module.

    Source-underlay geometry is intentionally ineligible: a record must either
    carry the requested A-module identity or use its controlled part-name
    prefix.  This prevents an imported source STEP from being counted as proof
    that a final exterior proxy exists.
    """

    module_key = module.strip().lower().replace("-", "_")
    prefix = module_key + "_"
    return [
        part
        for part in parts
        if state in part.states
        and (
            part.module.strip().lower().replace("-", "_") == module_key
            or part.name.strip().lower().replace("-", "_").startswith(prefix)
        )
    ]


def _normalised_tokens(value: Any) -> frozenset[str]:
    """Flatten a metadata value into controlled underscore tokens."""

    if value is None:
        return frozenset()
    if isinstance(value, Mapping):
        members: list[Any] = []
        for key, member in value.items():
            members.extend((key, member))
        value = members
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return frozenset(
            token
            for member in value
            for token in _normalised_tokens(member)
        )
    text = str(value).strip().lower().replace("-", "_")
    return frozenset(re.findall(r"[a-z0-9]+(?:_[a-z0-9]+)*", text))


def _functional_opening_tokens(part: PartRecord) -> frozenset[str]:
    values = (
        part.metadata.get("functional_opening"),
        part.metadata.get("opening_id"),
    )
    return frozenset(token for value in values for token in _normalised_tokens(value))


def _proxy_parts(
    parts: Sequence[PartRecord],
    state: str,
    module: str,
    *,
    name_tokens: Sequence[str] = (),
    opening_tokens: Sequence[str] = (),
    opening_token_fragments: Sequence[Sequence[str]] = (),
) -> list[PartRecord]:
    """Match a visible proxy by explicit part name or opening metadata.

    ``functional_opening`` is evaluated as tokens, rather than against the full
    metadata prose.  Exact tokens are preferred; narrow fragment groups are
    available where the part name has not yet been frozen.  Aggregate intent
    on a shell therefore cannot impersonate four separate windows or controls.
    """

    normalised_names = tuple(token.lower().replace("-", "_") for token in name_tokens)
    normalised_openings = {
        token.lower().replace("-", "_") for token in opening_tokens
    }
    fragment_groups = tuple(
        tuple(fragment.lower().replace("-", "_") for fragment in group)
        for group in opening_token_fragments
    )
    matches: list[PartRecord] = []
    for part in _module_parts(parts, state, module):
        name = part.name.lower().replace("-", "_")
        name_match = any(token in name for token in normalised_names)
        part_openings = _functional_opening_tokens(part)
        opening_match = bool(normalised_openings & part_openings) or any(
            all(fragment in token for fragment in group)
            for token in part_openings
            for group in fragment_groups
        )
        if name_match or opening_match:
            matches.append(part)
    return matches


def _add_proxy_gate(
    checks: Checks,
    check_id: str,
    matches: Sequence[PartRecord],
    *,
    minimum_count: int = 1,
    required_sides: Sequence[str] = (),
    note: str | None = None,
) -> None:
    detected_sides = sorted({_side(part) for part in matches})
    required = set(required_sides)
    passed = len(matches) >= minimum_count and required.issubset(detected_sides)
    details: dict[str, Any] = {
        "minimum_count": minimum_count,
        "detected_count": len(matches),
        "matches": [part.name for part in matches],
    }
    if required:
        details["required_sides"] = sorted(required)
        details["detected_sides"] = detected_sides
    if note:
        details["note"] = note
    # These are release hard gates.  They deliberately stay hard even when
    # --allow-missing-evidence is used for an intermediate engineering pass.
    checks.add(check_id, passed, **details)


def _validate_final_appearance_coverage(
    parts: Sequence[PartRecord], checks: Checks
) -> None:
    """Require explicit, visible exterior proxies in every controlled state.

    Envelope or clearance compliance alone is not evidence of an exterior
    design: a source assembly can satisfy both while leaving prototype modules
    exposed.  These A01/A02/A04/A05/A07/A08/A09/A10 gates therefore count only
    independent ``SkinPart`` records, with the repeated optical and service
    features represented by distinct records.
    """

    for state in STATES:
        # A01: one optical carrier, two front ToF windows plus one leg-scanner
        # window, and a final tactile edge/membrane.
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A01.optical_carrier",
            _proxy_parts(
                parts,
                state,
                "A01",
                name_tokens=("perception_horizon_carrier", "optical_carrier"),
                opening_tokens=("optical_carrier", "perception_carrier"),
            ),
        )
        front_tof = _proxy_parts(
            parts,
            state,
            "A01",
            name_tokens=("front_left_tof_window", "front_right_tof_window"),
            opening_tokens=("front_left_tof_window", "front_right_tof_window"),
        )
        leg_scanner = _proxy_parts(
            parts,
            state,
            "A01",
            name_tokens=("front_leg_scanner_window", "leg_scanner_window"),
            opening_tokens=("front_leg_scanner_window", "leg_scanner_window"),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A01.three_optical_windows",
            [*front_tof, *leg_scanner],
            minimum_count=3,
            note="requires two distinct front ToF windows and one distinct leg-scanner window",
        )
        checks.add(
            f"coverage.{state}.A01.window_semantics",
            len(front_tof) >= 2 and bool(leg_scanner),
            front_tof_matches=[part.name for part in front_tof],
            leg_scanner_matches=[part.name for part in leg_scanner],
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A01.tactile_edge",
            _proxy_parts(
                parts,
                state,
                "A01",
                name_tokens=("tactile_bumper", "pressure_bumper", "bumper_membrane"),
                opening_tokens=("tactile_bumper", "pressure_bumper", "bumper_membrane"),
            ),
        )

        # A02: repeated transducer faces must exist as separate final-surface
        # records.  Aggregate shell metadata is not allowed to satisfy counts.
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A02.ultrasonic_faces",
            _proxy_parts(
                parts,
                state,
                "A02",
                name_tokens=("side_ultrasonic_face_",),
                opening_tokens=("side_ultrasonic_face",),
            ),
            minimum_count=2,
            required_sides=("left", "right"),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A02.acoustic_faces",
            _proxy_parts(
                parts,
                state,
                "A02",
                name_tokens=("acoustic_mesh_", "acoustic_slot_"),
                opening_tokens=("voice_acoustic_slot", "microphone_acoustic_slot"),
            ),
            minimum_count=2,
            required_sides=("left", "right"),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A02.four_downview_windows",
            _proxy_parts(
                parts,
                state,
                "A02",
                name_tokens=("cliff_ir_window_", "downview_window_"),
                opening_tokens=("downward_cliff_ir_window", "downward_view_window"),
            ),
            minimum_count=4,
            required_sides=("left", "right"),
        )

        # A04: both side service islands plus caddy and recovery closeouts.
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A04.equipment_doors_bilateral",
            _proxy_parts(
                parts,
                state,
                "A04",
                name_tokens=("upper_equipment_door_", "equipment_bay_door_"),
                opening_tokens=("upper_equipment_door",),
            ),
            minimum_count=2,
            required_sides=("left", "right"),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A04.uwb_windows_bilateral",
            _proxy_parts(
                parts,
                state,
                "A04",
                name_tokens=("side_uwb_radome_", "side_uwb_window_"),
                opening_tokens=("side_uwb_rf_window",),
            ),
            minimum_count=2,
            required_sides=("left", "right"),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A04.equipment_release",
            _proxy_parts(
                parts,
                state,
                "A04",
                name_tokens=("equipment_release", "drawer_release"),
                opening_tokens=("drawer_release", "cots_latch", "equipment_release"),
            ),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A04.caddy_closeout",
            _proxy_parts(
                parts,
                state,
                "A04",
                name_tokens=("underseat_belly_closeout", "daily_caddy_flush_hatch", "caddy_closeout"),
                opening_tokens=("daily_caddy_access", "caddy_closeout"),
            ),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A04.recovery_interface",
            _proxy_parts(
                parts,
                state,
                "A04",
                name_tokens=("recovery_handle", "recovery_release"),
                opening_tokens=("manual_recovery_handle", "recovery_release"),
            ),
        )

        # A05: the left safety/HMI island is universal.  The right control pod
        # is also one conserved physical set: Ride uses its live forward pose,
        # The right-hand drive controls remain on one exposed forward armrest
        # station in every state; only traction authorisation changes.
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A05.emergency_stop",
            _proxy_parts(
                parts,
                state,
                "A05",
                name_tokens=("mechanical_emergency_stop", "emergency_stop"),
                opening_tokens=("emergency_stop", "e_stop", "estop"),
            ),
            required_sides=("left",),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A05.hmi",
            _proxy_parts(
                parts,
                state,
                "A05",
                name_tokens=("hmi_", "status_display_window"),
                opening_tokens=("left_hmi", "status_hmi", "display_hmi"),
            ),
            required_sides=("left",),
        )
        right_drive_controls = _proxy_parts(
            parts,
            state,
            "A05",
            name_tokens=(
                "right_removable_drive_pod",
                "right_control_pod",
                "right_joystick",
                "right_authorisation_key",
            ),
            opening_tokens=("drive_hmi", "control_pod", "drive_pod"),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A05.right_drive_control_conserved",
            right_drive_controls,
            minimum_count=3,
            required_sides=("right",),
        )
        expected_control_pose = "fixed_forward_armrest_top"
        checks.add(
            f"coverage.{state}.A05.right_drive_control_pose_is_physical",
            len(right_drive_controls) >= 3
            and all(
                part.metadata.get("same_physical_occurrence_all_states") is True
                and part.metadata.get("state_transition_never_deletes_occurrence")
                is True
                and part.metadata.get("state_pose") == expected_control_pose
                and part.metadata.get("drive_enabled_in_locked_state")
                is (state == "ride")
                and part.metadata.get("externally_visible_in_locked_state") is True
                and part.metadata.get("fixed_forward_armrest_location_all_states")
                is True
                for part in right_drive_controls
            ),
            detected=[part.name for part in right_drive_controls],
            expected_pose=expected_control_pose,
            actual_poses={
                part.name: part.metadata.get("state_pose")
                for part in right_drive_controls
            },
            requirement=(
                "The same right-hand pod, joystick and authorisation key must "
                "remain exposed at one fixed forward armrest datum in every "
                "state; table deployment may neither relocate nor hide them."
            ),
        )

        # A07: window and shutter are distinct final faces.  The lock-pin gate
        # intentionally prefers explicit functional_opening metadata so an
        # arbitrary shroud name or design-intent sentence cannot fake access.
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A07.sensor_window",
            _proxy_parts(
                parts,
                state,
                "A07",
                name_tokens=("sensor_beam_smoked_window", "mast_sensor_window"),
                opening_tokens=("mast_sensor_window", "sensor_beam_window"),
            ),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A07.privacy_shutter",
            _proxy_parts(
                parts,
                state,
                "A07",
                name_tokens=("physical_privacy_shutter", "privacy_shutter"),
                opening_tokens=("privacy_shutter", "physical_shutter"),
            ),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A07.lock_pin_access",
            _proxy_parts(
                parts,
                state,
                "A07",
                name_tokens=("lock_pin_access", "mast_lock_pin"),
                opening_tokens=(
                    "mast_lock_pin",
                    "mast_lock_pin_access",
                    "lock_pin_access",
                    "mast_lock_release",
                ),
                opening_token_fragments=(("lock", "pin"),),
            ),
            note="prefer functional_opening metadata until the upper-skin part name is frozen",
        )

        # A08 is one physical platform in mutually exclusive poses.  Its top,
        # replaceable tread and perimeter occur in every state; only Ride
        # exposes the moving deployed support/root surfaces.  The body-side
        # manual release and its finished shell remain fixed in every state.
        platform_top = _proxy_parts(
            parts,
            state,
            "A08",
            name_tokens=("footrest_top_skin",),
            opening_tokens=("footrest_top_skin",),
        )
        platform_tread = _proxy_parts(
            parts,
            state,
            "A08",
            name_tokens=("footrest_inset_tread", "footrest_tread"),
            opening_tokens=("footrest_tread",),
        )
        platform_perimeter = _proxy_parts(
            parts,
            state,
            "A08",
            name_tokens=("footrest_perimeter_skin",),
            opening_tokens=("footrest_perimeter",),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A08.invariant_platform_top",
            platform_top,
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A08.invariant_tread",
            platform_tread,
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A08.invariant_perimeter",
            platform_perimeter,
        )
        platform = [*platform_top, *platform_tread, *platform_perimeter]
        expected_pose = DEFAULT_FOOTREST_STATE[state]
        checks.add(
            f"coverage.{state}.A08.pose_contract_metadata",
            len(platform) == 3
            and all(part.metadata.get("footrest_pose") == expected_pose for part in platform)
            and all(
                part.metadata.get("footrest_contract_version")
                == FOOTREST_CONTRACT_VERSION
                for part in platform
            )
            and all(
                part.metadata.get("optional_footrest_open_available")
                is optional_footrest_open_available(state)
                for part in platform
            ),
            expected_pose=expected_pose,
            expected_contract=FOOTREST_CONTRACT_VERSION,
            parts=[part.name for part in platform],
        )

        root_and_supports = [
            part
            for part in _module_parts(parts, state, "A08")
            if part.name
            in {
                "A08_footrest_root_monocoque",
                "A08_footrest_support_monocoque_left",
                "A08_footrest_support_monocoque_right",
            }
        ]
        root_occurrences = [
            part
            for part in root_and_supports
            if part.name == "A08_footrest_root_monocoque"
        ]
        support_occurrences = [
            part for part in root_and_supports if "support_monocoque" in part.name
        ]
        body_side_release = [
            part
            for part in _module_parts(parts, state, "A08")
            if part.name == "A08_manual_release_paddle_shell"
        ]
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A08.body_side_manual_release",
            body_side_release,
        )
        checks.add(
            f"coverage.{state}.A08.body_side_manual_release_identity",
            len(body_side_release) == 1
            and body_side_release[0].metadata.get("physical_occurrence_id")
            == "E6-A08-MANUAL-RELEASE-PADDLE-SHELL"
            and body_side_release[0].metadata.get("body_side_fixed") is True
            and body_side_release[0].metadata.get("pose_invariant") is True,
            detected=[part.name for part in body_side_release],
            requirement=(
                "The finished no-power release paddle is one body-side, "
                "pose-invariant physical occurrence in every primary state."
            ),
        )
        expected_progress = 1.0 if default_footrest_is_deployed(state) else 0.0
        checks.add(
            f"coverage.{state}.A08.fixed_root_occurrence_conserved",
            len(root_occurrences) == 1
            and root_occurrences[0].metadata.get("body_side_fixed") is True
            and root_occurrences[0].metadata.get("pose_invariant") is True
            and root_occurrences[0].metadata.get("same_physical_occurrence_all_states")
            is True,
            detected=[part.name for part in root_occurrences],
            requirement=(
                "The fixed A08 root remains one pose-invariant BOM occurrence in "
                "every state; occurrence presence is not confused with exterior "
                "exposure."
            ),
        )
        checks.add(
            f"coverage.{state}.A08.moving_support_occurrences_conserved_at_endpoint",
            len(support_occurrences) == 2
            and sorted({_side(part) for part in support_occurrences})
            == ["left", "right"]
            and all(
                part.metadata.get("same_physical_occurrence_all_states") is True
                and part.metadata.get("body_side_fixed") is False
                and part.metadata.get("collision_allowlist_permitted") is False
                and abs(
                    float(part.metadata.get("a08_motion_progress", -1.0))
                    - expected_progress
                )
                <= 1.0e-9
                for part in support_occurrences
            ),
            detected=[part.name for part in support_occurrences],
            expected_progress=expected_progress,
            requirement=(
                "The same bilateral support shells remain on the product BOM and "
                "move to the state endpoint; stowed occurrences may be concealed "
                "but may not be deleted from the assembly."
            ),
        )

        # A10: final rear plane must expose deliberate service, status,
        # perception, RF and pressure-relief faces rather than source hardware.
        for feature, names, openings in (
            (
                "service_door",
                ("rear_flush_service_door", "rear_service_door"),
                ("rear_service_door",),
            ),
            (
                "status",
                ("rear_status_lens", "rear_status_window"),
                ("rear_status_light",),
            ),
            (
                "rear_tof",
                ("rear_tof_window",),
                ("rear_tof_window",),
            ),
            (
                "rear_uwb",
                ("rear_uwb_radome", "rear_uwb_window"),
                ("rear_uwb_rf_window",),
            ),
            (
                "pressure_vent",
                ("pressure_relief_vent", "pressure_vent"),
                ("battery_pressure_relief", "pressure_relief_vent"),
            ),
        ):
            _add_proxy_gate(
                checks,
                f"coverage.{state}.A10.{feature}",
                _proxy_parts(
                    parts,
                    state,
                    "A10",
                    name_tokens=names,
                    opening_tokens=openings,
                ),
            )

    # A09 appears only when a table leaf is deployed.  Café needs the right
    # interface; Focus needs independent positive-lock/release evidence on both
    # leaves.  Explicit functional_opening tokens take precedence over names.
    for state, required_sides in (("cafe", ("right",)), ("focus", ("left", "right"))):
        locks = _proxy_parts(
            parts,
            state,
            "A09",
            name_tokens=("table_positive_lock", "table_lock_pin", "desk_positive_lock"),
            opening_tokens=(
                "table_positive_lock",
                "table_lock_pin",
                "desk_positive_lock",
                "desk_lock_pin",
                "focus_centre_latch",
                "cafe_translation_lock",
                "cafe_rotation_lock_pin",
            ),
            opening_token_fragments=(
                ("positive", "lock"),
                ("lock", "pin"),
                ("centre", "latch"),
                ("translation", "lock"),
                ("rotation", "lock"),
            ),
        )
        releases = _proxy_parts(
            parts,
            state,
            "A09",
            name_tokens=("table_release_interface", "table_lock_release", "desk_release_interface"),
            opening_tokens=(
                "table_release_interface",
                "table_lock_release",
                "desk_release_interface",
                "table_manual_release",
                "cafe_lock_release",
                "focus_lock_release",
            ),
            opening_token_fragments=(("release",),),
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A09.positive_lock",
            locks,
            minimum_count=len(required_sides),
            required_sides=required_sides,
            note="prefer functional_opening metadata until the table-lock part name is frozen",
        )
        _add_proxy_gate(
            checks,
            f"coverage.{state}.A09.release_interface",
            releases,
            minimum_count=len(required_sides),
            required_sides=required_sides,
            note="prefer functional_opening metadata until the table-release part name is frozen",
        )


def _validate_feature_geometry(parts: Sequence[PartRecord], checks: Checks) -> None:
    for state in STATES:
        # The lower body must be a real covering volume, not a decorative badge.
        lower = _role_parts(parts, state, "lower_core")
        lower_box = _union_bounds(part.bounds for part in lower)
        checks.add(
            f"features.{state}.lower_core_cladding",
            lower_box is not None and lower_box.xlen >= 700.0 and lower_box.ylen >= 540.0 and lower_box.zlen >= 150.0,
            missing_evidence=lower_box is None,
            part_count=len(lower),
            combined_bounds=lower_box.to_dict() if lower_box else None,
            minimum_span_mm={"x": 700.0, "y": 540.0, "z": 150.0},
        )

        fairings = _role_parts(parts, state, "wheel_fairing")
        fairing_sides = sorted({_side(part) for part in fairings} & {"left", "right"})
        checks.add(
            f"features.{state}.rocker_wheel_fairings_bilateral",
            fairing_sides == ["left", "right"],
            missing_evidence=not fairings,
            detected_sides=fairing_sides,
            part_count=len(fairings),
        )

        armrests = [part for part in _role_parts(parts, state, "armrest") if part.bounds.xlen >= 250.0]
        for side in ("left", "right"):
            side_box = _union_bounds(part.bounds for part in armrests if _side(part) == side)
            checks.add(
                f"features.{state}.armrest_{side}_long_shell",
                side_box is not None
                and side_box.xlen >= 450.0
                and _check_range(abs(side_box.center[1]), 275.0, 380.0)
                and _check_range(side_box.zmax, 650.0, 705.0),
                missing_evidence=side_box is None,
                combined_bounds=side_box.to_dict() if side_box else None,
                target="two long armrests spanning roughly X=-380..+140 with top near Z=680",
            )

        backrests = [
            part
            for part in parts
            if state in part.states
            and part.name
            in {
                "A06_backrest_weather_shell",
                "A06_backrest_contact_panel",
            }
        ]
        back_box = _union_bounds(part.bounds for part in backrests)
        if state == "follow":
            back_ok = (
                len(backrests) == 2
                and back_box is not None
                and back_box.ylen >= 520.0
                and back_box.zmax <= 705.0
            )
        else:
            back_ok = (
                len(backrests) == 2
                and back_box is not None
                and _check_range(back_box.ylen, 520.0, 660.0)
                and back_box.zmax >= 990.0
            )
        checks.add(
            f"features.{state}.backrest_physical_item",
            back_ok,
            missing_evidence=back_box is None,
            part_count=len(backrests),
            combined_bounds=back_box.to_dict() if back_box else None,
        )

        mast = _role_parts(parts, state, "mast")
        mast_box = _union_bounds(part.bounds for part in mast)
        beam = next(
            (
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A07"
                and part.name == "A07_sensor_beam_shell"
            ),
            None,
        )
        beam_axis_x = (
            beam.metadata.get("controlled_axis_x_mm")
            if beam is not None
            else None
        )
        if state == "follow":
            # Follow is the folded A06/A07 object.  It is neither the Ride/Cafe
            # low pose nor a fabricated service-core substitute.  The exact
            # shared-hinge transform and A06 weather coverage are proved later
            # with the resolved B-Reps; this inexpensive gate binds the complete
            # folded package to its released broad envelope and rejects an
            # upright, truncated or fabricated low service-core substitute.
            mast_ok = (
                mast_box is not None
                and mast_box.xmin
                >= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["xmin_min"]
                and mast_box.xmax
                <= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["xmax_max"]
                and mast_box.ymin
                >= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["ymin_min"]
                and mast_box.ymax
                <= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["ymax_max"]
                and mast_box.zmin
                >= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["zmin_min"]
                and mast_box.zmax
                <= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["zmax_max"]
                and mast_box.xlen
                >= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["xspan_min"]
                and mast_box.ylen
                >= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["yspan_min"]
                and mast_box.zlen
                >= A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM["zspan_min"]
            )
            mast_center_ok = beam is not None
        elif state in {"ride", "cafe"}:
            mast_ok = (
                mast_box is not None
                and beam is not None
                and _check_range(beam.bounds.center[2], 1039.95, 1040.05)
                and _check_range(beam.bounds.zmin, 1007.8, 1008.2)
                and _check_range(beam.bounds.zmax, 1071.8, 1072.2)
                and _check_range(
                    beam.bounds.ylen,
                    A07_TERMINAL_NOMINAL_WIDTH_Y_MM - 2.0,
                    A07_TERMINAL_NOMINAL_WIDTH_Y_MM + 0.5,
                )
            )
            mast_center_ok = (
                beam is not None
                and isinstance(beam_axis_x, (int, float))
                and abs(float(beam_axis_x) - A07_MAST_AXIS_X_MM) <= 0.05
            )
        else:
            mast_ok = (
                mast_box is not None
                and beam is not None
                and _check_range(beam.bounds.center[2], 1459.95, 1460.05)
                and _check_range(beam.bounds.zmin, 1427.8, 1428.2)
                and _check_range(beam.bounds.zmax, 1491.8, 1492.2)
                and _check_range(
                    beam.bounds.ylen,
                    A07_TERMINAL_NOMINAL_WIDTH_Y_MM - 2.0,
                    A07_TERMINAL_NOMINAL_WIDTH_Y_MM + 0.5,
                )
            )
            mast_center_ok = (
                beam is not None
                and isinstance(beam_axis_x, (int, float))
                and abs(float(beam_axis_x) - A07_MAST_AXIS_X_MM) <= 0.05
            )
        checks.add(
            f"features.{state}.mast_state_position",
            mast_ok and mast_center_ok,
            missing_evidence=mast_box is None,
            part_count=len(mast),
            combined_bounds=mast_box.to_dict() if mast_box else None,
            sensor_beam_bounds=beam.bounds.to_dict() if beam else None,
            follow_folded_broad_envelope_contract=(
                A07_FOLLOW_FOLDED_MAST_ENVELOPE_MM
                if state == "follow"
                else None
            ),
            target=(
                "Follow uses the A06/A07 shared fold; Ride/Cafe expose the same "
                "low beam on X=310 at Z=1040; Focus keeps the fixed sleeve in "
                "place and translates only the moving sleeve/beam +420 mm"
            ),
        )

        platform = [
            part
            for part in _module_parts(parts, state, "A08")
            if part.name
            in {
                "A08_footrest_top_skin",
                "A08_footrest_inset_tread",
                "A08_footrest_perimeter_skin",
            }
        ]
        foot_box = _union_bounds(part.bounds for part in platform)
        if default_footrest_is_deployed(state):
            foot_ok = (
                foot_box is not None
                and _check_range(foot_box.center[0], -620.0, -590.0)
                and _check_range(foot_box.xlen, 205.0, 215.0)
                and _check_range(foot_box.ylen, 495.0, 505.0)
                and _check_range(foot_box.zmax, 105.0, 115.0)
            )
            check_name = f"features.{state}.footrest_deployed_locked_one"
            target = {"size_mm": [210.0, 500.0, 10.0], "center_x_mm": -605.0, "pose": "deployed_locked"}
        else:
            foot_ok = (
                foot_box is not None
                and _check_range(foot_box.center[0], -375.0, -345.0)
                and _check_range(foot_box.xlen, 205.0, 215.0)
                and _check_range(foot_box.ylen, 495.0, 505.0)
                and _check_range(foot_box.zmax, 155.0, 165.0)
            )
            check_name = f"features.{state}.footrest_stowed_one"
            target = {"size_mm": [210.0, 500.0, 10.0], "center_x_mm": -360.0, "pose": "stowed"}
        checks.add(
            check_name,
            foot_ok and len(platform) == 3,
            missing_evidence=foot_box is None,
            surface_occurrence_count=len(platform),
            combined_bounds=foot_box.to_dict() if foot_box else None,
            target=target,
        )

        supports = [
            part
            for part in _module_parts(parts, state, "A08")
            if "footrest_support_monocoque_" in part.name
        ]
        support_sides = sorted({_side(part) for part in supports} & {"left", "right"})
        expected_progress = 1.0 if default_footrest_is_deployed(state) else 0.0
        checks.add(
            f"features.{state}.footrest_support_endpoint_contract",
            support_sides == ["left", "right"]
            and len(supports) == 2
            and all(
                abs(
                    float(part.metadata.get("a08_motion_progress", -1.0))
                    - expected_progress
                )
                <= 1.0e-9
                and part.metadata.get("collision_allowlist_permitted") is False
                for part in supports
            ),
            expected="bilateral_conserved_occurrences_at_state_endpoint",
            expected_progress=expected_progress,
            detected_sides=support_sides,
            part_count=len(supports),
        )

    def named(state: str, name: str) -> PartRecord | None:
        matches = [
            part
            for part in parts
            if state in part.states and part.module.upper() == "A07" and part.name == name
        ]
        return matches[0] if len(matches) == 1 else None

    ride_beam = named("ride", "A07_sensor_beam_shell")
    cafe_beam = named("cafe", "A07_sensor_beam_shell")
    focus_beam = named("focus", "A07_sensor_beam_shell")
    checks.add(
        "features.a07.ride_cafe_low_beam_same_pose_bounds",
        ride_beam is not None
        and cafe_beam is not None
        and _bounds_pose_delta(ride_beam.bounds, cafe_beam.bounds) <= 0.01,
        missing_evidence=ride_beam is None or cafe_beam is None,
        maximum_bound_delta_mm=(
            round(_bounds_pose_delta(ride_beam.bounds, cafe_beam.bounds), 6)
            if ride_beam is not None and cafe_beam is not None
            else None
        ),
        requirement="Ride and Cafe use one identical, externally readable low A07 beam pose.",
    )

    ride_fixed = named("ride", "A07_mast_fixed_outer_sleeve")
    cafe_fixed = named("cafe", "A07_mast_fixed_outer_sleeve")
    focus_fixed = named("focus", "A07_mast_fixed_outer_sleeve")
    fixed_members = [part for part in (ride_fixed, cafe_fixed, focus_fixed) if part is not None]
    fixed_delta = (
        max(
            _bounds_pose_delta(ride_fixed.bounds, candidate.bounds)
            for candidate in (cafe_fixed, focus_fixed)
            if candidate is not None
        )
        if ride_fixed is not None and len(fixed_members) == 3
        else None
    )
    checks.add(
        "features.a07.ride_cafe_focus_fixed_outer_same_pose_bounds",
        fixed_delta is not None and fixed_delta <= 0.01,
        missing_evidence=fixed_delta is None,
        maximum_bound_delta_mm=round(fixed_delta, 6) if fixed_delta is not None else None,
        requirement="Focus may not translate or rebase the A07 fixed outer sleeve.",
    )

    ride_moving = named("ride", "A07_mast_moving_inner_sleeve")
    focus_moving = named("focus", "A07_mast_moving_inner_sleeve")
    moving_delta = (
        _bounds_pose_delta(
            ride_moving.bounds,
            focus_moving.bounds,
            (0.0, 0.0, -A07_FOCUS_TRANSLATION_MM),
        )
        if ride_moving is not None and focus_moving is not None
        else None
    )
    beam_delta = (
        _bounds_pose_delta(
            ride_beam.bounds,
            focus_beam.bounds,
            (0.0, 0.0, -A07_FOCUS_TRANSLATION_MM),
        )
        if ride_beam is not None and focus_beam is not None
        else None
    )
    checks.add(
        "features.a07.focus_moving_inner_and_beam_bounds_plus_420_only",
        moving_delta is not None
        and beam_delta is not None
        and moving_delta <= 0.01
        and beam_delta <= 0.01,
        missing_evidence=moving_delta is None or beam_delta is None,
        moving_inner_maximum_bound_delta_mm=(
            round(moving_delta, 6) if moving_delta is not None else None
        ),
        sensor_beam_maximum_bound_delta_mm=(
            round(beam_delta, 6) if beam_delta is not None else None
        ),
        declared_translation_mm=(0.0, 0.0, A07_FOCUS_TRANSLATION_MM),
    )

    # Deployed table leaves are identified geometrically at the controlled
    # 705 mm surface, which avoids counting the two stored physical bundles.
    focus_tables = [
        part for part in _role_parts(parts, "focus", "table") if part.bounds.zmin <= 710.0 and part.bounds.zmax >= 695.0
    ]
    focus_by_side = {side: [part for part in focus_tables if _side(part) == side] for side in ("left", "right")}
    focus_boxes = {side: _union_bounds(part.bounds for part in members) for side, members in focus_by_side.items()}
    tables_ok = all(
        box is not None and _check_range(box.xlen, 400.0, 455.0) and _check_range(box.ylen, 250.0, 290.0)
        for box in focus_boxes.values()
    )
    checks.add(
        "features.focus.two_table_leaves",
        tables_ok,
        missing_evidence=not focus_tables,
        detected_sides=[side for side, box in focus_boxes.items() if box],
        bounds={side: box.to_dict() if box else None for side, box in focus_boxes.items()},
        target_each_mm=[430.0, 270.0, 12.0],
    )
    if all(focus_boxes.values()):
        left, right = focus_boxes["left"], focus_boxes["right"]
        assert left is not None and right is not None
        gap = right.ymin - left.ymax
        checks.add(
            "features.focus.table_centre_gap",
            _check_range(gap, 10.0, 14.0),
            actual_mm=round(gap, 3),
            target_mm=12.0,
            allowed_mm=[10.0, 14.0],
        )

    cafe_tables = [
        part for part in _role_parts(parts, "cafe", "table") if part.bounds.zmin <= 710.0 and part.bounds.zmax >= 695.0
    ]
    cafe_box = _union_bounds(part.bounds for part in cafe_tables)
    cafe_ok = (
        cafe_box is not None
        and _check_range(cafe_box.center[0], -390.0, -310.0)
        and _check_range(cafe_box.xlen, 250.0, 290.0)
        and _check_range(cafe_box.ylen, 400.0, 455.0)
        and cafe_box.center[1] > 50.0
    )
    checks.add(
        "features.cafe.right_table_only_left_open",
        cafe_ok,
        missing_evidence=cafe_box is None,
        detected_part_count=len(cafe_tables),
        combined_bounds=cafe_box.to_dict() if cafe_box else None,
        target="one physical right leaf, rotated 90 deg, centre X~350 and left side open",
    )

    for state, expected_sides in (("cafe", {"right"}), ("focus", {"left", "right"})):
        trays = _role_parts(parts, state, "table_undertray")
        tray_sides = {_side(part) for part in trays} & {"left", "right"}
        checks.add(
            f"features.{state}.table_mechanism_cladding",
            expected_sides.issubset(tray_sides),
            missing_evidence=not trays,
            required_sides=sorted(expected_sides),
            detected_sides=sorted(tray_sides),
        )

        top_skins = [
            part
            for part in parts
            if state in part.states
            and part.module.upper() == "A09"
            and "table_top_skin" in part.search_text
        ]
        top_skin_sides = {_side(part) for part in top_skins} & {"left", "right"}
        checks.add(
            f"features.{state}.final_table_top_skins",
            top_skin_sides == expected_sides,
            missing_evidence=not top_skins,
            required_sides=sorted(expected_sides),
            detected_sides=sorted(top_skin_sides),
            part_count=len(top_skins),
            note="controlled prototype desk_panel geometry must not be the final presentation surface",
        )

        # The exposed 72/60/48 mm prototype lift posts are retired.  The final
        # layout gate below checks real A05 cassettes, internal roots/guides and
        # the single honest table-attached root neck instead of resurrecting
        # those obsolete dimensions.

        retired_prefixes = (
            "A09_cafe_armrest_to_table_root_bridge_",
            "A09_cafe_root_mechanism_fairing_",
            "A09_cafe_underleaf_saddle_",
            "A09_focus_armrest_to_table_root_bridge_",
            "A09_focus_root_fairing_",
            "A09_focus_underleaf_saddle_",
            "A09_table_lift_moving_stage_",
        )
        retired = sorted(
            part.name
            for part in parts
            if state in part.states and part.name.startswith(retired_prefixes)
        )
        bridge_detail: dict[str, Any] = {
            "retired_fragment_inventory": retired
        }
        if state == "cafe":
            required_root_names = {
                "A09_cafe_fixed_root_housing_right",
                "A09_cafe_fixed_yoke_bearing_carrier_right",
                "A09_cafe_rotary_hub_right",
                "A09_cafe_rotary_linear_rail_right",
                "A09_cafe_underleaf_motion_belly_right",
            }
            root_parts = {
                part.name: part
                for part in parts
                if state in part.states and part.name in required_root_names
            }
            neck = root_parts.get("A09_cafe_underleaf_motion_belly_right")
            cassette = next(
                (
                    part
                    for part in parts
                    if state in part.states
                    and part.name
                    == "A05_table_root_structural_cassette_right"
                ),
                None,
            )
            continuous = (
                not retired
                and set(root_parts) == required_root_names
                and cassette is not None
                and cassette.metadata.get("primary_table_load_path") is True
                and neck is not None
                and neck.metadata.get("final_exterior_visible") is True
                and neck.metadata.get("root_neck_outside_armrest") is True
                and neck.metadata.get("hinge_bearing_and_lock_outside_armrest")
                is False
                and float(neck.metadata.get("internal_spreader_length_mm", 0.0))
                == 220.0
                and all(
                    part.metadata.get("layout_kinematic_envelope_only") is True
                    for part in root_parts.values()
                )
            )
            detected_sides = {"right"} if set(root_parts) == required_root_names else set()
            missing_evidence = set(root_parts) != required_root_names or cassette is None
            bridge_detail["right"] = {
                "pass": continuous,
                "root_inventory": sorted(root_parts),
                "structural_cassette": cassette.name if cassette else None,
                "root_neck": neck.name if neck else None,
                "internal_spreader_length_mm": (
                    neck.metadata.get("internal_spreader_length_mm") if neck else None
                ),
            }
        else:
            mechanisms = {
                side: {
                    role: next(
                        (
                            part
                            for part in parts
                            if state in part.states and part.name == name
                        ),
                        None,
                    )
                    for role, name in {
                        "cassette": f"A05_table_root_structural_cassette_{side}",
                        "root_box": f"A09_focus_internal_root_box_{side}",
                        "stage_1": f"A09_focus_internal_nested_guide_stage_1_{side}",
                        "stage_2": f"A09_focus_internal_nested_guide_stage_2_{side}",
                        "stage_3": f"A09_focus_internal_nested_guide_stage_3_{side}",
                        "neck": f"A09_focus_table_hidden_root_tongue_{side}",
                    }.items()
                }
                for side in expected_sides
            }
            continuous = not retired
            for side in expected_sides:
                inventory = mechanisms[side]
                cassette = inventory["cassette"]
                root_box = inventory["root_box"]
                stages = tuple(inventory[f"stage_{index}"] for index in (1, 2, 3))
                neck = inventory["neck"]
                side_pass = (
                    all(part is not None for part in inventory.values())
                    and cassette is not None
                    and cassette.metadata.get("primary_table_load_path") is True
                    and root_box is not None
                    and root_box.metadata.get("final_exterior_visible") is False
                    and all(
                        stage is not None
                        and stage.metadata.get("final_exterior_visible") is False
                        and float(stage.metadata.get("mechanism_z_max_mm", 9999.0))
                        <= 674.0
                        for stage in stages
                    )
                    and neck is not None
                    and neck.metadata.get("final_exterior_visible") is True
                    and neck.metadata.get("root_neck_outside_armrest") is True
                    and neck.metadata.get("hinge_bearing_and_lock_outside_armrest")
                    is False
                    and float(neck.metadata.get("internal_spreader_length_mm", 0.0))
                    == 220.0
                )
                continuous = continuous and side_pass
                bridge_detail[side] = {
                    "pass": side_pass,
                    "inventory": sorted(
                        part.name for part in inventory.values() if part is not None
                    ),
                    "internal_spreader_length_mm": (
                        neck.metadata.get("internal_spreader_length_mm")
                        if neck is not None
                        else None
                    ),
                }
            detected_sides = {
                side
                for side in expected_sides
                if all(part is not None for part in mechanisms[side].values())
            }
            missing_evidence = any(
                any(part is None for part in mechanisms[side].values())
                for side in expected_sides
            )
        checks.add(
            f"features.{state}.armrest_table_root_visual_continuity",
            continuous,
            missing_evidence=missing_evidence,
            required_sides=sorted(expected_sides),
            detected_sides=sorted(detected_sides),
            details=bridge_detail,
        )

    legacy_side_table_tokens = (
        "table_cassette_door",
        "table_cassette_exit_bezel",
        "table_cassette_throat_seal",
        "table_cassette_shadow_horizon",
    )
    for state in STATES:
        legacy = [
            part.name
            for part in parts
            if state in part.states
            and part.module.upper() == "A05"
            and any(token in part.search_text for token in legacy_side_table_tokens)
        ]
        for side in ("left", "right"):
            lids = [
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A05"
                and "armrest_touch_lid" in part.search_text
                and _side(part) == side
            ]
            hinges = [
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A05"
                and "armrest_top_lid_hinge_reveal" in part.search_text
                and _side(part) == side
            ]
            releases = [
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A05"
                and "armrest_top_lid_release" in part.search_text
                and _side(part) == side
            ]
            lid_contract = (
                not legacy
                and len(lids) == 1
                and len(hinges) == 1
                and len(releases) == 1
                and lids[0].metadata.get("top_lid_outward_opening_enabled") is True
                and lids[0].metadata.get("full_armrest_side_opening_enabled") is False
                and float(lids[0].metadata.get("top_lid_open_angle_deg", 0.0))
                == 105.0
                and lids[0].metadata.get("final_state_pose")
                == "closed_and_double_latched"
                and releases[0].metadata.get("manual_no_power") is True
                and releases[0].metadata.get("two_action") is True
            )
            checks.add(
                f"features.{state}.armrest_top_table_access.{side}",
                lid_contract,
                missing_evidence=not lids or not hinges or not releases,
                legacy_side_table_parts=legacy,
                lid_parts=[part.name for part in lids],
                hinge_parts=[part.name for part in hinges],
                release_parts=[part.name for part in releases],
                target=(
                    "fixed armrest body; outer-long-edge top lid opens 105 degrees, "
                    "table exits upward, lid closes and double-locks before unfolding"
                ),
            )

            drains = [
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A05"
                and "table_cassette_lowpoint_drain" in part.search_text
                and _side(part) == side
            ]
            drain_contract = len(drains) == 1 and all(
                bool(part.metadata.get("gravity_drain"))
                and bool(part.metadata.get("cleaning_probe_access"))
                and tuple(part.metadata.get("through_opening_mm", ())) == (20.0, 6.0)
                and part.metadata.get("legacy_side_table_exit") is False
                for part in drains
            )
            checks.add(
                f"features.{state}.table_bay_lowpoint_drain.{side}",
                drain_contract,
                missing_evidence=not drains,
                drain_parts=[part.name for part in drains],
                target=(
                    "one real 20 x 6 mm gravity drain with cleaning-probe access; "
                    "never a table deployment opening"
                ),
            )

    focus_seals = [
        part
        for part in parts
        if "focus" in part.states
        and part.module.upper() == "A09"
        and "focus_centre_seam_seal" in part.search_text
    ]
    seal_by_side = {side: next((part for part in focus_seals if _side(part) == side), None) for side in ("left", "right")}
    seam_gap = None
    if seal_by_side["left"] is not None and seal_by_side["right"] is not None:
        seam_gap = seal_by_side["right"].bounds.ymin - seal_by_side["left"].bounds.ymax
    checks.add(
        "features.focus.controlled_centre_seam_seals",
        seam_gap is not None and _check_range(seam_gap, 10.0, 14.0),
        missing_evidence=seam_gap is None,
        actual_gap_mm=round(seam_gap, 3) if seam_gap is not None else None,
        target_gap_mm=12.0,
        detected_sides=sorted({_side(part) for part in focus_seals} & {"left", "right"}),
    )

    focus_paddles = [
        part
        for part in parts
        if "focus" in part.states
        and part.module.upper() == "A09"
        and "focus_lock_release_paddle" in part.search_text
    ]
    paddles_by_side = {side: [part for part in focus_paddles if _side(part) == side] for side in ("left", "right")}
    paddles_clear = (
        len(paddles_by_side["left"]) == 2
        and len(paddles_by_side["right"]) == 2
        and all(part.bounds.ymax <= -6.0 + 1e-6 for part in paddles_by_side["left"])
        and all(part.bounds.ymin >= 6.0 - 1e-6 for part in paddles_by_side["right"])
    )
    checks.add(
        "features.focus.leaf_local_lock_release_paddles",
        paddles_clear,
        missing_evidence=not focus_paddles,
        detected_counts={side: len(values) for side, values in paddles_by_side.items()},
        target="two independently operable paddles per leaf, none bridging the 12 mm centre seam",
    )

    for state in STATES:
        shrouds = _role_parts(parts, state, "mast_shroud")
        checks.add(
            f"features.{state}.mast_mechanism_shrouded",
            bool(shrouds),
            missing_evidence=not shrouds,
            part_count=len(shrouds),
        )


OPENING_REQUIREMENTS = {
    "follow.front_navigation_sensor": ("front_tof", "tof_window", "front_sensor", "leg_scanner", "navigation_horizon"),
    "follow.side_navigation_sensor": ("side_ultrasonic", "side_sensor", "ultrasonic_face"),
    "follow.cliff_sensor": ("cliff", "downward_sensor", "down_view"),
    "follow.tactile_bumper": ("tactile_bumper", "touch_bumper", "bumper_membrane"),
    "follow.acoustic_or_rf_aperture": ("acoustic", "microphone", "uwb", "rf_window", "radome"),
    "ride.emergency_stop": ("emergency_stop", "e_stop", "estop"),
    "ride.drive_hmi": ("drive_hmi", "joystick", "control_pod", "drive_pod", "authorization_key", "authorisation_key"),
    "focus.privacy_shutter": ("privacy_shutter", "physical_shutter"),
    "focus.mast_sensor_window": ("mast_sensor_window", "smoked_sensor_window", "sensor_beam_window"),
    "all.rear_service_door": ("rear_service_door", "service_rear", "service_door", "service_surround"),
    "all.recovery_release": ("brake_release", "battery_disconnect", "recovery_release", "manual_release"),
    "all.charge_port": ("charge_port", "charging_port"),
    "all.drainage": ("drain", "drainage", "water_exit"),
}


def _opening_matches(opening: OpeningRecord, words: Sequence[str]) -> bool:
    text = opening.search_text
    return any(word in text for word in words)


def _validate_openings(openings: Sequence[OpeningRecord], checks: Checks) -> None:
    for requirement, words in OPENING_REQUIREMENTS.items():
        state, name = requirement.split(".", 1)
        candidates = [
            opening
            for opening in openings
            if _opening_matches(opening, words) and (state == "all" or state in opening.states)
        ]
        checks.add(
            f"openings.{requirement}",
            bool(candidates),
            missing_evidence=not candidates,
            matches=[candidate.name for candidate in candidates],
            accepted_tokens=list(words),
        )

    dedicated_emergency = [
        opening
        for opening in openings
        if "ride" in opening.states
        and opening.bounds
        and (
            opening.name == "A05_left_mechanical_emergency_stop"
            or opening.metadata.get("physical_occurrence_id")
            == "WC-HMI-MECHANICAL-E-STOP-LEFT"
        )
    ]
    emergency = dedicated_emergency[0] if len(dedicated_emergency) == 1 else None
    if emergency and emergency.bounds:
        x, y, z = emergency.bounds.center
        checks.add(
            "openings.ride.emergency_stop_position",
            _check_range(x, -354.0, -234.0) and _check_range(y, -370.0, -270.0) and _check_range(z, 510.0, 670.0),
            actual_center_mm=[round(x, 3), round(y, 3), round(z, 3)],
            target_center_mm=[-294.0, -320.0, 590.0],
            note="left inner-front armrest; it may not migrate to the nose, right side or screen",
            dedicated_occurrence=emergency.name,
        )
    else:
        checks.add(
            "openings.ride.emergency_stop_position",
            False,
            missing_evidence=not dedicated_emergency,
            dedicated_matches=[opening.name for opening in dedicated_emergency],
        )

    service = next(
        (opening for opening in openings if _opening_matches(opening, OPENING_REQUIREMENTS["all.rear_service_door"]) and opening.bounds),
        None,
    )
    if service and service.bounds:
        checks.add(
            "openings.all.rear_service_door_position",
            service.bounds.center[0] > 180.0,
            actual_center_x_mm=round(service.bounds.center[0], 3),
            minimum_center_x_mm=180.0,
        )
    else:
        checks.add("openings.all.rear_service_door_position", False, missing_evidence=True)

    # Select the physical shutter itself, not another optical part whose
    # clearance metadata happens to mention ``physical_shutter``.  Focus must
    # preserve the controlled occurrence at its released parked pose; changing
    # the mast styling does not authorise a new shutter datum.
    shutter = next(
        (
            opening
            for opening in openings
            if opening.bounds
            and "focus" in opening.states
            and (
                "physical_privacy_shutter"
                in opening.name.lower().replace("-", "_")
                or opening.metadata.get("physical_occurrence_id")
                == "WC-MAST-PHYSICAL-PRIVACY-SHUTTER"
                or any(
                    token
                    in _normalised_tokens(
                        opening.metadata.get(key)
                    )
                    for key in ("functional_opening", "opening_id")
                    for token in ("privacy_shutter", "physical_shutter")
                )
            )
        ),
        None,
    )
    if shutter and shutter.bounds:
        x, y, z = shutter.bounds.center
        target_x, target_y, target_z = A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM
        checks.add(
            "openings.focus.privacy_shutter_on_sensor_beam",
            abs(x - target_x) <= 0.05
            and abs(y - target_y) <= 0.05
            and abs(z - target_z) <= 0.05,
            actual_center_mm=[round(x, 3), round(y, 3), round(z, 3)],
            target={
                "center_mm": [target_x, target_y, target_z],
                "basis": (
                    "controlled mast_privacy_shutter_parked_focus STEP occurrence; "
                    "the A07 mast axis remains X=310 mm"
                ),
            },
        )
    else:
        checks.add("openings.focus.privacy_shutter_on_sensor_beam", False, missing_evidence=True)


def _clearance_exempt(record: PartRecord, family: str) -> bool:
    value = record.metadata.get("clearance_exempt")
    if value is True:
        return True
    text = (str(value) + " " + str(record.metadata.get("moves_with", ""))).lower()
    if family == "tyre" and any(word in text for word in ("tyre", "wheel", "hub")):
        return True
    if family == "tyre" and any(word in record.search_text for word in ("wheel_end_service_cap", "hub_cap")):
        return True
    if family == "rocker" and "rocker" in text:
        return True
    if family == "rocker" and "rocker_pivot_service_cap" in record.search_text:
        return True
    if family == "mast" and any(word in text for word in ("mast_inner", "sensor_beam", "moving_mast")):
        return True
    return False


def _distance(shape_a: Any, shape_b: Any) -> float:
    if hasattr(shape_a, "val"):
        shape_a = shape_a.val()
    if hasattr(shape_b, "val"):
        shape_b = shape_b.val()
    return float(shape_a.distance(shape_b))


def _intersection_volume(shape_a: Any, shape_b: Any) -> float:
    """Return OCC overlap volume for two resolved solids."""

    if hasattr(shape_a, "val"):
        shape_a = shape_a.val()
    if hasattr(shape_b, "val"):
        shape_b = shape_b.val()
    common = shape_a.intersect(shape_b)
    return 0.0 if common.isNull() else float(common.Volume())


def _brep_pose_evidence(reference: Any, candidate: Any) -> dict[str, Any]:
    """Compare two already pose-normalised B-Reps, not their metadata."""

    if hasattr(reference, "val"):
        reference = reference.val()
    if hasattr(candidate, "val"):
        candidate = candidate.val()
    reference_box = _bounds_from_shape(reference)
    candidate_box = _bounds_from_shape(candidate)
    symmetric_difference = float(
        reference.cut(candidate).Volume() + candidate.cut(reference).Volume()
    )
    return {
        "symmetric_difference_mm3": symmetric_difference,
        "volume_delta_mm3": abs(float(reference.Volume()) - float(candidate.Volume())),
        "area_delta_mm2": abs(float(reference.Area()) - float(candidate.Area())),
        "maximum_bound_delta_mm": _bounds_pose_delta(reference_box, candidate_box),
        "face_count_equal": len(reference.Faces()) == len(candidate.Faces()),
        "edge_count_equal": len(reference.Edges()) == len(candidate.Edges()),
        "reference_bounds": reference_box.to_dict(),
        "candidate_bounds": candidate_box.to_dict(),
    }


def _brep_pose_matches(evidence: Mapping[str, Any], tolerance_mm3: float = 0.05) -> bool:
    return (
        float(evidence["symmetric_difference_mm3"]) <= tolerance_mm3
        and float(evidence["volume_delta_mm3"]) <= tolerance_mm3
        and float(evidence["area_delta_mm2"]) <= 0.05
        and float(evidence["maximum_bound_delta_mm"]) <= 0.01
        and bool(evidence["face_count_equal"])
        and bool(evidence["edge_count_equal"])
    )


def _rotate_about_a06_a07_hinge(shape: Any, degrees: float) -> Any:
    x, y, z = A06_A07_COMMON_FOLD_HINGE_MM
    return shape.rotate((x, y, z), (x, y + 1.0, z), degrees)


def _validate_a07_brep_contract(
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any,
) -> None:
    """Prove the frozen A06/A07 state contract from resolved solid geometry."""

    by_state: dict[str, dict[str, PartRecord]] = {}
    for state in STATES:
        state_parts = [part for part in parts if state in part.states]
        by_state[state] = {
            part.name: part
            for part in state_parts
            if part.shape is not None and part.module.upper() in {"A06", "A07"}
        }

    def get(state: str, name: str) -> PartRecord | None:
        return by_state[state].get(name)

    # Ride and Cafe are one low A07 pose, including the closed shutter and all
    # service inserts.  Matching names and bounds are insufficient: every
    # corresponding occurrence is compared at its actual world transform.
    ride_names = {
        name for name, part in by_state["ride"].items() if part.module.upper() == "A07"
    }
    cafe_names = {
        name for name, part in by_state["cafe"].items() if part.module.upper() == "A07"
    }
    ride_cafe_evidence: dict[str, Any] = {}
    ride_cafe_pass = bool(ride_names) and ride_names == cafe_names
    for name in sorted(ride_names & cafe_names):
        evidence = _brep_pose_evidence(
            by_state["ride"][name].shape,
            by_state["cafe"][name].shape,
        )
        ride_cafe_evidence[name] = evidence
        ride_cafe_pass = ride_cafe_pass and _brep_pose_matches(evidence)
    checks.add(
        "a07.brep.ride_cafe_complete_low_pose_identity",
        ride_cafe_pass,
        missing_evidence=not ride_names or not cafe_names,
        ride_inventory=sorted(ride_names),
        cafe_inventory=sorted(cafe_names),
        comparisons=ride_cafe_evidence,
        requirement="Ride and Cafe must contain the same A07 B-Reps at the same low world pose.",
    )

    focus_names = {
        name for name, part in by_state["focus"].items() if part.module.upper() == "A07"
    }
    checks.add(
        "a07.brep.focus_same_physical_inventory_as_low",
        bool(ride_names) and focus_names == ride_names,
        missing_evidence=not ride_names or not focus_names,
        ride_inventory=sorted(ride_names),
        focus_inventory=sorted(focus_names),
        focus_only_occurrences=sorted(focus_names - ride_names),
        missing_in_focus=sorted(ride_names - focus_names),
        requirement=(
            "Focus changes A07 poses and the shutter park, not the physical occurrence inventory."
        ),
    )

    ride_fixed = get("ride", "A07_mast_fixed_outer_sleeve")
    focus_fixed = get("focus", "A07_mast_fixed_outer_sleeve")
    fixed_evidence = (
        _brep_pose_evidence(ride_fixed.shape, focus_fixed.shape)
        if ride_fixed is not None and focus_fixed is not None
        else None
    )
    checks.add(
        "a07.brep.focus_fixed_outer_pose_invariant",
        fixed_evidence is not None and _brep_pose_matches(fixed_evidence),
        missing_evidence=fixed_evidence is None,
        comparison=fixed_evidence,
        permitted_translation_mm=(0.0, 0.0, 0.0),
        mast_axis_x_mm=A07_MAST_AXIS_X_MM,
    )

    # The finished spine is not allowed to rely on the old flush terminal
    # face.  Its hidden tenon enters a real socket with a measurable radial
    # air gap, while Focus still retains the full 150 mm fixed-sleeve capture.
    interface_evidence: dict[str, Any] = {}
    interface_pass = True

    def numeric_pair(value: object) -> tuple[float, float] | None:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(item, (int, float)) for item in value)
        ):
            return (float(value[0]), float(value[1]))
        return None

    for state in STATES:
        state_moving_names = sorted(
            name
            for name, part in by_state[state].items()
            if part.module.upper() == "A07"
            and name.startswith("A07_mast_moving_inner_sleeve")
        )
        fixed = get(state, "A07_mast_fixed_outer_sleeve")
        moving = get(state, "A07_mast_moving_inner_sleeve")
        terminal = get(state, "A07_sensor_beam_shell")
        if fixed is None or moving is None or terminal is None:
            interface_pass = False
            interface_evidence[state] = {
                "missing": True,
                "moving_stage_inventory": state_moving_names,
            }
            continue
        fixed_shape = fixed.shape
        moving_shape = moving.shape
        terminal_shape = terminal.shape
        if state == "follow":
            fixed_shape = _rotate_about_a06_a07_hinge(
                fixed_shape,
                -A06_A07_FOLLOW_FOLD_DEG,
            )
            moving_shape = _rotate_about_a06_a07_hinge(
                moving_shape,
                -A06_A07_FOLLOW_FOLD_DEG,
            )
            terminal_shape = _rotate_about_a06_a07_hinge(
                terminal_shape,
                -A06_A07_FOLLOW_FOLD_DEG,
            )

        fixed_box = _bounds_from_shape(fixed_shape)
        moving_box = _bounds_from_shape(moving_shape)
        terminal_box = _bounds_from_shape(terminal_shape)
        sleeve_capture = max(
            0.0,
            min(fixed_box.zmax, moving_box.zmax)
            - max(fixed_box.zmin, moving_box.zmin),
        )
        sleeve_common = _intersection_volume(fixed_shape, moving_shape)
        sleeve_clearance = _distance(fixed_shape, moving_shape)
        terminal_common = _intersection_volume(moving_shape, terminal_shape)
        terminal_clearance = _distance(moving_shape, terminal_shape)
        terminal_bbox_overlap = max(
            0.0,
            min(moving_box.zmax, terminal_box.zmax)
            - max(moving_box.zmin, terminal_box.zmin),
        )
        focus_z_shift = A07_FOCUS_TRANSLATION_MM if state == "focus" else 0.0
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
        tenon_plan = numeric_pair(
            moving.metadata.get("terminal_tenon_plan_mm")
        )
        socket_plan = numeric_pair(
            terminal.metadata.get("terminal_socket_plan_mm")
        )
        measured_engagement = (
            max(
                0.0,
                min(tenon_bounds[1] + focus_z_shift, terminal_box.zmax)
                - max(tenon_bounds[0] + focus_z_shift, terminal_box.zmin),
            )
            if tenon_bounds is not None
            else None
        )
        measured_dry_seam = (
            terminal_box.zmin - (cosmetic_bounds[1] + focus_z_shift)
            if cosmetic_bounds is not None
            else None
        )
        measured_end_clearance = (
            socket_bounds[1] - tenon_bounds[1]
            if socket_bounds is not None and tenon_bounds is not None
            else None
        )
        metadata_pass = (
            moving.metadata.get("telescopic_stage_count") == 1
            and moving.metadata.get("one_piece_finished_observation_spine") is True
            and moving.metadata.get(
                "three_stage_suitcase_handle_architecture_removed"
            )
            is True
            and float(moving.metadata.get("minimum_extended_overlap_mm", 0.0))
            >= A07_MINIMUM_EXTENDED_CAPTURE_MM
            and tenon_bounds is not None
            and max(abs(a - b) for a, b in zip(tenon_bounds, (1000.0, 1024.0)))
            <= 0.05
            and cosmetic_bounds is not None
            and max(abs(a - b) for a, b in zip(cosmetic_bounds, (438.0, 1004.0)))
            <= 0.05
            and socket_bounds is not None
            and max(abs(a - b) for a, b in zip(socket_bounds, (1000.0, 1026.0)))
            <= 0.05
            and tenon_plan is not None
            and max(abs(a - b) for a, b in zip(tenon_plan, (36.0, 80.0)))
            <= 0.05
            and socket_plan is not None
            and max(abs(a - b) for a, b in zip(socket_plan, (42.0, 86.0)))
            <= 0.05
            and radial_gap is not None
            and max(
                abs(value - A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM)
                for value in radial_gap
            )
            <= 0.05
            and terminal.metadata.get(
                "terminal_socket_captures_moving_spine_tenon"
            )
            is True
            and float(moving.metadata.get("terminal_tenon_engagement_mm", -1.0))
            == A07_TERMINAL_TENON_ENGAGEMENT_MM
            and float(moving.metadata.get("terminal_joint_end_clearance_mm", -1.0))
            == A07_TERMINAL_END_CLEARANCE_MM
            and float(moving.metadata.get("terminal_joint_dry_seam_mm", -1.0))
            == A07_TERMINAL_COSMETIC_DRY_SEAM_MM
        )
        state_pass = (
            state_moving_names == ["A07_mast_moving_inner_sleeve"]
            and sleeve_common <= 1.0e-5
            and sleeve_clearance >= 3.0 - 1.0e-4
            and sleeve_capture
            >= A07_MINIMUM_EXTENDED_CAPTURE_MM - 1.0e-4
            and terminal_common <= 1.0e-5
            and terminal_clearance > 1.0e-4
            and abs(
                terminal_clearance - A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM
            )
            <= 0.05
            and abs(
                terminal_bbox_overlap - A07_TERMINAL_TENON_ENGAGEMENT_MM
            )
            <= 0.05
            and measured_engagement is not None
            and abs(
                measured_engagement - A07_TERMINAL_TENON_ENGAGEMENT_MM
            )
            <= 0.05
            and measured_dry_seam is not None
            and abs(
                measured_dry_seam - A07_TERMINAL_COSMETIC_DRY_SEAM_MM
            )
            <= 0.05
            and measured_end_clearance is not None
            and abs(
                measured_end_clearance - A07_TERMINAL_END_CLEARANCE_MM
            )
            <= 0.05
            and metadata_pass
        )
        interface_pass = interface_pass and state_pass
        interface_evidence[state] = {
            "pass": state_pass,
            "moving_stage_inventory": state_moving_names,
            "sleeve_capture_mm": round(sleeve_capture, 6),
            "sleeve_clearance_mm": round(sleeve_clearance, 6),
            "sleeve_common_volume_mm3": round(sleeve_common, 9),
            "moving_to_terminal_minimum_distance_mm": round(
                terminal_clearance, 6
            ),
            "moving_to_terminal_common_volume_mm3": round(terminal_common, 9),
            "moving_to_terminal_bbox_axial_overlap_mm": round(
                terminal_bbox_overlap, 6
            ),
            "measured_tenon_engagement_mm": (
                round(measured_engagement, 6)
                if measured_engagement is not None
                else None
            ),
            "measured_socket_end_clearance_mm": (
                round(measured_end_clearance, 6)
                if measured_end_clearance is not None
                else None
            ),
            "measured_cosmetic_dry_seam_mm": (
                round(measured_dry_seam, 6)
                if measured_dry_seam is not None
                else None
            ),
            "metadata_pass": metadata_pass,
        }
    checks.add(
        "a07.brep.single_spine_150mm_capture_and_hidden_terminal_socket",
        interface_pass,
        missing_evidence=not interface_evidence,
        states=interface_evidence,
        required_focus_capture_mm=A07_MINIMUM_EXTENDED_CAPTURE_MM,
        required_terminal_radial_gap_mm=A07_TERMINAL_RADIAL_ASSEMBLY_GAP_MM,
        required_tenon_engagement_mm=A07_TERMINAL_TENON_ENGAGEMENT_MM,
        required_socket_end_clearance_mm=A07_TERMINAL_END_CLEARANCE_MM,
        required_cosmetic_dry_seam_mm=A07_TERMINAL_COSMETIC_DRY_SEAM_MM,
        requirement=(
            "A07 uses one moving spine with at least 150 mm Focus capture and a "
            "hidden 36 x 80 mm tenon inside a 42 x 86 mm socket.  The 3 mm radial "
            "gap, 16 mm engagement, 2 mm end clearance and 4 mm cosmetic dry seam "
            "must be real; zero-distance terminal face contact is forbidden."
        ),
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
        ride_part = get("ride", name)
        focus_part = get("focus", name)
        if ride_part is None or focus_part is None:
            moving_pass = False
            moving_evidence[name] = {"missing": True}
            continue
        normalised_focus = focus_part.shape.translate(
            (0.0, 0.0, -A07_FOCUS_TRANSLATION_MM)
        )
        evidence = _brep_pose_evidence(ride_part.shape, normalised_focus)
        ride_center = _bounds_from_shape(ride_part.shape).center
        focus_center = _bounds_from_shape(focus_part.shape).center
        actual_translation = tuple(
            focus_value - ride_value
            for ride_value, focus_value in zip(ride_center, focus_center)
        )
        translation_error = max(
            abs(actual - expected)
            for actual, expected in zip(
                actual_translation,
                (0.0, 0.0, A07_FOCUS_TRANSLATION_MM),
            )
        )
        evidence["actual_world_translation_mm"] = actual_translation
        evidence["translation_error_mm"] = translation_error
        moving_evidence[name] = evidence
        moving_pass = (
            moving_pass
            and _brep_pose_matches(evidence)
            and translation_error <= 0.01
        )
    focus_beam = get("focus", "A07_sensor_beam_shell")
    focus_beam_center = (
        _bounds_from_shape(focus_beam.shape).center if focus_beam is not None else None
    )
    focus_beam_axis_x = (
        focus_beam.metadata.get("controlled_axis_x_mm")
        if focus_beam is not None
        else None
    )
    moving_pass = moving_pass and focus_beam_center is not None and (
        isinstance(focus_beam_axis_x, (int, float))
        and abs(float(focus_beam_axis_x) - A07_MAST_AXIS_X_MM) <= 0.05
        and abs(focus_beam_center[2] - A07_FOCUS_BEAM_CENTER_Z_MM) <= 0.05
    )
    checks.add(
        "a07.brep.focus_moving_members_plus_420_only",
        moving_pass,
        missing_evidence=not moving_names or focus_beam_center is None,
        moving_occurrences=moving_names,
        comparisons=moving_evidence,
        sensor_beam_center_mm=focus_beam_center,
        controlled_axis_x_mm=focus_beam_axis_x,
        required_translation_mm=(0.0, 0.0, A07_FOCUS_TRANSLATION_MM),
    )

    # Follow must apply the same additional hinge transform to the existing A06
    # backrest and the low A07 package.  Normalising both by the one frozen
    # inverse transform must therefore recover their Ride B-Reps exactly.
    follow_names = {
        name for name, part in by_state["follow"].items() if part.module.upper() == "A07"
    }
    follow_package_names = sorted(ride_names)
    common_hinge_evidence: dict[str, Any] = {}
    common_hinge_pass = bool(follow_package_names) and follow_names == ride_names
    for name in ("A06_backrest_weather_shell", *follow_package_names):
        ride_part = get("ride", name)
        follow_part = get("follow", name)
        if ride_part is None or follow_part is None:
            common_hinge_pass = False
            common_hinge_evidence[name] = {"missing": True}
            continue
        normalised_follow = _rotate_about_a06_a07_hinge(
            follow_part.shape,
            -A06_A07_FOLLOW_FOLD_DEG,
        )
        evidence = _brep_pose_evidence(ride_part.shape, normalised_follow)
        common_hinge_evidence[name] = evidence
        common_hinge_pass = common_hinge_pass and _brep_pose_matches(evidence)
    checks.add(
        "a07.brep.follow_a06_a07_common_hinge_transform",
        common_hinge_pass,
        missing_evidence=not common_hinge_evidence,
        hinge_origin_mm=A06_A07_COMMON_FOLD_HINGE_MM,
        follow_rotation_deg=A06_A07_FOLLOW_FOLD_DEG,
        ride_inventory=sorted(ride_names),
        follow_inventory=sorted(follow_names),
        comparisons=common_hinge_evidence,
    )

    follow_cover = get("follow", "A06_backrest_weather_shell")
    follow_members = [
        get("follow", name) for name in follow_package_names
    ]
    follow_members = [part for part in follow_members if part is not None]
    forbidden_cover_tokens = (
        "weather_vault",
        "closed_field",
        "backrest_cowl",
        "backrest_lid",
        "travel_cap",
        "continuity_skirt",
        "travel_skirt",
    )
    forbidden_covers = sorted(
        name
        for name, part in by_state["follow"].items()
        if part.module.upper() in {"A06", "A07"}
        and name != "A06_backrest_weather_shell"
        and any(token in name.lower() for token in forbidden_cover_tokens)
    )
    allowed_follow_a06_surfaces = {
        "A06_backrest_weather_shell",
        "A06_backrest_contact_panel",
    }
    additional_follow_a06_surfaces = sorted(
        name
        for name, part in by_state["follow"].items()
        if part.module.upper() == "A06"
        and name not in allowed_follow_a06_surfaces
        and part.metadata.get("a06_motion_hardware") is not True
    )
    coverage_evidence: dict[str, Any] = {}
    interface_evidence: dict[str, Any] = {}
    lateral_surround_pass = False
    focus_egress_pass = False
    focus_egress_evidence: dict[str, Any] = {}
    if follow_cover is not None and follow_members:
        # Judge the folded package in the A06 master frame.  A06 and A07 have
        # already been required to share one rigid hinge transform above, so
        # this inverse transform preserves their real B-Rep clearance while
        # giving the enclosure probes stable product axes.
        normalised_cover = _rotate_about_a06_a07_hinge(
            follow_cover.shape,
            -A06_A07_FOLLOW_FOLD_DEG,
        )
        normalised_members = {
            part.name: _rotate_about_a06_a07_hinge(
                part.shape,
                -A06_A07_FOLLOW_FOLD_DEG,
            )
            for part in follow_members
        }
        cover_box = _bounds_from_shape(normalised_cover)
        package_box = _union_bounds(
            _bounds_from_shape(shape) for shape in normalised_members.values()
        )
        assert package_box is not None

        def lateral_probe(
            part_box: Bounds,
            station_z: float,
            direction: str,
        ) -> float:
            section_mm = 0.5
            offset_mm = 0.05
            x = part_box.center[0]
            y = part_box.center[1]
            if direction == "-x":
                start, end = part_box.xmin - offset_mm, cover_box.xmin - 2.0
                size = (abs(end - start), section_mm, section_mm)
                center = ((start + end) / 2.0, y, station_z)
            elif direction == "+x":
                start, end = part_box.xmax + offset_mm, cover_box.xmax + 2.0
                size = (abs(end - start), section_mm, section_mm)
                center = ((start + end) / 2.0, y, station_z)
            elif direction == "-y":
                start, end = part_box.ymin - offset_mm, cover_box.ymin - 2.0
                size = (section_mm, abs(end - start), section_mm)
                center = (x, (start + end) / 2.0, station_z)
            elif direction == "+y":
                start, end = part_box.ymax + offset_mm, cover_box.ymax + 2.0
                size = (section_mm, abs(end - start), section_mm)
                center = (x, (start + end) / 2.0, station_z)
            else:  # pragma: no cover - closed local contract
                raise ValueError(f"unsupported A07 surround direction {direction!r}")
            if min(size) <= 0.0:
                return 0.0
            probe = cq.Workplane("XY").box(*size).translate(center).val()
            return _intersection_volume(probe, normalised_cover)

        channel_member_names = (
            "A07_mast_fixed_outer_sleeve",
            "A07_mast_moving_inner_sleeve",
        )
        channel_members = [
            get("follow", name)
            for name in channel_member_names
        ]
        channel_members = [
            part for part in channel_members if part is not None
        ]
        for part in follow_members:
            common = _intersection_volume(part.shape, follow_cover.shape)
            clearance = _distance(part.shape, follow_cover.shape)
            compliant_seal = part.name == "A07_mast_throat_weather_gasket"
            interface_evidence[part.name] = {
                "a06_common_volume_mm3": common,
                "a06_clearance_mm": clearance,
                "intentional_compliant_seal_interface": compliant_seal,
                "interface_pass": (
                    common <= 1.0e-5
                    and (compliant_seal or clearance >= 0.5 - 1.0e-6)
                ),
            }

        for part in channel_members:
            normalised_part = normalised_members[part.name]
            part_box = _bounds_from_shape(normalised_part)
            stations: list[dict[str, Any]] = []
            for fraction in (0.25, 0.5, 0.75):
                station_z = part_box.zmin + part_box.zlen * fraction
                hits = {
                    direction: lateral_probe(part_box, station_z, direction)
                    for direction in ("-x", "+x", "-y", "+y")
                }
                # An open-top U-channel is the intended A06 architecture: both
                # side walls and at least one longitudinal weather wall must be
                # real B-Rep.  Requiring a +Z hit here would silently mandate a
                # prohibited cap across the Focus deployment throat.
                station_pass = (
                    hits["-y"] > 1.0e-6
                    and hits["+y"] > 1.0e-6
                    and max(hits["-x"], hits["+x"]) > 1.0e-6
                )
                stations.append(
                    {
                        "fraction_of_part_height": fraction,
                        "station_z_mm": station_z,
                        "directional_a06_common_volume_mm3": hits,
                        "u_channel_surround_pass": station_pass,
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
                bool(station["u_channel_surround_pass"])
                for station in item["lateral_surround_stations"]
            )
            for item in coverage_evidence.values()
            )
        )

        # The low beam and moving sleeve must have a continuous open egress
        # through the same A06 shell.  Nine actual B-Rep stroke poses keep the
        # 52.5 mm sample pitch below the 64 mm terminal height, so a transverse
        # cap anywhere on the pure +Z path cannot fall between samples.
        ride_cover = get("ride", "A06_backrest_weather_shell")
        egress_names = sorted(
            name
            for name in ride_names
            if "mast_moving_inner_sleeve" in name
            or name == "A07_sensor_beam_shell"
        )
        focus_egress_pass = ride_cover is not None and bool(egress_names)
        if ride_cover is not None:
            for name in egress_names:
                ride_part = get("ride", name)
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
                    common = _intersection_volume(posed, ride_cover.shape)
                    clearance = _distance(posed, ride_cover.shape)
                    samples.append(
                        {
                            "stroke_mm": stroke_mm,
                            "a06_common_volume_mm3": common,
                            "a06_clearance_mm": clearance,
                        }
                    )
                    focus_egress_pass = (
                        focus_egress_pass
                        and common <= 1.0e-5
                        and clearance >= 0.5 - 1.0e-6
                    )
                focus_egress_evidence[name] = {"samples": samples}

        coverage_pass = (
            not forbidden_covers
            and not additional_follow_a06_surfaces
            and len(follow_members) == len(follow_package_names)
            and lateral_surround_pass
            and focus_egress_pass
            and all(item["interface_pass"] for item in interface_evidence.values())
        )
    else:
        cover_box = None
        package_box = None
        coverage_pass = False
    checks.add(
        "a07.brep.follow_a06_only_weather_coverage_and_clearance",
        coverage_pass,
        missing_evidence=follow_cover is None or not follow_members,
        forbidden_additional_covers=forbidden_covers,
        allowed_follow_a06_surface_occurrences=sorted(
            allowed_follow_a06_surfaces
        ),
        additional_follow_a06_surface_occurrences=(
            additional_follow_a06_surfaces
        ),
        a06_weather_shell_bounds=cover_box.to_dict() if cover_box else None,
        a07_folded_package_bounds=package_box.to_dict() if package_box else None,
        evidence_frame="actual Follow B-Reps inverse-rotated to the common A06 hinge frame",
        lateral_u_channel_surround_pass=lateral_surround_pass,
        focus_open_egress_sweep_pass=focus_egress_pass,
        focus_open_egress_sweep=focus_egress_evidence,
        channel_coverage=coverage_evidence,
        all_a07_a06_interfaces=interface_evidence,
        minimum_clearance_mm=0.5,
        requirement=(
            "The same folded trapezoidal A06 backrest is the only Follow weather surface; "
            "its real side/rear U-channel laterally surrounds the fixed sleeve and "
            "one-piece moving spine with dry clearance.  The crowned terminal stays "
            "above the shoulder while the top remains an open Focus deployment throat."
        ),
    )

    # A low terminal is a deliberate readable object, not a visibility tag.  A
    # set of narrow +Z B-Rep sightlines across the crowned terminal must remain clear
    # of every non-A07 production solid in both low states.
    for state in ("ride", "cafe"):
        beam = get(state, "A07_sensor_beam_shell")
        state_shapes = [
            part
            for part in parts
            if state in part.states
            and part.shape is not None
            and part.module.upper() != "A07"
        ]
        obstructions: dict[str, dict[str, float]] = {}
        beam_box = _bounds_from_shape(beam.shape) if beam is not None else None
        beam_axis_x = (
            beam.metadata.get("controlled_axis_x_mm")
            if beam is not None
            else None
        )
        if beam_box is not None:
            sightline_axis_x = (
                float(beam_axis_x)
                if isinstance(beam_axis_x, (int, float))
                else beam_box.center[0]
            )
            ceiling = max(
                [beam_box.zmax + 50.0]
                + [_bounds_from_shape(part.shape).zmax + 5.0 for part in state_shapes]
            )
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
                for part in state_shapes:
                    common = _intersection_volume(part.shape, ray)
                    if common > 1.0e-6:
                        hits[part.name] = common
                obstructions[str(y_offset)] = hits
        readable = (
            beam_box is not None
            and isinstance(beam_axis_x, (int, float))
            and abs(float(beam_axis_x) - A07_MAST_AXIS_X_MM) <= 0.05
            and abs(beam_box.center[2] - A07_LOW_BEAM_CENTER_Z_MM) <= 0.05
            and abs(
                beam_box.ylen - A07_TERMINAL_NOMINAL_WIDTH_Y_MM
            ) <= 2.0
            and all(not hits for hits in obstructions.values())
            and len(obstructions) == 3
        )
        checks.add(
            f"a07.brep.{state}.low_beam_exterior_readable",
            readable,
            missing_evidence=beam_box is None,
            beam_bounds=beam_box.to_dict() if beam_box else None,
            upward_sightline_obstructions_mm3=obstructions,
            mast_axis_x_mm=A07_MAST_AXIS_X_MM,
            controlled_axis_x_mm=beam_axis_x,
            beam_center_z_mm=A07_LOW_BEAM_CENTER_Z_MM,
        )


def _projection_coverage(
    source: Bounds,
    proxy: Bounds,
    axes: tuple[str, str],
) -> float:
    """AABB projected-area coverage used for optical/RF interface gates."""

    values: list[float] = []
    source_area = 1.0
    for axis in axes:
        source_min = getattr(source, f"{axis}min")
        source_max = getattr(source, f"{axis}max")
        proxy_min = getattr(proxy, f"{axis}min")
        proxy_max = getattr(proxy, f"{axis}max")
        span = max(0.0, source_max - source_min)
        overlap = max(0.0, min(source_max, proxy_max) - max(source_min, proxy_min))
        source_area *= span
        values.append(overlap)
    if source_area <= 0.0:
        return 0.0
    return values[0] * values[1] / source_area


def _aabb_distance(a: Bounds, b: Bounds) -> float:
    """Conservative lower bound on the distance between two solids."""

    dx = max(a.xmin - b.xmax, b.xmin - a.xmax, 0.0)
    dy = max(a.ymin - b.ymax, b.ymin - a.ymax, 0.0)
    dz = max(a.zmin - b.zmax, b.zmin - a.zmax, 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _minimum_clearance_to_target(
    records: Sequence[PartRecord],
    target: Any,
    required_mm: float,
) -> tuple[float, str | None]:
    """Return a proven minimum without running OCC distance on remote parts.

    AABB distance is a lower bound.  Exact OCC work is therefore only required
    for parts whose lower bound is below the acceptance threshold.  This keeps
    four-state articulation checks fast while preserving fail-safe behaviour.
    """

    target_bounds = _bounds_from_shape(target)
    lower_bounds = [(_aabb_distance(record.bounds, target_bounds), record) for record in records]
    if not lower_bounds:
        return math.inf, None
    exact: list[tuple[float, str]] = []
    remote: list[tuple[float, str]] = []
    for lower, record in lower_bounds:
        if lower < required_mm - 1e-9:
            exact.append((_distance(record.shape, target), record.name))
        else:
            remote.append((lower, record.name))
    candidates = exact + remote
    return min(candidates, key=lambda item: item[0])


def _evidence_lists(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    groups: list[Any] = []
    for key in ("hard_clearances", "clearances"):
        groups.append(payload.get(key))
    for parent_key in ("validation", "validation_evidence", "evidence"):
        parent = payload.get(parent_key)
        if isinstance(parent, Mapping):
            groups.extend((parent.get("hard_clearances"), parent.get("clearances")))
    result: list[Mapping[str, Any]] = []
    for group in groups:
        if isinstance(group, Mapping):
            for key, value in group.items():
                if isinstance(value, Mapping):
                    result.append({"id": key, **value})
        elif isinstance(group, Sequence) and not isinstance(group, (str, bytes)):
            result.extend(item for item in group if isinstance(item, Mapping))
    return result


def _fallback_clearance(
    family: str,
    required_mm: float,
    payload: Mapping[str, Any],
    checks: Checks,
) -> None:
    candidates = []
    for item in _evidence_lists(payload):
        text = " ".join(str(item.get(key, "")) for key in ("id", "name", "family", "target_family")).lower()
        synonyms = {"tyre": ("tyre", "tire", "wheel"), "rocker": ("rocker", "suspension"), "mast": ("mast", "spine", "telescop")}[family]
        if any(word in text for word in synonyms):
            candidates.append(item)
    actuals = []
    for item in candidates:
        for key in ("actual_mm", "minimum_actual_mm", "min_mm", "clearance_mm"):
            if key in item:
                actuals.append(float(item[key]))
                break
    actual = min(actuals) if actuals else None
    checks.add(
        f"clearance.{family}.manifest_evidence",
        actual is not None and actual >= required_mm - 1e-6,
        missing_evidence=actual is None,
        actual_minimum_mm=round(actual, 3) if actual is not None else None,
        required_mm=required_mm,
        evidence_count=len(candidates),
    )


def _validate_functional_corridors(
    root: Path,
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any,
    search_roots: Sequence[Path],
) -> None:
    """Prove that final skins do not block controlled optical/RF/safety paths."""

    source_part_dir = root / "build" / "parts"

    def resolved(record: PartRecord | None) -> Any | None:
        return None if record is None else _shape_of(record, search_roots, cq)

    def opaque_hits(
        state: str,
        corridor: Any,
        *,
        modules: tuple[str, ...],
        exclude_name_tokens: tuple[str, ...] = (),
    ) -> dict[str, float]:
        hits: dict[str, float] = {}
        for record in parts:
            if state not in record.states or record.module.upper() not in modules:
                continue
            if any(token in record.search_text for token in exclude_name_tokens):
                continue
            shape = resolved(record)
            if shape is None:
                continue
            overlap = _intersection_volume(shape, corridor)
            if overlap > 1e-6:
                hits[record.name] = round(overlap, 6)
        return hits

    # The same table becomes a 432 x 32 mm maximum folded plan envelope and is
    # lifted through the armrest top.  Prove that the fixed shell leaves this
    # vertical corridor open while the closed final-state lid physically caps
    # it.  The separate motion-gate module proves the 105-degree lid sweep and
    # ordered extraction/re-latch sequence; a side-wall passage is forbidden.
    for state in STATES:
        for side in (-1, 1):
            side_name = "right" if side > 0 else "left"
            extraction_corridor = (
                cq.Workplane("XY")
                .box(432.0, 32.0, 220.0)
                .translate((-115.0, side * 343.0, 645.0))
                .val()
            )
            shell_record = next(
                (
                    part
                    for part in parts
                    if state in part.states
                    and part.name == f"A05_armrest_table_bay_shell_{side_name}"
                ),
                None,
            )
            lid_record = next(
                (
                    part
                    for part in parts
                    if state in part.states
                    and part.name == f"A05_armrest_touch_lid_{side_name}"
                ),
                None,
            )
            shell_shape = resolved(shell_record)
            lid_shape = resolved(lid_record)
            shell_common = (
                None
                if shell_shape is None
                else _intersection_volume(shell_shape, extraction_corridor)
            )
            lid_common = (
                None
                if lid_shape is None
                else _intersection_volume(lid_shape, extraction_corridor)
            )
            checks.add(
                f"functional.{state}.table_top_extraction_corridor.{side_name}",
                shell_common is not None
                and lid_common is not None
                and shell_common <= 1.0e-6
                and lid_common > 1.0,
                corridor_mm=(432.0, 32.0, 220.0),
                nominal_folded_pack_mm=(430.0, 30.0, 139.0),
                maximum_folded_material_envelope_mm=(432.0, 32.0, 141.0),
                fixed_shell_common_volume_mm3=(
                    None if shell_common is None else round(shell_common, 6)
                ),
                closed_lid_common_volume_mm3=(
                    None if lid_common is None else round(lid_common, 6)
                ),
                target=(
                    "fixed shell leaves a real vertical top-extraction corridor; "
                    "the closed final-state lid caps it and no side wall opens"
                ),
            )

    # Focus privacy shutter is one controlled physical occurrence.  Styling may
    # provide a clearance pocket, but may neither relocate nor trim that B-Rep.
    shutter_source_path = source_part_dir / "mast_privacy_shutter_parked_focus.step"
    shutter_source = cq.importers.importStep(str(shutter_source_path)).val()
    shutter_source_box = _bounds_from_shape(shutter_source)
    shutter_proxy = next(
        (
            part
            for part in parts
            if "focus" in part.states
            and part.module.upper() == "A07"
            and "physical_privacy_shutter" in part.search_text
        ),
        None,
    )
    shutter_shape = resolved(shutter_proxy)
    if shutter_proxy is not None and shutter_shape is not None:
        comparison = _brep_pose_evidence(shutter_source, shutter_shape)
        source_center = shutter_source_box.center
        proxy_center = shutter_proxy.bounds.center
        center_error = max(
            abs(actual - expected)
            for actual, expected in zip(
                proxy_center,
                A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM,
            )
        )
        checks.add(
            "functional.focus.privacy_shutter_conserved_brep",
            _brep_pose_matches(comparison) and center_error <= 0.05,
            source_bounds=shutter_source_box.to_dict(),
            proxy_bounds=shutter_proxy.bounds.to_dict(),
            source_center_mm=source_center,
            required_center_mm=A07_FOCUS_PRIVACY_SHUTTER_CENTER_MM,
            actual_center_mm=proxy_center,
            maximum_center_error_mm=center_error,
            brep_comparison=comparison,
            evidence_basis="direct world-pose B-Rep symmetric difference",
        )
    else:
        checks.add(
            "functional.focus.privacy_shutter_conserved_brep",
            False,
            missing_evidence=True,
        )

    beam_proxy = next(
        (
            part
            for part in parts
            if "focus" in part.states
            and part.module.upper() == "A07"
            and "sensor_beam_shell" in part.search_text
        ),
        None,
    )
    beam_shape = resolved(beam_proxy)
    if (
        shutter_proxy is not None
        and shutter_shape is not None
        and beam_proxy is not None
        and beam_shape is not None
    ):
        clearance = _distance(shutter_shape, beam_shape)
        common = _intersection_volume(shutter_shape, beam_shape)
        checks.add(
            "functional.focus.privacy_shutter_released_park_clearance",
            clearance >= 0.5 - 1e-6 and common <= 1.0e-5,
            actual_clearance_mm=round(clearance, 3),
            required_clearance_mm=0.5,
            common_volume_mm3=round(common, 9),
            shutter_bounds=shutter_proxy.bounds.to_dict(),
            sensor_beam_bounds=beam_proxy.bounds.to_dict(),
            target=(
                "canonical parked shutter remains inside the crowned terminal's integrated pocket, "
                "but its real B-Rep must remain collision-free"
            ),
        )
    else:
        checks.add(
            "functional.focus.privacy_shutter_released_park_clearance",
            False,
            missing_evidence=True,
        )

    window_proxy = next(
        (
            part
            for part in parts
            if "focus" in part.states
            and part.module.upper() == "A07"
            and "sensor_beam_smoked_window" in part.search_text
        ),
        None,
    )
    window_shape = resolved(window_proxy)
    if (
        shutter_proxy is not None
        and shutter_shape is not None
        and window_proxy is not None
        and window_shape is not None
    ):
        window_clearance = _distance(shutter_shape, window_shape)
        window_common = _intersection_volume(shutter_shape, window_shape)
        checks.add(
            "functional.focus.privacy_shutter_to_window_dry_clearance",
            window_clearance >= 0.5 - 1.0e-6 and window_common <= 1.0e-5,
            actual_clearance_mm=round(window_clearance, 6),
            required_clearance_mm=0.5,
            common_volume_mm3=round(window_common, 9),
            shutter_bounds=shutter_proxy.bounds.to_dict(),
            window_bounds=window_proxy.bounds.to_dict(),
        )
    else:
        checks.add(
            "functional.focus.privacy_shutter_to_window_dry_clearance",
            False,
            missing_evidence=True,
        )

    uwb_source = cq.importers.importStep(
        str(source_part_dir / "follow_uwb_rear_radome.step")
    ).val()
    horn_source = cq.importers.importStep(
        str(source_part_dir / "service_rear_horn_behind_door.step")
    ).val()
    vent_source = cq.importers.importStep(
        str(source_part_dir / "battery_pressure_vent_duct.step")
    ).val()
    uwb_source_box = _bounds_from_shape(uwb_source)
    horn_source_box = _bounds_from_shape(horn_source)

    for state in STATES:
        door = next(
            (
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A10"
                and "rear_flush_service_door_skin" in part.search_text
            ),
            None,
        )
        door_shape = resolved(door)
        radome = next(
            (
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A10"
                and "rear_uwb_radome" in part.search_text
            ),
            None,
        )
        radome_shape = resolved(radome)
        uwb_corridor = (
            cq.Workplane("XY")
            .box(6.0, 80.0, 24.0)
            .translate((330.0, 0.0, 270.0))
            .val()
        )
        uwb_hits = opaque_hits(
            state,
            uwb_corridor,
            modules=("A10",),
            exclude_name_tokens=("rear_uwb_radome",),
        )
        if door_shape is not None and radome is not None and radome_shape is not None:
            door_clearance = _distance(uwb_source, door_shape)
            yz_coverage = _projection_coverage(uwb_source_box, radome.bounds, ("y", "z"))
            material_ok = any(
                token in radome.search_text
                for token in ("rf_transparent", "rf-transparent", "non_conductive", "polycarbonate")
            )
            checks.add(
                f"functional.{state}.rear_uwb_clear_rf_corridor",
                not uwb_hits
                and door_clearance >= 2.0 - 1e-6
                and yz_coverage >= 0.999
                and material_ok,
                opaque_intersections_mm3=uwb_hits,
                door_to_source_clearance_mm=round(door_clearance, 3),
                required_perimeter_clearance_mm=2.0,
                source_yz_projection_coverage=round(yz_coverage, 6),
                material=radome.metadata.get("material"),
            )
        else:
            checks.add(
                f"functional.{state}.rear_uwb_clear_rf_corridor",
                False,
                missing_evidence=True,
                opaque_intersections_mm3=uwb_hits,
            )

        horn_mesh = next(
            (
                part
                for part in parts
                if state in part.states
                and part.module.upper() == "A10"
                and "rear_horn_acoustic_mesh" in part.search_text
            ),
            None,
        )
        horn_corridor = (
            cq.Workplane("XY")
            .box(8.0, 60.0, 28.0)
            .translate((329.0, 0.0, 400.0))
            .val()
        )
        horn_hits = opaque_hits(
            state,
            horn_corridor,
            modules=("A10",),
            exclude_name_tokens=("rear_horn_acoustic_mesh",),
        )
        if door_shape is not None and horn_mesh is not None:
            horn_door_overlap = _intersection_volume(horn_source, door_shape)
            horn_coverage = _projection_coverage(horn_source_box, horn_mesh.bounds, ("y", "z"))
            evidence_fields = all(
                horn_mesh.metadata.get(key)
                for key in (
                    "membrane",
                    "ip_validation_required",
                    "sound_pressure_validation_required",
                )
            )
            checks.add(
                f"functional.{state}.rear_horn_acoustic_outlet",
                not horn_hits
                and horn_door_overlap <= 1e-6
                and horn_coverage >= 0.999
                and evidence_fields,
                opaque_intersections_mm3=horn_hits,
                source_to_door_overlap_mm3=round(horn_door_overlap, 6),
                source_yz_projection_coverage=round(horn_coverage, 6),
                membrane=horn_mesh.metadata.get("membrane"),
                ip_validation_required=horn_mesh.metadata.get("ip_validation_required"),
                sound_pressure_validation_required=horn_mesh.metadata.get("sound_pressure_validation_required"),
            )
        else:
            checks.add(
                f"functional.{state}.rear_horn_acoustic_outlet",
                False,
                missing_evidence=True,
                opaque_intersections_mm3=horn_hits,
            )

        # A complete 42 x 42 mm source-mouth prism must remain clear through
        # the final bezel.  This geometric gate is stricter than trusting a
        # claimed free-area metadata value.
        vent_corridor = (
            cq.Workplane("XY")
            .box(10.0, 42.0, 42.0)
            .translate((330.0, 0.0, 178.0))
            .val()
        )
        vent_hits = opaque_hits(
            state,
            vent_corridor,
            modules=("A10",),
        )
        vent_source_hits = opaque_hits(
            state,
            vent_source,
            modules=("A01", "A02", "A03", "A04", "A08", "A10"),
        )
        checks.add(
            f"functional.{state}.battery_pressure_vent_full_mouth",
            not vent_hits and not vent_source_hits,
            source_mouth_area_mm2=1764.0,
            proven_clear_section_mm=(42.0, 42.0),
            corridor_intersections_mm3=vent_hits,
            source_duct_intersections_mm3=vent_source_hits,
        )

        for axle_name in ("front", "rear"):
            for side_name in ("left", "right"):
                source = cq.importers.importStep(
                    str(
                        source_part_dir
                        / f"follow_cliff_ir_window_{axle_name}_{side_name}.step"
                    )
                ).val()
                source_box = _bounds_from_shape(source)
                proxy = next(
                    (
                        part
                        for part in parts
                        if state in part.states
                        and part.module.upper() == "A02"
                        and f"cliff_ir_window_{axle_name}_{side_name}" in part.search_text
                    ),
                    None,
                )
                proxy_shape = resolved(proxy)
                if proxy is None or proxy_shape is None:
                    checks.add(
                        f"functional.{state}.downview_ir.{axle_name}_{side_name}",
                        False,
                        missing_evidence=True,
                    )
                    continue
                xy_coverage = _projection_coverage(source_box, proxy.bounds, ("x", "y"))
                corridor_height = source_box.zmin
                corridor = (
                    cq.Workplane("XY")
                    .box(source_box.xlen, source_box.ylen, corridor_height)
                    .translate(
                        (
                            source_box.center[0],
                            source_box.center[1],
                            corridor_height / 2.0,
                        )
                    )
                    .val()
                )
                optical_hits = opaque_hits(
                    state,
                    corridor,
                    modules=("A01", "A02", "A03", "A04", "A08", "A10"),
                    exclude_name_tokens=(
                        f"cliff_ir_window_{axle_name}_{side_name}",
                    ),
                )
                checks.add(
                    f"functional.{state}.downview_ir.{axle_name}_{side_name}",
                    proxy.bounds.zmax <= source_box.zmin + 0.5
                    and xy_coverage >= 0.95
                    and not optical_hits,
                    source_bounds=source_box.to_dict(),
                    proxy_bounds=proxy.bounds.to_dict(),
                    xy_projection_coverage=round(xy_coverage, 6),
                    opaque_downward_corridor_intersections_mm3=optical_hits,
                    target="final pane at or below source exterior face with clear -Z corridor",
                )


def _validate_wheel_contact_band_contract(
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any,
) -> None:
    """Prove the axis-height half-wrap, sweep and 752 mm width lock."""

    tyres: dict[tuple[str, str], Any] = {}
    hubs: dict[tuple[str, str], Any] = {}
    axles: dict[tuple[str, str], Any] = {}
    for axle in ("front", "rear"):
        for side_name in ("left", "right"):
            for family, destination in (
                ("tyre", tyres),
                ("hub", hubs),
                ("axle", axles),
            ):
                path = (
                    WORKSPACE_ROOT
                    / "build"
                    / "parts"
                    / f"{family}_{axle}_{side_name}.step"
                )
                imported = cq.importers.importStep(str(path))
                destination[(axle, side_name)] = (
                    imported.val() if hasattr(imported, "val") else imported
                )

    for state in STATES:
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            belt_matches = [
                part
                for part in parts
                if state in part.states
                and part.name == f"A03_continuous_wheel_belt_shell_{side_name}"
                and part.shape is not None
            ]
            class_a_belt_shell = (
                wheel_belt_class_a_shell(
                    belt_matches[0].shape,
                    side_name,
                )
                if len(belt_matches) == 1
                else None
            )
            for axle, wheel_x in (("front", -380.0), ("rear", 180.0)):
                visual_skin_matches = [
                    part
                    for part in parts
                    if state in part.states
                    and part.name
                    == (
                        "A03_body_colour_wheel_end_return_skin_"
                        f"{axle}_{side_name}"
                    )
                    and part.shape is not None
                ]
                cap_matches = [
                    part
                    for part in parts
                    if state in part.states
                    and part.name
                    == f"A03_wheel_end_service_cap_{axle}_{side_name}"
                    and part.shape is not None
                ]
                backing_matches = [
                    part
                    for part in parts
                    if state in part.states
                    and part.name
                    == (
                        "A03_wheel_end_service_seam_backing_"
                        f"{axle}_{side_name}"
                    )
                    and part.shape is not None
                ]
                gaiter_matches = [
                    part
                    for part in parts
                    if state in part.states
                    and part.name
                    == f"A03_wheel_end_motion_gaiter_{axle}_{side_name}"
                    and part.shape is not None
                ]
                if (
                    len(belt_matches) != 1
                    or len(visual_skin_matches) != 1
                    or len(cap_matches) != 1
                    or len(backing_matches) != 1
                    or len(gaiter_matches) != 1
                ):
                    checks.add(
                        f"wheel_contact_band.{state}.{axle}.{side_name}",
                        False,
                        missing_evidence=True,
                        continuous_belt_occurrences=len(belt_matches),
                        body_colour_end_return_skin_occurrences=len(
                            visual_skin_matches
                        ),
                        moving_hub_cap_occurrences=len(cap_matches),
                        moving_hub_backing_occurrences=len(backing_matches),
                        flexible_gaiter_occurrences=len(gaiter_matches),
                    )
                    continue
                belt = belt_matches[0]
                visual_skin = visual_skin_matches[0]
                cap = cap_matches[0]
                backing = backing_matches[0]
                gaiter = gaiter_matches[0]
                hub_articulation = evaluate_wheel_hub_articulation(
                    axle=axle,
                    side=side_name,
                    belt=belt.shape,
                    released_cap=cap.shape,
                    released_backing=backing.shape,
                    released_gaiter=gaiter.shape,
                    controlled_hub=hubs[(axle, side_name)],
                    controlled_axle=axles[(axle, side_name)],
                    boolean_tolerance_mm3=1.0e-5,
                    distance_tolerance_mm=1.0e-4,
                )
                belt_box = _bounds_from_shape(belt.shape)
                visual_skin_box = _bounds_from_shape(visual_skin.shape)
                product_width = 2.0 * max(
                    abs(belt_box.ymin),
                    abs(belt_box.ymax),
                )
                sweep_angles = (-10.0, -5.0, 0.0, 5.0, 10.0)
                sweep_clearances: dict[str, float] = {}
                tyre = tyres[(axle, side_name)]
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
                    sweep_clearances[f"{angle:+.1f}"] = _distance(
                        class_a_belt_shell,
                        swept,
                    )
                minimum_swept_clearance = min(sweep_clearances.values())
                tyre_box = _bounds_from_shape(tyre)
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
                                side * 371.5,
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
                                side * 371.5,
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
                            if side_closed_volume <= 1.0e-5
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
                outward_x = -1.0 if axle == "front" else 1.0
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
                    if end_closed_volume <= 1.0e-5
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
                            if coverage_volume <= 1.0e-5
                            else float(
                                coverage_section.BoundingBox().xlen
                                )
                        )
                visual_skin_belt_common = _intersection_volume(
                    visual_skin.shape,
                    belt.shape,
                )
                visual_skin_belt_gap = _distance(
                    visual_skin.shape,
                    belt.shape,
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
                            if visual_volume <= 1.0e-5
                            else float(visual_section.BoundingBox().xlen)
                        )
                visual_skin_outboard_of_tyre = (
                    visual_skin_box.xmax <= tyre_box.xmin
                    if axle == "front"
                    else visual_skin_box.xmin >= tyre_box.xmax
                )
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
                    side_tyre_first_hit[
                        f"x_offset_{x_offset:+.1f}_z_{witness_z:.1f}"
                    ] = {
                        "controlled_tyre_common_mm3": _intersection_volume(
                            tyre,
                            witness,
                        ),
                        "intervening_a03_common_mm3": sum(
                            _intersection_volume(shape, witness)
                            for shape in (
                                belt.shape,
                                cap.shape,
                                gaiter.shape,
                                visual_skin.shape,
                            )
                        ),
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
                        end_tyre_first_hit[
                            f"y_offset_{lateral_offset:+.1f}_z_{witness_z:.1f}"
                        ] = {
                            "controlled_tyre_common_mm3": _intersection_volume(
                                tyre,
                                witness,
                            ),
                            "intervening_a03_common_mm3": sum(
                                _intersection_volume(shape, witness)
                                for shape in (
                                    belt.shape,
                                    visual_skin.shape,
                                    cap.shape,
                                    gaiter.shape,
                                )
                            ),
                        }
                lower_tyre_first_hit_pass = all(
                    sample["controlled_tyre_common_mm3"] > 1.0e-5
                    and sample["intervening_a03_common_mm3"] <= 1.0e-5
                    for sample in (
                        *side_tyre_first_hit.values(),
                        *end_tyre_first_hit.values(),
                    )
                )
                visual_material = str(
                    visual_skin.metadata.get("material", "")
                )
                checks.add(
                    f"wheel_contact_band.{state}.{axle}.{side_name}",
                    side_open_common <= 1.0e-5
                    and 1.85 <= side_closed_wall <= 1.95
                    and len(side_half_wrap_samples)
                    == len(WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM)
                    and end_open_common <= 1.0e-5
                    and 1.85 <= end_closed_wall <= 1.95
                    and len(end_coverage_walls) == 9
                    and all(
                        1.85 <= value <= 1.95
                        for value in end_coverage_walls.values()
                    )
                    and visual_skin.shape.isValid()
                    and len(visual_skin.shape.Solids()) == 1
                    and visual_skin_belt_common <= 1.0e-5
                    and abs(
                        visual_skin_belt_gap
                        - WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM
                    )
                    <= 1.0e-4
                    and abs(
                        visual_skin_box.xlen
                        - WHEEL_END_VISUAL_SKIN_THICKNESS_MM
                    )
                    <= 1.0e-4
                    and abs(
                        visual_skin_box.ylen
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
                    and "body-colour" in visual_material
                    and "PC-ABS" in visual_material
                    and visual_skin.metadata.get("body_colour_end_return")
                    is True
                    and visual_skin.metadata.get("tyre_visual_occlusion")
                    is True
                    and visual_skin.metadata.get(
                        "covers_tyre_upper_projection"
                    )
                    is True
                    and visual_skin.metadata.get(
                        "underlying_end_return_connected_to_crown_brep"
                    )
                    is True
                    and visual_skin.metadata.get(
                        "decorative_graphics_or_fake_seams"
                    )
                    is False
                    and abs(
                        float(
                            visual_skin.metadata.get(
                                "nominal_wall_thickness_mm",
                                0.0,
                            )
                        )
                        - WHEEL_END_VISUAL_SKIN_THICKNESS_MM
                    )
                    <= 0.01
                    and abs(
                        float(
                            visual_skin.metadata.get(
                                "dry_gap_to_underlying_end_return_mm",
                                -1.0,
                            )
                        )
                        - WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM
                    )
                    <= 0.01
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
                    and abs(
                        float(
                            visual_skin.metadata.get(
                                "lower_half_reveal_top_z_mm",
                                -1.0,
                            )
                        )
                        - WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM
                    )
                    <= 0.01
                    and visual_skin.metadata.get(
                        "half_wrap_boundary_equals_wheel_axis"
                    )
                    is True
                    and minimum_swept_clearance
                    >= WHEEL_MINIMUM_SWEPT_CLEARANCE_MM - 1.0e-4
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
                    and float(
                        belt.metadata.get(
                            "production_minimum_swept_tyre_clearance_target_mm",
                            0.0,
                        )
                    )
                    >= WHEEL_MINIMUM_SWEPT_CLEARANCE_MM
                    and product_width
                    <= WHEEL_PRODUCTION_WIDTH_LIMIT_MM + 0.01
                    and hub_articulation.get("status") == "PASS"
                    and lower_tyre_first_hit_pass
                    and cap.metadata.get("moves_with")
                    == "controlled_suspension_rocker_and_wheel_hub"
                    and gaiter.metadata.get("one_piece_flexible_diaphragm")
                    is True,
                    wheel_axis_z_mm=WHEEL_AXIS_Z_MM,
                    lower_half_reveal_top_z_mm=(
                        WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM
                    ),
                    side_probe_longitudinal_offsets_mm=(
                        WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM
                    ),
                    side_open_probe_z_mm=WHEEL_SIDE_OPEN_PROBE_Z_MM,
                    side_open_common_volume_mm3=round(side_open_common, 9),
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
                    end_open_common_volume_mm3=round(end_open_common, 9),
                    end_closed_probe_z_mm=WHEEL_END_CLOSED_PROBE_Z_MM,
                    measured_end_closed_wall_mm=round(end_closed_wall, 6),
                    end_return_opaque_coverage_grid_mm={
                        key: round(value, 6)
                        for key, value in end_coverage_walls.items()
                    },
                    body_colour_visual_end_return_skin=visual_skin.name,
                    body_colour_visual_skin_material=visual_material,
                    body_colour_visual_skin_bounds=(
                        visual_skin_box.to_dict()
                    ),
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
                        for key, value in (
                            visual_skin_coverage_walls.items()
                        )
                    },
                    sampled_sweep_clearance_mm={
                        angle: round(value, 6)
                        for angle, value in sweep_clearances.items()
                    },
                    measured_minimum_swept_clearance_mm=round(
                        minimum_swept_clearance, 6
                    ),
                    moving_hub_cap_and_gaiter_articulation=(
                        hub_articulation
                    ),
                    side_lower_tyre_first_hit_witnesses=(
                        side_tyre_first_hit
                    ),
                    front_or_rear_lower_tyre_first_hit_witnesses=(
                        end_tyre_first_hit
                    ),
                    required_minimum_swept_clearance_mm=(
                        WHEEL_MINIMUM_SWEPT_CLEARANCE_MM
                    ),
                    measured_product_width_mm=round(product_width, 6),
                    nominal_product_width_mm=WHEEL_NOMINAL_PRODUCT_WIDTH_MM,
                    production_width_design_limit_mm=(
                        WHEEL_PRODUCTION_WIDTH_LIMIT_MM
                    ),
                    requirement=(
                        "The outboard wheel side and both longitudinal returns "
                        "remain open below the z=125 wheel axis and close above "
                        "it. A body-colour upper impact skin, continuous crown "
                        "and opaque hub island hide the tyre upper projection "
                        "and drive while positive first-hit rays prove that the "
                        "lower semicircle is real controlled tyre, not empty "
                        "background.  The cap follows the hub and one flexible "
                        "diaphragm closes the fixed sweep opening. "
                        "The belt clears each tyre by at least 15.5 mm through "
                        "the sampled +/-10 degree sweep and remains within the "
                        "752 mm production width limit; overall wheel exposure "
                        "is forbidden."
                    ),
                )


def _validate_fixed_drive_control_contract(
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any,
) -> None:
    """Prove invariant exposed controls and deployed-table hand clearance."""

    control_names = (
        "A05_right_removable_drive_pod",
        "A05_right_joystick",
        "A05_right_authorisation_key",
    )
    controls: dict[str, dict[str, PartRecord]] = {}
    inventory_pass = True
    for state in STATES:
        state_controls: dict[str, PartRecord] = {}
        for name in control_names:
            matches = [
                part
                for part in parts
                if state in part.states
                and part.name == name
                and part.shape is not None
            ]
            if len(matches) != 1:
                inventory_pass = False
                continue
            state_controls[name] = matches[0]
        controls[state] = state_controls

    comparisons: dict[str, dict[str, Any]] = {}
    reference = controls.get("ride", {})
    for state in STATES:
        comparisons[state] = {}
        for name in control_names:
            if name not in reference or name not in controls[state]:
                inventory_pass = False
                continue
            evidence = _brep_pose_evidence(
                reference[name].shape,
                controls[state][name].shape,
            )
            comparisons[state][name] = evidence
            inventory_pass = inventory_pass and _brep_pose_matches(evidence)

    physical_ids = {
        state: {
            name: part.metadata.get("physical_occurrence_id")
            for name, part in controls[state].items()
        }
        for state in STATES
    }
    metadata_pass = all(
        len(controls[state]) == len(control_names)
        and all(
            part.metadata.get("same_physical_occurrence_all_states") is True
            and part.metadata.get("state_transition_never_deletes_occurrence")
            is True
            and part.metadata.get("state_pose") == "fixed_forward_armrest_top"
            and part.metadata.get("externally_visible_in_locked_state") is True
            and part.metadata.get("fixed_forward_armrest_location_all_states")
            is True
            and part.metadata.get("drive_enabled_in_locked_state")
            is (state == "ride")
            for part in controls[state].values()
        )
        for state in STATES
    )
    id_pass = (
        bool(reference)
        and all(physical_ids["ride"].values())
        and all(physical_ids[state] == physical_ids["ride"] for state in STATES)
    )
    checks.add(
        "controls.four_state.fixed_visible_reachable_ride_only_traction",
        inventory_pass and metadata_pass and id_pass,
        expected_occurrences=list(control_names),
        physical_occurrence_ids=physical_ids,
        fixed_pose_brep_comparisons=comparisons,
        expected_state_pose="fixed_forward_armrest_top",
        traction_enabled_state="ride",
        requirement=(
            "The exact same pod, upright joystick and authorisation key B-Reps "
            "remain exposed at the same forward right-armrest datum in all four "
            "states; electrical traction enable is Ride-only."
        ),
    )

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
            for part in parts
            if state in part.states
            and part.module.upper() == "A09"
            and part.shape is not None
        ]
        intersections = {
            part.name: _intersection_volume(hand_envelope, part.shape)
            for part in obstacles
        }
        distances = {
            part.name: _distance(hand_envelope, part.shape)
            for part in obstacles
        }
        limiting_name = min(distances, key=distances.get) if distances else None
        minimum = distances[limiting_name] if limiting_name else -math.inf
        checks.add(
            f"controls.{state}.operator_hand_clearance_to_deployed_table",
            bool(obstacles)
            and all(value <= 1.0e-5 for value in intersections.values())
            and minimum >= RIGHT_CONTROL_MINIMUM_TABLE_CLEARANCE_MM - 1.0e-4,
            hand_envelope_plan_radii_mm=(
                RIGHT_CONTROL_HAND_ENVELOPE_PLAN_RADII_MM
            ),
            hand_envelope_center_mm=RIGHT_CONTROL_HAND_ENVELOPE_CENTER_MM,
            hand_envelope_height_mm=RIGHT_CONTROL_HAND_ENVELOPE_HEIGHT_MM,
            required_minimum_clearance_mm=(
                RIGHT_CONTROL_MINIMUM_TABLE_CLEARANCE_MM
            ),
            measured_minimum_clearance_mm=round(minimum, 6),
            limiting_a09_occurrence=limiting_name,
            intersecting_a09_occurrences={
                name: round(value, 9)
                for name, value in intersections.items()
                if value > 1.0e-5
            },
            requirement=(
                "Cafe and Focus must retain at least 5 mm around the real "
                "operating-hand envelope at the fixed exposed joystick."
            ),
        )


def _validate_side_sail_and_a05_a06_trim_contract(
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any,
) -> None:
    """Independently prove hidden UWB skin and hinge trim clearances."""

    def one(state: str, name: str) -> PartRecord | None:
        matches = [
            part
            for part in parts
            if state in part.states
            and part.name == name
            and part.shape is not None
        ]
        return matches[0] if len(matches) == 1 else None

    for state in STATES:
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            sail = one(
                state,
                f"A04_A05_integrated_side_sail_{side_name}",
            )
            bezel = one(
                state,
                f"A04_side_uwb_replaceable_bezel_{side_name}",
            )
            drain = one(
                state,
                f"A05_table_cassette_lowpoint_drain_{side_name}",
            )
            if sail is None or bezel is None or drain is None:
                checks.add(
                    f"side_sail.{state}.{side_name}.hidden_uwb_skin_and_drain",
                    False,
                    missing_evidence=True,
                    requirement=(
                        "One RF-transparent side sail, UWB bezel and real "
                        "cassette drain are required per side."
                    ),
                )
                continue
            probe = (
                cq.Workplane("XY")
                .box(1.0, 4.0, 1.0)
                .translate((-75.0, side * 369.5, 400.0))
                .val()
            )
            section = sail.shape.intersect(probe)
            measured_outer_skin = (
                0.0 if section.isNull() else float(section.BoundingBox().ylen)
            )
            bezel_common = _intersection_volume(sail.shape, bezel.shape)
            bezel_gap = _distance(sail.shape, bezel.shape)
            drain_common = _intersection_volume(sail.shape, drain.shape)
            checks.add(
                f"side_sail.{state}.{side_name}.hidden_uwb_skin_and_drain",
                sail.shape.isValid()
                and len(sail.shape.Solids()) == 1
                and bezel_common <= 1.0e-5
                and bezel_gap >= 0.29
                and drain_common <= 1.0e-5
                and measured_outer_skin >= 1.2 - 1.0e-4
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
                and sail.metadata.get("hidden_rf_transmission_zone") is True,
                measured_remaining_outer_skin_mm=round(
                    measured_outer_skin,
                    6,
                ),
                required_remaining_outer_skin_mm=1.2,
                sail_to_bezel_common_mm3=round(bezel_common, 9),
                sail_to_bezel_gap_mm=round(bezel_gap, 6),
                sail_to_drain_common_mm3=round(drain_common, 9),
                requirement=(
                    "The UWB uses only a shallow inner recess under at least "
                    "1.2 mm of continuous exterior skin; the bezel and drain "
                    "must have zero rigid interference."
                ),
            )

    for state in STATES:
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            shell = one(
                state,
                f"A05_armrest_table_bay_shell_{side_name}",
            )
            bearing = one(
                state,
                f"A06_backrest_hinge_bearing_{side_name}",
            )
            shaft = one(state, "A06_backrest_hinge_shaft")
            if shell is None or bearing is None or shaft is None:
                checks.add(
                    f"hinge_trim.{state}.{side_name}.a05_shell_clearances",
                    False,
                    missing_evidence=True,
                )
                continue
            disc_center_y = side * A06_LOCK_STATION_Y_MM
            disc = cq.Solid.makeCylinder(
                A06_LOCK_DISC_RADIUS_MM,
                A06_LOCK_DISC_AXIAL_MM,
                cq.Vector(
                    A06_A07_COMMON_FOLD_HINGE_MM[0],
                    disc_center_y - A06_LOCK_DISC_AXIAL_MM / 2.0,
                    A06_A07_COMMON_FOLD_HINGE_MM[2],
                ),
                cq.Vector(0.0, 1.0, 0.0),
            )
            bearing_common = _intersection_volume(shell.shape, bearing.shape)
            bearing_gap = _distance(shell.shape, bearing.shape)
            shaft_common = _intersection_volume(shell.shape, shaft.shape)
            shaft_gap = _distance(shell.shape, shaft.shape)
            disc_common = _intersection_volume(shell.shape, disc)
            disc_gap = _distance(shell.shape, disc)
            checks.add(
                f"hinge_trim.{state}.{side_name}.a05_shell_clearances",
                shell.shape.isValid()
                and len(shell.shape.Solids()) == 1
                and bearing_common <= 1.0e-5
                and bearing_gap >= 0.59
                and shaft_common <= 1.0e-5
                and shaft_gap >= 0.69
                and disc_common <= 1.0e-5
                and disc_gap >= 0.69
                and shell.metadata.get("a06_fixed_bearing_seat_present") is True
                and float(
                    shell.metadata.get(
                        "a06_lock_disc_axial_clearance_each_side_mm",
                        0.0,
                    )
                )
                >= 0.7,
                bearing_common_mm3=round(bearing_common, 9),
                bearing_gap_mm=round(bearing_gap, 6),
                complete_shaft_common_mm3=round(shaft_common, 9),
                complete_shaft_gap_mm=round(shaft_gap, 6),
                lock_disc_common_mm3=round(disc_common, 9),
                lock_disc_gap_mm=round(disc_gap, 6),
                requirement=(
                    "Each A05 root shell remains one valid solid and has zero "
                    "interference plus the released 0.6/0.7 mm trim clearance "
                    "to the A06 bearing, complete shaft and lock disc."
                ),
            )

    # The obsolete exterior A09 post-relief audit was removed with the post
    # stack.  Focus now uses a small inner-sidewall port, flat in-cavity guides
    # and a state-invariant metal cassette; those parts are validated by the
    # final A09 layout architecture checks.


def _validate_a06_hollow_and_fixed_root_shoulders(
    parts: Sequence[PartRecord],
    checks: Checks,
    cq: Any,
) -> None:
    """Independently verify the hollow A06 and conserved fixed A04 shoulders."""

    def one(state: str, name: str) -> PartRecord | None:
        matches = [
            part
            for part in parts
            if state in part.states and part.name == name and part.shape is not None
        ]
        return matches[0] if len(matches) == 1 else None

    reference_backrest = one("ride", "A06_backrest_weather_shell")
    for state in STATES:
        backrest = one(state, "A06_backrest_weather_shell")
        if backrest is None or reference_backrest is None:
            checks.add(
                f"a06.manufacturing_hollow_shell.{state}",
                False,
                missing_evidence=True,
            )
            continue
        normalised = backrest.shape
        if state == "follow":
            normalised = _rotate_about_a06_a07_hinge(
                normalised,
                -A06_A07_FOLLOW_FOLD_DEG,
            )
        normalised = _rotate_about_a06_a07_hinge(normalised, -6.0)
        void_probe = (
            cq.Workplane("XY")
            .box(2.0, 2.0, 2.0)
            .translate((258.5, 150.0, 800.0))
            .val()
        )
        void_common = _intersection_volume(normalised, void_probe)
        walls: dict[str, float] = {}
        for side_name, y in (("left", -230.0), ("right", 230.0)):
            probe = (
                cq.Workplane("XY")
                .box(1.0, 12.0, 1.0)
                .translate((258.5, y, 800.0))
                .val()
            )
            section = normalised.intersect(probe)
            volume = float(section.Volume())
            walls[side_name] = (
                0.0 if volume <= 1.0e-5 else float(section.BoundingBox().ylen)
            )
        checks.add(
            f"a06.manufacturing_hollow_shell.{state}",
            backrest.metadata.get("manufacturing_hollow_shell") is True
            and abs(
                float(
                    backrest.metadata.get(
                        "manufacturing_shell_nominal_wall_mm",
                        -1.0,
                    )
                )
                - 4.0
            )
            <= 0.01
            and void_common <= 1.0e-5
            and all(3.8 <= value <= 4.2 for value in walls.values()),
            manufacturing_void_common_volume_mm3=round(void_common, 9),
            measured_side_wall_mm={
                key: round(value, 6) for key, value in walls.items()
            },
            requirement=(
                "The conserved A06 is a real hollow monocoque with measured "
                "four-millimetre side walls, not a render-only solid block."
            ),
        )

    expected = {
        "A04_backrest_root_shoulder_left",
        "A04_backrest_root_shoulder_right",
    }
    inventories = {
        state: sorted(
            part.name
            for part in parts
            if state in part.states
            and part.name.startswith("A04_backrest_root_shoulder_")
        )
        for state in STATES
    }
    forbidden = {
        state: sorted(
            part.name
            for part in parts
            if state in part.states
            and part.name.startswith("A06_backrest_root_cheek_")
        )
        for state in STATES
    }
    checks.add(
        "a04_a06.fixed_root_shoulders.inventory",
        all(set(inventories[state]) == expected for state in STATES)
        and all(not forbidden[state] for state in STATES),
        inventories=inventories,
        forbidden_a06_cheeks=forbidden,
        requirement=(
            "Two fixed A04 root shoulders remain present in every state and "
            "replace all state-specific A06 cheek fragments."
        ),
    )
    for side_name in ("left", "right"):
        name = f"A04_backrest_root_shoulder_{side_name}"
        shoulder_by_state = {state: one(state, name) for state in STATES}
        reference = shoulder_by_state["ride"]
        passed = reference is not None
        evidence: dict[str, Any] = {}
        if reference is not None:
            reference_id = reference.metadata.get("physical_occurrence_id")
            for state, shoulder in shoulder_by_state.items():
                backrest = one(state, "A06_backrest_weather_shell")
                if shoulder is None or backrest is None:
                    passed = False
                    evidence[state] = {"missing": True}
                    continue
                comparison = _brep_pose_evidence(reference.shape, shoulder.shape)
                common = _intersection_volume(shoulder.shape, backrest.shape)
                clearance = _distance(shoulder.shape, backrest.shape)
                passed = passed and (
                    shoulder.module.upper() == "A04"
                    and shoulder.metadata.get("physical_occurrence_id")
                    == reference_id
                    and shoulder.metadata.get("fixed_to") == "A04_body"
                    and shoulder.metadata.get("same_brep_all_states") is True
                    and shoulder.metadata.get("state_specific_substitute") is False
                    and abs(float(shoulder.metadata.get("nominal_wall_mm", -1.0)) - 4.0)
                    <= 0.01
                    and common <= 1.0e-5
                    and clearance >= 4.0 - 1.0e-6
                    and _brep_pose_matches(comparison)
                )
                evidence[state] = {
                    "comparison": comparison,
                    "a06_common_volume_mm3": round(common, 9),
                    "a06_clearance_mm": round(clearance, 6),
                }
        checks.add(
            f"a04_a06.fixed_root_shoulder.{side_name}",
            passed,
            missing_evidence=reference is None,
            states=evidence,
        )


def _validate_clearances(
    root: Path,
    parts: Sequence[PartRecord],
    payload: Mapping[str, Any],
    checks: Checks,
    cq: Any | None,
    search_roots: Sequence[Path],
) -> None:
    if cq is None:
        for family, required in (("tyre", 12.0), ("rocker", 3.0), ("mast", 3.0)):
            _fallback_clearance(family, required, payload, checks)
        return

    resolved = 0
    for part in parts:
        try:
            if _shape_of(part, search_roots, cq) is not None:
                resolved += 1
        except Exception as exc:
            checks.add(
                f"geometry.skin_step_readable.{part.name}",
                False,
                missing_evidence=True,
                severity="warning",
                error=str(exc),
            )
    checks.add(
        "geometry.skin_solids_resolved",
        resolved == len(parts) and resolved > 0,
        missing_evidence=resolved == 0,
        severity="warning" if resolved else "hard",
        resolved=resolved,
        total=len(parts),
    )
    if resolved == 0:
        for family, required in (("tyre", 12.0), ("rocker", 3.0), ("mast", 3.0)):
            _fallback_clearance(family, required, payload, checks)
        return

    _validate_a07_brep_contract(parts, checks, cq)
    _validate_a06_hollow_and_fixed_root_shoulders(parts, checks, cq)
    _validate_fixed_drive_control_contract(parts, checks, cq)
    _validate_side_sail_and_a05_a06_trim_contract(parts, checks, cq)
    _validate_wheel_contact_band_contract(parts, checks, cq)

    source_part_dir = root / "build" / "parts"

    # Four tyre envelopes remain fixed in every user state.  All non-wheel-
    # attached Class-A solids must clear the actual tyre B-Reps by 12 mm.
    for state in STATES:
        state_skin = [part for part in parts if state in part.states and part.shape is not None and not _clearance_exempt(part, "tyre")]
        for corner in ("front_left", "front_right", "rear_left", "rear_right"):
            source_path = source_part_dir / f"tyre_{corner}.step"
            target = cq.importers.importStep(str(source_path)).val()
            minimum, nearest = _minimum_clearance_to_target(state_skin, target, 12.0)
            checks.add(
                f"clearance.{state}.tyre_{corner}",
                minimum >= 12.0 - 1e-6,
                missing_evidence=nearest is None,
                actual_mm=round(minimum, 3) if math.isfinite(minimum) else None,
                required_mm=12.0,
                nearest_skin_part=nearest,
            )

    # Rocker B-Reps are swept through the controlled +/-10 degree articulation.
    rocker_x = (-380.0 + 180.0) / 2.0
    for state in STATES:
        state_skin = [part for part in parts if state in part.states and part.shape is not None and not _clearance_exempt(part, "rocker")]
        for side in ("left", "right"):
            source_path = source_part_dir / f"suspension_rocker_{side}.step"
            source = cq.importers.importStep(str(source_path)).val()
            minimum = math.inf
            nearest = None
            worst_angle = None
            for angle in (-10.0, -5.0, 0.0, 5.0, 10.0):
                target = source if angle == 0.0 else source.rotate((rocker_x, 0.0, 125.0), (rocker_x, 1.0, 125.0), angle)
                distance, part_name = _minimum_clearance_to_target(state_skin, target, 3.0)
                if distance < minimum:
                    minimum, nearest, worst_angle = distance, part_name, angle
            checks.add(
                f"clearance.{state}.rocker_{side}_full_sweep",
                minimum >= 3.0 - 1e-6,
                missing_evidence=nearest is None,
                actual_mm=round(minimum, 3) if math.isfinite(minimum) else None,
                required_mm=3.0,
                nearest_skin_part=nearest,
                worst_angle_deg=worst_angle,
                sampled_angles_deg=[-10.0, -5.0, 0.0, 5.0, 10.0],
            )

    for state in STATES:
        mast_parts = [
            part
            for part in parts
            if state in part.states
            and part.shape is not None
            and part.module.upper() == "A07"
        ]
        dry_running_mast_parts = [
            part
            for part in mast_parts
            if part.metadata.get("fixed_to_backrest_channel") is not True
        ]
        compliant_seal_parts = [
            part.name
            for part in mast_parts
            if part.metadata.get("fixed_to_backrest_channel") is True
        ]
        state_skin = [
            part
            for part in parts
            if state in part.states
            and part.shape is not None
            and part.module.upper() != "A07"
            and not _clearance_exempt(part, "mast")
        ]
        minimum = math.inf
        nearest = None
        governing_mast_part = None
        for mast_part in dry_running_mast_parts:
            distance, part_name = _minimum_clearance_to_target(
                state_skin,
                mast_part.shape,
                0.5,
            )
            if distance < minimum:
                minimum = distance
                nearest = part_name
                governing_mast_part = mast_part.name
        checks.add(
            f"clearance.{state}.mast_telescoping_member",
            minimum >= 0.5 - 1e-6,
            missing_evidence=nearest is None or not dry_running_mast_parts,
            actual_mm=round(minimum, 3) if math.isfinite(minimum) else None,
            required_mm=0.5,
            nearest_skin_part=nearest,
            governing_mast_part=governing_mast_part,
            actual_final_a07_part_count=len(mast_parts),
            dry_running_a07_part_count=len(dry_running_mast_parts),
            intentional_compliant_seal_occurrences=compliant_seal_parts,
            source_proxy=(
                "resolved final-state A07 BReps; Follow uses the shared A06/A07 "
                "hinge pose and Ride/Cafe retain the readable low beam"
            ),
        )


def _validate_part_integrity(parts: Sequence[PartRecord], checks: Checks) -> None:
    names_by_state: dict[str, set[str]] = {state: set() for state in STATES}
    for part in parts:
        for state in part.states:
            prefix = f"part.{state}.{part.name}"
            checks.add(
                f"{prefix}.bounds_positive",
                part.bounds.xlen > 0
                and part.bounds.ylen > 0
                and part.bounds.zlen > 0,
                bounds=part.bounds.to_dict(),
            )
            checks.add(
                f"{prefix}.module_assigned",
                bool(part.module and part.module != "unassigned"),
                missing_evidence=not part.module or part.module == "unassigned",
                module=part.module,
            )
            checks.add(
                f"{prefix}.configuration_assigned",
                bool(part.states),
                missing_evidence=not part.states,
                configurations=sorted(part.states),
            )
            duplicate = part.name in names_by_state[state]
            checks.add(
                f"part_name_unique.{state}.{part.name}",
                not duplicate,
                configuration=state,
            )
            names_by_state[state].add(part.name)
            if part.shape is not None:
                shape = part.shape.val() if hasattr(part.shape, "val") else part.shape
                try:
                    checks.add(
                        f"{prefix}.solid_valid",
                        not shape.isNull()
                        and shape.isValid()
                        and shape.Volume() > 0.0
                        and len(shape.Solids()) == 1,
                        solid_count=len(shape.Solids()),
                    )
                except Exception as exc:
                    checks.add(f"{prefix}.solid_valid", False, error=str(exc))


def _validate_source_disposition(
    root: Path,
    parts: Sequence[PartRecord],
    checks: Checks,
) -> None:
    """Fail closed unless every controlled GLB occurrence has one final owner."""

    try:
        from source_disposition import build_all_ledgers, validate_ledgers

        available = {
            state: {part.name for part in parts if state in part.states}
            for state in STATES
        }
        ledgers = build_all_ledgers(repository_root=root)
        result = validate_ledgers(
            ledgers,
            repository_root=root,
            available_proxies_by_state=available,
        )
    except Exception as exc:
        checks.add(
            "presentation.source_disposition_complete",
            False,
            missing_evidence=True,
            error=str(exc),
        )
        return

    checks.add(
        "presentation.source_disposition_complete",
        result.get("status") == "PASS"
        and int(result.get("unknown", -1)) == 0
        and int(result.get("duplicates", -1)) == 0
        and int(result.get("extra", -1)) == 0,
        controlled_occurrences=result.get("total_controlled_occurrences"),
        ledger_occurrences=result.get("total_ledger_occurrences"),
        unknown=result.get("unknown"),
        duplicates=result.get("duplicates"),
        extra=result.get("extra"),
        errors=result.get("errors"),
    )
    for state in STATES:
        state_report = result.get("state_reports", {}).get(state, {})
        checks.add(
            f"presentation.{state}.source_disposition_complete",
            bool(state_report)
            and int(state_report.get("unknown", -1)) == 0
            and int(state_report.get("duplicates", -1)) == 0
            and int(state_report.get("extra", -1)) == 0
            and int(state_report.get("controlled_occurrences", -1))
            == int(state_report.get("ledger_occurrences", -2)),
            **state_report,
        )


def validate_class_a(
    *,
    parts: Any = None,
    manifest: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    workspace_root: Path | str | None = None,
    search_roots: Sequence[Path | str] = (),
    allow_missing_evidence: bool = False,
    source_only: bool = False,
) -> dict[str, Any]:
    """Validate a Class-A skin and return a JSON-serializable report.

    This is the preferred in-process API for the exterior builder.  Pass either
    a flat iterable or a ``{configuration: [SkinPart, ...]}`` mapping.  The
    function performs no file writes.
    """

    root = _workspace_root(Path(workspace_root) if workspace_root else None)
    checks = Checks(allow_missing_evidence=allow_missing_evidence)
    _validate_source_steps(root, checks)
    payload: dict[str, Any] = dict(manifest or {})
    if evidence:
        payload.setdefault("validation_evidence", dict(evidence))

    records: list[PartRecord] = []
    if parts is not None:
        records = _flatten_parts(parts, root)
    elif payload:
        records = _extract_parts(payload, root)

    if not source_only:
        checks.add(
            "input.class_a_parts_present",
            bool(records),
            missing_evidence=not records,
            part_count=len(records),
        )
        if records:
            _validate_part_integrity(records, checks)
            _validate_source_disposition(root, records, checks)
            cq = _import_cadquery()
            _validate_envelopes(root, records, checks, cq)
            _validate_feature_geometry(records, checks)
            _validate_final_appearance_coverage(records, checks)
            openings = _extract_openings(payload, records)
            _validate_openings(openings, checks)
            roots = [Path(value).resolve() for value in search_roots]
            roots.extend([root / "design" / "e6_final_exterior" / "step_anchored_v2" / "class_a_cad"])
            _validate_clearances(root, records, payload, checks, cq, roots)
            if cq is not None:
                _validate_functional_corridors(root, records, checks, cq, roots)

    hard_failures = checks.hard_failures
    status = "FAIL" if hard_failures else "PASS"
    if not hard_failures and checks.warnings:
        status = "PASS_WITH_WARNINGS"
    return {
        "schema_version": 1,
        "validator": "WorkCore E6 STEP-anchored Class-A validator",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(root),
        "source_revision": "E6-DFR5-A07-SHARED-HINGE",
        "scope": (
            "independent exterior skin; E6-DFR5-A07-SHARED-HINGE primary STEP "
            "files and preserved E6-DFR3 auxiliary STEP files are read-only underlays"
        ),
        "status": status,
        "summary": {
            "check_count": len(checks.items),
            "hard_failure_count": len(hard_failures),
            "warning_count": len(checks.warnings),
            "skin_part_count": len(records),
        },
        "hard_failures": [item["id"] for item in hard_failures],
        "warnings": [item["id"] for item in checks.warnings],
        "checks": checks.items,
    }


def _write_report(report: Mapping[str, Any], output: str, root: Path, pretty: bool) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)
    if output == "-":
        print(text)
        return
    path = Path(output)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    build = (root / "build").resolve()
    try:
        path.relative_to(build)
    except ValueError:
        pass
    else:
        raise ValueError("Validation reports may not be written into the controlled build/ tree")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text + "\n", encoding="utf-8")
    temporary.replace(path)
    print(text)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Class-A manifest JSON")
    parser.add_argument("--parts-module", type=Path, action="append", default=[], help="Python provider module; may be repeated")
    parser.add_argument("--step-root", type=Path, action="append", default=[], help="Additional exported STEP search root")
    parser.add_argument("--workspace-root", type=Path, help="Override automatic workcore root discovery")
    parser.add_argument("--output", default="-", help="Report path, or '-' for stdout (default)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--source-only", action="store_true", help="Only verify the four immutable source STEP files")
    parser.add_argument(
        "--allow-missing-evidence",
        action="store_true",
        help="Downgrade absent design evidence to warnings; measured violations still fail",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = _workspace_root(args.workspace_root)
    payload: dict[str, Any] = {}
    records: list[PartRecord] = []
    search_roots = [path.resolve() for path in args.step_root]

    if args.manifest:
        manifest_path = args.manifest.resolve()
        payload, records = _load_json_manifest(manifest_path)
        search_roots.append(manifest_path.parent)
    for provider in args.parts_module:
        provider_path = provider.resolve()
        provider_payload, provider_records = _provider_payload(provider_path)
        records.extend(provider_records)
        search_roots.append(provider_path.parent)
        for key, value in provider_payload.items():
            if key not in {"parts", "skin_parts", "configurations"}:
                payload.setdefault(key, value)

    report = validate_class_a(
        parts=records if records else None,
        manifest=payload,
        workspace_root=root,
        search_roots=search_roots,
        allow_missing_evidence=args.allow_missing_evidence,
        source_only=args.source_only,
    )
    _write_report(report, args.output, root, args.pretty)
    return 1 if report["summary"]["hard_failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
