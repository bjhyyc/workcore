from __future__ import annotations

import copy
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

import build_layout_appearance_series_low_memory as low_memory  # noqa: E402
from tests import test_v8_glb_pbr_contract as pbr_fixture  # noqa: E402


def _encode_glb(
    tree: dict[str, object],
    binary_payload: bytes,
    *,
    include_binary: bool = True,
) -> bytes:
    json_payload = json.dumps(tree, separators=(",", ":")).encode("utf-8")
    json_payload += b" " * ((4 - len(json_payload) % 4) % 4)
    chunks = struct.pack(
        "<II", len(json_payload), low_memory._GLB_JSON_CHUNK
    ) + json_payload
    if include_binary:
        binary_payload += b"\x00" * ((4 - len(binary_payload) % 4) % 4)
        chunks += struct.pack(
            "<II", len(binary_payload), low_memory._GLB_BINARY_CHUNK
        ) + binary_payload
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


class V8LowMemoryReleaseIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.valid_glb = pbr_fixture.V8GlbPbrContractTests._export_material_scene()
        cls.valid_tree, cls.valid_binary = pbr_fixture._decode_glb(cls.valid_glb)

    def _inspect_payload(self, payload: bytes) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary).resolve()
            path = repository_root / "review.glb"
            path.write_bytes(payload)
            with patch.object(low_memory, "REPOSITORY_ROOT", repository_root):
                return low_memory._inspect_glb_pbr_contract(
                    path,
                    "cafe",
                    "final_review",
                )

    def test_strict_pbr_gate_accepts_the_current_semantic_export(self) -> None:
        report = self._inspect_payload(self.valid_glb)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertTrue(report["all_textures_embedded"])
        self.assertGreater(report["binary_chunk_bytes"], 0)

    def test_controlled_four_state_battery_and_device_inventory_is_complete(self) -> None:
        controlled = CLASS_A / "controlled_source_e6_dfr5"
        for state in low_memory.STATE_NAMES:
            with self.subTest(state=state):
                report = low_memory._inspect_required_internal_source_occurrences(
                    controlled / f"workcore_e6_dfr5_{state}.step",
                    state,
                )
                self.assertEqual(report["status"], "PASS", report["failures"])
                self.assertEqual(report["required_occurrence_count"], 31)
                self.assertTrue(
                    all(
                        group["status"] == "PASS"
                        for group in report["groups"].values()
                    )
                )

    def test_internal_inventory_gate_rejects_missing_or_duplicate_products(self) -> None:
        names = [
            name
            for group in low_memory.REQUIRED_FULL_LAYOUT_SOURCE_OCCURRENCES.values()
            for name in group
        ]
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary).resolve()
            step_path = repository_root / "controlled.step"
            payload = "\n".join(f"PRODUCT('{name}','',());" for name in names)
            step_path.write_text(payload, encoding="ascii")
            with patch.object(low_memory, "REPOSITORY_ROOT", repository_root):
                passing = low_memory._inspect_required_internal_source_occurrences(
                    step_path,
                    "ride",
                )
                self.assertEqual(passing["status"], "PASS")

                duplicate = names[0]
                step_path.write_text(
                    payload + f"\nPRODUCT('{duplicate}','',());\n",
                    encoding="ascii",
                )
                failing = low_memory._inspect_required_internal_source_occurrences(
                    step_path,
                    "ride",
                )
                self.assertEqual(failing["status"], "FAIL")
                self.assertIn(duplicate, " | ".join(failing["failures"]))

                missing = names[-1]
                step_path.write_text(
                    "\n".join(
                        f"PRODUCT('{name}','',());"
                        for name in names
                        if name != missing
                    ),
                    encoding="ascii",
                )
                missing_report = (
                    low_memory._inspect_required_internal_source_occurrences(
                        step_path,
                        "ride",
                    )
                )
                self.assertEqual(missing_report["status"], "FAIL")
                self.assertIn(missing, " | ".join(missing_report["failures"]))

    def test_selected_source_plus_skin_step_roundtrip_cannot_be_skin_only(self) -> None:
        import cadquery as cq
        from build_class_a_skin import (
            STATES,
            _composite_shape_signature,
            _roundtrip_signature_failures,
            _save_final_layout_composite,
            _shape_signature,
            _signature_delta,
        )
        from skin_common import SkinPart

        ride = next(source for source in STATES if source.configuration == "ride")
        probe = SkinPart(
            "V8_full_layout_roundtrip_probe_skin",
            cq.Workplane("XY").box(10.0, 12.0, 14.0).translate(
                (1000.0, 1000.0, 1000.0)
            ).val(),
            (0.2, 0.3, 0.4, 1.0),
            "test",
            "QA",
            "ride",
        )
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "full_layout.step"
            selected_source, evidence = _save_final_layout_composite(
                ride,
                [probe],
                target,
            )
            expected = _composite_shape_signature(selected_source, [probe])
            reimported_shape = cq.importers.importStep(str(target)).val()
            reimported = _shape_signature(reimported_shape)
            delta = _signature_delta(expected, reimported)
            self.assertEqual(
                _roundtrip_signature_failures(expected, reimported, delta),
                [],
            )
            self.assertTrue(reimported_shape.isValid())
            self.assertEqual(
                evidence["source_shape_signature"]["solid_count"],
                low_memory.EXPECTED_DFR5_SOURCE_SOLID_COUNTS["ride"],
            )
            self.assertEqual(
                evidence["selected_shape_signature"]["solid_count"],
                low_memory.EXPECTED_FINAL_LAYOUT_SOURCE_SOLID_COUNTS["ride"],
            )
            self.assertEqual(
                reimported["solid_count"],
                low_memory.EXPECTED_FINAL_LAYOUT_SOURCE_SOLID_COUNTS["ride"] + 1,
            )

            counterfeit_skin_only = _shape_signature(probe.shape)
            self.assertNotEqual(
                counterfeit_skin_only["solid_count"],
                reimported["solid_count"],
            )
            step_bytes = target.read_bytes()
            self.assertEqual(
                step_bytes.count(b"PRODUCT('battery_lfp_16s30ah_1p536kwh'"),
                1,
            )
            self.assertEqual(
                step_bytes.count(b"PRODUCT('armrest_transfer_hinge_right'"),
                0,
            )

    def test_gate_rejects_broken_accessor_texture_and_buffer_view_links(self) -> None:
        tree = copy.deepcopy(self.valid_tree)
        for mesh in tree["meshes"]:
            attributes = mesh["primitives"][0]["attributes"]
            attributes["NORMAL"] = 999_999
            attributes["TEXCOORD_0"] = 999_998
        for material in tree["materials"]:
            material["pbrMetallicRoughness"]["baseColorTexture"] = {}
            material["normalTexture"] = {}
        for image in tree["images"]:
            image["bufferView"] = 999_997

        report = self._inspect_payload(_encode_glb(tree, self.valid_binary))
        self.assertEqual(report["status"], "FAIL")
        joined = " | ".join(report["failures"])
        self.assertIn("invalid NORMAL accessor", joined)
        self.assertIn("not embedded in the GLB", joined)
        self.assertIn("has no valid texture", joined)

    def test_gate_rejects_json_only_container_and_corrupt_png(self) -> None:
        json_only = self._inspect_payload(
            _encode_glb(self.valid_tree, b"", include_binary=False)
        )
        self.assertEqual(json_only["status"], "FAIL")
        self.assertIn("JSON/BIN", " | ".join(json_only["failures"]))

        binary = bytearray(self.valid_binary)
        image = self.valid_tree["images"][0]
        view = self.valid_tree["bufferViews"][image["bufferView"]]
        binary[int(view.get("byteOffset", 0))] ^= 0xFF
        corrupt = self._inspect_payload(_encode_glb(self.valid_tree, bytes(binary)))
        self.assertEqual(corrupt["status"], "FAIL")
        self.assertIn("PNG signature", " | ".join(corrupt["failures"]))

    def test_gate_rejects_semantically_wrong_stainless_pbr(self) -> None:
        tree = copy.deepcopy(self.valid_tree)
        stainless = next(
            material
            for material in tree["materials"]
            if "__fine_brushed_stainless_steel" in material.get("name", "")
        )
        stainless["pbrMetallicRoughness"]["metallicFactor"] = 0.0
        stainless["pbrMetallicRoughness"]["roughnessFactor"] = 0.95
        report = self._inspect_payload(_encode_glb(tree, self.valid_binary))
        self.assertEqual(report["status"], "FAIL")
        joined = " | ".join(report["failures"])
        self.assertIn("semantic stainless", joined)
        self.assertIn("metallicFactor", joined)
        self.assertIn("roughnessFactor", joined)

    def test_final_hash_and_eight_glb_gates_reopen_disk_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary).resolve()
            output = repository_root / "release"
            fragments: dict[str, dict[str, object]] = {}
            with patch.object(low_memory, "REPOSITORY_ROOT", repository_root):
                for state in low_memory.STATE_NAMES:
                    expected = low_memory._expected_state_artifacts(output, state)
                    for kind, paths in expected.items():
                        for path in paths:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            payload = (
                                self.valid_glb
                                if kind == "glb"
                                else f"{state}:{kind}:{path.name}".encode("utf-8")
                            )
                            path.write_bytes(payload)
                    inventory = low_memory._validate_state_artifact_inventory(
                        output, state
                    )
                    artifact_hashes = {
                        artifact: low_memory._sha256_path(repository_root / artifact)
                        for paths in inventory.values()
                        for artifact in paths
                    }
                    pbr_checks = [
                        {
                            "state": state,
                            "purpose": purpose,
                            "path": artifact,
                            "sha256": artifact_hashes[artifact],
                            "status": "PASS",
                            "failures": [],
                        }
                        for purpose, artifact in zip(
                            ("final_review", "qa_overlay"), inventory["glb"]
                        )
                    ]
                    fragments[state] = {
                        "state_payload": {
                            "artifact_inventory": inventory,
                            "artifact_sha256": artifact_hashes,
                            "full_layout_step": inventory["step"][0],
                            "full_layout_step_sha256": artifact_hashes[
                                inventory["step"][0]
                            ],
                            "exterior_step": inventory["step"][1],
                            "exterior_step_sha256": artifact_hashes[
                                inventory["step"][1]
                            ],
                            "review_glb": inventory["glb"][0],
                            "review_glb_sha256": artifact_hashes[
                                inventory["glb"][0]
                            ],
                            "qa_glb": inventory["glb"][1],
                            "qa_glb_sha256": artifact_hashes[inventory["glb"][1]],
                            "glb_pbr_material_checks": pbr_checks,
                        },
                        "render_checks": [
                            {
                                "path": artifact,
                                "sha256": artifact_hashes[artifact],
                            }
                            for artifact in inventory["png"]
                        ],
                    }

                final_hashes = low_memory._verify_final_artifact_hashes(
                    output, fragments
                )
                self.assertEqual(len(final_hashes), 48)
                pbr_checks = low_memory._inspect_final_glb_set(
                    output, final_hashes
                )
                self.assertEqual(len(pbr_checks), 8)
                self.assertTrue(
                    all(check["status"] == "PASS" for check in pbr_checks),
                    pbr_checks,
                )
                for state in low_memory.STATE_NAMES:
                    fragments[state]["state_payload"][
                        "glb_pbr_material_checks"
                    ] = [
                        check for check in pbr_checks if check["state"] == state
                    ]
                self.assertEqual(
                    low_memory._verify_final_artifact_hashes(output, fragments),
                    final_hashes,
                )

                changed_png = output / "follow" / "preview_class_a_follow.png"
                changed_png.write_bytes(b"late write")
                with self.assertRaisesRegex(RuntimeError, "bytes drifted"):
                    low_memory._verify_final_artifact_hashes(output, fragments)


if __name__ == "__main__":
    unittest.main()
