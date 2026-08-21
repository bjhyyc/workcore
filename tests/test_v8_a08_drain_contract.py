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

from skin_lower import _footrest_skin  # noqa: E402
from v8_functional_fixes import _cut_a08_through_drains  # noqa: E402
from v8_release_gates import _a08_channel, _intersection_volume, _part  # noqa: E402
from v8_rigid_partition_cross import a08_manual_release_corridor  # noqa: E402


class V8A08DrainContractTests(unittest.TestCase):
    def test_body_side_manual_release_shell_is_identical_in_all_states(self) -> None:
        reference = None
        corridor = a08_manual_release_corridor()
        for state in ("follow", "ride", "cafe", "focus"):
            with self.subTest(state=state):
                release = _part(_footrest_skin(state), "A08_manual_release_paddle_shell")
                self.assertEqual(
                    release.metadata.get("physical_occurrence_id"),
                    "E6-A08-MANUAL-RELEASE-PADDLE-SHELL",
                )
                self.assertIs(release.metadata.get("body_side_fixed"), True)
                self.assertIs(release.metadata.get("pose_invariant"), True)
                outside = release.shape.cut(corridor)
                outside_volume = 0.0 if outside.isNull() else float(outside.Volume())
                self.assertLessEqual(outside_volume, 1.0e-5)
                if reference is None:
                    reference = release.shape
                else:
                    common = _intersection_volume(reference, release.shape)
                    symmetric_difference = (
                        float(reference.Volume())
                        + float(release.shape.Volume())
                        - 2.0 * common
                    )
                    self.assertLessEqual(symmetric_difference, 1.0e-3)

    def test_three_true_through_channels_exist_in_every_primary_pose(self) -> None:
        for state in ("follow", "ride", "cafe", "focus"):
            with self.subTest(state=state):
                parts = _footrest_skin(state)
                _cut_a08_through_drains(parts)
                top = _part(parts, "A08_footrest_top_skin")
                tread = _part(parts, "A08_footrest_inset_tread")
                self.assertEqual(len(top.shape.Solids()), 1)
                self.assertEqual(len(tread.shape.Solids()), 1)
                for station in (-50.0, 0.0, 50.0):
                    witness = _a08_channel(top, tread, station)
                    self.assertLessEqual(
                        _intersection_volume(top.shape, witness),
                        1.0e-5,
                    )
                    self.assertLessEqual(
                        _intersection_volume(tread.shape, witness),
                        1.0e-5,
                    )


if __name__ == "__main__":
    unittest.main()
