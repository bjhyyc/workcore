from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from verify_release import _is_release_go, _model_integrity_failures  # noqa: E402


class ReleasePolicyTests(unittest.TestCase):
    def test_conditional_or_no_go_is_not_a_release(self) -> None:
        self.assertTrue(_is_release_go("GO"))
        self.assertTrue(_is_release_go("PASS_WITH_OPEN_ACTIONS"))
        self.assertFalse(_is_release_go("CONDITIONAL_GO after action"))
        self.assertFalse(_is_release_go("NO_GO"))

    def test_pose_mass_and_identity_are_model_integrity_failures(self) -> None:
        readiness = {
            "traceability_integrity": {"pass": True},
            "production_bom": {
                "pose_identity_status": "NOT_DEMONSTRATED",
                "configuration_mass_spread_kg": 5.7577,
                "definition_conflicts": 1,
            },
        }
        failures = _model_integrity_failures(readiness, {"status": "COMPLETE"})
        reasons = {row["reason"] for row in failures}
        self.assertIn("pose_invariant_part_identity_not_demonstrated", reasons)
        self.assertIn("pose_mass_spread_exceeds_0_001kg", reasons)
        self.assertIn("canonical_part_definition_conflicts", reasons)

    def test_clean_model_integrity_has_no_policy_failures(self) -> None:
        readiness = {
            "traceability_integrity": {"pass": True},
            "production_bom": {
                "pose_identity_status": "DEMONSTRATED",
                "configuration_mass_spread_kg": 0.001,
                "definition_conflicts": 0,
            },
        }
        self.assertEqual(_model_integrity_failures(readiness, {"status": "COMPLETE"}), [])


if __name__ == "__main__":
    unittest.main()
