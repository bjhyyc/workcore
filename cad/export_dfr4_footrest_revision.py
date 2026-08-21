"""Export the isolated E6-DFR4 A08 source revision.

The published E6-DFR3 files in ``build/`` are immutable inputs.  This command
creates a separate, hash-bound source set for the V8 Class-A release candidate:
four primary states plus Cafe/Focus optional-footrest-open validation states.
No artifact is published unless the A08 identity, endpoint clearance, 21-point
sweep and feet-to-floor gates all pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import cadquery as cq
import numpy as np
import trimesh


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from build import (  # noqa: E402
    Part,
    aabb,
    build_configuration,
    validate_footrest_contract,
)
from footrest_state import (  # noqa: E402
    CONTRACT_VERSION,
    FootrestPose,
    default_footrest_pose,
    optional_footrest_open_available,
)


DEFAULT_OUTPUT = (
    ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
    / "controlled_source_e6_dfr4"
)


@dataclass(frozen=True)
class StateSpec:
    release_state: str
    source_configuration: str
    footrest_pose: FootrestPose | None
    primary_render_state: bool


STATE_SPECS = (
    StateSpec("follow", "follow", None, True),
    StateSpec("ride", "seat", None, True),
    StateSpec("cafe", "cafe", None, True),
    StateSpec("focus", "desk", None, True),
    StateSpec("cafe_footrest_open", "cafe", FootrestPose.DEPLOYED_LOCKED, False),
    StateSpec("focus_footrest_open", "desk", FootrestPose.DEPLOYED_LOCKED, False),
)

PRESERVED_DFR3_FILES = (
    "workcore_follow_closed.step",
    "workcore_follow_closed.glb",
    "workcore_seat_ready.step",
    "workcore_seat_ready.glb",
    "workcore_cafe.step",
    "workcore_cafe.glb",
    "workcore_desk.step",
    "workcore_desk.glb",
)

GENERATOR_FILES = (
    "cad/parameters.py",
    "cad/footrest_state.py",
    "cad/build.py",
    "cad/export_dfr4_footrest_revision.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _export_step(parts: Iterable[Part], target: Path, state: str) -> None:
    assembly = cq.Assembly(name=f"WorkCore_E6_DFR4_{state}")
    for candidate in parts:
        assembly.add(
            candidate.shape,
            name=candidate.name,
            color=cq.Color(*candidate.color),
        )
    assembly.save(str(target), exportType="STEP", mode="default")


def _export_glb(parts: Iterable[Part], target: Path) -> None:
    """Export a standards-correct metre-native glTF scene."""

    scene = trimesh.Scene()
    scene.units = "meters"
    for candidate in parts:
        vertices, triangles = candidate.solid.tessellate(1.0, 0.25)
        vertices_np = np.asarray(
            [[vertex.x, vertex.y, vertex.z] for vertex in vertices],
            dtype=float,
        ) * 0.001
        faces_np = np.asarray(triangles, dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=vertices_np, faces=faces_np, process=False)
        mesh.visual = trimesh.visual.ColorVisuals(
            mesh,
            face_colors=np.asarray(
                [int(round(255.0 * channel)) for channel in candidate.color],
                dtype=np.uint8,
            ),
        )
        scene.add_geometry(
            mesh,
            node_name=candidate.name,
            geom_name=candidate.name,
        )
    target.write_bytes(scene.export(file_type="glb"))


def _part_record(candidate: Part) -> dict[str, object]:
    bounds = aabb(candidate.shape)
    return {
        "name": candidate.name,
        "physical_occurrence_id": candidate.physical_occurrence_id,
        "identity_basis": candidate.identity_basis,
        "definition_revision": candidate.definition_revision,
        "mechanism_pose": candidate.mechanism_pose,
        "mechanism_contract": candidate.mechanism_contract,
        "material": candidate.material,
        "process": candidate.process,
        "volume_mm3": round(candidate.volume_mm3, 6),
        "mass_kg": round(candidate.mass_kg, 9),
        "solid_count": len(candidate.solid.Solids()),
        "face_count": len(candidate.solid.Faces()),
        "edge_count": len(candidate.solid.Edges()),
        "bounds_mm": {key: round(value, 6) for key, value in bounds.items()},
    }


def _build_states() -> dict[str, list[Part]]:
    return {
        spec.release_state: build_configuration(
            spec.source_configuration,
            spec.footrest_pose,
        )
        for spec in STATE_SPECS
    }


def _validate(states: dict[str, list[Part]]) -> list[dict]:
    default_configs = {
        "follow": states["follow"],
        "seat": states["ride"],
        "cafe": states["cafe"],
        "desk": states["focus"],
    }
    checks = validate_footrest_contract(default_configs)
    for state, parts in states.items():
        invalid = sorted(
            candidate.name for candidate in parts if not candidate.solid.isValid()
        )
        checks.append(
            {
                "configuration": state,
                "check": "all_source_solids_valid",
                "invalid_parts": invalid,
                "part_count": len(parts),
                "pass": not invalid,
            }
        )
    return checks


def export_revision(output: Path, *, force: bool = False) -> dict[str, object]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing DFR4 source set: {output}")

    dfr3_hashes = {}
    for filename in PRESERVED_DFR3_FILES:
        path = ROOT / "build" / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        dfr3_hashes[filename] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

    generator_hashes = {}
    for relative in GENERATOR_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        generator_hashes[relative] = sha256(path)

    states = _build_states()
    checks = _validate(states)
    failures = [check for check in checks if not check["pass"]]
    if failures:
        raise RuntimeError(
            "E6-DFR4 A08 source validation failed:\n"
            + json.dumps(failures, ensure_ascii=False, indent=2)
        )

    temp_parent = output.parent
    with tempfile.TemporaryDirectory(prefix=".e6_dfr4_a08_", dir=temp_parent) as raw:
        staging = Path(raw)
        artifacts: dict[str, dict[str, object]] = {}
        state_records: dict[str, object] = {}
        for spec in STATE_SPECS:
            parts = states[spec.release_state]
            step_name = f"workcore_e6_dfr4_{spec.release_state}.step"
            glb_name = f"workcore_e6_dfr4_{spec.release_state}.glb"
            step_path = staging / step_name
            glb_path = staging / glb_name
            _export_step(parts, step_path, spec.release_state)
            _export_glb(parts, glb_path)
            for path in (step_path, glb_path):
                artifacts[path.name] = {
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            a08 = [part for part in parts if part.name.startswith("footrest_")]
            state_records[spec.release_state] = {
                "source_configuration": spec.source_configuration,
                "primary_render_state": spec.primary_render_state,
                "footrest_pose": a08[0].mechanism_pose,
                "optional_footrest_open_available": optional_footrest_open_available(
                    spec.source_configuration
                ),
                "step": step_name,
                "glb": glb_name,
                "glb_units": "meters",
                "part_count": len(parts),
                "a08_occurrence_count": len(a08),
                "a08_total_mass_kg": round(sum(part.mass_kg for part in a08), 9),
                "a08_occurrences": [_part_record(part) for part in a08],
            }

        # Recheck that immutable DFR3 inputs did not change during generation.
        dfr3_after = {
            filename: sha256(ROOT / "build" / filename)
            for filename in PRESERVED_DFR3_FILES
        }
        drift = {
            filename: {"before": dfr3_hashes[filename]["sha256"], "after": digest}
            for filename, digest in dfr3_after.items()
            if digest != dfr3_hashes[filename]["sha256"]
        }
        if drift:
            raise RuntimeError(f"Immutable E6-DFR3 source drifted during export: {drift}")

        manifest = {
            "schema": "workcore-e6-controlled-source-revision-v1",
            "revision": "E6-DFR4-A08",
            "status": "PASS",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": (
                "A08 footrest state/identity principle correction for the V8 "
                "Class-A release candidate; not a complete product certification"
            ),
            "footrest_contract_version": CONTRACT_VERSION,
            "primary_defaults": {
                "follow": default_footrest_pose("follow").value,
                "ride": default_footrest_pose("seat").value,
                "cafe": default_footrest_pose("cafe").value,
                "focus": default_footrest_pose("desk").value,
            },
            "optional_validation_states": [
                "cafe_footrest_open",
                "focus_footrest_open",
            ],
            "preserved_e6_dfr3_inputs": dfr3_hashes,
            "generator_sha256": generator_hashes,
            "validation": {
                "status": "PASS",
                "check_count": len(checks),
                "failed_count": 0,
                "checks": checks,
            },
            "states": state_records,
            "artifacts": {
                "files": [
                    {
                        "path": str((output / filename).relative_to(ROOT)).replace("\\", "/"),
                        **record,
                    }
                    for filename, record in sorted(artifacts.items())
                ]
            },
        }
        manifest_path = staging / "e6_dfr4_a08_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest["manifest_sha256_before_self_entry"] = sha256(manifest_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(staging, output)

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    manifest = export_revision(args.output, force=args.force)
    print(
        json.dumps(
            {
                "revision": manifest["revision"],
                "status": manifest["status"],
                "output": str(args.output.resolve()),
                "states": list(manifest["states"]),
                "validation_check_count": manifest["validation"]["check_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
