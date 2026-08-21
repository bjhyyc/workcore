"""Build the WorkCore V8 four-state render series with bounded peak memory.

The canonical :mod:`build_layout_appearance_series` path keeps all four state
B-Reps alive until export is complete.  This entry point preserves that
builder's artifact names, cameras, physical gates and manifest semantics while
running each state in a fresh, sequential child process.  The parent process
never imports the CAD stack; it only validates the child summaries and writes
the combined manifest and release gate.

Controlled STEP inputs remain read-only.  New STEP/GLB/PNG artifacts are
written only below the requested output directory.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Any

from v8_internal_layout_contract import (
    EXPECTED_DFR5_SOURCE_SOLID_COUNTS,
    EXPECTED_FINAL_LAYOUT_SOURCE_SOLID_COUNTS,
    REQUIRED_FULL_LAYOUT_SOURCE_OCCURRENCES,
    REQUIRED_REPLACED_SOURCE_PROXIES,
    required_occurrence_names,
    required_selected_occurrence_names,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parents[3]
DEFAULT_OUTPUT = (
    SCRIPT_DIR / "final_product_v8_layout_appearance_20260719_low_memory"
)
STATE_NAMES = ("follow", "ride", "cafe", "focus")
# Build the two deployed-table states first: they carry the highest BRep and
# collision complexity, so a regression fails before simpler states consume
# time or disk.  Final manifests and artifact ordering remain canonical.
BUILD_ORDER = ("focus", "cafe", "follow", "ride")
if set(BUILD_ORDER) != set(STATE_NAMES) or len(BUILD_ORDER) != len(STATE_NAMES):
    raise RuntimeError("Low-memory build order must contain every state exactly once")
RENDER_VIEW_NAMES = (
    "hero",
    "qa_overlay",
    "front",
    "rear",
    "left",
    "right",
    "top",
    "bottom",
)
A07_BREP_EXTERIOR_NAMES = (
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
)
A07_BREP_INTERNAL_NAMES = (
    "A07_mast_lock_pin_left",
    "A07_mast_lock_pin_right",
)
A07_BREP_ALL_NAMES = (*A07_BREP_EXTERIOR_NAMES, *A07_BREP_INTERNAL_NAMES)
A07_FOCUS_MOVING_NAMES = frozenset(
    {
        "A07_mast_moving_inner_sleeve",
        "A07_sensor_beam_shell",
        "A07_sensor_beam_smoked_window",
        "A07_physical_privacy_shutter",
        "A07_microphone_acoustic_mesh",
        "A07_environment_sensor_grille",
        "A07_fill_light_visible_window_left",
        "A07_fill_light_visible_window_right",
        "A07_privacy_shutter_carriage_bezel",
    }
)
A07_FOCUS_PRIVACY_NAMES = frozenset(
    {
        "A07_physical_privacy_shutter",
        "A07_privacy_shutter_carriage_bezel",
    }
)
EXPECTED_STATE_ARTIFACT_COUNTS = {"step": 2, "glb": 2, "png": 8}
EXPECTED_SERIES_ARTIFACT_COUNTS = {"step": 8, "glb": 8, "png": 32}
WORKER_DIRECTORY_NAME = ".low_memory_state_manifests"
INCOMPLETE_MARKER_NAME = "BUILD_INCOMPLETE"
# Keep enough free space for Windows' page file and for one interrupted state
# to coexist with its replacement.  The final series is normally well below
# this reserve, so crossing it indicates a host-stability risk rather than a
# legitimate release requirement.
MINIMUM_FREE_DISK_BEFORE_SERIES_BYTES = 3 * 1024**3
MINIMUM_FREE_DISK_BEFORE_STATE_BYTES = 1536 * 1024**2

# These are not decorative manifest labels.  Every named occurrence must be
# present in the hash-pinned controlled STEP and in its disposition-filtered
# final-layout selection embedded in each released
# ``workcore_e6_layout_full_*.step``.  The independent verifier later proves
# that selected B-Reps survived export and that retired/replaced source parts
# did not leak back into the final layout.


def _require_free_disk(path: Path, minimum_bytes: int, phase: str) -> None:
    """Fail before a CAD worker can exhaust the system volume."""

    probe = path.resolve()
    while not probe.exists():
        if probe.parent == probe:
            raise RuntimeError(f"Cannot resolve a disk-usage probe for {path}")
        probe = probe.parent
    free_bytes = shutil.disk_usage(probe).free
    if free_bytes < minimum_bytes:
        raise RuntimeError(
            f"Host-stability disk guard stopped {phase}: "
            f"{free_bytes / 1024**3:.2f} GiB free, "
            f"{minimum_bytes / 1024**3:.2f} GiB required"
        )


def _worker_scratch_directory(output: Path) -> Path:
    """Return a high-capacity, caller-overridable scratch directory.

    OCC/STEP and raster exporters can create large temporary files.  Keeping
    those writes off the nearly full system volume is part of the crash-safe
    release contract, while ``WORKCORE_CAD_TEMP`` remains an explicit escape
    hatch for a different host layout.
    """

    override = os.environ.get("WORKCORE_CAD_TEMP", "").strip()
    if override:
        scratch = Path(override).expanduser().resolve()
    else:
        high_capacity_root = Path("D:/")
        scratch = (
            high_capacity_root / "workcore_cad_temp"
            if high_capacity_root.exists()
            else output.resolve().parent / ".workcore_cad_temp"
        )
    scratch.mkdir(parents=True, exist_ok=True)
    _require_free_disk(
        scratch,
        MINIMUM_FREE_DISK_BEFORE_STATE_BYTES,
        "CAD worker scratch allocation",
    )
    return scratch.resolve()


def _write_json(path: Path, payload: object) -> Path:
    """Match the canonical builder's atomic UTF-8 JSON write semantics."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _sha256_path(path: Path) -> str:
    """Hash one completed artifact without importing the CAD stack."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload_sha256(payload: object) -> str:
    """Hash JSON evidence independently of pretty-print whitespace/order."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BINARY_CHUNK = 0x004E4942
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ACCESSOR_COMPONENT_BYTES = {
    5120: 1,
    5121: 1,
    5122: 2,
    5123: 2,
    5125: 4,
    5126: 4,
}
_ACCESSOR_COMPONENT_COUNTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
_MAX_EMBEDDED_PNG_BYTES = 64 * 1024 * 1024
_SEMANTIC_PBR_FAMILIES = {
    "leather": {
        "tokens": (
            "__semi_aniline_full_grain_leather",
            "__full_grain_leather_hand_contact",
        ),
        "metallic": (0.0, 0.001),
        "roughness": (0.60, 0.85),
    },
    "stainless": {
        "tokens": ("__fine_brushed_stainless_steel",),
        "metallic": (0.80, 1.0),
        "roughness": (0.20, 0.40),
    },
    "walnut": {
        "tokens": (
            "__natural_smoked_walnut_veneer",
            "__solid_smoked_walnut_lipping",
        ),
        "metallic": (0.0, 0.001),
        "roughness": (0.30, 0.50),
    },
}


def _is_index(value: object, size: int) -> bool:
    """Return true only for a JSON integer index inside ``[0, size)``."""

    return type(value) is int and 0 <= value < size


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _read_glb_container(path: Path) -> tuple[dict[str, Any], int, int]:
    """Read the unique JSON chunk and locate the unique BIN chunk.

    The BIN payload is deliberately not retained in memory.  The returned
    offset and length let the material gate validate only the embedded PNG
    buffer views while the CAD worker is still near its peak memory use.
    """

    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise RuntimeError(f"Truncated GLB header: {path}")
        magic, version, declared_length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or declared_length != file_size:
            raise RuntimeError(f"Invalid glTF 2.0 binary container: {path}")

        consumed = 12
        chunk_index = 0
        json_payload: bytes | None = None
        binary_offset: int | None = None
        binary_length: int | None = None
        while consumed < declared_length:
            if declared_length - consumed < 8:
                raise RuntimeError(f"Truncated GLB chunk header: {path}")
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise RuntimeError(f"Truncated GLB chunk header: {path}")
            chunk_length, chunk_type = struct.unpack("<II", chunk_header)
            consumed += 8
            if chunk_length % 4 != 0 or chunk_length > declared_length - consumed:
                raise RuntimeError(f"Invalid GLB chunk length/alignment: {path}")
            payload_offset = stream.tell()
            if chunk_index == 0 and chunk_type != _GLB_JSON_CHUNK:
                raise RuntimeError(f"GLB JSON chunk is not first: {path}")
            if chunk_type == _GLB_JSON_CHUNK:
                if json_payload is not None or chunk_index != 0:
                    raise RuntimeError(f"Duplicate or misplaced GLB JSON chunk: {path}")
                json_payload = stream.read(chunk_length)
                if len(json_payload) != chunk_length:
                    raise RuntimeError(f"Truncated GLB JSON chunk: {path}")
            elif chunk_type == _GLB_BINARY_CHUNK:
                if json_payload is None or binary_offset is not None:
                    raise RuntimeError(f"Duplicate or misplaced GLB BIN chunk: {path}")
                binary_offset = payload_offset
                binary_length = chunk_length
                stream.seek(chunk_length, os.SEEK_CUR)
            else:
                raise RuntimeError(
                    f"Unexpected GLB chunk type 0x{chunk_type:08x}: {path}"
                )
            consumed += chunk_length
            chunk_index += 1

        if (
            consumed != declared_length
            or json_payload is None
            or binary_offset is None
            or binary_length is None
            or binary_length <= 0
        ):
            raise RuntimeError(f"Malformed GLB JSON/BIN chunk inventory: {path}")

    try:
        tree = json.loads(json_payload.rstrip(b"\x00 \t\r\n").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid GLB JSON payload: {path}: {exc}") from exc
    if not isinstance(tree, dict):
        raise RuntimeError(f"GLB JSON root is not an object: {path}")
    asset = tree.get("asset")
    if not isinstance(asset, dict) or str(asset.get("version")) != "2.0":
        raise RuntimeError(f"GLB JSON asset.version is not 2.0: {path}")
    return tree, binary_offset, binary_length


def _read_glb_json(path: Path) -> dict[str, Any]:
    """Compatibility wrapper returning JSON after strict JSON+BIN parsing."""

    tree, _binary_offset, _binary_length = _read_glb_container(path)
    return tree


def _embedded_png_failure(
    path: Path,
    absolute_offset: int,
    byte_length: int,
) -> str | None:
    """Return a failure reason unless one buffer view is a complete PNG."""

    if byte_length < 33 or byte_length > _MAX_EMBEDDED_PNG_BYTES:
        return f"embedded PNG byteLength {byte_length} is outside the release range"
    with path.open("rb") as stream:
        stream.seek(absolute_offset)
        payload = stream.read(byte_length)
    if len(payload) != byte_length or not payload.startswith(_PNG_SIGNATURE):
        return "embedded PNG signature/payload is invalid"

    cursor = len(_PNG_SIGNATURE)
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    while cursor + 12 <= len(payload):
        chunk_length = struct.unpack_from(">I", payload, cursor)[0]
        chunk_end = cursor + 12 + chunk_length
        if chunk_end > len(payload):
            return "embedded PNG chunk exceeds its bufferView"
        chunk_type = payload[cursor + 4 : cursor + 8]
        chunk_data = payload[cursor + 8 : cursor + 8 + chunk_length]
        expected_crc = struct.unpack_from(">I", payload, cursor + 8 + chunk_length)[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return f"embedded PNG {chunk_type!r} CRC is invalid"
        if not saw_ihdr:
            if chunk_type != b"IHDR" or chunk_length != 13:
                return "embedded PNG does not start with a 13-byte IHDR"
            width, height = struct.unpack_from(">II", chunk_data, 0)
            if width <= 0 or height <= 0:
                return "embedded PNG has non-positive dimensions"
            saw_ihdr = True
        elif chunk_type == b"IHDR":
            return "embedded PNG contains a duplicate IHDR"
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if chunk_length != 0:
                return "embedded PNG IEND is not empty"
            saw_iend = True
            cursor = chunk_end
            break
        cursor = chunk_end

    if not (saw_ihdr and saw_idat and saw_iend):
        return "embedded PNG is missing IHDR, IDAT or IEND"
    trailing = payload[cursor:]
    if len(trailing) > 3 or any(value not in {0x00, 0x20} for value in trailing):
        return "embedded PNG has non-padding bytes after IEND"
    return None


def _inspect_glb_pbr_contract(path: Path, state: str, purpose: str) -> dict[str, Any]:
    """Fail closed when an exported review GLB loses authored material evidence."""

    logical_path = _relative(path.resolve())
    digest = _sha256_path(path)
    try:
        tree, binary_offset, binary_length = _read_glb_container(path)
    except (OSError, RuntimeError) as exc:
        return {
            "state": state,
            "purpose": purpose,
            "path": logical_path,
            "sha256": digest,
            "status": "FAIL",
            "failures": [f"GLB container validation failed: {exc}"],
            "counts": {
                "meshes": 0,
                "primitives": 0,
                "materials": 0,
                "textures": 0,
                "images": 0,
            },
            "required_semantic_materials": {},
            "all_textures_embedded": False,
            "all_referenced_materials_double_sided": False,
        }

    materials = tree.get("materials", [])
    textures = tree.get("textures", [])
    images = tree.get("images", [])
    meshes = tree.get("meshes", [])
    buffers = tree.get("buffers", [])
    buffer_views = tree.get("bufferViews", [])
    accessors = tree.get("accessors", [])
    failures: list[str] = []
    if state not in STATE_NAMES:
        failures.append(f"unsupported state {state!r}")
    if purpose not in {"final_review", "qa_overlay"}:
        failures.append(f"unsupported GLB purpose {purpose!r}")
    if not isinstance(materials, list) or not materials:
        failures.append("materials array is empty")
        materials = []
    if not isinstance(textures, list) or not textures:
        failures.append("textures array is empty")
        textures = []
    if not isinstance(images, list) or not images:
        failures.append("images array is empty")
        images = []
    if not isinstance(meshes, list) or not meshes:
        failures.append("meshes array is empty")
        meshes = []
    if not isinstance(buffer_views, list) or not buffer_views:
        failures.append("bufferViews array is empty")
        buffer_views = []
    if not isinstance(accessors, list) or not accessors:
        failures.append("accessors array is empty")
        accessors = []

    declared_buffer_length = -1
    if not isinstance(buffers, list) or len(buffers) != 1:
        failures.append("GLB must declare exactly one embedded buffer")
    else:
        buffer = buffers[0]
        if not isinstance(buffer, dict) or "uri" in buffer:
            failures.append("GLB buffer is not the embedded BIN buffer")
        elif not _is_nonnegative_int(buffer.get("byteLength")):
            failures.append("GLB buffer byteLength is invalid")
        else:
            declared_buffer_length = int(buffer["byteLength"])
            if (
                declared_buffer_length > binary_length
                or binary_length - declared_buffer_length > 3
            ):
                failures.append(
                    "GLB buffer byteLength does not match the BIN chunk"
                )

    view_records: list[dict[str, Any] | None] = []
    for view_index, view in enumerate(buffer_views):
        record: dict[str, Any] | None = None
        if not isinstance(view, dict):
            failures.append(f"bufferView {view_index} is not an object")
        else:
            buffer_index = view.get("buffer")
            byte_offset = view.get("byteOffset", 0)
            byte_length = view.get("byteLength")
            byte_stride = view.get("byteStride")
            valid = True
            if buffer_index != 0 or isinstance(buffer_index, bool):
                failures.append(f"bufferView {view_index} does not use buffer 0")
                valid = False
            if not _is_nonnegative_int(byte_offset):
                failures.append(f"bufferView {view_index} byteOffset is invalid")
                valid = False
            if not _is_nonnegative_int(byte_length) or byte_length <= 0:
                failures.append(f"bufferView {view_index} byteLength is invalid")
                valid = False
            if byte_stride is not None and (
                type(byte_stride) is not int
                or not 4 <= byte_stride <= 252
                or byte_stride % 4 != 0
            ):
                failures.append(f"bufferView {view_index} byteStride is invalid")
                valid = False
            if valid:
                end = int(byte_offset) + int(byte_length)
                if declared_buffer_length < 0 or end > declared_buffer_length:
                    failures.append(f"bufferView {view_index} exceeds the BIN buffer")
                    valid = False
            if valid:
                record = {
                    "offset": int(byte_offset),
                    "length": int(byte_length),
                    "stride": byte_stride,
                }
        view_records.append(record)

    accessor_records: list[dict[str, Any] | None] = []
    for accessor_index, accessor in enumerate(accessors):
        record: dict[str, Any] | None = None
        if not isinstance(accessor, dict):
            failures.append(f"accessor {accessor_index} is not an object")
        else:
            view_index = accessor.get("bufferView")
            byte_offset = accessor.get("byteOffset", 0)
            component_type = accessor.get("componentType")
            accessor_type = accessor.get("type")
            count = accessor.get("count")
            valid = True
            if not _is_index(view_index, len(view_records)) or view_records[view_index] is None:
                failures.append(f"accessor {accessor_index} has no valid bufferView")
                valid = False
            if not _is_nonnegative_int(byte_offset):
                failures.append(f"accessor {accessor_index} byteOffset is invalid")
                valid = False
            if component_type not in _ACCESSOR_COMPONENT_BYTES or isinstance(component_type, bool):
                failures.append(f"accessor {accessor_index} componentType is invalid")
                valid = False
            if accessor_type not in _ACCESSOR_COMPONENT_COUNTS:
                failures.append(f"accessor {accessor_index} type is invalid")
                valid = False
            if type(count) is not int or count <= 0:
                failures.append(f"accessor {accessor_index} count is invalid")
                valid = False
            if valid:
                view = view_records[view_index]
                assert view is not None
                element_size = (
                    _ACCESSOR_COMPONENT_BYTES[component_type]
                    * _ACCESSOR_COMPONENT_COUNTS[accessor_type]
                )
                stride = view["stride"] or element_size
                required = int(byte_offset) + (int(count) - 1) * stride + element_size
                if stride < element_size or required > view["length"]:
                    failures.append(f"accessor {accessor_index} exceeds its bufferView")
                    valid = False
                elif (
                    (view["offset"] + int(byte_offset))
                    % _ACCESSOR_COMPONENT_BYTES[component_type]
                    != 0
                ):
                    failures.append(f"accessor {accessor_index} is misaligned")
                    valid = False
            if valid:
                record = {
                    "componentType": component_type,
                    "type": accessor_type,
                    "count": int(count),
                }
        accessor_records.append(record)

    image_valid: list[bool] = []
    for image_index, image in enumerate(images):
        valid = True
        if not isinstance(image, dict):
            failures.append(f"image {image_index} is not an object")
            image_valid.append(False)
            continue
        view_index = image.get("bufferView")
        if "uri" in image or not _is_index(view_index, len(view_records)):
            failures.append(f"image {image_index} is not embedded in the GLB")
            valid = False
        elif view_records[view_index] is None:
            failures.append(f"image {image_index} uses an invalid bufferView")
            valid = False
        if image.get("mimeType") != "image/png":
            failures.append(f"image {image_index} is not embedded PNG")
            valid = False
        if valid:
            view = view_records[view_index]
            assert view is not None
            png_failure = _embedded_png_failure(
                path,
                binary_offset + view["offset"],
                view["length"],
            )
            if png_failure:
                failures.append(f"image {image_index}: {png_failure}")
                valid = False
        image_valid.append(valid)

    texture_valid: list[bool] = []
    for texture_index, texture in enumerate(textures):
        source = texture.get("source") if isinstance(texture, dict) else None
        valid = _is_index(source, len(images)) and image_valid[source]
        if not valid:
            failures.append(f"texture {texture_index} has no valid embedded image source")
        texture_valid.append(bool(valid))

    primitive_count = 0
    referenced_materials: set[int] = set()
    for mesh_index, mesh in enumerate(meshes):
        primitives = mesh.get("primitives", []) if isinstance(mesh, dict) else []
        if not isinstance(primitives, list) or not primitives:
            failures.append(f"mesh {mesh_index} has no primitives")
            continue
        for primitive_index, primitive in enumerate(primitives):
            primitive_count += 1
            attributes = primitive.get("attributes", {}) if isinstance(primitive, dict) else {}
            if not isinstance(attributes, dict):
                attributes = {}
            missing = sorted({"POSITION", "NORMAL", "TEXCOORD_0"} - set(attributes))
            if missing:
                failures.append(
                    f"mesh {mesh_index} primitive {primitive_index} misses {missing}"
                )
            attribute_records: dict[str, dict[str, Any]] = {}
            for semantic, expected_type in (
                ("POSITION", "VEC3"),
                ("NORMAL", "VEC3"),
                ("TEXCOORD_0", "VEC2"),
            ):
                accessor_index = attributes.get(semantic)
                if (
                    not _is_index(accessor_index, len(accessor_records))
                    or accessor_records[accessor_index] is None
                ):
                    if semantic not in missing:
                        failures.append(
                            f"mesh {mesh_index} primitive {primitive_index} "
                            f"has invalid {semantic} accessor"
                        )
                    continue
                record = accessor_records[accessor_index]
                assert record is not None
                attribute_records[semantic] = record
                if record["type"] != expected_type or record["componentType"] != 5126:
                    failures.append(
                        f"mesh {mesh_index} primitive {primitive_index} "
                        f"has incompatible {semantic} accessor"
                    )
            if "POSITION" in attribute_records:
                position_count = attribute_records["POSITION"]["count"]
                for semantic in ("NORMAL", "TEXCOORD_0"):
                    if (
                        semantic in attribute_records
                        and attribute_records[semantic]["count"] != position_count
                    ):
                        failures.append(
                            f"mesh {mesh_index} primitive {primitive_index} "
                            f"{semantic} count differs from POSITION"
                        )
            indices = primitive.get("indices") if isinstance(primitive, dict) else None
            if indices is not None:
                if (
                    not _is_index(indices, len(accessor_records))
                    or accessor_records[indices] is None
                ):
                    failures.append(
                        f"mesh {mesh_index} primitive {primitive_index} has invalid indices"
                    )
                else:
                    index_record = accessor_records[indices]
                    assert index_record is not None
                    if (
                        index_record["type"] != "SCALAR"
                        or index_record["componentType"] not in {5121, 5123, 5125}
                    ):
                        failures.append(
                            f"mesh {mesh_index} primitive {primitive_index} "
                            "has incompatible indices accessor"
                        )
            material_index = primitive.get("material") if isinstance(primitive, dict) else None
            if not _is_index(material_index, len(materials)):
                failures.append(
                    f"mesh {mesh_index} primitive {primitive_index} has no valid material"
                )
            else:
                referenced_materials.add(material_index)

    unreferenced_materials = sorted(set(range(len(materials))) - referenced_materials)
    if unreferenced_materials:
        failures.append(f"unreferenced materials are present: {unreferenced_materials}")

    referenced_textures: set[int] = set()

    def texture_reference(
        material_index: int,
        label: str,
        value: object,
    ) -> int | None:
        if not isinstance(value, dict):
            failures.append(f"material {material_index} {label} is not an object")
            return None
        texture_index = value.get("index")
        if not _is_index(texture_index, len(textures)) or not texture_valid[texture_index]:
            failures.append(f"material {material_index} {label} has no valid texture")
            return None
        referenced_textures.add(texture_index)
        return texture_index

    for material_index in sorted(referenced_materials):
        material = materials[material_index]
        if not isinstance(material, dict):
            failures.append(f"material {material_index} is not an object")
            continue
        if material.get("doubleSided") is not True:
            failures.append(
                f"material {material_index} is not double-sided for all-angle STEP review"
            )
        pbr = material.get("pbrMetallicRoughness")
        if not isinstance(pbr, dict):
            failures.append(f"material {material_index} has no PBR definition")
            continue
        for label, value in (
            ("baseColorTexture", pbr.get("baseColorTexture")),
            ("metallicRoughnessTexture", pbr.get("metallicRoughnessTexture")),
            ("normalTexture", material.get("normalTexture")),
            ("occlusionTexture", material.get("occlusionTexture")),
            ("emissiveTexture", material.get("emissiveTexture")),
        ):
            if value is not None:
                texture_reference(material_index, label, value)

    required_families = {"leather", "stainless"}
    if state in {"cafe", "focus"}:
        required_families.add("walnut")
    semantic_materials: dict[str, list[str]] = {}
    for label in sorted(required_families):
        profile = _SEMANTIC_PBR_FAMILIES[label]
        candidates = [
            index
            for index, material in enumerate(materials)
            if isinstance(material, dict)
            and any(
                token in str(material.get("name", "")).lower()
                for token in profile["tokens"]
            )
        ]
        semantic_materials[label] = [
            str(materials[index].get("name", "")) for index in candidates
        ]
        if not candidates:
            failures.append(f"semantic {label} material is absent")
            continue
        referenced_candidates = [
            index for index in candidates if index in referenced_materials
        ]
        if not referenced_candidates:
            failures.append(f"semantic {label} material is not referenced by a primitive")
            continue
        for material_index in referenced_candidates:
            material = materials[material_index]
            pbr = material.get("pbrMetallicRoughness", {})
            if not isinstance(pbr, dict):
                continue
            base_texture = texture_reference(
                material_index,
                "semantic baseColorTexture",
                pbr.get("baseColorTexture"),
            )
            normal_texture = texture_reference(
                material_index,
                "semantic normalTexture",
                material.get("normalTexture"),
            )
            if base_texture is None or normal_texture is None:
                failures.append(
                    f"semantic {label} material {material_index} lacks valid "
                    "base-colour and normal textures"
                )
            for factor_name in ("metallicFactor", "roughnessFactor"):
                value = pbr.get(factor_name)
                lower, upper = profile[
                    "metallic" if factor_name == "metallicFactor" else "roughness"
                ]
                if not _is_finite_number(value) or not lower <= float(value) <= upper:
                    failures.append(
                        f"semantic {label} material {material_index} {factor_name} "
                        f"is outside [{lower}, {upper}]"
                    )

    unused_textures = sorted(set(range(len(textures))) - referenced_textures)
    if unused_textures:
        failures.append(f"unreferenced textures are present: {unused_textures}")
    referenced_images = {
        textures[index]["source"]
        for index in referenced_textures
        if isinstance(textures[index], dict)
        and _is_index(textures[index].get("source"), len(images))
    }
    unused_images = sorted(set(range(len(images))) - referenced_images)
    if unused_images:
        failures.append(f"unreferenced images are present: {unused_images}")

    return {
        "state": state,
        "purpose": purpose,
        "path": logical_path,
        "sha256": digest,
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "counts": {
            "meshes": len(meshes),
            "primitives": primitive_count,
            "materials": len(materials),
            "textures": len(textures),
            "images": len(images),
        },
        "required_semantic_materials": semantic_materials,
        "all_textures_embedded": bool(images) and all(image_valid),
        "all_referenced_materials_double_sided": bool(referenced_materials)
        and all(
            isinstance(materials[index], dict)
            and materials[index].get("doubleSided") is True
            for index in referenced_materials
        ),
        "binary_chunk_bytes": binary_length,
    }


def _relative(path: Path) -> str:
    """Match the canonical repository-relative manifest path format."""

    return str(path.relative_to(REPOSITORY_ROOT)).replace("\\", "/")


def _inspect_required_internal_source_occurrences(
    step_path: Path,
    state: str,
) -> dict[str, Any]:
    """Prove the battery and equipment-bay inventory in one source STEP.

    ISO-10303-21 files are ASCII.  Counting the exact ``PRODUCT`` token avoids
    accepting a name that appears only in a comment, a derived QA file or an
    assembly reference.  Exactly one product definition is required per
    physical occurrence name.
    """

    payload = step_path.read_bytes()
    groups: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    for group, names in REQUIRED_FULL_LAYOUT_SOURCE_OCCURRENCES.items():
        counts = {
            name: payload.count(f"PRODUCT('{name}'".encode("ascii"))
            for name in names
        }
        invalid = {
            name: count for name, count in counts.items() if count != 1
        }
        if invalid:
            failures.append(f"{group} PRODUCT counts are not exactly one: {invalid}")
        groups[group] = {
            "required_count": len(names),
            "product_definition_counts": counts,
            "status": "FAIL" if invalid else "PASS",
        }
    return {
        "schema_version": 1,
        "state": state,
        "source_step": _relative(step_path.resolve()),
        "source_step_bytes": len(payload),
        "required_occurrence_count": sum(
            len(names) for names in REQUIRED_FULL_LAYOUT_SOURCE_OCCURRENCES.values()
        ),
        "groups": groups,
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
    }


def _a07_state_report_failures(
    report: object,
    state: str,
) -> list[str]:
    """Validate one JSON-only direct A06/A07 BRep report fail-closed."""

    failures: list[str] = []
    if not isinstance(report, dict):
        return [f"{state} A07 BRep report is not a JSON object"]
    if report.get("schema_version") != 1:
        failures.append(f"{state} A07 BRep schema is not 1")
    if report.get("state") != state:
        failures.append(f"{state} A07 BRep state label drifted")
    if report.get("status") != "PASS" or report.get("failures") != []:
        failures.append(f"{state} A07 BRep report is not a clean PASS")
    if report.get("canonical_exterior_inventory") != list(
        A07_BREP_EXTERIOR_NAMES
    ):
        failures.append(f"{state} A07 exterior inventory drifted")
    if report.get("canonical_internal_inventory") != list(
        A07_BREP_INTERNAL_NAMES
    ):
        failures.append(f"{state} A07 hidden-pin inventory drifted")
    if report.get("actual_a07_inventory") != sorted(A07_BREP_ALL_NAMES):
        failures.append(f"{state} A07 actual inventory is not exact")
    if report.get("visible_exterior_inventory") != sorted(
        A07_BREP_EXTERIOR_NAMES
    ):
        failures.append(f"{state} A07 visible inventory is not exact")

    occurrences = report.get("occurrences")
    physical_ids = report.get("physical_occurrence_ids_by_name")
    if not isinstance(occurrences, dict) or set(occurrences) != set(
        A07_BREP_ALL_NAMES
    ):
        failures.append(f"{state} A07 occurrence evidence inventory drifted")
        occurrences = {}
    if not isinstance(physical_ids, dict) or set(physical_ids) != set(
        A07_BREP_ALL_NAMES
    ):
        failures.append(f"{state} A07 physical-ID inventory drifted")
        physical_ids = {}
    for name in A07_BREP_ALL_NAMES:
        evidence = occurrences.get(name)
        if not isinstance(evidence, dict):
            failures.append(f"{state} {name} lacks direct BRep evidence")
            continue
        if (
            evidence.get("status") != "PASS"
            or evidence.get("physical_occurrence_id_equal") is not True
            or not isinstance(physical_ids.get(name), str)
            or not physical_ids.get(name)
        ):
            failures.append(f"{state} {name} BRep/physical identity failed")
        try:
            if float(evidence.get("symmetric_difference_volume_mm3")) > 1.0e-4:
                failures.append(f"{state} {name} BRep volume delta exceeds limit")
            if float(evidence.get("maximum_bound_delta_mm")) > 1.0e-6:
                failures.append(f"{state} {name} BRep bound delta exceeds limit")
        except (TypeError, ValueError):
            failures.append(f"{state} {name} BRep numeric evidence is invalid")
        expected_translation = [0.0, 0.0, 0.0]
        if state == "focus" and name in A07_FOCUS_MOVING_NAMES:
            expected_translation = [
                0.0,
                136.0 if name in A07_FOCUS_PRIVACY_NAMES else 0.0,
                420.0,
            ]
        if evidence.get("focus_translation_mm") != expected_translation:
            failures.append(f"{state} {name} Focus translation contract drifted")
        if evidence.get("follow_hinge_pose") != (state == "follow"):
            failures.append(f"{state} {name} Follow hinge-pose flag drifted")

    backrest = report.get("a06_backrest_brep_evidence")
    if not isinstance(backrest, dict) or backrest.get("status") != "PASS":
        failures.append(f"{state} A06 shared-hinge backrest BRep failed")
    endpoint = report.get("endpoint_contract")
    if not isinstance(endpoint, dict):
        failures.append(f"{state} A07 endpoint contract is absent")
    elif (
        endpoint.get("focus_moving_translation_mm") != [0.0, 0.0, 420.0]
        or endpoint.get("focus_privacy_translation_mm") != [0.0, 136.0, 420.0]
        or endpoint.get("fixed_inventory_translation_mm") != [0.0, 0.0, 0.0]
        or endpoint.get("follow_a06_a07_shared_hinge_mm") != [160.0, 0.0, 515.0]
        or endpoint.get("follow_fold_deg") != -95.0
        or endpoint.get("follow_shared_hinge_axis_invariant") is not True
    ):
        failures.append(f"{state} A06/A07 endpoint or hinge invariant drifted")
    return failures


def _a07_four_state_brep_gate(
    reports: dict[str, dict[str, Any]],
    state_report_sha256: dict[str, str],
) -> dict[str, Any]:
    """Recompute cross-state A07 rigid identity/pose evidence from JSON."""

    failures: list[str] = []
    if set(reports) != set(STATE_NAMES):
        failures.append("A07 report set is not the exact four states")
    for state in STATE_NAMES:
        failures.extend(_a07_state_report_failures(reports.get(state), state))

    reference = reports.get("ride", {})
    reference_ids = reference.get("physical_occurrence_ids_by_name", {})
    if not isinstance(reference_ids, dict):
        reference_ids = {}
    for state in STATE_NAMES:
        state_ids = reports.get(state, {}).get(
            "physical_occurrence_ids_by_name", {}
        )
        if state_ids != reference_ids:
            failures.append(f"{state} A07 physical IDs differ from Ride")

    ride_occurrences = reference.get("occurrences", {})
    cafe_occurrences = reports.get("cafe", {}).get("occurrences", {})
    focus_occurrences = reports.get("focus", {}).get("occurrences", {})
    translation_counts = {
        "fixed_[0,0,0]": 0,
        "moving_[0,0,420]": 0,
        "privacy_[0,136,420]": 0,
    }
    for name in A07_BREP_ALL_NAMES:
        ride_evidence = (
            ride_occurrences.get(name, {})
            if isinstance(ride_occurrences, dict)
            else {}
        )
        cafe_evidence = (
            cafe_occurrences.get(name, {})
            if isinstance(cafe_occurrences, dict)
            else {}
        )
        focus_evidence = (
            focus_occurrences.get(name, {})
            if isinstance(focus_occurrences, dict)
            else {}
        )
        ride_signature = ride_evidence.get("actual_signature", {})
        cafe_signature = cafe_evidence.get("actual_signature", {})
        focus_signature = focus_evidence.get("actual_signature", {})
        if cafe_signature != ride_signature:
            failures.append(f"Ride/Cafe {name} raw BRep signature differs")
        if not all(
            isinstance(signature, dict)
            for signature in (ride_signature, focus_signature)
        ):
            failures.append(f"Focus {name} lacks comparable rigid signature")
            continue
        expected_translation = [0.0, 0.0, 0.0]
        translation_key = "fixed_[0,0,0]"
        if name in A07_FOCUS_MOVING_NAMES:
            expected_translation = [0.0, 0.0, 420.0]
            translation_key = "moving_[0,0,420]"
        if name in A07_FOCUS_PRIVACY_NAMES:
            expected_translation = [0.0, 136.0, 420.0]
            translation_key = "privacy_[0,136,420]"
        translation_counts[translation_key] += 1
        if (
            focus_signature.get("volume_mm3") != ride_signature.get("volume_mm3")
            or focus_signature.get("area_mm2") != ride_signature.get("area_mm2")
            or focus_signature.get("topology") != ride_signature.get("topology")
        ):
            failures.append(f"Focus {name} is not a rigid copy of Ride")
        try:
            ride_centre = [float(value) for value in ride_signature["centre_mm"]]
            focus_centre = [float(value) for value in focus_signature["centre_mm"]]
            centre_delta = [
                focus_centre[index] - ride_centre[index] for index in range(3)
            ]
            ride_bounds = [float(value) for value in ride_signature["bounds_mm"]]
            focus_bounds = [float(value) for value in focus_signature["bounds_mm"]]
            bound_expected = [
                expected_translation[0],
                expected_translation[0],
                expected_translation[1],
                expected_translation[1],
                expected_translation[2],
                expected_translation[2],
            ]
            if max(
                abs(centre_delta[index] - expected_translation[index])
                for index in range(3)
            ) > 1.0e-6 or max(
                abs(
                    focus_bounds[index]
                    - ride_bounds[index]
                    - bound_expected[index]
                )
                for index in range(6)
            ) > 1.0e-6:
                failures.append(f"Focus {name} rigid translation is incorrect")
        except (KeyError, TypeError, ValueError, IndexError):
            failures.append(f"Focus {name} signature coordinates are invalid")

    if translation_counts != {
        "fixed_[0,0,0]": 6,
        "moving_[0,0,420]": 7,
        "privacy_[0,136,420]": 2,
    }:
        failures.append(f"Focus A07 translation inventory drifted: {translation_counts}")
    return {
        "schema_version": 1,
        "gate": "direct A06/A07 four-state physical BRep and shared-hinge closure",
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "state_count": len(reports),
        "required_state_count": 4,
        "canonical_exterior_inventory": list(A07_BREP_EXTERIOR_NAMES),
        "canonical_internal_inventory": list(A07_BREP_INTERNAL_NAMES),
        "physical_occurrence_ids_by_name": reference_ids,
        "focus_translation_inventory": translation_counts,
        "state_report_sha256": state_report_sha256,
        "states": reports,
    }


def _focus_root_neck_report_failures(report: object) -> list[str]:
    """Validate the JSON-only Focus root-neck release report."""

    failures: list[str] = []
    if not isinstance(report, dict):
        return ["Focus root-neck report is not a JSON object"]
    if (
        report.get("schema_version") != 1
        or report.get("state") != "focus"
        or report.get("status") != "PASS"
        or report.get("failures") != []
    ):
        failures.append("Focus root-neck report is not a clean schema-v1 PASS")
    expected_names = [
        "A09_focus_table_hidden_root_tongue_left",
        "A09_focus_table_hidden_root_tongue_right",
    ]
    if report.get("required_occurrences") != expected_names or report.get(
        "actual_root_tongue_inventory"
    ) != expected_names:
        failures.append("Focus root-neck occurrence inventory drifted")
    sides = report.get("sides")
    if not isinstance(sides, dict) or set(sides) != {"left", "right"}:
        failures.append("Focus root-neck bilateral evidence is incomplete")
        sides = {}
    for side_name in ("left", "right"):
        side = sides.get(side_name)
        if not isinstance(side, dict):
            failures.append(f"Focus {side_name} root-neck report is absent")
            continue
        if side.get("status") != "PASS" or side.get("failures") != []:
            failures.append(f"Focus {side_name} root-neck is not a clean PASS")
        for field in (
            "identity_and_visibility",
            "direct_canonical_brep",
            "smooth_gap_neck_containment",
        ):
            evidence = side.get(field)
            if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
                failures.append(f"Focus {side_name} {field} failed")
        probes = side.get("independent_thin_slice_probes")
        if (
            not isinstance(probes, list)
            or len(probes) != 3
            or any(
                not isinstance(probe, dict) or probe.get("status") != "PASS"
                for probe in probes
            )
        ):
            failures.append(f"Focus {side_name} smooth-neck slice probes failed")
        for field in (
            "a05_zero_collision_clearances",
            "load_path_zero_penetration_contacts",
        ):
            evidence_map = side.get(field)
            if not isinstance(evidence_map, dict) or not evidence_map or any(
                not isinstance(evidence, dict)
                or evidence.get("status") != "PASS"
                for evidence in evidence_map.values()
            ):
                failures.append(f"Focus {side_name} {field} failed")
    mirror = report.get("bilateral_xz_mirror")
    if not isinstance(mirror, dict) or mirror.get("status") != "PASS":
        failures.append("Focus root-neck bilateral XZ mirror failed")
    return failures


def _worker_fragment_path(output: Path, state: str) -> Path:
    return output / WORKER_DIRECTORY_NAME / f"{state}.json"


def _expected_state_artifacts(
    output: Path,
    state: str,
) -> dict[str, tuple[Path, ...]]:
    """Return the exact release-artifact contract for one physical state."""

    if state not in STATE_NAMES:
        raise ValueError(f"Unsupported V8 physical state: {state!r}")
    state_dir = output / state
    return {
        "step": (
            state_dir / f"workcore_e6_layout_full_{state}.step",
            state_dir / f"workcore_e6_exterior_{state}.step",
        ),
        "glb": (
            state_dir / f"workcore_e6_class_a_{state}.glb",
            state_dir / f"workcore_e6_class_a_{state}_qa_overlay.glb",
        ),
        "png": (
            state_dir / f"preview_class_a_{state}.png",
            state_dir / f"preview_class_a_{state}_qa_overlay.png",
            *(
                state_dir / f"silhouette_{view}_{state}.png"
                for view in RENDER_VIEW_NAMES[2:]
            ),
        ),
    }


def _validate_state_artifact_inventory(
    output: Path,
    state: str,
) -> dict[str, list[str]]:
    """Fail closed unless a state directory contains exactly 2 STEP/2 GLB/8 PNG."""

    expected = _expected_state_artifacts(output, state)
    state_dir = output / state
    if not state_dir.is_dir():
        raise RuntimeError(f"State output directory is missing: {state_dir}")

    expected_entries = {
        path.resolve()
        for paths in expected.values()
        for path in paths
    }
    actual_entries = {path.resolve() for path in state_dir.iterdir()}
    missing = sorted(str(path) for path in expected_entries - actual_entries)
    unexpected = sorted(str(path) for path in actual_entries - expected_entries)
    if missing or unexpected:
        raise RuntimeError(
            f"Exact release-artifact inventory failed for {state}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    invalid = [
        str(path)
        for path in sorted(expected_entries, key=str)
        if not path.is_file() or path.stat().st_size <= 0
    ]
    if invalid:
        raise RuntimeError(
            f"Release artifacts are missing, non-files, or empty for {state}: "
            + ", ".join(invalid)
        )

    inventory = {
        kind: [_relative(path.resolve()) for path in paths]
        for kind, paths in expected.items()
    }
    actual_counts = {kind: len(paths) for kind, paths in inventory.items()}
    if actual_counts != EXPECTED_STATE_ARTIFACT_COUNTS:
        raise RuntimeError(
            f"Artifact count contract drifted for {state}: {actual_counts!r}"
        )
    return inventory


def _build_one_state(output: Path, state: str, fragment_path: Path) -> None:
    """Build, export and validate one state inside an expendable process."""

    output = output.resolve()
    fragment_path = fragment_path.resolve()
    expected_fragment = _worker_fragment_path(output, state).resolve()
    if fragment_path != expected_fragment:
        raise RuntimeError(
            "Low-memory worker fragment must use the parent-owned path: "
            f"{expected_fragment}"
        )
    if not (output / INCOMPLETE_MARKER_NAME).is_file():
        raise RuntimeError(
            "Low-memory state workers may only run under an active parent build"
        )
    state_dir = output / state
    if state_dir.exists() and any(state_dir.iterdir()):
        raise FileExistsError(f"State output must start empty: {state_dir}")

    # Deliberately import the CAD/render stack only in the child process.  The
    # imported helpers are the same functions used by the canonical builder.
    from build_class_a_skin import (  # pylint: disable=import-outside-toplevel
        CONTROLLED_SOURCE,
        STATES,
        _assert_sources,
        _combined_bounds,
        _composite_shape_signature,
        _generator_source_hashes,
        _inspect_render_png,
        _parts_shape_signature,
        _render_glb,
        _rigid_collision_report,
        _save_final_layout_composite,
        _save_review_glbs,
        _save_skin_assembly,
        _shape_signature,
        _silhouette_views,
        build_state,
    )
    from exterior_presentation import (  # pylint: disable=import-outside-toplevel
        exterior_parts,
    )
    from skin_common import validate_parts  # pylint: disable=import-outside-toplevel

    state_sources = {
        state_source.configuration: state_source for state_source in STATES
    }
    if tuple(state_sources) != STATE_NAMES:
        raise RuntimeError(
            "Canonical state inventory drifted; update the low-memory "
            f"orchestrator before building: {tuple(state_sources)!r}"
        )
    state_source = state_sources[state]
    build_started_ns = time.time_ns()
    controlled_hashes = _assert_sources()
    generator_hashes = _generator_source_hashes()
    controlled_step_path = CONTROLLED_SOURCE / state_source.step_name
    controlled_internal_inventory = _inspect_required_internal_source_occurrences(
        controlled_step_path,
        state,
    )
    if controlled_internal_inventory["status"] != "PASS":
        raise RuntimeError(
            f"{state} controlled battery/device-bay inventory failed: "
            + " | ".join(controlled_internal_inventory["failures"])
        )

    print(f"[V8 low-memory] building Class-A state: {state}", flush=True)
    state_started = time.perf_counter()
    parts = build_state(state)
    errors = validate_parts(parts)
    if errors:
        raise RuntimeError(f"{state} layout/appearance skin invalid: {errors}")
    # Freeze the exact authored-skin input to every downstream physical gate.
    # The packaging report is otherwise only a detached PASS label attached to
    # A04 metadata; binding it to the controlled STEP hash and this compound
    # signature makes it impossible to reuse after either input changes.
    generated_skin_signature = _parts_shape_signature(parts)
    packaging_reports = [
        part.metadata.get("critical_internal_packaging_report")
        for part in parts
        if part.name == "A04_underseat_belly_closeout"
    ]
    if (
        len(packaging_reports) != 1
        or not isinstance(packaging_reports[0], dict)
        or packaging_reports[0].get("state") != state
        or packaging_reports[0].get("status") != "PASS"
        or packaging_reports[0].get("collision_count") != 0
    ):
        raise RuntimeError(
            f"{state} final skin lacks a passing critical internal packaging report"
        )
    critical_packaging_report = dict(packaging_reports[0])
    critical_packaging_report.update(
        {
            "controlled_source_step": _relative(controlled_step_path.resolve()),
            "controlled_source_step_sha256": controlled_hashes[
                state_source.step_name
            ],
            "controlled_required_internal_occurrence_inventory": (
                controlled_internal_inventory
            ),
            "generated_skin_shape_signature": generated_skin_signature,
            "generated_skin_part_count": len(parts),
            "generated_skin_part_inventory": sorted(part.name for part in parts),
            "input_binding_status": "PASS",
        }
    )
    cafe_deployment_report: dict[str, Any] | None = None
    if state == "cafe":
        from v8_cafe_deployment_clearance import (  # pylint: disable=import-outside-toplevel
            critical_cafe_deployment_report,
        )

        cafe_deployment_report = critical_cafe_deployment_report(parts)
        cafe_deployment_report["controlled_source_step"] = _relative(
            controlled_step_path.resolve()
        )
        cafe_deployment_report["controlled_source_step_sha256"] = _sha256_path(
            controlled_step_path
        )
        cafe_deployment_report["generated_skin_shape_signature"] = (
            generated_skin_signature
        )
        cafe_deployment_report["generated_skin_part_count"] = len(parts)
        if (
            cafe_deployment_report.get("status") != "PASS"
            or cafe_deployment_report.get("collision_count") != 0
            or cafe_deployment_report.get("failures") != []
        ):
            raise RuntimeError(
                "Cafe final table deployment clearance gate failed: "
                + " | ".join(
                    str(item)
                    for item in cafe_deployment_report.get("failures", [])
                )
            )

    collision_report = _rigid_collision_report(parts, state)
    state_dir.mkdir(parents=True, exist_ok=True)
    qa_dir = output / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    critical_packaging_path = _write_json(
        qa_dir / f"critical_internal_packaging_{state}.json",
        critical_packaging_report,
    )
    cafe_deployment_path = (
        _write_json(
            qa_dir / "cafe_table_deployment_clearance_gate.json",
            cafe_deployment_report,
        )
        if cafe_deployment_report is not None
        else None
    )
    collision_path = _write_json(
        qa_dir / f"rigid_pair_collision_{state}.json",
        collision_report,
    )
    if collision_report.get("status") != "PASS":
        raise RuntimeError(
            "Layout/appearance endpoint collision gate failed: "
            f"{state}; evidence={collision_path}"
        )

    visible_parts, visibility_report = exterior_parts(state, parts)
    visible_names = {part.name for part in visible_parts}
    from v8_a07_brep_release_contract import (  # pylint: disable=import-outside-toplevel
        a07_state_brep_report,
    )

    a07_brep_report = a07_state_brep_report(state, parts, visible_names)
    a07_brep_failures = _a07_state_report_failures(a07_brep_report, state)
    if a07_brep_failures:
        raise RuntimeError(
            f"{state} direct A06/A07 BRep release gate failed: "
            + " | ".join(a07_brep_failures)
        )

    focus_root_neck_report: dict[str, Any] | None = None
    if state == "focus":
        from v8_focus_root_neck_release_contract import (  # pylint: disable=import-outside-toplevel
            focus_root_neck_release_report,
        )

        focus_root_neck_report = focus_root_neck_release_report(parts)
        focus_root_neck_failures = _focus_root_neck_report_failures(
            focus_root_neck_report
        )
        if focus_root_neck_failures:
            raise RuntimeError(
                "Focus smooth root-neck direct BRep release gate failed: "
                + " | ".join(focus_root_neck_failures)
            )

    def invariant_signature(part: Any) -> dict[str, object]:
        box = part.shape.BoundingBox()
        return {
            "physical_occurrence_id": part.metadata.get(
                "physical_occurrence_id"
            ),
            "color": list(part.color),
            "material": part.material,
            "material_family": part.metadata.get("material_family"),
            "exterior_visible": part.name in visible_names,
            "volume_mm3": round(float(part.shape.Volume()), 6),
            "center_mm": [
                round(float(part.shape.Center().x), 6),
                round(float(part.shape.Center().y), 6),
                round(float(part.shape.Center().z), 6),
            ],
            "bounds_mm": [
                round(float(value), 6)
                for value in (
                    box.xmin,
                    box.xmax,
                    box.ymin,
                    box.ymax,
                    box.zmin,
                    box.zmax,
                )
            ],
            "topology": {
                "solids": len(part.shape.Solids()),
                "shells": len(part.shape.Shells()),
                "faces": len(part.shape.Faces()),
                "edges": len(part.shape.Edges()),
                "vertices": len(part.shape.Vertices()),
            },
        }

    a07_cmf_signature = {
        part.name: {
            "physical_occurrence_id": part.metadata.get(
                "physical_occurrence_id"
            ),
            "color": list(part.color),
            "material": part.material,
            "material_family": part.metadata.get("material_family"),
            "exterior_visible": part.name in visible_names,
        }
        for part in sorted(parts, key=lambda item: item.name)
        if part.module == "A07" or part.name.startswith("A07_")
    }
    a03_half_wrap_signature = {
        part.name: invariant_signature(part)
        for part in sorted(parts, key=lambda item: item.name)
        if part.name.startswith(
            (
                "A03_wheel_arch_belt_",
                "A03_wheel_end_body_colour_skin_",
                "A03_wheel_end_service_cap_",
                "A03_wheel_end_service_seam_backing_",
                "A03_wheel_end_motion_gaiter_",
            )
        )
    }
    a05_cassette_signature = {
        part.name: invariant_signature(part)
        for part in sorted(parts, key=lambda item: item.name)
        if part.name.startswith("A05_table_root_structural_cassette_")
    }
    right_control_signature = {
        part.name: invariant_signature(part)
        for part in sorted(parts, key=lambda item: item.name)
        if part.name
        in {
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        }
    }
    by_name = {part.name: part for part in parts}
    retired_table_prefixes = (
        "A09_cafe_armrest_to_table_root_bridge_",
        "A09_cafe_root_mechanism_fairing_",
        "A09_cafe_underleaf_saddle_",
        "A09_focus_armrest_to_table_root_bridge_",
        "A09_focus_root_fairing_",
        "A09_focus_underleaf_saddle_",
        "A09_table_lift_moving_stage_",
    )
    retired_table_parts = sorted(
        name for name in by_name if name.startswith(retired_table_prefixes)
    )
    if retired_table_parts:
        raise RuntimeError(
            f"{state} recreated retired table supports: {retired_table_parts}"
        )
    table_layout_contract: dict[str, object] = {
        "retired_exposed_supports": retired_table_parts,
    }
    if state in {"follow", "ride"}:
        visible_a09 = sorted(
            part.name for part in visible_parts if part.module == "A09"
        )
        if visible_a09:
            raise RuntimeError(
                f"{state} exposes deployed A09 occurrences: {visible_a09}"
            )
        table_layout_contract["visible_a09"] = visible_a09
    elif state == "cafe":
        required = {
            "A09_cafe_fixed_root_housing_right",
            "A09_cafe_fixed_yoke_bearing_carrier_right",
            "A09_cafe_rotary_hub_right",
            "A09_cafe_rotary_linear_rail_right",
            "A09_cafe_underleaf_motion_belly_right",
        }
        missing = sorted(required - set(by_name))
        root = by_name.get("A09_cafe_underleaf_motion_belly_right")
        underbelly = by_name.get("A09_table_underbelly_shell_right")
        if (
            missing
            or root is None
            or underbelly is None
            or root.name not in visible_names
            or root.metadata.get("internal_spreader_length_mm") != 220.0
            or root.metadata.get("root_neck_outside_armrest") is not True
            or root.metadata.get("hinge_bearing_and_lock_outside_armrest")
            is not False
            or abs(float(underbelly.shape.BoundingBox().ymax) - 276.0) > 0.01
        ):
            raise RuntimeError(
                f"Cafe table layout contract failed; missing={missing}"
            )
        table_layout_contract.update(
            {
                "root_inventory": sorted(required),
                "visible_root_neck": root.name,
                "internal_spreader_length_mm": 220.0,
                "table_outer_y_mm": round(
                    float(underbelly.shape.BoundingBox().ymax), 6
                ),
            }
        )
    else:
        focus_sides: dict[str, object] = {}
        for side_name, expected_outer in (("left", -276.0), ("right", 276.0)):
            names = {
                f"A05_table_root_structural_cassette_{side_name}",
                f"A09_focus_internal_root_box_{side_name}",
                *(
                    f"A09_focus_internal_nested_guide_stage_{index}_{side_name}"
                    for index in (1, 2, 3)
                ),
                f"A09_focus_table_hidden_root_tongue_{side_name}",
            }
            missing = sorted(names - set(by_name))
            root = by_name.get(
                f"A09_focus_table_hidden_root_tongue_{side_name}"
            )
            underbelly = by_name.get(f"A09_table_underbelly_shell_{side_name}")
            outer = (
                None
                if underbelly is None
                else float(
                    underbelly.shape.BoundingBox().ymin
                    if side_name == "left"
                    else underbelly.shape.BoundingBox().ymax
                )
            )
            if (
                missing
                or root is None
                or root.name not in visible_names
                or root.metadata.get("internal_spreader_length_mm") != 220.0
                or root.metadata.get("root_neck_outside_armrest") is not True
                or root.metadata.get("hinge_bearing_and_lock_outside_armrest")
                is not False
                or outer is None
                or abs(outer - expected_outer) > 0.01
            ):
                raise RuntimeError(
                    f"Focus {side_name} table layout contract failed; "
                    f"missing={missing}, outer={outer}"
                )
            focus_sides[side_name] = {
                "inventory": sorted(names),
                "visible_root_neck": root.name,
                "internal_spreader_length_mm": 220.0,
                "table_outer_y_mm": round(outer, 6),
            }
        table_layout_contract["sides"] = focus_sides
    full_layout_step = state_dir / f"workcore_e6_layout_full_{state}.step"
    exterior_step = state_dir / f"workcore_e6_exterior_{state}.step"
    underlay_shape, source_selection_evidence = _save_final_layout_composite(
        state_source,
        parts,
        full_layout_step,
    )
    source_underlay_signature = _shape_signature(underlay_shape)
    expected_full_layout_signature = _composite_shape_signature(
        underlay_shape,
        parts,
    )
    fixed_full_source_solid_count = EXPECTED_DFR5_SOURCE_SOLID_COUNTS[state]
    fixed_layout_source_solid_count = EXPECTED_FINAL_LAYOUT_SOURCE_SOLID_COUNTS[
        state
    ]
    full_source_signature = source_selection_evidence["source_shape_signature"]
    if int(full_source_signature["solid_count"]) != fixed_full_source_solid_count:
        raise RuntimeError(
            f"{state} controlled STEP importer returned "
            f"{full_source_signature['solid_count']} source solids; "
            f"fixed DFR5 baseline is {fixed_full_source_solid_count}"
        )
    if int(source_underlay_signature["solid_count"]) != (
        fixed_layout_source_solid_count
    ):
        raise RuntimeError(
            f"{state} disposition-filtered layout underlay contains "
            f"{source_underlay_signature['solid_count']} solids; "
            f"fixed baseline is {fixed_layout_source_solid_count}"
        )
    if int(expected_full_layout_signature["solid_count"]) != (
        fixed_layout_source_solid_count
        + int(generated_skin_signature["solid_count"])
    ):
        raise RuntimeError(
            f"{state} expected full-layout solid count does not equal the "
            "fixed DFR5 baseline plus generated skin"
        )
    selected_source_names = set(
        source_selection_evidence["selected_occurrence_names"]
    )
    required_source_names = set(required_selected_occurrence_names())
    if not required_source_names <= selected_source_names:
        raise RuntimeError(
            f"{state} final-layout source selection omitted required battery/"
            f"equipment occurrences: "
            f"{sorted(required_source_names - selected_source_names)}"
        )
    generated_part_names = {part.name for part in parts}
    missing_replacement_proxies = {
        source_name: proxy_name
        for source_name, proxy_name in REQUIRED_REPLACED_SOURCE_PROXIES.items()
        if source_name in selected_source_names
        or proxy_name not in generated_part_names
    }
    if missing_replacement_proxies:
        raise RuntimeError(
            f"{state} required source replacements are not one-for-one: "
            f"{missing_replacement_proxies}"
        )
    if not source_selection_evidence.get("retired_side_opening_armrest_absent"):
        raise RuntimeError(
            f"{state} final-layout source selection retained a retired "
            "side-opening armrest occurrence"
        )
    del underlay_shape
    gc.collect()
    _save_skin_assembly(visible_parts, exterior_step)
    final_glb, qa_glb, kept_source_names = _save_review_glbs(
        state_source,
        visible_parts,
        state_dir,
        qa_parts=parts,
    )
    pbr_checks = [
        _inspect_glb_pbr_contract(final_glb, state, "final_review"),
        _inspect_glb_pbr_contract(qa_glb, state, "qa_overlay"),
    ]
    pbr_report_path = _write_json(
        qa_dir / f"glb_pbr_material_{state}.json",
        {
            "schema_version": 1,
            "gate": "semantic self-contained glTF PBR material contract",
            "state": state,
            "status": (
                "PASS"
                if all(check["status"] == "PASS" for check in pbr_checks)
                else "FAIL"
            ),
            "checks": pbr_checks,
        },
    )
    pbr_failures = [
        f"{check['purpose']}: " + "; ".join(check["failures"])
        for check in pbr_checks
        if check["status"] != "PASS"
    ]
    if pbr_failures:
        raise RuntimeError(
            f"{state} GLB PBR material gate failed: " + " | ".join(pbr_failures)
        )

    render_checks: list[dict[str, object]] = []
    final_png = state_dir / f"preview_class_a_{state}.png"
    qa_png = state_dir / f"preview_class_a_{state}_qa_overlay.png"
    _render_glb(final_glb, final_png, state_source)
    _render_glb(qa_glb, qa_png, state_source)

    hero_check = _inspect_render_png(
        final_png,
        build_started_ns=build_started_ns,
        require_clear_frame=False,
    )
    hero_check.update({"state": state, "view": "hero"})
    qa_check = _inspect_render_png(
        qa_png,
        build_started_ns=build_started_ns,
        require_clear_frame=False,
    )
    qa_check.update({"state": state, "view": "qa_overlay"})
    render_checks.extend((hero_check, qa_check))

    silhouettes: dict[str, str] = {}
    for view_name, (view_state, scale) in _silhouette_views(state_source).items():
        path = state_dir / f"silhouette_{view_name}_{state}.png"
        camera = _render_glb(
            final_glb,
            path,
            view_state,
            parallel_scale=scale,
            include_floor=False,
            auto_frame=True,
            underside_fill=view_name == "bottom",
        )
        check = _inspect_render_png(
            path,
            build_started_ns=build_started_ns,
            require_clear_frame=True,
        )
        check.update({"state": state, "view": view_name, "camera": camera})
        render_checks.append(check)
        silhouettes[view_name] = _relative(path)

    artifact_inventory = _validate_state_artifact_inventory(output, state)
    artifact_sha256 = {
        _relative(path.resolve()): _sha256_path(path)
        for paths in _expected_state_artifacts(output, state).values()
        for path in paths
    }
    generator_hashes_after = _generator_source_hashes()
    if generator_hashes_after != generator_hashes:
        changed = sorted(
            path
            for path in set(generator_hashes) | set(generator_hashes_after)
            if generator_hashes.get(path) != generator_hashes_after.get(path)
        )
        raise RuntimeError(
            f"V8 generator sources changed while building {state}: "
            + ", ".join(changed)
        )

    a07_brep_report.update(
        {
            "controlled_source_step": _relative(controlled_step_path.resolve()),
            "controlled_source_step_sha256": controlled_hashes[
                state_source.step_name
            ],
            "generated_skin_shape_signature": generated_skin_signature,
            "generated_skin_part_count": len(parts),
            "exterior_step": _relative(exterior_step.resolve()),
            "exterior_step_sha256": artifact_sha256[_relative(exterior_step)],
            "exterior_part_inventory": [part.name for part in visible_parts],
            "output_binding_status": "PASS",
        }
    )
    a07_brep_path = _write_json(
        qa_dir / f"a07_brep_state_{state}.json",
        a07_brep_report,
    )
    a07_brep_sha256 = _sha256_path(a07_brep_path)
    focus_root_neck_path: Path | None = None
    focus_root_neck_sha256: str | None = None
    if focus_root_neck_report is not None:
        focus_root_neck_report.update(
            {
                "controlled_source_step": _relative(
                    controlled_step_path.resolve()
                ),
                "controlled_source_step_sha256": controlled_hashes[
                    state_source.step_name
                ],
                "generated_skin_shape_signature": generated_skin_signature,
                "generated_skin_part_count": len(parts),
                "exterior_step": _relative(exterior_step.resolve()),
                "exterior_step_sha256": artifact_sha256[
                    _relative(exterior_step)
                ],
                "exterior_part_inventory": [
                    part.name for part in visible_parts
                ],
                "output_binding_status": "PASS",
            }
        )
        focus_root_neck_path = _write_json(
            qa_dir / "focus_root_neck_release_gate.json",
            focus_root_neck_report,
        )
        focus_root_neck_sha256 = _sha256_path(focus_root_neck_path)

    # This payload is byte-for-byte structured like one entry in the canonical
    # combined manifest.  The transient wrapper is removed after aggregation.
    state_payload = {
        "generated_skin_part_count": len(parts),
        "exterior_part_count": len(visible_parts),
        "generated_skin_bounds_mm": _combined_bounds(parts),
        "exterior_bounds_mm": _combined_bounds(visible_parts),
        "full_layout_step": _relative(full_layout_step),
        "full_layout_step_sha256": artifact_sha256[_relative(full_layout_step)],
        "full_layout_underlay_assembly_name": source_selection_evidence[
            "underlay_assembly_name"
        ],
        "controlled_full_layout_source_step": _relative(
            controlled_step_path.resolve()
        ),
        "controlled_full_layout_source_step_sha256": controlled_hashes[
            state_source.step_name
        ],
        "controlled_internal_occurrence_inventory": (
            controlled_internal_inventory
        ),
        "controlled_full_source_shape_signature": full_source_signature,
        "controlled_full_source_fixed_solid_count": (
            fixed_full_source_solid_count
        ),
        "controlled_underlay_shape_signature": source_underlay_signature,
        "controlled_underlay_fixed_solid_count": (
            fixed_layout_source_solid_count
        ),
        "controlled_source_selection_evidence": source_selection_evidence,
        "generated_skin_shape_signature": generated_skin_signature,
        "expected_full_layout_shape_signature": expected_full_layout_signature,
        "exterior_step": _relative(exterior_step),
        "exterior_step_sha256": artifact_sha256[_relative(exterior_step)],
        "review_glb": _relative(final_glb),
        "review_glb_sha256": artifact_sha256[_relative(final_glb)],
        "qa_glb": _relative(qa_glb),
        "qa_glb_sha256": artifact_sha256[_relative(qa_glb)],
        "preview": _relative(final_png),
        "qa_preview": _relative(qa_png),
        "silhouette_views": silhouettes,
        "presentation_source_geometry": kept_source_names,
        "generated_skin_part_inventory": [part.name for part in parts],
        "full_layout_inventory_policy": (
            "disposition-filtered hash-pinned DFR5 source occurrences "
            "(retain_exposed, conceal_behind_access and internal_enclosed only) "
            "plus the exact generated_skin_part_inventory; replace_surface and "
            "trace_only_retired are excluded, and physical inclusion is "
            "independently proved after STEP export"
        ),
        "exterior_part_inventory": [part.name for part in visible_parts],
        "exterior_visibility_report": visibility_report,
        "a07_brep_state_gate": _relative(a07_brep_path.resolve()),
        "a07_brep_state_gate_sha256": a07_brep_sha256,
        "a07_brep_state_status": "PASS",
        "a07_cmf_and_visibility_signature": a07_cmf_signature,
        "focus_root_neck_release_gate": (
            _relative(focus_root_neck_path.resolve())
            if focus_root_neck_path is not None
            else None
        ),
        "focus_root_neck_release_gate_sha256": focus_root_neck_sha256,
        "focus_root_neck_release_status": (
            "PASS" if state == "focus" else "NOT_APPLICABLE"
        ),
        "a03_half_wrap_identity_cmf_and_visibility_signature": (
            a03_half_wrap_signature
        ),
        "a05_table_root_cassette_identity_signature": (
            a05_cassette_signature
        ),
        "right_control_identity_and_visibility_signature": (
            right_control_signature
        ),
        "table_layout_contract": table_layout_contract,
        "critical_internal_packaging_gate": _relative(
            critical_packaging_path.resolve()
        ),
        "critical_internal_packaging_status": "PASS",
        "cafe_table_deployment_clearance_gate": (
            _relative(cafe_deployment_path.resolve())
            if cafe_deployment_path is not None
            else None
        ),
        "cafe_table_deployment_clearance_status": (
            "PASS" if state == "cafe" else "NOT_APPLICABLE"
        ),
        "endpoint_collision_report": _relative(collision_path),
        "glb_pbr_material_report": _relative(pbr_report_path),
        "glb_pbr_material_checks": pbr_checks,
        "artifact_inventory": artifact_inventory,
        "artifact_sha256": artifact_sha256,
    }
    _write_json(
        fragment_path,
        {
            "schema_version": 1,
            "state": state,
            "controlled_source_hashes": controlled_hashes,
            "generator_source_hashes": generator_hashes,
            "state_payload": state_payload,
            "render_checks": render_checks,
        },
    )
    print(
        f"[V8 low-memory] completed {state} in "
        f"{time.perf_counter() - state_started:.1f}s "
        f"({len(parts)} layout parts, {len(render_checks)} renders)",
        flush=True,
    )


def _load_worker_fragment(path: Path, expected_state: str) -> dict[str, Any]:
    output = path.resolve().parents[1]
    if not path.is_file():
        raise RuntimeError(
            f"Low-memory worker did not write its state summary: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid low-memory worker summary {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Worker summary is not a JSON object: {path}")
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported worker summary schema: {path}")
    if payload.get("state") != expected_state:
        raise RuntimeError(
            f"Worker state mismatch in {path}: {payload.get('state')!r}"
        )
    if not isinstance(payload.get("controlled_source_hashes"), dict):
        raise RuntimeError(f"Worker summary lacks controlled source hashes: {path}")
    if not isinstance(payload.get("generator_source_hashes"), dict):
        raise RuntimeError(f"Worker summary lacks generator source hashes: {path}")
    state_payload = payload.get("state_payload")
    if not isinstance(state_payload, dict):
        raise RuntimeError(f"Worker summary lacks state manifest data: {path}")
    if state_payload.get("full_layout_internal_inventory_status") != "PASS":
        raise RuntimeError(
            f"Independent full-layout inventory verifier did not pass for "
            f"{expected_state}"
        )
    expected_internal_report = (
        output / "qa" / f"full_layout_internal_inventory_{expected_state}.json"
    ).resolve()
    declared_internal_report = state_payload.get(
        "full_layout_internal_inventory_gate"
    )
    if (
        not isinstance(declared_internal_report, str)
        or (REPOSITORY_ROOT / declared_internal_report).resolve()
        != expected_internal_report
        or not expected_internal_report.is_file()
    ):
        raise RuntimeError(
            f"Full-layout internal inventory report path is invalid for "
            f"{expected_state}"
        )
    try:
        internal_report = json.loads(
            expected_internal_report.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Invalid full-layout internal report for {expected_state}: {exc}"
        ) from exc
    if (
        not isinstance(internal_report, dict)
        or internal_report.get("state") != expected_state
        or internal_report.get("status") != "PASS"
        or internal_report.get("failures") != []
        or internal_report.get("full_layout_step")
        != state_payload.get("full_layout_step")
        or internal_report.get("full_layout_step_sha256")
        != state_payload.get("full_layout_step_sha256")
        or internal_report.get("required_internal_occurrences")
        != state_payload.get("controlled_internal_occurrence_inventory")
        or internal_report.get("reimported_full_layout_shape_signature")
        != state_payload.get("reimported_full_layout_shape_signature")
        or internal_report.get(
            "required_internal_occurrence_brep_identity_status"
        )
        != "PASS"
        or not isinstance(
            internal_report.get(
                "required_internal_occurrence_brep_evidence"
            ),
            dict,
        )
        or len(
            internal_report.get(
                "required_internal_occurrence_brep_evidence", {}
            )
        )
        != len(required_selected_occurrence_names())
        or _canonical_payload_sha256(
            internal_report.get(
                "required_internal_occurrence_brep_evidence", {}
            )
        )
        != internal_report.get(
            "required_internal_occurrence_brep_evidence_sha256"
        )
        or internal_report.get("critical_internal_packaging_gate")
        != _relative(
            (
                output
                / "qa"
                / f"critical_internal_packaging_{expected_state}.json"
            ).resolve()
        )
        or internal_report.get("critical_internal_packaging_gate_sha256")
        != state_payload.get("critical_internal_packaging_gate_sha256")
    ):
        raise RuntimeError(
            f"Full-layout internal inventory evidence drifted for {expected_state}"
        )
    expected_packaging_report = (
        output / "qa" / f"critical_internal_packaging_{expected_state}.json"
    ).resolve()
    declared_packaging_report = state_payload.get(
        "critical_internal_packaging_gate"
    )
    if (
        state_payload.get("critical_internal_packaging_status") != "PASS"
        or not isinstance(declared_packaging_report, str)
        or (REPOSITORY_ROOT / declared_packaging_report).resolve()
        != expected_packaging_report
        or not expected_packaging_report.is_file()
    ):
        raise RuntimeError(
            f"Critical internal packaging report path is invalid for "
            f"{expected_state}"
        )
    try:
        packaging_report = json.loads(
            expected_packaging_report.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Invalid critical internal packaging report for "
            f"{expected_state}: {exc}"
        ) from exc
    if (
        not isinstance(packaging_report, dict)
        or packaging_report.get("state") != expected_state
        or packaging_report.get("status") != "PASS"
        or packaging_report.get("collision_count") != 0
        or packaging_report.get("collisions") != []
        or packaging_report.get("missing_replacement_proxies") != {}
        or packaging_report.get("input_binding_status") != "PASS"
        or packaging_report.get("final_output_binding_status") != "PASS"
        or packaging_report.get("controlled_source_step")
        != state_payload.get("controlled_full_layout_source_step")
        or packaging_report.get("controlled_source_step_sha256")
        != state_payload.get("controlled_full_layout_source_step_sha256")
        or packaging_report.get(
            "controlled_required_internal_occurrence_inventory"
        )
        != state_payload.get("controlled_internal_occurrence_inventory")
        or packaging_report.get("generated_skin_shape_signature")
        != state_payload.get("generated_skin_shape_signature")
        or packaging_report.get("generated_skin_part_count")
        != state_payload.get("generated_skin_part_count")
        or packaging_report.get("generated_skin_part_inventory")
        != sorted(state_payload.get("generated_skin_part_inventory", []))
        or packaging_report.get("full_layout_step")
        != state_payload.get("full_layout_step")
        or packaging_report.get("full_layout_step_sha256")
        != state_payload.get("full_layout_step_sha256")
        or packaging_report.get("reimported_full_layout_shape_signature")
        != state_payload.get("reimported_full_layout_shape_signature")
        or packaging_report.get("final_step_required_internal_brep_identity_status")
        != "PASS"
        or packaging_report.get(
            "final_step_required_internal_brep_evidence_sha256"
        )
        != internal_report.get(
            "required_internal_occurrence_brep_evidence_sha256"
        )
        or packaging_report.get("full_layout_internal_inventory_gate")
        != state_payload.get("full_layout_internal_inventory_gate")
        or _sha256_path(expected_packaging_report)
        != state_payload.get("critical_internal_packaging_gate_sha256")
    ):
        raise RuntimeError(
            f"Critical internal packaging evidence failed for {expected_state}"
        )
    declared_cafe_report = state_payload.get(
        "cafe_table_deployment_clearance_gate"
    )
    declared_cafe_status = state_payload.get(
        "cafe_table_deployment_clearance_status"
    )
    expected_cafe_report = (
        output / "qa" / "cafe_table_deployment_clearance_gate.json"
    ).resolve()
    if expected_state == "cafe":
        if (
            declared_cafe_status != "PASS"
            or not isinstance(declared_cafe_report, str)
            or (REPOSITORY_ROOT / declared_cafe_report).resolve()
            != expected_cafe_report
            or not expected_cafe_report.is_file()
        ):
            raise RuntimeError("Cafe deployment clearance report path is invalid")
        try:
            cafe_report = json.loads(
                expected_cafe_report.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Invalid Cafe deployment clearance report: {exc}"
            ) from exc
        if (
            not isinstance(cafe_report, dict)
            or cafe_report.get("state") != "cafe"
            or cafe_report.get("status") != "PASS"
            or cafe_report.get("failures") != []
            or cafe_report.get("collision_count") != 0
            or cafe_report.get("clearance_lift_mm") != 90.0
            or cafe_report.get("final_endpoint_unchanged") is not True
            or cafe_report.get("controlled_source_step")
            != state_payload.get("controlled_full_layout_source_step")
            or cafe_report.get("controlled_source_step_sha256")
            != state_payload.get("controlled_full_layout_source_step_sha256")
            or cafe_report.get("generated_skin_shape_signature")
            != state_payload.get("generated_skin_shape_signature")
        ):
            raise RuntimeError("Cafe deployment clearance evidence failed")
    elif declared_cafe_status != "NOT_APPLICABLE" or declared_cafe_report is not None:
        raise RuntimeError(
            f"Non-Cafe state {expected_state} declared Cafe deployment evidence"
        )

    expected_a07_report = (
        output / "qa" / f"a07_brep_state_{expected_state}.json"
    ).resolve()
    declared_a07_report = state_payload.get("a07_brep_state_gate")
    if (
        state_payload.get("a07_brep_state_status") != "PASS"
        or not isinstance(declared_a07_report, str)
        or (REPOSITORY_ROOT / declared_a07_report).resolve()
        != expected_a07_report
        or not expected_a07_report.is_file()
        or _sha256_path(expected_a07_report)
        != state_payload.get("a07_brep_state_gate_sha256")
    ):
        raise RuntimeError(
            f"A07 direct BRep report path/hash is invalid for {expected_state}"
        )
    try:
        a07_report = json.loads(expected_a07_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Invalid A07 direct BRep report for {expected_state}: {exc}"
        ) from exc
    a07_report_failures = _a07_state_report_failures(
        a07_report, expected_state
    )
    if (
        a07_report_failures
        or a07_report.get("controlled_source_step")
        != state_payload.get("controlled_full_layout_source_step")
        or a07_report.get("controlled_source_step_sha256")
        != state_payload.get("controlled_full_layout_source_step_sha256")
        or a07_report.get("generated_skin_shape_signature")
        != state_payload.get("generated_skin_shape_signature")
        or a07_report.get("generated_skin_part_count")
        != state_payload.get("generated_skin_part_count")
        or a07_report.get("exterior_step")
        != state_payload.get("exterior_step")
        or a07_report.get("exterior_step_sha256")
        != state_payload.get("exterior_step_sha256")
        or a07_report.get("exterior_part_inventory")
        != state_payload.get("exterior_part_inventory")
        or a07_report.get("output_binding_status") != "PASS"
    ):
        raise RuntimeError(
            f"A07 direct BRep evidence failed for {expected_state}: "
            + " | ".join(a07_report_failures)
        )
    a07_cmf = state_payload.get("a07_cmf_and_visibility_signature")
    if not isinstance(a07_cmf, dict) or set(a07_cmf) != set(
        A07_BREP_ALL_NAMES
    ):
        raise RuntimeError(f"A07 CMF redundancy inventory drifted for {expected_state}")
    report_ids = a07_report.get("physical_occurrence_ids_by_name", {})
    report_visible = set(a07_report.get("visible_exterior_inventory", []))
    if any(
        not isinstance(a07_cmf.get(name), dict)
        or a07_cmf[name].get("physical_occurrence_id")
        != report_ids.get(name)
        or bool(a07_cmf[name].get("exterior_visible"))
        != (name in report_visible)
        for name in A07_BREP_ALL_NAMES
    ):
        raise RuntimeError(
            f"A07 direct BRep and CMF/visibility evidence disagree for {expected_state}"
        )

    declared_focus_report = state_payload.get("focus_root_neck_release_gate")
    declared_focus_status = state_payload.get("focus_root_neck_release_status")
    declared_focus_hash = state_payload.get(
        "focus_root_neck_release_gate_sha256"
    )
    expected_focus_report = (
        output / "qa" / "focus_root_neck_release_gate.json"
    ).resolve()
    if expected_state == "focus":
        if (
            declared_focus_status != "PASS"
            or not isinstance(declared_focus_report, str)
            or (REPOSITORY_ROOT / declared_focus_report).resolve()
            != expected_focus_report
            or not expected_focus_report.is_file()
            or _sha256_path(expected_focus_report) != declared_focus_hash
        ):
            raise RuntimeError("Focus root-neck report path/hash is invalid")
        try:
            focus_report = json.loads(
                expected_focus_report.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid Focus root-neck report: {exc}") from exc
        focus_report_failures = _focus_root_neck_report_failures(focus_report)
        if (
            focus_report_failures
            or focus_report.get("controlled_source_step")
            != state_payload.get("controlled_full_layout_source_step")
            or focus_report.get("controlled_source_step_sha256")
            != state_payload.get("controlled_full_layout_source_step_sha256")
            or focus_report.get("generated_skin_shape_signature")
            != state_payload.get("generated_skin_shape_signature")
            or focus_report.get("generated_skin_part_count")
            != state_payload.get("generated_skin_part_count")
            or focus_report.get("exterior_step")
            != state_payload.get("exterior_step")
            or focus_report.get("exterior_step_sha256")
            != state_payload.get("exterior_step_sha256")
            or focus_report.get("exterior_part_inventory")
            != state_payload.get("exterior_part_inventory")
            or focus_report.get("output_binding_status") != "PASS"
        ):
            raise RuntimeError(
                "Focus root-neck evidence failed: "
                + " | ".join(focus_report_failures)
            )
    elif (
        declared_focus_status != "NOT_APPLICABLE"
        or declared_focus_report is not None
        or declared_focus_hash is not None
    ):
        raise RuntimeError(
            f"Non-Focus state {expected_state} declared Focus root-neck evidence"
        )
    checks = payload.get("render_checks")
    if not isinstance(checks, list) or len(checks) != 8:
        raise RuntimeError(
            f"Worker render inventory for {expected_state} is not eight images"
        )
    expected_views = set(RENDER_VIEW_NAMES)
    actual_views = {
        str(check.get("view"))
        for check in checks
        if isinstance(check, dict) and check.get("state") == expected_state
    }
    if actual_views != expected_views or any(
        not isinstance(check, dict) or check.get("state") != expected_state
        for check in checks
    ):
        raise RuntimeError(
            f"Worker render views for {expected_state} do not match the exact "
            f"eight-view contract: {sorted(actual_views)!r}"
        )

    actual_inventory = _validate_state_artifact_inventory(output, expected_state)
    if state_payload.get("artifact_inventory") != actual_inventory:
        raise RuntimeError(
            f"Worker artifact manifest disagrees with disk for {expected_state}"
        )
    expected_hash_paths = {
        artifact
        for artifacts in actual_inventory.values()
        for artifact in artifacts
    }
    declared_hashes = state_payload.get("artifact_sha256")
    if not isinstance(declared_hashes, dict) or set(declared_hashes) != expected_hash_paths:
        raise RuntimeError(
            f"Worker artifact hash inventory is incomplete for {expected_state}"
        )
    actual_hashes = {
        artifact: _sha256_path(REPOSITORY_ROOT / artifact)
        for artifact in expected_hash_paths
    }
    if declared_hashes != actual_hashes:
        raise RuntimeError(
            f"Worker artifact hashes disagree with disk for {expected_state}"
        )
    pbr_checks = state_payload.get("glb_pbr_material_checks")
    if (
        not isinstance(pbr_checks, list)
        or len(pbr_checks) != 2
        or any(
            not isinstance(check, dict) or check.get("status") != "PASS"
            for check in pbr_checks
        )
    ):
        raise RuntimeError(
            f"Worker GLB PBR material gate did not pass twice for {expected_state}"
        )
    expected_pbr_paths = {
        "final_review": actual_inventory["glb"][0],
        "qa_overlay": actual_inventory["glb"][1],
    }
    pbr_by_purpose = {
        str(check.get("purpose")): check
        for check in pbr_checks
        if isinstance(check, dict)
        and check.get("state") == expected_state
    }
    if set(pbr_by_purpose) != set(expected_pbr_paths):
        raise RuntimeError(
            f"Worker GLB PBR purpose/state matrix is invalid for {expected_state}"
        )
    for purpose, artifact in expected_pbr_paths.items():
        check = pbr_by_purpose[purpose]
        if (
            check.get("path") != artifact
            or check.get("sha256") != actual_hashes[artifact]
        ):
            raise RuntimeError(
                f"Worker GLB PBR path/hash disagrees with disk for "
                f"{expected_state}.{purpose}"
            )
    pbr_report = state_payload.get("glb_pbr_material_report")
    expected_pbr_report_path = (
        output / "qa" / f"glb_pbr_material_{expected_state}.json"
    ).resolve()
    expected_pbr_report = _relative(expected_pbr_report_path)
    if (
        pbr_report != expected_pbr_report
        or not expected_pbr_report_path.is_file()
    ):
        raise RuntimeError(
            f"Worker GLB PBR material report is missing for {expected_state}"
        )
    try:
        pbr_report_payload = json.loads(
            expected_pbr_report_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Worker GLB PBR material report is invalid for {expected_state}: {exc}"
        ) from exc
    if (
        not isinstance(pbr_report_payload, dict)
        or pbr_report_payload.get("state") != expected_state
        or pbr_report_payload.get("status") != "PASS"
        or pbr_report_payload.get("checks") != pbr_checks
    ):
        raise RuntimeError(
            f"Worker GLB PBR material report content drifted for {expected_state}"
        )
    expected_render_paths = set(actual_inventory["png"])
    actual_render_paths = {str(check.get("path")) for check in checks}
    if actual_render_paths != expected_render_paths:
        raise RuntimeError(
            f"Worker render paths for {expected_state} do not match the exact "
            "release filenames"
        )
    for check in checks:
        artifact = str(check.get("path"))
        if check.get("sha256") != actual_hashes[artifact]:
            raise RuntimeError(
                f"Worker render analysis hash disagrees with disk for {artifact}"
            )
    return payload


def _verify_final_artifact_hashes(
    output: Path,
    fragments: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Re-hash the exact 48 release artifacts and align every derived check."""

    final_hashes: dict[str, str] = {}
    for state in STATE_NAMES:
        state_payload = fragments[state].get("state_payload")
        if not isinstance(state_payload, dict):
            raise RuntimeError(f"Final fragment payload is missing for {state}")
        inventory = _validate_state_artifact_inventory(output, state)
        if state_payload.get("artifact_inventory") != inventory:
            raise RuntimeError(f"Final on-disk artifact inventory drifted for {state}")
        expected_paths = {
            artifact
            for artifacts in inventory.values()
            for artifact in artifacts
        }
        declared = state_payload.get("artifact_sha256")
        if not isinstance(declared, dict) or set(declared) != expected_paths:
            raise RuntimeError(f"Final artifact hash inventory is invalid for {state}")
        actual = {
            artifact: _sha256_path(REPOSITORY_ROOT / artifact)
            for artifact in expected_paths
        }
        if actual != declared:
            changed = sorted(
                artifact
                for artifact in expected_paths
                if actual.get(artifact) != declared.get(artifact)
            )
            raise RuntimeError(
                f"Final artifact bytes drifted for {state}: " + ", ".join(changed)
            )

        path_sha_fields = (
            ("full_layout_step", "full_layout_step_sha256"),
            ("exterior_step", "exterior_step_sha256"),
            ("review_glb", "review_glb_sha256"),
            ("qa_glb", "qa_glb_sha256"),
        )
        for path_field, sha_field in path_sha_fields:
            artifact = state_payload.get(path_field)
            if (
                not isinstance(artifact, str)
                or artifact not in actual
                or state_payload.get(sha_field) != actual[artifact]
            ):
                raise RuntimeError(
                    f"Final {path_field}/{sha_field} pair drifted for {state}"
                )

        render_checks = fragments[state].get("render_checks")
        if not isinstance(render_checks, list) or len(render_checks) != 8:
            raise RuntimeError(f"Final render checks are incomplete for {state}")
        for check in render_checks:
            if not isinstance(check, dict):
                raise RuntimeError(f"Final render check is malformed for {state}")
            artifact = check.get("path")
            if (
                not isinstance(artifact, str)
                or artifact not in actual
                or check.get("sha256") != actual[artifact]
            ):
                raise RuntimeError(
                    f"Final render analysis hash drifted for {state}: {artifact!r}"
                )

        pbr_checks = state_payload.get("glb_pbr_material_checks")
        if not isinstance(pbr_checks, list) or len(pbr_checks) != 2:
            raise RuntimeError(f"Final PBR checks are incomplete for {state}")
        for check in pbr_checks:
            if not isinstance(check, dict):
                raise RuntimeError(f"Final PBR check is malformed for {state}")
            artifact = check.get("path")
            if (
                not isinstance(artifact, str)
                or artifact not in actual
                or check.get("sha256") != actual[artifact]
            ):
                raise RuntimeError(
                    f"Final PBR analysis hash drifted for {state}: {artifact!r}"
                )
        final_hashes.update(actual)

    expected_count = 4 * sum(EXPECTED_STATE_ARTIFACT_COUNTS.values())
    if len(final_hashes) != expected_count:
        raise RuntimeError(
            f"Final artifact hash count is {len(final_hashes)}, expected {expected_count}"
        )
    return final_hashes


def _inspect_final_glb_set(
    output: Path,
    final_hashes: dict[str, str],
) -> list[dict[str, Any]]:
    """Re-run the semantic PBR gate from the eight final on-disk GLBs."""

    checks: list[dict[str, Any]] = []
    for state in STATE_NAMES:
        final_glb, qa_glb = _expected_state_artifacts(output, state)["glb"]
        for purpose, path in (
            ("final_review", final_glb),
            ("qa_overlay", qa_glb),
        ):
            check = _inspect_glb_pbr_contract(path, state, purpose)
            logical_path = _relative(path.resolve())
            if check.get("sha256") != final_hashes.get(logical_path):
                failures = list(check.get("failures", []))
                failures.append("PBR inspection hash differs from final artifact hash")
                check["failures"] = failures
                check["status"] = "FAIL"
            checks.append(check)
    return checks


def _verify_full_layout_state(
    output: Path,
    state: str,
    fragment_path: Path,
) -> None:
    """Re-import one completed full-layout STEP in a fresh CAD process.

    The state builder has already exited before this entry point runs.  That
    separation prevents the controlled source, the authored skin and the
    round-tripped composite from occupying one high-water-mark process while
    still making the final on-disk STEP—not an in-memory intention—the release
    authority.
    """

    output = output.resolve()
    fragment_path = fragment_path.resolve()
    if fragment_path != _worker_fragment_path(output, state).resolve():
        raise RuntimeError("Full-layout verifier received a foreign fragment path")
    if not (output / INCOMPLETE_MARKER_NAME).is_file():
        raise RuntimeError("Full-layout verification requires an active build")
    try:
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read state fragment for {state}: {exc}") from exc
    if not isinstance(fragment, dict) or fragment.get("state") != state:
        raise RuntimeError(f"Invalid state fragment for full-layout check: {state}")
    state_payload = fragment.get("state_payload")
    if not isinstance(state_payload, dict):
        raise RuntimeError(f"Missing state payload for full-layout check: {state}")

    from build_class_a_skin import (  # pylint: disable=import-outside-toplevel
        STATES,
        _load_final_layout_source_underlay,
        _roundtrip_signature_failures,
        _shape_signature,
        _signature_delta,
    )
    import cadquery as cq  # pylint: disable=import-outside-toplevel

    failures: list[str] = []
    full_layout_path = REPOSITORY_ROOT / str(state_payload["full_layout_step"])
    source_step_path = REPOSITORY_ROOT / str(
        state_payload["controlled_full_layout_source_step"]
    )
    declared_full_hash = str(state_payload["full_layout_step_sha256"])
    declared_source_hash = str(
        state_payload["controlled_full_layout_source_step_sha256"]
    )
    if _sha256_path(full_layout_path) != declared_full_hash:
        failures.append("full-layout STEP hash differs from the worker artifact hash")
    if _sha256_path(source_step_path) != declared_source_hash:
        failures.append("controlled source STEP hash differs from the pinned hash")

    source_inventory = _inspect_required_internal_source_occurrences(
        source_step_path,
        state,
    )
    if source_inventory.get("status") != "PASS":
        failures.extend(str(item) for item in source_inventory.get("failures", []))
    if source_inventory != state_payload.get(
        "controlled_internal_occurrence_inventory"
    ):
        failures.append("controlled internal occurrence inventory changed after export")

    state_sources = {
        source.configuration: source for source in STATES
    }
    state_source = state_sources[state]
    selected_source_shape, selected_source_items, source_selection_evidence = (
        _load_final_layout_source_underlay(state_source)
    )
    actual_source_signature = _shape_signature(selected_source_shape)
    actual_full_source_signature = source_selection_evidence[
        "source_shape_signature"
    ]
    fixed_full_source_count = EXPECTED_DFR5_SOURCE_SOLID_COUNTS[state]
    fixed_layout_source_count = EXPECTED_FINAL_LAYOUT_SOURCE_SOLID_COUNTS[state]
    if int(actual_full_source_signature["solid_count"]) != fixed_full_source_count:
        failures.append(
            "controlled full-source solid count differs from fixed DFR5 baseline"
        )
    if int(actual_source_signature["solid_count"]) != fixed_layout_source_count:
        failures.append(
            "disposition-filtered source solid count differs from fixed layout baseline"
        )
    expected_underlay_name = str(
        state_payload.get("full_layout_underlay_assembly_name", "")
    )
    if not expected_underlay_name:
        failures.append("worker omitted final-layout underlay assembly name")
    else:
        source_selection_evidence["underlay_assembly_name"] = (
            expected_underlay_name
        )
    if source_selection_evidence != state_payload.get(
        "controlled_source_selection_evidence"
    ):
        failures.append("controlled source disposition selection changed after export")

    declared_full_source_signature = state_payload.get(
        "controlled_full_source_shape_signature"
    )
    if not isinstance(declared_full_source_signature, dict):
        failures.append("worker omitted controlled full-source shape signature")
    else:
        full_source_delta = _signature_delta(
            declared_full_source_signature,
            actual_full_source_signature,
        )
        failures.extend(
            "controlled full source re-import: " + reason
            for reason in _roundtrip_signature_failures(
                declared_full_source_signature,
                actual_full_source_signature,
                full_source_delta,
                exact_topology=True,
            )
        )

    declared_source_signature = state_payload.get(
        "controlled_underlay_shape_signature"
    )
    if not isinstance(declared_source_signature, dict):
        failures.append("worker omitted controlled layout-underlay shape signature")
    else:
        source_delta = _signature_delta(
            declared_source_signature,
            actual_source_signature,
        )
        failures.extend(
            "controlled layout source re-import: " + reason
            for reason in _roundtrip_signature_failures(
                declared_source_signature,
                actual_source_signature,
                source_delta,
                exact_topology=True,
            )
        )
    selected_source_names = set(
        source_selection_evidence["selected_occurrence_names"]
    )
    required_source_names = set(required_selected_occurrence_names())
    if not required_source_names <= selected_source_names:
        failures.append("selected source underlay omits required internal occurrences")
    expected_required_source_shapes = {
        name: shape
        for name, shape, _colour in selected_source_items
        if name in required_source_names
    }
    if set(expected_required_source_shapes) != required_source_names:
        failures.append(
            "selected source XDE shapes do not contain the exact required "
            "battery/equipment/device occurrence set"
        )
    excluded_source_names = {
        name
        for names in source_selection_evidence["excluded_by_disposition"].values()
        for name in names
    }
    for source_name, proxy_name in REQUIRED_REPLACED_SOURCE_PROXIES.items():
        if source_name not in excluded_source_names:
            failures.append(
                f"required replaced source occurrence was not excluded: {source_name}"
            )
        generated_inventory = set(
            state_payload.get("generated_skin_part_inventory", [])
        )
        if proxy_name not in generated_inventory:
            failures.append(f"required final replacement proxy is absent: {proxy_name}")
    del selected_source_shape, selected_source_items
    gc.collect()

    # Re-open the released assembly through XDE so the final authority is not
    # only a flattened mass-property match or a textual PRODUCT name.  Each
    # required battery/equipment/device occurrence must retain its own BRep and
    # world pose after the complete STEP round trip.
    full_assembly = cq.Assembly.importStep(str(full_layout_path))
    full_shape = full_assembly.toCompound()
    reimported_required_source_shapes: dict[str, Any] = {}
    duplicate_required_occurrences: list[str] = []
    malformed_required_occurrences: list[str] = []
    for occurrence_name, child in full_assembly.traverse():
        if occurrence_name not in required_source_names:
            continue
        if occurrence_name in reimported_required_source_shapes:
            duplicate_required_occurrences.append(occurrence_name)
            continue
        if not child.shapes:
            malformed_required_occurrences.append(occurrence_name)
            continue
        located_shapes = [shape.moved(child.loc) for shape in child.shapes]
        reimported_required_source_shapes[occurrence_name] = (
            located_shapes[0]
            if len(located_shapes) == 1
            else cq.Compound.makeCompound(located_shapes)
        )
    if duplicate_required_occurrences:
        failures.append(
            "duplicate required internal XDE occurrences after STEP roundtrip: "
            f"{sorted(duplicate_required_occurrences)}"
        )
    if malformed_required_occurrences:
        failures.append(
            "required internal XDE occurrences contain no shapes: "
            f"{sorted(malformed_required_occurrences)}"
        )
    missing_reimported_required = sorted(
        required_source_names - set(reimported_required_source_shapes)
    )
    if missing_reimported_required:
        failures.append(
            "required internal XDE occurrences are missing after STEP roundtrip: "
            f"{missing_reimported_required}"
        )
    if (
        full_shape.isNull()
        or not full_shape.isValid()
        or full_shape.Volume() <= 0.0
        or not full_shape.Solids()
    ):
        failures.append("released full-layout STEP did not re-import as valid solids")
        actual_full_signature: dict[str, object] = {}
        full_delta: dict[str, float] = {}
    else:
        actual_full_signature = _shape_signature(full_shape)
        expected_full_signature = state_payload.get(
            "expected_full_layout_shape_signature"
        )
        if not isinstance(expected_full_signature, dict):
            failures.append("worker omitted expected full-layout shape signature")
            full_delta = {}
        else:
            full_delta = _signature_delta(
                expected_full_signature,
                actual_full_signature,
            )
            failures.extend(
                "full-layout STEP roundtrip: " + reason
                for reason in _roundtrip_signature_failures(
                    expected_full_signature,
                    actual_full_signature,
                    full_delta,
                )
            )

    required_internal_brep_evidence: dict[str, dict[str, object]] = {}
    for occurrence_name in sorted(required_source_names):
        expected_occurrence = expected_required_source_shapes.get(occurrence_name)
        actual_occurrence = reimported_required_source_shapes.get(occurrence_name)
        if expected_occurrence is None or actual_occurrence is None:
            required_internal_brep_evidence[occurrence_name] = {
                "status": "FAIL",
                "reason": "missing expected or reimported XDE occurrence shape",
            }
            continue
        expected_occurrence_signature = _shape_signature(expected_occurrence)
        actual_occurrence_signature = _shape_signature(actual_occurrence)
        try:
            common_volume = float(
                expected_occurrence.intersect(actual_occurrence).Volume()
            )
            boolean_error: str | None = None
        except Exception as exc:  # pragma: no cover - OCC diagnostic path
            common_volume = 0.0
            boolean_error = f"{type(exc).__name__}: {exc}"
        expected_volume = float(expected_occurrence_signature["volume_mm3"])
        actual_volume = float(actual_occurrence_signature["volume_mm3"])
        symmetric_difference = max(
            0.0,
            expected_volume + actual_volume - 2.0 * common_volume,
        )
        volume_tolerance = max(0.01, abs(expected_volume) * 1.0e-8)
        expected_bounds = expected_occurrence_signature["bounds_mm"]
        actual_bounds = actual_occurrence_signature["bounds_mm"]
        assert isinstance(expected_bounds, dict) and isinstance(
            actual_bounds, dict
        )
        maximum_bound_delta = max(
            abs(float(expected_bounds[key]) - float(actual_bounds[key]))
            for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
        )
        expected_centroid = expected_occurrence_signature["centroid_mm"]
        actual_centroid = actual_occurrence_signature["centroid_mm"]
        assert isinstance(expected_centroid, list) and isinstance(
            actual_centroid, list
        )
        maximum_centroid_delta = max(
            abs(float(first) - float(second))
            for first, second in zip(expected_centroid, actual_centroid)
        )
        occurrence_passed = (
            boolean_error is None
            and expected_occurrence.isValid()
            and actual_occurrence.isValid()
            and int(expected_occurrence_signature["solid_count"])
            == int(actual_occurrence_signature["solid_count"])
            and symmetric_difference <= volume_tolerance
            and maximum_bound_delta <= 0.01
            and maximum_centroid_delta <= 0.01
        )
        required_internal_brep_evidence[occurrence_name] = {
            "status": "PASS" if occurrence_passed else "FAIL",
            "boolean_error": boolean_error,
            "common_volume_mm3": common_volume,
            "symmetric_difference_volume_mm3": symmetric_difference,
            "symmetric_difference_tolerance_mm3": volume_tolerance,
            "maximum_bound_delta_mm": maximum_bound_delta,
            "maximum_centroid_delta_mm": maximum_centroid_delta,
            "expected_signature": expected_occurrence_signature,
            "reimported_signature": actual_occurrence_signature,
        }
    failed_required_internal_breps = sorted(
        name
        for name, evidence in required_internal_brep_evidence.items()
        if evidence.get("status") != "PASS"
    )
    if failed_required_internal_breps:
        failures.append(
            "required internal occurrence BRep/pose identity failed after STEP "
            f"roundtrip: {failed_required_internal_breps}"
        )
    required_internal_brep_evidence_sha256 = _canonical_payload_sha256(
        required_internal_brep_evidence
    )

    generated_skin_signature = state_payload.get("generated_skin_shape_signature")
    expected_full_signature = state_payload.get(
        "expected_full_layout_shape_signature"
    )
    component_signature_arithmetic: dict[str, object] = {}
    if (
        isinstance(actual_source_signature, dict)
        and actual_source_signature
        and isinstance(generated_skin_signature, dict)
        and isinstance(expected_full_signature, dict)
    ):
        component_solid_count = int(actual_source_signature["solid_count"]) + int(
            generated_skin_signature["solid_count"]
        )
        expected_component_solid_count = int(
            expected_full_signature["solid_count"]
        )
        component_signature_arithmetic["solid_count"] = {
            "component_total": component_solid_count,
            "expected_compound": expected_component_solid_count,
            "exact": component_solid_count == expected_component_solid_count,
        }
        if component_solid_count != expected_component_solid_count:
            failures.append("source + skin solid-count arithmetic is inconsistent")
        for metric in ("volume_mm3", "area_mm2"):
            component_total = float(actual_source_signature[metric]) + float(
                generated_skin_signature[metric]
            )
            expected_compound = float(expected_full_signature[metric])
            absolute_delta = abs(component_total - expected_compound)
            # Nested OCC compounds can recompute analytic mass properties in
            # a different traversal order from the two component compounds.
            # Use the same strict 10 ppm allowance as the authoritative STEP
            # round-trip gate; names, solid counts, bounds and the 30 required
            # internal BReps remain independently exact.
            tolerance = max(
                0.01,
                abs(component_total) * 1.0e-5,
            )
            component_signature_arithmetic[metric] = {
                "component_total": component_total,
                "expected_compound": expected_compound,
                "absolute_delta": absolute_delta,
                "tolerance": tolerance,
                "within_tolerance": absolute_delta <= tolerance,
            }
            if absolute_delta > tolerance:
                failures.append(f"source + skin {metric} arithmetic is inconsistent")
        if actual_full_signature and int(actual_full_signature["solid_count"]) <= int(
            actual_source_signature["solid_count"]
        ):
            failures.append("full-layout STEP contains no authored-skin solid increment")
        if actual_full_signature and int(actual_full_signature["solid_count"]) != (
            fixed_layout_source_count
            + int(generated_skin_signature["solid_count"])
        ):
            failures.append(
                "final solid count is not fixed selected-source baseline plus skin"
            )
    else:
        component_signature_arithmetic["status"] = "INCOMPLETE"
        failures.append("component signatures are incomplete")

    underlay_name = str(state_payload.get("full_layout_underlay_assembly_name", ""))
    full_layout_payload = full_layout_path.read_bytes()
    marker_count = full_layout_payload.count(underlay_name.encode("ascii"))
    if not underlay_name or marker_count < 1:
        failures.append("named final-layout underlay occurrence is absent from output STEP")
    selected_product_counts = {
        name: full_layout_payload.count(f"PRODUCT('{name}'".encode("ascii"))
        for name in selected_source_names
    }
    invalid_selected_products = {
        name: count
        for name, count in selected_product_counts.items()
        if count != 1
    }
    if invalid_selected_products:
        failures.append(
            "selected controlled occurrences are not present exactly once in "
            f"output STEP: {invalid_selected_products}"
        )
    forbidden_product_counts = {
        name: full_layout_payload.count(f"PRODUCT('{name}'".encode("ascii"))
        for name in excluded_source_names
    }
    leaked_forbidden_products = {
        name: count
        for name, count in forbidden_product_counts.items()
        if count != 0
    }
    if leaked_forbidden_products:
        failures.append(
            "replaced/retired controlled occurrences leaked into final layout: "
            f"{leaked_forbidden_products}"
        )
    replacement_proxy_product_counts = {
        proxy_name: full_layout_payload.count(
            f"PRODUCT('{proxy_name}'".encode("ascii")
        )
        for proxy_name in REQUIRED_REPLACED_SOURCE_PROXIES.values()
    }
    invalid_replacement_proxies = {
        name: count
        for name, count in replacement_proxy_product_counts.items()
        if count != 1
    }
    if invalid_replacement_proxies:
        failures.append(
            "required final replacement proxies are not present exactly once: "
            f"{invalid_replacement_proxies}"
        )

    packaging_report_path = (
        output / "qa" / f"critical_internal_packaging_{state}.json"
    ).resolve()
    try:
        packaging_report = json.loads(
            packaging_report_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        packaging_report = {}
        failures.append(f"critical internal packaging report is unreadable: {exc}")
    if not isinstance(packaging_report, dict):
        packaging_report = {}
        failures.append("critical internal packaging report is not a JSON object")
    expected_generated_inventory = sorted(
        str(name)
        for name in state_payload.get("generated_skin_part_inventory", [])
    )
    packaging_input_binding_failures: list[str] = []
    if packaging_report.get("state") != state:
        packaging_input_binding_failures.append("state")
    if packaging_report.get("status") != "PASS":
        packaging_input_binding_failures.append("status")
    if packaging_report.get("collision_count") != 0:
        packaging_input_binding_failures.append("collision_count")
    if packaging_report.get("collisions") != []:
        packaging_input_binding_failures.append("collisions")
    if packaging_report.get("missing_replacement_proxies") != {}:
        packaging_input_binding_failures.append("missing_replacement_proxies")
    if packaging_report.get("input_binding_status") != "PASS":
        packaging_input_binding_failures.append("input_binding_status")
    if packaging_report.get("controlled_source_step") != _relative(
        source_step_path.resolve()
    ):
        packaging_input_binding_failures.append("controlled_source_step")
    if packaging_report.get("controlled_source_step_sha256") != declared_source_hash:
        packaging_input_binding_failures.append("controlled_source_step_sha256")
    if packaging_report.get(
        "controlled_required_internal_occurrence_inventory"
    ) != source_inventory:
        packaging_input_binding_failures.append(
            "controlled_required_internal_occurrence_inventory"
        )
    if packaging_report.get("generated_skin_shape_signature") != (
        state_payload.get("generated_skin_shape_signature")
    ):
        packaging_input_binding_failures.append("generated_skin_shape_signature")
    if packaging_report.get("generated_skin_part_count") != state_payload.get(
        "generated_skin_part_count"
    ):
        packaging_input_binding_failures.append("generated_skin_part_count")
    if packaging_report.get("generated_skin_part_inventory") != (
        expected_generated_inventory
    ):
        packaging_input_binding_failures.append("generated_skin_part_inventory")
    if packaging_input_binding_failures:
        failures.append(
            "critical internal packaging input binding drifted: "
            f"{packaging_input_binding_failures}"
        )

    report = {
        "schema_version": 1,
        "gate": (
            "physical disposition-filtered battery/equipment/device-bay inclusion "
            "in full-layout STEP"
        ),
        "state": state,
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "controlled_source_step": _relative(source_step_path.resolve()),
        "controlled_source_step_sha256": declared_source_hash,
        "full_layout_step": _relative(full_layout_path.resolve()),
        "full_layout_step_sha256": declared_full_hash,
        "underlay_assembly_name": underlay_name,
        "underlay_name_occurrences_in_output_step": marker_count,
        "required_internal_occurrences": source_inventory,
        "controlled_full_source_shape_signature": actual_full_source_signature,
        "controlled_layout_source_shape_signature": actual_source_signature,
        "controlled_source_selection_evidence": source_selection_evidence,
        "selected_output_product_counts": selected_product_counts,
        "forbidden_output_product_counts": forbidden_product_counts,
        "replacement_proxy_output_product_counts": (
            replacement_proxy_product_counts
        ),
        "required_internal_occurrence_brep_identity_status": (
            "FAIL" if failed_required_internal_breps else "PASS"
        ),
        "required_internal_occurrence_brep_evidence_sha256": (
            required_internal_brep_evidence_sha256
        ),
        "required_internal_occurrence_brep_evidence": (
            required_internal_brep_evidence
        ),
        "generated_skin_shape_signature": generated_skin_signature,
        "expected_full_layout_shape_signature": expected_full_signature,
        "reimported_full_layout_shape_signature": actual_full_signature,
        "roundtrip_delta": full_delta,
        "component_signature_arithmetic": component_signature_arithmetic,
        "physical_inclusion_assertions": {
            "controlled_source_hash_pinned": _sha256_path(source_step_path)
            == declared_source_hash,
            "required_battery_equipment_and_device_products_present_exactly_once": (
                source_inventory.get("status") == "PASS"
                and not invalid_selected_products
            ),
            "required_battery_equipment_and_device_breps_and_poses_identical": (
                not failed_required_internal_breps
                and len(required_internal_brep_evidence)
                == len(required_source_names)
            ),
            "replaced_and_retired_source_occurrences_absent": (
                not leaked_forbidden_products
            ),
            "required_replacement_proxies_present_exactly_once": (
                not invalid_replacement_proxies
            ),
            "source_and_skin_solid_counts_add": not any(
                "solid-count arithmetic" in failure for failure in failures
            ),
            "source_and_skin_mass_properties_add": not any(
                "arithmetic is inconsistent" in failure
                and "solid-count" not in failure
                for failure in failures
            ),
            "final_step_reimport_valid": bool(actual_full_signature),
            "final_step_roundtrip_within_tolerance": not any(
                failure.startswith("full-layout STEP roundtrip:")
                for failure in failures
            ),
        },
    }
    report_path = _write_json(
        output / "qa" / f"full_layout_internal_inventory_{state}.json",
        report,
    )
    if failures:
        raise RuntimeError(
            f"{state} full-layout internal-inventory gate failed: "
            + " | ".join(failures)
        )

    # Seal the earlier source-vs-skin clearance result to the independently
    # re-imported final STEP and its per-occurrence BRep identity evidence.
    packaging_report.update(
        {
            "full_layout_step": _relative(full_layout_path.resolve()),
            "full_layout_step_sha256": declared_full_hash,
            "reimported_full_layout_shape_signature": actual_full_signature,
            "final_step_required_internal_brep_identity_status": "PASS",
            "final_step_required_internal_brep_evidence_sha256": (
                required_internal_brep_evidence_sha256
            ),
            "full_layout_internal_inventory_gate": _relative(
                report_path.resolve()
            ),
            "final_output_binding_status": "PASS",
        }
    )
    _write_json(packaging_report_path, packaging_report)
    packaging_report_sha256 = _sha256_path(packaging_report_path)
    report["critical_internal_packaging_gate"] = _relative(
        packaging_report_path
    )
    report["critical_internal_packaging_gate_sha256"] = (
        packaging_report_sha256
    )
    _write_json(report_path, report)

    state_payload["full_layout_internal_inventory_gate"] = _relative(
        report_path.resolve()
    )
    state_payload["full_layout_internal_inventory_status"] = "PASS"
    state_payload["reimported_full_layout_shape_signature"] = actual_full_signature
    state_payload["full_layout_solid_count"] = int(
        actual_full_signature["solid_count"]
    )
    state_payload["full_layout_bounds_mm"] = actual_full_signature["bounds_mm"]
    state_payload["full_layout_volume_mm3"] = float(
        actual_full_signature["volume_mm3"]
    )
    state_payload["full_layout_area_mm2"] = float(actual_full_signature["area_mm2"])
    state_payload["critical_internal_packaging_gate_sha256"] = (
        packaging_report_sha256
    )
    _write_json(fragment_path, fragment)
    del full_shape, full_assembly, expected_required_source_shapes
    del reimported_required_source_shapes
    gc.collect()


def _run_state_worker(output: Path, state: str) -> dict[str, Any]:
    _require_free_disk(
        output,
        MINIMUM_FREE_DISK_BEFORE_STATE_BYTES,
        f"{state} state worker",
    )
    fragment_path = _worker_fragment_path(output, state)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--output",
        str(output),
        "--worker-state",
        state,
        "--worker-fragment",
        str(fragment_path),
    ]
    # OCC booleans are intentionally single-process here.  Bound numerical
    # backends as well, because an imported BLAS/OpenMP runtime may otherwise
    # create one worker per logical CPU and destabilise the desktop while the
    # CAD process is at peak memory.
    scratch_directory = _worker_scratch_directory(output)
    worker_environment = os.environ.copy()
    worker_environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(scratch_directory),
            "TMP": str(scratch_directory),
            "TMPDIR": str(scratch_directory),
            "CSF_TemporaryDirectory": str(scratch_directory),
        }
    )
    completed = subprocess.run(
        command,
        cwd=str(SCRIPT_DIR),
        check=False,
        env=worker_environment,
        creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Low-memory state worker failed for {state} "
            f"with exit code {completed.returncode}"
        )
    verifier_command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--output",
        str(output),
        "--verify-full-layout-state",
        state,
        "--worker-fragment",
        str(fragment_path),
    ]
    verified = subprocess.run(
        verifier_command,
        cwd=str(SCRIPT_DIR),
        check=False,
        env=worker_environment,
        creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
    )
    if verified.returncode != 0:
        raise RuntimeError(
            f"Independent full-layout STEP verifier failed for {state} "
            f"with exit code {verified.returncode}"
        )
    return _load_worker_fragment(fragment_path, state)


def main(output: Path = DEFAULT_OUTPUT) -> None:
    """Orchestrate four isolated workers and aggregate canonical QA outputs."""

    output = output.resolve()
    _require_free_disk(
        output,
        MINIMUM_FREE_DISK_BEFORE_SERIES_BYTES,
        "four-state render series",
    )
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(
            f"Layout/appearance output must start empty: {output}"
        )

    output.mkdir(parents=True, exist_ok=True)
    incomplete = output / INCOMPLETE_MARKER_NAME
    incomplete.write_text(
        "Layout/appearance render series is incomplete.\n",
        encoding="utf-8",
    )
    worker_dir = output / WORKER_DIRECTORY_NAME
    worker_dir.mkdir(parents=True, exist_ok=False)

    fragments: dict[str, dict[str, Any]] = {}
    controlled_hashes: dict[str, str] | None = None
    generator_hashes: dict[str, str] | None = None
    for state in BUILD_ORDER:
        fragment = _run_state_worker(output, state)
        state_hashes = fragment["controlled_source_hashes"]
        if controlled_hashes is None:
            controlled_hashes = state_hashes
        elif state_hashes != controlled_hashes:
            raise RuntimeError(
                f"Controlled source hash inventory changed while building {state}"
            )
        state_generator_hashes = fragment["generator_source_hashes"]
        if generator_hashes is None:
            generator_hashes = state_generator_hashes
        elif state_generator_hashes != generator_hashes:
            raise RuntimeError(
                f"Generator source hash inventory changed while building {state}"
            )
        fragments[state] = fragment

    if controlled_hashes is None or generator_hashes is None:
        raise RuntimeError("No low-memory state workers completed")

    qa_dir = output / "qa"
    # Run the complete four-state source-disposition validator with the actual
    # generated A01--A10 names from this release.  The ordinary ledger report
    # deliberately allows a semantic-only run; final release may not, because
    # every battery/equipment access door, external release and enclosure owner
    # must resolve to a physical authored occurrence in its own state.
    from source_disposition import (  # pylint: disable=import-outside-toplevel
        build_all_ledgers,
        validate_ledgers,
    )

    available_proxies_by_state = {
        state: set(
            fragments[state]["state_payload"].get(
                "generated_skin_part_inventory", []
            )
        )
        for state in STATE_NAMES
    }
    source_disposition_validation = validate_ledgers(
        build_all_ledgers(repository_root=REPOSITORY_ROOT),
        repository_root=REPOSITORY_ROOT,
        available_proxies_by_state=available_proxies_by_state,
    )
    source_disposition_gate = {
        "schema_version": 1,
        "gate": (
            "four-state controlled-source disposition and physical A01-A10 "
            "proxy/access/enclosure reference closure"
        ),
        **source_disposition_validation,
    }
    source_disposition_release_binding_failures: list[str] = []
    state_reports = source_disposition_gate.get("state_reports", {})
    if not isinstance(state_reports, dict):
        source_disposition_release_binding_failures.append(
            "state_reports is not a mapping"
        )
    else:
        for state in STATE_NAMES:
            ledger_state_report = state_reports.get(state, {})
            source_selection = fragments[state]["state_payload"].get(
                "controlled_source_selection_evidence", {}
            )
            if (
                not isinstance(ledger_state_report, dict)
                or not isinstance(source_selection, dict)
                or ledger_state_report.get("controlled_occurrences")
                != source_selection.get("source_occurrence_count")
                or ledger_state_report.get("ledger_occurrences")
                != source_selection.get("source_occurrence_count")
            ):
                source_disposition_release_binding_failures.append(
                    f"{state} ledger/source occurrence count drift"
                )
    if source_disposition_release_binding_failures:
        source_disposition_gate["status"] = "FAIL"
        source_disposition_gate["errors"] = [
            *source_disposition_gate.get("errors", []),
            *source_disposition_release_binding_failures,
        ]
    source_disposition_gate["release_binding_failures"] = (
        source_disposition_release_binding_failures
    )
    if (
        source_disposition_gate.get("status") != "PASS"
        or source_disposition_gate.get("proxy_reference_validation")
        != "performed"
        or source_disposition_gate.get("unknown") != 0
        or source_disposition_gate.get("duplicates") != 0
        or source_disposition_gate.get("extra") != 0
        or source_disposition_gate.get("errors") != []
        or set(source_disposition_gate.get("controlled_states", []))
        != set(STATE_NAMES)
    ):
        raise RuntimeError(
            "Four-state source-disposition physical proxy closure failed: "
            + " | ".join(
                str(item) for item in source_disposition_gate.get("errors", [])
            )
        )
    source_disposition_gate_path = _write_json(
        qa_dir / "source_disposition_full_proxy_gate.json",
        source_disposition_gate,
    )
    source_disposition_gate_sha256 = _sha256_path(
        source_disposition_gate_path
    )
    full_layout_internal_reports: list[dict[str, Any]] = []
    full_layout_internal_report_hashes: dict[str, str] = {}
    critical_packaging_reports: list[dict[str, Any]] = []
    critical_packaging_report_hashes: dict[str, str] = {}
    a07_brep_reports: dict[str, dict[str, Any]] = {}
    a07_brep_report_hashes: dict[str, str] = {}
    for state in STATE_NAMES:
        report_path = (
            qa_dir / f"full_layout_internal_inventory_{state}.json"
        ).resolve()
        packaging_path = (
            qa_dir / f"critical_internal_packaging_{state}.json"
        ).resolve()
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot close full-layout internal report for {state}: {exc}"
            ) from exc
        state_payload = fragments[state]["state_payload"]
        if (
            not isinstance(report, dict)
            or report.get("state") != state
            or report.get("status") != "PASS"
            or report.get("failures") != []
            or report.get("full_layout_step")
            != state_payload.get("full_layout_step")
            or report.get("full_layout_step_sha256")
            != state_payload.get("full_layout_step_sha256")
            or report.get(
                "required_internal_occurrence_brep_identity_status"
            )
            != "PASS"
            or not isinstance(
                report.get("required_internal_occurrence_brep_evidence"),
                dict,
            )
            or len(report.get("required_internal_occurrence_brep_evidence", {}))
            != len(required_selected_occurrence_names())
            or _canonical_payload_sha256(
                report.get("required_internal_occurrence_brep_evidence", {})
            )
            != report.get(
                "required_internal_occurrence_brep_evidence_sha256"
            )
            or report.get("critical_internal_packaging_gate")
            != _relative(packaging_path)
            or report.get("critical_internal_packaging_gate_sha256")
            != state_payload.get("critical_internal_packaging_gate_sha256")
        ):
            raise RuntimeError(
                f"Full-layout internal report failed aggregate closure for {state}"
            )
        logical_report_path = _relative(report_path)
        full_layout_internal_report_hashes[logical_report_path] = _sha256_path(
            report_path
        )
        full_layout_internal_reports.append(report)
        try:
            packaging_report = json.loads(
                packaging_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot close critical packaging report for {state}: {exc}"
            ) from exc
        if (
            not isinstance(packaging_report, dict)
            or packaging_report.get("state") != state
            or packaging_report.get("status") != "PASS"
            or packaging_report.get("collision_count") != 0
            or packaging_report.get("collisions") != []
            or packaging_report.get("missing_replacement_proxies") != {}
            or packaging_report.get("input_binding_status") != "PASS"
            or packaging_report.get("final_output_binding_status") != "PASS"
            or packaging_report.get("controlled_source_step")
            != state_payload.get("controlled_full_layout_source_step")
            or packaging_report.get("controlled_source_step_sha256")
            != state_payload.get("controlled_full_layout_source_step_sha256")
            or packaging_report.get(
                "controlled_required_internal_occurrence_inventory"
            )
            != state_payload.get("controlled_internal_occurrence_inventory")
            or packaging_report.get("generated_skin_shape_signature")
            != state_payload.get("generated_skin_shape_signature")
            or packaging_report.get("generated_skin_part_inventory")
            != sorted(state_payload.get("generated_skin_part_inventory", []))
            or packaging_report.get("full_layout_step")
            != state_payload.get("full_layout_step")
            or packaging_report.get("full_layout_step_sha256")
            != state_payload.get("full_layout_step_sha256")
            or packaging_report.get(
                "final_step_required_internal_brep_identity_status"
            )
            != "PASS"
            or packaging_report.get(
                "final_step_required_internal_brep_evidence_sha256"
            )
            != report.get(
                "required_internal_occurrence_brep_evidence_sha256"
            )
            or packaging_report.get("full_layout_internal_inventory_gate")
            != state_payload.get("full_layout_internal_inventory_gate")
            or _sha256_path(packaging_path)
            != state_payload.get("critical_internal_packaging_gate_sha256")
        ):
            raise RuntimeError(
                f"Critical packaging report failed aggregate closure for {state}"
            )
        logical_packaging_path = _relative(packaging_path)
        critical_packaging_report_hashes[logical_packaging_path] = _sha256_path(
            packaging_path
        )
        critical_packaging_reports.append(packaging_report)
        a07_path = (qa_dir / f"a07_brep_state_{state}.json").resolve()
        try:
            a07_report = json.loads(a07_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot close A07 direct BRep report for {state}: {exc}"
            ) from exc
        a07_failures = _a07_state_report_failures(a07_report, state)
        a07_digest = _sha256_path(a07_path)
        if (
            a07_failures
            or a07_digest
            != state_payload.get("a07_brep_state_gate_sha256")
            or a07_report.get("controlled_source_step")
            != state_payload.get("controlled_full_layout_source_step")
            or a07_report.get("controlled_source_step_sha256")
            != state_payload.get("controlled_full_layout_source_step_sha256")
            or a07_report.get("generated_skin_shape_signature")
            != state_payload.get("generated_skin_shape_signature")
            or a07_report.get("exterior_step")
            != state_payload.get("exterior_step")
            or a07_report.get("exterior_step_sha256")
            != state_payload.get("exterior_step_sha256")
            or a07_report.get("exterior_part_inventory")
            != state_payload.get("exterior_part_inventory")
            or a07_report.get("output_binding_status") != "PASS"
        ):
            raise RuntimeError(
                f"A07 direct BRep report failed aggregate closure for {state}: "
                + " | ".join(a07_failures)
            )
        logical_a07_path = _relative(a07_path)
        a07_brep_report_hashes[logical_a07_path] = a07_digest
        a07_brep_reports[state] = a07_report
    full_layout_internal_gate_path = _write_json(
        qa_dir / "full_layout_internal_inventory_gate.json",
        {
            "schema_version": 1,
            "gate": (
                "four-state physical disposition-filtered battery/equipment/"
                "device-bay inclusion in full-layout STEP"
            ),
            "status": "PASS",
            "state_count": len(full_layout_internal_reports),
            "required_state_count": 4,
            "state_report_sha256": full_layout_internal_report_hashes,
            "states": full_layout_internal_reports,
        },
    )
    critical_packaging_gate_path = _write_json(
        qa_dir / "critical_internal_packaging_gate.json",
        {
            "schema_version": 1,
            "gate": (
                "four-state exact battery/equipment/device BRep clearance "
                "against final A01-A10 skin"
            ),
            "status": "PASS",
            "state_count": len(critical_packaging_reports),
            "required_state_count": 4,
            "state_report_sha256": critical_packaging_report_hashes,
            "states": critical_packaging_reports,
        },
    )
    a07_four_state_gate = _a07_four_state_brep_gate(
        a07_brep_reports,
        a07_brep_report_hashes,
    )
    if (
        a07_four_state_gate.get("status") != "PASS"
        or a07_four_state_gate.get("failures") != []
        or a07_four_state_gate.get("state_count") != 4
    ):
        raise RuntimeError(
            "Four-state direct A06/A07 BRep gate failed: "
            + " | ".join(a07_four_state_gate.get("failures", []))
        )
    a07_four_state_gate_path = _write_json(
        qa_dir / "a07_four_state_brep_gate.json",
        a07_four_state_gate,
    )
    a07_four_state_gate_sha256 = _sha256_path(a07_four_state_gate_path)
    cafe_deployment_gate_path = (
        qa_dir / "cafe_table_deployment_clearance_gate.json"
    ).resolve()
    try:
        cafe_deployment_gate = json.loads(
            cafe_deployment_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot close Cafe deployment clearance report: {exc}"
        ) from exc
    cafe_state_payload = fragments["cafe"]["state_payload"]
    if (
        not isinstance(cafe_deployment_gate, dict)
        or cafe_deployment_gate.get("state") != "cafe"
        or cafe_deployment_gate.get("status") != "PASS"
        or cafe_deployment_gate.get("failures") != []
        or cafe_deployment_gate.get("collision_count") != 0
        or cafe_deployment_gate.get("final_endpoint_unchanged") is not True
        or cafe_deployment_gate.get("controlled_source_step_sha256")
        != cafe_state_payload.get("controlled_full_layout_source_step_sha256")
        or cafe_deployment_gate.get("generated_skin_shape_signature")
        != cafe_state_payload.get("generated_skin_shape_signature")
    ):
        raise RuntimeError("Cafe deployment clearance report failed closure")
    cafe_deployment_gate_hash = _sha256_path(cafe_deployment_gate_path)

    focus_root_neck_gate_path = (
        qa_dir / "focus_root_neck_release_gate.json"
    ).resolve()
    try:
        focus_root_neck_gate = json.loads(
            focus_root_neck_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot close Focus root-neck report: {exc}") from exc
    focus_state_payload = fragments["focus"]["state_payload"]
    focus_root_neck_failures = _focus_root_neck_report_failures(
        focus_root_neck_gate
    )
    focus_root_neck_gate_sha256 = _sha256_path(focus_root_neck_gate_path)
    if (
        focus_root_neck_failures
        or focus_root_neck_gate_sha256
        != focus_state_payload.get("focus_root_neck_release_gate_sha256")
        or focus_root_neck_gate.get("controlled_source_step")
        != focus_state_payload.get("controlled_full_layout_source_step")
        or focus_root_neck_gate.get("controlled_source_step_sha256")
        != focus_state_payload.get("controlled_full_layout_source_step_sha256")
        or focus_root_neck_gate.get("generated_skin_shape_signature")
        != focus_state_payload.get("generated_skin_shape_signature")
        or focus_root_neck_gate.get("exterior_step")
        != focus_state_payload.get("exterior_step")
        or focus_root_neck_gate.get("exterior_step_sha256")
        != focus_state_payload.get("exterior_step_sha256")
        or focus_root_neck_gate.get("exterior_part_inventory")
        != focus_state_payload.get("exterior_part_inventory")
        or focus_root_neck_gate.get("output_binding_status") != "PASS"
    ):
        raise RuntimeError(
            "Focus root-neck report failed aggregate closure: "
            + " | ".join(focus_root_neck_failures)
        )

    # Re-read every completed state after the final worker exits.  This closes
    # the aggregate release against cross-state writes or late stray files,
    # rather than relying only on the inventory observed immediately after
    # each individual worker.
    for state in STATE_NAMES:
        final_inventory = _validate_state_artifact_inventory(output, state)
        if (
            fragments[state]["state_payload"].get("artifact_inventory")
            != final_inventory
        ):
            raise RuntimeError(
                f"Final on-disk artifact inventory drifted for {state}"
            )

    reference_a07_signature = fragments["ride"]["state_payload"].get(
        "a07_cmf_and_visibility_signature"
    )
    for state in STATE_NAMES:
        if (
            fragments[state]["state_payload"].get(
                "a07_cmf_and_visibility_signature"
            )
            != reference_a07_signature
        ):
            raise RuntimeError(
                "A07 physical occurrence, CMF or exterior visibility differs "
                f"between Ride and {state}"
            )

    invariant_signature_keys = (
        "a03_half_wrap_identity_cmf_and_visibility_signature",
        "a05_table_root_cassette_identity_signature",
        "right_control_identity_and_visibility_signature",
    )
    for signature_key in invariant_signature_keys:
        reference_signature = fragments["ride"]["state_payload"].get(
            signature_key
        )
        if not isinstance(reference_signature, dict) or not reference_signature:
            raise RuntimeError(
                f"Ride worker omitted invariant signature {signature_key}"
            )
        for state in STATE_NAMES:
            if (
                fragments[state]["state_payload"].get(signature_key)
                != reference_signature
            ):
                raise RuntimeError(
                    f"Four-state invariant signature {signature_key} differs "
                    f"between Ride and {state}"
                )

    series_artifacts = {
        kind: [
            artifact
            for state in STATE_NAMES
            for artifact in fragments[state]["state_payload"][
                "artifact_inventory"
            ][kind]
        ]
        for kind in EXPECTED_SERIES_ARTIFACT_COUNTS
    }
    series_counts = {
        kind: len(artifacts) for kind, artifacts in series_artifacts.items()
    }
    if series_counts != EXPECTED_SERIES_ARTIFACT_COUNTS:
        raise RuntimeError(
            f"Four-state artifact count contract failed: {series_counts!r}"
        )
    for kind, artifacts in series_artifacts.items():
        if len(set(artifacts)) != len(artifacts):
            raise RuntimeError(
                f"Four-state {kind.upper()} artifact paths are not unique"
            )

    # Worker summaries prove each state at hand-off.  Re-hash all forty-eight
    # artifacts after the final worker exits, then inspect the eight GLBs from
    # disk again rather than aggregating cached PASS labels.
    final_artifact_hashes = _verify_final_artifact_hashes(output, fragments)
    pbr_checks = _inspect_final_glb_set(output, final_artifact_hashes)
    expected_pbr_matrix = {
        (
            state,
            purpose,
            _relative(path.resolve()),
        )
        for state in STATE_NAMES
        for purpose, path in zip(
            ("final_review", "qa_overlay"),
            _expected_state_artifacts(output, state)["glb"],
        )
    }
    actual_pbr_matrix = {
        (
            str(check.get("state")),
            str(check.get("purpose")),
            str(check.get("path")),
        )
        for check in pbr_checks
    }
    pbr_failures = [
        f"{check.get('state')}.{check.get('purpose')}: "
        + "; ".join(str(item) for item in check.get("failures", []))
        for check in pbr_checks
        if check.get("status") != "PASS"
    ]
    if len(pbr_checks) != 8:
        pbr_failures.append(
            f"PBR check inventory is {len(pbr_checks)}, expected 8"
        )
    if actual_pbr_matrix != expected_pbr_matrix:
        pbr_failures.append("PBR state/purpose/path matrix is not the exact 8-GLB set")
    for state in STATE_NAMES:
        fragments[state]["state_payload"]["glb_pbr_material_checks"] = [
            check for check in pbr_checks if check.get("state") == state
        ]
    pbr_gate_path = _write_json(
        qa_dir / "glb_pbr_material_gate.json",
        {
            "schema_version": 1,
            "gate": "four-state semantic self-contained glTF PBR material contract",
            "status": "FAIL" if pbr_failures else "PASS",
            "expected_glb_count": 8,
            "actual_glb_count": len(pbr_checks),
            "failures": pbr_failures,
            "checks": pbr_checks,
        },
    )
    if pbr_failures:
        raise RuntimeError(
            "Four-state GLB PBR material gate failed: "
            + " | ".join(pbr_failures)
        )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "status": "BUILD_INCOMPLETE",
        "scope": "final layout and exterior appearance freeze",
        "product_intent": (
            "retro-science-fiction, minimal, smooth, premium and mysterious; "
            "one coherent new object rather than an exposed prototype assembly"
        ),
        "supplier_component_policy": (
            "Unknown supplier models are represented by functional packaging "
            "envelopes and usable interaction zones, not false exact part claims."
        ),
        "production_certification_claimed": False,
        "complete_manufacturing_bom_claimed": False,
        "controlled_source_hashes": controlled_hashes,
        "generator_source_hashes": generator_hashes,
        "controlled_and_generator_sources_unchanged_across_states": True,
        "validation_profile": {
            "name": "layout_appearance",
            "endpoint_rigid_collision": "PASS",
            "continuous_motion_evidence": (
                "dedicated mechanism modules; not repeated as supplier-detail "
                "certification in this render build"
            ),
            "unknown_component_precision": "parameterised_envelopes",
        },
        "states": {
            state: fragments[state]["state_payload"] for state in STATE_NAMES
        },
        "artifact_inventory": {
            "counts": series_counts,
            "by_type": series_artifacts,
            "sha256": final_artifact_hashes,
        },
        "source_disposition_full_proxy_gate": _relative(
            source_disposition_gate_path.resolve()
        ),
        "source_disposition_full_proxy_gate_sha256": (
            source_disposition_gate_sha256
        ),
        "full_layout_internal_inventory_gate": _relative(
            full_layout_internal_gate_path.resolve()
        ),
        "full_layout_internal_state_report_sha256": (
            full_layout_internal_report_hashes
        ),
        "critical_internal_packaging_gate": _relative(
            critical_packaging_gate_path.resolve()
        ),
        "critical_internal_packaging_state_report_sha256": (
            critical_packaging_report_hashes
        ),
        "a07_four_state_brep_gate": _relative(
            a07_four_state_gate_path.resolve()
        ),
        "a07_four_state_brep_gate_sha256": a07_four_state_gate_sha256,
        "a07_brep_state_report_sha256": a07_brep_report_hashes,
        "focus_root_neck_release_gate": _relative(
            focus_root_neck_gate_path
        ),
        "focus_root_neck_release_gate_sha256": (
            focus_root_neck_gate_sha256
        ),
        "cafe_table_deployment_clearance_gate": _relative(
            cafe_deployment_gate_path
        ),
        "cafe_table_deployment_clearance_gate_sha256": (
            cafe_deployment_gate_hash
        ),
        "glb_pbr_material_gate": _relative(pbr_gate_path),
    }
    render_checks = [
        check
        for state in STATE_NAMES
        for check in fragments[state]["render_checks"]
    ]
    failures = [
        f"{check.get('state')}.{check.get('view')}: "
        + "; ".join(str(item) for item in check.get("failures", []))
        for check in render_checks
        if check.get("status") != "PASS"
    ]
    by_state_view = {
        (str(check.get("state")), str(check.get("view"))): check
        for check in render_checks
    }
    for state in STATE_NAMES:
        hero = by_state_view.get((state, "hero"))
        qa = by_state_view.get((state, "qa_overlay"))
        if hero is None or qa is None:
            failures.append(f"{state}: hero or QA overlay render check is missing")
        elif hero.get("sha256") == qa.get("sha256"):
            failures.append(f"{state}: hero and QA overlay are identical")
    if len(render_checks) != 32:
        failures.append(f"render inventory is {len(render_checks)}, expected 32")
    if len({str(check.get("path")) for check in render_checks}) != 32:
        failures.append("render paths are not 32 unique files")
    if {str(check.get("path")) for check in render_checks} != set(
        series_artifacts["png"]
    ):
        failures.append(
            "render check paths do not match the exact 32-PNG release inventory"
        )

    render_report = {
        "schema_version": 1,
        "gate": "layout/appearance 32-image raster delivery",
        "status": "FAIL" if failures else "PASS",
        "expected_render_count": 32,
        "actual_render_count": len(render_checks),
        "required_resolution_px": [1600, 1200],
        "failures": failures,
        "renders": render_checks,
    }
    render_report_path = _write_json(
        qa_dir / "render_series_raster_gate.json",
        render_report,
    )
    if failures:
        raise RuntimeError(
            "Layout/appearance raster gate failed: " + " | ".join(failures)
        )

    # Close the release immediately before publishing it.  This second pass
    # detects any external or late write that occurred while the aggregate
    # PBR/raster reports were being assembled.
    closing_hashes = _verify_final_artifact_hashes(output, fragments)
    if closing_hashes != final_artifact_hashes:
        raise RuntimeError("Final artifact hashes changed during aggregation")
    if _sha256_path(source_disposition_gate_path) != (
        source_disposition_gate_sha256
    ):
        raise RuntimeError(
            "Source-disposition physical proxy evidence changed during aggregation"
        )
    try:
        closing_source_disposition_gate = json.loads(
            source_disposition_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Source-disposition physical proxy gate changed during closure: {exc}"
        ) from exc
    if (
        not isinstance(closing_source_disposition_gate, dict)
        or closing_source_disposition_gate != source_disposition_gate
        or closing_source_disposition_gate.get("status") != "PASS"
        or closing_source_disposition_gate.get("proxy_reference_validation")
        != "performed"
        or closing_source_disposition_gate.get("release_binding_failures") != []
        or closing_source_disposition_gate.get("errors") != []
    ):
        raise RuntimeError(
            "Source-disposition physical proxy gate failed final closure"
        )
    for logical_path, expected_digest in full_layout_internal_report_hashes.items():
        if _sha256_path(REPOSITORY_ROOT / logical_path) != expected_digest:
            raise RuntimeError(
                f"Full-layout internal evidence changed during aggregation: "
                f"{logical_path}"
            )
    for logical_path, expected_digest in critical_packaging_report_hashes.items():
        if _sha256_path(REPOSITORY_ROOT / logical_path) != expected_digest:
            raise RuntimeError(
                f"Critical internal packaging evidence changed during "
                f"aggregation: {logical_path}"
            )
    try:
        closing_internal_gate = json.loads(
            full_layout_internal_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Full-layout aggregate gate changed during closure: {exc}"
        ) from exc
    if (
        not isinstance(closing_internal_gate, dict)
        or closing_internal_gate.get("status") != "PASS"
        or closing_internal_gate.get("state_report_sha256")
        != full_layout_internal_report_hashes
    ):
        raise RuntimeError("Full-layout aggregate internal gate failed closure")
    try:
        closing_packaging_gate = json.loads(
            critical_packaging_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Critical packaging aggregate gate changed during closure: {exc}"
        ) from exc
    if (
        not isinstance(closing_packaging_gate, dict)
        or closing_packaging_gate.get("status") != "PASS"
        or closing_packaging_gate.get("state_report_sha256")
        != critical_packaging_report_hashes
        or closing_packaging_gate.get("state_count") != 4
        or closing_packaging_gate.get("required_state_count") != 4
    ):
        raise RuntimeError("Critical packaging aggregate gate failed closure")
    for logical_path, expected_digest in a07_brep_report_hashes.items():
        if _sha256_path(REPOSITORY_ROOT / logical_path) != expected_digest:
            raise RuntimeError(
                f"A07 direct BRep evidence changed during aggregation: "
                f"{logical_path}"
            )
    if _sha256_path(a07_four_state_gate_path) != a07_four_state_gate_sha256:
        raise RuntimeError("A07 four-state BRep gate changed during aggregation")
    try:
        closing_a07_gate = json.loads(
            a07_four_state_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"A07 four-state BRep gate changed during closure: {exc}"
        ) from exc
    recomputed_a07_gate = _a07_four_state_brep_gate(
        a07_brep_reports,
        a07_brep_report_hashes,
    )
    if (
        not isinstance(closing_a07_gate, dict)
        or closing_a07_gate != a07_four_state_gate
        or closing_a07_gate != recomputed_a07_gate
        or closing_a07_gate.get("status") != "PASS"
        or closing_a07_gate.get("failures") != []
        or closing_a07_gate.get("state_count") != 4
        or closing_a07_gate.get("required_state_count") != 4
        or closing_a07_gate.get("state_report_sha256")
        != a07_brep_report_hashes
    ):
        raise RuntimeError("A07 four-state direct BRep gate failed final closure")
    if _sha256_path(focus_root_neck_gate_path) != (
        focus_root_neck_gate_sha256
    ):
        raise RuntimeError("Focus root-neck evidence changed during aggregation")
    try:
        closing_focus_root_neck_gate = json.loads(
            focus_root_neck_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Focus root-neck gate changed during closure: {exc}"
        ) from exc
    if (
        not isinstance(closing_focus_root_neck_gate, dict)
        or closing_focus_root_neck_gate != focus_root_neck_gate
        or _focus_root_neck_report_failures(closing_focus_root_neck_gate)
    ):
        raise RuntimeError("Focus root-neck gate failed final closure")
    if _sha256_path(cafe_deployment_gate_path) != cafe_deployment_gate_hash:
        raise RuntimeError(
            "Cafe deployment clearance evidence changed during aggregation"
        )
    try:
        closing_cafe_deployment_gate = json.loads(
            cafe_deployment_gate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cafe deployment clearance gate changed during closure: {exc}"
        ) from exc
    if (
        not isinstance(closing_cafe_deployment_gate, dict)
        or closing_cafe_deployment_gate.get("status") != "PASS"
        or closing_cafe_deployment_gate.get("collision_count") != 0
        or closing_cafe_deployment_gate.get("failures") != []
        or closing_cafe_deployment_gate.get("final_endpoint_unchanged") is not True
    ):
        raise RuntimeError("Cafe deployment clearance gate failed final closure")

    # The hand-off fragments are not release artifacts.  Only remove the exact
    # four files created by this build; an unexpected file keeps the build
    # fail-closed instead of being recursively deleted.  Do this before
    # publishing a complete release status so cleanup failure cannot leave a
    # contradictory complete release beside BUILD_INCOMPLETE.
    for state in STATE_NAMES:
        _worker_fragment_path(output, state).unlink()
    worker_dir.rmdir()

    manifest["status"] = "RENDER_SERIES_COMPLETE_PENDING_VISUAL_REVIEW"
    manifest["render_series_gate"] = _relative(render_report_path)
    manifest_path = _write_json(
        output / "layout_appearance_manifest.json",
        manifest,
    )
    release_status = {
        "status": "RENDER_SERIES_COMPLETE_PENDING_VISUAL_REVIEW",
        "production_certification_claimed": False,
        "complete_manufacturing_bom_claimed": False,
        "step_count": series_counts["step"],
        "glb_count": series_counts["glb"],
        "render_count": 32,
        "state_count": 4,
        "full_layout_internal_inventory": "PASS",
        "critical_internal_packaging": "PASS",
        "source_disposition_full_proxy_closure": "PASS",
        "a07_direct_brep_four_state": "PASS",
        "focus_root_neck_direct_brep": "PASS",
        "cafe_table_deployment_clearance": "PASS",
        "manifest": _relative(manifest_path),
        "next_review_phase": (
            "human semantic review of silhouette simplicity, concealed function, "
            "material coherence and four-state physical continuity"
        ),
    }
    _write_json(output / "release_status.json", release_status)
    incomplete.unlink()


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the canonical WorkCore E6 V8 32-image layout/appearance "
            "series with one isolated CAD process per physical state."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--worker-state",
        choices=STATE_NAMES,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--worker-fragment",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--verify-full-layout-state",
        choices=STATE_NAMES,
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args()
    internal_modes = sum(
        mode is not None
        for mode in (
            arguments.worker_state,
            arguments.verify_full_layout_state,
        )
    )
    if internal_modes > 1:
        parser.error("internal build and verification modes are mutually exclusive")
    if (internal_modes == 0) != (arguments.worker_fragment is None):
        parser.error("an internal mode and worker fragment must be supplied together")
    return arguments


if __name__ == "__main__":
    args = _parse_arguments()
    if args.worker_state is not None:
        _build_one_state(args.output, args.worker_state, args.worker_fragment)
    elif args.verify_full_layout_state is not None:
        _verify_full_layout_state(
            args.output,
            args.verify_full_layout_state,
            args.worker_fragment,
        )
    else:
        main(args.output)
