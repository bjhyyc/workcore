from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from artifact_publish import PUBLISH_PROTOCOL_VERSION, atomic_write_bytes


CURRENT_CONFIGURATIONS = (
    "stowed",
    "follow",
    "obstacle",
    "seat",
    "cafe",
    "internal",
    "transfer",
    "desk",
    "deployed",
)

CURRENT_ASSEMBLY_STEMS = (
    "workcore_stowed",
    "workcore_follow_closed",
    "workcore_obstacle_assist",
    "workcore_seat_ready",
    "workcore_cafe",
    "workcore_internal_layout",
    "workcore_transfer_ready",
    "workcore_desk",
    "workcore_canopy_deployed",
)

CURRENT_REVIEW_FILES = (
    "workcore_desk_occupied_review.glb",
    "workcore_storage_review.glb",
    "workcore_storage_wheel_review.glb",
    "workcore_electrical_thermal_review.glb",
    "workcore_e6_review.html",
    "workcore_e6_review_offline.html",
    "workcore_e4_review.html",
    "workcore_e4_review_offline.html",
)

CURRENT_REPORT_FILES = (
    "build_status.json",
    "bom.csv",
    "production_bom.csv",
    "cots_interface_register.csv",
    "tolerance_register.csv",
    "validation.json",
    "engineering_report.json",
    "mobility_report.json",
    "power_thermal_report.json",
    "production_readiness_report.json",
    "requirements_traceability.csv",
    "risk_register.csv",
    "dvpr.csv",
    "supplier_release_register.csv",
    "production_gate_checklist.csv",
    "access_scenarios.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, root: Path, logical_path: Path | None = None) -> dict:
    recorded_path = logical_path or path
    return {
        "path": recorded_path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _tree_digest(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(f"{record['path']}\0{record['sha256']}\n".encode("utf-8"))
    return digest.hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _source_control(root: Path) -> dict:
    head = root / ".git" / "HEAD"
    if not head.exists():
        return {"commit": None, "status": "NO_GIT_METADATA"}
    value = head.read_text(encoding="utf-8").strip()
    if value.startswith("ref: "):
        ref_name = value[5:]
        ref_path = root / ".git" / ref_name
        if ref_path.exists():
            return {"commit": ref_path.read_text(encoding="utf-8").strip(), "ref": ref_name, "status": "COMMIT_FOUND"}
        return {"commit": None, "ref": ref_name, "status": "UNBORN_BRANCH"}
    return {"commit": value or None, "status": "DETACHED_HEAD"}


def expected_artifact_paths(build_dir: Path, part_names: list[str] | None = None) -> list[Path]:
    paths: list[Path] = []
    for stem in CURRENT_ASSEMBLY_STEMS:
        paths.extend((build_dir / f"{stem}.step", build_dir / f"{stem}.glb"))
    paths.extend(build_dir / f"preview_{name}.png" for name in CURRENT_CONFIGURATIONS)
    paths.extend(
        (
            build_dir / "preview_desk_occupied.png",
            build_dir / "preview_storage.png",
            build_dir / "preview_storage_wheel.png",
            build_dir / "preview_electrical_thermal.png",
        )
    )
    paths.extend(build_dir / name for name in CURRENT_REVIEW_FILES)
    paths.extend(build_dir / name for name in CURRENT_REPORT_FILES)
    if part_names:
        paths.extend(build_dir / "parts" / f"{name}.step" for name in sorted(set(part_names)))
    return paths


def write_release_manifest(
    root: Path,
    build_dir: Path,
    *,
    revision: str,
    configs: dict,
    reports: dict,
    logical_build_dir: Path | None = None,
    run_id: str,
) -> dict:
    logical_build_dir = logical_build_dir or build_dir
    source_paths = [
        root / ".gitignore",
        root / "README.md",
        root / "build.ps1",
        root / "requirements.txt",
    ]
    lock = root / "requirements-lock.txt"
    if lock.exists():
        source_paths.append(lock)
    source_paths.extend(sorted((root / "cad").glob("*.py")))
    source_paths.extend(sorted((root / "docs").glob("*.md")))
    source_paths.extend(sorted((root / "tests").glob("*.py")))
    missing_sources = [path.relative_to(root).as_posix() for path in source_paths if not path.is_file()]
    if missing_sources:
        raise FileNotFoundError(f"Release source set is incomplete: {missing_sources}")
    source_records = [_record(path, root) for path in source_paths if path.is_file()]

    part_names = [part.name for parts in configs.values() for part in parts]
    artifact_paths = expected_artifact_paths(build_dir, part_names)
    missing_artifacts = [path.relative_to(root).as_posix() for path in artifact_paths if not path.is_file()]
    if missing_artifacts:
        raise FileNotFoundError(f"Release artifact set is incomplete: {missing_artifacts}")
    logical_artifact_paths = [
        logical_build_dir / path.relative_to(build_dir)
        for path in artifact_paths
    ]
    logical_names = [path.relative_to(root).as_posix() for path in logical_artifact_paths]
    if len(logical_names) != len(set(logical_names)):
        raise ValueError("Release artifact set contains duplicate logical paths")
    artifact_records = [
        _record(path, root, logical)
        for path, logical in zip(artifact_paths, logical_artifact_paths, strict=True)
    ]

    current_top_level = {path.resolve() for path in artifact_paths if path.parent == build_dir}
    excluded_top_level = sorted(
        path.relative_to(root).as_posix()
        for path in build_dir.iterdir()
        if path.is_file() and path.resolve() not in current_top_level and path.name != "release_manifest.json"
    )

    automated_reports = ("geometry", "engineering", "mobility", "power_thermal")
    check_counts = {
        name: {
            "total": len(reports[name].get("checks", [])),
            "failed": sum(not check.get("pass", False) for check in reports[name].get("checks", [])),
        }
        for name in automated_reports
    }
    geometry_checks = reports["geometry"].get("checks", [])
    solid_validity = sum(str(check.get("check", "")).startswith("solid_valid:") for check in geometry_checks)
    total_checks = sum(item["total"] for item in check_counts.values())
    failed_checks = sum(item["failed"] for item in check_counts.values())
    if failed_checks:
        raise ValueError(f"Cannot manifest {failed_checks} failed automated checks")
    traceability = reports["readiness"].get("traceability_integrity", {})
    if not traceability.get("pass", False):
        raise ValueError("Cannot manifest a release with failed traceability integrity")

    manifest = {
        "schema_version": 1,
        "revision": revision,
        "run_id": run_id,
        "publish_protocol_version": PUBLISH_PROTOCOL_VERSION,
        "logical_build_root": logical_build_dir.relative_to(root).as_posix(),
        "staged_preflight_pass": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_control": _source_control(root),
        "environment": {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "packages": {
                "cadquery": _package_version("cadquery"),
                "cadquery-ocp": _package_version("cadquery-ocp"),
                "trimesh": _package_version("trimesh"),
                "vtk": _package_version("vtk"),
            },
        },
        "sources": {
            "count": len(source_records),
            "tree_sha256": _tree_digest(source_records),
            "missing": missing_sources,
            "files": source_records,
        },
        "artifacts": {
            "count": len(artifact_records),
            "tree_sha256": _tree_digest(artifact_records),
            "missing": missing_artifacts,
            "excluded_stale_candidates": excluded_top_level,
            "files": artifact_records,
        },
        "automated_checks": {
            "total": total_checks,
            "failed": failed_checks,
            "solid_validity": solid_validity,
            "semantic_or_analytical": total_checks - solid_validity,
            "by_report": check_counts,
            "scope_note": "Solid validity and nominal analytical checks are not physical, tolerance, regulatory, supplier or production evidence.",
        },
        "stage_decision": reports["readiness"].get("stage_decision", {}),
        "managed_paths": sorted(record["path"] for record in artifact_records),
    }
    target = build_dir / "release_manifest.json"
    atomic_write_bytes(target, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return manifest
