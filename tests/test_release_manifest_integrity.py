from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from artifact_publish import PUBLISH_PROTOCOL_VERSION  # noqa: E402
from release_manifest import expected_artifact_paths  # noqa: E402
from verify_release import (  # noqa: E402
    BUILD,
    ROOT,
    _manifest_structure_failures,
    _tree_digest,
    _verify_records,
)


def _record(logical_path: str) -> dict:
    payload = logical_path.encode("utf-8")
    return {
        "path": logical_path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _refresh_artifact_summary(manifest: dict) -> None:
    records = manifest["artifacts"]["files"]
    manifest["artifacts"]["count"] = len(records)
    manifest["artifacts"]["tree_sha256"] = _tree_digest(records)
    manifest["managed_paths"] = [record["path"] for record in records]


def _minimal_valid_manifest() -> dict:
    core_paths = [
        path.relative_to(ROOT).as_posix()
        for path in expected_artifact_paths(BUILD)
    ]
    artifact_records = [_record(path) for path in core_paths]
    artifact_records.append(_record("build/parts/test_manufactured_part.step"))
    source_records: list[dict] = []
    return {
        "run_id": "manifest-integrity-test",
        "publish_protocol_version": PUBLISH_PROTOCOL_VERSION,
        "logical_build_root": "build",
        "staged_preflight_pass": True,
        "sources": {
            "count": 0,
            "tree_sha256": _tree_digest(source_records),
            "files": source_records,
        },
        "artifacts": {
            "count": len(artifact_records),
            "tree_sha256": _tree_digest(artifact_records),
            "files": artifact_records,
        },
        "managed_paths": [record["path"] for record in artifact_records],
    }


def _reasons(failures: list[dict]) -> set[str]:
    return {failure["reason"] for failure in failures}


class ReleaseManifestIntegrityTests(unittest.TestCase):
    def test_virtual_minimal_manifest_has_no_structure_failures(self) -> None:
        self.assertEqual(
            _manifest_structure_failures(_minimal_valid_manifest()),
            [],
        )

    def test_tampered_count_and_tree_summary_fail(self) -> None:
        manifest = _minimal_valid_manifest()
        manifest["artifacts"]["count"] += 1
        manifest["artifacts"]["tree_sha256"] = "0" * 64

        reasons = _reasons(_manifest_structure_failures(manifest))

        self.assertIn("record_count_mismatch", reasons)
        self.assertIn("tree_digest_mismatch", reasons)

    def test_missing_required_core_path_fails(self) -> None:
        manifest = _minimal_valid_manifest()
        missing_path = "build/validation.json"
        manifest["artifacts"]["files"] = [
            record
            for record in manifest["artifacts"]["files"]
            if record["path"] != missing_path
        ]
        _refresh_artifact_summary(manifest)

        failures = _manifest_structure_failures(manifest)
        missing_failures = [
            failure
            for failure in failures
            if failure["reason"] == "required_artifact_records_missing"
        ]

        self.assertEqual(len(missing_failures), 1)
        self.assertIn(missing_path, missing_failures[0]["paths"])

    def test_duplicate_artifact_path_fails_both_helpers(self) -> None:
        manifest = _minimal_valid_manifest()
        duplicate = copy.deepcopy(manifest["artifacts"]["files"][-1])
        manifest["artifacts"]["files"].append(duplicate)
        _refresh_artifact_summary(manifest)

        structure_reasons = _reasons(_manifest_structure_failures(manifest))
        record_reasons = _reasons(
            _verify_records([duplicate, copy.deepcopy(duplicate)], scope="artifact")
        )

        self.assertIn("managed_paths_mismatch_or_duplicate", structure_reasons)
        self.assertIn("invalid_managed_path", structure_reasons)
        self.assertIn("duplicate_manifest_path", record_reasons)

    def test_out_of_bounds_artifact_paths_fail_both_helpers(self) -> None:
        manifest = _minimal_valid_manifest()
        manifest["artifacts"]["files"][-1] = _record("docs/outside-build.step")
        _refresh_artifact_summary(manifest)

        structure_reasons = _reasons(_manifest_structure_failures(manifest))
        outside_reasons = _reasons(
            _verify_records([_record("docs/outside-build.step")], scope="artifact")
        )
        traversal_reasons = _reasons(
            _verify_records([_record("build/../escape.step")], scope="artifact")
        )

        self.assertIn("invalid_managed_path", structure_reasons)
        self.assertIn("artifact_path_outside_build", outside_reasons)
        self.assertIn("unsafe_manifest_path", traversal_reasons)


if __name__ == "__main__":
    unittest.main()
