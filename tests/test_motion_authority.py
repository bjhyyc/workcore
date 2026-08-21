from __future__ import annotations

import itertools
import sys
import unittest
from dataclasses import replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from motion_authority import (  # noqa: E402
    Confirmation,
    MotionInputs,
    Occupancy,
    ProductState,
    evaluate_motion_authority,
)


def confirmed_inputs(state: ProductState, occupancy: Occupancy) -> MotionInputs:
    return MotionInputs(
        state=state,
        occupancy=occupancy,
        mechanism_positions_known=Confirmation.CONFIRMED,
        brakes_available=Confirmation.CONFIRMED,
        safety_chain_healthy=Confirmation.CONFIRMED,
        emergency_stop_clear=Confirmation.CONFIRMED,
        user_authorized=Confirmation.CONFIRMED,
        travel_configuration_safe=Confirmation.CONFIRMED,
        follow_configuration_stowed=Confirmation.CONFIRMED,
        follow_target_confident=Confirmation.CONFIRMED,
        route_whitelisted=Confirmation.CONFIRMED,
    )


class MotionAuthorityTests(unittest.TestCase):
    def test_cafe_and_focus_never_receive_traction(self) -> None:
        for state, occupancy in itertools.product(
            (ProductState.CAFE_LOCKED, ProductState.FOCUS), tuple(Occupancy)
        ):
            decision = evaluate_motion_authority(confirmed_inputs(state, occupancy))
            self.assertFalse(decision.traction_permitted)
            self.assertEqual(decision.brake_command, "APPLY")
            self.assertEqual(decision.speed_limit_m_s, 0.0)

    def test_follow_requires_confirmed_empty_occupancy(self) -> None:
        for occupancy in (Occupancy.OCCUPIED, Occupancy.UNKNOWN):
            self.assertFalse(
                evaluate_motion_authority(confirmed_inputs(ProductState.FOLLOW, occupancy)).traction_permitted
            )

    def test_valid_restricted_follow_is_speed_limited(self) -> None:
        decision = evaluate_motion_authority(confirmed_inputs(ProductState.FOLLOW, Occupancy.EMPTY))
        self.assertTrue(decision.traction_permitted)
        self.assertEqual(decision.speed_limit_m_s, 0.8)

    def test_ride_requires_occupant_and_safe_travel_configuration(self) -> None:
        baseline = confirmed_inputs(ProductState.RIDE, Occupancy.OCCUPIED)
        self.assertTrue(evaluate_motion_authority(baseline).traction_permitted)
        self.assertFalse(
            evaluate_motion_authority(confirmed_inputs(ProductState.RIDE, Occupancy.EMPTY)).traction_permitted
        )
        self.assertFalse(
            evaluate_motion_authority(
                replace(baseline, travel_configuration_safe=Confirmation.UNKNOWN)
            ).traction_permitted
        )

    def test_every_unknown_common_safety_input_revokes_authority(self) -> None:
        baseline = confirmed_inputs(ProductState.RIDE, Occupancy.OCCUPIED)
        for field in (
            "mechanism_positions_known",
            "brakes_available",
            "safety_chain_healthy",
            "emergency_stop_clear",
            "user_authorized",
        ):
            decision = evaluate_motion_authority(replace(baseline, **{field: Confirmation.UNKNOWN}))
            self.assertFalse(decision.traction_permitted, field)
            self.assertEqual(decision.brake_command, "APPLY", field)

    def test_recovery_and_fault_states_default_to_braked(self) -> None:
        for state in (
            ProductState.LOW_ENERGY_RECOVERY,
            ProductState.STRANDED_SAFE,
            ProductState.FAULT,
        ):
            decision = evaluate_motion_authority(confirmed_inputs(state, Occupancy.OCCUPIED))
            self.assertFalse(decision.traction_permitted)
            self.assertEqual(decision.brake_command, "APPLY")


if __name__ == "__main__":
    unittest.main()
