"""Render the frozen eight-view, four-state V11 review series.

This script records render completion only.  It deliberately uses
``RENDERED_UNREVIEWED`` rather than claiming that visual or engineering gates
passed.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import bpy


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from render_v11_preview import configure_view  # noqa: E402
from v11_common import V11_ROOT, atomic_write_json, read_json, sha256, validate_state  # noqa: E402


VIEWS = (
    "hero",
    "front_high",
    "rear_oblique",
    "front",
    "rear",
    "left",
    "right",
    "top",
)


def args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--resolution", type=int, default=1280)
    return parser.parse_args(raw)


def render_atomic(scene: bpy.types.Scene, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial.png")
    if temporary.exists():
        temporary.unlink()
    scene.render.filepath = str(temporary)
    bpy.ops.render.render(write_still=True)
    if not temporary.is_file() or temporary.stat().st_size < 4096:
        raise RuntimeError(f"Incomplete final render: {temporary}")
    os.replace(temporary, output)


def main() -> None:
    parsed = args()
    state = validate_state(parsed.state)
    revision = parsed.revision.strip().lower()
    scene = bpy.context.scene
    if str(scene.get("wc_state", "")) != state:
        raise RuntimeError(f"Open blend state {scene.get('wc_state')} != requested {state}")
    if str(scene.get("visual_revision", "")) != revision:
        raise RuntimeError(
            f"Open blend revision {scene.get('visual_revision')} != requested {revision}"
        )
    blend_path = Path(bpy.data.filepath)
    if not blend_path.is_file():
        raise RuntimeError("Final renderer requires a saved blend")
    camera = bpy.data.objects.get("V11_CAMERA")
    if camera is None or camera.type != "CAMERA":
        raise RuntimeError("V11_CAMERA missing")

    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = parsed.resolution
    scene.render.resolution_y = parsed.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    output_root = V11_ROOT / "renders" / "final" / revision / state
    records = []
    for index, view in enumerate(VIEWS, start=1):
        configure_view(camera, state, view)
        output = output_root / f"{index:02d}_{state}_{view}.png"
        render_atomic(scene, output)
        records.append(
            {
                "index": index,
                "view": view,
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": sha256(output),
            }
        )
        print("V11_FINAL_RENDERED", state, index, view, output, flush=True)

    now = datetime.now(timezone.utc).isoformat()
    state_report = {
        "schema_version": 1,
        "status": "RENDERED_UNREVIEWED",
        "state": state,
        "revision": revision,
        "rendered_at_utc": now,
        "blend": str(blend_path),
        "blend_bytes": blend_path.stat().st_size,
        "blend_sha256": sha256(blend_path),
        "resolution": [parsed.resolution, parsed.resolution],
        "engine": scene.render.engine,
        "required_views": list(VIEWS),
        "renders": records,
    }
    report_path = V11_ROOT / "qa" / revision / f"v11_{state}_{revision}_final_render_report.json"
    atomic_write_json(report_path, state_report)

    manifest_path = V11_ROOT / "qa" / revision / "final_series_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {
        "schema_version": 1,
        "revision": revision,
        "status": "RENDERED_UNREVIEWED",
        "required_state_count": 4,
        "required_views_per_state": len(VIEWS),
        "required_render_count": 4 * len(VIEWS),
        "states": {},
    }
    manifest["updated_at_utc"] = now
    manifest["states"][state] = state_report
    manifest["actual_state_count"] = len(manifest["states"])
    manifest["actual_render_count"] = sum(
        len(value.get("renders", [])) for value in manifest["states"].values()
    )
    manifest["complete"] = (
        manifest["actual_state_count"] == manifest["required_state_count"]
        and manifest["actual_render_count"] == manifest["required_render_count"]
    )
    atomic_write_json(manifest_path, manifest)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
