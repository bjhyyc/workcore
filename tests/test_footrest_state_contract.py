from __future__ import annotations

import unittest
from functools import lru_cache

from cad.build import build_configuration, validate_footrest_contract
from cad.footrest_state import (
    FootrestPose,
    default_footrest_pose,
    optional_footrest_open_available,
    resolve_footrest_pose,
)


@lru_cache(maxsize=1)
def _primary_configurations_and_checks():
    configurations = {
        name: build_configuration(name)
        for name in ("follow", "seat", "cafe", "desk")
    }
    return configurations, validate_footrest_contract(configurations)


class FootrestStateContractTests(unittest.TestCase):
    def test_primary_footrest_pose_matrix_is_fail_closed(self) -> None:
        self.assertIs(default_footrest_pose("follow"), FootrestPose.STOWED)
        self.assertIs(default_footrest_pose("seat"), FootrestPose.DEPLOYED_LOCKED)
        self.assertIs(default_footrest_pose("cafe"), FootrestPose.STOWED)
        self.assertIs(default_footrest_pose("desk"), FootrestPose.STOWED)
        self.assertTrue(optional_footrest_open_available("cafe"))
        self.assertTrue(optional_footrest_open_available("desk"))
        self.assertFalse(optional_footrest_open_available("follow"))
        self.assertFalse(optional_footrest_open_available("seat"))
        with self.assertRaises(ValueError):
            resolve_footrest_pose("follow", FootrestPose.DEPLOYED_LOCKED)
        with self.assertRaises(ValueError):
            resolve_footrest_pose("unknown-mode")

    def test_a08_has_one_six_occurrence_definition_in_every_primary_pose(self) -> None:
        _, checks = _primary_configurations_and_checks()
        identity_check_names = {
            "a08_primary_pose_and_occurrence_inventory",
            "a08_cross_pose_definition_material_mass_conservation",
        }
        failures = [
            check
            for check in checks
            if check["check"] in identity_check_names and not check["pass"]
        ]
        self.assertFalse(failures, failures)

    def test_current_a08_motion_is_fail_closed_until_real_guides_and_interlock_exist(
        self,
    ) -> None:
        _, checks = _primary_configurations_and_checks()
        by_configuration_and_name = {
            (check["configuration"], check["check"]): check for check in checks
        }

        for configuration in ("cafe_footrest_open", "desk_footrest_open"):
            internal = by_configuration_and_name[
                (configuration, "a08_stow_to_open_101_point_internal_clearance")
            ]
            self.assertFalse(internal["pass"])
            self.assertTrue(internal["failures"])
            maximum_common = max(
                hit["common_volume_mm3"]
                for sample in internal["failures"]
                for hit in sample["exact_interferences"]
            )
            self.assertAlmostEqual(maximum_common, 17_272.5, delta=0.01)

            human = by_configuration_and_name[
                (
                    configuration,
                    "a08_occupied_floor_route_requires_safety_rated_clear_interlock",
                )
            ]
            self.assertFalse(human["pass"])
            self.assertTrue(human["occupied_sweep_hit_samples"])
            self.assertEqual(human["controlled_interlock_occurrences"], [])

            load_path = by_configuration_and_name[
                (
                    configuration,
                    "a08_support_fixed_hinge_or_captured_guide_load_path",
                )
            ]
            self.assertFalse(load_path["pass"])
            self.assertEqual(load_path["captured_guide_occurrences"], [])
            for side in ("left", "right"):
                self.assertAlmostEqual(
                    load_path["side_evidence"][side][
                        "minimum_endpoint_drift_mm"
                    ],
                    82.5,
                    delta=1.0e-6,
                )

    def test_cafe_and_focus_optional_open_use_the_same_occurrence_ids_and_mass(self) -> None:
        for configuration in ("cafe", "desk"):
            stowed = {
                part.physical_occurrence_id: part
                for part in build_configuration(configuration)
                if part.name.startswith("footrest_")
            }
            opened = {
                part.physical_occurrence_id: part
                for part in build_configuration(
                    configuration,
                    FootrestPose.DEPLOYED_LOCKED,
                )
                if part.name.startswith("footrest_")
            }
            self.assertEqual(set(stowed), set(opened))
            self.assertEqual(len(stowed), 6)
            self.assertAlmostEqual(
                sum(part.mass_kg for part in stowed.values()),
                sum(part.mass_kg for part in opened.values()),
                delta=1.0e-9,
            )
            for occurrence_id in stowed:
                self.assertAlmostEqual(
                    stowed[occurrence_id].volume_mm3,
                    opened[occurrence_id].volume_mm3,
                    delta=0.01,
                )
                self.assertEqual(
                    stowed[occurrence_id].material,
                    opened[occurrence_id].material,
                )
                self.assertEqual(
                    stowed[occurrence_id].definition_revision,
                    opened[occurrence_id].definition_revision,
                )


if __name__ == "__main__":
    unittest.main()
