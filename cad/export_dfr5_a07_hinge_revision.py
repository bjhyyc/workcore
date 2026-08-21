"""Export the isolated E6-DFR5 A07 shared-hinge source revision.

E6-DFR4-A08 remains an immutable parent source set.  DFR5 changes one and
only one principle-level item: in Follow, every physical A07 mast/sensor-bar
occurrence is re-posed from the legacy mast fold hinge ``(160, 0, 509)`` to
the A06 backrest hinge ``(160, 0, 515)`` at the same -95 degree fold angle.

Ride, Cafe, Focus and both optional-footrest-open states are copied byte for
byte from the published DFR4 directory.  The exporter also records the parent
hashes, complete A07 occurrence identity, per-occurrence old/new BRep hashes,
and the exact rigid transform used for the Follow correction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import cadquery as cq
import numpy as np
import trimesh


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from build import (  # noqa: E402
    Part,
    aabb,
    mast_and_beam_parts,
    rotate_about_y,
)
from export_dfr4_footrest_revision import (  # noqa: E402
    GENERATOR_FILES as DFR4_GENERATOR_FILES,
    STATE_SPECS,
    _build_states,
    _export_glb,
    _part_record,
    _validate,
    sha256,
)
from footrest_state import (  # noqa: E402
    CONTRACT_VERSION,
    default_footrest_pose,
    optional_footrest_open_available,
)
from parameters import P  # noqa: E402


PARENT_DFR4 = (
    ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
    / "controlled_source_e6_dfr4"
)
DEFAULT_OUTPUT = PARENT_DFR4.with_name("controlled_source_e6_dfr5")
PARENT_MANIFEST_NAME = "e6_dfr4_a08_manifest.json"
MANIFEST_NAME = "e6_dfr5_a07_hinge_manifest.json"
HASHES_NAME = "e6_dfr5_sha256.json"

LEGACY_MAST_HINGE = (P.back_hinge_x, 0.0, P.mast_fold_hinge_z)
SHARED_BACK_HINGE = (P.back_hinge_x, 0.0, P.back_hinge_z)
FOLLOW_FOLD_ANGLE_DEG = -95.0

INHERITED_STATES = (
    "ride",
    "cafe",
    "focus",
    "cafe_footrest_open",
    "focus_footrest_open",
)

GENERATOR_FILES = tuple(DFR4_GENERATOR_FILES) + (
    "cad/export_dfr5_a07_hinge_revision.py",
)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _export_step(parts: Iterable[Part], target: Path, state: str) -> None:
    assembly = cq.Assembly(name=f"WorkCore_E6_DFR5_{state}")
    for candidate in parts:
        assembly.add(
            candidate.shape,
            name=candidate.name,
            color=cq.Color(*candidate.color),
        )
    assembly.save(str(target), exportType="STEP", mode="default")


def _shape_brep_sha256(candidate: Part, scratch: Path, token: str) -> str:
    target = scratch / f"{token}.brep"
    candidate.solid.exportBrep(str(target))
    digest = sha256(target)
    target.unlink()
    return digest


def _centre_mm(candidate: Part) -> list[float]:
    centre = candidate.solid.Center()
    return [round(float(centre.x), 9), round(float(centre.y), 9), round(float(centre.z), 9)]


def _metadata_record(candidate: Part) -> dict[str, object]:
    return {
        "name": candidate.name,
        "physical_occurrence_id": candidate.physical_occurrence_id,
        "identity_basis": candidate.identity_basis,
        "definition_revision": candidate.definition_revision,
        "configuration": candidate.configuration,
        "mechanism_pose": candidate.mechanism_pose,
        "mechanism_contract": candidate.mechanism_contract,
        "material": candidate.material,
        "process": candidate.process,
        "quantity": candidate.quantity,
        "option_code": candidate.option_code,
        "include_in_ebom": candidate.include_in_ebom,
        "vendor": candidate.vendor,
        "vendor_part_number": candidate.vendor_part_number,
        "maturity": candidate.maturity,
    }


def _state_occurrence_contract(parts: list[Part]) -> dict[str, object]:
    names = [candidate.name for candidate in parts]
    if len(names) != len(set(names)):
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        raise RuntimeError(f"Duplicate source occurrence names: {duplicates}")
    records = []
    for candidate in parts:
        record = _part_record(candidate)
        record.update(
            {
                "configuration": candidate.configuration,
                "option_code": candidate.option_code,
                "include_in_ebom": candidate.include_in_ebom,
            }
        )
        records.append(record)
    return {
        "occurrence_count": len(records),
        "ordered_occurrence_names_sha256": _canonical_sha256(names),
        "occurrence_contract_sha256": _canonical_sha256(records),
    }


def _part_record_equivalence(
    actual: dict[str, object],
    expected: dict[str, object],
    *,
    bounds_tolerance_mm: float = 0.01,
) -> tuple[bool, float, list[str]]:
    """Compare regenerated source records across OCCT bbox-cache variants.

    The published DFR4 run serialized analytic A08 bounds with the shape's
    0.007298 mm OCCT tolerance included.  A fresh process can return the same
    analytic shape without that cache expansion.  Identity, topology, volume,
    mass and every non-bound field must still be exact; only the six bound
    scalars receive the released 0.01 mm source tolerance.
    """

    mismatched_fields = []
    for key in sorted(set(actual) | set(expected)):
        if key == "bounds_mm":
            continue
        if actual.get(key) != expected.get(key):
            mismatched_fields.append(key)
    actual_bounds = actual.get("bounds_mm", {})
    expected_bounds = expected.get("bounds_mm", {})
    bound_keys_match = set(actual_bounds) == set(expected_bounds)
    maximum_bounds_drift = (
        max(
            abs(float(actual_bounds[key]) - float(expected_bounds[key]))
            for key in actual_bounds
        )
        if bound_keys_match and actual_bounds
        else math.inf
    )
    return (
        not mismatched_fields
        and bound_keys_match
        and maximum_bounds_drift <= bounds_tolerance_mm,
        maximum_bounds_drift,
        mismatched_fields,
    )


def _rotation_y_matrix(angle_deg: float) -> np.ndarray:
    angle = math.radians(angle_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.asarray(
        [
            [cosine, 0.0, sine],
            [0.0, 1.0, 0.0],
            [-sine, 0.0, cosine],
        ],
        dtype=float,
    )


def _folded_pose_delta() -> tuple[np.ndarray, np.ndarray]:
    """Return the old-folded to shared-hinge-folded rigid transform."""

    rotation = _rotation_y_matrix(FOLLOW_FOLD_ANGLE_DEG)
    old_origin = np.asarray(LEGACY_MAST_HINGE, dtype=float)
    new_origin = np.asarray(SHARED_BACK_HINGE, dtype=float)
    translation = (np.eye(3) - rotation) @ (new_origin - old_origin)
    return np.eye(3), translation


def _matrix4x4(rotation: np.ndarray, translation: np.ndarray) -> list[list[float]]:
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = translation
    return [[round(float(value), 12) for value in row] for row in matrix]


def _parent_artifact_index(parent_manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    files = parent_manifest.get("artifacts", {}).get("files", [])
    return {Path(record["path"]).name: record for record in files}


def _load_and_verify_parent() -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, str]]:
    manifest_path = PARENT_DFR4 / PARENT_MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    parent_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if parent_manifest.get("revision") != "E6-DFR4-A08" or parent_manifest.get("status") != "PASS":
        raise RuntimeError("Parent source is not the released PASS E6-DFR4-A08 set")

    parent_artifacts = _parent_artifact_index(parent_manifest)
    parent_hashes: dict[str, str] = {PARENT_MANIFEST_NAME: sha256(manifest_path)}
    for state_record in parent_manifest["states"].values():
        for kind in ("step", "glb"):
            filename = state_record[kind]
            path = PARENT_DFR4 / filename
            if not path.is_file():
                raise FileNotFoundError(path)
            expected = parent_artifacts[filename]["sha256"]
            actual = sha256(path)
            if actual != expected:
                raise RuntimeError(
                    f"Immutable DFR4 artifact hash mismatch: {filename}: "
                    f"expected {expected}, got {actual}"
                )
            parent_hashes[filename] = actual

    for relative, expected in parent_manifest["generator_sha256"].items():
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"DFR4 generator drift prevents a controlled child revision: {relative}: "
                f"expected {expected}, got {actual}"
            )
    return parent_manifest, parent_artifacts, parent_hashes


def _a07_follow_names() -> tuple[str, ...]:
    return tuple(candidate.name for candidate in mast_and_beam_parts("folded"))


def _correct_follow_a07(
    follow_parts: list[Part],
    scratch: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    a07_names = _a07_follow_names()
    by_name = {candidate.name: candidate for candidate in follow_parts}
    missing = sorted(set(a07_names) - set(by_name))
    if missing:
        raise RuntimeError(f"Follow is missing A07 occurrences: {missing}")

    rotation, translation = _folded_pose_delta()
    transform_id = "A07-FOLLOW-LEGACY-MAST-HINGE-TO-SHARED-A06-HINGE"
    audits: list[dict[str, object]] = []
    checks: list[dict[str, object]] = []

    for index, name in enumerate(a07_names):
        candidate = by_name[name]
        metadata_before = _metadata_record(candidate)
        record_before = _part_record(candidate)
        centre_before = np.asarray(_centre_mm(candidate), dtype=float)
        brep_before = _shape_brep_sha256(candidate, scratch, f"a07_{index:02d}_before")

        # Undo the DFR4 legacy Follow pose and apply the identical -95 degree
        # fold about the shared A06/A07 physical hinge.
        unfolded = rotate_about_y(candidate.shape, LEGACY_MAST_HINGE, -FOLLOW_FOLD_ANGLE_DEG)
        candidate.shape = rotate_about_y(unfolded, SHARED_BACK_HINGE, FOLLOW_FOLD_ANGLE_DEG)

        metadata_after = _metadata_record(candidate)
        record_after = _part_record(candidate)
        centre_after = np.asarray(_centre_mm(candidate), dtype=float)
        brep_after = _shape_brep_sha256(candidate, scratch, f"a07_{index:02d}_after")
        observed_translation = centre_after - centre_before
        translation_error = float(np.max(np.abs(observed_translation - translation)))
        topology_preserved = all(
            record_before[key] == record_after[key]
            for key in ("solid_count", "face_count", "edge_count")
        )
        volume_error = abs(float(record_after["volume_mm3"]) - float(record_before["volume_mm3"]))
        passed = (
            metadata_before == metadata_after
            and topology_preserved
            and volume_error <= 1.0e-5
            and translation_error <= 1.0e-6
            and brep_before != brep_after
        )
        checks.append(
            {
                "configuration": "follow",
                "check": "a07_occurrence_shared_hinge_rigid_transform",
                "occurrence": name,
                "physical_occurrence_id": candidate.physical_occurrence_id,
                "metadata_identity_preserved": metadata_before == metadata_after,
                "topology_preserved": topology_preserved,
                "absolute_volume_drift_mm3": round(volume_error, 9),
                "maximum_translation_error_mm": round(translation_error, 12),
                "geometry_changed": brep_before != brep_after,
                "pass": passed,
            }
        )
        audits.append(
            {
                "name": name,
                "physical_occurrence_id": candidate.physical_occurrence_id,
                "identity_basis": candidate.identity_basis,
                "definition_revision": candidate.definition_revision,
                "transform_id": transform_id,
                "source_pose": {
                    "hinge_mm": list(LEGACY_MAST_HINGE),
                    "angle_deg": FOLLOW_FOLD_ANGLE_DEG,
                    "brep_sha256": brep_before,
                    "centre_mm": [round(float(value), 9) for value in centre_before],
                    "bounds_mm": record_before["bounds_mm"],
                },
                "published_pose": {
                    "hinge_mm": list(SHARED_BACK_HINGE),
                    "angle_deg": FOLLOW_FOLD_ANGLE_DEG,
                    "brep_sha256": brep_after,
                    "centre_mm": [round(float(value), 9) for value in centre_after],
                    "bounds_mm": record_after["bounds_mm"],
                },
                "metadata_identity_preserved": metadata_before == metadata_after,
                "topology_preserved": topology_preserved,
                "volume_mm3": record_after["volume_mm3"],
            }
        )
    return audits, checks


def _follow_expected_metrics(parts: list[Part]) -> dict[str, object]:
    """Capture analytic metrics before GLB tessellation populates bbox caches."""

    expected_bounds = {
        key: function(aabb(candidate.shape)[key] for candidate in parts)
        for key, function in (
            ("xmin", min),
            ("xmax", max),
            ("ymin", min),
            ("ymax", max),
            ("zmin", min),
            ("zmax", max),
        )
    }
    expected_solids = sum(len(candidate.solid.Solids()) for candidate in parts)
    expected_volume = sum(candidate.volume_mm3 for candidate in parts)
    return {
        "bounds_mm": expected_bounds,
        "solid_count": expected_solids,
        "volume_mm3": expected_volume,
        "part_count": len(parts),
    }


def _validate_follow_exports(
    expected: dict[str, object],
    step_path: Path,
    glb_path: Path,
) -> list[dict[str, object]]:
    expected_bounds = expected["bounds_mm"]
    expected_solids = expected["solid_count"]
    expected_volume = expected["volume_mm3"]

    imported = cq.importers.importStep(str(step_path))
    imported_shape = imported.val()
    imported_bounds = aabb(imported)
    step_bound_drift = max(
        abs(imported_bounds[key] - expected_bounds[key]) for key in expected_bounds
    )
    step_volume_drift = abs(float(imported_shape.Volume()) - expected_volume)
    step_relative_volume_drift = step_volume_drift / max(expected_volume, 1.0)
    step_check = {
        "configuration": "follow",
        "check": "dfr5_follow_step_roundtrip",
        "expected_solid_count": expected_solids,
        "imported_solid_count": len(imported_shape.Solids()),
        "maximum_bounds_drift_mm": round(step_bound_drift, 12),
        "relative_volume_drift": round(step_relative_volume_drift, 15),
        "imported_valid": imported_shape.isValid(),
        "pass": (
            imported_shape.isValid()
            and len(imported_shape.Solids()) == expected_solids
            and step_bound_drift <= 0.01
            and step_relative_volume_drift <= 1.0e-7
        ),
    }

    scene = trimesh.load(glb_path, force="scene", process=False)
    glb_bounds_mm = np.asarray(scene.bounds, dtype=float) * 1000.0
    expected_array = np.asarray(
        [
            [expected_bounds["xmin"], expected_bounds["ymin"], expected_bounds["zmin"]],
            [expected_bounds["xmax"], expected_bounds["ymax"], expected_bounds["zmax"]],
        ]
    )
    glb_bound_drift = float(np.max(np.abs(glb_bounds_mm - expected_array)))
    glb_check = {
        "configuration": "follow",
        "check": "dfr5_follow_glb_roundtrip",
        "expected_geometry_count": expected["part_count"],
        "imported_geometry_count": len(scene.geometry),
        "maximum_bounds_drift_mm": round(glb_bound_drift, 9),
        "source_mesh_boundary_tolerance_mm": 0.25,
        "pass": (
            len(scene.geometry) == expected["part_count"]
            and glb_bound_drift <= 0.25
        ),
    }
    return [step_check, glb_check]


def _copy_inherited_artifact(
    parent_manifest: dict[str, object],
    state: str,
    kind: str,
    staging: Path,
) -> tuple[str, str]:
    source_name = parent_manifest["states"][state][kind]
    source = PARENT_DFR4 / source_name
    target_name = f"workcore_e6_dfr5_{state}.{kind}"
    target = staging / target_name
    shutil.copy2(source, target)
    if sha256(target) != sha256(source):
        raise RuntimeError(f"Byte inheritance failed for {state} {kind}")
    return source_name, target_name


def export_revision(output: Path, *, force: bool = False) -> dict[str, object]:
    output = output.resolve()
    parent_resolved = PARENT_DFR4.resolve()
    if output == parent_resolved or parent_resolved in output.parents:
        raise ValueError(f"DFR5 output may not overwrite or nest inside DFR4: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing DFR5 source set: {output}")

    parent_manifest, parent_artifacts, parent_hashes_before = _load_and_verify_parent()
    generator_hashes = {}
    for relative in GENERATOR_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        generator_hashes[relative] = sha256(path)

    states = _build_states()
    checks = _validate(states)
    initial_failures = [check for check in checks if not check["pass"]]
    if initial_failures:
        raise RuntimeError(
            "DFR4 parent-state regeneration failed before the isolated A07 correction:\n"
            + json.dumps(initial_failures, ensure_ascii=False, indent=2)
        )

    # Confirm that the current hash-pinned generator regenerates the same state
    # identities captured by the DFR4 manifest before changing Follow.
    for spec in STATE_SPECS:
        state = spec.release_state
        parts = states[state]
        parent_state = parent_manifest["states"][state]
        a08 = [part for part in parts if part.name.startswith("footrest_")]
        regenerated_a08 = [_part_record(part) for part in a08]
        a08_comparisons = [
            _part_record_equivalence(actual, expected)
            for actual, expected in zip(
                regenerated_a08, parent_state["a08_occurrences"]
            )
        ]
        a08_matches = (
            len(regenerated_a08) == len(parent_state["a08_occurrences"])
            and all(comparison[0] for comparison in a08_comparisons)
        )
        checks.append(
            {
                "configuration": state,
                "check": "parent_dfr4_state_identity_regenerated",
                "part_count_matches": len(parts) == parent_state["part_count"],
                "a08_occurrences_match": a08_matches,
                "a08_maximum_bounds_drift_mm": round(
                    max((comparison[1] for comparison in a08_comparisons), default=0.0),
                    9,
                ),
                "a08_non_bound_mismatched_fields": sorted(
                    {
                        field
                        for comparison in a08_comparisons
                        for field in comparison[2]
                    }
                ),
                "pass": (
                    len(parts) == parent_state["part_count"]
                    and a08_matches
                ),
            }
        )

    before_contracts = {
        state: _state_occurrence_contract(parts) for state, parts in states.items()
    }
    before_part_records = {
        state: {part.name: _part_record(part) for part in parts}
        for state, parts in states.items()
    }

    temp_parent = output.parent
    with tempfile.TemporaryDirectory(prefix=".e6_dfr5_a07_hinge_", dir=temp_parent) as raw:
        staging = Path(raw)
        scratch = staging / ".brep_audit"
        scratch.mkdir()
        follow_audits, correction_checks = _correct_follow_a07(states["follow"], scratch)
        checks.extend(correction_checks)
        scratch.rmdir()

        after_contracts = {
            state: _state_occurrence_contract(parts) for state, parts in states.items()
        }
        a07_name_set = set(_a07_follow_names())
        follow_before_records = before_part_records["follow"]
        follow_after_records = {
            part.name: _part_record(part)
            for part in states["follow"]
        }
        changed_follow_names = sorted(
            name
            for name in follow_before_records
            if follow_before_records[name] != follow_after_records[name]
        )
        checks.append(
            {
                "configuration": "follow",
                "check": "only_complete_a07_occurrence_set_changed",
                "expected_changed_occurrence_count": len(a07_name_set),
                "actual_changed_occurrence_count": len(changed_follow_names),
                "changed_occurrences": changed_follow_names,
                "pass": set(changed_follow_names) == a07_name_set,
            }
        )
        for state in INHERITED_STATES:
            checks.append(
                {
                    "configuration": state,
                    "check": "non_follow_occurrence_contract_unchanged",
                    "before_sha256": before_contracts[state]["occurrence_contract_sha256"],
                    "after_sha256": after_contracts[state]["occurrence_contract_sha256"],
                    "pass": before_contracts[state] == after_contracts[state],
                }
            )

        artifacts: dict[str, dict[str, object]] = {}
        inheritance: dict[str, object] = {}
        state_records: dict[str, object] = {}
        for spec in STATE_SPECS:
            state = spec.release_state
            parts = states[state]
            if state == "follow":
                step_name = "workcore_e6_dfr5_follow.step"
                glb_name = "workcore_e6_dfr5_follow.glb"
                follow_expected = _follow_expected_metrics(parts)
                _export_step(parts, staging / step_name, state)
                _export_glb(parts, staging / glb_name)
                inheritance[state] = {
                    "mode": "isolated_a07_pose_revision",
                    "parent_step": parent_manifest["states"][state]["step"],
                    "parent_glb": parent_manifest["states"][state]["glb"],
                    "byte_identical_to_parent": False,
                }
                checks.extend(
                    _validate_follow_exports(
                        follow_expected,
                        staging / step_name,
                        staging / glb_name,
                    )
                )
            else:
                parent_step, step_name = _copy_inherited_artifact(
                    parent_manifest, state, "step", staging
                )
                parent_glb, glb_name = _copy_inherited_artifact(
                    parent_manifest, state, "glb", staging
                )
                inheritance[state] = {
                    "mode": "byte_for_byte_parent_inheritance",
                    "parent_step": parent_step,
                    "parent_glb": parent_glb,
                    "byte_identical_to_parent": True,
                }
                for kind, parent_name, child_name in (
                    ("step", parent_step, step_name),
                    ("glb", parent_glb, glb_name),
                ):
                    parent_digest = parent_artifacts[parent_name]["sha256"]
                    child_digest = sha256(staging / child_name)
                    checks.append(
                        {
                            "configuration": state,
                            "check": f"non_follow_{kind}_byte_identity_to_dfr4",
                            "parent_sha256": parent_digest,
                            "dfr5_sha256": child_digest,
                            "pass": parent_digest == child_digest,
                        }
                    )

            for filename in (step_name, glb_name):
                path = staging / filename
                artifacts[filename] = {
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }

            a08 = [part for part in parts if part.name.startswith("footrest_")]
            a07_configuration = (
                "folded"
                if state == "follow"
                else (
                    "focus"
                    if state in ("focus", "focus_footrest_open")
                    else "stowed"
                )
            )
            state_a07_names = {
                part.name for part in mast_and_beam_parts(a07_configuration)
            }
            a07 = [part for part in parts if part.name in state_a07_names]
            state_records[state] = {
                "source_configuration": spec.source_configuration,
                "primary_render_state": spec.primary_render_state,
                "footrest_pose": a08[0].mechanism_pose,
                "optional_footrest_open_available": optional_footrest_open_available(
                    spec.source_configuration
                ),
                "step": step_name,
                "glb": glb_name,
                "glb_units": "meters",
                "part_count": len(parts),
                "a08_occurrence_count": len(a08),
                "a08_total_mass_kg": round(sum(part.mass_kg for part in a08), 9),
                "a08_occurrences": [_part_record(part) for part in a08],
                "a07_occurrence_count": len(a07),
                "a07_occurrences": [
                    {
                        **_metadata_record(part),
                        **_part_record(part),
                    }
                    for part in a07
                ],
                "occurrence_contract": after_contracts[state],
                "artifact_inheritance": inheritance[state],
            }

        failures = [check for check in checks if not check["pass"]]
        if failures:
            raise RuntimeError(
                "E6-DFR5 A07 source validation failed:\n"
                + json.dumps(failures, ensure_ascii=False, indent=2)
            )

        parent_hashes_after = {
            filename: sha256(PARENT_DFR4 / filename) for filename in parent_hashes_before
        }
        if parent_hashes_after != parent_hashes_before:
            raise RuntimeError(
                "Immutable E6-DFR4 source drifted during DFR5 export: "
                + json.dumps(
                    {
                        name: {
                            "before": parent_hashes_before[name],
                            "after": parent_hashes_after.get(name),
                        }
                        for name in parent_hashes_before
                        if parent_hashes_before[name] != parent_hashes_after.get(name)
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

        delta_rotation, delta_translation = _folded_pose_delta()
        generated_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema": "workcore-e6-controlled-source-revision-v2",
            "revision": "E6-DFR5-A07-SHARED-HINGE",
            "status": "PASS",
            "generated_at_utc": generated_at,
            "scope": (
                "One principle correction only: the complete conserved A07 assembly "
                "shares the A06 backrest fold hinge in Follow; this is not a complete "
                "product certification"
            ),
            "parent_revision": {
                "revision": parent_manifest["revision"],
                "directory": str(PARENT_DFR4.relative_to(ROOT)).replace("\\", "/"),
                "manifest": PARENT_MANIFEST_NAME,
                "manifest_sha256": parent_hashes_before[PARENT_MANIFEST_NAME],
                "all_parent_file_sha256": parent_hashes_before,
                "immutability_recheck": "PASS",
            },
            "principle_correction": {
                "count": 1,
                "id": "A07_FOLLOW_SHARED_A06_HINGE",
                "description": (
                    "In Follow only, undo the complete A07 occurrence set's legacy "
                    "-95 degree pose about (160,0,509), then apply the same -95 degree "
                    "pose about the physical A06 BACK_HINGE (160,0,515)."
                ),
                "affected_state": "follow",
                "affected_subsystem": "A07",
                "affected_occurrence_count": len(follow_audits),
                "legacy_hinge_mm": list(LEGACY_MAST_HINGE),
                "shared_back_hinge_mm": list(SHARED_BACK_HINGE),
                "fold_angle_deg": FOLLOW_FOLD_ANGLE_DEG,
                "old_folded_to_corrected_folded_transform": {
                    "type": "rigid_transform",
                    "rotation": "identity",
                    "translation_mm": [
                        round(float(value), 12) for value in delta_translation
                    ],
                    "matrix4x4_row_major": _matrix4x4(
                        delta_rotation, delta_translation
                    ),
                },
                "occurrence_transform_audit": follow_audits,
            },
            "non_follow_identity": {
                "states": list(INHERITED_STATES),
                "policy": "STEP and GLB inherited byte for byte from E6-DFR4-A08",
                "status": "PASS",
            },
            "footrest_contract_version": CONTRACT_VERSION,
            "primary_defaults": {
                "follow": default_footrest_pose("follow").value,
                "ride": default_footrest_pose("seat").value,
                "cafe": default_footrest_pose("cafe").value,
                "focus": default_footrest_pose("desk").value,
            },
            "optional_validation_states": [
                "cafe_footrest_open",
                "focus_footrest_open",
            ],
            "generator_sha256": generator_hashes,
            "validation": {
                "status": "PASS",
                "check_count": len(checks),
                "failed_count": 0,
                "checks": checks,
            },
            "states": state_records,
            "artifacts": {
                "files": [
                    {
                        "path": str((output / filename).relative_to(ROOT)).replace(
                            "\\", "/"
                        ),
                        **record,
                    }
                    for filename, record in sorted(artifacts.items())
                ]
            },
        }
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest["manifest_sha256_before_self_entry"] = sha256(manifest_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        hashes = {
            "schema": "workcore-e6-sha256-index-v1",
            "revision": manifest["revision"],
            "generated_at_utc": generated_at,
            "files": {
                MANIFEST_NAME: {
                    "bytes": manifest_path.stat().st_size,
                    "sha256": sha256(manifest_path),
                },
                **{
                    filename: record for filename, record in sorted(artifacts.items())
                },
            },
        }
        (staging / HASHES_NAME).write_text(
            json.dumps(hashes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(staging, output)

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    manifest = export_revision(args.output, force=args.force)
    print(
        json.dumps(
            {
                "revision": manifest["revision"],
                "status": manifest["status"],
                "output": str(args.output.resolve()),
                "states": list(manifest["states"]),
                "a07_follow_occurrence_count": manifest["principle_correction"][
                    "affected_occurrence_count"
                ],
                "validation_check_count": manifest["validation"]["check_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
