from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cadquery as cq


CLASS_A_CAD = (
    Path(__file__).resolve().parents[1]
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
)
sys.path.insert(0, str(CLASS_A_CAD))

from skin_upper import BACK_FOLD_DEG, BACK_HINGE, BACK_RAKE_DEG  # noqa: E402
from skin_lower import _rear_service_frame  # noqa: E402
from v8_final_appearance_closure import (  # noqa: E402
    A06_LOCK_PIN_RETRACTION_MM,
    _a06_fixed_manual_release,
    _fixed_backrest_root_shoulder_master,
    _production_backrest_channel_master,
    _production_backrest_contact_panel_master,
    _production_backrest_hinge_bearing_master,
    _production_backrest_hinge_shaft_master,
    _production_backrest_positive_lock_pin,
)


def _rotate_about_back_hinge(shape: cq.Shape, degrees: float) -> cq.Shape:
    x, y, z = BACK_HINGE
    return shape.rotate((x, y, z), (x, y + 1.0, z), degrees)


class V8A06ContinuousFoldContractTests(unittest.TestCase):
    def test_real_shaft_bearings_and_both_endpoint_detents(self) -> None:
        shaft_master = _production_backrest_hinge_shaft_master()
        shell_master = _production_backrest_channel_master()
        self.assertTrue(shaft_master.isValid())
        self.assertEqual(len(shaft_master.Solids()), 1)
        self.assertEqual(shell_master.intersect(shaft_master).Volume(), 0.0)
        self.assertAlmostEqual(shell_master.distance(shaft_master), 0.5, delta=1.0e-6)

        upright = _rotate_about_back_hinge(shaft_master, BACK_RAKE_DEG)
        follow = _rotate_about_back_hinge(upright, BACK_FOLD_DEG)
        for side in (-1, 1):
            bearing = _production_backrest_hinge_bearing_master(side)
            pin = _production_backrest_positive_lock_pin(side)
            self.assertTrue(bearing.isValid())
            self.assertEqual(len(bearing.Solids()), 1)
            for endpoint in (upright, follow):
                self.assertLessEqual(endpoint.intersect(bearing).Volume(), 1.0e-6)
                self.assertGreaterEqual(endpoint.distance(bearing), 0.699999)
                self.assertLessEqual(endpoint.intersect(pin).Volume(), 1.0e-6)
                self.assertAlmostEqual(endpoint.distance(pin), 0.3, delta=1.0e-5)
            self.assertLessEqual(pin.intersect(bearing).Volume(), 1.0e-6)
            self.assertAlmostEqual(pin.distance(bearing), 0.3, delta=1.0e-6)

        release = _a06_fixed_manual_release()
        self.assertTrue(release.isValid())
        self.assertEqual(len(release.Solids()), 1)
        rear_surround = next(
            part.shape
            for part in _rear_service_frame("ride")
            if part.name == "A10_rear_service_surround"
        )
        self.assertLessEqual(
            float(release.intersect(rear_surround).Volume()),
            1.0e-6,
        )
        self.assertGreaterEqual(float(release.distance(rear_surround)), 3.0)

    def test_retracted_redundant_locks_clear_complete_101_pose_fold(self) -> None:
        shaft = _rotate_about_back_hinge(
            _production_backrest_hinge_shaft_master(),
            BACK_RAKE_DEG,
        )
        shell = _rotate_about_back_hinge(
            _production_backrest_channel_master(),
            BACK_RAKE_DEG,
        )
        fixed_hardware = cq.Compound.makeCompound(
            [
                _production_backrest_hinge_bearing_master(-1),
                _production_backrest_hinge_bearing_master(1),
                _production_backrest_positive_lock_pin(-1).translate(
                    (0.0, 0.0, A06_LOCK_PIN_RETRACTION_MM)
                ),
                _production_backrest_positive_lock_pin(1).translate(
                    (0.0, 0.0, A06_LOCK_PIN_RETRACTION_MM)
                ),
            ]
        )
        shaft_clearances: list[tuple[float, float]] = []
        shell_clearances: list[tuple[float, float]] = []
        for index in range(101):
            fold_degrees = BACK_FOLD_DEG * index / 100.0
            shaft_clearances.append(
                (
                    fold_degrees,
                    _rotate_about_back_hinge(
                        shaft,
                        fold_degrees,
                    ).distance(fixed_hardware),
                )
            )
            shell_clearances.append(
                (
                    fold_degrees,
                    _rotate_about_back_hinge(
                        shell,
                        fold_degrees,
                    ).distance(fixed_hardware),
                )
            )

        self.assertGreaterEqual(
            min(value for _, value in shaft_clearances),
            0.699999,
            shaft_clearances,
        )
        self.assertGreaterEqual(
            min(value for _, value in shell_clearances),
            4.775,
            shell_clearances,
        )

    def test_same_trapezoid_clears_both_fixed_root_shoulders_at_77_poses(self) -> None:
        """The final A06 B-Reps, not a proxy box, own the complete fold sweep."""

        shell = _rotate_about_back_hinge(
            _production_backrest_channel_master(),
            BACK_RAKE_DEG,
        )
        contact = _rotate_about_back_hinge(
            _production_backrest_contact_panel_master(),
            BACK_RAKE_DEG,
        )
        moving_master = cq.Compound.makeCompound([shell, contact])
        fixed_shoulders = cq.Compound.makeCompound(
            [
                _fixed_backrest_root_shoulder_master(-1),
                _fixed_backrest_root_shoulder_master(1),
            ]
        )

        samples: list[tuple[float, float]] = []
        for index in range(77):
            fold_degrees = BACK_FOLD_DEG * index / 76.0
            posed = _rotate_about_back_hinge(moving_master, fold_degrees)
            samples.append((fold_degrees, float(posed.distance(fixed_shoulders))))

        minimum_angle, minimum_clearance = min(samples, key=lambda item: item[1])
        self.assertGreaterEqual(
            minimum_clearance,
            4.0 - 1.0e-6,
            (minimum_angle, minimum_clearance, samples),
        )

    def test_contact_island_remains_a_dry_rigid_part_of_same_fold(self) -> None:
        shell = _rotate_about_back_hinge(
            _production_backrest_channel_master(),
            BACK_RAKE_DEG,
        )
        contact = _rotate_about_back_hinge(
            _production_backrest_contact_panel_master(),
            BACK_RAKE_DEG,
        )
        reference_clearance = float(shell.distance(contact))

        for fold_degrees in (0.0, BACK_FOLD_DEG / 2.0, BACK_FOLD_DEG):
            posed_shell = _rotate_about_back_hinge(shell, fold_degrees)
            posed_contact = _rotate_about_back_hinge(contact, fold_degrees)
            self.assertAlmostEqual(
                float(posed_shell.distance(posed_contact)),
                reference_clearance,
                delta=1.0e-6,
            )
            self.assertGreaterEqual(reference_clearance, 3.9)


if __name__ == "__main__":
    unittest.main()
