from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


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
from skin_upper import build_upper_skin  # noqa: E402
from skin_v8_refinement import refine_v8_parts  # noqa: E402
from v8_collision_partition import apply_v8_collision_partitions  # noqa: E402
from v8_functional_fixes import apply_v8_functional_fixes  # noqa: E402
from v8_mast_fixes import apply_v8_mast_fixes  # noqa: E402
from v8_lid_harness_gate import (  # noqa: E402
    evaluate_a05_lid_harness_gate,
)
from v8_final_appearance_closure import _fixed_right_armrest  # noqa: E402
from v8_release_gates import _GateBook, _gate_a05_lid_harness  # noqa: E402
from v8_table_lid_packaging import lid_harness_pose  # noqa: E402


class V8LidHarnessReleaseGateTests(unittest.TestCase):
    def test_final_qi_phone_stops_have_real_lid_overmould_seats(self) -> None:
        parts = build_lower_skin("follow") + build_upper_skin("follow")
        _fixed_right_armrest("follow", parts)
        by_name = {part.name: part for part in parts}
        lid = by_name["A05_armrest_touch_lid_left"]
        self.assertEqual(
            tuple(lid.metadata["qi_phone_stop_overmould_seats"]),
            (
                "A05_left_qi_phone_stop_front",
                "A05_left_qi_phone_stop_rear",
            ),
        )
        for position in ("front", "rear"):
            stop = by_name[f"A05_left_qi_phone_stop_{position}"]
            self.assertLessEqual(
                float(lid.shape.intersect(stop.shape).Volume()),
                1.0e-6,
            )
            self.assertGreaterEqual(
                float(lid.shape.distance(stop.shape)),
                0.2 - 1.0e-6,
            )

    def test_follow_collision_partition_preserves_lid_connector_bond_surface(
        self,
    ) -> None:
        raw_parts = build_lower_skin("follow") + build_upper_skin("follow")
        raw_by_name = {part.name: part for part in raw_parts}
        parts = refine_v8_parts("follow", raw_parts)
        parts = apply_v8_functional_fixes("follow", parts)
        parts = apply_v8_mast_fixes("follow", parts)
        parts = apply_v8_collision_partitions("follow", parts)
        by_name = {part.name: part for part in parts}

        for side, side_name in ((-1, "left"), (1, "right")):
            lid_name = f"A05_armrest_touch_lid_{side_name}"
            self.assertAlmostEqual(
                by_name[lid_name].shape.Volume(),
                raw_by_name[lid_name].shape.Volume(),
                places=3,
            )
            self.assertAlmostEqual(
                lid_harness_pose(side, 0.0).moving_connector.distance(
                    by_name[lid_name].shape
                ),
                0.0,
                places=6,
            )

        self.assertNotIn("A06_follow_closed_field_shell", by_name)

    def test_real_follow_a05_breps_pass_full_dynamic_flex_gate(self) -> None:
        parts = build_upper_skin("follow")
        by_name = {part.name: part for part in parts}
        shells = {}
        lid_parts = {}
        for side, side_name in ((-1, "left"), (1, "right")):
            shells[side] = by_name[
                f"A05_armrest_table_bay_shell_{side_name}"
            ].shape
            lid_parts[side] = tuple(
                (part.name, part.shape)
                for part in parts
                if part.name == f"A05_armrest_touch_lid_{side_name}"
                or (
                    bool(part.metadata.get("moves_with_top_lid"))
                    and part.name.startswith(f"A05_{side_name}_")
                )
                or (side < 0 and part.name == "A05_left_hmi_precision_bezel")
            )

        result = evaluate_a05_lid_harness_gate(shells, lid_parts)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["failures"], [])
        self.assertFalse(result["production_certification_claimed"])
        for side_name in ("left", "right"):
            evidence = result["sides"][side_name]
            self.assertTrue(evidence["pass"], evidence)
            self.assertEqual(evidence["evaluated_pose_count"], 106)
            self.assertGreaterEqual(
                evidence["minimum_inside_bend_radius_mm"],
                8.0,
            )
            self.assertLessEqual(
                evidence["centerline_length_variation_mm"],
                0.005,
            )
            self.assertLessEqual(
                evidence["flex_volume_variation_mm3"],
                0.02,
            )
            for clearance in evidence["minimum_clearances_mm"].values():
                self.assertGreaterEqual(clearance, 3.0)

    def test_gate_rejects_missing_side_and_non_dividing_angle_step(self) -> None:
        with self.assertRaisesRegex(ValueError, "sides -1 and \\+1"):
            evaluate_a05_lid_harness_gate({}, {})

        parts = build_upper_skin("follow")
        by_name = {part.name: part for part in parts}
        shells = {
            side: by_name[
                f"A05_armrest_table_bay_shell_{side_name}"
            ].shape
            for side, side_name in ((-1, "left"), (1, "right"))
        }
        lids = {
            side: (
                (
                    f"A05_armrest_touch_lid_{side_name}",
                    by_name[f"A05_armrest_touch_lid_{side_name}"].shape,
                ),
            )
            for side, side_name in ((-1, "left"), (1, "right"))
        }
        with self.assertRaisesRegex(ValueError, "divide 105 degrees"):
            evaluate_a05_lid_harness_gate(
                shells,
                lids,
                angle_step_deg=4.0,
            )

    def test_release_book_integrates_one_unique_fail_closed_gate(self) -> None:
        parts = build_upper_skin("follow")
        states = {state: parts for state in ("follow", "ride", "cafe", "focus")}
        book = _GateBook()
        evaluator_result = {
            "gate_id": "a05.lid_dynamic_flex_full_motion",
            "pass": True,
            "evidence_kind": "one_degree_brep_motion_sweep",
            "requirement": "fixture requirement",
            "hard_part_minimum_clearance_mm": 3.0,
            "sides": {
                side_name: {
                    "evaluated_pose_count": 106,
                    "minimum_clearances_mm": {
                        "open_harness_to_61_pose_extraction_aabb_mm": 3.0,
                    },
                }
                for side_name in ("left", "right")
            },
            "failures": [],
        }
        with patch(
            "v8_release_gates.evaluate_a05_lid_harness_gate",
            return_value=evaluator_result,
        ) as evaluate:
            _gate_a05_lid_harness(states, book)
        fixed_shells, lid_parts = evaluate.call_args.args
        self.assertEqual(set(fixed_shells), {-1, 1})
        self.assertEqual(set(lid_parts), {-1, 1})
        self.assertEqual(
            sum(name == "A05_armrest_touch_lid_right" for name, _ in lid_parts[1]),
            1,
        )
        self.assertGreater(len(lid_parts[-1]), 1)
        self.assertEqual(len(book.checks), 1)
        check = book.checks[0]
        self.assertEqual(check["id"], "a05.lid_dynamic_flex_full_motion")
        self.assertTrue(check["pass"], check)
        for side_name in ("left", "right"):
            self.assertEqual(
                check["sides"][side_name]["evaluated_pose_count"],
                106,
            )
            self.assertIn(
                "open_harness_to_61_pose_extraction_aabb_mm",
                check["sides"][side_name]["minimum_clearances_mm"],
            )

        missing_left_shell = [
            part
            for part in parts
            if part.name != "A05_armrest_table_bay_shell_left"
        ]
        failed_book = _GateBook()
        failed_states = {
            state: missing_left_shell
            for state in ("follow", "ride", "cafe", "focus")
        }
        _gate_a05_lid_harness(failed_states, failed_book)
        self.assertEqual(len(failed_book.checks), 1)
        self.assertFalse(failed_book.checks[0]["pass"])
        self.assertIn("KeyError", failed_book.checks[0]["error"])


if __name__ == "__main__":
    unittest.main()
