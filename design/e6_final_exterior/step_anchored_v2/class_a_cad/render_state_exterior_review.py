"""Fast one-state exterior review render for WorkCore E6 iteration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_class_a_skin import (
    STATES,
    _render_glb,
    _rigid_collision_report,
    _save_review_glbs,
    _silhouette_views,
    build_state,
)
from exterior_presentation import exterior_parts
from skin_common import validate_parts


def _critical_geometry_metrics(parts: list[object]) -> dict[str, object]:
    """Record compact production-clearance evidence beside each review."""

    by_name = {getattr(part, "name"): part for part in parts}
    nose = by_name["A01_front_nose_shell"]
    waist = by_name["A04_front_waist_fascia"]
    carrier = by_name["A01_perception_horizon_carrier"]
    metrics: dict[str, object] = {
        "front_nose_to_waist_clearance_mm": round(
            float(nose.shape.distance(waist.shape)), 6
        ),
        "front_nose_to_waist_clearance_method": waist.metadata.get(
            "a01_nose_clearance_envelope"
        ),
        "front_nose_to_waist_cutter_offset_mm": waist.metadata.get(
            "a01_nose_clearance_envelope_offset_mm"
        ),
        "front_nose_to_perception_carrier_common_mm3": round(
            float(nose.shape.intersect(carrier.shape).Volume()), 9
        ),
        "fixed_right_control_bounds_mm": {},
        "side_sail_interfaces": {},
    }
    control_bounds = metrics["fixed_right_control_bounds_mm"]
    assert isinstance(control_bounds, dict)
    for name in (
        "A05_right_removable_drive_pod",
        "A05_right_joystick",
        "A05_right_authorisation_key",
    ):
        part = by_name[name]
        bounds = part.shape.BoundingBox()
        control_bounds[name] = {
            "xmin": round(float(bounds.xmin), 6),
            "xmax": round(float(bounds.xmax), 6),
            "ymin": round(float(bounds.ymin), 6),
            "ymax": round(float(bounds.ymax), 6),
            "zmin": round(float(bounds.zmin), 6),
            "zmax": round(float(bounds.zmax), 6),
            "state_pose": part.metadata.get("state_pose"),
            "traction_authorised": part.metadata.get("traction_authorised"),
        }
    interfaces = metrics["side_sail_interfaces"]
    assert isinstance(interfaces, dict)
    for side in ("left", "right"):
        sail = by_name[f"A04_A05_integrated_side_sail_{side}"]
        bezel = by_name[f"A04_side_uwb_replaceable_bezel_{side}"]
        common = sail.shape.intersect(bezel.shape)
        interfaces[side] = {
            "sail_to_uwb_bezel_common_mm3": round(float(common.Volume()), 9),
            "sail_to_uwb_bezel_gap_mm": round(
                float(sail.shape.distance(bezel.shape)), 6
            ),
            "minimum_remaining_uwb_outer_skin_mm": sail.metadata.get(
                "minimum_remaining_uwb_outer_skin_mm"
            ),
        }
    return metrics


def main(state: str, output: Path) -> None:
    source = next(item for item in STATES if item.configuration == state)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Review output must start empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    print(f"[review:{state}] build_state", flush=True)
    full_parts = build_state(state)
    print(
        f"[review:{state}] build_state complete ({len(full_parts)} parts)",
        flush=True,
    )
    errors = validate_parts(full_parts)
    if errors:
        raise RuntimeError("; ".join(errors))
    critical_geometry = _critical_geometry_metrics(full_parts)
    print(f"[review:{state}] rigid collision gate", flush=True)
    collision = _rigid_collision_report(full_parts, state)
    (output / "endpoint_collision_review.json").write_text(
        json.dumps(collision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[review:{state}] exterior presentation", flush=True)
    visible_parts, visibility = exterior_parts(state, full_parts)
    print(
        f"[review:{state}] mesh/export ({len(visible_parts)} exterior parts)",
        flush=True,
    )
    final_glb, qa_glb, retained_source = _save_review_glbs(
        source,
        visible_parts,
        output,
        qa_parts=full_parts,
    )
    renders: dict[str, str] = {}
    hero = output / f"preview_class_a_{state}.png"
    print(f"[review:{state}] render hero", flush=True)
    _render_glb(final_glb, hero, source)
    renders["hero"] = str(hero)
    for view_name in ("front", "rear", "left", "top"):
        print(f"[review:{state}] render {view_name}", flush=True)
        view_source, scale = _silhouette_views(source)[view_name]
        target = output / f"silhouette_{view_name}_{state}.png"
        _render_glb(
            final_glb,
            target,
            view_source,
            parallel_scale=scale,
            include_floor=False,
            auto_frame=True,
        )
        renders[view_name] = str(target)

    (output / "review_summary.json").write_text(
        json.dumps(
            {
                "state": state,
                "status": (
                    "REVIEW_RENDER_COMPLETE"
                    if collision.get("status") == "PASS"
                    else "REVIEW_RENDER_COMPLETE_WITH_LAYOUT_COLLISIONS"
                ),
                "full_layout_part_count": len(full_parts),
                "exterior_part_count": len(visible_parts),
                "visibility": visibility,
                "retained_source_geometry": retained_source,
                "collision": collision,
                "critical_geometry": critical_geometry,
                "renders": renders,
                "final_glb": str(final_glb),
                "qa_glb": str(qa_glb),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[review:{state}] complete", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state", choices=[item.configuration for item in STATES])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.state, args.output.resolve())
