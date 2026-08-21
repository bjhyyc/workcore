from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MassPoint:
    name: str
    mass_kg: float
    x_mm: float
    y_mm: float
    z_mm: float


def _part_mass_point(part) -> MassPoint:
    c = part.solid.Center()
    total_mass_kg = float(part.mass_kg) * int(getattr(part, "quantity", 1))
    return MassPoint(part.name, total_mass_kg, float(c.x), float(c.y), float(c.z))


def required_proof_target_n_m(force_n: float, lever_mm: float, proof_factor: float = 1.5) -> float:
    """Return a required proof target, never a demonstrated component capacity."""
    if force_n < 0.0 or lever_mm < 0.0 or proof_factor < 1.0:
        raise ValueError("force/lever must be non-negative and proof factor must be at least 1.0")
    return proof_factor * force_n * lever_mm / 1000.0


def centre_of_mass(parts, extras: list[MassPoint] | None = None) -> dict:
    points = [_part_mass_point(p) for p in parts]
    if extras:
        points.extend(extras)
    total = sum(p.mass_kg for p in points)
    if total <= 0:
        raise ValueError("Mass model has no positive mass")
    return {
        "mass_kg": total,
        "x_mm": sum(p.mass_kg * p.x_mm for p in points) / total,
        "y_mm": sum(p.mass_kg * p.y_mm for p in points) / total,
        "z_mm": sum(p.mass_kg * p.z_mm for p in points) / total,
    }


def stability(cg: dict, p) -> dict:
    front_margin = cg["x_mm"] - p.wheel_x_front
    rear_margin = p.wheel_x_rear - cg["x_mm"]
    side_margin = p.wheel_y - abs(cg["y_mm"])
    z = max(cg["z_mm"], 1.0)
    return {
        "front_margin_mm": front_margin,
        "rear_margin_mm": rear_margin,
        "side_margin_mm": side_margin,
        "front_tip_angle_deg": math.degrees(math.atan2(front_margin, z)),
        "rear_tip_angle_deg": math.degrees(math.atan2(rear_margin, z)),
        "side_tip_angle_deg": math.degrees(math.atan2(side_margin, z)),
    }


def rectangular_solid_section(width_mm: float, height_mm: float) -> dict:
    inertia = width_mm * height_mm**3 / 12.0
    return {"i_mm4": inertia, "z_mm3": inertia / (height_mm / 2.0)}


def circular_tube_section(od_mm: float, wall_mm: float) -> dict:
    inner = od_mm - 2 * wall_mm
    inertia = math.pi * (od_mm**4 - inner**4) / 64.0
    return {"i_mm4": inertia, "z_mm3": inertia / (od_mm / 2.0)}


def square_tube_section(side_mm: float, wall_mm: float) -> dict:
    inner = side_mm - 2.0 * wall_mm
    inertia = (side_mm**4 - inner**4) / 12.0
    return {"i_mm4": inertia, "z_mm3": inertia / (side_mm / 2.0)}


def analyze(configs: dict, p) -> dict:
    occupant = MassPoint("design_occupant", p.occupant_design_mass, 45.0, 0.0, 850.0)
    cargo = MassPoint("design_cargo", p.cargo_design_mass, 0.0, 0.0, 400.0)
    desk_loads = [
        MassPoint("desk_load_left", p.desk_design_load_mass_each, p.table_x, -130.0, p.table_surface_z),
        MassPoint("desk_load_right", p.desk_design_load_mass_each, p.table_x, 130.0, p.table_surface_z),
    ]
    cafe_load = MassPoint(
        "cafe_transverse_table_load",
        p.desk_design_load_mass_each,
        p.cafe_table_x,
        p.table_centre_safety_gap / 2.0 + p.table_half_width / 2.0,
        p.table_surface_z,
    )

    scenarios = {}
    scenario_inputs = {
        "stowed_unoccupied": (configs["stowed"], []),
        "seat_occupied": (configs["seat"], [occupant, cargo]),
        "cafe_occupied_rated": (configs["cafe"], [occupant, cargo, cafe_load]),
        "desk_occupied_rated": (configs["desk"], [occupant, cargo, *desk_loads]),
        "canopy_unoccupied": (configs["deployed"], []),
        "canopy_occupied": (configs["deployed"], [occupant, cargo]),
    }
    for name, (parts, extras) in scenario_inputs.items():
        cg = centre_of_mass(parts, extras)
        scenarios[name] = {"centre_of_mass": cg, "stability": stability(cg, p)}

    checks = []
    for name, values in scenarios.items():
        s = values["stability"]
        for axis, value, minimum in (
            ("front_tip_angle", s["front_tip_angle_deg"], 10.0),
            ("rear_tip_angle", s["rear_tip_angle_deg"], 10.0),
            ("side_tip_angle", s["side_tip_angle_deg"], 12.0),
        ):
            checks.append(
                {
                    "category": "stability",
                    "check": f"{name}:{axis}",
                    "actual_deg": value,
                    "minimum_deg": minimum,
                    "pass": value >= minimum,
                }
            )

    # Occupied mobility is evaluated with the footrest deployed. Four fixed hub
    # wheels use left/right differential commands; zero-turn is deliberately a
    # low-speed peak-torque manoeuvre because tyre scrub dominates at standstill.
    occupied_cg = scenarios["seat_occupied"]["centre_of_mass"]
    occupied_mass = occupied_cg["mass_kg"]
    occupied_weight_n = occupied_mass * p.gravity
    wheelbase_m = (p.wheel_x_rear - p.wheel_x_front) / 1000.0
    tyre_radius_m = p.wheel_diameter / 2000.0
    pivot_x = (p.wheel_x_front + p.wheel_x_rear) / 2.0
    occupied_turn_radius_mm = 0.0
    occupied_xy_bounds = {
        "xmin": math.inf,
        "xmax": -math.inf,
        "ymin": math.inf,
        "ymax": -math.inf,
    }
    for candidate in configs["seat"]:
        box = candidate.solid.BoundingBox()
        occupied_xy_bounds["xmin"] = min(occupied_xy_bounds["xmin"], float(box.xmin))
        occupied_xy_bounds["xmax"] = max(occupied_xy_bounds["xmax"], float(box.xmax))
        occupied_xy_bounds["ymin"] = min(occupied_xy_bounds["ymin"], float(box.ymin))
        occupied_xy_bounds["ymax"] = max(occupied_xy_bounds["ymax"], float(box.ymax))
        for x in (float(box.xmin), float(box.xmax)):
            for y in (float(box.ymin), float(box.ymax)):
                occupied_turn_radius_mm = max(occupied_turn_radius_mm, math.hypot(x - pivot_x, y))
    turning_circle_mm = 2.0 * occupied_turn_radius_mm
    rocker_differential_travel_mm = (
        2.0
        * (p.wheel_x_rear - p.wheel_x_front)
        / 2.0
        * math.sin(math.radians(p.rocker_articulation_deg))
    )
    rocker_section = rectangular_solid_section(
        p.rocker_lateral_thickness,
        p.rocker_section,
    )
    rocker_extreme_moment_n_m = (
        occupied_weight_n
        * p.mobile_dynamic_factor
        * (p.wheel_x_rear - p.wheel_x_front)
        / 4000.0
    )
    rocker_extreme_stress_mpa = rocker_extreme_moment_n_m * 1000.0 / rocker_section["z_mm3"]

    zero_turn_scrub_n_m = (
        p.dry_traction_coefficient * occupied_weight_n * wheelbase_m / 2.0
    )
    zero_turn_peak_yaw_n_m = (
        4.0 * p.hub_motor_peak_torque_n_m / tyre_radius_m * p.wheel_y / 1000.0
    )
    zero_turn_continuous_yaw_n_m = (
        4.0 * p.hub_motor_continuous_torque_n_m / tyre_radius_m * p.wheel_y / 1000.0
    )
    zero_turn_peak_sf = zero_turn_peak_yaw_n_m / max(zero_turn_scrub_n_m, 1e-9)

    wheelbase_mm = p.wheel_x_rear - p.wheel_x_front
    front_reaction_n = occupied_weight_n * (p.wheel_x_rear - occupied_cg["x_mm"]) / wheelbase_mm
    rear_reaction_n = occupied_weight_n - front_reaction_n
    total_peak_tractive_n = min(
        p.dry_traction_coefficient * occupied_weight_n,
        4.0 * p.hub_motor_peak_torque_n_m / tyre_radius_m,
    )

    def obstacle_case(height_mm: float, design_sf: float) -> dict:
        radius_mm = p.wheel_diameter / 2.0
        if height_mm <= 0 or height_mm >= radius_mm:
            return {
                "height_mm": height_mm,
                "geometrically_possible": False,
                "pass_at_design_sf": False,
            }
        corner_arm_mm = math.sqrt(2.0 * radius_mm * height_mm - height_mm**2)
        required_torque_each_n_m = front_reaction_n / 2.0 * corner_arm_mm / 1000.0
        horizontal_force_n = front_reaction_n * corner_arm_mm / (radius_mm - height_mm)
        torque_sf = p.hub_motor_peak_torque_n_m / max(required_torque_each_n_m, 1e-9)
        traction_sf = total_peak_tractive_n / max(horizontal_force_n, 1e-9)
        clearance_margin_mm = p.footrest_deployed_z - p.footrest_thickness / 2.0 - height_mm
        return {
            "height_mm": height_mm,
            "corner_arm_mm": corner_arm_mm,
            "front_axle_static_reaction_n": front_reaction_n,
            "rear_axle_static_reaction_n": rear_reaction_n,
            "required_peak_torque_each_front_hub_n_m": required_torque_each_n_m,
            "available_peak_torque_each_hub_n_m": p.hub_motor_peak_torque_n_m,
            "required_horizontal_force_n": horizontal_force_n,
            "available_total_peak_tractive_force_n": total_peak_tractive_n,
            "torque_safety_factor": torque_sf,
            "traction_safety_factor": traction_sf,
            "footrest_ground_clearance_margin_mm": clearance_margin_mm,
            "geometrically_possible": True,
            "pass_at_design_sf": torque_sf >= design_sf
            and traction_sf >= design_sf
            and clearance_margin_mm >= 20.0,
        }

    rated_obstacle = obstacle_case(p.rated_vertical_obstacle_mm, 1.25)
    conditional_obstacle = obstacle_case(p.conditional_vertical_obstacle_mm, 1.0)
    qualified_height_mm = 0.0
    for step in range(1, int(p.wheel_diameter / 2.0)):
        if obstacle_case(float(step), 1.25)["pass_at_design_sf"]:
            qualified_height_mm = float(step)

    dynamic_front_limit_g = (occupied_cg["x_mm"] - p.wheel_x_front) / occupied_cg["z_mm"]
    dynamic_rear_limit_g = (p.wheel_x_rear - occupied_cg["x_mm"]) / occupied_cg["z_mm"]
    side_limit_deg = math.degrees(
        math.atan2(p.wheel_y - abs(occupied_cg["y_mm"]), occupied_cg["z_mm"])
    )
    stopping_distance_m = (
        p.occupied_speed_max_m_s**2 / (2.0 * p.occupied_braking_max_g * p.gravity)
        + p.occupied_speed_max_m_s * 0.15
    )
    service_brake_torque_each_n_m = (
        occupied_mass * p.occupied_braking_max_g * p.gravity / 4.0 * tyre_radius_m
    )
    ten_degree_hold_torque_each_n_m = occupied_weight_n * math.sin(math.radians(10.0)) / 4.0 * tyre_radius_m

    footrest_force_n = p.occupant_design_mass * p.gravity * p.mobile_dynamic_factor
    footrest_support_length_mm = abs(
        (p.body_x - p.body_length / 2.0) - p.footrest_deployed_x
    )
    footrest_section = square_tube_section(p.footrest_support_section, p.footrest_support_wall)
    footrest_root_moment_n_mm = footrest_force_n / 2.0 * footrest_support_length_mm
    footrest_support_stress_mpa = footrest_root_moment_n_mm / footrest_section["z_mm3"]
    footrest_support_deflection_mm = (
        footrest_force_n
        / 2.0
        * footrest_support_length_mm**3
        / (3.0 * 69_000.0 * footrest_section["i_mm4"])
    )
    footrest_pin_area_mm2 = math.pi * p.footrest_lock_pin_diameter**2 / 4.0
    footrest_lock_pin_shear_mpa = footrest_force_n / (4.0 * footrest_pin_area_mm2)

    restraint_force_n = (
        p.occupant_design_mass * p.restraint_design_deceleration_g * p.gravity
    )
    restraint_pin_area_mm2 = math.pi * p.restraint_anchor_pin_diameter**2 / 4.0
    restraint_anchor_pin_shear_mpa = restraint_force_n / 2.0 / restraint_pin_area_mm2

    mobility = {
        "drive_architecture": "four fixed hub motors; left/right differential command; power-off brakes",
        "occupied_mass_kg": occupied_mass,
        "occupied_xy_bounds_mm": occupied_xy_bounds,
        "instantaneous_turn_centre_x_mm": pivot_x,
        "occupied_turning_radius_mm": occupied_turn_radius_mm,
        "occupied_turning_circle_mm": turning_circle_mm,
        "rocker_articulation_each_direction_deg": p.rocker_articulation_deg,
        "rocker_differential_wheel_travel_mm": rocker_differential_travel_mm,
        "rocker_extreme_dynamic_moment_n_m": rocker_extreme_moment_n_m,
        "rocker_extreme_stress_mpa": rocker_extreme_stress_mpa,
        "zero_turn_tire_speed_m_s": p.zero_turn_tire_speed_m_s,
        "zero_turn_ramp_time_s": p.zero_turn_ramp_time_s,
        "estimated_dry_scrub_resistance_n_m": zero_turn_scrub_n_m,
        "available_peak_yaw_moment_n_m": zero_turn_peak_yaw_n_m,
        "available_continuous_yaw_moment_n_m": zero_turn_continuous_yaw_n_m,
        "zero_turn_peak_safety_factor": zero_turn_peak_sf,
        "zero_turn_continuous_operation_allowed": zero_turn_continuous_yaw_n_m >= zero_turn_scrub_n_m,
        "rated_obstacle": rated_obstacle,
        "conditional_obstacle": conditional_obstacle,
        "calculated_max_vertical_obstacle_at_1_25_sf_mm": qualified_height_mm,
        "dynamic_tip_limits_g": {
            "forward_braking": dynamic_front_limit_g,
            "rearward_acceleration": dynamic_rear_limit_g,
        },
        "side_tip_limit_deg": side_limit_deg,
        "stopping_distance_including_150ms_control_m": stopping_distance_m,
        "service_brake_torque_each_n_m": service_brake_torque_each_n_m,
        "ten_degree_hold_torque_each_n_m": ten_degree_hold_torque_each_n_m,
        "power_off_brake_available_each_n_m": p.power_off_brake_holding_torque_n_m,
        "footrest": {
            "factored_vertical_load_n": footrest_force_n,
            "support_root_moment_each_n_m": footrest_root_moment_n_mm / 1000.0,
            "support_stress_mpa": footrest_support_stress_mpa,
            "support_deflection_mm": footrest_support_deflection_mm,
            "lock_pin_double_shear_mpa": footrest_lock_pin_shear_mpa,
        },
        "pelvic_restraint": {
            "design_deceleration_g": p.restraint_design_deceleration_g,
            "total_design_force_n": restraint_force_n,
            "anchor_pin_single_shear_mpa": restraint_anchor_pin_shear_mpa,
        },
        "control_interlocks": [
            "zero-turn only with desk latched stowed, canopy retracted, footrest clear and speed below 0.30 m/s",
            "desk deployment inhibits traction; lid-closed dual-channel confirmation precedes panel unfold",
            "loss of power applies all four brakes; no software-only parking state",
        ],
    }
    checks.extend(
        [
            {
                "category": "mobility",
                "check": "occupied_zero_turn_circle",
                "actual_mm": turning_circle_mm,
                "maximum_mm": p.turning_circle_design_max_mm,
                "pass": turning_circle_mm <= p.turning_circle_design_max_mm,
            },
            {
                "category": "mobility",
                "check": "rocker_articulation_covers_conditional_obstacle",
                "actual_differential_travel_mm": rocker_differential_travel_mm,
                "minimum_mm": p.conditional_vertical_obstacle_mm,
                "pass": rocker_differential_travel_mm >= p.conditional_vertical_obstacle_mm,
            },
            {
                "category": "mobility",
                "check": "rocker_extreme_dynamic_stress",
                "actual_mpa": rocker_extreme_stress_mpa,
                "maximum_mpa": 240.0,
                "pass": rocker_extreme_stress_mpa <= 240.0,
            },
            {
                "category": "mobility",
                "check": "zero_turn_peak_yaw_safety_factor",
                "actual": zero_turn_peak_sf,
                "minimum": 1.25,
                "pass": zero_turn_peak_sf >= 1.25,
            },
            {
                "category": "mobility",
                "check": "rated_vertical_obstacle_torque_sf",
                "actual": rated_obstacle["torque_safety_factor"],
                "minimum": 1.25,
                "pass": rated_obstacle["torque_safety_factor"] >= 1.25,
            },
            {
                "category": "mobility",
                "check": "rated_vertical_obstacle_traction_sf",
                "actual": rated_obstacle["traction_safety_factor"],
                "minimum": 1.25,
                "pass": rated_obstacle["traction_safety_factor"] >= 1.25,
            },
            {
                "category": "mobility",
                "check": "rated_vertical_obstacle_ground_clearance",
                "actual_mm": rated_obstacle["footrest_ground_clearance_margin_mm"],
                "minimum_mm": 20.0,
                "pass": rated_obstacle["footrest_ground_clearance_margin_mm"] >= 20.0,
            },
            {
                "category": "mobility",
                "check": "occupied_braking_tip_safety_factor",
                "actual": dynamic_front_limit_g / p.occupied_braking_max_g,
                "minimum": p.anti_tip_safety_factor,
                "pass": dynamic_front_limit_g / p.occupied_braking_max_g >= p.anti_tip_safety_factor,
            },
            {
                "category": "mobility",
                "check": "occupied_acceleration_tip_safety_factor",
                "actual": dynamic_rear_limit_g / p.occupied_acceleration_max_g,
                "minimum": p.anti_tip_safety_factor,
                "pass": dynamic_rear_limit_g / p.occupied_acceleration_max_g >= p.anti_tip_safety_factor,
            },
            {
                "category": "mobility",
                "check": "occupied_cross_slope_tip_safety_factor",
                "actual": side_limit_deg / p.occupied_cross_slope_max_deg,
                "minimum": p.anti_tip_safety_factor,
                "pass": side_limit_deg / p.occupied_cross_slope_max_deg >= p.anti_tip_safety_factor,
            },
            {
                "category": "mobility",
                "check": "power_off_brake_ten_degree_hold",
                "actual_n_m": p.power_off_brake_holding_torque_n_m,
                "minimum_n_m": ten_degree_hold_torque_each_n_m * p.anti_tip_safety_factor,
                "pass": p.power_off_brake_holding_torque_n_m
                >= ten_degree_hold_torque_each_n_m * p.anti_tip_safety_factor,
            },
            {
                "category": "occupant_interface",
                "check": "footrest_support_dynamic_stress",
                "actual_mpa": footrest_support_stress_mpa,
                "maximum_mpa": 160.0,
                "pass": footrest_support_stress_mpa <= 160.0,
            },
            {
                "category": "occupant_interface",
                "check": "footrest_support_dynamic_deflection",
                "actual_mm": footrest_support_deflection_mm,
                "maximum_mm": 3.0,
                "pass": footrest_support_deflection_mm <= 3.0,
            },
            {
                "category": "occupant_interface",
                "check": "footrest_lock_pin_double_shear",
                "actual_mpa": footrest_lock_pin_shear_mpa,
                "maximum_mpa": 150.0,
                "pass": footrest_lock_pin_shear_mpa <= 150.0,
            },
            {
                "category": "occupant_interface",
                "check": "pelvic_restraint_anchor_pin_shear_10g",
                "actual_mpa": restraint_anchor_pin_shear_mpa,
                "maximum_mpa": 150.0,
                "pass": restraint_anchor_pin_shear_mpa <= 150.0,
            },
        ]
    )

    # Worst-direction unoccupied wind stability with canopy deployed.
    canopy_area_m2 = p.canopy_projection * p.canopy_total_width / 1_000_000.0
    structural_q_pa = 0.5 * p.air_density_kg_m3 * p.canopy_structural_wind_m_s**2
    structural_wind_force_n = (
        structural_q_pa * p.canopy_drag_coefficient * canopy_area_m2 * p.canopy_wind_load_factor
    )
    operational_q_pa = 0.5 * p.air_density_kg_m3 * p.canopy_retract_wind_m_s**2
    operational_wind_force_n = (
        operational_q_pa * p.canopy_drag_coefficient * canopy_area_m2 * p.canopy_wind_load_factor
    )
    canopy_parts = {part.name: part for part in configs["deployed"]}
    fabric_centre = canopy_parts["canopy_fabric_deployed"].solid.Center()
    dry = scenarios["canopy_unoccupied"]
    dry_cg = dry["centre_of_mass"]
    dry_stability = dry["stability"]
    restoring_n_m = (
        dry_cg["mass_kg"]
        * p.gravity
        * min(
            dry_stability["front_margin_mm"],
            dry_stability["rear_margin_mm"],
            dry_stability["side_margin_mm"],
        )
        / 1000.0
    )
    structural_overturning_n_m = structural_wind_force_n * float(fabric_centre.z) / 1000.0
    structural_tip_sf = restoring_n_m / max(structural_overturning_n_m, 1e-9)
    operational_overturning_n_m = operational_wind_force_n * float(fabric_centre.z) / 1000.0
    operational_tip_sf = restoring_n_m / max(operational_overturning_n_m, 1e-9)
    wind = {
        "auto_retract_air_speed_m_s": p.canopy_retract_wind_m_s,
        "operational_dynamic_pressure_pa": operational_q_pa,
        "operational_factored_force_n": operational_wind_force_n,
        "structural_air_speed_m_s": p.canopy_structural_wind_m_s,
        "structural_dynamic_pressure_pa": structural_q_pa,
        "structural_factored_force_n": structural_wind_force_n,
        "application_height_mm": float(fabric_centre.z),
        "restoring_moment_n_m": restoring_n_m,
        "operational_overturning_moment_n_m": operational_overturning_n_m,
        "operational_tip_safety_factor": operational_tip_sf,
        "structural_overturning_moment_n_m": structural_overturning_n_m,
        "structural_tip_safety_factor_without_retraction": structural_tip_sf,
        "required_control_mitigation": "dual wind sensing + spring-assisted fail-safe retract; no 20 m/s deployed rating",
    }
    checks.append(
        {
            "category": "wind",
            "check": "unoccupied_canopy_tip_sf_at_auto_retract_threshold",
            "actual": operational_tip_sf,
            "minimum": p.anti_tip_safety_factor,
            "pass": operational_tip_sf >= p.anti_tip_safety_factor,
        }
    )

    # Table post, panel and positive lock calculations.
    table_force_n = p.desk_design_load_mass_each * p.gravity * p.mobile_dynamic_factor
    table_lever_mm = p.table_pole_y - p.table_half_width / 2.0
    table_moment_n_mm = table_force_n * table_lever_mm
    pole = circular_tube_section(p.table_pole_od, p.table_pole_wall)
    pole_stress_mpa = table_moment_n_mm / pole["z_mm3"]
    pole_length_mm = p.table_surface_z - p.table_thickness - (p.armrest_bottom_z + 70.0)
    pole_deflection_mm = table_moment_n_mm * pole_length_mm**2 / (2 * 69_000.0 * pole["i_mm4"])

    skin_t = 0.8
    skin_centroid = (p.table_thickness - skin_t) / 2.0
    panel_i_per_mm = 2 * (skin_t * skin_centroid**2 + skin_t**3 / 12.0)
    panel_i = panel_i_per_mm * p.table_length
    line_load_n_mm = table_force_n / p.table_half_width
    panel_deflection_mm = (
        line_load_n_mm * p.table_half_width**4 / (8 * 69_000.0 * panel_i)
    )

    pin_area = math.pi * p.desk_lock_pin_diameter**2 / 4.0
    pin_shear_mpa = table_force_n / (2 * 2 * pin_area)
    table = {
        "factored_load_each_n": table_force_n,
        "post_bending_moment_n_m": table_moment_n_mm / 1000.0,
        "post_stress_mpa": pole_stress_mpa,
        "post_deflection_mm": pole_deflection_mm,
        "panel_deflection_mm": panel_deflection_mm,
        "lock_pin_double_shear_mpa": pin_shear_mpa,
    }
    cafe_panel_y = p.table_centre_safety_gap / 2.0 + p.table_half_width / 2.0
    cafe_support_dx = p.cafe_table_x - p.cafe_rotation_clearance_x
    cafe_support_dy = cafe_panel_y - p.table_pole_y
    cafe_centre_lever_mm = math.hypot(cafe_support_dx, cafe_support_dy)
    cafe_far_x = max(
        abs((p.cafe_table_x - p.table_half_width / 2.0) - p.cafe_rotation_clearance_x),
        abs((p.cafe_table_x + p.table_half_width / 2.0) - p.cafe_rotation_clearance_x),
    )
    cafe_far_y = max(
        abs((cafe_panel_y - p.table_length / 2.0) - p.table_pole_y),
        abs((cafe_panel_y + p.table_length / 2.0) - p.table_pole_y),
    )
    cafe_far_corner_lever_mm = math.hypot(cafe_far_x, cafe_far_y)
    cafe_centre_moment_n_m = table_force_n * cafe_centre_lever_mm / 1000.0
    cafe_far_corner_moment_n_m = table_force_n * cafe_far_corner_lever_mm / 1000.0
    cafe_proof_target_n_m = required_proof_target_n_m(table_force_n, cafe_far_corner_lever_mm)
    table.update(
        {
            "cafe_transverse_centre_lever_mm": cafe_centre_lever_mm,
            "cafe_transverse_far_corner_lever_mm": cafe_far_corner_lever_mm,
            "cafe_transverse_centre_moment_n_m": cafe_centre_moment_n_m,
            "cafe_transverse_far_corner_moment_n_m": cafe_far_corner_moment_n_m,
            "cafe_required_proof_target_n_m": cafe_proof_target_n_m,
            "cafe_demonstrated_capacity_n_m": None,
            "cafe_capacity_to_demand_safety_factor": None,
            "cafe_support_status": "UNVERIFIED: requirement only; physical proof and fatigue remain DV-043",
        }
    )
    for check, actual, maximum in (
        ("table_post_stress", pole_stress_mpa, 160.0),
        ("table_post_deflection", pole_deflection_mm, 2.0),
        ("table_panel_deflection", panel_deflection_mm, 3.0),
        ("table_lock_pin_shear", pin_shear_mpa, 150.0),
    ):
        checks.append(
            {"category": "desk", "check": check, "actual": actual, "maximum": maximum, "pass": actual <= maximum}
        )

    # Canopy arm conservative cantilever check. Hinge compliance is a prototype gate.
    arm_section = rectangular_solid_section(p.canopy_arm_width, p.canopy_arm_height)
    rain_force_n = p.canopy_rain_mass * p.gravity * p.canopy_wind_load_factor
    arm_force_each_n = (rain_force_n + structural_wind_force_n) / 2.0
    arm_moment_n_mm = arm_force_each_n * p.canopy_projection
    arm_stress_mpa = arm_moment_n_mm / arm_section["z_mm3"]
    arm_deflection_mm = (
        arm_force_each_n * p.canopy_projection**3 / (3 * 71_700.0 * arm_section["i_mm4"])
    )
    canopy_arm = {
        "rain_force_n": rain_force_n,
        "wind_force_n": structural_wind_force_n,
        "combined_force_each_arm_n": arm_force_each_n,
        "root_moment_each_n_m": arm_moment_n_mm / 1000.0,
        "stress_mpa": arm_stress_mpa,
        "tip_deflection_mm": arm_deflection_mm,
    }
    checks.extend(
        [
            {
                "category": "canopy",
                "check": "canopy_arm_stress",
                "actual_mpa": arm_stress_mpa,
                "maximum_mpa": 250.0,
                "pass": arm_stress_mpa <= 250.0,
            },
            {
                "category": "canopy",
                "check": "canopy_arm_tip_deflection",
                "actual_mm": arm_deflection_mm,
                "maximum_mm": 25.0,
                "pass": arm_deflection_mm <= 25.0,
            },
            {
                "category": "canopy",
                "check": "canopy_drain_pitch",
                "actual_deg": abs(p.canopy_pitch_deg),
                "minimum_deg": 2.0,
                "pass": abs(p.canopy_pitch_deg) >= 2.0,
            },
        ]
    )
    roller_surface_speed_mm_s = math.pi * p.roller_od * p.canopy_roller_rpm / 60.0
    theoretical_retract_time_s = p.canopy_projection / roller_surface_speed_mm_s
    checks.append(
        {
            "category": "canopy",
            "check": "spring_assisted_emergency_retract_time",
            "actual_s": theoretical_retract_time_s,
            "maximum_s": p.canopy_retract_time_target_s,
            "pass": theoretical_retract_time_s <= p.canopy_retract_time_target_s,
        }
    )
    canopy_arm["roller_surface_speed_mm_s"] = roller_surface_speed_mm_s
    canopy_arm["theoretical_retract_time_s"] = theoretical_retract_time_s

    # Motion multiplier load and package checks for the mast actuator.
    moving_names = {
        name
        for name in canopy_parts
        if name.startswith("sensor_beam")
        or name.startswith("canopy_")
        or name.startswith("mast_inner")
    }
    moving_mass = sum(
        canopy_parts[name].mass_kg * getattr(canopy_parts[name], "quantity", 1)
        for name in moving_names
    )
    mast_output_load_n = (moving_mass + p.canopy_rain_mass) * p.gravity * p.canopy_wind_load_factor
    reeving_efficiency = 0.75
    actuator_force_n = mast_output_load_n * p.mast_motion_ratio / reeving_efficiency
    mast = {
        "moving_mass_kg": moving_mass,
        "factored_output_load_n": mast_output_load_n,
        "required_actuator_force_n": actuator_force_n,
        "available_actuator_force_n": p.mast_actuator_rating_n,
        "available_output_stroke_mm": p.mast_actuator_stroke * p.mast_motion_ratio,
        "required_output_stroke_mm": p.mast_stroke,
    }
    checks.extend(
        [
            {
                "category": "mast",
                "check": "mast_actuator_force",
                "actual_n": actuator_force_n,
                "maximum_n": p.mast_actuator_rating_n,
                "pass": actuator_force_n <= p.mast_actuator_rating_n,
            },
            {
                "category": "mast",
                "check": "mast_motion_ratio_stroke",
                "actual_mm": p.mast_actuator_stroke * p.mast_motion_ratio,
                "minimum_mm": p.mast_stroke,
                "pass": p.mast_actuator_stroke * p.mast_motion_ratio >= p.mast_stroke,
            },
            {
                "category": "mast",
                "check": "mast_actuator_cross_section_fit",
                "actual_clearance_mm": (p.mast_inner_depth - 8 - p.mast_actuator_diameter) / 2.0,
                "minimum_clearance_mm": 3.0,
                "pass": (p.mast_inner_depth - 8 - p.mast_actuator_diameter) / 2.0 >= 3.0,
            },
        ]
    )

    # Drawer slide selection and process tolerance stack.
    drawer = {
        "slide_pair_rating_kg": p.drawer_slide_pair_rating_kg,
        "lower_dynamic_equivalent_kg": 20.0 * p.mobile_dynamic_factor,
        "upper_dynamic_equivalent_kg": 15.0 * p.mobile_dynamic_factor,
        "slide_travel_mm": p.drawer_slide_travel,
        "required_travel_mm": 230.0,
        "laptop_slide_travel_mm": p.laptop_slide_travel,
        "laptop_bay_depth_mm": p.laptop_bay_depth,
        "required_bracket_adjustment_each_side_mm": 0.5 + 0.3 + p.drawer_slide_side_tolerance_plus,
        "provided_bracket_adjustment_each_side_mm": 2.0,
    }
    checks.extend(
        [
            {
                "category": "drawer",
                "check": "lower_drawer_dynamic_rating",
                "actual_kg": drawer["lower_dynamic_equivalent_kg"],
                "maximum_kg": p.drawer_slide_pair_rating_kg,
                "pass": drawer["lower_dynamic_equivalent_kg"] <= p.drawer_slide_pair_rating_kg,
            },
            {
                "category": "drawer",
                "check": "upper_drawer_dynamic_rating",
                "actual_kg": drawer["upper_dynamic_equivalent_kg"],
                "maximum_kg": p.drawer_slide_pair_rating_kg,
                "pass": drawer["upper_dynamic_equivalent_kg"] <= p.drawer_slide_pair_rating_kg,
            },
            {
                "category": "drawer",
                "check": "drawer_slide_travel",
                "actual_mm": p.drawer_slide_travel,
                "minimum_mm": 230.0,
                "pass": p.drawer_slide_travel >= 230.0,
            },
            {
                "category": "drawer",
                "check": "laptop_bay_full_access_travel",
                "actual_mm": p.laptop_slide_travel,
                "minimum_mm": p.laptop_bay_depth,
                "pass": p.laptop_slide_travel >= p.laptop_bay_depth,
            },
            {
                "category": "tolerance",
                "check": "drawer_bracket_adjustment",
                "actual_mm": 2.0,
                "minimum_mm": drawer["required_bracket_adjustment_each_side_mm"],
                "pass": 2.0 >= drawer["required_bracket_adjustment_each_side_mm"],
            },
        ]
    )

    return {
        "revision": "E6",
        "assumptions": {
            "occupant_mass_kg": p.occupant_design_mass,
            "cargo_mass_kg": p.cargo_design_mass,
            "mobile_dynamic_factor": p.mobile_dynamic_factor,
            "canopy_auto_retract_threshold_m_s": p.canopy_retract_wind_m_s,
            "canopy_structural_wind_m_s": p.canopy_structural_wind_m_s,
        },
        "scenarios": scenarios,
        "mobility": mobility,
        "wind": wind,
        "desk": table,
        "canopy_arm": canopy_arm,
        "mast": mast,
        "drawer": drawer,
        "analysis_limitations": [
            {
                "id": "ENG-LIM-001",
                "subject": "cafe transverse support capacity",
                "status": "UNVERIFIED",
                "boundary": "The model calculates required moment only; no rail, bearing, lock-pin, joint or fatigue capacity is credited.",
            },
            {
                "id": "ENG-LIM-002",
                "subject": "stability load-case coverage",
                "status": "UNVERIFIED",
                "boundary": "Current automatic cases use centered nominal occupants/cargo; transfer, lean, one-sided load, grade and manoeuvre combinations require DVP/FEA.",
            },
            {
                "id": "ENG-LIM-003",
                "subject": "stopping performance",
                "status": "UNVERIFIED",
                "boundary": "The stopping-distance value is nominal physics, not a measured perception-to-STO-to-mechanical-brake envelope.",
            },
        ],
        "checks": checks,
    }
