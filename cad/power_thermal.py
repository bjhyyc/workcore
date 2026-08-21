from __future__ import annotations

import math


COPPER_RESISTIVITY_OHM_MM2_M = 0.0175
AIR_DENSITY_KG_M3 = 1.20
AIR_HEAT_CAPACITY_J_KG_K = 1005.0


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _voltage_drop(voltage_v: float, current_a: float, round_trip_m: float, section_mm2: float) -> dict:
    resistance = COPPER_RESISTIVITY_OHM_MM2_M * round_trip_m / section_mm2
    drop = current_a * resistance
    return {
        "current_a": current_a,
        "round_trip_length_m": round_trip_m,
        "copper_section_mm2": section_mm2,
        "resistance_ohm": _round(resistance, 6),
        "drop_v": _round(drop),
        "drop_percent": _round(100.0 * drop / voltage_v),
    }


def analyze(configs: dict, p) -> dict:
    wheel_radius_m = p.wheel_diameter / 2000.0
    wheel_speed_rad_s = p.occupied_speed_max_m_s / wheel_radius_m
    traction_continuous_mechanical_w = (
        4.0 * p.hub_motor_continuous_torque_n_m * wheel_speed_rad_s
    )
    traction_peak_mechanical_w = 4.0 * p.hub_motor_peak_torque_n_m * wheel_speed_rad_s
    traction_continuous_electrical_w = traction_continuous_mechanical_w / p.drive_electrical_efficiency
    traction_peak_electrical_w = traction_peak_mechanical_w / p.drive_electrical_efficiency

    mast_loads = {
        "4k_camera": 10.0,
        "depth_or_ir_camera": 12.0,
        "two_optional_fill_lights": 16.0,
        "microphone_array": 5.0,
        "environment_and_status_sensors": 4.0,
        "mast_network_bridge": 5.0,
        "design_margin": 8.0,
    }
    mast_total_w = sum(mast_loads.values())
    armrest_hmi_loads = {
        "left_status_display": p.armrest_display_power_w,
        "left_qi2_wireless_charging": p.armrest_qi_charge_power_w,
        "joystick_and_authorization": 3.0,
        "design_margin": 7.0,
    }
    armrest_hmi_total_w = sum(armrest_hmi_loads.values())
    auxiliary_peak_w = (
        2.0 * p.usb_c_pd_port_rating_w
        + p.parked_ac_inverter_rating_w
        + 100.0  # compute core including carrier/storage/network
        + 35.0  # 5G/Wi-Fi/UWB communications burst; no satellite domain
        + mast_total_w
        + armrest_hmi_total_w
        + 300.0  # actuator, brake release, pumps/fans and transient margin
    )
    mobile_peak_w = traction_peak_electrical_w + auxiliary_peak_w - p.parked_ac_inverter_rating_w
    mobile_peak_current_a = mobile_peak_w / p.battery_nominal_voltage_v
    continuous_system_w = traction_continuous_electrical_w + 720.0
    continuous_system_current_a = continuous_system_w / p.battery_nominal_voltage_v

    nominal_energy_wh = p.battery_nominal_voltage_v * p.battery_capacity_ah
    mission_energy_wh = nominal_energy_wh * p.battery_usable_fraction
    reserve_energy_wh = nominal_energy_wh * p.battery_emergency_reserve_fraction
    bottom_buffer_energy_wh = nominal_energy_wh - mission_energy_wh - reserve_energy_wh
    mission_loads = {
        "quiet_presence": 160.0,
        "community_workday": 300.0,
        "focus_single_device": 380.0,
        "mixed_mobility": 650.0,
        "aggressive_continuous_drive": 1800.0,
    }
    mission_profiles = {
        name: {
            "average_load_w": watts,
            "estimated_runtime_h": _round(mission_energy_wh / watts, 2),
        }
        for name, watts in mission_loads.items()
    }

    harness = {
        "battery_to_pdu_main": {
            "bus": "48V_TRACTION",
            "protection_a": p.battery_main_fuse_a,
            **_voltage_drop(p.battery_nominal_voltage_v, 120.0, 1.2, 35.0),
            "routing": "short central protected tunnel; service disconnect before contactors",
        },
        "four_motor_branches_each": {
            "bus": "48V_TRACTION",
            "protection_a": 40.0,
            **_voltage_drop(p.battery_nominal_voltage_v, 22.0, 3.0, 6.0),
            "routing": "left/right sill channels; sealed wheel-end connector and drip loop",
        },
        "24v_auxiliary_trunk": {
            "bus": "24V_AUX",
            "protection_a": 35.0,
            **_voltage_drop(24.0, 30.0, 4.0, 6.0),
            "routing": "rear service spine; star branches to mast, seats and drawers",
        },
        "24v_mast_branch": {
            "bus": "24V_MAST",
            "protection_a": 7.5,
            **_voltage_drop(24.0, mast_total_w / 24.0, 4.0, 1.5),
            "routing": "telescopic energy chain with shielded Cat6A and separate safety pair",
        },
        "12v_armrest_hmi_branch": {
            "bus": "12V_HMI",
            "protection_a": 3.0,
            **_voltage_drop(12.0, armrest_hmi_total_w / 12.0, 3.0, 0.75),
            "routing": "separate left display/Qi and right joystick branches; flex loops follow service lids",
        },
    }

    required_airflow_m3_s = p.electronics_heat_design_w / (
        AIR_DENSITY_KG_M3 * AIR_HEAT_CAPACITY_J_KG_K * p.electronics_air_rise_target_c
    )
    required_airflow_cfm = required_airflow_m3_s * 2118.88 * p.thermal_airflow_margin
    thermal = {
        "zones": {
            "battery": {
                "architecture": "sealed structural cassette, underbody conduction plate, outward pressure vent; no shared occupant-air path",
                "controls_c": {
                    "charge_inhibit_below": 0.0,
                    "charge_derate_above": 40.0,
                    "charge_inhibit_above": 45.0,
                    "drive_derate_above": 50.0,
                    "pack_shutdown_above": 55.0,
                },
                "heater_w": 100.0,
                "note": "provisional until selected cell and BMS limits are verified",
            },
            "electronics": {
                "design_heat_w": p.electronics_heat_design_w,
                "target_air_rise_c": p.electronics_air_rise_target_c,
                "required_airflow_with_margin_cfm": _round(required_airflow_cfm, 1),
                "implementation": "candidate dual 30-CFM monitored blowers and sealed recirculation plenum",
                "heat_rejection_status": "UNVERIFIED: airflow is an internal mixing target; heat-exchanger UA, external airflow and fan working points are not demonstrated",
            },
            "personal_and_compute_bays": {
                "closed_charge_limit_each_w": p.usb_c_pd_closed_bay_limit_w,
                "open_charge_limit_each_w": p.usb_c_pd_port_rating_w,
                "implementation": "one NTC and one tach-monitored exhaust fan per bay; filtered labyrinth intake; charge disabled on fan or sensor fault",
            },
            "left_armrest_qi": {
                "rated_output_w": p.armrest_qi_charge_power_w,
                "controls": "foreign-object detection, presence sensing and independent coil temperature cutoff",
                "interlock": "phone present inhibits left service-lid opening; overtemperature stops charging without affecting drive safety",
            },
            "condensation": {
                "dewpoint_margin_c": 3.0,
                "implementation": "humidity/dewpoint control, drain path and conformal-coated low-voltage boards",
            },
        }
    }

    ideal_charge_h = mission_energy_wh / (p.shore_charger_rating_w * 0.92)
    energy = {
        "chemistry": "16S LiFePO4 supplier-selected pack",
        "nominal_voltage_v": p.battery_nominal_voltage_v,
        "full_voltage_v": p.battery_full_voltage_v,
        "capacity_ah": p.battery_capacity_ah,
        "nominal_energy_wh": _round(nominal_energy_wh),
        "mission_energy_wh": _round(mission_energy_wh),
        "usable_energy_wh": _round(mission_energy_wh),
        "emergency_reserve_energy_wh": _round(reserve_energy_wh),
        "bottom_buffer_energy_wh": _round(bottom_buffer_energy_wh),
        "allocation_policy": "mission + emergency reserve + bottom buffer = nominal; advertised runtime uses mission energy only",
        "continuous_current_a": p.battery_continuous_current_a,
        "peak_current_a": p.battery_peak_current_a,
        "main_fuse_a": p.battery_main_fuse_a,
        "shore_charger_w": p.shore_charger_rating_w,
        "ideal_10_to_90_charge_h": _round(ideal_charge_h, 2),
        "charge_target_including_taper_h": 1.2,
        "safety_backup_wh": p.safety_backup_energy_wh,
    }

    checks = [
        {
            "category": "power",
            "check": "battery_peak_current_margin",
            "actual_a": _round(mobile_peak_current_a),
            "maximum_a": p.battery_peak_current_a,
            "pass": mobile_peak_current_a <= p.battery_peak_current_a,
        },
        {
            "category": "power",
            "check": "battery_continuous_current_margin",
            "actual_a": _round(continuous_system_current_a),
            "maximum_a": p.battery_continuous_current_a,
            "pass": continuous_system_current_a <= p.battery_continuous_current_a,
        },
        {
            "category": "power",
            "check": "main_fuse_above_continuous_below_pack_peak",
            "continuous_a": _round(continuous_system_current_a),
            "fuse_a": p.battery_main_fuse_a,
            "pack_peak_a": p.battery_peak_current_a,
            "pass": continuous_system_current_a < p.battery_main_fuse_a < p.battery_peak_current_a,
        },
        {
            "category": "power",
            "check": "mast_power_budget",
            "actual_w": mast_total_w,
            "maximum_w": p.mast_auxiliary_budget_w,
            "pass": mast_total_w <= p.mast_auxiliary_budget_w,
        },
        {
            "category": "power",
            "check": "dual_usb_c_pd_capacity",
            "actual_w": 2.0 * p.usb_c_pd_port_rating_w,
            "minimum_w": 280.0,
            "pass": 2.0 * p.usb_c_pd_port_rating_w >= 280.0,
        },
        {
            "category": "power",
            "check": "no_onboard_mains_inverter",
            "actual_w": p.parked_ac_inverter_rating_w,
            "maximum_w": 0.0,
            "pass": p.parked_ac_inverter_rating_w == 0.0,
        },
        {
            "category": "power",
            "check": "optional_stationary_dock_ac_capacity",
            "actual_w": p.optional_dock_ac_rating_w,
            "minimum_w": 600.0,
            "pass": p.optional_dock_ac_rating_w >= 600.0,
        },
        {
            "category": "power",
            "check": "armrest_display_and_qi_power_budget",
            "actual_w": armrest_hmi_total_w,
            "maximum_w": 36.0,
            "pass": armrest_hmi_total_w <= 36.0,
        },
        {
            "category": "thermal",
            "check": "electronics_internal_airflow_nominal_budget",
            "actual_cfm": 60.0,
            "minimum_cfm": _round(required_airflow_cfm, 1),
            "scope": "internal air-mixing target only; does not validate heat rejection to ambient",
            "pass": 60.0 >= required_airflow_cfm,
        },
        {
            "category": "energy",
            "check": "battery_energy_allocation_fraction",
            "actual_fraction": p.battery_usable_fraction + p.battery_emergency_reserve_fraction,
            "maximum_fraction": 1.0,
            "pass": p.battery_usable_fraction + p.battery_emergency_reserve_fraction <= 1.0,
        },
    ]
    for name, circuit in harness.items():
        checks.append(
            {
                "category": "harness",
                "check": f"voltage_drop:{name}",
                "actual_percent": circuit["drop_percent"],
                "maximum_percent": 3.0,
                "pass": circuit["drop_percent"] <= 3.0,
            }
        )

    return {
        "revision": "E6-PWR1",
        "status": "engineering design envelope; supplier and prototype validation required",
        "sources": {
            "usb_pd": "https://www.usb.org/usb-charger-pd",
            "macbook_pro": "https://www.apple.com/macbook-pro/specs/",
            "jetson_orin": "https://www.nvidia.com/content/dam/en-zz/Solutions/gtcf21/jetson-orin/nvidia-jetson-agx-orin-technical-brief.pdf",
            "qi2": "https://www.wirelesspowerconsortium.com/standards/qi-wireless-charging/",
            "poe": "https://ethernetalliance.org/wp-content/uploads/2022/10/PD-Design-for-Conformance-and-Interoperability_07AUG22.pdf",
        },
        "traction": {
            "wheel_speed_rad_s": _round(wheel_speed_rad_s),
            "continuous_mechanical_w": _round(traction_continuous_mechanical_w),
            "continuous_electrical_w": _round(traction_continuous_electrical_w),
            "peak_mechanical_w": _round(traction_peak_mechanical_w),
            "peak_electrical_w": _round(traction_peak_electrical_w),
            "mobile_system_peak_w": _round(mobile_peak_w),
            "mobile_system_peak_current_a": _round(mobile_peak_current_a),
        },
        "mast_loads_w": mast_loads,
        "armrest_hmi_loads_w": armrest_hmi_loads,
        "energy": energy,
        "mission_profiles": mission_profiles,
        "distribution": {
            "48v_traction": "battery -> 150A fuse -> service disconnect -> precharge/dual contactors -> four individually fused motor controllers",
            "48v_aux": "separate contactor -> 48/24V 750W and 48/12V 240W isolated converters",
            "device_power": "dual 140W USB-C PD; 100W closed-bay derate; no onboard mains; optional stationary dock provides 600W AC",
            "armrest_hmi": "separate 12V branch for left status display/Qi2 and right joystick/authorization key",
            "mast": "24V fused branch plus managed Ethernet/PoE data path; safety interlock pair remains independent",
            "backup": "60Wh independent safety rail for controller, communications and emergency lighting",
        },
        "evidence_limitations": [
            {
                "id": "PWR-LIM-001",
                "status": "UNVERIFIED",
                "subject": "ambient heat rejection",
                "required_evidence": "heat-exchanger UA and pressure drop, fan P-Q working point, 40 C/blocked-filter/single-fan tests and component derating",
            },
            {
                "id": "PWR-LIM-002",
                "status": "UNVERIFIED",
                "subject": "battery worst-case power and thermal envelope",
                "required_evidence": "minimum-voltage, cold, aged-pack, cell I2R heating, venting and protection-coordination tests",
            },
        ],
        "harness": harness,
        "thermal": thermal,
        "release_gates": [
            "select cell/BMS and verify 120A continuous, 200A short peak, propagation and pressure-vent behavior",
            "complete ISO 16750-style electrical/environmental validation and applicable mobility-device compliance review",
            "measure heat rejection at 40C ambient with the personal and compute bays at their closed-bay limits",
            "thermal-cycle mast and drawer harnesses through full life with minimum bend radius at every state",
            "perform conducted/radiated EMC testing with cameras and microphones operating during four-motor zero-turn",
            "verify Qi2 FOD, coil/phone temperature, wet contamination and phone-present lid interlock across all CMF materials",
        ],
        "checks": checks,
    }
