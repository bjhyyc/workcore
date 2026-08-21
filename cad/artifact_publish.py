from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


PUBLISH_PROTOCOL_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name != "nt" or not path.exists():
        return False
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    reparse_flag = getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def validate_managed_records(root: Path, public_build: Path, records: list[dict]) -> list[tuple[dict, Path, Path]]:
    root = root.resolve()
    public_build = public_build.resolve()
    if not _is_relative_to(public_build, root):
        raise ValueError("Published build root must remain inside the workspace")
    if _is_reparse_point(public_build):
        raise ValueError("Published build root may not be a symlink, junction, or reparse point")

    seen: set[str] = set()
    validated: list[tuple[dict, Path, Path]] = []
    for record in records:
        logical = str(record.get("path", "")).replace("\\", "/")
        if not logical or logical in seen:
            raise ValueError(f"Missing or duplicate managed path: {logical!r}")
        seen.add(logical)
        logical_path = Path(logical)
        if logical_path.is_absolute() or ".." in logical_path.parts:
            raise ValueError(f"Unsafe managed path: {logical}")
        destination = (root / logical_path).resolve()
        if not _is_relative_to(destination, public_build):
            raise ValueError(f"Managed path escapes published build: {logical}")
        relative = destination.relative_to(public_build)
        for parent in (public_build, *destination.parents):
            if parent == public_build.parent:
                break
            if parent.exists() and _is_reparse_point(parent):
                raise ValueError(f"Managed path crosses a reparse point: {logical}")
        validated.append((record, destination, relative))
    return validated


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _backup(path: Path, relative: Path, rollback_root: Path) -> Path | None:
    if not path.exists():
        return None
    target = rollback_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def _restore(path: Path, backup: Path | None) -> None:
    if backup is None:
        if path.exists():
            path.unlink()
        return
    atomic_copy(backup, path)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a non-destructive existence probe on
        # Windows: Python routes unsupported signals through TerminateProcess,
        # so signal 0 can terminate the publisher being checked.  Query the
        # process handle instead and fail closed on access-denied/probe errors
        # so an uncertain lock is never stolen.
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        error_access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        get_exit_code_process = kernel32.GetExitCodeProcess
        get_exit_code_process.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        get_exit_code_process.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        handle = open_process(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == error_access_denied
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code_process(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            close_handle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unreadable transaction metadata: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Transaction metadata must be a JSON object: {path}")
    return value


def _restore_interrupted_transaction(root: Path, public_build: Path, lock_path: Path) -> dict:
    """Recover a dead publisher using its write-ahead journal and backups."""

    lock = _read_json(lock_path)
    pid = int(lock.get("pid", 0))
    if _pid_is_alive(pid):
        raise FileExistsError(f"Another publication process is active (pid={pid})")
    run_id = str(lock.get("run_id", ""))
    if not run_id:
        raise RuntimeError("Stale publication lock has no run_id; manual recovery required")

    status_path = public_build / "build_status.json"
    manifest_path = public_build / "release_manifest.json"
    status = _read_json(status_path) if status_path.is_file() else {}
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    if status.get("status") == "COMPLETE" and status.get("run_id") == run_id and manifest.get("run_id") == run_id:
        records = manifest.get("artifacts", {}).get("files", [])
        validated = validate_managed_records(root, public_build, records)
        if all(
            destination.is_file()
            and destination.stat().st_size == record.get("bytes")
            and sha256(destination) == record.get("sha256")
            for record, destination, _ in validated
        ):
            lock_path.unlink()
            return {"recovered_run_id": run_id, "action": "FINALIZED_ALREADY_COMPLETE"}

    transaction_root = root / ".build-staging" / run_id
    journal_path = transaction_root / "publish_journal.json"
    rollback_root = transaction_root / "rollback"
    if not journal_path.is_file() or not rollback_root.is_dir():
        raise RuntimeError(
            f"Interrupted publication {run_id} lacks a complete recovery journal; manual recovery required"
        )
    journal = _read_json(journal_path)
    entries = journal.get("entries", [])
    if not isinstance(entries, list):
        raise RuntimeError("Interrupted publication journal entries are invalid")
    restore_plan: list[tuple[Path, Path | None]] = []
    for entry in reversed(entries):
        logical = str(entry.get("path", ""))
        logical_path = Path(logical.replace("\\", "/"))
        if logical_path.is_absolute() or ".." in logical_path.parts:
            raise RuntimeError(f"Unsafe path in recovery journal: {logical}")
        destination = (root / logical_path).resolve()
        if not _is_relative_to(destination, public_build):
            raise RuntimeError(f"Recovery journal path escapes build: {logical}")
        relative = destination.relative_to(public_build)
        backup = rollback_root / relative
        had_original = bool(entry.get("had_original"))
        if had_original and not backup.is_file():
            raise RuntimeError(f"Required rollback backup is missing: {logical}")
        restore_plan.append((destination, backup if had_original else None))
    for destination, backup in restore_plan:
        _restore(destination, backup)
    lock_path.unlink()
    return {"recovered_run_id": run_id, "action": "ROLLED_BACK_INTERRUPTED_TRANSACTION"}


def scan_unmanaged_files(public_build: Path, managed_paths: set[str], root: Path) -> list[str]:
    if not public_build.exists():
        return []
    unmanaged = []
    for path in public_build.rglob("*"):
        if not path.is_file():
            continue
        logical = path.relative_to(root).as_posix()
        if logical == "build/release_manifest.json":
            continue
        if logical not in managed_paths:
            unmanaged.append(logical)
    return sorted(unmanaged)


def publish_staged_release(
    *,
    root: Path,
    staged_build: Path,
    public_build: Path,
    manifest: dict,
    run_id: str,
    fail_after_replacements: int | None = None,
) -> dict:
    """Publish a staged release without deleting unknown files.

    Individual file replacements are atomic. The public status is PUBLISHING
    throughout the multi-file transaction and the hash-bound COMPLETE status is
    the final commit point. A normal exception rolls back every replacement; a
    hard process termination leaves PUBLISHING, which the verifier rejects.
    """

    if manifest.get("run_id") != run_id:
        raise ValueError("Manifest/run_id mismatch")
    if manifest.get("publish_protocol_version") != PUBLISH_PROTOCOL_VERSION:
        raise ValueError("Unsupported publish protocol")

    root = root.resolve()
    staged_build = staged_build.resolve()
    public_build.mkdir(parents=True, exist_ok=True)
    public_build = public_build.resolve()
    records = manifest.get("artifacts", {}).get("files", [])
    validated = validate_managed_records(root, public_build, records)
    managed_paths = {record["path"] for record, _, _ in validated}
    if set(manifest.get("managed_paths", [])) != managed_paths:
        raise ValueError("Manifest managed_paths does not match artifact records")

    staged_by_logical: dict[str, Path] = {}
    for record, _, relative in validated:
        source = staged_build / relative
        if not source.is_file():
            raise FileNotFoundError(f"Staged managed file missing: {record['path']}")
        if source.stat().st_size != record["bytes"] or sha256(source) != record["sha256"]:
            raise ValueError(f"Staged managed file changed after manifest: {record['path']}")
        staged_by_logical[record["path"]] = source

    staged_manifest_path = staged_build / "release_manifest.json"
    if not staged_manifest_path.is_file():
        raise FileNotFoundError("Staged release manifest missing")
    staged_manifest = _read_json(staged_manifest_path)
    if staged_manifest != manifest:
        raise ValueError("Staged release manifest changed after preflight")
    staged_status_source = staged_by_logical.get("build/build_status.json")
    if staged_status_source is None:
        raise ValueError("Manifest does not manage build/build_status.json")
    staged_status = _read_json(staged_status_source)
    if staged_status.get("status") != "COMPLETE" or staged_status.get("run_id") != run_id:
        raise ValueError("Staged status is not COMPLETE for the manifest run_id")
    if staged_status.get("revision") not in (None, manifest.get("revision")):
        raise ValueError("Staged status/manifest revision mismatch")

    lock_path = root / ".build-publish.lock"
    lock_fd = None
    lock_owned = False
    recovery = None
    if lock_path.exists():
        recovery = _restore_interrupted_transaction(root, public_build, lock_path)
    rollback_root = staged_build.parent / "rollback"
    journal_path = staged_build.parent / "publish_journal.json"
    backups: dict[Path, Path | None] = {}
    replacement_order: list[Path] = []
    old_manifest_path = public_build / "release_manifest.json"
    old_manifest = {}
    if old_manifest_path.is_file():
        try:
            old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("Existing release manifest is unreadable; refuse overwrite") from exc
    old_records = {
        row.get("path"): row
        for row in old_manifest.get("artifacts", {}).get("files", [])
        if row.get("path")
    }

    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        lock_owned = True
        os.write(
            lock_fd,
            json.dumps(
                {
                    "run_id": run_id,
                    "pid": os.getpid(),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            ).encode("utf-8"),
        )
        os.fsync(lock_fd)

        # Preserve user modifications and unknown-path ownership. Existing
        # managed paths must still match the previous release before overwrite.
        for record, destination, _ in validated:
            old = old_records.get(record["path"])
            if destination.exists() and old is None:
                raise FileExistsError(f"New managed path collides with an unmanaged file: {record['path']}")
            if old is not None:
                if not destination.is_file():
                    raise FileNotFoundError(f"Previously managed file is missing: {record['path']}")
                if destination.stat().st_size != old.get("bytes") or sha256(destination) != old.get("sha256"):
                    raise ValueError(f"Previously managed file was modified outside the publisher: {record['path']}")

        status_path = public_build / "build_status.json"
        manifest_path = public_build / "release_manifest.json"
        rollback_root.mkdir(parents=True, exist_ok=True)
        backups[status_path] = _backup(status_path, Path("build_status.json"), rollback_root)
        backups[manifest_path] = _backup(manifest_path, Path("release_manifest.json"), rollback_root)
        journal = {
            "run_id": run_id,
            "status": "PREPARED",
            "entries": [
                {"path": "build/build_status.json", "had_original": backups[status_path] is not None},
                {"path": "build/release_manifest.json", "had_original": backups[manifest_path] is not None},
            ],
        }
        atomic_write_bytes(journal_path, json.dumps(journal, indent=2).encode("utf-8"))
        publishing_status = {
            "schema_version": 1,
            "revision": manifest.get("revision"),
            "run_id": run_id,
            "status": "PUBLISHING",
            "scope": "artifact publication transaction; verifier must reject until COMPLETE",
        }
        atomic_write_bytes(status_path, json.dumps(publishing_status, ensure_ascii=False, indent=2).encode("utf-8"))
        replacement_order.append(status_path)

        journal["status"] = "PUBLISHING"
        atomic_write_bytes(journal_path, json.dumps(journal, indent=2).encode("utf-8"))
        replacements = 0
        for record, destination, relative in validated:
            if record["path"] == "build/build_status.json":
                continue
            if destination not in backups:
                backups[destination] = _backup(destination, relative, rollback_root)
            journal["entries"].append(
                {"path": record["path"], "had_original": backups[destination] is not None}
            )
            atomic_write_bytes(journal_path, json.dumps(journal, indent=2).encode("utf-8"))
            atomic_copy(staged_by_logical[record["path"]], destination)
            replacement_order.append(destination)
            replacements += 1
            if fail_after_replacements is not None and replacements >= fail_after_replacements:
                raise RuntimeError("Injected publication failure")

        atomic_copy(staged_manifest_path, manifest_path)
        replacement_order.append(manifest_path)
        atomic_copy(staged_by_logical["build/build_status.json"], status_path)

        # Post-publish verification before releasing the lock.
        for record, destination, _ in validated:
            if destination.stat().st_size != record["bytes"] or sha256(destination) != record["sha256"]:
                raise ValueError(f"Post-publish verification failed: {record['path']}")
        published_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        published_status = json.loads(status_path.read_text(encoding="utf-8"))
        if published_manifest.get("run_id") != run_id or published_status.get("run_id") != run_id:
            raise ValueError("Published status/manifest run_id mismatch")
        if published_status.get("status") != "COMPLETE":
            raise ValueError("Published status did not reach COMPLETE")
        journal["status"] = "COMPLETE"
        atomic_write_bytes(journal_path, json.dumps(journal, indent=2).encode("utf-8"))
        result = {
            "run_id": run_id,
            "managed_file_count": len(validated),
            "unmanaged_files_preserved": scan_unmanaged_files(public_build, managed_paths, root),
            "prior_recovery": recovery,
            "staging_cleanup": "NOT_OWNED_BY_STANDARD_STAGING_ROOT",
        }
        standard_transaction_root = (root / ".build-staging" / run_id).resolve()
        if staged_build.parent == standard_transaction_root:
            try:
                shutil.rmtree(standard_transaction_root)
            except OSError as exc:
                result["staging_cleanup"] = f"PRESERVED_AFTER_CLEANUP_FAILURE: {exc}"
            else:
                result["staging_cleanup"] = "REMOVED_AFTER_VERIFIED_PUBLICATION"
        return result
    except BaseException:
        for path in reversed(replacement_order):
            if path in backups:
                _restore(path, backups[path])
        raise
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_owned and lock_path.exists():
            lock_path.unlink()
