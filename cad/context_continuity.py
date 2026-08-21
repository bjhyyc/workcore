from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class RestoreStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


PARKED_RESTORE_STATES = frozenset({"CAFE_PARKED", "FOCUS_WORK"})
SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ContextSnapshot:
    """Non-secret references required to reconstruct a user's work context.

    Credentials, encryption keys, raw biometric data and safety-controller state
    are intentionally excluded. Production storage must encrypt and authenticate
    this record; the reference model only defines restore policy.
    """

    snapshot_id: str
    owner_id: str
    created_at: datetime
    physical_state: str
    workspace_refs: tuple[str, ...]
    required_device_ids: tuple[str, ...] = ()
    network_resource_refs: tuple[str, ...] = ()
    requests_camera: bool = False
    requests_microphone: bool = False
    schema_version: int = SUPPORTED_SCHEMA_VERSION


@dataclass(frozen=True)
class RestoreEnvironment:
    authenticated_owner_id: str
    physical_state: str
    parking_brake_applied: bool
    drive_contactor_open: bool
    mechanisms_known_and_locked: bool
    local_cache_available: bool
    network_available: bool
    present_device_ids: frozenset[str]
    camera_hardware_shutter_closed: bool
    microphone_hardware_muted: bool
    explicit_camera_consent: bool = False
    explicit_microphone_consent: bool = False
    stale_snapshot_confirmed: bool = False


@dataclass(frozen=True)
class RestorePlan:
    status: RestoreStatus
    actions: tuple[str, ...]
    blocked_items: tuple[str, ...]
    audit_events: tuple[str, ...]
    motion_authority_requested: bool = False


def _reject(*reasons: str) -> RestorePlan:
    return RestorePlan(
        status=RestoreStatus.REJECTED,
        actions=(),
        blocked_items=tuple(reasons),
        audit_events=tuple(f"RESTORE_REJECTED:{reason}" for reason in reasons),
        motion_authority_requested=False,
    )


def plan_restore(
    snapshot: ContextSnapshot,
    environment: RestoreEnvironment,
    *,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(days=7),
) -> RestorePlan:
    """Create a side-effect-free digital restore plan.

    This function never operates actuators, changes a privacy device or asks for
    drive authority. Callers must treat every returned action as a user-space
    digital action and keep the independent safety controller out of this API.
    """

    now = now or datetime.now(timezone.utc)
    if snapshot.created_at.tzinfo is None or now.tzinfo is None:
        return _reject("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    if snapshot.schema_version != SUPPORTED_SCHEMA_VERSION:
        return _reject("UNSUPPORTED_SNAPSHOT_SCHEMA")
    if not snapshot.snapshot_id or not snapshot.owner_id:
        return _reject("INVALID_SNAPSHOT_IDENTITY")
    if snapshot.owner_id != environment.authenticated_owner_id:
        return _reject("OWNER_MISMATCH")
    if environment.physical_state not in PARKED_RESTORE_STATES:
        return _reject("PHYSICAL_STATE_NOT_PARKED_RESTORE_STATE")
    if not environment.parking_brake_applied:
        return _reject("PARKING_BRAKE_NOT_CONFIRMED")
    if not environment.drive_contactor_open:
        return _reject("DRIVE_CONTACTOR_NOT_OPEN")
    if not environment.mechanisms_known_and_locked:
        return _reject("MECHANISM_STATE_UNKNOWN_OR_UNLOCKED")
    if now < snapshot.created_at:
        return _reject("SNAPSHOT_FROM_FUTURE")
    if now - snapshot.created_at > stale_after and not environment.stale_snapshot_confirmed:
        return _reject("STALE_SNAPSHOT_REQUIRES_USER_CONFIRMATION")
    if not environment.local_cache_available:
        return _reject("LOCAL_CORE_UNAVAILABLE")

    actions = [f"RESTORE_LOCAL_WORKSPACE:{reference}" for reference in snapshot.workspace_refs]
    blocked: list[str] = []
    audit = [f"RESTORE_STARTED:{snapshot.snapshot_id}", "SAFETY_GATE_CONFIRMED_PARKED"]

    missing_devices = sorted(set(snapshot.required_device_ids) - set(environment.present_device_ids))
    for device_id in missing_devices:
        blocked.append(f"MISSING_DEVICE:{device_id}")
    for device_id in sorted(set(snapshot.required_device_ids) & set(environment.present_device_ids)):
        actions.append(f"RECONNECT_DEVICE:{device_id}")

    if snapshot.network_resource_refs:
        if environment.network_available:
            actions.extend(f"RESTORE_NETWORK_RESOURCE:{reference}" for reference in snapshot.network_resource_refs)
        else:
            blocked.extend(f"NETWORK_RESOURCE_OFFLINE:{reference}" for reference in snapshot.network_resource_refs)
            audit.append("OFFLINE_DEGRADED_MODE")

    # A snapshot can remember that a task used sensors, but never re-enable a
    # camera or microphone by itself. Current physical state and fresh consent
    # are authoritative; the more private state always wins.
    if snapshot.requests_camera:
        if environment.camera_hardware_shutter_closed:
            blocked.append("CAMERA_HARDWARE_SHUTTER_CLOSED")
        elif environment.explicit_camera_consent:
            actions.append("REQUEST_CAMERA_SESSION_WITH_VISIBLE_INDICATOR")
        else:
            blocked.append("CAMERA_REQUIRES_FRESH_CONSENT")
    if snapshot.requests_microphone:
        if environment.microphone_hardware_muted:
            blocked.append("MICROPHONE_HARDWARE_MUTED")
        elif environment.explicit_microphone_consent:
            actions.append("REQUEST_MICROPHONE_SESSION_WITH_VISIBLE_INDICATOR")
        else:
            blocked.append("MICROPHONE_REQUIRES_FRESH_CONSENT")

    status = RestoreStatus.PARTIAL if blocked else RestoreStatus.FULL
    audit.append(f"RESTORE_PLAN:{status.value}")
    return RestorePlan(
        status=status,
        actions=tuple(actions),
        blocked_items=tuple(blocked),
        audit_events=tuple(audit),
        motion_authority_requested=False,
    )

