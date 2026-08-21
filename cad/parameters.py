from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    # Master envelope and coordinate datums (mm)
    body_length: float = 790.0
    # E6 community baseline: 720 mm is achievable with the current 64 mm tyre
    # envelope while retaining the 620 mm occupant clear width.  A 700 mm
    # stretch target requires a narrower qualified tyre and human trials.
    body_width: float = 720.0
    lower_body_length: float = 790.0
    lower_body_width: float = 560.0
    lower_body_height: float = 280.0
    lower_body_z: float = 275.0
    upper_deck_height: float = 110.0
    upper_deck_z: float = 415.0
    body_x: float = -75.0

    # Chassis and running gear
    frame_length: float = 720.0
    frame_width: float = 510.0
    frame_tube: float = 40.0
    frame_wall: float = 3.0
    frame_z: float = 115.0
    wheel_diameter: float = 250.0
    wheel_width: float = 64.0
    wheel_center_z: float = 125.0
    # The short 560 mm wheelbase reduces four-wheel skid-steer scrub. Its support
    # polygon still clears the occupied acceleration/braking stability targets.
    wheel_x_front: float = -380.0
    wheel_x_rear: float = 180.0
    wheel_y: float = 326.0
    wheel_running_clearance: float = 12.0
    axle_diameter: float = 25.0
    rocker_section: float = 50.0
    rocker_lateral_thickness: float = 10.0
    rocker_wall: float = 5.0
    rocker_articulation_deg: float = 10.0
    rocker_fairing_height: float = 72.0

    # Human interface packaging
    seat_length: float = 470.0
    seat_width: float = 590.0
    seat_height: float = 60.0
    seat_x: float = -75.0
    seat_z: float = 470.0
    seat_usable_depth: float = 420.0
    back_width: float = 590.0
    back_height: float = 520.0
    back_thickness: float = 80.0
    back_hinge_x: float = 160.0
    back_hinge_z: float = 515.0
    back_rake_deg: float = 6.0
    # v37-inspired integrated armrest plan. The height is corrected for ergonomics.
    armrest_x_min: float = -380.0
    armrest_x_chamfer_start: float = 40.0
    armrest_x_max: float = 140.0
    armrest_inner_y: float = 310.0
    armrest_chamfer_y: float = 332.0
    armrest_outer_y: float = 360.0
    armrest_bottom_z: float = 420.0
    armrest_top_z: float = 680.0
    armrest_wall: float = 4.0

    # v37 asymmetric armrest HMI retained as a controlled product feature.
    armrest_display_length: float = 124.0
    armrest_display_width: float = 50.0
    armrest_display_pitch_deg: float = 6.0
    armrest_qi_coil_od: float = 56.0
    armrest_qi_charge_power_w: float = 15.0
    armrest_display_power_w: float = 5.0
    # 54 mm tray centred at 333 mm lands flush with the 360 mm outer edge.
    armrest_hmi_y: float = 333.0

    # v37 rear obstacle-assist pull handle.  This is an unoccupied manual
    # handling aid: the back/mast and footrest must be stowed before extension.
    obstacle_handle_x: float = 245.0
    obstacle_handle_tube_y: float = 245.0
    obstacle_handle_outer_od: float = 20.0
    obstacle_handle_inner_od: float = 15.0
    obstacle_handle_wall: float = 2.0
    obstacle_handle_deck_z: float = 470.0
    obstacle_handle_extended_top_z: float = 1350.0
    obstacle_handle_crossbar_width: float = 540.0
    obstacle_handle_tilt_deg: float = 8.0

    # v37-inspired upright-fold table, corrected from 805 mm to a neutral-work range.
    # One 430 x 270 panel is two 430 x 134.5 x 12 mm rigid half-leaves with a
    # 1 mm fold seam.  The nominal folded material/hinge pack is 430 x 30 x
    # 139 mm; 432 x 32 x 141 mm is reserved as the maximum manufacturing
    # envelope.  A state-only box may not substitute for these occurrences.
    table_length: float = 430.0
    table_half_width: float = 270.0
    table_thickness: float = 12.0
    table_rigid_half_leaf_width: float = 134.5
    table_fold_seam: float = 1.0
    table_surface_z: float = 705.0
    table_stowed_height: float = 139.0
    table_stowed_thickness: float = 30.0
    table_stowed_max_length: float = 432.0
    table_stowed_max_thickness: float = 32.0
    table_stowed_max_height: float = 141.0
    table_stowed_y: float = 343.0
    table_stowed_x: float = -115.0
    armrest_top_lid_open_angle_deg: float = 105.0
    table_x: float = -405.0
    table_pole_y: float = 300.0
    table_centre_safety_gap: float = 12.0
    table_pole_od: float = 32.0
    table_pole_wall: float = 2.5

    # Café uses one 430 x 270 panel as a 430-wide x 270-deep transverse surface.
    # It first moves to the clearance datum, rotates about its own centre (so
    # the bearing stays below the centre of mass), then returns to the ergonomic
    # final X position while retaining one socially open side.
    cafe_table_x: float = -350.0
    cafe_rotation_clearance_x: float = -430.0
    cafe_rotation_deg: float = 90.0
    cafe_turntable_od: float = 76.0
    cafe_turntable_id: float = 34.0
    cafe_lock_pin_diameter: float = 10.0
    cafe_underdeck_spine_length: float = 220.0

    # Manual positive-lock foot support.  Ride requires DEPLOYED_LOCKED.
    # Parked Cafe/Focus default to STOWED so both feet may use the floor, while
    # the same physical assembly can be opened on request after a clear-sweep
    # check.  These dimensions are one invariant production definition in
    # both poses, not separate stowed/deployed surrogate panels.
    footrest_length: float = 210.0
    footrest_width: float = 500.0
    footrest_thickness: float = 10.0
    footrest_support_section: float = 30.0
    footrest_support_wall: float = 3.0
    footrest_lock_pin_diameter: float = 8.0
    footrest_deployed_x: float = -605.0
    footrest_deployed_z: float = 90.0
    footrest_top_adjustment_min: float = 70.0
    footrest_top_adjustment_max: float = 130.0
    footrest_fore_aft_adjustment: float = 80.0

    # E4 provisional 95th-percentile/clothed seated keep-outs. These are design
    # envelopes, not claims about the final accommodated population.
    occupant_pelvis_depth: float = 230.0
    occupant_pelvis_width: float = 520.0
    occupant_pelvis_height: float = 160.0
    occupant_torso_depth: float = 270.0
    occupant_torso_width: float = 560.0
    occupant_torso_height: float = 450.0
    occupant_head_diameter: float = 230.0
    occupant_table_body_clearance: float = 75.0
    occupant_thigh_clearance: float = 75.0
    occupant_armrest_side_clearance: float = 20.0
    restraint_anchor_pin_diameter: float = 10.0
    restraint_design_deceleration_g: float = 10.0

    # E4 occupied mobility targets: low-speed, four-hub differential drive.
    occupied_speed_max_m_s: float = 1.67
    community_default_speed_m_s: float = 1.00
    # CAFE_LOCKED is a parked use state: deployed furniture must revoke all
    # traction torque. Any positioning motion belongs to a separate transition
    # state that is not represented or released by this model.
    cafe_creep_speed_m_s: float = 0.0
    follow_speed_max_m_s: float = 0.80
    follow_gap_nominal_m: float = 1.20
    follow_target_loss_stop_s: float = 0.50
    zero_turn_tire_speed_m_s: float = 0.30
    zero_turn_ramp_time_s: float = 2.0
    hub_motor_peak_torque_n_m: float = 70.0
    hub_motor_continuous_torque_n_m: float = 25.0
    power_off_brake_holding_torque_n_m: float = 30.0
    dry_traction_coefficient: float = 0.70
    rated_vertical_obstacle_mm: float = 50.0
    conditional_vertical_obstacle_mm: float = 60.0
    occupied_acceleration_max_g: float = 0.10
    occupied_braking_max_g: float = 0.25
    occupied_cross_slope_max_deg: float = 6.0
    turning_circle_design_max_mm: float = 1450.0
    elevator_lobby_turning_space_mm: float = 1500.0

    # E4 electrical architecture design envelope.  These values define the
    # pack/PDU interfaces and automatic checks; cell, BMS and converter part
    # numbers remain supplier-selection gates until prototype thermal tests.
    battery_series_cells: int = 16
    battery_nominal_voltage_v: float = 51.2
    battery_full_voltage_v: float = 58.4
    battery_capacity_ah: float = 30.0
    # Energy allocation is additive: 80% is available for the advertised
    # mission, 15% is a separate stranded-recovery reserve and the final 5% is
    # an unallocated bottom buffer. The reserve is not included in runtime.
    battery_usable_fraction: float = 0.80
    battery_emergency_reserve_fraction: float = 0.15
    battery_continuous_current_a: float = 120.0
    battery_peak_current_a: float = 200.0
    battery_main_fuse_a: float = 150.0
    drive_electrical_efficiency: float = 0.85
    dc_dc_48_24_rating_w: float = 750.0
    dc_dc_48_12_rating_w: float = 240.0
    usb_c_pd_port_rating_w: float = 140.0
    usb_c_pd_closed_bay_limit_w: float = 100.0
    # AC moves to the stationary dock/professional accessory.  The core vehicle
    # is USB-C first and carries no inverter or exposed mains domain.
    parked_ac_inverter_rating_w: float = 0.0
    optional_dock_ac_rating_w: float = 600.0
    shore_charger_rating_w: float = 1500.0
    safety_backup_energy_wh: float = 60.0
    mast_auxiliary_budget_w: float = 60.0
    electronics_heat_design_w: float = 210.0
    electronics_air_rise_target_c: float = 12.0
    thermal_airflow_margin: float = 1.50

    # Sensor beam and telescopic mast
    beam_x: float = 310.0
    beam_width: float = 320.0
    beam_depth: float = 80.0
    beam_height: float = 64.0
    beam_wall: float = 6.0
    # In ride/cafe states the slim sensor bar sits at the backrest shoulder
    # line.  It rises only for an explicitly requested focus/creator state.
    beam_stowed_z: float = 1040.0
    mast_outer_x: float = 310.0
    mast_outer_width: float = 136.0
    mast_outer_depth: float = 70.0
    mast_outer_height: float = 300.0
    mast_inner_width: float = 120.0
    mast_inner_depth: float = 54.0
    mast_stroke: float = 420.0
    mast_overlap_deployed: float = 120.0
    # Separate transport hinge from the backrest datum.  Lowering this axis by
    # 6 mm creates a real production reserve below the 700 mm travel target.
    mast_fold_hinge_z: float = 509.0

    # Hidden canopy
    canopy_projection: float = 800.0
    canopy_main_width: float = 380.0
    canopy_total_width: float = 620.0
    canopy_fabric_thickness: float = 0.8
    canopy_pitch_deg: float = -3.0
    canopy_arm_segment: float = 400.0
    canopy_arm_width: float = 45.0
    canopy_arm_height: float = 20.0
    canopy_arm_y: float = 185.0
    roller_od: float = 40.0
    roller_id: float = 34.0
    roller_length: float = 380.0
    front_rail_depth: float = 22.0
    front_rail_height: float = 18.0
    outdoor_package_cassette_height: float = 104.0

    # General engineering clearances
    machined_clearance: float = 0.5
    formed_panel_clearance: float = 1.5
    moving_clearance: float = 3.0

    # E4 provisional design loads and safety targets
    gravity: float = 9.80665
    occupant_design_mass: float = 150.0
    cargo_design_mass: float = 25.0
    mobile_dynamic_factor: float = 2.0
    desk_design_load_mass_each: float = 30.0
    desk_lock_pin_diameter: float = 8.0
    canopy_retract_wind_m_s: float = 7.0
    canopy_structural_wind_m_s: float = 20.0
    canopy_drag_coefficient: float = 1.5
    canopy_wind_load_factor: float = 1.5
    air_density_kg_m3: float = 1.225
    anti_tip_safety_factor: float = 1.5
    canopy_rain_mass: float = 15.0
    canopy_roller_rpm: float = 60.0
    canopy_retract_time_target_s: float = 8.0
    canopy_motor_torque_n_m: float = 2.0

    # E4 COTS interface envelopes
    drawer_slide_length: float = 250.0
    drawer_slide_travel: float = 254.0
    laptop_slide_length: float = 300.0
    laptop_slide_travel: float = 305.0
    # Storage datums are centred between the wheel contact envelopes.  The
    # lower drawer is deliberately shorter than the visual-concept version so
    # it retains clearance at both rocker articulation limits, not only at the
    # nominal ride height.
    lower_drawer_length: float = 260.0
    lower_drawer_x: float = -100.0
    lower_drawer_z: float = 260.0
    lower_drawer_depth: float = 240.0
    lower_drawer_height: float = 88.0
    lower_drawer_front_height: float = 96.0
    upper_drawer_length: float = 440.0
    upper_drawer_x: float = -20.0
    upper_drawer_z: float = 364.0
    upper_drawer_height: float = 88.0
    upper_drawer_front_height: float = 80.0
    drawer_dynamic_clearance: float = 15.0
    laptop_bay_depth: float = 290.0
    laptop_envelope_length: float = 365.0
    laptop_envelope_depth: float = 255.0
    laptop_envelope_height: float = 28.0
    drawer_slide_thickness: float = 12.7
    drawer_slide_height: float = 45.7
    drawer_slide_pair_rating_kg: float = 45.5
    drawer_slide_side_tolerance_plus: float = 0.8
    drawer_latch_length: float = 77.0
    drawer_latch_width: float = 36.0
    drawer_latch_height: float = 20.0
    mast_guide_pad_thickness: float = 1.0
    mast_actuator_stroke: float = 240.0
    mast_motion_ratio: float = 2.0
    mast_actuator_built_in: float = 410.0
    mast_actuator_diameter: float = 40.0
    mast_actuator_rating_n: float = 2500.0

    # Product-definition envelope for unoccupied travel mode.  Occupant space
    # remains the priority; these limits preserve 800 mm-door access and a
    # practical 900 mm transport depth without forcing the armrests inward.
    travel_length_max: float = 900.0
    travel_width_max: float = 760.0
    travel_height_max: float = 700.0
    travel_length_production_reserve: float = 20.0
    travel_width_production_reserve: float = 10.0
    travel_height_production_reserve: float = 10.0


P = Params()
