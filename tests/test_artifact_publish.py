from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from artifact_publish import (  # noqa: E402
    PUBLISH_PROTOCOL_VERSION,
    publish_staged_release,
    validate_managed_records,
)


def _complete_status(run_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "run_id": run_id,
            "status": "COMPLETE",
        },
        sort_keys=True,
    ).encode("utf-8")


def _record(logical_path: str, payload: bytes) -> dict:
    return {
        "path": logical_path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _manifest(run_id: str, payloads: list[tuple[str, bytes]]) -> dict:
    records = [_record(logical_path, payload) for logical_path, payload in payloads]
    return {
        "revision": "TEST",
        "run_id": run_id,
        "publish_protocol_version": PUBLISH_PROTOCOL_VERSION,
        "managed_paths": [record["path"] for record in records],
        "artifacts": {"files": records},
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _stage_release(
    transaction_root: Path,
    run_id: str,
    payloads: list[tuple[str, bytes]],
) -> tuple[Path, dict]:
    staged_build = transaction_root / "staging" / "build"
    manifest = _manifest(run_id, payloads)
    for logical_path, payload in payloads:
        relative = Path(logical_path).relative_to("build")
        _write(staged_build / relative, payload)
    _write(
        staged_build / "release_manifest.json",
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
    )
    return staged_build, manifest


def _install_public_release(
    root: Path,
    run_id: str,
    payloads: list[tuple[str, bytes]],
) -> dict:
    manifest = _manifest(run_id, payloads)
    for logical_path, payload in payloads:
        _write(root / logical_path, payload)
    _write(
        root / "build" / "release_manifest.json",
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
    )
    return manifest


def _snapshot_files(directory: Path) -> dict[str, bytes]:
    if not directory.exists():
        return {}
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


class ArtifactPublishTests(unittest.TestCase):
    def test_rejects_paths_that_escape_the_public_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            public_build = root / "build"
            public_build.mkdir(parents=True)
            sentinel = public_build / "user" / "keep.txt"
            _write(sentinel, b"keep")
            before = _snapshot_files(public_build)

            run_id = "unsafe-run"
            staged_build = Path(directory) / "transaction" / "staging" / "build"
            staged_build.mkdir(parents=True)
            unsafe_path = "build/../escaped.txt"
            manifest = {
                "revision": "TEST",
                "run_id": run_id,
                "publish_protocol_version": PUBLISH_PROTOCOL_VERSION,
                "managed_paths": [unsafe_path],
                "artifacts": {
                    "files": [
                        {
                            "path": unsafe_path,
                            "bytes": 0,
                            "sha256": hashlib.sha256(b"").hexdigest(),
                        }
                    ]
                },
            }
            _write(
                staged_build / "release_manifest.json",
                json.dumps(manifest).encode("utf-8"),
            )

            with self.assertRaisesRegex(ValueError, "Unsafe managed path"):
                publish_staged_release(
                    root=root,
                    staged_build=staged_build,
                    public_build=public_build,
                    manifest=manifest,
                    run_id=run_id,
                )

            self.assertEqual(_snapshot_files(public_build), before)
            self.assertFalse((root / "escaped.txt").exists())
            self.assertFalse((root / ".build-publish.lock").exists())

    def test_rejects_a_public_build_root_outside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            root.mkdir()
            outside_build = base / "outside" / "build"

            with self.assertRaisesRegex(
                ValueError,
                "Published build root must remain inside the workspace",
            ):
                validate_managed_records(root, outside_build, [])

    def test_successful_publish_preserves_unknown_nested_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            public_build = root / "build"
            unknown = public_build / "user-owned" / "nested" / "notes.txt"
            _write(unknown, b"do not replace")

            run_id = "successful-run"
            payloads = [
                ("build/build_status.json", _complete_status(run_id)),
                ("build/generated/report.json", b'{"version": 2}'),
            ]
            staged_build, manifest = _stage_release(base / "transaction", run_id, payloads)

            result = publish_staged_release(
                root=root,
                staged_build=staged_build,
                public_build=public_build,
                manifest=manifest,
                run_id=run_id,
            )

            self.assertEqual(unknown.read_bytes(), b"do not replace")
            self.assertEqual(
                (public_build / "generated" / "report.json").read_bytes(),
                b'{"version": 2}',
            )
            self.assertEqual(
                result["unmanaged_files_preserved"],
                ["build/user-owned/nested/notes.txt"],
            )

    def test_injected_replacement_failure_rolls_back_the_complete_public_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            public_build = root / "build"
            old_run_id = "old-run"
            old_payloads = [
                ("build/build_status.json", _complete_status(old_run_id)),
                ("build/generated/a.txt", b"old-a"),
                ("build/generated/nested/b.txt", b"old-b"),
            ]
            _install_public_release(root, old_run_id, old_payloads)
            _write(public_build / "user-owned" / "nested" / "keep.bin", b"unknown")
            before = _snapshot_files(public_build)

            new_run_id = "new-run"
            new_payloads = [
                ("build/build_status.json", _complete_status(new_run_id)),
                ("build/generated/a.txt", b"new-a"),
                ("build/generated/brand-new.txt", b"new-file"),
                ("build/generated/nested/b.txt", b"new-b"),
            ]
            staged_build, manifest = _stage_release(base / "transaction", new_run_id, new_payloads)

            with self.assertRaisesRegex(RuntimeError, "Injected publication failure"):
                publish_staged_release(
                    root=root,
                    staged_build=staged_build,
                    public_build=public_build,
                    manifest=manifest,
                    run_id=new_run_id,
                    fail_after_replacements=2,
                )

            self.assertEqual(_snapshot_files(public_build), before)
            self.assertFalse((public_build / "generated" / "brand-new.txt").exists())
            self.assertFalse((root / ".build-publish.lock").exists())

    def test_refuses_to_overwrite_a_manually_modified_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            public_build = root / "build"
            old_run_id = "old-run"
            old_payloads = [
                ("build/build_status.json", _complete_status(old_run_id)),
                ("build/generated/report.txt", b"published-content"),
            ]
            _install_public_release(root, old_run_id, old_payloads)
            managed_file = public_build / "generated" / "report.txt"
            managed_file.write_bytes(b"manual-edit")
            before = _snapshot_files(public_build)

            new_run_id = "new-run"
            new_payloads = [
                ("build/build_status.json", _complete_status(new_run_id)),
                ("build/generated/report.txt", b"publisher-update"),
            ]
            staged_build, manifest = _stage_release(base / "transaction", new_run_id, new_payloads)

            with self.assertRaisesRegex(
                ValueError,
                "Previously managed file was modified outside the publisher",
            ):
                publish_staged_release(
                    root=root,
                    staged_build=staged_build,
                    public_build=public_build,
                    manifest=manifest,
                    run_id=new_run_id,
                )

            self.assertEqual(_snapshot_files(public_build), before)
            self.assertEqual(managed_file.read_bytes(), b"manual-edit")
            self.assertFalse((root / ".build-publish.lock").exists())

    def test_active_publisher_lock_is_not_stolen_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            public_build = root / "build"
            run_id = "contender"
            payloads = [("build/build_status.json", _complete_status(run_id))]
            staged_build, manifest = _stage_release(base / "transaction", run_id, payloads)
            lock_path = root / ".build-publish.lock"
            _write(lock_path, json.dumps({"run_id": "active", "pid": os.getpid()}).encode("utf-8"))

            with self.assertRaisesRegex(FileExistsError, "publication process is active"):
                publish_staged_release(
                    root=root,
                    staged_build=staged_build,
                    public_build=public_build,
                    manifest=manifest,
                    run_id=run_id,
                )

            self.assertTrue(lock_path.is_file())
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["run_id"], "active")

    def test_dead_publisher_is_rolled_back_from_journal_before_next_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            public_build = root / "build"
            old_run_id = "old-run"
            old_payloads = [
                ("build/build_status.json", _complete_status(old_run_id)),
                ("build/generated/report.txt", b"old-report"),
            ]
            _install_public_release(root, old_run_id, old_payloads)
            old_status = (public_build / "build_status.json").read_bytes()
            old_manifest = (public_build / "release_manifest.json").read_bytes()

            interrupted_run_id = "interrupted-run"
            transaction_root = root / ".build-staging" / interrupted_run_id
            rollback = transaction_root / "rollback"
            _write(rollback / "build_status.json", old_status)
            _write(rollback / "release_manifest.json", old_manifest)
            _write(rollback / "generated" / "report.txt", b"old-report")
            _write(public_build / "build_status.json", b'{"status":"PUBLISHING","run_id":"interrupted-run"}')
            _write(public_build / "generated" / "report.txt", b"interrupted-content")
            _write(public_build / "generated" / "new-during-crash.txt", b"partial")
            journal = {
                "run_id": interrupted_run_id,
                "status": "PUBLISHING",
                "entries": [
                    {"path": "build/build_status.json", "had_original": True},
                    {"path": "build/release_manifest.json", "had_original": True},
                    {"path": "build/generated/report.txt", "had_original": True},
                    {"path": "build/generated/new-during-crash.txt", "had_original": False},
                ],
            }
            _write(transaction_root / "publish_journal.json", json.dumps(journal).encode("utf-8"))
            _write(
                root / ".build-publish.lock",
                json.dumps({"run_id": interrupted_run_id, "pid": 2147483647}).encode("utf-8"),
            )

            new_run_id = "new-run"
            new_payloads = [
                ("build/build_status.json", _complete_status(new_run_id)),
                ("build/generated/report.txt", b"new-report"),
            ]
            staged_build, manifest = _stage_release(base / "next-transaction", new_run_id, new_payloads)
            result = publish_staged_release(
                root=root,
                staged_build=staged_build,
                public_build=public_build,
                manifest=manifest,
                run_id=new_run_id,
            )

            self.assertEqual(result["prior_recovery"]["action"], "ROLLED_BACK_INTERRUPTED_TRANSACTION")
            self.assertEqual((public_build / "generated" / "report.txt").read_bytes(), b"new-report")
            self.assertFalse((public_build / "generated" / "new-during-crash.txt").exists())
            self.assertFalse((root / ".build-publish.lock").exists())


if __name__ == "__main__":
    unittest.main()
