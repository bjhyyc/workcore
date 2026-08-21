from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from artifact_publish import PUBLISH_PROTOCOL_VERSION, scan_unmanaged_files, validate_managed_records
from release_manifest import expected_artifact_paths


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"

STAGE_KEYS = {
    "evt0": "EVT0_unoccupied_or_dummy_prototype",
    "human": "human_occupied_testing",
    "dvt": "design_freeze_DVT",
    "pvt": "PVT_mass_production",
    "mp": "PVT_mass_production",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_digest(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(f"{record['path']}\0{record['sha256']}\n".encode("utf-8"))
    return digest.hexdigest()


def _safe_workspace_path(logical: str) -> Path | None:
    logical_path = Path(str(logical).replace("\\", "/"))
    if not logical or logical_path.is_absolute() or ".." in logical_path.parts:
        return None
    candidate = (ROOT / logical_path).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate


def _verify_records(records: list[dict], *, scope: str) -> list[dict]:
    failures: list[dict] = []
    seen: set[str] = set()
    for record in records:
        logical = str(record.get("path", ""))
        if logical in seen:
            failures.append({"path": logical, "reason": "duplicate_manifest_path"})
            continue
        seen.add(logical)
        path = _safe_workspace_path(logical)
        if path is None:
            failures.append({"path": logical, "reason": "unsafe_manifest_path"})
            continue
        if scope == "artifact":
            try:
                path.relative_to(BUILD.resolve())
            except ValueError:
                failures.append({"path": logical, "reason": "artifact_path_outside_build"})
                continue
        if not path.is_file():
            failures.append({"path": logical, "reason": "missing"})
            continue
        actual_size = path.stat().st_size
        if actual_size != record.get("bytes"):
            failures.append(
                {"path": logical, "reason": "size_changed", "expected": record.get("bytes"), "actual": actual_size}
            )
            continue
        actual_hash = _sha256(path)
        if actual_hash != record.get("sha256"):
            failures.append(
                {"path": logical, "reason": "hash_changed", "expected": record.get("sha256"), "actual": actual_hash}
            )
    return failures


def _manifest_structure_failures(manifest: dict) -> list[dict]:
    failures: list[dict] = []
    if manifest.get("publish_protocol_version") != PUBLISH_PROTOCOL_VERSION:
        failures.append({"scope": "manifest", "reason": "unsupported_publish_protocol"})
    if manifest.get("logical_build_root") != "build":
        failures.append({"scope": "manifest", "reason": "invalid_logical_build_root"})
    if manifest.get("staged_preflight_pass") is not True:
        failures.append({"scope": "manifest", "reason": "staged_preflight_not_passed"})
    if not manifest.get("run_id"):
        failures.append({"scope": "manifest", "reason": "missing_run_id"})

    for section_name in ("sources", "artifacts"):
        section = manifest.get(section_name, {})
        records = section.get("files", [])
        if not isinstance(records, list):
            failures.append({"scope": "manifest", "reason": "invalid_record_list", "section": section_name})
            continue
        if section.get("count") != len(records):
            failures.append(
                {
                    "scope": "manifest",
                    "reason": "record_count_mismatch",
                    "section": section_name,
                    "declared": section.get("count"),
                    "actual": len(records),
                }
            )
        try:
            digest = _tree_digest(records)
        except (KeyError, TypeError):
            failures.append({"scope": "manifest", "reason": "invalid_tree_record", "section": section_name})
        else:
            if section.get("tree_sha256") != digest:
                failures.append({"scope": "manifest", "reason": "tree_digest_mismatch", "section": section_name})

    artifact_records = manifest.get("artifacts", {}).get("files", [])
    artifact_paths = [str(record.get("path", "")) for record in artifact_records if isinstance(record, dict)]
    if set(manifest.get("managed_paths", [])) != set(artifact_paths) or len(artifact_paths) != len(set(artifact_paths)):
        failures.append({"scope": "manifest", "reason": "managed_paths_mismatch_or_duplicate"})
    required_paths = {
        path.relative_to(ROOT).as_posix()
        for path in expected_artifact_paths(BUILD)
    }
    missing_required = sorted(required_paths - set(artifact_paths))
    if missing_required:
        failures.append(
            {"scope": "manifest", "reason": "required_artifact_records_missing", "paths": missing_required}
        )
    part_paths = [path for path in artifact_paths if path.startswith("build/parts/") and path.endswith(".step")]
    if not part_paths:
        failures.append({"scope": "manifest", "reason": "no_manufactured_part_records"})
    try:
        validate_managed_records(ROOT, BUILD, artifact_records)
    except (ValueError, KeyError, TypeError) as exc:
        failures.append({"scope": "manifest", "reason": "invalid_managed_path", "detail": str(exc)})
    return failures


def _is_release_go(decision: str) -> bool:
    normalized = decision.strip().upper()
    return normalized == "GO" or normalized.startswith("PASS")


def _model_integrity_failures(readiness: dict, build_status: dict) -> list[dict]:
    failures: list[dict] = []
    if build_status.get("status") != "COMPLETE":
        failures.append(
            {
                "scope": "artifact",
                "reason": "build_not_complete",
                "status": build_status.get("status", "MISSING"),
            }
        )
    traceability = readiness.get("traceability_integrity", {})
    if traceability and not traceability.get("pass", False):
        failures.append({"scope": "traceability", "reason": "integrity_check_failed"})
    production_bom = readiness.get("production_bom", {})
    if production_bom.get("pose_identity_status") != "DEMONSTRATED":
        failures.append(
            {
                "scope": "configuration",
                "reason": "pose_invariant_part_identity_not_demonstrated",
                "status": production_bom.get("pose_identity_status", "MISSING"),
            }
        )
    spread = production_bom.get("configuration_mass_spread_kg")
    if spread is not None and float(spread) > 0.001:
        failures.append(
            {
                "scope": "configuration",
                "reason": "pose_mass_spread_exceeds_0_001kg",
                "actual_kg": spread,
            }
        )
    if production_bom.get("definition_conflicts", 0):
        failures.append(
            {
                "scope": "configuration",
                "reason": "canonical_part_definition_conflicts",
                "count": production_bom["definition_conflicts"],
            }
        )
    return failures


def verify(stage: str) -> tuple[dict, bool]:
    manifest_path = BUILD / "release_manifest.json"
    if not manifest_path.is_file():
        result = {"stage": stage, "pass": False, "failures": [{"reason": "missing_release_manifest"}]}
        return result, False

    build_status_path = BUILD / "build_status.json"
    try:
        first_status_bytes = build_status_path.read_bytes()
        first_status = json.loads(first_status_bytes)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        second_status_bytes = build_status_path.read_bytes()
        second_status = json.loads(second_status_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "stage": stage,
            "pass": False,
            "failures": [{"scope": "artifact", "reason": "unreadable_status_or_manifest", "detail": str(exc)}],
        }
        return result, False

    failures = _manifest_structure_failures(manifest)
    source_records = manifest.get("sources", {}).get("files", [])
    artifact_records = manifest.get("artifacts", {}).get("files", [])
    if isinstance(source_records, list):
        failures.extend({"scope": "source", **item} for item in _verify_records(source_records, scope="source"))
    if isinstance(artifact_records, list):
        failures.extend({"scope": "artifact", **item} for item in _verify_records(artifact_records, scope="artifact"))
    if manifest.get("sources", {}).get("missing"):
        failures.append({"scope": "source", "reason": "manifest_recorded_missing", "paths": manifest["sources"]["missing"]})
    if manifest.get("artifacts", {}).get("missing"):
        failures.append({"scope": "artifact", "reason": "manifest_recorded_missing", "paths": manifest["artifacts"]["missing"]})
    if manifest.get("automated_checks", {}).get("failed", 0):
        failures.append(
            {"scope": "model", "reason": "failed_automated_checks", "count": manifest["automated_checks"]["failed"]}
        )

    readiness_path = BUILD / "production_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8")) if readiness_path.is_file() else {}
    if first_status_bytes != second_status_bytes:
        failures.append({"scope": "artifact", "reason": "status_changed_during_verification"})
    if first_status.get("status") != "COMPLETE" or second_status.get("status") != "COMPLETE":
        failures.append(
            {
                "scope": "artifact",
                "reason": "publication_not_complete",
                "first": first_status.get("status"),
                "second": second_status.get("status"),
            }
        )
    identities = {
        "manifest": (manifest.get("run_id"), manifest.get("revision")),
        "first_status": (first_status.get("run_id"), first_status.get("revision")),
        "second_status": (second_status.get("run_id"), second_status.get("revision")),
    }
    if len(set(identities.values())) != 1 or not manifest.get("run_id"):
        failures.append({"scope": "artifact", "reason": "status_manifest_identity_mismatch", "identities": identities})
    readiness_revision = readiness.get("revision")
    if readiness_revision != manifest.get("revision"):
        failures.append(
            {
                "scope": "readiness",
                "reason": "revision_mismatch",
                "manifest": manifest.get("revision"),
                "readiness": readiness_revision,
            }
        )
    failures.extend(_model_integrity_failures(readiness, second_status))

    stage_decision = None
    if stage != "model":
        key = STAGE_KEYS[stage]
        stage_decision = manifest.get("stage_decision", {}).get(key, "MISSING")
        if not _is_release_go(stage_decision):
            failures.append({"scope": "stage_gate", "reason": "not_released", "stage_key": key, "decision": stage_decision})

    warnings = []
    if manifest.get("source_control", {}).get("commit") is None:
        warnings.append("No immutable source-control commit is associated with this build.")
    managed_paths = set(manifest.get("managed_paths", []))
    stale = scan_unmanaged_files(BUILD, managed_paths, ROOT)
    if stale:
        warnings.append("Build directory contains files outside the current release manifest; package only manifest-listed artifacts.")

    result = {
        "revision": manifest.get("revision"),
        "stage": stage,
        "pass": not failures,
        "stage_decision": stage_decision,
        "automated_checks": manifest.get("automated_checks"),
        "failures": failures,
        "warnings": warnings,
        "excluded_stale_candidates": stale,
    }
    return result, not failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify WorkCore build provenance and an explicit development stage gate.")
    parser.add_argument("--stage", choices=("model", *STAGE_KEYS), default="model")
    args = parser.parse_args()
    result, passed = verify(args.stage)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
