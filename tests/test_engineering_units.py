from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from engineering import (  # noqa: E402
    _part_mass_point,
    circular_tube_section,
    rectangular_solid_section,
    required_proof_target_n_m,
    square_tube_section,
)
from mobility import _fit_clearance  # noqa: E402
from parameters import P  # noqa: E402
from power_thermal import _voltage_drop  # noqa: E402


class EngineeringUnitTests(unittest.TestCase):
    def test_mass_point_honours_part_quantity(self) -> None:
        class Centre:
            x, y, z = 1.0, 2.0, 3.0

        class Solid:
            @staticmethod
            def Center():
                return Centre()

        class Candidate:
            name = "quantity_probe"
            mass_kg = 2.5
            quantity = 3
            solid = Solid()

        self.assertEqual(_part_mass_point(Candidate()).mass_kg, 7.5)

    def test_cafe_proof_target_is_a_monotonic_requirement(self) -> None:
        baseline = required_proof_target_n_m(100.0, 500.0)
        self.assertGreater(required_proof_target_n_m(120.0, 500.0), baseline)
        self.assertGreater(required_proof_target_n_m(100.0, 600.0), baseline)

    def test_rectangular_section_matches_closed_form(self) -> None:
        result = rectangular_solid_section(10.0, 50.0)
        expected_i = 10.0 * 50.0**3 / 12.0
        self.assertAlmostEqual(result["i_mm4"], expected_i)
        self.assertAlmostEqual(result["z_mm3"], expected_i / 25.0)

    def test_tube_sections_are_positive_and_less_than_solid(self) -> None:
        circular = circular_tube_section(20.0, 2.0)
        square = square_tube_section(40.0, 3.0)
        solid_circle_i = math.pi * 20.0**4 / 64.0
        solid_square_i = 40.0**4 / 12.0
        self.assertGreater(circular["i_mm4"], 0.0)
        self.assertLess(circular["i_mm4"], solid_circle_i)
        self.assertGreater(square["i_mm4"], 0.0)
        self.assertLess(square["i_mm4"], solid_square_i)

    def test_door_clearance_is_total_and_per_side(self) -> None:
        result = _fit_clearance(800.0, 721.0)
        self.assertAlmostEqual(result["total_clearance_mm"], 79.0)
        self.assertAlmostEqual(result["clearance_each_side_mm"], 39.5)
        self.assertTrue(result["pass"])

    def test_voltage_drop_uses_round_trip_length(self) -> None:
        result = _voltage_drop(48.0, 10.0, 2.0, 2.5)
        expected_resistance = 0.0175 * 2.0 / 2.5
        self.assertAlmostEqual(result["resistance_ohm"], expected_resistance)
        self.assertAlmostEqual(result["drop_v"], 10.0 * expected_resistance, places=3)

    def test_master_parameter_invariants(self) -> None:
        self.assertLessEqual(P.battery_usable_fraction + P.battery_emergency_reserve_fraction, 1.0)
        self.assertLessEqual(P.follow_speed_max_m_s, P.community_default_speed_m_s)
        self.assertLessEqual(P.community_default_speed_m_s, P.occupied_speed_max_m_s)
        self.assertEqual(P.cafe_creep_speed_m_s, 0.0)
        self.assertLess(P.wheel_x_front, P.wheel_x_rear)
        self.assertGreater(P.wheel_running_clearance, 0.0)
        self.assertGreaterEqual(P.travel_width_max - P.body_width, P.travel_width_production_reserve)


if __name__ == "__main__":
    unittest.main()
