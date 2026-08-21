"""Checkpointed Eevee preview renderer for V11 state blends."""

from __future__ import annotations

import argparse
import math
import os
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from v11_common import PREVIEW_ROOT, V11_ROOT, atomic_write_json, sha256, validate_state  # noqa: E402


def args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--revision", default="r01")
    parser.add_argument("--views", default="hero")
    parser.add_argument("--resolution", type=int, default=720)
    return parser.parse_args(argv)


def point_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def configure_view(camera: bpy.types.Object, state: str, view: str) -> None:
    target_z = 0.42 if state == "follow" else (0.72 if state == "focus" else 0.57)
    target = (-0.10, 0.0, target_z)
    camera.data.lens = 58.0
    if view == "hero":
        camera.data.type = "PERSP"
        if state == "follow":
            camera.location = (-1.52, 1.38, 1.18)
            target = (-0.08, 0.0, 0.42)
        elif state == "focus":
            camera.location = (-2.05, 1.85, 1.92)
            target = (-0.10, 0.0, 0.72)
        else:
            camera.location = (-1.78, 1.58, 1.52)
    elif view == "rear_oblique":
        camera.data.type = "PERSP"
        # Keep the complete product silhouette in frame.  The former shared
        # camera aimed too low and cropped the mast in Ride/Cafe/Focus.
        camera.data.lens = 55.0
        if state == "follow":
            camera.location = (1.58, -1.40, 1.20)
            target = (-0.03, 0.0, 0.43)
        elif state == "focus":
            camera.location = (2.10, -1.85, 1.80)
            target = (-0.03, 0.0, 0.72)
        else:
            camera.location = (1.88, -1.65, 1.55)
            target = (-0.03, 0.0, 0.57)
    elif view == "front_high":
        camera.data.type = "PERSP"
        # Front-high remains an overview, not a cropped detail shot.
        camera.data.lens = 55.0
        if state == "follow":
            camera.location = (-1.75, 1.20, 1.38)
            target = (-0.08, 0.0, 0.43)
        elif state == "focus":
            camera.location = (-2.20, 1.65, 2.10)
            target = (-0.08, 0.0, 0.72)
        else:
            camera.location = (-1.95, 1.35, 1.67)
            target = (-0.08, 0.0, 0.57)
    else:
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 0.92 if state == "follow" else (1.62 if state == "focus" else 1.25)
        distance = 2.6
        if view == "front":
            camera.location = (-distance, 0.0, target_z)
        elif view == "rear":
            camera.location = (distance, 0.0, target_z)
        elif view == "left":
            camera.location = (-0.10, -distance, target_z)
        elif view == "right":
            camera.location = (-0.10, distance, target_z)
        elif view == "top":
            camera.location = (-0.10, 0.0, 3.0)
            target = (-0.10, 0.0, 0.30)
            # Camera screen-up is world -X, so the product's front is always up.
            camera.rotation_euler = (0.0, 0.0, math.pi * 0.5)
            return
        elif view == "bottom":
            camera.location = (-0.10, 0.0, -2.4)
            target = (-0.10, 0.0, 0.18)
            camera.rotation_euler = (math.pi, 0.0, -math.pi * 0.5)
            return
        else:
            raise ValueError(f"Unsupported preview view {view!r}")
    point_at(camera, target)


def render_atomic(scene: bpy.types.Scene, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_path.with_name(final_path.stem + ".partial.png")
    if temporary.exists():
        temporary.unlink()
    scene.render.filepath = str(temporary)
    bpy.ops.render.render(write_still=True)
    if not temporary.is_file() or temporary.stat().st_size < 1024:
        raise RuntimeError(f"Incomplete render: {temporary}")
    os.replace(temporary, final_path)


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
    camera = bpy.data.objects.get("V11_CAMERA")
    if camera is None or camera.type != "CAMERA":
        raise RuntimeError("V11_CAMERA missing")
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = parsed.resolution
    scene.render.resolution_y = parsed.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    views = [value.strip() for value in parsed.views.split(",") if value.strip()]
    records = []
    for view in views:
        configure_view(camera, state, view)
        output = PREVIEW_ROOT / revision / state / f"{state}_{view}.png"
        render_atomic(scene, output)
        records.append(
            {
                "view": view,
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": sha256(output),
            }
        )
        print("V11_PREVIEW_RENDERED", state, view, output, flush=True)

    report = {
        "schema_version": 1,
        "status": "PASS",
        "state": state,
        "revision": revision,
        "blend": bpy.data.filepath,
        "resolution": [parsed.resolution, parsed.resolution],
        "engine": scene.render.engine,
        "renders": records,
    }
    atomic_write_json(
        V11_ROOT / "qa" / revision / f"v11_{state}_{revision}_preview_report.json",
        report,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
