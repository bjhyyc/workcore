"""Exterior-only presentation policy for the WorkCore E6 layout freeze.

The parametric state assembly deliberately contains mechanism B-Reps used for
packaging and endpoint collision checks.  Those are not all Class-A exterior
occurrences.  Final product renders and the exterior STEP therefore use this
fail-closed visibility policy, while the full layout STEP and QA GLB retain the
complete mechanism inventory.

This module never deletes a physical occurrence from the layout assembly.  It
only decides whether an occurrence belongs to the visible exterior bill for a
given locked product state.
"""

from __future__ import annotations

from collections.abc import Iterable

from skin_common import SkinPart


_ALWAYS_INTERNAL_NAMES = frozenset(
    {
        # A01 sensing modules sit behind one continuous smoked horizon.
        "A01_perception_horizon_carrier",
        "A01_front_left_tof_window",
        "A01_front_right_tof_window",
        "A01_front_leg_scanner_window",
        # A06 load-path hardware remains behind the fixed root shoulder field.
        "A06_backrest_hinge_shaft",
        "A06_backrest_hinge_bearing_left",
        "A06_backrest_hinge_bearing_right",
        "A06_backrest_positive_lock_left",
        "A06_backrest_positive_lock_right",
        # A07 hardened lock pins are structural internals; only their separate
        # mechanically linked confirmation lenses are exterior occurrences.
        "A07_mast_lock_pin_left",
        "A07_mast_lock_pin_right",
        # A08 safety channels share the A01 smoked horizon instead of becoming
        # two extra robot-eye objects.
        "A08_foot_zone_interlock_channel_a",
        "A08_foot_zone_interlock_channel_b",
        "A08_footrest_counterbalance_cartridge",
        "A08_footrest_manual_release_actuator",
        "A08_footrest_manual_release_cable",
        "A08_footrest_rear_labyrinth_baffle",
        "A08_footrest_synchronising_cross_shaft",
    }
)


_ALWAYS_INTERNAL_PREFIXES = (
    # These gasket backings live behind the flush service caps and are never
    # separate cosmetic islands.
    "A03_wheel_end_service_seam_backing_",
    "A03_rocker_pivot_service_seam_backing_",
    # The removable integrated side sail is the weather surface.  These
    # equipment-bay items remain in the complete layout for authorised access.
    "A04_upper_equipment_door_",
    "A04_upper_equipment_release_",
    "A04_side_uwb_radome_",
    "A04_side_uwb_replaceable_bezel_",
    "A08_footrest_captured_inner_rail_",
    "A08_footrest_deployed_lock_pin_",
    "A08_footrest_drop_link_",
    "A08_footrest_fixed_guide_housing_",
    "A08_footrest_primary_cartridge_",
    "A08_footrest_stowed_lock_pin_",
    # The Café rail, bearings and guide shoes remain under the single smooth
    # motion belly; they are not separate exterior styling elements.
    "A09_cafe_fixed_root_housing_",
    "A09_cafe_fixed_yoke_bearing_carrier_",
    "A09_cafe_rotary_hub_",
    "A09_cafe_rotary_linear_rail_",
    "A09_cafe_telescopic_rail_cover_",
    "A09_cafe_linear_guide_shoe_",
    "A09_cafe_table_mount_shoe_",
)


_FOLLOW_ONLY_A07_COVER_TOKENS = (
    "cover",
    "cowl",
    "lid",
    "shroud",
    "vault",
)


# The production mast is one state-invariant physical package.  Follow changes
# only its shared A06 hinge pose; it does not switch to a smaller exterior bill
# or gain a state-only cassette cover.  Freeze the bill here so visibility
# metadata cannot accidentally hide a real mast surface or expose a lock pin.
A07_CANONICAL_EXTERIOR_NAMES = frozenset(
    {
        "A07_mast_fixed_outer_sleeve",
        "A07_mast_moving_inner_sleeve",
        "A07_sensor_beam_shell",
        "A07_sensor_beam_smoked_window",
        "A07_physical_privacy_shutter",
        "A07_microphone_acoustic_mesh",
        "A07_environment_sensor_grille",
        "A07_fill_light_visible_window_left",
        "A07_fill_light_visible_window_right",
        "A07_privacy_shutter_carriage_bezel",
        "A07_mast_throat_weather_gasket",
        "A07_mast_lock_pin_confirmation_lens_left",
        "A07_mast_lock_pin_confirmation_lens_right",
    }
)
A07_CANONICAL_INTERNAL_NAMES = frozenset(
    {
        "A07_mast_lock_pin_left",
        "A07_mast_lock_pin_right",
    }
)


def _is_forbidden_follow_only_a07_cover(part: SkinPart) -> bool:
    """Reject render-only A07 covers that exist solely in Follow.

    Follow uses the same exposed mast occurrences as the low states and changes
    only their shared-hinge pose.  A state-named cover must therefore fail
    closed even if a temporary renderer marks it explicitly visible.
    """

    name = part.name.lower()
    return (
        part.module == "A07"
        and name.startswith("a07_follow_")
        and any(token in name for token in _FOLLOW_ONLY_A07_COVER_TOKENS)
    )


def exterior_visibility_reason(state: str, part: SkinPart) -> tuple[bool, str]:
    """Return whether *part* belongs in the locked-state exterior bill."""

    if state == "follow" and _is_forbidden_follow_only_a07_cover(part):
        return False, "forbidden_follow_only_a07_cover"

    if part.name in _ALWAYS_INTERNAL_NAMES or part.name.startswith(
        _ALWAYS_INTERNAL_PREFIXES
    ):
        return False, "enclosed_mechanism_or_named_internal_backing"

    if part.module == "A07":
        if part.name in A07_CANONICAL_INTERNAL_NAMES:
            return False, "canonical_internal_a07_lock_hardware"
        if part.name in A07_CANONICAL_EXTERIOR_NAMES:
            return True, "canonical_four_state_exposed_a07"
        if any(
            token in part.name.lower()
            for token in _FOLLOW_ONLY_A07_COVER_TOKENS
        ):
            return False, "forbidden_noncanonical_a07_cover"
        return False, "noncanonical_a07_occurrence"

    explicit = part.metadata.get("final_exterior_visible")
    if explicit is not None:
        return bool(explicit), "explicit_part_metadata"

    name = part.name
    if (
        state == "follow"
        and name
        not in {
            "A07_mast_fixed_outer_sleeve",
            "A07_mast_throat_weather_gasket",
        }
        and str(part.metadata.get("presentation_visibility", "")).startswith(
            ("enclosed_", "internal_")
        )
    ):
        return False, "metadata_declares_locked_state_internal_stowage"
    if name.startswith("A08_footrest_") and (
        "bearing" in name or "guarded_pin" in name
    ):
        return False, "captured_inside_a08_support_monocoque"

    if name.startswith("A08_footrest_") and "lock_witness" in name:
        return False, "lock_witness_read_through_single_manual_release_interface"

    # The same support and undertray B-Reps remain in every state, but only
    # become exterior surfaces after the Ride platform leaves its fixed pocket.
    if state != "ride" and name in {
        "A08_footrest_top_skin",
        "A08_footrest_inset_tread",
        "A08_footrest_perimeter_skin",
        "A08_footrest_platform_undertray_monocoque",
        "A08_footrest_support_monocoque_left",
        "A08_footrest_support_monocoque_right",
    }:
        return False, "conserved_occurrence_hidden_inside_stowed_a08_pocket"

    return True, "class_a_or_deliberately_exposed_functional_surface"


def exterior_parts(
    state: str,
    parts: Iterable[SkinPart],
) -> tuple[list[SkinPart], dict[str, object]]:
    """Return the exterior bill and a traceable visibility report."""

    all_parts = list(parts)
    visible: list[SkinPart] = []
    hidden: list[dict[str, str]] = []
    for part in all_parts:
        is_visible, reason = exterior_visibility_reason(state, part)
        if is_visible:
            visible.append(part)
        else:
            hidden.append({"name": part.name, "reason": reason})
    return visible, {
        "state": state,
        "full_layout_occurrence_count": len(all_parts),
        "exterior_occurrence_count": len(visible),
        "internal_or_occluded_occurrence_count": len(hidden),
        "hidden_occurrences": hidden,
        "physical_occurrences_deleted_from_layout": False,
    }
