"""Run the V8 exterior gates with durable progress checkpoints.

The normal gate entry point intentionally returns one atomic report.  This
runner keeps the exact same gate functions, but records a checkpoint after
each group so a long OpenCascade boolean cannot make an entire unattended run
opaque.  It does not modify controlled STEP/GLB inputs or release artifacts.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import v8_release_gates as gates


Gate = tuple[str, Callable[..., None]]


GATE_SEQUENCE: tuple[Gate, ...] = (
    ("part_topology", gates._gate_part_topology),
    ("retract_then_fold", gates._gate_retract_then_fold),
    ("fixed_backrest_root_shoulders", gates._gate_fixed_backrest_root_shoulders),
    ("a05_stowed_faces", gates._gate_a05_stowed_faces),
    ("fixed_armrest_configuration", gates._gate_fixed_armrest_configuration),
    ("front_nose_sightline_crown", gates._gate_front_nose_sightline_crown),
    ("front_waist_closure", gates._gate_front_waist_closure),
    ("wheel_arch_coverage", gates._gate_wheel_arch_coverage),
    ("a07_single_moving_spine", gates._gate_a07_single_moving_spine),
    ("a07_privacy_shutter", gates._gate_a07_privacy_shutter),
    ("a08_root_enclosure", gates._gate_a08_root_enclosure),
    ("a08_drains", gates._gate_a08_drains),
    ("a09_three_stages", gates._gate_a09_three_stages),
    ("a09_production_enclosures", gates._gate_a09_production_enclosures),
    ("a10_openings", gates._gate_a10_openings),
    ("four_state_envelopes", gates._gate_four_state_envelopes),
)


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _snapshot(
    *,
    status: str,
    started_at: str,
    completed_groups: list[dict[str, Any]],
    book: gates._GateBook,
    active_group: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    failures = [check["id"] for check in book.checks if not check["pass"]]
    return {
        "schema_version": 1,
        "runner": "WorkCore E6 V8 staged release-gate runner",
        "status": status,
        "started_at_utc": started_at,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "active_group": active_group,
        "completed_groups": completed_groups,
        "check_count": len(book.checks),
        "hard_failure_count": len(failures),
        "hard_failures": failures,
        "checks": book.checks,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--only",
        help="Optional comma-separated gate group names; source_integrity is always run.",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        help="Optional isolated directory for non-release hero/left/top review renders.",
    )
    args = parser.parse_args()

    selected = None
    if args.only:
        selected = {name.strip() for name in args.only.split(",") if name.strip()}
        known = {name for name, _function in GATE_SEQUENCE}
        unknown = sorted(selected - known)
        if unknown:
            parser.error(f"unknown gate groups: {unknown}")

    output = args.output.resolve()
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    book = gates._GateBook()
    completed: list[dict[str, Any]] = []

    # Fail fast on source-responsibility ambiguity before spending minutes on
    # four OpenCascade state builds.  The full envelope gate repeats the same
    # ledger use later against geometry; this preflight only proves that each
    # controlled occurrence has exactly one disposition and that retained
    # exterior names can be resolved for every state.
    preflight_started = time.perf_counter()
    print("PREFLIGHT source_disposition", flush=True)
    for state in gates.STATES:
        ledger = gates.build_state_ledger(state, repository_root=gates.WORKSPACE_ROOT)
        gates.retain_exposed_names(ledger)
    preflight_elapsed = time.perf_counter() - preflight_started
    completed.append(
        {
            "group": "source_disposition_preflight",
            "seconds": round(preflight_elapsed, 3),
        }
    )
    print(
        f"COMPLETED source_disposition_preflight {preflight_elapsed:.3f}s",
        flush=True,
    )

    states: dict[str, list[gates.SkinPart]] = {}
    print("BUILDING_STATES", flush=True)
    for state in gates.STATES:
        _write_checkpoint(
            output,
            _snapshot(
                status="BUILDING_STATES",
                started_at=started_at,
                completed_groups=completed,
                book=book,
                active_group=f"build_state.{state}",
            ),
        )
        state_started = time.perf_counter()
        print(f"BUILDING_STATE {state}", flush=True)
        states[state] = gates.build_v8_state(state)
        elapsed = time.perf_counter() - state_started
        completed.append({"group": f"build_state.{state}", "seconds": round(elapsed, 3)})
        print(f"BUILT_STATE {state} {elapsed:.3f}s", flush=True)
    build_seconds = time.perf_counter() - started
    print(f"BUILT_STATES {build_seconds:.3f}s", flush=True)

    try:
        group_started = time.perf_counter()
        _write_checkpoint(
            output,
            _snapshot(
                status="RUNNING",
                started_at=started_at,
                completed_groups=completed,
                book=book,
                active_group="source_integrity",
            ),
        )
        source_shapes = gates._gate_source_integrity(gates.WORKSPACE_ROOT, book)
        elapsed = time.perf_counter() - group_started
        completed.append({"group": "source_integrity", "seconds": round(elapsed, 3)})
        print(f"COMPLETED source_integrity {elapsed:.3f}s", flush=True)

        for name, function in GATE_SEQUENCE:
            if selected is not None and name not in selected:
                continue
            _write_checkpoint(
                output,
                _snapshot(
                    status="RUNNING",
                    started_at=started_at,
                    completed_groups=completed,
                    book=book,
                    active_group=name,
                ),
            )
            print(f"RUNNING {name}", flush=True)
            group_started = time.perf_counter()
            if name in {"wheel_arch_coverage", "a07_privacy_shutter"}:
                function(states, gates.WORKSPACE_ROOT, book)
            elif name == "four_state_envelopes":
                function(states, source_shapes, book, gates.WORKSPACE_ROOT)
            else:
                function(states, book)
            elapsed = time.perf_counter() - group_started
            completed.append({"group": name, "seconds": round(elapsed, 3)})
            _write_checkpoint(
                output,
                _snapshot(
                    status="RUNNING",
                    started_at=started_at,
                    completed_groups=completed,
                    book=book,
                    active_group=None,
                ),
            )
            print(f"COMPLETED {name} {elapsed:.3f}s", flush=True)

        # Prove that Café/Focus can use the exact Ride deployed A08 exterior
        # without colliding with their own non-A08 state geometry.  The source
        # manifest separately owns the 21-point mechanism sweep.
        from build_class_a_skin import _optional_footrest_open_variants
        from v8_qa_gates import rigid_pair_collision_report

        optional_started = time.perf_counter()
        _write_checkpoint(
            output,
            _snapshot(
                status="RUNNING",
                started_at=started_at,
                completed_groups=completed,
                book=book,
                active_group="optional_footrest_open_collision",
            ),
        )
        optional_variants = _optional_footrest_open_variants(states)
        for substate, parts in optional_variants.items():
            report = rigid_pair_collision_report(parts, substate)
            book.add(
                f"a08.{substate}.class_a_static_collision",
                report["status"] == "PASS",
                evidence_kind="exact_rigid_pair_brep_boolean",
                requirement=(
                    "The same Ride deployed A08 exterior must fit the Café/Focus "
                    "optional-open state without a hard static interference."
                ),
                hard_collision_count=report["hard_collision_count"],
                broadphase_candidate_count=report["broadphase_candidate_count"],
                exact_boolean_count=report["exact_boolean_count"],
                hard_collisions=report["hard_collisions"],
                primary_render_series_membership=False,
            )
        elapsed = time.perf_counter() - optional_started
        completed.append(
            {"group": "optional_footrest_open_collision", "seconds": round(elapsed, 3)}
        )
        print(f"COMPLETED optional_footrest_open_collision {elapsed:.3f}s", flush=True)

        if args.preview_dir:
            from build_class_a_skin import (
                STATES as RENDER_STATES,
                _render_glb,
                _save_review_glbs,
                _silhouette_views,
            )

            preview_root = args.preview_dir.resolve()
            preview_started = time.perf_counter()
            for render_state in RENDER_STATES:
                state_dir = preview_root / render_state.configuration
                state_dir.mkdir(parents=True, exist_ok=True)
                final_glb, _qa_glb, _kept = _save_review_glbs(
                    render_state,
                    states[render_state.configuration],
                    state_dir,
                )
                _render_glb(
                    final_glb,
                    state_dir / f"hero_{render_state.configuration}.png",
                    render_state,
                )
                silhouette_views = _silhouette_views(render_state)
                for view_name in ("left", "top"):
                    view_state, scale = silhouette_views[view_name]
                    _render_glb(
                        final_glb,
                        state_dir / f"{view_name}_{render_state.configuration}.png",
                        view_state,
                        parallel_scale=scale,
                        include_floor=False,
                        auto_frame=True,
                    )
            elapsed = time.perf_counter() - preview_started
            completed.append(
                {"group": "diagnostic_preview_render", "seconds": round(elapsed, 3)}
            )
            print(f"COMPLETED diagnostic_preview_render {elapsed:.3f}s", flush=True)

        pre_schema_ids = [check["id"] for check in book.checks]
        pre_schema_evidence = [check.get("evidence_kind") for check in book.checks]
        book.add(
            "report.schema.unique_ids_and_evidence_kind",
            len(pre_schema_ids) == len(set(pre_schema_ids))
            and all(
                isinstance(value, str) and bool(value.strip())
                for value in pre_schema_evidence
            ),
            evidence_kind="report_schema_self_audit",
            requirement=(
                "Every executable check must have one unique ID and a non-empty "
                "evidence_kind."
            ),
            audited_check_count=len(pre_schema_ids),
        )
        status = "PASS" if all(check["pass"] for check in book.checks) else "FAIL"
        result = _snapshot(
            status=status,
            started_at=started_at,
            completed_groups=completed,
            book=book,
            active_group=None,
        )
        result["total_seconds"] = round(time.perf_counter() - started, 3)
        _write_checkpoint(output, result)
        print(
            f"FINISHED {status} checks={len(book.checks)} "
            f"failures={result['hard_failure_count']}",
            flush=True,
        )
        return 0 if status == "PASS" else 1
    except Exception:
        error = traceback.format_exc()
        _write_checkpoint(
            output,
            _snapshot(
                status="ERROR",
                started_at=started_at,
                completed_groups=completed,
                book=book,
                active_group=None,
                error=error,
            ),
        )
        print(error, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
