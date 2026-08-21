from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

import cadquery as cq
from cadquery import importers


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

from skin_common import GRAPHITE_BROWN, SkinPart  # noqa: E402
from skin_lower import build_lower_skin  # noqa: E402
from v8_final_appearance_closure import _continuous_wheel_belts  # noqa: E402
from v8_release_gates import (  # noqa: E402
    STATES,
    _A03_FOUR_STATE_CONSERVED_NAMES,
    _a03_motion_metadata_keys,
    _evaluate_a03_four_state_conservation,
)
from v8_wheel_contract import (  # noqa: E402
    WHEEL_AXIS_Z_MM,
    WHEEL_ARTICULATION_POSE_ANGLES_DEG,
    WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM,
    WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3,
    WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3,
    WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM,
)
from v8_wheel_hub_articulation import (  # noqa: E402
    evaluate_wheel_hub_articulation,
    rotate_running_gear,
    wheel_hub_fixed_carrier_return,
    wheel_hub_stack_pose,
)


class V8WheelHubArticulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hub = importers.importStep(
            str(ROOT / "build" / "parts" / "hub_front_right.step")
        ).val()
        cls.axle = importers.importStep(
            str(ROOT / "build" / "parts" / "axle_front_right.step")
        ).val()
        lower_parts = build_lower_skin("ride")
        _continuous_wheel_belts("ride", lower_parts)
        cls.belts = {
            side: next(
                part.shape
                for part in lower_parts
                if part.name == f"A03_continuous_wheel_belt_shell_{side}"
            )
            for side in ("left", "right")
        }
        cls.neutral = wheel_hub_stack_pose("front", "right", 0.0)

    def _evaluate(self, hub: cq.Shape | None = None) -> dict[str, object]:
        return evaluate_wheel_hub_articulation(
            axle="front",
            side="right",
            belt=self.belts["right"],
            released_cap=self.neutral.cap,
            released_backing=self.neutral.backing,
            released_gaiter=self.neutral.gaiter,
            controlled_hub=self.hub if hub is None else hub,
            controlled_axle=self.axle,
        )

    def test_actual_continuous_belt_owns_carrier_without_lower_outer_wedges(
        self,
    ) -> None:
        """Regress the released A03 B-Rep, not an isolated carrier proxy."""

        boolean_tolerance_mm3 = 1.0e-4
        distance_tolerance_mm = 1.0e-4
        for side_name, side_sign in (("left", -1.0), ("right", 1.0)):
            belt = self.belts[side_name]
            self.assertTrue(belt.isValid())
            self.assertEqual(len(belt.Solids()), 1)
            for axle_name, wheel_x, outward_x in (
                ("front", -380.0, -1.0),
                ("rear", 180.0, 1.0),
            ):
                with self.subTest(side=side_name, axle=axle_name):
                    # Match the production cutter's exterior-side slab.  The
                    # hidden rolled-in carrier sits inboard of this volume, so
                    # a non-zero result is specifically the old dangling
                    # Class-A terminal wedge rather than legitimate support.
                    forbidden_outer_lower = (
                        cq.Workplane("XY")
                        .box(1000.0, 10.0, 500.0)
                        .translate(
                            (
                                wheel_x + outward_x * 500.0,
                                side_sign
                                * WHEEL_HUB_FIXED_APERTURE_ABS_Y_MM,
                                WHEEL_AXIS_Z_MM - 250.0,
                            )
                        )
                        .val()
                    )
                    self.assertLessEqual(
                        float(
                            belt.intersect(forbidden_outer_lower).Volume()
                        ),
                        boolean_tolerance_mm3,
                    )

                    carrier = wheel_hub_fixed_carrier_return(
                        axle_name,
                        side_name,
                    )
                    carrier_volume = float(carrier.Volume())
                    self.assertGreater(carrier_volume, 0.0)
                    self.assertLessEqual(
                        float(carrier.cut(belt).Volume()),
                        boolean_tolerance_mm3,
                    )
                    self.assertAlmostEqual(
                        float(carrier.intersect(belt).Volume()),
                        carrier_volume,
                        delta=boolean_tolerance_mm3,
                    )

                    hub = importers.importStep(
                        str(
                            ROOT
                            / "build"
                            / "parts"
                            / f"hub_{axle_name}_{side_name}.step"
                        )
                    ).val()
                    axle = importers.importStep(
                        str(
                            ROOT
                            / "build"
                            / "parts"
                            / f"axle_{axle_name}_{side_name}.step"
                        )
                    ).val()
                    running_gear = hub.fuse(axle).clean()
                    for angle in WHEEL_ARTICULATION_POSE_ANGLES_DEG:
                        pose = wheel_hub_stack_pose(
                            axle_name,
                            side_name,
                            angle,
                        )
                        moved_running_gear = rotate_running_gear(
                            running_gear,
                            angle,
                        )
                        self.assertLessEqual(
                            float(
                                carrier.intersect(pose.gaiter).Volume()
                            ),
                            boolean_tolerance_mm3,
                        )
                        self.assertLessEqual(
                            float(carrier.distance(pose.gaiter)),
                            distance_tolerance_mm,
                        )
                        self.assertLessEqual(
                            float(
                                carrier.intersect(
                                    moved_running_gear
                                ).Volume()
                            ),
                            boolean_tolerance_mm3,
                        )
                        self.assertGreaterEqual(
                            float(carrier.distance(moved_running_gear)),
                            WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM
                            - distance_tolerance_mm,
                        )

    def test_actual_hub_axle_five_pose_occlusion_and_gaiter_invariants(
        self,
    ) -> None:
        evidence = self._evaluate()
        self.assertEqual(evidence["status"], "PASS", evidence)
        poses = evidence["poses"]
        self.assertEqual(
            tuple(row["angle_deg"] for row in poses),
            WHEEL_ARTICULATION_POSE_ANGLES_DEG,
        )
        self.assertLessEqual(
            evidence["gaiter_volume_variation_mm3"],
            WHEEL_HUB_GAITER_VOLUME_VARIATION_LIMIT_MM3,
        )
        self.assertTrue(evidence["same_topology_all_poses"])
        self.assertLessEqual(evidence["fixed_carrier_outside_belt_mm3"], 1.0e-4)
        topology = evidence["gaiter_topology_signature"]
        self.assertEqual(topology["solids"], 1)
        self.assertEqual(topology["shells"], 1)
        self.assertEqual(
            len(evidence["gaiter_topology_signatures_observed"]),
            1,
        )
        reference_bounds = poses[0]["gaiter_bounds_mm"]
        for row in poses:
            with self.subTest(angle=row["angle_deg"]):
                self.assertEqual(row["status"], "PASS", row)
                self.assertLessEqual(
                    row[
                        "normal_sightline_unoccluded_hub_axle_volume_mm3"
                    ],
                    WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3,
                )
                self.assertLessEqual(
                    row["cap_outside_fixed_aperture_mm3"],
                    1.0e-4,
                )
                self.assertLessEqual(
                    row["backing_outside_fixed_aperture_mm3"],
                    1.0e-4,
                )
                self.assertLessEqual(row["gaiter_to_belt_distance_mm"], 1.0e-4)
                self.assertGreaterEqual(
                    row["carrier_to_running_gear_clearance_mm"],
                    WHEEL_HUB_RIGID_RUNNING_GEAR_MIN_CLEARANCE_MM - 1.0e-4,
                )
                for axis, reference in reference_bounds.items():
                    self.assertAlmostEqual(
                        row["gaiter_bounds_mm"][axis],
                        reference,
                        places=6,
                    )

    def test_occlusion_proof_rejects_hub_outside_moving_island(self) -> None:
        evidence = self._evaluate(self.hub.translate((160.0, 0.0, 0.0)))
        self.assertEqual(evidence["status"], "FAIL")
        self.assertGreater(
            max(
                row[
                    "normal_sightline_unoccluded_hub_axle_volume_mm3"
                ]
                for row in evidence["poses"]
            ),
            WHEEL_HUB_NORMAL_SIGHTLINE_RESIDUAL_LIMIT_MM3,
        )


class V8WheelFourStateIdentityTests(unittest.TestCase):
    @staticmethod
    def _motion_metadata(name: str) -> dict[str, object]:
        values: dict[str, object] = {
            "fixed_to_lower_body": True,
            "suspension_articulation_sweep_deg": (-10.0, 10.0),
            "moves_with": "controlled_suspension_rocker_and_wheel_hub",
            "released_articulation_pose_angles_deg": (
                WHEEL_ARTICULATION_POSE_ANGLES_DEG
            ),
            "neutral_service_lock_required": True,
            "moves_with_service_cap": True,
            "bonded_to_service_cap_inner_face": True,
            "outer_edge_moves_with": "fixed_lower_body",
            "inner_edge_moves_with": (
                "controlled_suspension_rocker_and_wheel_hub"
            ),
            "one_piece_flexible_diaphragm": True,
            "visible_accordion_pleats": False,
        }
        return {
            key: values[key] for key in _a03_motion_metadata_keys(name)
        }

    @classmethod
    def _states(cls) -> dict[str, list[SkinPart]]:
        master_shapes = {
            name: (
                cq.Workplane("XY")
                .box(1.0, 1.0, 1.0)
                .translate((float(index) * 2.0, 0.0, 0.0))
                .val()
            )
            for index, name in enumerate(_A03_FOUR_STATE_CONSERVED_NAMES)
        }
        result: dict[str, list[SkinPart]] = {}
        for state in STATES:
            result[state] = []
            for name in _A03_FOUR_STATE_CONSERVED_NAMES:
                metadata = {
                    "physical_occurrence_id": f"TEST-{name}",
                    "material_family": "test_wheel_end_material",
                    "final_exterior_visible": (
                        "service_seam_backing" not in name
                    ),
                    **cls._motion_metadata(name),
                }
                result[state].append(
                    SkinPart(
                        name=name,
                        shape=master_shapes[name],
                        color=GRAPHITE_BROWN,
                        material="test wheel-end CMF",
                        module="A03",
                        configuration=state,
                        metadata=metadata,
                    )
                )
        return result

    @staticmethod
    def _replace_metadata(
        states: dict[str, list[SkinPart]],
        state: str,
        name: str,
        **updates: object,
    ) -> None:
        index = next(
            index
            for index, part in enumerate(states[state])
            if part.name == name
        )
        part = states[state][index]
        metadata = dict(part.metadata)
        metadata.update(updates)
        states[state][index] = replace(part, metadata=metadata)

    def test_four_state_identity_cmf_motion_and_global_id_contract(self) -> None:
        states = self._states()
        passed, _, summary = _evaluate_a03_four_state_conservation(states)
        self.assertTrue(passed, summary)
        self.assertTrue(summary["global_physical_occurrence_ids_unique"])

        gaiter = "A03_wheel_end_motion_gaiter_front_right"
        self._replace_metadata(
            states,
            "follow",
            gaiter,
            material_family="wrong_material_family",
            inner_edge_moves_with="fixed_lower_body",
        )
        first_name, second_name = _A03_FOUR_STATE_CONSERVED_NAMES[:2]
        duplicate_id = f"TEST-{first_name}"
        for state in STATES:
            self._replace_metadata(
                states,
                state,
                second_name,
                physical_occurrence_id=duplicate_id,
            )
        passed, evidence, summary = _evaluate_a03_four_state_conservation(
            states
        )
        self.assertFalse(passed)
        self.assertEqual(evidence[gaiter]["status"], "FAIL")
        self.assertFalse(summary["global_physical_occurrence_ids_unique"])


if __name__ == "__main__":
    unittest.main()
