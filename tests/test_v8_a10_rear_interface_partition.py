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

from skin_lower import build_lower_skin  # noqa: E402


class V8A10RearInterfacePartitionTests(unittest.TestCase):
    def test_fixed_status_lens_clears_door_carried_horn_mesh(self) -> None:
        for state in ("follow", "ride", "cafe", "focus"):
            with self.subTest(state=state):
                parts = {part.name: part for part in build_lower_skin(state)}
                status = parts["A10_rear_status_lens"]
                horn = parts["A10_rear_horn_acoustic_mesh"]
                self.assertAlmostEqual(
                    status.shape.intersect(horn.shape).Volume(), 0.0, places=6
                )
                self.assertAlmostEqual(status.shape.distance(horn.shape), 2.5, places=6)
                self.assertEqual(
                    status.metadata["controlled_source_center_z_mm"], 420.0
                )
                self.assertTrue(
                    status.metadata["fixed_to_rear_service_surround"]
                )
                self.assertFalse(status.metadata["service_door_carried"])


if __name__ == "__main__":
    unittest.main()
