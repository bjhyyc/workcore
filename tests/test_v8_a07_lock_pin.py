from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cadquery as cq
from cadquery import exporters, importers


ROOT = Path(__file__).resolve().parents[1]
CLASS_A = (
    ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
)
for path in (ROOT, CLASS_A):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from skin_common import SkinPart  # noqa: E402
from exterior_presentation import exterior_parts  # noqa: E402
from source_disposition import _replace_policy  # noqa: E402
from v8_final_appearance_closure import (  # noqa: E402
    A07_FOCUS_STROKE_MM,
    A07_LOCK_BORE_DIAMETER_MM,
    A07_LOCK_FOCUS_BORE_Z_MM,
    A07_LOCK_LOW_BORE_Z_MM,
    A07_LOCK_PIN_RETRACTED_X_MM,
    A07_LOCK_PIN_Y_MM,
    A07_LOCK_STATION_Z_MM,
    _production_a07_low_masters,
    _production_mast_layout,
    a07_lock_motion_pose,
)
from v8_release_gates import (  # noqa: E402
    _GateBook,
    _gate_a07_positive_lock_interlock,
)


COMMON_VOLUME_TOLERANCE_MM3 = 1.0e-5


def x_cylinder(radius: float, y_mm: float, z_mm: float) -> cq.Shape:
    return cq.Solid.makeCylinder(
        radius,
        68.0,
        cq.Vector(276.0, y_mm, z_mm),
        cq.Vector(1.0, 0.0, 0.0),
    )


def source_identity(name: str, state: str) -> SkinPart:
    return SkinPart(
        name=name,
        shape=cq.Workplane("XY").box(1.0, 1.0, 1.0).val(),
        color=(0.5, 0.5, 0.5, 1.0),
        material="controlled source identity",
        module="A07",
        configuration=state,
        intent="test identity carrier",
        metadata={"physical_occurrence_id": f"SOURCE-{name}"},
    )


class V8A07PositiveLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.master = _production_a07_low_masters()

    def test_two_discrete_endpoint_hole_sets_leave_a_real_midspan_web(self) -> None:
        moving = self.master["moving"]
        bearing_radius = A07_LOCK_BORE_DIAMETER_MM / 2.0 + 0.25
        for y_mm in (-A07_LOCK_PIN_Y_MM, A07_LOCK_PIN_Y_MM):
            for z_mm in (A07_LOCK_FOCUS_BORE_Z_MM, A07_LOCK_LOW_BORE_Z_MM):
                bearing_probe = x_cylinder(bearing_radius, y_mm, z_mm)
                self.assertGreater(
                    float(moving.intersect(bearing_probe).Volume()),
                    40.0,
                )
            web_probe = x_cylinder(
                2.0,
                y_mm,
                (A07_LOCK_FOCUS_BORE_Z_MM + A07_LOCK_LOW_BORE_Z_MM) / 2.0,
            )
            self.assertGreater(float(moving.intersect(web_probe).Volume()), 80.0)

    def test_pins_engage_only_at_endpoints_and_retract_for_full_sweep(self) -> None:
        for stroke in (0.0, 70.0, 140.0, 210.0, 280.0, 350.0, 420.0):
            with self.subTest(stroke_mm=stroke):
                pose = a07_lock_motion_pose(stroke)
                endpoint = stroke in {0.0, A07_FOCUS_STROKE_MM}
                self.assertEqual(
                    pose.pin_state,
                    "engaged" if endpoint else "retracted",
                )
                self.assertLessEqual(
                    float(pose.fixed_sleeve.intersect(pose.moving_spine).Volume()),
                    COMMON_VOLUME_TOLERANCE_MM3,
                )
                self.assertGreaterEqual(
                    float(pose.fixed_sleeve.distance(pose.moving_spine)),
                    3.0,
                )
                if endpoint:
                    self.assertAlmostEqual(
                        pose.active_bore_master_z_mm + stroke,  # type: ignore[operator]
                        A07_LOCK_STATION_Z_MM,
                        places=6,
                    )
                else:
                    self.assertIsNone(pose.active_bore_master_z_mm)
                for pin in pose.lock_pins:
                    self.assertLessEqual(
                        float(pin.intersect(pose.moving_spine).Volume()),
                        COMMON_VOLUME_TOLERANCE_MM3,
                    )
                    self.assertLessEqual(
                        float(pin.intersect(pose.fixed_sleeve).Volume()),
                        COMMON_VOLUME_TOLERANCE_MM3,
                    )
                    self.assertAlmostEqual(
                        float(pin.distance(pose.fixed_sleeve)),
                        0.25,
                        delta=0.02,
                    )
                    if endpoint:
                        self.assertAlmostEqual(
                            float(pin.distance(pose.moving_spine)),
                            0.25,
                            delta=0.02,
                        )
                    else:
                        self.assertLessEqual(
                            float(pin.BoundingBox().xmax),
                            A07_LOCK_PIN_RETRACTED_X_MM[1] + 1.0e-6,
                        )
                        self.assertGreaterEqual(
                            float(pin.distance(pose.moving_spine)),
                            5.0,
                        )

        # Continuous proof: this box is a conservative superset of every
        # retracted-pin location in the moving spine's inverse stroke frame.
        moving = self.master["moving"]
        for y_mm in (-A07_LOCK_PIN_Y_MM, A07_LOCK_PIN_Y_MM):
            swept_superset = (
                cq.Workplane("XY")
                .box(11.0, 8.0, 428.0)
                .translate((270.5, y_mm, 678.0))
                .val()
            )
            self.assertLessEqual(
                float(moving.intersect(swept_superset).Volume()),
                COMMON_VOLUME_TOLERANCE_MM3,
            )
            self.assertGreaterEqual(float(moving.distance(swept_superset)), 5.0)

    def test_released_state_layout_contains_pins_separate_from_witness_lenses(self) -> None:
        required = (
            "A07_mast_fixed_outer_sleeve",
            "A07_mast_moving_inner_sleeve",
            "A07_sensor_beam_shell",
            "A07_sensor_beam_smoked_window",
            "A07_physical_privacy_shutter",
            "A07_microphone_acoustic_mesh",
            "A07_environment_sensor_grille",
        )
        for state in ("ride", "focus"):
            with self.subTest(state=state):
                parts = [source_identity(name, state) for name in required]
                _production_mast_layout(state, parts)
                by_name = {part.name: part for part in parts}
                moving = by_name["A07_mast_moving_inner_sleeve"]
                fixed = by_name["A07_mast_fixed_outer_sleeve"]
                for side_name in ("left", "right"):
                    pin = by_name[f"A07_mast_lock_pin_{side_name}"]
                    lens = by_name[
                        f"A07_mast_lock_pin_confirmation_lens_{side_name}"
                    ]
                    self.assertTrue(
                        pin.metadata["pin_is_structural_not_confirmation_lens"]
                    )
                    self.assertFalse(lens.metadata["structural_lock_credit"])
                    self.assertNotEqual(
                        pin.metadata["physical_occurrence_id"],
                        lens.metadata["physical_occurrence_id"],
                    )
                    self.assertLessEqual(
                        float(pin.shape.intersect(moving.shape).Volume()),
                        COMMON_VOLUME_TOLERANCE_MM3,
                    )
                    self.assertLessEqual(
                        float(lens.shape.intersect(fixed.shape).Volume()),
                        COMMON_VOLUME_TOLERANCE_MM3,
                    )
                    self.assertAlmostEqual(
                        float(lens.shape.distance(fixed.shape)),
                        0.3,
                        places=5,
                    )

    def test_follow_uses_low_state_a07_inventory_and_exposes_lock_lenses(self) -> None:
        required = (
            "A07_mast_fixed_outer_sleeve",
            "A07_mast_moving_inner_sleeve",
            "A07_sensor_beam_shell",
            "A07_sensor_beam_smoked_window",
            "A07_physical_privacy_shutter",
            "A07_microphone_acoustic_mesh",
            "A07_environment_sensor_grille",
        )
        states: dict[str, list[SkinPart]] = {}
        for state in ("follow", "ride"):
            parts = [source_identity(name, state) for name in required]
            _production_mast_layout(state, parts)
            states[state] = parts

        inventories = {
            state: {
                part.name: part.metadata.get("physical_occurrence_id")
                for part in parts
                if part.module == "A07"
            }
            for state, parts in states.items()
        }
        self.assertEqual(inventories["follow"], inventories["ride"])
        self.assertFalse(
            any(
                part.name.startswith("A07_follow_")
                for part in states["follow"]
            )
        )

        visible, _ = exterior_parts("follow", states["follow"])
        visible_names = {part.name for part in visible}
        for side_name in ("left", "right"):
            self.assertIn(
                f"A07_mast_lock_pin_confirmation_lens_{side_name}",
                visible_names,
            )

    def test_follow_only_mast_cover_fails_closed_in_exterior_bill(self) -> None:
        cover = source_identity("A07_follow_spine_cassette_cover", "follow")
        cover.metadata["final_exterior_visible"] = True
        visible, report = exterior_parts("follow", [cover])
        self.assertEqual(visible, [])
        self.assertEqual(
            report["hidden_occurrences"],
            [
                {
                    "name": "A07_follow_spine_cassette_cover",
                    "reason": "forbidden_follow_only_a07_cover",
                }
            ],
        )

    def test_out_of_range_stroke_fails_closed(self) -> None:
        for stroke in (-0.1, A07_FOCUS_STROKE_MM + 0.1):
            with self.subTest(stroke_mm=stroke):
                with self.assertRaises(ValueError):
                    a07_lock_motion_pose(stroke)

    def test_source_pin_maps_to_real_pin_and_nonstructural_witness(self) -> None:
        for side_token, side_name in (("-1", "left"), ("+1", "right")):
            decision = _replace_policy(
                "ride",
                f"mast_lock_pin_ride_{side_token}",
            )
            self.assertIsNotNone(decision)
            self.assertEqual(
                decision.proxy_names,
                (
                    f"A07_mast_lock_pin_{side_name}",
                    f"A07_mast_lock_pin_confirmation_lens_{side_name}",
                ),
            )

    def test_release_gate_records_no_a07_lock_failure(self) -> None:
        required = (
            "A07_mast_fixed_outer_sleeve",
            "A07_mast_moving_inner_sleeve",
            "A07_sensor_beam_shell",
            "A07_sensor_beam_smoked_window",
            "A07_physical_privacy_shutter",
            "A07_microphone_acoustic_mesh",
            "A07_environment_sensor_grille",
        )
        states: dict[str, list[SkinPart]] = {}
        for state in ("follow", "ride", "cafe", "focus"):
            parts = [source_identity(name, state) for name in required]
            _production_mast_layout(state, parts)
            states[state] = parts
        book = _GateBook()
        _gate_a07_positive_lock_interlock(states, book)
        failures = [check["id"] for check in book.checks if not check["pass"]]
        self.assertEqual(failures, [])
        self.assertEqual(len(book.checks), 13)

    def test_lock_master_step_roundtrip_preserves_solid_and_volume(self) -> None:
        shapes = {
            "fixed": self.master["fixed"],
            "moving": self.master["moving"],
            "pin": self.master["lock_pin_engaged_left"],
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, shape in shapes.items():
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.step"
                    exporters.export(shape, str(path))
                    restored = importers.importStep(str(path)).val()
                    self.assertTrue(restored.isValid())
                    self.assertEqual(len(restored.Solids()), 1)
                    relative_volume_delta = abs(
                        float(restored.Volume()) - float(shape.Volume())
                    ) / float(shape.Volume())
                    self.assertLessEqual(relative_volume_delta, 1.0e-5)


if __name__ == "__main__":
    unittest.main()
