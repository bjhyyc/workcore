from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProductState(str, Enum):
    STOWED = "STOWED"
    FOLLOW = "FOLLOW"
    RIDE = "RIDE"
    CAFE_LOCKED = "CAFE_LOCKED"
    FOCUS = "FOCUS"
    LOW_ENERGY_RECOVERY = "LOW_ENERGY_RECOVERY"
    STRANDED_SAFE = "STRANDED_SAFE"
    FAULT = "FAULT"


class Confirmation(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class Occupancy(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MotionInputs:
    state: ProductState
    occupancy: Occupancy
    mechanism_positions_known: Confirmation
    brakes_available: Confirmation
    safety_chain_healthy: Confirmation
    emergency_stop_clear: Confirmation
    user_authorized: Confirmation
    travel_configuration_safe: Confirmation = Confirmation.UNKNOWN
    follow_configuration_stowed: Confirmation = Confirmation.UNKNOWN
    follow_target_confident: Confirmation = Confirmation.UNKNOWN
    route_whitelisted: Confirmation = Confirmation.UNKNOWN


@dataclass(frozen=True)
class MotionDecision:
    traction_permitted: bool
    brake_command: str
    speed_limit_m_s: float
    reasons: tuple[str, ...]


def _deny(*reasons: str) -> MotionDecision:
    return MotionDecision(False, "APPLY", 0.0, tuple(reasons))


def evaluate_motion_authority(
    inputs: MotionInputs,
    *,
    ride_speed_limit_m_s: float = 1.0,
    follow_speed_limit_m_s: float = 0.8,
) -> MotionDecision:
    """Fail-safe reference policy; it does not command hardware directly.

    Every positive permission is based on confirmed evidence. UNKNOWN never
    inherits an earlier safe value and every denial requests the mechanical
    brakes. CAFE/FOCUS are deliberately motionless product states.
    """

    common_failures: list[str] = []
    for label, value in (
        ("mechanism_positions_not_known", inputs.mechanism_positions_known),
        ("brakes_not_confirmed_available", inputs.brakes_available),
        ("safety_chain_not_healthy", inputs.safety_chain_healthy),
        ("emergency_stop_not_confirmed_clear", inputs.emergency_stop_clear),
        ("user_not_authorized", inputs.user_authorized),
    ):
        if value is not Confirmation.CONFIRMED:
            common_failures.append(label)
    if common_failures:
        return _deny(*common_failures)

    if inputs.state in {
        ProductState.STOWED,
        ProductState.CAFE_LOCKED,
        ProductState.FOCUS,
        ProductState.LOW_ENERGY_RECOVERY,
        ProductState.STRANDED_SAFE,
        ProductState.FAULT,
    }:
        return _deny(f"state_{inputs.state.value.lower()}_has_no_traction_authority")

    if inputs.state is ProductState.FOLLOW:
        failures = []
        if inputs.occupancy is not Occupancy.EMPTY:
            failures.append("follow_requires_confirmed_empty_occupancy")
        for label, value in (
            ("follow_configuration_not_confirmed_stowed", inputs.follow_configuration_stowed),
            ("follow_target_not_confident", inputs.follow_target_confident),
            ("follow_route_not_whitelisted", inputs.route_whitelisted),
        ):
            if value is not Confirmation.CONFIRMED:
                failures.append(label)
        if failures:
            return _deny(*failures)
        return MotionDecision(
            True,
            "RELEASE_WHILE_MONITORED",
            follow_speed_limit_m_s,
            ("restricted_follow_authorized",),
        )

    if inputs.state is ProductState.RIDE:
        failures = []
        if inputs.occupancy is not Occupancy.OCCUPIED:
            failures.append("ride_requires_confirmed_occupant")
        if inputs.travel_configuration_safe is not Confirmation.CONFIRMED:
            failures.append("travel_configuration_not_confirmed_safe")
        if failures:
            return _deny(*failures)
        return MotionDecision(
            True,
            "RELEASE_WHILE_MONITORED",
            ride_speed_limit_m_s,
            ("ride_authorized",),
        )

    return _deny("unhandled_state")
