from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from context_continuity import (  # noqa: E402
    ContextSnapshot,
    RestoreEnvironment,
    RestoreStatus,
    plan_restore,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def snapshot(**changes) -> ContextSnapshot:
    values = {
        "snapshot_id": "snap-001",
        "owner_id": "owner-a",
        "created_at": NOW - timedelta(minutes=5),
        "physical_state": "FOCUS_WORK",
        "workspace_refs": ("local://project/workcore",),
        "required_device_ids": ("display-a",),
        "network_resource_refs": ("remote://repo/workcore",),
    }
    values.update(changes)
    return ContextSnapshot(**values)


def environment(**changes) -> RestoreEnvironment:
    values = {
        "authenticated_owner_id": "owner-a",
        "physical_state": "FOCUS_WORK",
        "parking_brake_applied": True,
        "drive_contactor_open": True,
        "mechanisms_known_and_locked": True,
        "local_cache_available": True,
        "network_available": True,
        "present_device_ids": frozenset({"display-a"}),
        "camera_hardware_shutter_closed": True,
        "microphone_hardware_muted": True,
    }
    values.update(changes)
    return RestoreEnvironment(**values)


class ContextContinuityPolicyTests(unittest.TestCase):
    def test_full_restore_never_requests_motion_authority(self) -> None:
        result = plan_restore(snapshot(), environment(), now=NOW)
        self.assertEqual(result.status, RestoreStatus.FULL)
        self.assertFalse(result.motion_authority_requested)
        self.assertIn("RESTORE_LOCAL_WORKSPACE:local://project/workcore", result.actions)

    def test_wrong_owner_is_rejected_without_actions(self) -> None:
        result = plan_restore(snapshot(), environment(authenticated_owner_id="owner-b"), now=NOW)
        self.assertEqual(result.status, RestoreStatus.REJECTED)
        self.assertEqual(result.actions, ())
        self.assertIn("OWNER_MISMATCH", result.blocked_items)

    def test_restore_is_rejected_in_ride_even_if_ui_requests_it(self) -> None:
        result = plan_restore(snapshot(), environment(physical_state="RIDE_READY"), now=NOW)
        self.assertEqual(result.status, RestoreStatus.REJECTED)
        self.assertIn("PHYSICAL_STATE_NOT_PARKED_RESTORE_STATE", result.blocked_items)

    def test_unknown_mechanism_state_is_rejected(self) -> None:
        result = plan_restore(snapshot(), environment(mechanisms_known_and_locked=False), now=NOW)
        self.assertEqual(result.status, RestoreStatus.REJECTED)
        self.assertIn("MECHANISM_STATE_UNKNOWN_OR_UNLOCKED", result.blocked_items)

    def test_offline_mode_restores_local_core_as_partial(self) -> None:
        result = plan_restore(snapshot(), environment(network_available=False), now=NOW)
        self.assertEqual(result.status, RestoreStatus.PARTIAL)
        self.assertIn("RESTORE_LOCAL_WORKSPACE:local://project/workcore", result.actions)
        self.assertIn("NETWORK_RESOURCE_OFFLINE:remote://repo/workcore", result.blocked_items)

    def test_missing_local_core_rejects_instead_of_cloud_only_restore(self) -> None:
        result = plan_restore(snapshot(), environment(local_cache_available=False), now=NOW)
        self.assertEqual(result.status, RestoreStatus.REJECTED)
        self.assertIn("LOCAL_CORE_UNAVAILABLE", result.blocked_items)

    def test_snapshot_cannot_open_camera_or_unmute_microphone(self) -> None:
        result = plan_restore(
            snapshot(requests_camera=True, requests_microphone=True),
            environment(camera_hardware_shutter_closed=True, microphone_hardware_muted=True),
            now=NOW,
        )
        self.assertEqual(result.status, RestoreStatus.PARTIAL)
        self.assertNotIn("REQUEST_CAMERA_SESSION_WITH_VISIBLE_INDICATOR", result.actions)
        self.assertNotIn("REQUEST_MICROPHONE_SESSION_WITH_VISIBLE_INDICATOR", result.actions)
        self.assertIn("CAMERA_HARDWARE_SHUTTER_CLOSED", result.blocked_items)
        self.assertIn("MICROPHONE_HARDWARE_MUTED", result.blocked_items)

    def test_stale_snapshot_requires_fresh_confirmation(self) -> None:
        old = snapshot(created_at=NOW - timedelta(days=8))
        rejected = plan_restore(old, environment(), now=NOW)
        accepted = plan_restore(old, environment(stale_snapshot_confirmed=True), now=NOW)
        self.assertEqual(rejected.status, RestoreStatus.REJECTED)
        self.assertIn("STALE_SNAPSHOT_REQUIRES_USER_CONFIRMATION", rejected.blocked_items)
        self.assertEqual(accepted.status, RestoreStatus.FULL)


if __name__ == "__main__":
    unittest.main()

