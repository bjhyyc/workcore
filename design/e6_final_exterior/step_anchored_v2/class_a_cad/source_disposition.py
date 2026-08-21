"""Strict source-occurrence disposition ledger for the four controlled E6 states.

This module closes the presentation-policy gap identified as functional gate
V3 P0-11.  It reads the *actual* geometry names from each controlled GLB and
requires every ``(state, geometry-name)`` occurrence to resolve to exactly one
of five dispositions:

``retain_exposed``
    The controlled item is itself a final contact, rolling or weather surface.
``replace_surface``
    The prototype exterior is suppressed only because named A01--A10 final
    surface proxies take its place.
``conceal_behind_access``
    The controlled item remains physically present behind a named final door
    and a named external/manual release.
``internal_enclosed``
    The item is a module, mechanism or keep-out which is wholly enclosed by
    named A01--A10 responsibility shells.
``trace_only_retired``
    The controlled occurrence belongs to a prototype mechanism deleted from
    the production configuration.  It remains only in the immutable trace
    underlay and has no production proxy, access chain or render allowlist.

There is deliberately no fallback to ``internal_enclosed``.  A new or renamed
controlled occurrence raises :class:`UnknownOccurrenceError` until its design
responsibility is explicitly reviewed here.

The classification functions are pure and importable by the builder and
validator.  GLB reading and QA-file writing are kept in separate helpers so an
import has no filesystem side effects.

This ledger proves semantic ownership and proxy-name completeness only.  It
cannot prove a rigid transform, physical enclosure, sightline or dry clearance;
the independent Class-A validator and V8 release gates must verify those facts
from the final B-Reps.  In particular, an ``internal_enclosed`` label never
authorises a source occurrence to be moved to an invented service-core pose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence


Disposition = Literal[
    "retain_exposed",
    "replace_surface",
    "conceal_behind_access",
    "internal_enclosed",
    "trace_only_retired",
]

DISPOSITIONS: tuple[Disposition, ...] = (
    "retain_exposed",
    "replace_surface",
    "conceal_behind_access",
    "internal_enclosed",
    "trace_only_retired",
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_QA_DIR = SCRIPT_DIR.parent / "qa"

CONTROLLED_GLBS: Mapping[str, str] = {
    "follow": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_follow.glb",
    "ride": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_ride.glb",
    "cafe": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_cafe.glb",
    "focus": "design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_focus.glb",
}

A07_MECHANISM_ENCLOSURES_BY_STATE: Mapping[str, tuple[str, ...]] = {
    "follow": (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
        "A06_backrest_weather_shell",
    ),
    "ride": (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
    ),
    "cafe": (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
    ),
    "focus": (
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
    ),
}


class SourceDispositionError(RuntimeError):
    """Base exception for a non-auditable source disposition."""


class UnknownOccurrenceError(SourceDispositionError):
    """Raised when no explicit policy owns a controlled source occurrence."""


class DuplicateDispositionError(SourceDispositionError):
    """Raised when more than one policy tries to own one source occurrence."""


@dataclass(frozen=True)
class SourceDisposition:
    """One auditable controlled-GLB occurrence and its final design owner."""

    state: str
    source_glb: str
    source_occurrence: str
    disposition: Disposition
    rule_id: str
    rationale: str
    proxy_names: tuple[str, ...] = ()
    access_door: str | None = None
    external_release: str | None = None
    enclosure_proxies: tuple[str, ...] = ()
    retain_allowlist: bool = False
    release_integrated_with_door: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return self.state, self.source_occurrence

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _Decision:
    disposition: Disposition
    rule_id: str
    rationale: str
    proxy_names: tuple[str, ...] = ()
    access_door: str | None = None
    external_release: str | None = None
    enclosure_proxies: tuple[str, ...] = ()
    retain_allowlist: bool = False
    release_integrated_with_door: bool = False


def _state_checked(state: str) -> str:
    state = state.lower().strip()
    if state not in CONTROLLED_GLBS:
        raise ValueError(f"Unknown controlled E6 state: {state!r}")
    return state


def _side_from_name(name: str) -> str:
    """Return the controlled left/right token, including signed occurrences."""

    if "_left" in name or name.endswith("_-1"):
        return "left"
    if "_right" in name or name.endswith("_+1"):
        return "right"
    raise SourceDispositionError(f"Cannot resolve a side for {name!r}")


def _retain_policy(state: str, name: str) -> _Decision | None:
    if name.startswith("tyre_"):
        return _Decision(
            "retain_exposed",
            "retain.rolling.tyre",
            f"{name} is the controlled rolling/contact surface; duplicating it with cosmetic CAD would invalidate the tyre envelope.",
            retain_allowlist=True,
        )
    if name in {
        "travel_front_tpe_water_lip",
        "travel_hinge_local_weather_bridge",
        "travel_side_tpe_seal_drain_left",
        "travel_side_tpe_seal_drain_right",
    }:
        return _Decision(
            "internal_enclosed",
            "internal.weather_seal.follow",
            (
                f"{name} remains a real TPE sealing/drain interface in Follow, "
                "but it sits below the conserved trapezoidal backrest perimeter "
                "and behind the fixed-body shoulder labyrinth.  The water path "
                "is preserved in the layout/QA assembly without reading as an "
                "extra strip or second moving cover in the final exterior view."
            ),
            enclosure_proxies=(
                "A06_backrest_weather_shell",
                "A04_open_u_seat_pan_ring",
                "A05_armrest_table_bay_shell_left",
                "A05_armrest_table_bay_shell_right",
            ),
        )
    return None


def _replace_policy(state: str, name: str) -> _Decision | None:
    """Explicit prototype-surface to final-surface bindings."""

    if name == "seat_cushion_envelope":
        return _Decision(
            "replace_surface",
            "replace.human_contact.seat_cushion",
            "The controlled object is a packaging envelope, not a released Class-A soft surface; it is replaced inside the same hardpoint box by the crowned A04 contact island and concealed by the conserved Follow overlap skirt when closed.",
            ("A04_seat_cushion_contact_island",),
        )

    if name == "lower_body_enclosure":
        return _Decision(
            "replace_surface",
            "replace.lower_body.complete_skin",
            "The monolithic prototype lower enclosure is removed from presentation only after its front, sides, belly and rear are assigned to final skin modules.",
            (
                "A01_front_nose_shell",
                "A02_main_side_shell_left",
                "A02_main_side_shell_right",
                "A04_underseat_belly_closeout",
                "A10_rear_service_surround",
            ),
        )
    if name == "upper_deck_panel":
        return _Decision(
            "replace_surface",
            "replace.upper_deck.seat_ring",
            "The prototype upper deck surface is superseded by the open-U seat-pan ring while the controlled seat datum remains unchanged.",
            ("A04_open_u_seat_pan_ring",),
        )
    if name.startswith("wheel_arch_side_fairing_"):
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.wheel_arch.continuous_belt",
            f"The prototype {side} wheel-arch plate is superseded by one continuous A03 side-and-crown belt with an axis-height lower-tyre opening, body-colour end returns, moving hub caps and fixed-edge flexible diaphragms.",
            (
                f"A03_continuous_wheel_belt_shell_{side}",
                f"A03_body_colour_wheel_end_return_skin_front_{side}",
                f"A03_body_colour_wheel_end_return_skin_rear_{side}",
                f"A03_wheel_end_service_cap_front_{side}",
                f"A03_wheel_end_service_cap_rear_{side}",
                f"A03_wheel_end_motion_gaiter_front_{side}",
                f"A03_wheel_end_motion_gaiter_rear_{side}",
                f"A03_rocker_pivot_service_cap_{side}",
            ),
        )

    for token in ("base_shell", "shell", "lid"):
        prefix = f"armrest_{token}_"
        if name.startswith(prefix):
            side = _side_from_name(name)
            proxy = (
                f"A05_armrest_touch_lid_{side}"
                if token == "lid"
                else f"A05_armrest_table_bay_shell_{side}"
            )
            return _Decision(
                "replace_surface",
                f"replace.armrest.{token}",
                f"The prototype {side} armrest {token.replace('_', ' ')} gives way to the continuous final A05 wing surface.",
                (proxy,),
            )
    if name == "armrest_transfer_positive_lock_right":
        return _Decision(
            "trace_only_retired",
            "trace.retired_transfer_lock.fixed_armrest_configuration",
            "The controlled transfer lock belongs to the deleted side-opening prototype and remains only in the immutable trace underlay; it is absent from the fixed-armrest production BOM and final render.",
        )

    if name == "backrest_cushion_envelope":
        return _Decision(
            "replace_surface",
            "replace.backrest.contact_pad",
            "The prototype cushion envelope is represented by the final removable 3D-knit contact panel on the unchanged backrest stack.",
            ("A06_backrest_contact_panel",),
        )
    if name == "backrest_rear_cosmetic_shell":
        return _Decision(
            "replace_surface",
            "replace.backrest.weather_shell",
            "The prototype rear cosmetic plate is superseded by the final A06 weather shell around the conserved hinge and backrest volume.",
            ("A06_backrest_weather_shell",),
        )

    if name == "follow_front_tactile_bumper_membrane":
        return _Decision(
            "replace_surface",
            "replace.perception.tactile_bumper",
            "The released tactile membrane datum is expressed by the replaceable final bumper skin at the foremost A01 surface.",
            ("A01_front_tactile_bumper_skin",),
        )
    if name in {"follow_front_tof_left_window", "follow_front_tof_right_window"}:
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.perception.front_tof_window",
            f"The prototype {side} ToF pane is suppressed only because a named flush final optical window and carrier preserve its datum and sightline.",
            (f"A01_front_{side}_tof_window", "A01_perception_horizon_carrier"),
        )
    if name == "follow_leg_scanner_window":
        return _Decision(
            "replace_surface",
            "replace.perception.leg_scanner_window",
            "The prototype leg-scanner pane is replaced by the dedicated flush A01 window in the continuous perception carrier.",
            ("A01_front_leg_scanner_window", "A01_perception_horizon_carrier"),
        )
    if name.startswith("follow_cliff_ir_window_"):
        suffix = name.removeprefix("follow_cliff_ir_window_")
        return _Decision(
            "replace_surface",
            "replace.perception.cliff_ir_window",
            f"The controlled {suffix.replace('_', ' ')} downward IR pane has a one-to-one final window and bezel; optical egress remains a separate hard gate.",
            (f"A02_cliff_ir_window_{suffix}", f"A02_cliff_ir_bezel_{suffix}"),
        )
    if name.startswith("follow_side_ultrasonic_face_"):
        suffix = name.removeprefix("follow_side_ultrasonic_face_")
        return _Decision(
            "replace_surface",
            "replace.perception.side_ultrasonic_face",
            f"The controlled {suffix.replace('_', ' ')} transducer face is replaced by its named flush final membrane in A02.",
            (f"A02_side_ultrasonic_face_{suffix}",),
        )
    if name.startswith("follow_voice_acoustic_slot_"):
        suffix = name.removeprefix("follow_voice_acoustic_slot_")
        return _Decision(
            "replace_surface",
            "replace.acoustic.lower_voice_slot",
            f"The prototype {suffix.replace('_', ' ')} voice slot is replaced by the corresponding hydrophobic A02 acoustic mesh.",
            (f"A02_acoustic_mesh_{suffix}",),
        )
    if name in {"follow_uwb_side_radome_left", "follow_uwb_side_radome_right"}:
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.rf.side_uwb_radome",
            f"The prototype {side} UWB radome is replaced by the named non-conductive final A04 radome at the controlled side datum.",
            (f"A04_side_uwb_radome_{side}",),
        )
    if name == "follow_rear_tof_window":
        return _Decision(
            "replace_surface",
            "replace.perception.rear_tof_window",
            "The controlled rear ToF pane is replaced by the flush A10 final window and its through-shell optical tunnel.",
            ("A10_rear_tof_window", "A10_rear_service_surround"),
        )
    if name == "follow_uwb_rear_radome":
        return _Decision(
            "replace_surface",
            "replace.rf.rear_uwb_radome",
            "The prototype rear UWB pane is replaced by the final RF-transparent A10 radome at the same controlled projection.",
            ("A10_rear_uwb_radome",),
        )

    if name == "hmi_left_display_qi_tray":
        return _Decision(
            "replace_surface",
            "replace.hmi.left_tray",
            "The prototype combined tray surface is superseded by the precision bezel and body-colour A05 lid while its display and Qi hardpoints remain fixed.",
            ("A05_left_hmi_precision_bezel", "A05_armrest_touch_lid_left"),
        )
    if name == "hmi_status_display_left":
        return _Decision(
            "replace_surface",
            "replace.hmi.status_display",
            "The controlled status display aperture is expressed by the bonded final anti-glare display window.",
            ("A05_left_status_display_window",),
        )
    if name == "hmi_emergency_stop_guard":
        return _Decision(
            "replace_surface",
            "replace.safety.estop_guard",
            "The prototype guard is replaced by the final impact-resistant guard at the unchanged emergency-stop axis.",
            ("A05_left_emergency_stop_guard",),
        )
    if name == "hmi_mechanical_emergency_stop":
        return _Decision(
            "replace_surface",
            "replace.safety.estop_control",
            "The prototype emergency-stop exterior is replaced one-for-one by the visible safety-rated final stop interface.",
            ("A05_left_mechanical_emergency_stop",),
        )
    if name == "hmi_rear_status_light":
        return _Decision(
            "replace_surface",
            "replace.status.rear_lens",
            "The prototype rear status lamp face is replaced by the serviceable final A10 lens.",
            ("A10_rear_status_lens",),
        )
    if name in {
        "hmi_drive_control_pod_right",
        "hmi_joystick_right",
        "hmi_drive_authorization_key_right",
    }:
        proxy = {
            "hmi_drive_control_pod_right": "A05_right_removable_drive_pod",
            "hmi_joystick_right": "A05_right_joystick",
            "hmi_drive_authorization_key_right": "A05_right_authorisation_key",
        }[name]
        return _Decision(
            "replace_surface",
            "replace.hmi.drive_control.fixed_forward_station",
            (
                f"{name} remains externally exposed at the same forward "
                f"right-armrest hand datum in {state}; only Ride authorises "
                "traction, and table deployment may not relocate the control."
            ),
            (proxy,),
        )

    if name.startswith("footrest_platform_"):
        return _Decision(
            "replace_surface",
            "replace.footrest.invariant_platform",
            "The single DFR5 A08 platform occurrence is finished by the same top, inset tread and perimeter definitions in both stowed and deployed poses.",
            (
                "A08_footrest_top_skin",
                "A08_footrest_inset_tread",
                "A08_footrest_perimeter_skin",
            ),
        )
    if name.startswith("footrest_support_boot_") and name.endswith(
        "_deployed_locked"
    ):
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.footrest.captured_drawer_support_enclosure",
            f"The prototype free-floating {side} boot is superseded by the same smooth support monocoque, captured primary cartridge, inner rail and fixed guide used at the stowed endpoint.",
            (
                f"A08_footrest_support_monocoque_{side}",
                f"A08_footrest_primary_cartridge_{side}",
                f"A08_footrest_captured_inner_rail_{side}",
                f"A08_footrest_fixed_guide_housing_{side}",
                "A08_footrest_root_monocoque",
            ),
        )
    if name.startswith("footrest_manual_latch_"):
        return _Decision(
            "replace_surface",
            "replace.footrest.manual_release",
            "The one body-side controlled footrest latch remains mechanically operative beneath the same pose-invariant A08 glove-operable release-paddle shell in every state.",
            ("A08_manual_release_paddle_shell",),
        )

    if name == "obstacle_handle_crossbar_stowed":
        return _Decision(
            "replace_surface",
            "replace.rescue.handle_crossbar",
            "The prototype recovery crossbar is visually and tactilely superseded by the body-colour final grip shell.",
            ("A04_recovery_handle_grip_shell",),
        )
    if name == "obstacle_handle_grip_inlay_stowed":
        return _Decision(
            "replace_surface",
            "replace.rescue.handle_inlay",
            "The prototype grip insert is replaced by the dedicated dark final hand-contact inlay.",
            ("A04_recovery_handle_grip_inlay",),
        )
    if name == "obstacle_handle_deck_recess":
        return _Decision(
            "replace_surface",
            "replace.rescue.handle_recess",
            "The raw prototype deck recess is absorbed into the final A04 closeout and deliberate recovery-grip opening.",
            ("A04_underseat_belly_closeout", "A04_recovery_handle_grip_shell"),
        )

    if name == "service_rear_flush_door":
        return _Decision(
            "replace_surface",
            "replace.service.rear_door_skin",
            "The controlled service door remains the carrier but its prototype exterior is replaced by the final gasketed A10 door skin.",
            ("A10_rear_flush_service_door_skin",),
        )

    if name.startswith("mast_outer_cosmetic_shroud_"):
        return _Decision(
            "replace_surface",
            "replace.mast.outer_shroud",
            (
                "The prototype cosmetic mast shroud is replaced by the final A07 fixed outer sleeve on source axis X=310; "
                "Ride/Cafe/Focus keep that fixed sleeve at one identical world transform."
            ),
            ("A07_mast_fixed_outer_sleeve",),
        )
    if name.startswith("sensor_beam_shell_"):
        return _Decision(
            "replace_surface",
            "replace.mast.sensor_beam_shell",
            (
                "The prototype sensor-beam exterior is superseded by the final rounded A07 beam shell; "
                "Ride/Cafe retain its readable low pose and Focus translates that same terminal +420 mm."
            ),
            ("A07_sensor_beam_shell",),
        )
    if name.startswith("mast_smoked_sensor_window_"):
        return _Decision(
            "replace_surface",
            "replace.mast.combined_sensor_window",
            "The prototype smoked camera/depth cover is replaced by the final serviceable A07 optical window.",
            ("A07_sensor_beam_smoked_window",),
        )
    if name.startswith("mast_privacy_shutter_"):
        proxies = ["A07_physical_privacy_shutter"]
        if state == "focus":
            proxies.append("A07_sensor_beam_shell")
        elif state == "follow":
            proxies.append("A06_backrest_weather_shell")
        return _Decision(
            "replace_surface",
            "replace.mast.privacy_shutter",
            (
                f"The controlled {state} privacy shutter is bound to the same physical A07 occurrence. "
                "Focus preserves the released parked centre (264.5, 128, 1460) mm; Follow carries the closed shutter through the common A06/A07 fold beneath the same trapezoidal backrest."
            ),
            tuple(proxies),
        )
    if name.startswith("mast_lock_pin_"):
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.mast.lock_pin_and_witness",
            (
                f"The controlled {side} prototype pin is replaced by the named "
                "hardened A07 radial pin at the fixed Z=888 station.  It engages "
                "one of two discrete endpoint bores and fully retracts before "
                "motion; the separate confirmation lens carries no structural credit."
            ),
            (
                f"A07_mast_lock_pin_{side}",
                f"A07_mast_lock_pin_confirmation_lens_{side}",
            ),
        )
    if name.startswith("mast_fill_light_focus_"):
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.mast.fill_light_window",
            f"The controlled Focus {side} fill-light aperture is replaced by its dedicated visible-light A07 window.",
            (f"A07_fill_light_visible_window_{side}",),
        )

    if name.startswith("desk_panel_"):
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.table.complete_leaf_surface",
            f"The prototype {side} sandwich-panel appearance is fully partitioned into a named final top skin, edge band and underbelly within the exact leaf envelope.",
            (
                f"A09_table_top_skin_{side}",
                f"A09_table_top_skin_{side}_fold_half_inner",
                f"A09_table_edge_band_{side}",
                f"A09_table_edge_band_{side}_fold_half_inner",
                f"A09_table_underbelly_shell_{side}",
                f"A09_table_underbelly_shell_{side}_fold_half_inner",
            ),
        )
    if name.startswith("desk_lift_column_boot_"):
        side = _side_from_name(name)
        if state == "cafe":
            proxies = (
                "A05_table_root_structural_cassette_right",
                "A09_cafe_internal_lift_packaging_envelope_right",
                "A09_cafe_fixed_root_housing_right",
            )
        else:
            proxies = (
                f"A05_table_root_structural_cassette_{side}",
                f"A09_focus_internal_root_box_{side}",
                f"A09_focus_internal_nested_guide_stage_1_{side}",
                f"A09_focus_internal_nested_guide_stage_2_{side}",
                f"A09_focus_internal_nested_guide_stage_3_{side}",
            )
        return _Decision(
            "replace_surface",
            "replace.table.lift_boot",
            f"The prototype {side} exterior lift boot is superseded by the metal A05 cassette and compact A09 in-cavity root/package; no post remains beside the deployed table.",
            proxies,
        )
    if name in {"desk_cafe_translation_lock_right", "desk_cafe_rotation_lock_pin_right"}:
        proxies = (
            "A09_cafe_lock_release_paddle_right",
            "A09_cafe_positive_lock_witness_right",
        )
        return _Decision(
            "replace_surface",
            "replace.table.cafe_lock_interface",
            f"{name} remains internal controlled lock hardware; its external operation/state expression is replaced by the paired A09 release and witness mounted to the same outer half-leaf, outside the U-carriage sweep, and connected by a captive mechanical linkage.",
            proxies,
        )
    if name.startswith("desk_centre_latch_") or name.startswith("desk_lock_pin_"):
        station = "1" if name.endswith("-555") else "2"
        proxies = tuple(
            f"A09_focus_lock_release_paddle_{side}_{station}"
            for side in ("left", "right")
        )
        return _Decision(
            "replace_surface",
            "replace.table.focus_lock_station",
            f"{name} is one controlled Focus lock station; both leaf-local final paddles are explicitly tied to that shared station rather than counted as independent locks.",
            proxies,
        )
    return None


def _conceal_policy(state: str, name: str) -> _Decision | None:
    """Explicit access-chain bindings; door and external release are mandatory."""

    if name.startswith("hub_"):
        axle = "front" if "_front_" in name else "rear"
        side = _side_from_name(name)
        cap = f"A03_wheel_end_service_cap_{axle}_{side}"
        return _Decision(
            "conceal_behind_access",
            "conceal.wheel_hub.moving_cap_and_flexible_diaphragm",
            f"{name} remains on the controlled wheel but is never a normal exterior face: the body-colour cap and its opaque backing follow the hub, while a fixed-edge flexible diaphragm closes the complete articulation sweep.  Authorised removal is performed only with the suspension positively locked at neutral.",
            proxy_names=(
                cap,
                f"A03_wheel_end_motion_gaiter_{axle}_{side}",
            ),
            access_door=cap,
            external_release=cap,
            release_integrated_with_door=True,
        )

    if name in {
        "daily_caddy_liftout_bin_4p9l",
        "daily_caddy_soft_liner",
    }:
        return _Decision(
            "conceal_behind_access",
            "conceal.daily_caddy.integrated_lift_hatch",
            f"{name} remains behind the final flush caddy hatch; the hatch's exterior tool-less lift edge is the manual no-power release.",
            access_door="A04_daily_caddy_flush_hatch",
            external_release="A04_daily_caddy_flush_hatch",
            release_integrated_with_door=True,
        )
    if name == "daily_caddy_unpowered_access_lid":
        return _Decision(
            "replace_surface",
            "replace.daily_caddy.controlled_lid_with_final_a04_hatch",
            "The controlled prototype lid is replaced one-for-one at the same seat-pan service datum by A04_daily_caddy_flush_hatch; retaining both creates duplicate solids, while moving the final hatch above the device drawers blocks their stowed envelope.",
            proxy_names=("A04_daily_caddy_flush_hatch",),
        )

    if (
        name.startswith("drawer_front_left_upper")
        or name.startswith("drawer_tray_left_upper")
        or name.startswith("cots_latch_left_upper")
    ):
        return _Decision(
            "conceal_behind_access",
            "conceal.upper_equipment.left",
            f"{name} stays serviceable behind the final left upper-equipment door and its independent external two-action release.",
            access_door="A04_upper_equipment_door_left",
            external_release="A04_upper_equipment_release_left",
        )
    if (
        name.startswith("drawer_front_right_upper")
        or name.startswith("drawer_tray_right_upper")
        or name.startswith("cots_latch_right_upper")
    ):
        return _Decision(
            "conceal_behind_access",
            "conceal.upper_equipment.right",
            f"{name} stays serviceable behind the final right upper-equipment door and its independent external two-action release.",
            access_door="A04_upper_equipment_door_right",
            external_release="A04_upper_equipment_release_right",
        )

    if name.startswith("desk_bundle_stowed_"):
        side = _side_from_name(name)
        return _Decision(
            "conceal_behind_access",
            "conceal.table.stowed_top_access_bay",
            f"The controlled folded {side} table bundle remains inside the fixed A05 body and is lifted through the outward-flipping top lid; there is no side cassette opening.",
            access_door=f"A05_armrest_touch_lid_{side}",
            external_release=f"A05_armrest_top_lid_release_{side}",
            release_integrated_with_door=False,
        )

    if name in {
        "service_charge_port_guarded",
        "service_battery_disconnect_guarded",
        "service_brake_release_guarded",
    }:
        return _Decision(
            "conceal_behind_access",
            "conceal.service.rear_no_power_chain",
            f"{name} is normally hidden but remains reachable through the named A10 rear door and its separate glove-operable no-power release.",
            access_door="A10_rear_flush_service_door_skin",
            external_release="A10_rear_service_external_no_power_release",
        )
    if name == "service_rear_horn_behind_door":
        return _Decision(
            "conceal_behind_access",
            "conceal.service.rear_horn",
            "The horn body remains serviceable behind the A10 door while its sound exits through the separately named final acoustic mesh.",
            proxy_names=("A10_rear_horn_acoustic_mesh",),
            access_door="A10_rear_flush_service_door_skin",
            external_release="A10_rear_service_external_no_power_release",
        )
    return None


def _internal_policy(state: str, name: str) -> _Decision | None:
    """Explicit internal items and the final shells that own their enclosure."""

    if name.startswith("axle_") or name.startswith("suspension_"):
        side = _side_from_name(name)
        proxies = [
            f"A03_wheel_interspace_bridge_{side}",
            f"A03_continuous_wheel_belt_shell_{side}",
        ]
        if "centre_pivot" in name or "rocker" in name:
            proxies.append(f"A03_rocker_pivot_service_cap_{side}")
        if name.startswith("axle_"):
            axle = "front" if "_front_" in name else "rear"
            proxies.extend(
                (
                    f"A03_wheel_end_service_cap_{axle}_{side}",
                    f"A03_wheel_end_motion_gaiter_{axle}_{side}",
                )
            )
        return _Decision(
            "internal_enclosed",
            "internal.running_gear",
            f"{name} is structural running gear, not an exterior styling surface; A03 owns its normal-view enclosure while retaining wheel travel and service openings.",
            enclosure_proxies=tuple(proxies),
        )
    if name.startswith("chassis_crossmember_") or name.startswith("chassis_rail_"):
        return _Decision(
            "internal_enclosed",
            "internal.chassis",
            f"{name} is a structural chassis member fully inside the A02/A04 final body envelope.",
            enclosure_proxies=(
                "A02_main_side_shell_left",
                "A02_main_side_shell_right",
                "A04_underseat_belly_closeout",
            ),
        )
    if name.startswith("battery_"):
        proxies = (
            ("A10_pressure_relief_vent_bezel", "A10_rear_service_surround")
            if name == "battery_pressure_vent_duct"
            else ("A04_underseat_belly_closeout", "A10_rear_service_surround")
        )
        return _Decision(
            "internal_enclosed",
            "internal.battery_system",
            f"{name} is retained as protected battery hardware inside the A04/A10 envelope; any pressure function exits only through the named A10 vent interface.",
            enclosure_proxies=proxies,
        )
    if name in {
        "communications_5g_wifi_uwb_module",
        "compute_core_cartridge",
        "drive_imu_controller",
        "encrypted_data_vault",
        "occupant_energy_firewall",
        "power_distribution_unit",
        "safety_backup_battery_24v60wh",
    }:
        return _Decision(
            "internal_enclosed",
            "internal.core_electronics",
            f"{name} is an internal functional module enclosed by the main side and under-seat responsibility shells.",
            enclosure_proxies=(
                "A02_main_side_shell_left",
                "A02_main_side_shell_right",
                "A04_underseat_belly_closeout",
            ),
        )

    if name in {
        "armrest_transfer_hinge_right",
        "armrest_transfer_link_right",
    }:
        return _Decision(
            "trace_only_retired",
            "trace.retired_transfer_mechanism.fixed_armrest_configuration",
            f"{name} belongs to the deleted side-opening prototype and remains only in the immutable trace underlay; the fixed-armrest production configuration contains no corresponding hinge or link.",
        )
    if name in {
        "armrest_transfer_hinge_shroud_right",
        "armrest_transfer_link_shroud_right",
    }:
        return _Decision(
            "replace_surface",
            "replace.fixed_armrest.prototype_transfer_shroud",
            f"{name} is a prototype transfer shroud removed in favour of the fixed continuous right A05 wing; no side-opening seam or control remains in the final exterior.",
            ("A05_armrest_table_bay_shell_right",),
        )
    if name == "backrest_structural_carrier":
        return _Decision(
            "internal_enclosed",
            "internal.backrest.carrier",
            "The structural backrest carrier remains between the final A06 weather shell and contact panel.",
            enclosure_proxies=(
                "A06_backrest_weather_shell",
                "A06_backrest_contact_panel",
            ),
        )

    if name.startswith("cots_slide_"):
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.upper_equipment.slide",
            f"{name} is an internal slide behind the named {side} A04 equipment-door enclosure.",
            enclosure_proxies=(f"A04_upper_equipment_door_{side}",),
        )
    if name.startswith("cots_mast_actuator_"):
        return _Decision(
            "internal_enclosed",
            "internal.mast.actuator",
            f"{name} is the concealed mast actuator inside the A04/A07 structural transition, not an exterior occurrence.",
            enclosure_proxies=("A04_underseat_belly_closeout", "A07_mast_fixed_outer_sleeve"),
        )
    if name.startswith("device_bay_shock_liner_"):
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.armrest.device_bay",
            f"{name} is a compliant internal liner below the named {side} A05 armrest shell and lid.",
            enclosure_proxies=(
                f"A05_armrest_table_bay_shell_{side}",
                f"A05_armrest_touch_lid_{side}",
            ),
        )

    if name.startswith("follow_front_tof_") and name.endswith("_module"):
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.perception.front_tof_module",
            f"{name} is enclosed behind its named A01 tunnel and final optical window.",
            enclosure_proxies=("A01_perception_horizon_carrier", f"A01_front_{side}_tof_window"),
        )
    if name == "follow_leg_scanner_module":
        return _Decision(
            "internal_enclosed",
            "internal.perception.leg_scanner_module",
            "The leg-scanner module remains behind the A01 carrier and its dedicated final optical pane.",
            enclosure_proxies=("A01_perception_horizon_carrier", "A01_front_leg_scanner_window"),
        )
    if name.startswith("follow_cliff_ir_module_"):
        suffix = name.removeprefix("follow_cliff_ir_module_")
        return _Decision(
            "internal_enclosed",
            "internal.perception.cliff_ir_module",
            f"{name} is enclosed by A02 and looks outward only through its one-to-one {suffix.replace('_', ' ')} final pane.",
            enclosure_proxies=("A02_main_side_shell_left" if "left" in suffix else "A02_main_side_shell_right", f"A02_cliff_ir_window_{suffix}"),
        )
    if name.startswith("follow_side_ultrasonic_module_"):
        suffix = name.removeprefix("follow_side_ultrasonic_module_")
        side = "left" if "left" in suffix else "right"
        return _Decision(
            "internal_enclosed",
            "internal.perception.side_ultrasonic_module",
            f"{name} is enclosed behind the {side} A02 shell and its corresponding flush transducer face.",
            enclosure_proxies=(f"A02_main_side_shell_{side}", f"A02_side_ultrasonic_face_{suffix}"),
        )
    if name in {"follow_uwb_side_module_left", "follow_uwb_side_module_right"}:
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.rf.side_uwb_module",
            f"{name} remains inside the A04 equipment enclosure behind the named {side} final RF radome.",
            enclosure_proxies=(f"A04_upper_equipment_door_{side}", f"A04_side_uwb_radome_{side}"),
        )
    if name == "follow_uwb_rear_module":
        return _Decision(
            "internal_enclosed",
            "internal.rf.rear_uwb_module",
            "The rear UWB electronics stay behind the A10 door and communicate only through the named final radome aperture.",
            enclosure_proxies=("A10_rear_flush_service_door_skin", "A10_rear_uwb_radome"),
        )
    if name == "follow_rear_tof_module":
        return _Decision(
            "internal_enclosed",
            "internal.perception.rear_tof_module",
            "The rear ToF module is enclosed by A10 and looks outward through the dedicated final rear ranging window.",
            enclosure_proxies=("A10_rear_service_surround", "A10_rear_tof_window"),
        )
    if name.startswith("follow_hidden_backrest_antenna_"):
        return _Decision(
            "internal_enclosed",
            "internal.rf.hidden_backrest_antenna",
            f"{name} is intentionally invisible behind the non-metallic A06 weather shell; its RF keep-out remains a separate verification gate.",
            enclosure_proxies=("A06_backrest_weather_shell",),
        )
    if name.startswith("follow_voice_mic_strip_"):
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.acoustic.lower_voice_module",
            f"{name} remains behind the {side} A02 side shell and its two named hydrophobic acoustic meshes.",
            enclosure_proxies=(
                f"A02_main_side_shell_{side}",
                f"A02_acoustic_mesh_{side}_1",
                f"A02_acoustic_mesh_{side}_2",
            ),
        )

    if name.startswith("hmi_qi2_"):
        return _Decision(
            "internal_enclosed",
            "internal.hmi.qi_stack",
            f"{name} remains below the sealed left A05 lid and is located externally only by the final Qi target ring.",
            enclosure_proxies=("A05_armrest_touch_lid_left", "A05_left_qi_target_ring"),
        )
    if name in {"laptop_16in_keepout_right", "universal_flat_device_keepout_left"}:
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.hmi.device_keepout",
            f"{name} is a controlled non-physical keep-out volume contained within the {side} A05 bay, not a final visible part.",
            enclosure_proxies=(
                f"A05_armrest_table_bay_shell_{side}",
                f"A05_armrest_touch_lid_{side}",
            ),
        )

    if name.startswith("mast_camera_4k_") or name.startswith("mast_camera_depth_ir_"):
        return _Decision(
            "internal_enclosed",
            "internal.mast.camera_module",
            f"{name} remains inside the final A07 sensor beam behind the controlled combined smoked optical window.",
            enclosure_proxies=("A07_sensor_beam_shell", "A07_sensor_beam_smoked_window"),
        )
    if name.startswith("mast_microphone_array_"):
        return _Decision(
            "internal_enclosed",
            "internal.mast.microphone_array",
            f"{name} remains inside the final beam with its acoustic path assigned to the named A07 microphone mesh.",
            enclosure_proxies=("A07_sensor_beam_shell", "A07_microphone_acoustic_mesh"),
        )
    if name.startswith("mast_environment_sensor_"):
        return _Decision(
            "internal_enclosed",
            "internal.mast.environment_sensor",
            f"{name} remains inside the final beam with air exchange assigned to the named A07 environment grille.",
            enclosure_proxies=("A07_sensor_beam_shell", "A07_environment_sensor_grille"),
        )
    if (
        name.startswith("mast_guide_")
        or name.startswith("mast_harness_")
        or name.startswith("mast_inner_")
        or (
            name.startswith("mast_outer_")
            and not name.startswith("mast_outer_cosmetic_shroud_")
        )
        or name.startswith("mast_reeving_pulley_")
    ):
        proxies = A07_MECHANISM_ENCLOSURES_BY_STATE[state]
        if state == "follow":
            rationale = (
                f"{name} remains inside the conserved A07 sleeves while A06 and A07 apply one common Follow hinge transform; "
                "the same folded trapezoidal A06 backrest supplies the only weather coverage."
            )
        elif state in {"ride", "cafe"}:
            rationale = (
                f"{name} remains inside the conserved A07 sleeves at the identical Ride/Cafe low pose; "
                "the 320 mm sensor beam itself remains externally readable at X=310, Z=1040."
            )
        else:
            rationale = (
                f"{name} remains inside the conserved A07 sleeves: the fixed outer keeps the Ride/Cafe transform, "
                "while only the moving inner member and sensor terminal translate +420 mm in Focus."
            )
        return _Decision(
            "internal_enclosed",
            "internal.mast.mechanism",
            rationale,
            enclosure_proxies=tuple(proxies),
        )

    if (
        name.startswith("obstacle_handle_inner_tube_")
        or name.startswith("obstacle_handle_outer_tube_")
        or name.startswith("obstacle_handle_positive_latch_")
    ):
        return _Decision(
            "internal_enclosed",
            "internal.rescue.handle_mechanism",
            f"{name} is the concealed recovery-handle mechanism beneath the A04 closeout and final grip shell.",
            enclosure_proxies=("A04_underseat_belly_closeout", "A04_recovery_handle_grip_shell"),
        )

    if name.startswith("pelvic_belt_hidden_"):
        return _Decision(
            "internal_enclosed",
            "internal.occupant.pelvic_belt",
            f"{name} is a deliberately hidden occupant-restraint component inside the A04/A06 seat-back envelope.",
            enclosure_proxies=("A04_open_u_seat_pan_ring", "A06_backrest_contact_panel"),
        )
    if name in {"seat_occupancy_sensor", "seat_structural_pan"}:
        return _Decision(
            "internal_enclosed",
            "internal.occupant.seat_stack",
            f"{name} remains beneath the retained seat cushion and inside the A04 seat-pan ring.",
            enclosure_proxies=("A04_open_u_seat_pan_ring",),
        )

    if name.startswith("footrest_support_boot_") and name.endswith("_stowed"):
        side = _side_from_name(name)
        return _Decision(
            "replace_surface",
            "replace.footrest.stowed_captured_drawer_support_enclosure",
            f"The non-physical upright {side} prototype boot is retired. The same production support monocoque translates into the body on its captured cartridge and inner rail without rotating or disappearing.",
            (
                f"A08_footrest_support_monocoque_{side}",
                f"A08_footrest_primary_cartridge_{side}",
                f"A08_footrest_captured_inner_rail_{side}",
                f"A08_footrest_fixed_guide_housing_{side}",
                "A08_footrest_root_monocoque",
            ),
        )
    if name.startswith("footrest_support_") and not name.startswith(
        "footrest_support_boot_"
    ):
        side = _side_from_name(name)
        if name.endswith("_stowed"):
            return _Decision(
                "internal_enclosed",
                "internal.footrest.stowed_captured_load_path",
                f"The obsolete interpolated {side} support is replaced by the captured primary cartridge, inner rail and paired over-centre links; no member rotates upright through free space.",
                enclosure_proxies=(
                    "A01_front_nose_shell",
                    f"A08_footrest_support_monocoque_{side}",
                    f"A08_footrest_primary_cartridge_{side}",
                    f"A08_footrest_captured_inner_rail_{side}",
                    "A08_footrest_root_monocoque",
                ),
            )
        return _Decision(
            "internal_enclosed",
            "internal.footrest.captured_drawer_load_path",
            f"{name} is superseded by the named {side} captured cartridge, inner rail and paired links inside the final moving enclosure and fixed root.",
            enclosure_proxies=(
                f"A08_footrest_support_monocoque_{side}",
                f"A08_footrest_primary_cartridge_{side}",
                f"A08_footrest_captured_inner_rail_{side}",
                f"A08_footrest_drop_link_{side}_front",
                f"A08_footrest_drop_link_{side}_rear",
                "A08_footrest_root_monocoque",
            ),
        )

    if name.startswith("desk_lift_tube_"):
        side = _side_from_name(name)
        if state == "cafe":
            root_enclosures = [
                "A05_table_root_structural_cassette_right",
                "A09_cafe_internal_lift_packaging_envelope_right",
                "A09_cafe_fixed_root_housing_right",
                "A09_cafe_fixed_yoke_bearing_carrier_right",
                "A09_cafe_rotary_hub_right",
                "A09_cafe_rotary_linear_rail_right",
            ]
        else:
            root_enclosures = [
                f"A05_table_root_structural_cassette_{side}",
                f"A09_focus_internal_root_box_{side}",
                f"A09_focus_internal_nested_guide_stage_1_{side}",
                f"A09_focus_internal_nested_guide_stage_2_{side}",
                f"A09_focus_internal_nested_guide_stage_3_{side}",
            ]
        return _Decision(
            "internal_enclosed",
            "internal.table.lift_tube",
            f"{name} is superseded by the named compact A09 root and nested guide occurrences inside the fixed A05 armrest cavity.",
            enclosure_proxies=tuple(root_enclosures),
        )
    if name.startswith("desk_leaf_rigidizer_"):
        side = _side_from_name(name)
        return _Decision(
            "internal_enclosed",
            "internal.table.leaf_rigidizer",
            f"{name} leaves the seated sightline inside the named {side} A09 underbelly shell.",
            enclosure_proxies=(
                f"A09_table_underbelly_shell_{side}",
                f"A09_table_underbelly_shell_{side}_fold_half_inner",
            ),
        )
    if name.startswith("desk_leaf_fold_hinge_"):
        side = _side_from_name(name)
        if state == "cafe":
            enclosures = (
                f"A09_table_underbelly_shell_{side}",
                f"A09_table_underbelly_shell_{side}_fold_half_inner",
                "A09_cafe_underleaf_motion_belly_right",
            )
            rationale = (
                f"{name} stays inside the two canonical half-leaf underbellies "
                f"and the Cafe {side} table-attached cross-spine; the separate "
                "fixed root housing does not bridge the fold."
            )
        else:
            enclosures = (
                f"A09_table_underbelly_shell_{side}",
                f"A09_table_underbelly_shell_{side}_fold_half_inner",
            )
            rationale = (
                f"{name} stays between the two canonical Focus {side} half-leaf "
                "underbellies; the concealed armrest root tongue attaches only "
                "to the outer half and never bridges this fold."
            )
        return _Decision(
            "internal_enclosed",
            "internal.table.fold_hinge",
            rationale,
            enclosure_proxies=enclosures,
        )
    if name.startswith("desk_forward_carriage_") or name.startswith("desk_yoke_"):
        side = _side_from_name(name)
        if state == "cafe":
            enclosures = (
                "A05_table_root_structural_cassette_right",
                "A09_cafe_internal_lift_packaging_envelope_right",
                "A09_cafe_fixed_root_housing_right",
                "A09_cafe_fixed_yoke_bearing_carrier_right",
                "A09_cafe_rotary_hub_right",
                "A09_cafe_rotary_linear_rail_right",
                "A09_cafe_underleaf_motion_belly_right",
            )
            rationale = (
                f"{name} is assigned to the Cafe {side} metal cassette, compact "
                "internal bearing/key package and the one closed table root neck; "
                "supplier guide details remain explicitly unfrozen."
            )
        else:
            enclosures = (
                f"A05_table_root_structural_cassette_{side}",
                f"A09_focus_internal_root_box_{side}",
                f"A09_focus_internal_nested_guide_stage_1_{side}",
                f"A09_focus_internal_nested_guide_stage_2_{side}",
                f"A09_focus_internal_nested_guide_stage_3_{side}",
                f"A09_focus_table_hidden_root_tongue_{side}",
            )
            rationale = (
                f"{name} is superseded by the Focus {side} flat root box and "
                "three nested guides inside A05; only the leaf-attached tongue "
                "crosses the small inner-sidewall port."
            )
        return _Decision(
            "internal_enclosed",
            "internal.table.root_mechanism",
            rationale,
            enclosure_proxies=enclosures,
        )
    cafe_mechanism_proxies = {
        "desk_cafe_rotation_bearing_right": (
            "A09_cafe_fixed_yoke_bearing_carrier_right",
            "A09_cafe_rotary_hub_right",
        ),
        "desk_cafe_rotation_index_plate_right": (
            "A09_cafe_rotary_hub_right",
            "A09_cafe_positive_lock_witness_right",
        ),
        "desk_cafe_translation_rail_right": (
            "A09_cafe_rotary_linear_rail_right",
            "A09_cafe_underleaf_motion_belly_right",
            "A09_cafe_internal_lift_packaging_envelope_right",
        ),
        "desk_cafe_transverse_yoke_right": (
            "A09_cafe_fixed_yoke_bearing_carrier_right",
            "A09_cafe_fixed_root_housing_right",
        ),
        "desk_cafe_underdeck_spine_right": (
            "A09_cafe_underleaf_motion_belly_right",
        ),
    }
    if name in cafe_mechanism_proxies:
        return _Decision(
            "internal_enclosed",
            "internal.table.cafe_mechanism",
            f"{name} is assigned to the layout-level metal cassette, internal bearing/key package and closed table root neck according to its actual final owner; unknown supplier hardware is not fabricated as false detail.",
            enclosure_proxies=cafe_mechanism_proxies[name],
        )
    return None


def disposition_for(state: str, source_occurrence: str) -> _Decision:
    """Classify one occurrence and reject zero or multiple policy matches.

    This function is intentionally pure: it does not read a GLB and has no
    filesystem side effects.  Builder/validator code can call it directly.
    """

    state = _state_checked(state)
    candidates = tuple(
        decision
        for decision in (
            _retain_policy(state, source_occurrence),
            _replace_policy(state, source_occurrence),
            _conceal_policy(state, source_occurrence),
            _internal_policy(state, source_occurrence),
        )
        if decision is not None
    )
    if not candidates:
        raise UnknownOccurrenceError(
            f"No source disposition for {state}:{source_occurrence}; explicit review required"
        )
    if len(candidates) > 1:
        rules = ", ".join(decision.rule_id for decision in candidates)
        raise DuplicateDispositionError(
            f"Multiple source dispositions for {state}:{source_occurrence}: {rules}"
        )
    return candidates[0]


def make_entry(state: str, source_occurrence: str) -> SourceDisposition:
    """Create one immutable ledger entry from the pure classifier."""

    state = _state_checked(state)
    decision = disposition_for(state, source_occurrence)
    return SourceDisposition(
        state=state,
        source_glb=CONTROLLED_GLBS[state],
        source_occurrence=source_occurrence,
        disposition=decision.disposition,
        rule_id=decision.rule_id,
        rationale=decision.rationale,
        proxy_names=decision.proxy_names,
        access_door=decision.access_door,
        external_release=decision.external_release,
        enclosure_proxies=decision.enclosure_proxies,
        retain_allowlist=decision.retain_allowlist,
        release_integrated_with_door=decision.release_integrated_with_door,
    )


def source_disposition_for(state: str, source_occurrence: str) -> SourceDisposition:
    """Public one-occurrence API returning the complete ledger record."""

    return make_entry(state, source_occurrence)


def controlled_glb_path(state: str, repository_root: Path | str = REPOSITORY_ROOT) -> Path:
    state = _state_checked(state)
    return Path(repository_root) / CONTROLLED_GLBS[state]


def read_controlled_geometry_names(
    state: str,
    repository_root: Path | str = REPOSITORY_ROOT,
) -> tuple[str, ...]:
    """Read exact geometry keys from one controlled GLB without processing it."""

    # Local import keeps the pure classification API lightweight for validators.
    import trimesh

    path = controlled_glb_path(state, repository_root)
    if not path.is_file():
        raise FileNotFoundError(path)
    scene = trimesh.load(path, force="scene", process=False)
    names = tuple(sorted(str(name) for name in scene.geometry.keys()))
    node_occurrences = tuple(str(name) for name in scene.graph.nodes_geometry)
    if len(node_occurrences) != len(names):
        raise SourceDispositionError(
            f"{path.name}: {len(names)} geometry keys but {len(node_occurrences)} geometry nodes"
        )
    if len(set(node_occurrences)) != len(node_occurrences):
        raise SourceDispositionError(f"{path.name}: duplicate geometry-node occurrence names")
    return names


def build_state_ledger(
    state: str,
    geometry_names: Iterable[str] | None = None,
    repository_root: Path | str = REPOSITORY_ROOT,
) -> tuple[SourceDisposition, ...]:
    """Build one state ledger from supplied names or the actual controlled GLB."""

    state = _state_checked(state)
    names = tuple(
        read_controlled_geometry_names(state, repository_root)
        if geometry_names is None
        else sorted(str(name) for name in geometry_names)
    )
    if len(set(names)) != len(names):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise DuplicateDispositionError(
            f"Duplicate controlled occurrences in {state}: {duplicates}"
        )
    return tuple(make_entry(state, name) for name in names)


def build_all_ledgers(
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, tuple[SourceDisposition, ...]]:
    """Read and classify all four controlled GLBs."""

    return {
        state: build_state_ledger(state, repository_root=repository_root)
        for state in CONTROLLED_GLBS
    }


def retain_exposed_names(entries: Sequence[SourceDisposition]) -> frozenset[str]:
    """Return the exact source allowlist for builder presentation export."""

    return frozenset(
        entry.source_occurrence
        for entry in entries
        if entry.disposition == "retain_exposed"
    )


def disposition_index(
    entries: Iterable[SourceDisposition],
) -> dict[tuple[str, str], SourceDisposition]:
    """Index entries and reject duplicate ``(state, occurrence)`` keys."""

    result: dict[tuple[str, str], SourceDisposition] = {}
    for entry in entries:
        if entry.key in result:
            raise DuplicateDispositionError(f"Duplicate ledger key: {entry.key}")
        result[entry.key] = entry
    return result


def validate_ledgers(
    ledgers: Mapping[str, Sequence[SourceDisposition]],
    repository_root: Path | str = REPOSITORY_ROOT,
    available_proxies_by_state: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, object]:
    """Validate source completeness, disposition contracts and proxy bindings."""

    errors: list[str] = []
    state_reports: dict[str, object] = {}
    all_entries: list[SourceDisposition] = []

    for state in CONTROLLED_GLBS:
        entries = tuple(ledgers.get(state, ()))
        all_entries.extend(entries)
        actual_names = read_controlled_geometry_names(state, repository_root)
        entry_names = tuple(entry.source_occurrence for entry in entries)
        missing = sorted(set(actual_names) - set(entry_names))
        extra = sorted(set(entry_names) - set(actual_names))
        duplicate_names = sorted(
            name for name in set(entry_names) if entry_names.count(name) > 1
        )
        if missing:
            errors.append(f"{state}: missing ledger occurrences {missing}")
        if extra:
            errors.append(f"{state}: non-controlled ledger occurrences {extra}")
        if duplicate_names:
            errors.append(f"{state}: duplicate ledger occurrences {duplicate_names}")

        available = (
            set(available_proxies_by_state[state])
            if available_proxies_by_state is not None and state in available_proxies_by_state
            else None
        )
        counts = {kind: 0 for kind in DISPOSITIONS}
        referenced_proxies: set[str] = set()
        a07_mechanism_contract_entries = 0
        for entry in entries:
            if entry.state != state:
                errors.append(
                    f"{state}:{entry.source_occurrence}: entry state is {entry.state!r}"
                )
            if entry.disposition not in DISPOSITIONS:
                errors.append(
                    f"{state}:{entry.source_occurrence}: invalid disposition {entry.disposition!r}"
                )
                continue
            counts[entry.disposition] += 1
            if not entry.rationale.strip():
                errors.append(f"{state}:{entry.source_occurrence}: rationale is empty")

            refs = set(entry.proxy_names) | set(entry.enclosure_proxies)
            if entry.access_door:
                refs.add(entry.access_door)
            if entry.external_release:
                refs.add(entry.external_release)
            referenced_proxies.update(refs)
            invalid_refs = sorted(
                ref
                for ref in refs
                if not any(ref.startswith(f"A{module:02d}_") for module in range(1, 11))
            )
            if invalid_refs:
                errors.append(
                    f"{state}:{entry.source_occurrence}: non-A01--A10 refs {invalid_refs}"
                )

            if entry.disposition == "retain_exposed":
                if not entry.retain_allowlist:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: retained source missing allowlist flag"
                    )
                if refs:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: retained source must not have replacement/access refs"
                    )
            elif entry.disposition == "replace_surface":
                if not entry.proxy_names:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: replacement has no final proxy"
                    )
                if entry.access_door or entry.external_release:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: replacement incorrectly uses an access chain"
                    )
            elif entry.disposition == "conceal_behind_access":
                if not entry.access_door or not entry.external_release:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: concealed source lacks door+external release"
                    )
            elif entry.disposition == "internal_enclosed":
                if not entry.enclosure_proxies:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: internal source lacks named enclosure proxies"
                    )
            elif entry.disposition == "trace_only_retired":
                if refs or entry.retain_allowlist:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: retired trace occurrence must have no production refs or retain allowlist"
                    )

            if entry.rule_id == "internal.mast.mechanism":
                a07_mechanism_contract_entries += 1
                expected_enclosures = A07_MECHANISM_ENCLOSURES_BY_STATE[state]
                if entry.enclosure_proxies != expected_enclosures:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: A07 mechanism enclosure contract "
                        f"is {entry.enclosure_proxies}, expected {expected_enclosures}"
                    )
                invented_service_core_refs = sorted(
                    ref
                    for ref in entry.enclosure_proxies
                    if ref.startswith(("A04_", "A10_"))
                )
                if invented_service_core_refs:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: A07 mechanism may not be "
                        f"dispositioned into an A04/A10 service core {invented_service_core_refs}"
                    )

            if available is not None:
                missing_refs = sorted(refs - available)
                if missing_refs:
                    errors.append(
                        f"{state}:{entry.source_occurrence}: proxy refs absent from state skin {missing_refs}"
                    )

        state_reports[state] = {
            "source_glb": CONTROLLED_GLBS[state],
            "controlled_occurrences": len(actual_names),
            "ledger_occurrences": len(entries),
            "unknown": len(missing),
            "duplicates": len(duplicate_names),
            "extra": len(extra),
            "counts": counts,
            "retain_allowlist": sorted(retain_exposed_names(entries)),
            "referenced_proxy_count": len(referenced_proxies),
            "a07_mechanism_contract_entries": a07_mechanism_contract_entries,
            "a07_mechanism_enclosure_contract": list(
                A07_MECHANISM_ENCLOSURES_BY_STATE[state]
            ),
            "a07_geometry_proof_deferred_to_brep_validators": True,
        }

    try:
        disposition_index(all_entries)
    except DuplicateDispositionError as exc:
        errors.append(str(exc))

    return {
        "schema": "workcore-e6-source-disposition-v1",
        "status": "PASS" if not errors else "FAIL",
        "proxy_reference_validation": (
            "performed" if available_proxies_by_state is not None else "not_performed"
        ),
        "controlled_states": list(CONTROLLED_GLBS),
        "state_reports": state_reports,
        "total_controlled_occurrences": sum(
            report["controlled_occurrences"] for report in state_reports.values()
        ),
        "total_ledger_occurrences": sum(
            report["ledger_occurrences"] for report in state_reports.values()
        ),
        "unknown": sum(report["unknown"] for report in state_reports.values()),
        "duplicates": sum(report["duplicates"] for report in state_reports.values()),
        "extra": sum(report["extra"] for report in state_reports.values()),
        "errors": errors,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _markdown_report(
    ledgers: Mapping[str, Sequence[SourceDisposition]],
    validation: Mapping[str, object],
    source_hashes: Mapping[str, str],
) -> str:
    lines = [
        "# WorkCore E6 controlled-source disposition ledger",
        "",
        f"Status: **{validation['status']}**",
        "",
        "This ledger is generated from the actual geometry keys in the four controlled GLBs. It is a presentation/cladding-responsibility contract, not a substitute for optical, RF, acoustic, pressure, thermal, motion or production validation.",
        "",
        "A07 state truth is geometry-gated elsewhere: Ride/Cafe are the same readable low pose on X=310; Focus keeps the fixed outer transform and moves only the inner/terminal +420 mm; Follow shares the A06 hinge and is covered by that same trapezoidal backrest. Proxy names in this ledger cannot prove those B-Rep facts.",
        "",
        "No unmatched occurrence is defaulted to `internal_enclosed`; a new source name makes generation fail until explicitly reviewed.",
        "",
        f"A01--A10 proxy-name verification: **{validation['proxy_reference_validation']}**.",
        "",
        "## Completeness",
        "",
        "| State | GLB occurrences | Ledger entries | retain_exposed | replace_surface | conceal_behind_access | internal_enclosed | trace_only_retired | Unknown | Duplicate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    state_reports = validation["state_reports"]
    for state in CONTROLLED_GLBS:
        report = state_reports[state]
        counts = report["counts"]
        lines.append(
            f"| {state} | {report['controlled_occurrences']} | {report['ledger_occurrences']} | {counts['retain_exposed']} | {counts['replace_surface']} | {counts['conceal_behind_access']} | {counts['internal_enclosed']} | {counts['trace_only_retired']} | {report['unknown']} | {report['duplicates']} |"
        )
    lines.extend(
        [
            "",
            f"Total: **{validation['total_ledger_occurrences']} / {validation['total_controlled_occurrences']}** occurrences; unknown **{validation['unknown']}**; duplicate **{validation['duplicates']}**.",
            "",
            "## Controlled GLB fingerprints",
            "",
        ]
    )
    for state, filename in CONTROLLED_GLBS.items():
        lines.append(f"- `{state}` — `{filename}` — SHA256 `{source_hashes[state]}`")

    for state in CONTROLLED_GLBS:
        lines.extend(
            [
                "",
                f"## {state.capitalize()} occurrence ledger",
                "",
                "| Source occurrence | Disposition | Final responsibility | Rationale |",
                "|---|---|---|---|",
            ]
        )
        for entry in ledgers[state]:
            if entry.disposition == "retain_exposed":
                responsibility = "controlled source retained in final allowlist"
            elif entry.disposition == "replace_surface":
                responsibility = ", ".join(f"`{name}`" for name in entry.proxy_names)
            elif entry.disposition == "conceal_behind_access":
                responsibility = (
                    f"door `{entry.access_door}`; external release `{entry.external_release}`"
                )
                if entry.proxy_names:
                    responsibility += "; functional proxy " + ", ".join(
                        f"`{name}`" for name in entry.proxy_names
                    )
            elif entry.disposition == "trace_only_retired":
                responsibility = "immutable trace underlay only; absent from production BOM and final render"
            else:
                responsibility = ", ".join(
                    f"`{name}`" for name in entry.enclosure_proxies
                )
            rationale = entry.rationale.replace("|", "\\|")
            lines.append(
                f"| `{entry.source_occurrence}` | `{entry.disposition}` | {responsibility} | {rationale} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_qa_artifacts(
    output_dir: Path | str = DEFAULT_QA_DIR,
    repository_root: Path | str = REPOSITORY_ROOT,
    available_proxies_by_state: Mapping[str, Iterable[str]] | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    """Generate auditable JSON/Markdown ledgers after full validation."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledgers = build_all_ledgers(repository_root)
    validation = validate_ledgers(
        ledgers,
        repository_root=repository_root,
        available_proxies_by_state=available_proxies_by_state,
    )
    if validation["status"] != "PASS":
        raise SourceDispositionError(
            "Source disposition validation failed:\n" + "\n".join(validation["errors"])
        )
    source_hashes = {
        state: _sha256(controlled_glb_path(state, repository_root))
        for state in CONTROLLED_GLBS
    }
    payload = {
        **validation,
        "controlled_glb_sha256": source_hashes,
        "entries": {
            state: [entry.to_dict() for entry in ledgers[state]]
            for state in CONTROLLED_GLBS
        },
    }
    json_path = output_dir / "source_disposition_ledger.json"
    md_path = output_dir / "source_disposition_ledger.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        _markdown_report(ledgers, validation, source_hashes),
        encoding="utf-8",
    )
    return json_path, md_path, validation


def _load_current_proxy_names() -> dict[str, set[str]]:
    """Build names only for a strong standalone QA run; not used on import."""

    import sys

    for path in (REPOSITORY_ROOT, SCRIPT_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from skin_lower import build_lower_skin
    from skin_upper import build_upper_skin

    return {
        state: {
            part.name
            for part in (build_lower_skin(state) + build_upper_skin(state))
        }
        for state in CONTROLLED_GLBS
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write JSON and Markdown ledgers to step_anchored_v2/qa",
    )
    parser.add_argument(
        "--verify-proxies",
        action="store_true",
        help="also build current skin part names and reject stale proxy references",
    )
    parser.add_argument("--qa-dir", type=Path, default=DEFAULT_QA_DIR)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args(argv)

    available = _load_current_proxy_names() if args.verify_proxies else None
    if args.write:
        json_path, md_path, validation = write_qa_artifacts(
            args.qa_dir,
            args.repository_root,
            available,
        )
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        print(json_path)
        print(md_path)
        return 0

    ledgers = build_all_ledgers(args.repository_root)
    validation = validate_ledgers(
        ledgers,
        repository_root=args.repository_root,
        available_proxies_by_state=available,
    )
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    return 0 if validation["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
