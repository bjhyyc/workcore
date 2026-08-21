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

from build_class_a_skin import (  # noqa: E402
    STEP_ROUNDTRIP_LIMITS,
    _roundtrip_signature_failures,
    _shape_signature,
    _signature_delta,
)
from validate_class_a import (  # noqa: E402
    Checks,
    _part_from_object,
    _validate_wheel_contact_band_contract,
)
from skin_lower import build_lower_skin  # noqa: E402
from skin_common import LUNAR_STONE  # noqa: E402
from skin_upper import build_upper_skin  # noqa: E402
from v8_collision_partition import (  # noqa: E402
    _fix_a05_cassette_interfaces,
)
from v8_final_appearance_closure import (  # noqa: E402
    _continuous_wheel_belts,
    _fixed_backrest_root_shoulder_master,
    _fixed_right_armrest,
    _production_backrest_channel_master,
)
from v8_release_gates import (  # noqa: E402
    ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM,
    _within_locked_envelope_axis,
)
from v8_wheel_contract import (  # noqa: E402
    WHEEL_AXIS_Z_MM,
    WHEEL_END_CLOSED_PROBE_Z_MM,
    WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM,
    WHEEL_END_COVERAGE_PROBE_Z_MM,
    WHEEL_END_OPEN_PROBE_Z_MM,
    WHEEL_END_RETURN_LOWER_EDGE_Z_MM,
    WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM,
    WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
    WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
    WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM,
    WHEEL_MINIMUM_SWEPT_CLEARANCE_MM,
    WHEEL_NOMINAL_PRODUCT_WIDTH_MM,
    WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
    WHEEL_PRODUCTION_WIDTH_LIMIT_MM,
    WHEEL_SIDE_CLOSED_PROBE_Z_MM,
    WHEEL_SIDE_OPEN_PROBE_Z_MM,
    WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM,
)
from v8_wheel_hub_articulation import (  # noqa: E402
    wheel_belt_class_a_shell,
)


class V8StepRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = {
            "solid_count": 1,
            "face_count": 120,
            "edge_count": 240,
        }
        self.after = dict(self.before)

    def test_kernel_scale_mass_property_drift_is_accepted(self) -> None:
        delta = {
            "max_bound_abs_mm": 0.001,
            "centroid_max_abs_mm": 0.001,
            "volume_relative": 5.162389672e-6,
            "volume_absolute_mm3": 9.529713751,
            "area_relative": 1.191758725e-6,
            "area_absolute_mm2": 0.729210212,
        }
        self.assertLess(
            delta["volume_relative"],
            STEP_ROUNDTRIP_LIMITS["volume_relative"],
        )
        self.assertEqual(
            _roundtrip_signature_failures(self.before, self.after, delta),
            [],
        )

    def test_material_mass_property_drift_still_fails(self) -> None:
        delta = {
            "max_bound_abs_mm": 0.001,
            "centroid_max_abs_mm": 0.001,
            "volume_relative": 2.0e-5,
            "volume_absolute_mm3": 9.5,
            "area_relative": 2.0e-5,
            "area_absolute_mm2": 0.7,
        }
        failures = _roundtrip_signature_failures(
            self.before,
            self.after,
            delta,
        )
        self.assertEqual(len(failures), 2)
        self.assertTrue(any("volume delta" in item for item in failures))
        self.assertTrue(any("area delta" in item for item in failures))

    def test_solid_count_and_position_remain_fail_closed(self) -> None:
        after = dict(self.after)
        after["solid_count"] = 2
        delta = {
            "max_bound_abs_mm": 0.02,
            "centroid_max_abs_mm": 0.02,
            "volume_relative": 0.0,
            "volume_absolute_mm3": 0.0,
            "area_relative": 0.0,
            "area_absolute_mm2": 0.0,
        }
        failures = _roundtrip_signature_failures(self.before, after, delta)
        self.assertTrue(any("solid_count" in item for item in failures))
        self.assertTrue(any("bounds delta" in item for item in failures))
        self.assertTrue(any("centroid delta" in item for item in failures))

    def test_focus_internal_root_boxes_guides_and_necks_survive_step(self) -> None:
        parts = build_upper_skin("focus")
        by_name = {part.name: part for part in parts}

        with tempfile.TemporaryDirectory() as temp_dir:
            for side in ("left", "right"):
                names = (
                    f"A09_focus_internal_root_box_{side}",
                    *(
                        f"A09_focus_internal_nested_guide_stage_{index}_{side}"
                        for index in (1, 2, 3)
                    ),
                    f"A09_focus_table_hidden_root_tongue_{side}",
                )
                for name in names:
                    part = by_name[name]
                    before = part.shape
                    target = Path(temp_dir) / f"{name}.step"
                    exporters.export(before, str(target))
                    after = importers.importStep(str(target)).val()
                    before_signature = _shape_signature(before)
                    after_signature = _shape_signature(after)
                    delta = _signature_delta(before_signature, after_signature)
                    failures = _roundtrip_signature_failures(
                        before_signature,
                        after_signature,
                        delta,
                    )

                    with self.subTest(side=side, name=name):
                        self.assertTrue(after.isValid())
                        self.assertEqual(len(before.Solids()), 1)
                        self.assertEqual(len(after.Solids()), 1)
                        self.assertEqual(failures, [])
                        self.assertEqual(
                            part.metadata["final_exterior_visible"],
                            name.endswith(f"hidden_root_tongue_{side}"),
                        )

    def test_fixed_armrest_top_lids_and_releases_survive_step_without_side_doors(
        self,
    ) -> None:
        parts = build_lower_skin("ride") + build_upper_skin("ride")
        _fix_a05_cassette_interfaces("ride", parts)
        _fixed_right_armrest("ride", parts)
        by_name = {part.name: part for part in parts}

        self.assertFalse(
            any(
                name.startswith(
                    (
                        "A05_table_cassette_door_",
                        "A05_table_cassette_exit_bezel_",
                        "A05_table_cassette_throat_seal_",
                        "A05_table_cassette_shadow_horizon_",
                    )
                )
                for name in by_name
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            for side in ("left", "right"):
                names = (
                    f"A05_armrest_touch_lid_{side}",
                    f"A05_armrest_top_lid_hinge_reveal_{side}",
                    f"A05_armrest_top_lid_release_{side}",
                )
                for name in names:
                    path = Path(temp_dir) / f"{name}.step"
                    before = by_name[name]
                    exporters.export(before.shape, str(path))
                    after = importers.importStep(str(path)).val()
                    self.assertTrue(after.isValid())
                    self.assertEqual(len(after.Solids()), 1)
                    self.assertAlmostEqual(
                        float(after.Volume()),
                        float(before.shape.Volume()),
                        delta=max(1.0e-5, float(before.shape.Volume()) * 1.0e-8),
                    )

                lid = by_name[f"A05_armrest_touch_lid_{side}"]
                release = by_name[f"A05_armrest_top_lid_release_{side}"]
                self.assertTrue(lid.metadata["top_lid_outward_opening_enabled"])
                self.assertFalse(lid.metadata["full_armrest_side_opening_enabled"])
                self.assertEqual(lid.metadata["top_lid_open_angle_deg"], 105.0)
                self.assertTrue(release.metadata["manual_no_power"])
                self.assertTrue(release.metadata["two_action"])

    def test_a06_master_is_a_real_four_millimetre_hollow_shell(self) -> None:
        master = _production_backrest_channel_master()
        self.assertTrue(master.isValid())
        self.assertEqual(len(master.Solids()), 1)
        void_probe = (
            cq.Workplane("XY")
            .box(2.0, 2.0, 2.0)
            .translate((258.5, 150.0, 800.0))
            .val()
        )
        self.assertLessEqual(float(master.intersect(void_probe).Volume()), 1.0e-5)
        for y in (-230.0, 230.0):
            wall_probe = (
                cq.Workplane("XY")
                .box(1.0, 12.0, 1.0)
                .translate((258.5, y, 800.0))
                .val()
            )
            section = master.intersect(wall_probe)
            self.assertGreater(float(section.Volume()), 1.0e-5)
            self.assertGreaterEqual(float(section.BoundingBox().ylen), 3.8)
            self.assertLessEqual(float(section.BoundingBox().ylen), 4.2)

    def test_a04_root_shoulders_are_hollow_single_fixed_body_breps(self) -> None:
        for side in (-1, 1):
            shoulder = _fixed_backrest_root_shoulder_master(side)
            box = shoulder.BoundingBox()
            bbox_volume = box.xlen * box.ylen * box.zlen
            with self.subTest(side=side):
                self.assertTrue(shoulder.isValid())
                self.assertEqual(len(shoulder.Solids()), 1)
                self.assertGreater(float(shoulder.Volume()) / bbox_volume, 0.02)
                self.assertLess(float(shoulder.Volume()) / bbox_volume, 0.50)
                self.assertLessEqual(box.zmax, 511.001)

    def test_wheel_belt_enforces_axis_height_half_wrap(self) -> None:
        parts = build_lower_skin("ride")
        _continuous_wheel_belts("ride", parts)
        by_name = {part.name: part for part in parts}
        self.assertEqual(WHEEL_AXIS_Z_MM, 125.0)
        self.assertEqual(WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM, WHEEL_AXIS_Z_MM)
        self.assertEqual(WHEEL_END_RETURN_LOWER_EDGE_Z_MM, WHEEL_AXIS_Z_MM)
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            belt = by_name[f"A03_continuous_wheel_belt_shell_{side_name}"]
            class_a_belt_shell = wheel_belt_class_a_shell(
                belt.shape,
                side_name,
            )
            self.assertTrue(belt.metadata["tyre_lower_contact_band_visible"])
            self.assertTrue(belt.metadata["tyre_lower_contact_half_visible"])
            self.assertEqual(
                belt.metadata["lower_half_reveal_top_z_mm"],
                WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
            )
            self.assertTrue(
                belt.metadata["half_wrap_boundary_equals_wheel_axis"]
            )
            self.assertEqual(
                belt.metadata["nominal_product_width_mm"],
                WHEEL_NOMINAL_PRODUCT_WIDTH_MM,
            )
            self.assertEqual(
                belt.metadata["production_width_design_limit_mm"],
                WHEEL_PRODUCTION_WIDTH_LIMIT_MM,
            )
            belt_box = belt.shape.BoundingBox()
            product_width = 2.0 * max(abs(belt_box.ymin), abs(belt_box.ymax))
            self.assertAlmostEqual(
                product_width,
                WHEEL_NOMINAL_PRODUCT_WIDTH_MM,
                places=6,
            )
            self.assertLessEqual(product_width, WHEEL_PRODUCTION_WIDTH_LIMIT_MM)
            for axle, wheel_x in (("front", -380.0), ("rear", 180.0)):
                visual_skin = by_name[
                    "A03_body_colour_wheel_end_return_skin_"
                    f"{axle}_{side_name}"
                ]
                outward_x = -1.0 if axle == "front" else 1.0
                end_open_probe = (
                    cq.Workplane("XY")
                    .box(20.0, 1.0, 1.0)
                    .translate(
                        (
                            wheel_x + outward_x * 143.0,
                            side * 328.625,
                            WHEEL_END_OPEN_PROBE_Z_MM,
                        )
                    )
                    .val()
                )
                end_closed_probe = (
                    cq.Workplane("XY")
                    .box(20.0, 1.0, 1.0)
                    .translate(
                        (
                            wheel_x + outward_x * 143.0,
                            side * 328.625,
                            WHEEL_END_CLOSED_PROBE_Z_MM,
                        )
                    )
                    .val()
                )
                with self.subTest(side=side_name, wheel_x=wheel_x):
                    for longitudinal_offset in (
                        WHEEL_SIDE_REVEAL_LONGITUDINAL_OFFSETS_FROM_AXIS_MM
                    ):
                        side_open_probe = (
                            cq.Workplane("XY")
                            .box(1.0, 20.0, 1.0)
                            .translate(
                                (
                                    wheel_x + longitudinal_offset,
                                    side * 371.5,
                                    WHEEL_SIDE_OPEN_PROBE_Z_MM,
                                )
                            )
                            .val()
                        )
                        side_closed_probe = (
                            cq.Workplane("XY")
                            .box(1.0, 20.0, 1.0)
                            .translate(
                                (
                                    wheel_x + longitudinal_offset,
                                    side * 371.5,
                                    WHEEL_SIDE_CLOSED_PROBE_Z_MM,
                                )
                            )
                            .val()
                        )
                        self.assertLessEqual(
                            float(
                                belt.shape.intersect(side_open_probe).Volume()
                            ),
                            1.0e-5,
                        )
                        side_closed = belt.shape.intersect(side_closed_probe)
                        self.assertGreater(
                            float(side_closed.Volume()),
                            1.0e-5,
                        )
                        self.assertGreaterEqual(
                            float(side_closed.BoundingBox().ylen),
                            1.85,
                        )
                        self.assertLessEqual(
                            float(side_closed.BoundingBox().ylen),
                            1.95,
                        )
                    self.assertLessEqual(
                        float(belt.shape.intersect(end_open_probe).Volume()),
                        1.0e-5,
                    )
                    end_closed = belt.shape.intersect(end_closed_probe)
                    self.assertGreater(float(end_closed.Volume()), 1.0e-5)
                    self.assertGreaterEqual(
                        float(end_closed.BoundingBox().xlen), 1.85
                    )
                    self.assertLessEqual(
                        float(end_closed.BoundingBox().xlen), 1.95
                    )
                    for lateral_offset in (
                        WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM
                    ):
                        for coverage_z in WHEEL_END_COVERAGE_PROBE_Z_MM:
                            coverage_probe = (
                                cq.Workplane("XY")
                                .box(20.0, 1.0, 1.0)
                                .translate(
                                    (
                                        wheel_x + outward_x * 143.0,
                                        side * (326.0 + lateral_offset),
                                        coverage_z,
                                    )
                                )
                                .val()
                            )
                            coverage = belt.shape.intersect(coverage_probe)
                            self.assertGreater(
                                float(coverage.Volume()),
                                1.0e-5,
                            )
                            self.assertGreaterEqual(
                                float(coverage.BoundingBox().xlen),
                                1.85,
                            )
                            self.assertLessEqual(
                                float(coverage.BoundingBox().xlen),
                                1.95,
                            )
                    visual_box = visual_skin.shape.BoundingBox()
                    self.assertTrue(visual_skin.shape.isValid())
                    self.assertEqual(len(visual_skin.shape.Solids()), 1)
                    self.assertEqual(visual_skin.color, LUNAR_STONE)
                    self.assertTrue(
                        visual_skin.metadata["body_colour_end_return"]
                    )
                    self.assertTrue(
                        visual_skin.metadata["tyre_visual_occlusion"]
                    )
                    self.assertTrue(
                        visual_skin.metadata[
                            "covers_tyre_upper_projection"
                        ]
                    )
                    self.assertTrue(
                        visual_skin.metadata[
                            "underlying_end_return_connected_to_crown_brep"
                        ]
                    )
                    self.assertFalse(
                        visual_skin.metadata[
                            "decorative_graphics_or_fake_seams"
                        ]
                    )
                    self.assertEqual(
                        visual_skin.metadata["lower_half_reveal_top_z_mm"],
                        WHEEL_LOWER_HALF_REVEAL_TOP_Z_MM,
                    )
                    self.assertTrue(
                        visual_skin.metadata[
                            "half_wrap_boundary_equals_wheel_axis"
                        ]
                    )
                    self.assertAlmostEqual(
                        visual_box.xlen,
                        WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
                        places=6,
                    )
                    self.assertAlmostEqual(
                        visual_box.ylen,
                        WHEEL_END_VISUAL_SKIN_Y_SPAN_MM,
                        places=6,
                    )
                    self.assertAlmostEqual(
                        visual_box.zmin,
                        WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM[0],
                        places=6,
                    )
                    self.assertAlmostEqual(
                        visual_box.zmax,
                        WHEEL_END_VISUAL_SKIN_Z_BOUNDS_MM[1],
                        places=6,
                    )
                    self.assertLessEqual(
                        float(
                            visual_skin.shape.intersect(belt.shape).Volume()
                        ),
                        1.0e-5,
                    )
                    self.assertAlmostEqual(
                        float(visual_skin.shape.distance(belt.shape)),
                        WHEEL_END_VISUAL_SKIN_GAP_TO_BELT_MM,
                        places=6,
                    )
                    visual_skin_x = (visual_box.xmin + visual_box.xmax) / 2.0
                    for lateral_offset in (
                        WHEEL_END_COVERAGE_LATERAL_OFFSETS_FROM_CENTER_MM
                    ):
                        for coverage_z in WHEEL_END_COVERAGE_PROBE_Z_MM:
                            visual_probe = (
                                cq.Workplane("XY")
                                .box(20.0, 1.0, 1.0)
                                .translate(
                                    (
                                        visual_skin_x,
                                        side * (326.0 + lateral_offset),
                                        coverage_z,
                                    )
                                )
                                .val()
                            )
                            visual_coverage = visual_skin.shape.intersect(
                                visual_probe
                            )
                            self.assertGreater(
                                float(visual_coverage.Volume()),
                                1.0e-5,
                            )
                            self.assertAlmostEqual(
                                float(
                                    visual_coverage.BoundingBox().xlen
                                ),
                                WHEEL_END_VISUAL_SKIN_THICKNESS_MM,
                                places=6,
                            )
                    tyre = importers.importStep(
                        str(
                            ROOT
                            / "build"
                            / "parts"
                            / f"tyre_{axle}_{side_name}.step"
                        )
                    ).val()
                    clearances = []
                    for angle in (-10.0, -5.0, 0.0, 5.0, 10.0):
                        swept = (
                            tyre
                            if angle == 0.0
                            else tyre.rotate(
                                (-100.0, 0.0, 125.0),
                                (-100.0, 1.0, 125.0),
                                angle,
                            )
                        )
                        clearances.append(
                            float(class_a_belt_shell.distance(swept))
                        )
                    self.assertGreaterEqual(
                        min(clearances),
                        WHEEL_MINIMUM_SWEPT_CLEARANCE_MM - 1.0e-4,
                    )

        validator_checks = Checks()
        _validate_wheel_contact_band_contract(
            [
                _part_from_object(
                    part
                )
                for name, part in by_name.items()
                if name.startswith("A03_continuous_wheel_belt_shell_")
                or name.startswith(
                    "A03_body_colour_wheel_end_return_skin_"
                )
                or name.startswith("A03_wheel_end_service_cap_")
                or name.startswith(
                    "A03_wheel_end_service_seam_backing_"
                )
                or name.startswith("A03_wheel_end_motion_gaiter_")
            ],
            validator_checks,
            cq,
        )
        by_id = {item["id"]: item for item in validator_checks.items}
        for axle in ("front", "rear"):
            for side_name in ("left", "right"):
                check_id = f"wheel_contact_band.ride.{axle}.{side_name}"
                self.assertTrue(by_id[check_id]["pass"], by_id[check_id])

    def test_envelope_lock_accepts_only_step_scale_numerical_drift(self) -> None:
        self.assertEqual(ENVELOPE_BREP_NUMERICAL_TOLERANCE_MM, 0.01)
        self.assertTrue(_within_locked_envelope_axis(1041.009, 1041.0))
        self.assertTrue(_within_locked_envelope_axis(1041.010, 1041.0))
        self.assertFalse(_within_locked_envelope_axis(1041.011, 1041.0))


if __name__ == "__main__":
    unittest.main()
