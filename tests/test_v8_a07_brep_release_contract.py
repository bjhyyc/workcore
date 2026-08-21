from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLASS_A = (
    ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
)
for path in (ROOT, CLASS_A):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_layout_appearance_series_low_memory import (  # noqa: E402
    A07_BREP_ALL_NAMES,
    A07_BREP_EXTERIOR_NAMES,
    _a07_four_state_brep_gate,
    _a07_state_report_failures,
)
from exterior_presentation import exterior_parts  # noqa: E402
from skin_lower import build_lower_skin  # noqa: E402
from skin_upper import build_upper_skin  # noqa: E402
from v8_a07_brep_release_contract import (  # noqa: E402
    a07_state_brep_report,
)
from v8_final_appearance_closure import (  # noqa: E402
    _production_mast_layout,
    _shared_backrest_master,
)


class V8A07DirectBrepReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reports: dict[str, dict[str, object]] = {}
        for state in ("follow", "ride", "cafe", "focus"):
            # The direct gate owns only A06/A07.  Applying the two canonical
            # replacement stages gives the exact released solids without
            # spending test memory on unrelated wheel/table/service booleans.
            parts = build_lower_skin(state) + build_upper_skin(state)
            _shared_backrest_master(state, parts)
            _production_mast_layout(state, parts)
            visible, _visibility = exterior_parts(state, parts)
            cls.reports[state] = a07_state_brep_report(
                state,
                parts,
                {part.name for part in visible},
            )

    def test_every_state_is_a_direct_brep_pass(self) -> None:
        for state, report in self.reports.items():
            with self.subTest(state=state):
                self.assertEqual(report["status"], "PASS", report["failures"])
                self.assertEqual(_a07_state_report_failures(report, state), [])
                self.assertEqual(
                    set(report["occurrences"]), set(A07_BREP_ALL_NAMES)
                )
                self.assertEqual(
                    set(report["visible_exterior_inventory"]),
                    set(A07_BREP_EXTERIOR_NAMES),
                )

    def test_four_state_identity_and_pose_gate_passes(self) -> None:
        hashes = {f"qa/{state}.json": state * 16 for state in self.reports}
        gate = _a07_four_state_brep_gate(self.reports, hashes)
        self.assertEqual(gate["status"], "PASS", gate["failures"])
        self.assertEqual(gate["focus_translation_inventory"], {
            "fixed_[0,0,0]": 6,
            "moving_[0,0,420]": 7,
            "privacy_[0,136,420]": 2,
        })

    def test_gate_rejects_a_focus_pose_falsification(self) -> None:
        import copy

        changed = copy.deepcopy(self.reports)
        changed["focus"]["occurrences"][
            "A07_sensor_beam_shell"
        ]["actual_signature"]["centre_mm"][2] += 1.0
        gate = _a07_four_state_brep_gate(
            changed,
            {f"qa/{state}.json": state * 16 for state in changed},
        )
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("rigid translation", " | ".join(gate["failures"]))


if __name__ == "__main__":
    unittest.main()
