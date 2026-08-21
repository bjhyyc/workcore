from __future__ import annotations

import sys
import unittest
from collections import defaultdict
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad"))

from build import table_parts  # noqa: E402


class ConfigurationIdentityTests(unittest.TestCase):
    def test_cafe_and_focus_tables_do_not_reuse_a_name_for_different_definitions(self) -> None:
        definitions: dict[str, set[tuple[float, float, str, str]]] = defaultdict(set)
        for configuration in ("cafe", "desk"):
            for candidate in table_parts(configuration):
                if candidate.name.startswith("desk_bundle_stowed_"):
                    continue
                definitions[candidate.name].add(
                    (
                        round(candidate.mass_kg, 6),
                        round(candidate.volume_mm3, 3),
                        candidate.material,
                        candidate.process,
                    )
                )
        conflicts = {
            name: sorted(signatures)
            for name, signatures in definitions.items()
            if len(signatures) > 1
        }
        self.assertEqual(conflicts, {})

    def test_cafe_transverse_yoke_and_focus_yoke_have_distinct_supplier_names(self) -> None:
        cafe_names = {candidate.name for candidate in table_parts("cafe")}
        focus_names = {candidate.name for candidate in table_parts("desk")}
        self.assertIn("desk_cafe_transverse_yoke_right", cafe_names)
        self.assertIn("desk_yoke_right", focus_names)
        self.assertNotIn("desk_yoke_right", cafe_names)


if __name__ == "__main__":
    unittest.main()
