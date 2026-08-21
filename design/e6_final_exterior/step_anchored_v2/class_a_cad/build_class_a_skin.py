"""Build an independent E6 exterior-skin study without touching controlled CAD.

The isolated E6-DFR5-A07-SHARED-HINGE STEP/GLB files are read-only hardpoint underlays.  The
original E6-DFR3 files remain preserved in ``build/`` as trace evidence.  This
script writes all new parts, assemblies, review GLBs, previews and evidence
under ``step_anchored_v2/class_a_cad/release_candidate_v8`` only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_EARLY_SCRIPT_DIR = Path(__file__).resolve().parent
_EARLY_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
for _path in (_EARLY_REPOSITORY_ROOT, _EARLY_SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import cadquery as cq
import numpy as np
import trimesh
import vtk
from PIL import Image
from vtk.util.numpy_support import vtk_to_numpy

from skin_common import (
    CHARCOAL_KNIT,
    CHAMPAGNE,
    ESPRESSO,
    GRAPHITE_BROWN,
    LUNAR_STONE,
    OXBLOOD_LEATHER,
    SAFETY_RED,
    SATIN_STAINLESS,
    SMOKED_WALNUT,
    SMOKED_UMBER,
    SkinPart,
    export_parts,
    validate_parts,
)
from skin_lower import build_lower_skin
from skin_upper import build_upper_skin
from skin_v8_refinement import refine_v8_parts
from v8_collision_partition import apply_v8_collision_partitions
from v8_functional_fixes import apply_v8_functional_fixes
from v8_final_appearance_closure import apply_v8_final_appearance_closure
from v8_internal_packaging_clearance import apply_v8_internal_packaging_clearance
from v8_mast_fixes import apply_v8_mast_fixes
from v8_rigid_partition_mast import apply_v8_mast_rigid_partitions
from v8_rigid_partition_service import apply_v8_service_rigid_partitions
from v8_rigid_partition_cross import apply_v8_cross_rigid_partitions
from v8_release_gates import run_v8_release_gates
from v8_rigid_partition_deployables import apply_v8_deployable_rigid_partitions
from v8_qa_gates import (
    annotate_evidence_kinds,
    assert_unique_check_ids,
    pin_and_verify_consumed_inputs,
    rigid_pair_collision_report,
    validate_closed_artifact_set,
    validate_exported_part_steps,
    validate_glb_units_and_inventory,
)
from source_disposition import (
    build_state_ledger,
    retain_exposed_names,
    write_qa_artifacts,
)
from v8_internal_layout_contract import FINAL_LAYOUT_SOURCE_DISPOSITIONS
from validate_class_a import validate_class_a


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTROLLED_BUILD = REPOSITORY_ROOT / "build"
CONTROLLED_SOURCE = SCRIPT_DIR / "controlled_source_e6_dfr5"
OUTPUT = SCRIPT_DIR / "release_candidate_v8"
RIGID_PAIR_COLLISION_ALLOWLIST = {
    "follow": {
        (
            "A04_seat_cushion_contact_island",
            "A06_backrest_weather_shell",
        ): (
            "Intentional unoccupied Follow preload into the explicitly "
            "non-rigid foam cushion; bounded by release check "
            "a04_a06.follow.compliant_cushion_preload_bounded_and_state_exclusive. "
            "Supplier compression-set data, occupied-fold interlock and physical "
            "cycle validation remain mandatory."
        ),
    },
}


def _rigid_collision_report(
    parts: Iterable[SkinPart],
    state: str,
) -> dict[str, object]:
    """Apply only the state-specific, geometry-gated compliant interface list."""

    return rigid_pair_collision_report(
        list(parts),
        state,
        RIGID_PAIR_COLLISION_ALLOWLIST.get(state, {}),
    )


@dataclass(frozen=True)
class StateSource:
    configuration: str
    step_name: str
    glb_name: str
    camera: tuple[float, float, float]
    focal: tuple[float, float, float]
    view_up: tuple[float, float, float] = (0.0, 0.0, 1.0)


STATES = (
    StateSource(
        "follow",
        "workcore_e6_dfr5_follow.step",
        "workcore_e6_dfr5_follow.glb",
        (-1730.0, 1650.0, 1535.0),
        (-80.0, 0.0, 380.0),
    ),
    StateSource(
        "ride",
        "workcore_e6_dfr5_ride.step",
        "workcore_e6_dfr5_ride.glb",
        (-2020.0, 1900.0, 1900.0),
        (-120.0, 0.0, 570.0),
    ),
    StateSource(
        "cafe",
        "workcore_e6_dfr5_cafe.step",
        "workcore_e6_dfr5_cafe.glb",
        (-2020.0, 1900.0, 1900.0),
        (-120.0, 0.0, 570.0),
    ),
    StateSource(
        "focus",
        "workcore_e6_dfr5_focus.step",
        "workcore_e6_dfr5_focus.glb",
        (-2470.0, 2350.0, 2395.0),
        (-120.0, 0.0, 750.0),
    ),
)


EXPECTED_SOURCE_HASHES = {
    "workcore_e6_dfr5_follow.step": "f925527ce086f2b18b0c53312733aadd6fa69aebb541d158f260d9c33b1a88fc",
    "workcore_e6_dfr5_ride.step": "3bf21b0811845c0d0fc10fbd116c96fc2188cc6e7a54956cd5e383c6a48fbb89",
    "workcore_e6_dfr5_cafe.step": "8118b34c83bde30f316717e028279de656db4640d1c1f74e2c7fb6c96ecddd88",
    "workcore_e6_dfr5_focus.step": "598ad5a8686989be548140c5629a1b996b85bc833f1672850c98da400626ed4c",
}

EXPECTED_SOURCE_GLB_HASHES = {
    "workcore_e6_dfr5_follow.glb": "337e21e6335966bc0695e2f18af9e3a671db24072dfaf1dbbb258f3718f4e4ce",
    "workcore_e6_dfr5_ride.glb": "b62bbdae5e02e021d79ef2f2ba0be6a9d4b91ef05e312a45ab319f887a1568ec",
    "workcore_e6_dfr5_cafe.glb": "82d738ca716921983252c8ffc5499faa389b6d05920b1090f8edc58e60891f1f",
    "workcore_e6_dfr5_focus.glb": "ffea83de6d37021cb7a62b8be6013cf2f94410c366ebc10592ebdce3f215d1cb",
}

EXPECTED_OPTIONAL_SOURCE_HASHES = {
    "workcore_e6_dfr5_cafe_footrest_open.step": "9ae030b518ef20304b3e5ca72816983a37c06771fd22a60192650435c71ba1ea",
    "workcore_e6_dfr5_cafe_footrest_open.glb": "4399fe24a63c34c70a67dbfabc7d5b053746386eb497d222264bbdf85e1658b5",
    "workcore_e6_dfr5_focus_footrest_open.step": "5914a9eb0c746950a02149d0673cb4583010840339f26eb84478f94acc05cd9f",
    "workcore_e6_dfr5_focus_footrest_open.glb": "3a9c10f4a5220d0f583beaa573a234632c0e519567dd47f8cc3c1bf0c54ff529",
}

EXPECTED_DFR5_MANIFEST_SHA256 = "dc27774b66320f8580c7bcd7d23a5c0f97e8e2187a808809f8116e811bc601a4"

EXPECTED_CONTROLLED_AUX_HASHES = {
    "release_manifest.json": "47d60408ec65e401ca95d630cd090a9f36443399e36cc1a3e1e64e3c9e09260a",
    "validation.json": "6e447998e321dad45bfcb70918fdbe97853f1ed8392946bd24df17237b3db522",
}

EXPECTED_CONTROLLED_OCCURRENCE_DIGESTS = {
    "follow": (180, "3b451ccb1f253d3b5450b7f85081f181762b808d675b7beb141273f1e530bbd6"),
    "ride": (176, "4c8d8b367ecd8c75b2604382e8e39f3bbf7a24f57d65a2f75072f0e21135356e"),
    "cafe": (189, "054567e236963c7cbc2da4be9fd9e6159831063376819751269793e96f5b3713"),
    "focus": (196, "4362926ef46fd27d04e3e5befdf7216365274602a3c3ef49dba03d19ea6f67cd"),
}


# Every controlled file consumed by the builder or its executable validators.
# The authenticated build/release_manifest.json supplies the expected byte
# count and SHA-256 for each path; adding a new source read without adding it
# here makes the V8 input-closure review fail.
CONSUMED_CONTROLLED_INPUTS = (
    "build/validation.json",
    "build/parts/battery_pressure_vent_duct.step",
    "build/parts/follow_uwb_rear_radome.step",
    "build/parts/mast_privacy_shutter_parked_focus.step",
    "build/parts/service_rear_horn_behind_door.step",
    "build/parts/mast_inner_focus.step",
    "build/parts/mast_inner_folded.step",
    "build/parts/mast_inner_stowed.step",
    "build/parts/suspension_rocker_left.step",
    "build/parts/suspension_rocker_right.step",
    "build/parts/axle_front_left.step",
    "build/parts/axle_front_right.step",
    "build/parts/axle_rear_left.step",
    "build/parts/axle_rear_right.step",
    "build/parts/hub_front_left.step",
    "build/parts/hub_front_right.step",
    "build/parts/hub_rear_left.step",
    "build/parts/hub_rear_right.step",
    "build/parts/follow_cliff_ir_window_front_left.step",
    "build/parts/follow_cliff_ir_window_front_right.step",
    "build/parts/follow_cliff_ir_window_rear_left.step",
    "build/parts/follow_cliff_ir_window_rear_right.step",
    "build/parts/tyre_front_left.step",
    "build/parts/tyre_front_right.step",
    "build/parts/tyre_rear_left.step",
    "build/parts/tyre_rear_right.step",
)

CONSUMED_DFR5_INPUTS = tuple(
    f"design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr5/"
    f"workcore_e6_dfr5_{state}.{extension}"
    for state in (
        "follow",
        "ride",
        "cafe",
        "focus",
        "cafe_footrest_open",
        "focus_footrest_open",
    )
    for extension in ("step", "glb")
)

# Pin the complete authored generator and design-decision chain as well as the
# controlled CAD inputs.  These files live outside the release artifact tree,
# so their digests must be embedded in the manifest to make a later result
# reproducible and to prevent a mid-build source edit from being silently
# mixed into one release candidate.
GENERATOR_SOURCE_PATHS = (
    "cad/parameters.py",
    "cad/footrest_state.py",
    "cad/build.py",
    "cad/export_dfr4_footrest_revision.py",
    "cad/export_dfr5_a07_hinge_revision.py",
    "requirements-lock.txt",
    "docs/e6_object_character_and_mystery_brief.md",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/skin_common.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_state_contract.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_internal_layout_contract.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_internal_packaging_clearance.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/skin_lower.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/skin_upper.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/skin_v8_refinement.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_functional_fixes.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_table_lid_packaging.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_cafe_table_root_motion.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_cafe_deployment_clearance.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_lid_harness_gate.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_mast_fixes.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_a07_brep_release_contract.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_focus_root_neck_release_contract.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_collision_partition.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_rigid_partition_deployables.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_rigid_partition_mast.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_rigid_partition_service.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_rigid_partition_cross.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_final_appearance_closure.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_wheel_contract.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_wheel_hub_articulation.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/exterior_presentation.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_release_gates.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_qa_gates.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/validate_class_a.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/source_disposition.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/build_class_a_skin.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/build_layout_appearance_series.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/build_layout_appearance_series_low_memory.py",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/v8_final_appearance_freeze.md",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/release_docs_v8_draft/RELEASE_README_DRAFT.md",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/release_docs_v8_draft/production_retest_matrix_draft.md",
    "design/e6_final_exterior/step_anchored_v2/class_a_cad/release_docs_v8_draft/visual_design_rationale_draft.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _generator_source_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in GENERATOR_SOURCE_PATHS:
        path = REPOSITORY_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing V8 generator source: {path}")
        hashes[relative] = sha256(path)
    return hashes


def _assert_sources() -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, expected in EXPECTED_CONTROLLED_AUX_HASHES.items():
        path = CONTROLLED_BUILD / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing controlled auxiliary input: {path}")
        digest = sha256(path)
        actual[name] = digest
        if digest != expected:
            raise RuntimeError(
                f"Controlled auxiliary hash drift for {name}: {digest}"
            )
    dfr5_manifest = CONTROLLED_SOURCE / "e6_dfr5_a07_hinge_manifest.json"
    if not dfr5_manifest.is_file():
        raise FileNotFoundError(f"Missing E6-DFR5 source manifest: {dfr5_manifest}")
    manifest_digest = sha256(dfr5_manifest)
    actual[str(dfr5_manifest.relative_to(REPOSITORY_ROOT))] = manifest_digest
    if manifest_digest != EXPECTED_DFR5_MANIFEST_SHA256:
        raise RuntimeError(
            "E6-DFR5 source manifest hash drift: "
            f"{manifest_digest}"
        )
    for state in STATES:
        step_path = CONTROLLED_SOURCE / state.step_name
        glb_path = CONTROLLED_SOURCE / state.glb_name
        if not step_path.is_file() or not glb_path.is_file():
            raise FileNotFoundError(f"Missing controlled source for {state.configuration}")
        digest = sha256(step_path)
        actual[state.step_name] = digest
        if digest != EXPECTED_SOURCE_HASHES[state.step_name]:
            raise RuntimeError(
                f"Controlled STEP hash drift for {state.step_name}: {digest}"
            )
        glb_digest = sha256(glb_path)
        actual[state.glb_name] = glb_digest
        if glb_digest != EXPECTED_SOURCE_GLB_HASHES[state.glb_name]:
            raise RuntimeError(
                f"Controlled GLB hash drift for {state.glb_name}: {glb_digest}"
            )
        source_scene = trimesh.load(glb_path, force="scene", process=False)
        if str(source_scene.units).lower() not in {"meter", "meters", "m"}:
            raise RuntimeError(
                f"E6-DFR5 GLB must be metre-native: {state.glb_name} units={source_scene.units!r}"
            )
        occurrence_names = sorted(source_scene.geometry)
        occurrence_digest = hashlib.sha256(
            "\n".join(occurrence_names).encode("utf-8")
        ).hexdigest()
        expected_count, expected_digest = EXPECTED_CONTROLLED_OCCURRENCE_DIGESTS[
            state.configuration
        ]
        if len(occurrence_names) != expected_count or occurrence_digest != expected_digest:
            raise RuntimeError(
                "Controlled GLB occurrence set drift for "
                f"{state.configuration}: count={len(occurrence_names)}, "
                f"digest={occurrence_digest}"
            )
    for name, expected in EXPECTED_OPTIONAL_SOURCE_HASHES.items():
        path = CONTROLLED_SOURCE / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing controlled optional A08 source: {path}")
        digest = sha256(path)
        actual[name] = digest
        if digest != expected:
            raise RuntimeError(
                f"Controlled optional A08 hash drift for {name}: {digest}"
            )
        if path.suffix.lower() == ".glb":
            scene = trimesh.load(path, force="scene", process=False)
            if str(scene.units).lower() not in {"meter", "meters", "m"}:
                raise RuntimeError(
                    f"Optional E6-DFR5 GLB must be metre-native: "
                    f"{name} units={scene.units!r}"
                )
    return actual


def _cq_color(part: SkinPart) -> cq.Color:
    return cq.Color(*part.color)


def _save_skin_assembly(parts: list[SkinPart], target: Path) -> None:
    assembly = cq.Assembly(name=target.stem)
    for part in parts:
        assembly.add(part.shape, name=part.name, color=_cq_color(part))
    assembly.save(str(target), exportType="STEP", mode="default")


STEP_ROUNDTRIP_LIMITS = {
    "max_bound_abs_mm": 0.01,
    "centroid_max_abs_mm": 0.01,
    # OCC recomputes analytic mass properties after STEP serialization.  Ten
    # parts per million is a strict numerical integration allowance for the
    # large filleted/lofted shells; geometry position remains locked to 0.01 mm,
    # solid count remains exact, and the reloaded STEP becomes downstream
    # authority for the full release/collision gate suite.
    "volume_relative": 1.0e-5,
    "volume_absolute_mm3": 0.01,
    "area_relative": 1.0e-5,
    "area_absolute_mm2": 0.01,
}


def _shape_signature(shape: cq.Shape) -> dict[str, object]:
    box = shape.BoundingBox()
    center = shape.Center()
    return {
        "bounds_mm": {
            "xmin": box.xmin,
            "xmax": box.xmax,
            "ymin": box.ymin,
            "ymax": box.ymax,
            "zmin": box.zmin,
            "zmax": box.zmax,
            "xlen": box.xlen,
            "ylen": box.ylen,
            "zlen": box.zlen,
        },
        "volume_mm3": float(shape.Volume()),
        "area_mm2": float(shape.Area()),
        "centroid_mm": [center.x, center.y, center.z],
        "solid_count": len(shape.Solids()),
        "face_count": len(shape.Faces()),
        "edge_count": len(shape.Edges()),
    }


def _signature_delta(
    before: dict[str, object],
    after: dict[str, object],
) -> dict[str, float]:
    before_bounds = before["bounds_mm"]
    after_bounds = after["bounds_mm"]
    assert isinstance(before_bounds, dict) and isinstance(after_bounds, dict)
    bound_keys = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
    before_centroid = before["centroid_mm"]
    after_centroid = after["centroid_mm"]
    assert isinstance(before_centroid, list) and isinstance(after_centroid, list)
    return {
        "max_bound_abs_mm": max(
            abs(float(before_bounds[key]) - float(after_bounds[key]))
            for key in bound_keys
        ),
        "volume_relative": abs(
            float(before["volume_mm3"]) - float(after["volume_mm3"])
        )
        / max(abs(float(before["volume_mm3"])), 1e-9),
        "volume_absolute_mm3": abs(
            float(before["volume_mm3"]) - float(after["volume_mm3"])
        ),
        "area_relative": abs(float(before["area_mm2"]) - float(after["area_mm2"]))
        / max(abs(float(before["area_mm2"])), 1e-9),
        "area_absolute_mm2": abs(
            float(before["area_mm2"]) - float(after["area_mm2"])
        ),
        "centroid_max_abs_mm": max(
            abs(float(a) - float(b))
            for a, b in zip(before_centroid, after_centroid)
        ),
    }


def _roundtrip_signature_failures(
    before: dict[str, object],
    after: dict[str, object],
    delta: dict[str, float],
    *,
    exact_topology: bool = False,
    ignore_bounds: bool = False,
) -> list[str]:
    failures: list[str] = []
    if int(before["solid_count"]) != int(after["solid_count"]):
        failures.append(
            f"solid_count {before['solid_count']} -> {after['solid_count']}"
        )
    if exact_topology:
        for key in ("face_count", "edge_count"):
            if int(before[key]) != int(after[key]):
                failures.append(f"{key} {before[key]} -> {after[key]}")
    if (
        not ignore_bounds
        and delta["max_bound_abs_mm"]
        > STEP_ROUNDTRIP_LIMITS["max_bound_abs_mm"]
    ):
        failures.append(f"bounds delta {delta['max_bound_abs_mm']:.9f} mm")
    if (
        delta["centroid_max_abs_mm"]
        > STEP_ROUNDTRIP_LIMITS["centroid_max_abs_mm"]
    ):
        failures.append(
            f"centroid delta {delta['centroid_max_abs_mm']:.9f} mm"
        )
    if (
        delta["volume_relative"] > STEP_ROUNDTRIP_LIMITS["volume_relative"]
        and delta["volume_absolute_mm3"]
        > STEP_ROUNDTRIP_LIMITS["volume_absolute_mm3"]
    ):
        failures.append(
            f"volume delta rel={delta['volume_relative']:.9e}, "
            f"abs={delta['volume_absolute_mm3']:.9f} mm3"
        )
    if (
        delta["area_relative"] > STEP_ROUNDTRIP_LIMITS["area_relative"]
        and delta["area_absolute_mm2"]
        > STEP_ROUNDTRIP_LIMITS["area_absolute_mm2"]
    ):
        failures.append(
            f"area delta rel={delta['area_relative']:.9e}, "
            f"abs={delta['area_absolute_mm2']:.9f} mm2"
        )
    return failures


def _reload_exported_parts(
    parts: list[SkinPart],
    directory: Path,
) -> tuple[list[SkinPart], dict[str, dict[str, object]]]:
    """Reload exact generated part paths and make them downstream authority."""

    reloaded: list[SkinPart] = []
    evidence: dict[str, dict[str, object]] = {}
    violations: list[str] = []
    for part in parts:
        path = directory / f"{part.name}.step"
        first_import = cq.importers.importStep(str(path)).val()
        if (
            first_import.isNull()
            or not first_import.isValid()
            or first_import.Volume() <= 0.0
        ):
            raise RuntimeError(f"Exported STEP failed solid reload: {path}")
        design_signature = _shape_signature(part.shape)
        first_signature = _shape_signature(first_import)
        design_to_first_delta = _signature_delta(
            design_signature, first_signature
        )
        roundtrip_failures = _roundtrip_signature_failures(
            design_signature,
            first_signature,
            design_to_first_delta,
        )

        evidence[part.name] = {
            "pre_export": design_signature,
            "post_export": first_signature,
            "delta": design_to_first_delta,
            "hard_gate_status": "FAIL" if roundtrip_failures else "PASS",
            "hard_gate_thresholds": {
                **STEP_ROUNDTRIP_LIMITS,
                "metric_failure_rule": (
                    "relative_and_absolute_thresholds_must_both_be_exceeded"
                ),
                "solid_count_exact": True,
            },
            "source_step": str(path.relative_to(REPOSITORY_ROOT)),
        }
        reloaded.append(replace(part, shape=first_import))
        if roundtrip_failures:
            violations.append(
                f"{part.name}: " + "; ".join(roundtrip_failures)
            )
    if violations:
        raise RuntimeError(
            f"Exported STEP roundtrip drift in {len(violations)} part(s): "
            + " | ".join(violations)
        )
    return reloaded, evidence


def _remove_stale_part_steps(parts: list[SkinPart], directory: Path) -> None:
    """Remove only obsolete generated part exports inside this output tree."""

    directory.mkdir(parents=True, exist_ok=True)
    expected = {f"{part.name}.step" for part in parts}
    for path in directory.glob("*.step"):
        if path.name not in expected:
            path.unlink()


def _save_underlay_composite(
    state: StateSource,
    parts: list[SkinPart],
    target: Path,
) -> cq.Shape:
    """Save the controlled internal assembly plus the final V8 skin.

    The returned shape is the exact controlled STEP shape placed below the
    named read-only underlay occurrence.  Callers use it to freeze a physical
    source/composite signature before releasing memory; it is not a substitute
    for the independent post-export STEP re-import gate.
    """

    imported = cq.importers.importStep(str(CONTROLLED_SOURCE / state.step_name))
    underlay_shape = imported.val()
    if (
        underlay_shape.isNull()
        or not underlay_shape.isValid()
        or underlay_shape.Volume() <= 0.0
        or not underlay_shape.Solids()
    ):
        raise RuntimeError(
            f"Controlled full-layout underlay is not a valid solid assembly: "
            f"{state.step_name}"
        )
    assembly = cq.Assembly(name=target.stem)
    assembly.add(
        underlay_shape,
        name=f"E6_DFR5_{state.configuration}_READ_ONLY_UNDERLAY",
        color=cq.Color(0.32, 0.34, 0.36, 0.22),
    )
    for part in parts:
        assembly.add(part.shape, name=part.name, color=_cq_color(part))
    assembly.save(str(target), exportType="STEP", mode="default")
    del assembly, imported
    return underlay_shape


def _composite_shape_signature(
    underlay_shape: cq.Shape,
    parts: Iterable[SkinPart],
) -> dict[str, object]:
    """Return the physical signature expected from an un-fused STEP assembly."""

    shapes = [underlay_shape, *(part.shape for part in parts)]
    composite = cq.Compound.makeCompound(shapes)
    return _shape_signature(composite)


def _parts_shape_signature(parts: Iterable[SkinPart]) -> dict[str, object]:
    """Return one un-fused physical signature for an authored part inventory."""

    compound = cq.Compound.makeCompound([part.shape for part in parts])
    return _shape_signature(compound)


def _load_final_layout_source_underlay(
    state: StateSource,
) -> tuple[cq.Shape, list[tuple[str, cq.Shape, cq.Color | None]], dict[str, object]]:
    """Select production-layout source occurrences from the controlled STEP.

    The XDE assembly importer preserves occurrence names, so obsolete prototype
    surfaces and the retired side-opening armrest mechanism can be excluded by
    the reviewed source-disposition ledger while batteries, core equipment,
    device bays, running gear and service hardware retain their exact controlled
    B-Reps and world poses.  Validation keep-outs remain layout evidence; this
    assembly is deliberately not presented as a supplier-final manufacturing
    BOM.
    """

    source_path = CONTROLLED_SOURCE / state.step_name
    source_assembly = cq.Assembly.importStep(str(source_path))
    occurrences: dict[str, tuple[cq.Shape, cq.Color | None]] = {}
    for name, child in source_assembly.traverse():
        if name == source_assembly.name and not child.shapes:
            continue
        if name in occurrences:
            raise RuntimeError(
                f"Duplicate XDE occurrence name in {state.step_name}: {name}"
            )
        if not child.shapes:
            raise RuntimeError(
                f"Non-leaf XDE occurrence in flat controlled assembly: {name}"
            )
        located_shapes = [shape.moved(child.loc) for shape in child.shapes]
        located = (
            located_shapes[0]
            if len(located_shapes) == 1
            else cq.Compound.makeCompound(located_shapes)
        )
        occurrences[name] = (located, child.color)

    ledger = build_state_ledger(state.configuration)
    ledger_by_name = {entry.source_occurrence: entry for entry in ledger}
    if set(occurrences) != set(ledger_by_name):
        raise RuntimeError(
            f"Controlled STEP/GLB occurrence mismatch for {state.configuration}: "
            f"STEP-only={sorted(set(occurrences) - set(ledger_by_name))}, "
            f"GLB-only={sorted(set(ledger_by_name) - set(occurrences))}"
        )

    selected_names = sorted(
        name
        for name, entry in ledger_by_name.items()
        if entry.disposition in FINAL_LAYOUT_SOURCE_DISPOSITIONS
    )
    selected = [
        (name, occurrences[name][0], occurrences[name][1])
        for name in selected_names
    ]
    full_source_shape = cq.Compound.makeCompound(
        [shape for shape, _color in occurrences.values()]
    )
    selected_shape = cq.Compound.makeCompound(
        [shape for _name, shape, _color in selected]
    )
    excluded_by_disposition = {
        disposition: sorted(
            name
            for name, entry in ledger_by_name.items()
            if entry.disposition == disposition
        )
        for disposition in ("replace_surface", "trace_only_retired")
    }
    evidence = {
        "schema_version": 1,
        "state": state.configuration,
        "source_step": str(source_path.relative_to(REPOSITORY_ROOT)).replace(
            "\\", "/"
        ),
        "source_occurrence_count": len(occurrences),
        "source_shape_signature": _shape_signature(full_source_shape),
        "included_dispositions": sorted(FINAL_LAYOUT_SOURCE_DISPOSITIONS),
        "selected_occurrence_count": len(selected),
        "selected_occurrence_names": selected_names,
        "selected_shape_signature": _shape_signature(selected_shape),
        "excluded_by_disposition": excluded_by_disposition,
        "retired_side_opening_armrest_absent": all(
            name not in selected_names
            for name in (
                "armrest_transfer_hinge_right",
                "armrest_transfer_link_right",
                "armrest_transfer_positive_lock_right",
                "armrest_transfer_hinge_shroud_right",
                "armrest_transfer_link_shroud_right",
            )
        ),
        "manufacturing_bom_claimed": False,
        "layout_envelopes_included": True,
    }
    del source_assembly, full_source_shape, occurrences
    return selected_shape, selected, evidence


def _save_final_layout_composite(
    state: StateSource,
    parts: list[SkinPart],
    target: Path,
) -> tuple[cq.Shape, dict[str, object]]:
    """Save the disposition-filtered source layout plus final authored skin."""

    selected_shape, selected, evidence = _load_final_layout_source_underlay(state)
    underlay_name = f"E6_DFR5_{state.configuration}_FINAL_LAYOUT_UNDERLAY"
    underlay = cq.Assembly(name=underlay_name)
    for name, shape, color in selected:
        underlay.add(
            shape,
            name=name,
            color=color if color is not None else cq.Color(0.32, 0.34, 0.36, 0.22),
        )
    assembly = cq.Assembly(name=target.stem)
    assembly.add(underlay, name=underlay_name)
    for part in parts:
        assembly.add(part.shape, name=part.name, color=_cq_color(part))
    assembly.save(str(target), exportType="STEP", mode="default")
    evidence["underlay_assembly_name"] = underlay_name
    del assembly, underlay, selected
    return selected_shape, evidence


def _rgba8(colour: tuple[float, float, float, float]) -> np.ndarray:
    """Return one audited linear-RGBA swatch as 8-bit glTF colour."""

    return np.clip(
        np.rint(np.asarray(colour, dtype=float) * 255.0),
        0.0,
        255.0,
    ).astype(np.uint8)


@lru_cache(maxsize=4)
def _procedural_material_textures(kind: str) -> tuple[Image.Image, Image.Image]:
    """Build deterministic, offline material evidence for the review GLB.

    These maps do not pretend that a supplier veneer or hide has already been
    selected.  They make the released *material family* legible at the digital
    layout stage: directional natural walnut, fine leather pore and linear
    brushed stainless.  No image is downloaded and no random seed can change
    the resulting artifact between builds.
    """

    size = 512 if kind == "walnut" else 256
    u = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float64)
    v = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float64)
    uu, vv = np.meshgrid(u, v)

    if kind == "walnut":
        # Grain runs along U.  Slow waviness and two nested pore frequencies
        # keep it recognisably natural without turning the table into a loud
        # decorative graphic.
        warped_v = (
            vv
            + 0.028 * np.sin(2.0 * np.pi * (1.0 * uu + 0.15))
            + 0.012 * np.sin(2.0 * np.pi * (3.0 * uu - 0.35))
        )
        broad = np.sin(2.0 * np.pi * (8.0 * warped_v + 0.20 * np.sin(2.0 * np.pi * uu)))
        fine = np.sin(2.0 * np.pi * (31.0 * warped_v + 0.45 * uu))
        pore = np.sin(2.0 * np.pi * (79.0 * warped_v - 1.5 * uu))
        height = 0.58 * broad + 0.29 * fine + 0.13 * pore
        tone = np.clip(0.98 + 0.045 * broad + 0.016 * fine, 0.89, 1.06)
        base = np.asarray(SMOKED_WALNUT[:3], dtype=np.float64) * 1.08
        rgb = np.clip(base[None, None, :] * tone[:, :, None], 0.0, 1.0)
    elif kind == "leather":
        pebble = (
            0.52 * np.sin(2.0 * np.pi * (17.0 * uu + 23.0 * vv))
            + 0.31 * np.sin(2.0 * np.pi * (29.0 * uu - 13.0 * vv))
            + 0.17 * np.sin(2.0 * np.pi * (47.0 * uu + 41.0 * vv))
        )
        height = pebble
        tone = np.clip(0.98 + 0.045 * pebble, 0.90, 1.06)
        base = np.asarray(OXBLOOD_LEATHER[:3], dtype=np.float64)
        rgb = np.clip(base[None, None, :] * tone[:, :, None], 0.0, 1.0)
    elif kind == "brushed_stainless":
        brush = (
            0.66 * np.sin(2.0 * np.pi * 54.0 * vv)
            + 0.24 * np.sin(2.0 * np.pi * (113.0 * vv + 0.35 * uu))
            + 0.10 * np.sin(2.0 * np.pi * (181.0 * vv - 0.20 * uu))
        )
        height = brush
        tone = np.clip(0.97 + 0.055 * brush, 0.86, 1.07)
        # The physically metallic response provides the highlight; the base
        # remains a restrained warm stainless, not chrome or champagne paint.
        base = np.asarray((0.70, 0.69, 0.66), dtype=np.float64)
        rgb = np.clip(base[None, None, :] * tone[:, :, None], 0.0, 1.0)
    else:
        raise ValueError(f"Unsupported procedural material texture: {kind!r}")

    rgba = np.empty((size, size, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(np.rint(rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    rgba[:, :, 3] = 255

    # A restrained tangent-space normal map lets real light, rather than a
    # painted highlight, distinguish pore/grain direction.  The amplitude is
    # deliberately low enough that no Class-A edge or silhouette is changed.
    grad_v, grad_u = np.gradient(height)
    amplitude = {
        "walnut": 0.30,
        "leather": 0.85,
        "brushed_stainless": 0.38,
    }[kind]
    nx = -grad_u * amplitude
    ny = -grad_v * amplitude
    nz = np.ones_like(nx)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal_rgb = np.stack((nx / norm, ny / norm, nz / norm), axis=2)
    normal_rgba = np.empty((size, size, 4), dtype=np.uint8)
    normal_rgba[:, :, :3] = np.clip(
        np.rint((normal_rgb * 0.5 + 0.5) * 255.0),
        0.0,
        255.0,
    ).astype(np.uint8)
    normal_rgba[:, :, 3] = 255
    return Image.fromarray(rgba, mode="RGBA"), Image.fromarray(
        normal_rgba,
        mode="RGBA",
    )


def _material_uv(
    vertices: np.ndarray,
    kind: str | None,
    mapping: str,
) -> np.ndarray:
    """Return deterministic physical/world-space UVs for one review mesh."""

    if len(vertices) == 0:
        return np.empty((0, 2), dtype=np.float64)
    if kind == "walnut":
        # One texture field spans both canonical half-leaves.  Café is the
        # same right table occurrence rotated through ninety degrees, so its
        # long-grain datum follows world Y while Focus follows world X.
        if mapping == "cafe_walnut":
            return np.column_stack(
                (
                    (vertices[:, 1] + 0.18) / 0.50,
                    (vertices[:, 0] + 0.51) / 0.34,
                )
            )
        return np.column_stack(
            (
                (vertices[:, 0] + 0.65) / 0.50,
                (vertices[:, 1] + 0.30) / 0.60,
            )
        )

    spans = np.ptp(vertices, axis=0)
    axes = np.argsort(spans)[-2:]
    scale = 0.075 if kind == "leather" else 0.030
    if kind is None:
        # Solid-colour PBR materials still receive a legal TEXCOORD_0 so the
        # export path stays uniform and future texture sampling cannot change
        # the geometry/node inventory.
        return np.zeros((len(vertices), 2), dtype=np.float64)
    return vertices[:, axes] / scale


def _pbr_visual(
    vertices: np.ndarray,
    *,
    name: str,
    colour: tuple[float, float, float, float],
    texture_kind: str | None,
    mapping: str,
    metallic: float,
    roughness: float,
) -> trimesh.visual.TextureVisuals:
    base_texture: Image.Image | None = None
    normal_texture: Image.Image | None = None
    base_factor: tuple[float, float, float, float] = colour
    if texture_kind is not None:
        base_texture, normal_texture = _procedural_material_textures(texture_kind)
        base_factor = (1.0, 1.0, 1.0, float(colour[3]))
    material = trimesh.visual.material.PBRMaterial(
        name=name,
        baseColorFactor=base_factor,
        baseColorTexture=base_texture,
        normalTexture=normal_texture,
        metallicFactor=float(metallic),
        roughnessFactor=float(roughness),
        # The GLB is a review derivative of authoritative closed STEP BRep.
        # CadQuery compound tessellation can retain patch-local winding, so a
        # standards-compliant single-sided viewer may otherwise hide valid
        # enclosure faces from the opposite review direction.
        doubleSided=True,
        alphaMode="BLEND" if float(colour[3]) < 0.999 else "OPAQUE",
    )
    return trimesh.visual.TextureVisuals(
        uv=_material_uv(vertices, texture_kind, mapping),
        material=material,
    )


def _skin_pbr_profile(part: SkinPart) -> tuple[str | None, float, float]:
    """Map the released CMF family to reproducible glTF PBR parameters."""

    family = str(part.metadata.get("material_family", "")).lower()
    material = part.material.lower()
    name = part.name.lower()
    if "natural_smoked_walnut_veneer" in family or "natural smoked-walnut veneer" in material:
        return "walnut", 0.0, 0.36
    if "solid_smoked_walnut" in family or "solid smoked-walnut" in material:
        return "walnut", 0.0, 0.40
    if "full_grain_leather" in family or "full-grain leather" in material:
        return "leather", 0.0, 0.74
    if "fine_brushed_stainless" in family or "stainless" in material:
        return "brushed_stainless", 0.88, 0.28
    if "tpe" in family or "epdm" in family or "gasket" in name:
        return None, 0.0, 0.84
    if "smoked" in name or "window" in name or "lens" in name:
        return None, 0.0, 0.20
    if "blackened" in family or "graphite" in family:
        return None, 0.08, 0.50
    if "mineral_matte" in family or "pc_abs" in family:
        return None, 0.02, 0.60
    return None, 0.02, 0.62


def _skin_mesh(part: SkinPart, linear: float = 0.45, angular: float = 0.08) -> trimesh.Trimesh:
    vertices, faces = part.shape.tessellate(linear, angular)
    # glTF 2.0 is metre-native.  The controlled CAD remains millimetres, so
    # scale every review mesh exactly once at the export boundary.
    vertex_array = np.asarray(
        [[v.x * 0.001, v.y * 0.001, v.z * 0.001] for v in vertices],
        dtype=float,
    )
    face_array = np.asarray(faces, dtype=np.int64)
    mesh = trimesh.Trimesh(vertex_array, face_array, process=False)
    texture_kind, metallic, roughness = _skin_pbr_profile(part)
    mesh.visual = _pbr_visual(
        vertex_array,
        name=f"{part.name}__{part.metadata.get('material_family', 'cmf')}",
        colour=part.color,
        texture_kind=texture_kind,
        mapping=(
            "cafe_walnut"
            if texture_kind == "walnut" and part.configuration == "cafe"
            else "default"
        ),
        metallic=metallic,
        roughness=roughness,
    )
    return mesh


@lru_cache(maxsize=4)
def _source_retain_allowlist(state: str) -> frozenset[str]:
    """Return the fail-closed retain allowlist from the controlled GLB ledger."""

    return retain_exposed_names(build_state_ledger(state, repository_root=REPOSITORY_ROOT))


def _source_keep(state: str, name: str) -> bool:
    """Keep only controlled occurrences explicitly approved as final exposed.

    The source-disposition ledger has no generic fallback: a new/renamed GLB
    occurrence makes the build fail until its A01--A10 responsibility is
    reviewed.  The complete source remains visible in the separate QA overlay
    and read-only-underlay STEP.
    """

    return name in _source_retain_allowlist(state)


def _functional_color(name: str) -> tuple[int, int, int, int]:
    if name.startswith("tyre_"):
        color = GRAPHITE_BROWN
    elif name.startswith("hub_"):
        color = CHAMPAGNE
    elif "cushion" in name:
        color = CHARCOAL_KNIT
    elif name.startswith("footrest_"):
        color = ESPRESSO
    elif "emergency_stop" in name:
        color = SAFETY_RED
    elif (
        "window" in name
        or "radome" in name
        or "acoustic_slot" in name
        or "camera" in name
        or "privacy" in name
    ):
        color = SMOKED_UMBER
    else:
        color = GRAPHITE_BROWN
    return tuple(int(channel * 255) for channel in color)


def _source_pbr_profile(name: str) -> tuple[float, float]:
    """Assign a restrained PBR response to retained controlled occurrences."""

    lowered = name.lower()
    if lowered.startswith("tyre_"):
        return 0.0, 0.88
    if lowered.startswith("hub_") or "stainless" in lowered:
        return 0.82, 0.31
    if "cushion" in lowered or "knit" in lowered:
        return 0.0, 0.86
    if lowered.startswith("footrest_"):
        return 0.03, 0.70
    if any(
        token in lowered
        for token in (
            "window",
            "radome",
            "camera",
            "privacy",
            "acoustic_slot",
        )
    ):
        return 0.0, 0.21
    return 0.04, 0.58


def _add_source_geometry(
    destination: trimesh.Scene,
    source: trimesh.Scene,
    *,
    state: str,
    ghost: bool,
) -> None:
    source_units = str(source.units).strip().lower()
    if source_units in {"meter", "meters", "metre", "metres", "m"}:
        source_scale = 1.0
    elif source_units in {"millimeter", "millimeters", "millimetre", "millimetres", "mm"}:
        source_scale = 0.001
    else:
        raise RuntimeError(
            f"Controlled source scene has unknown units {source.units!r}; refusing implicit scale"
        )
    for name, original in source.geometry.items():
        if not ghost and not _source_keep(state, name):
            continue
        mesh = original.copy()
        # E6-DFR5 is standards-correct metre-native glTF.  The explicit branch
        # remains for audited legacy inputs, but unknown units fail closed.
        if source_scale != 1.0:
            mesh.apply_scale(source_scale)
        if ghost:
            colour = tuple(value / 255.0 for value in (72, 84, 96, 38))
            metallic, roughness = 0.0, 0.78
        else:
            colour = tuple(
                value / 255.0 for value in _functional_color(name)
            )
            metallic, roughness = _source_pbr_profile(name)
        mesh.visual = _pbr_visual(
            np.asarray(mesh.vertices, dtype=float),
            name=f"source_{name}__pbr",
            colour=colour,
            texture_kind=None,
            mapping="default",
            metallic=metallic,
            roughness=roughness,
        )
        destination.add_geometry(mesh, node_name=f"source_{name}", geom_name=f"source_{name}")


def _save_review_glbs(
    state: StateSource,
    parts: list[SkinPart],
    state_dir: Path,
    *,
    qa_parts: list[SkinPart] | None = None,
) -> tuple[Path, Path, list[str]]:
    source = trimesh.load(
        CONTROLLED_SOURCE / state.glb_name,
        force="scene",
        process=False,
    )
    kept_source_names = sorted(
        name for name in source.geometry if _source_keep(state.configuration, name)
    )

    final_scene = trimesh.Scene()
    final_scene.units = "meters"
    _add_source_geometry(
        final_scene,
        source,
        state=state.configuration,
        ghost=False,
    )
    for part in parts:
        final_scene.add_geometry(
            _skin_mesh(part), node_name=part.name, geom_name=part.name
        )
    final_path = state_dir / f"workcore_e6_class_a_{state.configuration}.glb"
    final_path.write_bytes(
        final_scene.export(file_type="glb", include_normals=True)
    )

    qa_scene = trimesh.Scene()
    qa_scene.units = "meters"
    _add_source_geometry(
        qa_scene,
        source,
        state=state.configuration,
        ghost=True,
    )
    for part in (parts if qa_parts is None else qa_parts):
        qa_scene.add_geometry(
            _skin_mesh(part), node_name=part.name, geom_name=part.name
        )
    qa_path = state_dir / f"workcore_e6_class_a_{state.configuration}_qa_overlay.glb"
    qa_path.write_bytes(
        qa_scene.export(file_type="glb", include_normals=True)
    )
    return final_path, qa_path, kept_source_names


def _add_floor(renderer: vtk.vtkRenderer, scale: float = 0.001) -> None:
    floor = vtk.vtkPlaneSource()
    # A finite 2.4 x 2.2 m review tile exposed diagonal edges in the hero
    # cameras, especially once Focus raised the mast.  Extend the physical
    # shadow plane beyond every authored frustum and keep it lighter than the
    # product CMF so the final image reads as a seamless studio, never as a
    # debug viewport or a body-colour plinth.
    floor.SetOrigin(-100000.0 * scale, -100000.0 * scale, -0.75 * scale)
    floor.SetPoint1(100000.0 * scale, -100000.0 * scale, -0.75 * scale)
    floor.SetPoint2(-100000.0 * scale, 100000.0 * scale, -0.75 * scale)
    floor.Update()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(floor.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.18, 0.19, 0.19)
    # The floor is a neutral photographic sweep, not a fourth product
    # material.  Keep it unlit so scene-key intensity cannot drag it into the
    # same mid-value range as Lunar Stone; SSAO still supplies the local
    # contact cue at the tyres.
    actor.GetProperty().LightingOff()
    renderer.AddActor(actor)


def _add_studio_lights(
    renderer: vtk.vtkRenderer,
    focal_point: tuple[float, float, float],
    scale: float = 0.001,
    *,
    underside_fill: bool = False,
) -> None:
    """Use a repeatable three-light rig so enclosure breaks remain readable."""

    renderer.RemoveAllLights()
    specifications = (
        ((-1300.0, 900.0, 2500.0), (1.00, 0.97, 0.93), 1.10),
        ((900.0, -1700.0, 1450.0), (0.74, 0.84, 1.00), 0.58),
        ((1200.0, 1800.0, 2050.0), (1.00, 0.91, 0.74), 0.72),
    )
    if underside_fill:
        # The bottom review camera sits below the product and the normal studio
        # rig is intentionally overhead.  A dedicated lower three-light fill
        # keeps the underbody service skin readable without lifting the hero,
        # side or top renders or introducing a floor that occludes the view.
        specifications += (
            ((-900.0, -900.0, -2300.0), (0.96, 0.98, 1.00), 1.35),
            ((1250.0, 700.0, -1750.0), (0.78, 0.87, 1.00), 0.82),
            ((-250.0, 1700.0, -1350.0), (1.00, 0.90, 0.76), 0.62),
        )
    for position, colour, intensity in specifications:
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*(value * scale for value in position))
        light.SetFocalPoint(*(value * scale for value in focal_point))
        light.SetColor(*colour)
        light.SetIntensity(intensity)
        renderer.AddLight(light)


def _render_glb(
    source: Path,
    target: Path,
    state: StateSource,
    *,
    parallel_scale: float | None = None,
    include_floor: bool = True,
    auto_frame: bool = False,
    frame_margin: float = 1.12,
    underside_fill: bool | None = None,
) -> dict[str, object]:
    renderer = vtk.vtkRenderer()
    # A desaturated charcoal field keeps both the pale Lunar Stone enclosure
    # and graphite lower core readable.  The former near-white field clipped
    # the rear shell visually into the sweep before the GLB double-sided gate
    # exposed and corrected the underlying tessellation-display error.
    renderer.SetUseFXAA(True)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1600, 1200)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)
    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(source))
    importer.SetRenderWindow(window)
    importer.Update()
    # vtkGLTFImporter installs scene-level renderer settings during Update;
    # apply the delivery background afterwards so the intended gradient cannot
    # be silently replaced by the file's flat clear colour.
    renderer.SetBackground(0.30, 0.31, 0.31)

    # glTF vertex colour alone is not enough for a design-review image.  OCC
    # loft tessellation otherwise arrives with visibly faceted actor shading,
    # which made a smooth field shell read like a rough prototype.  Recompute
    # consistent point normals, retain the imported colour arrays and use a
    # repeatable matte PBR response for every cosmetic actor.
    actors = renderer.GetActors()
    actors.InitTraversal()
    actor = actors.GetNextActor()
    while actor is not None:
        mapper = actor.GetMapper()
        polydata = mapper.GetInput() if mapper is not None else None
        if isinstance(polydata, vtk.vtkPolyData):
            normals = vtk.vtkPolyDataNormals()
            normals.SetInputData(polydata)
            normals.ComputePointNormalsOn()
            normals.ComputeCellNormalsOff()
            normals.SplittingOff()
            normals.ConsistencyOn()
            normals.AutoOrientNormalsOn()
            normals.Update()
            # Preserve the glTF importer's material/direct-colour mapper state.
            # Replacing the mapper caused VTK to reinterpret RGB(A) arrays
            # through its default scalar lookup table (green/orange false
            # colour), which was visually unrelated to the CAD CMF values.
            mapper.SetInputData(normals.GetOutput())
        prop = actor.GetProperty()
        # Fail-safe for legacy and third-party GLBs: review renders must show
        # both sides of STEP-derived tessellation so a camera direction can
        # never masquerade as missing enclosure geometry.  Newly exported
        # delivery GLBs also declare every review material double-sided.
        prop.BackfaceCullingOff()
        prop.FrontfaceCullingOff()
        prop.SetInterpolationToPBR()
        # New review GLBs carry real glTF PBR materials and textures.  Preserve
        # the importer's authored response; only legacy COLOR_0-only files use
        # the historical colour-proximity fallback below.
        imported_metallic = float(prop.GetMetallic())
        imported_roughness = float(prop.GetRoughness())
        has_texture_coordinates = bool(
            isinstance(polydata, vtk.vtkPolyData)
            and polydata.GetPointData().GetTCoords() is not None
        )
        has_authored_pbr = (
            has_texture_coordinates
            or abs(imported_metallic) > 1.0e-6
            or abs(imported_roughness - 0.5) > 1.0e-6
        )
        rgba_mean: np.ndarray | None = None
        if isinstance(polydata, vtk.vtkPolyData):
            scalars = polydata.GetPointData().GetScalars()
            if scalars is not None and scalars.GetNumberOfComponents() >= 3:
                values = np.asarray(vtk_to_numpy(scalars), dtype=float)
                if values.ndim == 1:
                    values = values.reshape(-1, scalars.GetNumberOfComponents())
                if values.size:
                    if float(np.nanmax(values[:, :3])) > 1.5:
                        values = values / 255.0
                    rgba_mean = np.nanmean(values, axis=0)

        if not has_authored_pbr and rgba_mean is not None:
            rgb = rgba_mean[:3]

            def close_to(colour: tuple[float, float, float, float], tolerance: float) -> bool:
                return float(np.linalg.norm(rgb - np.asarray(colour[:3]))) <= tolerance

            metallic = 0.04
            roughness = 0.62
            if close_to(SMOKED_WALNUT, 0.035):
                metallic, roughness = 0.0, 0.34
            elif close_to(OXBLOOD_LEATHER, 0.035):
                metallic, roughness = 0.0, 0.72
            elif close_to(SATIN_STAINLESS, 0.028) or close_to(CHAMPAGNE, 0.035):
                metallic, roughness = 0.72, 0.33
            elif close_to(SMOKED_UMBER, 0.035):
                metallic, roughness = 0.0, 0.24
            elif close_to(GRAPHITE_BROWN, 0.035):
                metallic, roughness = 0.16, 0.48
            elif close_to(LUNAR_STONE, 0.04):
                metallic, roughness = 0.02, 0.58
            prop.SetMetallic(metallic)
            prop.SetRoughness(roughness)
        actor = actors.GetNextActor()

    # Capture the product-only bounds before adding the studio floor.  These
    # are the exact visible GLB actors, including retained controlled source
    # occurrences, so orthographic framing cannot silently crop geometry that
    # is absent from the cosmetic-skin BRep bounds.
    model_bounds = tuple(float(value) for value in renderer.ComputeVisiblePropBounds())
    if len(model_bounds) != 6 or not all(np.isfinite(model_bounds)):
        raise RuntimeError(f"Invalid render bounds for {source}: {model_bounds}")

    renderer.UseSSAOOn()
    renderer.SetSSAORadius(0.036)
    renderer.SetSSAOBias(0.015)
    renderer.SetSSAOKernelSize(64)
    renderer.SSAOBlurOn()
    if include_floor:
        _add_floor(renderer)
    camera = renderer.GetActiveCamera()
    camera_evidence: dict[str, object] = {
        "policy": "authored_perspective",
        "model_bounds_m": list(model_bounds),
    }
    light_focal_mm = state.focal
    if auto_frame:
        bounds_min = np.array(
            (model_bounds[0], model_bounds[2], model_bounds[4]),
            dtype=float,
        )
        bounds_max = np.array(
            (model_bounds[1], model_bounds[3], model_bounds[5]),
            dtype=float,
        )
        centre = 0.5 * (bounds_min + bounds_max)
        authored_position = np.asarray(state.camera, dtype=float) * 0.001
        authored_focal = np.asarray(state.focal, dtype=float) * 0.001
        view_direction = authored_focal - authored_position
        view_direction /= np.linalg.norm(view_direction)
        view_up = np.asarray(state.view_up, dtype=float)
        view_up -= np.dot(view_up, view_direction) * view_direction
        view_up /= np.linalg.norm(view_up)
        screen_right = np.cross(view_direction, view_up)
        screen_right /= np.linalg.norm(screen_right)
        corners = np.array(
            [
                (x, y, z)
                for x in (bounds_min[0], bounds_max[0])
                for y in (bounds_min[1], bounds_max[1])
                for z in (bounds_min[2], bounds_max[2])
            ],
            dtype=float,
        )
        offsets = corners - centre
        half_height = float(np.max(np.abs(offsets @ view_up)))
        half_width = float(np.max(np.abs(offsets @ screen_right)))
        aspect = 1600.0 / 1200.0
        minimum_parallel_scale = max(half_height, half_width / aspect)
        applied_parallel_scale = minimum_parallel_scale * frame_margin
        authored_distance = float(np.linalg.norm(authored_focal - authored_position))
        model_diagonal = float(np.linalg.norm(bounds_max - bounds_min))
        camera_distance = max(authored_distance, model_diagonal * 2.5, 1.0)
        camera_position = centre - view_direction * camera_distance
        camera.SetPosition(*camera_position)
        camera.SetFocalPoint(*centre)
        camera.SetViewUp(*view_up)
        camera.ParallelProjectionOn()
        camera.SetParallelScale(applied_parallel_scale)
        light_focal_mm = tuple(float(value * 1000.0) for value in centre)
        camera_evidence = {
            "policy": "visible_glb_bounds_auto_frame",
            "model_bounds_m": list(model_bounds),
            "frame_margin_ratio": frame_margin,
            "minimum_parallel_scale_m": minimum_parallel_scale,
            "applied_parallel_scale_m": applied_parallel_scale,
            "projected_half_width_m": half_width,
            "projected_half_height_m": half_height,
            "focal_point_m": centre.tolist(),
            "camera_position_m": camera_position.tolist(),
            "view_direction": view_direction.tolist(),
            "view_up": view_up.tolist(),
        }
    else:
        camera.SetPosition(*(value * 0.001 for value in state.camera))
        camera.SetFocalPoint(*(value * 0.001 for value in state.focal))
        camera.SetViewUp(*state.view_up)
    camera.SetViewAngle(30.0)
    if parallel_scale is not None and not auto_frame:
        camera.ParallelProjectionOn()
        camera.SetParallelScale(parallel_scale * 0.001)
        camera_evidence["policy"] = "authored_orthographic"
        camera_evidence["applied_parallel_scale_m"] = parallel_scale * 0.001
    if underside_fill is None:
        underside_fill = not include_floor
    _add_studio_lights(
        renderer,
        light_focal_mm,
        underside_fill=underside_fill,
    )
    renderer.ResetCameraClippingRange()
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(target))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
    return camera_evidence


def _inspect_render_png(
    path: Path,
    *,
    build_started_ns: int,
    require_clear_frame: bool,
    minimum_content_fraction: float = 0.001,
) -> dict[str, object]:
    """Decode one render and enforce delivery plus silhouette framing gates."""

    try:
        with Image.open(path) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        modified_ns = path.stat().st_mtime_ns
        digest = sha256(path)
    except Exception as exc:
        return {
            "path": str(path.relative_to(REPOSITORY_ROOT)).replace("\\", "/"),
            "status": "FAIL",
            "clear_frame_required": require_clear_frame,
            "failures": [f"PNG decode/read failed: {type(exc).__name__}: {exc}"],
        }
    height, width, channels = rgba.shape
    rgb = rgba[:, :, :3].astype(np.int16)
    luminance = (
        0.2126 * rgb[:, :, 0]
        + 0.7152 * rgb[:, :, 1]
        + 0.0722 * rgb[:, :, 2]
    )
    corner = 24
    corner_pixels = np.concatenate(
        (
            rgb[:corner, :corner].reshape(-1, 3),
            rgb[:corner, -corner:].reshape(-1, 3),
            rgb[-corner:, :corner].reshape(-1, 3),
            rgb[-corner:, -corner:].reshape(-1, 3),
        ),
        axis=0,
    )
    background_rgb = np.median(corner_pixels, axis=0)
    content_mask = np.max(np.abs(rgb - background_rgb), axis=2) > 4.0
    content_pixels = int(np.count_nonzero(content_mask))
    content_fraction = float(content_pixels / (height * width))
    edge_contact_pixels = int(
        np.count_nonzero(
            np.concatenate(
                (
                    content_mask[:1, :].ravel(),
                    content_mask[-1:, :].ravel(),
                    content_mask[:, :1].ravel(),
                    content_mask[:, -1:].ravel(),
                )
            )
        )
    )
    frame_clearance_px: int | None = None
    if content_pixels:
        ys, xs = np.nonzero(content_mask)
        frame_clearance_px = int(
            min(
                xs.min(),
                width - 1 - xs.max(),
                ys.min(),
                height - 1 - ys.max(),
            )
        )

    failures: list[str] = []
    if (width, height, channels) != (1600, 1200, 4):
        failures.append(f"decoded raster is {width}x{height}x{channels}, expected 1600x1200x4")
    if modified_ns + 2_000_000_000 < build_started_ns:
        failures.append("render timestamp predates this build")
    if content_pixels < 1000 or content_fraction < minimum_content_fraction:
        failures.append("render is blank or nearly blank")
    if float(np.mean(luminance)) < 40.0:
        failures.append("render is globally too dark")
    if float(np.std(luminance)) < 3.0:
        failures.append("render has insufficient luminance variation")
    if float(np.mean(luminance < 8.0)) > 0.35:
        failures.append("near-black pixels exceed 35 percent")
    if require_clear_frame:
        if edge_contact_pixels:
            failures.append(f"product/background transition touches {edge_contact_pixels} edge pixels")
        if frame_clearance_px is None or frame_clearance_px < 24:
            failures.append(
                f"orthographic frame clearance {frame_clearance_px} px is below 24 px"
            )

    return {
        "path": str(path.relative_to(REPOSITORY_ROOT)).replace("\\", "/"),
        "status": "FAIL" if failures else "PASS",
        "decoded_size_px": [width, height],
        "channels": channels,
        "sha256": digest,
        "mtime_ns": modified_ns,
        "background_rgb_median": background_rgb.tolist(),
        "mean_luminance_8bit": float(np.mean(luminance)),
        "luminance_stddev_8bit": float(np.std(luminance)),
        "near_black_fraction": float(np.mean(luminance < 8.0)),
        "content_pixel_count": content_pixels,
        "content_fraction": content_fraction,
        "edge_contact_pixels": edge_contact_pixels,
        "frame_clearance_px": frame_clearance_px,
        "clear_frame_required": require_clear_frame,
        "minimum_content_fraction": minimum_content_fraction,
        "failures": failures,
    }


def _combined_bounds(parts: Iterable[SkinPart]) -> dict[str, float]:
    boxes = [part.shape.BoundingBox() for part in parts]
    return {
        "xmin": min(box.xmin for box in boxes),
        "xmax": max(box.xmax for box in boxes),
        "ymin": min(box.ymin for box in boxes),
        "ymax": max(box.ymax for box in boxes),
        "zmin": min(box.zmin for box in boxes),
        "zmax": max(box.zmax for box in boxes),
    }


def _silhouette_views(
    state: StateSource,
) -> dict[str, tuple[StateSource, float]]:
    """Return repeatable 1:1-style orthographic review directions."""

    if state.configuration == "follow":
        z, elevation_scale, plan_scale = 350.0, 420.0, 470.0
    elif state.configuration == "focus":
        z, elevation_scale, plan_scale = 760.0, 820.0, 690.0
    else:
        z, elevation_scale, plan_scale = 550.0, 620.0, 670.0
    elevation_focal = (-100.0, 0.0, z)
    # The deployed footrest shifts the true plan centre forward.  A separate
    # plan focal/scale prevents the top and bottom QA views from clipping it
    # while keeping the elevation plates comparable to the earlier gates.
    plan_focal = (-185.0, 0.0, 350.0 if state.configuration == "follow" else 500.0)
    cameras = {
        "front": ((-3000.0, 0.0, z), (0.0, 0.0, 1.0), elevation_focal, elevation_scale),
        "rear": ((3000.0, 0.0, z), (0.0, 0.0, 1.0), elevation_focal, elevation_scale),
        "left": ((-100.0, -3000.0, z), (0.0, 0.0, 1.0), elevation_focal, elevation_scale),
        "right": ((-100.0, 3000.0, z), (0.0, 0.0, 1.0), elevation_focal, elevation_scale),
        "top": ((plan_focal[0], 0.0, 3000.0), (1.0, 0.0, 0.0), plan_focal, plan_scale),
        "bottom": ((plan_focal[0], 0.0, -3000.0), (1.0, 0.0, 0.0), plan_focal, plan_scale),
    }
    return {
        label: (
            StateSource(
                state.configuration,
                state.step_name,
                state.glb_name,
                camera_data[0],
                camera_data[2],
                camera_data[1],
            ),
            camera_data[3],
        )
        for label, camera_data in cameras.items()
    }


def build_state(configuration: str) -> list[SkinPart]:
    """Build one physical state for fast exterior iteration and review."""

    if configuration not in {state.configuration for state in STATES}:
        raise ValueError(f"Unsupported Class-A state: {configuration!r}")
    final_skin = apply_v8_final_appearance_closure(
        configuration,
        apply_v8_cross_rigid_partitions(
            configuration,
            apply_v8_service_rigid_partitions(
                configuration,
                apply_v8_mast_rigid_partitions(
                    configuration,
                    apply_v8_deployable_rigid_partitions(
                        configuration,
                        apply_v8_collision_partitions(
                            configuration,
                            apply_v8_mast_fixes(
                                configuration,
                                apply_v8_functional_fixes(
                                    configuration,
                                    refine_v8_parts(
                                        configuration,
                                        build_lower_skin(configuration)
                                        + build_upper_skin(configuration),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    return apply_v8_internal_packaging_clearance(configuration, final_skin)


def build_all() -> dict[str, list[SkinPart]]:
    """Build all four physical states without exporting or mutating sources."""

    result: dict[str, list[SkinPart]] = {}
    for state in STATES:
        state_started = time.perf_counter()
        print(f"[V8] building Class-A state: {state.configuration}", flush=True)
        result[state.configuration] = build_state(state.configuration)
        print(
            f"[V8] built {state.configuration} in "
            f"{time.perf_counter() - state_started:.1f}s "
            f"({len(result[state.configuration])} skin parts)",
            flush=True,
        )
    return result


def _optional_footrest_open_variants(
    parts_by_state: dict[str, list[SkinPart]],
) -> dict[str, list[SkinPart]]:
    """Compose Café/Focus optional-open states from the same deployed A08 skin.

    The four primary renders remain unchanged.  This composition is used only
    for exact static collision evidence: every non-A08 part comes from the
    target primary state, while every A08 exterior occurrence comes from the
    already validated Ride deployed pose.  No alternative footrest geometry is
    authored for Café or Focus.
    """

    deployed_a08 = [part for part in parts_by_state["ride"] if part.module == "A08"]
    try:
        from .v8_footrest_drawer_brep import a08_footrest_drawer_occurrences
    except ImportError:
        from v8_footrest_drawer_brep import a08_footrest_drawer_occurrences

    # The optional state must reuse the complete Ride mechanism, not just its
    # three visible skins.  Derive the frozen list from the production B-Rep
    # author so a newly introduced lock, bearing or safety sensor cannot be
    # silently omitted here.
    required_names = set(
        a08_footrest_drawer_occurrences(1.0, "ride")
    ) | {"A08_manual_release_paddle_shell"}
    actual_names = {part.name for part in deployed_a08}
    if not required_names.issubset(actual_names):
        raise RuntimeError(
            "Ride deployed A08 exterior inventory is incomplete: "
            + ", ".join(sorted(required_names - actual_names))
        )

    variants: dict[str, list[SkinPart]] = {}
    for target in ("cafe", "focus"):
        substate = f"{target}_footrest_open"
        target_fixed = [
            replace(part, configuration=substate)
            for part in parts_by_state[target]
            if part.module != "A08"
        ]
        optional_a08: list[SkinPart] = []
        for part in deployed_a08:
            metadata = dict(part.metadata)
            metadata.update(
                {
                    "primary_state": target,
                    "footrest_pose": "deployed_locked",
                    "default_footrest_state": "stowed",
                    "optional_footrest_open_available": True,
                    "optional_substate_in_primary_render_set": False,
                    "optional_substate_name": substate,
                    "optional_substate_geometry_source": "ride_same_physical_a08",
                }
            )
            optional_a08.append(
                replace(
                    part,
                    configuration=substate,
                    metadata=metadata,
                )
            )
        variant = target_fixed + optional_a08
        errors = validate_parts(variant)
        if errors:
            raise RuntimeError(f"{substate} optional-open skin invalid: {errors}")
        variants[substate] = variant
    return variants


def _require_pass(report: dict[str, object], phase: str) -> None:
    status = report.get("status")
    if status != "PASS":
        summary = report.get("summary")
        hard_failures = report.get("hard_failures")
        diagnostic_name = (
            phase.lower().replace(" ", "_").replace("-", "_")
            + "_validation_failure_latest.json"
        )
        diagnostic_path = SCRIPT_DIR / ".validation_work" / diagnostic_name
        try:
            _write_json_atomic(diagnostic_path, report)
            print(
                f"[V8] preserved failed {phase} validation report: "
                f"{diagnostic_path}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[V8] could not preserve failed {phase} validation report: {exc}",
                flush=True,
            )
        raise RuntimeError(
            f"{phase} Class-A validation gate failed: {status} {summary}; "
            f"hard_failures={hard_failures}"
        )


def _require_gate_pass(report: dict[str, object], phase: str) -> None:
    if report.get("status") != "PASS":
        raise RuntimeError(
            f"{phase} V8 release gate failed: "
            f"{report.get('status')} {report.get('summary') or report.get('failures')}"
        )


def _write_json(path: Path, payload: object) -> Path:
    return _write_json_atomic(path, payload)


def _write_json_atomic(path: Path, payload: object) -> Path:
    """Durably stage JSON beside its destination, then atomically replace it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            )
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return path


def _commit_final_artifact_closure(
    *,
    output: Path,
    incomplete_path: Path,
    manifest_path: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    """Publish the manifest before removing the fail-safe release marker.

    ``BUILD_INCOMPLETE`` is the commit lock.  It remains present while the
    complete manifest is atomically replaced, so serialization, fsync and
    replacement failures are fail-closed without relying on a second write to
    restore the marker.  Once the marker is removed, only a read-only closure
    check remains; a hard stop in that window still leaves a fully committed
    manifest and artifact set.
    """

    commit_ready_report = validate_closed_artifact_set(
        output,
        manifest,
        allowed_unlisted=(manifest_path.name, incomplete_path.name),
    )
    manifest["validation_gates"]["artifact_closure"] = commit_ready_report
    manifest["validation_gates"][
        "artifact_closure_commit_ready"
    ] = commit_ready_report
    _write_json_atomic(manifest_path, manifest)

    # Marker removal is deliberately the final mutating commit operation.
    incomplete_path.unlink()
    try:
        final_closure_report = validate_closed_artifact_set(
            output,
            manifest,
            allowed_unlisted=(manifest_path.name,),
        )
    except BaseException:
        # The manifest is already durable.  Recreate the marker only if the
        # read-only post-commit audit detects an external race or corruption.
        incomplete_path.write_text(
            "Formal V8 build did not complete artifact closure.\n",
            encoding="utf-8",
        )
        raise
    return final_closure_report


def main() -> None:
    build_started_ns = time.time_ns()
    generator_source_hashes_before = _generator_source_hashes()
    legacy_input_pin_report = pin_and_verify_consumed_inputs(
        REPOSITORY_ROOT,
        CONSUMED_CONTROLLED_INPUTS,
    )
    dfr5_input_pin_report = pin_and_verify_consumed_inputs(
        REPOSITORY_ROOT,
        CONSUMED_DFR5_INPUTS,
        release_manifest_path=(
            "design/e6_final_exterior/step_anchored_v2/class_a_cad/"
            "controlled_source_e6_dfr5/e6_dfr5_a07_hinge_manifest.json"
        ),
        expected_manifest_sha256=EXPECTED_DFR5_MANIFEST_SHA256,
    )
    input_pin_report = {
        "gate": "dual_revision_input_pin",
        "status": (
            "PASS"
            if legacy_input_pin_report["status"] == "PASS"
            and dfr5_input_pin_report["status"] == "PASS"
            else "FAIL"
        ),
        "preserved_e6_dfr3_auxiliary_inputs": legacy_input_pin_report,
        "e6_dfr5_primary_state_inputs": dfr5_input_pin_report,
    }
    source_hashes_before = _assert_sources()
    parts_by_state = build_all()
    for configuration, parts in parts_by_state.items():
        errors = validate_parts(parts)
        if errors:
            raise RuntimeError(f"{configuration} skin invalid: {errors}")

    geometry_release_report = run_v8_release_gates(
        parts_by_state=parts_by_state,
        workspace_root=REPOSITORY_ROOT,
    )
    _require_gate_pass(geometry_release_report, "executable geometry")

    collision_reports = {
        state: _rigid_collision_report(parts, state)
        for state, parts in parts_by_state.items()
    }
    for state, report in collision_reports.items():
        _require_gate_pass(report, f"{state} rigid-pair collision")

    optional_footrest_variants = _optional_footrest_open_variants(parts_by_state)
    optional_footrest_collision_reports = {
        substate: _rigid_collision_report(parts, substate)
        for substate, parts in optional_footrest_variants.items()
    }
    for substate, report in optional_footrest_collision_reports.items():
        _require_gate_pass(report, f"{substate} rigid-pair collision")

    pre_export_report = validate_class_a(
        parts=parts_by_state,
        manifest={"controlled_revision": "E6-DFR5-A07-SHARED-HINGE", "validation_phase": "pre_export"},
        workspace_root=REPOSITORY_ROOT,
        search_roots=(SCRIPT_DIR,),
    )
    _require_pass(pre_export_report, "pre-export")
    pre_export_check_id_report = assert_unique_check_ids(
        pre_export_report,
        "pre_export",
    )
    pre_export_report = annotate_evidence_kinds(pre_export_report)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    incomplete_path = OUTPUT / "BUILD_INCOMPLETE"
    incomplete_path.write_text(
        "V8 export is incomplete until every digital gate passes.\n",
        encoding="utf-8",
    )
    qa_dir = OUTPUT / "qa"
    input_pin_path = _write_json(qa_dir / "input_pin_report.json", input_pin_report)
    geometry_release_path = _write_json(
        qa_dir / "v8_geometry_release_gate.json",
        geometry_release_report,
    )
    pre_export_check_id_path = _write_json(
        qa_dir / "pre_export_check_id_gate.json",
        pre_export_check_id_report,
    )
    collision_paths = {
        state: _write_json(
            qa_dir / f"rigid_pair_collision_{state}.json",
            report,
        )
        for state, report in collision_reports.items()
    }
    optional_footrest_collision_paths = {
        substate: _write_json(
            qa_dir / f"rigid_pair_collision_{substate}.json",
            report,
        )
        for substate, report in optional_footrest_collision_reports.items()
    }
    pre_export_validation_path = OUTPUT / "validation_pre_export.json"
    _write_json(pre_export_validation_path, pre_export_report)
    proxy_names_by_state = {
        state: {part.name for part in state_parts}
        for state, state_parts in parts_by_state.items()
    }
    ledger_json, ledger_markdown, ledger_report = write_qa_artifacts(
        OUTPUT / "qa",
        REPOSITORY_ROOT,
        proxy_names_by_state,
    )
    artifact_paths: list[Path] = [
        ledger_json,
        ledger_markdown,
        input_pin_path,
        geometry_release_path,
        pre_export_check_id_path,
        *collision_paths.values(),
        *optional_footrest_collision_paths.values(),
        pre_export_validation_path,
    ]
    manifest: dict[str, object] = {
        "schema_version": 2,
        "scope": (
            "independent STEP-anchored exterior Class-A release candidate; "
            "production release still requires signed physical-test evidence"
        ),
        "controlled_revision": "E6-DFR5-A07-SHARED-HINGE",
        "production_certification_claimed": False,
        "generator_source_hashes_before": generator_source_hashes_before,
        "controlled_source_hashes_before": source_hashes_before,
        "source_disposition": {
            "status": ledger_report["status"],
            "controlled_occurrences": ledger_report[
                "total_controlled_occurrences"
            ],
            "ledger_occurrences": ledger_report["total_ledger_occurrences"],
            "unknown": ledger_report["unknown"],
            "duplicates": ledger_report["duplicates"],
            "json": str(ledger_json.relative_to(REPOSITORY_ROOT)),
            "markdown": str(ledger_markdown.relative_to(REPOSITORY_ROOT)),
        },
        "validation_gates": {
            "input_pin": {
                "status": input_pin_report["status"],
                "report": str(input_pin_path.relative_to(REPOSITORY_ROOT)),
            },
            "v8_geometry_release": {
                "status": geometry_release_report["status"],
                "decision": geometry_release_report["decision"],
                "summary": geometry_release_report["summary"],
                "report": str(geometry_release_path.relative_to(REPOSITORY_ROOT)),
            },
            "rigid_pair_collision": {
                state: {
                    "status": report["status"],
                    "hard_collision_count": report["hard_collision_count"],
                    "report": str(collision_paths[state].relative_to(REPOSITORY_ROOT)),
                }
                for state, report in collision_reports.items()
            },
            "optional_footrest_open_collision": {
                "status": (
                    "PASS"
                    if all(
                        report["status"] == "PASS"
                        for report in optional_footrest_collision_reports.values()
                    )
                    else "FAIL"
                ),
                "source_motion_evidence": (
                    "controlled_source_e6_dfr5/e6_dfr5_a07_hinge_manifest.json: "
                    "21-point stow-to-open sweep and endpoint clearance"
                ),
                "primary_render_series_membership": False,
                "substates": {
                    substate: {
                        "status": report["status"],
                        "hard_collision_count": report["hard_collision_count"],
                        "report": str(
                            optional_footrest_collision_paths[substate].relative_to(
                                REPOSITORY_ROOT
                            )
                        ),
                    }
                    for substate, report in optional_footrest_collision_reports.items()
                },
            },
            "pre_export": {
                "status": pre_export_report["status"],
                "summary": pre_export_report["summary"],
                "report": str(pre_export_validation_path.relative_to(REPOSITORY_ROOT)),
                "check_id_gate": str(
                    pre_export_check_id_path.relative_to(REPOSITORY_ROOT)
                ),
            }
        },
        "states": {},
    }
    roundtripped_parts_by_state: dict[str, list[SkinPart]] = {}
    render_checks: list[dict[str, object]] = []

    for state in STATES:
        parts = parts_by_state[state.configuration]

        state_dir = OUTPUT / state.configuration
        part_dir = state_dir / "parts"
        state_dir.mkdir(parents=True, exist_ok=True)
        _remove_stale_part_steps(parts, part_dir)
        export_parts(parts, part_dir)
        artifact_paths.extend(part_dir / f"{part.name}.step" for part in parts)
        parts, roundtrip_evidence = _reload_exported_parts(parts, part_dir)
        # Freeze the freshly imported STEP authority before any assembly save,
        # tessellation or render can populate/mutate OCCT triangulation caches.
        authoritative_part_bounds = {
            name: dict(evidence["post_export"]["bounds_mm"])
            for name, evidence in roundtrip_evidence.items()
        }
        authoritative_skin_bounds = {
            "xmin": min(bounds["xmin"] for bounds in authoritative_part_bounds.values()),
            "xmax": max(bounds["xmax"] for bounds in authoritative_part_bounds.values()),
            "ymin": min(bounds["ymin"] for bounds in authoritative_part_bounds.values()),
            "ymax": max(bounds["ymax"] for bounds in authoritative_part_bounds.values()),
            "zmin": min(bounds["zmin"] for bounds in authoritative_part_bounds.values()),
            "zmax": max(bounds["zmax"] for bounds in authoritative_part_bounds.values()),
        }
        roundtrip_errors = validate_parts(parts)
        if roundtrip_errors:
            raise RuntimeError(
                f"{state.configuration} exported STEP reload invalid: {roundtrip_errors}"
            )
        roundtripped_parts_by_state[state.configuration] = parts
        skin_step = state_dir / f"workcore_e6_class_a_skin_{state.configuration}.step"
        composite_step = (
            state_dir
            / f"workcore_e6_class_a_{state.configuration}_with_read_only_underlay.step"
        )
        _save_skin_assembly(parts, skin_step)
        _save_underlay_composite(state, parts, composite_step)
        artifact_paths.extend((skin_step, composite_step))
        final_glb, qa_glb, kept_source_names = _save_review_glbs(
            state, parts, state_dir
        )
        artifact_paths.extend((final_glb, qa_glb))
        final_png = state_dir / f"preview_class_a_{state.configuration}.png"
        qa_png = state_dir / f"preview_class_a_{state.configuration}_qa_overlay.png"
        _render_glb(final_glb, final_png, state)
        _render_glb(qa_glb, qa_png, state)
        artifact_paths.extend((final_png, qa_png))
        hero_render_check = _inspect_render_png(
            final_png,
            build_started_ns=build_started_ns,
            require_clear_frame=False,
        )
        hero_render_check.update(
            {"state": state.configuration, "view": "hero"}
        )
        qa_render_check = _inspect_render_png(
            qa_png,
            build_started_ns=build_started_ns,
            require_clear_frame=False,
        )
        qa_render_check.update(
            {"state": state.configuration, "view": "qa_overlay"}
        )
        render_checks.extend((hero_render_check, qa_render_check))
        silhouette_paths: dict[str, str] = {}
        for view_name, (view_state, scale) in _silhouette_views(state).items():
            silhouette_path = state_dir / f"silhouette_{view_name}_{state.configuration}.png"
            camera_evidence = _render_glb(
                final_glb,
                silhouette_path,
                view_state,
                parallel_scale=scale,
                include_floor=False,
                auto_frame=True,
                underside_fill=view_name == "bottom",
            )
            silhouette_render_check = _inspect_render_png(
                silhouette_path,
                build_started_ns=build_started_ns,
                require_clear_frame=True,
                # Auto-framed front/rear/side/plan views should devote a
                # material portion of the plate to the product.  The former
                # single-sided rear GLB left only seams and tyres (~2%); this
                # fail-closed threshold prevents that false PASS recurring.
                minimum_content_fraction=0.05,
            )
            silhouette_render_check.update(
                {
                    "state": state.configuration,
                    "view": view_name,
                    "camera": camera_evidence,
                }
            )
            render_checks.append(silhouette_render_check)
            silhouette_paths[view_name] = str(
                silhouette_path.relative_to(REPOSITORY_ROOT)
            )
            artifact_paths.append(silhouette_path)

        manifest["states"][state.configuration] = {
            "source_step": str((CONTROLLED_SOURCE / state.step_name).relative_to(REPOSITORY_ROOT)),
            "source_glb": str((CONTROLLED_SOURCE / state.glb_name).relative_to(REPOSITORY_ROOT)),
            "source_step_sha256": source_hashes_before[state.step_name],
            "part_count": len(parts),
            "skin_bounds": authoritative_skin_bounds,
            "skin_step": str(skin_step.relative_to(REPOSITORY_ROOT)),
            "composite_step": str(composite_step.relative_to(REPOSITORY_ROOT)),
            "review_glb": str(final_glb.relative_to(REPOSITORY_ROOT)),
            "qa_glb": str(qa_glb.relative_to(REPOSITORY_ROOT)),
            "review_glb_units": "m",
            "glb_coordinate_scale_from_step_mm": 0.001,
            "presentation_source_geometry": kept_source_names,
            "presentation_source_policy": (
                "Exact retain_exposed allowlist from the per-state controlled-GLB "
                "source-disposition ledger; every other occurrence has a named A01-A10 "
                "replacement, access chain or enclosing responsibility."
            ),
            "preview": str(final_png.relative_to(REPOSITORY_ROOT)),
            "qa_preview": str(qa_png.relative_to(REPOSITORY_ROOT)),
            "silhouette_views": silhouette_paths,
            "parts": [
                {
                    "name": part.name,
                    "module": part.module,
                    "material": part.material,
                    "intent": part.intent,
                    "bounds": authoritative_part_bounds[part.name],
                    "metadata": part.metadata,
                    "geometry_roundtrip": roundtrip_evidence[part.name],
                    "step_path": str(
                        (part_dir / f"{part.name}.step").relative_to(REPOSITORY_ROOT)
                    ),
                }
                for part in parts
            ],
        }

    hero_qa_pair_failures: list[str] = []
    checks_by_state_view = {
        (str(check["state"]), str(check["view"])): check
        for check in render_checks
    }
    for state in STATES:
        hero_check = checks_by_state_view.get((state.configuration, "hero"), {})
        qa_check = checks_by_state_view.get((state.configuration, "qa_overlay"), {})
        if hero_check.get("sha256") == qa_check.get("sha256"):
            hero_qa_pair_failures.append(
                f"{state.configuration} hero and QA overlay hashes are identical"
            )
    render_gate_failures = [
        f"{check.get('state')}.{check.get('view')}: "
        + "; ".join(str(item) for item in check.get("failures", []))
        for check in render_checks
        if check.get("status") != "PASS"
    ]
    render_gate_failures.extend(hero_qa_pair_failures)
    if len(render_checks) != 32:
        render_gate_failures.append(
            f"render inventory is {len(render_checks)}, expected 32"
        )
    if len({str(check.get("path")) for check in render_checks}) != 32:
        render_gate_failures.append("render paths are not 32 unique files")
    render_series_report = {
        "schema_version": 1,
        "gate": "V8 final render-series raster delivery and framing",
        "status": "FAIL" if render_gate_failures else "PASS",
        "build_started_ns": build_started_ns,
        "expected_render_count": 32,
        "actual_render_count": len(render_checks),
        "required_resolution_px": [1600, 1200],
        "orthographic_minimum_frame_clearance_px": 24,
        "hero_qa_hashes_must_differ": True,
        "failures": render_gate_failures,
        "renders": render_checks,
    }
    render_series_report_path = _write_json(
        qa_dir / "render_series_raster_gate.json",
        render_series_report,
    )
    artifact_paths.append(render_series_report_path)
    manifest["validation_gates"]["render_series_raster"] = {
        "status": render_series_report["status"],
        "render_count": render_series_report["actual_render_count"],
        "report": str(render_series_report_path.relative_to(REPOSITORY_ROOT)),
    }
    if render_series_report["status"] != "PASS":
        raise RuntimeError(
            "Final render-series raster gate failed: "
            + " | ".join(render_gate_failures)
        )

    # GLB generation tessellates each reloaded TopoDS shape in place.  That
    # presentation cache is allowed to approximate the surface for pixels but
    # must never become downstream dimensional evidence.  Re-import every
    # individually exported part from disk after rendering, comparing it once
    # more with the untouched pre-export authority, and use only these clean
    # STEP B-Reps for all post-step geometry and collision gates.
    roundtripped_parts_by_state.clear()
    for state in STATES:
        pristine_parts, _ = _reload_exported_parts(
            parts_by_state[state.configuration],
            OUTPUT / state.configuration / "parts",
        )
        pristine_errors = validate_parts(pristine_parts)
        if pristine_errors:
            raise RuntimeError(
                f"{state.configuration} pristine post-render STEP reload invalid: "
                f"{pristine_errors}"
            )
        roundtripped_parts_by_state[state.configuration] = pristine_parts

    # The individually exported-and-reloaded STEP solids are the downstream
    # authority.  Re-run both release and rigid-pair collision gates on those
    # exact BReps so the final evidence cannot rely only on pre-export memory.
    post_step_geometry_release_report = run_v8_release_gates(
        parts_by_state=roundtripped_parts_by_state,
        workspace_root=REPOSITORY_ROOT,
    )
    post_step_collision_reports = {
        state: _rigid_collision_report(parts, state)
        for state, parts in roundtripped_parts_by_state.items()
    }
    post_step_optional_footrest_variants = _optional_footrest_open_variants(
        roundtripped_parts_by_state
    )
    post_step_optional_footrest_collision_reports = {
        substate: _rigid_collision_report(parts, substate)
        for substate, parts in post_step_optional_footrest_variants.items()
    }
    post_step_collision_status = (
        "PASS"
        if len(post_step_collision_reports) == len(STATES)
        and all(
            report.get("status") == "PASS"
            for report in post_step_collision_reports.values()
        )
        else "FAIL"
    )

    post_step_geometry_release_path = _write_json(
        qa_dir / "v8_geometry_release_gate_post_step.json",
        post_step_geometry_release_report,
    )
    post_step_collision_paths = {
        state: _write_json(
            qa_dir / f"rigid_pair_collision_post_step_{state}.json",
            report,
        )
        for state, report in post_step_collision_reports.items()
    }
    post_step_optional_footrest_collision_paths = {
        substate: _write_json(
            qa_dir / f"rigid_pair_collision_post_step_{substate}.json",
            report,
        )
        for substate, report in post_step_optional_footrest_collision_reports.items()
    }
    artifact_paths.extend(
        (
            post_step_geometry_release_path,
            *post_step_collision_paths.values(),
            *post_step_optional_footrest_collision_paths.values(),
        )
    )
    manifest["validation_gates"]["v8_geometry_release_post_step"] = {
        "status": post_step_geometry_release_report["status"],
        "decision": post_step_geometry_release_report["decision"],
        "summary": post_step_geometry_release_report["summary"],
        "report": str(
            post_step_geometry_release_path.relative_to(REPOSITORY_ROOT)
        ),
    }
    manifest["validation_gates"]["rigid_pair_collision_post_step"] = {
        "status": post_step_collision_status,
        "states": {
            state: {
                "status": report["status"],
                "hard_collision_count": report["hard_collision_count"],
                "report": str(
                    post_step_collision_paths[state].relative_to(REPOSITORY_ROOT)
                ),
            }
            for state, report in post_step_collision_reports.items()
        },
    }
    manifest["validation_gates"]["optional_footrest_open_collision_post_step"] = {
        "status": (
            "PASS"
            if all(
                report["status"] == "PASS"
                for report in post_step_optional_footrest_collision_reports.values()
            )
            else "FAIL"
        ),
        "primary_render_series_membership": False,
        "substates": {
            substate: {
                "status": report["status"],
                "hard_collision_count": report["hard_collision_count"],
                "report": str(
                    post_step_optional_footrest_collision_paths[substate].relative_to(
                        REPOSITORY_ROOT
                    )
                ),
            }
            for substate, report in post_step_optional_footrest_collision_reports.items()
        },
    }
    _require_gate_pass(
        post_step_geometry_release_report,
        "post-STEP executable geometry",
    )
    for state, report in post_step_collision_reports.items():
        _require_gate_pass(report, f"{state} post-STEP rigid-pair collision")
    for substate, report in post_step_optional_footrest_collision_reports.items():
        _require_gate_pass(report, f"{substate} post-STEP rigid-pair collision")

    source_hashes_after = _assert_sources()
    generator_source_hashes_after = _generator_source_hashes()
    if generator_source_hashes_before != generator_source_hashes_after:
        changed = sorted(
            path
            for path in set(generator_source_hashes_before)
            | set(generator_source_hashes_after)
            if generator_source_hashes_before.get(path)
            != generator_source_hashes_after.get(path)
        )
        raise RuntimeError(
            "V8 generator/design sources changed during the formal build: "
            + ", ".join(changed)
        )
    manifest["controlled_source_hashes_after"] = source_hashes_after
    manifest["generator_source_hashes_after"] = generator_source_hashes_after
    manifest["generator_sources_unchanged"] = True
    manifest["controlled_sources_unchanged"] = (
        source_hashes_before == source_hashes_after
    )

    post_export_report = validate_class_a(
        manifest=manifest,
        workspace_root=REPOSITORY_ROOT,
        search_roots=(OUTPUT,),
    )
    _require_pass(post_export_report, "post-export")
    post_export_check_id_report = assert_unique_check_ids(
        post_export_report,
        "post_export",
    )
    post_export_report = annotate_evidence_kinds(post_export_report)
    validation_path = OUTPUT / "class_a_validation.json"
    _write_json(validation_path, post_export_report)
    post_export_check_id_path = _write_json(
        OUTPUT / "qa" / "post_export_check_id_gate.json",
        post_export_check_id_report,
    )
    artifact_paths.extend((validation_path, post_export_check_id_path))
    manifest["validation_gates"]["post_export"] = {
        "status": post_export_report["status"],
        "summary": post_export_report["summary"],
        "report": str(validation_path.relative_to(REPOSITORY_ROOT)),
        "check_id_gate": str(
            post_export_check_id_path.relative_to(REPOSITORY_ROOT)
        ),
    }
    manifest["validation_report"] = str(validation_path.relative_to(REPOSITORY_ROOT))

    exported_step_report = validate_exported_part_steps(
        manifest,
        REPOSITORY_ROOT,
    )
    glb_report = validate_glb_units_and_inventory(
        manifest,
        REPOSITORY_ROOT,
    )
    exported_step_report_path = _write_json(
        OUTPUT / "qa" / "exported_part_step_reload_gate.json",
        exported_step_report,
    )
    glb_report_path = _write_json(
        OUTPUT / "qa" / "glb_units_inventory_gate.json",
        glb_report,
    )
    artifact_paths.extend((exported_step_report_path, glb_report_path))
    manifest["validation_gates"]["exported_part_step_reload"] = {
        "status": exported_step_report["status"],
        "report": str(exported_step_report_path.relative_to(REPOSITORY_ROOT)),
    }
    manifest["validation_gates"]["glb_units_inventory"] = {
        "status": glb_report["status"],
        "report": str(glb_report_path.relative_to(REPOSITORY_ROOT)),
    }
    # These two reports validate the exact downstream artifacts rather than
    # the in-memory BReps.  They are release gates, not informational logs:
    # neither the release status nor removal of BUILD_INCOMPLETE is permitted
    # when an exported part cannot be reloaded or a review GLB has the wrong
    # unit/inventory contract.
    _require_gate_pass(exported_step_report, "exported part STEP reload")
    _require_gate_pass(glb_report, "GLB units and inventory")

    draft_docs_dir = SCRIPT_DIR / "release_docs_v8_draft"
    release_doc_paths: list[Path] = []
    release_doc_sources = (
        (draft_docs_dir / "RELEASE_README_DRAFT.md", "RELEASE_README_DRAFT.md"),
        (
            draft_docs_dir / "production_retest_matrix_draft.md",
            "production_retest_matrix_draft.md",
        ),
        (
            draft_docs_dir / "visual_design_rationale_draft.md",
            "visual_design_rationale_draft.md",
        ),
        (
            SCRIPT_DIR / "v8_final_appearance_freeze.md",
            "v8_final_appearance_freeze.md",
        ),
        (
            REPOSITORY_ROOT / "docs" / "e6_object_character_and_mystery_brief.md",
            "e6_object_character_and_mystery_brief.md",
        ),
    )
    for source_path, destination_name in release_doc_sources:
        if not source_path.is_file():
            raise FileNotFoundError(f"missing V8 release document: {source_path}")
        destination = OUTPUT / "docs" / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        release_doc_paths.append(destination)
    artifact_paths.extend(release_doc_paths)
    manifest["release_documents"] = [
        str(path.relative_to(REPOSITORY_ROOT)).replace("\\", "/")
        for path in release_doc_paths
    ]

    release_status = {
        "schema_version": 1,
        "status": "DIGITAL_CAD_RELEASE_GATE_PASS",
        "production_certification_claimed": False,
        "production_release_status": "BLOCKED_PENDING_PHYSICAL_AND_REGULATORY_EVIDENCE",
        "controlled_sources_unchanged": manifest["controlled_sources_unchanged"],
        "generator_sources_unchanged": manifest["generator_sources_unchanged"],
        "digital_gate_status": {
            key: value.get("status") if isinstance(value, dict) else None
            for key, value in manifest["validation_gates"].items()
            if key != "rigid_pair_collision"
        },
        "rigid_pair_collision_status": {
            state: entry["status"]
            for state, entry in manifest["validation_gates"][
                "rigid_pair_collision"
            ].items()
        },
        "not_certified_domains": geometry_release_report["not_certified_domains"],
    }
    release_status_path = _write_json(
        OUTPUT / "release_status.json",
        release_status,
    )
    artifact_paths.append(release_status_path)

    manifest["artifact_sha256"] = {
        str(path.relative_to(OUTPUT)).replace("\\", "/"): sha256(path)
        for path in sorted(set(artifact_paths))
    }

    # First prove the artifact tree is closed while the fail-safe marker still
    # exists.  The marker is an explicit pre-commit exception, never a payload
    # artifact.  Removing it before this check could leave a failed build that
    # appears releasable.
    precommit_closure_report = validate_closed_artifact_set(
        OUTPUT,
        manifest,
        allowed_unlisted=("class_a_skin_manifest.json", "BUILD_INCOMPLETE"),
    )
    manifest["validation_gates"]["artifact_closure_precommit"] = (
        precommit_closure_report
    )
    manifest_path = OUTPUT / "class_a_skin_manifest.json"
    _write_json(manifest_path, manifest)
    # Removing the fail-safe marker, proving final closure and publishing the
    # final manifest are one protected commit.  A caught failure restores the
    # marker; the manifest replacement itself cannot expose a partial JSON file.
    final_closure_report = _commit_final_artifact_closure(
        output=OUTPUT,
        incomplete_path=incomplete_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "states": list(manifest["states"]),
                "controlled_sources_unchanged": manifest[
                    "controlled_sources_unchanged"
                ],
                "pre_export_validation": pre_export_report["summary"],
                "post_export_validation": post_export_report["summary"],
                "exported_part_step_reload": exported_step_report["status"],
                "glb_units_inventory": glb_report["status"],
                "artifact_closure": final_closure_report["status"],
                "production_certification_claimed": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
