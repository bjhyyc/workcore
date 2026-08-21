from __future__ import annotations

import copy
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
    _focus_root_neck_report_failures,
)
from skin_upper import build_upper_skin  # noqa: E402
from v8_focus_root_neck_release_contract import (  # noqa: E402
    focus_root_neck_release_report,
)


class V8FocusRootNeckReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = focus_root_neck_release_report(build_upper_skin("focus"))

    def test_direct_brep_clearance_and_load_path_pass(self) -> None:
        self.assertEqual(
            self.report["status"], "PASS", self.report["failures"]
        )
        self.assertEqual(_focus_root_neck_report_failures(self.report), [])
        for side_name in ("left", "right"):
            side = self.report["sides"][side_name]
            self.assertEqual(len(side["independent_thin_slice_probes"]), 3)
            self.assertTrue(
                all(
                    item["common_volume_mm3"] == 0.0
                    for item in side["a05_zero_collision_clearances"].values()
                )
            )
            self.assertTrue(
                all(
                    item["common_volume_mm3"] == 0.0
                    and item["minimum_distance_mm"] == 0.0
                    for item in side[
                        "load_path_zero_penetration_contacts"
                    ].values()
                )
            )

    def test_json_gate_rejects_a_missing_smooth_section(self) -> None:
        changed = copy.deepcopy(self.report)
        changed["sides"]["right"]["independent_thin_slice_probes"].pop()
        failures = _focus_root_neck_report_failures(changed)
        self.assertTrue(failures)
        self.assertIn("slice probes", " | ".join(failures))


if __name__ == "__main__":
    unittest.main()
