from __future__ import annotations

import hashlib
import json
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import trimesh


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
    _pbr_visual,
    _procedural_material_textures,
    _skin_pbr_profile,
)
from skin_common import (  # noqa: E402
    OXBLOOD_LEATHER,
    SATIN_STAINLESS,
    SMOKED_WALNUT,
)


_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BINARY_CHUNK = 0x004E4942
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _decode_glb(payload: bytes) -> tuple[dict[str, object], bytes]:
    magic, version, declared_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(payload):
        raise AssertionError(
            "Export is not one complete glTF 2.0 binary container: "
            f"magic={magic!r}, version={version}, "
            f"declared={declared_length}, actual={len(payload)}"
        )

    json_payload: bytes | None = None
    binary_payload: bytes | None = None
    offset = 12
    while offset < declared_length:
        chunk_length, chunk_type = struct.unpack_from("<II", payload, offset)
        offset += 8
        chunk = payload[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == _GLB_JSON_CHUNK:
            json_payload = chunk
        elif chunk_type == _GLB_BINARY_CHUNK:
            binary_payload = chunk

    if offset != declared_length or json_payload is None or binary_payload is None:
        raise AssertionError("GLB JSON/BIN chunks are missing or malformed")
    tree = json.loads(json_payload.rstrip(b"\x00 \t\r\n").decode("utf-8"))
    return tree, binary_payload


class V8GlbPbrContractTests(unittest.TestCase):
    _CASES = (
        {
            "part_name": "A09_table_top_skin_right",
            "family": "natural_smoked_walnut_veneer",
            "material": "book-matched natural smoked-walnut veneer",
            "colour": SMOKED_WALNUT,
            "texture_kind": "walnut",
            "metallic": 0.0,
            "roughness": 0.36,
        },
        {
            "part_name": "A06_backrest_contact_panel",
            "family": "semi_aniline_full_grain_leather",
            "material": "deep-oxblood semi-aniline full-grain leather",
            "colour": OXBLOOD_LEATHER,
            "texture_kind": "leather",
            "metallic": 0.0,
            "roughness": 0.74,
        },
        {
            "part_name": "A05_left_hmi_precision_bezel",
            "family": "fine_brushed_stainless_steel",
            "material": "fine-brushed stainless-steel precision boundary",
            "colour": SATIN_STAINLESS,
            "texture_kind": "brushed_stainless",
            "metallic": 0.88,
            "roughness": 0.28,
        },
    )

    @classmethod
    def _export_material_scene(cls) -> bytes:
        scene = trimesh.Scene()
        scene.units = "meters"
        base_vertices = np.asarray(
            (
                (0.000, 0.000, 0.000),
                (0.045, 0.000, 0.002),
                (0.000, 0.040, 0.004),
                (0.045, 0.040, 0.007),
            ),
            dtype=np.float64,
        )
        faces = np.asarray(((0, 1, 2), (1, 3, 2)), dtype=np.int64)

        for index, case in enumerate(cls._CASES):
            part = SimpleNamespace(
                name=case["part_name"],
                material=case["material"],
                metadata={"material_family": case["family"]},
            )
            texture_kind, metallic, roughness = _skin_pbr_profile(part)
            if (texture_kind, metallic, roughness) != (
                case["texture_kind"],
                case["metallic"],
                case["roughness"],
            ):
                raise AssertionError(
                    f"Released PBR profile drift for {case['family']}: "
                    f"{(texture_kind, metallic, roughness)!r}"
                )

            vertices = base_vertices + np.asarray(
                (index * 0.070, 0.0, 0.0), dtype=np.float64
            )
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            mesh.visual = _pbr_visual(
                vertices,
                name=f"{case['part_name']}__{case['family']}",
                colour=case["colour"],
                texture_kind=texture_kind,
                mapping="default",
                metallic=metallic,
                roughness=roughness,
            )
            scene.add_geometry(
                mesh,
                node_name=case["part_name"],
                geom_name=case["part_name"],
            )

        return scene.export(file_type="glb", include_normals=True)

    def test_semantic_pbr_glb_is_deterministic_and_self_contained(self) -> None:
        _procedural_material_textures.cache_clear()
        first = self._export_material_scene()
        first_digest = hashlib.sha256(first).hexdigest()
        _procedural_material_textures.cache_clear()
        second = self._export_material_scene()
        self.assertEqual(first_digest, hashlib.sha256(second).hexdigest())

        tree, binary_payload = _decode_glb(first)
        materials = tree.get("materials", [])
        textures = tree.get("textures", [])
        images = tree.get("images", [])
        meshes = tree.get("meshes", [])

        self.assertEqual(len(materials), len(self._CASES))
        self.assertGreaterEqual(len(textures), len(self._CASES) * 2)
        self.assertGreaterEqual(len(images), len(self._CASES) * 2)
        self.assertEqual(len(meshes), len(self._CASES))

        material_by_name = {item.get("name"): item for item in materials}
        for case in self._CASES:
            material_name = f"{case['part_name']}__{case['family']}"
            self.assertIn(material_name, material_by_name)
            material = material_by_name[material_name]
            pbr = material.get("pbrMetallicRoughness", {})
            self.assertAlmostEqual(pbr.get("metallicFactor"), case["metallic"])
            self.assertAlmostEqual(pbr.get("roughnessFactor"), case["roughness"])
            self.assertIn("baseColorTexture", pbr)
            self.assertIn("normalTexture", material)
            self.assertEqual(material.get("alphaMode"), "OPAQUE")
            self.assertIs(
                material.get("doubleSided"),
                True,
                "STEP-derived review GLB must remain visible from every audit view",
            )

        for mesh in meshes:
            primitives = mesh.get("primitives", [])
            self.assertEqual(len(primitives), 1)
            primitive = primitives[0]
            self.assertIn("material", primitive)
            attributes = primitive.get("attributes", {})
            self.assertIn("POSITION", attributes)
            self.assertIn("NORMAL", attributes)
            self.assertIn("TEXCOORD_0", attributes)

        buffer_views = tree.get("bufferViews", [])
        self.assertEqual(len(tree.get("buffers", [])), 1)
        self.assertNotIn("uri", tree["buffers"][0])
        for image in images:
            self.assertEqual(image.get("mimeType"), "image/png")
            self.assertNotIn("uri", image)
            self.assertIn("bufferView", image)
            view = buffer_views[image["bufferView"]]
            self.assertEqual(view.get("buffer", 0), 0)
            start = int(view.get("byteOffset", 0))
            end = start + int(view["byteLength"])
            self.assertEqual(binary_payload[start:end][:8], _PNG_SIGNATURE)

        for texture in textures:
            self.assertIn("source", texture)
            self.assertGreaterEqual(texture["source"], 0)
            self.assertLess(texture["source"], len(images))


if __name__ == "__main__":
    unittest.main()
