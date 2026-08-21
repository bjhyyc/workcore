"""Independent V8 CAD/release-integrity quality gates.

These gates verify pinned inputs, report integrity, exported B-Rep geometry,
GLB unit/inventory consistency, and release-set closure.  They are engineering
evidence checks only: passing them is not a physical test, safety certification,
regulatory approval, or production certification.

The module deliberately has no CadQuery, OCP, NumPy, or trimesh imports at
module-import time.  Geometry dependencies are loaded only by the gates that
need them, so builders can import the lightweight report/hash gates in a clean
Python process.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


PINNED_RELEASE_MANIFEST_SHA256 = (
    "47d60408ec65e401ca95d630cd090a9f36443399e36cc1a3e1e64e3c9e09260a"
)

_CLASS_A_RELATIVE_ROOT = PurePosixPath(
    "design/e6_final_exterior/step_anchored_v2/class_a_cad"
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_BBOX_KEYS = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
_DIRECT_REPO_PREFIXES = frozenset(
    {"build", "design", "docs", "firmware", "hardware", "mechanical", "qa", "src", "tests"}
)


class QAGateError(RuntimeError):
    """Base error for a failed V8 QA gate.

    ``report`` is JSON-serialisable and contains all failures collected before
    the gate stopped.  Builders should persist it in their own output location
    if failed-gate evidence is required; this module never writes reports.
    """

    gate = "v8_qa"

    def __init__(self, message: str, report: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = dict(report or {})


class InputPinError(QAGateError):
    gate = "pin_and_verify_consumed_inputs"


class CheckIdError(QAGateError):
    gate = "assert_unique_check_ids"


class EvidenceAnnotationError(QAGateError):
    gate = "annotate_evidence_kinds"


class ExportedStepValidationError(QAGateError):
    gate = "validate_exported_part_steps"


class GLBValidationError(QAGateError):
    gate = "validate_glb_units_and_inventory"


class ArtifactSetError(QAGateError):
    gate = "validate_closed_artifact_set"


class CollisionGateError(QAGateError):
    gate = "rigid_pair_collision_report"


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalise_relative_path(value: str | os.PathLike[str], *, label: str) -> str:
    raw = os.fspath(value).strip().replace("\\", "/")
    if not raw:
        raise ValueError(f"{label} is empty")
    if raw.startswith("/") or raw.startswith("//") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"{label} must be relative, got {raw!r}")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} contains an unsafe path segment: {raw!r}")
    return path.as_posix()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_path_under(
    root: Path,
    value: str | os.PathLike[str],
    *,
    label: str,
    allow_absolute: bool = False,
) -> Path:
    root = root.resolve()
    raw = Path(os.fspath(value))
    if raw.is_absolute():
        if not allow_absolute:
            raise ValueError(f"{label} must be relative to {root}: {raw}")
        candidate = raw.resolve()
    else:
        relative = _normalise_relative_path(value, label=label)
        candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if not _is_within(candidate, root):
        raise ValueError(f"{label} escapes its allowed root {root}: {candidate}")
    return candidate


def _repo_relative_path(
    repo_root: Path, value: str | os.PathLike[str], *, label: str
) -> tuple[str, Path]:
    repo_root = repo_root.resolve()
    raw = Path(os.fspath(value))
    if raw.is_absolute():
        candidate = raw.resolve()
        if not _is_within(candidate, repo_root):
            raise ValueError(f"{label} is outside repo_root: {candidate}")
        relative = candidate.relative_to(repo_root).as_posix()
    else:
        relative = _normalise_relative_path(value, label=label)
        candidate = _safe_path_under(repo_root, relative, label=label)
    return relative, candidate


def _load_mapping(
    value: Mapping[str, Any] | str | os.PathLike[str],
    *,
    repo_root: Path | None = None,
    label: str = "manifest",
) -> tuple[dict[str, Any], Path | None]:
    if isinstance(value, Mapping):
        return dict(value), None
    path = Path(os.fspath(value))
    if not path.is_absolute() and repo_root is not None:
        path = _safe_path_under(repo_root, path, label=label)
    else:
        path = path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return dict(payload), path


def _require_sequence(value: Any, *, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array, not {type(value).__name__}")
    return value


def _failure_message(gate: str, failures: Sequence[Mapping[str, Any]]) -> str:
    first = failures[0] if failures else {}
    code = first.get("code", "unknown_failure")
    detail = first.get("detail") or first.get("path") or first.get("part") or ""
    suffix = f": {detail}" if detail else ""
    return f"{gate} failed with {len(failures)} error(s); first={code}{suffix}"


def pin_and_verify_consumed_inputs(
    repo_root: str | os.PathLike[str],
    paths: Sequence[str | os.PathLike[str]],
    *,
    release_manifest_path: str | os.PathLike[str] = "build/release_manifest.json",
    expected_manifest_sha256: str = PINNED_RELEASE_MANIFEST_SHA256,
) -> dict[str, Any]:
    """Pin the controlled release manifest and verify every consumed input.

    The manifest itself is authenticated against ``expected_manifest_sha256``.
    Each requested path must then have an exact ``path``/``bytes``/``sha256``
    entry in ``artifacts.files``.  Paths may be repo-relative or absolute paths
    inside ``repo_root``; path traversal and duplicate logical paths are rejected.
    """

    root = Path(repo_root).resolve()
    failures: list[dict[str, Any]] = []
    expected_digest = str(expected_manifest_sha256).lower()
    if not _SHA256_RE.fullmatch(expected_digest):
        failures.append(
            {
                "code": "invalid_expected_manifest_sha256",
                "detail": "expected_manifest_sha256 must be exactly 64 hexadecimal characters",
            }
        )

    try:
        manifest_relative, manifest_path = _repo_relative_path(
            root, release_manifest_path, label="release_manifest_path"
        )
    except ValueError as exc:
        failures.append({"code": "unsafe_release_manifest_path", "detail": str(exc)})
        manifest_relative, manifest_path = str(release_manifest_path), None

    manifest_digest: str | None = None
    manifest: dict[str, Any] | None = None
    if manifest_path is not None:
        if not manifest_path.is_file():
            failures.append(
                {
                    "code": "release_manifest_missing",
                    "path": manifest_relative,
                    "detail": f"file does not exist: {manifest_path}",
                }
            )
        else:
            manifest_digest = _sha256_file(manifest_path)
            if _SHA256_RE.fullmatch(expected_digest) and manifest_digest != expected_digest:
                failures.append(
                    {
                        "code": "release_manifest_digest_mismatch",
                        "path": manifest_relative,
                        "expected_sha256": expected_digest,
                        "actual_sha256": manifest_digest,
                    }
                )
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, Mapping):
                    raise ValueError("top-level JSON value is not an object")
                manifest = dict(loaded)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                failures.append(
                    {
                        "code": "release_manifest_invalid_json",
                        "path": manifest_relative,
                        "detail": str(exc),
                    }
                )

    file_index: dict[str, dict[str, Any]] = {}
    if manifest is not None:
        artifact_block = manifest.get("artifacts")
        raw_files = artifact_block.get("files") if isinstance(artifact_block, Mapping) else None
        try:
            manifest_files = _require_sequence(raw_files, label="release_manifest.artifacts.files")
        except ValueError as exc:
            failures.append({"code": "manifest_files_missing", "detail": str(exc)})
            manifest_files = []
        casefold_paths: dict[str, str] = {}
        for index, raw_entry in enumerate(manifest_files):
            if not isinstance(raw_entry, Mapping):
                failures.append(
                    {
                        "code": "invalid_manifest_file_entry",
                        "index": index,
                        "detail": "entry must be an object",
                    }
                )
                continue
            try:
                rel = _normalise_relative_path(
                    raw_entry.get("path", ""), label=f"artifacts.files[{index}].path"
                )
            except (TypeError, ValueError) as exc:
                failures.append(
                    {"code": "unsafe_manifest_file_path", "index": index, "detail": str(exc)}
                )
                continue
            folded = rel.casefold()
            if rel in file_index or folded in casefold_paths:
                failures.append(
                    {
                        "code": "duplicate_manifest_file_path",
                        "path": rel,
                        "first_path": casefold_paths.get(folded, rel),
                        "index": index,
                    }
                )
                continue
            file_index[rel] = dict(raw_entry)
            casefold_paths[folded] = rel

    try:
        consumed = _require_sequence(paths, label="paths")
    except ValueError as exc:
        failures.append({"code": "invalid_consumed_paths", "detail": str(exc)})
        consumed = []

    requested: list[tuple[str, Path]] = []
    requested_casefold: dict[str, str] = {}
    for index, raw_path in enumerate(consumed):
        try:
            rel, actual_path = _repo_relative_path(root, raw_path, label=f"paths[{index}]")
        except (TypeError, ValueError) as exc:
            failures.append({"code": "unsafe_consumed_path", "index": index, "detail": str(exc)})
            continue
        folded = rel.casefold()
        if folded in requested_casefold:
            failures.append(
                {
                    "code": "duplicate_consumed_path",
                    "path": rel,
                    "first_path": requested_casefold[folded],
                }
            )
            continue
        requested_casefold[folded] = rel
        requested.append((rel, actual_path))

    checked: list[dict[str, Any]] = []
    for rel, actual_path in requested:
        entry = file_index.get(rel)
        if entry is None:
            failures.append({"code": "consumed_path_not_in_manifest", "path": rel})
            continue
        expected_bytes = entry.get("bytes")
        expected_sha = str(entry.get("sha256", "")).lower()
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
            failures.append(
                {
                    "code": "invalid_manifest_byte_count",
                    "path": rel,
                    "detail": f"expected non-negative integer, got {expected_bytes!r}",
                }
            )
            continue
        if not _SHA256_RE.fullmatch(expected_sha):
            failures.append(
                {
                    "code": "invalid_manifest_file_sha256",
                    "path": rel,
                    "detail": "sha256 must be 64 hexadecimal characters",
                }
            )
            continue
        if not actual_path.is_file():
            failures.append({"code": "consumed_file_missing", "path": rel})
            continue
        stat_bytes = actual_path.stat().st_size
        actual_sha = _sha256_file(actual_path)
        if stat_bytes != expected_bytes:
            failures.append(
                {
                    "code": "consumed_file_byte_count_mismatch",
                    "path": rel,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": stat_bytes,
                }
            )
        if actual_sha != expected_sha:
            failures.append(
                {
                    "code": "consumed_file_digest_mismatch",
                    "path": rel,
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                }
            )
        checked.append(
            {
                "path": rel,
                "bytes": stat_bytes,
                "sha256": actual_sha,
                "manifest_bytes": expected_bytes,
                "manifest_sha256": expected_sha,
                "status": "PASS" if stat_bytes == expected_bytes and actual_sha == expected_sha else "FAIL",
            }
        )

    report: dict[str, Any] = {
        "gate": "pin_and_verify_consumed_inputs",
        "status": "FAIL" if failures else "PASS",
        "release_manifest": {
            "path": manifest_relative,
            "expected_sha256": expected_digest,
            "actual_sha256": manifest_digest,
            "pinned": bool(manifest_digest and manifest_digest == expected_digest),
        },
        "requested_count": len(consumed),
        "checked_count": len(checked),
        "checked": checked,
        "failures": failures,
        "certification_scope": "CAD/release-integrity evidence only; not physical certification",
    }
    if failures:
        raise InputPinError(_failure_message("input pin gate", failures), report)
    return report


def assert_unique_check_ids(report: Mapping[str, Any], phase: str) -> dict[str, Any]:
    """Fail unless every check in ``report['checks']`` has a unique, non-empty ID."""

    if not isinstance(report, Mapping):
        raise CheckIdError(
            "check-ID gate failed: report must be a mapping",
            {"gate": "assert_unique_check_ids", "phase": str(phase), "status": "FAIL"},
        )
    try:
        checks = _require_sequence(report.get("checks"), label="report.checks")
    except ValueError as exc:
        result = {
            "gate": "assert_unique_check_ids",
            "phase": str(phase),
            "status": "FAIL",
            "failures": [{"code": "checks_missing", "detail": str(exc)}],
        }
        raise CheckIdError(str(exc), result) from exc

    positions: dict[str, list[int]] = {}
    invalid: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            invalid.append(
                {"code": "check_not_object", "index": index, "type": type(check).__name__}
            )
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            invalid.append({"code": "missing_check_id", "index": index, "value": check_id})
            continue
        positions.setdefault(check_id.strip(), []).append(index)

    duplicates = [
        {"id": check_id, "positions": indexes, "occurrences": len(indexes)}
        for check_id, indexes in positions.items()
        if len(indexes) > 1
    ]
    duplicates.sort(key=lambda item: item["positions"][0])
    failures = invalid + [dict(item, code="duplicate_check_id") for item in duplicates]
    result = {
        "gate": "assert_unique_check_ids",
        "phase": str(phase),
        "status": "FAIL" if failures else "PASS",
        "check_count": len(checks),
        "unique_id_count": len(positions),
        "duplicate_id_count": len(duplicates),
        "duplicates": duplicates,
        "failures": failures,
    }
    if failures:
        raise CheckIdError(_failure_message(f"check-ID gate ({phase})", failures), result)
    return result


_EVIDENCE_KIND_ORDER = (
    "BRep_boolean",
    "BRep_measurement",
    "topology_integrity",
    "hash_integrity",
    "name_presence",
    "metadata_contract",
    "process_assertion",
    "unclassified",
)
_EVIDENCE_LAYERS = {
    "direct_geometry": ("BRep_boolean", "BRep_measurement", "topology_integrity"),
    "file_and_inventory": ("hash_integrity", "name_presence"),
    "declared_contract": ("metadata_contract", "process_assertion"),
    "unclassified": ("unclassified",),
}


def _check_passed(check: Mapping[str, Any]) -> bool | None:
    for key in ("pass", "passed", "ok"):
        value = check.get(key)
        if isinstance(value, bool):
            return value
    status = check.get("status")
    if isinstance(status, str):
        normalised = status.strip().upper()
        if normalised in {"PASS", "PASSED", "OK"}:
            return True
        if normalised in {"FAIL", "FAILED", "ERROR"}:
            return False
    return None


def _classify_evidence(check: Mapping[str, Any]) -> tuple[str, list[str]]:
    def nested_keys(value: Any, depth: int = 0) -> set[str]:
        if depth > 4:
            return set()
        if isinstance(value, Mapping):
            result = {str(key).casefold() for key in value.keys()}
            for nested in value.values():
                result.update(nested_keys(nested, depth + 1))
            return result
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            result: set[str] = set()
            for nested in value[:50]:
                result.update(nested_keys(nested, depth + 1))
            return result
        return set()

    keys = nested_keys(check)
    identifying_values = " ".join(
        str(check.get(key, ""))
        for key in ("id", "kind", "type", "metric", "gate", "message", "description")
    ).casefold()
    haystack = " ".join(sorted(keys)) + " " + identifying_values

    rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "BRep_boolean",
            (
                "brep_boolean",
                "common_volume",
                "common volume",
                "intersection_mm3",
                "intersections_mm3",
                "intersection_volume",
                "overlap_mm3",
                "overlap_volume",
                "collision_volume",
                "penetration_volume",
                "boolean_common",
            ),
        ),
        (
            "topology_integrity",
            (
                "solid_valid",
                "is_valid",
                "isvalid",
                "solid_count",
                "solids_resolved",
                "watertight",
                "topology",
                "null_shape",
                "closed_shell",
                "manifold",
            ),
        ),
        (
            "hash_integrity",
            (
                "sha256",
                "digest",
                "hash_integrity",
                "byte_count",
                "file_bytes",
                "artifact_hash",
            ),
        ),
        (
            "BRep_measurement",
            (
                "brep_measurement",
                "clearance_mm",
                "clearance.",
                "distance_mm",
                "gap_mm",
                "thickness_mm",
                "volume_mm3",
                "area_mm2",
                "bbox",
                "bounds",
                "bounding_box",
                "minimum_distance",
                "measured_",
            ),
        ),
        (
            "name_presence",
            (
                "name_presence",
                "name_inventory",
                "node_inventory",
                "geometry_inventory",
                "required_names",
                "missing_names",
                "unexpected_names",
                "coverage",
                "name_match",
                "part_name_unique",
                "present",
            ),
        ),
        (
            "metadata_contract",
            (
                "metadata",
                "contract",
                "declared",
                "expected_",
                "target_",
                "material",
                "module_assigned",
                "configuration_assigned",
                "configurations",
                "policy",
                "feature",
                "opening",
                "envelope",
                "intent",
            ),
        ),
        (
            "process_assertion",
            (
                "generated_at",
                "validator",
                "schema_version",
                "release_status",
                "phase_status",
                "process",
            ),
        ),
    )
    for kind, needles in rules:
        matched = sorted({needle for needle in needles if needle in haystack})
        if matched:
            return kind, matched
    return "unclassified", []


def annotate_evidence_kinds(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep-copied report with conservative evidence classifications.

    Classification describes what a check actually demonstrates.  A declared
    metadata field is never promoted to B-Rep evidence merely because it reports
    a passing value.
    """

    if not isinstance(report, Mapping):
        raise EvidenceAnnotationError("evidence report must be a mapping")
    try:
        annotated = copy.deepcopy(dict(report))
        checks = _require_sequence(annotated.get("checks"), label="report.checks")
    except (TypeError, ValueError) as exc:
        raise EvidenceAnnotationError(f"cannot annotate evidence: {exc}") from exc

    stats = {
        kind: {
            "kind": kind,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "unknown_result": 0,
            "hard_failures": 0,
            "warnings": 0,
        }
        for kind in _EVIDENCE_KIND_ORDER
    }
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            raise EvidenceAnnotationError(
                f"cannot annotate evidence: report.checks[{index}] is not an object"
            )
        kind, matched_rules = _classify_evidence(check)
        check["evidence_kind"] = kind
        check["evidence_classification_basis"] = matched_rules
        passed = _check_passed(check)
        severity = str(check.get("severity", "")).strip().casefold()
        entry = stats[kind]
        entry["total"] += 1
        if passed is True:
            entry["passed"] += 1
        elif passed is False:
            entry["failed"] += 1
            if severity in {"hard", "error", "fatal", "critical"}:
                entry["hard_failures"] += 1
        else:
            entry["unknown_result"] += 1
        if severity in {"warning", "warn"}:
            entry["warnings"] += 1

    layer_summaries: list[dict[str, Any]] = []
    for layer, kinds in _EVIDENCE_LAYERS.items():
        layer_summaries.append(
            {
                "layer": layer,
                "kinds": list(kinds),
                "total": sum(stats[kind]["total"] for kind in kinds),
                "passed": sum(stats[kind]["passed"] for kind in kinds),
                "failed": sum(stats[kind]["failed"] for kind in kinds),
                "hard_failures": sum(stats[kind]["hard_failures"] for kind in kinds),
                "warnings": sum(stats[kind]["warnings"] for kind in kinds),
            }
        )

    annotated["evidence_summary"] = {
        "classification_version": 1,
        "total_checks": len(checks),
        "kinds": [stats[kind] for kind in _EVIDENCE_KIND_ORDER],
        "layers": layer_summaries,
        "interpretation": (
            "Direct geometry evidence is stronger than name/metadata proxies, but none of "
            "these layers constitutes physical or regulatory certification."
        ),
    }
    return annotated


def _import_cadquery() -> Any:
    try:
        import cadquery as cq  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "CadQuery/OCP is required for this gate; activate the workspace CAD environment"
        ) from exc
    return cq


def _import_glb_dependencies() -> tuple[Any, Any]:
    try:
        import numpy as np  # type: ignore
        import trimesh  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "NumPy and trimesh are required for GLB validation; activate the workspace environment"
        ) from exc
    return np, trimesh


def _shape_from_cadquery_value(value: Any, cq: Any) -> Any:
    if hasattr(value, "val") and callable(value.val):
        values = list(value.vals()) if hasattr(value, "vals") else [value.val()]
        if not values:
            raise ValueError("CadQuery workplane contains no shapes")
        if len(values) == 1:
            return values[0]
        return cq.Compound.makeCompound(values)
    if hasattr(value, "BoundingBox"):
        return value
    raise TypeError(f"expected a CadQuery Workplane/Shape, got {type(value).__name__}")


def _shape_bbox(shape: Any) -> dict[str, float]:
    box = shape.BoundingBox()
    result = {
        "xmin": float(box.xmin),
        "xmax": float(box.xmax),
        "ymin": float(box.ymin),
        "ymax": float(box.ymax),
        "zmin": float(box.zmin),
        "zmax": float(box.zmax),
        "xlen": float(box.xlen),
        "ylen": float(box.ylen),
        "zlen": float(box.zlen),
    }
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError(f"shape bounding box contains non-finite values: {result}")
    return result


def _shape_is_null(shape: Any) -> bool:
    method = getattr(shape, "isNull", None)
    return bool(method()) if callable(method) else False


def _shape_is_valid(shape: Any) -> bool:
    method = getattr(shape, "isValid", None)
    if not callable(method):
        raise ValueError("CadQuery shape does not expose isValid()")
    return bool(method())


def _subshape_count(shape: Any, method_name: str) -> int:
    method = getattr(shape, method_name, None)
    if not callable(method):
        raise ValueError(f"CadQuery shape does not expose {method_name}()")
    return len(method())


def _round_finite(value: Any, digits: int, *, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite: {number}")
    return round(number, digits)


def _geometry_signature_payload(shape: Any, digits: int) -> dict[str, Any]:
    bbox = _shape_bbox(shape)
    centre = shape.Center()
    solids = list(shape.Solids())
    faces = list(shape.Faces())
    edges = list(shape.Edges())
    vertices = list(shape.Vertices())

    solid_descriptors = []
    for index, solid in enumerate(solids):
        solid_box = _shape_bbox(solid)
        solid_centre = solid.Center()
        solid_descriptors.append(
            {
                "volume_mm3": _round_finite(solid.Volume(), digits, label=f"solid[{index}].volume"),
                "centre_mm": [
                    _round_finite(solid_centre.x, digits, label=f"solid[{index}].centre.x"),
                    _round_finite(solid_centre.y, digits, label=f"solid[{index}].centre.y"),
                    _round_finite(solid_centre.z, digits, label=f"solid[{index}].centre.z"),
                ],
                "bbox_mm": [_round_finite(solid_box[key], digits, label=key) for key in _BBOX_KEYS],
            }
        )
    solid_descriptors.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))

    face_areas = sorted(
        _round_finite(face.Area(), digits, label=f"face[{index}].area")
        for index, face in enumerate(faces)
    )
    edge_lengths = sorted(
        _round_finite(edge.Length(), digits, label=f"edge[{index}].length")
        for index, edge in enumerate(edges)
    )
    vertex_points = []
    for index, vertex in enumerate(vertices):
        point = vertex.Center()
        vertex_points.append(
            [
                _round_finite(point.x, digits, label=f"vertex[{index}].x"),
                _round_finite(point.y, digits, label=f"vertex[{index}].y"),
                _round_finite(point.z, digits, label=f"vertex[{index}].z"),
            ]
        )
    vertex_points.sort()

    return {
        "algorithm": f"brep-metric-topology-v1-round-{digits}",
        "bbox_mm": {key: _round_finite(bbox[key], digits, label=key) for key in _BBOX_KEYS},
        "volume_mm3": _round_finite(shape.Volume(), digits, label="shape.volume"),
        "area_mm2": _round_finite(shape.Area(), digits, label="shape.area"),
        "centre_mm": [
            _round_finite(centre.x, digits, label="shape.centre.x"),
            _round_finite(centre.y, digits, label="shape.centre.y"),
            _round_finite(centre.z, digits, label="shape.centre.z"),
        ],
        "counts": {
            "solids": len(solids),
            "faces": len(faces),
            "edges": len(edges),
            "vertices": len(vertices),
        },
        "solids": solid_descriptors,
        "face_areas_mm2": face_areas,
        "edge_lengths_mm": edge_lengths,
        "vertex_points_mm": vertex_points,
    }


def _manifest_artifact_path(repo_root: Path, raw: Any, *, label: str) -> tuple[str, Path]:
    relative = _normalise_relative_path(raw, label=label)
    parts = PurePosixPath(relative).parts
    if parts and parts[0].casefold() in _DIRECT_REPO_PREFIXES:
        logical_repo_path = relative
    else:
        logical_repo_path = (_CLASS_A_RELATIVE_ROOT / PurePosixPath(relative)).as_posix()
    path = _safe_path_under(repo_root, logical_repo_path, label=label)
    return logical_repo_path, path


def validate_exported_part_steps(
    manifest: Mapping[str, Any] | str | os.PathLike[str],
    repo_root: str | os.PathLike[str],
    *,
    bbox_tolerance_mm: float = 0.05,
    expected_solid_count: int = 1,
    signature_digits: int = 6,
) -> dict[str, Any]:
    """Re-open every exact per-part STEP path and validate exported geometry.

    The gate checks importability, null/valid state, positive volume, solid count,
    and the six exported bounding-box coordinates against the manifest.  It also
    records the file digest and an order-independent B-Rep metric/topology
    signature.  It never searches for replacement files when a path is wrong.
    """

    root = Path(repo_root).resolve()
    failures: list[dict[str, Any]] = []
    try:
        manifest_data, manifest_source = _load_mapping(manifest, repo_root=root)
    except (OSError, ValueError) as exc:
        report = {
            "gate": "validate_exported_part_steps",
            "status": "FAIL",
            "failures": [{"code": "manifest_unreadable", "detail": str(exc)}],
        }
        raise ExportedStepValidationError(str(exc), report) from exc

    if not isinstance(bbox_tolerance_mm, (int, float)) or bbox_tolerance_mm < 0:
        raise ValueError("bbox_tolerance_mm must be a finite non-negative number")
    if not math.isfinite(float(bbox_tolerance_mm)):
        raise ValueError("bbox_tolerance_mm must be finite")
    if not isinstance(expected_solid_count, int) or isinstance(expected_solid_count, bool) or expected_solid_count < 1:
        raise ValueError("expected_solid_count must be a positive integer")
    if not isinstance(signature_digits, int) or not 0 <= signature_digits <= 12:
        raise ValueError("signature_digits must be an integer from 0 through 12")

    states = manifest_data.get("states")
    if not isinstance(states, Mapping) or not states:
        failures.append({"code": "manifest_states_missing", "detail": "manifest.states must be a non-empty object"})
        state_items: list[tuple[Any, Any]] = []
    else:
        state_items = list(states.items())

    try:
        cq = _import_cadquery()
    except RuntimeError as exc:
        report = {
            "gate": "validate_exported_part_steps",
            "status": "FAIL",
            "failures": [{"code": "cad_dependency_unavailable", "detail": str(exc)}],
        }
        raise ExportedStepValidationError(str(exc), report) from exc

    records: list[dict[str, Any]] = []
    seen_paths: dict[str, str] = {}
    seen_state_parts: set[tuple[str, str]] = set()
    for state_name_raw, state_data in state_items:
        state_name = str(state_name_raw)
        if not isinstance(state_data, Mapping):
            failures.append({"code": "state_not_object", "state": state_name})
            continue
        try:
            parts = _require_sequence(state_data.get("parts"), label=f"states.{state_name}.parts")
        except ValueError as exc:
            failures.append({"code": "state_parts_missing", "state": state_name, "detail": str(exc)})
            continue
        for part_index, part in enumerate(parts):
            context = {"state": state_name, "part_index": part_index}
            if not isinstance(part, Mapping):
                failures.append(dict(context, code="part_not_object"))
                continue
            name = part.get("name")
            if not isinstance(name, str) or not name.strip():
                failures.append(dict(context, code="part_name_missing"))
                continue
            name = name.strip()
            context["part"] = name
            state_part_key = (state_name, name)
            if state_part_key in seen_state_parts:
                failures.append(dict(context, code="duplicate_state_part_name"))
                continue
            seen_state_parts.add(state_part_key)

            raw_step_path = part.get("step_path")
            try:
                logical_path, step_path = _manifest_artifact_path(
                    root, raw_step_path, label=f"states.{state_name}.parts[{part_index}].step_path"
                )
            except (TypeError, ValueError) as exc:
                failures.append(dict(context, code="invalid_step_path", detail=str(exc)))
                continue
            context["path"] = logical_path
            folded = logical_path.casefold()
            if folded in seen_paths:
                failures.append(
                    dict(context, code="duplicate_step_path", first_part=seen_paths[folded])
                )
                continue
            seen_paths[folded] = f"{state_name}/{name}"
            if not step_path.is_file():
                failures.append(dict(context, code="step_file_missing"))
                continue

            expected_bounds = part.get("bounds", part.get("bbox"))
            if not isinstance(expected_bounds, Mapping):
                failures.append(dict(context, code="manifest_part_bbox_missing"))
                continue
            expected_bbox: dict[str, float] = {}
            invalid_bbox = False
            for key in _BBOX_KEYS:
                try:
                    expected_bbox[key] = float(expected_bounds[key])
                    if not math.isfinite(expected_bbox[key]):
                        raise ValueError("not finite")
                except (KeyError, TypeError, ValueError):
                    failures.append(
                        dict(context, code="manifest_part_bbox_invalid", coordinate=key, value=expected_bounds.get(key))
                    )
                    invalid_bbox = True
            if invalid_bbox:
                continue

            metadata = part.get("metadata")
            declared_solid_count = part.get("solid_count")
            if declared_solid_count is None and isinstance(metadata, Mapping):
                declared_solid_count = metadata.get("expected_solid_count")
            if declared_solid_count is None:
                declared_solid_count = expected_solid_count
            if (
                not isinstance(declared_solid_count, int)
                or isinstance(declared_solid_count, bool)
                or declared_solid_count < 1
            ):
                failures.append(
                    dict(context, code="invalid_expected_solid_count", value=declared_solid_count)
                )
                continue

            try:
                imported = cq.importers.importStep(str(step_path))
                shape = _shape_from_cadquery_value(imported, cq)
                is_null = _shape_is_null(shape)
                is_valid = False if is_null else _shape_is_valid(shape)
                actual_bbox = _shape_bbox(shape)
                volume = float(shape.Volume())
                area = float(shape.Area())
                solid_count = _subshape_count(shape, "Solids")
                face_count = _subshape_count(shape, "Faces")
                edge_count = _subshape_count(shape, "Edges")
                vertex_count = _subshape_count(shape, "Vertices")
                centre = shape.Center()
                centre_mm = [float(centre.x), float(centre.y), float(centre.z)]
                if not all(math.isfinite(value) for value in [volume, area, *centre_mm]):
                    raise ValueError("shape metrics contain non-finite values")
                signature_payload = _geometry_signature_payload(shape, signature_digits)
                geometry_signature = _canonical_sha256(signature_payload)
            except Exception as exc:  # CadQuery/OCP raises several non-unified exception types.
                failures.append(
                    dict(
                        context,
                        code="step_import_or_measurement_failed",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            deltas = {
                key: actual_bbox[key] - expected_bbox[key]
                for key in _BBOX_KEYS
            }
            max_bbox_error = max(abs(value) for value in deltas.values())
            record_failures: list[str] = []
            if is_null:
                record_failures.append("null_shape")
                failures.append(dict(context, code="step_shape_null"))
            if not is_valid:
                record_failures.append("invalid_shape")
                failures.append(dict(context, code="step_shape_invalid"))
            if volume <= 0.0:
                record_failures.append("non_positive_volume")
                failures.append(dict(context, code="step_volume_not_positive", actual_volume_mm3=volume))
            if solid_count != declared_solid_count:
                record_failures.append("solid_count_mismatch")
                failures.append(
                    dict(
                        context,
                        code="step_solid_count_mismatch",
                        expected=declared_solid_count,
                        actual=solid_count,
                    )
                )
            if max_bbox_error > float(bbox_tolerance_mm):
                record_failures.append("bbox_mismatch")
                failures.append(
                    dict(
                        context,
                        code="step_bbox_mismatch",
                        tolerance_mm=float(bbox_tolerance_mm),
                        max_abs_error_mm=max_bbox_error,
                        deltas_mm=deltas,
                    )
                )

            records.append(
                {
                    "state": state_name,
                    "part": name,
                    "step_path": logical_path,
                    "status": "FAIL" if record_failures else "PASS",
                    "failure_codes": record_failures,
                    "step_bytes": step_path.stat().st_size,
                    "step_sha256": _sha256_file(step_path),
                    "is_null": is_null,
                    "is_valid": is_valid,
                    "volume_mm3": volume,
                    "area_mm2": area,
                    "centre_mm": centre_mm,
                    "solid_count": solid_count,
                    "expected_solid_count": declared_solid_count,
                    "face_count": face_count,
                    "edge_count": edge_count,
                    "vertex_count": vertex_count,
                    "manifest_bbox_mm": expected_bbox,
                    "actual_bbox_mm": actual_bbox,
                    "bbox_delta_mm": deltas,
                    "bbox_max_abs_error_mm": max_bbox_error,
                    "geometry_signature_algorithm": signature_payload["algorithm"],
                    "geometry_signature_sha256": geometry_signature,
                }
            )

    report = {
        "gate": "validate_exported_part_steps",
        "status": "FAIL" if failures else "PASS",
        "manifest_path": manifest_source.as_posix() if manifest_source else None,
        "bbox_tolerance_mm": float(bbox_tolerance_mm),
        "default_expected_solid_count": expected_solid_count,
        "part_count": len(records),
        "passed_part_count": sum(record["status"] == "PASS" for record in records),
        "failed_part_count": sum(record["status"] == "FAIL" for record in records),
        "parts": records,
        "failures": failures,
        "certification_scope": "exported B-Rep integrity evidence only; not physical certification",
    }
    if failures:
        raise ExportedStepValidationError(_failure_message("exported STEP gate", failures), report)
    return report


def _scene_inventory(scene: Any, np: Any) -> dict[str, Any]:
    geometry_names = [str(name) for name in scene.geometry.keys()]
    raw_node_names = list(scene.graph.nodes_geometry)
    node_names = [str(name) for name in raw_node_names]
    node_to_geometry: dict[str, str | None] = {}
    non_identity_nodes: list[str] = []
    for raw_node in raw_node_names:
        node = str(raw_node)
        transform, geometry_name = scene.graph.get(raw_node)
        node_to_geometry[node] = None if geometry_name is None else str(geometry_name)
        if not np.allclose(np.asarray(transform), np.eye(4), rtol=0.0, atol=1e-12):
            non_identity_nodes.append(node)
    bounds = scene.bounds
    bbox = None
    if bounds is not None:
        array = np.asarray(bounds, dtype=float)
        if array.shape == (2, 3) and np.isfinite(array).all():
            bbox = {
                "xmin": float(array[0, 0]),
                "xmax": float(array[1, 0]),
                "ymin": float(array[0, 1]),
                "ymax": float(array[1, 1]),
                "zmin": float(array[0, 2]),
                "zmax": float(array[1, 2]),
            }
    return {
        "units": scene.units,
        "geometry_names": geometry_names,
        "node_names": node_names,
        "node_to_geometry": node_to_geometry,
        "non_identity_nodes": non_identity_nodes,
        "bbox_native": bbox,
    }


def _inventory_delta(actual: Sequence[str], expected: Sequence[str]) -> dict[str, Any]:
    actual_counter = Counter(actual)
    expected_counter = Counter(expected)
    return {
        "missing": sorted((expected_counter - actual_counter).elements()),
        "unexpected": sorted((actual_counter - expected_counter).elements()),
        "duplicates": sorted(name for name, count in actual_counter.items() if count > 1),
        "matches": actual_counter == expected_counter,
    }


def _unit_is_meters(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"m", "meter", "meters", "metre", "metres"}


def _import_step_shape(path: Path, cq: Any) -> Any:
    imported = cq.importers.importStep(str(path))
    return _shape_from_cadquery_value(imported, cq)


def validate_glb_units_and_inventory(
    manifest: Mapping[str, Any] | str | os.PathLike[str],
    repo_root: str | os.PathLike[str],
    *,
    bbox_tolerance_mm: float = 1.0,
) -> dict[str, Any]:
    """Validate output GLB metre units, world bounds, geometry, and node inventory.

    GLB coordinates are required to be metres.  Consequently each output GLB
    world-space bound multiplied by 1000 must match its canonical millimetre
    reference.  The review reference is the skin STEP B-Rep bound unioned with
    the retained presentation subset of the controlled source GLB; the QA
    reference remains the full composite STEP B-Rep bound.  Merely declaring
    ``units='meters'`` while exporting millimetre-valued coordinates fails this
    gate.
    """

    root = Path(repo_root).resolve()
    if not isinstance(bbox_tolerance_mm, (int, float)) or bbox_tolerance_mm < 0:
        raise ValueError("bbox_tolerance_mm must be a finite non-negative number")
    if not math.isfinite(float(bbox_tolerance_mm)):
        raise ValueError("bbox_tolerance_mm must be finite")
    try:
        manifest_data, manifest_source = _load_mapping(manifest, repo_root=root)
        np, trimesh = _import_glb_dependencies()
        cq = _import_cadquery()
    except (OSError, ValueError, RuntimeError) as exc:
        report = {
            "gate": "validate_glb_units_and_inventory",
            "status": "FAIL",
            "failures": [{"code": "gate_setup_failed", "detail": str(exc)}],
        }
        raise GLBValidationError(str(exc), report) from exc

    states = manifest_data.get("states")
    failures: list[dict[str, Any]] = []
    state_reports: dict[str, Any] = {}
    if not isinstance(states, Mapping) or not states:
        failures.append({"code": "manifest_states_missing"})
        state_items: list[tuple[Any, Any]] = []
    else:
        state_items = list(states.items())

    for state_name_raw, state_data in state_items:
        state_name = str(state_name_raw)
        state_failures: list[dict[str, Any]] = []
        if not isinstance(state_data, Mapping):
            failure = {"code": "state_not_object", "state": state_name}
            failures.append(failure)
            continue

        path_fields: dict[str, tuple[str, Path]] = {}
        for field in (
            "source_glb",
            "skin_step",
            "composite_step",
            "review_glb",
            "qa_glb",
        ):
            try:
                path_fields[field] = _manifest_artifact_path(
                    root, state_data.get(field), label=f"states.{state_name}.{field}"
                )
                if not path_fields[field][1].is_file():
                    raise FileNotFoundError(path_fields[field][1])
            except (TypeError, ValueError, FileNotFoundError) as exc:
                state_failures.append(
                    {"code": "artifact_path_invalid_or_missing", "field": field, "detail": str(exc)}
                )

        parts = state_data.get("parts")
        if isinstance(parts, Sequence) and not isinstance(parts, (str, bytes, bytearray)):
            skin_names = [part.get("name") for part in parts if isinstance(part, Mapping)]
            if len(skin_names) != len(parts) or any(not isinstance(name, str) or not name for name in skin_names):
                state_failures.append({"code": "invalid_part_name_inventory"})
                skin_names = [name for name in skin_names if isinstance(name, str) and name]
        else:
            skin_names = []
            state_failures.append({"code": "state_parts_missing"})
        if len(set(skin_names)) != len(skin_names):
            state_failures.append({"code": "duplicate_skin_part_names"})

        presentation = state_data.get("presentation_source_geometry")
        if isinstance(presentation, Sequence) and not isinstance(presentation, (str, bytes, bytearray)):
            presentation_names = [str(name) for name in presentation]
        else:
            presentation_names = []
            state_failures.append({"code": "presentation_source_geometry_missing"})
        if len(set(presentation_names)) != len(presentation_names):
            state_failures.append({"code": "duplicate_presentation_source_geometry"})

        if state_failures:
            for failure in state_failures:
                failures.append(dict(failure, state=state_name))
            state_reports[state_name] = {
                "status": "FAIL",
                "failures": state_failures,
                "paths": {field: logical for field, (logical, _path) in path_fields.items()},
            }
            continue

        try:
            source_scene = trimesh.load(
                str(path_fields["source_glb"][1]), force="scene", process=False
            )
            source_inventory = _scene_inventory(source_scene, np)
            if not _unit_is_meters(source_inventory["units"]):
                raise ValueError(
                    "controlled E6-DFR5 source GLB is not metre-native: "
                    f"{source_inventory['units']!r}"
                )
            source_bounds_to_mm = 1000.0
            source_geometry_names = source_inventory["geometry_names"]
            if len(set(source_geometry_names)) != len(source_geometry_names):
                state_failures.append({"code": "duplicate_controlled_source_geometry_names"})

            expected_review = skin_names + [f"source_{name}" for name in presentation_names]
            expected_qa = skin_names + [f"source_{name}" for name in source_geometry_names]
            if len(set(expected_review)) != len(expected_review):
                state_failures.append({"code": "review_expected_inventory_not_unique"})
            if len(set(expected_qa)) != len(expected_qa):
                state_failures.append({"code": "qa_expected_inventory_not_unique"})

            skin_shape = _import_step_shape(path_fields["skin_step"][1], cq)
            if _shape_is_null(skin_shape) or not _shape_is_valid(skin_shape):
                raise ValueError("skin STEP is null or invalid")
            skin_step_bbox = _shape_bbox(skin_shape)

            retained_source_bounds: list[Any] = []
            for geometry_name in presentation_names:
                if geometry_name not in source_scene.geometry:
                    raise ValueError(
                        "retained presentation geometry is absent from controlled "
                        f"source GLB: {geometry_name}"
                    )
                geometry_bounds = np.asarray(
                    source_scene.geometry[geometry_name].bounds,
                    dtype=float,
                )
                if geometry_bounds.shape != (2, 3) or not np.isfinite(
                    geometry_bounds
                ).all():
                    raise ValueError(
                        "retained presentation geometry has missing or non-finite "
                        f"bounds: {geometry_name}"
                    )
                retained_source_bounds.append(
                    geometry_bounds * source_bounds_to_mm
                )

            # E6-DFR5 source GLBs and review GLBs are both metre-native, while
            # STEP B-Reps remain millimetres.  Convert the retained source
            # geometry bounds exactly once before unioning them with the skin
            # STEP bounds.  Mixing the two native units can otherwise let a
            # review GLB drift by hundreds of millimetres while its reference
            # box appears to remain skin-only.
            review_min = np.asarray(
                [
                    skin_step_bbox["xmin"],
                    skin_step_bbox["ymin"],
                    skin_step_bbox["zmin"],
                ],
                dtype=float,
            )
            review_max = np.asarray(
                [
                    skin_step_bbox["xmax"],
                    skin_step_bbox["ymax"],
                    skin_step_bbox["zmax"],
                ],
                dtype=float,
            )
            for geometry_bounds in retained_source_bounds:
                review_min = np.minimum(review_min, geometry_bounds[0])
                review_max = np.maximum(review_max, geometry_bounds[1])
            review_reference_bbox = {
                "xmin": float(review_min[0]),
                "xmax": float(review_max[0]),
                "ymin": float(review_min[1]),
                "ymax": float(review_max[1]),
                "zmin": float(review_min[2]),
                "zmax": float(review_max[2]),
            }

            composite_shape = _import_step_shape(path_fields["composite_step"][1], cq)
            if _shape_is_null(composite_shape) or not _shape_is_valid(composite_shape):
                raise ValueError("composite STEP is null or invalid")
            composite_step_bbox = _shape_bbox(composite_shape)
        except Exception as exc:
            state_failures.append(
                {"code": "reference_inventory_or_step_load_failed", "detail": f"{type(exc).__name__}: {exc}"}
            )
            for failure in state_failures:
                failures.append(dict(failure, state=state_name))
            state_reports[state_name] = {
                "status": "FAIL",
                "failures": state_failures,
                "paths": {field: logical for field, (logical, _path) in path_fields.items()},
            }
            continue

        outputs: dict[str, Any] = {}
        for output_kind, field, expected_inventory, reference_bbox, reference_kind in (
            (
                "review",
                "review_glb",
                expected_review,
                review_reference_bbox,
                "skin_step_brep_union_retained_controlled_source_glb",
            ),
            (
                "qa",
                "qa_glb",
                expected_qa,
                composite_step_bbox,
                "full_composite_step_brep",
            ),
        ):
            output_failures: list[dict[str, Any]] = []
            try:
                scene = trimesh.load(str(path_fields[field][1]), force="scene", process=False)
                inventory = _scene_inventory(scene, np)
            except Exception as exc:
                output_failures.append(
                    {"code": "glb_load_failed", "detail": f"{type(exc).__name__}: {exc}"}
                )
                inventory = {
                    "units": None,
                    "geometry_names": [],
                    "node_names": [],
                    "node_to_geometry": {},
                    "non_identity_nodes": [],
                    "bbox_native": None,
                }

            geometry_delta = _inventory_delta(inventory["geometry_names"], expected_inventory)
            node_delta = _inventory_delta(inventory["node_names"], expected_inventory)
            if not geometry_delta["matches"]:
                output_failures.append(
                    {"code": "geometry_inventory_mismatch", **geometry_delta}
                )
            if not node_delta["matches"]:
                output_failures.append({"code": "node_inventory_mismatch", **node_delta})

            node_binding_mismatches = sorted(
                node
                for node, geometry in inventory["node_to_geometry"].items()
                if node != geometry
            )
            if node_binding_mismatches:
                output_failures.append(
                    {
                        "code": "node_geometry_binding_mismatch",
                        "nodes": node_binding_mismatches,
                    }
                )
            if inventory["non_identity_nodes"]:
                output_failures.append(
                    {
                        "code": "non_identity_node_transform",
                        "nodes": inventory["non_identity_nodes"],
                    }
                )
            if not _unit_is_meters(inventory["units"]):
                output_failures.append(
                    {
                        "code": "glb_units_not_meters",
                        "actual_units": inventory["units"],
                    }
                )

            bbox_m: dict[str, float] | None = inventory["bbox_native"]
            if bbox_m is None:
                bbox_mm = None
                bbox_delta_mm = None
                max_bbox_error = None
                output_failures.append({"code": "glb_bbox_missing_or_nonfinite"})
            else:
                bbox_mm = {key: value * 1000.0 for key, value in bbox_m.items()}
                bbox_delta_mm = {
                    key: bbox_mm[key] - reference_bbox[key] for key in _BBOX_KEYS
                }
                max_bbox_error = max(abs(value) for value in bbox_delta_mm.values())
                if max_bbox_error > float(bbox_tolerance_mm):
                    output_failures.append(
                        {
                            "code": "glb_step_bbox_mismatch",
                            "max_abs_error_mm": max_bbox_error,
                            "tolerance_mm": float(bbox_tolerance_mm),
                            "deltas_mm": bbox_delta_mm,
                        }
                    )

            outputs[output_kind] = {
                "status": "FAIL" if output_failures else "PASS",
                "path": path_fields[field][0],
                "declared_units": inventory["units"],
                "expected_inventory_count": len(expected_inventory),
                "geometry_inventory": geometry_delta,
                "node_inventory": node_delta,
                "node_geometry_binding_mismatches": node_binding_mismatches,
                "non_identity_nodes": inventory["non_identity_nodes"],
                "bbox_m": bbox_m,
                "bbox_converted_mm": bbox_mm,
                "bbox_reference_kind": reference_kind,
                "step_bbox_mm": {key: reference_bbox[key] for key in _BBOX_KEYS},
                "bbox_delta_mm": bbox_delta_mm,
                "bbox_max_abs_error_mm": max_bbox_error,
                "failures": output_failures,
            }
            for failure in output_failures:
                failures.append(dict(failure, state=state_name, output=output_kind))
                state_failures.append(dict(failure, output=output_kind))

        state_reports[state_name] = {
            "status": "FAIL" if state_failures else "PASS",
            "paths": {field: logical for field, (logical, _path) in path_fields.items()},
            "source_geometry_count": len(source_geometry_names),
            "skin_part_count": len(skin_names),
            "presentation_source_geometry_count": len(presentation_names),
            "skin_step_bbox_mm": {
                key: skin_step_bbox[key] for key in _BBOX_KEYS
            },
            "review_reference_bbox_mm": {
                key: review_reference_bbox[key] for key in _BBOX_KEYS
            },
            "composite_step_bbox_mm": {
                key: composite_step_bbox[key] for key in _BBOX_KEYS
            },
            "outputs": outputs,
            "failures": state_failures,
        }

    report = {
        "gate": "validate_glb_units_and_inventory",
        "status": "FAIL" if failures else "PASS",
        "manifest_path": manifest_source.as_posix() if manifest_source else None,
        "bbox_tolerance_mm": float(bbox_tolerance_mm),
        "states": state_reports,
        "failures": failures,
        "certification_scope": "digital unit/inventory evidence only; not physical certification",
    }
    if failures:
        raise GLBValidationError(_failure_message("GLB unit/inventory gate", failures), report)
    return report


def _artifact_manifest_entries(manifest: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("artifact_sha256", "artifacts_sha256", "artifact_hashes"):
        value = manifest.get(key)
        if isinstance(value, Mapping):
            return value
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, Mapping):
        for key in ("sha256", "files"):
            value = artifacts.get(key)
            if isinstance(value, Mapping):
                return value
    return None


def validate_closed_artifact_set(
    output: str | os.PathLike[str],
    manifest: Mapping[str, Any] | str | os.PathLike[str],
    *,
    allowed_unlisted: Sequence[str | os.PathLike[str]] = (),
) -> dict[str, Any]:
    """Require the output tree to equal the manifest's hashed artifact set.

    Manifest paths may be relative to ``output`` or prefixed once with
    ``output.name``.  The default is deliberately strict: even a README or the
    manifest itself must be listed.  Builders that validate before writing a
    self-referential manifest may explicitly allow that one relative path.
    """

    output_root = Path(output).resolve()
    failures: list[dict[str, Any]] = []
    if not output_root.is_dir():
        report = {
            "gate": "validate_closed_artifact_set",
            "status": "FAIL",
            "output": output_root.as_posix(),
            "failures": [{"code": "output_directory_missing"}],
        }
        raise ArtifactSetError("artifact closure gate failed: output directory missing", report)
    try:
        manifest_data, manifest_source = _load_mapping(manifest, label="manifest")
    except (OSError, ValueError) as exc:
        report = {
            "gate": "validate_closed_artifact_set",
            "status": "FAIL",
            "output": output_root.as_posix(),
            "failures": [{"code": "manifest_unreadable", "detail": str(exc)}],
        }
        raise ArtifactSetError(str(exc), report) from exc

    raw_entries = _artifact_manifest_entries(manifest_data)
    if raw_entries is None:
        failures.append(
            {
                "code": "artifact_hash_mapping_missing",
                "detail": "expected artifact_sha256 (or equivalent mapping)",
            }
        )
        raw_entries = {}

    allowed: set[str] = set()
    allowed_casefold: dict[str, str] = {}
    for index, value in enumerate(allowed_unlisted):
        try:
            rel = _normalise_relative_path(value, label=f"allowed_unlisted[{index}]")
        except (TypeError, ValueError) as exc:
            failures.append({"code": "invalid_allowed_unlisted_path", "detail": str(exc)})
            continue
        folded = rel.casefold()
        if folded in allowed_casefold:
            failures.append({"code": "duplicate_allowed_unlisted_path", "path": rel})
            continue
        allowed.add(rel)
        allowed_casefold[folded] = rel

    listed: dict[str, dict[str, Any]] = {}
    listed_casefold: dict[str, str] = {}
    output_prefix = output_root.name.casefold()
    for index, (raw_path, raw_hash_record) in enumerate(raw_entries.items()):
        try:
            rel = _normalise_relative_path(raw_path, label=f"artifact entry {index}")
        except (TypeError, ValueError) as exc:
            failures.append({"code": "invalid_artifact_path", "detail": str(exc)})
            continue
        parts = list(PurePosixPath(rel).parts)
        if parts and parts[0].casefold() == output_prefix:
            parts = parts[1:]
        if not parts:
            failures.append({"code": "artifact_path_names_output_directory", "path": rel})
            continue
        output_rel = PurePosixPath(*parts).as_posix()
        folded = output_rel.casefold()
        if folded in listed_casefold:
            failures.append(
                {
                    "code": "duplicate_artifact_path",
                    "path": output_rel,
                    "first_path": listed_casefold[folded],
                }
            )
            continue
        if isinstance(raw_hash_record, Mapping):
            expected_sha = str(raw_hash_record.get("sha256", "")).lower()
            expected_bytes = raw_hash_record.get("bytes")
        else:
            expected_sha = str(raw_hash_record).lower()
            expected_bytes = None
        if not _SHA256_RE.fullmatch(expected_sha):
            failures.append({"code": "invalid_artifact_sha256", "path": output_rel})
            continue
        if expected_bytes is not None and (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes < 0
        ):
            failures.append({"code": "invalid_artifact_bytes", "path": output_rel})
            continue
        listed[output_rel] = {"sha256": expected_sha, "bytes": expected_bytes}
        listed_casefold[folded] = output_rel

    actual: dict[str, Path] = {}
    actual_casefold: dict[str, str] = {}
    for path in sorted(output_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not _is_within(resolved, output_root):
            failures.append(
                {
                    "code": "artifact_symlink_escapes_output",
                    "path": path.relative_to(output_root).as_posix(),
                    "target": resolved.as_posix(),
                }
            )
            continue
        rel = path.relative_to(output_root).as_posix()
        folded = rel.casefold()
        if folded in actual_casefold:
            failures.append(
                {
                    "code": "case_colliding_actual_artifact",
                    "path": rel,
                    "first_path": actual_casefold[folded],
                }
            )
            continue
        actual[rel] = path
        actual_casefold[folded] = rel

    listed_folded = {path.casefold(): path for path in listed}
    actual_folded = {path.casefold(): path for path in actual}
    missing = sorted(
        listed[path].get("logical_path", path)
        for path in listed
        if path.casefold() not in actual_folded
    )
    extras = sorted(
        path
        for path in actual
        if path.casefold() not in listed_folded and path.casefold() not in allowed_casefold
    )
    absent_allowed = sorted(
        path for path in allowed if path.casefold() not in actual_folded
    )
    if missing:
        failures.append({"code": "listed_artifacts_missing", "paths": missing})
    if extras:
        failures.append({"code": "unlisted_artifacts_present", "paths": extras})

    checked: list[dict[str, Any]] = []
    for rel, record in listed.items():
        actual_name = actual_folded.get(rel.casefold())
        if actual_name is None:
            continue
        path = actual[actual_name]
        actual_sha = _sha256_file(path)
        actual_bytes = path.stat().st_size
        mismatches: list[str] = []
        if actual_sha != record["sha256"]:
            mismatches.append("sha256")
            failures.append(
                {
                    "code": "artifact_digest_mismatch",
                    "path": rel,
                    "expected_sha256": record["sha256"],
                    "actual_sha256": actual_sha,
                }
            )
        if record["bytes"] is not None and actual_bytes != record["bytes"]:
            mismatches.append("bytes")
            failures.append(
                {
                    "code": "artifact_byte_count_mismatch",
                    "path": rel,
                    "expected_bytes": record["bytes"],
                    "actual_bytes": actual_bytes,
                }
            )
        checked.append(
            {
                "path": rel,
                "status": "FAIL" if mismatches else "PASS",
                "bytes": actual_bytes,
                "sha256": actual_sha,
                "mismatches": mismatches,
            }
        )

    report = {
        "gate": "validate_closed_artifact_set",
        "status": "FAIL" if failures else "PASS",
        "output": output_root.as_posix(),
        "manifest_path": manifest_source.as_posix() if manifest_source else None,
        "listed_count": len(listed),
        "actual_count": len(actual),
        "allowed_unlisted": sorted(allowed),
        "allowed_unlisted_absent": absent_allowed,
        "missing": missing,
        "unlisted": extras,
        "checked": checked,
        "failures": failures,
        "certification_scope": "artifact integrity/closure evidence only; not physical certification",
    }
    if failures:
        raise ArtifactSetError(_failure_message("artifact closure gate", failures), report)
    return report


def _part_value(part: Any, key: str, default: Any = None) -> Any:
    if isinstance(part, Mapping):
        return part.get(key, default)
    return getattr(part, key, default)


def _normalise_pair(a: Any, b: Any) -> tuple[str, str]:
    left = str(a).strip()
    right = str(b).strip()
    if not left or not right or left == right:
        raise ValueError(f"invalid collision pair: {a!r}, {b!r}")
    return tuple(sorted((left, right)))


def _normalise_allowlist(allowlist: Any, state: str) -> dict[tuple[str, str], str]:
    if allowlist is None:
        return {}
    if isinstance(allowlist, Mapping) and state in allowlist and not (
        isinstance(state, tuple) and len(state) == 2
    ):
        candidate = allowlist[state]
        if isinstance(candidate, (Mapping, Sequence)) and not isinstance(candidate, (str, bytes)):
            allowlist = candidate

    result: dict[tuple[str, str], str] = {}
    if isinstance(allowlist, Mapping):
        iterator: Iterable[Any] = allowlist.items()
        for raw_pair, reason in iterator:
            if isinstance(raw_pair, str):
                separators = ("|", "::", ",")
                split = next((raw_pair.split(sep, 1) for sep in separators if sep in raw_pair), None)
                if split is None:
                    raise ValueError(f"allowlist key must identify two parts: {raw_pair!r}")
                a, b = split
            elif isinstance(raw_pair, Sequence) and len(raw_pair) == 2:
                a, b = raw_pair
            else:
                raise ValueError(f"allowlist key must be a two-part pair: {raw_pair!r}")
            pair = _normalise_pair(a, b)
            if pair in result:
                raise ValueError(f"duplicate allowlisted pair: {pair}")
            result[pair] = str(reason or "explicitly allowlisted")
        return result

    if isinstance(allowlist, (str, bytes)) or not isinstance(allowlist, Iterable):
        raise ValueError("allowlist must be a mapping or iterable of two-part pairs")
    for index, item in enumerate(allowlist):
        reason = "explicitly allowlisted"
        item_state = None
        if isinstance(item, Mapping):
            a, b = item.get("a"), item.get("b")
            reason = str(item.get("reason") or reason)
            item_state = item.get("state")
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) in {2, 3}:
            a, b = item[0], item[1]
            if len(item) == 3:
                reason = str(item[2] or reason)
        else:
            raise ValueError(f"allowlist[{index}] must identify two parts")
        if item_state is not None and str(item_state) != state:
            continue
        pair = _normalise_pair(a, b)
        if pair in result:
            raise ValueError(f"duplicate allowlisted pair: {pair}")
        result[pair] = reason
    return result


def _bbox_overlap_mm3(a: Mapping[str, float], b: Mapping[str, float]) -> tuple[float, list[float]]:
    lengths = [
        max(0.0, min(a[f"{axis}max"], b[f"{axis}max"]) - max(a[f"{axis}min"], b[f"{axis}min"]))
        for axis in ("x", "y", "z")
    ]
    return lengths[0] * lengths[1] * lengths[2], lengths


def rigid_pair_collision_report(
    parts: Sequence[Any],
    state: str,
    allowlist: Any = (),
    *,
    interference_volume_mm3: float = 0.1,
    numerical_epsilon_mm3: float = 1e-6,
) -> dict[str, Any]:
    """Return exact common-volume results for rigid part pairs.

    An axis-aligned bounding-box broad phase limits OCC Boolean common operations.
    Common volume above ``interference_volume_mm3`` is a failure unless the pair
    is explicitly allowlisted.  Values at or below ``numerical_epsilon_mm3`` are
    recorded as numerical residue, and intermediate values are recorded as below
    the hard interference threshold.  The report does not claim dynamic,
    tolerance-stack, load, fatigue, or physical collision certification.
    """

    for label, value in (
        ("interference_volume_mm3", interference_volume_mm3),
        ("numerical_epsilon_mm3", numerical_epsilon_mm3),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"{label} must be a finite non-negative number")
    if numerical_epsilon_mm3 > interference_volume_mm3:
        raise ValueError("numerical_epsilon_mm3 may not exceed interference_volume_mm3")
    try:
        part_sequence = _require_sequence(parts, label="parts")
        cq = _import_cadquery()
        allowed = _normalise_allowlist(allowlist, str(state))
    except (ValueError, RuntimeError) as exc:
        raise CollisionGateError(f"collision gate setup failed: {exc}") from exc

    prepared: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, part in enumerate(part_sequence):
        part_state = _part_value(part, "state")
        if part_state is not None and str(part_state) != str(state):
            continue
        name = _part_value(part, "name")
        if not isinstance(name, str) or not name.strip():
            raise CollisionGateError(f"parts[{index}] has no non-empty name")
        name = name.strip()
        if name in seen_names:
            raise CollisionGateError(f"duplicate rigid part name in state {state!r}: {name}")
        seen_names.add(name)
        shape_value = _part_value(part, "shape")
        try:
            shape = _shape_from_cadquery_value(shape_value, cq)
            if _shape_is_null(shape) or not _shape_is_valid(shape):
                raise ValueError("shape is null or invalid")
            bbox = _shape_bbox(shape)
        except Exception as exc:
            raise CollisionGateError(
                f"cannot prepare rigid part {name!r}: {type(exc).__name__}: {exc}"
            ) from exc
        prepared.append({"name": name, "shape": shape, "bbox": bbox})

    pairs: list[dict[str, Any]] = []
    hard_collisions: list[dict[str, Any]] = []
    broadphase_candidates = 0
    exact_boolean_count = 0
    for left_index, left in enumerate(prepared):
        for right in prepared[left_index + 1 :]:
            pair = _normalise_pair(left["name"], right["name"])
            broadphase_volume, overlap_lengths = _bbox_overlap_mm3(left["bbox"], right["bbox"])
            if broadphase_volume <= 0.0:
                continue
            broadphase_candidates += 1
            try:
                common = left["shape"].intersect(right["shape"])
                common_volume = 0.0 if _shape_is_null(common) else float(common.Volume())
                if not math.isfinite(common_volume):
                    raise ValueError(f"non-finite common volume {common_volume}")
                common_volume = max(0.0, common_volume)
            except Exception as exc:
                raise CollisionGateError(
                    f"OCC common failed for {pair[0]!r} / {pair[1]!r}: {type(exc).__name__}: {exc}"
                ) from exc
            exact_boolean_count += 1
            allow_reason = allowed.get(pair)
            if common_volume <= float(numerical_epsilon_mm3):
                classification = "numerical_residue"
                failed = False
            elif common_volume <= float(interference_volume_mm3):
                classification = "below_interference_threshold"
                failed = False
            elif allow_reason is not None:
                classification = "allowlisted_interference"
                failed = False
            else:
                classification = "hard_interference"
                failed = True
            record = {
                "a": pair[0],
                "b": pair[1],
                "bbox_overlap_lengths_mm": overlap_lengths,
                "bbox_overlap_volume_mm3": broadphase_volume,
                "common_volume_mm3": common_volume,
                "classification": classification,
                "allowlisted": allow_reason is not None,
                "allowlist_reason": allow_reason,
                "status": "FAIL" if failed else "PASS",
                "evidence_kind": "BRep_boolean",
            }
            pairs.append(record)
            if failed:
                hard_collisions.append(record)

    unused_allowlist = [
        {"a": pair[0], "b": pair[1], "reason": reason}
        for pair, reason in sorted(allowed.items())
        if pair not in {
            _normalise_pair(record["a"], record["b"])
            for record in pairs
            if record["common_volume_mm3"] > float(interference_volume_mm3)
        }
    ]
    return {
        "gate": "rigid_pair_collision_report",
        "state": str(state),
        "status": "FAIL" if hard_collisions else "PASS",
        "part_count": len(prepared),
        "possible_pair_count": len(prepared) * (len(prepared) - 1) // 2,
        "broadphase_candidate_count": broadphase_candidates,
        "exact_boolean_count": exact_boolean_count,
        "hard_collision_count": len(hard_collisions),
        "interference_volume_mm3": float(interference_volume_mm3),
        "numerical_epsilon_mm3": float(numerical_epsilon_mm3),
        "pairs": pairs,
        "hard_collisions": hard_collisions,
        "unused_allowlist": unused_allowlist,
        "certification_scope": (
            "static CAD B-Rep common-volume evidence only; not dynamic or physical collision certification"
        ),
    }


__all__ = [
    "PINNED_RELEASE_MANIFEST_SHA256",
    "QAGateError",
    "InputPinError",
    "CheckIdError",
    "EvidenceAnnotationError",
    "ExportedStepValidationError",
    "GLBValidationError",
    "ArtifactSetError",
    "CollisionGateError",
    "pin_and_verify_consumed_inputs",
    "assert_unique_check_ids",
    "annotate_evidence_kinds",
    "validate_exported_part_steps",
    "validate_glb_units_and_inventory",
    "validate_closed_artifact_set",
    "rigid_pair_collision_report",
]
