"""Render STEP-anchored WorkCore E6 reference images from the co-generated GLBs.

This script is intentionally read-only with respect to ``build/``.  It reads
exactly four allow-listed GLB files and writes PNG references beside itself.
The GLBs are the tessellated, colour-preserving counterparts of the STEP
assemblies generated from the same ``Part`` lists in ``cad/build.py``.

The repository's checked-in virtual-environment launcher may be stale if its
original CPython installation has moved.  In that case, invoke this script
with a compatible Python 3.12 runtime while exposing ``.venv/Lib/site-packages``
through ``PYTHONPATH``.  No CAD rebuild is required or performed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import vtk


IMAGE_SIZE = (1600, 1200)
VIEW_ANGLE_DEG = 34.0
SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
BUILD_DIR = REPOSITORY_ROOT / "build"


@dataclass(frozen=True)
class RenderCase:
    label: str
    source_name: str
    output_name: str
    camera_position: tuple[float, float, float]
    focal_point: tuple[float, float, float]


# WorkCore coordinates: -X is front, +Y is right, +Z is up.  Every camera uses
# the same (-1, +1, +0.7) direction ratio.  Focus is moved farther away and its
# focal point is raised to accommodate the deployed mast without changing the
# three-quarter viewing direction.
CASES = (
    RenderCase(
        label="Follow",
        source_name="workcore_follow_closed.glb",
        output_name="01_follow_step_anchored.png",
        camera_position=(-1730.0, 1650.0, 1535.0),
        focal_point=(-80.0, 0.0, 380.0),
    ),
    RenderCase(
        label="Ride",
        source_name="workcore_seat_ready.glb",
        output_name="02_ride_step_anchored.png",
        camera_position=(-2020.0, 1900.0, 1900.0),
        focal_point=(-120.0, 0.0, 570.0),
    ),
    RenderCase(
        label="Cafe",
        source_name="workcore_cafe.glb",
        output_name="03_cafe_step_anchored.png",
        camera_position=(-2020.0, 1900.0, 1900.0),
        focal_point=(-120.0, 0.0, 570.0),
    ),
    RenderCase(
        label="Focus",
        source_name="workcore_desk.glb",
        output_name="04_focus_step_anchored.png",
        camera_position=(-2470.0, 2350.0, 2395.0),
        focal_point=(-120.0, 0.0, 750.0),
    ),
)


def _add_studio_floor(renderer: vtk.vtkRenderer) -> None:
    floor = vtk.vtkPlaneSource()
    floor.SetOrigin(-1400.0, -1100.0, -0.75)
    floor.SetPoint1(1000.0, -1100.0, -0.75)
    floor.SetPoint2(-1400.0, 1100.0, -0.75)
    floor.Update()

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(floor.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.77, 0.775, 0.78)
    actor.GetProperty().SetInterpolationToPBR()
    actor.GetProperty().SetMetallic(0.0)
    actor.GetProperty().SetRoughness(0.96)
    renderer.AddActor(actor)


def _add_studio_lights(
    renderer: vtk.vtkRenderer,
    focal_point: tuple[float, float, float],
) -> None:
    renderer.RemoveAllLights()
    specifications = (
        ((-1300.0, 900.0, 2500.0), (1.00, 0.97, 0.93), 1.10),
        ((900.0, -1700.0, 1450.0), (0.74, 0.84, 1.00), 0.58),
        ((1200.0, 1800.0, 2050.0), (1.00, 0.91, 0.74), 0.72),
    )
    for position, colour, intensity in specifications:
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*position)
        light.SetFocalPoint(*focal_point)
        light.SetColor(*colour)
        light.SetIntensity(intensity)
        renderer.AddLight(light)


def _render(case: RenderCase) -> None:
    source = BUILD_DIR / case.source_name
    output = SCRIPT_DIR / case.output_name

    allowed_sources = {BUILD_DIR / item.source_name for item in CASES}
    if source not in allowed_sources:
        raise ValueError(f"Source is not allow-listed: {source}")
    if not source.is_file():
        raise FileNotFoundError(source)

    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.925, 0.93, 0.935)
    renderer.SetUseFXAA(True)

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(*IMAGE_SIZE)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)

    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(source))
    importer.SetRenderWindow(window)
    importer.Update()

    geometry_actor_count = renderer.GetActors().GetNumberOfItems()
    if geometry_actor_count < 1:
        window.Finalize()
        raise RuntimeError(f"No renderable geometry imported from {source}")

    camera = renderer.GetActiveCamera()
    camera.SetPosition(*case.camera_position)
    camera.SetFocalPoint(*case.focal_point)
    camera.SetViewUp(0.0, 0.0, 1.0)
    camera.SetViewAngle(VIEW_ANGLE_DEG)

    _add_studio_floor(renderer)
    _add_studio_lights(renderer, case.focal_point)
    renderer.ResetCameraClippingRange()

    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(output))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()

    print(
        f"{case.label}: source={source.name} actors={geometry_actor_count} "
        f"camera={case.camera_position} focal={case.focal_point} "
        f"size={IMAGE_SIZE[0]}x{IMAGE_SIZE[1]} output={output}"
    )


def main() -> None:
    for case in CASES:
        _render(case)


if __name__ == "__main__":
    main()
