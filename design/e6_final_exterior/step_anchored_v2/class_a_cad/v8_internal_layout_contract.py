"""Frozen internal-layout inventory and source-selection contract for E6 V8."""

from __future__ import annotations


FINAL_LAYOUT_SOURCE_DISPOSITIONS = frozenset(
    {"retain_exposed", "conceal_behind_access", "internal_enclosed"}
)

REQUIRED_FULL_LAYOUT_SOURCE_OCCURRENCES = {
    "battery_and_power": (
        "battery_lfp_16s30ah_1p536kwh",
        "power_distribution_unit",
        "safety_backup_battery_24v60wh",
        "battery_safety_cassette",
        "battery_pressure_vent_duct",
        "battery_compartment_temperature_sensor_-150",
        "battery_compartment_temperature_sensor_170",
        "service_battery_disconnect_guarded",
    ),
    "device_bays_and_daily_storage": (
        "drawer_tray_left_upper",
        "drawer_front_left_upper",
        "cots_slide_left_upper_a",
        "cots_slide_left_upper_b",
        "cots_latch_left_upper",
        "device_bay_shock_liner_left",
        "universal_flat_device_keepout_left",
        "drawer_tray_right_upper",
        "drawer_front_right_upper",
        "cots_slide_right_upper_a",
        "cots_slide_right_upper_b",
        "cots_latch_right_upper",
        "device_bay_shock_liner_right",
        "laptop_16in_keepout_right",
        "daily_caddy_liftout_bin_4p9l",
        "daily_caddy_soft_liner",
        "daily_caddy_unpowered_access_lid",
    ),
    "core_equipment_and_service": (
        "compute_core_cartridge",
        "encrypted_data_vault",
        "communications_5g_wifi_uwb_module",
        "drive_imu_controller",
        "occupant_energy_firewall",
        "service_charge_port_guarded",
    ),
}

EXPECTED_DFR5_SOURCE_SOLID_COUNTS = {
    "follow": 180,
    "ride": 176,
    "cafe": 189,
    "focus": 196,
}

# The counts below exclude every source occurrence classified as
# ``replace_surface`` or ``trace_only_retired``.  The controlled daily-caddy
# lid is one of those replacements; its exact final proxy is the A04 hatch.
EXPECTED_FINAL_LAYOUT_SOURCE_SOLID_COUNTS = {
    "follow": 119,
    "ride": 115,
    "cafe": 124,
    "focus": 125,
}

REQUIRED_REPLACED_SOURCE_PROXIES = {
    "daily_caddy_unpowered_access_lid": "A04_daily_caddy_flush_hatch",
}


def required_occurrence_names() -> frozenset[str]:
    """Return the exact explicit battery/equipment/device occurrence set."""

    return frozenset(
        name
        for names in REQUIRED_FULL_LAYOUT_SOURCE_OCCURRENCES.values()
        for name in names
    )


def required_selected_occurrence_names() -> frozenset[str]:
    """Return required source names that must remain in the final underlay."""

    return required_occurrence_names() - frozenset(
        REQUIRED_REPLACED_SOURCE_PROXIES
    )
