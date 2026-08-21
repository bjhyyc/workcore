from __future__ import annotations

import csv
import math
from pathlib import Path


def _fit_clearance(aperture_mm: float, product_mm: float) -> dict:
    clearance = aperture_mm - product_mm
    return {
        "aperture_mm": aperture_mm,
        "product_mm": product_mm,
        "total_clearance_mm": clearance,
        "clearance_each_side_mm": clearance / 2.0,
        "pass": clearance >= 0.0,
    }


def analyze(geometry_report: dict, engineering_report: dict, p) -> dict:
    stowed = geometry_report["overall_envelopes"]["stowed"]
    follow = geometry_report["overall_envelopes"]["follow"]
    occupied = geometry_report["overall_envelopes"]["seat"]
    mobility = engineering_report["mobility"]
    turning_circle = mobility["occupied_turning_circle_mm"]
    stowed_mass = engineering_report["scenarios"]["stowed_unoccupied"]["centre_of_mass"]["mass_kg"]

    doors = {
        "existing_accessible_800": _fit_clearance(800.0, occupied["width_y_mm"]),
        "new_accessible_manual_900": _fit_clearance(900.0, occupied["width_y_mm"]),
        "new_accessible_automatic_1000": _fit_clearance(1000.0, occupied["width_y_mm"]),
    }
    for name, values in doors.items():
        values["operating_assessment"] = (
            "normal low-speed passage"
            if values["clearance_each_side_mm"] >= 75.0
            else "precision passage only; edge sensing and 0.20 m/s limit required"
            if values["pass"]
            else "not passable"
        )

    elevators = {
        "minimum_accessible_car_1100x1400_door900": {
            "car_width_mm": 1100.0,
            "car_depth_mm": 1400.0,
            "door": _fit_clearance(900.0, occupied["width_y_mm"]),
        },
        "existing_renovation_car_1100x1400_door800": {
            "car_width_mm": 1100.0,
            "car_depth_mm": 1400.0,
            "door": _fit_clearance(800.0, occupied["width_y_mm"]),
        },
    }
    for values in elevators.values():
        values["straight_entry_fit"] = (
            occupied["width_y_mm"] <= values["car_width_mm"]
            and occupied["length_x_mm"] <= values["car_depth_mm"]
            and values["door"]["pass"]
        )
        values["in_car_zero_turn_fit"] = turning_circle <= min(
            values["car_width_mm"], values["car_depth_mm"]
        )
        values["assessment"] = (
            "enter and exit in the same longitudinal orientation; do not promise an in-car 90-degree turn"
            if values["straight_entry_fit"] and not values["in_car_zero_turn_fit"]
            else "geometry fit"
            if values["straight_entry_fit"]
            else "does not fit"
        )

    public_space = {
        "accessible_passage_1200": {
            **_fit_clearance(1200.0, occupied["width_y_mm"]),
            "assessment": "comfortable straight travel with pedestrian yielding logic",
        },
        "elevator_lobby_turning_space_1500": {
            "space_mm": p.elevator_lobby_turning_space_mm,
            "turning_circle_mm": turning_circle,
            "diametral_margin_mm": p.elevator_lobby_turning_space_mm - turning_circle,
            "pass": turning_circle <= p.elevator_lobby_turning_space_mm,
            "assessment": "low-speed zero-turn only; no moving pedestrian may be inside the swept envelope",
        },
        "shop_aisle_1200": {
            **_fit_clearance(1200.0, occupied["width_y_mm"]),
            "assessment": "straight travel feasible; shelf-end turns need a 1500 mm clear node",
        },
    }

    # These are engineering fit templates, not vehicle standards. Every target
    # vehicle must be measured at the actual opening, sill, wheel housings and
    # seatback before a compatibility claim is made.
    trunk_templates = {
        "sedan_reference": {"opening_width_mm": 1000.0, "opening_height_mm": 550.0, "depth_mm": 900.0},
        "compact_suv_reference": {"opening_width_mm": 1050.0, "opening_height_mm": 700.0, "depth_mm": 850.0},
        "midsize_suv_reference": {"opening_width_mm": 1100.0, "opening_height_mm": 780.0, "depth_mm": 1000.0},
        "mpv_reference": {"opening_width_mm": 1150.0, "opening_height_mm": 900.0, "depth_mm": 1100.0},
    }
    for values in trunk_templates.values():
        values["stowed_width_mm"] = stowed["width_y_mm"]
        values["stowed_height_mm"] = stowed["height_z_mm"]
        values["stowed_length_mm"] = stowed["length_x_mm"]
        values["raw_upright_opening_fit"] = (
            stowed["width_y_mm"] <= values["opening_width_mm"]
            and stowed["height_z_mm"] <= values["opening_height_mm"]
        )
        values["raw_depth_fit"] = stowed["length_x_mm"] <= values["depth_mm"]
        values["opening_width_margin_mm"] = values["opening_width_mm"] - stowed["width_y_mm"]
        values["opening_height_margin_mm"] = values["opening_height_mm"] - stowed["height_z_mm"]
        values["depth_margin_mm"] = values["depth_mm"] - stowed["length_x_mm"]
        values["production_reserve_requirements_mm"] = {
            "opening_width_total": 50.0,
            "opening_height": 30.0,
            "depth": 50.0,
        }
        values["overall_geometric_fit"] = (
            values["opening_width_margin_mm"] >= 50.0
            and values["opening_height_margin_mm"] >= 30.0
            and values["depth_margin_mm"] >= 50.0
        )
        values["assessment"] = (
            "template fit with handling reserve only; powered lift or roll-in system still required"
            if values["overall_geometric_fit"]
            else "raw dimensions may fit, but production/handling reserve is inadequate"
            if values["raw_upright_opening_fit"] and values["raw_depth_fit"]
            else "template does not fit"
        )

    lift_capacity = math.ceil(stowed_mass * 1.25 / 10.0) * 10.0
    transport = {
        "stowed_mass_kg": stowed_mass,
        "manual_lift_allowed": False,
        "manual_handling_reason": "integrated product mass and unstable handholds make trunk lifting an unacceptable user task",
        "minimum_vehicle_lift_platform_mm": {
            "length": math.ceil((stowed["length_x_mm"] + 100.0) / 10.0) * 10.0,
            "width": math.ceil((stowed["width_y_mm"] + 100.0) / 10.0) * 10.0,
        },
        "minimum_vehicle_lift_rated_capacity_kg": lift_capacity,
        "required_restraints": "four chassis-datum tie-downs; wheels/brakes are not cargo restraints",
    }
    follow_nominal_stop_distance_m = (
        p.follow_speed_max_m_s * p.follow_target_loss_stop_s
        + p.follow_speed_max_m_s**2 / (2.0 * p.occupied_braking_max_g * p.gravity)
    )

    checks = []
    for name, values in doors.items():
        checks.append(
            {
                "category": "access",
                "check": f"door_width:{name}",
                "actual_mm": values["product_mm"],
                "maximum_mm": values["aperture_mm"],
                "pass": values["pass"],
            }
        )
    checks.extend(
        [
            {
                "category": "restricted_follow",
                "check": "follow_speed_cap",
                "actual_m_s": p.follow_speed_max_m_s,
                "maximum_m_s": 0.8,
                "pass": p.follow_speed_max_m_s <= 0.8,
            },
            {
                "category": "restricted_follow",
                "check": "follow_target_loss_stop_time",
                "actual_s": p.follow_target_loss_stop_s,
                "maximum_s": 0.5,
                "pass": p.follow_target_loss_stop_s <= 0.5,
            },
            {
                "category": "restricted_follow",
                "check": "follow_nominal_gap",
                "actual_m": p.follow_gap_nominal_m,
                "minimum_m": 1.0,
                "maximum_m": 1.5,
                "pass": 1.0 <= p.follow_gap_nominal_m <= 1.5,
            },
            {
                "category": "restricted_follow",
                "check": "follow_closed_envelope_matches_stowed",
                "actual_mm": follow,
                "reference_mm": stowed,
                "pass": all(abs(follow[key] - stowed[key]) < 0.01 for key in stowed),
            },
            {
                "category": "community_motion",
                "check": "community_default_speed_cap",
                "actual_m_s": p.community_default_speed_m_s,
                "maximum_m_s": 1.0,
                "pass": p.community_default_speed_m_s <= 1.0,
            },
            {
                "category": "community_motion",
                "check": "cafe_locked_traction_speed_zero",
                "actual_m_s": p.cafe_creep_speed_m_s,
                "maximum_m_s": 0.0,
                "pass": p.cafe_creep_speed_m_s == 0.0,
            },
            {
                "category": "transport_envelope",
                "check": "stowed_length_limit",
                "actual_mm": stowed["length_x_mm"],
                "maximum_mm": p.travel_length_max,
                "pass": stowed["length_x_mm"] <= p.travel_length_max,
            },
            {
                "category": "transport_envelope",
                "check": "stowed_width_limit",
                "actual_mm": stowed["width_y_mm"],
                "maximum_mm": p.travel_width_max,
                "pass": stowed["width_y_mm"] <= p.travel_width_max,
            },
            {
                "category": "transport_envelope",
                "check": "stowed_height_limit",
                "actual_mm": stowed["height_z_mm"],
                "maximum_mm": p.travel_height_max,
                "pass": stowed["height_z_mm"] <= p.travel_height_max,
            },
            {
                "category": "transport_envelope",
                "check": "stowed_length_production_reserve",
                "actual_margin_mm": p.travel_length_max - stowed["length_x_mm"],
                "minimum_margin_mm": p.travel_length_production_reserve,
                "pass": p.travel_length_max - stowed["length_x_mm"] >= p.travel_length_production_reserve,
            },
            {
                "category": "transport_envelope",
                "check": "stowed_width_production_reserve",
                "actual_margin_mm": p.travel_width_max - stowed["width_y_mm"],
                "minimum_margin_mm": p.travel_width_production_reserve,
                "pass": p.travel_width_max - stowed["width_y_mm"] >= p.travel_width_production_reserve,
            },
            {
                "category": "transport_envelope",
                "check": "stowed_height_production_reserve",
                "actual_margin_mm": p.travel_height_max - stowed["height_z_mm"],
                "minimum_margin_mm": p.travel_height_production_reserve,
                "pass": p.travel_height_max - stowed["height_z_mm"] >= p.travel_height_production_reserve,
            },
            {
                "category": "access",
                "check": "minimum_accessible_elevator_straight_entry",
                "pass": elevators["minimum_accessible_car_1100x1400_door900"]["straight_entry_fit"],
            },
            {
                "category": "access",
                "check": "1500mm_lobby_zero_turn",
                "actual_mm": turning_circle,
                "maximum_mm": p.elevator_lobby_turning_space_mm,
                "pass": turning_circle <= p.elevator_lobby_turning_space_mm,
            },
            {
                "category": "access",
                "check": "1200mm_shop_aisle_straight",
                "actual_mm": occupied["width_y_mm"],
                "maximum_mm": 1200.0,
                "pass": occupied["width_y_mm"] <= 1200.0,
            },
        ]
    )

    return {
        "revision": "E6",
        "basis": {
            "target_population": "Creators, AI-intensive knowledge workers, freelancers and users with light mobility constraints moving between home, community and café; no elder-care or unattended medical claim",
            "door_and_elevator_basis": "GB 55019-2021 geometry; existing-site measurements remain mandatory",
            "trunk_template_status": "internal design templates, not universal vehicle dimensions or compatibility claims",
        },
        "occupied_envelope_mm": occupied,
        "stowed_envelope_mm": stowed,
        "follow_envelope_mm": follow,
        "follow_operating_boundary": {
            "occupancy": "empty and fully folded only",
            "route": "whitelisted private/community route Beta; owner in sight; no public-road claim",
            "identity": "paired UWB key or authorized phone plus visual confidence",
            "speed_max_m_s": p.follow_speed_max_m_s,
            "nominal_gap_m": p.follow_gap_nominal_m,
            "target_loss_stop_s": p.follow_target_loss_stop_s,
            "nominal_stop_reference": {
                "distance_m": follow_nominal_stop_distance_m,
                "gap_margin_m": p.follow_gap_nominal_m - follow_nominal_stop_distance_m,
                "status": "analytical reference only; full perception-to-STO/brake chain and surface/grade/load envelope remain DVP evidence",
            },
            "hard_exclusions": ["stairs", "road crossings", "crowds", "autonomous elevator or automatic-door traversal"],
        },
        "doors": doors,
        "elevators": elevators,
        "public_space": public_space,
        "trunk_templates": trunk_templates,
        "transport": transport,
        "checks": checks,
    }


def write_access_csv(report: dict, target: Path) -> None:
    rows = []
    for name, values in report["doors"].items():
        rows.append(
            [
                "door",
                name,
                values["aperture_mm"],
                values["product_mm"],
                values["total_clearance_mm"],
                "PASS" if values["pass"] else "FAIL",
                values["operating_assessment"],
            ]
        )
    for name, values in report["trunk_templates"].items():
        rows.append(
            [
                "vehicle_template",
                name,
                f"{values['opening_width_mm']}x{values['opening_height_mm']} opening; {values['depth_mm']} deep",
                f"{values['stowed_width_mm']:.1f}x{values['stowed_height_mm']:.1f}; {values['stowed_length_mm']:.1f} long",
                "",
                "PASS" if values["overall_geometric_fit"] else "FAIL",
                values["assessment"],
            ]
        )
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["category", "scenario", "available", "required", "margin_mm", "status", "assessment"])
        writer.writerows(rows)
