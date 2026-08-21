from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from readiness import (  # noqa: E402
    analyze_and_write,
    dvpr,
    requirements,
    risks,
    traceability_integrity,
    write_production_bom,
)


class _Bounds:
    def __init__(self, scale: float):
        self.xlen = scale
        self.ylen = scale
        self.zlen = scale


class _Solid:
    def __init__(self, volume: float):
        self._volume = volume

    def Volume(self) -> float:
        return self._volume

    def BoundingBox(self) -> _Bounds:
        return _Bounds(self._volume ** (1.0 / 3.0))


class _Candidate:
    def __init__(
        self,
        name: str,
        mass_kg: float,
        volume: float,
        *,
        occurrence_id: str = "",
        identity_basis: str = "LEGACY_NAME",
        option_code: str = "BASE",
    ):
        self.name = name
        self.mass_kg = mass_kg
        self.quantity = 1
        self.material = "test material"
        self.process = "test process"
        self.vendor = ""
        self.vendor_part_number = ""
        self.maturity = "custom"
        self.source_url = ""
        self.solid = _Solid(volume)
        self.physical_occurrence_id = occurrence_id
        self.identity_basis = identity_basis
        self.option_code = option_code
        self.include_in_ebom = True
        self.definition_revision = "TEST-A"


class ReadinessIntegrityTests(unittest.TestCase):
    def test_traceability_links_are_structurally_complete(self) -> None:
        result = traceability_integrity(requirements(), risks(), dvpr())
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["counts"]["requirements"], 36)
        self.assertEqual(result["counts"]["risks"], 40)
        self.assertEqual(result["counts"]["tests"], 49)

    def test_same_canonical_name_with_different_mass_or_volume_is_a_conflict(self) -> None:
        configs = {
            "stowed": [_Candidate("desk_yoke_right", 0.5564, 1000.0)],
            "seat": [_Candidate("desk_yoke_right", 0.2624, 800.0)],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = write_production_bom(configs, Path(directory) / "production_bom.csv")
        self.assertEqual(result["definition_conflicts"], 1)
        self.assertGreater(result["configuration_mass_spread_kg"], 0.001)
        self.assertEqual(result["pose_identity_status"], "NOT_DEMONSTRATED")

    def test_controlled_occurrence_identity_can_be_demonstrated_across_pose_names(self) -> None:
        configs = {
            "stowed": [
                _Candidate(
                    "mast_inner_stowed",
                    1.0,
                    1000.0,
                    occurrence_id="WC-MAST-INNER",
                    identity_basis="CONTROLLED_ID",
                )
            ],
            "seat": [
                _Candidate(
                    "mast_inner_seat",
                    1.0,
                    1000.0,
                    occurrence_id="WC-MAST-INNER",
                    identity_basis="CONTROLLED_ID",
                )
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = write_production_bom(configs, Path(directory) / "production_bom.csv")
        self.assertEqual(result["pose_identity_status"], "DEMONSTRATED")
        self.assertTrue(result["base_pose_occurrence_sets_invariant"])
        self.assertEqual(result["controlled_occurrence_identity_percent"], 100.0)

    def test_legacy_name_identity_cannot_silently_close_pose_identity(self) -> None:
        configs = {
            "stowed": [_Candidate("same_name", 1.0, 1000.0)],
            "seat": [_Candidate("same_name", 1.0, 1000.0)],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = write_production_bom(configs, Path(directory) / "production_bom.csv")
        self.assertTrue(result["base_pose_occurrence_sets_invariant"])
        self.assertEqual(result["configuration_mass_spread_kg"], 0.0)
        self.assertEqual(result["pose_identity_status"], "NOT_DEMONSTRATED")

    def test_failed_model_reports_reopen_readiness_gates(self) -> None:
        configs = {"stowed": [_Candidate("probe", 1.0, 1000.0)]}
        reports = {
            "geometry": {"checks": [{"check": "probe_geometry", "pass": False}]},
            "engineering": {"checks": []},
            "mobility": {"checks": []},
            "power_thermal": {"checks": [{"check": "probe_power", "pass": False}]},
        }
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_and_write(configs, reports, Path(directory))
        gates = {row["gate_id"]: row for row in result["gates"]}
        self.assertEqual(gates["G-017"]["status"], "open")
        self.assertEqual(gates["G-021"]["status"], "open")


if __name__ == "__main__":
    unittest.main()
