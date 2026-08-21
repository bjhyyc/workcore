"""Generate CAD-anchored patent drawings for WorkCore E6 V8.

The appearance drawings are generated only from the four exterior STEP files.
Technical-disclosure figures are generated from named occurrences in the
full-layout STEP files and from the same motion modules used by the V8 gates.

This script deliberately produces a DRAFT package.  The source release still
declares PENDING_VISUAL_REVIEW and its current 779.4 mm width conflicts with the
752 mm freeze limit.  Nothing here claims filing or production release.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import cadquery as cq
from cadquery.occ_impl.exporters.svg import getPaths
from cadquery.occ_impl.shapes import Compound, Shape
from OCP.BRepLib import BRepLib
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from PIL import Image


SCRIPT_PATH = Path(__file__).resolve()
PACKAGE_ROOT = SCRIPT_PATH.parent
REPOSITORY_ROOT = SCRIPT_PATH.parents[3]
SOURCE_RELEASE = (
    REPOSITORY_ROOT
    / "design"
    / "e6_final_exterior"
    / "v8_final_product_original_scheme_release_20260719"
)
CAD_CODE_ROOT = (
    REPOSITORY_ROOT
    / "design"
    / "e6_final_exterior"
    / "step_anchored_v2"
    / "class_a_cad"
)
SOURCE_MANIFEST = SOURCE_RELEASE / "layout_appearance_manifest.json"
APPEARANCE_ROOT = PACKAGE_ROOT / "01_appearance_patent_drawings"
DISCLOSURE_ROOT = PACKAGE_ROOT / "02_technical_disclosure_figures"
QA_ROOT = PACKAGE_ROOT / "qa"

WIDTH = 1600
HEIGHT = 1200
STATES = ("follow", "ride", "cafe", "focus")


@dataclass(frozen=True)
class View:
    key: str
    direction: tuple[float, float, float]
    x_direction: tuple[float, float, float]
    orthographic: bool = True


VIEWS: "OrderedDict[str, View]" = OrderedDict(
    (
        ("front", View("front", (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0))),
        ("rear", View("rear", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))),
        ("left", View("left", (0.0, -1.0, 0.0), (1.0, 0.0, 0.0))),
        ("right", View("right", (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))),
        ("top", View("top", (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))),
        ("bottom", View("bottom", (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))),
        (
            "perspective_front_right",
            View(
                "perspective_front_right",
                (-1.6, 1.3, 1.1),
                (-1.3, -1.6, 0.0),
                False,
            ),
        ),
        (
            "perspective_rear_left",
            View(
                "perspective_rear_left",
                (1.4, -1.2, 0.9),
                (1.2, 1.4, 0.0),
                False,
            ),
        ),
    )
)

APPEARANCE_FILE_CODES = OrderedDict(
    (
        ("front", "D01_front"),
        ("rear", "D02_rear"),
        ("left", "D03_left"),
        ("right", "D04_right"),
        ("top", "D05_top"),
        ("bottom", "D06_bottom"),
        ("perspective_front_right", "D07_perspective_front_right"),
        ("perspective_rear_left", "D08_perspective_rear_left"),
    )
)


@dataclass(frozen=True)
class Callout:
    number: str
    selector: Callable[[str], bool]
    side: str | None = None


@dataclass(frozen=True)
class SvgProjection:
    svg: str
    unit_scale: float
    x_translate: float
    y_translate: float
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    bounds_2d: tuple[float, float, float, float]

    def screen_point(self, point: tuple[float, float, float]) -> tuple[float, float]:
        px = sum(value * axis for value, axis in zip(point, self.x_axis))
        py = sum(value * axis for value, axis in zip(point, self.y_axis))
        return (
            self.unit_scale * (px + self.x_translate),
            -self.unit_scale * (py + self.y_translate),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(vector: Sequence[float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(float(value) ** 2 for value in vector))
    if length <= 1.0e-12:
        raise ValueError(f"Cannot normalise zero vector: {vector}")
    return tuple(float(value) / length for value in vector)  # type: ignore[return-value]


def _cross(
    first: Sequence[float], second: Sequence[float]
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _bbox_tuple(shape: cq.Shape) -> tuple[float, float, float, float, float, float]:
    box = shape.BoundingBox()
    return (box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax)


def _bbox_center(shape: cq.Shape) -> tuple[float, float, float]:
    xmin, xmax, ymin, ymax, zmin, zmax = _bbox_tuple(shape)
    return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)


def _combine(shapes: Iterable[cq.Shape]) -> cq.Shape:
    material = [shape for shape in shapes if shape is not None and not shape.isNull()]
    if not material:
        raise ValueError("Cannot make a patent drawing from an empty shape selection")
    return Compound.makeCompound(material)


def _load_named_step(path: Path) -> dict[str, cq.Shape]:
    if not path.is_file():
        raise FileNotFoundError(path)
    assembly = cq.Assembly.importStep(str(path))
    result: dict[str, cq.Shape] = {}
    for name, occurrence in assembly.objects.items():
        if occurrence.obj is None:
            continue
        shape = occurrence.obj.moved(occurrence.loc)
        if shape.isNull():
            continue
        result[name] = shape
    if not result:
        raise ValueError(f"STEP assembly contains no drawable named occurrences: {path}")
    return result


def _exterior_step(state: str) -> Path:
    return SOURCE_RELEASE / state / f"workcore_e6_exterior_{state}.step"


def _full_step(state: str) -> Path:
    return SOURCE_RELEASE / state / f"workcore_e6_layout_full_{state}.step"


def _select(
    mapping: Mapping[str, cq.Shape],
    predicate: Callable[[str], bool],
    *,
    label: str,
) -> dict[str, cq.Shape]:
    selected = {name: shape for name, shape in mapping.items() if predicate(name)}
    if not selected:
        raise KeyError(f"No occurrences matched selection {label!r}")
    return selected


def _prefix(*prefixes: str) -> Callable[[str], bool]:
    return lambda name: any(name.startswith(prefix) for prefix in prefixes)


def _contains(*tokens: str) -> Callable[[str], bool]:
    return lambda name: any(token in name for token in tokens)


def _exact(*names: str) -> Callable[[str], bool]:
    allowed = set(names)
    return lambda name: name in allowed


def _or(*predicates: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda name: any(predicate(name) for predicate in predicates)


def _and(*predicates: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda name: all(predicate(name) for predicate in predicates)


def _not(predicate: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda name: not predicate(name)


def _moved_mapping(
    mapping: Mapping[str, cq.Shape],
    vector: tuple[float, float, float],
    *,
    name_prefix: str = "",
) -> dict[str, cq.Shape]:
    return {
        f"{name_prefix}{name}": shape.translate(vector)
        for name, shape in mapping.items()
    }


def _project_hlr(
    named_shapes: Mapping[str, cq.Shape],
    view: View,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    margin: float = 110.0,
    fixed_scale: float | None = None,
    show_hidden: bool = False,
    figure_label: str | None = None,
    callouts: Sequence[Callout] = (),
    panel_labels: Sequence[tuple[str, Callable[[str], bool]]] = (),
) -> SvgProjection:
    shape = _combine(named_shapes.values())
    normal = _normalise(view.direction)
    x_axis = _normalise(view.x_direction)
    dot = sum(a * b for a, b in zip(normal, x_axis))
    if abs(dot) > 1.0e-7:
        raise ValueError(f"View normal and X axis are not perpendicular: {view}")
    y_axis = _normalise(_cross(normal, x_axis))
    coordinate_system = gp_Ax2(
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Dir(*normal),
        gp_Dir(*x_axis),
    )
    algorithm = HLRBRep_Algo()
    algorithm.Add(shape.wrapped)
    algorithm.Projector(HLRAlgo_Projector(coordinate_system))
    algorithm.Update()
    algorithm.Hide()
    projected = HLRBRep_HLRToShape(algorithm)

    sharp: list[Shape] = []
    outline: list[Shape] = []
    hidden: list[Shape] = []
    visible_sharp = projected.VCompound()
    if not visible_sharp.IsNull():
        BRepLib.BuildCurves3d_s(visible_sharp, 1.0e-3)
        sharp.append(Shape(visible_sharp))
    visible_outline = projected.OutLineVCompound()
    if not visible_outline.IsNull():
        BRepLib.BuildCurves3d_s(visible_outline, 1.0e-3)
        outline.append(Shape(visible_outline))
    if show_hidden:
        for candidate in (projected.HCompound(), projected.OutLineHCompound()):
            if not candidate.IsNull():
                BRepLib.BuildCurves3d_s(candidate, 1.0e-3)
                hidden.append(Shape(candidate))
    if not sharp and not outline:
        raise ValueError("OCC HLR returned no visible paths")

    all_projected = [*sharp, *outline, *hidden]
    projected_box = Compound.makeCompound(all_projected).BoundingBox()
    xmin, xmax = projected_box.xmin, projected_box.xmax
    ymin, ymax = projected_box.ymin, projected_box.ymax
    xlen = max(xmax - xmin, 1.0e-6)
    ylen = max(ymax - ymin, 1.0e-6)
    usable_height = height - 2.0 * margin - (55.0 if figure_label else 0.0)
    unit_scale = fixed_scale or min(
        (width - 2.0 * margin) / xlen,
        usable_height / ylen,
    )
    if unit_scale <= 0:
        raise ValueError("Invalid SVG unit scale")
    centre_x = (xmin + xmax) / 2.0
    centre_y = (ymin + ymax) / 2.0
    target_centre_y = (height - (45.0 if figure_label else 0.0)) / 2.0
    x_translate = width / (2.0 * unit_scale) - centre_x
    y_translate = -target_centre_y / unit_scale - centre_y

    _, sharp_paths = getPaths(sharp, [])
    _, outline_paths = getPaths(outline, [])
    hidden_paths, _ = getPaths([], hidden)
    sharp_paths = list(dict.fromkeys(sharp_paths))
    outline_paths = list(dict.fromkeys(outline_paths))
    hidden_paths = list(dict.fromkeys(hidden_paths))
    sharp_width = 1.25 / unit_scale
    outline_width = 1.80 / unit_scale
    hidden_width = 1.0 / unit_scale

    def paths_markup(paths: Sequence[str]) -> str:
        return "\n".join(f'<path d="{path}"/>' for path in paths)

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="white"/>
  <g transform="scale({unit_scale},-{unit_scale}) translate({x_translate},{y_translate})" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <g stroke="#000" stroke-width="{sharp_width}">{paths_markup(sharp_paths)}</g>
    <g stroke="#000" stroke-width="{outline_width}">{paths_markup(outline_paths)}</g>
    <g stroke="#777" stroke-width="{hidden_width}" stroke-dasharray="{5.0 / unit_scale},{4.0 / unit_scale}">{paths_markup(hidden_paths)}</g>
  </g>
</svg>'''
    projection = SvgProjection(
        svg=svg,
        unit_scale=unit_scale,
        x_translate=x_translate,
        y_translate=y_translate,
        x_axis=x_axis,
        y_axis=y_axis,
        bounds_2d=(xmin, xmax, ymin, ymax),
    )

    overlay: list[str] = []
    if callouts:
        targets: list[tuple[Callout, float, float]] = []
        for callout in callouts:
            matching = [
                shape
                for name, shape in named_shapes.items()
                if callout.selector(name)
            ]
            if not matching:
                raise KeyError(
                    f"Callout {callout.number} matched no occurrence in figure {figure_label}"
                )
            centre = _bbox_center(_combine(matching))
            screen_x, screen_y = projection.screen_point(centre)
            targets.append((callout, screen_x, screen_y))
        assignments: dict[str, list[tuple[Callout, float, float]]] = {
            "left": [],
            "right": [],
        }
        for callout, screen_x, screen_y in targets:
            side = callout.side or ("left" if screen_x < width / 2.0 else "right")
            assignments[side].append((callout, screen_x, screen_y))
        for side, items in assignments.items():
            items.sort(key=lambda item: item[2])
            minimum_y = 105.0
            maximum_y = height - (120.0 if figure_label else 70.0)
            if not items:
                continue
            if len(items) == 1:
                label_ys = [max(min(items[0][2], maximum_y), minimum_y)]
            else:
                preferred = [max(min(item[2], maximum_y), minimum_y) for item in items]
                gap = min(70.0, (maximum_y - minimum_y) / (len(items) - 1))
                label_ys = []
                for index, value in enumerate(preferred):
                    floor = minimum_y if index == 0 else label_ys[-1] + gap
                    label_ys.append(max(value, floor))
                overshoot = label_ys[-1] - maximum_y
                if overshoot > 0:
                    label_ys = [value - overshoot for value in label_ys]
            for (callout, target_x, target_y), label_y in zip(items, label_ys):
                if side == "left":
                    text_x, elbow_x, text_anchor = 58.0, 180.0, "start"
                    line_end_x = 122.0
                else:
                    text_x, elbow_x, text_anchor = width - 58.0, width - 180.0, "end"
                    line_end_x = width - 122.0
                overlay.append(
                    f'<polyline points="{target_x:.2f},{target_y:.2f} {elbow_x:.2f},{label_y:.2f} {line_end_x:.2f},{label_y:.2f}" fill="none" stroke="#000" stroke-width="1.4"/>'
                )
                overlay.append(
                    f'<text x="{text_x:.2f}" y="{label_y + 9.0:.2f}" text-anchor="{text_anchor}" font-family="Arial, Helvetica, sans-serif" font-size="28" fill="#000">{_escape_xml(callout.number)}</text>'
                )
    for label, selector in panel_labels:
        matching = [shape for name, shape in named_shapes.items() if selector(name)]
        if not matching:
            raise KeyError(f"Panel label {label!r} matched no occurrence")
        centre = _bbox_center(_combine(matching))
        screen_x, _ = projection.screen_point(centre)
        overlay.append(
            f'<text x="{screen_x:.2f}" y="{height - 72}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="28" fill="#000">{_escape_xml(label)}</text>'
        )
    if figure_label:
        overlay.append(
            f'<text x="{width / 2:.2f}" y="{height - 24}" text-anchor="middle" font-family="Microsoft YaHei, SimSun, sans-serif" font-size="30" fill="#000">{_escape_xml(figure_label)}</text>'
        )
    if overlay:
        svg = svg.replace("</svg>", "  <g>\n" + "\n".join(overlay) + "\n  </g>\n</svg>")
        projection = SvgProjection(
            svg=svg,
            unit_scale=projection.unit_scale,
            x_translate=projection.x_translate,
            y_translate=projection.y_translate,
            x_axis=projection.x_axis,
            y_axis=projection.y_axis,
            bounds_2d=projection.bounds_2d,
        )
    return projection


def _edge_path() -> Path:
    candidates = (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No supported Chromium/Edge executable was found")


def _svg_to_png(svg_path: Path, png_path: Path) -> None:
    browser = _edge_path()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    profile = QA_ROOT / ".headless_profile"
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--force-device-scale-factor=1",
        f"--window-size={WIDTH},{HEIGHT}",
        f"--user-data-dir={profile}",
        f"--screenshot={png_path.resolve()}",
        svg_path.resolve().as_uri(),
    ]
    completed = subprocess.run(
        command,
        cwd=str(PACKAGE_ROOT),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0 or not png_path.is_file():
        raise RuntimeError(
            f"Headless SVG rasterisation failed ({completed.returncode}):\n{completed.stdout}"
        )
    with Image.open(png_path) as image:
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"Unexpected PNG size for {png_path}: {image.size}")


def _write_projection(
    projection: SvgProjection,
    svg_path: Path,
    png_path: Path,
) -> None:
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(projection.svg, encoding="utf-8")
    _svg_to_png(svg_path, png_path)


def _state_bounds(state: str) -> dict[str, float]:
    payload = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    bounds = payload["states"][state]["exterior_bounds_mm"]
    return {key: float(value) for key, value in bounds.items()}


def _orthographic_scale(state: str) -> float:
    bounds = _state_bounds(state)
    xlen = bounds["xmax"] - bounds["xmin"]
    ylen = bounds["ymax"] - bounds["ymin"]
    zlen = bounds["zmax"] - bounds["zmin"]
    maximum_width = max(xlen, ylen)
    maximum_height = max(zlen, xlen)
    margin = 135.0
    return min(
        (WIDTH - 2.0 * margin) / maximum_width,
        (HEIGHT - 2.0 * margin) / maximum_height,
    )


def _appearance_worker(state: str, view_key: str) -> None:
    if state not in STATES:
        raise ValueError(state)
    view = VIEWS[view_key]
    named = _load_named_step(_exterior_step(state))
    scale = _orthographic_scale(state) if view.orthographic else None
    projection = _project_hlr(
        named,
        view,
        margin=135.0,
        fixed_scale=scale,
        show_hidden=False,
    )
    folder = APPEARANCE_ROOT / f"application_candidate_{state}"
    code = APPEARANCE_FILE_CODES[view_key]
    _write_projection(
        projection,
        folder / f"{code}_{state}.svg",
        folder / f"{code}_{state}.png",
    )


def _appearance_jobs() -> list[tuple[str, str]]:
    return [(state, view_key) for state in STATES for view_key in VIEWS]


def _run_isolated(arguments: Sequence[str]) -> None:
    command = [sys.executable, str(SCRIPT_PATH), *arguments]
    completed = subprocess.run(
        command,
        cwd=str(REPOSITORY_ROOT),
        check=False,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Patent drawing worker failed: {' '.join(command)}")


def _generate_appearance() -> None:
    for state, view_key in _appearance_jobs():
        print(f"[appearance] {state} / {view_key}", flush=True)
        _run_isolated(("--worker-appearance", state, view_key))


def _figure_output(stem: str) -> tuple[Path, Path]:
    return (
        DISCLOSURE_ROOT / f"{stem}.svg",
        DISCLOSURE_ROOT / f"{stem}.png",
    )


def _render_technical(
    stem: str,
    figure_label: str,
    named: Mapping[str, cq.Shape],
    view: View,
    *,
    callouts: Sequence[Callout] = (),
    panel_labels: Sequence[tuple[str, Callable[[str], bool]]] = (),
    show_hidden: bool = False,
    margin: float = 155.0,
) -> None:
    projection = _project_hlr(
        named,
        view,
        margin=margin,
        show_hidden=show_hidden,
        figure_label=figure_label,
        callouts=callouts,
        panel_labels=panel_labels,
    )
    svg_path, png_path = _figure_output(stem)
    _write_projection(projection, svg_path, png_path)


def _technical_figure_01() -> None:
    named = _load_named_step(_exterior_step("ride"))
    _render_technical(
        "fig01_ride_overall_structure",
        "图1",
        named,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("100", lambda _name: True, "left"),
            Callout("110", _prefix("A01_"), "left"),
            Callout("130", _prefix("A03_"), "left"),
            Callout("140", _prefix("A04_"), "left"),
            Callout("150", _prefix("A05_"), "right"),
            Callout("180", _prefix("A06_"), "right"),
            Callout("190", _prefix("A07_"), "right"),
            Callout("210", _prefix("A08_"), "left"),
            Callout("250", _prefix("A10_"), "right"),
        ),
    )


def _technical_figure_02() -> None:
    combined: dict[str, cq.Shape] = {}
    offsets = {"follow": 1950.0, "ride": 650.0, "cafe": -650.0, "focus": -1950.0}
    for state in STATES:
        mapping = _load_named_step(_exterior_step(state))
        combined.update(
            _moved_mapping(
                mapping,
                (offsets[state], 0.0, 0.0),
                name_prefix=f"{state}::",
            )
        )
        del mapping
        gc.collect()
    _render_technical(
        "fig02_four_state_relationship",
        "图2",
        combined,
        VIEWS["right"],
        panel_labels=tuple(
            (f"（{letter}）", lambda name, s=state: name.startswith(f"{s}::"))
            for letter, state in zip("abcd", STATES)
        ),
        margin=90.0,
    )


def _module_number(name: str) -> str | None:
    match = re.match(r"A(\d\d)_", name)
    if not match:
        return None
    return {
        "01": "110",
        "02": "120",
        "03": "130",
        "04": "140",
        "05": "150",
        "06": "180",
        "07": "190",
        "08": "210",
        "09": "230",
        "10": "250",
    }.get(match.group(1))


def _technical_figure_03() -> None:
    source = _load_named_step(_full_step("ride"))
    selected = _select(source, lambda name: re.match(r"A(01|02|03|04|05|06|07|08|09|10)_", name) is not None, label="A01-A10 generated occurrences")
    exploded: dict[str, cq.Shape] = {}
    module_offsets = {
        "A01_": (-220.0, 0.0, 0.0),
        "A02_": (0.0, 0.0, 0.0),
        "A03_": (0.0, 0.0, -90.0),
        "A04_": (0.0, 0.0, 120.0),
        "A05_": (0.0, 0.0, 210.0),
        "A06_": (180.0, 0.0, 260.0),
        "A07_": (180.0, 0.0, 500.0),
        "A08_": (-320.0, 0.0, -150.0),
        "A09_": (-80.0, 0.0, 390.0),
        "A10_": (280.0, 0.0, 0.0),
    }
    for name, shape in selected.items():
        offset = next(vector for prefix, vector in module_offsets.items() if name.startswith(prefix))
        exploded[name] = shape.translate(offset)
    callouts = []
    for prefix in module_offsets:
        number = _module_number(prefix)
        if number:
            callouts.append(Callout(number, _prefix(prefix)))
    _render_technical(
        "fig03_module_exploded",
        "图3",
        exploded,
        VIEWS["perspective_front_right"],
        callouts=tuple(callouts),
        margin=175.0,
    )


def _technical_figure_04() -> None:
    source = _load_named_step(_full_step("ride"))
    predicate = _contains(
        "/chassis_",
        "/battery_",
        "/compute_core_",
        "/communications_",
        "/drive_imu_",
        "/encrypted_data_",
        "/tyre_",
        "/hub_",
        "/axle_",
        "/suspension_rocker_",
        "/laptop_16in_",
        "/universal_flat_device_",
        "/daily_caddy_",
    )
    named = _select(source, predicate, label="internal layout essentials")
    _render_technical(
        "fig04_chassis_internal_layout",
        "图4",
        named,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("110", _contains("/chassis_"), "left"),
            Callout("132", _contains("/tyre_"), "left"),
            Callout("138", _contains("/hub_"), "left"),
            Callout("139", _contains("/suspension_rocker_"), "left"),
            Callout("261", _contains("/battery_"), "right"),
            Callout("264", _contains("/compute_core_"), "right"),
            Callout("265", _contains("/encrypted_data_"), "right"),
            Callout("266", _contains("/communications_"), "right"),
            Callout("269", _contains("/laptop_16in_", "/universal_flat_device_", "/daily_caddy_"), "right"),
        ),
        margin=175.0,
    )


def _technical_figure_05() -> None:
    source = _load_named_step(_full_step("ride"))
    predicate = _or(
        _exact(
            "A05_armrest_table_bay_shell_right",
            "A05_armrest_touch_lid_right",
            "A05_table_root_structural_cassette_right",
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        ),
        _contains("/desk_bundle_stowed_right"),
    )
    named = _select(source, predicate, label="right armrest and stowed table")
    _render_technical(
        "fig05_fixed_armrest_table_storage",
        "图5",
        named,
        VIEWS["right"],
        show_hidden=True,
        callouts=(
            Callout("152", _exact("A05_armrest_table_bay_shell_right"), "left"),
            Callout("153", _exact("A05_armrest_touch_lid_right"), "right"),
            Callout("156", _exact("A05_table_root_structural_cassette_right"), "left"),
            Callout("171", _exact("A05_right_removable_drive_pod"), "right"),
            Callout("172", _exact("A05_right_joystick"), "right"),
            Callout("173", _exact("A05_right_authorisation_key"), "right"),
            Callout("230", _contains("/desk_bundle_stowed_right"), "left"),
        ),
    )


def _lid_panel(
    source: Mapping[str, cq.Shape],
    *,
    angle: float,
    table_pose: Sequence[cq.Shape],
    offset_x: float,
    prefix: str,
) -> dict[str, cq.Shape]:
    sys.path.insert(0, str(CAD_CODE_ROOT))
    from v8_table_lid_packaging import pose_lid_shape  # pylint: disable=import-outside-toplevel

    fixed_names = (
        "A05_armrest_table_bay_shell_right",
        "A05_table_root_structural_cassette_right",
    )
    moving_names = (
        "A05_armrest_touch_lid_right",
        "A05_right_removable_drive_pod",
        "A05_right_joystick",
        "A05_right_authorisation_key",
    )
    result: dict[str, cq.Shape] = {}
    for name in fixed_names:
        result[f"{prefix}{name}"] = source[name].translate((offset_x, 0.0, 0.0))
    for name in moving_names:
        posed = pose_lid_shape(source[name], 1, angle)
        result[f"{prefix}{name}"] = posed.translate((offset_x, 0.0, 0.0))
    for index, shape in enumerate(table_pose):
        result[f"{prefix}table_pose_{index:02d}"] = shape.translate((offset_x, 0.0, 0.0))
    return result


def _technical_figure_06() -> None:
    sys.path.insert(0, str(CAD_CODE_ROOT))
    from v8_table_lid_packaging import (  # pylint: disable=import-outside-toplevel
        LID_OPEN_ANGLE_DEG,
        extraction_motion_occurrences,
        folded_pack_occurrences,
    )

    ride = _load_named_step(_full_step("ride"))
    cafe = _load_named_step(_full_step("cafe"))
    folded = tuple(item.shape for item in folded_pack_occurrences(1))
    extraction = extraction_motion_occurrences(1, samples_per_leg=5)
    raised = tuple(item.shape for item in extraction[4])
    combined: dict[str, cq.Shape] = {}
    panel_offsets = (1800.0, 600.0, -600.0, -1800.0)
    combined.update(_lid_panel(ride, angle=0.0, table_pose=folded, offset_x=panel_offsets[0], prefix="a::"))
    combined.update(_lid_panel(ride, angle=LID_OPEN_ANGLE_DEG, table_pose=folded, offset_x=panel_offsets[1], prefix="b::"))
    combined.update(_lid_panel(ride, angle=LID_OPEN_ANGLE_DEG, table_pose=raised, offset_x=panel_offsets[2], prefix="c::"))
    final_predicate = _or(
        _exact(
            "A05_armrest_table_bay_shell_right",
            "A05_armrest_touch_lid_right",
            "A05_table_root_structural_cassette_right",
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        ),
        _prefix("A09_"),
    )
    final = _select(cafe, final_predicate, label="Cafe final table and right armrest")
    combined.update(_moved_mapping(final, (panel_offsets[3], 0.0, 0.0), name_prefix="d::"))
    _render_technical(
        "fig06_top_lid_table_extraction_sequence",
        "图6",
        combined,
        VIEWS["right"],
        panel_labels=tuple(
            (f"（{letter}）", lambda name, p=f"{letter}::": name.startswith(p))
            for letter in "abcd"
        ),
        margin=95.0,
    )


def _technical_figure_07() -> None:
    source = _load_named_step(_full_step("cafe"))
    predicate = _or(
        _exact(
            "A04_seat_cushion_contact_island",
            "A05_armrest_table_bay_shell_right",
            "A05_armrest_touch_lid_right",
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        ),
        _prefix("A09_"),
    )
    named = _select(source, predicate, label="Cafe table and control")
    _render_technical(
        "fig07_cafe_single_table_mechanism",
        "图7",
        named,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("142", _exact("A04_seat_cushion_contact_island"), "left"),
            Callout("152", _exact("A05_armrest_table_bay_shell_right"), "right"),
            Callout("171", _exact("A05_right_removable_drive_pod"), "right"),
            Callout("172", _exact("A05_right_joystick"), "right"),
            Callout("173", _exact("A05_right_authorisation_key"), "right"),
            Callout("231", _contains("A09_table_half_leaf_right"), "left"),
            Callout("238", _contains("A09_cafe_underleaf_motion_belly_right", "A09_table_underbelly_shell_right"), "left"),
            Callout("239", _contains("A09_cafe_table_lift_stage_", "A09_table_lift_stage_right"), "left"),
            Callout("242", _contains("A09_cafe_", "A09_table_root_"), "right"),
        ),
    )


def _technical_figure_08() -> None:
    source = _load_named_step(_full_step("focus"))
    predicate = _or(
        _exact(
            "A04_seat_cushion_contact_island",
            "A05_armrest_table_bay_shell_left",
            "A05_armrest_table_bay_shell_right",
            "A05_armrest_touch_lid_left",
            "A05_armrest_touch_lid_right",
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        ),
        _prefix("A09_"),
    )
    named = _select(source, predicate, label="Focus dual table")
    _render_technical(
        "fig08_focus_dual_table_mechanism",
        "图8",
        named,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("142", _exact("A04_seat_cushion_contact_island"), "left"),
            Callout("151", _exact("A05_armrest_table_bay_shell_left"), "left"),
            Callout("152", _exact("A05_armrest_table_bay_shell_right"), "right"),
            Callout("170", _or(_exact("A05_right_removable_drive_pod"), _exact("A05_right_joystick"), _exact("A05_right_authorisation_key")), "right"),
            Callout("232", _contains("A09_table_half_leaf_left"), "left"),
            Callout("231", _contains("A09_table_half_leaf_right"), "right"),
            Callout("239", _contains("A09_focus_table_lift_stage_", "A09_table_lift_stage_"), "left"),
            Callout("245", _contains("centre", "center", "seam"), "right"),
        ),
    )


def _technical_figure_09() -> None:
    source = _load_named_step(_full_step("focus"))
    predicate = _or(
        _prefix("A09_"),
        _exact(
            "A05_table_root_structural_cassette_left",
            "A05_table_root_structural_cassette_right",
            "A05_right_table_root_tongue_compression_gland",
        ),
    )
    named = _select(source, predicate, label="table leaves and roots")
    _render_technical(
        "fig09_table_leaf_and_root_structure",
        "图9",
        named,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("156", _contains("A05_table_root_structural_cassette_"), "right"),
            Callout("157", _contains("compression_gland"), "right"),
            Callout("233", _contains("outer"), "left"),
            Callout("234", _contains("inner"), "left"),
            Callout("238", _contains("underbelly", "motion_belly"), "left"),
            Callout("239", _contains("lift_stage"), "right"),
            Callout("240", _contains("root"), "right"),
        ),
    )


def _technical_figure_10() -> None:
    source = _load_named_step(_exterior_step("ride"))
    predicate = _or(
        _exact(
            "A05_armrest_touch_lid_left",
            "A05_left_hmi_precision_bezel",
            "A05_left_status_display_window",
            "A05_left_qi_phone_cradle",
            "A05_left_qi_target_ring",
            "A05_left_qi_phone_stop_front",
            "A05_left_qi_phone_stop_rear",
            "A05_left_emergency_stop_guard",
            "A05_left_mechanical_emergency_stop",
            "A05_armrest_touch_lid_right",
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        ),
    )
    named = _select(source, predicate, label="left HMI and right control zone")
    _render_technical(
        "fig10_armrest_hmi_and_control_layout",
        "图10",
        named,
        VIEWS["top"],
        callouts=(
            Callout("153", _contains("armrest_touch_lid"), "left"),
            Callout("161", _contains("status_display_window"), "left"),
            Callout("162", _contains("hmi_precision_bezel"), "left"),
            Callout("163", _contains("qi_phone_cradle"), "left"),
            Callout("164", _contains("qi_target_ring"), "left"),
            Callout("165", _contains("qi_phone_stop"), "left"),
            Callout("166", _contains("emergency_stop_guard"), "left"),
            Callout("167", _contains("mechanical_emergency_stop"), "left"),
            Callout("171", _contains("removable_drive_pod"), "right"),
            Callout("172", _contains("right_joystick"), "right"),
            Callout("173", _contains("right_authorisation_key"), "right"),
        ),
    )


def _paired_state_modules(
    first_state: str,
    second_state: str,
    predicate: Callable[[str], bool],
    *,
    spacing: float,
) -> dict[str, cq.Shape]:
    first = _select(_load_named_step(_full_step(first_state)), predicate, label=f"{first_state} paired module")
    second = _select(_load_named_step(_full_step(second_state)), predicate, label=f"{second_state} paired module")
    combined = _moved_mapping(first, (spacing / 2.0, 0.0, 0.0), name_prefix="a::")
    combined.update(_moved_mapping(second, (-spacing / 2.0, 0.0, 0.0), name_prefix="b::"))
    return combined


def _technical_figure_11() -> None:
    named = _paired_state_modules("follow", "ride", _prefix("A08_"), spacing=1050.0)
    _render_technical(
        "fig11_footrest_stowed_and_deployed",
        "图11",
        named,
        VIEWS["right"],
        panel_labels=(("（a）", _prefix("a::")), ("（b）", _prefix("b::"))),
        callouts=(
            Callout("211", _contains("footrest_top_skin", "footrest_platform_undertray"), "left"),
            Callout("214", _contains("footrest_root_monocoque"), "left"),
            Callout("215", _contains("support_monocoque"), "right"),
            Callout("219", _contains("drop_link"), "right"),
            Callout("223", _contains("stowed_lock"), "left"),
            Callout("224", _contains("deployed_lock"), "right"),
        ),
    )


def _technical_figure_12() -> None:
    predicate = _or(_prefix("A06_"), _prefix("A07_"), _contains("A04_backrest_root_shoulder"))
    named = _paired_state_modules("follow", "ride", predicate, spacing=1250.0)
    _render_technical(
        "fig12_backrest_mast_shared_fold",
        "图12",
        named,
        VIEWS["right"],
        panel_labels=(("（a）", _prefix("a::")), ("（b）", _prefix("b::"))),
        callouts=(
            Callout("180", _contains("A06_backrest_weather_shell"), "left"),
            Callout("183", _contains("A06_backrest_hinge_shaft"), "left"),
            Callout("184", _contains("A06_backrest_hinge_bearing"), "left"),
            Callout("185", _contains("A06_backrest_positive_lock"), "right"),
            Callout("190", _contains("A07_mast_"), "right"),
            Callout("193", _contains("A07_sensor_beam_shell"), "right"),
        ),
    )


def _technical_figure_13() -> None:
    predicate = _or(_prefix("A07_"), _prefix("A06_"))
    named = _paired_state_modules("ride", "focus", predicate, spacing=1300.0)
    _render_technical(
        "fig13_mast_low_and_focus_high",
        "图13",
        named,
        VIEWS["right"],
        panel_labels=(("（a）", _prefix("a::")), ("（b）", _prefix("b::"))),
        callouts=(
            Callout("191", _contains("mast_fixed_outer_sleeve"), "left"),
            Callout("192", _contains("mast_moving_inner_sleeve"), "right"),
            Callout("193", _contains("sensor_beam_shell"), "right"),
            Callout("199", _contains("mast_throat_weather_gasket"), "left"),
            Callout("200", _contains("mast_lock_pin_left", "mast_lock_pin_right"), "right"),
        ),
    )


def _technical_figure_14() -> None:
    source = _load_named_step(_full_step("ride"))
    predicate = _or(
        _and(_prefix("A03_"), _contains("right")),
        _contains(
            "/tyre_front_right",
            "/tyre_rear_right",
            "/hub_front_right",
            "/hub_rear_right",
            "/axle_front_right",
            "/axle_rear_right",
            "/suspension_rocker_right",
        ),
    )
    named = _select(source, predicate, label="right wheel enclosure")
    _render_technical(
        "fig14_wheel_enclosure_and_running_gear",
        "图14",
        named,
        VIEWS["perspective_front_right"],
        show_hidden=True,
        callouts=(
            Callout("131", _contains("continuous_wheel_belt_shell_right"), "left"),
            Callout("132", _contains("/tyre_"), "left"),
            Callout("133", _contains("body_colour_wheel_end_return_skin"), "left"),
            Callout("134", _contains("wheel_end_service_cap"), "right"),
            Callout("136", _contains("wheel_end_motion_gaiter"), "right"),
            Callout("137", _contains("rocker_pivot_service_cap"), "right"),
            Callout("138", _contains("/hub_"), "right"),
            Callout("139", _contains("/suspension_rocker_right"), "right"),
        ),
    )


def _technical_figure_15() -> None:
    source = _load_named_step(_full_step("ride"))
    predicate = _or(
        _prefix("A10_"),
        _contains(
            "/battery_",
            "/compute_core_",
            "/encrypted_data_",
            "/communications_",
            "/power_distribution_",
            "/service_disconnect_",
            "/manual_brake_",
            "/charge_",
        ),
    )
    named = _select(source, predicate, label="rear service and internals")
    _render_technical(
        "fig15_rear_service_and_rescue_access",
        "图15",
        named,
        VIEWS["perspective_rear_left"],
        show_hidden=True,
        callouts=(
            Callout("251", _contains("A10_rear_service_surround"), "left"),
            Callout("252", _contains("A10_rear_flush_service_door_skin"), "left"),
            Callout("253", _contains("A10_rear_service_external_no_power_release"), "left"),
            Callout("254", _contains("A10_rear_service_external_release_guard"), "left"),
            Callout("255", _contains("pull_cup", "pull_grip"), "right"),
            Callout("261", _contains("/battery_"), "right"),
            Callout("264", _contains("/compute_core_"), "right"),
            Callout("265", _contains("/encrypted_data_"), "right"),
            Callout("266", _contains("/communications_"), "right"),
        ),
    )


def _technical_figure_16() -> None:
    source = _load_named_step(_full_step("ride"))
    predicate = _or(
        _contains(
            "tof_window",
            "uwb_radome",
            "ultrasonic_face",
            "cliff_ir_window",
            "acoustic_mesh",
            "sensor_beam",
            "environment_sensor_grille",
            "fill_light_visible_window",
            "privacy_shutter",
        ),
        _contains(
            "/follow_front_tof_",
            "/follow_rear_tof_",
            "/follow_uwb_",
            "/follow_side_ultrasonic_",
            "/follow_cliff_ir_",
        ),
    )
    named = _select(source, predicate, label="sensor architecture")
    _render_technical(
        "fig16_sensor_and_privacy_architecture",
        "图16",
        named,
        VIEWS["perspective_front_right"],
        show_hidden=True,
        callouts=(
            Callout("112", _contains("perception_horizon", "tof_window"), "left"),
            Callout("123", _contains("ultrasonic_face", "acoustic_mesh"), "left"),
            Callout("193", _contains("sensor_beam_shell"), "right"),
            Callout("194", _contains("sensor_beam_smoked_window"), "right"),
            Callout("195", _contains("physical_privacy_shutter"), "right"),
            Callout("198", _contains("environment_sensor_grille"), "right"),
            Callout("202", _contains("fill_light_visible_window"), "right"),
        ),
    )


def _technical_figure_17() -> None:
    sys.path.insert(0, str(CAD_CODE_ROOT))
    from v8_table_lid_packaging import (  # pylint: disable=import-outside-toplevel
        LID_OPEN_ANGLE_DEG,
        lid_harness_pose,
        pose_lid_shape,
    )

    source = _load_named_step(_full_step("ride"))
    lid = source["A05_armrest_touch_lid_right"]
    base = source["A05_armrest_table_bay_shell_right"]
    combined: dict[str, cq.Shape] = {}
    for prefix, angle, offset in (("a::", 0.0, 500.0), ("b::", LID_OPEN_ANGLE_DEG, -500.0)):
        harness = lid_harness_pose(1, angle)
        combined[f"{prefix}armrest_shell"] = base.translate((offset, 0.0, 0.0))
        combined[f"{prefix}lid"] = pose_lid_shape(lid, 1, angle).translate((offset, 0.0, 0.0))
        combined[f"{prefix}flex"] = harness.flex_circuit.translate((offset, 0.0, 0.0))
        combined[f"{prefix}fixed_connector"] = harness.fixed_connector.translate((offset, 0.0, 0.0))
        combined[f"{prefix}moving_connector"] = harness.moving_connector.translate((offset, 0.0, 0.0))
    _render_technical(
        "fig17_lid_dynamic_flex",
        "图17",
        combined,
        VIEWS["right"],
        panel_labels=(("（a）", _prefix("a::")), ("（b）", _prefix("b::"))),
        callouts=(
            Callout("153", _contains("lid"), "left"),
            Callout("154", _contains("flex"), "right"),
            Callout("155", _contains("connector"), "right"),
        ),
    )


def _technical_figure_18() -> None:
    source = _load_named_step(_full_step("ride"))
    predicate = _and(
        _prefix("A08_"),
        _not(
            _contains(
                "top_skin",
                "inset_tread",
                "perimeter_skin",
                "platform_undertray",
                "support_monocoque",
                "root_monocoque",
            )
        ),
    )
    named = _select(source, predicate, label="footrest internal mechanism")
    _render_technical(
        "fig18_footrest_links_locks_and_interlock",
        "图18",
        named,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("216", _contains("fixed_guide_housing"), "left"),
            Callout("217", _contains("primary_cartridge"), "left"),
            Callout("218", _contains("captured_inner_rail"), "left"),
            Callout("219", _contains("drop_link"), "right"),
            Callout("220", _contains("bearing", "guarded_pin"), "right"),
            Callout("221", _contains("synchronising_cross_shaft"), "right"),
            Callout("222", _contains("counterbalance"), "right"),
            Callout("224", _contains("deployed_lock"), "right"),
            Callout("227", _contains("foot_zone_interlock"), "left"),
        ),
    )


def _technical_figure_19() -> None:
    source = _load_named_step(_full_step("focus"))
    names = (
        "A07_sensor_beam_shell",
        "A07_sensor_beam_smoked_window",
        "A07_physical_privacy_shutter",
        "A07_privacy_shutter_carriage_bezel",
        "A07_microphone_acoustic_mesh",
        "A07_environment_sensor_grille",
        "A07_fill_light_visible_window_left",
        "A07_fill_light_visible_window_right",
    )
    selected = _select(source, _exact(*names), label="A07 sensor head")
    exploded: dict[str, cq.Shape] = {}
    offsets = {
        "A07_sensor_beam_shell": (0.0, 0.0, 0.0),
        "A07_sensor_beam_smoked_window": (-45.0, 0.0, 0.0),
        "A07_physical_privacy_shutter": (-90.0, 0.0, 30.0),
        "A07_privacy_shutter_carriage_bezel": (-120.0, 0.0, -20.0),
        "A07_microphone_acoustic_mesh": (0.0, 0.0, -70.0),
        "A07_environment_sensor_grille": (0.0, 0.0, 70.0),
        "A07_fill_light_visible_window_left": (0.0, -60.0, 0.0),
        "A07_fill_light_visible_window_right": (0.0, 60.0, 0.0),
    }
    for name, shape in selected.items():
        exploded[name] = shape.translate(offsets[name])
    _render_technical(
        "fig19_sensor_head_privacy_exploded",
        "图19",
        exploded,
        VIEWS["perspective_front_right"],
        callouts=(
            Callout("193", _exact("A07_sensor_beam_shell"), "left"),
            Callout("194", _exact("A07_sensor_beam_smoked_window"), "left"),
            Callout("195", _exact("A07_physical_privacy_shutter"), "right"),
            Callout("196", _exact("A07_privacy_shutter_carriage_bezel"), "right"),
            Callout("197", _exact("A07_microphone_acoustic_mesh"), "left"),
            Callout("198", _exact("A07_environment_sensor_grille"), "right"),
            Callout("202", _contains("fill_light_visible_window"), "right"),
        ),
    )


def _technical_figure_20() -> None:
    source = _load_named_step(_full_step("cafe"))
    predicate = _or(
        _exact(
            "A05_armrest_touch_lid_right",
            "A05_right_removable_drive_pod",
            "A05_right_joystick",
            "A05_right_authorisation_key",
        ),
        _prefix("A09_"),
    )
    named = _select(source, predicate, label="Cafe table/control clearance")
    _render_technical(
        "fig20_cafe_table_control_clearance",
        "图20",
        named,
        VIEWS["top"],
        callouts=(
            Callout("153", _exact("A05_armrest_touch_lid_right"), "right"),
            Callout("171", _exact("A05_right_removable_drive_pod"), "right"),
            Callout("172", _exact("A05_right_joystick"), "right"),
            Callout("173", _exact("A05_right_authorisation_key"), "right"),
            Callout("231", _contains("A09_table_half_leaf_right"), "left"),
            Callout("238", _contains("underbelly", "motion_belly"), "left"),
        ),
    )


TECHNICAL_FIGURES: dict[str, Callable[[], None]] = {
    "01": _technical_figure_01,
    "02": _technical_figure_02,
    "03": _technical_figure_03,
    "04": _technical_figure_04,
    "05": _technical_figure_05,
    "06": _technical_figure_06,
    "07": _technical_figure_07,
    "08": _technical_figure_08,
    "09": _technical_figure_09,
    "10": _technical_figure_10,
    "11": _technical_figure_11,
    "12": _technical_figure_12,
    "13": _technical_figure_13,
    "14": _technical_figure_14,
    "15": _technical_figure_15,
    "16": _technical_figure_16,
    "17": _technical_figure_17,
    "18": _technical_figure_18,
    "19": _technical_figure_19,
    "20": _technical_figure_20,
}


def _generate_technical() -> None:
    for figure in TECHNICAL_FIGURES:
        print(f"[disclosure] figure {figure}", flush=True)
        _run_isolated(("--worker-technical", figure))


def _png_metrics(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        pixels = list(image.getdata())
    nonwhite = sum(1 for red, green, blue in pixels if min(red, green, blue) < 245)
    nongray = sum(1 for red, green, blue in pixels if max(red, green, blue) - min(red, green, blue) > 3)
    return {
        "width": image.width,
        "height": image.height,
        "nonwhite_fraction": nonwhite / len(pixels),
        "nongray_fraction": nongray / len(pixels),
    }


def _write_manifest() -> None:
    outputs = sorted(
        path
        for root in (APPEARANCE_ROOT, DISCLOSURE_ROOT)
        if root.exists()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".svg", ".png"}
    )
    png_reports = {str(path.relative_to(PACKAGE_ROOT)): _png_metrics(path) for path in outputs if path.suffix.lower() == ".png"}
    failures = []
    for logical, metrics in png_reports.items():
        if (metrics["width"], metrics["height"]) != (WIDTH, HEIGHT):
            failures.append(f"{logical}: wrong pixel dimensions")
        if float(metrics["nonwhite_fraction"]) < 0.002:
            failures.append(f"{logical}: drawing is nearly blank")
        if float(metrics["nongray_fraction"]) > 0.0005:
            failures.append(f"{logical}: drawing contains non-grayscale pixels")
    source_files = [SOURCE_MANIFEST, *(_exterior_step(state) for state in STATES), *(_full_step(state) for state in STATES)]
    source_hashes = {str(path.relative_to(REPOSITORY_ROOT)): _sha256(path) for path in source_files}
    artifact_hashes = {str(path.relative_to(PACKAGE_ROOT)): _sha256(path) for path in outputs}
    payload = {
        "status": "DRAFT_PATENT_DISCLOSURE_DRAWINGS_GEOMETRY_ANCHORED_PENDING_VISUAL_FREEZE_AND_PATENT_COUNSEL",
        "filing_ready": False,
        "production_certification_claimed": False,
        "source_release_status": json.loads((SOURCE_RELEASE / "release_status.json").read_text(encoding="utf-8"))["status"],
        "known_blockers": [
            "source release remains PENDING_VISUAL_REVIEW",
            "source exterior width is approximately 779.4 mm while the V8 freeze limit is 752 mm",
            "application grouping and claim scope require applicant/patent-counsel decision",
        ],
        "appearance_policy": "exterior STEP only; visible sharp edges and outlines; no hidden lines, shading, material texture, dimensions, axes, callouts or background",
        "technical_policy": "named full-layout STEP occurrences and gate motion B-Reps; black/white line art with stable reference numerals",
        "source_sha256": source_hashes,
        "artifact_count": len(outputs),
        "appearance_png_count": len(list(APPEARANCE_ROOT.rglob("*.png"))) if APPEARANCE_ROOT.exists() else 0,
        "technical_png_count": len(list(DISCLOSURE_ROOT.rglob("*.png"))) if DISCLOSURE_ROOT.exists() else 0,
        "artifact_sha256": artifact_hashes,
        "png_qa": png_reports,
        "qa_status": "PASS" if not failures else "FAIL",
        "qa_failures": failures,
    }
    QA_ROOT.mkdir(parents=True, exist_ok=True)
    (QA_ROOT / "patent_drawing_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        raise ValueError("Patent drawing QA failed: " + "; ".join(failures))


def _clean_generated() -> None:
    for path in (APPEARANCE_ROOT, DISCLOSURE_ROOT, QA_ROOT):
        if path.exists():
            shutil.rmtree(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--appearance", action="store_true")
    parser.add_argument("--technical", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--worker-appearance", nargs=2, metavar=("STATE", "VIEW"))
    parser.add_argument("--worker-technical", choices=tuple(TECHNICAL_FIGURES))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.worker_appearance:
        _appearance_worker(*args.worker_appearance)
        return
    if args.worker_technical:
        TECHNICAL_FIGURES[args.worker_technical]()
        return
    if args.clean:
        _clean_generated()
    if args.manifest_only:
        _write_manifest()
        return
    run_appearance = args.all or args.appearance or not args.technical
    run_technical = args.all or args.technical or not args.appearance
    if run_appearance:
        _generate_appearance()
    if run_technical:
        _generate_technical()
    _write_manifest()


if __name__ == "__main__":
    main()
